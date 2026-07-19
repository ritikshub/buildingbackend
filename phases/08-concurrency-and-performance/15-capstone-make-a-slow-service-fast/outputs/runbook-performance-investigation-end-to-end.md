# Runbook — Performance Investigation, End to End

Use this when someone hands you a service and says "make it faster". Work top to
bottom. Do not skip step 0, and do not skip the prediction in step 4 — those two
are what separate an investigation from three weeks of guessing.

Paste the tables into the ticket. The artefact of this work is not the speedup,
it is the **attribution**: which change bought what, and how you know.

---

## 0 · Define "fast" before you measure anything

- [ ] Write the SLO as one sentence with three numbers in it.
      `99% of requests complete in under ___ ms, at ___ req/s, with errors below ___%`
- [ ] Get a human outside engineering to agree to the latency number.
- [ ] Record today's **peak** offered rate, not the average. You size for peak.
- [ ] Decide what a *useful* response is (the deadline). That defines **goodput**.

> Without an SLO there is no finish line, and work expands until the quarter ends.

## 1 · Baseline you would defend in a review

- [ ] Measure **open loop**: arrivals on a fixed schedule, latency from the
      **intended** arrival time. Closed-loop tools (a fixed pool of clients each
      waiting for its own reply) suffer **coordinated omission** and under-report
      the tail by 10-100x. Confirm your tool: `wrk2`, `k6` with constant-arrival-rate,
      `vegeta -rate`, or Gatling's `constantUsersPerSec` — **not** `ab`, and not
      `wrk` without `-R`.
- [ ] Measure **at the edge** (load balancer / client), never inside the handler.
      A histogram started after `lock.acquire()` or `pool.get()` cannot see the
      queue in front of it.
- [ ] Record all six: **throughput · goodput · p50 · p99 · error rate · sample size**.
- [ ] State the sample size. Under ~150 samples your "p99" is the maximum observed.
- [ ] **Establish the noise floor**: run the identical build 3x and record the
      spread — and never claim better than ~3%, the floor for a wall clock on a
      machine you share with an operating system. Smaller than that is not a result.

```text
baseline    offered ___/s   thr ___/s   good ___/s   p50 ___ms   p99 ___ms   err ___%   n=___
noise floor 3 runs of the same build: ___ , ___ , ___  ->  ±___%
```

## 2 · Localise — profile, then count

- [ ] **Wall-clock profile**, not CPU profile. For an I/O-bound service they rank
      differently: in the reference investigation the hottest CPU function was
      **6.2% of the wall clock and 100% of the on-CPU samples**.
      Tools: `py-spy record --idle`, `async-profiler -e wall`, `perf sched`,
      or a continuous profiler (Pyroscope, Datadog, Cloud Profiler).
- [ ] Profile **under load** to find contention, and **one request at a time** to
      find the cost budget. They answer different questions; do both.
- [ ] **Count calls per request** — the number no percentage shows you. Span
      counts per trace, `pg_stat_statements.calls`, RPC client counters.
      A count > 1 where you expected 1 is an N+1.
- [ ] Check **USE** for every pool, queue and semaphore: utilisation, saturation
      (wait time), errors. Saturation moves minutes before user-facing latency.

## 3 · Compute the Amdahl ceiling for every candidate

`max speedup = 1 / (1 − p)` where `p` is that component's fraction of wall time.

| candidate | wall % | max speedup | effort | worth doing? |
|---|---|---|---|---|
| | | | | |

- [ ] Rule out the loud-but-small candidates **by arithmetic**, in writing. This
      ends the "I'm sure it's the parser" conversation without a fight.
- [ ] Recompute after every landed change — fixing one thing moves every other
      ceiling.

## 4 · The fix-one-thing loop

For each change, in this order:

1. [ ] **Predict the magnitude** from the ceiling. Write it in the ticket first.
2. [ ] **Change exactly one thing.** Behind a feature flag if you can.
3. [ ] **Re-measure identically** — same rate, same duration, same environment.
4. [ ] **Compare to the prediction.**
       Far under → you fixed something else. Far over → your baseline was wrong.
       Within the noise floor → **no result**, whatever the direction.
5. [ ] **Verify correctness** (step 6 below). Every time.
6. [ ] **Keep or revert**, and record the delta in the table.

```text
stage  change                      pred   thr/s  good/s  p50   p99   err%  correct  verdict
0      baseline                    --
1      ______________________      __x
2      ______________________      __x
```

## 5 · The standard fix catalogue, in the order to try them

Cheapest and largest first. Stop when you are inside the SLO with headroom.

1. **N+1 → batch.** Usually the biggest single win and invisible without a call
   count. `WHERE id IN (...)`, a DataLoader, a bulk endpoint.
   *Reference result: 2.03x, against a 2.43x ceiling.*
2. **Sequential → concurrent** for calls with no data dependency between them.
   `asyncio.gather`, `ThreadPoolExecutor`, `errgroup`. **This is the step that
   exposes latent races — go to step 6 before you celebrate.**
   *Reference result: 1.70x.*
3. **Lock scope.** Get I/O *out* from under every lock, shrink the critical
   section to the smallest set of instructions that preserve the invariant, then
   shard/stripe by key. Do not reach for a "faster lock".
   *Reference result: **12.2x capacity** — the largest win in the run, and it
   deleted no work at all.*
