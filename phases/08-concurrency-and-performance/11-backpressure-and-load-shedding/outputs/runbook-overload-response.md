# Runbook: Service Under Overload

For the on-call engineer at 03:00: latency is up, the service is not erroring, and there is
no bad deploy to roll back. Work top to bottom; do not skip §0. **Scope:** a request-serving
service whose internal queues have grown — not a crash loop, not a bad deploy (roll back).

---

## 0. Confirm it is overload — 60 seconds

Overload has a signature. Three or more of these means yes.

- [ ] **Queue time is most of your latency.** `p99_total` climbing while `p99_service_time`
      is flat — the difference is queueing.
- [ ] **Goodput << throughput.** Goodput = responses delivered *before their deadline*;
      normal throughput with collapsed goodput means work nobody will read.
- [ ] **Wasted-work ratio high.** `completions_past_deadline / completions`. Above ~20%
      you are in the loop; a measured unbounded queue at 2x overload hit **98%**.
- [ ] **Retry rate above budget.** `requests{attempt>1} / requests` over ~10% means the load
      you see is partly your own echo (measured: 80 -> **187 req/s, 2.3x**, demand flat).
- [ ] **Utilization "looks fine" at 85-95%.** Not reassurance: `W = S/(1-rho)` puts 0.90
      at 10x service time, and the knee is at **0.78** once service times vary.

```bash
promtool query instant $PROM 'max(queue_oldest_item_age_seconds)'   # THE signal
promtool query instant $PROM 'sum(rate(http_responses_within_deadline_total[1m]))'
ss -ltn | head                          # Send-Q on the listener = accept backlog depth
nstat -az TcpExtListenOverflows TcpExtListenDrops   # non-zero = kernel dropping SYNs
py-spy dump --pid $(pgrep -f 'uvicorn|gunicorn' | head -1)   # where are threads parked?
```

**If `queue_oldest_item_age_seconds` exceeds the client timeout, everything queued is
already dead.** State that number in the incident channel.

---

## 1. Immediate mitigations, in priority order

### 1.1 Shed load — lowers lambda, do this first

- [ ] **Tier 3 to zero.** Analytics, prefetch, batch, webhook replay. No user impact.
      `curl -XPOST :9000/admin/flags -d 'shed_tier3=true'`
- [ ] **Tier 2 by 50%.** Search, personalisation. Serve stale cache or a reduced response.
- [ ] **Never shed Tier 1** — checkout, payment, auth, anything a human awaits.
- [ ] **Enable dequeue-time deadline checking.** Dropping expired work is free.
- [ ] **Switch the queue to LIFO** if you have the flag. Measured at 2x overload: FIFO
      goodput **16.5/s**, LIFO **80.1/s**, same capacity and arrivals.

### 1.2 Break circuits — stops paying timeouts

- [ ] **Force-open the breaker on any dependency above ~50% error/timeout rate.** Measured:
      a dead dependency took **95% of all thread-time** and pushed an unrelated 4 ms
      endpoint to a **905 ms p99**; a breaker brought it to **54 ms**.
- [ ] Every outbound call needs a timeout: a breaker on an unbounded call never trips.

### 1.3 Shrink limits — counterintuitive and correct

