"""
Reading the Machine — uptime, vmstat, free, iostat and the descriptor
limit rebuilt from /proc, then a load generator so each number moves.

Every tool that tells you a machine is busy reads a counter from /proc,
waits, reads it again, and divides by the interval. This script does that
for the four resources a backend can run out of (CPU, memory, disk, file
descriptors), explains what each number means, then generates load of each
kind on purpose: CPU burners raise the load average and %us, an fsync loop
raises %wa and disk utilisation, a memory hog lowers MemAvailable, and an
open-file loop hits EMFILE at exactly the soft limit. Self-terminating; on
macOS the /proc parts explain what they cannot show.

Docs: phases/01-linux-and-the-command-line/12-reading-the-machine/docs/en.md
Spec: Linux man-pages proc(5) (/proc/stat, /proc/loadavg, /proc/meminfo,
      /proc/diskstats, /proc/vmstat), getrlimit(2); kernel Documentation/
      accounting/psi.rst (pressure stall information); vmstat(8), iostat(1)

Run:
    python machine.py
"""

import os
import resource
import sys
import tempfile
import time

LINUX = os.path.exists("/proc/stat")


def banner(title):
    line = "=" * 72
    print(f"\n{line}\n{title}\n{line}", flush=True)


def read(path):
    with open(path) as f:
        return f.read()


# ─── CPU: /proc/stat, sampled twice ──────────────────────────────────────────
def cpu_snapshot():
    """The 'cpu' line: user nice system idle iowait irq softirq steal, in ticks."""
    for line in read("/proc/stat").splitlines():
        if line.startswith("cpu "):
            return [int(x) for x in line.split()[1:9]]


def cpu_percentages(a, b):
    d = [y - x for x, y in zip(a, b)]
    total = sum(d) or 1
    names = ["us", "ni", "sy", "id", "wa", "hi", "si", "st"]
    return {n: 100.0 * v / total for n, v in zip(names, d)}


def stat_counter(name):
    for line in read("/proc/stat").splitlines():
        if line.startswith(name + " "):
            return int(line.split()[1])
    return 0


def vmstat(interval=1.0):
    """vmstat's line: procs r/b, memory, swap in/out, io in/out, cs, and the CPU split."""
    a = cpu_snapshot(); cs_a = stat_counter("ctxt"); vm_a = vm_counters(); t0 = time.time()
    time.sleep(interval)
    b = cpu_snapshot(); cs_b = stat_counter("ctxt"); vm_b = vm_counters(); dt = time.time() - t0
    pct = cpu_percentages(a, b)
    r = stat_counter("procs_running"); blocked = stat_counter("procs_blocked")
    return {
        "r": r, "b": blocked,
        "si": (vm_b["pswpin"] - vm_a["pswpin"]) / dt, "so": (vm_b["pswpout"] - vm_a["pswpout"]) / dt,
        "bi": (vm_b["pgpgin"] - vm_a["pgpgin"]) / dt, "bo": (vm_b["pgpgout"] - vm_a["pgpgout"]) / dt,
        "cs": (cs_b - cs_a) / dt, **pct,
    }


def vm_counters():
    out = {}
    for line in read("/proc/vmstat").splitlines():
        k, v = line.split()
        if k in ("pswpin", "pswpout", "pgpgin", "pgpgout"):
            out[k] = int(v)
    return out


# ─── memory: /proc/meminfo ───────────────────────────────────────────────────
def meminfo():
    out = {}
    for line in read("/proc/meminfo").splitlines():
        k, v = line.split(":")
        out[k] = int(v.split()[0])          # kB
    return out


# ─── disk: /proc/diskstats, sampled twice ────────────────────────────────────
def diskstats():
    """Per device: reads completed, sectors read, writes completed, sectors written, ms in I/O."""
    out = {}
    for line in read("/proc/diskstats").splitlines():
        f = line.split()
        name = f[2]
        if name.startswith(("loop", "ram", "nbd")) or (name[-1].isdigit() and name[:-1] in out):
            continue                                   # skip partitions and pseudo devices
        out[name] = {"r": int(f[3]), "rsec": int(f[5]), "w": int(f[7]), "wsec": int(f[9]), "io_ms": int(f[12])}
    return out


