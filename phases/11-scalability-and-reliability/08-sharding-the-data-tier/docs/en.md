# Sharding the Data Tier

> Replicas scale reads. Nothing scales writes except splitting the data across machines that do not know about each other — and the moment you do that, you lose transactions, joins, global uniqueness, and the ability to run a query that does not carry the shard key. Measured here: hashing 500 tenants across 8 shards spread them perfectly and still put **47.7% of all writes on one machine**, a query touching 8 shards has a p99 of **409 ms against a single shard's 61 ms**, and adding one machine to an 8-shard `hash % N` layout moves **88.9% of the database**. The shard key is the most expensive decision in the system and you make it on day one.

**Type:** Build
**Languages:** Python
**Prerequisites:** [Read Replicas & Replication Lag](../07-read-replicas-and-replication-lag/), [Indexes & the B-Tree](../../03-relational-databases/09-indexes-and-the-btree/), [Data Modeling by Access Pattern](../../04-nosql-and-data-modeling/07-data-modeling-by-access-pattern/)
**Time:** ~85 minutes

## The Problem

Eighteen months ago the writes outgrew the machine. Not the storage — storage you can buy. **Writes.** The primary sat at 84% CPU pushing 30,000 inserts a second, the write-ahead log was the disk's whole budget, and the next instance size up was 30% more CPU for 2.2× the money. You had already done the cheap things: fixed the two sequential scans, added the covering index, moved reporting to a read replica, put the product catalogue in Redis. Lesson 7 gave you three replicas and they absorbed every read in the system. None of that touched the write path, because **every replica replays every write.** Adding a replica adds write work; it does not remove any.

So you sharded. `shard_id = hash(user_id) % 8`, eight independent Postgres primaries, each with its own disk, its own connection pool, its own page cache. It took a quarter. It worked. For a year it was the best decision the team ever made.

Then four things happen, in this order, and not one of them is a bug.

**Month 13 — one customer becomes 40% of the database.** The enterprise account you signed in Q2 finishes rolling out. Their tenant now generates 40% of all writes on the platform. `user_id` hashes uniformly, so their users are spread across all eight shards — except their integration writes through three service accounts, and those three `user_id`s hash to shard 3. Shard 3 is at 91% CPU with a 400 ms p99. Shards 0, 1, 2, 4, 5, 6 and 7 are at 11%. You cannot add capacity to shard 3 without adding it to all eight, and you cannot move those three users, because their shard is a pure function of their id.

**Month 14 — the query that used to be free stops working.** Support has always run `SELECT * FROM orders WHERE created_at > now() - interval '1 hour'`. It has no `user_id` in it, because "recent orders" is not a per-user question. Before sharding it was an index range scan. Now it is a **scatter-gather**: fan out to all eight shards, wait for all eight, merge, sort, limit. Its latency is not the average of eight shards. It is the **maximum** of eight shards, and one of the eight is always the slow one. The dashboard that used to load in 40 ms now loads in 400, and nobody changed the query.

**Month 15 — the refund that cannot be a transaction.** Finance needs to move a credit from one account to another. Both accounts are rows in `balances`. They are on different shards. There is no `BEGIN` that covers two Postgres servers. Everything you learned about atomicity — [Transactions & ACID](../../03-relational-databases/11-transactions-and-acid/) — was a guarantee provided by *one* database process, and you now have eight of them that have never heard of each other. The two-statement transaction that was correct for four years is now two independent writes with a window between them where the money exists twice, or not at all.

**Month 16 — you need a ninth machine.** Not sixteen. Nine. You have 8 shards at 70% and you want headroom for Black Friday. `hash(user_id) % 8` becomes `hash(user_id) % 9`, and **88.9% of every row in the database now lives on the wrong machine** — measured below. So you do not add one machine. You add eight, because doubling is the only resize your mapping supports, and you move half the database to do it, while it is serving production traffic.

None of these are bugs. There is no stack trace, no bad deploy, no misconfiguration. They are all **the shard key**, decided in a design doc eighteen months ago by people who had never operated a sharded system, and it is the one decision in the entire architecture you cannot change with a migration.

This lesson is about making that decision on purpose, and about the one procedure that gets you out when you made it wrong.

## The Concept

### Sharding vs partitioning vs replication

These three words are used interchangeably in blog posts, product docs and interviews, and they mean three different things. Getting them exactly right is not pedantry — the difference determines whether you still have transactions.

**Replication** = the same data, many copies. Every replica holds every row. It scales *reads* and provides *redundancy*, and it is what Lesson 7 built. It does nothing for write throughput, because every copy must apply every write.

**Partitioning** = splitting one logical table into several physical pieces by some key. Postgres calls this **declarative partitioning**: `PARTITION BY RANGE (created_at)` gives you `orders_2026_01`, `orders_2026_02` and so on. The planner prunes partitions it does not need, `VACUUM` runs per partition, and dropping last year's data is a `DROP TABLE` instead of a `DELETE` of 400 million rows.

**Sharding** = partitioning **across independent machines**, each with its own CPU, its own disk, its own memory, its own failure, and its own view of the world in which the other shards do not exist.

That last clause is the whole lesson. Postgres declarative partitioning is *single-machine* partitioning: all partitions live in one server, so one `BEGIN` still covers all of them, a foreign key can still point across them, `SELECT` can still join them, and a `UNIQUE` constraint is still global. **Everything you know still works.** The moment those partitions become eight separate servers, the transaction manager that made all of that true is gone. There is no process anywhere that can see two shards at once and hold a lock on both.

So: partitioning is a physical layout optimisation you can adopt on a Tuesday and revert on a Wednesday. Sharding is a distributed system you now operate. They are not points on the same spectrum.

### When to shard — and the strong case for not doing it yet

Sharding is the most expensive scaling move available, and it is frequently done years early. Work down this list, and only shard when everything above it is genuinely exhausted:

1. **Fix the queries and the indexes.** A missing index is a 1000× difference. [Query Planning & EXPLAIN](../../03-relational-databases/10-query-planning-and-explain/) will usually find more headroom in an afternoon than sharding finds in a quarter.
2. **Scale up.** Lesson 1 measured what one machine actually does. A modern server with 128 cores and NVMe (Non-Volatile Memory Express, the flash-storage interface) handles workloads that people shard for. It is the cheapest engineer-hour-per-QPS on the list.
3. **Add read replicas.** Lesson 7. If your load is 95% reads — most OLTP (Online Transaction Processing) workloads are — replicas solve it outright.
4. **Cache.** Phase 5. A 90% cache hit rate is a 10× reduction in database load for a fraction of the effort of sharding.
5. **Move cold data out.** Most tables are 5% hot. Archive rows older than 90 days to object storage or a columnar warehouse and the working set fits in RAM again.
6. **Partition on one machine.** Postgres declarative partitioning. Smaller indexes, faster vacuum, instant drops of old data — and none of the costs below.
7. **Split by table, not by row** (*functional partitioning*): move `events` to its own database, then `sessions`, then `audit_log`. Each move is a normal service extraction with normal rollback. You get most of the relief and you keep transactions *within* each domain.

Only then shard by row. Here is the bill, in full, payable the day you do:

- **No cross-shard transactions.** Two rows on two shards cannot be updated atomically.
- **No cross-shard joins.** The database will not do it. Your application will, badly, in a loop.
- **No global `AUTO_INCREMENT` / `SERIAL`.** Every shard's sequence starts at 1. You need UUIDv7, Snowflake-style ids, or per-shard id ranges — decided *before* the first row is written.
- **No global secondary index.** `WHERE email = ?` on a table sharded by `user_id` is a scatter-gather to every shard, forever, unless you build and maintain a separate lookup table that is not transactionally consistent with the rows it points at.
- **No global uniqueness.** `UNIQUE(email)` is enforced per shard. Two shards will happily accept the same email.
- **Every query needs the shard key**, or it becomes a scatter-gather with the tail behaviour measured below.
- **Schema migrations run N times**, and can fail on shard 5 of 8.
- **Backup, restore and point-in-time recovery are now N-way**, and a consistent snapshot across shards does not exist without coordination.

### The four strategies, and the failure each one produces

