# Read Replicas & Replication Lag

> You add read replicas and the read problem disappears. What arrives instead is a class of bug that never reproduces: measured here, **61.65% of reads that follow a write return the old value** when the redirect takes 12 ms and the replicas are 12–33 ms behind, and a page that fans out to eight widgets shows a user **time running backwards in 3,857 of 4,000 sessions**. Then the primary dies mid-batch and **387 commits that returned 200 OK are simply gone, with zero errors returned to anyone.** This lesson is the consistency models taught through the bugs they produce, and the one fix — pinning reads to a log position — that removes the whole class for +0.30 ms.

**Type:** Build
**Languages:** Python
**Prerequisites:** [Stateless Services: Where the State Actually Went](../06-stateless-services/), [Write-Ahead Logging](../../03-relational-databases/13-write-ahead-logging/), [Transactions & ACID](../../03-relational-databases/11-transactions-and-acid/)
**Time:** ~80 minutes

## The Problem

Six weeks ago you added three read replicas. It worked exactly as advertised. Primary CPU went from 78% to 31%, the p99 on your read endpoints halved, the nightly analytics job stopped competing with checkout traffic, and the change was so uneventful that nobody has thought about the replicas since. They are green on the dashboard. Their lag metric reads 12 milliseconds.

Then the tickets start, and they do not look like they are related to each other.

**09:41 — "I changed my display name and it changed back."** A user edits their profile, hits save, and the page that loads immediately afterwards shows the old name. They change it again. It sticks. Support cannot reproduce it. You cannot reproduce it. The row in the database is correct, right now, in front of you.

**10:02 — "My comment disappeared."** Someone posts a comment, sees it appear, refreshes, and it is gone. They post it again. Now there are two. The duplicate is the only durable evidence that anything happened, and it makes the user look careless rather than the system.

**11:20 — "It says I haven't paid."** This one is not cosmetic. A payment succeeded, the charge is on the card, the receipt email went out — and the account page renders `UNPAID` for eight seconds. The customer opens a dispute with their bank in that window, because from where they are sitting they were charged for nothing.

Every one of these closes as **not reproducible**. Every one of them is "fixed" by refreshing. And every one of them is the same bug: a read went to a replica that had not yet applied the write the user had just made. Your replicas are around 12 to 33 milliseconds behind. **Your HTTP redirect after a POST takes 12 milliseconds.** Twelve is less than thirty-three, so the race is lost before it starts, and it is lost on a system where nothing is broken, nothing is overloaded, and nothing is red.

The Build It measures it precisely on healthy replicas with no incident in progress: at a 12 ms read delay, **61.65% of read-after-write requests return a value older than the one the user just saved.** Not 0.6%. Not a tail event. The majority. The reason it does not feel like the majority is that most reads are not read-after-write — but for the user who just clicked save, it is the only read that matters.

Then, at 14:07 on a Tuesday, the second problem arrives and it is a different kind of thing entirely.

The nightly batch job has been moved earlier and it is pushing six times the normal write rate. Four seconds into it, the primary dies. Your orchestrator does exactly what you configured it to do: it promotes the most caught-up replica in about thirty seconds, the application reconnects, and the site comes back. The incident review calls it a clean failover, and by the standard everybody uses — how long were we down — it was.

Here is what that review does not contain. At the instant the primary died, **44,283 commits had returned `200 OK` to a caller.** The replica you promoted had 43,896 of them durably on disk. The other **387 were acknowledged and are gone.** Not corrupted, not delayed — absent, from a database that is now serving traffic and reports itself perfectly healthy. Nobody received an error. There is no log line, no failed request, no alert, and no list of which 387 they were. Somewhere in there is a payment your ledger believes it took and your database has never heard of.

That is the trade you bought when you typed the word `async`, and this lesson is about knowing exactly what it costs before the invoice arrives.

## The Concept

### Why you add replicas at all — and the limit built into them

A **replica** is a second copy of your database that continuously applies the same changes as the first. The machine accepting writes is the **primary**; the copies are **replicas** or **standbys**. You add them for three distinct reasons, and they are worth separating because they pull in different directions.

**Read scaling.** Most applications read far more than they write. Nine reads per write is unremarkable; for a content site it can be a hundred. Every read a replica serves is a read the primary does not.

**Availability.** A replica is a warm copy that can be promoted. Restoring a large database from a backup is measured in hours; promoting a replica is measured in seconds. This is usually the reason you keep one even when reads are not a problem.

**Isolation.** A single analytics query that scans a year of orders will evict the working set from the primary's buffer pool ([Storage, Pages & Heaps](../../03-relational-databases/08-storage-pages-and-heaps/) covers why that is expensive: your fast queries were fast because their pages were in memory, and now they are not). Sending that query to a dedicated replica confines the damage to a machine no user is waiting on.

Now the limit, and it is structural rather than a matter of tuning. **Replicas scale reads. They never scale writes.** A replica is not a machine that does a share of the work; it is a machine that does *all* of the write work plus a share of the reads. Every replica applies 100% of your write volume. Adding one adds write load to the system as a whole and removes only read load.

That has an exact consequence you can compute. If one node can serve `C` operations per second and your write rate is `W`, then each replica has `C − W` left over for reads. The number of replicas needed for `R` reads per second is `ceil(R / (C − W))`, and as `W` approaches `C` that denominator approaches zero. Section 6 of the Build It sweeps it, with `C` = 20,000 ops/s and 60,000 ops/s offered:

```text
     write %      W ops/s   R ops/s   replicas   total system work   amplif.   useful new machine
       1.0%          600    59,400          4            62,400     1.04x          97% reads
      10.0%        6,000    54,000          4            84,000     1.40x          70% reads
      16.7%       10,000    50,000          5           110,000     1.83x          50% reads
      25.0%       15,000    45,000          9           195,000     3.25x          25% reads
      30.0%       18,000    42,000         21           438,000     7.30x          10% reads
      33.0%       19,800    40,200        201         4,039,800    67.33x           1% reads
      35.0%       21,000    39,000   IMPOSSIBLE    — every replica is already saturated by writes alone
```

Read the last column: it is the fraction of a newly purchased machine that does anything for a user. At a 1% write ratio a new replica is 97% useful. At 30% it is 10% useful and you need **21 machines to do 60,000 operations per second, which the system performs as 438,000 operations of actual work — a 7.3× amplification.** At 33% you need 201. At 35% there is no number of replicas that works, because a replica cannot even keep up with the write stream, let alone serve a read.

**The crossover is at `W = C/2`** — a 16.7% write ratio here — and it is where each additional replica starts adding more write work to the system than the read work it relieves. Gray, Helland, O'Neil and Shasha made this argument formally in *The Dangers of Replication and a Solution* (SIGMOD 1996): under eager replication the deadlock rate grows as roughly the cube of the node count, so a replicated system scales worse than linearly and eventually negatively. **Replication is a read-scaling technique with a hard ceiling, and the only way through the ceiling is to stop making every machine hold every row.** That is Lesson 8.

### How replication actually works: shipping the log, then replaying it

[Write-Ahead Logging](../../03-relational-databases/13-write-ahead-logging/) built the mechanism this depends on: before a change touches a data page, it is appended to the **WAL** (Write-Ahead Log), a sequential file of physical change records, and that append is what makes a commit durable. The lesson there was about crash recovery on a single machine — the log lets you replay what the pages have not yet absorbed.

Replication is the same log with the tape shipped elsewhere. **The replica is a machine that never stops performing crash recovery.** It streams the primary's WAL over a TCP connection and continuously replays it. Every position in that log has an **LSN** (Log Sequence Number) — a byte offset into the log, printed by Postgres as `0/1A2B3C8`. LSNs are monotonic and totally ordered, which is what makes the fix in this lesson possible: "has this replica reached the point my write created?" is an integer comparison.

There are three things you can ship, and the difference matters:

- **Physical / WAL / block-level.** Ship the actual byte-level page changes. Fast to apply, and the replica is by construction identical to the primary. The cost is rigidity: the replica must run the same major version and the same architecture, and it is all-or-nothing — you cannot replicate one table.
- **Logical / row-based.** Ship the *effect* of each change as rows ("in table `users`, the row with `id=7` now has these values"). Slower and more flexible: cross-version replication, selected tables, a different schema on the far end, and the basis of change-data-capture pipelines.
- **Statement-based.** Ship the SQL text and re-execute it. This is the one that is **unsafe**, and it is worth knowing why rather than just avoiding it. `UPDATE t SET last_seen = NOW()` produces a different value on a machine that runs it 40 ms later. `ORDER BY x LIMIT 10` with ties can pick different rows. `RANDOM()`, `UUID()`, `CURRENT_USER`, auto-increment interleaving under concurrency, and any trigger or user-defined function with a side effect can all diverge. The replica does not fail; it silently becomes a slightly different database. MySQL's `binlog_format` still offers `STATEMENT`; the answer is `ROW`.

The critical detail for everything that follows: **shipping is not applying.** The WAL arriving on the replica's disk and the WAL being visible to a query on that replica are two different events, separated by a queue. A replica can hold every byte you have ever written and still answer a query with data from eight seconds ago.

### Synchronous, asynchronous, semi-synchronous: what the ack means

The only real question in replication is: **at what point does the primary tell the client "committed"?**

**Asynchronous.** The primary flushes locally, acknowledges the client, and ships the WAL whenever it gets around to it. Writes are as fast as the local disk. In exchange you have a **guaranteed loss window**: the interval between the ack and the record becoming durable somewhere else. Every commit inside that window is a commit you will lose if the primary dies at that moment. This is the default nearly everywhere.

**Synchronous.** The primary waits for a standby to confirm before acknowledging. There is no loss window. You pay two prices, and the second one is the one people are not expecting. The first is latency: every write now costs a network round trip. The second is that **your primary's availability is now the logical AND of itself and its synchronous standby.** A standby that is slow, or hung, or GC-pausing, does not fail over — it *blocks every write on the primary*. You added a machine to improve availability and made your write path depend on two machines instead of one.

**Semi-synchronous / quorum.** Wait for *any k of n* standbys rather than one named one. Postgres spells this `ANY 2 (r1, r2, r3)`; MySQL calls it semi-synchronous replication. You get durability on more than one machine while any single slow standby is simply not the one you waited for — the AND becomes an OR. This is the practical middle and it is what most serious deployments run.

