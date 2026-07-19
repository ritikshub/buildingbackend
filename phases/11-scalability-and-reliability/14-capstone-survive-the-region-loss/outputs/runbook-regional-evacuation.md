---
name: runbook-regional-evacuation
description: Use this when one region is failing and the other is healthy.
phase: 11
lesson: 14
---

# Runbook — Regional Evacuation

Use this when one region is failing and the other is healthy. Section 2 is the whole
runbook; the rest is mechanical, and running it against a non-regional failure makes the
outage worse.

**RPO** = Recovery Point Objective (writes you accept losing), **RTO** = Recovery Time
Objective, **GSLB** = Global Server Load Balancing (health-checked cross-region steering),
**AZ** = Availability Zone, **SLO** = Service Level Objective. Failing region `us-east-1`,
survivor `us-west-2`; do not reorder the steps.

---

## 1 · Preconditions — you cannot acquire any of these during an incident

If a line below is false right now, close this runbook. Attempting it converts a
regional outage into a global one, plus data loss.

- [ ] **Cross-region replicas for every shard, with lag on a dashboard you read in five
      seconds.** Lag you cannot quote is an RPO you cannot choose.
- [ ] **Pre-provisioned headroom for 100% of peak in the survivor** — one region alone runs
      the whole service at **80% utilization**. Bought at the budget meeting, not at 03:00.
- [ ] **Stateless services.** No sticky sessions, no on-instance cache holding the only
      copy, no local disk in the request path.
- [ ] **GSLB health checks configured and their failure action known** — whether failing
      the check drains the region or blackholes it.
- [ ] **Rehearsed end to end within the last 90 days**, by someone who did not write it,
      against production-shaped infrastructure. Freeze, GSLB weights, and promotion must
      all be reachable from a control plane that does not live in `us-east-1`.

## 2 · Go / no-go decision

The **incident commander** owns this alone, and announces the window that supported it.

**Decision deadline: 5 minutes from the first regional page.** The SLO is 99.95% monthly;
a month averages 43,830 minutes, so the budget is **21.9 minutes = 1,315 error-seconds**.
A half-dead region burns **30 error-seconds per minute** and exhausts the month in 44
minutes; a clean evacuation costs about **22 error-seconds, 1.7% of the month**.
Hesitating is more expensive than moving.

| Signal | Evacuate when | Observation window | DO NOT evacuate when |
|---|---|---|---|
| `us-east-1` error rate | > 25% of that region's requests | 3 consecutive 30 s windows | < 10%, or the slope improved across the last 2 windows |
| Duration | No recovery trend, or the provider confirms control-plane loss | ≥ 5 min | Failure is < 2 min old and unclassified — you are looking at a deploy or a blip |
| Blast radius | Confined to one region: `us-west-2` errors < 1% | 2 consecutive 30 s windows | **Both regions degraded.** A global fault (bad release, poisoned config, dependency outage) follows you west and you arrive with half the fleet |
| Replication lag at decision time | ≤ 1.0 s | Read now, re-read 30 s later | > 5 s, unless a named business owner accepts the loss aloud on the bridge |
| Surviving-region headroom | ≤ 45% utilized now, and scale-out to 100% of peak lands at ≤ 80% | Instantaneous | > 60% utilized now — you would evacuate into a second saturation event |
| Rehearsal recency | Within 90 days | — | Never rehearsed. Improvising promotion loses the replicas too |

**RPO arithmetic — do this before you decide.** `RPO_writes ≈ write_rate_to_affected_shards
× replication_lag_seconds`. At the reference figures — roughly **45 writes/s** reaching the
affected shards at **0.45 s** of lag — measured loss was **20 acknowledged writes**, scaling
linearly: 1.0 s is about 67 writes, 5.0 s about 330. Say the number aloud before step 7.

## 3 · The ordered steps

Announce each step number as you start it. Steps 1-6 are **REVERSIBLE**: aborting costs
money and nothing else.

1. **Declare the incident, name the incident commander.** REVERSIBLE. One IC, one bridge,
   one scribe recording wall-clock time per step.
