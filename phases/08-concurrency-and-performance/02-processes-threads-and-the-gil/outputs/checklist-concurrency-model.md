---
name: checklist-concurrency-model
description: A decision checklist for picking processes, threads or async for a given workload — how to classify the work with a measurement rather than a guess, how to size the pool from CPUs you can actually use, the container CPU-limit and fork-plus-threads traps, and what to record before and after
phase: 8
lesson: 02
---

# Concurrency Model Checklist

Use this before you add `threading`, `multiprocessing`, or `asyncio` to a service — and again when
someone proposes changing the model of one that already ships. The wrong choice is not a small
inefficiency: threads on pure-Python CPU work give **1.00x**, and processes on chatty shared-state
work can be slower than the serial version they replaced. Both look like "we tried concurrency and
it didn't help". Ten minutes of measurement beats an afternoon of argument.

## Step 0 — Is concurrency the answer at all?

- [ ] You have a **measured** bottleneck, not a suspicion. You know the p50 and p99 of the slow
      operation and what fraction of total time it is.
- [ ] You have already tried the cheap wins: an index, a cache, a batched query, removing an N+1,
      not doing the work at all. Concurrency multiplies throughput; it never makes a unit faster.
- [ ] The downstream can take the extra load. Ten parallel workers against a database with a
      10-connection pool is a queue, not a speedup.
- [ ] You know your target — requests/second, or wall time for a batch job. Write it down now.

## Step 1 — Classify the workload (measure, do not guess)

Run **one unit of work** under a profiler or with coarse timers and answer: where did the time go?

- [ ] **I/O-bound** — mostly blocked on network, disk, or another service. Sockets, HTTP calls,
      database round trips, queue reads, file reads.
- [ ] **CPU-bound (bytecode)** — mostly executing *your Python*: loops, comprehensions,
      arithmetic, string and dict work, pure-Python parsing or serialisation.
- [ ] **CPU-bound (C)** — mostly inside a compiled extension: NumPy, Pandas, Polars, `hashlib`,
      `zlib`/`gzip`, image codecs, a driver's network layer, Cython/Numba/Rust kernels.
      **This behaves like I/O-bound**, because those libraries release the GIL.
- [ ] **Mixed** — write down the split (e.g. "30 ms DB, 20 ms JSON transform"). Mixed workloads
      get a mixed answer: threads or async for the waiting, a process pool for the computing.

Quick test if you are unsure whether a library releases the GIL: run the same total work on 1
thread and on 4. Scaling ≈ 1x means bytecode; scaling ≈ 3-4x means the GIL is released.

```bash
python -c "
import time, threading
W = 4
def run(n, fn, arg):
    ts=[threading.Thread(target=fn,args=(arg,)) for _ in range(n)]
    t0=time.perf_counter(); [t.start() for t in ts]; [t.join() for t in ts]
    return time.perf_counter()-t0
one, many = run(1, work, TOTAL), run(W, work, TOTAL//W)
print(f'{W} threads: {one/many:.2f}x  -> >2x means the GIL is released')"
```

## Step 2 — Choose the model

| Classification | Choose | Why |
|---|---|---|
| I/O-bound, up to ~a few hundred concurrent ops | **Threads** (`ThreadPoolExecutor`) | GIL released while blocked; no serialisation; ordinary blocking code |
| I/O-bound, thousands of concurrent connections | **asyncio** | ~KB per task instead of an 8 MiB stack reservation; no 20 us switch per wakeup |
| CPU-bound, pure Python | **Processes** (`ProcessPoolExecutor`) | Own interpreter, own GIL; real parallelism |
| CPU-bound, inside a C extension | **Threads** | The extension already releases the GIL |
| Isolation, crash containment, hard kill, memory cap | **Processes** | Only a separate address space gives you these |
| Mixed | **Both** | Threads/async for the waiting, a process pool for the computing |

- [ ] If you chose **processes**: your task function is importable at module level, and its
      arguments and return values are cheap to pickle. (A 200 MB DataFrame per task is not.)
- [ ] If you chose **threads**: you have read Step 5 and you know which state is shared.
- [ ] If you chose **asyncio**: every library on the hot path is async-native. One blocking
      driver call stalls the entire event loop — that is a different failure than a slow thread.
- [ ] You did **not** choose processes purely to "get around the GIL" without checking Step 1.

## Step 3 — Size the pool from CPUs you can actually use

`os.cpu_count()` reports the **host's** cores. In a container it is a lie, and sizing a pool from
it is the most common Python-in-Kubernetes performance bug.

