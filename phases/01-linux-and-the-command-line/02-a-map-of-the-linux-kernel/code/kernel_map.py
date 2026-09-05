"""
A Map of the Linux Kernel — a tour of its five subsystems through /proc.

The kernel does not have a dashboard. It has /proc and /sys: filesystems that
live in RAM, where every read is the kernel answering a question about itself.
This script visits each subsystem's window in turn: the scheduler (who ran, how
often it was switched out), memory (what "free" really means, the page cache),
the virtual filesystem (mounts, this process's open files), the network stack
(interfaces, listening sockets decoded from hex), and the tunables in /proc/sys.
Self-terminating; on a non-Linux kernel it says what it cannot show.

Docs: phases/01-linux-and-the-command-line/02-a-map-of-the-linux-kernel/docs/en.md
Spec: Linux man-pages proc(5), sysctl(8); Documentation/filesystems/proc.rst in
      the kernel tree; Documentation/admin-guide/sysctl/

Run:
    python kernel_map.py
"""

import os
import socket
import struct
import sys
import tempfile
import time

LINUX = os.path.exists("/proc/self/status")


def banner(title):
    line = "=" * 72
    print(f"\n{line}\n{title}\n{line}")


def read(path, default=""):
    try:
        with open(path) as f:
            return f.read()
    except OSError:
        return default


def kv(path):
    """Parse 'Key:   value' files such as /proc/meminfo and /proc/self/status."""
    out = {}
    for line in read(path).splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            out[k.strip()] = v.strip()
    return out


def kib(s):
    return int(s.split()[0])  # "12345 kB" -> 12345


# ─── 0 · Which kernel ────────────────────────────────────────────────────────
banner("0 · The kernel and the machine")
u = os.uname()
print(f"kernel    : {u.sysname} {u.release} ({u.machine})")
print(f"cpus      : {os.cpu_count()} online")
if LINUX:
    print(f"/proc/version: {read('/proc/version').strip()[:80]}")
    up = float(read("/proc/uptime").split()[0])
    print(f"/proc/uptime : {up:.0f} s since boot ({up / 3600:.1f} h)")
else:
    print("no /proc on this kernel; the Linux-only windows below will say so. Run inside `make shell`.")

# ─── 1 · The scheduler ───────────────────────────────────────────────────────
banner("1 · Process management: the scheduler's view of this process")
try:
    l1, l5, l15 = os.getloadavg()
    print(f"load average : {l1:.2f} {l5:.2f} {l15:.2f}   (runnable + uninterruptible tasks, averaged over 1/5/15 min)")
except (OSError, AttributeError):
    pass

if LINUX:
    st = kv("/proc/self/status")
    print(f"/proc/self/status: State={st['State']}  Pid={st['Pid']}  PPid={st['PPid']}  Threads={st['Threads']}")
    before_v, before_nv = int(st["voluntary_ctxt_switches"]), int(st["nonvoluntary_ctxt_switches"])

    # Two kinds of leaving the CPU. Sleeping is voluntary: we asked the kernel
    # to park us. Being preempted at the timer tick is involuntary: the
    # scheduler decided someone else's turn had come.
    for _ in range(20):
        time.sleep(0.005)
    mid = kv("/proc/self/status")
    mid_v, mid_nv = int(mid["voluntary_ctxt_switches"]), int(mid["nonvoluntary_ctxt_switches"])
    print(f"after 20 x sleep(5 ms) : +{mid_v - before_v} voluntary, +{mid_nv - before_nv} involuntary switches")

    t_end = time.perf_counter() + 0.3
    x = 0
    while time.perf_counter() < t_end:
        x += 1  # burn CPU without ever asking the kernel for anything
    after = kv("/proc/self/status")
    after_v, after_nv = int(after["voluntary_ctxt_switches"]), int(after["nonvoluntary_ctxt_switches"])
    print(f"after 300 ms of pure CPU: +{after_v - mid_v} voluntary, +{after_nv - mid_nv} involuntary switches")
    print("   sleep() hands the CPU back on purpose; a busy loop is taken off it at the timer tick")

    fields = read("/proc/self/stat").rsplit(")", 1)[1].split()
    # fields after the comm: state is [0]; utime [11], stime [12] in clock ticks
    hz = os.sysconf("SC_CLK_TCK")
    print(f"/proc/self/stat  : state={fields[0]}  user={int(fields[11]) / hz:.2f}s  kernel={int(fields[12]) / hz:.2f}s  (CPU time so far, {hz} ticks/s)")
    sched = read("/proc/self/sched")
    if sched:
        for line in sched.splitlines():
            if line.startswith(("nr_switches", "se.sum_exec_runtime", "nr_involuntary")):
                print(f"/proc/self/sched : {line.strip()}")
