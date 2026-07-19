# Rollback, Backups & Disaster Recovery

> "We can always roll back" is a sentence with a hidden assumption, and this lesson measures it: across nine releases of a realistic history, **exactly one is a rollback target you can actually reach** — the other eight are blocked by two irreversible changes nobody flagged at review. Then the other half. A backup job returned exit code 0 for **31 consecutive nights** while silently omitting a table; the restore that discovered it lost **9,120 payment rows**. And an RTO nobody had timed: a measured **30.7 MB/s** of restore throughput turns a 2 TB database into an **18h 05m** recovery against a stated four-hour target.

**Type:** Build
**Languages:** Python
**Prerequisites:** [Zero-Downtime Schema & Contract Changes](../13-zero-downtime-schema-changes/), [Config, Environments & the Twelve-Factor App](../05-config-and-twelve-factor/), [Durability: Write-Ahead Logging](../../03-relational-databases/13-write-ahead-logging/)
**Time:** ~75 minutes

## The Problem

Three scenes. They escalate, and each one is the ordinary consequence of a decision that looked correct when it was made.

**03:14 — the rollback that made it worse.** Release 42 went out four hours ago. Error rate is 2%, climbing, and the graph has the shape everyone recognises. The on-call engineer does the thing every runbook says to do first: roll back. One command, the previous container image, thirty seconds. It is the safest action available and it is the right instinct.

The error rate goes to **100%**.

Release 42 shipped three changes in one release: a new artifact, a new config value, and a schema migration that added `orders.total_cents` and dropped `orders.total` in the same deploy. The rollback reverted exactly one of those three. The old code — the "known-good" code, the code that ran perfectly for six weeks — opens a connection, issues its first query, and gets `column orders.total does not exist`. Every request. There is no partial degradation and no cache to hide behind, because the failure is at the first statement of every code path. A 2% error rate was an incident. **100% is an outage, and the rollback caused it.**

It gets worse before it gets better. The engineer, now reasoning correctly about the cause, re-adds the dropped column. Errors go to zero. Dashboards green. And **200 of the next 200 orders are charged one hundred times the correct amount**, because the config value is still pointing at a catalogue that returns cents to code that expects whole currency units. Nothing alerts. A 5xx stops; **a wrong number persists**, and it persists in a table that other systems will read as truth for months.

**04:12 — the backup that had never been restored.** Different night, different company, same category of surprise. A destructive statement runs without a `WHERE` clause. The team is calm, because the team has backups: a nightly job, a dashboard of green ticks, thirty-one consecutive successes. They start a restore.

The `payments` table is not in it.

Not corrupted — **absent**. A migration created that table thirty-one nights earlier. The backup job's table list is a static array in a config file that the migration did not touch, so the job dutifully backed up the four tables it was told about and exited 0, every night, for a month. The backup size grew about 0.4% a night, exactly as it always had, so the size-anomaly alert had nothing to fire on either. **9,120 payment rows are unrecoverable**, and every order row that did restore now references a payment that does not exist. The backup never failed. It succeeded, thirty-one times, at doing the wrong thing.

**The sentence underneath both scenes.** Every team says "we have backups." Almost always, the honest translation is **"we have files we have never read."** A backup is not an artifact; it is a *claim* — that a specific set of bytes can be turned back into a working system, by a specific person, within a specific time, having lost no more than a specific amount of data. Every word in that claim is testable. Most teams have tested none of them, and discover which parts were false at 04:12, under time pressure, on the worst night of the quarter.

This lesson makes each of those words measurable.

## The Concept

### Rollback or roll forward — decide before the incident, not during it

There are two ways out of a bad release.

**Rollback** returns the system to a state that was recently known to be good. Its enormous advantage is that the target state has *already been observed working in production* — no new code, no new hypothesis, no reasoning required at 03:14 by someone who has been awake for nineteen hours. **Under time pressure, rollback is the right default,** because it is the only option whose outcome you already have evidence for.

**Roll forward** ships a new release that fixes the problem. It is correct in two specific situations, and you should be able to name them: when the previous state is **unreachable** (which is most of this lesson), or when the fix is **trivial, well understood, and already reviewed** — a one-character constant, a feature flag flip, a config value. Note that "already reviewed" is doing real work in that sentence. Writing new code during an incident and shipping it without review has a failure rate that nobody measures because the failures get absorbed into the original incident.

The decision itself must be made **in advance**, written down, and reduced to something a tired person can execute:

> If the previous release is reachable → roll back, then diagnose.
> If it is not reachable → roll forward, and the runbook must already say what "forward" means.

The word doing all the work is **reachable**, and almost nobody computes it.

### The central idea: a deploy is reversible only if every change in it is

Here is the whole lesson in one line:

> **A release is reversible only if every change inside it is reversible. One irreversible change makes the entire release irreversible — and nobody notices until they try.**

Reversibility is not a property of your deployment tool. Your tool can put any image back on any server in thirty seconds; that has never been the hard part. Reversibility is a property of **the world the release left behind**. Roll the code back and the code runs against the *current* database, the *current* message topics, the *current* downstream contracts — not the ones that existed when it was written.

So enumerate the irreversible changes plainly, because the list is short and every item is easy to ship without noticing:

- **A contracted schema.** A dropped column, a dropped table, a narrowed type, a tightened constraint. Lesson 13's expand/contract sequence exists precisely to keep the expand phase reversible; the **contract** phase is the point of no return, and it is usually done by someone tidying up weeks later.
- **A consumed message.** Once a consumer has advanced its offset past a message and the topic's retention window has moved on, the old consumer cannot re-read it. Dropping support for an old payload version is the same class of change — see [Schema Evolution & Event Contracts](../../06-messaging-and-pub-sub/12-schema-evolution-and-event-contracts/).
- **A sent email or push notification.** There is no `DELETE` for someone's inbox.
- **A charged card.** Refundable, which is not the same as reversible: it costs money, support time and trust, and it is visible to the customer.
- **A migrated data format.** If the transform is lossy — normalising, truncating, re-encoding, collapsing two fields into one — the original is gone the moment you stop dual-writing.
- **Any external call with no undo.** A webhook delivered to a partner, a row written to someone else's system, a DNS change that has propagated, a file published to a CDN.

