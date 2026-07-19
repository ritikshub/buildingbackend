---
name: runbook-rollback-and-recovery
description: The three questions to answer before you deploy and the exact sequence to follow when a release goes bad — reachability, the three-layer rollback order, restore and point-in-time recovery, and the verification schedule that keeps all of it true.
phase: 10
lesson: 14
---

# Rollback & recovery runbook

Two halves. **Part A runs before you deploy**, when you are calm and have time. **Part B runs at
03:14**, when you do not. Part B only works if Part A was done — that is the whole design.
Every item exists because skipping it produced a real outage.

---

## PART A — before the deploy

### A1 · Compute the reachable rollback set

- [ ] Each build declares what it **touches**: tables and columns it reads or writes, message
      topics and payload versions it produces or consumes, external contracts it depends on.
- [ ] CI replays the migration and contract history to compute **what exists now**, then marks
      each prior release reachable or blocked, naming the **specific release and element** that
      blocks it. Forty lines of set arithmetic; no vendor required.
- [ ] The output is published with the release: *"reachable targets: v9 only (revert
      PRICE_ROUNDING). v1–v8 blocked by v9 dropping topic:orders.v1."*
- [ ] The build **fails** when a release reduces the reachable set to zero without a written,
      approved decision attached.
- [ ] `revisionHistoryLimit` (or your platform's equivalent) is large enough that the
      orchestrator can still reach the releases your analysis says are reachable.

> Measured: across 9 releases of a realistic history, **1 was reachable and 8 were blocked**.
> A single dropped message-payload version accounted for **8 of those 8**.

### A2 · Name every irreversible change in the release

Go through this list at review. If any box is ticked, **the release is not reversible** and
someone must say so in writing before it ships.

- [ ] Contracted schema — dropped column or table, narrowed type, tightened constraint.
- [ ] Dropped support for an older message payload version, or a consumer that advanced past
      messages it can no longer read.
- [ ] Emails, SMS or push notifications sent.
- [ ] Cards charged, payouts issued, invoices finalised. *Refundable is not reversible.*
- [ ] A lossy data migration — normalising, truncating, re-encoding, collapsing fields — where
      dual-write has already stopped.
- [ ] Any external call with no undo: partner webhooks, third-party writes, propagated DNS,
      published CDN artifacts.

**Cheapest mitigation, by a wide margin:** make consumers accept the **old and new** payload
versions for at least one release. Measured: that single change took reachable releases from
**1 to 4**.

### A3 · Version all three layers together

- [ ] The **artifact** is an immutable digest, not a mutable tag.
- [ ] The **config** is versioned and the effective value is introspectable at runtime.
- [ ] The **schema** version is recorded, and every migration has a written, tested forward
      recovery path — because there is no such thing as rolling a schema back.
- [ ] One release id maps to a specific (artifact, config, schema) triple, and the rollback
      procedure names all three.

### A4 · Know your numbers before you need them

- [ ] **RPO** is written down *and* matches your actual capture frequency. A nightly backup is
      an RPO of up to 24 hours, whatever the document says.
- [ ] **RTO** comes from a **real timed restore of production-sized data**, with the date it was
      measured. Re-time it whenever the dataset grows by half.
- [ ] Plan against the **slow end** of the measured range, not the median. The same restore
      repeated five times ranged **22.1–30.5 MB/s** on an idle machine.
- [ ] Do not extrapolate from a small dataset: measured throughput was **46.5 MB/s at 0.7 MB and
      28.4 MB/s at 42.8 MB**, because small dumps fit in page cache and production will not.
- [ ] A DR tier is chosen **per dataset**, not per company, and each tier's RTO/RPO claim is
      backed by a rehearsal.
- [ ] It is written down whether you bought **availability-zone tolerance** or **region
      tolerance**. They are different products at different prices.

---

## PART B — the incident

### B1 · Decide: roll back or roll forward

```text
1. Is the previous release REACHABLE?   (look it up; do not guess)
     no  -> roll forward. The runbook must already say what forward means.
     yes -> continue.
2. Which of the three layers does the rollback need?  artifact / config / schema
     Any schema step is a FORWARD migration and is O(rows). Time it before you start.
3. What irreversible side effects were already emitted?
     Emails, charges, webhooks, consumed messages. List them now and assign the
     cleanup to a named person. The rollback does not undo any of them.
4. Roll back in order: schema (forward-fix) -> config -> artifact.
     Verify after EACH step.
5. Errors at zero is not "done". Check the DATA.
```

- [ ] Roll forward only when the previous state is unreachable, **or** the fix is trivial, well
      understood and already reviewed. Writing new code mid-incident is the last resort, not
      the first instinct.

### B2 · Execute the rollback in order

- [ ] **Schema first.** Re-create what the old code needs. This is a new forward migration and
      it only works if the data is still derivable from something that still exists.
- [ ] **Backfill**, batched to respect lock and replication limits. This step is `O(rows)` and
      cannot be skipped — a 200-row sample is instant; an 18.2M-row table is **91,000×** that
      work.
- [ ] **Config next**, and only after the backfill completes.
- [ ] **Artifact last.**
- [ ] **Verify after each step**, and verify *data*, not just status codes.

> The trap, measured: restoring the schema but not the config gave **0 errors and 200 of 200
> orders charged 100× the correct amount** — $2,286,655.00 against $22,866.55 owed. Green
> dashboards, no alerts. A 5xx stops; a wrong number persists.

### B3 · Recover data — point in time, not last night

- [ ] Identify the **exact instant** before the damage (statement timestamp, LSN, or transaction
      id). An LSN or xid is more precise than wall-clock time.
- [ ] Restore the **base backup**, then replay the write-ahead log to a target *just before* that
      instant. Do not restore the base backup and stop — that silently discards everything
      written since it was taken.
- [ ] Set recovery to **pause at the target** rather than promoting automatically, so a human can
      run counts and confirm the instant before committing to it.
- [ ] Record the **achieved RPO**: the gap between the last replayed record and your target. It
      is bounded by write frequency, so it is *worst on a quiet database* — which is when most
      disasters are noticed.
- [ ] Restore into an **isolated** environment first when the blast radius is unclear. Recovering
      onto the live cluster removes your ability to try again.

> Measured: base-backup-only recovery lost **6h 58m 10s** of writes — 2,711 orders. WAL replay to
> one second before the statement restored **8,711 of 8,711 rows** with a **2.016 s** loss
> window: a **12,443×** improvement, from log shipping already running for replication.

### B4 · During a restore, watch for these

- [ ] The chain: a single unreadable part costs you **everything after it**, not just itself.
      Verify part checksums before you begin, and know where your most recent **full** is.
- [ ] Stale rows are worse than missing ones. Missing rows announce themselves; stale rows are
      handed to you as facts. Measured: one flipped byte produced 840 missing **and 215 stale**.
- [ ] Referential damage: a partially restored dataset can leave orders pointing at payments
      that no longer exist. Check cross-table integrity before declaring recovery complete.

---

## PART C — the recurring work that keeps A and B true

### C1 · Automated restore verification (the highest-value item here)

Scheduled, automated, and alerting on failure as loudly as a production outage.

- [ ] **Restore** the latest backup into a scratch namespace or throwaway instance.
- [ ] **Diff the restored table set against the LIVE catalogue** — never against a hand-maintained
      list of expected tables, which rots exactly the same way the backup's include-list does.
- [ ] **Compare row counts** against live, with a tolerance, per table.
- [ ] **Run the application's own smoke queries** against the restored data.
- [ ] **Record the duration every run** and alert on the *trend*, so a dataset outgrowing the
      maintenance window shows up on a graph rather than in an incident.
- [ ] Exit non-zero and page the owning team on any fault.
- [ ] Use the **same key retrieval path and the same identity** an engineer would use during a
      real incident — otherwise you have verified a path nobody can walk.
- [ ] Restore into the **engine version you actually run**, so a format that the current engine
      can no longer read is caught here.

> Measured: a job returned exit code 0 for **31 consecutive nights**, size growing a plausible
> **0.4% a night**, while silently omitting a table added 31 nights earlier — **9,120
> unrecoverable rows**. Verification caught it on the **first run**.

### C2 · Backup integrity and retention

- [ ] **3-2-1**: three copies, two media or storage classes, one off-site. A snapshot in the same
      region as the thing it protects fails the "1", and it is the default.
- [ ] **Shorten the chain.** Chain length is a reliability number: at a 0.20% per-part failure
      rate, 4 links restore **99.20%** of the time and 90 links restore **83.51%** of the time.
      Add fulls until that number is one you would accept.
- [ ] **Immutable storage** (object lock / write-once retention) so deletion is refused *below*
      your permission model.
- [ ] **A separate backup account.** Production can write backups; only a break-glass identity
      elsewhere can delete them.
- [ ] Encryption keys are recoverable **from outside** the environment being restored, and are
      not stored only in the secret manager that is down.
- [ ] Retention is set by how long a slow corruption can go unnoticed — usually far longer than a
      week — and reconciled against any legal obligation to destroy data on schedule.
- [ ] Automated snapshots are not the only copy, because deleting a database often deletes them.

> The one-sentence test: **if an attacker held every credential my production environment holds,
> could they destroy my backups?** If yes, you have copies, not backups. Replication is not a
> backup either — it faithfully replicates your mistake.

### C3 · Game days

- [ ] **Monthly:** review restore-verification metrics and the RTO trend line.
- [ ] **Quarterly:** a real timed restore of production-sized data into an isolated environment,
      run by whoever is on call, following **only the written runbook**. Anything they had to ask
      about is a runbook defect — fix it that day.
- [ ] **Annually:** a full region failover, or a written, signed statement that you cannot do one
      and have accepted that risk.
- [ ] Rotate who runs it. A procedure only one person can execute is a single point of failure
      with a pulse.
- [ ] After every rehearsal, **replace the aspirational RTO in the DR document with the measured
      one**, and date it.

What game days reliably find: a hostname that changed; the only person with the permission is on
holiday; a required flag nobody documented; a decryption key inside the environment that is down;
a restore four times longer than the stated RTO; and a runbook whose author has left.

---

## The three sentences to remember

1. **A deploy is reversible only if every change in it is** — one irreversible change makes the
   whole release irreversible, and nobody notices until they try.
2. **Your RPO is your WAL shipping interval, not your backup schedule.**
3. **A backup you have not restored is not a backup, and an RTO you have not timed is a wish.**