The arithmetic is not subtle, because the round trip is physics. The Build It measures 30,000 commits with a ~0.4 ms local flush:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 476" width="100%" style="max-width:840px" role="img" aria-label="One commit drawn on a single millisecond timeline under four replication modes. Asynchronous replication acknowledges the client after 0.42 milliseconds of local flush, but the record does not become durable on any replica until 4.3 milliseconds, and the shaded gap between those two points is the data-loss window. Quorum of any one of three standbys acknowledges at 1.01 milliseconds and a single named synchronous standby at 1.08 milliseconds, both with a zero loss window. A cross-region synchronous standby acknowledges at 88.88 milliseconds, drawn with a broken axis. A table underneath gives p50 and p99 write latency and the recovery point objective in rows for each mode.">
  <defs>
    <marker id="p11-07-a1" markerWidth="9" markerHeight="9" refX="5.5" refY="3" orient="auto"><path d="M0,0 L6.5,3 L0,6 Z" fill="currentColor"/></marker>
  </defs>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <text x="440" y="24" text-anchor="middle" font-size="14.5" font-weight="700" fill="currentColor">One commit, four modes: where the ack happens and what is still at risk</text>
    <text x="440" y="42" text-anchor="middle" font-size="10" fill="currentColor" opacity="0.8">measured p50s. The shaded band is the only thing that can be lost — and only async has one.</text>

    <g fill="none" stroke="currentColor" stroke-width="1" opacity="0.16">
      <path d="M228.3 58 L228.3 340"/><path d="M306.7 58 L306.7 340"/><path d="M385 58 L385 340"/><path d="M463.3 58 L463.3 340"/><path d="M541.7 58 L541.7 340"/><path d="M620 58 L620 340"/>
    </g>
    <path d="M150 58 L150 348" fill="none" stroke="#3553ff" stroke-width="1.8" stroke-dasharray="5 4" opacity="0.85"/>
    <text x="150" y="54" font-size="9.5" font-weight="700" text-anchor="middle" fill="#3553ff">COMMIT</text>

    <!-- lane 1: async -->
    <rect x="182.9" y="72" width="303.9" height="26" fill="#d64545" fill-opacity="0.14" stroke="#d64545" stroke-width="1.4" stroke-dasharray="4 3"/>
    <rect x="150" y="72" width="32.9" height="26" rx="3" fill="#0fa07f" fill-opacity="0.30" stroke="#0fa07f" stroke-width="1.6"/>
    <path d="M182.9 66 L182.9 104" fill="none" stroke="#0fa07f" stroke-width="2.4"/>
    <circle cx="182.9" cy="85" r="4.5" fill="#0fa07f" stroke="none"/>
    <path d="M486.8 66 L486.8 104" fill="none" stroke="#7c5cff" stroke-width="2.4"/>
    <g fill="currentColor">
      <text x="24" y="82" font-size="11.5" font-weight="700">ASYNC</text>
      <text x="24" y="96" font-size="8.5" opacity="0.75">the default</text>
      <text x="192" y="66" font-size="9.5" font-weight="700" fill="#0fa07f">ACK 0.42 ms</text>
      <text x="334" y="90" font-size="10" font-weight="700" text-anchor="middle" fill="#d64545">DATA-LOSS WINDOW</text>
      <text x="496" y="82" font-size="9.5" font-weight="700" fill="#7c5cff">durable on a replica</text>
      <text x="496" y="95" font-size="9" opacity="0.85">4.3 ms — 1.7 rows</text>
    </g>

    <!-- lane 2: quorum -->
    <rect x="150" y="142" width="27.4" height="26" rx="3" fill="#0fa07f" fill-opacity="0.30" stroke="#0fa07f" stroke-width="1.6"/>
    <rect x="177.4" y="142" width="51.7" height="26" rx="3" fill="#7c5cff" fill-opacity="0.20" stroke="#7c5cff" stroke-width="1.6"/>
    <path d="M229.1 136 L229.1 174" fill="none" stroke="#0fa07f" stroke-width="2.4"/>
    <circle cx="229.1" cy="155" r="4.5" fill="#0fa07f" stroke="none"/>
    <g fill="currentColor">
      <text x="24" y="152" font-size="11.5" font-weight="700">QUORUM</text>
      <text x="24" y="166" font-size="8.5" opacity="0.75">ANY 1 (r1,r2,r3)</text>
      <text x="238" y="152" font-size="9.5" font-weight="700" fill="#0fa07f">ACK 1.01 ms</text>
      <text x="238" y="165" font-size="9" opacity="0.85">waits for the FASTEST of three — no window</text>
      <text x="620" y="152" font-size="9.5" font-weight="700" fill="#0fa07f">loss window: none</text>
      <text x="620" y="165" font-size="9" opacity="0.85">one slow standby cannot block you</text>
    </g>

    <!-- lane 3: sync 1 -->
    <rect x="150" y="212" width="27.4" height="26" rx="3" fill="#0fa07f" fill-opacity="0.30" stroke="#0fa07f" stroke-width="1.6"/>
    <rect x="177.4" y="212" width="57.2" height="26" rx="3" fill="#7c5cff" fill-opacity="0.20" stroke="#7c5cff" stroke-width="1.6"/>
    <path d="M234.6 206 L234.6 244" fill="none" stroke="#0fa07f" stroke-width="2.4"/>
    <circle cx="234.6" cy="225" r="4.5" fill="#0fa07f" stroke="none"/>
    <rect x="430" y="207" width="424" height="36" rx="7" fill="#e0930f" fill-opacity="0.13" stroke="#e0930f" stroke-width="1.5"/>
    <g fill="currentColor">
      <text x="24" y="222" font-size="11.5" font-weight="700">SYNC × 1</text>
      <text x="24" y="236" font-size="8.5" opacity="0.75">one named standby</text>
      <text x="244" y="222" font-size="9.5" font-weight="700" fill="#0fa07f">ACK 1.08 ms</text>
      <text x="244" y="235" font-size="9" opacity="0.85">waits for THAT standby</text>
      <text x="444" y="222" font-size="9.5" font-weight="700" fill="#e0930f">THE AVAILABILITY INVERSION</text>
      <text x="444" y="235" font-size="9" opacity="0.9">that standby stalls 5 s → p99 4,702 ms, 5,000 commits blocked</text>
    </g>

    <!-- lane 4: cross region -->
    <rect x="150" y="282" width="27.4" height="26" rx="3" fill="#0fa07f" fill-opacity="0.30" stroke="#0fa07f" stroke-width="1.6"/>
    <rect x="177.4" y="282" width="192" height="26" rx="3" fill="#7c5cff" fill-opacity="0.20" stroke="#7c5cff" stroke-width="1.6"/>
    <rect x="392" y="282" width="192" height="26" rx="3" fill="#7c5cff" fill-opacity="0.20" stroke="#7c5cff" stroke-width="1.6"/>
    <g fill="none" stroke="currentColor" stroke-width="2">
      <path d="M372 278 L 382 312"/><path d="M380 278 L 390 312"/>
    </g>
    <path d="M584 276 L 584 314" fill="none" stroke="#0fa07f" stroke-width="2.4"/>
    <circle cx="584" cy="295" r="4.5" fill="#0fa07f" stroke="none"/>
    <g fill="currentColor">
      <text x="24" y="292" font-size="11.5" font-weight="700">SYNC × 1</text>
      <text x="24" y="306" font-size="8.5" opacity="0.75">cross-region</text>
      <text x="380" y="276" font-size="9.5" font-weight="700" text-anchor="middle" fill="#7c5cff">≈ 71 ms of wire, both ways — physics, not configuration</text>
      <text x="594" y="292" font-size="9.5" font-weight="700" fill="#e0930f">ACK 88.88 ms</text>
      <text x="594" y="305" font-size="9" opacity="0.85">211× the async commit</text>
    </g>

    <!-- axis -->
    <path d="M150 340 L 660 340" fill="none" stroke="currentColor" stroke-width="1.4" marker-end="url(#p11-07-a1)"/>
    <g fill="currentColor" font-size="9" text-anchor="middle" opacity="0.75">
      <text x="150" y="356">0</text><text x="228.3" y="356">1</text><text x="306.7" y="356">2</text><text x="385" y="356">3</text><text x="463.3" y="356">4</text><text x="541.7" y="356">5</text><text x="620" y="356">6</text>
      <text x="690" y="356" text-anchor="start" opacity="0.9">milliseconds since COMMIT</text>
    </g>

    <!-- table -->
    <path d="M24 376 L 856 376" fill="none" stroke="currentColor" stroke-width="1.1" opacity="0.4"/>
    <g fill="currentColor" font-size="9" font-weight="700" opacity="0.65">
      <text x="24" y="392">MODE</text><text x="250" y="392">p50</text><text x="330" y="392">p99</text><text x="410" y="392">RPO, CALM</text><text x="546" y="392">RPO, UNDER LOAD</text><text x="720" y="392">WHAT YOU ARE BUYING</text>
    </g>
    <g fill="currentColor" font-size="9.5">
      <text x="24" y="410">async</text><text x="250" y="410">0.42 ms</text><text x="330" y="410">4.63 ms</text><text x="410" y="410" fill="#e0930f">1 row</text><text x="546" y="410" fill="#d64545" font-weight="700">398 rows</text><text x="720" y="410" opacity="0.85">the cheapest write</text>
      <text x="24" y="426">quorum ANY 1 of 3</text><text x="250" y="426">1.01 ms</text><text x="330" y="426">5.22 ms</text><text x="410" y="426" fill="#0fa07f">0 rows</text><text x="546" y="426" fill="#0fa07f">0 rows</text><text x="720" y="426" opacity="0.85">the practical middle</text>
      <text x="24" y="442">sync × 1, same AZ</text><text x="250" y="442">1.08 ms</text><text x="330" y="442">7.01 ms</text><text x="410" y="442" fill="#0fa07f">0 rows</text><text x="546" y="442" fill="#0fa07f">0 rows</text><text x="720" y="442" opacity="0.85">their uptime is now yours</text>
      <text x="24" y="458">sync × 1, cross-region</text><text x="250" y="458">88.88 ms</text><text x="330" y="458">184.24 ms</text><text x="410" y="458" fill="#0fa07f">0 rows</text><text x="546" y="458" fill="#0fa07f">0 rows</text><text x="720" y="458" opacity="0.85">a different product</text>
    </g>
    <text x="440" y="474" font-size="11" text-anchor="middle" fill="currentColor" opacity="0.9">Async does not lose data because it is careless. It loses data because the ack is 3.9 ms early, every single time.</text>
  </g>
