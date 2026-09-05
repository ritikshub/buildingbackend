---
name: runbook-stopping-a-process
description: The escalation ladder for stopping a process safely (identify, TERM, wait, KILL, and the process group or the service manager around it), the four reasons a process will not die (ignored TERM, state D, a zombie, a respawning parent), and the diagnosis when a process disappeared on its own (OOM, 137, a signal from someone)
phase: 01
lesson: 10
---

# Stopping a process, and finding out why one stopped

`kill -9` is the last rung of a ladder, not the first. Every rung above
it gives the process a chance to finish a request, flush a log, release a
lock, or tell its children. This runbook is the ladder, the four things
that stop it working, and the reverse question.

## 1 · Identify, precisely

- [ ] Get the PID from the source of truth, not from a guess: `systemctl status name` (the `Main PID:` line), `pgrep -f 'exact string'`, `ps -eo pid,ppid,user,stat,etime,cmd | grep -v grep | grep name`, `ss -tlnp` for "who holds this port", `lsof -p` for "who holds this file".
- [ ] `pgrep -f` matches the **whole command line** and will match your own `grep`; `pgrep -x name` matches the process name exactly. Read the list before you kill it.
- [ ] Look at its tree first: `pstree -p PID` or `ps -o pid,ppid,pgid,sid,stat,cmd --forest`. Killing a parent may orphan workers that keep the port; killing a worker may make its supervisor spawn another.
- [ ] Look at its state: `ps -o stat= -p PID`. `S` or `R` will respond to signals. `D`, `Z` and `T` are section 3.
- [ ] If it belongs to a service manager, **stop it through the manager**: `systemctl stop name`, `docker stop id`, `kubectl delete pod`. Killing the process directly makes the manager restart it, and the log says "failed" for something that was you.

## 2 · The ladder

```bash
kill -TERM PID            # 1. ask nicely: the default, what systemctl stop and docker stop send first
sleep 5; ps -p PID        # 2. wait a grace period; check
kill -TERM -- -PGID       # 3. the whole process group (a pipeline, a parent with workers): ps -o pgid= -p PID
kill -KILL PID            # 4. the kernel ends it; no cleanup, no flush, no goodbye
```