The build measures a ten-release history and asks, for each earlier release, *does everything this code touches still exist?* The answer is that **one** of nine is reachable. Two changes are responsible for all of it:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 486" width="100%" style="max-width:840px" role="img" aria-label="A timeline of ten releases with two irreversible barriers drawn as walls. Release seven dropped the database column user.name, which blocks rollback to releases one through five. Release nine dropped the message topic orders version one, which blocks rollback to releases one through eight. Only release nine is reachable from the current release ten, and it needs one config key reverted. Two irreversible side effects are marked: release nine sent twelve thousand four hundred and twelve verification emails and release ten charged one thousand two hundred and four cards, neither of which a rollback undoes.">
  <defs>
    <marker id="l14-a1" markerWidth="9" markerHeight="9" refX="5.5" refY="3" orient="auto"><path d="M0,0 L6.5,3 L0,6 Z" fill="currentColor"/></marker>
  </defs>
  <text x="440" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">Rollback reachability: 8 of the last 9 releases are not rollback targets</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <g fill="none" stroke-width="1.8" stroke-linejoin="round">
      <rect x="60" y="48" width="368" height="54" rx="9" fill="#d64545" fill-opacity="0.11" stroke="#d64545"/><rect x="470" y="48" width="380" height="54" rx="9" fill="#d64545" fill-opacity="0.11" stroke="#d64545"/>
    </g>
    <g fill="currentColor">
      <text x="74" y="68" font-size="10.5" font-weight="700" fill="#d64545">WALL 1 &#8195; release 7 &#8195; DROP COLUMN user.name</text><text x="74" y="84" font-size="9.5" opacity="0.9">a contracted schema. Every earlier build still reads that</text>
      <text x="74" y="96" font-size="9.5" opacity="0.9">column, so v1-v5 have no rollback path at all.</text><text x="484" y="68" font-size="10.5" font-weight="700" fill="#d64545">WALL 2 &#8195; release 9 &#8195; dropped topic:orders.v1</text>
      <text x="484" y="84" font-size="9.5" opacity="0.9">consumers went v2-only in the same release. Blocks v1-v8:</text><text x="484" y="96" font-size="9.5" opacity="0.9">this one wall alone costs you every earlier target.</text>
    </g>
    <g fill="none" stroke="#d64545" stroke-width="1.5" stroke-dasharray="4 4">
      <path d="M420 102 L 440 142" marker-end="url(#l14-a1)"/><path d="M640 102 L 686 142" marker-end="url(#l14-a1)"/>
    </g>

    <g fill="none" stroke-width="1.9" stroke-linejoin="round">
      <rect x="36" y="150" width="70" height="60" rx="8" fill="#d64545" fill-opacity="0.12" stroke="#d64545"/><rect x="118" y="150" width="70" height="60" rx="8" fill="#d64545" fill-opacity="0.12" stroke="#d64545"/><rect x="200" y="150" width="70" height="60" rx="8" fill="#d64545" fill-opacity="0.12" stroke="#d64545"/>
      <rect x="282" y="150" width="70" height="60" rx="8" fill="#d64545" fill-opacity="0.12" stroke="#d64545"/><rect x="364" y="150" width="70" height="60" rx="8" fill="#d64545" fill-opacity="0.12" stroke="#d64545"/><rect x="446" y="150" width="70" height="60" rx="8" fill="#d64545" fill-opacity="0.12" stroke="#d64545"/>
      <rect x="528" y="150" width="70" height="60" rx="8" fill="#d64545" fill-opacity="0.12" stroke="#d64545"/><rect x="610" y="150" width="70" height="60" rx="8" fill="#d64545" fill-opacity="0.12" stroke="#d64545"/><rect x="692" y="150" width="70" height="60" rx="8" fill="#0fa07f" fill-opacity="0.16" stroke="#0fa07f"/>
      <rect x="774" y="150" width="70" height="60" rx="8" fill="#7c5cff" fill-opacity="0.16" stroke="#7c5cff"/>
    </g>
    <g fill="none" stroke="#d64545" stroke-width="6" stroke-linecap="round">
      <path d="M440 138 L 440 224"/><path d="M686 138 L 686 224"/>
    </g>
    <g fill="currentColor" text-anchor="middle">
      <text x="71" y="176" font-size="13" font-weight="700">v1</text><text x="153" y="176" font-size="13" font-weight="700">v2</text><text x="235" y="176" font-size="13" font-weight="700">v3</text><text x="317" y="176" font-size="13" font-weight="700">v4</text>
      <text x="399" y="176" font-size="13" font-weight="700">v5</text><text x="481" y="176" font-size="13" font-weight="700">v6</text><text x="563" y="176" font-size="13" font-weight="700">v7</text><text x="645" y="176" font-size="13" font-weight="700">v8</text>
      <text x="727" y="176" font-size="13" font-weight="700" fill="#0fa07f">v9</text><text x="809" y="176" font-size="13" font-weight="700" fill="#7c5cff">v10</text><text x="71" y="196" font-size="8.5" opacity="0.75">a1c3e0</text><text x="153" y="196" font-size="8.5" opacity="0.75">b7e042</text>
      <text x="235" y="196" font-size="8.5" opacity="0.75">c2f9a8</text><text x="317" y="196" font-size="8.5" opacity="0.75">d4a17b</text><text x="399" y="196" font-size="8.5" opacity="0.75">e8b6cc</text><text x="481" y="196" font-size="8.5" opacity="0.75">f1d803</text>
      <text x="563" y="196" font-size="8.5" opacity="0.75">9a2c5e</text><text x="645" y="196" font-size="8.5" opacity="0.75">3e5f11</text><text x="727" y="196" font-size="8.5" opacity="0.75">6b0d7a</text><text x="809" y="196" font-size="8.5" opacity="0.75">8c7419</text>
      <text x="809" y="140" font-size="9" font-weight="700" fill="#7c5cff">CURRENT</text>
    </g>

    <g fill="none" stroke-width="1.8">
      <path d="M36 236 L 36 244 L 680 244 L 680 236" stroke="#d64545"/><path d="M692 236 L 692 244 L 762 244 L 762 236" stroke="#0fa07f"/>
    </g>
    <g fill="currentColor">
      <text x="358" y="262" font-size="11" font-weight="700" text-anchor="middle" fill="#d64545">8 BLOCKED &#8195; no rollback path exists at any price</text>
      <text x="727" y="262" font-size="10" font-weight="700" text-anchor="middle" fill="#0fa07f">1 REACHABLE</text><text x="727" y="276" font-size="8.5" text-anchor="middle" opacity="0.9">revert 1 config key:</text><text x="727" y="288" font-size="8.5" text-anchor="middle" opacity="0.9">PRICE_ROUNDING</text>
    </g>

    <text x="36" y="322" font-size="10" font-weight="700" fill="#e0930f">IRREVERSIBLE SIDE EFFECTS STILL IN THE WINDOW &#8195; a rollback does not undo these</text>
    <g fill="none" stroke-width="1.8" stroke-linejoin="round">
      <rect x="36" y="332" width="392" height="44" rx="8" fill="#e0930f" fill-opacity="0.13" stroke="#e0930f"/><rect x="446" y="332" width="392" height="44" rx="8" fill="#e0930f" fill-opacity="0.13" stroke="#e0930f"/>
    </g>
    <g fill="currentColor">
      <text x="50" y="350" font-size="10" font-weight="700">v9 &#8195; 12,412 'verify your email' messages sent</text><text x="50" y="366" font-size="9" opacity="0.9">delivered to real inboxes. There is no DELETE for that.</text><text x="460" y="350" font-size="10" font-weight="700">v10 &#8195; 1,204 cards charged, new rounding rule</text>
      <text x="460" y="366" font-size="9" opacity="0.9">refundable is not the same word as reversible.</text>
    </g>

    <rect x="36" y="390" width="802" height="52" rx="8" fill="#0fa07f" fill-opacity="0.12" stroke="#0fa07f" stroke-width="1.8"/>
    <g fill="currentColor">
      <text x="50" y="408" font-size="10.5" font-weight="700" fill="#0fa07f">THE CHEAPEST FIX IN THIS DIAGRAM</text><text x="50" y="423" font-size="9.5" opacity="0.95">had v9's consumers accepted BOTH payload versions instead of going v2-only,</text>
      <text x="50" y="436" font-size="9.5" opacity="0.95">reachable releases go 1 -&gt; 4. One line of tolerance, three more targets.</text>
    </g>
    <text x="440" y="470" font-size="11" text-anchor="middle" fill="currentColor" opacity="0.9">Reversibility is a property of the world the release left behind, not of your deploy tool.</text>
  </g>
</svg>
```

Two things in that picture are worth sitting with. First, **a single wall invalidates everything behind it** — release 9's topic drop alone costs you eight rollback targets, and it was one line in a consumer config. Second, **nothing in a normal deployment pipeline computes this.** The pipeline knows how to put v8's image back on the servers. It has no idea that v8's image cannot run. The reachable set is knowable *before* you deploy — it is a static analysis over "what does this build read" versus "what has been dropped" — and computing it takes about forty lines.

### Three things roll back separately

Lesson 5 established the identity `release = build + config`: the same immutable artifact with different configuration is a different release, which is why a config change is a deploy and needs a version. Lesson 13 added the third: the schema the code runs against. So a release is really three things, and **each one has its own rollback with its own mechanism, its own speed, and its own failure mode.**

| Layer | Rolled back by | Speed | Fails like |
|---|---|---|---|
| **Artifact** | redeploy the previous image digest | seconds | cleanly — the wrong code, but running code |
| **Config** | revert the config version and reload | seconds | silently — wrong values, no errors, bad numbers |
| **Schema** | a **forward** migration, if the data still exists | minutes to hours, `O(rows)` | totally — every query fails at the first statement |

The third row is the one that surprises people. **There is no such thing as rolling a schema back.** What you can do is apply a *new forward migration* that re-creates what the old code needs, and that only works if the data is still derivable from something that still exists. Re-adding a dropped column is a new `ADD COLUMN` plus a backfill over every row, and backfill is `O(rows)` — the build measures the per-row cost on 200 rows and the real table is 18.2M rows, **91,000× the work**, batched to respect lock and replication limits. That is not a thirty-second operation, and it is happening while you are down.

And if the column's data exists *nowhere else* — no dual-write, no derivable source — then no sequence of operations gets you back at all. The rollback does not exist. It is not slow; it is absent.

The opening scene is what happens when a team calls "revert the deployment" a rollback while only reverting one of the three layers. The build runs all four combinations and the results are on a spectrum from bad to worse.

### Backups: full, incremental, and the chain that is only as strong as its weakest link

A **full backup** copies everything. An **incremental** copies only what changed since the previous backup. Incrementals are cheap to take and cheap to store, which is why they are the default everywhere, and they introduce one property that people consistently under-price: **a dependency chain.**

To restore to night 11 from a chain of one full plus eleven incrementals, you must successfully read **all twelve parts, in order**. Part 5 being unreadable does not cost you part 5; it costs you **everything after it**. The build corrupts one byte in one incremental and measures the result: the restore stops after applying 5 parts, the recovered state is the end of night 4, and **840 of 2,520 orders are missing entirely with another 215 stale** — 168 hours of writes gone to a single flipped byte.

The fix is not exotic. Taking a **weekly full** — a second full backup at night 7 — puts the restore on a path of `full(7) + 4 incrementals` that does not include the damaged part at all: **0 missing, 0 stale**, same corruption, same night. The bad link is still on the shelf; it is simply no longer on the path.

Which makes chain length a **reliability number, not a storage detail.** With a per-part probability of an unreadable object of just 0.20% — bit rot, a truncated upload, an expired encryption key, a lifecycle rule that expired one object early — the arithmetic is brutal:

```text
  links   P(whole chain restores)
      4    99.20%
      7    98.61%
     11    97.82%
     30    94.17%
     90    83.51%   <- nightly incrementals, quarterly full