</svg>
```

Same-AZ synchronous replication costs **+0.66 ms at p50 (0.42 → 1.08 ms, a 2.6× commit)**, which for most systems is an easy purchase. (**AZ** = Availability Zone: a separate datacenter within a cloud region, close enough for sub-millisecond round trips, far enough to fail independently.) Cross-AZ costs +1.8 ms. **Cross-region synchronous replication costs +88.5 ms per commit** — measured p50 88.88 ms against async's 0.42 ms, a **211× commit**. At 400 commits per second that is not a slower product, it is a different product; every write in your application now takes longer than a full page load, and no amount of engineering below it will help, because you are paying for the speed of light in fibre.

Quorum is visibly the better shape: `ANY 1 of 3` waits for the **fastest** of three acknowledgements rather than one designated one, and measures a **p99 of 5.22 ms against 7.01 ms for a single named standby** — better tail latency *and* better availability than sync-1, for the same durability.

And then the row that explains why people are afraid of synchronous replication. When one synchronous standby stalls for five seconds, the measured p99 goes to **4,701.99 ms and 5,000 commits block behind it**. The standby is not down. It is not marked unhealthy. It is not failed over. It is simply slow, and every write in your system is now queued behind it. **A hung synchronous replica is a total write outage on a primary that is completely healthy.** Quorum is what turns that AND into an OR.

### What lag actually is, and how the usual metric lies

Ask for "replication lag" and you will usually be handed a number in seconds, computed as *now minus the timestamp of the last transaction the replica applied*. That number has a specific and dangerous failure mode:

> **A replica that has completely stopped receiving WAL reports a time-based lag of zero as soon as writes stop arriving on the primary.**

Time-based lag measures the age of the newest thing you have applied. If nothing new is being produced, the newest thing you have applied stops getting older relative to the newest thing that exists — so a totally disconnected replica looks perfectly healthy on any quiet system, and quiet systems are exactly when nobody is watching. This is why the honest signal is **byte distance in the log**: `primary_lsn − replica_lsn`. It cannot read zero unless the replica genuinely holds everything, and it never depends on the write rate.

The second thing the single number hides is that there are **three** lags, not one, and they fail for different reasons:

- **Send lag** — bytes the primary has produced but not yet put on the wire. A network or a saturated primary.
- **Receive / flush lag** — bytes received but not yet durable on the replica's disk. This is the one that determines **what survives a failover**, because promotion can only use what was flushed.
- **Replay lag** — bytes flushed but not yet applied to the visible data. This is the one that determines **what a read on that replica actually sees.**

They come apart, and the case where they come apart is the one that will page you. Replay on a standby can be blocked by a long-running query on that standby: applying the WAL would remove a row version the query still needs, so the replay pauses instead. The replica keeps receiving perfectly and stops applying entirely. Here is that measured on one replica:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 500" width="100%" style="max-width:840px" role="img" aria-label="Measured trace of one replica during a twelve second query conflict on the standby. The upper panel plots how many kilobytes of write-ahead log each of the replica's three positions is behind the primary: the sent and flushed positions stay pinned to zero for the whole window, while the replayed position climbs steadily from zero to 788 kilobytes, equal to 8.3 seconds of lag, and then drains back to zero in about one second once the conflicting query ends. The lower strip plots the send and flush lag in milliseconds on a 0 to 22 millisecond scale, showing both bouncing between 1 and 18 milliseconds throughout, entirely unaffected. The replica received every byte on time and simply did not apply them.">
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <text x="440" y="24" text-anchor="middle" font-size="14.5" font-weight="700" fill="currentColor">Three lags, one replica: it received everything and applied almost none of it</text>
    <text x="440" y="42" text-anchor="middle" font-size="10" fill="currentColor" opacity="0.8">measured — r2 during a 12 s query conflict on the standby. LSN = Log Sequence Number.</text>

    <rect x="212.3" y="60" width="192.6" height="262" fill="#e0930f" fill-opacity="0.10" stroke="none"/>
    <text x="308.6" y="74" font-size="10" font-weight="700" text-anchor="middle" fill="#e0930f">a 12 s analytics query holds a snapshot — replay must wait</text>

    <g fill="none" stroke="currentColor" stroke-width="1" opacity="0.15"><path d="M116 265.9 L758 265.9"/><path d="M116 209.8 L758 209.8"/><path d="M116 153.7 L758 153.7"/><path d="M116 97.6 L758 97.6"/></g>
    <g fill="none" stroke="currentColor" stroke-width="1.4"><path d="M116 60 L116 322"/><path d="M116 322 L758 322"/></g>
    <g fill="none" stroke="currentColor" stroke-width="1.1" opacity="0.5"><path d="M132.1 322 L132.1 327"/><path d="M212.3 322 L212.3 327"/><path d="M292.6 322 L292.6 327"/><path d="M372.8 322 L372.8 327"/><path d="M453.1 322 L453.1 327"/><path d="M533.3 322 L533.3 327"/><path d="M613.5 322 L613.5 327"/><path d="M693.8 322 L693.8 327"/></g>

    <path d="M116.0 321.9 L124.0 321.7 L132.1 321.9 L140.1 321.9 L148.1 321.7 L156.1 321.7 L164.2 321.1 L172.2 321.9 L180.2 321.9 L188.2 321.4 L196.2 322.0 L204.3 321.7 L212.3 321.8 L220.3 311.8 L228.3 302.5 L236.4 293.3 L244.4 282.8 L252.4 273.5 L260.5 264.7 L268.5 255.6 L276.5 246.6 L284.5 237.9 L292.6 227.3 L300.6 217.1 L308.6 207.1 L316.6 198.1 L324.6 190.6 L332.7 180.9 L340.7 173.2 L348.7 165.0 L356.8 154.0 L364.8 146.3 L372.8 135.0 L380.8 125.2 L388.8 117.6 L396.9 109.0 L404.9 100.9 L412.9 203.4 L420.9 305.6 L429.0 320.8 L437.0 321.8 L445.0 321.9 L453.1 321.5 L461.1 321.9 L469.1 321.4 L477.1 320.8 L485.1 321.4 L493.2 321.9 L501.2 321.6 L509.2 321.9 L517.2 321.2 L525.3 321.8 L533.3 321.8 L541.3 321.7 L549.4 321.7 L557.4 321.8 L565.4 321.9 L573.4 321.4 L581.5 321.9 L589.5 321.0 L597.5 321.9 L605.5 320.6 L613.5 321.3 L621.6 321.8 L629.6 321.6 L637.6 320.6 L645.6 321.9 L653.7 321.4 L661.7 321.3 L669.7 321.7 L677.8 321.8 L685.8 321.9 L693.8 321.9 L701.8 321.9 L709.9 321.6 L717.9 322.0 L725.9 321.3 L733.9 321.9 L741.9 321.7 L750.0 321.8 L758.0 321.8" fill="none" stroke="#d64545" stroke-width="2.8" stroke-linejoin="round"/>
    <path d="M116.0 321.9 L124.0 321.7 L132.1 321.9 L140.1 321.9 L148.1 321.7 L156.1 321.7 L164.2 321.8 L172.2 321.9 L180.2 321.9 L188.2 322.0 L196.2 322.0 L204.3 321.9 L212.3 321.9 L220.3 321.8 L228.3 321.9 L236.4 321.9 L244.4 321.9 L252.4 321.9 L260.5 322.0 L268.5 322.0 L276.5 321.9 L284.5 321.8 L292.6 322.0 L300.6 321.7 L308.6 322.0 L316.6 321.9 L324.6 322.0 L332.7 321.9 L340.7 322.0 L348.7 321.8 L356.8 321.9 L364.8 321.9 L372.8 321.8 L380.8 321.6 L388.8 321.9 L396.9 322.0 L404.9 322.0 L412.9 322.0 L420.9 322.0 L429.0 321.9 L437.0 321.8 L445.0 321.9 L453.1 321.9 L461.1 321.9 L469.1 322.0 L477.1 322.0 L485.1 321.7 L493.2 322.0 L501.2 322.0 L509.2 321.9 L517.2 322.0 L525.3 321.9 L533.3 321.8 L541.3 321.7 L549.4 321.7 L557.4 321.8 L565.4 321.9 L573.4 321.7 L581.5 321.9 L589.5 321.9 L597.5 321.9 L605.5 321.6 L613.5 321.8 L621.6 321.8 L629.6 322.0 L637.6 321.9 L645.6 322.0 L653.7 321.9 L661.7 321.9 L669.7 321.7 L677.8 321.8 L685.8 321.9 L693.8 322.0 L701.8 321.9 L709.9 321.9 L717.9 322.0 L725.9 321.7 L733.9 321.9 L741.9 321.9 L750.0 321.8 L758.0 321.8" fill="none" stroke="#0fa07f" stroke-width="2.4" stroke-linejoin="round"/>
    <path d="M116.0 322.0 L124.0 321.9 L132.1 322.0 L140.1 322.0 L148.1 322.0 L156.1 321.9 L164.2 322.0 L172.2 321.9 L180.2 322.0 L188.2 322.0 L196.2 322.0 L204.3 321.9 L212.3 321.9 L220.3 321.9 L228.3 322.0 L236.4 321.9 L244.4 321.9 L252.4 321.9 L260.5 322.0 L268.5 322.0 L276.5 321.9 L284.5 322.0 L292.6 322.0 L300.6 321.9 L308.6 322.0 L316.6 322.0 L324.6 322.0 L332.7 321.9 L340.7 322.0 L348.7 321.9 L356.8 322.0 L364.8 322.0 L372.8 321.9 L380.8 321.9 L388.8 322.0 L396.9 322.0 L404.9 322.0 L412.9 322.0 L420.9 322.0 L429.0 321.9 L437.0 322.0 L445.0 322.0 L453.1 321.9 L461.1 321.9 L469.1 322.0 L477.1 322.0 L485.1 321.9 L493.2 322.0 L501.2 322.0 L509.2 322.0 L517.2 322.0 L525.3 322.0 L533.3 322.0 L541.3 321.9 L549.4 322.0 L557.4 321.9 L565.4 322.0 L573.4 322.0 L581.5 322.0 L589.5 322.0 L597.5 322.0 L605.5 321.9 L613.5 321.9 L621.6 321.9 L629.6 322.0 L637.6 321.9 L645.6 322.0 L653.7 322.0 L661.7 321.9 L669.7 322.0 L677.8 322.0 L685.8 321.9 L693.8 322.0 L701.8 322.0 L709.9 322.0 L717.9 322.0 L725.9 322.0 L733.9 321.9 L741.9 322.0 L750.0 322.0 L758.0 321.9" fill="none" stroke="#3553ff" stroke-width="1.8" stroke-dasharray="5 3" stroke-linejoin="round"/>

    <circle cx="404.9" cy="100.9" r="5" fill="none" stroke="#d64545" stroke-width="2.2"/>
    <path d="M398.9 96.9 L 539 118" fill="none" stroke="#d64545" stroke-width="1.2" stroke-dasharray="4 3"/>
    <g fill="currentColor">
      <text x="545" y="114" font-size="10.5" font-weight="700" fill="#d64545">peak: 788 KB behind = 8.3 s</text>
      <text x="545" y="128" font-size="9" opacity="0.9">Postgres tolerates this until</text>
      <text x="545" y="141" font-size="9" opacity="0.9">max_standby_streaming_delay</text>
      <text x="545" y="154" font-size="9" opacity="0.9">= 30 s, then cancels the query.</text>
      <text x="545" y="167" font-size="9" opacity="0.9">It never fired: nothing logged,</text>
      <text x="545" y="180" font-size="9" opacity="0.9">nothing alerted. The replica</text>
      <text x="545" y="193" font-size="9" font-weight="700" opacity="0.95">served 8-second-old rows.</text>
    </g>
    <path d="M437.0 322 L 437.0 274" fill="none" stroke="#0fa07f" stroke-width="1.4" stroke-dasharray="4 3"/>
    <text x="443.0" y="270" font-size="9" font-weight="700" fill="#0fa07f">query ends → 1.0 s to drain</text>

    <g fill="currentColor"><text x="108" y="325.5" font-size="9" text-anchor="end" opacity="0.7">0</text><text x="108" y="269.4" font-size="9" text-anchor="end" opacity="0.7">200</text><text x="108" y="213.3" font-size="9" text-anchor="end" opacity="0.7">400</text><text x="108" y="157.2" font-size="9" text-anchor="end" opacity="0.7">600</text><text x="108" y="101.1" font-size="9" text-anchor="end" opacity="0.7">800</text><text x="132.1" y="340" font-size="9" text-anchor="middle" opacity="0.7">35s</text><text x="212.3" y="340" font-size="9" text-anchor="middle" opacity="0.7">40s</text><text x="292.6" y="340" font-size="9" text-anchor="middle" opacity="0.7">45s</text><text x="372.8" y="340" font-size="9" text-anchor="middle" opacity="0.7">50s</text><text x="453.1" y="340" font-size="9" text-anchor="middle" opacity="0.7">55s</text><text x="533.3" y="340" font-size="9" text-anchor="middle" opacity="0.7">60s</text><text x="613.5" y="340" font-size="9" text-anchor="middle" opacity="0.7">65s</text><text x="693.8" y="340" font-size="9" text-anchor="middle" opacity="0.7">70s</text></g>
    <text x="52" y="150" font-size="10" opacity="0.85" transform="rotate(-90 52 150)" text-anchor="middle">KB of WAL behind</text>
    <g><text x="768" y="325.5" font-size="9" opacity="0.7" fill="#e0930f">0 s</text><text x="768" y="270.7" font-size="9" opacity="0.7" fill="#e0930f">2 s</text><text x="768" y="215.9" font-size="9" opacity="0.7" fill="#e0930f">4 s</text><text x="768" y="161.2" font-size="9" opacity="0.7" fill="#e0930f">6 s</text><text x="768" y="106.4" font-size="9" opacity="0.7" fill="#e0930f">8 s</text></g>
    <text x="838" y="150" font-size="10" opacity="0.85" fill="#e0930f" transform="rotate(-90 838 150)" text-anchor="middle">= replay lag</text>

    <g fill="currentColor" font-size="10" font-weight="700">
      <text x="468" y="206" fill="#d64545">— replay_lsn  (what a read here actually sees)</text>
      <text x="468" y="222" fill="#0fa07f">— flush_lsn   (what survives a failover)</text>
      <text x="468" y="238" fill="#3553ff">- - sent_lsn   (what left the primary)</text>
    </g>

    <text x="116" y="360" font-size="10.5" font-weight="700" fill="currentColor">the same window, send and flush lag only — nothing happened to either</text>
    <g fill="none" stroke="currentColor" stroke-width="1.3"><path d="M116 366 L116 428"/><path d="M116 428 L758 428"/></g>
    <g fill="none" stroke="currentColor" stroke-width="1" opacity="0.5"><path d="M132.1 428 L132.1 432"/><path d="M212.3 428 L212.3 432"/><path d="M292.6 428 L292.6 432"/><path d="M372.8 428 L372.8 432"/><path d="M453.1 428 L453.1 432"/><path d="M533.3 428 L533.3 432"/><path d="M613.5 428 L613.5 432"/><path d="M693.8 428 L693.8 432"/></g>
    <rect x="212.3" y="366" width="192.6" height="62" fill="#e0930f" fill-opacity="0.10" stroke="none"/>
    <path d="M116.0 418.0 L124.0 410.9 L132.1 418.7 L140.1 375.3 L148.1 403.0 L156.1 411.6 L164.2 405.0 L172.2 413.9 L180.2 403.8 L188.2 422.2 L196.2 411.6 L204.3 412.5 L212.3 407.7 L220.3 394.4 L228.3 393.0 L236.4 421.4 L244.4 405.9 L252.4 409.3 L260.5 420.9 L268.5 382.7 L276.5 410.8 L284.5 400.5 L292.6 416.7 L300.6 403.6 L308.6 420.6 L316.6 396.7 L324.6 410.3 L332.7 412.5 L340.7 417.8 L348.7 410.2 L356.8 418.8 L364.8 415.3 L372.8 404.7 L380.8 390.7 L388.8 402.3 L396.9 421.5 L404.9 418.4 L412.9 424.1 L420.9 411.2 L429.0 418.9 L437.0 408.3 L445.0 402.2 L453.1 424.7 L461.1 420.3 L469.1 420.1 L477.1 421.0 L485.1 385.3 L493.2 424.1 L501.2 410.4 L509.2 397.1 L517.2 409.6 L525.3 392.5 L533.3 407.9 L541.3 394.7 L549.4 414.3 L557.4 414.5 L565.4 381.4 L573.4 410.9 L581.5 415.0 L589.5 411.7 L597.5 410.2 L605.5 394.9 L613.5 398.8 L621.6 402.5 L629.6 413.5 L637.6 416.5 L645.6 411.1 L653.7 415.2 L661.7 408.8 L669.7 395.2 L677.8 405.9 L685.8 415.3 L693.8 420.7 L701.8 424.2 L709.9 396.1 L717.9 419.0 L725.9 403.9 L733.9 403.8 L741.9 402.4 L750.0 395.4 L758.0 408.6" fill="none" stroke="#0fa07f" stroke-width="1.8"/>
    <path d="M116.0 422.2 L124.0 423.8 L132.1 425.5 L140.1 424.3 L148.1 424.0 L156.1 425.0 L164.2 423.0 L172.2 413.9 L180.2 422.8 L188.2 422.2 L196.2 411.6 L204.3 412.5 L212.3 407.7 L220.3 415.5 L228.3 424.4 L236.4 421.4 L244.4 405.9 L252.4 409.3 L260.5 420.9 L268.5 382.7 L276.5 410.8 L284.5 414.7 L292.6 416.7 L300.6 424.6 L308.6 420.6 L316.6 407.9 L324.6 410.3 L332.7 417.6 L340.7 417.8 L348.7 422.2 L356.8 421.8 L364.8 423.6 L372.8 421.1 L380.8 422.7 L388.8 423.3 L396.9 421.5 L404.9 418.4 L412.9 424.1 L420.9 411.2 L429.0 424.3 L437.0 425.5 L445.0 421.2 L453.1 424.7 L461.1 420.3 L469.1 420.1 L477.1 421.0 L485.1 409.4 L493.2 424.1 L501.2 410.4 L509.2 423.1 L517.2 409.6 L525.3 419.8 L533.3 426.7 L541.3 418.6 L549.4 425.6 L557.4 416.0 L565.4 425.3 L573.4 424.0 L581.5 425.7 L589.5 418.2 L597.5 419.4 L605.5 419.7 L613.5 424.2 L621.6 411.3 L629.6 413.5 L637.6 419.8 L645.6 411.1 L653.7 422.6 L661.7 408.8 L669.7 415.4 L677.8 423.8 L685.8 415.3 L693.8 420.7 L701.8 425.1 L709.9 421.1 L717.9 419.0 L725.9 418.5 L733.9 403.8 L741.9 417.9 L750.0 420.8 L758.0 423.0" fill="none" stroke="#3553ff" stroke-width="1.5" stroke-dasharray="4 3"/>
    <g fill="currentColor" font-size="9" text-anchor="end" opacity="0.7">
      <text x="108" y="431">0</text><text x="108" y="373">22 ms</text>
    </g>
    <text x="758" y="360" text-anchor="end" font-size="9.5" font-weight="700" fill="currentColor" opacity="0.9">1–18 ms, start to finish</text>

    <text x="440" y="462" font-size="11.5" font-weight="700" text-anchor="middle" fill="currentColor">A network-lag metric would have shown a perfectly healthy replica for the whole 12 seconds.</text>
    <text x="440" y="482" font-size="11" text-anchor="middle" fill="currentColor" opacity="0.9">Alert on replay, page on flush, debug with send. They are three different failures wearing one name.</text>
  </g>
</svg>
```

For twelve seconds, `sent_lsn` and `flush_lsn` sit at **1–18 ms of lag, completely unaffected** — the WAL arrived on time, all of it. Meanwhile the replay position falls **788 KB behind, which is 8.3 seconds of data.** Any read routed to this replica during that window returns eight-second-old rows to a real user. A network-lag metric, a ping check, a "is the stream connected" check, and a TCP-level dashboard all show a perfectly healthy replica for the entire event.

