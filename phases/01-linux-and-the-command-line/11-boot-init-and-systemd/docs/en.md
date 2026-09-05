# Boot, init & systemd

> Between the power button and your service there is one program the kernel starts, PID 1, and everything else on the box is its descendant. This lesson builds that program's core in Python, a supervisor that starts a unit, keeps its output, restarts it with backoff, gives up on a crash loop, and stops it with `TERM`, a grace period and `KILL`, then puts a real service under `systemd` on a box that boots: `enable --now`, `status`, `journalctl`, a `kill -9` that `Restart=on-failure` survives with `NRestarts=1`, a `reload` that is a `SIGHUP`, a stop that drains and exits 0, a broken unit reporting `203/EXEC`, a crash loop hitting `Start request repeated too quickly`, a timer, cron, and log rotation.

## The Problem

Your service has to be running at 3 a.m. on a machine that rebooted at 2 a.m. after a kernel update, with nobody logged in. It has to come back when it crashes, but not spin forever when the database is down. It has to stop cleanly when you deploy, log somewhere you can read a week later, run as its own user in its own directories, and do a nightly backup without you remembering. Lessons 06 and 10 gave you every piece of that: users, permissions, signals, sessions. The piece that assembles them is the **init system**, and on every Linux server you will touch it is `systemd`.

`systemd` has a reputation for being large, and it is. But the part a backend engineer needs is small: one unit file of about twenty lines, six `systemctl` verbs, `journalctl`, and a timer. What makes it feel like magic is not knowing what a supervisor does. So this lesson writes one first.

## The Concept

### From the power button to PID 1