```

Nightly incrementals with a quarterly full is a completely normal-sounding policy, and it is **a one-in-six chance that your restore does not complete**. Nobody chose that number. It fell out of a retention setting.

### Point-in-time recovery: your RPO is the WAL, not the backup schedule

Phase 3's [write-ahead log](../../03-relational-databases/13-write-ahead-logging/) exists so a committed transaction survives a crash: the intent is written to a sequential log and flushed *before* the data pages are updated. That same log is the most valuable disaster-recovery asset you own, because it is an ordered, timestamped record of **every change since the last base backup**.

**PITR (Point-In-Time Recovery)** means: restore the base backup, then replay the WAL forward and *stop at a chosen instant*. Not "restore last night's backup" — restore to 08:58:09.083, one second before the destructive statement ran.

The build models exactly that. A base backup at 02:00. Nearly seven hours of traffic. Then `DELETE FROM orders WHERE status = 'pending'` with no tenant filter, removing **4,780 of 8,711 rows** in one statement. Two recovery strategies, and the gap between them is the entire argument:

- **Base backup only:** you get the 6,000 rows that existed at 02:00 and you throw away the **2,711 orders written since**. Data loss: **6h 58m 10s**.
- **Base backup + WAL replay to one second before the statement:** 4,985 records replayed, **8,711 rows restored** — every row that existed the instant before the mistake. Data loss: the **2.016 s** between the last replayed WAL record and the statement itself.

That is a **12,443×** improvement, and it comes from log shipping you already have running for replication. The lesson to take is a redefinition:

> **Your RPO is not your backup schedule. It is your WAL shipping interval.**

Note also *why* the achieved RPO is 1.016 s rather than zero: you can only stop at a record that exists. The build's WAL has a mean inter-record gap of 5.03 s and a longest gap of 50.09 s, so the granularity of "just before" is bounded by write frequency. On a busy production database the gaps are microseconds; on a quiet one at 04:00 they are seconds. **Your recovery precision is worst exactly when your system is quietest, which is when most disasters get noticed.**

### RPO and RTO, defined precisely

These two acronyms are in every DR document and are routinely written down as aspirations rather than measurements. Definitions first (they match NIST SP 800-34, the US federal contingency-planning standard):

- **RPO — Recovery Point Objective.** How much data you can afford to lose, expressed as time. It is bounded by **how often you capture state**: nightly backups mean an RPO of up to 24 hours; WAL archived every 60 seconds means an RPO of about 60 seconds; synchronous replication means an RPO near zero. RPO is decided by your *replication and backup frequency*, and it costs write latency and money.
- **RTO — Recovery Time Objective.** How long until the service is serving again. It is dominated by **restore throughput** — bytes per second of data you can turn back into a running database — plus the human time to notice, decide, find the runbook and type the commands.

RPO is the gap *before* the incident; RTO is the gap *after* it.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 492" width="100%" style="max-width:840px" role="img" aria-label="One timeline showing both recovery objectives. The base backup is at 02:00 and the destructive delete statement runs at 08:58:10, so recovering from the nightly backup alone loses six hours fifty-eight minutes of writes, or 2711 orders. Recovery time objective is the gap after the incident, dominated by restore throughput: a measured 30.7 megabytes per second means a 2 terabyte restore takes 18 hours 5 minutes against a stated 4 hour target. A zoomed inset of the last three seconds shows write-ahead-log records as ticks, the last replayed record at 08:58:08.067, the recovery target at 08:58:09.083, and the delete at 08:58:10.083, giving an achieved recovery point objective of 2.016 seconds instead of nearly seven hours.">
  <defs>
    <marker id="l14-a2" markerWidth="10" markerHeight="10" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker>
  </defs>
  <text x="440" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">RPO is what you lose. RTO is how long you are down. Both are measured.</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <g fill="none" stroke="#d64545" stroke-width="1.8">
      <path d="M110 96 L 110 128"/><path d="M560 96 L 560 128"/><path d="M110 96 L 560 96"/>
    </g>
    <g fill="currentColor" text-anchor="middle">
      <text x="335" y="70" font-size="11.5" font-weight="700" fill="#d64545">RPO &#8195; the data you lose</text><text x="335" y="86" font-size="10" opacity="0.95">nightly backup only: 6h 58m 10s = 2,711 orders written after 02:00, gone</text>
    </g>

    <path d="M40 172 L 856 172" fill="none" stroke="currentColor" stroke-width="1.6" marker-end="url(#l14-a2)"/>
    <g fill="none" stroke="currentColor" stroke-width="1.6">
      <path d="M110 166 L 110 178"/><path d="M560 166 L 560 178"/><path d="M800 166 L 800 178"/>
    </g>
    <g fill="none" stroke-width="2" stroke-linejoin="round">
      <rect x="60" y="132" width="100" height="30" rx="7" fill="#7c5cff" fill-opacity="0.15" stroke="#7c5cff"/><rect x="486" y="132" width="148" height="30" rx="7" fill="#d64545" fill-opacity="0.15" stroke="#d64545"/><rect x="742" y="132" width="116" height="30" rx="7" fill="#0fa07f" fill-opacity="0.15" stroke="#0fa07f"/>
    </g>
    <g fill="currentColor" text-anchor="middle">
      <text x="110" y="152" font-size="10" font-weight="700">base backup</text><text x="560" y="152" font-size="10" font-weight="700" fill="#d64545">the statement</text><text x="800" y="152" font-size="10" font-weight="700" fill="#0fa07f">serving again</text><text x="110" y="192" font-size="9.5" opacity="0.85">02:00:00.000</text>
      <text x="560" y="192" font-size="9.5" opacity="0.85">08:58:10.083</text><text x="800" y="192" font-size="9.5" opacity="0.85">+ RTO</text><text x="560" y="206" font-size="9" opacity="0.85" fill="#d64545">DELETE ... WHERE status='pending'</text>
    </g>

    <g fill="none" stroke="#e0930f" stroke-width="1.8">
      <path d="M560 224 L 560 254"/><path d="M800 224 L 800 254"/><path d="M560 254 L 800 254"/>
    </g>
    <g fill="currentColor">
      <text x="680" y="274" font-size="11.5" font-weight="700" text-anchor="middle" fill="#e0930f">RTO &#8195; how long you are down</text><text x="680" y="290" font-size="9.5" text-anchor="middle" opacity="0.95">measured 30.7 MB/s &#8594; 2 TB = 18h 05m</text>
      <text x="680" y="304" font-size="9.5" text-anchor="middle" opacity="0.95">against a stated 4h target: MISSES by 4.5x</text>
    </g>

    <rect x="36" y="318" width="802" height="134" rx="10" fill="#0fa07f" fill-opacity="0.09" stroke="#0fa07f" stroke-width="1.8"/><text x="50" y="338" font-size="10.5" font-weight="700" fill="#0fa07f">ZOOM &#8195; the last 3 seconds — this is what continuous WAL archiving buys</text>
    <path d="M110 386 L 730 386" fill="none" stroke="currentColor" stroke-width="1.4"/>
    <g fill="none" stroke="currentColor" stroke-width="1.2" opacity="0.55">
      <path d="M140 380 L 140 392"/><path d="M186 380 L 186 392"/><path d="M232 380 L 232 392"/><path d="M278 380 L 278 392"/><path d="M324 380 L 324 392"/><path d="M370 380 L 370 392"/><path d="M416 380 L 416 392"/>
    </g>
    <g fill="none" stroke-width="2.4">
      <path d="M480 374 L 480 398" stroke="#0fa07f"/><path d="M590 374 L 590 398" stroke="#3553ff"/><path d="M700 370 L 700 402" stroke="#d64545"/>
    </g>
    <g fill="none" stroke-width="1.4">
      <path d="M480 368 L 590 368" stroke="#3553ff"/><path d="M480 354 L 700 354" stroke="#d64545"/>
    </g>
    <g fill="currentColor">
      <text x="120" y="364" font-size="8.5" opacity="0.7">WAL records, mean gap 5.03 s</text><text x="535" y="364" font-size="9" text-anchor="middle" font-weight="700" fill="#3553ff">1.016 s</text><text x="590" y="350" font-size="9" text-anchor="middle" font-weight="700" fill="#d64545">2.016 s</text>
      <text x="480" y="416" font-size="8.5" text-anchor="middle" font-weight="700" fill="#0fa07f">08:58:08.067</text><text x="590" y="416" font-size="8.5" text-anchor="middle" font-weight="700" fill="#3553ff">08:58:09.083</text><text x="700" y="416" font-size="8.5" text-anchor="middle" font-weight="700" fill="#d64545">08:58:10.083</text>
      <text x="480" y="428" font-size="8.5" text-anchor="middle" opacity="0.85">last replayed record</text><text x="590" y="428" font-size="8.5" text-anchor="middle" opacity="0.85">recovery target</text><text x="700" y="428" font-size="8.5" text-anchor="middle" opacity="0.85">the DELETE</text>
      <text x="437" y="446" font-size="9.5" text-anchor="middle" font-weight="700" fill="#d64545">achieved RPO 2.016 s — against 6h 58m 10s from the backup alone: 12,443x better</text>
    </g>
    <text x="440" y="476" font-size="11" text-anchor="middle" fill="currentColor" opacity="0.9">RPO is bounded by how often you capture. RTO is bounded by restore throughput — and an RTO you have not timed is a wish.</text>
  </g>
</svg>
```