Note what Postgres does here, because it is the trap behind the trap. It will tolerate this until `max_standby_streaming_delay` (default **30 seconds**) and only then cancel the conflicting query. Our conflict lasted 12 seconds, so **the timeout never fired, nothing was logged, and nothing alerted.** The system behaved exactly as configured while serving stale data, which is the worst possible combination: a failure with no error attached to it.

**Alert on replay lag. Page on flush lag. Debug with send lag.** They are three different failures wearing one name.

### Read-your-writes: the profile bug

Now the consistency models. These are usually taught as a taxonomy, which is the least useful way to meet them — they are much easier to hold onto as the specific bug each one is the absence of. The names come from Terry, Demers, Petersen, Spreitzer, Theimer and Welch, *Session Guarantees for Weakly Consistent Replicated Data* (PDIS 1994), which defined them as **session guarantees**: properties that hold for one user's sequence of operations, not for the database globally. That framing is the practical one, because it is achievable — you do not need a globally consistent system, you need each user's own view to make sense.

**Read-your-writes** is the guarantee that once you have successfully written something, you will not subsequently read an older value. Its absence is the 09:41 ticket. Here it is as a sequence, with the fix beside it:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 560" width="100%" style="max-width:840px" role="img" aria-label="Two sequence diagrams side by side for the same profile update. On the left, the naive version: the browser posts the new value, the primary commits it at log position 0/1A2B3C8 and returns a 302 redirect after 0.4 milliseconds, the browser follows the redirect 12 milliseconds later, the router picks a replica at random, that replica has only replayed up to position 0/1A2B390 because it is 33 milliseconds behind, and the page renders the old value; this happens to 61.65 percent of read-after-write requests. On the right, the LSN-pinned version: the commit returns its log position to the client, the follow-up read carries that position, the router only considers replicas whose replay position has reached it and waits up to 10 milliseconds otherwise falling back to the primary, and the page renders the new value every time, with zero stale reads, only 1.32 percent of reads on the primary and 0.30 milliseconds of added mean latency.">
  <defs>
    <marker id="p11-07-a2" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L6.5,3 L0,6 Z" fill="currentColor"/></marker>
    <marker id="p11-07-a2r" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L6.5,3 L0,6 Z" fill="#d64545"/></marker>
    <marker id="p11-07-a2g" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L6.5,3 L0,6 Z" fill="#0fa07f"/></marker>
  </defs>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <text x="440" y="24" text-anchor="middle" font-size="14.5" font-weight="700" fill="currentColor">Read-your-writes: the same page load, with and without the LSN</text>
    <text x="440" y="42" text-anchor="middle" font-size="10" fill="currentColor" opacity="0.8">LSN = Log Sequence Number, the byte offset of a record in the write-ahead log</text>

    <rect x="14" y="54" width="418" height="450" rx="12" fill="#d64545" fill-opacity="0.06" stroke="#d64545" stroke-width="1.8"/>
    <rect x="448" y="54" width="418" height="450" rx="12" fill="#0fa07f" fill-opacity="0.07" stroke="#0fa07f" stroke-width="1.8"/>
    <text x="223" y="76" text-anchor="middle" font-size="12.5" font-weight="700" fill="#d64545">NAIVE — the read goes to whichever replica answers</text>
    <text x="657" y="76" text-anchor="middle" font-size="12.5" font-weight="700" fill="#0fa07f">LSN-PINNED — the read names the position it needs</text>

    <!-- lifelines LEFT -->
    <g fill="none" stroke="currentColor" stroke-width="1.2" stroke-dasharray="4 5" opacity="0.4">
      <path d="M62 112 L62 330"/><path d="M200 112 L200 330"/><path d="M338 112 L338 330"/>
    </g>
    <g fill="none" stroke-width="1.7">
      <rect x="26" y="88" width="72" height="24" rx="6" fill="#3553ff" fill-opacity="0.13" stroke="#3553ff"/>
      <rect x="158" y="88" width="84" height="24" rx="6" fill="#0fa07f" fill-opacity="0.13" stroke="#0fa07f"/>
      <rect x="290" y="88" width="96" height="24" rx="6" fill="#7c5cff" fill-opacity="0.13" stroke="#7c5cff"/>
    </g>
    <g fill="currentColor" font-size="9.5" font-weight="700" text-anchor="middle">
      <text x="62" y="104">browser</text><text x="200" y="104">primary</text><text x="338" y="104">replica r3</text>
    </g>

    <g fill="none" stroke="currentColor" stroke-width="1.6">
      <path d="M62 140 L 194 140" marker-end="url(#p11-07-a2)"/>
      <path d="M200 186 L 68 186" marker-end="url(#p11-07-a2)"/>
      <path d="M62 250 L 332 250" marker-end="url(#p11-07-a2)"/>
    </g>
    <path d="M338 308 L 68 308" fill="none" stroke="#d64545" stroke-width="1.9" marker-end="url(#p11-07-a2r)"/>

    <g fill="currentColor" font-size="9">
      <text x="128" y="134" text-anchor="middle" font-weight="700">POST /profile  name="Ada"</text>
      <text x="204" y="160" font-size="9.5" font-weight="700" fill="#0fa07f">COMMIT → LSN 0/1A2B3C8</text>
      <text x="204" y="173" opacity="0.85">local flush 0.42 ms</text>
      <text x="134" y="180" text-anchor="middle" font-weight="700">302 → /profile</text>
      <text x="134" y="200" text-anchor="middle" opacity="0.8">no LSN in the response</text>
      <text x="197" y="244" text-anchor="middle" font-weight="700">GET /profile   (12 ms later)</text>
      <text x="197" y="226" text-anchor="middle" font-size="8.5" opacity="0.75">router: "any replica will do"</text>
      <text x="420" y="262" text-anchor="end" font-size="9.5" font-weight="700" fill="#e0930f">replay_lsn = 0/1A2B390</text>
      <text x="420" y="274" text-anchor="end" opacity="0.85">33 ms behind — the row</text>
      <text x="420" y="286" text-anchor="end" opacity="0.85">has not arrived yet</text>
      <text x="196" y="302" text-anchor="middle" font-weight="700" fill="#d64545">200 OK  name="Ana"</text>
      <text x="196" y="322" text-anchor="middle" font-size="9" fill="#d64545">the value the user just replaced</text>
    </g>

    <rect x="30" y="336" width="386" height="74" rx="9" fill="#d64545" fill-opacity="0.12" stroke="#d64545" stroke-width="1.6"/>
    <g fill="currentColor">
      <text x="44" y="356" font-size="10.5" font-weight="700" fill="#d64545">61.65% of read-after-write requests, measured</text>
      <text x="44" y="374" font-size="9.5" opacity="0.9">The redirect takes 12 ms. The replicas are 12–33 ms behind.</text>
      <text x="44" y="389" font-size="9.5" opacity="0.9">12 &lt; 33, so the race is lost before it starts — and it is</text>
      <text x="44" y="404" font-size="9.5" opacity="0.9">"fixed" by refreshing, so it never reproduces for you.</text>
    </g>
    <rect x="30" y="422" width="386" height="68" rx="9" fill="#7f7f7f" fill-opacity="0.08" stroke="currentColor" stroke-opacity="0.4" stroke-width="1.4"/>
    <g fill="currentColor">
      <text x="44" y="441" font-size="10" font-weight="700">the popular half-fix: sticky-to-primary for 500 ms</text>
      <text x="44" y="457" font-size="9.5" opacity="0.9">kills 99.3% of them — but sends 18.52% of ALL reads to</text>
      <text x="44" y="471" font-size="9.5" opacity="0.9">the primary, and misses every cross-device read, because</text>
      <text x="44" y="485" font-size="9.5" opacity="0.9">the sticky flag lives in the session that did the write.</text>
    </g>

    <!-- lifelines RIGHT -->
    <g fill="none" stroke="currentColor" stroke-width="1.2" stroke-dasharray="4 5" opacity="0.4">
      <path d="M496 112 L496 330"/><path d="M634 112 L634 330"/><path d="M772 112 L772 254"/>
    </g>
    <g fill="none" stroke-width="1.7">
      <rect x="460" y="88" width="72" height="24" rx="6" fill="#3553ff" fill-opacity="0.13" stroke="#3553ff"/>
      <rect x="592" y="88" width="84" height="24" rx="6" fill="#0fa07f" fill-opacity="0.13" stroke="#0fa07f"/>
      <rect x="716" y="88" width="112" height="24" rx="6" fill="#7c5cff" fill-opacity="0.13" stroke="#7c5cff"/>
    </g>
    <g fill="currentColor" font-size="9.5" font-weight="700" text-anchor="middle">
      <text x="496" y="104">browser</text><text x="634" y="104">primary</text><text x="772" y="104">router + replicas</text>
    </g>

    <g fill="none" stroke="currentColor" stroke-width="1.6">
      <path d="M496 140 L 628 140" marker-end="url(#p11-07-a2)"/>
      <path d="M634 186 L 502 186" marker-end="url(#p11-07-a2)"/>
      <path d="M496 250 L 766 250" marker-end="url(#p11-07-a2)"/>
    </g>
    <path d="M772 310 L 502 310" fill="none" stroke="#0fa07f" stroke-width="1.9" marker-end="url(#p11-07-a2g)"/>

    <g fill="currentColor" font-size="9">
      <text x="562" y="134" text-anchor="middle" font-weight="700">POST /profile  name="Ada"</text>
      <text x="638" y="160" font-size="9.5" font-weight="700" fill="#0fa07f">COMMIT → LSN 0/1A2B3C8</text>
      <text x="638" y="173" opacity="0.85">pg_current_wal_lsn()</text>
      <text x="568" y="180" text-anchor="middle" font-weight="700" fill="#3553ff">302 + X-Read-LSN: 0/1A2B3C8</text>
      <text x="576" y="200" text-anchor="middle" opacity="0.8">the position, in a cookie or a header</text>
      <text x="631" y="244" text-anchor="middle" font-weight="700">GET /profile   X-Read-LSN: 0/1A2B3C8</text>
      <text x="631" y="226" text-anchor="middle" font-size="8.5" opacity="0.75">router: "a replica that has reached this"</text>
    </g>

    <rect x="700" y="258" width="156" height="44" rx="7" fill="#7c5cff" fill-opacity="0.13" stroke="#7c5cff" stroke-width="1.5"/>
    <g fill="currentColor" font-size="8.5">
      <text x="710" y="272" font-weight="700">r1  0/1A2B3D0  ✓ ahead</text>
      <text x="710" y="284" opacity="0.6">r3  0/1A2B390  ✗ behind</text>
      <text x="710" y="296" opacity="0.6">r2  0/1A2B2F1  ✗ behind</text>
    </g>
    <g fill="currentColor" font-size="9">
      <text x="630" y="304" text-anchor="middle" font-weight="700" fill="#0fa07f">200 OK  name="Ada"</text>
      <text x="630" y="324" text-anchor="middle" font-size="9">served by r1 — correct, and still not the primary</text>
    </g>

    <rect x="464" y="338" width="386" height="76" rx="9" fill="#0fa07f" fill-opacity="0.12" stroke="#0fa07f" stroke-width="1.6"/>
    <g fill="currentColor">
      <text x="478" y="358" font-size="10.5" font-weight="700" fill="#0fa07f">0 stale reads out of 60,000, measured</text>
      <text x="478" y="376" font-size="9.5" opacity="0.9">reads landing on the primary: 1.32%  (sticky: 18.52%)</text>
      <text x="478" y="391" font-size="9.5" opacity="0.9">added mean latency: +0.30 ms   ·   p99 read 11.80 ms</text>
      <text x="478" y="406" font-size="9.5" opacity="0.9">14× less primary load than sticky, and no session state.</text>
    </g>
    <rect x="464" y="426" width="386" height="62" rx="9" fill="#e0930f" fill-opacity="0.11" stroke="#e0930f" stroke-width="1.4"/>
    <g fill="currentColor">
      <text x="478" y="445" font-size="10" font-weight="700" fill="#e0930f">no replica has reached it?</text>
      <text x="478" y="462" font-size="9.5" opacity="0.9">poll every 2 ms for up to 10 ms, then fall back to the</text>
      <text x="478" y="477" font-size="9.5" opacity="0.9">primary. Correctness never depends on the wait finishing.</text>
    </g>

    <text x="440" y="526" font-size="11.5" font-weight="700" text-anchor="middle" fill="currentColor">The bug is not that the replica is slow. It is that the read never said how fresh it needed to be.</text>
    <text x="440" y="546" font-size="11" text-anchor="middle" fill="currentColor" opacity="0.9">One integer, returned by the write and echoed by the read, turns a consistency guess into a check.</text>
  </g>
</svg>
```

The measured rate is the part that surprises people. Sampling 10,473 write-then-read trials against healthy replicas, by read delay:

```text
     read delay      stale reads     what that delay is
          5 ms       83.91%       same-process read-back
         12 ms       61.65%       HTTP 302 redirect after POST
         25 ms       38.83%       a fast SPA refetch
         50 ms       17.39%       user clicks 'back'
        100 ms        8.31%       a slow page load
        250 ms        5.03%       a human re-reads the page
       1000 ms        4.85%       a second later
       5000 ms        2.22%       five seconds later
