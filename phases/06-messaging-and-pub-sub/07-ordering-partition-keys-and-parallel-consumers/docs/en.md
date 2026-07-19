# Ordering, Partition Keys & Parallel Consumers

> You added nine more consumers and throughput went up beautifully. Then the tickets arrived: a profile updated before it was created, an account deleted before it existed, a wallet that briefly showed a negative balance and tripped a fraud alert. Nothing crashed. Nothing was lost. Every consumer was correct on its own. **Parallelism destroyed order**, and order turned out to be a correctness requirement nobody had written down. This lesson is about the one design decision that decides it — the partition key — and the three separate jobs it is secretly doing at the same time.

**Type:** Build
**Languages:** Python
**Prerequisites:** [Delivery Semantics & Idempotent Consumers](../06-delivery-semantics-and-idempotency/)
**Time:** ~80 minutes

## The Problem

Your consumer was falling behind, so you did the obvious thing. One consumer became ten. Lag went to zero, the graph looked wonderful, and you closed the ticket.

A week later support escalates three bugs that have nothing to do with each other.

**Ticket one.** A user's `ProfileUpdated` was applied before their `ProfileCreated`. The update handler did an `UPDATE ... WHERE user_id = ?`, matched zero rows, logged nothing, and returned successfully. Then `ProfileCreated` inserted the row with the *old* values. The user changed their display name, saw it change, refreshed, and watched it change back.

**Ticket two.** An `AccountDeleted` was processed before the `AccountCreated` that preceded it by **40 milliseconds**. The delete matched nothing. The create then inserted a row for an account that had already been closed. Nobody noticed for eleven days, at which point a compliance report found accounts that existed in your system and not in your ledger.

**Ticket three.** A wallet's `Debit` and `Credit` were applied in the wrong order. The final balance was correct — addition commutes — but for four seconds the intermediate balance was negative, the fraud rule that watches for negative balances fired, and the customer's card was frozen over an event ordering artefact.

Now look at what these have in common, because it is the uncomfortable part. **No message was lost.** **No consumer crashed.** **Every handler was correct in isolation** and would pass any unit test you wrote for it. Your delivery guarantee held perfectly. The broker did exactly what it promised.

The mechanism is embarrassingly simple. Two consumers pull from the same stream. Consumer A picks up `AccountCreated` and takes 90 ms because it missed a cache. Consumer B picks up `AccountDeleted` 40 ms later and takes 3 ms. B finishes first. The database sees the delete, then the create. That is the entire bug, and it exists the instant you run more than one consumer against a stream where any two messages are causally related.

Here is what it costs, measured. The program in this lesson pushes 300 accounts through their full lifecycle — `Created → Updated → Updated → Deleted`, 1,200 records — into six partitions consumed by six parallel consumers running at realistic, slightly different speeds:

```text
round-robin partitioning, 6 parallel consumers
  inversions                  242
  accounts damaged        178 of 300      (59% of the book)
  wrong final state       109 of 300      (deleted rows that came back)
  anomalies:  update-to-missing-row=59   create-over-live-row=52
              resurrected-deleted-row=109   delete-of-missing-row=7
```

Fifty-nine percent of accounts corrupted, by a system where nothing failed. And the fix is not more error handling, retries, or transactions. It is a single line of configuration that most engineers set without thinking about it.

## The Concept

### What ordering actually means when there is more than one machine

Start with the thing everyone assumes and nobody states: **there is no global "now" in a distributed system.**

You might reach for timestamps. Every event carries a wall-clock time; sort by it. This does not work, and it is worth understanding exactly why, because the failure is silent. Two machines' clocks disagree. Even with NTP (Network Time Protocol) disciplining them, skew of a few milliseconds is normal, tens of milliseconds is common under load, and clocks can jump *backwards* when a correction lands. Two events 40 ms apart on different machines — precisely the gap in ticket two — can carry timestamps in the wrong order. A timestamp is a useful *hint* for humans reading logs. It is **not** an ordering primitive. This is why brokers assign their own monotonic **sequence numbers** or **offsets** at the point of append: one machine, one counter, no clocks involved.

Leslie Lamport formalized this in "Time, Clocks, and the Ordering of Events in a Distributed System" (*Communications of the ACM* 21(7), 1978), and the paper gives us the two words this lesson turns on.

The **happens-before** relation, written `a → b`, holds when `a` could possibly have caused `b`: they happened in that order in the same process, or `a` was a message send and `b` its receipt, or you can chain those two rules together. If neither `a → b` nor `b → a`, the events are **concurrent** — not "simultaneous", but *causally unrelated*. Nothing in the system depends on which one you consider first.

That gives two kinds of order:

- A **total order** puts every pair of events in a definite sequence. Event 7 comes after event 6, always, everywhere, for everyone.
- A **partial order** constrains only the pairs that are causally related and says nothing about the rest.

And here is Lamport's insight, which is the load-bearing idea of this entire lesson: **almost no system needs a total order.** `acct-0001`'s `Created` must precede its `Updated`. `acct-0002`'s events are completely unrelated to `acct-0001`'s — no invariant in your business connects them, no handler reads one while writing the other. Ordering them relative to each other is work you are paying for and getting nothing back.

What you actually need is order **per entity**. Per user, per account, per order, per aggregate. That is a partial order, and partial orders are cheap in a way total orders are not.

### Ordering and parallelism are in direct opposition

Why is a total order expensive? Because a total order requires a **single sequencer** — one point that every message passes through, assigning consecutive numbers. Something has to be the arbiter of "before", and it has to see everything to do the job.

A single sequencer has two properties you will not enjoy:

1. **It is a throughput ceiling.** Whatever one machine can do is what the whole system can do. You cannot add capacity, because adding a second sequencer means two counters and no total order.
2. **It is a single point of failure.** When the sequencer is down, the system is down. Not degraded — down.

The same is true on the consuming side. Applying a totally-ordered stream in order means **one consumer, processing serially**. The moment a second consumer touches the stream, the order you paid for is gone.

The program measures the cost directly:

```text
single partition (total order)        585 records/s
hash-by-key across 6 partitions     1,535 records/s      2.6x
```

That factor is small here only because the workload is small; in production the gap is the difference between one machine and a hundred. **Ordering and parallelism are in direct opposition, always.** Every technique in the rest of this lesson is the same move: buy back parallelism by *weakening the ordering guarantee* down to exactly what the business actually requires, and not one bit stronger.

### Partitioning: total order inside, no order across

The resolution is to stop asking for one order and start asking for many independent ones.

**Split the stream into N partitions.** Each partition is an independent append-only log of the kind you built in [The Log: Offsets, Replay & Retention](../05-the-log-offsets-and-replay/): messages get consecutive offsets, and a consumer reading a partition sees them in exactly the order they were appended. Across partitions, there is **no** ordering relationship at all — none, not "weak", not "best effort". Partition 3's offset 500 and partition 5's offset 12 have no defined relative order and never will.

Now the design problem has a shape. You have N independent total orders and one lever: **which partition does each message go to?** Choose that mapping so everything that must be ordered together lands in the same partition, and the partial order you need falls out of the partition's own total order for free.

That mapping is the **partition key**. Take a field from the message — the user id, the account id, the order id, the aggregate id — hash it, and take the hash modulo the partition count.

```python
def hash_by_key(record, n_partitions):
    return stable_hash(record.key) % n_partitions
```

