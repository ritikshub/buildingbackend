# The Log: Offsets, Replay & Retention

> A queue forgets. The instant a consumer says "got it", the message is gone — which is exactly what you want until the morning you discover your consumer has been silently writing garbage for six hours and there is nothing left to fix it with. This lesson takes one small idea — *stop deleting on acknowledgement* — and follows it all the way down. What comes out is the third broker shape: an ordered, immutable, replayable log where the reader, not the broker, remembers where it is. You will build one, rewind it, expire it, compact it, and crash it.

**Type:** Build
**Languages:** Python
**Prerequisites:** [Pub/Sub: Topics, Subscriptions & Fan-Out](../04-pub-sub-topics-and-fan-out/)
**Time:** ~90 minutes

## The Problem

The queue of [Lesson 3](../03-build-a-message-queue/) and the topic of [Lesson 4](../04-pub-sub-topics-and-fan-out/) look like different things, but they share one design decision so deeply that it is easy to miss: **a message is destroyed once it has been acknowledged.** The queue deletes it after the single consumer acks. The topic deletes each subscriber's copy after that subscriber acks. In both, the broker's job is to hold a message *until delivery is confirmed*, and then to forget it. Delivery is the goal; storage is a temporary inconvenience on the way there.

This is a perfectly good design, and it is what most people mean by "message broker". It is also wrong in four specific situations, and each one is a real outage or a real project that got cancelled.

**One: the bug you cannot undo.** Your `payments-reconciler` deploys at 09:00 with a subtle error — a currency conversion applied twice. It reads 40,000 messages over six hours, writes 40,000 wrong rows, and acks every one. At 15:00 someone notices. You fix the code in ten minutes, and then discover the real problem: **there is nothing to reprocess.** The messages were acked, so the broker deleted them. The broker did its job flawlessly — it delivered every message exactly as promised — and the data is gone. Your options are to reconstruct the input from the corrupted output, or to ask another team to re-emit six hours of history they probably cannot reproduce either.

**Two: the service you cannot launch.** Product wants search over orders. The new `search-indexer` needs the last 30 days to build its initial index; after that it keeps up in real time. Every one of those events existed and flowed through your broker. **None were kept.** So the launch plan is no longer "subscribe and backfill" — it is a bespoke migration job that reads the `orders` table directly, reimplements the event-shaping logic the producer already has, and gets to drift from it forever. A capability you should have had for free became a two-week project with a permanent maintenance tail.

**Three: the question you cannot answer.** During an incident review someone asks the only question that matters: *"what did the system actually receive at 14:32?"* Not what your database looks like now — what **arrived**. The message was consumed and deleted, so the only evidence is the downstream state it produced, which is precisely the thing under suspicion. You are debugging a system whose inputs were thrown away.

**Four: the two consumers you cannot satisfy.** A fraud check must see every transaction within a second. A finance aggregation runs at 02:00 over the whole day in one pass. The queue model forces them into one delivery lifecycle: the broker tracks, per message, whether *each* has taken it, holds every message until the slowest has acked, and grows unboundedly whenever the batch job is paused. The fast consumer's latency and the slow consumer's schedule are now coupled through the broker's bookkeeping.

All four trace back to one line of code somewhere inside the broker: **`ack` and `delete` happen together.** Two ideas — *this consumer has finished with this message* and *no one will ever need this message again* — are welded into one operation. The first is about one reader's progress. The second is a claim about every reader, present and future, forever.

Prise them apart and you do not get a better queue. You get a different primitive, and it is the one most large-scale data infrastructure is built on.

## The Concept

### The append-only log — and you have already built one

An **append-only log** is an ordered, immutable sequence of records with exactly two operations:

- **Append** a record to the end. Nothing else. You cannot insert in the middle, update a record, or delete one.
- **Read** from a position, forward. Reads are *positional*, not destructive — reading does not change the log.

That is the entire data structure, and its power comes from what it refuses to do. Because records are immutable and only ever added at the tail, a record's position is fixed the moment it is written — so a position is a permanent, meaningful name for a record. Because reads never mutate, any number of readers can read the same log at once without coordinating, and any reader can read the same region twice.

If this feels familiar, it should. **[Phase 3, Lesson 13](../../03-relational-databases/13-write-ahead-logging/) built exactly this structure** as a write-ahead log (WAL), to make a database commit durable: write the *intent* of a change to a sequential file, flush it, update the data pages lazily. Same append-only file, same length-prefixed records, same recovery-by-replay. That continuity is worth naming, because it tells you the log is not a messaging trick — it is a general-purpose primitive solving two problems that look unrelated:

| | Write-ahead log (Phase 3) | Message log (this lesson) |
|---|---|---|
| Records | intended changes to pages | events produced by a service |
| Read by | the recovery process, after a crash | consumers, continuously |
| Why replay | rebuild committed state | reprocess, backfill, audit |
| Lifetime | until a checkpoint makes it redundant | until a retention policy expires it |
| The invariant | the log is the truth; pages are a cache of it | the log is the truth; downstream stores are caches of it |

That last row is the one to sit with. In both cases **the log is authoritative and everything derived from it is a materialised view that can be rebuilt.** The database can throw away its data pages and reconstruct them from the WAL. A downstream service can throw away its entire database and reconstruct it from the event log. That is the same idea wearing two hats, and it is the reason this lesson eventually points at event sourcing and change data capture.

### The offset, and the one consequence that matters

Every record in the log gets an **offset**: a monotonically increasing integer identifying its position. Offset 0 is the first record ever written, offset 1 the next, and so on. An offset is *not* a message ID chosen by a producer (that was [Lesson 2](../02-anatomy-of-a-message/)) — it is assigned by the log at append time and encodes ordering.

Now the consequence that changes everything:

> **The consumer owns its position. The broker does not track delivery.**

In the queue model the broker maintains per-message, per-consumer state: delivered, acked, in-flight since when, redelivery count, visibility timeout expiry. That state is the broker's core job, and it grows as messages × consumers.

In the log model the broker maintains **one integer per consumer group**: "this group has processed everything below offset N." Nothing per-message. One number.

