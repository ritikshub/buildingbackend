---
name: runbook-find-your-wall
description: Use this before any 'we need to scale out' decision, and before any instance-type change.
phase: 11
lesson: 01
---

# Runbook: Find Your Wall Before You Buy Machines

Use this before any "we need to scale out" decision, and before any instance-type
change. It takes about 30 minutes on one production box. The output is a filled-in
decision record at the bottom that a reviewer can argue with.

Rule: **you may not add capacity until every line of section 5 has a number in it.**

---

## 1. Pressure first (2 minutes)

Pressure Stall Information tells you how much time tasks spent *stalled* on a
resource. Utilization tells you a resource was busy. They are different questions
and only one of them predicts pain. Requires Linux >= 4.20.

```bash
cat /proc/pressure/cpu /proc/pressure/io /proc/pressure/memory
# per-container, cgroup v2:
cat /sys/fs/cgroup/<slice>/{cpu,io,memory}.pressure
```

| Field | Meaning |
|---|---|
| `some` | % of wall time at least one runnable task was stalled on this resource |
| `full` | % of wall time *every* task was stalled — the box made no progress at all |
| `avg10/60/300` | those percentages over 10 / 60 / 300 seconds |
| `total` | cumulative microseconds stalled; alert on the **rate of change** of this, not the averages, so a spike cannot hide between scrapes |

| Signal | Threshold | Read it as |
|---|---|---|
| `cpu some avg60` | > 10% | Runnable work is queueing for cores. Real, not yet urgent. |
| `cpu some avg60` | > 30% | CPU-bound now. Confirm with `vmstat` `r` column. |
| `io full avg60` | > 5% | The box regularly does nothing but wait on storage. Investigate today. |
| `io full avg60` | > 20% | This is your outage. Go to section 3. |
| `memory full avg60` | > 1% | Reclaim or swap is stalling everything. Treat as urgent — it degrades nonlinearly. |

`memory` pressure above zero on a box that is nowhere near its capacity limit
usually means page-cache thrash, not a leak. Check `vmstat` `si/so` before
concluding anything about your heap.

## 2. Identify the wall (10 minutes, under real traffic)

Run each and write the number down. Do not skip the ones you "already know".

```bash
vmstat 1 10
#   r  = runnable threads. r > (cores) sustained  -> CPU wall
#   b  = blocked on I/O.   b > 0 sustained        -> I/O wall
#   si/so = swap in/out.   non-zero               -> memory CAPACITY wall
#   wa = % waiting on I/O

iostat -x 1 10
#   %util   near 100        -> device saturated (note: meaningless on NVMe/SSD
#                              with deep queues; use await + aqu-sz instead)
#   await   ms per I/O; if it climbs while %util is flat -> queueing
#   aqu-sz  average queue depth; > 2-3 sustained -> the disk is the wall

sar -n DEV 1 10
#   rxkB/s + txkB/s vs your link rate:
#     1 GbE  =   125,000 kB/s      10 GbE =  1,250,000 kB/s
#     25 GbE = 3,125,000 kB/s
#   > 60% of line rate sustained -> NIC wall (and check for microbursts;
#   a 1-second average hides a 10 ms burst that filled the queue)

ss -s
ss -tan state time-wait | wc -l
#   large time-wait counts = connection churn, not load. Fix keep-alive first.
#   compare established count against `ulimit -n` and net.core.somaxconn

perf stat -a sleep 10
#   IPC (instructions per cycle):
#     > 1.5  -> genuinely CPU-bound, cores are executing
#     < 0.5  -> MEMORY BANDWIDTH bound; cores are stalled on cache misses.
#               Faster cores will not help. Data layout will.
#   cache-misses / instructions > 2%  -> confirm memory-bound

numactl --hardware          # multi-socket: bandwidth is per-socket
cat /sys/fs/cgroup/cpu.max  # are you even allowed the cores you counted?
```

### The four walls, and what each looks like

| Wall | Confirming signal | Scales with more cores? | First fix to try |
|---|---|---|---|
| CPU | `vmstat r` > cores, `perf` IPC > 1.5 | Yes, with one worker per core | Profile the hot path; more workers |
| Memory capacity | `si/so` non-zero, OOM kills, `memory.pressure` | No | Cut per-request/per-connection footprint |
| Memory bandwidth | IPC < 0.5, high cache-miss rate | **No** — one shared bus | Data layout, batching, fewer copies |
| Disk / durability | `iostat await` climbing, `io full` pressure | **No** — one device queue | Group commit, batching, fewer fsyncs |
| Syscall rate | `strace -c -f -p <pid>` counts | Mostly | Batch I/O; larger buffers; fewer small writes |
| NIC | `sar -n DEV` > 60% of line rate | **No** — one link | Compression, smaller payloads, fewer round trips |

## 3. Durability check (the most commonly missed wall)

An `fsync()` costs roughly a same-zone network round trip. Measured in this
lesson's sandbox: **503.87 us with fsync against 1.46 us buffered — 346x.**
One fsync per request caps a box at roughly **2,000 req/s** regardless of cores.

```bash
strace -c -f -p <pid> 2>&1 | grep -E 'fsync|fdatasync'   # count them
```

```sql
-- Postgres: amortise the flush across concurrent commits
SHOW commit_delay;        -- default 0; try 100-500 (microseconds)
SHOW commit_siblings;     -- default 5; only delay when this many txns are active
SHOW synchronous_commit;  -- 'off' trades a few hundred ms of committed data on
                          -- crash for throughput. NOT a corruption risk.
                          -- This is a product decision. Get it in writing.
SHOW wal_compression;
```

