---
name: checklist-tail-tolerance-review
description: For any service whose request fans out to more than one backend, or that sits inside someone else's fan-out.
phase: 11
lesson: 11
---

# Tail-Tolerance Review Checklist

For any service whose request fans out to more than one backend, or that sits inside
someone else's fan-out. Work top to bottom. Every threshold below is a starting value to
**measure and then change**, not a constant to paste.

Source: Dean, J. & Barroso, L. A., "The Tail at Scale", CACM 56(2):74-80, 2013.

---

## 0 · Know your fan-out number

Trace one request end to end and record **N**, the number of backends it touches. Note
whether N is fixed or grows with the query, and whether you need all N or a quorum.
"All" is the expensive case this checklist assumes.

**The percentile your callers actually feel is roughly your `p(100 − 100/N)`:**

| N | you must care about | because |
|---:|---|---|
| 1 | p99 | 1.0% of requests hit it |
| 10 | p99.9 | 9.6% of requests hit your p99 |
| 100 | p99.9 → p99.99 | 63.4% of requests hit your p99 |
| 1000 | p99.99 | 99.996% of requests hit your p99 |

- [ ] N is written down for each fan-out endpoint.
- [ ] The percentile above is **measured and graphed**, not merely assumed to be fine.
- [ ] Someone owns the composed request. (If the answer is "the shard teams", nobody does.)

---

## 1 · Measurement (do this before changing anything)

- [ ] **Percentiles of the fan-out request**, not of the backends. Per-backend dashboards
      are structurally incapable of showing this problem — in the measured example every
      backend was green at p99 = 105 ms while the composed median was 129 ms.
- [ ] **Shards contributing per response** emitted on every response
      (`shards_answered: 98/100`), not only on partial ones.
- [ ] **Histograms, not pre-computed percentiles.** You cannot average p99s across
      instances. Export buckets and merge them (`histogram_quantile` over the fleet).
- [ ] **Coordinated omission checked** in the load generator. If it waits for a response
      before sending the next request, it under-samples exactly the slow window and your
      percentiles are fiction.
- [ ] Counters: `hedges_issued`, `hedges_won`, `hedge_budget_denied`,
      `deadline_exceeded_before_start`, `partial_responses`.

---

## 2 · Hedged requests

Ship only if the operation is **idempotent**. A hedge is a duplicate execution and the
loser may still complete.

| Knob | Start at | Never |
|---|---|---|
| Hedge delay `D` | your **measured p95** | a hard-coded round number |
| Hedge budget | **5–10% of traffic**, global | unlimited |
| Hedge target | a **different replica**, different failure domain | the same instance |
| Applies to | safe reads (`GET`, queries) | anything that mutates without an idempotency key |

Measured trade (200k calls, backend p50 9.2 ms / p99 105.0 ms):

```text
 delay set at    delay      p99    p99.9   extra load
 (none)              -    103.3    386.9         0.0%
 p99            105.0     105.3    121.0         1.0%
 p95             22.5      34.2     54.3         5.0%   <-- operating point
 p90             17.3      29.1     43.4        10.0%
 p75             12.6      25.2     40.6        25.0%
 p50              9.2      22.9     37.8        49.9%
```

- [ ] `D` is derived from a percentile **measured in the last 30 days**, at peak.
- [ ] `D` is **re-derived automatically or reviewed on a schedule**. A constant delay is
      correct for exactly one load level.
- [ ] A **budget exists and is enforced globally**, not per request.
      Without it, measured: hedge rate 5% → 95.2%, offered load 1.95×, ρ 0.85 → 1.66,
      p99 466 → 9401 ms (20× worse than not hedging).
- [ ] Alert on **hedge rate > 2× its configured target** — that is the early warning that
      the distribution moved.
- [ ] Alert on **hedge win rate collapsing while hedge rate stays high** — that is
      correlated slowness, and hedging is now pure cost. See §5.

---

## 3 · Tied requests (only if your server can cancel)

Send both copies immediately; each carries the other's identity; whichever **starts**
first cancels its twin.

- [ ] The server can **drop enqueued-but-not-started work**. Verify by experiment. A plain
      HTTP server cannot: a client hanging up does not remove an already-accepted request.
- [ ] There is a **real queue** in front of the resource. No queue ⇒ both copies start ⇒
      you have doubled your load and gained nothing.
- [ ] Cancel message flight time ≪ service time. Same datacenter only; across regions the
      cancel lands after both copies have finished.
- [ ] Race window measured and accepted (measured: 11.2% duplicate work).