There are four ways to decide which shard a row belongs to. Each is excellent at exactly one thing and produces one characteristic fire. The Build It runs all of them over the same 150,000-write multi-tenant workload — 500 tenants, one of which is 40.1% of all writes, plus a sequential `order_id`:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 522" width="100%" style="max-width:840px" role="img" aria-label="Four sharding strategies measured over the same 150,000-write multi-tenant workload, drawn as per-shard write share. Range on tenant id puts 85.5 percent on shard 0; hash on tenant id puts 47.7 percent on shard 3; a directory isolates the 40 percent enterprise tenant on its own shard and balances the other seven to 1.42x; geographic sharding inherits a population skew of 8.2x. The hottest shard in each panel is drawn in red.">
  <text x="440" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">Same workload, four shard keys, four different fires</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <rect x="24" y="46" width="404" height="200" rx="10" fill="#7f7f7f" fill-opacity="0.05" stroke="#7f7f7f" stroke-width="1.3"/><text x="40" y="68" font-size="12" font-weight="700" fill="currentColor">range(tenant_id)</text><text x="40" y="83" font-size="8" opacity="0.75" fill="currentColor">8 contiguous id ranges  ·  dashed line = 12.5% (even)</text><text x="412" y="68" font-size="10" text-anchor="end" font-weight="700" fill="#d64545">max/min 97.4x</text>
    <path d="M42 193 L 410 193" fill="none" stroke="currentColor" stroke-width="1" stroke-dasharray="4 4" opacity="0.4"/><rect x="46" y="105.4" width="34" height="102.6" rx="2" fill="#d64545" fill-opacity="0.16" stroke="#d64545" stroke-width="1.6"/><text x="63" y="221" font-size="8.5" text-anchor="middle" opacity="0.7" fill="currentColor">s0</text><text x="63" y="101.4" font-size="8" text-anchor="middle" font-weight="700" fill="#d64545">85.5</text><rect x="92" y="201.8" width="34" height="6.2" rx="2" fill="#0fa07f" fill-opacity="0.16" stroke="#0fa07f" stroke-width="1.6"/>
    <text x="109" y="221" font-size="8.5" text-anchor="middle" opacity="0.7" fill="currentColor">s1</text><text x="109" y="197.8" font-size="8" text-anchor="middle" opacity="0.85" fill="currentColor">5.2</text><rect x="138" y="204.6" width="34" height="3.4" rx="2" fill="#0fa07f" fill-opacity="0.16" stroke="#0fa07f" stroke-width="1.6"/><text x="155" y="221" font-size="8.5" text-anchor="middle" opacity="0.7" fill="currentColor">s2</text>
    <text x="155" y="200.6" font-size="8" text-anchor="middle" opacity="0.85" fill="currentColor">2.8</text><rect x="184" y="205.7" width="34" height="2.3" rx="2" fill="#0fa07f" fill-opacity="0.16" stroke="#0fa07f" stroke-width="1.6"/><text x="201" y="221" font-size="8.5" text-anchor="middle" opacity="0.7" fill="currentColor">s3</text><text x="201" y="201.7" font-size="8" text-anchor="middle" opacity="0.85" fill="currentColor">1.9</text>
    <rect x="230" y="206.0" width="34" height="2.0" rx="2" fill="#0fa07f" fill-opacity="0.16" stroke="#0fa07f" stroke-width="1.6"/><text x="247" y="221" font-size="8.5" text-anchor="middle" opacity="0.7" fill="currentColor">s4</text><text x="247" y="202.0" font-size="8" text-anchor="middle" opacity="0.85" fill="currentColor">1.5</text><rect x="276" y="206.0" width="34" height="2.0" rx="2" fill="#0fa07f" fill-opacity="0.16" stroke="#0fa07f" stroke-width="1.6"/>
    <text x="293" y="221" font-size="8.5" text-anchor="middle" opacity="0.7" fill="currentColor">s5</text><text x="293" y="202.0" font-size="8" text-anchor="middle" opacity="0.85" fill="currentColor">1.2</text><rect x="322" y="206.0" width="34" height="2.0" rx="2" fill="#0fa07f" fill-opacity="0.16" stroke="#0fa07f" stroke-width="1.6"/><text x="339" y="221" font-size="8.5" text-anchor="middle" opacity="0.7" fill="currentColor">s6</text>
    <text x="339" y="202.0" font-size="8" text-anchor="middle" opacity="0.85" fill="currentColor">1.0</text><rect x="368" y="206.0" width="34" height="2.0" rx="2" fill="#0fa07f" fill-opacity="0.16" stroke="#0fa07f" stroke-width="1.6"/><text x="385" y="221" font-size="8.5" text-anchor="middle" opacity="0.7" fill="currentColor">s7</text><text x="385" y="202.0" font-size="8" text-anchor="middle" opacity="0.85" fill="currentColor">0.9</text>
    <path d="M42 208 L 410 208" fill="none" stroke="currentColor" stroke-width="1.4"/><text x="40" y="238" font-size="8.5" opacity="0.9" fill="currentColor">old ids are big customers: 85.5% on one machine</text><rect x="452" y="46" width="404" height="200" rx="10" fill="#7f7f7f" fill-opacity="0.05" stroke="#7f7f7f" stroke-width="1.3"/><text x="468" y="68" font-size="12" font-weight="700" fill="currentColor">hash(tenant_id)</text>
    <text x="468" y="83" font-size="8" opacity="0.75" fill="currentColor">blake2b(tenant_id) % 8  ·  dashed line = 12.5% (even)</text><text x="840" y="68" font-size="10" text-anchor="end" font-weight="700" fill="#d64545">max/min 18.1x</text><path d="M470 193 L 838 193" fill="none" stroke="currentColor" stroke-width="1" stroke-dasharray="4 4" opacity="0.4"/><rect x="474" y="204.9" width="34" height="3.1" rx="2" fill="#0fa07f" fill-opacity="0.16" stroke="#0fa07f" stroke-width="1.6"/><text x="491" y="221" font-size="8.5" text-anchor="middle" opacity="0.7" fill="currentColor">s0</text>
    <text x="491" y="200.9" font-size="8" text-anchor="middle" opacity="0.85" fill="currentColor">2.6</text><rect x="520" y="186.8" width="34" height="21.2" rx="2" fill="#0fa07f" fill-opacity="0.16" stroke="#0fa07f" stroke-width="1.6"/><text x="537" y="221" font-size="8.5" text-anchor="middle" opacity="0.7" fill="currentColor">s1</text><text x="537" y="182.8" font-size="8" text-anchor="middle" opacity="0.85" fill="currentColor">17.7</text>
    <rect x="566" y="195.4" width="34" height="12.6" rx="2" fill="#0fa07f" fill-opacity="0.16" stroke="#0fa07f" stroke-width="1.6"/><text x="583" y="221" font-size="8.5" text-anchor="middle" opacity="0.7" fill="currentColor">s2</text><text x="583" y="191.4" font-size="8" text-anchor="middle" opacity="0.85" fill="currentColor">10.5</text><rect x="612" y="150.8" width="34" height="57.2" rx="2" fill="#d64545" fill-opacity="0.16" stroke="#d64545" stroke-width="1.6"/>
    <text x="629" y="221" font-size="8.5" text-anchor="middle" opacity="0.7" fill="currentColor">s3</text><text x="629" y="146.8" font-size="8" text-anchor="middle" font-weight="700" fill="#d64545">47.7</text><rect x="658" y="202.7" width="34" height="5.3" rx="2" fill="#0fa07f" fill-opacity="0.16" stroke="#0fa07f" stroke-width="1.6"/><text x="675" y="221" font-size="8.5" text-anchor="middle" opacity="0.7" fill="currentColor">s4</text>
    <text x="675" y="198.7" font-size="8" text-anchor="middle" opacity="0.85" fill="currentColor">4.4</text><rect x="704" y="200.4" width="34" height="7.6" rx="2" fill="#0fa07f" fill-opacity="0.16" stroke="#0fa07f" stroke-width="1.6"/><text x="721" y="221" font-size="8.5" text-anchor="middle" opacity="0.7" fill="currentColor">s5</text><text x="721" y="196.4" font-size="8" text-anchor="middle" opacity="0.85" fill="currentColor">6.3</text>
    <rect x="750" y="200.7" width="34" height="7.3" rx="2" fill="#0fa07f" fill-opacity="0.16" stroke="#0fa07f" stroke-width="1.6"/><text x="767" y="221" font-size="8.5" text-anchor="middle" opacity="0.7" fill="currentColor">s6</text><text x="767" y="196.7" font-size="8" text-anchor="middle" opacity="0.85" fill="currentColor">6.1</text><rect x="796" y="202.4" width="34" height="5.6" rx="2" fill="#0fa07f" fill-opacity="0.16" stroke="#0fa07f" stroke-width="1.6"/>
    <text x="813" y="221" font-size="8.5" text-anchor="middle" opacity="0.7" fill="currentColor">s7</text><text x="813" y="198.4" font-size="8" text-anchor="middle" opacity="0.85" fill="currentColor">4.7</text><path d="M470 208 L 838 208" fill="none" stroke="currentColor" stroke-width="1.4"/><text x="468" y="238" font-size="8.5" opacity="0.9" fill="currentColor">placement is uniform, volume is not: 47.7% on s3</text>
    <rect x="24" y="258" width="404" height="200" rx="10" fill="#7f7f7f" fill-opacity="0.05" stroke="#7f7f7f" stroke-width="1.3"/><text x="40" y="280" font-size="12" font-weight="700" fill="currentColor">directory(tenant_id)</text><text x="40" y="295" font-size="8" opacity="0.75" fill="currentColor">an explicit tenant -&gt; shard table  ·  dashed = 12.5%</text><text x="412" y="280" font-size="10" text-anchor="end" font-weight="700" fill="#d64545">max/min 5.0x</text>
    <path d="M42 405 L 410 405" fill="none" stroke="currentColor" stroke-width="1" stroke-dasharray="4 4" opacity="0.4"/><rect x="46" y="371.9" width="34" height="48.1" rx="2" fill="#d64545" fill-opacity="0.16" stroke="#d64545" stroke-width="1.6"/><text x="63" y="433" font-size="8.5" text-anchor="middle" opacity="0.7" fill="currentColor">s0</text><text x="63" y="367.9" font-size="8" text-anchor="middle" font-weight="700" fill="#d64545">40.1</text><rect x="92" y="406.2" width="34" height="13.8" rx="2" fill="#0fa07f" fill-opacity="0.16" stroke="#0fa07f" stroke-width="1.6"/>
    <text x="109" y="433" font-size="8.5" text-anchor="middle" opacity="0.7" fill="currentColor">s1</text><text x="109" y="402.2" font-size="8" text-anchor="middle" opacity="0.85" fill="currentColor">11.5</text><rect x="138" y="410.3" width="34" height="9.7" rx="2" fill="#0fa07f" fill-opacity="0.16" stroke="#0fa07f" stroke-width="1.6"/><text x="155" y="433" font-size="8.5" text-anchor="middle" opacity="0.7" fill="currentColor">s2</text>
    <text x="155" y="406.3" font-size="8" text-anchor="middle" opacity="0.85" fill="currentColor">8.1</text><rect x="184" y="410.3" width="34" height="9.7" rx="2" fill="#0fa07f" fill-opacity="0.16" stroke="#0fa07f" stroke-width="1.6"/><text x="201" y="433" font-size="8.5" text-anchor="middle" opacity="0.7" fill="currentColor">s3</text><text x="201" y="406.3" font-size="8" text-anchor="middle" opacity="0.85" fill="currentColor">8.1</text>
    <rect x="230" y="410.3" width="34" height="9.7" rx="2" fill="#0fa07f" fill-opacity="0.16" stroke="#0fa07f" stroke-width="1.6"/><text x="247" y="433" font-size="8.5" text-anchor="middle" opacity="0.7" fill="currentColor">s4</text><text x="247" y="406.3" font-size="8" text-anchor="middle" opacity="0.85" fill="currentColor">8.1</text><rect x="276" y="410.3" width="34" height="9.7" rx="2" fill="#0fa07f" fill-opacity="0.16" stroke="#0fa07f" stroke-width="1.6"/>
    <text x="293" y="433" font-size="8.5" text-anchor="middle" opacity="0.7" fill="currentColor">s5</text><text x="293" y="406.3" font-size="8" text-anchor="middle" opacity="0.85" fill="currentColor">8.1</text><rect x="322" y="410.3" width="34" height="9.7" rx="2" fill="#0fa07f" fill-opacity="0.16" stroke="#0fa07f" stroke-width="1.6"/><text x="339" y="433" font-size="8.5" text-anchor="middle" opacity="0.7" fill="currentColor">s6</text>
    <text x="339" y="406.3" font-size="8" text-anchor="middle" opacity="0.85" fill="currentColor">8.1</text><rect x="368" y="410.3" width="34" height="9.7" rx="2" fill="#0fa07f" fill-opacity="0.16" stroke="#0fa07f" stroke-width="1.6"/><text x="385" y="433" font-size="8.5" text-anchor="middle" opacity="0.7" fill="currentColor">s7</text><text x="385" y="406.3" font-size="8" text-anchor="middle" opacity="0.85" fill="currentColor">8.1</text>
    <path d="M42 420 L 410 420" fill="none" stroke="currentColor" stroke-width="1.4"/><text x="40" y="450" font-size="8.5" opacity="0.9" fill="currentColor">the whale gets its own shard; the other 7 are 1.42x</text><rect x="452" y="258" width="404" height="200" rx="10" fill="#7f7f7f" fill-opacity="0.05" stroke="#7f7f7f" stroke-width="1.3"/><text x="468" y="280" font-size="12" font-weight="700" fill="currentColor">geographic(region)</text>
    <text x="468" y="295" font-size="8" opacity="0.75" fill="currentColor">one shard per region  ·  dashed line = 12.5% (even)</text><text x="840" y="280" font-size="10" text-anchor="end" font-weight="700" fill="#d64545">max/min 8.2x</text><path d="M470 405 L 838 405" fill="none" stroke="currentColor" stroke-width="1" stroke-dasharray="4 4" opacity="0.4"/><rect x="474" y="381.4" width="34" height="38.6" rx="2" fill="#d64545" fill-opacity="0.16" stroke="#d64545" stroke-width="1.6"/><text x="491" y="433" font-size="8.5" text-anchor="middle" opacity="0.7" fill="currentColor">s0</text>
    <text x="491" y="377.4" font-size="8" text-anchor="middle" font-weight="700" fill="#d64545">32.2</text><rect x="520" y="398.4" width="34" height="21.6" rx="2" fill="#0fa07f" fill-opacity="0.16" stroke="#0fa07f" stroke-width="1.6"/><text x="537" y="433" font-size="8.5" text-anchor="middle" opacity="0.7" fill="currentColor">s1</text><text x="537" y="394.4" font-size="8" text-anchor="middle" opacity="0.85" fill="currentColor">18.0</text>
    <rect x="566" y="405.5" width="34" height="14.5" rx="2" fill="#0fa07f" fill-opacity="0.16" stroke="#0fa07f" stroke-width="1.6"/><text x="583" y="433" font-size="8.5" text-anchor="middle" opacity="0.7" fill="currentColor">s2</text><text x="583" y="401.5" font-size="8" text-anchor="middle" opacity="0.85" fill="currentColor">12.1</text><rect x="612" y="406.9" width="34" height="13.1" rx="2" fill="#0fa07f" fill-opacity="0.16" stroke="#0fa07f" stroke-width="1.6"/>
    <text x="629" y="433" font-size="8.5" text-anchor="middle" opacity="0.7" fill="currentColor">s3</text><text x="629" y="402.9" font-size="8" text-anchor="middle" opacity="0.85" fill="currentColor">10.9</text><rect x="658" y="410.5" width="34" height="9.5" rx="2" fill="#0fa07f" fill-opacity="0.16" stroke="#0fa07f" stroke-width="1.6"/><text x="675" y="433" font-size="8.5" text-anchor="middle" opacity="0.7" fill="currentColor">s4</text>
    <text x="675" y="406.5" font-size="8" text-anchor="middle" opacity="0.85" fill="currentColor">7.9</text><rect x="704" y="412.7" width="34" height="7.3" rx="2" fill="#0fa07f" fill-opacity="0.16" stroke="#0fa07f" stroke-width="1.6"/><text x="721" y="433" font-size="8.5" text-anchor="middle" opacity="0.7" fill="currentColor">s5</text><text x="721" y="408.7" font-size="8" text-anchor="middle" opacity="0.85" fill="currentColor">6.1</text>
    <rect x="750" y="409.2" width="34" height="10.8" rx="2" fill="#0fa07f" fill-opacity="0.16" stroke="#0fa07f" stroke-width="1.6"/><text x="767" y="433" font-size="8.5" text-anchor="middle" opacity="0.7" fill="currentColor">s6</text><text x="767" y="405.2" font-size="8" text-anchor="middle" opacity="0.85" fill="currentColor">9.0</text><rect x="796" y="415.3" width="34" height="4.7" rx="2" fill="#0fa07f" fill-opacity="0.16" stroke="#0fa07f" stroke-width="1.6"/>
    <text x="813" y="433" font-size="8.5" text-anchor="middle" opacity="0.7" fill="currentColor">s7</text><text x="813" y="411.3" font-size="8" text-anchor="middle" opacity="0.85" fill="currentColor">3.9</text><path d="M470 420 L 838 420" fill="none" stroke="currentColor" stroke-width="1.4"/><text x="468" y="450" font-size="8.5" opacity="0.9" fill="currentColor">buys latency and residency, inherits population skew</text>
    <text x="440" y="490" font-size="11" text-anchor="middle" opacity="0.9" fill="currentColor">Measured over the same 150,000 writes. The fifth option, hash(order_id), is the only balanced one (1.02x)</text><text x="440" y="506" font-size="11" text-anchor="middle" opacity="0.9" fill="currentColor">— and the only one where 'every order for tenant X' has to ask all 8 shards.</text>
  </g>
