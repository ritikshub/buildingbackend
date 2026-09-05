"""
Boot, init & systemd — a service supervisor rebuilt from fork, exec, wait
and signals: the core of what systemd does for your backend.

A supervisor is a process that starts a child, keeps the child's output,
waits for it, and restarts it when it dies (with a backoff, and a limit so
a crash loop does not spin), and that stops it politely on request (TERM,
a grace period, then KILL). It also reaps every child it is left with,
which is what PID 1 must do. This file is that, driving two "units" whose
ExecStart is a small flaky server and a timer job, and printing a journal
the way journalctl would. Self-terminating; runs on macOS and Linux.

Docs: phases/01-linux-and-the-command-line/11-boot-init-and-systemd/docs/en.md
Spec: POSIX.1-2017 fork(), execve(), waitpid(), kill(), setsid(); the
      systemd.service(5) and systemd.timer(5) manual pages for the option
      names this file mirrors (Restart=, RestartSec=, StartLimitBurst=,
      TimeoutStopSec=, OnUnitActiveSec=)

Run:
    python supervisor.py
"""

import os
import signal
import sys
import textwrap
import time

# ─── the "unit files": the same option names systemd uses ────────────────────
UNITS = {
    "app.service": {
        "Description": "a flaky HTTP-ish server that crashes now and then",
        "ExecStart": [sys.executable, "-u", "-c", textwrap.dedent("""
            import os, random, signal, sys, time
            random.seed(int(sys.argv[1]) if len(sys.argv) > 1 else 0)
            stable = len(sys.argv) > 2 and sys.argv[2] == "stable"
            crash_at = 10**9 if stable else random.randint(1, 5)      # this many requests, then a bug
            def on_term(*_):
                print("app: SIGTERM, draining 1 request, bye"); sys.stdout.flush(); time.sleep(0.3); os._exit(0)
            signal.signal(signal.SIGTERM, on_term)
            print(f"app: listening (pid {os.getpid()})")
            for i in range(100):
                time.sleep(0.2)
                if i + 1 == crash_at:
                    print("app: unhandled exception in request handler"); sys.stdout.flush(); os._exit(1)
                print(f"app: served request {i + 1}")
        """).strip()],
        "Restart": "on-failure",
        "RestartSec": 0.3,                 # first wait; doubles each time (systemd uses a fixed RestartSec)
        "StartLimitBurst": 4,              # this many starts ...
        "StartLimitIntervalSec": 5,        # ... within this window = give up ("start-limit-hit")
        "TimeoutStopSec": 1.0,             # TERM, then KILL after this long
    },
    "stubborn.service": {
        "Description": "a process that ignores SIGTERM, to show the stop timeout",
        "ExecStart": [sys.executable, "-u", "-c", "import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); print('stubborn: ignoring TERM'); time.sleep(60)"],
        "Restart": "no",
        "TimeoutStopSec": 0.8,
    },
    "backup.timer": {
        "Description": "run backup.service every 0.6 s (OnUnitActiveSec)",
        "OnUnitActiveSec": 0.6,
        "Unit": "backup.service",
    },
    "backup.service": {
        "Description": "a one-shot job",
        "ExecStart": [sys.executable, "-u", "-c", "import time; print('backup: snapshot taken at', time.strftime('%H:%M:%S'))"],
        "Type": "oneshot",
        "Restart": "no",
    },
}

journal = []          # what journald keeps: (timestamp, unit, pid, line)
state = {}            # per unit: active/failed/inactive, pid, starts, restarts, since


def log(unit, pid, line):
    entry = (time.strftime("%H:%M:%S"), unit, pid, line)
    journal.append(entry)
    print(f"   {entry[0]} {unit:<17} [{pid:>5}] {line}", flush=True)


# ─── start: fork, wire stdout/stderr to the journal, exec ────────────────────
def start(unit, seed=0, stable=False):
    spec = UNITS[unit]
    r, w = os.pipe()                                   # the child's stdout/stderr come to us through a pipe
    pid = os.fork()
    if pid == 0:
        os.setsid()                                    # its own session: no terminal, no stray SIGHUP
        os.dup2(w, 1); os.dup2(w, 2); os.close(r); os.close(w)
        signal.signal(signal.SIGPIPE, signal.SIG_DFL)
        argv = spec["ExecStart"] + ([str(seed)] + (["stable"] if stable else []) if unit == "app.service" else [])
        try:
            os.execv(argv[0], argv)
        except OSError as e:
            os.write(2, f"exec failed: {e}\n".encode()); os._exit(203)   # systemd's own code for exec failure
    os.close(w)
    st = state.setdefault(unit, {"starts": 0, "restarts": 0, "history": []})
    st.update(active="active", pid=pid, fd=r, since=time.time())
    st["starts"] += 1
    st["history"].append(time.time())
    log("supervisor", os.getpid(), f"Started {unit} ({spec['Description']}) as pid {pid}")
    return pid


def pump(unit):
    """Read whatever the child printed (non-blocking) and journal it, line by line."""
    import fcntl
    st = state[unit]
    fcntl.fcntl(st["fd"], fcntl.F_SETFL, os.O_NONBLOCK)
    try:
        data = os.read(st["fd"], 65536)
    except BlockingIOError:
        return
    for line in data.decode(errors="replace").splitlines():
        log(unit, st["pid"], line)


