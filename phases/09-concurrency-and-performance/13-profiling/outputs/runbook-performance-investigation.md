# Runbook — "This endpoint is slow"

For the engineer who has just been handed a latency complaint. Work top to bottom — steps
1–3 are what stop you profiling the wrong thing with the wrong tool. **Rule zero: no code
changes until step 6 has a number in it.**

## 0 · Frame the complaint (2 min)

- [ ] **Which number moved** — p50, p95, p99, max? A p99-only regression is a tail problem
      (contention, GC, cold cache, one bad host); a p50 shift is everyone.
- [ ] **Since when?** Check the deploy timeline first — a step change at a deploy boundary
      is a bisect, not a profiling problem.
- [ ] **Where does it reproduce?** If only in production, every profile must come from
      production — a laptop has no network, no real dataset, no concurrency.
- [ ] **Write the target**: "p99 900 ms → under 400 ms." No target, no stopping condition.

## 1 · Localize the resource with USE, before any profiler

Check **U**tilization, **S**aturation, **E**rrors per resource. Saturation leads: utilization pins at 100% and goes quiet while the queue keeps growing.

| Resource | Utilization | Saturation (the one that matters) |
|---|---|---|
| CPU | `top`, `mpstat 1` | run-queue: `vmstat 1` (column `r`); container `nr_throttled` |
| Memory | RSS vs limit | swap-in rate, OOM kills (`vmstat 1`, `si`/`so`) |
| Disk | `iostat -xz 1` `%util` | `aqu-sz`, `await` |
| Network | throughput | retransmits: `ss -ti`, `netstat -s` |
| **DB pool** | in-use / size | **wait-queue depth, checkout time** |
| **Thread pool** | busy workers | queued tasks, task age |
| **Event loop** | — | **loop lag p99** |

The bottom three rows are where backend engineers actually find it: a pool at 100% with a
growing wait queue **is the answer**, and no code profiler would have said so.

## 2 · Decide: CPU-bound, or waiting?

```bash
/usr/bin/time -v <cmd>     # "User time" + "System time"  vs  "Elapsed"
pidstat -p <PID> 1         # live %CPU
```

- [ ] `CPU time / wall time` **≫ 0.5** → CPU-bound. Use an **on-CPU** profiler.
- [ ] `CPU time / wall time` **≪ 0.5** → waiting. Use a **wall-clock / off-CPU**
      profiler. **This is the common case for backend latency.**

> Getting this backwards is the most common profiling mistake there is. An on-CPU profiler
> is blind to waiting *by definition* (`ITIMER_PROF` counts down in CPU time, so a blocked
> process is never sampled). Measured: it reported a wait worth **55.9% of the request** as
> **0.0% of 1,476 samples**, and the missing share inflated an unrelated loop to **59.5%**.

## 3 · If it is an async service, do this instead

- [ ] **Measure event-loop lag first** (schedule every 5 ms, record the actual delay); p99
      lag above ~50 ms means something is blocking the loop. Then `PYTHONASYNCIODEBUG=1` or
      `loop.set_debug(True); loop.slow_callback_duration = 0.1` on a canary, which logs the
      offending callback with its stack.
- [ ] **Prefer traces to stacks.** A suspended coroutine has no frames, so its time is
      unsamplable: a stack profiler accounted for only **150 ms of 1,202 ms (12%)** of
      request time here. Spans at logical boundaries capture what stacks cannot.

## 4 · Capture a profile, safely

**Live process — no restart, no code change. The default:**

```bash
py-spy record -o flame.svg --pid <PID> --duration 60 --idle   # --idle INCLUDES off-CPU <- latency
py-spy record -o before.folded -f raw --pid <PID> --duration 60   # KEEP this file
py-spy top  --pid <PID>       # live, interactive
py-spy dump --pid <PID>       # every thread's stack — works on a HUNG process
```

- [ ] `--idle` is on if you are chasing latency — without it you get the blind profiler.
      Needs `SYS_PTRACE` (`docker run --cap-add SYS_PTRACE`; k8s `securityContext.capabilities`).