def iostat(interval=1.0):
    a = diskstats(); t0 = time.time()
    time.sleep(interval)
    b = diskstats(); dt = time.time() - t0
    rows = []
    for dev in b:
        if dev not in a:
            continue
        x, y = a[dev], b[dev]
        rows.append((dev, (y["r"] - x["r"]) / dt, (y["w"] - x["w"]) / dt,
                     (y["rsec"] - x["rsec"]) * 512 / dt / 2**20, (y["wsec"] - x["wsec"]) * 512 / dt / 2**20,
                     100.0 * (y["io_ms"] - x["io_ms"]) / (dt * 1000)))
    return rows


def pressure():
    """PSI: the share of time some task was stalled waiting for each resource (kernel 4.20+)."""
    out = {}
    for res in ("cpu", "memory", "io"):
        p = f"/proc/pressure/{res}"
        if os.path.exists(p):
            some = read(p).splitlines()[0]
            out[res] = float(some.split()[1].split("=")[1])   # avg10
    return out


if __name__ == "__main__":
    ncpu = os.cpu_count()
    banner(f"1 · Load average: how many tasks want a CPU (or a disk), against {ncpu} CPUs")
    l1, l5, l15 = os.getloadavg()
    print(f"   load average {l1:.2f} {l5:.2f} {l15:.2f}   ->   {l1 / ncpu * 100:.0f}% of {ncpu} CPUs 'wanted' over the last minute")
    print("   rule: load / CPUs. Under 1.0 there is idle capacity; over 1.0 tasks are queueing. Tasks in state D count too, so a disk stall raises it")
    if not LINUX:
        print("   (the rest of this script reads /proc; on macOS it explains each section and moves on. Run it inside `make shell`.)")

    banner("2 · vmstat: the CPU split, the run queue, swap and I/O, sampled over one second")
    if LINUX:
        v = vmstat()
        print(f"   r {v['r']:>3}  b {v['b']:>3}   si {v['si']:6.0f} so {v['so']:6.0f}   bi {v['bi']:8.0f} bo {v['bo']:8.0f} KiB/s   cs {v['cs']:8.0f}/s   "
              f"us {v['us']:4.1f} sy {v['sy']:4.1f} id {v['id']:4.1f} wa {v['wa']:4.1f} st {v['st']:4.1f}")
        print("   r: runnable tasks (compare with CPUs) · b: blocked on I/O · si/so: swap in/out (non-zero for long = thrashing)")
        print("   us: your code · sy: the kernel (syscalls, lesson 01) · id: idle · wa: idle BECAUSE waiting for disk · st: stolen by the hypervisor")
    else:
        print("   /proc/stat is the source; sample twice and divide. macOS: `vm_stat 1` and `top -l 2`")

    banner("3 · free: what 'free' means, and the one number that matters")
    if LINUX:
        m = meminfo()
        print(f"   MemTotal {m['MemTotal'] / 1024:8.0f} MiB   MemFree {m['MemFree'] / 1024:8.0f}   Cached {m['Cached'] / 1024:8.0f}   MemAvailable {m['MemAvailable'] / 1024:8.0f}   "
              f"SwapUsed {(m['SwapTotal'] - m['SwapFree']) / 1024:6.0f}")
        print("   MemAvailable is what a new process could get (free + reclaimable cache). Watch it, not MemFree (lesson 02)")
        dirty = m.get("Dirty", 0); print(f"   Dirty {dirty / 1024:.0f} MiB: written to the page cache but not yet to disk; a crash loses it, fsync forces it")
    else:
        print("   /proc/meminfo is the source. macOS: `vm_stat` and Activity Monitor's 'memory pressure'")

    banner("4 · iostat: requests per second, MiB/s and % utilisation per disk, sampled over one second")
    if LINUX:
        rows = iostat()
        print(f"   {'device':10} {'r/s':>7} {'w/s':>7} {'rMiB/s':>8} {'wMiB/s':>8} {'util%':>6}")
        for dev, r, w, rmb, wmb, util in rows[:6]:
            print(f"   {dev:10} {r:7.0f} {w:7.0f} {rmb:8.1f} {wmb:8.1f} {util:6.1f}")
        print("   util% near 100 with a small queue is a saturated disk; the wa column above is the CPU side of the same fact")
    else:
        print("   /proc/diskstats is the source. macOS: `iostat -w 1`")

    banner("5 · Pressure stall information: how much of the last 10 s SOMEONE waited for each resource")
    if LINUX and pressure():
        for res, avg in pressure().items():
            print(f"   /proc/pressure/{res:<7} some avg10 = {avg:5.2f}%")
        print("   one number per resource, comparable across machines; the modern replacement for reading load average")
    else:
        print("   /proc/pressure/{cpu,memory,io}: kernel 4.20+. Not available here.")

    banner("6 · File descriptors: the limit every server hits once")
    soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
    print(f"   this process: soft limit {soft}, hard limit {hard} (ulimit -n / LimitNOFILE=)")
    if LINUX:
        used, _, mx = read("/proc/sys/fs/file-nr").split()
        print(f"   system-wide: {used} open of a maximum {mx} (/proc/sys/fs/file-nr)")
    fd_dir = "/proc/self/fd" if LINUX else "/dev/fd"
    print(f"   descriptors held right now: {len(os.listdir(fd_dir))}")
    resource.setrlimit(resource.RLIMIT_NOFILE, (min(soft, 256), hard))    # lower the soft limit so the leak bites quickly
    opened = []
    try:
        while True:
            opened.append(os.open(os.devnull, os.O_RDONLY))
    except OSError as e:
        print(f"   opened {len(opened)} more, then: errno {e.errno} {os.strerror(e.errno)}  <- EMFILE at the soft limit ({min(soft, 256)})")
    for fd in opened:
        os.close(fd)
    resource.setrlimit(resource.RLIMIT_NOFILE, (soft, hard))
    print("   a server that accepts a socket per client hits this at (limit - a few) concurrent connections: 'Too many open files'")

    if not LINUX:
        sys.exit(0)

    banner("7 · Make the numbers move: CPU burners, then an fsync loop, then a memory hog")
    burners = []
    for _ in range(ncpu):
        pid = os.fork()
        if pid == 0:
            t_end = time.time() + 3.0
            while time.time() < t_end:
                pass
            os._exit(0)
        burners.append(pid)
    time.sleep(1.0)
    v = vmstat()
    print(f"   {ncpu} CPU burners: r {v['r']:>2}  us {v['us']:4.1f}%  id {v['id']:4.1f}%   load now {os.getloadavg()[0]:.2f} (it lags: a 1-minute average needs a minute)")
    for pid in burners:
        os.waitpid(pid, 0)

    work = tempfile.mkdtemp(prefix="machine-")
    path = os.path.join(work, "fsync.bin")
    pid = os.fork()
    if pid == 0:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT, 0o644)
        t_end = time.time() + 2.5
        n = 0
        while time.time() < t_end:
            os.write(fd, b"x" * 65536); os.fsync(fd); n += 1      # each fsync waits for the disk
        os.close(fd); os._exit(0)
    time.sleep(0.6)
    v = vmstat(); rows = iostat()
    busiest = max(rows, key=lambda r: r[5]) if rows else None
    print(f"   an fsync loop: wa {v['wa']:4.1f}%  bo {v['bo']:6.0f} KiB/s  b {v['b']}" + (f"   {busiest[0]} util {busiest[5]:.0f}%  w/s {busiest[2]:.0f}" if busiest else ""))
    os.waitpid(pid, 0)
    os.unlink(path); os.rmdir(work)

    before = meminfo()["MemAvailable"]
    hog = bytearray(300 * 2**20)                                    # 300 MiB, touched so pages are really allocated
    for i in range(0, len(hog), 4096):
        hog[i] = 1
    after = meminfo()["MemAvailable"]
    rss = int([l for l in read("/proc/self/status").splitlines() if l.startswith("VmRSS")][0].split()[1]) // 1024
    print(f"   a 300 MiB hog: MemAvailable {before / 1024:.0f} -> {after / 1024:.0f} MiB (-{(before - after) / 1024:.0f}); this process RSS {rss} MiB")
    oom = read("/proc/self/oom_score").strip()
    print(f"   /proc/self/oom_score = {oom}: the kernel's ranking of who dies first if RAM runs out (bigger = sooner)")
    del hog
    print("\n   every line above was two reads of a /proc file and a subtraction. That is all top, vmstat, free and iostat do.")