Nothing in user space exists until the kernel creates one process and points it at an `init` program. Everything before that is firmware and a bootloader; everything after it is that process's children.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 430" width="100%" style="max-width:880px" font-family="'JetBrains Mono', ui-monospace, monospace" role="img" aria-label="The boot sequence as six stages left to right. Firmware, UEFI or BIOS, runs from a chip, initialises hardware, and finds a bootloader on disk. The bootloader, GRUB or systemd-boot, loads the kernel image and an initramfs from /boot into RAM and hands over. The kernel initialises drivers, mounts the root filesystem, and starts exactly one process, PID 1, from init=, by default /sbin/init which is a symlink to systemd. systemd reads unit files, computes a dependency graph, and starts units in parallel until it reaches the default target, multi-user.target on a server. Then your service starts, as one of those units, and its children are all descendants of PID 1. A footnote says a container skips the first three stages entirely: it is a process whose PID 1 is whatever CMD names, which is why the main sandbox cannot run systemd and this lesson uses a privileged one that boots /sbin/init.">
  <defs>
    <marker id="p1l11a-ar" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker>
  </defs>
  <text x="450" y="26" text-anchor="middle" font-size="14.5" font-weight="700" fill="currentColor">From the power button to your service: five hand-offs, one process at the end of them</text>
  <g stroke-linejoin="round" stroke-width="1.7">
    <rect x="30"  y="60" width="150" height="150" rx="10" fill="#7f7f7f" fill-opacity="0.12" stroke="#7f7f7f"/>
    <rect x="200" y="60" width="150" height="150" rx="10" fill="#7f7f7f" fill-opacity="0.12" stroke="#7f7f7f"/>
    <rect x="370" y="60" width="150" height="150" rx="10" fill="#0fa07f" fill-opacity="0.12" stroke="#0fa07f"/>
    <rect x="540" y="60" width="150" height="150" rx="10" fill="#c94a12" fill-opacity="0.12" stroke="#c94a12" stroke-width="2.2"/>
    <rect x="710" y="60" width="160" height="150" rx="10" fill="#7c5cff" fill-opacity="0.12" stroke="#7c5cff"/>
  </g>
  <g text-anchor="middle" font-size="8.5" fill="currentColor">
    <text x="105" y="82" font-size="10" font-weight="700">1 · FIRMWARE</text>
    <text x="105" y="98" opacity="0.75">UEFI (or BIOS)</text>
    <text x="105" y="118">runs from a chip</text>
    <text x="105" y="132">initialises hardware</text>
    <text x="105" y="146">finds a bootloader</text>
    <text x="105" y="160">on the boot disk</text>
    <text x="105" y="190" opacity="0.7">milliseconds to seconds</text>
    <text x="275" y="82" font-size="10" font-weight="700">2 · BOOTLOADER</text>
    <text x="275" y="98" opacity="0.75">GRUB, systemd-boot</text>
    <text x="275" y="118">reads /boot</text>
    <text x="275" y="132">loads the kernel image</text>
    <text x="275" y="146">and an initramfs</text>
    <text x="275" y="160">passes the cmdline</text>
    <text x="275" y="190" opacity="0.7">/proc/cmdline shows it</text>
    <text x="445" y="82" font-size="10" font-weight="700" fill="#0fa07f">3 · THE KERNEL</text>
    <text x="445" y="98" opacity="0.75">lesson 02's five subsystems</text>
    <text x="445" y="118">drivers, memory, clocks</text>
    <text x="445" y="132">mounts the root filesystem</text>
    <text x="445" y="146">creates ONE process:</text>
    <text x="445" y="160" font-weight="700">PID 1 = init=/sbin/init</text>
    <text x="445" y="190" opacity="0.7">everything after is user space</text>
    <text x="615" y="82" font-size="10" font-weight="700" fill="#c94a12">4 · systemd</text>
    <text x="615" y="98" opacity="0.75">/sbin/init → systemd</text>
    <text x="615" y="118">reads every unit file</text>
    <text x="615" y="132">builds a dependency graph</text>
    <text x="615" y="146">starts units in parallel</text>
    <text x="615" y="160">until the default target</text>
    <text x="615" y="190" opacity="0.7">multi-user.target on a server</text>
    <text x="790" y="82" font-size="10" font-weight="700" fill="#7c5cff">5 · YOUR SERVICE</text>
    <text x="790" y="98" opacity="0.75">app.service</text>
    <text x="790" y="118">one unit among dozens</text>
    <text x="790" y="132">started, watched, logged</text>
    <text x="790" y="146">and restarted by PID 1</text>
    <text x="790" y="160">no terminal, no login</text>
    <text x="790" y="190" opacity="0.7">a descendant of PID 1, like all</text>
  </g>
  <g fill="none" stroke="currentColor" stroke-width="1.6">
    <path d="M182 135 L196 135" marker-end="url(#p1l11a-ar)"/>
    <path d="M352 135 L366 135" marker-end="url(#p1l11a-ar)"/>
    <path d="M522 135 L536 135" marker-end="url(#p1l11a-ar)"/>
    <path d="M692 135 L706 135" marker-end="url(#p1l11a-ar)"/>
  </g>
  <rect x="30" y="236" width="840" height="120" rx="10" fill="#e0930f" fill-opacity="0.08" stroke="#e0930f" stroke-width="1.6" stroke-linejoin="round"/>
  <text x="450" y="258" text-anchor="middle" font-size="10" font-weight="700" fill="#e0930f">SEEN ON THE BOOTED SANDBOX</text>
  <g font-size="8.5" fill="currentColor">
    <text x="46" y="280">cat /proc/1/comm → systemd        systemctl get-default → graphical.target        systemd-analyze → Startup finished in 253ms (userspace)</text>
    <text x="46" y="298">ps --forest: systemd (1) → systemd-journald (26), cron (70), app.service's python3 (147) ...        systemd-analyze blame → the slowest units first</text>
    <text x="46" y="316">systemctl list-dependencies multi-user.target → the tree of what "up" means: basic.target, cron.service, your app.service ...</text>
    <text x="46" y="340" opacity="0.8">a container skips stages 1 to 3: its PID 1 is whatever CMD names. That is why `make shell` cannot run systemd, and why this lesson boots one that can.</text>
  </g>
  <text x="450" y="392" text-anchor="middle" font-size="10.5" fill="currentColor" opacity="0.9">Firmware finds the loader, the loader loads the kernel, the kernel starts PID 1, PID 1 starts everything else.</text>
  <text x="450" y="412" text-anchor="middle" font-size="9.5" fill="currentColor" opacity="0.72">"The server rebooted" means this whole chain ran again and your service came back only if a unit told PID 1 to start it.</text>