Now the uncomfortable arithmetic, which is where most DR documents fall apart.

**RPO.** A nightly backup means an RPO of *up to* 24 hours, because a disaster at 23:50 loses everything since 02:00. Teams write "RPO: 4 hours" in a document while running one nightly job. Those two facts are simply incompatible, and the incompatibility is arithmetic, not opinion.

**RTO.** This is worse, because the number is not merely optimistic — it is usually **unmeasured**. "RTO: 4 hours" is written by someone who has never timed a restore of the production dataset. The build times real restores at four sizes and finds throughput of **30.7 MB/s** on the largest sample. Extrapolate honestly:

| dataset | at 30.7 MB/s | vs a 4-hour RTO |
|---|---|---|
| 80 GB | 43m 25s | **MEETS** |
| 500 GB | 4h 31m 21s | misses by 1.1× |
| 2 TB | **18h 05m** | **misses by 4.5×** |

And that extrapolation is *optimistic*. It is a single stream reading a warm local file: no network transfer from object storage, no constraint or foreign-key validation, no index rebuild beyond one, no vacuum, no replica re-seeding, and an engineer who types the right command first time at 03:00. Every one of those adds hours.

One more measured detail, because it is the trap inside the measurement: **throughput is not a constant.** The small dumps restore at 51.9 MB/s and the largest at 30.7 MB/s, because the small ones fit entirely in page cache and your production restore will not. Benchmark on a small dataset and extrapolate and you will **over-read your real throughput by 1.7×**. Use the largest sample you can afford to run, and treat it as a ceiling.

Repeat the same restore five times and it ranges from **29.1 to 31.5 MB/s** on an idle sandbox with no competing load. **Your RTO is a distribution, not a scalar.** Plan against the slow end, because a real disaster is precisely when the storage backend is also busy with everyone else's recovery.

> **An RTO you have not timed is a wish.** Time it, write down the date you timed it, and re-time it whenever the dataset grows by half.

### A backup you have not restored is not a backup

The single highest-value practice in this lesson, and the one most often replaced by a green tick.

**A successful backup exit code proves that a program ran and did not crash.** It does not prove that the output is complete, readable, decryptable, or loadable by the engine you are running today. Those are four separate claims and the only thing that tests all four at once is **an actual restore**.

The build's sixth section is that failure end to end: 31 nights of exit code 0, four tables backed up out of five, size growing a plausible 0.4% a night so no anomaly alert fires, and a restore that yields **9,120 unrecoverable payment rows** and an orders table full of dangling references.

Then it bolts on verification, and the entire fix is four steps: **restore into a scratch namespace, list the tables, diff against the live catalogue, compare row counts.** It finds the fault **on the first run** — 31 nights before anyone needed the backup — and exits non-zero so a human gets paged. Nothing about it requires a vendor or a product.

What rots silently, and what each item needs a check for:

- **A table excluded by a changed filter.** A new table appears; the include-list does not. Diff the restored table set against the live catalogue.
- **An encryption key nobody kept.** The backups are perfect and unreadable. Restore-test with the key retrieval in the loop, from the account that would actually be doing it during an incident.
- **A format the current engine no longer reads.** You are on Postgres 16; that dump was written by 11. Restore into the version you actually run.
- **A chain with a broken link.** Verify checksums of every part, not just the newest.
- **A restore that no longer fits the maintenance window.** The dataset grew 40% and nobody re-timed it. Record the duration on every verification run and alert on the trend, not just on failure.

The one rule: **verification must be automated and scheduled.** A restore test that a human performs when they remember is a restore test that stops happening in month three.

### 3-2-1, immutability, and credential isolation

The **3-2-1 rule** is the old, durable heuristic: **3** copies of the data, on **2** different media or storage classes, with **1** off-site. It survives because each number defends against a different failure: three copies against random corruption, two media against a systematic defect in one technology, one off-site against fire, flood, and the destruction of a single region.

The ransomware era added a requirement that 3-2-1 does not cover, and it is the one most backup setups still fail:

> **Backups must be immutable and credential-isolated, because an attacker who obtains production credentials deletes the backups first.**

This is not a hypothetical; it is the standard playbook. Encrypting live data is only leverage if the victim cannot simply restore, so destroying the restore path is step one. If your production role can delete your backups, then **your backups have exactly the same blast radius as your production database** and all the copies in the world do not help. The same reasoning applies to a bad script or a mis-scoped Terraform apply — Lesson 6's plan/apply loop will cheerfully destroy a bucket if the state says so.

Three concrete defences, in increasing order of strength:

- **Object lock / write-once-read-many retention.** The storage layer itself refuses deletion until the retention period expires, *including* by the account owner. This is enforced below your permission model, which is the point.
- **A separate backup account or subscription**, with its own identity boundary. Production writes backups *in*; only a break-glass identity in the other account can delete them.
- **An offline or logically air-gapped copy** for the longest retention tier, with restore credentials that are not stored in the same secret manager as everything else — see [Secrets Management & Rotation](../../07-auth-and-security/13-secrets-management-and-rotation/).

And **retention is a policy question, not a storage question.** Decide how far back you must be able to go, which is usually set by how long a slow-burning corruption can go unnoticed — often far longer than a week — and by legal or regulatory obligations that may also require the opposite, that data be *destroyed* on schedule. Both are constraints on the same setting.

### DR tiers: four honest price tags