The program makes that difference concrete: for 2,000 records and 3 groups, queue-shaped bookkeeping is **6,000 entries** while the log's is **3 integers**. Not just smaller — a different *shape*, O(consumers) instead of O(messages × consumers), so it does not grow when traffic does.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 520" width="100%" style="max-width:840px" role="img" aria-label="Comparison of the queue or topic model with the log model. In the queue model acknowledging deletes the message and the broker holds per-message per-consumer delivery state, 6000 entries for 2000 messages and 3 consumers, and nothing can be replayed. In the log model records are never deleted on acknowledgement, three consumer groups sit at different offsets in one shared copy of the data, and the broker holds only three integers.">
  <defs>
    <marker id="l05-arrow" markerWidth="10" markerHeight="10" refX="6" refY="3" orient="auto">
      <path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/>
    </marker>
  </defs>
  <text x="440" y="24" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">Acknowledging is not deleting — separate them and you get a different primitive</text>

  <g fill="none" stroke-linejoin="round" stroke-width="2">
    <rect x="16" y="40" width="848" height="196" rx="13" fill="#e0930f" fill-opacity="0.07" stroke="#e0930f"/>
    <rect x="16" y="250" width="848" height="256" rx="13" fill="#0fa07f" fill-opacity="0.07" stroke="#0fa07f"/>
  </g>

  <g fill="none" stroke-linejoin="round" stroke-width="2">
    <rect x="36" y="118" width="92" height="46" rx="9" fill="#3553ff" fill-opacity="0.13" stroke="#3553ff"/>
    <rect x="172" y="96" width="232" height="92" rx="10" fill="#e0930f" fill-opacity="0.14" stroke="#e0930f"/>
    <rect x="452" y="96" width="112" height="40" rx="8" fill="#7f7f7f" fill-opacity="0.10" stroke="currentColor" stroke-opacity="0.55"/>
    <rect x="452" y="148" width="112" height="40" rx="8" fill="#7f7f7f" fill-opacity="0.10" stroke="currentColor" stroke-opacity="0.55"/>
  </g>
  <g fill="none" stroke="currentColor" stroke-width="1.6">
    <path d="M128 141 L 166 141" marker-end="url(#l05-arrow)"/>
    <path d="M404 116 L 446 116" marker-end="url(#l05-arrow)"/>
    <path d="M404 168 L 446 168" marker-end="url(#l05-arrow)"/>
  </g>
  <g fill="none" stroke="#e0930f" stroke-width="1.5" stroke-dasharray="5 4">
    <path d="M452 130 L 410 130" marker-end="url(#l05-arrow)"/>
    <path d="M452 182 L 410 182" marker-end="url(#l05-arrow)"/>
  </g>

  <g fill="none" stroke-linejoin="round" stroke-width="2">
    <rect x="36" y="352" width="92" height="46" rx="9" fill="#3553ff" fill-opacity="0.13" stroke="#3553ff"/>
  </g>
  <g fill="none" stroke-linejoin="round" stroke-width="1.6" stroke="#0fa07f">
    <rect x="176" y="330" width="34" height="42" rx="4" fill="#0fa07f" fill-opacity="0.16"/>
    <rect x="212" y="330" width="34" height="42" rx="4" fill="#0fa07f" fill-opacity="0.16"/>
    <rect x="248" y="330" width="34" height="42" rx="4" fill="#0fa07f" fill-opacity="0.16"/>
    <rect x="284" y="330" width="34" height="42" rx="4" fill="#0fa07f" fill-opacity="0.16"/>
    <rect x="320" y="330" width="34" height="42" rx="4" fill="#0fa07f" fill-opacity="0.16"/>
    <rect x="356" y="330" width="34" height="42" rx="4" fill="#0fa07f" fill-opacity="0.16"/>
    <rect x="392" y="330" width="34" height="42" rx="4" fill="#0fa07f" fill-opacity="0.16"/>
    <rect x="428" y="330" width="34" height="42" rx="4" fill="#0fa07f" fill-opacity="0.16"/>
    <rect x="464" y="330" width="34" height="42" rx="4" fill="#0fa07f" fill-opacity="0.16"/>
    <rect x="500" y="330" width="34" height="42" rx="4" fill="#0fa07f" fill-opacity="0.16"/>
    <rect x="536" y="330" width="34" height="42" rx="4" fill="#0fa07f" fill-opacity="0.16"/>
    <rect x="572" y="330" width="34" height="42" rx="4" fill="#0fa07f" fill-opacity="0.16"/>
  </g>
  <g fill="none" stroke="currentColor" stroke-width="1.6">
    <path d="M128 353 L 170 340" marker-end="url(#l05-arrow)"/>
    <path d="M622 351 L 656 351" marker-end="url(#l05-arrow)"/>
  </g>
  <g fill="none" stroke-width="1.8">
    <path d="M229 400 L 229 378" stroke="#3553ff" marker-end="url(#l05-arrow)"/>
    <path d="M373 400 L 373 378" stroke="#7c5cff" marker-end="url(#l05-arrow)"/>
    <path d="M517 400 L 517 378" stroke="#e0930f" marker-end="url(#l05-arrow)"/>
  </g>
  <g fill="none" stroke-linejoin="round" stroke-width="2">
    <rect x="656" y="322" width="192" height="58" rx="9" fill="#0fa07f" fill-opacity="0.14" stroke="#0fa07f"/>
  </g>

  <g font-family="'JetBrains Mono', ui-monospace, monospace" fill="currentColor">
    <text x="34" y="66" font-size="12.5" font-weight="700" fill="#e0930f">QUEUE / TOPIC — ack DELETES the message</text>
    <text x="34" y="84" font-size="9.5" opacity="0.85">the broker's job is delivery; storage is temporary</text>
    <text x="82" y="139" font-size="9.5" font-weight="700" text-anchor="middle">producer</text>
    <text x="82" y="153" font-size="8" text-anchor="middle" opacity="0.8">publish</text>
    <text x="288" y="118" font-size="10.5" font-weight="700" text-anchor="middle">BROKER — delivery state</text>
    <text x="288" y="136" font-size="8.5" text-anchor="middle" opacity="0.9">per message x per consumer:</text>
    <text x="288" y="150" font-size="8.5" text-anchor="middle" opacity="0.9">delivered? acked? in-flight since?</text>
    <text x="288" y="164" font-size="8.5" text-anchor="middle" opacity="0.9">redelivery count? timeout when?</text>
    <text x="288" y="180" font-size="9" text-anchor="middle" font-weight="700" fill="#e0930f">2,000 msgs x 3 consumers = 6,000 entries</text>
    <text x="508" y="121" font-size="9" font-weight="700" text-anchor="middle">consumer A</text>
    <text x="508" y="173" font-size="9" font-weight="700" text-anchor="middle">consumer B</text>
    <text x="428" y="127" font-size="7.5" text-anchor="middle" fill="#e0930f" font-weight="700">ack</text>
    <text x="428" y="179" font-size="7.5" text-anchor="middle" fill="#e0930f" font-weight="700">ack</text>
    <text x="600" y="122" font-size="9.5" font-weight="700" fill="#e0930f">then: DELETED</text>
    <text x="600" y="138" font-size="8.5" opacity="0.9">no replay. no backfill.</text>
    <text x="600" y="152" font-size="8.5" opacity="0.9">no audit. a new consumer</text>
    <text x="600" y="166" font-size="8.5" opacity="0.9">starts from empty.</text>
    <text x="600" y="184" font-size="8.5" opacity="0.9">slowest consumer gates</text>
    <text x="600" y="198" font-size="8.5" opacity="0.9">everyone's retention.</text>

    <text x="34" y="276" font-size="12.5" font-weight="700" fill="#0fa07f">THE LOG — ack COMMITS A POSITION; the record stays</text>
    <text x="34" y="294" font-size="9.5" opacity="0.85">retention is decoupled from acknowledgement — the defining property</text>
    <text x="82" y="373" font-size="9.5" font-weight="700" text-anchor="middle">producer</text>
    <text x="82" y="387" font-size="8" text-anchor="middle" opacity="0.8">append only</text>
    <text x="193" y="322" font-size="8" text-anchor="middle" opacity="0.75">0</text>
    <text x="373" y="322" font-size="8" text-anchor="middle" opacity="0.75">offset 5</text>
    <text x="589" y="322" font-size="8" text-anchor="middle" opacity="0.75">tail</text>
    <text x="229" y="416" font-size="9" font-weight="700" text-anchor="middle" fill="#3553ff">nightly-batch</text>
    <text x="229" y="430" font-size="8" text-anchor="middle" opacity="0.85">offset 1</text>
    <text x="373" y="416" font-size="9" font-weight="700" text-anchor="middle" fill="#7c5cff">search-indexer</text>
    <text x="373" y="430" font-size="8" text-anchor="middle" opacity="0.85">offset 5</text>
    <text x="517" y="416" font-size="9" font-weight="700" text-anchor="middle" fill="#e0930f">fraud-realtime</text>
    <text x="517" y="430" font-size="8" text-anchor="middle" opacity="0.85">offset 9</text>
    <text x="752" y="342" font-size="10" font-weight="700" text-anchor="middle">BROKER STATE</text>
    <text x="752" y="360" font-size="9.5" text-anchor="middle" font-weight="700" fill="#0fa07f">3 integers. Total.</text>
    <text x="752" y="374" font-size="8" text-anchor="middle" opacity="0.85">O(groups), not O(msgs x groups)</text>
    <text x="440" y="458" font-size="10" text-anchor="middle" opacity="0.95">Three groups read the same 215,042 bytes. The fan-out model of lesson 04 would store 3 x 215,042 = 645,126 bytes.</text>
    <text x="440" y="476" font-size="10" text-anchor="middle" opacity="0.95">A fourth group costs the log 0 additional bytes — it is a new integer, not a new copy.</text>
    <text x="440" y="494" font-size="9.5" text-anchor="middle" opacity="0.8">And because the record is still there, any group can move its integer backwards. That is replay.</text>
  </g>
</svg>
```

Everything below falls out of that one change, with no extra machinery:

- **Replay.** Set the integer lower. The records are still there, so they come back — same order, same offsets.
- **Independent readers at zero extra storage.** Each group is an integer over one shared copy. Adding a reader costs an integer.
- **Different speeds, no coupling.** A group 900,000 records behind does not slow a group at the tail; neither one's progress is visible to the other.
- **A far simpler broker.** No delivery tracking, no visibility timeouts, no in-flight tables, no per-message locks — the hard, stateful, contended part of a queue broker simply does not exist. What remains is roughly a file supporting appends and positional reads, which is why log-shaped systems tend to scale further.
- **Time travel.** "What did we receive at 14:32?" becomes a seek.

### Reading is not consuming

This is the sentence to memorise, because it is the property everything else derives from: **in a log, reading does not remove.** Whether a record is still available has nothing to do with whether anyone has read it. It has to do with the **retention policy** — a rule about age, or size, or keys — that is configured on the log and applies to every reader identically.

A record no one has read can be deleted (it aged out). A record everybody has read stays (it is inside the window). The broker never asks "has everyone finished with this?" — the question the queue model must ask constantly, and the source of most of its complexity.

This is also the first honest cost. Delete-on-ack is a *storage optimisation*: it keeps the broker small. Giving it up means holding data a queue would have freed. You are buying replay with disk, and your retention policy sets the exchange rate.

### Committed offsets, and where at-least-once comes back

A consumer's in-memory position is useless across a restart, so the position must be **committed** — written somewhere durable. Where it goes is a design decision with three common answers:

1. **In the broker**, in a dedicated store keyed by (group, log). This is the usual choice, and it means a restarting consumer can ask "where was I?" without any local state.
2. **In the consumer's own datastore**, in the *same transaction* as the work. This is strictly stronger and is the key to effectively-once processing — [Lesson 6](../06-delivery-semantics-and-idempotency/) covers why.
3. **In an external coordinator** — a file, a key-value store, a table.

Now the trap. When you commit, relative to when you process, reproduces exactly the delivery-semantics choice from Lesson 3 — the same fork in the road, wearing different clothes:

```text
read record 42 -> COMMIT offset 43 -> process record 42
                                       ^ crash here: record 42 is never processed
                                         and never redelivered.   AT-MOST-ONCE

