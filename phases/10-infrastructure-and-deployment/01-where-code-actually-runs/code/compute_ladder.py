#!/usr/bin/env python3
"""Measure the compute ladder from inside one of its rungs.

Lesson: phases/10-infrastructure-and-deployment/01-where-code-actually-runs/docs/en.md
Sources: Linux kernel include/linux/proc_ns.h (initial namespace inode constants),
         Documentation/admin-guide/cgroup-v2.rst (cgroup v2 interface files),
         Documentation/scheduler/sched-bwc.rst (CFS bandwidth control / cpu.max).
Standard library only. Self-terminating, ~20 s. Timing rows are best-of-N so the
ratios are stable across runs; the absolute milliseconds move with host load.
"""

from __future__ import annotations

import math
import os
import subprocess
import sys
import threading
import time

# Compile-time initial-namespace inode numbers from include/linux/proc_ns.h.
# A process whose namespace inode equals one of these is in the *host's* original
# namespace of that type -- i.e. that namespace is NOT isolated for it.
INIT_INO = {
    "time": 0xEFFFFFFA,   # 4026531834
    "cgroup": 0xEFFFFFFB,  # 4026531835
    "pid": 0xEFFFFFFC,    # 4026531836
    "user": 0xEFFFFFFD,   # 4026531837
    "uts": 0xEFFFFFFE,    # 4026531838
    "ipc": 0xEFFFFFFF,    # 4026531839
}

NS_MEANING = {
    "mnt": "the filesystem tree: what / looks like",
    "pid": "the process table: who exists, and who is PID 1",
    "net": "interfaces, routes, ports: your own 0.0.0.0:8080",
    "ipc": "System V IPC and POSIX message queues",
    "uts": "hostname and domain name",
    "user": "uid/gid mapping: whether root here is root out there",
    "cgroup": "where the cgroup tree appears to be rooted",
    "time": "CLOCK_MONOTONIC and CLOCK_BOOTTIME offsets",
}

CG = "/sys/fs/cgroup"


def read(path: str, default: str = "") -> str:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return fh.read().strip()
    except OSError:
        return default


def rule(title: str) -> None:
    print("\n== %s ==" % title)