```

Two things to take from that column. First, at the delays that real applications actually produce — a redirect, a refetch — the stale rate is **not a tail, it is the common case**. Second, and more important: **the curve does not decay to zero.** At five full seconds it is still 2.22%, because the curve does not decay toward "caught up", it decays toward *your worst replica*. One replica in this fleet spends twelve seconds with a replay conflict; a read routed there is stale no matter how long you wait. **There is no delay you can add to a request that makes this correct.** Any fix built on "wait a bit" is a fix that works in staging.

There are two real fixes.

**Sticky-to-primary window.** After a user writes, route that user's reads to the primary for the next N milliseconds. It is easy, it works, and it has two flaws you should say out loud. It **needs per-user state** somewhere in the routing layer — a cookie, a session entry, something the load balancer or app must consult, which is exactly the instance-local state Lesson 6 spent a whole lesson removing. And it is **scoped to a session, while users are not**: the write happens on the phone, the read happens on the laptop, and the sticky flag is in the wrong place entirely. Measured over 60,000 reads, a 500 ms sticky window removed **99.3% of stale reads** — and the 47 it missed are precisely the cross-device ones. It also sent **18.52% of all read traffic back to the primary**, which is a meaningful fraction of the load you bought the replicas to remove.

**LSN pinning.** This is the correct answer and it is rarely taught, so here is the mechanism in full:

1. The write completes. The primary knows the LSN its commit produced — in Postgres, `pg_current_wal_lsn()`. **Return that position to the client**, in a cookie, a header (`X-Read-LSN`), or the response body. It is one integer.
2. The client sends it back with subsequent reads. The read is no longer "get my profile", it is "**get my profile from a copy that has replayed at least `0/1A2B3C8`**".
3. The router compares that token against each replica's `pg_last_wal_replay_lsn()` — a number it already tracks for health — and picks any replica that has reached it.
4. If none has, it **waits a bounded moment** (poll every 2 ms for up to 10 ms) and then **falls back to the primary**, which by definition has the data.

Step 4 is what makes it safe. Correctness never depends on the wait succeeding; the wait is only an optimisation to avoid touching the primary. The worst case is a read on the primary, which is what you would have done anyway.

The measured comparison over the identical 60,000-read trace:

```text
     policy                 stale reads      reads on primary   mean read   p99 read
     naive: always replica    6,844 (11.41%)         0 ( 0.00%)      1.10ms     1.10ms
     sticky-to-primary 500ms     47 ( 0.08%)    11,113 (18.52%)      1.23ms     1.80ms
     LSN-pinned read              0 ( 0.00%)       795 ( 1.32%)      1.40ms    11.80ms
```

**LSN pinning eliminated 100% of stale reads while sending only 1.32% of reads to the primary — 14× less primary load than the sticky window — for +0.30 ms of mean latency.** It requires no session state, works across devices, works across a fleet of any size, and degrades to "read the primary" rather than to "return the wrong answer". The p99 of 11.80 ms is the bounded wait doing its job on the small fraction of reads that need it.

The general principle is worth extracting, because it applies well beyond databases: **the bug is not that the replica is slow. The bug is that the read never said how fresh it needed to be.** A read with no freshness requirement attached is a read that has silently accepted whatever it gets. One integer, returned by the write and echoed by the read, converts a guess into a check.

### Monotonic reads: watching time run backwards

**Monotonic reads** is the guarantee that successive reads in one session never move backwards in time. Its absence is the 10:02 ticket, and the mechanism is worth being precise about, because a common defence is wrong:

> A **single** replica's position only ever moves forward. The **set** of replicas does not, and round-robin walks the set.

Read one: routed to r1, 12 ms behind, sees the comment. Read two, moments later: routed to r3, 33 ms behind, does not. The comment appeared and then disappeared, and both replicas were behaving correctly and moving only forward. Nothing was broken.

This needs no incident at all — and that is the finding worth internalising. The measurement:

```text
  A · one page load, 8 widgets fanned out 6 ms apart  (4,000 sessions)
     routing                        backwards events   sessions affected
     round-robin over 3 replicas        12,119       3,857/4,000
     session pinned to one replica           0           0/4,000
     last-seen-LSN token                     0           0/4,000
```

**A single page load that fans out to eight widgets six milliseconds apart shows time running backwards in 3,857 of 4,000 sessions — 96%.** Not during an incident. On healthy replicas, in steady state. The gap between a 12 ms replica and a 33 ms replica is simply larger than the gap between two parallel API calls on the same page, so an ordinary dashboard renders a mutually inconsistent view of itself as a matter of routine. A slower poll (every 250 ms for 30 s) only goes backwards when one replica is badly behind, and it did: 3,869 events across 319 of 400 sessions during the replay conflict.

Both fixes drive it to exactly zero:

- **Pin the session to one replica** — `hash(user_id) % n`. One hash, no state, and monotonicity comes free because one replica cannot move backwards. The cost is that a slow replica now consistently serves the same unlucky users, and rebalancing when a replica leaves will break the guarantee for whoever moves.
- **Carry the last-seen LSN** — the same token as read-your-writes, now used as a floor: never accept a replica that has replayed less than what this session has already been shown. Strictly stronger, and it composes with the read-your-writes fix because it is the same mechanism.

Note that these are different guarantees and you can have either without the other. Pinning to one replica gives monotonic reads but *not* read-your-writes — your pinned replica may not have your write yet. The LSN token gives both, which is the argument for it.

### Consistent prefix: the reply before the message

**Consistent prefix** is the guarantee that if writes happened in a causal order, no observer sees them out of that order. Its absence produces the strangest artifact of the three: a reply visible before the message it answers.

Alice comments "is the deploy done?" Bob replies "yes, ten minutes ago." Both are written to the primary in that order. A reader whose two queries land on differently-lagged copies — or on a system where those two rows live in different partitions replicating independently — can see Bob's reply above a thread with no question in it. Nothing was lost and nothing will need repair; the final state is correct. But it is briefly, visibly nonsense.

Single-primary WAL replication gives you consistent prefix for free within one database, because the WAL is one totally-ordered stream and a replica applies it strictly in order — a replica is always a *prefix* of the primary, never a subset with holes. **This is a property you lose exactly when you shard** ([Sharding the Data Tier](../08-sharding-the-data-tier/)), because two shards replicate independently and there is no global order between them. It is also what you lose across regions. Worth knowing now, so that you notice when you give it up.

The general form is **causal consistency**: if write B was caused by write A, everyone who sees B sees A. It is the strongest model that remains available during a network partition (Bailis et al., *Highly Available Transactions: Virtues and Limitations*, VLDB 2014), which makes it the ceiling for any system that must keep serving when the network splits.

### Failover and the data-loss window

Asynchronous replication means that at every instant there is some set of commits that are acknowledged but exist on only one machine. **Your RPO — Recovery Point Objective, the amount of data you accept losing — is not a policy you set. It is a number your system produces, continuously, and you either measure it or you find out during a failover.**

The arithmetic is a product: `rows lost ≈ flush lag × commit rate`. Both terms move, and the trap is that they move **together and in the wrong direction**:

```text
    on a calm system   p50     1   p99     5   worst     6 acknowledged commits
    during the batch   p50   398   p99   639   worst   647 acknowledged commits
```

**128× worse during the batch job** — and the batch job is exactly the thing most likely to kill the primary in the first place. The dashboard number is the calm number, because the calm state is where the system spends its time; the number you will actually experience is the load number, because load is what breaks things. **Your RPO is your lag during the incident, never the median on the dashboard.** The measured product confirms it: 4.3 ms of flush lag × 400 commits/s = 1.7 rows (measured 1); 167.6 ms × 2,400 commits/s = 402.3 rows (measured 398).

Here is the failover itself, with the primary dying four seconds into a 6× batch job:

```text
     replica          sent_lsn     flush_lsn    replay_lsn   flush lag   rows not durable
     r1-same-az      11.0467 MB    10.8900 MB    10.6485 MB     269.7ms          635
     r2-same-az      11.0456 MB    10.9515 MB    10.5174 MB     164.4ms          387
     r3-cross-az     11.0359 MB    10.2478 MB     9.9153 MB    1341.1ms        3,203
```

Three things in that table. The replicas **disagree about how much they have** — flush positions differ by 700 KB, which is why "promote by highest LSN" is a correctness requirement and not a nicety: promoting r3 instead of r2 loses **3,203 rows instead of 387, 8.3× more.** Second, `sent_lsn` is nearly identical across all three while `flush_lsn` is not — the WAL was sent to everyone and made durable at very different rates. Third, and this is the one to sit with: **387 commits returned `200 OK` and are gone, and the number of errors returned to those callers is zero.**

That silence is the defining property of asynchronous failover. There is no mechanism by which a caller could be told, because the commit succeeded — the machine that knew about it is what no longer exists. Any reconciliation has to come from outside the database: an idempotency ledger, an event log, the payment processor's own records.

Then there is the failure mode that is worse than losing 387 rows.

**Split brain** is two primaries accepting writes at once. It happens because the failure you detected was not the failure that occurred: the old primary was **partitioned, not dead**. It cannot reach the replicas or the orchestrator, so the orchestrator promotes. But the app servers in its own zone can still reach it, so it keeps accepting and acknowledging writes on a timeline nobody else will ever see.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 512" width="100%" style="max-width:840px" role="img" aria-label="Two timelines of the same network partition. In the upper unfenced timeline the old primary keeps accepting writes for twenty-five seconds because it is only partitioned and not dead, while a new primary is promoted at five seconds, so for twenty seconds both nodes accept writes; the overlap produces ten thousand writes that can never reach the new timeline, one thousand and eighty rows updated on both sides, and five thousand four hundred and eighty-nine writes to those rows that no tool can merge. In the lower fenced timeline the old primary must renew a two-second lease it can no longer reach, so it refuses all writes after two seconds, and promotion is deliberately held until five seconds; the two windows never overlap, so eight hundred writes are still lost but zero rows diverge.">
  <defs>
    <marker id="p11-07-a5" markerWidth="9" markerHeight="9" refX="5.5" refY="3" orient="auto"><path d="M0,0 L6.5,3 L0,6 Z" fill="currentColor"/></marker>
  </defs>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <text x="440" y="24" text-anchor="middle" font-size="14.5" font-weight="700" fill="currentColor">Split brain: the old primary was never dead, only unreachable</text>
    <text x="440" y="42" text-anchor="middle" font-size="10" fill="currentColor" opacity="0.8">both timelines lose data. Only one of them produces rows that disagree with each other.</text>

    <!-- ===== TOP: no fencing ===== -->
    <rect x="14" y="56" width="852" height="182" rx="12" fill="#d64545" fill-opacity="0.06" stroke="#d64545" stroke-width="1.8"/>
    <text x="30" y="78" font-size="12.5" font-weight="700" fill="#d64545">NO FENCING — the old primary runs until a human notices</text>

    <path d="M164 96 L 164 224" fill="none" stroke="#e0930f" stroke-width="2" stroke-dasharray="6 4"/>
    <text x="164" y="92" font-size="9.5" font-weight="700" text-anchor="middle" fill="#e0930f">t=0  PARTITION</text>
    <path d="M264 108 L 264 224" fill="none" stroke="#7c5cff" stroke-width="2" stroke-dasharray="6 4"/>
    <text x="264" y="104" font-size="9.5" font-weight="700" text-anchor="middle" fill="#7c5cff">t=5 s  PROMOTE</text>

    <rect x="264" y="112" width="400" height="98" fill="#d64545" fill-opacity="0.16" stroke="none"/>
    <text x="464" y="128" font-size="11" font-weight="700" text-anchor="middle" fill="#d64545">TWO PRIMARIES · 20 s · both returning 200 OK</text>

    <rect x="60" y="140" width="604" height="26" rx="5" fill="#0fa07f" fill-opacity="0.18" stroke="#0fa07f" stroke-width="1.6"/>
    <rect x="264" y="176" width="400" height="26" rx="5" fill="#3553ff" fill-opacity="0.18" stroke="#3553ff" stroke-width="1.6"/>
    <g fill="currentColor" font-size="9.5">
      <text x="70" y="157" font-weight="700">OLD primary — still accepting writes, still fsyncing them</text>
      <text x="274" y="193" font-weight="700">NEW primary — accepting writes on a fresh timeline</text>
    </g>
    <path d="M60 224 L 760 224" fill="none" stroke="currentColor" stroke-width="1.3" marker-end="url(#p11-07-a5)"/>
    <g fill="currentColor" font-size="9" text-anchor="middle" opacity="0.75">
      <text x="164" y="236">0 s</text><text x="264" y="236">5 s</text><text x="464" y="236">15 s</text><text x="664" y="236">25 s</text>
    </g>
    <g fill="currentColor" font-size="9.5">
      <text x="684" y="146" font-weight="700" fill="#d64545">10,000 writes</text>
      <text x="684" y="159" opacity="0.85">never reach the</text>
      <text x="684" y="171" opacity="0.85">new timeline</text>
      <text x="684" y="190" font-weight="700" fill="#d64545">1,080 rows</text>
      <text x="684" y="203" opacity="0.85">written on BOTH</text>
      <text x="684" y="215" opacity="0.85">— 5,489 writes</text>
    </g>

    <!-- ===== BOTTOM: fencing ===== -->
    <rect x="14" y="252" width="852" height="182" rx="12" fill="#0fa07f" fill-opacity="0.07" stroke="#0fa07f" stroke-width="1.8"/>
    <text x="30" y="274" font-size="12.5" font-weight="700" fill="#0fa07f">LEASE FENCING — the old primary must keep earning the right to write</text>

    <path d="M164 292 L 164 420" fill="none" stroke="#e0930f" stroke-width="2" stroke-dasharray="6 4"/>
    <text x="164" y="288" font-size="9.5" font-weight="700" text-anchor="middle" fill="#e0930f">t=0  PARTITION</text>
    <path d="M204 292 L 204 420" fill="none" stroke="#d64545" stroke-width="2"/>
    <text x="204" y="306" font-size="9.5" font-weight="700" fill="#d64545">t=2 s  LEASE EXPIRES → the old primary refuses every write</text>
    <path d="M264 316 L 264 420" fill="none" stroke="#7c5cff" stroke-width="2" stroke-dasharray="6 4"/>
    <text x="290" y="330" font-size="9.5" font-weight="700" fill="#7c5cff">t=5 s  PROMOTE — held 3 s longer than the lease, on purpose</text>

    <rect x="204" y="336" width="60" height="62" fill="#0fa07f" fill-opacity="0.14" stroke="none"/>
    <text x="234" y="352" font-size="8.5" font-weight="700" text-anchor="middle" fill="#0fa07f">nobody</text>
    <text x="234" y="363" font-size="8.5" font-weight="700" text-anchor="middle" fill="#0fa07f">writes</text>

    <rect x="60" y="336" width="144" height="26" rx="5" fill="#0fa07f" fill-opacity="0.18" stroke="#0fa07f" stroke-width="1.6"/>
    <rect x="264" y="372" width="400" height="26" rx="5" fill="#3553ff" fill-opacity="0.18" stroke="#3553ff" stroke-width="1.6"/>
    <g fill="currentColor" font-size="9.5">
      <text x="70" y="353" font-weight="700">OLD primary</text>
      <text x="274" y="389" font-weight="700">NEW primary — the only writer, and provably so</text>
    </g>
    <path d="M60 420 L 760 420" fill="none" stroke="currentColor" stroke-width="1.3" marker-end="url(#p11-07-a5)"/>
    <g fill="currentColor" font-size="9" text-anchor="middle" opacity="0.75">
      <text x="164" y="432">0 s</text><text x="204" y="432">2 s</text><text x="264" y="432">5 s</text><text x="464" y="432">15 s</text><text x="664" y="432">25 s</text>
    </g>
    <g fill="currentColor" font-size="9.5">
      <text x="684" y="346" font-weight="700" fill="#e0930f">800 writes</text>
      <text x="684" y="359" opacity="0.85">still lost — that</text>
      <text x="684" y="371" opacity="0.85">part is unfixable</text>
      <text x="684" y="390" font-weight="700" fill="#0fa07f">0 rows diverge</text>
      <text x="684" y="403" opacity="0.85">and 0 writes are</text>
      <text x="684" y="415" opacity="0.85">unmergeable</text>
    </g>

    <text x="440" y="464" font-size="11.5" font-weight="700" text-anchor="middle" fill="currentColor">Fencing does not save the lost writes. It converts "we lost 25 s of orders" into "we lost 2 s of orders."</text>
    <text x="440" y="484" font-size="11" text-anchor="middle" fill="currentColor" opacity="0.9">The alternative is 1,080 rows where two committed values both claim to be true, and no rule that picks between them.</text>
    <text x="440" y="504" font-size="10.5" text-anchor="middle" fill="currentColor" opacity="0.85">The old primary can never simply rejoin: it holds WAL the new timeline never saw. Rewind it (pg_rewind) or rebuild it.</text>
  </g>
</svg>
```