read record 42 -> process record 42 -> COMMIT offset 43
                                       ^ crash here: record 42 is processed, but the
                                         commit never landed, so on restart the
                                         consumer resumes at 42 and processes it
                                         again.                   AT-LEAST-ONCE
```

Commit-before-process loses records on a crash. Commit-after-process duplicates them. **There is no third option that a single non-transactional commit can give you**, which is the same conclusion Lesson 3 reached about acks — and it is not a coincidence, because a commit *is* an ack, batched. The log changed the mechanism and left the fundamental trade-off exactly where it was. Note also that a log makes the duplicate window *wider*: consumers commit every N records or every few seconds rather than per message, so a crash replays the whole uncommitted batch, not one message. [Lesson 6](../06-delivery-semantics-and-idempotency/) is where this gets resolved properly, with idempotent consumers and transactional commits.

### Why appending is fast: sequential I/O

An append-only design is not just conceptually clean, it is the fastest thing you can ask a storage device to do, for three reasons.

**Sequential writes.** Writing to the end of a file means every write lands immediately after the last one. On a spinning disk this is the difference between the head staying put and seeking across the platter — a factor of hundreds. On an SSD it is smaller but still real: sequential writes align with the flash translation layer's erase blocks and reduce write amplification, while scattered small writes multiply it. The program below measures the *physical* argument deterministically: writing 4 MiB sequentially moves the write position **4.0 MiB** in total; writing the identical 4 MiB in random 512-byte blocks moves it **10,964.5 MiB** — a **2,741×** difference in distance travelled, with 8,191 discontiguous writes instead of 0.

**The page cache.** Appends land in the operating system's page cache and are written back in large contiguous batches. Recent reads hit that same cache, so a consumer at the tail is usually served from RAM without touching disk — which is why a log serves many tail consumers cheaply, and why the broker needs no big application-level cache of its own.

**Zero-copy reads.** A log serves *byte ranges of a file* to a socket. Because it need not interpret records to send them, the kernel can move data straight from the page cache to the network interface with `sendfile(2)`, skipping the copies into and out of user space. A queue broker that tracks per-message state generally cannot — it must touch each message to update its bookkeeping. This is a design consequence, not a tuning flag: *the log is fast partly because it refuses to know anything about the messages it stores.*

The Kafka paper (Kreps, Narkhede & Rao, "Kafka: a Distributed Messaging System for Log Processing", NetDB 2011) is the canonical write-up of this reasoning.

### Segments: the unit of deletion

A log is conceptually one infinite file. It cannot be one *actual* file, because you can never delete anything from the front of a file without rewriting it. So the log is split into **segments**: fixed-size files, each named for the offset of its first record.

```text
00000000000000000000.log   base offset     0   309 records   32,674 B
00000000000000000309.log   base offset   309   307 records   32,704 B
00000000000000000616.log   base offset   616   304 records   32,740 B
...
00000000000000001828.log   base offset 1,828   172 records   18,811 B   <- active
```

Only the last segment — the **active segment** — is open for writing. When it exceeds a size threshold (or an age threshold), it is closed and a new one is opened at the next offset.

The payoff is that **retention operates on whole segments**. Expiring old data is `unlink()` on a closed file: constant time, no rewriting, no fragmentation, no interference with the append path. This is also why retention is approximate — a log set to keep 7 days keeps 7 days *plus whatever remains in a segment whose newest record is still inside the window*, since a segment can only be deleted as a unit. The active segment is never deleted, which stops a low-traffic log from expiring itself into nothing.

### The sparse offset index

Positional reads create a problem: given "start at offset 1,337", how do you find the bytes? Scanning from the start is O(n) and unacceptable.

The answer is an **offset index**: a map from offset to byte position within a segment. A dense index — one entry per record — would be fast but cost memory proportional to record count, defeating the purpose of a cheap broker. So it is **sparse**: one entry every N records (or N bytes). To find offset 1,337, binary-search for the largest indexed offset at or below it, seek there, scan forward a handful of records.

Two lookups combine: choosing the segment (a binary search over base offsets, which are the filenames) and then the sparse index within it. Measured below, at one entry per 8 records: an average of **3.48 records deserialized per seek** across all 2,000 offsets versus **999.5** for a naive scan — **287× fewer records touched** — for an index costing **4,048 bytes, 1.88% of the log**. That is the argument for sparseness: nearly all the benefit of a dense index at a fraction of the memory, with a bounded, tunable amount of scanning as the price.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 470" width="100%" style="max-width:840px" role="img" aria-label="The physical layout of a log: seven segment files with base offsets in their filenames, a record framed with a length prefix and a CRC, and a sparse index with one entry per eight records costing 1.88 percent of the log. Retention deletes whole segment files with unlink, moving the earliest readable offset from 0 to 1224, which puts a consumer committed at offset 300 out of range.">
  <defs>
    <marker id="l05-arrow2" markerWidth="10" markerHeight="10" refX="6" refY="3" orient="auto">
      <path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/>
    </marker>
  </defs>
  <text x="440" y="24" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">One log, seven files — and why deletion is an unlink</text>

  <g fill="none" stroke-linejoin="round" stroke-width="2">
    <rect x="24" y="70" width="118" height="56" rx="8" fill="#e0930f" fill-opacity="0.13" stroke="#e0930f" stroke-dasharray="6 4"/>
    <rect x="148" y="70" width="118" height="56" rx="8" fill="#e0930f" fill-opacity="0.13" stroke="#e0930f" stroke-dasharray="6 4"/>
    <rect x="272" y="70" width="118" height="56" rx="8" fill="#e0930f" fill-opacity="0.13" stroke="#e0930f" stroke-dasharray="6 4"/>
    <rect x="396" y="70" width="118" height="56" rx="8" fill="#e0930f" fill-opacity="0.13" stroke="#e0930f" stroke-dasharray="6 4"/>
    <rect x="520" y="70" width="118" height="56" rx="8" fill="#0fa07f" fill-opacity="0.14" stroke="#0fa07f"/>
    <rect x="644" y="70" width="118" height="56" rx="8" fill="#0fa07f" fill-opacity="0.14" stroke="#0fa07f"/>
    <rect x="768" y="70" width="88" height="56" rx="8" fill="#3553ff" fill-opacity="0.15" stroke="#3553ff"/>
  </g>

  <g fill="none" stroke-linejoin="round" stroke-width="1.8">
    <rect x="140" y="212" width="86" height="40" rx="5" fill="#7c5cff" fill-opacity="0.16" stroke="#7c5cff"/>
    <rect x="226" y="212" width="86" height="40" rx="5" fill="#7c5cff" fill-opacity="0.16" stroke="#7c5cff"/>
    <rect x="312" y="212" width="128" height="40" rx="5" fill="#7f7f7f" fill-opacity="0.10" stroke="currentColor" stroke-opacity="0.55"/>
    <rect x="440" y="212" width="104" height="40" rx="5" fill="#7f7f7f" fill-opacity="0.10" stroke="currentColor" stroke-opacity="0.55"/>
    <rect x="544" y="212" width="176" height="40" rx="5" fill="#0fa07f" fill-opacity="0.13" stroke="#0fa07f"/>
  </g>

  <g fill="none" stroke-linejoin="round" stroke-width="2">
    <rect x="24" y="322" width="404" height="118" rx="11" fill="#3553ff" fill-opacity="0.08" stroke="#3553ff"/>
    <rect x="452" y="322" width="404" height="118" rx="11" fill="#e0930f" fill-opacity="0.09" stroke="#e0930f"/>
  </g>

  <g fill="none" stroke="currentColor" stroke-width="1.5">
    <path d="M60 132 L 60 160" marker-end="url(#l05-arrow2)"/>
    <path d="M182 198 L 182 190"/>
  </g>
  <g fill="none" stroke="#7c5cff" stroke-width="1.5">
    <path d="M300 148 L 200 206" marker-end="url(#l05-arrow2)"/>
  </g>

  <g font-family="'JetBrains Mono', ui-monospace, monospace" fill="currentColor">
    <text x="24" y="54" font-size="11.5" font-weight="700">SEGMENTS — the filename IS the base offset, so finding one is a binary search</text>
    <text x="83" y="90" font-size="8.5" text-anchor="middle" font-weight="700">...0000.log</text>
    <text x="83" y="104" font-size="8" text-anchor="middle" opacity="0.85">309 rec</text>
    <text x="83" y="117" font-size="8" text-anchor="middle" opacity="0.85">32,674 B</text>
    <text x="207" y="90" font-size="8.5" text-anchor="middle" font-weight="700">...0309.log</text>
    <text x="207" y="104" font-size="8" text-anchor="middle" opacity="0.85">307 rec</text>
    <text x="207" y="117" font-size="8" text-anchor="middle" opacity="0.85">32,704 B</text>
    <text x="331" y="90" font-size="8.5" text-anchor="middle" font-weight="700">...0616.log</text>
    <text x="331" y="104" font-size="8" text-anchor="middle" opacity="0.85">304 rec</text>
    <text x="331" y="117" font-size="8" text-anchor="middle" opacity="0.85">32,740 B</text>
    <text x="455" y="90" font-size="8.5" text-anchor="middle" font-weight="700">...0920.log</text>
    <text x="455" y="104" font-size="8" text-anchor="middle" opacity="0.85">304 rec</text>
    <text x="455" y="117" font-size="8" text-anchor="middle" opacity="0.85">32,763 B</text>
    <text x="579" y="90" font-size="8.5" text-anchor="middle" font-weight="700">...1224.log</text>
    <text x="579" y="104" font-size="8" text-anchor="middle" opacity="0.85">304 rec</text>
    <text x="703" y="90" font-size="8.5" text-anchor="middle" font-weight="700">...1528.log</text>
    <text x="703" y="104" font-size="8" text-anchor="middle" opacity="0.85">300 rec</text>
    <text x="812" y="90" font-size="8.5" text-anchor="middle" font-weight="700">...1828.log</text>
    <text x="812" y="104" font-size="8" text-anchor="middle" opacity="0.85">ACTIVE</text>
    <text x="812" y="117" font-size="8" text-anchor="middle" opacity="0.85">appends here</text>
    <text x="24" y="150" font-size="9" opacity="0.9">closed, read-only, deletable</text>
    <text x="24" y="178" font-size="9" font-weight="700" fill="#e0930f">orange = expired by retention, deleted with unlink()</text>

    <text x="24" y="200" font-size="11.5" font-weight="700">ONE RECORD — the frame is 27 B of overhead on an average 107.5 B record</text>
    <text x="183" y="237" font-size="8.5" text-anchor="middle" font-weight="700">4B length</text>
    <text x="269" y="237" font-size="8.5" text-anchor="middle" font-weight="700">4B crc32</text>
    <text x="376" y="231" font-size="8.5" text-anchor="middle">8B offset · 8B ts</text>
    <text x="376" y="245" font-size="8.5" text-anchor="middle">1B flags · 2B klen</text>
    <text x="492" y="237" font-size="8.5" text-anchor="middle">key</text>
    <text x="632" y="237" font-size="8.5" text-anchor="middle">value  (empty + tombstone flag = delete)</text>
    <text x="140" y="272" font-size="8.5" opacity="0.9">length prefix: the reader knows where the next record starts, with no delimiter to escape</text>
    <text x="140" y="288" font-size="8.5" opacity="0.9">crc32: a half-written or bit-rotted record is detected, not believed — this is how a torn tail is found</text>
    <text x="300" y="304" font-size="9" font-weight="700" fill="#7c5cff">sparse index: 253 entries, one per 8 records, 4,048 B = 1.88% of the log</text>

    <text x="42" y="346" font-size="11" font-weight="700" fill="#3553ff">SEEKING — segment search + sparse index</text>
    <text x="42" y="368" font-size="9" opacity="0.92">read_from(1,337): binary-search filenames -> ...1224.log</text>
    <text x="42" y="384" font-size="9" opacity="0.92">binary-search its index -> nearest entry at 1,336</text>
    <text x="42" y="400" font-size="9" opacity="0.92">seek, then scan forward 1 record</text>
    <text x="42" y="422" font-size="9.5" font-weight="700" fill="#3553ff">3.48 records scanned on average vs 999.5 naive — 287x</text>

    <text x="470" y="346" font-size="11" font-weight="700" fill="#e0930f">RETENTION — deletion is per segment, never per record</text>
    <text x="470" y="368" font-size="9" opacity="0.92">retention.ms = 7d  -> 1 segment, 309 records, 32,674 B</text>
    <text x="470" y="384" font-size="9" opacity="0.92">retention.bytes = 96 KiB -> 3 more segments</text>
    <text x="470" y="400" font-size="9" opacity="0.92">earliest readable offset: 0 -> 1,224</text>
    <text x="470" y="422" font-size="9.5" font-weight="700" fill="#e0930f">a consumer committed at 300 now gets OFFSET OUT OF RANGE</text>
  </g>
</svg>
```