</svg>
```

On a server the chain takes seconds and you rarely see it. What you need from it is three facts. `/proc/cmdline` is what the bootloader told the kernel. `/boot` holds the kernel and is empty inside a container, because a container never booted. And **PID 1 is `systemd`**, started by the kernel, and every process on the box is its descendant, which is why `systemd` is the one that adopts orphans (lesson 10) and the one that decides what runs at boot.

### What a supervisor does

Strip `systemd` down to what it does for one service and you get a loop that any init has had since the 1970s, plus three refinements that make it safe to run in production:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 470" width="100%" style="max-width:880px" font-family="'JetBrains Mono', ui-monospace, monospace" role="img" aria-label="The supervisor's state machine for one unit. Start: fork, put the child in its own session, connect its stdout and stderr to the journal, drop to the service user, exec the ExecStart command; the unit is now active. The supervisor waits. If the child exits with status 0 and Restart is on-failure, the unit becomes inactive: it was asked to stop or it finished. If the child exits non-zero or dies by signal, the unit has failed; if Restart says so, the supervisor counts recent starts: if more than StartLimitBurst within StartLimitIntervalSec, it gives up and marks the unit failed with start-limit-hit; otherwise it waits RestartSec and goes back to start, with NRestarts incremented. A separate path: a stop request sends SIGTERM, waits TimeoutStopSec while the child drains, and if the child is still alive sends SIGKILL to the whole cgroup; the unit is then inactive. Throughout, every line the child prints is timestamped with the unit name and PID into the journal, and any orphan the supervisor inherits is reaped.">
  <defs>
    <marker id="p1l11b-ar" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker>
    <marker id="p1l11b-arg" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#0fa07f"/></marker>
    <marker id="p1l11b-ard" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#d64545"/></marker>
  </defs>
  <text x="450" y="26" text-anchor="middle" font-size="14.5" font-weight="700" fill="currentColor">One unit's life inside the supervisor: start, watch, restart with limits, stop with a deadline</text>
  <rect x="40" y="56" width="260" height="96" rx="10" fill="#0fa07f" fill-opacity="0.12" stroke="#0fa07f" stroke-width="2" stroke-linejoin="round"/>
  <text x="170" y="78" text-anchor="middle" font-size="10.5" font-weight="700" fill="#0fa07f">START</text>
  <g text-anchor="middle" font-size="8.5" fill="currentColor">
    <text x="170" y="96">fork · setsid · stdout,stderr → journal</text>
    <text x="170" y="110">drop to User= · chdir WorkingDirectory=</text>
    <text x="170" y="124">exec ExecStart=  →  active (running)</text>
    <text x="170" y="140" opacity="0.75">the child never sees a terminal</text>
  </g>
  <rect x="360" y="56" width="180" height="96" rx="10" fill="#7f7f7f" fill-opacity="0.12" stroke="#7f7f7f" stroke-width="1.7" stroke-linejoin="round"/>
  <text x="450" y="78" text-anchor="middle" font-size="10.5" font-weight="700" fill="currentColor">WATCH</text>
  <g text-anchor="middle" font-size="8.5" fill="currentColor">
    <text x="450" y="96">waitpid(WNOHANG) in a loop</text>
    <text x="450" y="110">journal every line it prints</text>
    <text x="450" y="124">reap any adopted orphan</text>
    <text x="450" y="140" opacity="0.75">this is where PID 1 lives</text>
  </g>
  <path d="M302 104 L356 104" fill="none" stroke="currentColor" stroke-width="1.6" marker-end="url(#p1l11b-ar)"/>
  <!-- exits -->
  <rect x="600" y="56" width="270" height="96" rx="10" fill="#e0930f" fill-opacity="0.10" stroke="#e0930f" stroke-width="1.7" stroke-linejoin="round"/>
  <text x="735" y="78" text-anchor="middle" font-size="10.5" font-weight="700" fill="#e0930f">THE CHILD EXITED</text>
  <g text-anchor="middle" font-size="8.5" fill="currentColor">
    <text x="735" y="96">status 0 → inactive (it finished or was asked)</text>
    <text x="735" y="110">non-zero or a signal → failed</text>
    <text x="735" y="124">Restart=on-failure: restart only the second kind</text>
    <text x="735" y="140" opacity="0.75">Restart=always: both · Restart=no: neither</text>
  </g>
  <path d="M542 104 L596 104" fill="none" stroke="currentColor" stroke-width="1.6" marker-end="url(#p1l11b-ar)"/>
  <!-- restart decision -->
  <rect x="600" y="186" width="270" height="110" rx="10" fill="#d64545" fill-opacity="0.08" stroke="#d64545" stroke-width="1.7" stroke-linejoin="round"/>
  <text x="735" y="208" text-anchor="middle" font-size="10.5" font-weight="700" fill="#d64545">RESTART, OR GIVE UP?</text>
  <g text-anchor="middle" font-size="8.5" fill="currentColor">
    <text x="735" y="226">starts in the last StartLimitIntervalSec</text>
    <text x="735" y="240">≥ StartLimitBurst → failed (start-limit-hit)</text>
    <text x="735" y="254">else: sleep RestartSec, NRestarts += 1,</text>
    <text x="735" y="268">and START again</text>
    <text x="735" y="286" opacity="0.75">a crash loop stops here; an outage waits</text>
  </g>
  <path d="M735 154 L735 182" fill="none" stroke="#d64545" stroke-width="1.6" marker-end="url(#p1l11b-ard)"/>
  <path d="M598 240 L170 240 L170 156" fill="none" stroke="#0fa07f" stroke-width="1.8" marker-end="url(#p1l11b-arg)"/>
  <text x="380" y="232" text-anchor="middle" font-size="8.5" fill="#0fa07f" font-weight="700">restart after RestartSec</text>
  <!-- stop path -->
  <rect x="40" y="320" width="500" height="96" rx="10" fill="#7c5cff" fill-opacity="0.10" stroke="#7c5cff" stroke-width="1.7" stroke-linejoin="round"/>
  <text x="290" y="342" text-anchor="middle" font-size="10.5" font-weight="700" fill="#7c5cff">STOP (systemctl stop, a deploy, shutdown)</text>
  <g text-anchor="middle" font-size="8.5" fill="currentColor">
    <text x="290" y="360">SIGTERM to the main PID (KillMode=mixed) or the whole cgroup (control-group)</text>
    <text x="290" y="374">wait up to TimeoutStopSec while it drains; journal what it says</text>
    <text x="290" y="388">still alive → SIGKILL to every process in the cgroup → inactive</text>
    <text x="290" y="404" opacity="0.75">a clean exit 0 here is NOT a failure, so on-failure does not restart it</text>
  </g>
  <path d="M450 154 L450 316" fill="none" stroke="#7c5cff" stroke-width="1.6" stroke-dasharray="5 4" marker-end="url(#p1l11b-ar)"/>
  <text x="464" y="240" font-size="8" fill="#7c5cff">stop requested</text>
  <rect x="600" y="320" width="270" height="96" rx="10" fill="#7f7f7f" fill-opacity="0.12" stroke="#7f7f7f" stroke-width="1.7" stroke-linejoin="round"/>
  <text x="735" y="342" text-anchor="middle" font-size="10.5" font-weight="700" fill="currentColor">THE JOURNAL</text>
  <g text-anchor="middle" font-size="8.5" fill="currentColor">
    <text x="735" y="360">every line, stamped: time, unit, PID</text>
    <text x="735" y="374">plus the supervisor's own events:</text>
    <text x="735" y="388">Started, Main process exited, Scheduled restart</text>
    <text x="735" y="404" opacity="0.75">journalctl -u app is a filter on the unit column</text>
  </g>
  <text x="450" y="446" text-anchor="middle" font-size="10.5" fill="currentColor" opacity="0.9">Every directive in a unit file is a knob on this diagram. The Build It script is this diagram in 200 lines.</text>
</svg>
```