</svg>
```

**Range sharding** assigns contiguous key ranges to shards: `s0` holds tenants 0–62, `s1` holds 63–125, and so on. It is the only strategy that makes range scans cheap — "everything between these two keys" is one shard, one contiguous read. Its failure is **the hot tail**, and it has two shapes. The first is measured above: `tenant_id` is assigned at signup, so low ids are old accounts, and your oldest accounts are your biggest ones. The distribution is not random with respect to the key, and **85.5% of writes land on `s0` — a 97.4× imbalance.** The second shape is worse and gets its own section below.

**Hash sharding** applies a hash function to the key and takes the remainder: `blake2b(tenant_id) % 8`. It destroys any relationship between key order and placement, which is exactly what you want for spread — and exactly what you lose for scans. The measured result is the important one: hashing spread 499 tenants beautifully and **still put 47.7% of writes on `s3`, an 18.1× imbalance**, because the whale hashed to `s3` and hashing randomises *placement*, not *volume*. A hash function cannot fix a distribution that is skewed in the value you are hashing.

**Directory sharding** stores the mapping in an explicit lookup table: `tenant_id → shard_id`, maintained by you. Maximum flexibility — you can place any tenant on any shard and move them at will. This is what makes the 40% enterprise tenant tractable: measured above, greedy placement puts the whale alone on `s0` and balances the other seven to **1.42× of each other**. Note what it does *not* do: the overall imbalance is still **5.0×**, because no tenant-keyed scheme can put a 40% tenant on less than 40% of a shard. What the directory buys is not balance, it is **isolation** — the whale's traffic, its bloat, its vacuum storms and its incidents are confined to one machine that nobody else shares. The cost is severe and permanent: the lookup service is now a hard dependency on *every single query*, a new single point of failure, and a cache-coherence problem (a stale directory entry sends a write to the wrong shard, which is data loss, not an error).

**Geographic sharding** places rows by region: EU users in Frankfurt, US users in Virginia. It is chosen for latency and for data residency law (GDPR, data-localisation regimes), not for balance — and it inherits your user population's skew directly, measured here at **8.2×**. Lesson 10 goes into multi-region properly.

The fifth row in the measured table is the one that looks best and is used least: **`hash(order_id)`, hashing the row's own primary key, is the only balanced option at 1.02×** — and it is the only one where "every order for tenant X" has to ask all eight shards. That is the trade in one line. **Balance and locality are in direct opposition, and the shard key is where you choose between them.**

### The monotonic key: a range shard with seven idle machines

The second shape of the hot tail deserves its own treatment because it is the single most common sharding mistake, and it looks completely reasonable in a design doc.

You shard on a key that always increases: an auto-increment `order_id`, a `created_at` timestamp, a ULID, a Snowflake id. You cut the existing keyspace into eight equal ranges when you shard. Then every new row has a key larger than every existing key, so **every insert lands in the top range**. Measured: 120,000 new orders after sharding a 1,000,000-row table into eight equal `order_id` ranges put **100.0% of writes on `s7`** and 0.0% on the other seven.

The trap inside the trap: splitting the hot range does not help. Split `s7` into two and the new top range inherits 100% of the inserts, because the hotspot follows the *sequence*, not the split. You can split forever and the hot shard is always the newest one. Cassandra, DynamoDB, HBase and MongoDB all warn about this in their documentation, and it is the same phenomenon each time.

Hashing fixes it completely — the same 120,000 writes spread to 12.4–12.6% per shard — and the bill arrives immediately. `SELECT * FROM orders WHERE order_id BETWEEN 1,040,000 AND 1,045,000` was **1 shard** under range and is **8 shards** under hash, because consecutive ids are now maximally far apart. If your dominant access pattern is a time range, hashing the time is the wrong answer; the right answer is usually a composite key that hashes something else and ranges on time within it (Cassandra's partition key plus clustering key, covered in [Wide-Column Stores](../../04-nosql-and-data-modeling/04-wide-column-stores/), is exactly this shape).

### Choosing the shard key

Four criteria. They conflict, and the conflict is the design work.

- **High cardinality.** The key must have far more distinct values than you have shards, or you cannot subdivide. `country` has ~200 values and `plan_tier` has 4 — neither can ever be split beyond that number.
- **Even distribution.** Not just of *values*, of *volume*. See the 47.7% above.
- **Present in the vast majority of queries.** Every query without it is a scatter-gather. This is the criterion people weight lowest and regret most.
- **Stable.** A key whose value changes means the row must physically **move between machines** — a delete on one shard and an insert on another, with no transaction covering both. MongoDB made shard keys immutable for exactly this reason (and later allowed changes only under a heavyweight internal protocol). Never shard on anything a user can edit: email, username, team, region, plan.

The multi-tenant case makes the conflict concrete. `tenant_id` gives perfect locality — every tenant-scoped query hits one shard, and a tenant is a natural blast-radius boundary — and terrible balance, because tenant size is Zipfian and one tenant is 40% of your traffic. `user_id` gives good balance and breaks every tenant-wide query into an 8-way fan-out. The usual compromise is a **composite key**: shard on `tenant_id` for the 99% of tenants that are small, and for the handful of whales shard on `(tenant_id, user_id)` so that one tenant spreads across several shards. You keep locality where locality is cheap and buy balance only where you have to pay for it.

Here is a procedure you can actually run, and it takes an afternoon:

1. Pull your top 20 queries by call volume out of `pg_stat_statements` (or your APM). Twenty is enough; the distribution is Zipfian here too.
2. For each candidate shard key, mark every query as **routed** (the key is in the `WHERE` clause) or **scatter** (it is not).
3. Weight by call volume, not by query count. One query at 40,000 QPS outranks fifteen at 3 QPS.
4. Sum the scatter percentage. Then look at the *writes* separately, because that is what you are sharding for.
5. Reject any candidate whose value can change. Then pick the survivor with the lowest weighted scatter.

Write the answer down along with the queries that lost, because in two years someone will ask why, and "we chose `tenant_id` knowing that cross-tenant analytics would fan out to every shard" is an engineering decision. "It seemed natural" is not.

### Hot shards: uniform placement is not uniform load

Hashing gives you uniform *placement*. It says nothing about *access*, and access is never uniform. Real key popularity follows a Zipf-like distribution — a small number of keys take a large fraction of the traffic — which has been measured repeatedly since Breslau et al., *Web Caching and Zipf-like Distributions* (INFOCOM 1999).

The Build It places 50,000 keys by hash across 8 shards and then draws 400,000 accesses from Zipf(s = 1.25):

```text
  measure                   s0    s1    s2    s3    s4    s5    s6    s7   max/min
  keys placed (%)         12.3  12.5  12.4  12.6  12.6  12.8  12.2  12.5     1.05x
  load received (%)       17.2   7.5   5.0  29.0  10.0   5.4  17.3   8.6     5.83x
```

**Placement is flat at 1.05×. Load is 5.83× out of balance**, and the hottest single key is 23.1% of all traffic on its own. This is not a hashing failure; the hash did its job. It is the difference between how many keys a shard owns and how often anyone asks for them. (This is the same skew that makes caching work at all — Phase 5's hit rates come from exactly this distribution. Here it is the enemy rather than the ally.)

Three mitigations, in the order you should try them:

**Salt the specific hot key.** Rewrite the one key that is on fire as N sub-keys — `sku:8123#0` through `sku:8123#15` — placed independently, so its write load spreads over up to 16 shards. Measured: salting the single hottest key took imbalance from **5.83× to 3.15×**. Salting the top four (42.7% of traffic) reached **2.18×**, and the top sixteen reached **1.76×**. Read the cost column next to those numbers, because it is the part people skip: reading a salted key means reading *all* its pieces and summing them, so total shard-touches went up **4.47×, 7.41× and 10.05×** respectively. Salting converts a write hotspot into a read fan-out. It is right for a counter and wrong for a lookup. **Salt the key that is on fire, never the keyspace** — and note that Zipf has no bottom, so there is always a next hottest key and the returns diminish while the cost does not.

**Place the hot tenant deliberately, with a directory.** This is the enterprise-whale answer from the strategy table, and it is usually the correct one for a multi-tenant system.

**Move the single worst tenant to dedicated infrastructure.** Their own shard, their own instance class, their own maintenance window, and — if they are 40% of your revenue as well as 40% of your writes — their own price. This is a commercial decision as much as a technical one, and it is the standard endgame for enterprise SaaS.

Note the thing that is *not* on the list: adding shards. Going from 8 to 16 shards does not help a hot key at all. The key still hashes to exactly one place; you have just bought eight more idle machines.

### Scatter-gather and the tail

A query without the shard key must ask every shard. Its latency is not the average of S responses — it is the **maximum** of S samples from the per-shard latency distribution, because you cannot return until the slowest one is in. The maximum of S samples lives in the tail, and the tail is where the ugly numbers are.

The arithmetic is simple enough to do in your head. If one shard is "slow" with probability *p*, the chance that a fan-out to S shards touches at least one slow shard is:

```text
P(the query is slow)  =  1 - (1 - p)^S

p = 0.01 (one shard is slow 1% of the time)
  S =  1      1 - 0.99^1   =  1.00%
  S =  2      1 - 0.99^2   =  1.99%
  S =  4      1 - 0.99^4   =  3.94%
  S =  8      1 - 0.99^8   =  7.73%     <- a 1-in-100 event became 1-in-13
  S = 16      1 - 0.99^16  = 14.85%
```