### Retention: time, size, money, and law

Retention is the policy that decides how long records survive. There are three kinds, and the first two are the familiar ones.

**By time.** "Keep 7 days." A segment becomes eligible once its newest record is older than the window. This policy answers a *question*: how far back might I need to replay? If your worst-case bug-detection-and-fix loop is three days, three-day retention gives you no margin at all.

**By size.** "Keep at most 500 GB." Oldest segments go until the log fits. This policy encodes a *budget*, and it is what stops a runaway producer from filling the disk and taking the broker down — worth setting even when time is your real policy. Where both are set, whichever triggers first wins, and that is usually size at exactly the moment you least want it to be.

The measured run applies both: 7-day retention on a 10-day log deletes 1 segment (309 records, 32,674 B), moving the earliest readable offset to 309; a 96 KiB size cap deletes 3 more and moves it to 1,224.

That moving offset is the failure you will meet at 3 a.m. **A consumer that falls further behind than the retention window loses data.** A group committed at offset 300 comes back to find 300 no longer exists:

```text
OffsetOutOfRange: offset 300 is below the earliest available offset 1224
```

There is no good answer at that point, only two bad ones — reset to earliest and reprocess a large backlog (duplicates, load, possibly re-sent emails), or reset to latest and accept a permanent hole. The run recovers 776 of 2,000 records that way; the other 1,224 are gone. The real fix happens long before: **alert on consumer lag measured against the retention window, not against zero.** A consumer 4 hours behind on a 7-day log is fine; one 6 days behind is 24 hours from data loss and nobody has noticed. [Lesson 9](../09-backpressure-lag-and-flow-control/) makes lag a first-class metric.

Retention is also a **cost and compliance decision at least as much as a technical one**. Disk is the cheap part; what usually decides the number is a lawyer. "Keep all customer events for 7 years" and "delete all personal data after 90 days" are both retention policies, from different departments, pointing in opposite directions.

### Log compaction: keyed retention

There is a third retention policy, and it is the interesting one. **Compaction** keeps, for each distinct **key**, only the most recent record — and discards every earlier record for that key.

The consequences are large. A time-retained log is a *history*: every state change in the window, in order. A **compacted log is a snapshot of current state**: one record per key holding its latest value, replayable from the beginning to rebuild that state in full. It converges to a size proportional to the **number of distinct keys**, not the number of events — 500 million updates across 2 million customers compacts toward 2 million records and stays there.

Compaction requires two things:

**Keys.** Every record must carry a key meaning "the identity of the thing this record describes" — `customer_id`, `order_id`, `device_id`. Compacting unkeyed records is meaningless, which makes keying a design-time schema decision, not a flag you flip later.

**Tombstones.** If the rule is "keep the latest value per key", how do you delete a key? You append a record with that key and a **null value** — a **tombstone**. Compaction reads it as "this key is deleted", removes every earlier record for the key, and after a grace period removes the tombstone too. The grace period exists because a lagging consumer must still see the tombstone to learn about the deletion and apply it to its own copy; if tombstones vanish too fast, a slow consumer keeps a deleted record forever.

The run compacts 2,000 order events across 400 keys, 57 of the records being tombstones:

```text
full log:       2,000 records   215,042 B  7 segments
compacted log:    387 records    42,623 B  2 segments
reduction 5.17x by count, 5.05x by bytes
```

