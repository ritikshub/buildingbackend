---
name: runbook-blank-box-to-running-backend
description: The whole phase as one procedure — from a blank Debian box to a supervised, firewalled, key-only backend in eight steps, each with the commands, the lesson it comes from, and the check that proves it, followed by the fault table for when the box misbehaves later
phase: 01
lesson: 18
---

# A blank box to a running backend

Assumes: a fresh Debian or Ubuntu server you can reach as root (or with
`sudo`), the application's code and unit file at hand, and the
operator's public key. `provision.sh` does all of this; the runbook is
the same thing at human speed, so you can do it by hand once and read
the script afterwards.

## 0 · Before you touch it (lessons 01, 02, 12)

```bash
cat /etc/os-release | head -2;  uname -r          # which distribution, which kernel
nproc; free -h; df -h /                            # what you have to work with
cat /proc/1/comm                                   # systemd? (a container says otherwise: lesson 11)
ss -tlnp                                           # what already listens; a fresh box has sshd and little else
```

- [ ] Note the numbers. A box that later "got slow" is diagnosed against this baseline.

## 1 · Packages (lesson 13)

```bash
apt-get update && apt-get install -y --no-install-recommends python3 curl nftables logrotate rsync openssh-server sudo
apt-mark showmanual                                # the list that defines this box
```

- [ ] Everything the service needs comes from the repository or is written into `provision.sh`; nothing is `curl | bash`.

## 2 · Users (lesson 06)

```bash
groupadd --system app
useradd --system --gid app --home-dir /var/lib/app --shell /usr/sbin/nologin app
useradd -m -s /bin/bash -G app ops                 # the human, in the app group
cat > /etc/sudoers.d/ops <<'S'
ops ALL=(ALL) /usr/bin/systemctl restart app, /usr/bin/systemctl status app, /usr/bin/systemctl reload app, /usr/bin/journalctl
ops ALL=(app) NOPASSWD: ALL
S
chmod 440 /etc/sudoers.d/ops && visudo -cf /etc/sudoers.d/ops
```

- [ ] `id app` shows a uid below 1000 and `nologin`; `sudo -l -U ops` shows exactly those commands.

## 3 · Code and config (lessons 04, 05, 06)

```bash
install -d -m 755 -o root -g root /opt/app                    # read-only half: root owns the code
install -m 644 -o root -g root app/server.py /opt/app/server.py
install -d -m 750 -o root -g app /etc/app
tmp=$(mktemp /etc/app/app.env.XXXXXX)                         # write beside, then rename: atomic
printf 'PORT=8080\nBIND=127.0.0.1\nSTATE_DIR=/var/lib/app\nGREETING=hello\n' > "$tmp"
chown root:app "$tmp"; chmod 640 "$tmp"; mv "$tmp" /etc/app/app.env
```

- [ ] `stat -c '%A %U:%G %n' /etc/app/app.env` is `-rw-r----- root:app`. `sudo -u app cat /etc/app/app.env` works; `sudo -u app sh -c 'echo x >> /etc/app/app.env'` is denied.
- [ ] The app binds `127.0.0.1`: a reverse proxy (Phase 11) will front it; nothing outside the box reaches 8080.

## 4 · The unit (lessons 10, 11)

```bash
install -m 644 app.service /etc/systemd/system/app.service
systemd-analyze verify /etc/systemd/system/app.service
systemctl daemon-reload
systemctl enable --now app
systemctl status app --no-pager
journalctl -u app -n 5 --no-pager
```

- [ ] `status` says `active (running)`, `Main PID` is a `python3` running as `app` (`ps -o user= -p PID`), and `/run/app`, `/var/lib/app`, `/var/log/app` exist owned by `app` (the `*Directory=` lines made them).
- [ ] `systemctl show app -p Restart,TimeoutStopSec,LimitNOFILE,MemoryMax`: `on-failure`, a drain window, a raised descriptor limit, a memory ceiling.

## 5 · Log rotation (lessons 04, 11)

```bash
cat > /etc/logrotate.d/app <<'LR'
/var/log/app/*.log { daily
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
LR
logrotate -d /etc/logrotate.d/app                  # dry run parses it
```

