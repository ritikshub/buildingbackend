---
name: checklist-ssh-setup-and-hardening
description: Setting up SSH the way a server should have it — one ed25519 key per person and per machine, an agent, a config file with aliases and a jump host, sshd hardened to keys only with no root login, tunnels for databases, scp and rsync for files, tmux for long jobs — and the diagnosis when a login is refused
phase: 01
lesson: 17
---

# SSH: set it up once, harden it once

## 1 · Your side: keys, agent, config

- [ ] **One key per person per laptop**, ed25519, with a passphrase:
      ```bash
      ssh-keygen -t ed25519 -C "you@laptop-2026"       # ~/.ssh/id_ed25519 (private, mode 600) and .pub (public)
      ssh-keygen -lf ~/.ssh/id_ed25519.pub              # its fingerprint, for the record
      ```
      The private key never leaves the machine it was made on. No copying it to servers, no sharing, no pasting into chat. A new laptop gets a new key; the old one is removed from every `authorized_keys`.
- [ ] `~/.ssh` is `700`, private keys `600`, `authorized_keys` and `config` `600`. ssh refuses a world-readable key (`UNPROTECTED PRIVATE KEY FILE`) and silently ignores a group-writable `authorized_keys` on the server.
- [ ] **The agent holds the unlocked key** so the passphrase is typed once per session: `eval $(ssh-agent -s); ssh-add ~/.ssh/id_ed25519`; `ssh-add -l` lists what is loaded. On macOS, `ssh-add --apple-use-keychain`. Never `ForwardAgent yes` to a host you do not fully trust: the host's root can use your agent while you are connected. Use `-J` (a jump host) instead.
- [ ] **`~/.ssh/config`** turns command lines into names:
      ```text
      Host *
          ServerAliveInterval 30
          ServerAliveCountMax 3
          IdentitiesOnly yes

      Host bastion
          HostName bastion.example.com
          User ops
          IdentityFile ~/.ssh/id_ed25519

      Host app-*
          User ops
          ProxyJump bastion

      Host app-prod
          HostName 10.0.1.20
      ```
      `ssh app-prod` then goes through the bastion with the right user and key. `ssh -G app-prod` prints the effective settings. `Host *` defaults go last or first consistently; the first match wins per option.
- [ ] Install a public key on a server with `ssh-copy-id -i ~/.ssh/id_ed25519.pub user@host` (or append it to `~user/.ssh/authorized_keys` there, mode 600, directory 700).
- [ ] `known_hosts`: the first connection asks you to confirm the server's fingerprint; the answer should come from somewhere out of band (the provider's console, the person who built it), not from the prompt itself. A changed key later (`REMOTE HOST IDENTIFICATION HAS CHANGED`) is either a rebuilt server or an attack; find out which before `ssh-keygen -R host`.

## 2 · The server: sshd hardened

Drop-in file (`/etc/ssh/sshd_config.d/10-hardening.conf` on Debian/Ubuntu), then `sshd -t` to check and `systemctl reload ssh` to apply:

```text
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin no
PubkeyAuthentication yes
MaxAuthTries 3
LoginGraceTime 30
X11Forwarding no
AllowUsers ops dev
ClientAliveInterval 300
ClientAliveCountMax 2
```

- [ ] **Keys only.** With `PasswordAuthentication no` the internet's password guessing (thousands of attempts a day on any public port 22) stops mattering. Set it only after your key works.
- [ ] **No root login.** Operators are themselves, and `sudo` for the rest (lesson 06). Services do not log in at all (`nologin`).
- [ ] **`AllowUsers` or `AllowGroups`**: the list of accounts that may connect, so a stray account with a key is not a door.
- [ ] `sshd -T` prints the effective configuration; `journalctl -u ssh` shows every `Accepted publickey` and `Failed password`, with the source address. `fail2ban` or the cloud firewall (lesson 14) limits who can even try.
- [ ] Moving the port (`Port 2222`) reduces log noise, not risk. A firewall rule limiting 22 to known networks reduces risk.
- [ ] Host keys in `/etc/ssh/ssh_host_*_key` are the server's identity; back them up with the box's definition, or a rebuilt server will scare every client with a changed fingerprint. Publish fingerprints where operators can check them.
- [ ] Certificates (`ssh-keygen -s ca_key`) scale past a dozen servers: one CA trusted by all hosts, short-lived user certificates, no `authorized_keys` to manage. Worth it when the fleet grows.

