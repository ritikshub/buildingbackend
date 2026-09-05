---
name: checklist-systemd-unit-for-a-backend
description: The unit file for a backend service, directive by directive, with the reason for each — user and directories, environment and secrets, restart and stop behaviour, logging, resource limits and hardening — plus the operate-it commands, the timer that replaces a cron job, log rotation, and the diagnosis when a unit will not start or keeps restarting
phase: 01
lesson: 11
---

# A systemd unit for a backend service

Copy the unit, change the four names (`app`, its user, its path, its
port), and go through the checklist once. Every directive below is there
because leaving it out has caused an outage somewhere.

## 1 · The unit

```ini
# /etc/systemd/system/app.service
[Unit]
Description=App API server
Documentation=https://example.internal/runbooks/app
After=network-online.target postgresql.service
Wants=network-online.target
StartLimitIntervalSec=60
StartLimitBurst=5

[Service]
Type=simple
User=app
Group=app
WorkingDirectory=/opt/app
ExecStart=/opt/app/.venv/bin/python3 -m app.server --port 8080
ExecReload=/bin/kill -HUP $MAINPID
EnvironmentFile=/etc/app/app.env
Environment=PYTHONUNBUFFERED=1
UMask=027
RuntimeDirectory=app
StateDirectory=app
LogsDirectory=app
Restart=on-failure
RestartSec=2
TimeoutStartSec=30
TimeoutStopSec=30
KillMode=mixed
KillSignal=SIGTERM
LimitNOFILE=65536
MemoryMax=1G
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
PrivateTmp=true
ReadWritePaths=/var/lib/app /var/log/app
AmbientCapabilities=

[Install]
WantedBy=multi-user.target
```

## 2 · Directive by directive

**[Unit]**
- [ ] `After=network-online.target` plus `Wants=network-online.target`: start after the network is actually up, not merely configured. `After=` orders; `Wants=` pulls the target in. Add the database unit if it runs on the same box; it does not wait for a remote one, so the app must retry its first connection (Phase 2, lesson 14).
- [ ] `StartLimitIntervalSec=60` / `StartLimitBurst=5`: more than five starts in a minute and systemd stops trying and marks the unit `failed`. Without it a crash loop restarts forever and floods the log; with it, `systemctl reset-failed app` is the manual reset.

**[Service]**
- [ ] `Type=simple`: the `ExecStart` process **is** the service and does not fork into the background. Almost every modern server. `Type=forking` is for old daemons that daemonise themselves (then set `PIDFile=`); `Type=notify` for services that call `sd_notify` when ready; `Type=oneshot` for jobs that run and exit (backups, migrations).
- [ ] `User=` and `Group=`: the service user from lesson 06. Never omitted; omitted means root.
- [ ] `WorkingDirectory=`: relative paths in the app resolve here. Default is `/`.
- [ ] `ExecStart=`: an **absolute path** to the interpreter or binary; no shell, so no `&&`, no `$VAR` expansion beyond `${VAR}` from `Environment=`, no redirection. Wrap in `/bin/sh -c '...'` only when you must, and then `exec` the real program so signals reach it.
- [ ] `ExecReload=`: what `systemctl reload` sends. `$MAINPID` is the main process. Only if the program reloads on `SIGHUP`; otherwise omit, and `reload` becomes an error rather than a lie.
- [ ] `EnvironmentFile=`: `KEY=value` lines, one per line, no `export`, no quotes needed. Mode `640 root:app` (lesson 06). Secrets go here or in a secrets manager, never in the unit (which is world-readable).
- [ ] `Environment=PYTHONUNBUFFERED=1` (or the equivalent for the runtime): logs reach the journal as they happen (lesson 07).
- [ ] `UMask=027`: files the service creates are `640`, directories `750`.
- [ ] `RuntimeDirectory=app` creates `/run/app` (owned by `User=`) at start and removes it at stop; `StateDirectory=app` creates `/var/lib/app`; `LogsDirectory=app` creates `/var/log/app`. No install script needed for the runtime half of lesson 04's layout.
- [ ] `Restart=on-failure`: restart on a non-zero exit or a signal, not on a clean exit 0 (which means "I was asked to stop, or I finished"). `always` for services that must run even if they exit 0; `no` for oneshots.
- [ ] `RestartSec=2`: the pause before a restart. Too short hammers a dependency that is down; too long is downtime.
- [ ] `TimeoutStartSec=`: how long the service may take to start (for `Type=notify`, to become ready) before it is killed.
- [ ] `TimeoutStopSec=30`: the grace period after `SIGTERM` before `SIGKILL` (lesson 10). Set it to the longest request the service will drain, plus margin.
- [ ] `KillMode=mixed`: `SIGTERM` to the main process only, `SIGKILL` to the whole cgroup at the deadline. `control-group` (the default) sends TERM to every process in the cgroup at once, which can kill workers before the parent has drained them; `process` leaves children running, which is almost never right.
- [ ] `LimitNOFILE=65536`: the descriptor limit (lesson 12). The default of 1024 is too low for any server that holds connections.
- [ ] `MemoryMax=1G` (and `CPUQuota=200%` if needed): a cgroup limit; exceed memory and the OOM killer takes this unit only, not the box (Phase 11).
- [ ] Hardening: `NoNewPrivileges=true` (no setuid escalation), `ProtectSystem=strict` (`/usr`, `/etc`, `/boot` read-only), `ProtectHome=true`, `PrivateTmp=true` (its own `/tmp`), `ReadWritePaths=` for exactly the directories it writes. `systemd-analyze security app` scores the result; aim for the low numbers.
- [ ] `AmbientCapabilities=CAP_NET_BIND_SERVICE` only if it must bind a port below 1024 (lesson 06); otherwise a reverse proxy in front.