Why 387 and not 400: 13 keys ended with a tombstone as their most recent record, so they are gone entirely. And note that **compaction preserves offsets** — the compacted log runs from offset 7 to 1,999 but holds only 387 records, full of gaps. That is essential: an offset must mean the same thing before and after compaction, or a background process would invalidate every committed offset in the system. A consumer asking for offset 500 gets the next record at or after 500, whatever that is.

### The duality: a log is a table, and a table is a log

Take a log of keyed records and apply them in order to a dictionary — set the key on a value, remove it on a tombstone. What you get is a **table**: current state, one row per key. Reverse it: record every change to a table as it happens and you get a **log**. Two representations of the same information. This is **stream-table duality**: a log is a table's changelog, and a table is a log's fold.

The program demonstrates it as an equality rather than an assertion — folding the full 2,000-record log and the 387-record compacted log and comparing:

```text
fold(full log)      -> 387 keys
fold(compacted log) -> 387 keys
the two tables are identical: True
```

Same table, from 2,000 records or from 387. That is what "compaction is lossless with respect to current state" means.

Now run the same fold over the age-and-size-retained copy of that log — the 776 records that survived the retention policies above — and the contrast lands:

```text
fold(compacted log)            -> 387 keys   from 387 records
fold(age+size-retained log)    -> 335 keys   from 776 records   <- 52 keys have no surviving record
```

A history window is not a snapshot. Deleting old segments deletes whole *keys* — any order whose last update fell outside the window simply has no record left, so a consumer replaying from the earliest available offset rebuilds an incomplete table. Only compaction guarantees that every key is still represented. This is the single most useful distinction in the lesson, and it is why the two policies are not interchangeable:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 468" width="100%" style="max-width:840px" role="img" aria-label="One 2000-record log under two retention policies. Time retention keeps a recent suffix of 776 records which folds to only 335 keys, losing 52 keys entirely, and preserves ordered history. Compaction keeps the latest record per key, 387 records, which folds to the full 387-key table identical to folding the original log, but destroys the history of how each key got there.">
  <defs>
    <marker id="l05-arrow3" markerWidth="10" markerHeight="10" refX="6" refY="3" orient="auto">
      <path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/>
    </marker>
  </defs>
  <text x="440" y="24" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">One log, two retention policies — a history or a table, not both</text>

  <g fill="none" stroke-linejoin="round" stroke-width="2">
    <rect x="252" y="44" width="376" height="56" rx="10" fill="#3553ff" fill-opacity="0.12" stroke="#3553ff"/>
    <rect x="24" y="164" width="404" height="192" rx="12" fill="#e0930f" fill-opacity="0.08" stroke="#e0930f"/>
    <rect x="452" y="164" width="404" height="192" rx="12" fill="#0fa07f" fill-opacity="0.09" stroke="#0fa07f"/>
  </g>

  <g fill="none" stroke="currentColor" stroke-width="1.7">
    <path d="M380 100 L 226 156" marker-end="url(#l05-arrow3)"/>
    <path d="M500 100 L 654 156" marker-end="url(#l05-arrow3)"/>
  </g>

  <g fill="none" stroke-width="1.6" stroke="#e0930f">
    <rect x="48" y="212" width="26" height="30" rx="3" fill="#e0930f" fill-opacity="0.05" stroke-dasharray="4 3"/>
    <rect x="78" y="212" width="26" height="30" rx="3" fill="#e0930f" fill-opacity="0.05" stroke-dasharray="4 3"/>
    <rect x="108" y="212" width="26" height="30" rx="3" fill="#e0930f" fill-opacity="0.05" stroke-dasharray="4 3"/>
    <rect x="138" y="212" width="26" height="30" rx="3" fill="#e0930f" fill-opacity="0.05" stroke-dasharray="4 3"/>
    <rect x="168" y="212" width="26" height="30" rx="3" fill="#e0930f" fill-opacity="0.18"/>
    <rect x="198" y="212" width="26" height="30" rx="3" fill="#e0930f" fill-opacity="0.18"/>
    <rect x="228" y="212" width="26" height="30" rx="3" fill="#e0930f" fill-opacity="0.18"/>
    <rect x="258" y="212" width="26" height="30" rx="3" fill="#e0930f" fill-opacity="0.18"/>
    <rect x="288" y="212" width="26" height="30" rx="3" fill="#e0930f" fill-opacity="0.18"/>
    <rect x="318" y="212" width="26" height="30" rx="3" fill="#e0930f" fill-opacity="0.18"/>
    <rect x="348" y="212" width="26" height="30" rx="3" fill="#e0930f" fill-opacity="0.18"/>
    <rect x="378" y="212" width="26" height="30" rx="3" fill="#e0930f" fill-opacity="0.18"/>
  </g>
  <g fill="none" stroke-width="1.6" stroke="#0fa07f">
    <rect x="476" y="212" width="26" height="30" rx="3" fill="#0fa07f" fill-opacity="0.18"/>
    <rect x="512" y="212" width="26" height="30" rx="3" fill="#0fa07f" fill-opacity="0.05" stroke-dasharray="4 3"/>
    <rect x="548" y="212" width="26" height="30" rx="3" fill="#0fa07f" fill-opacity="0.18"/>
    <rect x="584" y="212" width="26" height="30" rx="3" fill="#0fa07f" fill-opacity="0.05" stroke-dasharray="4 3"/>
    <rect x="620" y="212" width="26" height="30" rx="3" fill="#0fa07f" fill-opacity="0.05" stroke-dasharray="4 3"/>
    <rect x="656" y="212" width="26" height="30" rx="3" fill="#0fa07f" fill-opacity="0.18"/>
    <rect x="692" y="212" width="26" height="30" rx="3" fill="#0fa07f" fill-opacity="0.05" stroke-dasharray="4 3"/>
    <rect x="728" y="212" width="26" height="30" rx="3" fill="#0fa07f" fill-opacity="0.18"/>
    <rect x="764" y="212" width="26" height="30" rx="3" fill="#0fa07f" fill-opacity="0.18"/>
    <rect x="800" y="212" width="26" height="30" rx="3" fill="#0fa07f" fill-opacity="0.05" stroke-dasharray="4 3"/>
  </g>

  <g font-family="'JetBrains Mono', ui-monospace, monospace" fill="currentColor">
    <text x="440" y="68" font-size="11.5" font-weight="700" text-anchor="middle">THE LOG — 2,000 records · 400 keys · 215,042 B</text>
    <text x="440" y="87" font-size="9" text-anchor="middle" opacity="0.9">every state change, in order, keyed by order id</text>

    <text x="42" y="192" font-size="11.5" font-weight="700" fill="#e0930f">AGE / SIZE RETENTION — keep a recent window</text>
    <text x="42" y="266" font-size="9" opacity="0.9">delete whole segments by age, then by size;</text>
    <text x="42" y="282" font-size="9" opacity="0.9">what survives is a SUFFIX: 776 records</text>
    <text x="42" y="304" font-size="10" font-weight="700">fold() -&gt; 335 keys</text>
    <text x="42" y="322" font-size="9.5" font-weight="700" fill="#e0930f">52 keys have NO surviving record</text>
    <text x="42" y="342" font-size="9" opacity="0.9">history: intact.   state: incomplete.</text>
    <text x="216" y="204" font-size="8" text-anchor="middle" opacity="0.75">deleted                    kept</text>

    <text x="470" y="192" font-size="11.5" font-weight="700" fill="#0fa07f">COMPACTION — keep the latest per key</text>
    <text x="470" y="266" font-size="9" opacity="0.9">drop superseded records and tombstoned keys;</text>
    <text x="470" y="282" font-size="9" opacity="0.9">what survives is a SNAPSHOT: 387 records</text>
    <text x="470" y="304" font-size="10" font-weight="700">fold() -&gt; 387 keys — identical to folding the original</text>
    <text x="470" y="322" font-size="9.5" font-weight="700" fill="#0fa07f">every key still represented</text>
    <text x="470" y="342" font-size="9" opacity="0.9">state: complete.   history: destroyed.</text>
    <text x="650" y="204" font-size="8" text-anchor="middle" opacity="0.75">superseded records dropped, offsets kept</text>

    <text x="440" y="386" font-size="10.5" text-anchor="middle" opacity="0.95">Compaction is lossless for STATE and lossy for HISTORY. Time retention is lossy for both — it just bounds the loss by age.</text>
    <text x="440" y="406" font-size="10" text-anchor="middle" opacity="0.9">Pick by the question the consumer asks: "what happened?" needs the window; "what is it now?" needs compaction.</text>
    <text x="440" y="428" font-size="10" text-anchor="middle" opacity="0.8">If two consumers ask different questions, that is two topics — not one topic with a compromise policy.</text>
    <text x="440" y="450" font-size="9.5" text-anchor="middle" opacity="0.75">Compaction requires keyed records, and deletion requires tombstones retained long enough for slow consumers to see them.</text>
  </g>
