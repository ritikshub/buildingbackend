# Runbook — "The connection pool is exhausted"

**Page trigger:** `pool_checkout_wait_seconds` p99 > 0.5 s for 2 min, or `pool_checkout_timeouts_total` rate > 0.

**Read this first:** exhaustion is a *symptom*. There are five diseases with this one symptom, and
four of them get **worse** if you raise `pool_size`. Diagnose before you tune. Time-box triage to
10 minutes, then mitigate.

---

## 0 · Confirm and scope (2 min)

- [ ] Which pool? App→Postgres, app→Redis, app→HTTP, or the pooler's own server-side pool.
- [ ] One replica or all of them? Started at a deploy, a scale event, a migration, or spontaneously?
- [ ] Is the database itself healthy — CPU, disk, replication lag, failover in the last hour?

```text
histogram_quantile(0.99, sum by (le) (rate(pool_checkout_wait_seconds_bucket[5m])))
sum by (pod) (pool_in_use) / sum by (pod) (pool_max_size)
sum(rate(pool_checkout_timeouts_total[5m]))
sum(rate(pool_connections_created_total[5m]))     # churn: should be ~0 in steady state
```

## 1 · Decision table — which disease is it?

| Signal | Leak | Slow queries | Held-open txn | await inside checkout | Real capacity |
|---|---|---|---|---|---|
| Utilization at 100% **through the traffic trough** | **YES** | no | maybe | no | no |
| DB CPU / active queries | idle | **busy** | idle | idle | **busy** |
| `pg_stat_activity` dominant state | `idle` | `active` | **`idle in transaction`** | `idle` | `active` |
| Mean query duration | normal | **up** | normal | normal | normal |
| Checkout hold time (app-side) | ∞ | up ≈ query time | **minutes** | **≫ query time** | ≈ query time |
| Recovers when load drops | **never** | yes | sometimes | yes | yes |
| Correlates with a deploy | usually | maybe | usually | usually | no |

**The trough test is the single most valuable check.** Anything load-driven eases off at 4am.
A leak does not.

## 2 · The queries

```sql
-- Where are the backends and what are they doing?
SELECT state, wait_event_type, count(*)
FROM pg_stat_activity WHERE datname = current_database()
GROUP BY 1, 2 ORDER BY 3 DESC;

-- Held-open transactions: the classic silent pool killer.
SELECT pid, application_name, state, now() - xact_start AS txn_age,
       now() - state_change AS in_state, left(query, 120) AS query
FROM pg_stat_activity
WHERE state IN ('idle in transaction', 'idle in transaction (aborted)')
  AND now() - state_change > interval '10 seconds' ORDER BY txn_age DESC;

-- Genuinely slow statements right now.
SELECT pid, now() - query_start AS runtime, wait_event_type, wait_event, left(query,120)
FROM pg_stat_activity WHERE state = 'active' AND now() - query_start > interval '1 second'
ORDER BY runtime DESC;

-- Who is holding connections at all, and how much headroom is left?
SELECT application_name, client_addr, count(*)
FROM pg_stat_activity GROUP BY 1,2 ORDER BY 3 DESC LIMIT 20;
SELECT (SELECT setting::int FROM pg_settings WHERE name='max_connections') AS max_conn,
       count(*) AS in_use FROM pg_stat_activity;

-- PgBouncer, if present (psql "host=<bouncer> port=6432 dbname=pgbouncer"):
--   SHOW POOLS;   cl_waiting > 0 means clients are queueing for a server conn
--   SHOW STATS;   avg_wait_time is PgBouncer's checkout wait
```

App-side, with leak tracking on (keep it on permanently in staging):

- [ ] Dump outstanding checkouts older than 30 s with their acquiring stack.
      SQLAlchemy: `echo_pool="debug"`. HikariCP-style: `leakDetectionThreshold`.
- [ ] Compare checkout **hold** time p99 against query duration p99. A large gap = non-DB work
      inside the checkout (an HTTP call, a template render, a cache miss, an `await`).

## 3 · Immediate mitigations (buy time, do not "fix")

Ranked least to most invasive. Record which you used, in the incident doc.