# --------------------------------------------------------------------------
# 1 - You are already in a container
# --------------------------------------------------------------------------
def section_isolation_proof() -> None:
    rule("1 · YOU ARE ALREADY IN A CONTAINER — HERE IS THE PROOF")
    print("  a namespace is just an inode. Two processes that see the same inode")
    print("  number share that namespace; a different number means a private view.")
    print("  %-8s %-14s %-9s %s" % ("NS", "INODE", "ISOLATED", "WHAT IT CONTROLS"))
    private = shared = 0
    for name in ("mnt", "pid", "net", "ipc", "uts", "user", "cgroup", "time"):
        link = "/proc/self/ns/%s" % name
        try:
            target = os.readlink(link)          # e.g. "pid:[4026533911]"
            ino = int(target.split("[")[1].rstrip("]"))
        except OSError:
            print("  %-8s %-14s %-9s %s" % (name, "unreadable", "?", NS_MEANING[name]))
            continue
        if name in INIT_INO:
            isolated = ino != INIT_INO[name]
            verdict = "private" if isolated else "SHARED"
        else:
            # mnt and net have no compile-time constant; they are allocated at boot.
            isolated = True
            verdict = "private*"
        if verdict == "SHARED":
            shared += 1
        else:
            private += 1
        print("  %-8s %-14d %-9s %s" % (name, ino, verdict, NS_MEANING[name]))
    print("  * mnt and net have no compile-time initial inode to compare against;")
    print("    every container runtime gives you both, so they are reported private.")
    print("  -> %d namespaces private to this process, %d shared with the host."
          % (private, shared))
    if read("/proc/self/ns/user").endswith("[%d]" % INIT_INO["user"]):
        print("  the SHARED one is 'user': there is no uid remapping here, so uid 0")
        print("  inside this container is uid 0 on the host kernel. That is why a")
        print("  container escape is a root escape, and why rootless runtimes exist.")

    print("\n  -- what the kernel says about your cgroup --")
    print("  /proc/self/cgroup       %s" % (read("/proc/self/cgroup") or "(missing)"))
    print("    '0::/' means cgroup v2 (a single unified hierarchy, controller id 0),")
    print("    and the path is '/' because a cgroup NAMESPACE hides the real path.")
    print("    On the host this same cgroup has a long /docker/<id> path.")

    mount_opts = "unknown"
    for line in read("/proc/self/mountinfo").splitlines():
        if " cgroup2 " in line:
            mount_opts = line.split(" - ")[0].split()[5]
            break
    print("  %s mounted %s" % (CG, mount_opts))
    if "ro" in mount_opts.split(","):
        print("    read-only: this process can READ its limits and cannot RAISE them.")
        print("    Whoever ran the container set them; you live inside them.")

    fields = [
        ("cgroup.controllers", "resource controllers enabled for you"),
        ("cpu.max", "CPU bandwidth: '<quota_us> <period_us>' or 'max'"),
        ("cpu.weight", "relative CPU share when everyone is busy (default 100)"),
        ("cpuset.cpus.effective", "which physical CPUs you may actually run on"),
        ("memory.max", "hard memory ceiling; exceeding it is an OOM kill"),
        ("memory.current", "bytes charged to you right now"),
        ("memory.high", "soft ceiling: throttle+reclaim instead of kill"),
        ("pids.max", "cap on processes+threads (a fork-bomb bound)"),
    ]
    print("\n  -- cgroup v2 interface files (%s) --" % CG)
    for fname, meaning in fields:
        val = read(os.path.join(CG, fname), "(absent)")
        if fname == "memory.current" and val.isdigit():
            val = "%s (%.1f MiB)" % (val, int(val) / 1048576)
        print("  %-24s %s" % (fname, val))
        print("  %-24s   %s" % ("", meaning))

    stat = dict(
        line.split(None, 1) for line in read(os.path.join(CG, "cpu.stat")).splitlines()
        if " " in line
    )
    print("  cpu.stat nr_throttled=%s throttled_usec=%s"
          % (stat.get("nr_throttled", "?"), stat.get("throttled_usec", "?")))
    print("    nr_throttled is THE container metric nobody graphs. Non-zero means")
    print("    the kernel stopped your runnable threads to enforce cpu.max.")

    memtotal_kb = 0
    for line in read("/proc/meminfo").splitlines():
        if line.startswith("MemTotal:"):
            memtotal_kb = int(line.split()[1])
            break
    mem_max = read(os.path.join(CG, "memory.max"))
    print("\n  /proc/meminfo MemTotal   %.2f GiB   <- the HOST's RAM, not yours"
          % (memtotal_kb / 1048576))
    print("  cgroup memory.max        %s" % mem_max)
    if mem_max == "max":
        print("    no limit set here, so both numbers agree today. In production they")
        print("    do not: /proc/meminfo is not namespaced, so a runtime that sizes a")
        print("    heap or a cache from it reads the host's RAM and gets OOM-killed.")


# --------------------------------------------------------------------------
# 2 - The CPU-count trap
# --------------------------------------------------------------------------
def parse_cpu_max(raw: str) -> tuple[float | None, int]:
    """Parse cgroup v2 cpu.max -> (effective CPUs or None if unlimited, period_us)."""
    parts = raw.split()
    if len(parts) != 2:
        return None, 100000
    quota, period = parts
    period_us = int(period)
    if quota == "max":
        return None, period_us
    return int(quota) / period_us, period_us


def burn(n: int) -> int:
    """Deterministic CPU-bound work: a fixed-length LCG walk. No I/O, no allocation."""
    x = 0
    for i in range(900_000):
        x = (x * 1103515245 + 12345 + i) & 0xFFFFFFFF
    return x