- [ ] **TERM first, always.** A correctly written server (lesson 10's handler) stops accepting, finishes in-flight requests, closes files and exits 0. The exit status you see from the shell is 143 (128 + 15).
- [ ] **Wait.** A grace period is part of the protocol. `systemd` waits `TimeoutStopSec` (default 90 s); Docker waits 10 s; Kubernetes waits `terminationGracePeriodSeconds` (30 s). If your service needs longer to drain, set the timeout; do not shorten it because you are impatient.
- [ ] **INT, HUP, QUIT are not "softer TERMs."** `INT` is what `Ctrl+C` sends and many programs treat it like TERM. `HUP` means "reload config" to daemons and "your terminal went away" to everything else. `QUIT` makes many programs dump core or a thread dump (the JVM does). Send the one the program documents.
- [ ] **Do not `kill -9` a database, a message broker or anything with a write-ahead log** unless it is already unresponsive to TERM after its documented timeout. Recovery on the next start can take longer than the drain you skipped.
- [ ] `timeout 30 cmd` for one-off commands gives you the ladder automatically: TERM at the deadline, and `timeout -k 5 30 cmd` adds a KILL five seconds later. Exit 124 means it timed out.
- [ ] After a KILL: check for what it left behind. A stale PID file (`/run/name.pid`), a lock file, a socket file in `/run`, a half-written temp file, a port in `TIME_WAIT` (lesson 14). The next start may fail on any of them.

## 3 · It will not die

| symptom | cause | what to do |
|---|---|---|
| `kill -TERM` does nothing; state stays `S` | the program **ignores TERM** (`SigIgn` in `/proc/PID/status` has bit 15 set) or handles it and never exits (a bug in its shutdown path) | check `grep -E 'SigIgn\|SigCgt' /proc/PID/status`; read its docs for the right signal; then `kill -KILL` |
| state `D`, even KILL does nothing | **uninterruptible sleep**: waiting on a disk, a hung NFS server, a stuck driver. Signals are delivered only when the I/O returns | `cat /proc/PID/wchan` and `cat /proc/PID/stack` (root) say what it waits on; fix the I/O (remount, restore the server); if it never returns, the only kill is a reboot |
| state `Z` (`<defunct>`) | a **zombie**: already dead; only a PID and an exit status remain. It cannot be killed because there is nothing to kill | the parent must `wait()`. Find it: `ps -o ppid= -p PID`. Send the parent `SIGCHLD` (`kill -CHLD PPID`) in case it merely missed it; otherwise restart the parent, and PID 1 adopts and reaps the zombie. Hundreds of zombies = a parent that never waits: fix that program |
| state `T` | **stopped**: `Ctrl+Z`, `SIGSTOP`, or a debugger attached | `kill -CONT PID` to resume; then TERM if you still want it gone. A stopped process ignores TERM until continued |
| it dies and **comes back with a new PID** | a supervisor restarts it: `systemd` (`Restart=always`), a container runtime, a wrapper script with a loop, `cron` every minute | stop the supervisor's intent, not the child: `systemctl stop`, `systemctl disable`, `docker stop`, edit the crontab |
| it dies but the **port stays busy** | a child or a forked worker inherited the listening socket and is still alive | `ss -tlnp` names the holder; kill the whole process group (`-- -PGID`), or the child by PID |
| `kill: (PID): Operation not permitted` | you are not its owner and not root | `sudo kill`, or `sudo -u owner kill` |

## 4 · It disappeared on its own

- [ ] **What was the exit status?** From `systemctl status name`: `code=killed, signal=KILL` or `status=1/FAILURE`. From a shell: `$?` (137 = KILL, 143 = TERM, 139 = SEGV, 134 = ABRT, 1..125 = the program chose). From Docker: `docker inspect id --format '{{.State.ExitCode}}'`.
- [ ] **137 / `signal=KILL` and you did not send it: the OOM killer.** `dmesg -T | grep -iE 'killed process|out of memory'` names the victim and its RSS; `journalctl -k` on a systemd box. In a container, `docker inspect` shows `OOMKilled: true`. Fix: the memory limit or the leak (lesson 12).
- [ ] **143 / `signal=TERM`:** someone or something sent TERM: a deploy, `systemctl stop`, a cluster autoscaler draining the node, a `docker stop`. `journalctl _COMM=sudo` and the deploy log are where to look.
- [ ] **139 / `signal=SEGV`, 134 / `signal=ABRT`:** the program crashed. There may be a core dump (`coredumpctl list`), and the program's own log has the last lines *unless* they were in a buffer (lesson 07).
- [ ] **Exited 0 but should have kept running:** it thought it was done. A server that exits when its config is unreadable, a worker that exits on an empty queue, a process that was told to fork into the background and the supervisor tracked the wrong PID (`Type=forking` vs `simple` in systemd, lesson 11).
- [ ] **Terminal closed, and it went with it:** `SIGHUP` from the pty. It was started with `&` in a shell instead of `nohup`, `setsid`, `tmux`, or a unit file.
- [ ] **Nothing in any log:** check it was not a *different* copy that died, and that the box did not reboot (`uptime`, `last reboot`).

## 5 · Writing a process that stops well

For the services you own (lesson 11 puts one under systemd):

- [ ] Handle `SIGTERM`: stop accepting new work, finish in-flight work with a deadline, flush and close, exit 0. Treat `SIGINT` the same, so `Ctrl+C` during development matches production.
- [ ] Handle `SIGHUP` as "reload config" if the program reloads at all; otherwise leave the default, which exits.
- [ ] Never ignore `SIGTERM`, and never install a handler that only logs and continues.
- [ ] Log to stderr or flush after every log line, so the shutdown lines survive a KILL.
- [ ] If the process runs as PID 1 (a container), it must reap children it adopts, or use `--init` / `tini` (Phase 11, lesson 02).
- [ ] Exit non-zero when stopping because of an error, zero when stopping because asked, so the supervisor's `Restart=on-failure` does the right thing.
