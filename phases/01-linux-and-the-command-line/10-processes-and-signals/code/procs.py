"""
Processes & Signals — ps and pstree rebuilt from /proc, and every kind of
signal delivery demonstrated on children this script forks.

A process is a record in the kernel: a PID, a parent, a user, a state, an
exit status, and the /proc/<pid>/ directory that exposes all of it. `ps` is
that directory read and formatted; `pstree` is the PPid column followed.
A signal is one small integer delivered asynchronously by the kernel; what
happens next depends on whether the process installed a handler, ignores
it, or (for SIGKILL and SIGSTOP) is given no choice. This script shows the
graceful-shutdown handler every service needs, a child that ignores
SIGTERM and must be killed, the stop and continue signals, a zombie, an
orphan being adopted, and a child that survives its parent with setsid.
Self-terminating; on macOS the /proc parts use `ps` instead.

Docs: phases/01-linux-and-the-command-line/10-processes-and-signals/docs/en.md
Spec: POSIX.1-2017 signal.h, kill(), sigaction(), waitpid(), setsid();
      Linux man-pages signal(7), proc(5) (/proc/[pid]/status and stat),
      credentials(7), ps(1)

Run:
    python procs.py
"""

import os
import pwd
import signal
import subprocess
import sys
import time

LINUX = os.path.exists("/proc/self/status")


def banner(title):
    line = "=" * 72
    print(f"\n{line}\n{title}\n{line}", flush=True)


# ─── 1 · ps and pstree from /proc ────────────────────────────────────────────
def read_status(pid):
    """/proc/<pid>/status: Name, State, PPid, Uid, VmRSS, Threads ... as a dict."""
    out = {}
    try:
        with open(f"/proc/{pid}/status") as f:
            for line in f:
                k, _, v = line.partition(":")
                out[k] = v.strip()
    except OSError:
        return None
    return out


def cmdline(pid):
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as f:
            raw = f.read()
    except OSError:
        return ""
    return raw.replace(b"\0", b" ").decode(errors="replace").strip() or f"[{read_status(pid)['Name']}]"


def cpu_ticks(pid):
    """utime + stime from /proc/<pid>/stat, in clock ticks."""
    with open(f"/proc/{pid}/stat") as f:
        fields = f.read().rsplit(")", 1)[1].split()
    return int(fields[11]) + int(fields[12])


def ps():
    """ps -eo pid,ppid,user,stat,%cpu,rss,cmd  from /proc, with %cpu over a 0.2 s sample."""
    pids = sorted(int(p) for p in os.listdir("/proc") if p.isdigit())
    before = {}
    for pid in pids:
        try:
            before[pid] = cpu_ticks(pid)
        except OSError:
            pass
    time.sleep(0.2)
    hz = os.sysconf("SC_CLK_TCK")
    rows = []
    for pid in pids:
        st = read_status(pid)
        if not st:
            continue
        try:
            cpu = (cpu_ticks(pid) - before.get(pid, 0)) / hz / 0.2 * 100
        except OSError:
            cpu = 0.0
        uid = int(st["Uid"].split()[0])
        try:
            user = pwd.getpwuid(uid).pw_name
        except KeyError:
            user = str(uid)
        rss = st.get("VmRSS", "0 kB").split()[0]
        rows.append((pid, int(st["PPid"]), user, st["State"].split()[0], cpu, int(rss), cmdline(pid)))
    return rows


def pstree(rows):
    children = {}
    for r in rows:
        children.setdefault(r[1], []).append(r)
    def walk(pid, depth):
        for r in children.get(pid, []):
            print("   " + "  " * depth + f"{r[0]:>6} {r[3]:<2} {r[6][:60]}")
            walk(r[0], depth + 1)
    roots = [r for r in rows if r[1] not in {x[0] for x in rows}]
    for r in roots:
        print("   " + f"{r[0]:>6} {r[3]:<2} {r[6][:60]}")
        walk(r[0], 1)


def state_of(pid):
    """One letter: R, S, D, Z, T. From /proc on Linux, from ps on macOS."""
    if LINUX:
        st = read_status(pid)
        return st["State"].split()[0] if st else "?"
    out = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True).stdout.strip()
    return out[:1] if out else "?"