**DR (Disaster Recovery)** covers the loss of a whole environment, not one bad release. The industry taxonomy has four tiers, and the ladder is really a ladder of *cost*, since each rung buys you a smaller RTO and RPO by keeping more infrastructure running when nothing is wrong.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 484" width="100%" style="max-width:840px" role="img" aria-label="Four disaster recovery tiers as columns: backup and restore, pilot light, warm standby, and active-active. For each, the recovery time objective, recovery point objective, what is actually running when nothing is wrong, a green bar showing relative recovery speed and an amber bar showing relative steady-state cost. Backup and restore is anchored with a measured figure: 2 terabytes at 30.7 megabytes per second is 18 hours 5 minutes. A red note at the bottom warns that most real-world disaster recovery is availability-zone tolerance rather than region tolerance.">
  <text x="440" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">Four DR tiers — each rung buys a smaller RTO by running more when nothing is wrong</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <g fill="none" stroke-width="1.9" stroke-linejoin="round">
      <rect x="24" y="46" width="196" height="318" rx="11" fill="#7c5cff" fill-opacity="0.07" stroke="#7c5cff" stroke-opacity="0.7"/><rect x="244" y="46" width="196" height="318" rx="11" fill="#7c5cff" fill-opacity="0.07" stroke="#7c5cff" stroke-opacity="0.7"/>
      <rect x="464" y="46" width="196" height="318" rx="11" fill="#7c5cff" fill-opacity="0.07" stroke="#7c5cff" stroke-opacity="0.7"/><rect x="684" y="46" width="196" height="318" rx="11" fill="#7c5cff" fill-opacity="0.07" stroke="#7c5cff" stroke-opacity="0.7"/>
      <rect x="24" y="46" width="196" height="38" rx="11" fill="#7c5cff" fill-opacity="0.18" stroke="#7c5cff"/><rect x="244" y="46" width="196" height="38" rx="11" fill="#7c5cff" fill-opacity="0.18" stroke="#7c5cff"/><rect x="464" y="46" width="196" height="38" rx="11" fill="#7c5cff" fill-opacity="0.18" stroke="#7c5cff"/>
      <rect x="684" y="46" width="196" height="38" rx="11" fill="#7c5cff" fill-opacity="0.18" stroke="#7c5cff"/>
    </g>
    <g fill="currentColor" text-anchor="middle" font-size="11.5" font-weight="700">
      <text x="122" y="71">BACKUP &amp; RESTORE</text><text x="342" y="71">PILOT LIGHT</text><text x="562" y="71">WARM STANDBY</text><text x="782" y="71">ACTIVE-ACTIVE</text>
    </g>

    <g fill="currentColor" font-size="8.5" opacity="0.6">
      <text x="38" y="106">RTO</text><text x="258" y="106">RTO</text><text x="478" y="106">RTO</text><text x="698" y="106">RTO</text><text x="38" y="156">RPO</text><text x="258" y="156">RPO</text><text x="478" y="156">RPO</text><text x="698" y="156">RPO</text>
      <text x="38" y="206">RUNNING WHEN HEALTHY</text><text x="258" y="206">RUNNING WHEN HEALTHY</text><text x="478" y="206">RUNNING WHEN HEALTHY</text><text x="698" y="206">RUNNING WHEN HEALTHY</text>
    </g>
    <g fill="currentColor" font-size="11" font-weight="700">
      <text x="38" y="124">hours to days</text><text x="258" y="124">tens of minutes</text><text x="478" y="124">minutes</text><text x="698" y="124">near zero</text><text x="38" y="174">the backup interval</text><text x="258" y="174">seconds to minutes</text><text x="478" y="174">seconds</text><text x="698" y="174">near zero</text>
    </g>
    <g fill="currentColor" font-size="9" opacity="0.9">
      <text x="38" y="138">bounded by restore rate</text><text x="258" y="138">scale up the small copy</text><text x="478" y="138">shift traffic, scale out</text><text x="698" y="138">already serving</text>
      <text x="38" y="188">nightly = up to 24 h</text><text x="258" y="188">async replication</text><text x="478" y="188">continuous replication</text><text x="698" y="188">synchronous, costs latency</text>
      <text x="38" y="222">nothing. Objects in a</text><text x="38" y="234">bucket in another region.</text><text x="258" y="222">data replicated + the</text><text x="258" y="234">smallest possible core.</text>
      <text x="478" y="222">a full but under-scaled</text><text x="478" y="234">copy, serving nothing.</text><text x="698" y="222">every region takes live</text><text x="698" y="234">traffic all the time.</text>
    </g>

    <g fill="currentColor" font-size="8.5" opacity="0.6">
      <text x="38" y="262">RECOVERY SPEED</text><text x="258" y="262">RECOVERY SPEED</text><text x="478" y="262">RECOVERY SPEED</text><text x="698" y="262">RECOVERY SPEED</text>
      <text x="38" y="302">STEADY-STATE COST</text><text x="258" y="302">STEADY-STATE COST</text><text x="478" y="302">STEADY-STATE COST</text><text x="698" y="302">STEADY-STATE COST</text>
    </g>
    <g fill="none" stroke="currentColor" stroke-width="1" opacity="0.25">
      <rect x="38" y="268" width="168" height="12" rx="6"/><rect x="258" y="268" width="168" height="12" rx="6"/><rect x="478" y="268" width="168" height="12" rx="6"/><rect x="698" y="268" width="168" height="12" rx="6"/><rect x="38" y="308" width="168" height="12" rx="6"/><rect x="258" y="308" width="168" height="12" rx="6"/>
      <rect x="478" y="308" width="168" height="12" rx="6"/><rect x="698" y="308" width="168" height="12" rx="6"/>
    </g>
    <g fill="#0fa07f" fill-opacity="0.75">
      <rect x="38" y="268" width="21" height="12" rx="6"/><rect x="258" y="268" width="76" height="12" rx="6"/><rect x="478" y="268" width="126" height="12" rx="6"/><rect x="698" y="268" width="168" height="12" rx="6"/>
    </g>
    <g fill="#e0930f" fill-opacity="0.8">
      <rect x="38" y="308" width="14" height="12" rx="6"/><rect x="258" y="308" width="55" height="12" rx="6"/><rect x="478" y="308" width="118" height="12" rx="6"/><rect x="698" y="308" width="168" height="12" rx="6"/>
    </g>

    <text x="38" y="340" font-size="9" font-weight="700" fill="#d64545">measured: 2 TB @ 30.7 MB/s</text><text x="38" y="353" font-size="9" font-weight="700" fill="#d64545">= 18h 05m to restore</text>
    <text x="258" y="340" font-size="9" opacity="0.85">the copy is small,</text><text x="258" y="353" font-size="9" opacity="0.85">not absent</text><text x="478" y="340" font-size="9" opacity="0.85">tested by shifting</text><text x="478" y="353" font-size="9" opacity="0.85">real traffic</text>
    <text x="698" y="340" font-size="9" opacity="0.85">DR is your normal</text><text x="698" y="353" font-size="9" opacity="0.85">Tuesday</text>

    <rect x="24" y="378" width="856" height="60" rx="9" fill="#d64545" fill-opacity="0.11" stroke="#d64545" stroke-width="1.8"/>
    <g fill="currentColor">
      <text x="38" y="396" font-size="10" font-weight="700" fill="#d64545">THE HONEST FOOTNOTE</text><text x="38" y="412" font-size="9.5" opacity="0.95">Most real-world "DR" is availability-zone tolerance, not region tolerance. A multi-AZ database survives one</text>
      <text x="38" y="426" font-size="9.5" opacity="0.95">datacentre. It does not survive a region, a bad migration, or a deleted bucket. Say which one you bought.</text>
    </g>
    <text x="440" y="466" font-size="11" text-anchor="middle" fill="currentColor" opacity="0.9">Pick a tier per dataset, not per company. Your session store and your ledger do not deserve the same bill.</text>
  </g>
</svg>
```

Two notes on that ladder. First, **pick a tier per dataset, not per company.** Your ledger and your session cache do not deserve the same recovery guarantees or the same bill; the session cache can often be tier zero, because losing it entirely is a cold-start problem rather than a data-loss problem. Second, and this is the footnote in the diagram: most of what organisations call DR is **availability-zone tolerance**, not region tolerance. A multi-AZ (Availability Zone — an isolated datacentre within a cloud region) database failover is genuinely valuable and it protects against exactly one failure: the loss of one building. It does not protect you from a region-wide outage, a bad migration replicated instantly to every replica, or an attacker with your credentials. **Replication is not a backup, because replication faithfully replicates your mistake.**

### Game days

Everything above is a plan, and the first execution of any plan is the slowest and most error-prone. A **game day** is a scheduled rehearsal, on a normal Tuesday, in working hours, with the people who would actually be on call — restoring a real backup, failing over to a standby, executing the runbook exactly as written.

What game days reliably find, in rough order of frequency: the runbook references a hostname that changed; the person with the necessary permission is on holiday and there is no break-glass path; the restore command needs a flag nobody documented; the decryption key is in a secret manager inside the environment that is down; the restore takes four times longer than the stated RTO; and the runbook was written by someone who has since left and assumed context nobody else has.

Every one of those is cheap to find on a Tuesday and expensive to find at 04:12. Time the rehearsal, and **write the measured number into the DR document, replacing the aspiration that was there before.**

## Build It

[`code/rollback_and_recovery.py`](code/rollback_and_recovery.py) is six arguments, standard library only, seeded with `random.Random(7)`, about 11 seconds. Run it:

```bash
docker compose exec -T app python \
  phases/10-infrastructure-and-deployment/14-rollback-backups-and-disaster-recovery/code/rollback_and_recovery.py
```

**Section 1 is the centrepiece**, and it is an analysis most teams have never run. Every release declares the elements its code touches — namespaced as `db:<table>.<column>` and `topic:<name>.<version>` — plus what it added and what it dropped. Reachability is then a set question, not an opinion:

```python
def reachability(history: Tuple[Release, ...]) -> List[Dict[str, Any]]:
    current = history[-1]
    world = world_after(history, current.n)      # what exists TODAY
    rows: List[Dict[str, Any]] = []
    for target in history[:-1]:
        missing = [e for e in target.needs if e not in world]
        barriers = []
        for elem in sorted(missing):
            killer = killed_by(history, elem, current.n)   # who removed it
            if killer is not None:
                barriers.append((killer.n, elem))
        ...