</svg>
```

The two policies answer different questions:

| | Time-retained log | Compacted log |
|---|---|---|
| Contains | every event in the window | latest record per key |
| Size grows with | event rate × window | number of distinct keys |
| Answers | "what happened, in order?" | "what is the state now?" |
| Read from offset 0 gives | recent history | a full snapshot |
| Good for | audit, reprocessing, analytics | caches, config, lookup tables, state restore |
| Deletion | whole segments by age/size | tombstones |

The duality is the conceptual heart of two things you will meet later. **Event sourcing** ([Lesson 11](../11-event-driven-architecture/)) stores the log as the system of record and derives state by folding — so state is a *view*, not the truth. **Change data capture** ([Lesson 10](../10-dual-write-outbox-and-cdc/)) goes the other direction, turning a database's own replication log into an event stream. Both are the same equation read left-to-right or right-to-left.

### Consumer groups: one primitive, both shapes

The queue (work distribution) and the topic (broadcast) look like two different brokers. The log subsumes both with one mechanism: the **consumer group**.

- **Many groups over one log = fan-out.** Each group has its own offset and independently sees every record. That is [Lesson 4](../04-pub-sub-topics-and-fan-out/)'s topic, at one copy of the data instead of one per subscriber.
- **Many members within one group = work distribution.** The log's partitions are divided among the group's members, so each record is processed by exactly one member of that group. That is [Lesson 3](../03-build-a-message-queue/)'s queue.

Both shapes from one structure, chosen by how you arrange consumers rather than by which broker you deployed. That is the strongest argument for the log as *the* general primitive: queue and topic turn out to be configurations of it.

Partitioning belongs to [Lesson 7](../07-ordering-partition-keys-and-parallel-consumers/), but one consequence bounds everything above: **a single log is a single sequence, therefore a single ordering, therefore one writer's throughput and one reader's throughput per group.** You cannot parallelise consumption within a group beyond one member without splitting the log. That split is the partition, and it is where total ordering is traded for scale.

### What the log costs you

A log is not a free upgrade over a queue.

**Storage you did not need before.** You keep data justified only by "someone might need it later". At 200 GB/day and 7 days that is 1.4 TB, replicated, for a capability you might use twice a year. Sometimes obviously worth it; sometimes not, and a queue is the right answer.

**No per-message ack or redelivery.** A queue can redeliver message 7 because it tracks message 7. The log tracks a position. There is no way to say "I failed on record 512 alone, give it to someone else."

**Selective retry is genuinely hard.** A poison record at offset 512 that always throws is a wall: skipping it means committing 513, which asserts you processed 512 successfully. **Head-of-line blocking** is the log's characteristic failure — one bad record stalls a partition and lag climbs behind it while everything else is healthy. The standard answer is to catch the failure, publish the record to a separate **retry topic**, commit, and move on — restoring per-message handling by adding another log. That is [Lesson 8](../08-retries-backoff-and-dead-letter-queues/), which exists largely because of this limitation.

**Deleting one user's data is hard.** Under the GDPR (General Data Protection Regulation) a data subject may demand erasure (Article 17), and an append-only immutable log is close to the worst possible data structure for that. There are three real answers, and "delete the record" is not among them:

1. **Wait for retention.** If the log keeps 7 days, the data expires — legally adequate in many cases and operationally free, but useless for a long-retention or compacted log.
2. **Compaction plus tombstones.** If the log is keyed by user, write a tombstone and compaction eventually removes every record for that key. This is the intended mechanism, and it constrains key design: you can only erase along the key you compact by.
3. **Crypto-shredding.** Encrypt each user's personal fields with a per-user key held in a separate, mutable key store; on an erasure request, delete the key. The ciphertext stays in the log, permanently undecryptable, which regulators generally accept as erasure. This is the technique that scales — and it is a **design-time** decision you cannot retrofit.

If a log will carry personal data, decide how you will erase it *before* the first record is written. Phase 9's log pipeline reached the same conclusion about pseudonymising at the edge, from a completely different direction.

## Build It

[`code/append_only_log.py`](code/append_only_log.py) builds the whole primitive on the standard library: a segmented log with CRC-checked, length-prefixed records; a sparse offset index; consumer groups that own their positions; time, size and keyed retention; and crash recovery. It is seeded and runs on a virtual clock, so every number below reproduces exactly — with one labelled exception noted at the end.

The record framing is deliberately the same shape as Phase 3's WAL, because it is the same job: know where the next record starts, and know whether this one is intact.

```python
# frame:   [ 4B payload length ][ 4B crc32 of payload ][ payload ]
# payload: [ 8B offset ][ 8B timestamp_ms ][ 1B flags ][ 2B key length ][ key ][ value ]
FRAME = struct.Struct(">II")
HEAD = struct.Struct(">QQBH")
TOMBSTONE = 0x01


def encode(rec: Record) -> bytes:
    flags = TOMBSTONE if rec.value is None else 0
    payload = HEAD.pack(rec.offset, rec.timestamp_ms, flags, len(rec.key))
    payload += rec.key + (rec.value or b"")
    return FRAME.pack(len(payload), zlib.crc32(payload)) + payload
```

The length prefix means a reader never has to escape a delimiter. The CRC (Cyclic Redundancy Check) means a half-written record is *detected* rather than believed — which is the entire basis of recovery in section 8. A null value plus the tombstone flag is a delete.

Appending builds the sparse index as it goes, and rolls a segment when the active one is full:

```python
def _append_record(self, rec: Record) -> int:
    blob = encode(rec)
    seg = self.segments[-1]
    if seg.n_records and seg.size_bytes + len(blob) > self.segment_bytes:
        seg = self._roll(rec.offset)          # new file, named for this offset
    pos = seg.size_bytes
    self._fh.write(blob)
    if seg.n_records % self.index_interval == 0:
        seg.index_offsets.append(rec.offset)  # one entry per N records
        seg.index_positions.append(pos)
    ...
```

Seeking is the two-level lookup — binary search the segment base offsets, then binary search that segment's sparse index — and the method reports what it cost, so the index can be judged rather than assumed:

```python
bases = [s.base_offset for s in self.segments]
si = max(0, bisect_right(bases, offset) - 1)
seg = self.segments[si]
i = bisect_right(seg.index_offsets, offset) - 1      # nearest index entry at or before
start_pos = seg.index_positions[i] if i >= 0 else 0
```

Compaction keeps the last record per key, drops keys whose last record is a tombstone, and preserves the original offsets:

```python
latest: dict[bytes, Record] = {}
for rec in self.scan_all():
    latest[rec.key] = rec                            # last write wins
keep = sorted((r for r in latest.values() if r.value is not None), key=lambda r: r.offset)
```

And the duality is six lines, which is the point — folding a stream into a table is not a framework feature, it is a `for` loop:

```python
def fold(log: Log) -> dict[bytes, bytes]:
    table: dict[bytes, bytes] = {}
    for rec in log.scan_all():
        if rec.value is None:
            table.pop(rec.key, None)                  # tombstone = delete
        else:
            table[rec.key] = rec.value
    return table
```

One more detail worth pointing at: committed offsets are stored in **their own compacted keyed log**, keyed by group name. The log's bookkeeping is itself a log — the same self-referential trick real brokers use.

Run it:

```console
$ python append_only_log.py
== 1. THE SEGMENTED APPEND-ONLY LOG ==
  appended 2,000 records spanning 10.0 days of virtual time
  offsets 0 .. 1999   215,042 bytes   avg 107.5 B/record
  frame: 4B length + 4B crc32 + 19B header + key + value  (overhead 27 B/record)
  7 segment files, rolling at 32 KiB:
    00000000000000000000.log  base offset     0   309 records   32,674 B  index  39 entries
    00000000000000000309.log  base offset   309   307 records   32,704 B  index  39 entries
    00000000000000000616.log  base offset   616   304 records   32,740 B  index  38 entries
    00000000000000000920.log  base offset   920   304 records   32,763 B  index  38 entries
    ... 2 more ...
    00000000000000001828.log  base offset 1,828   172 records   18,811 B  index  22 entries   <- active, appends land here
  sparse index: 253 entries (one per 8 records), 4,048 B = 1.88% of the log