Two lines. Here is what they buy, measured on the identical workload and the identical consumer group:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 500" width="100%" style="max-width:840px" role="img" aria-label="One account's four lifecycle events under two partitioning strategies. Round-robin scatters the events across four partitions handled by four consumers running at different speeds, so they are applied as Updated, Created, Deleted, Updated, producing 242 inversions and 178 damaged accounts out of 300. Hash-by-key sends all four events to partition 3 handled by one consumer, which applies them in exact order, producing zero inversions.">
  <defs>
    <marker id="l07-arrow" markerWidth="10" markerHeight="10" refX="6" refY="3" orient="auto">
      <path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/>
    </marker>
  </defs>
  <text x="440" y="24" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">acct-0001, same four events, same six consumers — one field different</text>

  <g fill="none" stroke-linejoin="round" stroke-width="2">
    <rect x="16" y="40" width="848" height="204" rx="13" fill="#e0930f" fill-opacity="0.07" stroke="#e0930f"/>
    <rect x="16" y="256" width="848" height="196" rx="13" fill="#0fa07f" fill-opacity="0.07" stroke="#0fa07f"/>
  </g>

  <g fill="none" stroke-linejoin="round" stroke-width="2">
    <rect x="34" y="112" width="96" height="46" rx="9" fill="#3553ff" fill-opacity="0.13" stroke="#3553ff"/>
    <rect x="196" y="88" width="88" height="30" rx="7" fill="#7f7f7f" fill-opacity="0.10" stroke="currentColor" stroke-opacity="0.5"/>
    <rect x="196" y="124" width="88" height="30" rx="7" fill="#7f7f7f" fill-opacity="0.10" stroke="currentColor" stroke-opacity="0.5"/>
    <rect x="196" y="160" width="88" height="30" rx="7" fill="#7f7f7f" fill-opacity="0.10" stroke="currentColor" stroke-opacity="0.5"/>
    <rect x="196" y="196" width="88" height="30" rx="7" fill="#7f7f7f" fill-opacity="0.10" stroke="currentColor" stroke-opacity="0.5"/>
    <rect x="352" y="88" width="120" height="30" rx="7" fill="#e0930f" fill-opacity="0.13" stroke="#e0930f"/>
    <rect x="352" y="124" width="120" height="30" rx="7" fill="#e0930f" fill-opacity="0.13" stroke="#e0930f"/>
    <rect x="352" y="160" width="120" height="30" rx="7" fill="#e0930f" fill-opacity="0.13" stroke="#e0930f"/>
    <rect x="352" y="196" width="120" height="30" rx="7" fill="#e0930f" fill-opacity="0.13" stroke="#e0930f"/>
    <rect x="536" y="98" width="316" height="118" rx="10" fill="#e0930f" fill-opacity="0.12" stroke="#e0930f"/>
  </g>
  <g fill="none" stroke="currentColor" stroke-width="1.5">
    <path d="M130 128 L 190 103" marker-end="url(#l07-arrow)"/>
    <path d="M130 133 L 190 139" marker-end="url(#l07-arrow)"/>
    <path d="M130 140 L 190 175" marker-end="url(#l07-arrow)"/>
    <path d="M130 146 L 190 211" marker-end="url(#l07-arrow)"/>
    <path d="M284 103 L 346 103" marker-end="url(#l07-arrow)"/>
    <path d="M284 139 L 346 139" marker-end="url(#l07-arrow)"/>
    <path d="M284 175 L 346 175" marker-end="url(#l07-arrow)"/>
    <path d="M284 211 L 346 211" marker-end="url(#l07-arrow)"/>
    <path d="M472 157 L 530 157" marker-end="url(#l07-arrow)"/>
  </g>

  <g fill="none" stroke-linejoin="round" stroke-width="2">
    <rect x="34" y="330" width="96" height="46" rx="9" fill="#3553ff" fill-opacity="0.13" stroke="#3553ff"/>
    <rect x="196" y="316" width="88" height="74" rx="9" fill="#0fa07f" fill-opacity="0.16" stroke="#0fa07f"/>
    <rect x="352" y="316" width="120" height="74" rx="9" fill="#0fa07f" fill-opacity="0.16" stroke="#0fa07f"/>
    <rect x="536" y="306" width="316" height="94" rx="10" fill="#0fa07f" fill-opacity="0.14" stroke="#0fa07f"/>
  </g>
  <g fill="none" stroke="currentColor" stroke-width="1.5">
    <path d="M130 353 L 190 353" marker-end="url(#l07-arrow)"/>
    <path d="M284 353 L 346 353" marker-end="url(#l07-arrow)"/>
    <path d="M472 353 L 530 353" marker-end="url(#l07-arrow)"/>
  </g>

  <g font-family="'JetBrains Mono', ui-monospace, monospace" fill="currentColor">
    <text x="34" y="66" font-size="12.5" font-weight="700" fill="#e0930f">ROUND-ROBIN — spread the load, destroy the meaning</text>
    <text x="34" y="84" font-size="9.5" opacity="0.85">partitions are perfectly balanced at 200 records each. That is the only thing it gets right.</text>
    <text x="82" y="131" font-size="9.5" font-weight="700" text-anchor="middle">acct-0001</text>
    <text x="82" y="146" font-size="8.5" text-anchor="middle" opacity="0.8">v1 v2 v3 v4</text>
    <text x="240" y="107" font-size="9" text-anchor="middle">p3  Cre v1</text>
    <text x="240" y="143" font-size="9" text-anchor="middle">p2  Upd v2</text>
    <text x="240" y="179" font-size="9" text-anchor="middle">p1  Upd v3</text>
    <text x="240" y="215" font-size="9" text-anchor="middle">p0  Del v4</text>
    <text x="412" y="107" font-size="9" text-anchor="middle">c3 · 1.4 ms/rec</text>
    <text x="412" y="143" font-size="9" text-anchor="middle">c2 · 0.7 ms/rec</text>
    <text x="412" y="179" font-size="9" text-anchor="middle">c1 · 1.9 ms/rec</text>
    <text x="412" y="215" font-size="9" text-anchor="middle">c0 · 1.0 ms/rec</text>
    <text x="694" y="120" font-size="10" font-weight="700" text-anchor="middle">APPLIED IN THIS ORDER</text>
    <text x="694" y="142" font-size="10.5" text-anchor="middle" font-weight="700" fill="#e0930f">Upd v2 → Cre v1 → Del v4 → Upd v3</text>
    <text x="694" y="164" font-size="9.5" text-anchor="middle" opacity="0.9">update to a row that does not exist,</text>
    <text x="694" y="179" font-size="9.5" text-anchor="middle" opacity="0.9">then a delete, then a resurrection</text>
    <text x="694" y="202" font-size="9.5" text-anchor="middle" font-weight="700">242 inversions · 178 of 300 accounts damaged</text>
    <text x="440" y="234" font-size="10" text-anchor="middle" opacity="0.95">The four faster consumers overtook the slower ones. That is not a bug — that is what parallelism is.</text>

    <text x="34" y="282" font-size="12.5" font-weight="700" fill="#0fa07f">HASH BY KEY — one entity, one partition, one consumer</text>
    <text x="34" y="300" font-size="9.5" opacity="0.85">partitions are uneven: 180 176 148 204 280 212. That is the price, and it is the cheaper problem.</text>
    <text x="82" y="349" font-size="9.5" font-weight="700" text-anchor="middle">acct-0001</text>
    <text x="82" y="364" font-size="8.5" text-anchor="middle" opacity="0.8">v1 v2 v3 v4</text>
    <text x="240" y="342" font-size="9.5" text-anchor="middle" font-weight="700">p3 only</text>
    <text x="240" y="360" font-size="8.5" text-anchor="middle" opacity="0.85">hash(key) % 6</text>
    <text x="240" y="376" font-size="8.5" text-anchor="middle" opacity="0.85">v1 v2 v3 v4</text>
    <text x="412" y="342" font-size="9.5" text-anchor="middle" font-weight="700">c3 only</text>
    <text x="412" y="360" font-size="8.5" text-anchor="middle" opacity="0.85">serial, in offset</text>
    <text x="412" y="376" font-size="8.5" text-anchor="middle" opacity="0.85">order, always</text>
    <text x="694" y="330" font-size="10" font-weight="700" text-anchor="middle">APPLIED IN THIS ORDER</text>
    <text x="694" y="352" font-size="10.5" text-anchor="middle" font-weight="700" fill="#0fa07f">Cre v1 → Upd v2 → Upd v3 → Del v4</text>
    <text x="694" y="376" font-size="9.5" text-anchor="middle" font-weight="700">0 inversions · 0 accounts damaged</text>
    <text x="694" y="392" font-size="9" text-anchor="middle" opacity="0.85">and still 6 consumers running in parallel</text>
    <text x="440" y="424" font-size="10.5" text-anchor="middle" opacity="0.95">The other 299 accounts are still processed concurrently. We gave up ordering only between accounts —</text>
    <text x="440" y="440" font-size="10.5" text-anchor="middle" opacity="0.95">which nothing in the business ever needed. That is the whole trick.</text>
    <text x="440" y="472" font-size="10" text-anchor="middle" opacity="0.8">Round-robin is FASTER (1,627 rec/s vs 1,535) because its partitions are balanced. Speed was never the problem.</text>
  </g>
