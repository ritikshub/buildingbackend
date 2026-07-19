---
name: checklist-choosing-and-sizing-a-runtime
description: Pick the rung your service runs on, then prove your process knows the limits it was actually given — the CPU quota, the memory ceiling, the AZ topology, and who patches the kernel.
phase: 10
lesson: 01
---

# Choosing and sizing a runtime — a pre-deploy checklist

Two jobs. **Part A** picks the rung. **Parts B-E** make sure the process you ship knows
what it was actually given, instead of what the machine happens to have.

Every item here exists because skipping it produced a real outage or a real invoice.

---

## A · Choosing the rung

Answer these before arguing about the technology. The right rung is the highest one whose
failure modes you can staff.

- [ ] **Who is on call, and how many of them?** Write the number down. A three-person team
      running its own cluster is a three-person team with a part-time platform job.
- [ ] **Average utilisation, not peak-to-trough ratio.** Compute
      `requests served per day / (instances x req-per-instance x 86400)`. Spikiness is the
      wrong test; the bill responds to the area under the curve.
- [ ] **Crossover computed with your own prices**, not a blog's:
      `always_on_per_day = instances x 24 x hourly` versus
      `utilisation x capacity_per_day x per_request`. Solve for the utilisation where they
      meet. For commodity prices this lands in the low single-digit percents.
- [ ] **Latency floor stated.** If a few hundred milliseconds of cold start is unacceptable
      on your p99, scale-to-zero is not available to you — and provisioned concurrency buys
      idle cost straight back.
- [ ] **State inventory written down**: local disk, long-lived connections, WebSockets,
      in-process caches you depend on, background loops that run after a response. Each one
      is a reason the serverless rung will fight you.
- [ ] **Compliance constraints checked first**, not last: data residency, dedicated tenancy,
      audit requirements. These rule out whole rungs before any technical argument starts.
- [ ] **Engineer-hours priced.** The single biggest cost every "which is cheaper" model
      omits, and the one that most often favours the higher rung.
- [ ] **A date to re-run this.** The answer changes when traffic moves by an order of
      magnitude. Put it in the calendar.

## B · The CPU budget your process actually has

- [ ] **Nothing sizes a pool from `os.cpu_count()`** (or `runtime.NumCPU()`,
      `availableProcessors()`, `nproc`, `multiprocessing.cpu_count()`). Grep for all of them.
- [ ] The startup path reads **`/sys/fs/cgroup/cpu.max`** (v2: `"<quota_us> <period_us>"`, or
      `max`), falling back to `cpu.cfs_quota_us` / `cpu.cfs_period_us` on cgroup v1.
- [ ] It also reads **`os.sched_getaffinity(0)`** — the cpuset is a separate limit from the
      bandwidth quota and either can be the binding one. Take the minimum.
- [ ] **Both numbers are logged at startup, on one line**, next to what `cpu_count()` said.
      When they disagree you want it in the logs of the deploy that introduced it.
- [ ] Runtime-specific container awareness verified, not assumed: JVM `UseContainerSupport`
      (on by default in modern JVMs), .NET reads cgroups, **Go's `GOMAXPROCS` still defaults
      to the machine's core count** unless you set it.
- [ ] Pool size ultimately comes from a **load test of your workload**, not from a core count.
      An I/O-bound pool and a CPU-bound pool want completely different numbers.
- [ ] Every *other* thread source is accounted for: the HTTP server's pool, the database
      driver's pool, the GC threads, the tracing exporter, the metrics scraper. They all
      count against the same quota.

## C · Limits, and how you will die

- [ ] **Both `requests` and `limits` are set on every container.** Requests decide where you
      land; limits decide how you die. Missing either is a decision you did not make.
- [ ] `limits` without `requests` is understood to mean requests **default to the limits**,
      quietly reserving your ceiling across the whole fleet.
- [ ] `requests` without `limits` is understood to mean you can burst into a neighbour's
      capacity — pleasant until they want it back and your latency collapses.
- [ ] **Memory limit set above measured peak RSS with real headroom.** A breach is an
      immediate SIGKILL: exit code 137, no traceback, no application log line. Check the
      kernel log and the container exit code, not your logs.
- [ ] Nothing sizes a heap, buffer pool or cache from **`/proc/meminfo`** — it is not
      namespaced and reports the *host's* RAM.
- [ ] `--memory-swap` set equal to `--memory` (or swap disabled) so a memory limit means a
      memory limit rather than a slow slide into disk.
- [ ] A **`pids.max`** is set where untrusted or fork-happy code runs. It is your fork-bomb
      bound.
- [ ] You know whether `/sys/fs/cgroup` is mounted read-only in your runtime (it usually is):
      you can read your limits and you cannot raise them.

## D · Seeing the throttling

- [ ] **`nr_throttled` / `throttled_usec` from `cpu.stat`** is scraped and graphed
      (`container_cpu_cfs_throttled_periods_total` in the common exporters).
- [ ] It is on the **same dashboard panel as your p99**, because that is the correlation you
      will need to see at 03:00.
- [ ] There is an alert on a sustained non-zero throttle rate. Unexplained tail latency in a
      CPU-limited container is throttling until proven otherwise.
- [ ] Someone on the team can state the arithmetic from memory: with W runnable threads and a
      quota of Q per period P, you burn the quota in `Q/W` and are frozen for the rest of `P`.
- [ ] Liveness and readiness probe timeouts are generous enough that a throttled process is
      not restarted **for being throttled** — an easy way to turn a latency problem into a
      crash loop.

## E · Topology and ownership

- [ ] **Replica count is not confused with redundancy.** Confirm the replicas are actually
      spread across at least two availability zones — check the placement, do not assume it.
- [ ] The **data layer's** cross-AZ failover has been **tested**, with a date. An untested
      failover is an assumption.
- [ ] Cross-AZ and cross-region data transfer costs are known and on someone's dashboard;
      a naive "spread everything everywhere" design can become your largest line item.
- [ ] The region-level failure story is **written down as a decision** — including "we accept
      it" — rather than discovered during an incident.
- [ ] **Who patches the kernel is named**, per environment. On a VM or your own cluster
      nodes: you, on a schedule you actually keep. On managed containers and serverless: the
      provider. "We run containers so the kernel is someone else's problem" is backwards.
- [ ] Node OS upgrades and image rebuilds have an owner and a cadence, not just a ticket.
- [ ] If untrusted or third-party code runs, it is on a rung with a **hardware** boundary
      (a VM or microVM), not a shared kernel — and `CAP_SYS_ADMIN` is dropped either way.

> ## Decision shortcut
>
> **"What is the smallest number that describes my slice, and does my process know it?"**
> CPU → `cpu.max` and the cpuset, whichever binds first. Memory → `memory.max`.
> Failure domain → the availability zone.
> If your process learned any of those from the machine instead of from its cgroup,
> you have the bug in this lesson, and it will not raise an exception.
