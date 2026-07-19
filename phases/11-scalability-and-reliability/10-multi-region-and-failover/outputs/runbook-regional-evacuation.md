---
name: runbook-regional-evacuation
description: Move 100% of traffic out of one region and keep serving.
phase: 11
lesson: 10
---

# Runbook: Regional Evacuation

Move 100% of traffic out of one region and keep serving. Use it for a real region loss **and**
for the scheduled drill — they must be the same document, or the drill proves nothing.

**Scope:** loss or degradation of one whole region. Not an AZ failure (multi-AZ handles that,
do nothing), not a bad deploy (roll back), not a dependency outage (shed load — see Phase 8
Lesson 11).

**Decision authority:** a named on-call incident commander. **Region failover is not
automated.** A false positive in an automatic region failover *causes* an outage — it promotes
a standby while the primary is still taking writes, producing split brain in the one system you
were most careful about.

---

## 0. Confirm it is a region event — 3 minutes

- [ ] **Failures span multiple AZs in one region and no other region.** If one AZ, stop.
- [ ] **External probes from ≥3 other regions fail.** Your own in-region monitoring may be
      part of the failure; never decide from inside the thing that is broken.
- [ ] **Provider status page / health API** confirms, or explicitly does not.
- [ ] **Classify: hard loss or partial?** Hard loss (network gone, instances gone) withdraws
      BGP automatically — anycast traffic has already moved. Partial (region up, app broken)
      still costs the full health-check detection window.

```bash
# from OUTSIDE the affected region
for R in us-west-2 eu-west-1 ap-southeast-1; do
  curl -sS -o /dev/null -w "$R %{http_code} %{time_total}s\n" \
    --max-time 5 https://probe-$R.example.com/healthz
done
aws route53 get-health-check-status --health-check-id "$HC_ID"
aws rds describe-db-clusters --db-cluster-identifier "$CLUSTER" \
  --query 'DBClusters[0].GlobalWriteForwardingStatus'
```

**State in the incident channel, before acting:** which region, hard or partial, current
replication lag, and the RPO you are about to accept.

---

## 1. Read the RPO before you promote — 2 minutes

This is the number you cannot recover later. Get it now, while the replica still knows it.

| Signal | Command | Threshold |
|---|---|---|
| Replica lag (Postgres) | `SELECT now() - pg_last_xact_replay_timestamp();` | > 10 s → escalate |
| Replica lag (Aurora Global) | CloudWatch `AuroraGlobalDBReplicationLag` | > 1 s is abnormal |
| Replica lag (MySQL) | `SHOW REPLICA STATUS\G` → `Seconds_Behind_Source` | > 10 s → escalate |
| Unreplicated WAL bytes | `pg_current_wal_lsn() - sent_lsn` on the primary | any value = data at risk |

- [ ] **Record the lag value in the incident channel.** Measured reference: async cross-region
      lag was p50 **84 ms** but p99 **7.30 s** and max **9.10 s** during a bulk-write window.
      **Quote the tail, not the median** — a region does not fail at the p50.
- [ ] **Translate it into business terms before promoting:** "we are about to lose up to N
      seconds of writes, which is approximately X orders / Y profile updates."
- [ ] If a bulk job or migration is running, **the lag is much larger than normal.** Check
      before you promote, not after.

---

## 2. Drain traffic — the order matters

Drain **before** promoting. Traffic still arriving at a half-promoted database is how you get
writes on both sides.

- [ ] **1. Anycast / edge origin change first** (seconds). Repoint the edge's origin pool away
      from the dead region. This is the fast path and it moves the bulk of traffic.
- [ ] **2. Then DNS**, knowing it is slow. Measured tail on a 60 s TTL record: **72.17%** still
      hitting the dead region at 1 min, **17.01%** at 5 min, **11.01%** at 15 min, **5.24%** at
      1 hour, and it **never reached 1% within 24 hours.**
- [ ] **3. Stop cross-region job schedulers** that target the dead region (cron, workers,
      pipelines) so they do not retry into a hole.
- [ ] **4. Quiesce writers in the dead region if it is reachable** — a partial failure means
      the region can still accept writes. Fence it explicitly.

```bash
# edge origin switch (the fast path)
curl -X PATCH "https://api.cdn.example.com/v1/origin-pools/$POOL" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"origins":[{"name":"eu-west-1","enabled":true},{"name":"us-east-1","enabled":false}]}'

# DNS failover (the slow path) — expect the tail above
aws route53 change-resource-record-sets --hosted-zone-id "$ZONE" \
  --change-batch file://failover-to-euw1.json
```

**Do not lower the TTL during the incident.** The new TTL only applies to resolvers that
re-query, which are exactly the ones already behaving. Lower TTLs *in advance*, permanently.