2. **Freeze deploys, config pushes, and autoscaling policy edits globally.** REVERSIBLE.
   Not east-only — a `us-west-2` deploy mid-evacuation looks exactly like the evacuation
   failing.
3. **Scale out `us-west-2` FIRST, to 100% of global peak.** REVERSIBLE. Instances take
   **90 s to boot and warm up**; shifting traffic before the fleet exists shifts it onto
   machines that are not there yet and saturates the ones that are. Most common failure.
4. **Gate on capacity being in service.** REVERSIBLE. `readyReplicas == replicas` and
   load-balancer targets healthy. Ready pods, not scheduled pods. Wait the full 90 s.
5. **Shift traffic: fail the `us-east-1` GSLB health check, set its DNS weight to 0.**
   REVERSIBLE. Detection takes **15 s**; resolver traffic then decays exponentially with
   time constant **tau = 22 s**.
6. **Verify traffic actually moved.** REVERSIBLE, and a hard gate. Expect 3 tau (about
   **66 s**) to flatten, and a **residual 1.8% floor that never moves** — resolvers may
   serve stale records past TTL when authoritative servers are unreachable, per **RFC
   8767** (*Serving Stale Data to Improve DNS Resiliency*). Do not wait for 0%.

> ### STEP 7 IS THE POINT OF NO RETURN
>
> **Everything above this line is reversible. Nothing below it is.** Promotion takes **45 s**
> and cannot be undone. The instant a replica is promoted, every write the old primary
> acknowledged but had not replicated is **permanently unrecoverable** — the RPO you computed
> in section 2. The old primary becomes a diverged timeline: it can never rejoin as a
> replica, and fail-back requires a **full re-sync**. The IC states the RPO number aloud,
> then promotes.

7. **Promote the `us-west-2` replicas.** **IRREVERSIBLE.** Promote every affected shard
   and verify each exits recovery. A half-promoted data tier is worse than either end state.
8. **Re-point writers at the new primaries.** **IRREVERSIBLE in practice.** Rotate the
   connection string or DNS alias and confirm write errors fall to baseline. Until this
   lands, reads are served and writes are failing.
9. **Rebuild redundancy inside `us-west-2`.** REVERSIBLE. You now run one region with no
   failover target. Re-create replicas across AZs and re-arm silenced alerts.

**Expected recovery curve**, served fraction by 10 s bucket after the cut:
`46, 63, 79, 79, 82, 86, 86, 85, 86, 90, 95` (%). Full recovery is gated by the 90 s boot,
not by DNS and not by promotion. A curve materially below this means diagnose, not add
operator actions: a hardened configuration needs **0 operator restarts** to survive an
evacuation, a naive one needed **3**, and a restart is not a repair.

## 4 · Verification commands

**Step 4 — capacity in service.** Pass: numbers equal, `No resources found`, held for 30 s.

```bash
kubectl --context us-west-2 -n api get deploy api \
  -o jsonpath='{.status.readyReplicas}/{.spec.replicas}{"\n"}'
kubectl --context us-west-2 -n api get pods -l app=api --field-selector status.phase!=Running
```

**Steps 5-6 — weights landed, resolvers followed.** Pass: observations read `Failure`, the
record shows `Weight 0`, resolvers answer `us-west-2` only. East answers past 66 s are the
RFC 8767 stale tail, not a failed change.

```bash
aws route53 get-health-check-status --health-check-id "$HC_EAST" \
  --query 'HealthCheckObservations[].StatusReport.Status' --output text
aws route53 list-resource-record-sets --hosted-zone-id "$ZONE_ID" \
  --query "ResourceRecordSets[?Name=='api.example.com.'].[SetIdentifier,Weight]" --output text
dig +noall +answer +ttlid api.example.com A @1.1.1.1
```

**Step 7 — replica state, every shard.** First two gate promotion; the last runs after.

```sql
SELECT pg_is_in_recovery();                                              -- expect: t
SELECT EXTRACT(epoch FROM (now() - pg_last_xact_replay_timestamp())) AS lag_s;  -- <= 1.0
SELECT pg_last_wal_receive_lsn() AS received;   -- record per shard; evidence for section 6
SELECT pg_is_in_recovery();                     -- AFTER promotion, expect: f
```

