---
name: checklist-hidden-state-audit-and-migration
description: For the engineer taking a service from one instance to many, removing sticky sessions, or explaining why a green autoscaler event logged out a third of the users.
phase: 11
lesson: 06
---

# Checklist: Hidden Instance-Local State — Audit & Migration

For the engineer taking a service from one instance to many, removing sticky sessions, or
explaining why a green autoscaler event logged out a third of the users. Every number below
was measured by this lesson's `code/stateless.py`. **Scope:** state living inside one process
on a fleet where the balancer will not send the next request back to it — not cache strategy
(Phase 5), rate-limit algorithms (Phase 2 L09), or deployment mechanics (Phase 10).

**Audit against this, not the textbook definition:** a service is stateless if **any instance
can serve any request, and losing an instance loses nothing but in-flight work.** "No state"
is not the test — every service has state. "No state that only one instance has" is.

---

## 0. Is hidden state implicated? — 90 seconds

**Each symptom looks like a separate bug in a separate subsystem.** Two or more appearing together after a replica-count change means yes.

- [ ] **Auth failures nobody can reproduce.** Measured, sessions in a dict + round-robin:
      **0.0% logout rate at 1 instance, 50.0% at 2, 85.0% at 6** — exactly
      `1 − floor(20/N)/20`, not load-dependent and not gradual.
- [ ] **Partial data loss that looks like flakiness.** Of 12,000 cart writes, **15.0% were
      stored and 2.5% visible at checkout.** "Mostly broken, sometimes" is the tell.
- [ ] **A quota that stopped biting.** A **100/min policy enforced as 600/min at 6, 1,600/min
      at 16** — a number in no config file.
- [ ] **Duplicate side effects on a schedule.** Measured: **126 executions for 21 ticks**.
- [ ] **404s on files that provably exist** (on *one* disk of N); flags or prices that flip.

```bash
kubectl scale deploy/app --replicas=1   # symptom vanishes entirely at N=1, returns at N>1
promtool query instant $PROM 'sum(rate(http_requests_total{status="401"}[5m])) / sum(rate(http_requests_total[5m]))'
```

**If the symptom disappears at one replica and returns at full strength at two, stop reading
application code.** It is routing arithmetic, and no unit test can see it.

---

## 1. The inventory — grep for it, do not rely on memory

```bash
grep -rnE 'self\.(sessions|cache|clients|counters|seen|next_id)\s*=' --include='*.py' .
grep -rnE '^\s*(_?[A-Z_]+)\s*=\s*(\{\}|\[\]|set\(\)|Counter\(\))' --include='*.py' .
grep -rnE '@(lru_cache|cache)\b|threading\.(Lock|RLock)\(|Timer\(' --include='*.py' .
grep -rnE 'BackgroundScheduler|schedule\.every|tempfile|/tmp/|sqlite3\.connect' --include='*.py' .
grep -rnE 'var .*(map\[|sync\.(Map|Mutex))|time\.NewTicker|cron\.New' --include='*.go' .
grep -rnE 'new (Map|Set)\(|setInterval\(' --include='*.ts' --include='*.js' .
```

**The middle column is the acceptance criterion:** if you cannot state the symptom at N=6, the audit is not finished.

| Found in process | What it does to a fleet of 6 | Moves to |
|---|---|---|
| Sessions in a dict | **85.0% of authenticated requests 401** | Shared session store, or a signed token |
| In-memory cache | Six instances hold six answers; invalidation reaches 1 of 6 | Shared cache tier + pub/sub invalidation |
| Rate-limit counters | **100/min enforced as 600/min**; 1,600 at 16 | One shared counter, atomic `INCR` + TTL |
| Files on local disk | 5 reads in 6 404; scale-in deletes the only copy | Object storage, versioned, pre-signed URLs |
| `threading.Lock()` | Excludes 1 process, permits the other 5 | Distributed lock **+ a fencing token** |
| In-process scheduler | **126 executions for 21 ticks** | Leader election via a renewable lease |
| Idempotency / dedupe keys | Retry lands elsewhere; the card is charged twice | Shared store, TTL ≥ client retry window |
| WebSocket connection map | Publish on instance 3 never reaches instance 5, silently, with `200 OK` | Pub/sub fan-out; map stays local as an index |
| Sequential id counter | Six instances all hand out id 1 | DB sequence or UUIDv7 |
| Mutated config / flags | Flag on for 1 instance in 6; bugs never reproduce | Read-only config service, pulled at boot |