The Build It measures it against 120,000 simulated fan-outs per point, with a per-shard distribution that is 99% fast and 1% drawn from a heavy Pareto tail:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 410" width="100%" style="max-width:840px" role="img" aria-label="Measured tail amplification of a scatter-gather query. The left panel plots p50 and p99 of the fan-out against the number of shards touched: p50 rises only from 12 to 28 milliseconds while p99 rises from 61 to 622 milliseconds. The right panel plots the measured probability that a query hits at least one slow shard against the prediction one minus zero point nine nine to the power S; the measured points sit on the predicted curve, reaching 7.83 percent at eight shards and 14.89 percent at sixteen.">
  <text x="440" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">Scatter-gather: the p50 barely moves, the p99 is a different service</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <path d="M70 320 L 430 320 M70 70 L 70 320" fill="none" stroke="currentColor" stroke-width="1.4"/><path d="M70 320.0 L 430 320.0" fill="none" stroke="currentColor" stroke-width="1" stroke-dasharray="3 5" opacity="0.28"/><text x="62" y="324.0" font-size="9" text-anchor="end" opacity="0.7" fill="currentColor">0</text><path d="M70 248.6 L 430 248.6" fill="none" stroke="currentColor" stroke-width="1" stroke-dasharray="3 5" opacity="0.28"/><text x="62" y="252.6" font-size="9" text-anchor="end" opacity="0.7" fill="currentColor">200</text>
    <path d="M70 177.1 L 430 177.1" fill="none" stroke="currentColor" stroke-width="1" stroke-dasharray="3 5" opacity="0.28"/><text x="62" y="181.1" font-size="9" text-anchor="end" opacity="0.7" fill="currentColor">400</text><path d="M70 105.7 L 430 105.7" fill="none" stroke="currentColor" stroke-width="1" stroke-dasharray="3 5" opacity="0.28"/><text x="62" y="109.7" font-size="9" text-anchor="end" opacity="0.7" fill="currentColor">600</text>
    <path d="M100 298.2 L175 263.9 L250 230.4 L325 173.9 L400 97.9" fill="none" stroke="#d64545" stroke-width="2.6"/><path d="M100 315.7 L175 314.6 L250 313.2 L325 311.8 L400 310.0" fill="none" stroke="#0fa07f" stroke-width="2.6"/><circle cx="100" cy="298.2" r="4" fill="#d64545" fill-opacity="0.5" stroke="#d64545" stroke-width="1.6"/><circle cx="100" cy="315.7" r="4" fill="#0fa07f" fill-opacity="0.5" stroke="#0fa07f" stroke-width="1.6"/><text x="100" y="289.2" font-size="9" text-anchor="middle" font-weight="700" fill="#d64545">61</text><text x="100" y="335" font-size="9.5" text-anchor="middle" opacity="0.85" fill="currentColor">1</text><circle cx="175" cy="263.9" r="4" fill="#d64545" fill-opacity="0.5" stroke="#d64545" stroke-width="1.6"/><circle cx="175" cy="314.6" r="4" fill="#0fa07f" fill-opacity="0.5" stroke="#0fa07f" stroke-width="1.6"/>
    <text x="175" y="254.89999999999998" font-size="9" text-anchor="middle" font-weight="700" fill="#d64545">157</text><text x="175" y="335" font-size="9.5" text-anchor="middle" opacity="0.85" fill="currentColor">2</text><circle cx="250" cy="230.4" r="4" fill="#d64545" fill-opacity="0.5" stroke="#d64545" stroke-width="1.6"/><circle cx="250" cy="313.2" r="4" fill="#0fa07f" fill-opacity="0.5" stroke="#0fa07f" stroke-width="1.6"/><text x="250" y="221.4" font-size="9" text-anchor="middle" font-weight="700" fill="#d64545">251</text>
    <text x="250" y="335" font-size="9.5" text-anchor="middle" opacity="0.85" fill="currentColor">4</text><circle cx="325" cy="173.9" r="4" fill="#d64545" fill-opacity="0.5" stroke="#d64545" stroke-width="1.6"/><circle cx="325" cy="311.8" r="4" fill="#0fa07f" fill-opacity="0.5" stroke="#0fa07f" stroke-width="1.6"/><text x="325" y="164.9" font-size="9" text-anchor="middle" font-weight="700" fill="#d64545">409</text><text x="325" y="335" font-size="9.5" text-anchor="middle" opacity="0.85" fill="currentColor">8</text>
    <circle cx="400" cy="97.9" r="4" fill="#d64545" fill-opacity="0.5" stroke="#d64545" stroke-width="1.6"/><circle cx="400" cy="310.0" r="4" fill="#0fa07f" fill-opacity="0.5" stroke="#0fa07f" stroke-width="1.6"/><text x="400" y="88.9" font-size="9" text-anchor="middle" font-weight="700" fill="#d64545">622</text><text x="400" y="335" font-size="9.5" text-anchor="middle" opacity="0.85" fill="currentColor">16</text><text x="250.0" y="352" font-size="10" text-anchor="middle" opacity="0.85" fill="currentColor">shards touched by one query (S)</text>
    <text x="24" y="195.0" font-size="10" text-anchor="middle" opacity="0.85" fill="currentColor">ms</text><text x="84" y="86" font-size="10.5" font-weight="700" fill="#d64545">p99 of the fan-out</text><text x="84" y="102" font-size="9" opacity="0.9" fill="#d64545">61 ms -> 622 ms  (10.2x)</text><text x="84" y="120" font-size="10.5" font-weight="700" fill="#0fa07f">p50 of the fan-out</text>
    <text x="84" y="136" font-size="9" opacity="0.9" fill="#0fa07f">12 ms -> 28 ms  (2.3x)</text><path d="M528 320 L 828 320 M528 70 L 528 320" fill="none" stroke="currentColor" stroke-width="1.4"/><path d="M528 320.0 L 828 320.0" fill="none" stroke="currentColor" stroke-width="1" stroke-dasharray="3 5" opacity="0.28"/><text x="520" y="324.0" font-size="9" text-anchor="end" opacity="0.7" fill="currentColor">0%</text><path d="M528 241.9 L 828 241.9" fill="none" stroke="currentColor" stroke-width="1" stroke-dasharray="3 5" opacity="0.28"/>
    <text x="520" y="245.9" font-size="9" text-anchor="end" opacity="0.7" fill="currentColor">5%</text><path d="M528 163.8 L 828 163.8" fill="none" stroke="currentColor" stroke-width="1" stroke-dasharray="3 5" opacity="0.28"/><text x="520" y="167.8" font-size="9" text-anchor="end" opacity="0.7" fill="currentColor">10%</text><path d="M528 85.6 L 828 85.6" fill="none" stroke="currentColor" stroke-width="1" stroke-dasharray="3 5" opacity="0.28"/>
    <text x="520" y="89.6" font-size="9" text-anchor="end" opacity="0.7" fill="currentColor">15%</text><path d="M554 304.4 L616 288.9 L678 258.4 L740 199.2 L802 88.0" fill="none" stroke="#7c5cff" stroke-width="2.4" stroke-dasharray="7 4"/><circle cx="554" cy="304.7" r="4.5" fill="#e0930f" fill-opacity="0.55" stroke="#e0930f" stroke-width="1.6"/><text x="554" y="335" font-size="9.5" text-anchor="middle" opacity="0.85" fill="currentColor">1</text><circle cx="616" cy="289.1" r="4.5" fill="#e0930f" fill-opacity="0.55" stroke="#e0930f" stroke-width="1.6"/>
    <text x="616" y="335" font-size="9.5" text-anchor="middle" opacity="0.85" fill="currentColor">2</text><circle cx="678" cy="258.6" r="4.5" fill="#e0930f" fill-opacity="0.55" stroke="#e0930f" stroke-width="1.6"/><text x="678" y="335" font-size="9.5" text-anchor="middle" opacity="0.85" fill="currentColor">4</text><circle cx="740" cy="197.7" r="4.5" fill="#e0930f" fill-opacity="0.55" stroke="#e0930f" stroke-width="1.6"/>
    <text x="740" y="335" font-size="9.5" text-anchor="middle" opacity="0.85" fill="currentColor">8</text><circle cx="802" cy="87.3" r="4.5" fill="#e0930f" fill-opacity="0.55" stroke="#e0930f" stroke-width="1.6"/><text x="802" y="335" font-size="9.5" text-anchor="middle" opacity="0.85" fill="currentColor">16</text><text x="752" y="201.7" font-size="9" font-weight="700" fill="#e0930f">7.83%</text>
    <text x="792" y="105.3" font-size="9" text-anchor="end" font-weight="700" fill="#e0930f">14.89%</text><text x="678.0" y="352" font-size="10" text-anchor="middle" opacity="0.85" fill="currentColor">shards touched by one query (S)</text><text x="528" y="58" font-size="10.5" font-weight="700" fill="currentColor">P(a query hits at least one slow shard)</text><text x="542" y="126" font-size="9.5" font-weight="700" fill="#e0930f">o    measured</text>
    <text x="542" y="142" font-size="9.5" font-weight="700" fill="#7c5cff">- -  1 - (1 - p)^S,  p = 0.01</text><text x="542" y="158" font-size="8.5" opacity="0.85" fill="currentColor">120,000 fan-outs per point</text><text x="440" y="372" font-size="11" text-anchor="middle" opacity="0.95" fill="currentColor">one shard is slow 1% of the time. That is a fixed, unremarkable, well-behaved number.</text><text x="440" y="390" font-size="11" text-anchor="middle" font-weight="700" fill="#d64545">A query that asks 8 of them is slow 7.8% of the time, and its p99 is 6.7x one shard's p99.</text>
  </g>
</svg>
```

The measured column tracks the prediction to within a tenth of a percent (7.83% measured vs 7.73% predicted at S = 8), which means this is arithmetic and not a rule of thumb. But look at the left panel, because that is the part that surprises people. **The p50 of the fan-out went from 12 ms to 28 ms — 2.3× — while the p99 went from 61 ms to 622 ms, 10.2×.** Your median dashboard, your median load test, and your median local development experience all say the fan-out is fine. It is fine. It is fine 99% of the time and catastrophic 1% of the time, and at 40,000 QPS that 1% is 400 users a second.

This is Dean & Barroso's argument in *The Tail at Scale* (CACM 56(2), 2013) applied to your database instead of your service mesh, and it is why every scatter-gather query is a liability you should be able to name. Lesson 11 covers the mitigations — hedged requests, tied requests, and why they cost throughput.

Two things follow directly. First, **a partial-result path is worth building**: return the seven shards that answered inside the deadline and mark the response degraded, rather than making every user wait for the eighth. Second, **shard count is a latency decision, not just a capacity decision.** Doubling from 8 to 16 shards halves per-shard load and *doubles* your fan-out's exposure to a slow machine.

### Cross-shard writes

Most sharded setups have no distributed transaction available at all. Here are the honest options, in the order you should want them.

**Redesign so the transaction fits in one shard.** This is the best answer and it is available far more often than people assume, because it is a *data modelling* decision, not a distributed-systems one. Shard on `account_id` and a transfer between two accounts spans two shards; shard on `ledger_id` and a transfer *within* a ledger is one shard. Colocate the rows that must change together — the same thinking as [Data Modeling by Access Pattern](../../04-nosql-and-data-modeling/07-data-modeling-by-access-pattern/), applied to writes. Citus calls this **colocation** and makes it explicit: distribute `orders` and `order_items` on the same column and the two tables' matching rows are guaranteed to live on the same node, so joins and transactions between them are local.

**Two-phase commit (2PC).** A coordinator asks every participant to *prepare* (do the work, hold the locks, promise you can commit), collects the votes, then tells everyone to *commit* or *abort*. It is correct, it is implemented — Postgres has `PREPARE TRANSACTION` — and it is rare in production for one reason: **it blocks.** If the coordinator crashes after the participants have prepared and before it has told them what to do, every participant sits holding its locks, unable to commit (it might have to abort) and unable to abort (it might have to commit), until a human intervenes. Skeen proved in *Nonblocking Commit Protocols* (SIGMOD 1981) that no protocol can be non-blocking in the presence of arbitrary failures without additional assumptions. Meanwhile every prepared transaction is holding row locks on a production database. 2PC turns a network partition into a total outage on the shards that were merely participants. Systems that do offer cross-shard transactions at scale — Spanner (Corbett et al., OSDI 2012) — get there with synchronised clocks and Paxos-replicated participants so that no single coordinator failure can block anyone. That is not a library you install.

**Sagas.** Break the transaction into a sequence of local transactions, each with a **compensating action** that semantically undoes it (Garcia-Molina & Salem, *Sagas*, SIGMOD 1987). Debit shard A, credit shard B; if the credit fails, run "refund" on shard A. You give up atomicity and isolation — there is a window where an observer sees the money missing — and you get availability and no distributed locks. [Event-Driven Architecture](../../06-messaging-and-pub-sub/11-event-driven-architecture/) builds the pattern; the sharding-specific note is that compensations must be **idempotent** and must be *semantic* rather than literal (you refund a charge, you do not un-charge it).

**The outbox pattern** is the plumbing under all of this. When a write must update a shard *and* tell something else, write the row and an outbox record in the same local transaction on the same shard, and let a relay publish it. [Dual Writes, Outbox & CDC](../../06-messaging-and-pub-sub/10-dual-write-outbox-and-cdc/) covers it; here it is what keeps a shard and its downstream index or search cluster from drifting.

One more consequence worth stating plainly: **there is no consistent snapshot across shards.** Backups taken at "the same time" on eight machines are eight backups from eight slightly different moments. A cross-shard invariant — "total balance across all accounts is constant" — cannot be verified from them without a coordination protocol you almost certainly do not have.

### Virtual buckets: hash once, forever

Before the resharding procedure, the design decision that makes it survivable. This is the most valuable single tip in this lesson.

The naive mapping is `shard = hash(key) % N`. It is one line and it is a trap, because **N is in the formula**. Change N and every key's identity changes. Measured over 120,000 keys:

```text
  8 ->    naive hash % N    consistent ring    4096 virtual buckets    buckets moved
  9               88.9%               9.5%                   11.3%          456/4096
  10              80.1%              17.8%                   20.2%          820/4096
  12              66.8%              31.5%                   33.6%         1368/4096
  16              50.1%              48.9%                   50.0%         2048/4096