Decision table:

| Situation | Action |
|---|---|
| Every request fsyncs its own audit/event log | Batch to a group commit; this is usually 10x+ |
| A queue writes one message per fsync | Batch by count **and** time (e.g. 128 msgs or 5 ms) |
| Durability requirement is genuinely per-request | You have found a real wall. Price replication instead |
| Nobody can say what the durability requirement is | Stop. That is the actual finding — go and ask |

## 4. Efficiency check (before any purchase)

Five minutes of profiling on one box under real traffic. In this lesson, 10.5x
was sitting in code that reviewed cleanly. Look for these in order of measured
payoff, not in order of how interesting they are:

| Habit | Measured cost here | How to spot it |
|---|---|---|
| Defensive `deepcopy` / clone that is never mutated | **2.45x** | Profiler shows `deepcopy`/`clone` in the top 10 |
| Membership or lookup against a list instead of a set/dict | **3.66x** | `list.index`, `x in [...]`, rebuilt collections in loops |
| N+1 queries / per-item I/O | Often 10-100x | Query count scales with result count |
| Per-item serialization instead of batch | 2-5x | `json.dumps` called per row |
| Re-parsing, re-compiling, re-deriving constants in a loop | 1.5-5x | Anything expensive whose input never changes |
| Hoisting globals, string concat -> join | **1.17x** | The one people argue about. Do it last. |

Cross-check: **run the fixed and unfixed versions and assert the output is
byte-identical.** An optimisation that changes behaviour is not an optimisation.

## 5. The decision record — fill this in

Copy into the ticket. A reviewer should be able to disagree with any line.

```text
SERVICE:                                    DATE:                OWNER:

1. THE WALL
   Which resource saturates first?  ______________________________________
   Its measured ceiling:            ____________ (unit: ______ per second)
   Command that produced it:        ______________________________________
   Current load against it:         ____________  (____% of ceiling)

2. THE GAP
   Next-nearest wall:               ______________ at ____________ /s
   Ratio (next / binding):          ______x
   > If this ratio is > 3x, the box is mostly idle at its own ceiling.
   > A batching or caching change is probably worth more than a fleet.

3. THE PER-REQUEST BUDGET
   One request costs:  ______ syscalls, ______ fsyncs, ______ KiB memory
                       ______ KiB on the wire, ______ ms CPU
   Binding term:       ______________________________________________

4. THE EFFICIENCY CHECK
   Profiled on one box under real traffic?         [ ] yes  [ ] no
   Top 3 costs found:  1. ____________  2. ____________  3. ____________
   Estimated headroom from fixing them:  ______x
   Engineer-days to fix:                 ______
   Machines that headroom would remove:  ______

5. THE HONEST REASON (tick exactly one)
   [ ] 1. AVAILABILITY  — one box cannot meet our SLO of ______%.
          Measured single-box availability: ______%
          NOTE: this is a RELIABILITY project. Size and design it as one.
   [ ] 2. BLAST RADIUS  — we cannot deploy or fail safely on one box.
   [ ] 3. GEOGRAPHY     — users ______ km away need < ______ ms.
          Cross-region RTT is 70-150 ms and is not negotiable.
   [ ] 4. WE RAN OUT    — we exceeded the largest machine available.
          Largest instance considered: ____________ at ______ /s
          Our requirement:             ______ /s

   If none is ticked, the reason is "it felt slow". Do not proceed.

6. THE ARITHMETIC
   Target throughput:            ______ req/s
   Per-box capacity AFTER fixes: ______ req/s
   Machines needed:              ______   (target / per-box, rounded up)
   Plus headroom for peak+failure (see Lesson 12): ______
   Distribution costs accepted:  LB $____  cross-AZ $____  eng-days ____
```

## 6. Availability arithmetic (for reason 1)

```text
single machine at 99.9%                            8.8 h/year down
two replicas, failures independent      6.0 nines  31.5 s/year
two replicas, 1% common-mode            5.0 nines   5.8 min/year
two replicas, 10% common-mode           4.0 nines  53.0 min/year
three or four replicas, 10% common-mode 4.0 nines  ~52.6 min/year  <- no gain

serial chain, each service at 99.95%:
  N =  1     99.9500%     4.4 h/year
  N =  5     99.7502%    21.9 h/year
  N = 10     99.5011%    43.7 h/year
```

P(all N down) = `c * P(one down) + (1 - c) * P(one down)^N`, where `c` is the
fraction of failures that are common-mode.

**Checklist for actually earning the independence term:**

- [ ] Replicas in different availability zones (not just different hosts)
- [ ] Different power and network paths
- [ ] Config changes roll out to replicas at different times
- [ ] Deploys are staged, not simultaneous — a bad build must not reach all replicas
- [ ] No shared singleton in the request path (one cache, one lock service, one DB primary)
- [ ] Health checks can actually remove a replica (verified, not assumed)

Every unticked box pushes `c` up, and `c` is what your nines are really made of.

## 7. Stop conditions

Abandon the scale-out plan and go back to section 4 if any of these are true:

- The binding wall is more than 3x below the next wall.
- Nobody has profiled a single box under real traffic in the last month.
- The top profiler entry is an allocation, a copy, or a serialization call.
- The durability requirement that forces per-request `fsync` is undocumented.
- The honest reason in section 5 is availability, but the plan is written as a
  throughput project — it will be sized wrong and it will not deliver nines.