The measured difference between fencing and not fencing:

```text
     no fencing — old primary runs until a human notices (25 s)
       writes the OLD primary accepted after the partition     10,000
       rows updated on BOTH timelines                           1,080
       writes to those rows — unmergeable by any tool           5,489

     lease fencing — 2 s TTL, promotion held until 5 s
       writes the OLD primary accepted after the partition     800
       rows updated on BOTH timelines                           0
       writes to those rows — unmergeable by any tool           0
```

Read what fencing does and does not do. **It does not save the old primary's writes — nothing can.** 800 writes are still lost. What it does is drive the **divergent** set to zero: from 1,080 rows carrying 5,489 mutually contradictory writes down to none. That is the difference between "we lost two seconds of orders", which is a bounded, explainable, apologise-and-refund problem, and "1,080 rows have two committed values that both claim to be true and there is no rule that picks between them", which is a problem with no correct ending.

**Fencing** means a node must keep *earning* the right to write rather than assuming it. Practically:

- **Leases.** The primary holds a time-bounded lease and must renew it. If it cannot reach the lease store, its lease expires and **it must stop accepting writes on its own initiative**, without being told. Promotion is held until strictly after the old lease could have expired — above, a 2 s lease and promotion at 5 s, so the overlap is provably zero.
- **Epoch / term numbers.** Every promotion increments a monotonic number stamped on writes and carried to storage. Storage rejects anything with a stale epoch, so a partitioned old primary is refused by the disk itself. This is how Raft and ZooKeeper-based systems do it, and it is the strongest form because it does not depend on clocks.
- **STONITH.** "Shoot The Other Node In The Head" — power off or network-isolate the old primary via an out-of-band path before promoting. Crude, effective, and it needs hardware that is itself reachable during a network problem.

Finally: **the old primary can never simply rejoin.** It holds WAL records for a timeline the new primary never saw and never will. Reattaching it would mean two conflicting histories claiming the same LSNs. It must be rewound to the last common point (`pg_rewind`) or rebuilt from a base backup. Plan for the rebuild time — for a large database it may be hours, and until it finishes you are running with one fewer copy than you designed for, which is when a second failure finds you.

### Routing reads: who decides

Something has to choose primary or replica for every query. There are three places to put that decision.

**The application.** Two connection pools, and the query picks. Maximum precision — the code issuing the query is the only thing that knows whether this read follows a write. It is also the most invasive, and the discipline decays as the codebase grows.

**A proxy** (PgBouncer, ProxySQL, Vitess, RDS Proxy). Central, language-agnostic, and no application change. The catch is that a proxy routing on SQL text alone is guessing: it cannot know that *this* `SELECT` follows *that* user's `UPDATE`. ProxySQL's query rules and a mandatory hint or comment are how this is made explicit rather than inferred.

**The driver.** Many drivers accept `target_session_attrs=read-only` or a replica set read preference. Convenient, and coarse — a per-connection setting, so per-query decisions mean per-query connections.

Whichever you choose, the rule that matters is about the **default**:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 528" width="100%" style="max-width:840px" role="img" aria-label="A read-routing decision table with eight query classes down the left, the node each should be sent to, the consistency you are accepting by doing so, and what actually breaks if you route it wrongly. Writes and anything inside a transaction go to the primary. Read-after-write goes to a replica pinned by log sequence number, falling back to the primary. Money, permissions and inventory checks go to the primary. Another user's profile, feeds, search and analytics go to replicas with increasingly relaxed freshness. A banner across the bottom states the governing rule: the default must be the primary, and replica routing must be an explicit opt-in on each query, because the failure mode of the wrong default is a silent correctness bug rather than a slow page.">
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <text x="440" y="24" text-anchor="middle" font-size="14.5" font-weight="700" fill="currentColor">Read routing: decide per query class, never per service</text>
    <text x="440" y="42" text-anchor="middle" font-size="10" fill="currentColor" opacity="0.8">the third column is the promise you are making to the user; the fourth is the bug you ship if you get it wrong</text>

    <g fill="currentColor" font-size="9" font-weight="700" opacity="0.65">
      <text x="24" y="68">QUERY CLASS</text><text x="242" y="68">ROUTE TO</text><text x="424" y="68">WHAT YOU ACCEPT</text><text x="628" y="68">WHAT BREAKS IF YOU GET IT WRONG</text>
    </g>
    <path d="M20 76 L 860 76" fill="none" stroke="currentColor" stroke-width="1.2" opacity="0.45"/>

    <g fill="none" stroke-width="1.6">
      <rect x="20" y="84" width="212" height="36" rx="6" fill="#0fa07f" fill-opacity="0.13" stroke="#0fa07f"/>
      <rect x="20" y="126" width="212" height="36" rx="6" fill="#0fa07f" fill-opacity="0.13" stroke="#0fa07f"/>
      <rect x="20" y="168" width="212" height="36" rx="6" fill="#3553ff" fill-opacity="0.13" stroke="#3553ff"/>
      <rect x="20" y="210" width="212" height="36" rx="6" fill="#0fa07f" fill-opacity="0.13" stroke="#0fa07f"/>
      <rect x="20" y="252" width="212" height="36" rx="6" fill="#7c5cff" fill-opacity="0.13" stroke="#7c5cff"/>
      <rect x="20" y="294" width="212" height="36" rx="6" fill="#7c5cff" fill-opacity="0.13" stroke="#7c5cff"/>
      <rect x="20" y="336" width="212" height="36" rx="6" fill="#7c5cff" fill-opacity="0.13" stroke="#7c5cff"/>
      <rect x="20" y="378" width="212" height="36" rx="6" fill="#e0930f" fill-opacity="0.13" stroke="#e0930f"/>
    </g>

    <g fill="currentColor" font-size="10">
      <text x="32" y="100" font-weight="700">INSERT / UPDATE / DELETE</text><text x="32" y="114" font-size="8.5" opacity="0.75">and everything inside the transaction</text>
      <text x="32" y="142" font-weight="700">SELECT … FOR UPDATE</text><text x="32" y="156" font-size="8.5" opacity="0.75">any read that takes a row lock</text>
      <text x="32" y="184" font-weight="700">read-after-write</text><text x="32" y="198" font-size="8.5" opacity="0.75">the redirect, the refetch, the toast</text>
      <text x="32" y="226" font-weight="700">money · permissions · stock</text><text x="32" y="240" font-size="8.5" opacity="0.75">balances, entitlements, stock counts</text>
      <text x="32" y="268" font-weight="700">the user's own history</text><text x="32" y="282" font-size="8.5" opacity="0.75">orders, messages, notifications</text>
      <text x="32" y="310" font-weight="700">someone else's profile</text><text x="32" y="324" font-size="8.5" opacity="0.75">feeds, timelines, comment threads</text>
      <text x="32" y="352" font-weight="700">search · listings · browse</text><text x="32" y="366" font-size="8.5" opacity="0.75">already behind a cache and an index</text>
      <text x="32" y="394" font-weight="700">analytics · exports · BI</text><text x="32" y="408" font-size="8.5" opacity="0.75">long scans, big sorts, nightly jobs</text>
    </g>

    <g font-size="10" font-weight="700">
      <text x="242" y="106" fill="#0fa07f">PRIMARY</text>
      <text x="242" y="148" fill="#0fa07f">PRIMARY</text>
      <text x="242" y="184" fill="#3553ff">REPLICA, LSN-PINNED</text><text x="242" y="197" font-size="8.5" font-weight="400" fill="currentColor" opacity="0.75">primary if none has caught up</text>
      <text x="242" y="232" fill="#0fa07f">PRIMARY</text>
      <text x="242" y="268" fill="#7c5cff">REPLICA, SESSION-PINNED</text><text x="242" y="281" font-size="8.5" font-weight="400" fill="currentColor" opacity="0.75">hash(user_id) → one replica</text>
      <text x="242" y="316" fill="#7c5cff">ANY REPLICA</text>
      <text x="242" y="358" fill="#7c5cff">ANY REPLICA</text>
      <text x="242" y="394" fill="#e0930f">A DEDICATED REPLICA</text><text x="242" y="407" font-size="8.5" font-weight="400" fill="currentColor" opacity="0.75">its own node, never a shared one</text>
    </g>

    <g fill="currentColor" font-size="9" opacity="0.92">
      <text x="424" y="100">linearizable — one copy</text><text x="424" y="113" opacity="0.7">there is no other option</text>
      <text x="424" y="142">the lock only exists here</text><text x="424" y="155" opacity="0.7">a replica cannot take one</text>
      <text x="424" y="184">read-your-writes, exactly</text><text x="424" y="197" opacity="0.7">+0.30 ms mean, 1.32% to primary</text>
      <text x="424" y="226">no staleness at all</text><text x="424" y="239" opacity="0.7">the money must be current</text>
      <text x="424" y="268">monotonic reads</text><text x="424" y="281" opacity="0.7">never goes backwards for them</text>
      <text x="424" y="310">seconds of staleness</text><text x="424" y="323" opacity="0.7">nobody can tell, nobody asked</text>
      <text x="424" y="352">seconds of staleness</text><text x="424" y="365" opacity="0.7">the cache is already staler</text>
      <text x="424" y="394">minutes of staleness</text><text x="424" y="407" opacity="0.7">and isolation from the buffer pool</text>
    </g>

    <g font-size="9">
      <text x="628" y="100" fill="#d64545" font-weight="700">a replica cannot accept a write at all</text>
      <text x="628" y="113" fill="currentColor" opacity="0.7">at least this one fails loudly</text>
      <text x="628" y="142" fill="#d64545" font-weight="700">ERROR: cannot execute in a read-only txn</text>
      <text x="628" y="155" fill="currentColor" opacity="0.7">also loud — the last loud one</text>
      <text x="628" y="184" fill="#d64545" font-weight="700">61.65% of them show the OLD value</text>
      <text x="628" y="197" fill="currentColor" opacity="0.7">"it fixed itself when I refreshed"</text>
      <text x="628" y="226" fill="#d64545" font-weight="700">double-spend, oversell, ghost access</text>
      <text x="628" y="239" fill="currentColor" opacity="0.7">receipt says unpaid; support cannot repro</text>
      <text x="628" y="268" fill="#d64545" font-weight="700">their comment appears, then vanishes</text>
      <text x="628" y="281" fill="currentColor" opacity="0.7">96% of 8-widget page loads, measured</text>
      <text x="628" y="310" fill="#e0930f" font-weight="700">a post shows up a second late</text>
      <text x="628" y="323" fill="currentColor" opacity="0.7">this is the one you are allowed to accept</text>
      <text x="628" y="352" fill="#e0930f" font-weight="700">a listing lingers after deletion</text>
      <text x="628" y="365" fill="currentColor" opacity="0.7">fix it at the cache, not at the router</text>
      <text x="628" y="394" fill="#d64545" font-weight="700">one report evicts the OLTP working set</text>
      <text x="628" y="407" fill="currentColor" opacity="0.7">and every user-facing read goes to disk</text>
    </g>

    <rect x="20" y="428" width="840" height="56" rx="10" fill="#d64545" fill-opacity="0.12" stroke="#d64545" stroke-width="2"/>
    <g fill="currentColor">
      <text x="40" y="450" font-size="12" font-weight="700" fill="#d64545">THE RULE: the default connection is the PRIMARY. Replica routing is an explicit opt-in, per query.</text>
      <text x="40" y="470" font-size="10" opacity="0.92">Default-to-replica fails silently, and a customer finds it. Default-to-primary fails as a capacity graph you can watch.</text>
    </g>
    <text x="440" y="506" font-size="11" text-anchor="middle" fill="currentColor" opacity="0.9">Only the top three rows are ever worth arguing about. If you cannot say which class a query is in, it belongs on the primary.</text>
  </g>