</svg>
```

Note the last line of that diagram, because it is the trap. Round-robin is *faster*. It distributes load perfectly. Every metric on your dashboard looks better. It is also completely, silently wrong, and the wrongness shows up in a support queue three weeks later rather than on a graph.

### The partition key does three jobs at once

This is the part engineers usually get wrong, and it is not because the concept is hard. It is because the key is doing three unrelated jobs simultaneously and most people are only thinking about one of them.

| Job | What the key decides | The failure when you ignore it |
|---|---|---|
| **1. Ordering** | Which messages are guaranteed to be processed in sequence — everything sharing a key, and nothing else | Causally related events processed concurrently. Ticket one, two and three. |
| **2. Load distribution** | How evenly work spreads across partitions, which is a direct function of your key's real-world frequency distribution | Hot partitions. One consumer at 100% while nine idle. |
| **3. Maximum parallelism** | The partition count caps consumer count; the *key cardinality* caps useful partition count | A ceiling you cannot raise without a dangerous migration. |

An engineer thinking only about job 1 picks `user_id`, ships it, and discovers job 2 when one enterprise customer generates 40% of traffic. An engineer thinking only about job 2 picks a random UUID, gets a beautiful flat histogram, and discovers job 1 in a compliance report. An engineer thinking only about job 3 picks something with huge cardinality and finds out later that increasing the partition count is one of the more dangerous operations in the system.

**Write down which of the three you are optimizing, and what you are conceding on the other two.** That sentence belongs in the design doc.

### Choosing the key: too coarse and too fine both fail

The trade-off runs in both directions, and the failure at each end is different.

**Too coarse** — partition by `region`, `event_type`, or worst of all a boolean like `is_premium`. You get ordering far stronger than the business asked for and almost no parallelism: four regions means at most four useful partitions, and `us-east` is 60% of traffic. **You cannot scale past your key's cardinality.**

**Too fine** — partition by a per-event UUID (RFC 4122), a timestamp, or a hash of the whole payload. Distribution is textbook-perfect and **you have no ordering guarantee at all** — you have reinvented round-robin with extra steps. A key that is unique per message is not a partition key; it is a message id.

The right key is the **identity of the thing whose event sequence must be consistent**. Ask: *"what is the smallest unit that has a state machine?"* Usually that is the aggregate — the account, the order, the wallet, the device, the conversation. Not the tenant that owns a million of them, and not the individual event.

### Key skew: the distribution is Zipfian and it will hurt

Even a correct key can wreck you, because **real-world key distributions are never uniform**. Tenant traffic, user activity, item popularity, and city population all follow roughly a **Zipfian** distribution: the item at rank *r* gets traffic proportional to `1/r^s`, with `s` near 1. The top key gets an enormous share; the tail is long and thin.

The program runs 20,000 messages over 500 tenants at `s = 1.0` through a hash partitioner across 16 partitions. The top three tenants alone are **26.7%** of all traffic. Here is what the partitions look like:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 452" width="100%" style="max-width:840px" role="img" aria-label="Two bar charts of measured message counts across 16 partitions under a Zipfian key distribution. Plain hash-by-key produces a hot partition holding 3,296 messages against a mean of 1,250 and a minimum of 500, a max over mean ratio of 2.64 that wastes 9.93 of 16 consumers. Salting the top three keys across eight suffixes flattens the maximum to 1,914, a max over mean of 1.53, recovering effective parallelism to 10.45 of 16 at the cost of all ordering for those three keys.">
  <text x="440" y="24" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">20,000 Zipfian messages, 500 tenants, 16 partitions — measured</text>

  <g fill="none" stroke-linejoin="round" stroke-width="2">
    <rect x="16" y="40" width="416" height="332" rx="13" fill="#e0930f" fill-opacity="0.07" stroke="#e0930f"/>
    <rect x="448" y="40" width="416" height="332" rx="13" fill="#0fa07f" fill-opacity="0.07" stroke="#0fa07f"/>
  </g>

  <g fill="none" stroke="currentColor" stroke-width="1.3" opacity="0.55">
    <path d="M36 302 L 414 302"/>
    <path d="M468 302 L 846 302"/>
  </g>
  <g fill="none" stroke="#3553ff" stroke-width="1.5" stroke-dasharray="6 4" opacity="0.9">
    <path d="M36 256.5 L 414 256.5"/>
    <path d="M468 256.5 L 846 256.5"/>
  </g>

  <g fill="#e0930f" fill-opacity="0.55" stroke="#e0930f" stroke-width="1.2">
    <rect x="40" y="239.1" width="18" height="62.9"/>
    <rect x="63" y="277.6" width="18" height="24.4"/>
    <rect x="86" y="279.2" width="18" height="22.8"/>
    <rect x="109" y="182.0" width="18" height="120.0"/>
    <rect x="132" y="245.5" width="18" height="56.5"/>
    <rect x="155" y="283.8" width="18" height="18.2"/>
    <rect x="178" y="264.0" width="18" height="38.0"/>
    <rect x="201" y="274.0" width="18" height="28.0"/>
    <rect x="224" y="270.2" width="18" height="31.8"/>
    <rect x="247" y="273.2" width="18" height="28.8"/>
    <rect x="270" y="270.5" width="18" height="31.5"/>
    <rect x="293" y="237.4" width="18" height="64.6"/>
    <rect x="316" y="253.1" width="18" height="48.9"/>
    <rect x="339" y="269.8" width="18" height="32.2"/>
    <rect x="362" y="260.6" width="18" height="41.4"/>
    <rect x="385" y="224.0" width="18" height="78.0"/>
  </g>
  <g fill="#0fa07f" fill-opacity="0.55" stroke="#0fa07f" stroke-width="1.2">
    <rect x="472" y="275.0" width="18" height="27.0"/>
    <rect x="495" y="272.8" width="18" height="29.2"/>
    <rect x="518" y="272.3" width="18" height="29.7"/>
    <rect x="541" y="274.2" width="18" height="27.8"/>
    <rect x="564" y="245.5" width="18" height="56.5"/>
    <rect x="587" y="270.8" width="18" height="31.2"/>
    <rect x="610" y="244.6" width="18" height="57.4"/>
    <rect x="633" y="256.4" width="18" height="45.6"/>
    <rect x="656" y="232.3" width="18" height="69.7"/>
    <rect x="679" y="262.8" width="18" height="39.2"/>
    <rect x="702" y="264.0" width="18" height="38.0"/>
    <rect x="725" y="237.4" width="18" height="64.6"/>
    <rect x="748" y="238.2" width="18" height="63.8"/>
    <rect x="771" y="265.3" width="18" height="36.7"/>
    <rect x="794" y="242.5" width="18" height="59.5"/>
    <rect x="817" y="250.3" width="18" height="51.7"/>
  </g>

  <g font-family="'JetBrains Mono', ui-monospace, monospace" fill="currentColor">
    <text x="34" y="66" font-size="12" font-weight="700" fill="#e0930f">hash(key) % 16</text>
    <text x="34" y="84" font-size="9.5" opacity="0.85">tenant-0000 alone is 2,905 msgs — 14.5% of everything</text>
    <text x="118" y="172" font-size="9.5" font-weight="700" fill="#e0930f" text-anchor="middle">3,296</text>
    <text x="118" y="158" font-size="8.5" text-anchor="middle" opacity="0.8">HOT</text>
    <text x="164" y="296" font-size="8" text-anchor="middle" opacity="0.8">500</text>
    <text x="410" y="250" font-size="8.5" text-anchor="end" fill="#3553ff" font-weight="700">mean 1,250</text>
    <text x="34" y="324" font-size="10" opacity="0.95">max/min 6.59   max/mean 2.64</text>
    <text x="34" y="342" font-size="10.5" font-weight="700" fill="#e0930f">effective parallelism 6.07 of 16 — 9.93 consumers wasted</text>
    <text x="34" y="360" font-size="9" opacity="0.8">the busiest partition sets the drain time; extra consumers cannot touch it</text>

    <text x="466" y="66" font-size="12" font-weight="700" fill="#0fa07f">hash(key + salt) % 16, top 3 keys, fanout 8</text>
    <text x="466" y="84" font-size="9.5" opacity="0.85">the three hot keys are spread over up to 8 partitions each</text>
    <text x="665" y="222" font-size="9.5" font-weight="700" fill="#0fa07f" text-anchor="middle">1,914</text>
    <text x="842" y="250" font-size="8.5" text-anchor="end" fill="#3553ff" font-weight="700">mean 1,250</text>
    <text x="466" y="324" font-size="10" opacity="0.95">max/min 2.58   max/mean 1.53</text>
    <text x="466" y="342" font-size="10.5" font-weight="700" fill="#0fa07f">effective parallelism 10.45 of 16 — 5.55 wasted</text>
    <text x="466" y="360" font-size="9" opacity="0.8">...and those 3 tenants, 26.7% of traffic, now have NO ordering at all</text>

    <text x="440" y="398" font-size="10.5" text-anchor="middle" opacity="0.95">Salting is not a free win. It converts an availability problem into a correctness problem</text>
    <text x="440" y="416" font-size="10.5" text-anchor="middle" opacity="0.95">and you must be able to say, out loud, that those keys no longer need ordering.</text>
    <text x="440" y="440" font-size="10" text-anchor="middle" opacity="0.8">effective parallelism = N ÷ (max/mean): the fraction of your consumer fleet actually doing work</text>
  </g>
</svg>
```