**[Install]**
- [ ] `WantedBy=multi-user.target`: `systemctl enable` creates the symlink that starts it at boot. Without this section, `enable` fails.

## 3 · Operating it

```bash
systemd-analyze verify /etc/systemd/system/app.service   # syntax and references, before daemon-reload
systemctl daemon-reload            # after every edit of a unit file; nothing takes effect without it
systemctl enable --now app         # start now and at every boot
systemctl status app               # active/failed, Main PID, recent log lines, the cgroup tree
systemctl restart app              # stop (TERM, wait, KILL) then start
systemctl reload app               # ExecReload= (usually SIGHUP): config without dropping connections
systemctl stop app                 # TERM, TimeoutStopSec, KILL
systemctl disable app              # do not start at boot (does not stop it now)
systemctl cat app                  # the unit as loaded, including drop-ins
systemctl edit app                 # a drop-in override in /etc/systemd/system/app.service.d/override.conf
systemctl show app -p MainPID,NRestarts,ActiveState,SubState,Result
systemctl reset-failed app         # clear a start-limit-hit before starting again
systemctl list-units --failed      # anything on the box that is failed right now
```

```bash
journalctl -u app                  # this unit's log, oldest first
journalctl -u app -f               # follow (tail -f)
journalctl -u app -n 200 --no-pager
journalctl -u app --since '1 hour ago' -p warning   # priority filter: emerg alert crit err warning notice info debug
journalctl -u app -o json | jq .   # structured fields: _PID, _SYSTEMD_UNIT, MESSAGE, PRIORITY
journalctl -k                      # the kernel log (dmesg): OOM kills live here
journalctl --disk-usage;  journalctl --vacuum-size=500M
```

- [ ] After editing the unit: `verify`, `daemon-reload`, `restart`, `status`, in that order.
- [ ] `enable` and `start` are different verbs: one is "at boot", the other is "now". `enable --now` is both.
- [ ] `systemctl status` shows the last ten log lines; `journalctl -u` shows all of them. Read the journal before concluding anything.

## 4 · Timers instead of cron

```ini
# /etc/systemd/system/app-backup.service
[Unit]
Description=Nightly app backup
[Service]
Type=oneshot
User=app
ExecStart=/opt/app/bin/backup.sh

# /etc/systemd/system/app-backup.timer
[Unit]
Description=Run app-backup nightly
[Timer]
OnCalendar=*-*-* 03:15:00
RandomizedDelaySec=10m
Persistent=true
[Install]
WantedBy=timers.target
```

- [ ] `systemctl enable --now app-backup.timer`; `systemctl list-timers` shows the next and last run; `journalctl -u app-backup` has the output, with no mail setup.
- [ ] `Persistent=true` runs a missed job at the next boot; `RandomizedDelaySec` spreads a fleet's jobs. `systemd-analyze calendar '*-*-* 03:15:00'` checks the expression.
- [ ] Cron still exists and is fine for a one-liner: `crontab -e`, five fields `min hour dom mon dow`, `MAILTO=` or `>> log 2>&1` on every line, absolute paths, and remember the empty environment (lesson 09).

## 5 · Log rotation

If the service writes files under `/var/log/app` rather than to the journal:

```text
# /etc/logrotate.d/app
/var/log/app/*.log {
    daily
    rotate 14
    compress
    delaycompress
    missingok
    notifempty
    create 0640 app app
    postrotate
        systemctl kill -s HUP app.service
    endscript
}
```

- [ ] The service reopens its log on `SIGHUP` (or use `copytruncate`, which loses a few lines but needs nothing from the program). Without either, the service keeps writing to the renamed, then deleted, inode and the disk fills invisibly (lesson 04, lesson 05).
- [ ] `logrotate -d /etc/logrotate.d/app` is a dry run; `logrotate -f` forces one. It runs from `logrotate.timer` daily.
- [ ] The journal rotates itself; set `SystemMaxUse=` in `/etc/systemd/journald.conf` so it cannot fill `/var`.

## 6 · It will not start, or keeps restarting

1. `systemctl status app` and `journalctl -u app -n 50 --no-pager`. The answer is nearly always in the last twenty lines.
2. `status=203/EXEC`: `ExecStart` path wrong, not executable, or a bad shebang (lesson 03's runbook). `status=217/USER`: the `User=` does not exist. `status=200/CHDIR`: `WorkingDirectory=` missing. `status=1` or any small number: the program exited on its own; read its log.
3. `code=killed, signal=KILL` on **stop**: it ignored TERM or drained longer than `TimeoutStopSec`. On **start** or at random: the OOM killer (`journalctl -k`), or `MemoryMax`.
4. `start request repeated too quickly` / `start-limit-hit`: a crash loop hit the burst limit; fix the cause, then `systemctl reset-failed app`.
5. `Failed to determine user credentials`, `Permission denied` on a file: lesson 06. `id app`, `ls -l` on the paths, `ProtectSystem=`/`ReadWritePaths=` too strict.
6. Works with `systemctl start`, fails at boot: an `After=` is missing (the network, a mount, a database), so it started before something it needs. `systemd-analyze critical-chain app`.
7. Port in use: `ss -tlnp`; the old copy, or `KillMode=process` left a child holding the socket.
8. Changed the unit, nothing changed: `daemon-reload`. Changed the env file, nothing changed: `restart` (not `reload`, unless the program re-reads it on HUP).
