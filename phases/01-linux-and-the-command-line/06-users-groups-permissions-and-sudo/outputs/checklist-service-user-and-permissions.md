---
name: checklist-service-user-and-permissions
description: How to run a backend service as a dedicated user with the least permissions that work — the user and group to create, the exact mode and owner for config, secrets, data, logs and sockets, the umask, the sudo rules for the humans who operate it, and the audit that catches the box drifting back to root
phase: 01
lesson: 06
---

# A service user, and the permissions around it

The rule: **a service runs as its own user, reads config owned by root,
writes only to directories it owns, and never runs as root.** Everything
below is that rule applied to one service called `app`, followed by the
checks that prove it stayed true.

## 1 · Create the identity

- [ ] A **system** group and user, no password, no login shell, no real home:
      ```bash
      groupadd --system app
      useradd  --system --gid app --home-dir /var/lib/app --shell /usr/sbin/nologin app
      id app          # uid=999(app) gid=999(app) groups=999(app)
      ```
      `--system` picks a uid below 1000, so the user never shows up on login screens or in "real users" reports. `nologin` means a leaked password would be useless: there is none, and the shell refuses anyway.
- [ ] The uid is **stable**. If the same service runs on many hosts or in containers with mounted volumes, pin it (`useradd --uid 1500 ...`) so the files on the volume mean the same owner everywhere. An inode stores a number, not a name.
- [ ] Nothing else runs as this user. One user per service; a compromise of one does not reach the others' files.

## 2 · Lay out the files (mode and owner per kind)

| path | owner:group | mode | why |
|---|---|---|---|
| `/usr/local/bin/app`, `/opt/app/` | `root:root` | `755` / dirs `755` | the service must not be able to modify its own code |
| `/etc/app/` | `root:app` | `750` | root writes config, the service reads it, nobody else enters |
| `/etc/app/app.yaml` | `root:app` | `640` | readable by the service through the group, not writable by it |
| `/etc/app/secrets.env` | `root:app` | `640` (or `600` + `root` running the loader) | never `644`; `ls -l /etc/app` must show no `r` in the last triplet |
| `/var/lib/app/` | `app:app` | `750` | the one place it writes persistent data; others stay out |
| `/var/log/app/` | `app:app` | `750` (or `2750` so rotated logs keep the group) | it writes; operators read via the group or via `sudo` |
| `/run/app/` | `app:app` | `755` (`RuntimeDirectory=app` in the unit creates it) | sockets and PID files; world may traverse to reach the socket |
| `/run/app/app.sock` | `app:app` or `app:www-data` | `660` | only the reverse proxy's user may connect |
| `/var/cache/app/` | `app:app` | `750` | regenerable; not backed up |

- [ ] **Directories get `x`, files do not** unless they are programs. `chmod -R 755` on a data tree makes every data file "executable," which is wrong and which some tools flag. Use `find /var/lib/app -type d -exec chmod 750 {} +` and `find /var/lib/app -type f -exec chmod 640 {} +` when fixing a tree.
- [ ] **Group, not world.** When a second user (the reverse proxy, an operator, a backup job) needs read access, add them to the `app` group or set the file's group; never open the third triplet.
- [ ] The service's **umask** is set in the unit (`UMask=027`) so files it creates come out `640` and directories `750` without every code path remembering to chmod.
- [ ] `chown` is done by root, once, at deploy. The service never needs to chown, and a service that can `chown` is usually one that is running as root.

## 3 · Prove the service cannot do what it should not

Run these **as the service user** (`sudo -u app -s`, or `su -s /bin/sh app -c '...'`):

- [ ] `cat /etc/app/app.yaml` works. `echo >> /etc/app/app.yaml` is `Permission denied`.
- [ ] `touch /var/lib/app/x` works. `touch /etc/x`, `touch /usr/local/bin/x`, `touch /opt/app/x` are all denied.
- [ ] `cat /etc/shadow` is denied. `ls /root` is denied. `cat /etc/app/../nginx/secret` for any other service's secrets is denied.
- [ ] Binding a port below 1024 fails (`EACCES`). If the service must listen on 80 or 443, give it `CAP_NET_BIND_SERVICE` (`AmbientCapabilities=CAP_NET_BIND_SERVICE` in the unit, or `setcap 'cap_net_bind_service=+ep' /usr/local/bin/app`) or put a reverse proxy in front. Never run as root for a port number.
- [ ] `id` inside the running process says the service user: `ps -o user= -p $(pgrep -f app)` or `cat /proc/<pid>/status | grep Uid`. A unit with `User=app` but an `ExecStart` that calls `sudo` or a setuid wrapper is root anyway.