- **Start** is lesson 03 plus lesson 07 plus lesson 10: fork, `setsid` so the child has no terminal, connect its stdout and stderr to a pipe the supervisor reads, drop to the service user, `exec`.
- **Watch** is a non-blocking `waitpid` in a loop, draining that pipe into a **journal**: every line stamped with time, unit and PID, alongside the supervisor's own events. `journalctl -u app` is that list filtered by the unit column.
- **Restart** is a policy, not a reflex. `on-failure` restarts a non-zero exit or a signal death but not a clean exit 0, which means "I was asked to stop." `always` restarts both. And a **start limit** (`StartLimitBurst` starts within `StartLimitIntervalSec`) turns a crash loop into a `failed` unit instead of a log flood, while `RestartSec` gives a dependency time to come back.
- **Stop** is lesson 10's contract, enforced: `SIGTERM`, `TimeoutStopSec` of patience, then `SIGKILL` to everything the unit started.

### The unit file

A unit is a text file in `/etc/systemd/system/` with three sections. Here is the one the **Use It** section installs, which is also the one in the checklist, because it is the shape of every backend service unit you will write:

```ini
[Unit]
Description=App API server (lesson 11)
After=network-online.target
Wants=network-online.target
StartLimitIntervalSec=60
StartLimitBurst=5

[Service]
Type=simple
User=app
Group=app
WorkingDirectory=/opt/app
ExecStart=/usr/bin/python3 /opt/app/server.py
ExecReload=/bin/kill -HUP $MAINPID
EnvironmentFile=/etc/app/app.env
Environment=PYTHONUNBUFFERED=1
UMask=027
RuntimeDirectory=app
StateDirectory=app
LogsDirectory=app
Restart=on-failure
RestartSec=1
TimeoutStopSec=10
KillMode=mixed
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
```