---

## 3. Verify capacity BEFORE you send it double traffic

The surviving region is about to receive 100% of demand. If it cannot take it, you have
converted a 50% outage into a 100% brownout.

- [ ] **Current headroom = (capacity − current load) / current load.** You need ≥ 100%.
- [ ] **Check the real limits, not the autoscaler's max:** instance quotas, per-AZ capacity,
      connection-pool sizes, database `max_connections`, third-party API rate limits.
- [ ] **Pre-scale now**, before redirection completes. Autoscaling from cold is too slow:
      measured, new capacity did not begin landing until **t = 245 s**.
- [ ] **If capacity is short, shed by tier immediately** (Phase 8 Lesson 11). Tier 3 to zero,
      Tier 2 degraded. A 44% error rate for six minutes is worse than dropping analytics.

Measured, and the reason this section exists — two identical evacuations, capacity the only
difference:

| survivor | peak err | err after redirect | failed requests | full recovery |
|---|---|---|---|---|
| no headroom (90% utilised) | 50.0% | 44.4% | 2,941,245 | 407 s |
| headroom (50% utilised) | 50.0% | 0.0% | 455,000 | 55 s |

**The identical 50.0% peak is the detection window; headroom does not shorten detection, it
shortens the outage — 6.5x fewer failed requests.**

---

## 4. Promote the database

- [ ] **Confirm the old primary is fenced or genuinely gone.** Two writable primaries is worse
      than an outage, and it is silent.
- [ ] **Promote**, then verify with a real write, not an exit code.
- [ ] **Repoint applications** at the new writer endpoint (DNS alias, connection string,
      service discovery).
- [ ] **Re-establish replication** to a third location if you have one; you are now
      single-homed and one failure from a real disaster.

```bash
aws rds failover-global-cluster --global-cluster-identifier "$GLOBAL" \
  --target-db-cluster-identifier "$SECONDARY_ARN"

# verify by WRITING, then reading back
psql "$NEW_WRITER" -c "SELECT pg_is_in_recovery();"           # must be false
psql "$NEW_WRITER" -c "INSERT INTO evac_probe(at) VALUES (now()) RETURNING id;"
```

---

## 5. Verify like a user, not like an operator

- [ ] Synthetic probe from **3 external regions** hits a real endpoint, not `/healthz`.
- [ ] **One full critical-path transaction** end to end (login → read → write → confirm).
- [ ] Error rate and p99 back inside SLO (Phase 9 Lesson 9).
- [ ] Queue depth and consumer lag draining, not growing (Phase 6).
- [ ] **Residual traffic to the dead region is falling** on the curve you expect. If it is
      flat, something is hard-coded.

---

## 6. Fail back — plan it, do not improvise it

Fail-back is usually **harder than fail-over**, because the old region may hold divergent
writes it accepted before it was fenced.

- [ ] **Never fail back during the incident.** Schedule it. The emergency is over.
- [ ] **Rebuild the old region as a replica from the new primary.** Do not "resume" it.
- [ ] **Reconcile divergent writes explicitly** if the old primary took writes after the split:
      export, diff, and decide with the data owner. This is a data problem, not a traffic one.
- [ ] Fail back during business hours, with the same runbook, in the reverse direction.

---

## 7. Standing requirements (the part that makes the above work)

- [ ] **Run this runbook on a schedule** — quarterly at minimum, in production. An untested
      failover does not work: expired credentials, primary-only security groups, a replica
      broken for six weeks, a 3600 s TTL nobody noticed, a renamed hostname.
- [ ] **Every entity has a home region** and only that region may write it. Measured: pinning
      produced 0 conflicts and 0 lost writes against multi-master's 209 diverged entities and
      **694 silently discarded acknowledged writes**.
- [ ] **Run at most (N−1)/N utilization**: 2 regions → 50% (2.00x cost), 3 → 66.7% (1.50x),
      4 → 75% (1.33x). Two regions is the most expensive way to be multi-region.
- [ ] **Keep app tier and data tier in the same region.** Measured penalty for splitting them:
      **9.3 ms → 456.2 ms p50, 49.3x**, plus **$6,221/month** of egress at 2,000 req/s.
- [ ] **Budget ≤ 2 sequential cross-region round trips per request**, and design for 1. One
      transatlantic round trip is 75 ms — 37.5% of a 200 ms budget.
- [ ] **NTP health is a data-integrity control, not a hygiene task**, anywhere last-write-wins
      is in play. At 10 s of clock drift LWW kept the *earlier* write 12.9% of the time.
- [ ] **Lower TTLs in advance** and put the anycast edge in front. You cannot fix DNS caching
      during an incident.