**Without the cancel path**, the identical policy measured: 100% of second copies
executed, 53.0% of all service time wasted, p99 157 → 5514 ms.

---

## 4 · Deadlines

- [ ] Every request carries a **deadline** (absolute time), not a timeout (duration).
- [ ] Each hop computes `remaining = deadline − now()` and passes the **remainder** on.
- [ ] Each hop **refuses immediately** when `remaining < expected_service_time`. Starting
      work you cannot finish is pure waste.
- [ ] Sent on the wire as a **remaining duration**, converted to a local absolute time at
      each hop (skew-tolerant; does not need synchronised clocks).
- [ ] No downstream timeout exceeds the caller's remaining budget.
- [ ] Cancellation propagates on caller disconnect, and a handler actually stops.

Measured, 3 hops, 1 s user deadline:

```text
mode          p50    p99   worst    late   wasted ms/req   refused early
independent   594   1587    2664   10.4%            38.3            0.0%
propagated    594   1000    1000    0.0%             0.0            6.7%
```

Identical p50 — which is why this never surfaces in a dashboard review.

---

## 5 · Correlation (the part that invalidates §2 and §3)

Hedging bets the second replica is having a better minute. Measured, same 8.9% extra load:
**8.86×** median improvement under independent slowness, **1.02×** under correlated.

- [ ] Replicas of a shard are in **different failure domains** — rack, power, hypervisor,
      AZ, deploy wave. Replica placement is a *latency* decision, not only availability.
- [ ] Deploys are **waved**, so a bad build cannot stall every replica of a shard at once.
- [ ] Compaction / index rebuild / backup schedules are **staggered across replicas**.

**Jitter every periodic action.** Correlation, not volume, is what turns 300 instances
into an incident.

| Periodic thing | Fix |
|---|---|
| Circuit-breaker cool-down | `cooldown × U(0.5, 1.5)` |
| Retry backoff | full jitter: `sleep(U(0, backoff))` |
| Cron / scheduled jobs | offset per instance; never `:00` |
| Cache TTLs | `ttl × U(0.9, 1.1)` at write time |
| Health checks, token refresh, config reload | random initial phase |

Measured, 300 breakers vs a dependency absorbing 25 probes / 100 ms:

```text
cool-down            peak probes   windows overwhelmed   all closed at
fixed 5.000 s                158                    22   NEVER (>60 s)
5 s × U(0.5, 1.5)             14                     0   7.61 s
```

---

## 6 · Retries across layers

Retries **multiply**; they do not add.

```text
layers   3 attempts each   3 attempts + 10% budget each
   1              3                    1.10
   2              9                    1.21
   3             27                    1.33
   4             81                    1.46
```

- [ ] Retries enabled at **exactly one layer** — usually the one nearest the caller,
      which knows the deadline. Disabled everywhere else, in writing.
- [ ] That layer has a **budget** (fraction of traffic), not just an attempt count.
- [ ] Inventory taken of every layer that *could* retry: client SDK, gateway, service
      mesh sidecar, application code, database driver.
- [ ] Retries only on idempotent operations, and never past the deadline.

---

## 7 · Degradation

- [ ] The response contract supports a **partial result** (`partial: true`,
      `shards_answered: n/N`), and clients are written to handle it.
- [ ] Decided **in advance**, per endpoint, whether partial is acceptable. Search: yes.
      Account balance: no. This is a product decision, not a runtime one.
- [ ] Slow replicas go on **latency-induced probation** — removed from rotation but still
      sent shadow traffic, so recovery is detected rather than guessed.
- [ ] Partitions are **smaller than machines** (micro-partitioning), so load can be moved
      in small increments; hot partitions get extra replicas.

---

## Incident quick reference

| Symptom | Likely cause | First move |
|---|---|---|
| Composed p50 ≫ any backend p99 | fan-out arithmetic, working as designed | hedge at the p95, with a budget |
| Hedge rate climbing past its target | delay no longer matches the distribution | budget is holding — re-derive `D`; do **not** raise the budget |
| Hedge rate at budget, win rate → 0 | correlated slowness | stop tuning hedges; look at shared resources and placement |
| p99 far worse *with* hedging than without | unbudgeted hedging under overload | cap the budget; consider disabling hedging until ρ drops |
| Dependency recovers, then dies again on a cycle | synchronised half-open probes | jitter the cool-down |
| Throughput normal, goodput near zero | work executing past the deadline | propagate deadlines; refuse at each hop |
| One user request → dozens of backend calls | retry amplification across layers | disable retries at all but one layer |