```

Read the last row first, because it is the honest one: **going 8 → 16 costs about 50% under every scheme**, and it has to — the eight new shards must be filled from somewhere. No mapping is clever enough to avoid that. The difference is the row above it. Adding *one* machine costs 88.9% under `hash % N` and 11.3% under buckets, which means `hash % N` does not really support adding one machine at all. It locks you into doubling forever, and doubling means buying eight machines and moving half the database every time you need 15% more headroom.

The fix is one level of indirection:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 478" width="100%" style="max-width:840px" role="img" aria-label="Virtual buckets explained and measured. A key hashes once into one of 4096 buckets and that mapping never changes; a routing table maps buckets to physical shards and that table is editable. Rebalancing from 8 shards to 9 moves 57 buckets off each existing shard onto the new one, 456 buckets or 11.3 percent of rows. The measured comparison below shows naive hash modulo N moving 88.9 percent of rows for the same change, a consistent hash ring moving 9.5 percent, and virtual buckets moving 11.3 percent.">
  <text x="440" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">Virtual buckets: hash once, then move buckets, never keys</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <rect x="30" y="48" width="150" height="44" rx="8" fill="#3553ff" fill-opacity="0.13" stroke="#3553ff" stroke-width="1.8"/><text x="105.0" y="68" font-size="9.5" text-anchor="middle" font-weight="700" fill="#3553ff">key</text><text x="105.0" y="82" font-size="8" text-anchor="middle" opacity="0.8" fill="currentColor">orders:user:8123</text><rect x="214" y="48" width="128" height="44" rx="8" fill="#7f7f7f" fill-opacity="0.13" stroke="#7f7f7f" stroke-width="1.8"/>
    <text x="278.0" y="68" font-size="9.5" text-anchor="middle" font-weight="700" fill="#7f7f7f">blake2b(key) % 4096</text><text x="278.0" y="82" font-size="8" text-anchor="middle" opacity="0.8" fill="currentColor">a pure function</text><rect x="376" y="48" width="128" height="44" rx="8" fill="#0fa07f" fill-opacity="0.13" stroke="#0fa07f" stroke-width="1.8"/><text x="440.0" y="68" font-size="9.5" text-anchor="middle" font-weight="700" fill="#0fa07f">bucket 1743</text>
    <text x="440.0" y="82" font-size="8" text-anchor="middle" opacity="0.8" fill="currentColor">FIXED FOREVER</text><rect x="538" y="48" width="150" height="44" rx="8" fill="#7c5cff" fill-opacity="0.13" stroke="#7c5cff" stroke-width="1.8"/><text x="613.0" y="68" font-size="9.5" text-anchor="middle" font-weight="700" fill="#7c5cff">routing table</text><text x="613.0" y="82" font-size="8" text-anchor="middle" opacity="0.8" fill="currentColor">1743 -> s5</text>
    <rect x="722" y="48" width="122" height="44" rx="8" fill="#0fa07f" fill-opacity="0.13" stroke="#0fa07f" stroke-width="1.8"/><text x="783.0" y="68" font-size="9.5" text-anchor="middle" font-weight="700" fill="#0fa07f">shard s5</text><text x="783.0" y="82" font-size="8" text-anchor="middle" opacity="0.8" fill="currentColor">the machine</text>
    <defs><marker id="p11-08-a2" markerWidth="10" markerHeight="10" refX="7" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker></defs>
    <path d="M180 70 L 208 70" fill="none" stroke="currentColor" stroke-width="1.6" marker-end="url(#p11-08-a2)"/><path d="M342 70 L 370 70" fill="none" stroke="currentColor" stroke-width="1.6" marker-end="url(#p11-08-a2)"/><path d="M504 70 L 532 70" fill="none" stroke="currentColor" stroke-width="1.6" marker-end="url(#p11-08-a2)"/><path d="M688 70 L 716 70" fill="none" stroke="currentColor" stroke-width="1.6" marker-end="url(#p11-08-a2)"/><text x="255" y="112" font-size="9" text-anchor="middle" font-weight="700" fill="#0fa07f">this half never changes</text><path d="M132 100 L 132 106 L 470 106 L 470 100" fill="none" stroke="#0fa07f" stroke-width="1.4"/><text x="660" y="112" font-size="9" text-anchor="middle" font-weight="700" fill="#7c5cff">this half is a row you UPDATE</text>
    <path d="M546 100 L 546 106 L 780 106 L 780 100" fill="none" stroke="#7c5cff" stroke-width="1.4"/><text x="88" y="152" font-size="9.5" text-anchor="end" font-weight="700" fill="currentColor">BEFORE</text><text x="88" y="165" font-size="8.5" text-anchor="end" opacity="0.85" fill="currentColor">8 shards</text><text x="88" y="177" font-size="8.5" text-anchor="end" opacity="0.85" fill="currentColor">512 bkts ea</text>
    <rect x="96.0" y="140" width="71.5" height="34" rx="0" fill="#0fa07f" fill-opacity="0.14" stroke="#0fa07f" stroke-width="1.3"/><rect x="167.5" y="140" width="9.0" height="34" rx="0" fill="#e0930f" fill-opacity="0.35" stroke="#e0930f" stroke-width="1.3"/><text x="131.8" y="161" font-size="9" text-anchor="middle" font-weight="700" fill="currentColor">s0</text><rect x="176.5" y="140" width="71.5" height="34" rx="0" fill="#0fa07f" fill-opacity="0.14" stroke="#0fa07f" stroke-width="1.3"/><rect x="248.0" y="140" width="9.0" height="34" rx="0" fill="#e0930f" fill-opacity="0.35" stroke="#e0930f" stroke-width="1.3"/><text x="212.3" y="161" font-size="9" text-anchor="middle" font-weight="700" fill="currentColor">s1</text>
    <rect x="257.0" y="140" width="71.5" height="34" rx="0" fill="#0fa07f" fill-opacity="0.14" stroke="#0fa07f" stroke-width="1.3"/><rect x="328.5" y="140" width="9.0" height="34" rx="0" fill="#e0930f" fill-opacity="0.35" stroke="#e0930f" stroke-width="1.3"/><text x="292.8" y="161" font-size="9" text-anchor="middle" font-weight="700" fill="currentColor">s2</text><rect x="337.5" y="140" width="71.5" height="34" rx="0" fill="#0fa07f" fill-opacity="0.14" stroke="#0fa07f" stroke-width="1.3"/><rect x="409.0" y="140" width="9.0" height="34" rx="0" fill="#e0930f" fill-opacity="0.35" stroke="#e0930f" stroke-width="1.3"/><text x="373.3" y="161" font-size="9" text-anchor="middle" font-weight="700" fill="currentColor">s3</text>
    <rect x="418.0" y="140" width="71.5" height="34" rx="0" fill="#0fa07f" fill-opacity="0.14" stroke="#0fa07f" stroke-width="1.3"/><rect x="489.5" y="140" width="9.0" height="34" rx="0" fill="#e0930f" fill-opacity="0.35" stroke="#e0930f" stroke-width="1.3"/><text x="453.8" y="161" font-size="9" text-anchor="middle" font-weight="700" fill="currentColor">s4</text><rect x="498.5" y="140" width="71.5" height="34" rx="0" fill="#0fa07f" fill-opacity="0.14" stroke="#0fa07f" stroke-width="1.3"/><rect x="570.0" y="140" width="9.0" height="34" rx="0" fill="#e0930f" fill-opacity="0.35" stroke="#e0930f" stroke-width="1.3"/><text x="534.3" y="161" font-size="9" text-anchor="middle" font-weight="700" fill="currentColor">s5</text>
    <rect x="579.0" y="140" width="71.5" height="34" rx="0" fill="#0fa07f" fill-opacity="0.14" stroke="#0fa07f" stroke-width="1.3"/><rect x="650.5" y="140" width="9.0" height="34" rx="0" fill="#e0930f" fill-opacity="0.35" stroke="#e0930f" stroke-width="1.3"/><text x="614.8" y="161" font-size="9" text-anchor="middle" font-weight="700" fill="currentColor">s6</text><rect x="659.5" y="140" width="71.5" height="34" rx="0" fill="#0fa07f" fill-opacity="0.14" stroke="#0fa07f" stroke-width="1.3"/><rect x="731.0" y="140" width="9.0" height="34" rx="0" fill="#e0930f" fill-opacity="0.35" stroke="#e0930f" stroke-width="1.3"/><text x="695.3" y="161" font-size="9" text-anchor="middle" font-weight="700" fill="currentColor">s7</text>
    <text x="88" y="246" font-size="9.5" text-anchor="end" font-weight="700" fill="currentColor">AFTER</text><text x="88" y="259" font-size="8.5" text-anchor="end" opacity="0.85" fill="currentColor">9 shards</text><text x="88" y="271" font-size="8.5" text-anchor="end" opacity="0.85" fill="currentColor">455 bkts ea</text><rect x="96.0" y="234" width="71.6" height="34" rx="0" fill="#0fa07f" fill-opacity="0.14" stroke="#0fa07f" stroke-width="1.3"/>
    <text x="131.8" y="255" font-size="9" text-anchor="middle" font-weight="700" fill="currentColor">s0</text><rect x="167.6" y="234" width="71.6" height="34" rx="0" fill="#0fa07f" fill-opacity="0.14" stroke="#0fa07f" stroke-width="1.3"/><text x="203.3" y="255" font-size="9" text-anchor="middle" font-weight="700" fill="currentColor">s1</text><rect x="239.1" y="234" width="71.6" height="34" rx="0" fill="#0fa07f" fill-opacity="0.14" stroke="#0fa07f" stroke-width="1.3"/>
    <text x="274.9" y="255" font-size="9" text-anchor="middle" font-weight="700" fill="currentColor">s2</text><rect x="310.7" y="234" width="71.6" height="34" rx="0" fill="#0fa07f" fill-opacity="0.14" stroke="#0fa07f" stroke-width="1.3"/><text x="346.4" y="255" font-size="9" text-anchor="middle" font-weight="700" fill="currentColor">s3</text><rect x="382.2" y="234" width="71.6" height="34" rx="0" fill="#0fa07f" fill-opacity="0.14" stroke="#0fa07f" stroke-width="1.3"/>
    <text x="418.0" y="255" font-size="9" text-anchor="middle" font-weight="700" fill="currentColor">s4</text><rect x="453.8" y="234" width="71.6" height="34" rx="0" fill="#0fa07f" fill-opacity="0.14" stroke="#0fa07f" stroke-width="1.3"/><text x="489.6" y="255" font-size="9" text-anchor="middle" font-weight="700" fill="currentColor">s5</text><rect x="525.3" y="234" width="71.6" height="34" rx="0" fill="#0fa07f" fill-opacity="0.14" stroke="#0fa07f" stroke-width="1.3"/>
    <text x="561.1" y="255" font-size="9" text-anchor="middle" font-weight="700" fill="currentColor">s6</text><rect x="596.9" y="234" width="71.6" height="34" rx="0" fill="#0fa07f" fill-opacity="0.14" stroke="#0fa07f" stroke-width="1.3"/><text x="632.7" y="255" font-size="9" text-anchor="middle" font-weight="700" fill="currentColor">s7</text><rect x="668.4" y="234" width="71.6" height="34" rx="0" fill="#e0930f" fill-opacity="0.35" stroke="#e0930f" stroke-width="1.3"/>
    <text x="704.2" y="255" font-size="9" text-anchor="middle" font-weight="700" fill="currentColor">s8</text><path d="M172.0 176 L 704.2 230" fill="none" stroke="#e0930f" stroke-width="1.1" opacity="0.6"/><path d="M252.5 176 L 704.2 230" fill="none" stroke="#e0930f" stroke-width="1.1" opacity="0.6"/><path d="M333.0 176 L 704.2 230" fill="none" stroke="#e0930f" stroke-width="1.1" opacity="0.6"/><path d="M413.5 176 L 704.2 230" fill="none" stroke="#e0930f" stroke-width="1.1" opacity="0.6"/><path d="M494.0 176 L 704.2 230" fill="none" stroke="#e0930f" stroke-width="1.1" opacity="0.6"/><path d="M574.5 176 L 704.2 230" fill="none" stroke="#e0930f" stroke-width="1.1" opacity="0.6"/><path d="M655.0 176 L 704.2 230" fill="none" stroke="#e0930f" stroke-width="1.1" opacity="0.6"/><path d="M735.5 176 L 704.2 230" fill="none" stroke="#e0930f" stroke-width="1.1" opacity="0.6"/><text x="752" y="158" font-size="9" font-weight="700" fill="#e0930f">57 buckets</text>
    <text x="752" y="170" font-size="9" opacity="0.85" fill="currentColor">leave each</text><text x="752" y="252" font-size="9" font-weight="700" fill="#e0930f">456 arrive</text><text x="752" y="264" font-size="9" opacity="0.85" fill="currentColor">= 11.3% of rows</text><text x="440" y="292" font-size="10" text-anchor="middle" font-weight="700" fill="#0fa07f">no key is rehashed. 456 rows of the routing table change.</text>
    <text x="96" y="330" font-size="11" font-weight="700" fill="currentColor">rows that must MOVE to go from 8 shards to 9:</text><text x="96" y="362" font-size="9.5" fill="currentColor">naive  hash % N</text><rect x="258" y="348" width="320.0" height="20" rx="3" fill="#d64545" fill-opacity="0.2" stroke="#d64545" stroke-width="1.5"/><text x="586.0" y="362" font-size="10" font-weight="700" fill="#d64545">88.9%</text>
    <text x="664" y="362" font-size="9" opacity="0.85" fill="currentColor">every key changes identity</text><text x="96" y="392" font-size="9.5" fill="currentColor">consistent ring</text><rect x="258" y="378" width="34.2" height="20" rx="3" fill="#0fa07f" fill-opacity="0.2" stroke="#0fa07f" stroke-width="1.5"/><text x="300.2" y="392" font-size="10" font-weight="700" fill="#0fa07f">9.5%</text>
    <text x="664" y="392" font-size="9" opacity="0.85" fill="currentColor">arcs move; unnamed units</text><text x="96" y="422" font-size="9.5" fill="currentColor">4096 virtual buckets</text><rect x="258" y="408" width="40.7" height="20" rx="3" fill="#0fa07f" fill-opacity="0.2" stroke="#0fa07f" stroke-width="1.5"/><text x="306.7" y="422" font-size="10" font-weight="700" fill="#0fa07f">11.3%</text>
    <text x="664" y="422" font-size="9" opacity="0.85" fill="currentColor">456 named, resumable buckets</text><path d="M258 344 L 258 434" fill="none" stroke="currentColor" stroke-width="1.1" opacity="0.35"/><text x="440" y="460" font-size="11" text-anchor="middle" opacity="0.9" fill="currentColor">8 -> 16 costs 50% under every scheme. 8 -> 9 is where the mapping you chose three years ago decides your week.</text>
  </g>
</svg>
```

Hash each key **once and forever** into a large, fixed number of **virtual buckets** (also called logical shards, vnodes, or — in Vitess — keyspace id ranges). Then keep a separate, small, editable table mapping buckets to physical shards. `key → bucket` is a pure function that never changes for the life of the system. `bucket → shard` is data: a few thousand rows you can `UPDATE`.