The measured numbers: `max/min = 6.59`, `max/mean = 2.64`. The busiest partition holds 3,296 messages, the quietest 500.

**Effective parallelism** is the number that matters, and it is easy to compute: because the busiest partition sets the wall-clock drain time, your fleet does `N ÷ (max/mean)` partitions' worth of useful work. Here that is `16 / 2.64 = 6.07`. **You are paying for sixteen consumers and getting six.** Nine and a half of them are sitting on quiet partitions with nothing to do.

And here is the part that surprises people: **you cannot fix this by adding consumers.** The partition is the unit of parallelism. A second consumer cannot join partition 3 to help — the group protocol forbids it, and if it didn't, you would be back to the ordering bug. The hot partition drains at one consumer's speed no matter how many machines you buy.

Three mitigations, each with a real cost:

**Composite keys.** Instead of `tenant_id`, use `tenant_id + ":" + account_id`. Cardinality goes up, distribution flattens, and you keep ordering *per account* — which is usually the real requirement anyway. This is the best answer when it applies, because it does not give up any ordering you actually needed. Check first that nothing depends on cross-account ordering within a tenant.

**Salting / sharding the hot key.** Append a rotating suffix to the hottest keys only: `tenant-0000#0` through `tenant-0000#7`. The program does exactly this for the top three tenants with a fanout of 8. `max/mean` falls from 2.64 to 1.53 and effective parallelism rises from 6.07 to 10.45 of 16 — a 72% improvement in useful capacity. **The cost is explicit and large:** those three keys are now spread over up to eight partitions and have *no ordering guarantee whatsoever*. That is 26.7% of your traffic. Only do this when you can state clearly why those particular keys do not need order — or when you pair it with the version-rejection technique below.

**Isolate the elephant.** Give the enormous tenant its own topic, partitions and consumer deployment. Often the right answer: ordering is preserved completely, one customer stops affecting everyone else's lag, and the two can be scaled separately. The cost is operational — two pipelines, routing logic at the producer, and a manual decision about who is big enough to promote.

### The rebalance problem: `hash(key) % N` and why changing N is dangerous

Here is a fact that a surprising number of experienced engineers do not know, and it causes real incidents.

`hash(key) % N` is a function of **both** the key and the partition count. Change N and you change the answer for nearly every key. From the measured run over 500 keys:

```text
  8 -> 12  partitions   modulo:  329 of 500 keys move ( 65.8%)   consistent hash:  170 ( 34.0%)   ideal  33.3%
 16 -> 32  partitions   modulo:  262 of 500 keys move ( 52.4%)   consistent hash:  250 ( 50.0%)   ideal  50.0%
 16 -> 17  partitions   modulo:  473 of 500 keys move ( 94.6%)   consistent hash:   30 (  6.0%)   ideal   5.9%
```

Adding **one** partition to sixteen relocates **94.6% of your keys**. That is not a rebalancing; that is a reshuffle of the entire keyspace.

Why does this matter so much more than it does for a cache? Because in a cache, a remapped key is a miss — annoying, self-healing. Here, a remapped key means this:

> `acct-0000`'s events `v1` and `v2` are sitting **unconsumed** in partition 2 (the old mapping). Its events `v3` and `v4` are appended to partition 6 (the new mapping). Partition 2 is owned by consumer A, partition 6 by consumer B. **The same key is now being processed by two consumers at the same time** — precisely the situation the whole partitioning scheme exists to prevent.

The program constructs exactly this case. Partition 2 has 40 ms of consumer lag; partition 6 is caught up:

```text
apply order  Updv3@c1 -> Delv4@c1 -> Crev1@c0 -> Updv2@c0
inversions 2   anomalies resurrected-deleted-row=1  update-to-missing-row=1
```

The account was updated, deleted, then created, then updated again. It ends the run alive when it should be gone.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 466" width="100%" style="max-width:840px" role="img" aria-label="The repartitioning hazard. When partition count grows from 8 to 12, account acct-0000 moves from partition 2 to partition 6, but its earlier events v1 and v2 remain as unconsumed backlog in partition 2 while v3 and v4 are appended to partition 6. Two consumers then process the same key concurrently and the caught-up consumer overtakes the lagging one, applying Updated v3 and Deleted v4 before Created v1 and Updated v2.">
  <defs>
    <marker id="l07-arrow2" markerWidth="10" markerHeight="10" refX="6" refY="3" orient="auto">
      <path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/>
    </marker>
  </defs>
  <text x="440" y="24" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">Growing 8 partitions to 12 puts one key in two partitions at once</text>

  <g fill="none" stroke-linejoin="round" stroke-width="2">
    <rect x="16" y="42" width="848" height="176" rx="13" fill="#7f7f7f" fill-opacity="0.06" stroke="currentColor" stroke-opacity="0.45" stroke-dasharray="7 6"/>
    <rect x="40" y="80" width="180" height="60" rx="9" fill="#3553ff" fill-opacity="0.12" stroke="#3553ff"/>
    <rect x="40" y="152" width="180" height="46" rx="9" fill="#7c5cff" fill-opacity="0.13" stroke="#7c5cff"/>
    <rect x="300" y="72" width="228" height="60" rx="9" fill="#e0930f" fill-opacity="0.16" stroke="#e0930f"/>
    <rect x="300" y="148" width="228" height="60" rx="9" fill="#0fa07f" fill-opacity="0.16" stroke="#0fa07f"/>
    <rect x="600" y="72" width="240" height="136" rx="10" fill="#e0930f" fill-opacity="0.10" stroke="#e0930f"/>
  </g>
  <g fill="none" stroke="currentColor" stroke-width="1.5">
    <path d="M220 108 L 294 102" marker-end="url(#l07-arrow2)"/>
    <path d="M220 172 L 294 178" marker-end="url(#l07-arrow2)"/>
    <path d="M528 102 L 594 118" marker-end="url(#l07-arrow2)"/>
    <path d="M528 178 L 594 162" marker-end="url(#l07-arrow2)"/>
  </g>

  <g fill="none" stroke-linejoin="round" stroke-width="2">
    <rect x="16" y="234" width="848" height="130" rx="13" fill="#3553ff" fill-opacity="0.06" stroke="#3553ff" stroke-opacity="0.7"/>
  </g>

  <g font-family="'JetBrains Mono', ui-monospace, monospace" fill="currentColor">
    <text x="130" y="105" font-size="10" font-weight="700" text-anchor="middle">acct-0000, v1 v2</text>
    <text x="130" y="122" font-size="8.5" text-anchor="middle" opacity="0.85">written when N = 8</text>
    <text x="130" y="176" font-size="10" font-weight="700" text-anchor="middle">acct-0000, v3 v4</text>
    <text x="130" y="191" font-size="8.5" text-anchor="middle" opacity="0.85">written when N = 12</text>
    <text x="414" y="94" font-size="10.5" font-weight="700" text-anchor="middle" fill="#e0930f">PARTITION 2  (the old home)</text>
    <text x="414" y="112" font-size="9" text-anchor="middle" opacity="0.9">hash % 8 = 2 · consumer c0</text>
    <text x="414" y="126" font-size="9" text-anchor="middle" font-weight="700">40 ms of unconsumed backlog</text>
    <text x="414" y="170" font-size="10.5" font-weight="700" text-anchor="middle" fill="#0fa07f">PARTITION 6  (the new home)</text>
    <text x="414" y="188" font-size="9" text-anchor="middle" opacity="0.9">hash % 12 = 6 · consumer c1</text>
    <text x="414" y="202" font-size="9" text-anchor="middle" font-weight="700">caught up, zero lag</text>
    <text x="720" y="98" font-size="10" font-weight="700" text-anchor="middle">TWO CONSUMERS, ONE KEY</text>
    <text x="720" y="122" font-size="10" text-anchor="middle" font-weight="700" fill="#e0930f">Upd v3 → Del v4</text>
    <text x="720" y="140" font-size="10" text-anchor="middle" font-weight="700" fill="#e0930f">→ Cre v1 → Upd v2</text>
    <text x="720" y="164" font-size="9.5" text-anchor="middle" opacity="0.9">2 inversions · row resurrected</text>
    <text x="720" y="182" font-size="9.5" text-anchor="middle" opacity="0.9">c1 simply had less work to do</text>
    <text x="720" y="200" font-size="9" text-anchor="middle" opacity="0.8">no error, no retry, no alert</text>

    <text x="34" y="260" font-size="11.5" font-weight="700" fill="#3553ff">HOW MANY KEYS MOVE — measured over 500 keys</text>
    <text x="40" y="284" font-size="10">  8 → 12    modulo  65.8%     consistent hash  34.0%     ideal  33.3%</text>
    <text x="40" y="304" font-size="10"> 16 → 32    modulo  52.4%     consistent hash  50.0%     ideal  50.0%   ← doubling is the benign case</text>
    <text x="40" y="324" font-size="10" font-weight="700"> 16 → 17    modulo  94.6%     consistent hash   6.0%     ideal   5.9%   ← adding ONE partition</text>
    <text x="40" y="348" font-size="9.5" opacity="0.85">Consistent hashing shrinks the blast radius. It does not make the operation safe: any key that moves has the split-brain above.</text>

    <text x="34" y="394" font-size="11.5" font-weight="700" fill="#0fa07f">THE THREE SAFE PROCEDURES</text>
    <text x="40" y="416" font-size="10">1 · OVER-PROVISION.  Pick the partition count for peak-plus-headroom on day one. Idle partitions are nearly free.</text>
    <text x="40" y="434" font-size="10">2 · DRAIN FIRST.  Stop producers, consume to zero lag, change N, restart. The only procedure with no window at all.</text>
    <text x="40" y="452" font-size="10">3 · DOUBLE, NEVER INCREMENT.  8→16 keeps half the keys put; 16→17 moves 94.6%. If you must grow, grow by 2x.</text>
  </g>