```

`world_after` replays adds and drops to compute the present; a target release is reachable if nothing it needs is missing from it. That is the entire idea, and it is forty lines you could run in CI against your own migration history.

```console
== 1 · ROLLBACK REACHABILITY: WHICH RELEASES CAN YOU ACTUALLY GO BACK TO ==
  current release: v10 (8c7419) — CURRENT: artifact+config, banker's rounding
  a release is REACHABLE if every element its code touches still exists.

   rel  build   change                                        rollback?  why
   v1   a1c3e0  baseline                                      BLOCKED    v9 removed topic:orders.v1  +  v7 removed db:user.name
   v2   b7e042  artifact only: null-pointer fix in checkout   BLOCKED    v9 removed topic:orders.v1  +  v7 removed db:user.name
   v3   c2f9a8  expand: ADD COLUMN user.full_name (nullable)  BLOCKED    v9 removed topic:orders.v1  +  v7 removed db:user.name
   v4   d4a17b  backfill user.full_name (18.2M rows), dual-wr BLOCKED    v9 removed topic:orders.v1  +  v7 removed db:user.name
   v5   e8b6cc  config: FULLNAME_READ=on (reads switch over)  BLOCKED    v9 removed topic:orders.v1  +  v7 removed db:user.name
   v6   f1d803  artifact: stop writing user.name              BLOCKED    v9 removed topic:orders.v1
   v7   9a2c5e  contract: DROP COLUMN user.name               BLOCKED    v9 removed topic:orders.v1
   v8   3e5f11  expand: ADD user.email_verified NOT NULL DEFA BLOCKED    v9 removed topic:orders.v1
   v9   6b0d7a  orders payload v1->v2, consumers now v2-only  REACHABLE  revert 1 config key(s): PRICE_ROUNDING

  1 of 9 prior releases are reachable by rollback. The other 8 are not,
  and nothing in your deploy pipeline told you so.
  the two walls:
    v7  removed db:user.name           -> blocks 5 earlier release(s): v1,v2,v3,v4,v5
    v9  removed topic:orders.v1        -> blocks 8 earlier release(s): v1,v2,v3,v4,v5,v6,v7,v8
  irreversible side effects still in the window (rollback does NOT undo these):
    v9  12,412 'verify your email' messages sent to real inboxes
    v10 1,204 cards charged under the new rounding rule

  WHAT IF release 9's consumers had accepted v1 AND v2 (no drop)?
    reachable releases: 1 -> 4  (v6,v7,v8,v9)
    one line of consumer tolerance is worth 3 releases of rollback range.
```

Read the `why` column, because it is the artefact you actually want. It does not say "cannot roll back"; it names **the specific release and the specific element** that blocks each target. That turns an unanswerable incident question into a lookup. And note the shape of the damage: **v9's topic drop alone blocks eight releases**, which is every rollback target the team had. The counterfactual at the bottom is the cheapest fix in the lesson — had those consumers accepted both payload versions rather than going v2-only in one release, reachability goes from **1 to 4**. One line of tolerance in a consumer is worth **three releases** of rollback range.

**Section 2** serves 200 real requests under four different rollback attempts. The world is a small object with an artifact version, a config map and a set of columns, so each attempt is genuinely a different combination rather than a description of one:

```console
== 2 · A RELEASE HAS THREE ROLLBACKS: ARTIFACT, CONFIG, SCHEMA ==
  attempt                                 5xx   silent-wrong-price       charged     should be
  A. artifact only        (v42->v41)     200            0       $       0.00  $      0.00
  B. artifact + config    (v42->v41)     200            0       $       0.00  $      0.00
  C. artifact + schema    (v42->v41)       0          200       $ 2286655.00  $  22866.55
  D. artifact+config+schema, in order      0            0       $   22866.55  $  22866.55
```

Four attempts, one correct. **A** is the opening scene: rolling back the artifact alone fails **200 of 200 requests** on `column orders.total does not exist`. **B** is the result worth pausing on — reverting the config as well changes **nothing at all**, an identical 200 errors, because the schema stops every request at the first query and the config value is never reached. Two of three layers rolled back and the outage is **100% unchanged**, which is exactly the situation in which an incident channel concludes "rollback doesn't work" and starts doing something much more dangerous.

**C is the most dangerous row in this lesson.** Restore the column, forget the config, and errors go to **zero**. Every dashboard turns green. And **200 of 200 orders are charged 100× the correct amount — $2,286,655.00 against $22,866.55 owed, a $2,263,788.45 error that nothing alerts on**, because there is no error. A 5xx stops; a wrong number is written to a table and read as truth by every system downstream. **The green dashboard is the failure mode.**

**D** is the coordinated sequence, and its steps are ordered for a reason: add the column, backfill it, *then* revert the config, *then* revert the artifact. Step 2 is the one that costs real time — the build's 200-row backfill is instant, but the real table is 18.2M rows, **91,000× the work**, batched to respect lock and replication limits. The header on that step is the sentence to remember:

```console
  note step 1: 'rolling back' a dropped column is a FORWARD migration.
  It only worked because total was derivable from total_cents. Drop a column
  whose data exists nowhere else and no sequence gets you back at all.
```

**Section 3** builds a real backup chain — a full backup plus nightly incrementals, each part checksummed with SHA-256 — then flips a single bit in one part and restores:

```console
== 3 · AN INCREMENTAL CHAIN IS ONLY AS GOOD AS ITS WEAKEST LINK ==
  12 nights: 1 full (night 0) + 11 incrementals. 2520 orders at the end.
  night 5's incremental gets one flipped byte on the object store.

  restore, chain of 12, one full at night 0:
    applied 5 part(s), then night 5 failed checksum verification
    recovered state = end of night 4
    orders MISSING entirely : 840
    orders STALE (wrong amt): 215
    data lost               : 168h 00m 00s of writes (840 of 2520 orders unrecoverable)

  same corruption, same night, one change — a weekly full at night 7:
    restore path = full(night 7) + 4 incrementals, checksum failures: none
    orders missing 0, stale 0 — the bad link is no longer on the path.
```

**One flipped byte costs 840 of 2,520 orders and 168 hours of writes.** Note the second category too: **215 orders are *stale* rather than missing** — present in the restored data, with amounts from an earlier night. Missing rows announce themselves. Stale rows do not, and a restore that reports "success" hands them to you as facts.

The mitigation is a scheduling change, not a technology change: a weekly full puts the restore on a path of `full(night 7) + 4 incrementals` that never touches the damaged part — **0 missing, 0 stale**. And the probability table turns chain length into the reliability number it always was: at a 0.20% per-part failure rate, 4 links restore **99.20%** of the time and 90 links — nightly incrementals with a quarterly full, a policy nobody would flag in review — restore **83.51%** of the time.

**Section 4** is point-in-time recovery against a write-ahead log, and it is Phase 3's WAL used for the purpose that pays for itself:

```console
== 4 · POINT-IN-TIME RECOVERY: THE WAL IS THE RPO ==
  base backup taken at 02:00:00.000.  6h 58m 10s later, at 08:58:10.083, someone runs
    DELETE FROM orders WHERE status = 'pending';     -- no tenant filter
  8711 rows before, 3931 after. 4780 orders gone in one statement.

  WAL: 4985 records between the base backup and the statement,
       mean inter-record gap 5.03 s, longest gap 50.09 s

  recovery target: 08:58:09.083  (1.000 s before the statement)
  last replayable WAL record at 08:58:08.067 -> replayed 4985 records in 1 ms

    restored rows                        : 8711
    rows in the base backup alone        : 6000
    rows the disaster left behind        : 3931

    ACHIEVED RPO vs the target instant   : 1.016 s   (WAL record granularity)
    data-loss window vs the statement    : 2.016 s
    RPO from the backup interval ALONE   : 6h 58m 10s  (25090 s)
    PITR improvement                     : 12443x
```

The three row counts tell the whole story. The disaster left **3,931** rows. The base backup alone would have given you **6,000** — better, but it silently discards the **2,711 orders written after 02:00**, which is the kind of "recovery" that generates a second incident a week later when customers ask where their orders went. WAL replay gives back **8,711**: every row that existed the instant before the statement.

The **achieved RPO of 1.016 s** against a 1.000 s target is the detail worth understanding. You cannot stop between records; you stop *at* one. With a mean inter-record gap of 5.03 s the granularity of "just before" is bounded by how often anything was written, which is why the same recovery on a quiet database at 04:00 is less precise than on a busy one at noon. Against the **6h 58m 10s** you would have lost from the backup interval alone, that is a **12,443× improvement** — obtained from log shipping most teams are already running for replication and simply never point at recovery.

**Section 5 measures RTO instead of asserting it.** The restore does the three things `pg_restore` does — read, parse, load, build an index — at four dataset sizes, five repeats each, reporting the median:

```console
== 5 · RTO IS A MEASUREMENT, NOT A TARGET ==
     rows        bytes    dump s   restore s    MB/s   rows/s
       5000       659483     0.02        0.01    51.9   393656
      20000      2651232     0.10        0.05    48.6   366473
      80000     10638004     0.39        0.27    39.9   299801
     320000     42805178     1.52        1.39    30.7   229582

  throughput is NOT a constant: 51.9 MB/s at 0.7 MB, 30.7 MB/s at 42.8 MB.
  it DEGRADES as the dataset grows — the small dumps fit in page cache and
  your production restore will not. Across the whole range bytes x64.9 cost
  time x109.7 (super-linear, all of it cache); between the two LARGEST samples
  bytes x4.0 cost time x5.2, close enough to linear to extrapolate from.
  So use the largest sample's 30.7 MB/s and treat it as OPTIMISTIC, not as
  a best estimate: benchmarking on the SMALLEST dump would have over-read
  your real throughput by 1.7x.
  the same restore, 5 times, ranged 29.1 - 31.5 MB/s on an idle sandbox.
  your RTO is a distribution, not a scalar. Plan against the slow end.

  EXTRAPOLATION:    80 GB at 30.7 MB/s -> 43m 25s      (slow end 45m 52s     ) vs a 4h RTO: MEETS
  EXTRAPOLATION:   500 GB at 30.7 MB/s -> 4h 31m 21s   (slow end 4h 46m 43s  ) vs a 4h RTO: MISSES by 1.1x
  EXTRAPOLATION:  2000 GB at 30.7 MB/s -> 18h 05m 25s  (slow end 19h 06m 52s ) vs a 4h RTO: MISSES by 4.5x