Every property you want falls out of that split:

- **Rebalancing moves buckets, not rows.** Going 8 → 9 moves 57 buckets off each existing shard: 456 buckets, 11.3% of rows, and **not one key is rehashed.**
- **The unit of movement has a name.** "Bucket 1743 is migrating" is a state you can store, a job you can retry, a transfer you can rate-limit, checkpoint, pause at 3 a.m. and resume, and revert by editing one row. A consistent hash ring gets you the same 9.5% movement but the unit is "whatever fell in this arc" — unnamed and unbounded.
- **Routing is a table lookup, not a computation**, so you can express things a formula cannot: pin the whale's buckets to dedicated hardware, keep two buckets together because they are always joined, temporarily park a bucket on a beefier box.
- **Both mappings can be verified independently.** `key → bucket` is testable with a unit test. `bucket → shard` is inspectable with a `SELECT`.

The measured comparison against **consistent hashing** (Karger et al., *Consistent Hashing and Random Trees*, STOC 1997 — the ring that Dynamo popularised, and which Phase 4 covers as a *data placement* mechanism inside a key-value store) is worth a note. The ring moves slightly *fewer* keys (9.5% vs 11.3% for 8 → 9) but it achieves that by under-filling the new shard, and its balance is worse:

```text
    ring,   1 vnode(s)/shard   max/min =  8.01x   hottest shard  35.2%
    ring,   8 vnode(s)/shard   max/min =  1.62x   hottest shard  16.3%
    ring, 160 vnode(s)/shard   max/min =  1.41x   hottest shard  14.8%
```

A ring with one point per shard is **8.01× out of balance** — worse than doing nothing. Virtual nodes are not an optimisation on the ring, they are a requirement of it, and 160 per shard still leaves 1.41×. A fixed bucket table gives you exact balance by construction, because you choose the assignment.

Which leaves the only number you have to get right: **how many buckets.** It is fixed at creation and you cannot change it without a full rehash, so pick one you will never outgrow:

```text
    buckets    at 9 shards    at 17 shards    at 40 shards
         16         2.000x            idle            idle
         64         1.143x          1.333x          2.000x
        256         1.036x          1.067x          1.167x
       1024         1.009x          1.017x          1.040x
       4096         1.002x          1.004x          1.010x
      16384         1.001x          1.001x          1.002x
```

Sixteen buckets cannot balance nine shards at all, and cannot use more than 16 machines ever. **4096 is flat to three decimal places at every size you will plausibly run**, and buckets are almost free — a bucket is an integer column and a row in a routing table. Choose 4096 or 8192, write it in the design doc, and never think about it again. This is the cheapest decision in the lesson and the one most likely to save you.

### Resharding without downtime

Now the procedure. Seven steps, and the ordering is not a style preference — the Build It measures what each wrong ordering costs.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 400" width="100%" style="max-width:840px" role="img" aria-label="The seven-step resharding procedure drawn as a timeline. Steps one through five, double-write, backfill, verify, shadow-read and flip reads, are all reversible with a feature flag because the old topology is still authoritative. Step six, stopping the double-write, is marked as the point of no return because the old topology immediately starts to drift. Step seven, dropping the old tables, is destructive and recoverable only from backup.">
  <text x="440" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">Resharding live: six reversible steps and one that is not</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <defs><marker id="p11-08-a4" markerWidth="10" markerHeight="10" refX="7" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker><marker id="p11-08-a4r" markerWidth="10" markerHeight="10" refX="7" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#0fa07f"/></marker></defs>
    <rect x="8" y="142" width="120" height="96" rx="9" fill="#0fa07f" fill-opacity="0.13" stroke="#0fa07f" stroke-width="1.8"/><circle cx="24" cy="160" r="9.5" fill="#0fa07f" fill-opacity="0.25" stroke="#0fa07f" stroke-width="1.6"/><text x="24" y="164" font-size="10" text-anchor="middle" font-weight="700" fill="#0fa07f">1</text><text x="39" y="164" font-size="9" font-weight="700" fill="#0fa07f">double-write</text><text x="18" y="186" font-size="7.5" opacity="0.9" fill="currentColor">app writes BOTH</text>
    <text x="18" y="198" font-size="7.5" opacity="0.9" fill="currentColor">topologies, on</text><text x="18" y="210" font-size="7.5" opacity="0.9" fill="currentColor">every write</text><text x="68.0" y="230" font-size="8.5" text-anchor="middle" font-weight="700" fill="#0fa07f">reversible</text><path d="M128 190 L 134 190" fill="none" stroke="currentColor" stroke-width="1.4" marker-end="url(#p11-08-a4)"/>
    <text x="68.0" y="270" font-size="7.5" text-anchor="middle" opacity="0.85" fill="currentColor">turn the flag off</text><rect x="132" y="142" width="120" height="96" rx="9" fill="#0fa07f" fill-opacity="0.13" stroke="#0fa07f" stroke-width="1.8"/><circle cx="148" cy="160" r="9.5" fill="#0fa07f" fill-opacity="0.25" stroke="#0fa07f" stroke-width="1.6"/><text x="148" y="164" font-size="10" text-anchor="middle" font-weight="700" fill="#0fa07f">2</text><text x="163" y="164" font-size="9" font-weight="700" fill="#0fa07f">backfill</text>
    <text x="142" y="186" font-size="7.5" opacity="0.9" fill="currentColor">rate-limited</text><text x="142" y="198" font-size="7.5" opacity="0.9" fill="currentColor">batches, INSERT</text><text x="142" y="210" font-size="7.5" opacity="0.9" fill="currentColor">IF NOT EXISTS</text><text x="192.0" y="230" font-size="8.5" text-anchor="middle" font-weight="700" fill="#0fa07f">reversible</text>
    <path d="M252 190 L 258 190" fill="none" stroke="currentColor" stroke-width="1.4" marker-end="url(#p11-08-a4)"/><text x="192.0" y="283" font-size="7.5" text-anchor="middle" opacity="0.85" fill="currentColor">TRUNCATE the new tables</text><rect x="256" y="142" width="120" height="96" rx="9" fill="#0fa07f" fill-opacity="0.13" stroke="#0fa07f" stroke-width="1.8"/><circle cx="272" cy="160" r="9.5" fill="#0fa07f" fill-opacity="0.25" stroke="#0fa07f" stroke-width="1.6"/><text x="272" y="164" font-size="10" text-anchor="middle" font-weight="700" fill="#0fa07f">3</text>
    <text x="287" y="164" font-size="9" font-weight="700" fill="#0fa07f">verify</text><text x="266" y="186" font-size="7.5" opacity="0.9" fill="currentColor">per-bucket counts</text><text x="266" y="198" font-size="7.5" opacity="0.9" fill="currentColor">+ checksums,</text><text x="266" y="210" font-size="7.5" opacity="0.9" fill="currentColor">old vs new</text>
    <text x="316.0" y="230" font-size="8.5" text-anchor="middle" font-weight="700" fill="#0fa07f">reversible</text><path d="M376 190 L 382 190" fill="none" stroke="currentColor" stroke-width="1.4" marker-end="url(#p11-08-a4)"/><text x="316.0" y="270" font-size="7.5" text-anchor="middle" opacity="0.85" fill="currentColor">nothing changed yet</text><rect x="380" y="142" width="120" height="96" rx="9" fill="#0fa07f" fill-opacity="0.13" stroke="#0fa07f" stroke-width="1.8"/><circle cx="396" cy="160" r="9.5" fill="#0fa07f" fill-opacity="0.25" stroke="#0fa07f" stroke-width="1.6"/>
    <text x="396" y="164" font-size="10" text-anchor="middle" font-weight="700" fill="#0fa07f">4</text><text x="411" y="164" font-size="9" font-weight="700" fill="#0fa07f">shadow-read</text><text x="390" y="186" font-size="7.5" opacity="0.9" fill="currentColor">serve from old,</text><text x="390" y="198" font-size="7.5" opacity="0.9" fill="currentColor">ALSO read new,</text>
    <text x="390" y="210" font-size="7.5" opacity="0.9" fill="currentColor">compare, discard</text><text x="440.0" y="230" font-size="8.5" text-anchor="middle" font-weight="700" fill="#0fa07f">reversible</text><path d="M500 190 L 506 190" fill="none" stroke="currentColor" stroke-width="1.4" marker-end="url(#p11-08-a4)"/><text x="440.0" y="283" font-size="7.5" text-anchor="middle" opacity="0.85" fill="currentColor">stop shadow-reading</text>
    <rect x="504" y="142" width="120" height="96" rx="9" fill="#0fa07f" fill-opacity="0.13" stroke="#0fa07f" stroke-width="1.8"/><circle cx="520" cy="160" r="9.5" fill="#0fa07f" fill-opacity="0.25" stroke="#0fa07f" stroke-width="1.6"/><text x="520" y="164" font-size="10" text-anchor="middle" font-weight="700" fill="#0fa07f">5</text><text x="535" y="164" font-size="9" font-weight="700" fill="#0fa07f">flip reads</text><text x="514" y="186" font-size="7.5" opacity="0.9" fill="currentColor">feature flag,</text>
    <text x="514" y="198" font-size="7.5" opacity="0.9" fill="currentColor">1% -&gt; 100%; old</text><text x="514" y="210" font-size="7.5" opacity="0.9" fill="currentColor">still written</text><text x="564.0" y="230" font-size="8.5" text-anchor="middle" font-weight="700" fill="#0fa07f">reversible</text><path d="M624 190 L 630 190" fill="none" stroke="currentColor" stroke-width="1.4" marker-end="url(#p11-08-a4)"/>
    <text x="564.0" y="270" font-size="7.5" text-anchor="middle" opacity="0.85" fill="currentColor">flip the flag back</text><rect x="628" y="142" width="120" height="96" rx="9" fill="#e0930f" fill-opacity="0.13" stroke="#e0930f" stroke-width="1.8"/><circle cx="644" cy="160" r="9.5" fill="#e0930f" fill-opacity="0.25" stroke="#e0930f" stroke-width="1.6"/><text x="644" y="164" font-size="10" text-anchor="middle" font-weight="700" fill="#e0930f">6</text><text x="659" y="164" font-size="9" font-weight="700" fill="#e0930f">stop dbl-write</text>
    <text x="638" y="186" font-size="7.5" opacity="0.9" fill="currentColor">new becomes the</text><text x="638" y="198" font-size="7.5" opacity="0.9" fill="currentColor">only source of</text><text x="638" y="210" font-size="7.5" opacity="0.9" fill="currentColor">truth</text><text x="688.0" y="230" font-size="8.5" text-anchor="middle" font-weight="700" fill="#e0930f">one-way</text>
    <path d="M748 190 L 754 190" fill="none" stroke="currentColor" stroke-width="1.4" marker-end="url(#p11-08-a4)"/><text x="688.0" y="283" font-size="7.5" text-anchor="middle" font-weight="700" fill="#e0930f">none — you are committed</text><rect x="752" y="142" width="120" height="96" rx="9" fill="#d64545" fill-opacity="0.13" stroke="#d64545" stroke-width="1.8"/><circle cx="768" cy="160" r="9.5" fill="#d64545" fill-opacity="0.25" stroke="#d64545" stroke-width="1.6"/><text x="768" y="164" font-size="10" text-anchor="middle" font-weight="700" fill="#d64545">7</text>
    <text x="783" y="164" font-size="9" font-weight="700" fill="#d64545">drop old</text><text x="762" y="186" font-size="7.5" opacity="0.9" fill="currentColor">days later, after</text><text x="762" y="198" font-size="7.5" opacity="0.9" fill="currentColor">a full backup</text><text x="762" y="210" font-size="7.5" opacity="0.9" fill="currentColor">cycle</text>
    <text x="812.0" y="230" font-size="8.5" text-anchor="middle" font-weight="700" fill="#d64545">destructive</text><text x="812.0" y="270" font-size="7.5" text-anchor="middle" font-weight="700" fill="#d64545">restore from backup</text><path d="M564.0 296 C 564.0 322, 68.0 322, 68.0 300" fill="none" stroke="#0fa07f" stroke-width="1.5" stroke-dasharray="5 4" marker-end="url(#p11-08-a4r)"/><text x="316.0" y="336" font-size="9.5" text-anchor="middle" font-weight="700" fill="#0fa07f">any of steps 1-5: flip one flag and you are back where you started</text>
    <text x="8" y="256" font-size="8.5" font-weight="700" opacity="0.85" fill="currentColor">rollback action:</text><path d="M626.0 62 L 626.0 250" fill="none" stroke="#d64545" stroke-width="2" stroke-dasharray="6 5"/><text x="616.0" y="78" font-size="10" text-anchor="end" font-weight="700" fill="#0fa07f">REVERSIBLE — old is still authoritative</text><text x="616.0" y="94" font-size="8.5" text-anchor="end" opacity="0.85" fill="currentColor">the new topology is a copy you can throw away</text>
    <text x="616.0" y="108" font-size="8.5" text-anchor="end" opacity="0.85" fill="currentColor">at any moment, with no data loss</text><text x="636.0" y="78" font-size="10" font-weight="700" fill="#d64545">POINT OF NO RETURN</text><text x="636.0" y="94" font-size="8.5" opacity="0.85" fill="currentColor">old starts drifting the second you stop</text><text x="636.0" y="108" font-size="8.5" opacity="0.85" fill="currentColor">writing to it; the gap only widens</text>
    <text x="440" y="364" font-size="10.5" text-anchor="middle" opacity="0.95" fill="currentColor">Measured: skipping step 1 corrupted 2,286 of 20,000 rows (11.43%). Doing step 2 without INSERT IF NOT EXISTS corrupted 35 (0.17%).</text><text x="440" y="382" font-size="11" text-anchor="middle" font-weight="700" fill="#d64545">Both pass every health check you own. Only steps 3 and 4 find them.</text>
  </g>