</svg>
```

The safe procedures, in order of preference:

1. **Over-provision up front.** Choose the partition count for projected peak plus headroom on day one. An idle partition costs a file handle and a little metadata; a partition migration costs a maintenance window. Sizing for 3–5× current peak is normal and cheap — the upper bound is that every partition adds file descriptors, replication traffic and rebalance time, and thousands per broker is where it starts to hurt.
2. **Drain before repartitioning.** Stop producers, let consumers reach zero lag on every partition, then change N and restart. The only procedure with *no* correctness window — the old partitions are empty, so no key can exist in two places. It requires pipeline downtime, which is why people skip it, which is why the incident happens.
3. **Use consistent hashing where the system supports it.** The ring from the caching and sharding material (`glossary/terms.md` → *Consistent Hashing*) maps keys and virtual nodes onto one hash space so a key belongs to the next node clockwise; growing the ring moves only the slice beside the new nodes. The measured improvement is dramatic — 6.0% instead of 94.6% for `16 → 17`. But be precise about what it buys: it **shrinks the blast radius, it does not remove the hazard.** Every key that *does* move has exactly the split-brain problem above. Consistent hashing turns "a catastrophe" into "a small catastrophe", which is genuinely worth having, and is not the same as safety.

One more consequence worth internalising: **partition counts generally go up and never down.** Reducing N would strand the data already written to the disappearing partitions. Kafka refuses the operation outright. So the number you pick is close to permanent — treat it that way.

### Consumer groups, assignment, and what a rebalance costs you

A **consumer group** is a set of consumers cooperating to consume one topic, with one rule that determines everything: **each partition is assigned to at most one consumer in the group at a time.** That rule is what makes the ordering guarantee hold end to end — the broker orders the partition, and the assignment guarantees exactly one reader applying it.

The direct consequence is a hard ceiling:

```text
  6 partitions, 3 consumers -> c0:[0, 1]  c1:[2, 3]  c2:[4, 5]
      0 consumer(s) idle, effective parallelism 3
  6 partitions, 9 consumers -> c0:[0]  c1:[1]  c2:[2]  c3:[3]  c4:[4]  c5:[5]  c6:-  c7:-  c8:-
      3 consumer(s) idle, effective parallelism 6
```

**Consumer parallelism is capped at the partition count.** Consumers 6, 7 and 8 are running, healthy, connected, consuming CPU and memory, holding a group membership — and doing nothing at all. They are not "spare capacity"; they are a slow-motion billing error. (They are not entirely useless: they are warm standbys that take over instantly if a consumer dies. Just be honest that that is what you are paying for.) The summary table confirms it: 6 consumers and 9 consumers both give exactly **1,535 records/s**.

When membership changes — a consumer joins, leaves, crashes, or just fails to heartbeat because of a long garbage-collection pause — the group **rebalances**: partitions are revoked and reassigned. And a rebalance is a duplicate generator, by construction.

The reason is offsets. A consumer commits its position periodically, not per message, because committing every message would cost a round trip per message. So at any instant there is a gap between *processed* and *committed*. When a partition is reassigned, its new owner resumes from the **last committed** offset — and everything in that gap gets processed a second time.

The program kills consumer 1 mid-run with offsets committed every 25 records, and measures the two rebalance protocols:

```text
  eager        revoked 6/6 partitions   delivered 1,320   unique 1,200   duplicates 120 (10.0%)
  cooperative  revoked 2/6 partitions   delivered 1,240   unique 1,200   duplicates  40 (3.3%)
```

**Eager (stop-the-world) rebalancing** revokes *every* partition from *every* consumer, then reassigns from scratch. All six partitions replay their uncommitted window, so 120 records — 10% of the workload — are processed twice, including on the four partitions belonging to consumers that were perfectly healthy the whole time. During the revoke-to-assign gap, the entire group also stops consuming, so this is a throughput stall as well as a duplicate storm.

**Cooperative (incremental) rebalancing** revokes only what must move — the dead consumer's two partitions. The other four consumers never pause and never replay. Duplicates fall from 120 to 40, a **3× reduction**, and there is no stop-the-world gap.

**Sticky assignment** is the companion idea: when reassigning, prefer to give each consumer back the partitions it already had. This matters more than it sounds, because consumers accumulate per-partition state — deduplication tables (Lesson 06), aggregation windows, warm caches — and a non-sticky assignment throws all of it away on every membership change.

Two things follow directly, and they are not optional:

**Idempotency is mandatory, not advisable.** The duplicate window above is not a bug you can fix; it is a structural property of committing offsets in batches. It fires on every deploy, every autoscale event, every pod eviction, every GC pause long enough to miss a heartbeat — which in a busy service is several times a day. The dedup-on-message-id consumer from [Delivery Semantics & Idempotent Consumers](../06-delivery-semantics-and-idempotency/) absorbs it completely: 1,320 deliveries become **1,200 side effects, 0 wrong**, in both the eager and cooperative runs. Without it, 120 duplicate charges.

**A rebalance also breaks ordering briefly.** During the window, the old owner may still be processing a record it fetched before revocation while the new owner starts from the committed offset. Two consumers, one partition, for a moment. This is why brokers fence the old owner off at commit time and why "at most one consumer per partition" is a statement about *committed effects*, not about wall-clock exclusivity.

### Ordering is not free even inside one partition

The broker did its job. The partition is a perfectly ordered sequence. Then you write this, because it makes the throughput graph look great:

```python
records = consumer.poll(max_records=500)
await asyncio.gather(*(handle(r) for r in records))   # <-- the bug
```

And you have thrown the ordering away *after* paying for it. The partition's order survived the network and the broker and died in your own thread pool.

The program measures it on the hash-partitioned log — the one with zero violations:

```text
  1 thread per partition (serial)    inversions     0   accounts damaged    0   throughput   1,535/s
  8 threads, next-free-worker        inversions    49   accounts damaged   47   throughput  11,501/s
  8 threads, routed by key           inversions     0   accounts damaged    0   throughput   4,511/s