**Steps 6, 8, 9 — served fraction, per-region errors, residual tail.**

```text
# served fraction (global) -- pass: >= 0.95 within 110 s of the cut
sum(rate(http_requests_total{status!~"5.."}[30s])) / sum(rate(http_requests_total[30s]))

# per-region error rate; add method=~"POST|PUT|PATCH|DELETE" to check writes after step 8
# pass: us-west-2 < 0.01. A rising us-west-2 means the fault is global, not regional: STOP
sum by (region) (rate(http_requests_total{status=~"5.."}[30s]))
  / sum by (region) (rate(http_requests_total[30s]))

# residual traffic still reaching us-east-1 -- pass: <= 0.018 and flat
sum(rate(http_requests_total{region="us-east-1"}[1m])) / sum(rate(http_requests_total[1m]))
```

## 5 · Fail-back — slower, more dangerous, never an emergency

Evacuation is a fire drill; fail-back is elective surgery. The region you return to has
been serving nothing, so its caches, pools, and capacity assumptions are all stale.

- [ ] **Never fail back during the incident.** The incident ends when service is restored
      in `us-west-2`, not when `us-east-1` returns. Going back under time pressure turns a
      one-region outage into two.
- [ ] **Require a scheduled off-peak maintenance window**, with the IC, a DBA, and on-call
      for every dependent service present, and the original root cause understood and
      fixed in writing before the window is booked.
- [ ] **Full re-sync, not catch-up.** The old primary diverged at promotion. Rebuild it from
      a fresh base backup as a replica of the current primary; stream until lag ≤ 1.0 s.
- [ ] **Return traffic in increments with a bake at each: 1% → 10% → 50% → 100%.** At least
      30 min at 1% and at 10%, a full peak cycle at 50%. Watch error rate, p99, and lag.
- [ ] **Define the abort condition in numbers first**: error rate 0.5 points above baseline,
      or p99 regressed 20%, rolls back one increment and ends the window. Symmetry is not
      required — staying primary in `us-west-2` is a valid outcome.

## 6 · Post-evacuation checklist — within 24 hours, while timestamps are trustworthy

- [ ] **Reconcile the lost writes.** You have the RPO number and the last received LSN per
      shard. Diff the old primary's WAL beyond that LSN against the promoted primary and
      produce the actual list of records and customers — "about 20 writes" is not a
      reconciliation. Replay or refund what is recoverable, mark what is not, and route
      ambiguous cases to a human owner rather than a retry job.
- [ ] **Customer comms**: acknowledge during the incident, state the impact window once
      traffic is stable, and name the data loss to affected customers. Do not let the RPO
      surface first in a support ticket.
- [ ] **Error-budget accounting.** Total error-seconds burned against the **1,315** monthly
      budget and record the remainder. If it is negative, the freeze stays on.
- [ ] **Record timings per step**: detection, decision, scale-out complete, traffic shifted,
      residual floor reached, promotion complete, writers re-pointed, 95% served.
- [ ] **Count operator interventions.** Every restart and manual nudge is a hardening gap;
      the target is zero. Book the next rehearsal before the retrospective ends — the 90-day
      clock restarted when this evacuation did.

---

### Reference figures

| quantity | value |
|---|---|
| SLO / monthly budget | 99.95% → 21.9 min → **1,315 error-seconds** (43,830 min/month) |
| GSLB health-check detection | 15 s |
| DNS resolver decay constant | tau = 22 s; ~66 s to flatten |
| Residual traffic floor (RFC 8767) | 1.8%, never reaches zero |
| Replica promotion | 45 s, irreversible |
| Instance boot + warm-up | 90 s — gates full recovery |
| Measured RPO | 20 acknowledged writes at 0.45 s lag (45 writes/s x 0.45 s) |
| Surviving-region load | 100% of peak at 80% utilization |
| Served fraction, 10 s buckets | 46, 63, 79, 79, 82, 86, 86, 85, 86, 90, 95 (%) |
| Operator restarts required | hardened: **0** · naive: **3** |