- [ ] You read the **cgroup quota**, not the host core count. `/sys/fs/cgroup/cpu.max` (v2) or
      `cpu.cfs_quota_us` / `cpu.cfs_period_us` (v1). `len(os.sched_getaffinity(0))` catches
      cpuset pinning but **not** a quota; `os.process_cpu_count()` (3.13+) honours affinity and
      `PYTHON_CPU_COUNT` but is also blind to quota.
- [ ] Verify from inside the running container, not from the Dockerfile:
      `kubectl exec POD -- sh -c 'cat /sys/fs/cgroup/cpu.max; nproc; python -c "import os;print(os.cpu_count())"'`
- [ ] **Process pool** ≈ available CPUs (leave one for the main process on a busy box).
- [ ] **Thread pool for I/O**: start from `concurrency = target_rps x avg_latency_seconds`
      (Little's Law, lesson 01), then cap it at whatever the *downstream* can take —
      the database's `max_connections`, the API's rate limit — whichever is smaller.
- [ ] The pool size is **configurable at deploy time**, not a literal in the source.
- [ ] Total workers across *all* pools in the process is accounted for. Three pools of 32 on a
      2-CPU pod is 96 threads fighting over two cores.

## Step 4 — The traps that only show up in production

- [ ] **fork + threads.** Never `fork()` from a process that has already started threads: locks
      held by threads that do not exist in the child stay locked forever, and the child deadlocks
      on its first `malloc` or log line. Start threads *after* forking, or use
      `get_context("spawn")` / `get_context("forkserver")`.
- [ ] **Start method is explicit.** `fork` on Linux today, `spawn` on macOS/Windows,
      `forkserver` on Linux from 3.14. Set it in code so behaviour and startup cost do not change
      between your laptop, CI, and prod.
- [ ] **`if __name__ == "__main__":` guard** is present if any process may be spawned.
- [ ] **Every wait is bounded**: `join(timeout=...)`, `future.result(timeout=...)`,
      socket and HTTP timeouts on every call a worker makes.
- [ ] **Every future's result is inspected** inside `try`/`except`. An exception in a worker is
      stored on the future and re-raised only when read — an ignored future is a silent failure.
- [ ] **Threads cannot be killed.** There is no safe API. If a task may hang or run away, it must
      be a process (which you can `terminate()`), or it must poll a cancellation flag itself.
- [ ] **Pool startup is not on the request path** for spawn-based pools (36 ms per worker).
      Create the pool at boot; reuse it.
- [ ] **Background CPU work is not in the request process.** A busy background thread holds the
      GIL for up to a full switch interval (5 ms by default) at a time and inflates request tail
      latency — the convoy effect. Move it to a process before reaching for
      `sys.setswitchinterval()`.

## Step 5 — If you chose threads: what is shared?

- [ ] List every object two threads can touch. Everything on the heap is shared by default:
      module globals, class attributes, caches, connection objects, loggers, counters.
- [ ] Every shared mutable object is either **immutable**, **owned by exactly one thread**,
      **passed through a `queue.Queue`**, or **protected by a lock** (lessons 08-10).
- [ ] No design relies on an operation "being atomic because of the GIL". `counter += 1` is
      several bytecodes with a switch point between them — it is already a race, and on a
      free-threaded build (PEP 703) it fires routinely instead of rarely.
- [ ] Log `sys._is_gil_enabled()` at startup (guard with `getattr`, it exists from 3.13) so you
      always know which interpreter produced a bug report.

## Step 6 — Prove it, then keep proving it

- [ ] You measured **serial baseline** wall time before changing anything. Without it there is
      no speedup, only a number.
- [ ] You measured at **1, 2, 4, 8** workers with **total work held constant**, and took the
      best of at least 3 rounds (noise only ever makes a run slower).
- [ ] The speedup curve **flattens where you expect it to** — at available CPUs for processes,
      at the downstream's capacity for I/O. If it flattens at 1.0x, you have the wrong model for
      the workload; go back to Step 1.
- [ ] You checked **p99, not just throughput**. More concurrency almost always improves
      throughput and can quietly wreck tail latency through queueing and switching.
- [ ] You are watching in production: pool saturation (a gauge), queue depth, task duration
      (a histogram), rejected/timed-out tasks (a counter), and cgroup CPU throttling.

## Decision shortcut

> Time one unit of work first. If it was **waiting**, use threads — or asyncio past a few
> thousand concurrent operations. If it was **executing your Python**, use processes and size the
> pool from the cgroup quota, never `os.cpu_count()`. If it was inside **NumPy, hashlib, zlib or
> a driver**, use threads, because the GIL is already released there. If you need **isolation or
> the ability to kill it**, it is a process no matter what the profile says. Then measure the
> speedup curve at 1/2/4/8 workers — if it is flat at 1.0x, you chose wrong, and no amount of
> tuning will fix it.