```

Eight threads with naive dispatch is **7.5× the throughput and 47 corrupted accounts** — 16% of the book. The mechanism is exactly the one from The Problem, just moved inside a single process: some handlers are slow (a cache miss, a retry), later records overtake earlier ones, and the effects land out of order.

The fix is **per-key sequencing inside the consumer**: route each record to a worker by `hash(key) % n_workers`, so every record for a given key always goes to the same thread and is therefore serialized against its own history. This recovers 4,511/s — 2.9× the serial version — with **zero** violations. It is slower than naive dispatch because the workers get uneven loads (the same skew problem, one level down), and that is the honest price.

The rule to remember: **the guarantee is "ordered per key, end to end", and the consumer is part of "end to end."** A broker cannot enforce anything about what you do after `poll()` returns.

### Do you actually need ordering at all?

The senior move is often to sidestep the whole thing. Ordering is expensive — in parallelism, in operational risk, in the partition-count decision you can never take back. Sometimes you can delete the requirement instead of satisfying it.

**Version-based rejection (last-write-wins by version).** Put a monotonically increasing version or sequence number on every event for an entity — which you probably already have, since it is your row's optimistic-concurrency version. Then the handler rejects anything stale:

```python
if incoming.version <= stored.version:
    return          # a newer state is already applied; this event is history
apply(incoming)
```

Run the *badly ordered* round-robin stream through this handler:

```text
rejected 242 stale events   accounts in the WRONG final state: 0 of 300
```

242 inversions and **zero corrupted rows**. The ordering requirement was not satisfied — it was removed. The handler no longer cares what order events arrive in, because it can recognise the past when it sees it.

Be precise about the limits, because this is where people over-apply it:

- **It converges on the final state, and skips intermediate ones.** If `Updated(v2)` arrives after `Deleted(v4)`, it is dropped. If anything downstream needed to observe `v2` — an audit trail, a change-data-feed, a notification — it never happens. Fine for a materialized view; wrong for an event-sourced ledger.
- **It works because the handler overwrites state.** For handlers that *accumulate* (`balance += amount`), a version check is wrong: you must not drop a debit just because a later credit already landed.

**Commutativity.** For accumulating handlers, the tool is different: make the operation commutative, so order stops mattering by algebra rather than by check. Ticket three is the perfect example. `Debit(50)` and `Credit(100)` applied in either order give the same final balance — addition commutes, and the *final* answer was never in danger. The only thing that broke was a fraud rule reading an intermediate state that had no meaning. The correct fix was not to order the events; it was to stop alerting on a mid-stream value that is meaningless until the stream settles. Counters, sets, and max/min aggregations are all naturally commutative — this is the same family of ideas as CRDTs (Conflict-free Replicated Data Types).

The design question, then, is not "how do I get ordering?" It is: **"what specifically breaks if these two events swap? and is fixing that cheaper than guaranteeing order?"** Often it is.

### The same idea under other names

Once you see the primitive, every broker's version of it is obvious.

- **Kafka** calls it the message `key`, and the unit is a **partition**.
- **AWS Kinesis** calls it the **partition key**, and the unit is a **shard**.
- **SQS FIFO** calls it `MessageGroupId`: order is guaranteed within a group, and different groups are delivered in parallel. That is exactly a partition key with a different noun.
- **Google Cloud Pub/Sub** calls it an **ordering key**.
- **RabbitMQ** has no native concept, but the consistent-hash exchange plugin recreates it.

Five products, five words, one idea: *messages that share this field are ordered relative to each other; everything else is fair game.*

## Build It

`code/partitioned_log.py` takes Lesson 05's append-only log, splits it into N partitions with a pluggable partitioner, and runs one causally-ordered workload — 300 accounts × `Created → Updated → Updated → Deleted` — through every strategy in this lesson. Standard library only, seeded, virtual clock, deterministic.

The log itself is small, because the idea is small. N independent lists, one partitioner:

```python
class PartitionedLog:
    """N independent append-only logs. Order is total within a partition and
    undefined across partitions. That is the whole guarantee."""

    def append(self, rec: Record) -> int:
        p = self.partitioner(rec, self.n)
        rec.partition, rec.offset = p, len(self.partitions[p])
        self.partitions[p].append(rec)
        return p
```

The hash deserves a comment, because it is a real production trap:

```python
def stable_hash(key: str) -> int:
    """The partitioner's hash must be explicit and stable across processes.

    Python's built-in hash() of a str is randomised per interpreter (PEP 456,
    SipHash), so using it would send the same key to a different partition
    after every restart - silently breaking ordering. Kafka ships its own
    murmur2 for exactly this reason.
    """
    return int.from_bytes(hashlib.blake2b(key.encode(), digest_size=8).digest(), "big")
```

Violations are *detected*, not assumed. An **inversion** is an event applied after a strictly newer version of the same key was already applied, and alongside it the program runs the entity's real state machine so the damage has the names a support ticket would use:

```python
h = high.get(r.key, 0)
if r.version < h:
    inversions += 1
    damaged.add(r.key)
high[r.key] = max(h, r.version)

s = state.get(r.key, "NONE")
if s == "GONE":                                   anomalies["resurrected-deleted-row"] += 1
elif s == "NONE" and r.etype == "Updated":        anomalies["update-to-missing-row"] += 1
elif s == "NONE" and r.etype == "Deleted":        anomalies["delete-of-missing-row"] += 1
elif s == "ACTIVE" and r.etype == "Created":      anomalies["create-over-live-row"] += 1
```

Parallelism is modelled honestly on a virtual clock. Each consumer runs at its own speed, and per-record service time is heavy-tailed — most records are quick, roughly one in ten misses a cache or retries an upstream and takes several times longer. **That tail is the entire mechanism**; without variance, consumers never overtake each other:

```python
def service_time(rnd, speed):
    x = rnd.random()
    return speed * (8.0 * x if x > 0.9 else 1.0 + 0.35 * x)
```

The rebalance simulation tracks `processed` and `committed` separately per partition, which is where duplicates come from, and the difference between the two protocols is one line:

```python
revoked = list(range(log.n)) if mode == "eager" else list(assign[dead])
replay = 0
for p in revoked:                                # uncommitted work is redone
    replay += processed[p] - committed[p]
    processed[p] = committed[p]
```

Run it:

```console
$ python partitioned_log.py
== 1. THE WORKLOAD: causally ordered, per entity ==
  300 accounts x 4 lifecycle events = 1,200 records
  per account the order is fixed: Created(v1) -> Updated(v2) -> Updated(v3) -> Deleted(v4)
  across accounts nothing is ordered - we need a PARTIAL order, not a total one
  producer's global stream, first 8: 0131v1 0260v1 0073v1 0286v1 0153v1 0129v1 0088v1 0276v1

== 2. ASSIGNMENT: parallelism is capped at the partition count ==
  6 partitions, 3 consumers -> c0:[0, 1]  c1:[2, 3]  c2:[4, 5]
      0 consumer(s) idle, effective parallelism 3
  6 partitions, 6 consumers -> c0:[0]  c1:[1]  c2:[2]  c3:[3]  c4:[4]  c5:[5]
      0 consumer(s) idle, effective parallelism 6
  6 partitions, 9 consumers -> c0:[0]  c1:[1]  c2:[2]  c3:[3]  c4:[4]  c5:[5]  c6:-  c7:-  c8:-
      3 consumer(s) idle, effective parallelism 6

== 3. THE CORE CONTRAST: same workload, two partitioners ==
  round-robin      partitions [200, 200, 200, 200, 200, 200]
      inversions   242   accounts damaged  178 of 300   wrong final state  109
      anomalies: create-over-live-row=52  delete-of-missing-row=7  resurrected-deleted-row=109  update-to-missing-row=59
  hash(key) % N    partitions [180, 176, 148, 204, 280, 212]
      inversions     0   accounts damaged    0 of 300   wrong final state    0
      anomalies: none - every event applied to a legal state
  one damaged account, acct-0001:
      round-robin : Updv2@c2 -> Crev1@c3 -> Delv4@c0 -> Updv3@c1
      hash(key)   : Crev1@c3 -> Updv2@c3 -> Updv3@c3 -> Delv4@c3
  nothing crashed and no record was lost - every consumer was correct alone