</svg>
```

**1 · Double-write.** Deploy code that writes to both topologies on every write, behind a flag. Old is still the source of truth; new is a write-only copy nobody reads. *Reversible: turn the flag off.*

**2 · Backfill.** Copy historical data in batches, rate-limited so the copy never competes with production traffic. The copy must be **`INSERT ... IF NOT EXISTS`** (Postgres: `ON CONFLICT DO NOTHING`) or version-guarded — anything already in the destination arrived via a double-write and is newer than your snapshot. *Reversible: truncate the new tables.*

**3 · Verify.** Per-bucket row counts and checksums, old against new, plus a full-table comparison if you can afford it. This is the step people skip because steps 1 and 2 "obviously worked". *Reversible: nothing has changed yet.*

**4 · Shadow-read.** Serve every read from old as usual, and *also* run it against new, compare the two, report mismatches as a metric, and throw the new result away. This is the only step that exercises the new topology under real query shapes and real concurrency without exposing a single user to it. *Reversible: stop shadow-reading.*

**5 · Flip reads.** Move reads to the new topology behind a feature flag, ramped: 1%, 10%, 50%, 100%. Old is still being double-written the whole time, so it stays perfectly current. *Reversible: flip the flag back — instantly, with no data loss.*

**6 · Stop double-writing.** **This is the point of no return.** The instant you stop writing to old, old begins to drift, and the gap widens every second. Rolling back after this means replaying writes, not flipping a flag. Sit at step 5 for days.

**7 · Drop the old tables.** Days later, after a full backup cycle has aged out. *Recoverable only from backup.*

The measured cost of getting the order wrong, over 20,000 rows and 10,000 concurrent writes with a byte-identical write stream in all three runs:

```text
  procedure                                  stale copies   rows wrong   verify
  1. copy first, double-write after                    56        2,286     FAIL
  2. double-write on, copier overwrites                56           35     FAIL
  3. double-write FIRST, insert-if-absent               0            0     PASS
```

Run 1 is the obvious mistake: **2,286 wrong rows, 11.43%** — every write that landed after its row was copied and before double-writing started. On a real table that window is the entire backfill, which is hours.

Run 2 is the subtle one, and it is the reason this section exists. Double-writes are on the whole time. The copier still corrupts **35 rows, 0.17%**, because copying is a read followed by a write and something can happen in between: the copier reads version 5, a live write sets both copies to version 6, the copier writes its stale 5 over the top. **Copying is not idempotent unless it is conditional.** 0.17% sounds survivable until you scale it — the same rate on a 500-million-row table is **875,000 rows that are quietly, permanently wrong**, with no error, no alert, and no log line.

Run 3 turns double-writing on before the first row is read and never writes backwards. Zero wrong rows.

And this is what step 4 is for. The Build It also simulates a double-write path that silently drops 1 write in 400 — a plausible bug, a missing `await`, a swallowed exception:

```text
  step 4, shadow reads: serve 20,000 reads from OLD, run the same read against
  NEW, compare, report, discard. 45 of 20,000 double-writes were dropped
  (0.23%) and 48 shadow reads disagreed (0.24%).
```

That bug produces no errors, no latency change, and no replication lag. Every dashboard is green. **Shadow reading is the only step that makes it fail loudly while the blast radius is still zero.**

## Build It

[`code/sharding.py`](code/sharding.py) is six numbered arguments. Standard library only, seeded with `random.Random(7)`, a few seconds end to end. Three parts are worth reading.

**The hash is stable on purpose.** Python's `hash()` for strings is salted per process (PYTHONHASHSEED), so a shard map built on it would reshuffle every restart — which is a genuine production bug people ship:

```python
def h64(key: str) -> int:
    """A stable 64-bit hash. Python's hash() is salted per process; this is not."""
    return int.from_bytes(hashlib.blake2b(key.encode(), digest_size=8).digest(), "big")
```

**The bucket rebalance is the whole idea in a dozen lines.** Note what it does *not* do: it never touches `key → bucket`. It only decides which shard each bucket sits on, keeping every bucket where it is unless its shard is over its fair share:

```python
def bucket_map(n_buckets, n_shards, previous=None):
    """buckets -> shards. If `previous` is given, keep every bucket where it is
    unless a shard is over its fair share; that is the whole trick."""
    if previous is None:
        return [b % n_shards for b in range(n_buckets)]
    target = n_buckets / n_shards
    owned = {}
    for b, s in enumerate(previous):
        owned.setdefault(s, []).append(b)
    new = list(previous)
    donors = []
    for s, bs in owned.items():
        keep = int(math.floor(target))
        donors.extend(bs[keep:])          # everything above fair share is movable
    ...
```

**The migration harness** puts the double-write and the copier in the same loop so the race is real rather than asserted. The three modes differ by exactly two things — whether `dw` is true during the backfill, and whether the copier's write is conditional:

```python
for _ in range(writes_per_batch):            # production, mid-batch
    r = rng.randrange(n_rows)
    old[r] += 1
    if dw:
        new[r] = old[r]                      # double-write: blind upsert

for r, v in snapshot.items():                # the copier WRITES here
    if mode == "guarded":
        if r not in new:                     # insert-if-absent
            new[r] = v
        continue
    if old[r] != v:
        stale_copies += 1
    new[r] = v                               # unconditional overwrite
```

Run it:

```bash
docker compose exec -T app python \
  phases/11-scalability-and-reliability/08-sharding-the-data-tier/code/sharding.py
```

```console
== 1 · FOUR STRATEGIES OVER THE SAME KEYSPACE ==
  150,000 writes, 500 tenants, 8 shards.
  tenant 0 (the enterprise account) is 40.1% of all writes;
  the next 9 tenants together are 29.9%. tenant_id is assigned at
  signup, so low ids are old accounts and old accounts are the big ones.

  strategy                  s0    s1    s2    s3    s4    s5    s6    s7   max/min   hot   tenant-q
  range(tenant_id)        85.5   5.2   2.8   1.9   1.5   1.2   1.0   0.9     97.4x    s0          1
  hash(tenant_id)          2.6  17.7  10.5  47.7   4.4   6.3   6.1   4.7     18.1x    s3          1
  hash(order_id)          12.5  12.4  12.5  12.5  12.6  12.5  12.5  12.6      1.0x    s4          8
  directory(tenant_id)    40.1  11.5   8.1   8.1   8.1   8.1   8.1   8.1      5.0x    s0          1
  geographic(region)      32.2  18.0  12.1  10.9   7.9   6.1   9.0   3.9      8.2x    s0          1

  hash(tenant_id) spreads 499 tenants perfectly and still puts 47.7% on one shard:
  hashing randomises PLACEMENT, it does not randomise VOLUME.
  directory isolates the whale on s0 and balances the other 7 to 1.42x of each other,
  but no tenant-keyed scheme can put a 40% tenant on less than 40% of a shard.

== 2 · THE MONOTONIC KEY: A RANGE SHARD WITH SEVEN IDLE MACHINES ==
  scheme                    s0    s1    s2    s3    s4    s5    s6    s7   shards taking >1%
  range(order_id)          0.0   0.0   0.0   0.0   0.0   0.0   0.0 100.0                   1
  hash(order_id)          12.4  12.4  12.5  12.5  12.5  12.5  12.6  12.6                   8

  the fix is not free. 'SELECT * FROM orders WHERE order_id BETWEEN 1,040,000 AND 1,045,000'
    range(order_id): 1 shard   — a contiguous read, one machine
    hash(order_id) : 8 shards  — every row is somewhere else