## 3 · Tunnels: reach what is not exposed

```bash
ssh -L 5432:127.0.0.1:5432 app-prod              # local 5432 → the server's loopback 5432: psql -h localhost, the database never exposed
ssh -L 5432:db.internal:5432 bastion              # local 5432 → a third host as seen from the bastion
ssh -N -f -L 5432:127.0.0.1:5432 app-prod         # -N: no shell; -f: background; kill it with pkill -f 'ssh -N -f -L'
ssh -R 8080:127.0.0.1:3000 app-prod               # the server's 8080 → your laptop's 3000 (a webhook to your dev box)
ssh -D 1080 bastion                                # a SOCKS proxy: browsers and curl -x socks5h://localhost:1080 through the bastion
ssh -J bastion app-prod                            # jump: one hop through the bastion, keys stay on your laptop
```

- [ ] A tunnel is a channel inside the encrypted connection: the database port stays bound to `127.0.0.1` on the server (lesson 14), and only key-holders can reach it.
- [ ] `-R` binds on the server's loopback unless `GatewayPorts yes`; do not enable that casually.
- [ ] `ServerAliveInterval` keeps long tunnels alive through NAT timeouts; `autossh` restarts them.

## 4 · Files: scp and rsync

```bash
scp file app-prod:/tmp/                           # one file, one direction; -r for a tree; -P for a port (capital, unlike ssh -p)
scp app-prod:/var/log/app/app.log .               # back the other way
rsync -avz --progress src/ app-prod:/opt/app/     # a tree: only changed blocks, preserves modes and times, compressed on the wire
rsync -avn --delete src/ app-prod:/opt/app/       # -n: dry run FIRST when --delete is involved
rsync -a --exclude '.git' --exclude 'node_modules' src/ app-prod:/opt/app/
sftp app-prod                                     # interactive get/put when you need to browse
```

- [ ] `rsync src/ dst/` copies the *contents* of `src` into `dst`; `rsync src dst/` creates `dst/src`. The trailing slash on the source is the whole difference (lesson 05's checklist).
- [ ] `rsync -a` on a second run transfers only what changed: the deploy of a code tree, a backup, a log collection. `--delete` mirrors removals and needs a dry run every time.
- [ ] A big upload goes through `rsync -P` (progress + partial: resumable) rather than `scp`.

## 5 · Long-running work

- [ ] Anything that must outlive your connection runs in **`tmux`** (`tmux new -s work`, detach with `Ctrl+b d`, `tmux attach -t work`) or is a **unit** (lesson 11). Not `nohup`, not `&`, not hope (lesson 10).
- [ ] `ssh host 'command'` runs one command and exits; `ssh -t host 'top'` allocates a pty for interactive programs; `ssh host bash < script.sh` runs a local script remotely; `ssh -n` when stdin must not be consumed (in loops).
- [ ] Automation uses a **dedicated key** with a `command=` restriction in `authorized_keys` (`command="/usr/local/bin/backup" ssh-ed25519 AAAA...`) so the key can do one thing.

## 6 · Login refused: in order

1. `ssh -vv user@host` on the client: which key was offered, which methods the server accepts (`Authentications that can continue`), whether the host key was accepted.
2. On the server, `journalctl -u ssh -n 30`: `Invalid user` (the account does not exist or `AllowUsers` excludes it), `Failed publickey` (the key is not in `authorized_keys`, or the file's permissions are wrong), `Authentication refused: bad ownership or modes` (the `~/.ssh` directory or file modes, or a home directory writable by others), `Connection closed by ... [preauth]` (`MaxAuthTries`, or a client offering too many keys: `IdentitiesOnly yes`).
3. `ls -ld ~user ~user/.ssh ~user/.ssh/authorized_keys` on the server: `755`/`700`/`600`, owned by the user.
4. `sshd -T | grep -iE 'pubkey|password|allowusers|permitroot'`: what the server actually allows.
5. Nothing on port 22 at all: lesson 14's ladder (`nc -zv host 22`), the firewall, `systemctl status ssh`.
6. Locked out with keys-only and a lost key: the provider's console or serial access is the only door. Which is why two people hold keys, and the host is in configuration management.