else:
    print("(context-switch counters live in /proc/self/status: Linux only)")

# ─── 2 · Memory ──────────────────────────────────────────────────────────────
banner("2 · Memory management: what 'free' actually means")
if LINUX:
    m = kv("/proc/meminfo")
    total, free, avail = kib(m["MemTotal"]), kib(m["MemFree"]), kib(m["MemAvailable"])
    cached, buffers = kib(m["Cached"]), kib(m["Buffers"])
    print(f"MemTotal     {total / 1024:9.0f} MiB   all the RAM the kernel manages")
    print(f"MemFree      {free / 1024:9.0f} MiB   touched by nobody: this is the number that looks scary")
    print(f"Cached       {cached / 1024:9.0f} MiB   the page cache: file data kept in RAM, dropped the instant someone needs it")
    print(f"MemAvailable {avail / 1024:9.0f} MiB   what a new process could actually get: the number that matters")
    print(f"SwapTotal    {kib(m['SwapTotal']) / 1024:9.0f} MiB   disk the kernel can spill rarely-used pages to")

    # Watch the page cache grow: write 64 MiB, and the kernel keeps it in RAM.
    tmp = tempfile.mkdtemp(prefix="kernel-map-")
    path = os.path.join(tmp, "blob.bin")
    before = kib(kv("/proc/meminfo")["Cached"])
    with open(path, "wb") as f:
        f.write(os.urandom(64 * 1024 * 1024))
    after = kib(kv("/proc/meminfo")["Cached"])
    print(f"\nwrote a 64 MiB file: Cached went {before / 1024:.0f} MiB -> {after / 1024:.0f} MiB (+{(after - before) / 1024:.0f} MiB)")
    t0 = time.perf_counter()
    with open(path, "rb") as f:
        while f.read(1 << 20):
            pass
    t_cached = time.perf_counter() - t0
    print(f"read it back: {64 / t_cached:,.0f} MiB/s: it never went near the disk, it came from the page cache")
    os.unlink(path)
    os.rmdir(tmp)

    st = kv("/proc/self/status")
    print(f"\nthis process : VmSize={st['VmSize']} (address space reserved)  VmRSS={st['VmRSS']} (RAM actually resident)")
    maps = read("/proc/self/maps").splitlines()
    print(f"/proc/self/maps: {len(maps)} mapped regions (the code/data/heap/stack map from Foundations, plus every shared library)")
    for line in maps:
        if "[heap]" in line or "[stack]" in line:
            print(f"   {line.split()[0]:28} {line.split()[-1]}")
else:
    print("(/proc/meminfo is Linux only; on macOS the equivalent is `vm_stat` and `sysctl hw.memsize`)")

# ─── 3 · The virtual filesystem ──────────────────────────────────────────────
banner("3 · The VFS: one API, many filesystems, and this process's open files")
if LINUX:
    mounts = [line.split() for line in read("/proc/mounts").splitlines()]
    types = {}
    for _, mnt, fstype, *_ in mounts:
        types.setdefault(fstype, []).append(mnt)
    print(f"/proc/mounts: {len(mounts)} mounts, {len(types)} filesystem types")
    for fstype, mnts in sorted(types.items(), key=lambda t: -len(t[1]))[:8]:
        shown = ", ".join(mnts[:3]) + (" ..." if len(mnts) > 3 else "")
        print(f"   {fstype:10} {len(mnts):3}   {shown}")
    print("   proc, sysfs, tmpfs, cgroup2 are not on any disk; overlay is the container's layered root (Phase 11)")