- [ ] The service logs to stdout (the journal) by default; the rotation stanza covers anything it writes under `/var/log/app`, and the `HUP` makes it reopen (lesson 04's deleted-but-open trap).

## 6 · The firewall (lesson 14)

```bash
cat > /etc/nftables.conf <<'NFT'
#!/usr/sbin/nft -f
flush ruleset
table inet filter {
  chain input { type filter hook input priority 0; policy drop;
    ct state established,related accept
    iif lo accept
    ip protocol icmp accept
    ip6 nexthdr icmpv6 accept
    tcp dport 22 accept
    tcp dport { 80, 443 } accept }
  chain forward { type filter hook forward priority 0; policy drop; }
  chain output  { type filter hook output priority 0; policy accept; }
}
NFT
nft -c -f /etc/nftables.conf && nft -f /etc/nftables.conf && systemctl enable nftables
nft list ruleset
```

- [ ] Default deny inbound, established traffic allowed back, loopback open, 22 and the web ports open, **8080 not open**. From another host: `nc -zv box 22` succeeds, `nc -zv box 8080` times out (drop), `nc -zv box 8081` times out too.
- [ ] Do this over a session you can afford to lose, or with a second session open; a wrong rule locks you out and the console is the only way back. (`ufw default deny incoming; ufw allow 22/tcp; ufw allow 80,443/tcp; ufw enable` is the same policy on Ubuntu.)

## 7 · SSH (lesson 17)

```bash
install -d -m 700 -o ops -g ops /home/ops/.ssh
echo "$OPS_PUBKEY" >> /home/ops/.ssh/authorized_keys
chown ops:ops /home/ops/.ssh/authorized_keys; chmod 600 /home/ops/.ssh/authorized_keys
ssh ops@box true                                   # FROM YOUR LAPTOP, with the key: must work before the next line
cat > /etc/ssh/sshd_config.d/10-hardening.conf <<'H'
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin no
MaxAuthTries 3
X11Forwarding no
AllowUsers ops
H
sshd -t && systemctl reload ssh
sshd -T | grep -E '^(passwordauthentication|permitrootlogin|allowusers) '
```

- [ ] From a **second** terminal: `ssh ops@box` works with the key; `ssh -o PubkeyAuthentication=no ops@box` is refused with `(publickey)`; `ssh root@box` is refused. Only then close the first session.
- [ ] `journalctl -u ssh` shows `Accepted publickey for ops`.

## 8 · Verify (lessons 12, 14, 15)

```bash
curl -sf http://127.0.0.1:8080/health
curl -sf --json '{"text":"first"}' http://127.0.0.1:8080/api/notes
curl -s http://127.0.0.1:8080/api/notes | jq .
ss -tlnp 'sport = :8080'                           # 127.0.0.1 only, owned by python3 as app
verify.sh                                          # every check in this runbook, as a script
```

- [ ] `verify.sh` reports 0 failures. Its checks are the phase: user and modes, unit and restart policy, bind address and firewall, journal and rotation, sshd.

## 9 · When it breaks later: the fault table

| symptom | first command | what you will see | the lesson |
|---|---|---|---|
| `curl` fails with connection refused | `systemctl status app` | `inactive`/`failed`, and the last log lines | 10, 11 |
| `failed`, `status=203/EXEC` | `systemctl cat app`; `ls -l` the `ExecStart` path | wrong path or not executable | 03, 11 |
| `failed`, `Failed to load environment files` | `stat -c '%A %U:%G' /etc/app/app.env` | not readable by group `app` | 06 |
| crash loop, `start request repeated too quickly` | `journalctl -u app -n 50` | the app's own traceback (a bad config value, a missing dependency) | 09, 11 |
| `Address already in use` in the log | `ss -tlnp 'sport = :8080'` | the process holding the port, and its PID | 10, 14 |
| up, but the client times out | `ss -tln`, `nft list ruleset`, from another host `nc -zv` | bound to loopback with no proxy, or the firewall dropping | 14 |
| up, but slow | `curl -w` timing; `top`, `vmstat 1 5`, `iostat -x 1 3`; `strace -p PID` | which of the five waits, which resource, which syscall | 12, 16, 01 |
| killed with signal 9, nobody did it | `journalctl -k \| grep -i 'killed process'` | the OOM killer, or `MemoryMax` | 12 |
| disk full | `df -h`, `df -i`, `du -xh --max-depth=1 /var \| sort -h`, `lsof +L1` | a log nobody rotated, or a deleted file still open | 04, 05 |
| cannot log in | `ssh -vv`, on the box `journalctl -u ssh -n 30` | which auth method failed, `AllowUsers`, file modes | 17 |
| `Permission denied` anywhere | `id` in the failing context; `ls -ld` every path component | the one triplet that applies | 06 |
| "it worked in my terminal" | `env -i`, the unit's `Environment=`, `WorkingDirectory=` | the empty environment a service gets | 03, 09, 11 |
| the box rebooted and the app did not come back | `systemctl is-enabled app`; `journalctl -b -1 -u app` | not enabled, or a dependency it needs was not `After=` | 11 |

Every row is `journalctl`, `ss`, `stat`, `strace`, `curl` or `nft`. There is no tool in the table that this phase did not build once by hand.