</svg>
```

> **The default connection must be the primary. Replica routing is an explicit, per-query opt-in.**

The asymmetry in the failure modes is the entire argument. Default-to-replica fails **silently and correctly-looking**: a stale read returns a plausible number, no error, no log, no metric, and a customer finds it weeks later — the 11:20 ticket. Default-to-primary fails **loudly and gradually**: primary CPU rises, and you watch it on a graph and move query classes off it deliberately. One failure mode is a correctness bug you cannot see; the other is a capacity problem you can. Choose the one you can see.

The corollary in the diagram is the one to keep: **if you cannot say which class a query is in, it belongs on the primary.** Uncertainty is not evidence that staleness is acceptable.

## Build It

[`code/replication.py`](code/replication.py) is one file, standard library only, seeded with `random.Random(7)`, and runs in about a second. It models a primary WAL and three replicas, then runs six arguments over that one world.

The core of the model is that a replica's position is bounded **two different ways, and both bind at different times**. A latency floor (wire + fsync + apply scheduling) sets how far behind it sits while keeping up. A throughput ceiling (bytes per millisecond it can flush and replay) sets what happens when the primary outruns it. Real lag is whichever binds:

```python
def _positions(self, lag, upstream, bw):
    """Position under a latency floor, an upstream bound and a bandwidth cap."""
    out = [0] * NG
    run = 0
    for i in range(NG):
        p = self.lsn_at(i * GRID_MS - lag[i])
        if upstream is not None:
            if upstream[i] < p:
                p = upstream[i]
            cap = run + (bw[i] if isinstance(bw, list) else bw) * GRID_MS
            if cap < p:
                p = int(cap)
        if p > run:                       # never un-apply WAL
            run = p
        out[i] = run
    return out
```

The `upstream` argument is what enforces the ordering that makes the three lags real: send is bounded by the primary, flush is bounded by send, replay is bounded by flush. A replica cannot apply what it has not received. The `if p > run` line is the monotonicity property the whole lesson leans on — **a position never moves backwards**, which is why pinning to one replica gives you monotonic reads for free.

The replay conflict is a change to one array, not a special case in the logic — the standby's apply bandwidth collapses to 30 B/ms for twelve seconds while its flush bandwidth is untouched:

```python
if conflict:
    lo, hi = conflict[0] // GRID_MS, conflict[1] // GRID_MS
    for i in range(lo, hi):
        abw[i] = 30.0                 # replay is blocked, not slow
    for i in range(hi, min(NG, hi + 6_000)):
        abw[i] = apply_bw * 1.8       # then it catches up flat out
```

And the LSN-pinned read is the whole fix, in ten lines. Note that the loop is bounded and the fallback is unconditional — correctness does not depend on the wait succeeding:

```python
if policy == "lsn":
    # Ask the router for a replica that has already replayed `need`.
    elapsed = 0.0
    while True:
        ok = [k for k in range(w.k) if w.replay(k, t + elapsed) >= need]
        if ok:
            break
        if elapsed >= PIN_WAIT_MS:
            ok = None
            break
        elapsed += POLL_MS
    if ok is None:
        on_primary += 1
        ...
```

Run it:

```bash
docker compose exec -T app python \
  phases/11-scalability-and-reliability/07-read-replicas-and-replication-lag/code/replication.py
```

```console
== 1 · ASYNC REPLICATION AND THE STALE-READ RATE ==
  primary: 64,331 commits over 120 s (400 commits/s, 16.0 MB of WAL)
  sections 1-3 use the CALM window (0-84 s). Nothing is
  wrong here: no incident, no failover, every replica healthy.
  replica replay lag, sampled 1,200x per replica:
     replica          p50        p90        p99        max
     r1-same-az       11.7ms     33.7ms     51.6ms     77.3ms
     r2-same-az       18.8ms   2980.0ms   7825.8ms   8324.0ms
     r3-cross-az      33.1ms     94.8ms    143.3ms    185.1ms

  10,473 write-then-read-a-replica trials per row:
     read delay      stale reads     what that delay is
          5 ms       83.91%       same-process read-back
         12 ms       61.65%       HTTP 302 redirect after POST
         25 ms       38.83%       a fast SPA refetch
         50 ms       17.39%       user clicks 'back'
        100 ms        8.31%       a slow page load
        250 ms        5.03%       a human re-reads the page
       1000 ms        4.85%       a second later
       5000 ms        2.22%       five seconds later

  THE HEADLINE: your redirect takes 12 ms. Your median replica is
  12-33 ms behind.
  61.7% of read-after-write requests read a value older than the
  one the user just saved. Every one of them 'fixes itself' on refresh.

  And read the bottom of the column: waiting 5 SECONDS still leaves
  2.22% stale. The curve does not decay to zero — it decays to
  your WORST replica. r2 spends 12 s of this window with a replay
  conflict; a read routed there is stale no matter how long you wait.
  There is no delay you can add to a request that makes this correct.

== 2 · THE THREE FIXES: NAIVE / STICKY WINDOW / LSN-PINNED ==
  60,000 reads. 20% follow this session's own write;
  8% of those arrive on a second device/session.
  sticky window = 500 ms; LSN pin waits up to 10 ms then falls back to the primary.
  replica read = 1.1 ms, primary read = 1.8 ms.

     policy                 stale reads      reads on primary   mean read   p99 read
     naive: always replica    6,844 (11.41%)         0 ( 0.00%)      1.10ms     1.10ms
     sticky-to-primary 500ms     47 ( 0.08%)    11,113 (18.52%)      1.23ms     1.80ms
     LSN-pinned read              0 ( 0.00%)       795 ( 1.32%)      1.40ms    11.80ms

  sticky removed 99.3% of the stale reads and gave
  back 18.52% of read traffic to the primary. The 47 it missed are
  the cross-device ones — the sticky flag lives in the wrong session.
  LSN pinning removed 100% of them and sent only 1.32% to the
  primary — 14.0x less primary load than sticky — for +0.30 ms of mean latency.

== 3 · MONOTONIC READS: WATCHING TIME RUN BACKWARDS ==
  'backwards' = a read shows LESS committed data than a read this
  same session already saw. A comment appears, then disappears.
  A single replica's position only ever moves forward. The SET of
  replicas does not, and round-robin walks the set.

  A · one page load, 8 widgets fanned out 6 ms apart  (4,000 sessions)
     routing                        backwards events   sessions affected
     round-robin over 3 replicas        12,119       3,857/4,000
     session pinned to one replica           0           0/4,000
     last-seen-LSN token                     0           0/4,000

  B · a feed polling every 250 ms for 30 s  (400 sessions)
     routing                        backwards events   sessions affected
     round-robin over 3 replicas         3,869         319/400
     session pinned to one replica           0           0/400
     last-seen-LSN token                     0           0/400

== 4 · SYNC vs ASYNC vs QUORUM: LATENCY, RPO, AND THE STALL ==
  30,000 commits. local fsync ~0.4 ms. Same-AZ RTT 0.5 ms,
  cross-AZ 1.4 ms, cross-region 71.0 ms (AZ = Availability Zone).

     mode                            p50       p99       max     RPO (rows lost on failover)
     async                          0.42ms    4.63ms    35.24ms   p50 1 rows calm / 398 under load
     sync-1 same-az                 1.08ms    7.01ms   106.77ms   0
     sync-1 cross-az                2.21ms    8.42ms    76.11ms   0
     sync-1 cross-region           88.88ms  184.24ms   353.73ms   0
     quorum ANY 1 of 3              1.01ms    5.22ms    35.92ms   0 — if you promote the acking replica
     sync-1 (replica stalls 5 s)    1.13ms 4701.99ms  5001.01ms   0 rows, and 0 writes for 5 s

  The stall row is the availability inversion: 5,000 commits blocked behind
  a healthy-looking replica, max wait 5001 ms. Your primary's uptime is now
  the AND of every synchronous standby. Quorum turns it into an OR.

  ASYNC RPO IS NOT ONE NUMBER. Rows lost if the primary dies now:
    on a calm system   p50     1   p99     5   worst     6 acknowledged commits
    during the batch   p50   398   p99   639   worst   647 acknowledged commits
  128x worse, and the batch job is exactly the thing most likely to
  kill the primary. Your RPO is your lag DURING the incident, never
  the median on the dashboard. The arithmetic is just a product:
    calm:  flush lag   4.3 ms x   400 commits/s =    1.7 rows  (measured 1)
    load:  flush lag 167.6 ms x 2,400 commits/s =  402.3 rows  (measured 398)

== 5 · FAILOVER: THE LOSS WINDOW AND SPLIT BRAIN ==
     replica          sent_lsn     flush_lsn    replay_lsn   flush lag   rows not durable
     r1-same-az      11.0467 MB    10.8900 MB    10.6485 MB     269.7ms          635
     r2-same-az      11.0456 MB    10.9515 MB    10.5174 MB     164.4ms          387
     r3-cross-az     11.0359 MB    10.2478 MB     9.9153 MB    1341.1ms        3,203

  Promote the most-caught-up replica (r2-same-az):
    acknowledged commits ..................... 44,283
    acknowledged AND durable on the new primary 43,896
    ACKNOWLEDGED AND GONE .................... 387
    the loss window .......................... the last 164 ms before death
    errors returned to any of those callers .. 0
    RPO = flush lag x commit rate = 164 ms x 2,400/s = 395 rows  (measured: 387)
    promote the WRONG replica instead and it is 3,203 rows —
    8.3x more. 'Promote by highest LSN' is not a nicety.

     no fencing — old primary runs until a human notices (25 s)
       writes the OLD primary accepted after the partition     10,000
       writes the NEW primary accepted while it still ran       8,000
       rows updated on BOTH timelines                           1,080
       writes to those rows — unmergeable by any tool           5,489
       writes that can never reach the new timeline             10,000

     lease fencing — 2 s TTL, promotion held until 5 s
       writes the OLD primary accepted after the partition     800
       writes the NEW primary accepted while it still ran       0
       rows updated on BOTH timelines                           0
       writes to those rows — unmergeable by any tool           0
       writes that can never reach the new timeline             800

== 6 · REPLICAS SCALE READS. THEY NEVER SCALE WRITES. ==
  One node does 20,000 ops/s. You are offered 60,000 ops/s.
  EVERY replica applies 100% of the writes; only the reads divide.

     write %      W ops/s   R ops/s   replicas   total system work   amplif.   useful new machine
       1.0%          600    59,400          4            62,400     1.04x          97% reads
       5.0%        3,000    57,000          4            72,000     1.20x          85% reads
      10.0%        6,000    54,000          4            84,000     1.40x          70% reads
      16.7%       10,000    50,000          5           110,000     1.83x          50% reads
      20.0%       12,000    48,000          6           132,000     2.20x          40% reads
      25.0%       15,000    45,000          9           195,000     3.25x          25% reads
      30.0%       18,000    42,000         21           438,000     7.30x          10% reads
      33.0%       19,800    40,200        201         4,039,800    67.33x           1% reads
      35.0%       21,000    39,000   IMPOSSIBLE    — every replica is already saturated by writes alone

== APPENDIX · SEND vs FLUSH vs REPLAY LAG ON ONE REPLICA (r2) ==
  a 12 s query conflict on the standby starting at t = 40 s.
  send and flush stay flat — the WAL ARRIVED. Replay does not.
       t      send lag   flush lag   replay lag   replay bytes behind
       36s      1.59ms       9.84ms         9.8ms            1.1 KB
       40s      7.99ms       7.99ms        11.6ms            0.8 KB
       43s      2.77ms       2.77ms      2129.3ms          204.4 KB
       46s      2.92ms       2.92ms      4239.6ms          409.5 KB
       49s      2.43ms       3.63ms      6319.9ms          598.9 KB
       52s      3.78ms       3.78ms      8324.0ms          788.3 KB
       55s      1.31ms       1.31ms         8.5ms            1.7 KB
       62s      1.05ms      18.30ms        18.3ms            0.2 KB
       70s      2.87ms       2.87ms         6.6ms            0.2 KB