## 4 · The humans

- [ ] Operators log in as **themselves** (their own user, their own key, lesson 17), never as `root` and never as `app`. `PermitRootLogin no` in `sshd_config`.
- [ ] They get **`sudo` for the specific commands** the job needs, in a file under `/etc/sudoers.d/`, validated with `visudo -c`:
      ```text
      # /etc/sudoers.d/app-operators
      %app-ops ALL=(ALL) /usr/bin/systemctl restart app, /usr/bin/systemctl status app, /usr/bin/journalctl -u app
      %app-ops ALL=(app) NOPASSWD: ALL
      ```
      The second line lets them become the service user (`sudo -u app -s`) to inspect its files, without becoming root.
- [ ] `sudo -l` as each operator shows exactly that list and nothing broader. `ALL=(ALL) ALL` is a root account with extra steps; reserve it for the people who would have root anyway.
- [ ] `sudo` logs every command to the auth log (`journalctl _COMM=sudo`). Someone reads it.
- [ ] Nobody edits `/etc/sudoers` with a plain editor. `visudo` checks syntax; a broken sudoers file locks everyone out of root at once.
- [ ] `sudo` resets `PATH` to `secure_path` and drops most environment variables. Commands in sudoers use absolute paths, and "works for me, not with sudo" is almost always this (lesson 03's runbook).

## 5 · The audit (run monthly, and after every incident)

```bash
# anything running as root that is not the kernel or init
ps -eo user,pid,comm | awk '$1=="root" && $3!~/^(kthreadd|kworker|systemd|ksoftirqd|migration|rcu_)/' | head -30

# setuid and setgid programs: each is a root-escalation path, so the list should be short and known
find / -xdev \( -perm -4000 -o -perm -2000 \) -type f -exec ls -l {} + 2>/dev/null

# world-writable files and directories outside /tmp (and dirs without the sticky bit)
find / -xdev -type f -perm -0002 2>/dev/null
find / -xdev -type d -perm -0002 ! -perm -1000 2>/dev/null

# secrets that anyone can read
find /etc /opt /srv /var/lib -type f \( -name '*.env' -o -name '*secret*' -o -name '*.key' -o -name '*.pem' \) -perm -0004 2>/dev/null

# files owned by users that no longer exist (a uid with no /etc/passwd entry)
find / -xdev -nouser -o -nogroup 2>/dev/null | head

# who can sudo what
grep -rE 'ALL' /etc/sudoers /etc/sudoers.d/ ; getent group sudo wheel

# accounts that can log in
awk -F: '$7 !~ /(nologin|false)$/ {print $1, $3, $7}' /etc/passwd
```

- [ ] Every line of output is either expected and documented, or fixed before the audit is closed.
- [ ] A service that "needs" root is investigated for the one capability it actually needs; it is nearly always `CAP_NET_BIND_SERVICE`, a directory it does not own, or a port it could get from a proxy.

## 6 · When it goes wrong: Permission denied

1. `id` in the failing context: which uid and groups is the check being run against? (Not the one you think, under systemd, cron or sudo.)
2. `ls -ld` every component of the path from `/` down: the failing bit is often `x` missing on a **directory** above the file, not on the file.
3. `stat -c '%A %U:%G %n'` on the file: which triplet applies to this uid, and does it have the bit? Only one triplet ever applies.
4. For a delete or create: `w` on the **directory**, and the sticky bit if the directory is shared.
5. Still denied with the bits right: SELinux or AppArmor (`dmesg | grep -i denied`, `ausearch -m avc`), a read-only mount (`findmnt -T path`), an immutable attribute (`lsattr`), or a capability the process lacks (`capsh --print`).