== 4. THE OTHER ANSWER: reject stale versions instead of buying order ==
  same out-of-order round-robin stream, handler adds `if v <= stored.v: skip`
  rejected 242 stale events   accounts in the WRONG final state: 0 of 300
  242 inversions, 0 corrupted rows: the ordering requirement was removed,
  not satisfied. Intermediate states are still skipped - that is the price.

== 5. KEY SKEW: Zipfian tenants against a hash partitioner ==
  20,000 messages over 500 tenants (Zipf s=1.0), 16 partitions
  hottest tenants: tenant-0000=2,905 (14.5%)  tenant-0001=1,450 (7.2%)  tenant-0002=985 (4.9%)
  hash(key) % N
      counts 1,728   671   627 3,296 1,553   500 1,043   770   873   792   864 1,775 1,342   884 1,138 2,144
      max 3,296  min 500  mean 1,250   max/min 6.59   max/mean 2.64
      effective parallelism 6.07 of 16 consumers   (9.93 wasted)
  hash(key+salt) % N  (top 3 keys, fanout 8)
      counts   743   803   817   764 1,553   858 1,576 1,254 1,914 1,078 1,045 1,775 1,754 1,009 1,635 1,422
      max 1,914  min 743  mean 1,250   max/min 2.58   max/mean 1.53
      effective parallelism 10.45 of 16 consumers   (5.55 wasted)
  the salt spreads the top 3 tenants over up to 8 partitions -
  and those 3 tenants, 26.7% of all traffic, now have NO ordering guarantee at all
  adding consumers past 16 cannot help: the busiest partition still holds one consumer's work

== 6. THE REPARTITION HAZARD: changing N remaps almost every key ==
    8 -> 12  partitions   modulo:  329 of 500 keys move ( 65.8%)   consistent hash:  170 ( 34.0%)   ideal  33.3%
   16 -> 32  partitions   modulo:  262 of 500 keys move ( 52.4%)   consistent hash:  250 ( 50.0%)   ideal  50.0%
   16 -> 17  partitions   modulo:  473 of 500 keys move ( 94.6%)   consistent hash:   30 (  6.0%)   ideal   5.9%
  concrete: acct-0000 lived in partition 2 of 8; after growing to 12 it lives in 6
  its v1,v2 are still unconsumed backlog in p2 while v3,v4 are appended to p6
  two consumers now own the same key at the same time:
      apply order Updv3@c1 -> Delv4@c1 -> Crev1@c0 -> Updv2@c0
      inversions 2   anomalies resurrected-deleted-row=1  update-to-missing-row=1
  drain p2 to zero lag BEFORE adding partitions and this window closes

== 7. REBALANCE: a consumer dies and uncommitted work is replayed ==
  6 partitions, 3 consumers, offsets committed every 25 records; consumer 1 dies
  eager        revoked 6/6 partitions   delivered 1,320   unique 1,200   duplicates 120 (10.0%)
      naive consumer: 1,320 side effects, 120 of them wrong
      idempotent consumer (Lesson 06, dedup on message id): 1,200 side effects, 0 wrong
  cooperative  revoked 2/6 partitions   delivered 1,240   unique 1,200   duplicates  40 (3.3%)
      naive consumer: 1,240 side effects, 40 of them wrong
      idempotent consumer (Lesson 06, dedup on message id): 1,200 side effects, 0 wrong
  a rebalance is a duplicate generator by construction - idempotency is
  what makes it survivable, and cooperative assignment is what makes it small

== 8. ORDER DIES INSIDE THE CONSUMER TOO ==
  1 thread per partition (serial)    inversions     0   accounts damaged    0   throughput   1,535/s
  8 threads, next-free-worker        inversions    49   accounts damaged   47   throughput  11,501/s
  8 threads, routed by key           inversions     0   accounts damaged    0   throughput   4,511/s
  the broker handed the consumer a perfectly ordered partition and the
  consumer's own thread pool threw it away. Per-key routing keeps both.

== 9. SUMMARY ==
  strategy                               part  cons   inver.  mx/mean   eff.p      rec/s
  single partition (total order)            1     1        0     1.00    1.00        585
  round-robin, 6 consumers                  6     6      242     1.00    6.00      1,627
  hash(key) % N, 6 consumers                6     6        0     1.40    4.29      1,535
  hash(key) % N, 9 consumers (3 idle)       6     9        0     1.40    4.29      1,535
  hash + 1 thread per partition (serial)    6     6        0     1.40    4.29      1,535
  hash + 8 threads, next-free-worker        6     6       49     1.40    4.29     11,501
  hash + 8 threads, routed by key           6     6        0     1.40    4.29      4,511
  a total order costs 585/s; partitioning by key buys 2.6x with the same guarantee where it matters