---

## 2. The one-question test — what stays local

> **If this instance dies right now, does the system lose correctness, or only warmth?**

- [ ] **Warmth is fine to lose — keep it local.** Connection pools (sockets are inherently
      per-process), prepared statements, compiled regexes, warmed read-through caches, boot-
      loaded reference data. Watch the verb: a flag *snapshot* is fine, a *mutated* flag not.
- [ ] **Correctness is never fine to lose.** A session, an unflushed counter, the only copy
      of an upload, the record that an idempotency key was already used.
- [ ] **Warmth is not free.** Cold instances get full traffic share immediately — fix with
      readiness gates and a warm-up period, not with local state.

---

## 3. Migration procedure — one kind of state per deployment

Never migrate two kinds at once; when something breaks you must know which move broke it.
Each phase is independently revertible and none needs a flag day.

- [ ] **Phase 1 — Dual-write.** Write to memory *and* the store; keep reading from memory
      only, so request handling cannot break.
      **Gate:** `session_store_writes_total` rate ≈ login rate. Hold ≥ 24 h.
- [ ] **Phase 2 — Read store first, fall back to memory, repair on miss.** Emit `store_fallback_total`.
      **Gate:** that counter is **0 and stays 0 across a full session-TTL window** — non-zero
      means the store is not yet authoritative, so do not proceed.
- [ ] **Phase 3 — Remove the in-memory read, then the write.** Then disable sticky sessions.
      **Gate:** the 401 rate **does not move**. This is the step that proves the migration —
      if state were still local, dropping affinity would take it to ~85%.
- [ ] **Phase 4 — Remove affinity config entirely, then allow scale-in.** Only now.
      **Gate:** one deliberate 6→4 scale-in in business hours, zero session loss.
- [ ] **Repeat for the next row:** sessions, then counters, then the scheduler, then uploads.

**The common failure:** disabling stickiness during Phase 2 because "the store works now", then discovering the fallback path carried more traffic than anyone thought.

---

## 4. If you must keep affinity — know the bill

Affinity is a legitimate **cache-locality optimisation** and an illegitimate **correctness
mechanism**: it makes every instance a single point of failure for its pinned users.

- [ ] **Consistent hashing, never `hash(cookie) % N`.** Measured on a routine 6→4 scale-in:
      **34.0% of sessions lost (33.2% of requests) with a ring, versus 66.6% (65.2%) with
      modulo** — half the damage for a one-line config change.
- [ ] **Budget for skew.** Sessions are heavy-tailed and affinity cannot split one. Measured:
      busiest **11,038** requests, quietest **7,066** — **1.56x**, against **1.00x** for
      per-request routing. The hottest single session was **6.4%** of its instance's load.
- [ ] **Price the deploy.** A rolling deploy replaces every instance: **100%** lost, not 34%.
- [ ] **Check inherited defaults.** AWS ALB `stickiness.lb_cookie.duration_seconds` defaults
      to **86400 — one day**; Kubernetes `sessionAffinity: ClientIP` pins for **10800 s (3
      hours)**. Behind an ingress, kube-proxy may hash the *proxy's* address, pinning all.

---

## 5. Locks, leaders and fencing

- [ ] **Every distributed lock has a fencing token.** A lease TTL bounds how long the lock is
      *held*, not how long the holder *believes* it holds it. Measured: one 30 s pause on the
      leader (GC, CPU throttle, live migration) with a **15 s TTL** gave **two leaders for
      15 s and 4 duplicate executions** from an entirely correct lease.