else:
    print("(no /proc/mounts; `mount` shows the same table on macOS)")

fd_dir = "/proc/self/fd" if LINUX else "/dev/fd"
print(f"\n{fd_dir}: descriptors this process holds right now")
for name in sorted(os.listdir(fd_dir), key=int):
    try:
        target = os.readlink(os.path.join(fd_dir, name)) if LINUX else "(target not exposed on macOS)"
    except OSError:
        continue
    print(f"   fd {name:>2} -> {target}")
if LINUX:
    print(f"cwd -> {os.readlink('/proc/self/cwd')}     exe -> {os.readlink('/proc/self/exe')}")

# ─── 4 · The network stack ───────────────────────────────────────────────────
banner("4 · The network stack: interfaces and sockets, decoded from /proc/net")

# Open a listening socket so there is something to find.
srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
srv.bind(("127.0.0.1", 0))
srv.listen(8)
port = srv.getsockname()[1]
print(f"this script is now listening on 127.0.0.1:{port}; let's find it the way ss does")

if LINUX:
    for line in read("/proc/net/dev").splitlines()[2:]:
        iface, data = line.split(":", 1)
        nums = data.split()
        print(f"   {iface.strip():8} rx {int(nums[0]) / 1e6:9.2f} MB   tx {int(nums[8]) / 1e6:9.2f} MB")

    TCP_STATES = {"01": "ESTABLISHED", "06": "TIME_WAIT", "0A": "LISTEN"}
    def hexaddr(s):
        ip_hex, port_hex = s.split(":")
        ip = socket.inet_ntoa(struct.pack("<I", int(ip_hex, 16)))  # little-endian hex -> dotted quad
        return f"{ip}:{int(port_hex, 16)}"
    print("\n/proc/net/tcp, the table ss -tln reads (hex, little-endian, one row per socket):")
    for line in read("/proc/net/tcp").splitlines()[1:]:
        cols = line.split()
        local, remote, state = cols[1], cols[2], cols[3]
        if state == "0A":
            mark = "  <- ours" if hexaddr(local).endswith(f":{port}") else ""
            print(f"   raw {local:>14} state {state}  ->  {hexaddr(local):22} {TCP_STATES.get(state, state)}{mark}")
else:
    print("(/proc/net/tcp is Linux only; on macOS `netstat -an` or `lsof -iTCP -sTCP:LISTEN` show the same table)")
srv.close()

# ─── 5 · Tunables: /proc/sys ─────────────────────────────────────────────────
banner("5 · /proc/sys: the knobs, and the ones a backend engineer actually turns")
if LINUX:
    knobs = [
        ("net.core.somaxconn", "max length of a listen() backlog: full = new connections refused"),
        ("net.ipv4.ip_local_port_range", "ports a client may use: exhaust them and connect() fails"),
        ("net.ipv4.tcp_fin_timeout", "seconds a closed socket lingers"),
        ("fs.file-max", "system-wide open file limit"),
        ("fs.nr_open", "per-process ceiling for ulimit -n"),
        ("vm.swappiness", "how eagerly the kernel swaps (0-100)"),
        ("vm.overcommit_memory", "whether malloc may promise RAM that does not exist"),
        ("kernel.pid_max", "largest PID before numbers wrap"),
        ("kernel.hostname", "what uname -n reports"),
    ]
    for name, why in knobs:
        val = read("/proc/sys/" + name.replace(".", "/")).strip().replace("\t", " ")
        print(f"   {name:30} = {val:14}  {why}")
    print("   (sysctl -w name=value writes the same files; /etc/sysctl.d/ makes it survive a reboot)")
else:
    print("(macOS has `sysctl -a` with different names; the Linux tree lives in /proc/sys)")

print("\nEvery number above came from a file that is not on disk. The kernel wrote it as you asked.")