def run_pool(nworkers: int, ntasks: int) -> tuple[float, list[float], int]:
    import multiprocessing as mp

    ctx = mp.get_context("fork")
    pool = ctx.Pool(nworkers)
    try:
        pool.map(int, range(nworkers))          # warm: pay the fork cost up front
        rss = pool_rss(pool)
        t0 = time.perf_counter()
        arrivals = [time.perf_counter() - t0 for _ in pool.imap_unordered(burn, range(ntasks))]
        wall = time.perf_counter() - t0
    finally:
        pool.close()
        pool.join()
    arrivals.sort()
    return wall, arrivals, rss


def pool_rss(pool) -> int:
    total = 0
    for proc in getattr(pool, "_pool", []):
        for line in read("/proc/%d/status" % proc.pid).splitlines():
            if line.startswith("VmRSS:"):
                total += int(line.split()[1])
    return total


def section_cpu_trap() -> None:
    rule("2 · THE CPU-COUNT TRAP: WHAT THREE APIs REPORT, AND WHICH ONE IS TRUE")
    host = os.cpu_count() or 1
    affinity = len(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else host
    raw = read(os.path.join(CG, "cpu.max"), "max 100000")
    quota_cpus, period_us = parse_cpu_max(raw)

    print("  os.cpu_count()          %-11d the machine's CPUs. Never your limit."
          % host)
    print("  os.sched_getaffinity(0) %-11d CPUs you may be SCHEDULED on (cpuset)"
          % affinity)
    print("  /sys/fs/cgroup/cpu.max  %-11s the CFS bandwidth quota you are held to"
          % raw)
    if quota_cpus is None:
        print("    quota = 'max' -> no bandwidth limit is set in this sandbox.")
        effective = float(affinity)
        print("    so today the true budget is the cpuset: %.1f CPUs." % effective)
    else:
        effective = quota_cpus
        print("    %d us of CPU per %d us period -> %.2f effective CPUs."
              % (int(quota_cpus * period_us), period_us, quota_cpus))
    print("  every runtime's default pool size reads the FIRST line and ignores the rest.")

    # Impose a real limit we are permitted to impose. sched_setaffinity is exactly
    # what `docker run --cpuset-cpus=0,1` does: a hard restriction on which CPUs
    # this process and all its children may run on. os.cpu_count() will not notice.
    budget = 2
    original = set(os.sched_getaffinity(0))
    os.sched_setaffinity(0, set(sorted(original)[:budget]))
    print("\n  -- imposing a real limit: sched_setaffinity to %d CPUs --" % budget)
    print("  (identical to `docker run --cpuset-cpus=0,1`; inherited by every child)")
    print("  after the call: os.cpu_count()=%d  sched_getaffinity=%d  <- they now DISAGREE"
          % (os.cpu_count() or 0, len(os.sched_getaffinity(0))))

    ntasks, trials = 24, 5
    print("\n  identical work both times: %d tasks x 900k-iteration LCG walk, through a"
          % ntasks)
    print("  process pool. The ONLY difference is how the pool was sized. Each row is")
    print("  the BEST of %d trials: external load can only ever add time, so the" % trials)
    print("  minimum is the closest thing to an uncontended measurement.")
    print("  %-24s %8s %10s %11s %12s %11s"
          % ("pool sized from", "workers", "wall", "throughput", "1st result", "worker RSS"))
    results = {}
    try:
        for label, n in (("cgroup/cpuset budget", budget), ("os.cpu_count()", host)):
            runs = [run_pool(n, ntasks) for _ in range(trials)]
            runs.sort(key=lambda r: r[0])
            wall, arrivals, rss = runs[0]      # the least-contended trial, whole
            first = arrivals[0]                 # so every number below is ONE run
            results[label] = (wall, first, rss, n)
            print("  %-24s %8d %8.0fms %8.2f/s %10.0fms %9.1fMB"
                  % (label, n, wall * 1000, ntasks / wall, first * 1000, rss / 1024))
    finally:
        os.sched_setaffinity(0, original)

    right = results["cgroup/cpuset budget"]
    wrong = results["os.cpu_count()"]
    print("\n  oversubscription        %.1fx        %d workers sharing %d CPUs"
          % (wrong[3] / budget, wrong[3], budget))
    print("  throughput              %.2f/s -> %.2f/s   (%+.0f%%)"
          % (ntasks / right[0], ntasks / wrong[0], (right[0] / wrong[0] - 1) * 100))
    print("     Never better, usually slightly worse, and the exact figure moves with")
    print("     host load. That is the whole point: the CPUs are the CPUs. Five times")
    print("     the workers bought five times the context switching, five times the")
    print("     resident memory, and zero extra capacity.")
    print("  time to FIRST answer    %.0f ms -> %.0f ms   (%.1fx worse)"
          % (right[1] * 1000, wrong[1] * 1000, wrong[1] / right[1]))
    print("     The oversized pool returned NOTHING for %.0f ms. Every task ran ~%.0fx"
          % (wrong[1] * 1000, wrong[3] / budget))
    print("     slower so that all of them could finish at the same late moment.")
    print("  worker memory           %.1f MB -> %.1f MB  (%.1fx)"
          % (right[2] / 1024, wrong[2] / 1024, wrong[2] / max(right[2], 1)))
    print("     Exactly the oversubscription factor, and the one that OOM-kills you:")
    print("     under a memory.max this pool is the difference between running")
    print("     and being SIGKILLed by the kernel with no stack trace.")
    print("  -> you did not buy capacity. You bought a worse latency profile and %.1fx RAM."
          % (wrong[2] / max(right[2], 1)))

    # ---- the part we cannot measure here: CFS bandwidth throttling ----
    print("\n  -- MODEL (not a measurement): what cpu.max does that cpuset does not --")
    print("  cpu.max is a *bandwidth* limit, not a pinning limit. `docker run --cpus=%d`"
          % budget)
    print("  writes cpu.max = '%d %d': %d us of CPU time per %d us period."
          % (budget * period_us, period_us, budget * period_us, period_us))
    print("  With W runnable threads the cgroup burns its whole quota in quota/W wall")
    print("  time, and the kernel then freezes ALL of them until the period rolls over:")
    print("       burn_time = quota_us / W        stall = period_us - burn_time")
    print("  %-10s %14s %14s %14s" % ("threads W", "quota spent in", "then stalled", "added p99"))
    quota_us = budget * period_us
    for w in (budget, 4, 8, 10, 16, 32):
        burn_us = quota_us / w
        stall_us = max(0.0, period_us - burn_us)
        print("  %-10d %12.1f ms %12.1f ms %12.1f ms"
              % (w, burn_us / 1000, stall_us / 1000, stall_us / 1000))
    print("  at W = %d (= the quota) there is no stall at all. At W = 32 the cgroup is" % budget)
    print("  frozen for %.0f ms out of every %.0f ms period, and that %.0f ms lands on a"
          % ((period_us - quota_us / 32) / 1000, period_us / 1000,
             (period_us - quota_us / 32) / 1000))
    print("  request that was already halfway through being served. This is the")
    print("  mechanism behind 'our p99 is 100 ms and we cannot find the slow query'.")
    print("  It is invisible in CPU utilisation graphs and visible only in")
    print("  cpu.stat's nr_throttled / throttled_usec.")


# --------------------------------------------------------------------------
# 3 - Isolation cost and density
# --------------------------------------------------------------------------
MEM_SNIPPET = (
    "import sys\n"
    "d={}\n"
    "for line in open('/proc/self/smaps_rollup'):\n"
    "    k,_,v = line.partition(':')\n"
    "    if k in ('Rss','Pss'): d[k]=v.split()[0]\n"
    "sys.stdout.write('%s %s' % (d.get('Rss','0'), d.get('Pss','0')))\n"
)


def self_mem_kb() -> tuple[int, int]:
    """(Rss, Pss) in KiB. Pss divides each shared page by its number of sharers,
    so it is the honest *marginal* cost of one more isolate; Rss double-counts
    every copy-on-write page a forked child shares with its parent."""
    rss = pss = 0
    for line in read("/proc/self/smaps_rollup").splitlines():
        key, _, val = line.partition(":")
        if key == "Rss":
            rss = int(val.split()[0])
        elif key == "Pss":
            pss = int(val.split()[0])
    return rss, pss


def measure_thread(n: int) -> tuple[float, float]:
    gate = threading.Event()
    before = self_mem_kb()[0]
    live: list[threading.Thread] = []
    t0 = time.perf_counter()
    for _ in range(n):
        th = threading.Thread(target=gate.wait)
        th.start()
        live.append(th)
    elapsed = time.perf_counter() - t0
    after = self_mem_kb()[0]
    gate.set()
    for th in live:
        th.join()
    return elapsed / n, max(0.0, (after - before) / n)


def measure_fork(n: int) -> tuple[float, float]:
    total = 0.0
    pss_kb = 0.0
    for i in range(n):
        r, w = os.pipe()
        t0 = time.perf_counter()
        pid = os.fork()
        if pid == 0:
            os.close(r)
            try:
                os.write(w, ("%d %d" % self_mem_kb()).encode())
            finally:
                os._exit(0)
        os.close(w)
        payload = os.read(r, 32)
        os.close(r)
        os.waitpid(pid, 0)
        total += time.perf_counter() - t0
        if i == 0 and payload:
            pss_kb = float(payload.split()[1])
    return total / n, pss_kb


def measure_subprocess(n: int) -> tuple[float, float]:
    total = 0.0
    pss_kb = 0.0
    for i in range(n):
        t0 = time.perf_counter()
        out = subprocess.run([sys.executable, "-c", MEM_SNIPPET],
                             capture_output=True, check=True)
        total += time.perf_counter() - t0
        if i == 0 and out.stdout.split():
            pss_kb = float(out.stdout.split()[1])
    return total / n, pss_kb


def best_of(fn, n: int, trials: int = 3) -> tuple[float, float]:
    """Run a batch measurement `trials` times, keep the fastest batch whole.

    Creation cost is a *minimum* problem: contention from other tenants on the
    host can only ever add time. Taking the min of several batches is the closest
    this sandbox gets to an uncontended number, and it is what makes the ratios
    below stable across runs instead of swinging with the host's mood."""
    runs = [fn(n) for _ in range(trials)]
    runs.sort(key=lambda r: r[0])
    return runs[0]


def section_isolate_cost() -> None:
    rule("3 · THE COST OF A FRESH ISOLATE RISES BY AN ORDER OF MAGNITUDE PER RUNG")
    thread_s, thread_mem = best_of(measure_thread, 500)
    fork_s, fork_mem = best_of(measure_fork, 200)
    proc_s, proc_mem = best_of(measure_subprocess, 30)

    rows = [
        ("thread", thread_s, thread_mem, "address space, fds, kernel, interpreter"),
        ("fork() child", fork_s, fork_mem, "fds and kernel; pages are copy-on-write"),
        ("fresh interpreter", proc_s, proc_mem, "the kernel, and the binary's file pages"),
    ]
    print("  each row is the fastest of 3 batches of 500 / 200 / 30 creations,")
    print("  reported as a per-creation mean.")
    print("  memory is Pss (proportional set size): shared pages divided by the")
    print("  number of sharers, which is the honest marginal cost of one more isolate.")
    print("  %-20s %12s %12s  %s" % ("isolate", "create", "memory", "what it still SHARES"))
    for name, secs, mem, note in rows:
        print("  %-20s %10.3f ms %9.0f KB  %s" % (name, secs * 1000, mem, note))
    print("\n  measured step-ups in creation cost on this machine:")
    print("    thread -> fork()            %6.1fx slower" % (fork_s / thread_s))
    print("    fork() -> new interpreter   %6.1fx slower" % (proc_s / fork_s))
    print("    thread -> new interpreter   %6.1fx slower" % (proc_s / thread_s))
    print("  roughly one order of magnitude per rung, and the ladder does not stop here.")
    print("  memory: %.0f KB -> %.0f KB is %.0fx from a thread to a private address space."
          % (thread_mem, proc_mem, proc_mem / max(thread_mem, 1e-9)))
    print("  On memory alone that is ~%s threads or ~%d fresh interpreters per GiB."
          % ("{:,}".format(int(1048576 / max(thread_mem, 1e-9))),
             int(1048576 / max(proc_mem, 1e-9))))
    print("  (Note the fork child measures %.0f KB, MORE than a fresh interpreter's %.0f."
          % (fork_mem, proc_mem))
    print("   Pss charges it a share of its parent's already-grown heap. A fork's cost")
    print("   is a function of how fat the parent is; a fresh process inherits nothing.)")

    print("\n  -- the rungs above this, quoted not measured --")
    print("  A container start adds an image pull (if cold), namespace and cgroup")
    print("  setup, and a full process tree: tens to hundreds of ms.")
    print("  A VM boot adds firmware, a kernel, and a userland init sequence:")
    print("  seconds to tens of seconds for a general-purpose hypervisor. AWS")
    print("  publishes < 125 ms for a Firecracker microVM, which is the number to")
    print("  quote when someone says 'VMs are slow' -- a stripped VM is not.")
    print("  This script CANNOT measure either: creating a namespace needs")
    print("  CAP_SYS_ADMIN and booting a VM needs a hypervisor. Both are absent here.")
    try:
        import ctypes

        libc = ctypes.CDLL("libc.so.6", use_errno=True)
        rc = libc.unshare(0x00020000)      # CLONE_NEWNS
        err = ctypes.get_errno()
        if rc == 0:
            print("  proof: unshare(CLONE_NEWNS) SUCCEEDED -- this process has CAP_SYS_ADMIN.")
        else:
            print("  proof: unshare(CLONE_NEWNS) -> errno %d (%s)."
                  % (err, os.strerror(err)))
            print("  We are uid 0 inside this container and still cannot create a")
            print("  namespace, because the runtime dropped CAP_SYS_ADMIN. Root is not")
            print("  the same as capable -- and that gap is the entire reason a shared")
            print("  kernel is a boundary you should not trust with someone else's code.")
    except OSError:
        print("  (libc not loadable; skipping the unshare demonstration)")


# --------------------------------------------------------------------------
# 4 - The economics of idle
# --------------------------------------------------------------------------
# One realistic weekday, requests per second per hour (UTC). Diurnal, ~30x peak/trough.
DAILY_RPS = [
    120, 80, 55, 40, 38, 45, 90, 220, 480, 760, 980, 1120,
    1180, 1150, 1090, 1010, 940, 880, 820, 900, 1100, 780, 420, 220,
]

# Unit prices, stated so a reader can substitute their own.
VM_HOURLY = 0.0416          # USD per instance-hour, 2 vCPU / 4 GiB on-demand class
RPS_PER_INSTANCE = 200.0    # sustained req/s one instance serves at target load
HEADROOM = 1.25             # provision 25% above measured peak
FAAS_PER_REQ = 0.20 / 1e6   # USD per request
FAAS_PER_GB_S = 0.0000166667
FAAS_MEM_GB = 0.5
FAAS_SECONDS = 0.100        # billed duration per request


def section_economics() -> None:
    rule("4 · THE ECONOMICS OF IDLE (a model, with the prices printed)")
    peak = max(DAILY_RPS)
    trough = min(DAILY_RPS)
    total_req = sum(r * 3600 for r in DAILY_RPS)
    instances = math.ceil(peak * HEADROOM / RPS_PER_INSTANCE)
    capacity_req_day = instances * RPS_PER_INSTANCE * 86400

    print("  assumptions (substitute your own):")
    print("    provisioned  $%.4f per instance-hour, %d req/s per instance, %.0f%% headroom"
          % (VM_HOURLY, RPS_PER_INSTANCE, (HEADROOM - 1) * 100))
    print("    per-invocation  $%.2f per 1M requests + $%.7f per GB-second,"
          % (FAAS_PER_REQ * 1e6, FAAS_PER_GB_S))
    print("                    %.0f MB x %.0f ms billed per request"
          % (FAAS_MEM_GB * 1024, FAAS_SECONDS * 1000))
    print("  one weekday of real traffic: peak %d req/s, trough %d req/s (%.0fx), %s requests"
          % (peak, trough, peak / trough, "{:,}".format(total_req)))

    per_req = FAAS_PER_REQ + FAAS_PER_GB_S * FAAS_MEM_GB * FAAS_SECONDS
    always_on = instances * 24 * VM_HOURLY
    scale_to_zero = total_req * per_req
    utilisation = total_req / capacity_req_day

    print("\n  provisioned for peak: %d instances, always on" % instances)
    print("    capacity            %s requests/day" % "{:,}".format(int(capacity_req_day)))
    print("    delivered           %s requests/day" % "{:,}".format(total_req))
    print("    utilisation         %.1f%%  -> you paid for %.1f%% of nothing"
          % (utilisation * 100, (1 - utilisation) * 100))
    print("    cost                $%.2f/day   $%.0f/year" % (always_on, always_on * 365))
    print("  scale-to-zero, billed per invocation")
    print("    unit cost           $%.9f per request" % per_req)
    print("    cost                $%.2f/day   $%.0f/year" % (scale_to_zero, scale_to_zero * 365))
    cheaper = "scale-to-zero" if scale_to_zero < always_on else "always-on"
    print("    -> %s is cheaper today, by $%.2f/day ($%.0f/year)"
          % (cheaper, abs(always_on - scale_to_zero), abs(always_on - scale_to_zero) * 365))

    crossover = always_on / (per_req * capacity_req_day)
    print("\n  crossover: always-on wins once utilisation exceeds %.1f%%" % (crossover * 100))
    print("  (solve  instances x 24 x hourly  =  utilisation x capacity x per_request)")
    print("  %-14s %14s %14s %10s" % ("utilisation", "always-on/day", "per-invoke/day", "winner"))
    for util in sorted((0.01, 0.05, crossover, 0.10, 0.25, 0.50, 1.00)):
        faas = util * capacity_req_day * per_req
        mark = "always-on" if always_on < faas else "per-invoke"
        tag = "%.1f%%" % (util * 100)
        if abs(util - crossover) < 1e-9:
            tag += " <-"
            mark = "crossover"
        print("  %-14s %13.2f %14.2f %10s" % (tag, always_on, faas, mark))
    print("  this curve's own utilisation is %.1f%%, which is %s the crossover."
          % (utilisation * 100, "below" if utilisation < crossover else "above"))
    print("  Note what the model does NOT price: cold starts, the engineer-hours of")
    print("  operating each rung, egress, and the reserved/committed-use discount that")
    print("  moves the always-on line down by 30-60%. Substitute your own numbers.")


def main() -> None:
    t0 = time.perf_counter()
    section_isolation_proof()
    section_cpu_trap()
    section_isolate_cost()
    section_economics()
    print("\n  (total wall time %.1f s)" % (time.perf_counter() - t0))


if __name__ == "__main__":
    main()