- [ ] Profile an instance under **real traffic** and **save the raw folded stacks** — no
      before-profile, no differential flame graph later.

**Local, reproducible — when you need exact call counts:**

```bash
python -m cProfile -o out.prof -s cumulative script.py
python -m pstats out.prof     # sort tottime | stats 25 | callers <fn> | callees <fn>
```

cProfile taxes **calls**: it inflated a 50,000-call component **+27.7%** while leaving a
1-call component at **−0.0%**, and took a one-line function from **46 ns to 190 ns (4.2x)**.
Never use its timings to choose between call-heavy and compute-heavy code.

**Memory — the diff, never a single snapshot:**

```python
tracemalloc.start(25); snap1 = tracemalloc.take_snapshot()
...                                            # run several FULL cycles
for s in tracemalloc.take_snapshot().compare_to(snap1, "lineno")[:10]: print(s)
print(tracemalloc.get_traced_memory())         # (current, peak)
```

`peak` ≫ `current` **with a near-zero diff = a high-water mark, not a leak.** Fix with
streaming or pagination, not leak-hunting.

## 5 · Read it without the classic misreadings

- [ ] **Never sort by cumulative and pick the top** — `main` is always 100%; it called
      everything. Cumulative is for following a chain *downward*.
- [ ] **Never sort by self time and stop** — it misses N+1s (50,000 × 4.79 µs looks
      unremarkable per call). **Scan `ncalls` first.**
- [ ] **Hunt plateaus**: wide boxes with nothing above them. Width is the share of samples;
      **the x-axis is not time**.
- [ ] **Use the caller/callee view** (`print_callers`) — the hot utility is rarely the bug;
      the caller invoking it 50,000 times is.
- [ ] If the profile's total does not resemble the duration you set out to explain, you are
      holding the wrong profiler. Go back to step 2.

## 6 · Compute Amdahl's ceiling — the gate

```text
speedup = 1 / ((1 - f) + f/k)      f = the component's fraction of runtime
ceiling = 1 / (1 - f)              k = infinity: the most it can EVER be worth
```

- [ ] Put **f**, the **ceiling**, and **ms saved at k=∞** in the ticket.
- [ ] **f < 10% → walk away unless the fix is free.** f=2% caps you at 1.02x, forever.
      f=20% → 1.25x. f=50% → 2.00x. f=56% at merely k=10 → 2.01x. If nothing clears 10%,
      the answer is architectural — batch, cache, move it off the request path.

## 7 · Change one thing, with a prediction

- [ ] Write the hypothesis **with a predicted magnitude in ms** first: *"batching the 50,000
      lookups removes ~194 ms of 895 ms, p50 to ~700 ms."* A prediction that cannot be wrong
      is not a hypothesis. **One change per measurement** — two changes, one useless result.
- [ ] Re-measure with the **same tool, environment, load and duration**; diff the flame
      graphs, which also shows what got *slower*.
- [ ] **Gain smaller than run-to-run noise → revert, and say so.** 900 ms → 880 ms from one
      run is a sample, not a win. Keep the new profile as the next baseline.

## Fast triage

| Symptom | Most likely | First command |
|---|---|---|
| High CPU, p50 up | hot loop, bad algorithm, GC churn | `py-spy top --pid` |
| Low CPU, p99 up | downstream wait, pool exhaustion, lock | `py-spy record --idle` |
| p99 only, p50 flat | contention, cold cache, one bad host | per-instance histograms |
| Process hung | deadlock | `py-spy dump --pid` |
| Memory climbing forever | unbounded retention | `tracemalloc` snapshot **diff** |
| Memory high but flat | high-water mark | `current` vs `peak`; stream it |
| Async p99 up, flat graph | blocked event loop | loop-lag p99, `slow_callback_duration` |
| Fast locally, slow in prod | data volume, network, concurrency | profile **in production** |

**Escape hatches, before micro-optimizing:** batch N+1 calls into one round trip · add the
missing index (read the plan, not the ORM) · cache with an explicit TTL and an invalidation
story · move work onto a queue · parallelize independent waits (`asyncio.gather`) · stream
instead of materializing, so one request stops sizing the whole process.