- [ ] **Shed load at the edge** — rate limit or return 503 on the noisiest low-value endpoint.
      Bounded failure beats an unbounded queue.
- [ ] **Terminate held-open transactions** older than N minutes (check the query first):
      ```sql
      SELECT pg_terminate_backend(pid) FROM pg_stat_activity
      WHERE state = 'idle in transaction' AND now() - state_change > interval '5 minutes';
      ```
- [ ] **Kill runaway queries** (`pg_cancel_backend` first, `pg_terminate_backend` if it ignores you).
- [ ] **Roll the replicas** if it is a leak — a restart resets the pool and buys hours, not a fix.
- [ ] **Scale replicas DOWN**, not up, when the database is the bottleneck: more replicas = more
      pools = more connections = worse.
- [ ] **Do NOT raise `pool_size`** unless the decision table says "real capacity" AND §4 still fits.
- [ ] Set `idle_in_transaction_session_timeout` (`'30s'`) and `statement_timeout` if unset.

## 4 · Sizing worksheet (do this before the fix ships)

```text
A  measured knee (smallest pool reaching ~97% of peak throughput)  = ______
   sanity check: (cores x 2) + effective_spindles                  = ______
   Little's Law: peak_rps_per_process x hold_time_seconds          = ______
   pool_size  := max(Little's Law, 2), capped by the knee          = ______

B  worker processes per replica (gunicorn/uvicorn --workers)       = ______
C  PEAK replica count (HPA maxReplicas, not today's count)         = ______
D  sidecars / crons / migration jobs / admin sessions              = ______

   FLEET TOTAL = A x B x C + D                                     = ______

E  max_connections                                                 = ______
F  reserved (superuser_reserved_connections + monitoring + you)    = ______
   BUDGET = E - F                                                  = ______

   PASS if FLEET TOTAL <= 0.8 x BUDGET.  Otherwise: shrink A, cap C, or add PgBouncer.
```

Worked example from the lesson: `20 x 4 x 20 = 1600` against a budget of `192` — 8.3x over, with
nobody having typed 1600 anywhere.

## 5 · Permanent fixes, by diagnosis

- **Leak** — every acquire inside a `with` / `async with`; no bare `acquire()` anywhere, enforced by
  a lint rule. Leak detection threshold ≈ 10x p99 request time. Assert `pool.in_use == 0` after the
  test suite.
- **Slow queries** — `EXPLAIN (ANALYZE, BUFFERS)`, add the index, set `statement_timeout` so one bad
  query cannot own a permit indefinitely.
- **Held-open transaction** — shrink the transaction to the writes that must be atomic; never do
  network I/O or a queue publish inside one. Set `idle_in_transaction_session_timeout`.
- **Unrelated I/O inside the checkout** — move every HTTP call, cache lookup and template render
  *outside* the `with`. Measured cost of getting this wrong: 6.4x throughput and 9.4x the connections.
- **Real capacity** — only now consider a bigger pool, and only after re-running §4. Otherwise: read
  replica, cache the hot query, or cut the per-request query count (N+1).

## 6 · Prevention checklist (paste into the PR template)

- [ ] `checkout_timeout` / `pool_timeout` is set and is ≤ 1 s. Never unbounded.
- [ ] `statement_timeout` and `idle_in_transaction_session_timeout` are set server-side.
- [ ] Every acquire is inside a `with` / `async with`. No unrelated I/O between acquire and release.
- [ ] Pool is created **after** fork (worker-init hook), never at import time before forking.
- [ ] `pool_recycle` / `max_lifetime` is set **and jittered** (±10–25%) to avoid a reconnect stampede.
- [ ] TCP keepalives set below the NAT/LB idle timeout; `pool_pre_ping` on if behind NAT/proxy/failover.
- [ ] §4 worksheet completed and pasted in the PR description; `PASS` at peak replica count.
- [ ] Exported: checkout wait p50/p99, in_use, idle, waiting, timeouts/s, connections created/s.
- [ ] Alerts: checkout wait p99 (page), timeouts/s > 0 (page), utilization 100% for 15 min (ticket),
      connections created/s sustained above ~1/s per pool (ticket — you are churning, not pooling).