```

Three findings, and the middle one is the methodological trap. First, **the extrapolation**: at a measured 30.7 MB/s a 2 TB database takes **18h 05m** to restore, missing a stated four-hour RTO by **4.5×** — and at the slow end of the measured range, **19h 07m**. A team can hold that four-hour number in a document for years without ever discovering it is off by most of a day.

Second, **throughput is not constant and small benchmarks lie in the optimistic direction.** The 0.7 MB dump restores at 51.9 MB/s and the 42.8 MB dump at 30.7 MB/s, purely because the small one fits in page cache. Benchmark your restore on a development-sized dataset and you will over-read your real throughput by 1.7×. Across the whole range, 64.9× the bytes cost 109.7× the time — super-linear, all of it cache effects — while between the two largest samples 4.0× the bytes cost 5.2× the time, which is close enough to linear that extrapolating from the *largest* sample is defensible.

Third, **the same restore five times ranged 29.1–31.5 MB/s** on an idle machine with nothing competing for I/O. Your RTO is a distribution. During a real disaster you are at the slow end, because so is everyone else.

**Section 6** is the backup that succeeds forever. The verification function is the entire fix, and it is short enough to read in full:

```python
def verify_restore(job: Dict[str, Any], live: Dict[str, int]) -> List[str]:
    """Restore into a scratch namespace and assert on schema and row counts."""
    faults: List[str] = []
    restored = job["tables"]
    for name, expected in sorted(live.items()):
        if name not in restored:
            faults.append("MISSING TABLE   %-10s expected %d rows, restored none"
                          % (name, expected))
            continue
        got = restored[name]
        drift = abs(got - expected) / max(expected, 1)
        if drift > 0.25:
            faults.append("ROW-COUNT DRIFT %-10s expected ~%d, restored %d (%.0f%%)"
                          % (name, expected, got, drift * 100))
    return faults
```

It diffs the restored table set against the **live catalogue** — not against a list of expected tables, which would have the same staleness bug as the backup job's include-list. That distinction is the whole design.

```console
== 6 · A BACKUP YOU HAVE NOT RESTORED IS NOT A BACKUP ==
  what the monitoring saw — the last 5 of 31 nights:
    night   exit   tables   bytes      verdict
       27      0        4   17410572   OK (green)
       28      0        4   17481908   OK (green)
       29      0        4   17526604   OK (green)
       30      0        4   17593648   OK (green)
       31      0        4   17676824   OK (green)
  31 consecutive green nights. Backup size grows ~0.4%/night, so a
  size-anomaly alert would not have fired either. Exit code 0 every time.

  now the restore, at 04:12 during the incident:
    audit_log   -> 65225 rows restored
    orders      -> 13494 rows restored
    payments    -> ABSENT. 9120 rows unrecoverable.
    sessions    -> 35320 rows restored
    users       -> 5399 rows restored

  the same job with automated restore verification bolted on:
    restore into scratch namespace ... done
    assert table set matches live catalog ... 1 fault(s)
      MISSING TABLE   payments   expected 9120 rows, restored none
    VERIFY EXIT CODE: 1  ->  page the owning team
  it fires on the FIRST run, 31 nights before anyone needed the backup.
```

Every defence a normal team has was in place and every one of them passed. **The exit code was 0.** The table count was stable at 4. The **size grew 0.4% a night**, so an anomaly detector watching backup size had nothing to report — the missing table was missing from the baseline too. **31 consecutive green nights**, and the first time anyone read the file was during the incident, at which point **9,120 payment rows** were gone and every restored order referenced a payment that no longer existed.

The verification catches it **on the first run**. That is the whole return on investment: four lines of assertion, one scratch namespace, and a fault found a month before it mattered.

## Use It

### Postgres: logical dumps, physical backups, and continuous archiving

Two families, and the difference decides your RTO more than any other choice (PostgreSQL 16 manual, ch. 25–26).

```bash
# LOGICAL — portable, selective, slow to restore. A stream of SQL/objects.
pg_dump --format=custom --jobs=4 --file=orders.dump orders_db
pg_restore --dbname=orders_db --jobs=8 orders.dump      # parallel restore

# PHYSICAL — a byte-level copy of the data directory. Fast, whole-cluster only.
pg_basebackup --pgdata=/backup/base --wal-method=stream --checkpoint=fast \
              --progress --compress=zstd
```

**Logical** dumps are portable across major versions and architectures, and let you restore a single table — genuinely useful for the "someone deleted one table" incident. But a logical restore *re-executes* the work: parse, insert, validate constraints, **rebuild every index from scratch**. That is why a large logical dump is a **restore-time problem, not a backup-time problem**, and why section 5's numbers matter. `pg_dump --jobs` and `pg_restore --jobs` parallelise it, but index builds and constraint validation still dominate.

**Physical** backups copy the files, so restore is closer to a file copy, and they are the only practical basis for PITR. They are tied to the major version and platform, and they are all-or-nothing.

The rule of thumb: **logical for portability and partial restores; physical for RTO.** Above a few hundred gigabytes, if your RTO is in hours, physical is not a preference.

**Continuous archiving and PITR** is section 4 in production:

```bash
# postgresql.conf — ship every completed WAL segment off the machine
wal_level = replica
archive_mode = on
archive_command = 'test ! -f /archive/%f && cp %p /archive/%f'   # or aws s3 cp
archive_timeout = 60      # force a segment at least once a minute -> RPO ~60 s
```

That last line *is* your RPO, and it is the single most important setting in this section: with `archive_timeout = 60`, a low-traffic database still ships a segment every minute, so the worst case is about sixty seconds of loss. Restoring to a chosen instant:

```bash
# 1. restore the base backup into an empty data directory
# 2. tell Postgres where the WAL lives and when to stop
cat >> postgresql.conf <<'EOF'
restore_command = 'cp /archive/%f %p'
recovery_target_time = '2026-07-18 08:58:09.083+00'
recovery_target_action = 'pause'      # stop and let a human verify BEFORE promoting
EOF
touch $PGDATA/recovery.signal && pg_ctl start
```

`recovery_target_action = 'pause'` is the setting people skip and regret. It stops recovery at the target and waits, so you can connect, run a `SELECT COUNT(*)`, confirm you picked the right instant, and only then `pg_wal_replay_resume()` and promote. Without it, an off-by-one on the timestamp means redoing the entire restore. There are other targets besides time — `recovery_target_lsn`, `recovery_target_xid`, `recovery_target_name` — and an LSN or transaction ID is more precise than a wall-clock time when you can identify the offending transaction.

### Cloud snapshots, cross-region copies, and immutability

Managed snapshots are physical backups with the operational work removed:

```bash
# A snapshot is regional. It does not survive the region until you copy it.
aws rds create-db-snapshot --db-instance-identifier prod --db-snapshot-identifier prod-2026-07-18
aws rds copy-db-snapshot --source-db-snapshot-identifier prod-2026-07-18 \
    --target-db-snapshot-identifier prod-2026-07-18-dr --source-region eu-west-1 --region us-east-1
```

Two traps. **A snapshot in the same region as the thing it protects is not off-site** — it fails the "1" in 3-2-1, and it is the default. And **automated snapshots are usually deleted with the instance**; deleting a database can delete its own backups, which is a very fast way to turn a mistake into a disaster. Take manual or copied snapshots for anything you must keep.

Immutability is enforced by the storage layer, below your permission model:

```bash
# Object lock in COMPLIANCE mode: nobody deletes this before the date. Not you,
# not the root account, not an attacker holding your production credentials.
aws s3api put-object-retention --bucket backups-prod --key base/2026-07-18.tar.zst \
    --retention '{"Mode":"COMPLIANCE","RetainUntilDate":"2026-08-18T00:00:00Z"}'
