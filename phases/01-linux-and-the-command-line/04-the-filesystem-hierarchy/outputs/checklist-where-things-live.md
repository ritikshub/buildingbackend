---
name: checklist-where-things-live
description: Where a backend service's files belong on a Linux box (config, binary, data, logs, runtime state, cache, temp, secrets) and where to look for someone else's — the Filesystem Hierarchy Standard applied to one deployed service, plus the find, du, df and stat recipes that locate things fast
phase: 01
lesson: 04
---

# Where things live

Two uses. **Deploying**: put each kind of file where the Filesystem
Hierarchy Standard, `systemd`, log rotation, backups and the next engineer
expect it. **Investigating**: know where a service you did not write keeps
its config, its data and its logs, before you have read a line of its docs.

## 1 · One service, laid out correctly

For a service called `app`, run as its own user `app` (lesson 06):

| what | where | notes |
|---|---|---|
| the binary or entry point | `/usr/local/bin/app` or `/opt/app/bin/app` | `/usr/local` for things you installed by hand; `/opt/<name>` for self-contained trees with their own libs. Never in `/usr/bin` (the package manager owns it) |
| the code of an interpreted app + its venv | `/opt/app/` (`/opt/app/.venv/bin/python3`) | one directory, owned by root, readable by `app`, writable by nobody at runtime |
| system-wide configuration | `/etc/app/app.yaml`, `/etc/app/app.env` | text, owned by root, mode `640` with group `app` if it holds secrets; never writable by the service |
| the systemd unit | `/etc/systemd/system/app.service` | lesson 11 |
| persistent data (a database, uploads, queues) | `/var/lib/app/` | owned by `app`, mode `750`; the one directory that must be on a backed-up volume |
| logs | `/var/log/app/` (or none: log to stdout and let journald keep it) | owned by `app`; a `/etc/logrotate.d/app` entry so it never fills the disk |
| runtime state (PID file, Unix socket) | `/run/app/` | tmpfs, wiped at boot; created by `RuntimeDirectory=app` in the unit |
| caches that can be regenerated | `/var/cache/app/` | safe to delete at any time; not backed up |
| scratch during a request | `/tmp/` or `/var/tmp/` | `/tmp` is often tmpfs (RAM) and cleared at boot; `/var/tmp` survives reboot. Both are world-writable: use `mktemp`, never a fixed name |
| secrets | `/etc/app/secrets.env` mode `600`, or a secrets manager | never in the code tree, never in `/tmp`, never world-readable (Phase 8, lesson 13) |
| a home directory for the service user | `/var/lib/app` or `/nonexistent` | services do not need a real home; set it to the data dir or nothing |

- [ ] Nothing the service writes at runtime lives under `/etc`, `/usr` or `/opt`. Those are read-only in operation, which is what lets them be baked into an image and mounted read-only.
- [ ] Everything the service writes at runtime lives under `/var/lib/app`, `/var/log/app`, `/var/cache/app`, `/run/app` or `/tmp`. Those are the directories a volume, a backup or a `tmpfs` can be attached to independently.
- [ ] Paths in the config are absolute. Relative paths depend on the working directory, which is `/` under systemd and whatever you `cd`'d to in a terminal.
- [ ] `df -h /var/lib/app` and `df -i /var/lib/app` are on the dashboard. Disks fill; inodes run out (a million tiny files) while `df -h` still shows space.

## 2 · Investigating a box you did not build

Where a service you did not write keeps things, in the order to check:

- [ ] **Its unit file** says everything: `systemctl cat name` shows `ExecStart=` (the binary and its arguments), `WorkingDirectory=`, `EnvironmentFile=` (the config), `User=`. Lesson 11.
- [ ] **Its running process** says the rest: `ls -l /proc/<pid>/cwd` (where it runs), `ls -l /proc/<pid>/fd` (every file and socket it has open, including the log it is writing and the database it is reading), `tr '\0' '\n' < /proc/<pid>/environ` (its config as it sees it). Lesson 02's runbook.
- [ ] **The package** that installed it: `dpkg -L name` (Debian) or `rpm -ql name` (Red Hat) lists every file it owns, config included. Lesson 13.
- [ ] Config: `/etc/<name>/`, `/etc/<name>.conf`, `/etc/default/<name>` (Debian), `/etc/sysconfig/<name>` (Red Hat), `/opt/<name>/etc/`, `~/.config/<name>/` for per-user tools.
- [ ] Data: `/var/lib/<name>/`. Postgres: `/var/lib/postgresql/<version>/main`. Docker: `/var/lib/docker`. Redis: `/var/lib/redis`.
- [ ] Logs: `/var/log/<name>/` or `/var/log/<name>.log`, else `journalctl -u name`. Nginx: `/var/log/nginx/`. The system log: `journalctl` or `/var/log/syslog` / `/var/log/messages`.
- [ ] Sockets and PID files: `/run/<name>/`, `/run/<name>.pid`, `/var/run` (a symlink to `/run`).

## 3 · Finding things fast

```bash
# by name, anywhere (skip other filesystems and permission errors)
find / -xdev -name 'app.yaml' 2>/dev/null
find /etc -iname '*nginx*'                   # case-insensitive

# by what it is
find /var/lib/app -type f -name '*.db'        # regular files
find /etc -type l                              # symlinks (and: find -L /etc -type l  -> broken ones)
find / -xdev -type f -perm -4000               # setuid binaries (lesson 06)

# by size and age: what is filling the disk, what changed
find / -xdev -type f -size +100M 2>/dev/null | xargs ls -lh
find /var/log -type f -mmin -30                # modified in the last 30 minutes
find /var/lib/app -type f -mtime +30 -name '*.tmp' -delete   # careful: test without -delete first
du -xh --max-depth=1 / 2>/dev/null | sort -h | tail -12      # biggest top-level directories
du -sh /var/log/* | sort -h | tail -5

# what a file is, and where a link really goes
file /usr/local/bin/app                        # ELF binary? script? text?
stat /etc/app/app.yaml                         # inode, links, mode, owner, three timestamps
readlink -f /bin/sh                            # resolve every symlink to the final path
ls -li a b                                     # same inode number = the same file under two names

# space
df -h                                          # bytes per filesystem
df -i                                          # inodes per filesystem: the other way a disk is full
lsof +L1                                       # deleted files still held open: space df counts but du cannot find
```

## 4 · Traps

- [ ] **Deleted but still open.** `df` says full, `du` finds nothing. A process holds a deleted log open and the blocks stay allocated until it closes them: `lsof +L1`, then restart or signal the process (lesson 10). Rotating logs with `copytruncate` or `SIGHUP` exists for this reason.
- [ ] **`/tmp` is small and volatile.** It may be a tmpfs of a few hundred megabytes and is cleared on boot. Large scratch files go in `/var/tmp` or the service's own `/var/lib/app/tmp`.
- [ ] **`/bin`, `/sbin`, `/lib` are symlinks into `/usr`** on every current distribution. Scripts that special-case them are decades out of date; hardcode `/usr/bin/env` and let PATH resolve the rest.
- [ ] **Hidden files are not hidden.** `.env`, `.git`, `.ssh` are just names starting with a dot that `ls` skips without `-a`. `ls -la` before you conclude a directory is empty, and never serve a directory that contains one over HTTP.
- [ ] **Relative paths and the working directory.** "No such file" with the file plainly there means the process's cwd is not yours: `ls -l /proc/<pid>/cwd`.
- [ ] **Case matters.** `Config.yaml` and `config.yaml` are different files on Linux and the same file on a default macOS disk. Bugs that only appear after deploy often start here.
- [ ] **A symlink's target is relative to the link, not to you.** `ln -s config.yaml /etc/app/current` points at `/etc/app/config.yaml`; `ls -l` shows the raw text, `readlink -f` shows the truth.
- [ ] **Hard links cannot cross filesystems or point at directories**; symlinks can do both, and can dangle. A backup that follows symlinks can loop; `rsync -a` copies the link, `cp -rL` copies the target.
- [ ] **Inodes run out.** Millions of tiny files (sessions, cache entries, mail) on a filesystem sized for a few large ones. `df -i`. The fix is a different directory layout or a different filesystem, not more space.