```

Six arguments, and the ones that should change how you build things are 1, 2 and 5.

**Section 1 is the scale of the problem.** The p50 lags — 11.7 ms, 18.8 ms, 33.1 ms — are exactly the numbers that make a dashboard look healthy, and they produce a **61.65% stale rate at a 12 ms redirect.** Look also at r2's row: a p50 of 18.8 ms and a **p99 of 7,825.8 ms.** A single "replication lag" number on a dashboard is almost always a p50 or an average, and for this replica the p50 is off by more than a factor of 400 from the tail that hurts users.

**Section 2 is the answer to the whole lesson.** Three policies over the identical 60,000-read trace. Naive: 11.41% stale. Sticky: 0.08% stale but **18.52% of all reads pushed back onto the primary**, and the residue is the cross-device case that a session flag structurally cannot fix. LSN-pinned: **zero stale reads, 1.32% on the primary, +0.30 ms mean.** It is better on every axis simultaneously, which is rare enough to be worth noticing.

**Section 3** is the one that reframes staleness as an ordering problem rather than a freshness problem. 96% of eight-widget page loads observed time moving backwards, with no incident and no unhealthy replica.

**Section 4** prices the durability spectrum. Same-AZ sync is +0.66 ms — usually worth it. Cross-region sync is **+88.5 ms, a 211× commit** — usually a different product. The stall row is the availability inversion: **5,000 commits blocked for 5 seconds behind a replica that was never marked unhealthy.**

**Section 5** is the number to carry into design reviews. **387 acknowledged commits gone, zero errors, 8.3× worse if you promote the wrong replica** — and split brain producing **1,080 rows with 5,489 unmergeable writes** that fencing takes to zero.

**Section 6** is the wall, and the reason Lesson 8 exists. Past a 16.7% write ratio, each replica you buy adds more write work than the read work it relieves.

## Use It

Postgres exposes every number in this lesson, and the one view to know is `pg_stat_replication` on the **primary** — one row per connected standby:

```sql
SELECT application_name,
       sent_lsn, write_lsn, flush_lsn, replay_lsn,
       pg_wal_lsn_diff(pg_current_wal_lsn(), sent_lsn)   AS send_bytes,
       pg_wal_lsn_diff(pg_current_wal_lsn(), flush_lsn)  AS flush_bytes,   -- your RPO
       pg_wal_lsn_diff(pg_current_wal_lsn(), replay_lsn) AS replay_bytes,  -- what reads see
       write_lag, flush_lag, replay_lag
FROM pg_stat_replication;
```

The four LSN columns map exactly onto the three lags:

- `sent_lsn` — what the primary has put on the wire.
- `write_lsn` — what the standby has written to the OS. **Not durable**: it is in the page cache, and a power loss takes it.
- `flush_lsn` — what the standby has `fsync`ed. **This is the failover line.** Everything past it is what you lose. This is the column your RPO alert reads.
- `replay_lsn` — what is visible to queries on the standby. **This is the column your staleness alert reads.**

`pg_wal_lsn_diff()` gives the honest **byte** distance; the `*_lag` columns give time-based estimates with the caveat from The Concept — on a quiet primary they read zero regardless of the truth. Use bytes for alerting and time for human-readable context. On the standby itself, `pg_last_wal_replay_lsn()` is the position an LSN-pinned router polls, and it is cheap enough to call per health check.

**`synchronous_commit` is the durability dial**, and each level promises something specific:

| Value | The primary acks after… | You lose on… |
|---|---|---|
| `off` | writing to its own WAL buffer, not even a local flush | a primary crash — **local data loss, no replica involved** |
| `local` | its own `fsync` only | a primary loss: everything not yet on a replica |
| `remote_write` | the standby has `write()`n it to the OS | the standby's **machine** dying (page cache, not disk) |
| `on` | the standby has `fsync`ed it | nothing, if the standby survives — the usual "synchronous" |
| `remote_apply` | the standby has **applied** it and it is query-visible | nothing — and this is the only level that makes replica reads non-stale |

Two of those are commonly misunderstood. `remote_write` sounds durable and is not: the bytes are in the standby's page cache, so a standby that loses power loses them. And **`remote_apply` is the only setting that solves stale reads at the database layer** — every commit waits for the standby to make it visible. It is correct and it is expensive: your write latency becomes the *slowest* standby's replay latency, and any replay conflict now stalls the primary. This is why LSN pinning is the better answer: it pays the cost only on the reads that actually need freshness, rather than on every write.

Set the quorum, not a single standby:

```text
# postgresql.conf — the primary
synchronous_standby_names = 'ANY 2 (r1, r2, r3)'   # any 2 of 3, not one named node
synchronous_commit = on                            # standby fsync before ack
```

`ANY 2 (...)` is the OR from section 4: a single slow standby is simply not one of the two you waited for. **`FIRST 1 (r1, r2, r3)` is the trap** — it always prefers `r1`, so a sick `r1` blocks every write. And note the emergency behaviour: with `synchronous_standby_names` set and *no* standby available, Postgres **blocks writes indefinitely** rather than degrading to async. That is the correct default (it is what "no data loss" means) but you must know it, because clearing the setting is then the fastest way to restore writes — at the cost of the guarantee.

On the standby, two settings control the replay-conflict trade:

```text
# postgresql.conf — the standby
hot_standby_feedback = on          # tell the primary about our oldest snapshot
max_standby_streaming_delay = 30s  # how long replay waits before cancelling a query
```

These are two sides of one problem: the standby is replaying WAL that removes row versions a long-running query on the standby still needs ([Isolation Levels & MVCC](../../03-relational-databases/12-isolation-levels-and-mvcc/) is the mechanism).

- **`hot_standby_feedback = on`** tells the primary to hold those row versions back. Queries stop being cancelled — and the primary now accumulates **bloat** on behalf of a query running on another machine. A runaway analytics query on a standby can bloat the primary's tables badly.
- **`max_standby_streaming_delay`** is the other choice: let replay wait this long, then cancel the query with `ERROR: canceling statement due to conflict with recovery`. Bounded lag, angry analysts.

There is no setting that gives both. Pick per replica: `hot_standby_feedback = on` with a short `max_standby_streaming_delay` on a dedicated analytics replica, and the opposite on replicas serving user traffic where lag is the thing you cannot afford. **Setting `max_standby_streaming_delay = -1` (wait forever) on a user-facing replica is how you get the eight-second stale reads from section 1 with nothing in the log.**

**MySQL** reaches the same place with different vocabulary. A **GTID** (Global Transaction Identifier, `server_uuid:N`) names each transaction globally rather than by file offset, which makes "has this replica applied my transaction?" answerable without knowing which binary log file it landed in — the same primitive as an LSN, and `WAIT_FOR_EXECUTED_GTID_SET()` is MySQL's LSN-pinned read. Semi-synchronous replication (`rpl_semi_sync_source_enabled`) waits for a replica to acknowledge receipt with `rpl_semi_sync_source_timeout` controlling how long before it **silently degrades to asynchronous** — an important difference from Postgres, which blocks. Use `binlog_format = ROW`, never `STATEMENT`.

**On AWS**, two features are constantly confused and they are genuinely different mechanisms:

- **RDS Multi-AZ** is a *standby you cannot read*. Synchronous physical replication to a second AZ purely for availability; it serves no traffic and does not reduce primary load at all. It buys RPO ≈ 0 and automatic failover in 60–120 seconds.
- **RDS read replicas** are *asynchronous* copies you can read from — read scaling, with every consistency problem in this lesson, and no RPO guarantee.

They solve different problems and most production systems need both. **Aurora** changes the story: compute and storage are separated, the six-way replicated storage layer is shared by all instances, and replicas read the same volume rather than replaying a log into their own copy. Replica lag becomes the time to invalidate cached pages — typically **10–20 ms rather than seconds** — and it does not grow with write volume the way log replay does. It does not become zero, so read-your-writes still needs handling. Watch `ReplicaLag` in CloudWatch, plus `AuroraReplicaLagMaximum` across the fleet.

**Alerting**, with the practice from [Alerting & On-Call](../../09-logging-monitoring-and-observability/10-alerting-and-on-call/) — alert on the byte-distance signals, and page on the two that mean different things:

| Signal | Warn | Page | Why |
|---|---|---|---|
| `flush_bytes` (per standby) | > 5 MB for 2 min | > 50 MB for 1 min | This is RPO. 50 MB at 250 B/commit ≈ **200,000 commits** you would lose. |
| `replay_bytes` (per standby) | > 2 MB for 2 min | > 20 MB for 2 min | This is staleness. Users are being served old rows right now. |
| `replay_lag` seconds | > 1 s for 5 min | > 10 s for 2 min | Human-readable context. **Never the only signal** — reads zero on a stalled quiet replica. |
| standby count in `pg_stat_replication` | < expected | < expected for 1 min | A disconnected standby often reports *no* lag rather than infinite lag. |
| `pg_replication_slots.active = false` | any | > 5 min | An inactive slot **retains WAL forever** and will fill the primary's disk. |

Convert the byte thresholds into the number your business actually cares about — `flush_bytes / bytes_per_commit` is commits at risk — and put *that* on the dashboard. "50 MB behind" means nothing in an incident channel; "we would lose about 200,000 orders" ends the discussion immediately.

That last row deserves emphasis because it takes primaries down. A **replication slot** guarantees the primary retains WAL until the standby has consumed it. If a standby is destroyed without dropping its slot, the primary keeps every WAL segment forever and eventually fills its disk, which stops all writes. **An orphaned replication slot is an outage on a timer.** Alert on `active = false`, always.

## Think about it

1. Your read-after-write fix is a 500 ms sticky-to-primary window and it works in every test. A user writes on their phone and reads on their laptop 200 ms later. Trace exactly what happens and why no amount of tuning the window fixes it. Now suppose you move the sticky flag from a cookie to a shared Redis keyed by user ID — what does that fix, what does it cost, and what have you just re-created from Lesson 6?
2. You set `synchronous_standby_names = 'FIRST 1 (r1, r2)'` and `synchronous_commit = on`. At 03:00 the `r1` machine's disk begins responding in 4 seconds instead of 0.5 ms — it is not down, and every health check passes. Describe what your users experience, what your dashboards show, and which single character you would change to prevent it.
3. Section 4 measured an RPO of 1 row calm and 398 rows during the batch job. You are asked for "our RPO" for a compliance document. What number do you give, how do you justify it, and what would you have to change about the system to be able to write a number you can actually defend?
4. Your router picks any replica that has replayed past the client's LSN token. Under a sustained batch job, all three replicas fall behind the tokens and every read falls back to the primary — the primary's load doubles at exactly the moment it is already struggling. Design the degradation: what do you give up first, and how does the client learn that what it is being handed is not what it asked for?
5. You have consistent prefix today because one totally-ordered WAL feeds every replica. Lesson 8 splits the data across four shards. Name two user-visible behaviours that become possible the day you shard, and say what it would cost to prevent each one.

## Key takeaways

- **Replicas scale reads and never writes, and the ceiling is computable.** Every replica applies 100% of write volume, so read capacity per replica is `C − W`. Measured at C = 20,000 ops/s: a 10% write ratio makes a new machine **70% useful**, 30% makes it **10% useful and needs 21 machines to perform 438,000 operations for 60,000 of demand (7.3× amplification)**, and past a **16.7% write ratio (W = C/2)** each replica adds more write work than the read work it relieves.
- **Read-after-write staleness is the common case, not a tail event.** With replicas 12–33 ms behind and healthy, **61.65% of reads following a write returned the old value at a 12 ms redirect** — and waiting longer does not fix it, because the curve decays toward your worst replica, not toward zero: **2.22% still stale after five full seconds.**
- **LSN pinning beats sticky-to-primary on every axis.** The write returns its log position; the read demands a replica that has reached it, waits up to 10 ms, then falls back to the primary. Measured: **0 stale reads out of 60,000 with 1.32% of reads on the primary, versus sticky's 0.08% stale with 18.52% on the primary — 14× less primary load, for +0.30 ms of mean latency**, no session state, and it works across devices.
- **Monotonic reads break with no incident at all.** Round-robin across three healthy replicas made time run backwards in **3,857 of 4,000 (96%) eight-widget page loads**. A single replica never moves backwards; the *set* does, and round-robin walks the set. One hash or one integer in a cookie takes it to zero.
- **There are three lags and the popular metric watches the wrong one.** Measured on one replica during a query conflict: send and flush lag stayed at **1–18 ms** — every byte arrived on time — while replay fell **788 KB / 8.3 seconds behind**, serving eight-second-old rows with nothing logged, because the 30 s `max_standby_streaming_delay` never fired. Alert on **byte distance**, not time: time-based lag reads zero on a stalled replica when writes stop.
- **Sync durability is cheap nearby and a different product far away — and it inverts your availability.** Same-AZ sync costs **+0.66 ms (2.6× commit)**; cross-region costs **+88.5 ms (211×)**. One synchronous standby stalling for 5 s blocked **5,000 commits at a p99 of 4,702 ms** while looking healthy. `ANY 2 (...)` turns that AND into an OR.
- **Your RPO is your lag during the incident, and it is silent.** The same system loses **1 row on a calm failover and 398 during the batch job (128× worse)** — and the batch job is what kills primaries. In the measured failover, **387 acknowledged commits vanished with zero errors returned**, and promoting the wrong replica would have lost **3,203 — 8.3× more**.
- **Fencing does not save the old primary's writes; it prevents the unmergeable ones.** Unfenced split brain produced **1,080 rows on two timelines carrying 5,489 contradictory writes**. A 2 s lease with promotion held to 5 s produced **0 divergent rows** — still 800 writes lost, but bounded and explainable. And the old primary can never simply rejoin: rewind it or rebuild it.
- **The default connection must be the primary; replica routing is a per-query opt-in.** Default-to-replica fails silently as a correctness bug a customer finds; default-to-primary fails loudly as a capacity graph you can watch. If you cannot say which class a query is in, it belongs on the primary.

Next: [Sharding the Data Tier](../08-sharding-the-data-tier/) — replicas hit a wall at a 16.7% write ratio because every machine holds every row. Sharding is the only way past it, and it costs you transactions, joins, global uniqueness, and the consistent-prefix guarantee this lesson got for free.