== 3 · UNIFORM PLACEMENT IS NOT UNIFORM LOAD ==
  50,000 keys placed by hash, 400,000 accesses drawn Zipf(s=1.25).
  the hottest key is 23.1% of all traffic and it lives on s3.

  measure                   s0    s1    s2    s3    s4    s5    s6    s7   max/min
  keys placed (%)         12.3  12.5  12.4  12.6  12.6  12.8  12.2  12.5     1.05x
  load received (%)       17.2   7.5   5.0  29.0  10.0   5.4  17.3   8.6     5.83x

  now salt the hottest K keys into 16 suffixes each (key#0 .. key#15):
  salted load               s0    s1    s2    s3    s4    s5    s6    s7   max/min   read fan-out
  salt top 1  (23.1%)     23.0   8.9   9.3   7.3  14.4   8.3  18.8  10.0     3.15x          4.47x
  salt top 4  (42.7%)     17.4  13.6  12.3   8.3  18.0   9.2   9.6  11.6     2.18x          7.41x
  salt top 16 (60.3%)     17.0  12.3  15.1   9.7  15.7  11.0   9.6   9.7     1.76x         10.05x

== 4 · SCATTER-GATHER: A FAN-OUT IS THE MAX OF S SAMPLES ==
  one shard, 300,000 sampled responses: 99% fast,
  1% drawn from a Pareto(alpha=1.5) tail starting at 100 ms.
  so p, the chance ONE shard is in the slow path, is exactly 0.01 by construction.

  shards      p50      p99     p999    p99 vs S=1   P(slow) meas    1-(1-p)^S
       1       12       61      425         1.00x          0.98%        1.00%
       2       15      157      689         2.59x          1.98%        1.99%
       4       19      251      985         4.14x          3.93%        3.94%
       8       23      409     1304         6.74x          7.83%        7.73%
      16       28      622     2032        10.25x         14.89%       14.85%

  at S=8 a 1%-slow shard is a 7.8% chance the QUERY is slow (predicted 7.7%),
  and p99 goes from 61 ms to 409 ms — 6.7x — with no machine getting slower.

== 5 · RESHARDING 8 -> N: THE COST OF THE MAPPING YOU CHOSE ==
  120,000 keys currently on 8 shards. How many rows move?

  8 ->    naive hash % N    consistent ring    4096 virtual buckets    buckets moved
  9               88.9%               9.5%                   11.3%          456/4096
  10              80.1%              17.8%                   20.2%          820/4096
  12              66.8%              31.5%                   33.6%         1368/4096
  16              50.1%              48.9%                   50.0%         2048/4096

    hash % N     : key -> shard. Change N and EVERY key's identity changes.
    ring         : key -> point on a ring -> shard. Stable, but the unit of
                   movement is 'whatever fell in this arc' — unnamed, unbounded.
    virtual bkt  : key -> bucket (FIXED FOREVER) -> shard (a table you edit).
                   The unit of movement is bucket 1743: nameable, resumable,
                   checkpointable, revertible by editing one row.

  a note on ring balance — vnodes are not optional:
    ring,   1 vnode(s)/shard   max/min =  8.01x   hottest shard  35.2%
    ring, 160 vnode(s)/shard   max/min =  1.41x   hottest shard  14.8%

    buckets    at 9 shards    at 17 shards    at 40 shards
         16         2.000x            idle            idle
        256         1.036x          1.067x          1.167x
       4096         1.002x          1.004x          1.010x
      16384         1.001x          1.001x          1.002x

== 6 · THE MIGRATION: ORDERING IS THE ENTIRE ALGORITHM ==
  procedure                                  stale copies   rows wrong   verify
  1. copy first, double-write after                    56        2,286     FAIL
  2. double-write on, copier overwrites                56           35     FAIL
  3. double-write FIRST, insert-if-absent               0            0     PASS

  run 2's 0.17% sounds survivable until you scale it. Same rate on a
  500,000,000-row table is 875,000 rows that are quietly, permanently wrong,
  and nothing in the migration reports it. That is what step 3 exists for.

  step 4, shadow reads: serve 20,000 reads from OLD, run the same read against
  NEW, compare, report, discard. 45 of 20,000 double-writes were dropped
  (0.23%) and 48 shadow reads disagreed (0.24%).

  (total wall time 3.5 s)
```

Five of these are arguments rather than demos.

**Section 1** is the whole shard-key problem in one table. The row to stare at is `hash(tenant_id)`: a good hash function, 499 tenants spread flawlessly, and **47.7% of all writes on `s3`**. Hashing gave you uniform placement and you needed uniform *volume*, which no hash function can provide. `directory(tenant_id)` is the only row where a human made a choice, and it is the only one where the whale is isolated rather than merely relocated — and even then the overall imbalance is 5.0×, because a 40% tenant is 40% of a shard no matter where you put it. Then the last column, which is the price list: **`hash(order_id)` is the only balanced option at 1.02×, and the only one where every tenant-scoped query becomes an 8-way fan-out.**

**Section 2** is the mistake to never make. 100.0% of writes on one of eight machines, and the seven idle ones cannot help, because the key is a sequence and the sequence only goes one way. The second half is the honest part: hashing fixes it completely and turns a 1-shard range scan into an 8-shard one. There is no free version.

**Section 3** separates two things that get confused constantly. Keys are placed at 1.05× — essentially perfect. Load arrives at 5.83×. The salting rows show a real mitigation with a real bill: **3.15× imbalance for 4.47× the shard-touches** on one key, **1.76× for 10.05×** if you salt sixteen. And the diminishing return is structural, not a tuning problem — Zipf has no bottom, so there is always a next hottest key.

**Section 4** is the arithmetic every fan-out obeys. Measured 7.83% against a predicted 7.73% at S = 8 means you can compute this for your own system on the back of an envelope. The pairing that matters is p50 versus p99: **2.3× versus 10.2×** across the same sweep. Every test you run at the median says the fan-out is fine.

**Section 5 is the headline.** `hash % N` and virtual buckets cost the same 50% to double, and 88.9% versus 11.3% to add one machine. That is the difference between "we added a shard last Tuesday" and "we are planning a quarter to double the fleet". The ring-balance rows are the footnote people miss: consistent hashing with one point per shard is **8.01× out of balance**, and even 160 vnodes per shard leaves 1.41x. A bucket table is exactly balanced because you assign it.

**Section 6 is the one to reread before you run a migration.** The write stream is byte-identical across all three runs; only the *order* of operations differs. Copy first and you lose 11.43% of rows. Double-write correctly but copy unconditionally and you still lose 0.17% — 875,000 rows at production scale, silently. Only the version-guarded, double-write-first ordering passes. And the shadow-read block shows what verification is for: a double-write path dropping 1 write in 400 is invisible to every metric you have except a comparison against ground truth.

## Use It

**Vitess** is the canonical open-source implementation of everything above; it is what YouTube's MySQL tier became and what PlanetScale is built on. Its vocabulary maps directly onto this lesson. A **keyspace** is a logical database. A **vindex** is the shard-key function — `hash` is the default, and `lookup` vindexes are the directory strategy, implemented as a real table Vitess maintains for you so that queries on a *secondary* key can still be routed instead of scattered. Crucially, Vitess shards a keyspace by **keyspace-id ranges** rather than by a modulo, which is the virtual-bucket idea in its purest form: the key hashes to a 64-bit keyspace id once, and shards own ranges of that space. Splitting a shard means splitting a range. **VReplication** and `MoveTables` / `Reshard` implement exactly the seven-step procedure — copy phase, then a running replication stream that keeps the target current, then `VDiff` (that is step 3, verify), then `SwitchTraffic` for reads first and writes second (steps 5 and 6), with `ReverseTraffic` available until you `Complete`. If you want to see the diagram above as a production tool, that is it.

```bash
vtctldclient Reshard create --workflow r1 --target-keyspace commerce \
    --source-shards '0' --target-shards '-80,80-'
vtctldclient VDiff create --workflow r1 --target-keyspace commerce   # verify
vtctldclient Reshard SwitchTraffic --workflow r1 --tablet-types rdonly,replica
vtctldclient Reshard SwitchTraffic --workflow r1 --tablet-types primary
vtctldclient Reshard Complete --workflow r1        # <- the point of no return
```

**Citus** shards Postgres and is the shortest path from a single node. The distribution column is the shard key and it is declared once:

```sql
SELECT create_distributed_table('orders', 'tenant_id');
SELECT create_distributed_table('order_items', 'tenant_id',
                                colocate_with => 'orders');   -- same shard, always
SELECT create_reference_table('countries');   -- copied to every node
```

Three things there are worth internalising. **Colocation** is the answer to "no cross-shard joins" — two tables distributed on the same column have their matching rows on the same node, so joins and multi-statement transactions between them stay local and stay ACID. **Reference tables** are the answer to the small-lookup-table problem: `countries`, `currencies`, `feature_flags` are replicated in full to every node, so joining them never crosses the network. And Citus's `shard_count` (default 32) is a virtual-bucket count — shards are logical and get rebalanced across nodes with `rebalance_table_shards()`, which is why adding a node to Citus is an afternoon rather than a quarter. Set it high at creation.

**MongoDB** sharding will teach you the shard-key rules the hard way if you let it. `sh.shardCollection("db.orders", { tenantId: "hashed" })` picks the strategy; the collection is then divided into **chunks** that split as they grow and are moved between shards by the **balancer**. Two things the docs warn about loudly, both of which you have now measured: monotonically increasing shard keys send every insert to the chunk holding `MaxKey` (which is why `"hashed"` exists), and the shard key was historically **immutable** — you could not update the field, because the row would have to change machines. Choose it as though it were a primary key, because it is one.

**Cassandra and DynamoDB** make the shard key the first thing you write. In Cassandra, `PRIMARY KEY ((tenant_id), created_at)` declares `tenant_id` as the **partition key** — which node owns the row — and `created_at` as the **clustering key** — the sort order within that partition. That composite is the "hash something, range within it" answer to the monotonic-key problem, and it is why a partition that grows without bound is Cassandra's classic anti-pattern. DynamoDB's partition key and sort key are the same idea with different names, and its adaptive-capacity feature exists precisely because uniform placement is not uniform load. [Wide-Column Stores](../../04-nosql-and-data-modeling/04-wide-column-stores/) and [Key-Value Stores](../../04-nosql-and-data-modeling/02-key-value-stores/) cover the storage-engine side.

**Elasticsearch** is the cautionary tale. `number_of_shards` is fixed **at index creation** and cannot be changed — changing it requires reindexing into a new index. This is `hash % N` shipped as a product decision, and it is why every Elasticsearch capacity guide leads with "think hard about shard count", and why over-sharding (hundreds of tiny shards, each with its own Lucene overhead and each adding to every query's fan-out) is as common a failure as under-sharding.

**Postgres declarative partitioning** is the step that often removes the need for any of this:

```sql
CREATE TABLE events (id bigserial, tenant_id int, created_at timestamptz, body jsonb)
    PARTITION BY RANGE (created_at);
CREATE TABLE events_2026_07 PARTITION OF events
    FOR VALUES FROM ('2026-07-01') TO ('2026-08-01');
```

One machine, one transaction manager, one `UNIQUE` constraint, smaller indexes, per-partition `VACUUM`, and dropping July 2025 is a metadata operation instead of a 400-million-row `DELETE`. You keep every guarantee. Exhaust this before you shard.

**Before you shard — the checklist:**

- [ ] The bottleneck is **writes**, and you have the number. If reads dominate, you want replicas.
- [ ] Query and index tuning is exhausted; `pg_stat_statements` has nothing left worth fixing.
- [ ] You are on the largest instance that makes economic sense, and you measured the ceiling.
- [ ] Caching is deployed and its hit rate is where it should be.
- [ ] Cold data is archived out of the hot tables.
- [ ] Declarative partitioning is in place and did not solve it.
- [ ] Functional partitioning is done — the obviously separable tables already live elsewhere.
- [ ] You have listed your top 20 queries by volume and know the scatter-gather percentage of each shard-key candidate.
- [ ] The candidate key **cannot change value** for the life of a row.
- [ ] You have a plan for global ids (UUIDv7 / Snowflake / per-shard ranges) and for uniqueness constraints that must be global.
- [ ] You have written down which cross-shard transactions exist today and how each one becomes a saga or is redesigned into one shard.
- [ ] **You are using virtual buckets with a count you will never outgrow (4096 or 8192), not `hash % N`.**
- [ ] Routing lives in one library, used by every service, so the mapping can change in one place.

That last-but-one item is the one to fight for in review. Everything else on this list can be redone later at some cost. `hash % N` cannot.

## Think about it

1. Your top query by volume is `SELECT * FROM messages WHERE conversation_id = ? ORDER BY created_at DESC LIMIT 50`, and your top write is inserting a message. A conversation can have two participants or fifty thousand. Work through `conversation_id`, `user_id` and `(conversation_id, created_at bucket)` as shard keys — which queries become scatter-gather under each, and which one produces an unbounded partition?
2. Section 4 measured p99 rising 6.7× at S = 8 while p50 rose 1.9×. You have a fan-out query you cannot eliminate. Design the degraded response: what do you return when the eighth shard has not answered by the deadline, how does the caller know, and what would you have to change in the client contract to make that acceptable?
3. You are at step 5 of the migration — reads flipped to the new topology, double-writes still on — and shadow-read mismatches are at 0.02%. Is that a stop-the-migration number or a proceed number? What would you need to know about *which* rows disagree before you could tell, and what is the cheapest instrumentation that answers it?
4. Your directory service maps `tenant_id → shard_id` and every query consults it. Design its failure behaviour: what happens on a cache miss during a directory outage, what happens if two application instances hold different versions of the mapping during a bucket move, and which of those two failures is data loss rather than an error?
5. A 40% tenant sits alone on `s0` and the other seven shards are at 1.42× of each other. The tenant doubles. You can (a) split them across four shards with a composite key, (b) move them to a dedicated cluster, or (c) put them on a machine four times the size. For each, say what breaks in the query layer, what the rollback looks like, and which one you can do this week.

## Key takeaways

- **Sharding is partitioning across independent machines, and that is a different thing from partitioning within one.** Postgres declarative partitioning keeps one transaction manager, so `BEGIN`, joins, foreign keys and `UNIQUE` all still work. Eight servers have no process that can see two shards at once. Exhaust indexes, vertical scale, replicas, caching, cold-data archival, declarative partitioning and splitting by *table* before you split by *row*.
- **Hashing randomises placement, not volume.** Measured: 500 tenants hashed across 8 shards placed keys at 1.02× and still put **47.7% of writes on one shard**, because one tenant was 40.1% of the workload. Range sharding on the same data put **85.5% on one shard** (97.4×), because ids are assigned at signup and old accounts are big accounts. A directory fixes *isolation*, not balance: the whale alone on its shard, the other seven within **1.42×** of each other, overall still 5.0×.
- **A monotonically increasing shard key sends 100% of writes to one machine.** Measured exactly: 120,000 new orders, all of them on `s7`, seven shards idle. Splitting the hot range does not help — the new top range inherits everything. Hashing flattens it to 12.4–12.6% and turns a 1-shard range scan into an **8-shard** one. There is no free version; there is a composite key.
- **Uniform placement is not uniform load.** Keys placed at **1.05×** received load at **5.83×** under Zipf(1.25) access, with one key taking 23.1% of traffic. Salting that key bought **3.15×** at a cost of **4.47× more shard-touches**; salting the top 16 bought 1.76× at **10.05×**. Salt the key that is on fire, never the keyspace.
- **A fan-out's latency is the maximum of S samples, so p99 degrades far faster than p50.** Measured across 120,000 fan-outs per point: p50 went 12 → 28 ms (2.3×) while p99 went **61 → 622 ms (10.2×)**. The chance a query touches a slow shard follows `1 − (1−p)^S` exactly — **7.83% measured against 7.73% predicted at S = 8** for a shard that is slow just 1% of the time. Every query without the shard key pays this.
- **`hash % N` cannot add one machine.** Going 8 → 9 moves **88.9% of all rows**; the same change costs **11.3%** with 4096 virtual buckets and 9.5% with a consistent hash ring. Doubling costs ~50% under every scheme, so `hash % N` locks you into doubling forever. Hash once into a large fixed bucket count, then map buckets → shards in an editable table: rebalancing moves **456 named, resumable, revertible buckets** and rehashes zero keys. A ring with 1 vnode per shard is **8.01× out of balance**; 4096 buckets are flat to 1.002× at 9 shards and 1.010× at 40.
- **In a live migration the ordering is the algorithm, and the wrong order fails silently.** With a byte-identical write stream: backfilling before enabling double-writes corrupted **2,286 of 20,000 rows (11.43%)**; enabling double-writes but copying unconditionally still corrupted **35 (0.17%)** — 875,000 rows at 500 M scale — because a copy is a read then a write and a live update fits between them. Double-write **first**, copy with `INSERT ... IF NOT EXISTS`, and it is **0**.
- **Steps 1–5 are reversible with a feature flag; step 6 is not.** Stop double-writing and the old topology begins to drift immediately. Shadow-reading (step 4) is the only step that catches a double-write path dropping 1 write in 400 — measured at **0.24% of shadow reads disagreeing** while error rate, latency and replication lag were all perfectly normal.

Next: [Failure Domains, Blast Radius & Shuffle Sharding](../09-failure-domains-and-shuffle-sharding/) — this lesson split your data across eight machines that fail independently. The next one is about what "independently" is worth, how large a blast radius each shard actually has, and the counter-intuitive trick that makes one bad customer stop taking everyone else down with them.