`[Unit]` says what it is and what it needs: `After=` orders it behind the network being up, `Wants=` pulls that target in, and the start limit is the crash-loop brake. `[Service]` is the diagram's knobs: `Type=simple` means the `ExecStart` process *is* the service and stays in the foreground (nearly every modern server; `forking` is for old daemons that background themselves, `oneshot` for jobs, `notify` for services that report readiness); `User=`, `WorkingDirectory=`, `EnvironmentFile=` and `UMask=` are lessons 06 and 09; `RuntimeDirectory=`, `StateDirectory=` and `LogsDirectory=` create `/run/app`, `/var/lib/app` and `/var/log/app` owned by the service user, which is lesson 04's layout with no install script; `Restart=`, `RestartSec=`, `TimeoutStopSec=` and `KillMode=` are the supervisor; the `Protect*` lines are a sandbox (`/usr` and `/etc` read-only, no `/home`, a private `/tmp`) that costs nothing and stops a whole class of mistakes. `[Install]` says when to start it at boot: `multi-user.target` is "the server is up."

Three things about `ExecStart=` catch everyone. It is an **absolute path and no shell**: no `&&`, no pipes, no `$VAR` expansion except `${VAR}` from `Environment=`; wrap in `/bin/sh -c '...'` only when you must, and then `exec` the real program so that signals reach it rather than the shell (lesson 03's fork-skipping exec, and lesson 10's Think-about-it 1). A `%` is a **specifier** (`%T` is `/tmp`, `%i` an instance name) and must be written `%%` to mean a percent sign; the **Use It** timer prints `tick at /tmp` until you know that. And after *any* edit, `systemctl daemon-reload`, or nothing changes.

### journald: logs without log files

The service printed to stdout and never opened a log file, yet `journalctl -u app` has every line, with a timestamp, the unit, the PID, and the priority, stored in an indexed binary journal that rotates itself. That is the third piece of the supervisor made real: `systemd` connected the service's descriptors 1 and 2 to `journald` (lesson 07), and `journald` stamps and stores. `journalctl -u app -f` follows, `--since '1 hour ago'` and `-p warning` filter, `-o json` gives the fields to `jq`, and `-k` is the kernel log where the OOM killer writes. The rule from lesson 07 applies with force: set `PYTHONUNBUFFERED=1` (or flush) or the journal gets lines in 8 KiB lumps.

### Timers, cron, and rotation

A `.timer` unit starts a `.service` on a schedule: `OnCalendar=*-*-* 03:15:00` for wall-clock times, `OnUnitActiveSec=10m` for intervals, `Persistent=true` to run a missed job after a reboot, `RandomizedDelaySec=` to spread a fleet. `systemctl list-timers` shows the next and last run; the job's output is in the journal like any other unit. `cron` is the older, simpler tool and still fine for a one-liner: five fields, `min hour dom mon dow`, then the command, in `crontab -e` or a file in `/etc/cron.d/`, with the empty environment of lesson 09 and no log unless you redirect.

If the service writes files under `/var/log/app` instead of the journal, **`logrotate`** renames them on a schedule (`app.log` becomes `app.log.1`, then compresses to `app.log.2.gz`), keeps `rotate N` of them, and runs a `postrotate` command, which must make the service reopen its log: `SIGHUP` if it handles one, `copytruncate` if it does not. Without that step the service keeps writing to the renamed, then deleted, inode, and lesson 04's invisible disk-filling file is born.

## Build It

The script for this lesson is [`code/supervisor.py`](../code/supervisor.py). It defines four "units" using `systemd`'s own directive names, then acts as PID 1 for them: a flaky server that crashes after a few requests, a process that ignores `SIGTERM`, a timer, and a one-shot job. It runs on macOS and Linux:

```bash
python3 phases/01-linux-and-the-command-line/11-boot-init-and-systemd/code/supervisor.py
```

**Start** is the four lessons assembled, and `203` is the status `systemd` itself uses when `exec` fails:

```python
r, w = os.pipe()                                   # the child's stdout/stderr come to us through a pipe
pid = os.fork()
if pid == 0:
    os.setsid()                                    # its own session: no terminal, no stray SIGHUP
    os.dup2(w, 1); os.dup2(w, 2); os.close(r); os.close(w)
    try:
        os.execv(argv[0], argv)
    except OSError as e:
        os.write(2, f"exec failed: {e}\n".encode()); os._exit(203)
```

**Restart with a limit** is the decision in the middle of the diagram:

```python
want_restart = spec["Restart"] == "always" or (spec["Restart"] == "on-failure" and failed)
recent = [t for t in st["history"] if t > time.time() - spec["StartLimitIntervalSec"]]
if len(recent) >= spec["StartLimitBurst"]:
    st["active"] = "failed"                        # start-limit-hit: stop trying
else:
    delay = spec["RestartSec"] * (2 ** st["restarts"])
    st["restart_at"] = time.time() + delay         # back off, then start again
```

**Stop** is `TERM`, a deadline, `KILL`, exactly as lesson 10 described and as `systemd` does with `TimeoutStopSec`. Run it and read the journal it prints. The crash loop and the brake:

```console
   10:08:06 app.service       [41219] app: unhandled exception in request handler
   10:08:06 supervisor        [41218] app.service: main process exited, code=exited, status=1
   10:08:06 supervisor        [41218] app.service: scheduling restart 1 in 0.3s
   10:08:06 supervisor        [41218] Started app.service (...) as pid 41227
   10:08:07 supervisor        [41218] app.service: scheduling restart 2 in 0.6s
   10:08:08 supervisor        [41218] app.service: scheduling restart 3 in 1.2s
   10:08:09 supervisor        [41218] app.service: main process exited, code=exited, status=1
   10:08:09 supervisor        [41218] app.service: start request repeated too quickly (4 in 5s); giving up (start-limit-hit)

● app.service - a flaky HTTP-ish server that crashes now and then
     Active: failed
     Starts: 4   Restarts: 3
```

The two stops, one against a process that ignores the signal and one against a well-behaved one:

```console
   10:08:13 stubborn.service  [41235] stubborn: ignoring TERM
   10:08:13 supervisor        [41218] Stopping stubborn.service: SIGTERM to pid 41235, TimeoutStopSec=0.8s
   10:08:14 supervisor        [41218] stubborn.service: grace period over, SIGKILL to pid 41235
   10:08:14 supervisor        [41218] stubborn.service: code=killed, signal=SIGKILL

   10:08:15 supervisor        [41218] Stopping app.service: SIGTERM to pid 41236, TimeoutStopSec=1.0s
   10:08:15 app.service       [41236] app: SIGTERM, draining 1 request, bye
   10:08:15 supervisor        [41218] app.service: exited during grace period, status code=exited, status=0
```

And the timer, starting a fresh one-shot process every 0.6 s, each one reaped as it finishes. Compare every line of this output with the `journalctl` output in the next section; the words are nearly the same because the mechanism is the same.

## Use It

`systemd` needs a booted machine, and the main sandbox is a process, not a machine. So this lesson ships a second one: [`code/systemd-sandbox/Dockerfile`](../code/systemd-sandbox/Dockerfile) builds a Debian image whose command is `/sbin/init`, run privileged so that `systemd` can manage cgroups. It is for these exercises only. Along with it are [`code/server.py`](../code/server.py), the service (drains on `TERM`, reloads on `HUP`, logs unbuffered), and [`code/app.service`](../code/app.service), the unit above.

```bash
docker build -t phase1-systemd phases/01-linux-and-the-command-line/11-boot-init-and-systemd/code/systemd-sandbox
docker run -d --rm --privileged --name sysd -v "$PWD":/workspace:ro --tmpfs /run --tmpfs /run/lock phase1-systemd
docker exec -it sysd bash
```

Inside, PID 1 is `systemd`, and the boot has already happened:

```console
$ cat /proc/1/comm;  systemctl get-default;  systemd-analyze
systemd
graphical.target
Startup finished in 253ms (userspace)
$ ps -eo pid,ppid,user,comm --forest | head -5
    PID    PPID USER     COMMAND
      1       0 root     systemd
     26       1 root     systemd-journal
     70       1 root     cron
```

Install the service the lesson 06 way, then the unit, verify it, and start it:

```console
$ groupadd --system app;  useradd --system --gid app --home-dir /var/lib/app --shell /usr/sbin/nologin app
$ mkdir -p /opt/app /etc/app;  cp /workspace/phases/01-linux-and-the-command-line/11-boot-init-and-systemd/code/server.py /opt/app/
$ printf 'PORT=8080\n' > /etc/app/app.env;  chown root:app /etc/app/app.env;  chmod 640 /etc/app/app.env
$ cp /workspace/phases/01-linux-and-the-command-line/11-boot-init-and-systemd/code/app.service /etc/systemd/system/
$ systemd-analyze verify /etc/systemd/system/app.service && echo "verify: ok"
verify: ok
$ systemctl daemon-reload;  systemctl enable --now app
Created symlink '/etc/systemd/system/multi-user.target.wants/app.service' → '/etc/systemd/system/app.service'.
```

`enable` created the symlink that starts it at boot; `--now` started it. `status` shows the supervisor's view, the cgroup, and the last log lines:

```console
$ systemctl status app
● app.service - App API server (lesson 11)
     Loaded: loaded (/etc/systemd/system/app.service; enabled; preset: enabled)
     Active: active (running) since Sat 2026-09-05 04:38:39 UTC; 1s ago
   Main PID: 147 (python3)
      Tasks: 1 (limit: 9641)
     Memory: 19.8M (peak: 19.9M)
        CPU: 117ms
     CGroup: /system.slice/app.service
             └─147 /usr/bin/python3 /opt/app/server.py

Sep 05 04:38:39 0970caef98b3 systemd[1]: Started app.service - App API server (lesson 11).
Sep 05 04:38:39 0970caef98b3 python3[147]: listening on 8080 as uid 997, cwd /opt/app, HOME=/var/lib/app
$ curl -s localhost:8080/;  ls -ld /run/app /var/lib/app /var/log/app
hello from pid 147 as uid 997
drwxr-xr-x 2 app app 40 Sep  5 04:38 /run/app
drwxr-xr-x 1 app app  0 Sep  5 04:38 /var/lib/app
drwxr-xr-x 1 app app  0 Sep  5 04:38 /var/log/app
```

The service is uid 997 in `/opt/app` with the three directories created for it, and its first line is in the journal. Now the supervisor at work: kill the main process and `Restart=on-failure` brings it back, counted:

```console
$ kill -KILL $(systemctl show app -p MainPID --value);  sleep 2;  systemctl show app -p MainPID,NRestarts,Result
MainPID=164
NRestarts=1
Result=success
$ journalctl -u app | tail -5
Sep 05 04:38:40 0970caef98b3 systemd[1]: app.service: Main process exited, code=killed, status=9/KILL
Sep 05 04:38:40 0970caef98b3 systemd[1]: app.service: Failed with result 'signal'.
Sep 05 04:38:41 0970caef98b3 systemd[1]: app.service: Scheduled restart job, restart counter is at 1.
Sep 05 04:38:41 0970caef98b3 systemd[1]: Started app.service - App API server (lesson 11).
Sep 05 04:38:41 0970caef98b3 python3[164]: listening on 8080 as uid 997, cwd /opt/app, HOME=/var/lib/app
```

`reload` is the `ExecReload=` line, a `SIGHUP`; `stop` is `TERM`, the drain, and a clean exit that `on-failure` correctly does not restart:

```console
$ systemctl reload app;  journalctl -u app | tail -2
Sep 05 04:38:42 0970caef98b3 python3[164]: SIGHUP: reloading config
Sep 05 04:38:42 0970caef98b3 systemd[1]: Reloaded app.service - App API server (lesson 11).
$ systemctl stop app;  journalctl -u app | tail -4;  systemctl is-active app
Sep 05 04:38:43 0970caef98b3 systemd[1]: Stopping app.service - App API server (lesson 11)...
Sep 05 04:38:43 0970caef98b3 python3[164]: SIGTERM: draining, closing the socket, exiting 0
Sep 05 04:38:43 0970caef98b3 systemd[1]: app.service: Deactivated successfully.
Sep 05 04:38:43 0970caef98b3 systemd[1]: Stopped app.service - App API server (lesson 11).
inactive
```

The two failures you will diagnose most, reproduced on purpose. A wrong `ExecStart` path is `203/EXEC` (the same 203 the script uses), and a crash loop hits the limit:

```console
$ systemctl status broken | grep -E 'Active|Process'
     Active: activating (auto-restart) (Result: exit-code) since Sat 2026-09-05 04:38:44 UTC; 386ms ago
    Process: 212 ExecStart=/opt/app/does-not-exist (code=exited, status=203/EXEC)
$ systemctl status crashy | grep -E 'Active|repeated';  systemctl show crashy -p NRestarts
     Active: failed (Result: exit-code) since Sat 2026-09-05 04:38:45 UTC; 2s ago
Sep 05 04:38:45 0970caef98b3 systemd[1]: crashy.service: Start request repeated too quickly.
NRestarts=3
```

A timer every two seconds, the calendar checker, and the `%` trap in the flesh:

```console
$ systemctl enable --now tick.timer;  sleep 5;  systemctl list-timers | grep tick
Sat 2026-09-05 04:38:54 UTC   1s   Sat 2026-09-05 04:38:52 UTC   809ms ago   tick.timer   tick.service
$ journalctl -u tick | grep 'tick at' | tail -1
Sep 05 04:38:52 0970caef98b3 sh[310]: tick at /tmp                   <- %T was a specifier; the shipped unit writes %%T
$ systemd-analyze calendar '*-*-* 03:15:00' | tail -2
    Next elapse: Sun 2026-09-06 03:15:00 UTC
       From now: 22h left
```

Then the cgroup the unit lives in, the security score (a to-do list: the unit above still scores `8.3 EXPOSED`, and each further `Protect*` line lowers it), the journal as JSON, `cron`, and `logrotate` doing a forced rotation and sending the `HUP` that the service answers:

```console
$ cat /proc/$(systemctl show app -p MainPID --value)/cgroup
0::/system.slice/app.service
$ systemd-analyze security app | tail -1
→ Overall exposure level for app.service: 8.3 EXPOSED :-(
$ journalctl -u app -n 1 -o json | cut -c1-120
{"SYSLOG_IDENTIFIER":"systemd","JOB_RESULT":"done","MESSAGE":"Started app.service - App API server (lesson 11).","_SYSTEMD_UNIT":...
$ echo '*/5 * * * * /opt/app/bin/backup.sh >> /var/log/app/backup.log 2>&1' | crontab -;  crontab -l
*/5 * * * * /opt/app/bin/backup.sh >> /var/log/app/backup.log 2>&1
$ logrotate -f /etc/logrotate.d/app;  ls -l /var/log/app/;  journalctl -u app | tail -1
-rw-r----- 1 app  app      0 Sep  5 04:38 app.log
-rw-r--r-- 1 root root 23893 Sep  5 04:38 app.log.1
Sep 05 04:38:54 0970caef98b3 python3[323]: SIGHUP: reloading config
```

`docker stop sysd` when you are done. Everything you just did is what the capstone (lesson 18) does on a blank box, from memory.

## Ship It

The artifact for this lesson is a checklist: [`outputs/checklist-systemd-unit-for-a-backend.md`](../outputs/checklist-systemd-unit-for-a-backend.md). It is the unit file above with every directive explained and the reason it is there; the operating commands in the order to run them (`verify`, `daemon-reload`, `enable --now`, `status`, `restart`, `reload`, `stop`, `cat`, `edit`, `reset-failed`) and the `journalctl` forms; a timer unit to replace a cron job and the cron form if you keep it; a `logrotate` stanza with the reopen step that prevents the invisible full disk; and the eight-step diagnosis for a unit that will not start or keeps restarting, keyed on the status codes you just saw (`203/EXEC`, `217/USER`, `signal=KILL`, `start-limit-hit`).

## Think about it

1. A service's `ExecStart=/bin/sh -c 'cd /opt/app && python3 server.py'`. `systemctl stop` takes exactly `TimeoutStopSec` and ends with `signal=KILL`, and the server's drain message never appears. Explain with lesson 03 and lesson 10, and write the one-word fix.
2. `Restart=always` on a database migration job that exits 0 when done. What happens, and which two directives should it have instead?
3. The nightly backup timer never ran during a week when the box was rebooting every night at 03:10. Which `[Timer]` directive was missing, and how does `systemctl list-timers` show it?
4. `journalctl -u app` shows the service's log lines arriving in bursts of about 30, minutes apart, while `curl` shows it serving requests continuously. Which lesson 07 mechanism, which unit directive fixes it, and why does the fix belong in the unit rather than the code?

## Key takeaways

- **Boot** is firmware, bootloader, kernel, then one process: **PID 1, `systemd`**, from which every other process descends. A container skips the first three stages and its PID 1 is whatever `CMD` names.
- A **supervisor** starts a unit (fork, `setsid`, stdout to the journal, drop privileges, exec), watches it (`waitpid`, reap orphans), **restarts by policy** (`on-failure` skips a clean exit 0; a **start limit** brakes a crash loop; `RestartSec` waits), and **stops by contract** (`TERM`, `TimeoutStopSec`, `KILL`).
- A **unit file** is three sections: `[Unit]` (`After=`, `Wants=`, the start limit), `[Service]` (`Type=simple`, `User=`, `WorkingDirectory=`, `ExecStart=` absolute and shell-less, `EnvironmentFile=`, `*Directory=`, `Restart=`, `TimeoutStopSec=`, `KillMode=`, `Protect*`), `[Install]` (`WantedBy=multi-user.target`). **`daemon-reload` after every edit**; `%%` for a percent sign.
- `enable` is "at boot", `start` is "now", `status` is the supervisor's view, `show -p NRestarts` is the count, **`journalctl -u`** is the log: stdout, stamped and indexed, no log file needed. Keep the program unbuffered.
- **Timers** replace cron with a journal and `Persistent=`; `cron` remains fine for a one-liner with absolute paths and a redirect. **`logrotate`** must make the service reopen its log (`HUP` or `copytruncate`) or the disk fills invisibly.
- `203/EXEC` is a bad path, `217/USER` a missing user, `signal=KILL` on stop is an ignored `TERM`, `start-limit-hit` is a crash loop; the checklist has the rest.

Next: [Reading the Machine](../12-reading-the-machine/). The service is supervised. Now the questions you ask when it is slow anyway: what the load average means, why `free` says the RAM is gone, how a disk is the bottleneck when the CPU is idle, and who killed the process with signal 9.