```

Pair that with a **separate backup account**: production holds a role that can `PutObject` and nothing else; deletion requires a break-glass identity in an account whose credentials never appear on a production host. The test to apply is one sentence — *if an attacker had every credential my production environment holds, could they destroy my backups?* If yes, you have copies, not backups.

### Scheduled restore verification

Section 6 as a cron job. This is the highest-value thing in the lesson and it fits on a page:

```bash
#!/usr/bin/env bash
set -euo pipefail                       # a silent failure here defeats the purpose

SNAP=$(latest_snapshot)
restore_into_scratch "$SNAP" verify_db  # a throwaway instance/namespace, then dropped

# 1. schema: every live table must exist in the restore
diff <(list_tables verify_db) <(list_tables prod_readonly) || fail "table set differs"

# 2. volume: row counts within tolerance of live
for t in $(list_tables prod_readonly); do
  compare_counts "$t" verify_db prod_readonly 0.25 || fail "row count drift in $t"
done

# 3. semantics: the app's own health query must succeed against the restore
psql verify_db -f smoke_queries.sql || fail "restored data fails smoke queries"

# 4. RTO: record the duration EVERY time; alert on the trend, not just failure
emit_metric restore_verify_seconds "$SECONDS"
```

Four assertions and one metric. Step 4 is the one that keeps the DR document honest: it turns your RTO into a time series, so the day the dataset grows past the maintenance window you find out from a graph rather than from an incident. Alert on the *verification job* failing exactly as loudly as you would alert on the database being down, because it is the same thing with a delay.

### Rolling back the artifact layer — and what it does not touch

Every orchestrator makes the artifact rollback trivial, which is precisely why the other two layers get forgotten:

```bash
kubectl rollout undo deployment/api                  # previous ReplicaSet
kubectl rollout undo deployment/api --to-revision=3  # a specific one
kubectl rollout history deployment/api               # what you can reach

argocd app rollback api 42                           # a previous synced revision
helm rollback api 7                                  # previous chart + values
```

`kubectl rollout undo` re-points a Deployment at an earlier ReplicaSet, and the rollout is governed by the same readiness gates and `maxUnavailable` settings as a normal deploy (Lesson 11) — so **a rollback into a fleet whose readiness probes fail can stall exactly like a bad deploy can**, and Lesson 7's control loop will sit there mid-rollout. Note also that `revisionHistoryLimit` (default 10) bounds how far back `--to-revision` can go: your reachable set has an orchestrator-imposed ceiling as well as a schema-imposed one.

And the reminder that this entire lesson exists to deliver:

> **None of these commands touch your database.** `kubectl rollout undo` reverts one of the three layers. Helm reverts the artifact and its config. Argo reverts what is in Git. **The schema is not in any of them**, and the schema is the layer that turns a 2% error rate into a 100% one.

### Game days and the decision rule

Schedule the rehearsal like any other recurring work, and rotate who runs it so the knowledge is not held by one person:

- **Monthly:** an automated restore verification review — read the metrics, look at the RTO trend.
- **Quarterly:** a real timed restore of the production dataset into an isolated environment, run by whoever is on call, following only the written runbook. Anything they had to ask about is a runbook defect; fix it that day.
- **Annually:** a full region failover, or an honest written statement that you cannot do one and have accepted that risk at a named level.

And the rule itself, small enough to print and put in the runbook:

```text
INCIDENT: a release is bad. Roll back or roll forward?

1. Is the previous release REACHABLE?   (query it; do not guess)
     no  -> roll forward. The runbook must already say what forward means.
     yes -> continue.
2. Does the rollback need all three layers?  artifact / config / schema
     Any schema step is a FORWARD migration and is O(rows). Time it first.
3. Are there irreversible side effects already emitted?
     Emails, charges, webhooks, consumed messages: list them, and assign
     someone to the cleanup NOW. Rollback does not undo them.
4. Roll back, in order: schema (forward-fix) -> config -> artifact.
     Verify after EACH step. Never revert one layer and declare victory.
5. If the numbers look right but you did not verify data correctness,
     you are in case C: green dashboards, wrong values. Check the data.
```

Production rules that survive contact with an incident:

- **Know your reachable rollback set before you deploy, not during the incident.** Compute it in CI from your migration history and your build's declared dependencies, and fail the build when a release reduces the reachable set to zero without a written decision.
- **Version artifact, config and schema together, and roll back all three.** A "rollback" that reverts one layer is why the opening scene happens; a rollback that reverts two can leave the outage 100% unchanged.
- **Never let a release contain an irreversible change without a written decision.** Contracting a schema, dropping a payload version, sending a bulk email — each is fine, and each needs someone to have said "this release cannot be rolled back" out loud, in the pull request.
- **Restore-test on a schedule, automatically, and alert on failure.** Assert the table set against the live catalogue, assert row counts, run smoke queries, and record the duration every time.
- **Measure RTO with a real timed restore of production-sized data.** Re-time it whenever the dataset grows by half. Plan against the slow end of the measured range, not the median.
- **Keep backups immutable and credential-isolated.** Object lock plus a separate account. If production credentials can delete your backups, you have copies, not backups.
- **Shorten your incremental chains.** Chain length is a reliability number: 90 links at a 0.20% per-part failure rate is an 83.51% chance of a complete restore.

## Think about it

1. Section 1 shows that computing the reachable rollback set is about forty lines over a declared list of "what this build touches". What would you have to add to your own repository to make that list accurate and trustworthy — and what would you do when a release legitimately must reduce the reachable set to zero?
2. Attempt C produced zero errors, green dashboards, and $2,263,788.45 of wrong charges. Design the check that catches C within one minute. What does it have to compare, where does it have to run, and why can it not be an error-rate alert?
3. The achieved RPO was 1.016 s because the WAL's mean inter-record gap was 5.03 s. Describe a system where that granularity is much worse, and one where it is irrelevant. What would you change about the archiving configuration in each case, and what does each change cost?
4. Your restore verification has been green for a year. Name three ways it could be green while your real recovery is broken, and say what additional assertion catches each one.
5. You are asked to choose a DR tier for three datasets: the ledger, the product catalogue, and the session store. Pick a tier for each, state the RTO and RPO you are committing to, and then say what you would have to *measure* to know whether the commitment is real rather than aspirational.

## Key takeaways

- **A deploy is reversible only if every change in it is.** Across nine releases of history, **1 was reachable and 8 were blocked** — and a single dropped message-payload version at release 9 accounted for **8 of those 8** on its own. Had those consumers accepted both versions, reachability would have been **4 instead of 1**. Compute the reachable set in CI; nothing in a deployment pipeline computes it for you.
- **One rollback is really three, and reverting two of them can change nothing.** Rolling back only the artifact failed **200 of 200 requests**; rolling back artifact *and* config left the outage **100% unchanged**, because the schema stopped every request before the config was ever read. Only the coordinated schema → config → artifact sequence was correct — and its schema step is a **forward** migration costing `O(rows)`, **91,000×** the build's sample on a real 18.2M-row table.
- **The dangerous rollback is the one that turns the dashboards green.** Restoring the column but not the config produced **0 errors and 200 of 200 orders charged 100× the correct amount — $2,286,655.00 against $22,866.55 owed.** A 5xx stops when you fix it; a wrong number persists and propagates.
- **Your RPO is your WAL shipping interval, not your backup schedule.** Base-backup-only recovery lost **6h 58m 10s** of writes — **2,711 orders**; replaying the write-ahead log to one second before the destructive statement restored **8,711 of 8,711 rows** with a **2.016 s** loss window, a **12,443×** improvement from log shipping most teams already run. And one flipped byte in one incremental cost **840 of 2,520 orders** plus 215 stale ones; a weekly full made the same corruption cost **zero**.
- **An RTO you have not timed is a wish.** Measured restore throughput was **30.7 MB/s** — meaning **18h 05m for 2 TB against a stated 4-hour RTO, a 4.5× miss**, and **19h 07m** at the slow end of the measured range. Throughput also *degrades* with size (**51.9 MB/s at 0.7 MB, 30.7 MB/s at 42.8 MB**), so benchmarking on a small dataset over-reads your real throughput by about **1.7×**.
- **A backup you have not restored is not a backup.** A job returned exit code 0 for **31 consecutive nights**, with backup size growing a plausible **0.4% a night**, while silently omitting a table created 31 nights earlier — discovered during an incident, costing **9,120 unrecoverable payment rows**. Automated restore verification — restore to scratch, diff the table set against the live catalogue, compare row counts — caught it **on the first run**. Keep those backups immutable and in a separate account, because an attacker with production credentials deletes them first.

Next: [Capstone: Ship a Service End to End](../15-capstone-ship-a-service/) — every primitive in this phase, from image build to rollout to rollback plan, assembled into one service you ship and then deliberately break.