def ppid_of(pid):
    if LINUX:
        st = read_status(pid)
        return int(st["PPid"]) if st else -1
    out = subprocess.run(["ps", "-o", "ppid=", "-p", str(pid)], capture_output=True, text=True).stdout.strip()
    return int(out) if out else -1


# ─── 2 · signals ─────────────────────────────────────────────────────────────
def graceful_child():
    """What a well-behaved server does: finish the request, clean up, exit 0 on SIGTERM."""
    stop = False
    def on_term(signum, frame):
        nonlocal stop
        print(f"      child {os.getpid()}: got SIGTERM, finishing the request in flight", flush=True)
        stop = True
    def on_hup(signum, frame):
        print(f"      child {os.getpid()}: got SIGHUP, reloading config (not exiting)", flush=True)
    def on_usr1(signum, frame):
        print(f"      child {os.getpid()}: got SIGUSR1, dumping stats: 3 requests served", flush=True)
    signal.signal(signal.SIGTERM, on_term)
    signal.signal(signal.SIGHUP, on_hup)
    signal.signal(signal.SIGUSR1, on_usr1)
    while not stop:
        time.sleep(0.05)                                    # "serving"; a sleep interrupted by a signal returns early
    print(f"      child {os.getpid()}: cleanup done, exiting 0", flush=True)
    os._exit(0)


def stubborn_child():
    """A process that ignores SIGTERM. Only SIGKILL ends it."""
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    while True:
        time.sleep(0.05)


def report(pid, label):
    _, status = os.waitpid(pid, 0)
    if os.WIFEXITED(status):
        print(f"   {label}: exited with status {os.WEXITSTATUS(status)}")
    elif os.WIFSIGNALED(status):
        sig = os.WTERMSIG(status)
        print(f"   {label}: killed by signal {sig} ({signal.Signals(sig).name}); a shell would report $? = {128 + sig}")