# ─── stop: TERM, wait up to TimeoutStopSec, then KILL ────────────────────────
def stop(unit):
    st = state[unit]
    spec = UNITS[unit]
    pid = st["pid"]
    log("supervisor", os.getpid(), f"Stopping {unit}: SIGTERM to pid {pid}, TimeoutStopSec={spec['TimeoutStopSec']}s")
    os.kill(pid, signal.SIGTERM)
    deadline = time.time() + spec["TimeoutStopSec"]
    while time.time() < deadline:
        pump(unit)
        done, status = os.waitpid(pid, os.WNOHANG)
        if done:
            log("supervisor", os.getpid(), f"{unit}: exited during grace period, status {describe(status)}")
            st.update(active="inactive", pid=None)
            return
        time.sleep(0.05)
    log("supervisor", os.getpid(), f"{unit}: grace period over, SIGKILL to pid {pid}")
    os.kill(pid, signal.SIGKILL)
    _, status = os.waitpid(pid, 0)
    log("supervisor", os.getpid(), f"{unit}: {describe(status)}")
    st.update(active="inactive", pid=None)


def describe(status):
    if os.WIFEXITED(status):
        return f"code=exited, status={os.WEXITSTATUS(status)}"
    return f"code=killed, signal={signal.Signals(os.WTERMSIG(status)).name}"


# ─── the loop: wait for children, restart with backoff, run timers ───────────
timers_enabled = False


def supervise(duration):
    """What init does forever; here, for `duration` seconds."""
    t_end = time.time() + duration
    next_fire = {u: time.time() for u, s in UNITS.items() if u.endswith(".timer") and timers_enabled}
    while time.time() < t_end:
        for unit, st in list(state.items()):
            if st.get("pid"):
                pump(unit)
                done, status = os.waitpid(st["pid"], os.WNOHANG)      # non-blocking: has it died?
                if done:
                    pump(unit)
                    spec = UNITS[unit]
                    log("supervisor", os.getpid(), f"{unit}: main process exited, {describe(status)}")
                    st.update(pid=None)
                    failed = not (os.WIFEXITED(status) and os.WEXITSTATUS(status) == 0)
                    if spec.get("Type") == "oneshot":
                        st["active"] = "inactive"
                        continue
                    want_restart = spec["Restart"] == "always" or (spec["Restart"] == "on-failure" and failed)
                    if not want_restart:
                        st["active"] = "failed" if failed else "inactive"
                        continue
                    recent = [t for t in st["history"] if t > time.time() - spec["StartLimitIntervalSec"]]
                    if len(recent) >= spec["StartLimitBurst"]:
                        st["active"] = "failed"
                        log("supervisor", os.getpid(), f"{unit}: start request repeated too quickly ({len(recent)} in {spec['StartLimitIntervalSec']}s); giving up (start-limit-hit)")
                        continue
                    delay = spec["RestartSec"] * (2 ** st["restarts"])            # exponential backoff
                    st["restarts"] += 1
                    log("supervisor", os.getpid(), f"{unit}: scheduling restart {st['restarts']} in {delay:.1f}s")
                    st["restart_at"] = time.time() + delay
                    st["active"] = "activating (auto-restart)"
            elif st.get("restart_at") and time.time() >= st["restart_at"]:
                st.pop("restart_at")
                start(unit, seed=st["starts"])
        for timer, at in next_fire.items():                                      # timers: start a oneshot on schedule
            if time.time() >= at:
                target = UNITS[timer]["Unit"]
                if not state.get(target, {}).get("pid"):
                    start(target)
                next_fire[timer] = time.time() + UNITS[timer]["OnUnitActiveSec"]
        # reap anything else we were left with (adopted orphans): what PID 1 must always do
        try:
            while True:
                pid, status = os.waitpid(-1, os.WNOHANG)
                if pid == 0:
                    break
                if not any(s.get("pid") == pid for s in state.values()):
                    log("supervisor", os.getpid(), f"reaped adopted child {pid} ({describe(status)})")
        except ChildProcessError:
            pass
        time.sleep(0.02)


def status(unit):
    st = state.get(unit, {})
    spec = UNITS[unit]
    since = time.time() - st.get("since", time.time())
    print(f"● {unit} - {spec['Description']}")
    print(f"     Active: {st.get('active', 'inactive')}" + (f" since {since:.1f}s ago" if st.get("pid") else ""))
    if st.get("pid"):
        print(f"   Main PID: {st['pid']}")
    print(f"     Starts: {st.get('starts', 0)}   Restarts: {st.get('restarts', 0)}")
    for entry in [e for e in journal if e[1] == unit][-3:]:
        print(f"   {entry[0]} {entry[3]}")


if __name__ == "__main__":
    print("supervisor: pid", os.getpid(), "(pretend this is PID 1: it starts units, keeps their output, restarts them, reaps children)\n")

    print("=== 1 · start app.service and supervise it for 6 s: it crashes, gets restarted with backoff, and eventually hits the start limit")
    start("app.service")
    supervise(6.0)
    print(); status("app.service"); print()

    print("=== 2 · a timer: backup.timer starts backup.service every 0.6 s, each run a fresh oneshot process")
    timers_enabled = True
    supervise(1.5)
    timers_enabled = False
    print()

    print("=== 3 · stop a service that ignores SIGTERM: TERM, TimeoutStopSec, then KILL")
    start("stubborn.service")
    supervise(0.3)
    stop("stubborn.service")
    print(); status("stubborn.service"); print()

    print("=== 4 · stop a well-behaved service: TERM, and it drains and exits 0 inside the grace period")
    state.pop("app.service")
    start("app.service", stable=True)
    supervise(0.6)
    stop("app.service")
    print(); status("app.service"); print()

    print("=== 5 · the journal: every line every unit printed, with time, unit and pid, in one place")
    print(f"   {len(journal)} entries; `journalctl -u app.service` is this list filtered by the unit column:")
    for e in [e for e in journal if e[1] == "app.service"][:6]:
        print(f"   {e[0]} {e[1]} [{e[2]}] {e[3]}")
    print("   ...")