```

Read the summary table from the top, because it is the lesson compressed into seven rows.

**The single partition is the only configuration with a total order, and it is the slowest** — 585 records/s, one consumer, no parallelism available at any price. That is the throughput ceiling a sequencer imposes.

**Round-robin is the fastest of the correct-looking options and the only wrong one.** Perfect balance (`max/mean = 1.00`), full effective parallelism (6.00 of 6), 1,627 records/s — and 242 inversions across 178 of 300 accounts. Every operational metric improved. The data got worse.

**Hash-by-key gives up 6% of throughput and all of the errors.** 1,535 records/s against round-robin's 1,627. `max/mean` rises to 1.40 because hashing 300 keys into 6 buckets is lumpy, so effective parallelism falls to 4.29 of 6. **That is the trade, quantified: about 6% of throughput and 1.7 consumers' worth of balance, in exchange for zero corrupted accounts.** Nobody who has read a support ticket would hesitate.

**Nine consumers and six consumers are the same number.** Both 1,535 records/s. Three processes running, three processes idle, one bill.

**The serial row reproduces the group row exactly** — both 1,535 records/s. That is deliberate: the two simulators share a clock and a service-time distribution, so the intra-consumer rows below can be compared to the ones above without an asterisk.

**And then the consumer undoes it.** Eight naive threads: 11,501 records/s and 49 inversions. The broker's guarantee ended at `poll()`. Eight threads routed by key: 4,511 records/s, zero inversions — 2.9× the serial throughput with the guarantee intact, and lower than naive dispatch because per-key routing gives workers uneven loads.

Three more results worth pausing on.

**The skew numbers are the ones that cost real money.** A perfectly correct partition key still gave an effective parallelism of **6.07 of 16 consumers**. Nothing is broken and lag is fine — you are simply paying for ten machines that cannot help, and no amount of scaling changes it, because the hot partition is one consumer's work by definition.

**94.6%.** Adding one partition to sixteen relocates almost every key in the system. If you take one operational fact from this lesson, take that one: *increasing the partition count is a correctness-affecting operation, not a capacity operation.* Note also that consistent hashing at `16 → 32` is exactly as good as modulo (both 50%) — doubling is the one growth step where plain modulo is already optimal, which is a good reason to grow by doubling.

**Idempotency turns the rebalance from an incident into a metric.** Cooperative rebalancing makes the duplicate window *smaller* (120 → 40); idempotency makes it *harmless* (1,320 deliveries → 1,200 side effects, zero wrong). Do both; if you can only do one, do idempotency.

## Use It

You will not implement a partitioner. You will pick a key and a number, and live with both for years.

**Kafka.** A record carries an optional `key`; the producer's partitioner hashes it to choose a partition. That's the whole mechanism.

```python
producer.send("account-events", key=b"acct-0001", value=payload)   # key -> partition
producer.send("account-events", value=payload)                     # no key -> no ordering
```

A null key means no ordering guarantee at all — the producer batches records into whichever partition is convenient (the "sticky partitioner", chosen for batching efficiency, not for you). **A missing key is the round-robin row of the summary table**, and it is the single most common cause of the bug in The Problem.

Watch the hash function across client libraries. The Java client's default partitioner hashes the key with **murmur2**; `librdkafka` — and therefore the Python, Go, C++ and .NET clients built on it — defaults to a different scheme (`consistent_random`, using CRC32). Two services in different languages publishing the same key to the same topic can land it in **two different partitions**, which silently breaks ordering across the pair. Set the partitioner explicitly (`partitioner="murmur2_random"` in `confluent-kafka-python`) when more than one language produces to a topic.

On the consumer side:

```text
partition.assignment.strategy=org.apache.kafka.clients.consumer.CooperativeStickyAssignor
max.poll.records=500          # a batch -- process it IN ORDER, or route by key
enable.auto.commit=false      # commit after processing, not on a timer
```

`CooperativeStickyAssignor` is the cooperative + sticky combination from The Concept, and it is what you want in almost every deployment. `max.poll.records` is the trap from section 8: a poll hands you up to 500 records, and if you fan them out across a thread pool you have just reproduced 49 inversions.

Partition count: `kafka-topics.sh --alter --partitions 32` increases it. There is **no** command to decrease it. Kafka does not move existing data when you add partitions — the partitioner simply starts sending new records elsewhere, which is precisely the split-brain of section 6.

**AWS Kinesis.** `PutRecord` takes a `PartitionKey`; Kinesis MD5-hashes it into a 128-bit space and maps the result to whichever **shard** owns that range. Because the mapping is range-based, resizing is `SplitShard`/`MergeShards` on specific ranges rather than a global remap — better behaved than modulo, and still a window where a key's old and new shards are both live. A shard is also a hard capacity unit (1 MB/s or 1,000 records/s in, 2 MB/s out), so a hot key does not merely idle consumers, it earns you `ProvisionedThroughputExceededException`.

**SQS FIFO.** The clearest naming of the idea in any product:

```python
sqs.send_message(
    QueueUrl=q,
    MessageBody=body,
    MessageGroupId="acct-0001",        # <- the partition key. Order within a group.
    MessageDeduplicationId=event_id,   # <- Lesson 06, built into the broker
)
```

Messages sharing a `MessageGroupId` are delivered in order, one in flight at a time; different groups proceed in parallel. Note the direct consequence — **an in-flight message blocks its whole group until it is deleted or its visibility timeout expires**, so one poison message stalls that account (Lesson 08's problem). FIFO queues also trade throughput for the guarantee: 300 transactions/second per API action by default, 3,000 messages/second with batches of 10, with a high-throughput mode for FIFO that raises the limits considerably. Standard queues have no such cap — because they make no such promise.

**Google Cloud Pub/Sub.** Set an `ordering_key` on publish and `enable_message_ordering` on the subscription; messages with the same key are delivered in order within a region. If a publish for an ordering key fails, the client suspends that key until you call `resume_publish()` — it will not let a gap through silently, which is the right default and surprises people.

**RabbitMQ.** No native partitioning, because a queue is a queue. The `rabbitmq_consistent_hash_exchange` plugin recreates it: bind N queues to a consistent-hash exchange, and it routes each message by hashing the routing key (or a named header) onto the ring, weighted by the binding keys. One consumer per queue, and you have partitions. The same trick, in a broker that was not designed for it.

**The metric to watch, in every one of them:** per-partition lag, not aggregate lag. Aggregate lag hides the entire skew problem — fifteen partitions at zero and one at four million averages out to something that looks survivable. Alarm on `max(lag) across partitions`, and chart the per-partition message rate so a hot key is visible as a shape rather than as a customer complaint.

## Think about it

1. Your `orders` topic is keyed by `order_id` and everything works. Product asks for a per-customer running total of lifetime spend, computed by a new consumer on the same topic. Explain precisely why that consumer can produce wrong totals under the current key, and give two different fixes — one that changes the key and one that does not. What does each cost?

2. You have 16 partitions and measured `max/mean = 2.64`. Your manager proposes doubling the consumer count from 16 to 32 to halve the lag. Using the measured effective-parallelism number, explain what will actually happen, and name the only two things that would help.

3. A team salts their hottest tenant across 8 partitions to fix a hot spot, and the ordering bug from The Problem appears for that tenant only. They cannot un-salt without recreating the hot spot. Describe how the version-rejection handler from section 4 lets them keep the salt — and identify the specific kind of event for which that rescue would *not* work.

4. Your pipeline has 8 partitions and needs 12. Compare the three procedures — over-provision (too late), drain-first, and consistent hashing — against three criteria: correctness window, downtime, and implementation cost. Which do you pick if the pipeline must not stop, and what do you have to accept?

5. A consumer commits offsets every 5 seconds and processes 400 records/second. A pod eviction triggers an eager rebalance across 12 partitions. Estimate the number of duplicate deliveries, and explain why the answer barely changes if the eviction was graceful. Then say what single change makes the number irrelevant rather than smaller.

6. The measured run shows round-robin partitioning is *faster* than hash-by-key (1,627 vs 1,535 records/s) with perfectly balanced partitions. Construct the argument you would make to a manager who has seen only the dashboard and wants to know why you are proposing a change that makes the numbers worse.

## Key takeaways

- **Wall-clock timestamps do not order events across machines** — clock skew of tens of milliseconds is routine and corrections can move clocks backwards, so two events 40 ms apart can carry reversed times. Brokers assign monotonic offsets at append instead. Lamport's happens-before relation ("Time, Clocks, and the Ordering of Events in a Distributed System", CACM 21(7), 1978) defines the order you actually need, and it is a **partial** order: order per entity, no order between unrelated entities.
- **A total order requires a single sequencer, which is a throughput ceiling and a single point of failure.** Ordering and parallelism are in direct opposition — measured, a single-partition total order ran at 585 records/s against 1,535 for hash-by-key across six. Every technique in this lesson buys parallelism back by weakening the guarantee to exactly what the business needs.
- **Partitioning is the resolution: total order within a partition, none across.** Choose a partition key so everything that must be ordered together lands together. On an identical workload and consumer group, round-robin produced **242 inversions across 178 of 300 accounts** (109 left in the wrong final state) while hash-by-key produced **zero** — and round-robin was *faster*, which is why this bug ships.
- **The partition key does three jobs at once**: it defines the ordering guarantee, it determines load distribution, and it caps consumer parallelism. Engineers typically reason about one. Too coarse (region, a boolean) means hot partitions and no scale; too fine (a per-event UUID) means perfect balance and no ordering at all. The right key is the identity of the smallest thing that has a state machine.
- **Real key distributions are Zipfian and one key will be enormous.** Measured, 500 tenants over 16 partitions gave `max/mean = 2.64` and an **effective parallelism of 6.07 of 16** — ten consumers paid for and unable to help, because the partition is the unit of parallelism. Mitigations are composite keys (best: keeps the ordering you needed), salting the hot key (recovered 10.45 of 16, at the cost of *all* ordering for 26.7% of traffic), or isolating the elephant tenant onto its own topic.
- **`hash(key) % N` means changing N remaps almost everything.** Measured over 500 keys: `8→12` moves 65.8%, and **`16→17` moves 94.6%**. A moved key with unconsumed backlog exists in two partitions at once and is processed by two consumers concurrently — the exact split-brain partitioning exists to prevent. Over-provision up front, drain to zero lag before repartitioning, grow by doubling (`16→32` moves only 50%), and treat consistent hashing as blast-radius reduction rather than safety. Partition counts go up and never down.
- **Consumer parallelism is capped at the partition count** — 6 consumers and 9 consumers both measured 1,535 records/s, with three processes idle. **Rebalancing generates duplicates by construction**, because offsets are committed in batches and reassignment replays the uncommitted window: measured 120 duplicates (10%) with eager stop-the-world rebalancing versus 40 (3.3%) with cooperative. Cooperative + sticky assignment makes the window smaller; **Lesson 06's idempotency makes it harmless** — 1,320 deliveries became 1,200 side effects with zero wrong.
- **The guarantee is end-to-end, and your consumer is part of "end".** Fanning a poll batch across a thread pool destroys the order the broker just handed you: measured, 8 naive threads gave 7.5× throughput and **49 inversions across 47 accounts**. Per-key routing to workers (`hash(key) % n_workers`) kept 2.9× the serial throughput with zero violations.
- **The senior move is often to delete the ordering requirement rather than pay for it.** A version check (`if incoming.version <= stored.version: skip`) turned 242 inversions into **zero corrupted rows** — but it converges only on the final state and silently drops intermediates, and it is wrong for accumulating handlers, where the tool is commutativity instead. Ask "what specifically breaks if these two swap?" before asking "how do I order them?"

Next: [Retries, Backoff, Dead-Letter Queues & Poison Messages](../08-retries-backoff-and-dead-letter-queues/) — because the moment you guarantee order within a partition, one message that will never succeed stops everything behind it, and you need somewhere to put it.