if __name__ == "__main__":
    banner("1 · ps from /proc: one directory per process, one file per fact")
    if LINUX:
        rows = ps()
        print(f"   {'PID':>6} {'PPID':>6} {'USER':<8} {'ST':<2} {'%CPU':>5} {'RSS kB':>8} CMD")
        for r in rows[:12]:
            print(f"   {r[0]:>6} {r[1]:>6} {r[2]:<8} {r[3]:<2} {r[4]:>5.1f} {r[5]:>8} {r[6][:50]}")
        print(f"   ({len(rows)} processes visible; every column came from /proc/<pid>/status, stat or cmdline)")
        print("\n   pstree: the same rows, following PPid:")
        pstree(rows)
    else:
        print("   (no /proc on macOS; `ps -eo pid,ppid,user,stat,%cpu,rss,command` reads the same facts through sysctl)")
        print("   " + subprocess.run(["ps", "-o", "pid,ppid,user,stat,%cpu,rss,command", "-p", str(os.getpid())], capture_output=True, text=True).stdout.replace("\n", "\n   "))

    banner("2 · SIGTERM to a process with a handler: graceful shutdown")
    pid = os.fork()
    if pid == 0:
        graceful_child()
    time.sleep(0.2)
    print(f"   parent: child {pid} is state {state_of(pid)} (S = sleeping, waiting in sleep())")
    os.kill(pid, signal.SIGHUP);  time.sleep(0.1)          # reload, not exit
    os.kill(pid, signal.SIGUSR1); time.sleep(0.1)          # a user-defined signal: whatever the program decides
    os.kill(pid, signal.SIGTERM)                           # please stop
    report(pid, "graceful child")
    print("   this is what `systemctl stop` and `docker stop` send first, and what a server must handle")

    banner("3 · SIGTERM to a process that ignores it, then SIGKILL")
    pid = os.fork()
    if pid == 0:
        stubborn_child()
    time.sleep(0.2)
    os.kill(pid, signal.SIGTERM)
    time.sleep(0.2)
    print(f"   after SIGTERM: child {pid} is still state {state_of(pid)}: it installed SIG_IGN, so the kernel dropped the signal")
    os.kill(pid, signal.SIGKILL)                           # cannot be caught, blocked or ignored
    report(pid, "stubborn child")
    print("   SIGKILL never reaches the program: the kernel ends it. No cleanup, no flush, no goodbye (lesson 07's lost buffer)")

    banner("4 · SIGSTOP and SIGCONT: pausing a process (Ctrl+Z, fg, bg)")
    pid = os.fork()
    if pid == 0:
        while True:
            time.sleep(0.05)
    time.sleep(0.1)
    os.kill(pid, signal.SIGSTOP); time.sleep(0.1)
    print(f"   after SIGSTOP: state {state_of(pid)} (T = stopped; it gets no CPU at all, like Ctrl+Z)")
    os.kill(pid, signal.SIGCONT); time.sleep(0.1)
    print(f"   after SIGCONT: state {state_of(pid)} (running again, like fg or bg)")
    os.kill(pid, signal.SIGKILL); report(pid, "paused child")

    banner("5 · A zombie: exited, but the parent has not called wait() yet")
    pid = os.fork()
    if pid == 0:
        os._exit(7)                                        # the child is gone immediately ...
    time.sleep(0.1)
    print(f"   child {pid} exited with 7; before the parent waits it is state {state_of(pid)} (Z = zombie: a PID and an exit status, nothing else)")
    if LINUX:
        st = read_status(pid)
        print(f"   /proc/{pid}/status says: State={st['State']}  VmRSS={st.get('VmRSS', 'gone')}  <- no memory, no files, just the record")
    _, status = os.waitpid(pid, 0)                         # ... the parent collects the status ...
    print(f"   parent called wait(): status {os.WEXITSTATUS(status)} collected; now /proc/{pid} exists? {os.path.exists(f'/proc/{pid}') if LINUX else 'n/a'}")
    print("   zombies cost one PID each. A parent that never waits (a buggy daemon) leaks PIDs until the box cannot fork")

    banner("6 · An orphan: the parent dies first, and init (or a subreaper) adopts the child")
    pid = os.fork()
    if pid == 0:                                           # the middle process
        grandchild = os.fork()
        if grandchild == 0:
            time.sleep(0.6)                                # the grandchild outlives its parent
            os._exit(0)
        print(f"      middle {os.getpid()}: forked grandchild {grandchild}, now exiting without waiting", flush=True)
        os._exit(0)
    time.sleep(0.1)
    os.waitpid(pid, 0)
    # find the grandchild: it printed its parent's pid; on Linux scan /proc for PPid == 1 with our name
    time.sleep(0.1)
    if LINUX:
        for p in os.listdir("/proc"):
            if p.isdigit():
                st = read_status(int(p))
                if st and st["PPid"] == "1" and "procs.py" in cmdline(int(p)) and int(p) != os.getpid():
                    print(f"   grandchild {p} now has PPid {st['PPid']}: adopted by PID 1, which will wait() for it so it never becomes a zombie")
                    break
        else:
            print("   (grandchild already finished, or PID 1 in this container is not visible)")
    else:
        print("   on macOS: `ps -o pid,ppid,command | grep procs.py` shows the grandchild with PPID 1 (launchd)")
    time.sleep(0.6)

    banner("7 · setsid: how nohup and daemons survive the terminal closing")
    pid = os.fork()
    if pid == 0:
        os.setsid()                                        # a new session: no controlling terminal, so no SIGHUP from it
        print(f"      daemon-style child {os.getpid()}: session id {os.getsid(0)}, parent will exit; I keep running", flush=True)
        time.sleep(0.4)
        print(f"      daemon-style child {os.getpid()}: still alive after the parent 'left'; exiting", flush=True)
        os._exit(0)
    time.sleep(0.1)
    print(f"   parent: child {pid} has its own session ({os.getsid(pid)} vs mine {os.getsid(0)}); `nohup cmd &` and systemd do this")
    time.sleep(0.6)
    try:
        os.waitpid(pid, 0)
    except ChildProcessError:
        pass

    banner("8 · The signal table, from the kernel")
    for name in ("SIGHUP", "SIGINT", "SIGQUIT", "SIGKILL", "SIGUSR1", "SIGSEGV", "SIGPIPE", "SIGALRM", "SIGTERM", "SIGCHLD", "SIGCONT", "SIGSTOP", "SIGTSTP"):
        sig = getattr(signal, name)
        catchable = name not in ("SIGKILL", "SIGSTOP")
        print(f"   {int(sig):>2} {name:<8} {'catchable' if catchable else 'NOT catchable':<14} exit 128+{int(sig)} = {128 + int(sig)}")
    print("   kill -l prints the same list; kill -TERM, kill -15 and kill with no flag are the same signal")