== 2. POSITIONAL READS: what the sparse index buys ==
  read_from(    0)  -> offset     0  key order-0173   deserialized 0 record(s) to get there, skipped 0
  read_from(  137)  -> offset   137  key order-0008   deserialized 1 record(s) to get there, skipped 136
  read_from(1,337)  -> offset 1,337  key order-0044   deserialized 1 record(s) to get there, skipped 1,336
  read_from(1,999)  -> offset 1,999  key order-0212   deserialized 3 record(s) to get there, skipped 1,996
  averaged over all 2,000 offsets: 3.48 records scanned per seek
  a full scan from the start would average 999.5  -> 287x fewer records touched
  cost of that: 4,048 B of index for 215,042 B of log

== 3. INDEPENDENT CONSUMERS: one log, three readers, one copy ==
  two groups, deliberately different speeds - the log does not care
  round  fraud-realtime (batch 256)      nightly-batch (batch 40)
      1  pos   256  lag 1,744              pos    40  lag 1,960
      2  pos   512  lag 1,488              pos    80  lag 1,920
      3  pos   768  lag 1,232              pos   120  lag 1,880
      4  pos 1,024  lag   976              pos   160  lag 1,840
  a new service launches and needs the whole history - it just starts at 0:
    fraud-realtime   consumed 2,000  committed 2,000  lag 0  digest cd0974f3
    nightly-batch    consumed 2,000  committed 2,000  lag 0  digest cd0974f3
    search-indexer   consumed 2,000  committed 2,000  lag 0  digest cd0974f3
  storage: the log holds 2,000 records ONCE = 215,042 B
  the fan-out model of lesson 04 gives each subscriber its own queue copy: 3 x 215,042 = 645,126 B
  storage amplification 3.00x   -- and a 4th subscriber costs the log 0 B and the fan-out 215,042 B more
  broker-side state per group: 1 integer.  Queue-model state for the same job: 1 record per message per consumer = 6,000 entries

== 4. REPLAY: the consumer owns the position, so rewinding is free ==
  reset fraud-realtime to offset 0 -> re-read 2,000 records, digest cd0974f3  identical: True
  reset to offset 1,500 -> first record back is offset 1,500, 500 records, digest ee955f20  matches the original slice: True
  nothing was re-sent by a producer and nothing was copied: replay is a seek

== 5. RETENTION: delete whole segments, never single records ==
  policy: retention.ms = 7 days   (log spans 10.0 days)
  deleted 1 segment(s), 309 records, 32,674 B
  earliest readable offset moved 0 -> 309   log 215,042 B -> 182,368 B   (7 -> 6 segments)
  then retention.bytes = 96 KiB: deleted 3 more segments, earliest offset now 1,224, size 84,161 B
  a consumer that fell behind and committed offset 300 now polls:
    OffsetOutOfRange: offset 300 is below the earliest available offset 1224
    the operator's choice: reset to earliest (1,224, reprocess a backlog) or to latest (2,000, accept the data loss)
    reset-to-earliest recovers 776 records -- the 1,224 deleted ones are gone for good

== 6. COMPACTION: keyed retention turns a history into a table ==
  full log:       2,000 records   215,042 B  7 segments  (57 of them tombstones)
  compacted log:    387 records    42,623 B  2 segments  (400 keys were written; 13 ended deleted)
  reduction 5.17x by count, 5.05x by bytes
  offsets are PRESERVED, so the compacted log has gaps: first 7, last 1,999, but only 387 records in between
  fold(full log)      -> 387 keys
  fold(compacted log) -> 387 keys
  the two tables are identical: True   <- stream-table duality, demonstrated
  for contrast, the age+size-retained log from section 5 holds 776 records and folds to 335 keys, not 387 -- 52 keys have no surviving record
  a history window is not a snapshot: only compaction guarantees every key is still represented
  the offsets log is itself compacted: 11 appends for 3 groups -> 3 records after compaction

== 7. WHY APPENDING IS FAST: sequential vs random writes ==
  same work both ways: 8,192 writes of 512 B = 4.0 MiB, one fsync at the end
  sequential  head travel       4.0 MiB   discontiguous writes      0
  random      head travel  10,964.5 MiB   discontiguous writes  8,191
  head travel ratio 2,741x   <- deterministic, and the reason the design is append-only
  wall clock on this machine: sequential 564 MiB/s, random 162 MiB/s, ratio 3.5x
  (the wall-clock line is the only non-deterministic output here; on a spinning disk it is far wider)

== 8. RECOVERY: reopen from disk, rebuild the index, truncate a torn tail ==
  simulated crash: appended 32 bytes of a 64-byte record to 00000000000000001828.log
  reopened: 7 segments scanned, 2,000 records, next offset 2,000
  torn tail detected and truncated: 32 bytes discarded
  sparse index rebuilt from the bytes: 253 entries  (matches the pre-crash 253: True)
  state after recovery is byte-identical to before: True
  the log accepts writes again at offset 2,000 -- no gap, no duplicate
```

Every claim in The Concept is now a measurement. Read them in order.

**The index is cheap and it works.** 253 entries covering 2,000 records cost 4,048 bytes — **1.88% of the log** — and reduce the average seek from touching 999.5 records to touching **3.48**, a **287×** reduction. Note the shape of the individual seeks: `read_from(1,337)` deserialized exactly **1** record and skipped **1,336**. The worst case in the sample was 3, which is the index interval's guarantee: you never scan more than N-1 records past an index entry. That bound is what makes sparseness safe — you are not gambling, you are choosing a constant.

**Three consumers, one copy — this is the punchline.** All three groups consumed all 2,000 records and produced the **identical digest `cd0974f3`**, an order-sensitive checksum of every `(offset, key, value)` they saw — so they demonstrably received the same stream in the same order. The log stored **215,042 bytes, once**. Lesson 4's fan-out model, where each subscriber gets its own queue copy, would have stored **645,126 bytes** — **3.00×** amplification for an identical outcome. The marginal cost tells it better than the total: a fourth subscriber costs the log **0 bytes** and the fan-out model another **215,042**. The log's cost is O(data); fan-out's is O(data × subscribers).

Broker state is the same insight from the other side: **3 integers** versus **6,000 entries** of per-message, per-consumer tracking. Not a constant-factor saving — a different complexity class, and the reason removing per-message state is what *makes* the log fast rather than an optimisation on top of it.

**Replay is a seek.** Resetting `fraud-realtime` to 0 re-read all 2,000 records and produced digest `cd0974f3`, byte-identical to the first pass. Resetting to 1,500 returned exactly the 500 records from there, matching the original slice. No producer re-sent anything; nothing was copied. The position is an integer the consumer owns, so rewinding is an assignment.

**Retention moves the floor, and a slow consumer falls off it.** 7-day retention on a 10-day log deleted one whole segment — 309 records, 32,674 bytes — by `unlink()`, moving the earliest offset to 309; a 96 KiB size cap then deleted three more, taking it to 1,224. The consumer committed at offset 300 came back to `OffsetOutOfRange`, and reset-to-earliest recovered **776 of 2,000 records**; the other 1,224 are gone. That is the "consumer fell off the log" incident in miniature, and it is entirely preventable by alarming on lag as a *fraction of the retention window*.

**Compaction turns 2,000 records into a 387-record table** — 5.17× fewer records, 5.05× fewer bytes, 7 segments down to 2, with 13 of the 400 keys removed entirely by tombstones. The compacted log runs from offset 7 to 1,999 holding only 387 records: **gaps everywhere, offsets preserved**, which is what keeps committed offsets valid across compaction. Then the equality that justifies the idea: both logs fold to **387 keys** and **the two tables are identical**, while the age-and-size-retained copy folds to only **335** — 52 keys with no surviving record. Compaction is lossless for state and lossy for history; time retention is lossy for both. The run proves all of it.

The self-referential detail deserves a second look: the offsets log took **11 appends for 3 groups** and compacts to **3 records**. Committed offsets are a keyed, latest-value-wins dataset — the textbook case for compaction — so the log stores its own bookkeeping in a compacted log.

**Sequential wins by a factor you can compute without a stopwatch.** The same 4 MiB written sequentially moves the write position **4.0 MiB** with **0** discontiguous writes; in random 512-byte blocks it moves **10,964.5 MiB** with **8,191** — a **2,741×** difference in distance travelled, deterministic and machine-independent. The wall-clock line beneath it (**564 MiB/s vs 162 MiB/s**, 3.5×) is the consequence on one modern SSD, and it is the program's only non-reproducible number. The gap between 2,741× and 3.5× is itself instructive: the OS and the SSD controller work hard to hide random-access cost and largely succeed at this size. On a spinning disk, or at a working set larger than RAM, the wall-clock ratio moves sharply toward the physical one.

**Recovery is why the CRC is there.** A 64-byte record was cut in half mid-write. On reopen the scanner hit a record whose declared length exceeded the bytes present, **truncated the 32-byte partial tail**, and rebuilt the sparse index from the surviving bytes — **253 entries, matching the pre-crash 253 exactly**. Folded state was identical to before the crash and the next append landed at offset 2,000: no gap, no duplicate. Same discipline as Phase 3's WAL — a record is real only if it is complete and its checksum verifies, and a torn tail is discarded rather than trusted.

## Use It

Everything above is the primitive. Every system below is an instance of it, and the point of this section is that once you see the primitive, the products are mostly vocabulary.

**Apache Kafka** is the system this design is usually named after. A topic is a log (partitioned — Lesson 7); records have offsets; consumer groups hold positions; retention is time or size or keyed compaction.

```text
# retention: history for 7 days, capped at 500 GB per partition
log.retention.hours=168
log.retention.bytes=536870912000
log.segment.bytes=1073741824      # 1 GiB segments -- the unit of deletion
log.index.interval.bytes=4096     # the sparse index: one entry per 4 KiB, not per record