4. **Pool the connections**, sized from the measured curve. Sweep sizes, plot
   capacity and p99, find the knee. Little's Law: `connections = rate × hold_time`.
   Take a small multiple of that for bursts, and never exceed the dependency's
   own concurrency limit — a bigger pool moves your queue into their database.
   *Reference result: capacity unchanged, p50 −38%. Pooling buys latency.*
5. **Offload or shrink the CPU step.** First prove threads do not help (they will
   not, under a GIL or on a saturated core): quadrupling threads gave 515 → 519
   req/s and a 4.4x worse tail. Then process pool, a native library, a cache, or a
   cheaper algorithm — and account for the serialisation tax.
   *Reference result: 1.59x capacity, no change to p99 at the SLO rate. Headroom,
   not latency — say which one you bought.*
6. **Bound the queues and add deadlines** (see step 7). Not optional.

## 6 · Verify no correctness regression — every stage

Speed uncovers bugs that serialisation was hiding. Assume every concurrency
change re-tests every accidental invariant in the process at once.

- [ ] Name an **invariant** that must hold and assert it in the load test itself.
      (`counted_calls == actual_calls`, `sum(balances) == constant`,
      `rows_written == requests_completed`.)
- [ ] Grep the newly-concurrent path for **read-modify-write** on shared state:
      `x = x + 1`, `if k not in cache: cache[k] = load(k)`, `max()` accumulators,
      lazy singletons.
- [ ] Ask of every lock you kept: *which invariant does this defend?* If you
      cannot answer in one sentence, you do not know what it protects — you know
      what it currently happens to prevent.
- [ ] Run the race test with the window **deliberately widened** (`sleep(0)`,
      `sched_yield`, a debug hook) so the bug is punctual instead of quarterly.
      Widening does not create the bug.
- [ ] Compare business metrics before/after, not just latency. A 47% under-count
      on a counter passes every test and poisons every dashboard downstream.

## 7 · Prove it survives overload

- [ ] Measure capacity (saturating probe), then offer **3x** it and watch.
- [ ] Report **goodput**, not throughput. A collapsing service holds throughput
      near capacity while goodput goes to zero — 802/s throughput against 115/s
      goodput, at a **0.00% error rate**.
- [ ] Then add, and re-measure:
      - **bounded queue** — reject at the door when full;
      - **deadline at ingress**, propagated to every downstream call;
      - **deadline check at dequeue** — never start work whose deadline has passed;
      - **timeouts on every outbound call** (there is no default; the default is forever);
      - **retry budget + circuit breaker**, so retries cannot amplify the overload.
- [ ] Expect the **error rate to rise** and goodput to rise with it. That is the
      point. *Reference result: errors 0% → 60%, goodput 115/s → 801/s (6.9x),
      p99 1,565 ms → 160 ms.*

## 8 · When to stop

Stop when **any** of these is true. Write down which one.

- [ ] The next win is **smaller than the noise floor** (ours: 3%) — you cannot
      demonstrate it, defend it, or protect it in CI.
- [ ] The **Amdahl ceiling** on everything remaining is small (biggest component
      6% ⇒ at most 1.07x, which is what stopped us rewriting the scoring loop).
- [ ] You are **inside the SLO with headroom** above the knee of the latency curve.
- [ ] **Hardware is cheaper than engineering** for what is left. Optimise
      structural bugs that scale with your data (an N+1 gets worse forever); buy
      capacity for constant factors.
- [ ] The remaining work trades **correctness or clarity** for speed.

## 9 · Hold the line

- [ ] **Regression benchmark in CI** on the critical path, threshold set from the
      measured noise floor. A flaky benchmark gets disabled and then lies to you.
- [ ] **SLO + error budget** so "fast enough" is a shared decision, not an argument.
- [ ] **Saturation alerts** on every pool/queue/semaphore: utilisation > 80% for
      10 min → ticket, not page.
- [ ] **Deploy annotations** on every latency dashboard.
- [ ] **Keep the load test** that proved the win — it is what proves next quarter
      that the win is still there.
- [ ] Write the attribution into the ticket: what was kept, what was reverted,
      what turned out to be noise, and what the theory-everyone-had was worth.

---

### Reference results (the investigation this runbook was extracted from)

| stage | change | capacity req/s | p99 ms @ SLO rate | verdict |
|---|---|---|---|---|
| 0 | as inherited | 11.5 | 5,515 | baseline |
| 2 | batch the N+1 | 23.3 | 1,891 | 2.03x — kept |
| 3 | concurrent I/O | 40 | 54 | faster, **counter 47% wrong** |
| 3b | lock the counter | 40 | 84 | correctness free — kept |
| 4 | shrink + shard the lock | 484 | 39 | **12.2x** — kept |
| 5 | connection pool = 16 | 499 | 26 | latency, not capacity — kept |
| 6 | CPU → process pool | 794 | 27 | headroom, not latency — kept |
| 7 | workers 24 → 128 | 791 | 25 | flat + 5.8x worse tail — **reverted** |
| 8 | bounded queue + deadlines | 794 | 160 @ 3x load | goodput 6.9x — kept |

End to end: **11.5 → 40.1 req/s** served at the offered rate, **p99 5,515 → 27 ms**,
**capacity 11.5 → 794 req/s**. Three changes produced nearly all of it, one was
reverted, and one was a bug in disguise.