- [ ] **The resource checks the token, or the token is decoration** — fencing took duplicates **4 → 0** only because the write path compared it.

```sql
-- Acquire or steal an expired lease; the UPDATE takes a row lock, so only one wins.
UPDATE job_leases
   SET holder = $1, expires_at = now() + interval '15 seconds',
       fence_token = fence_token + 1
 WHERE job_name = 'nightly-invoice' AND (holder = $1 OR expires_at < now())
RETURNING fence_token;

-- The enforcement. Without this predicate you have a number nobody checks.
UPDATE invoice_runs SET status = 'done', last_token = $2
 WHERE run_date = $3 AND last_token < $2;   -- 0 rows updated = you are stale. Stop.
```

- [ ] **Do not lengthen the TTL to "fix" it** — it cannot close the check-then-act gap, and
      it delays every legitimate failover by the same amount.
- [ ] **If the resource cannot fence** (third-party payment API), make the operation
      idempotent with a key the downstream honours — there is no third option.
- [ ] **Design for missed work.** Fencing prevents double execution, not lost execution —
      measured, **2 ticks ran zero times** either way. Catch-up must itself be fenced.
- [ ] **On Kubernetes use `coordination.k8s.io/v1` Lease** — `leaseTransitions` is your token.

---

## 6. Token vs session store — pick a point, knowingly

Measured over one simulated hour: 400 users, 29,012 requests, 6 instances, 120 revoked
mid-hour. **A signed token cannot be un-issued** — revocation is bought with a short TTL or a
shared lookup, and no configuration removes the trade.

| Design | Lookups / 1,000 req | Worst revocation window | Served after revocation |
|---|---|---|---|
| Server-side session store | **1000.0** | **0 s** | 0 |
| Signed token, TTL 60 s | 434.8 | 54 s | 39 |
| Signed token, TTL 300 s | 251.1 | 281 s | 322 |
| Signed token, TTL 900 s | **177.9** | **880 s** | 1,130 |
| Signed token, TTL 3600 s | 90.5 | 3,121 s | 3,079 |
| **Token + denylist, 30 s pull** | **202.7** | **29 s** | 26 |

- [ ] **Default to the hybrid** (15-min token + 30 s denylist pull). Cost is
      `instances × (3600 / 30)` = **720 fixed reads per hour** — proportional to fleet size,
      **not traffic**. Nearly free at 10x traffic; 10x the cost at 10x the instances.
- [ ] **Do not shorten the TTL as the revocation fix.** A 60 s TTL costs **2.1x** the
      hybrid's store traffic for a *worse* window (54 s vs 29 s).
- [ ] **Never rotate the signing key to revoke one account** — it logs out every user.
- [ ] **State the revocation SLO in seconds.** "Within 60 s" rules out every TTL ≥ 300 s.

---

## 7. The shared store is a new SPOF

You removed single points of failure and built one. Decide these **before** you need them.

- [ ] **Replicate across AZs.** A single-AZ session store makes the whole service single-AZ.
- [ ] **Decide fail-open or fail-closed now, in writing.** Fail-closed for anything touching
      money or personal data; fail-open is a security incident with a schedule. Third option:
      on outage accept *unexpired signed tokens* — degrade to the token model, not to zero.
- [ ] **TTL on every session key** — sessions without expiry are a memory leak with a login
      page — and **alert on store latency, not just availability**: every request waits on it.

---

## Sign-off gate

Do not call a service stateless until **all** of these hold:

- [ ] Replica count goes 1 → N → 1 with no change in error rate.
- [ ] Sticky sessions are **off**, and the 401 rate did not move when they were disabled.
- [ ] A deliberate scale-in destroyed **0** sessions.
- [ ] Every scheduled job runs exactly once per tick at N > 1, under a fenced lease.
- [ ] `kill -9` on a random instance costs only in-flight requests, which retry, and nothing
      in the container filesystem is read by a later request.
- [ ] The revocation window is a number you can state, and it meets the security SLO.