- [ ] **Make the in-flight limit smaller, not bigger** — target `capacity x target_latency`
      (Little's Law). Measured: a fixed limit of 64 gave **4 req/s of goodput at 320 ms
      RTT**; shrinking to ~7 gave **181 req/s at 33 ms**.
- [ ] Cut `max_pending_requests` in the mesh — Envoy's default of **1024** is an unbounded
      queue with extra steps.

### 1.4 Cut the retry loop — lowers lambda at the source

- [ ] **Retry budget to 0%** fleet-wide, temporarily — the single most effective action
      against a metastable loop.
- [ ] Return `503` with a **jittered** `Retry-After` — a constant re-synchronises the herd.
- [ ] Audit retries at multiple layers: SDK 3x + mesh 3x + gateway 3x = **27** per request.

---

## 2. Breaking a metastable loop

You are here if **the trigger is gone and the system is still down.** Identify the loop:

| Loop | Signature | The cut |
|---|---|---|
| Retry amplification | offered load > real demand; retry rate over budget | budget to 0, shed at ingress |
| Cache-miss amplification | hit rate ~0, DB saturated, requests time out before populating | serve stale, single-flight misses, warm while drained |
| Connection-pool thrash | all workers in the pool wait queue, DB at `max_connections` | shrink the app pool, add `statement_timeout` |
| GC / memory | pause time rising with queue depth | shed to shrink the queue; do NOT raise the heap |

Every cut has the same shape: **drop arrivals below capacity long enough that queue time
falls under the client timeout.** Once it does, retries stop and load falls on its own —
measured at **2.0 s** with shedding on, and never without it.

- [ ] Shed hard enough to actually cross the line — 50% is often not enough, try 90%/60 s.
- [ ] Ramp back **slowly** (10% every 30 s); all at once re-enters the loop.
- [ ] Restart last, and **only with shedding already on** — a cold start into full traffic
      with empty caches re-enters the loop immediately.

---

## 3. What NOT to do

- [ ] **Do not add capacity blindly.** With a retry-driven loop, load scales with capacity
      and new instances join the collapse. Add it *after* goodput recovers.
- [ ] **Do not raise timeouts.** Each doomed request then occupies a worker for longer.
- [ ] **Do not increase pool or queue sizes.** More queue = more latency, more memory.
- [ ] **Do not restart repeatedly.** Each restart drops the queue (helps for seconds) and
      empties every cache (hurts for minutes). You will oscillate.
- [ ] **Do not chase "the slow endpoint".** Under queueing every endpoint is slow, even ones
      that do nothing. Find the saturated resource, not the slow URL.
- [ ] **Do not trust a healthy utilization number.** 89% and 91% are the same picture.

---

## 4. Permanent fixes — file before closing the incident

- [ ] **Bound every queue** and record the value (accept backlog, server connection queue,
      work queue, pool wait queue, DB timeouts, client retry budget). For anything you leave
      unbounded, write down why.
- [ ] **Deadline on every request, checked at dequeue.** Propagate the *remaining* budget
      downstream; no downstream timeout may exceed it.
- [ ] **Criticality tiers at ingress**, with a per-tier shed switch that works at 100% CPU.
- [ ] **Instrument queue TIME**: `queue_oldest_item_age_seconds` (gauge) plus `shed_total`
      and `completions_past_deadline_total` (counters — a 15 s gauge scrape misses a 4 s
      saturation entirely). Graph goodput beside throughput.
- [ ] **Adaptive concurrency limit** (Netflix concurrency-limits, resilience4j, Polly, or an
      RTT-gradient semaphore) instead of a hand-tuned constant.
- [ ] **One pool per dependency** plus a breaker on each: a failure *rate* over a window
      with a minimum call count, and a **jittered** cool-down.
- [ ] **Retry budget 10% + full jitter + idempotency keys, at exactly one layer.**
- [ ] **Load-test the shed path** — the path where the semaphore is full and the deadline
      has passed. Assert it does not allocate per request, log at INFO, call a feature-flag
      service, or need a connection from the pool it protects.

```text
kernel      net.core.somaxconn=4096, net.ipv4.tcp_max_syn_backlog
uvicorn     --backlog 512 --limit-concurrency <cap*target_latency> --timeout-keep-alive 5
gunicorn    --backlog 512 --timeout 30 --graceful-timeout 10
nginx       limit_req_zone + limit_req burst=N nodelay; limit_conn; limit_req_status 429;
            proxy_read_timeout <under the caller's deadline>
envoy       circuit_breakers.max_pending_requests (DEFAULT 1024), max_retries;
            outlier_detection.consecutive_5xx + max_ejection_percent 50
app         Queue(maxsize=N), asyncio.Semaphore(N), one pool per dependency
sqlalchemy  pool_size, max_overflow, pool_timeout, pool_pre_ping
postgres    max_connections, statement_timeout, idle_in_transaction_session_timeout
```

---

## 5. Post-incident questions

1. What was the queue *time* when the first alert fired? If you cannot answer, the top fix
   is instrumentation, not capacity.
2. How long from trigger to the point of no return? (Measured: ~**7 s** from a 30% dip.)
3. Would the shed switch have worked? Prove it in a load test this week, not in the review.
4. Which queue was the bottleneck — and which one did you *assume* it was?