# the same broker, keyed retention instead: a table, not a history
cleanup.policy=compact
delete.retention.ms=86400000      # keep tombstones 24h so slow consumers see the delete
```

```bash
# replay a consumer group from the beginning -- the group must be stopped first
kafka-consumer-groups --bootstrap-server localhost:9092 \
  --group search-indexer --topic orders --reset-offsets --to-earliest --execute
```

The self-referential detail is a good one: Kafka stores committed offsets in an internal topic, `__consumer_offsets`, which is itself **compacted** and keyed by (group, topic, partition) — exactly the pattern the program above implements. The log's bookkeeping is a log.

**AWS Kinesis Data Streams** is the same primitive with different nouns. A stream has **shards** (partitions); a record's position is a **sequence number** rather than an integer offset; you obtain a **shard iterator** (`TRIM_HORIZON` for earliest, `LATEST` for the tail, `AT_TIMESTAMP` for a point in time) and read forward. Retention is 24 hours by default and configurable up to 365 days. Positions are checkpointed by the client library into a DynamoDB table rather than by the broker.

```bash
aws kinesis get-shard-iterator --stream-name orders \
  --shard-id shardId-000000000000 --shard-iterator-type TRIM_HORIZON
```

**Apache Pulsar** separates the log's two jobs. Serving is done by brokers; storage is delegated to **Apache BookKeeper**, which spreads segments across a pool of storage nodes rather than binding a whole log to one broker's disk — so growing capacity does not require rebalancing whole topics. Consumer positions are **cursors**, and Pulsar keeps both a subscription model (queue-like acks, including individual-message acks) and a reader model (log-like positional reads), which makes it a useful illustration that the two shapes can coexist over one storage layer.

**Redis Streams** is the log at a small scale, and it is the fastest way to hold the primitive in your hands. Entry IDs are `<milliseconds>-<sequence>`, which are offsets that happen to encode time. It has both models: `XRANGE` for positional reads and `XREADGROUP` for consumer groups.

```text
XADD orders '*' order_id 1001 status paid       # append; returns the entry ID
XRANGE orders 1700000000000-0 +  COUNT 10       # positional read from a position
XLEN orders                                     # how long is the log
XADD orders MAXLEN '~' 1000000 '*' ...          # trim to ~1M entries: retention by size
XGROUP CREATE orders fraud-check 0              # a consumer group starting at offset 0
XREADGROUP GROUP fraud-check worker-1 COUNT 100 STREAMS orders '>'
```

`MAXLEN ~` is retention by size, and the `~` means "approximately" — Redis trims on whole macro-nodes rather than single entries, for exactly the reason a log trims whole segments.

**And the one that closes the loop: your database is already doing this.** PostgreSQL's WAL and MySQL's binary log (binlog) are append-only, ordered, replayable logs of every change — segmented into files, retained by size or time, positioned by LSN (Log Sequence Number) or binlog coordinates. Physical replication *is* a consumer reading a log from an offset. Once you see that, **change data capture** stops being a product category and becomes an obvious idea: attach a consumer to the database's existing replication log and publish what it says. That is [Lesson 10](../10-dual-write-outbox-and-cdc/), and it only makes sense because the WAL of Phase 3 and the message log of this lesson were the same structure all along.

## Think about it

1. Your team runs a topic with 7-day retention and four consumer groups. One group has been down for 8 days while a dependency was migrated. Walk through exactly what happens when it starts — what error, what the two reset options each cost in your specific system, and what metric and threshold would have paged someone on day 4 instead.

2. A colleague proposes compacting the `orders` topic to save disk, since "compaction is lossless — the fold proved it". The topic feeds a nightly revenue report that sums every order transition. Explain precisely what breaks, using the difference between a history and a table, and describe the two-topic arrangement that gives both teams what they need.

3. The program measured a 2,741× difference in head travel but only a 3.5× difference in wall-clock throughput. Explain what absorbed the other three orders of magnitude, and describe a workload where the wall-clock ratio would move much closer to the physical one.

4. You must replay 6 hours of `payments` into a fixed consumer, but the consumer sends a receipt email on every record. List everything you would check before resetting the offset, and describe an approach that gets the data reprocessed without sending 40,000 duplicate emails — without modifying the consumer's business logic.

5. A record at offset 512 throws on every attempt. You cannot skip it without committing 513, which asserts you processed it. Describe the head-of-line blocking that follows, what your lag graph looks like, and how a retry topic converts an unsolvable positional problem into a solvable per-message one. What did you give up in exchange?

6. A user requests erasure under GDPR Article 17. Their personal data is in a 90-day-retention `user-events` log and in a compacted `user-profiles` log keyed by `user_id`. Give your answer for each log separately, then explain what you would have had to build before the first record was written to make this a five-minute job for both.

## Key takeaways

- A queue and a topic both **delete a message when it is acknowledged**, welding together two unrelated ideas: *this reader is finished* and *no one will ever need this again*. The log separates them, and everything else in this lesson follows from that one change.
- An **append-only log** is an ordered, immutable, positional sequence — the same structure as Phase 3's **write-ahead log**, serving a different purpose. In both, the log is authoritative and everything derived from it is a rebuildable view; that equivalence is what makes event sourcing and CDC possible.
- **The consumer owns its position, not the broker.** Broker state drops from per-message-per-consumer to **one integer per group** — measured, **3 integers versus 6,000 entries** for 2,000 records and 3 groups. That is a different complexity class, and it is what buys replay, independent readers, and a far simpler broker.
- **Reading is not consuming.** Retention is decoupled from acknowledgement, so record lifetime is set by policy — time, size, or key — not by who has read it. Three groups read the same **215,042 bytes once**; the fan-out model of Lesson 4 would store **645,126 bytes (3.00×)**, and a fourth subscriber costs the log **0 extra bytes**.
- **Committing before processing is at-most-once; committing after is at-least-once** — the identical fork from Lesson 3, in a new guise, and made *wider* by batched commits. The log moved the mechanism and left the trade-off untouched. Lesson 6 resolves it.
- **Segments are the unit of retention**: the log is many files, deletion is `unlink()` on a closed one, and you never delete from the middle of a file. A **sparse offset index** (one entry per N records) made seeks touch **3.48 records on average instead of 999.5 — 287× fewer — for 1.88% of the log in memory**, with a hard bound of N-1 records scanned.
- **Append-only is fast because it is sequential**: the same 4 MiB moved the write position **4.0 MiB** sequentially versus **10,964.5 MiB** randomly (**2,741×**), and sequential writes also let the OS page cache and zero-copy `sendfile` do the rest of the work. The broker is fast partly because it refuses to interpret the messages it stores.
- **Compaction is keyed retention**: keep the latest record per key, delete via **tombstones**, preserve offsets (so the compacted log has gaps). Measured, **2,000 records became 387** — and folding either log produced the **identical 387-key table**. That equality is **stream-table duality**: a time-retained log is a *history*, a compacted log is a *table*, and a table is just a log folded.
- **Consumer groups subsume both earlier shapes**: many groups over one log is fan-out (Lesson 4), many members in one group is work distribution (Lesson 3). But a single log is a single ordering and therefore a single-consumer throughput ceiling per group — the reason partitions exist (Lesson 7).
- **The costs are real**: storage you did not previously need, no per-message ack or redelivery, head-of-line blocking on a poison record (Lesson 8's retry topic is the workaround), a consumer that falls behind retention losing data permanently, and GDPR erasure against an immutable log — answerable only by waiting out retention, compaction tombstones, or **crypto-shredding**, all of which must be designed in before the first record is written.

Next: [Delivery Semantics & Idempotent Consumers](../06-delivery-semantics-and-idempotency/) — at-most-once, at-least-once, and the "exactly-once" that is really at-least-once plus an idempotent consumer, which is the only way the commit-after-process choice above stops being a data-corruption bug.
