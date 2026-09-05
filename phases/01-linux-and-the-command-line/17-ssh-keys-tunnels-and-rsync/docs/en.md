# SSH, Tunnels & rsync

> Before SSH there was `rsh`: a remote shell over a plain TCP socket. This lesson builds one in sixty lines, logs in, runs three commands, and then reads the whole session off the wire: the password `hunter2`, every command, every result, in the clear. Each of the four things wrong with that program is one part of SSH. Then the real thing on a booted box: an ed25519 key generated and installed, `Accepted publickey` in the server's log, an agent, a config file that turns `ssh -i key -p 22 user@host` into `ssh box`, a tunnel that reaches a port bound to the server's loopback, `scp`, an `rsync` second run that moves **1** file instead of 2, and `sshd` hardened until a password login answers `Permission denied (publickey)`.

## The Problem

Every lesson in this phase assumed you were already on the box. In practice you got there over SSH, and so did your deploy script, your database client, your log tail and your file copy. SSH is the front door of every server you will operate, which makes it the thing whose misconfiguration is most expensive: a leaked private key is every server it was installed on, a `PermitRootLogin yes` on a public address is a password-guessing target from the whole internet, and an agent forwarded to the wrong host is your identity in someone else's hands.

It is also more than a login. The same connection carries files, tunnels to ports that are not exposed to the network, and a route through a bastion to hosts that have no public address at all. Understanding why it does these things starts with what it replaced.

## The Concept

### What SSH replaced, and the four problems

A remote shell is not hard to build. Listen on a port, ask for a password, and run whatever lines arrive through `/bin/sh`, sending the output back. That was `rsh` and, with a terminal protocol on top, `telnet`. The **Build It** script is exactly that, and in the sandbox it sniffs its own session off the loopback:

```console
   [server -> client] password:
   [client -> server] hunter2
   [server -> client] ok. type commands; 'exit' to leave
   [client -> server] id
   [server -> client] uid=0(root) gid=0(root) groups=0(root)
   [client -> server] echo the database password is s3cr3t
   [server -> client] the database password is s3cr3t
```

Anyone on the path (a router, a wifi access point, a compromised switch, `tcpdump -A` on any box the packets cross) reads all of it. That is problem one and two: the password is visible, and so is everything after it, and nothing stops a third party from *changing* it in flight. Problem three is quieter: the client connected to an address and trusted whatever answered; a machine that intercepts the connection can present its own password prompt and collect yours. Problem four is a design limit: one byte stream, so no second command while the first runs, no file transfer, no way to reach another port through the connection.

SSH (RFC 4251 to 4254) is the answer to those four, in order:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 460" width="100%" style="max-width:880px" font-family="'JetBrains Mono', ui-monospace, monospace" role="img" aria-label="An SSH connection as three layers, each answering problems of the plaintext shell. Layer one, transport, RFC 4253: the two sides run a key exchange, here mlkem768x25519, to agree a secret that never crosses the wire; the server signs the exchange with its host key, and the client checks that key against known_hosts, which answers problem three, identity; everything after is encrypted and carries a MAC, answering problems one and two, confidentiality and integrity. Layer two, authentication, RFC 4252: the client proves who it is, by password, which is what the plaintext shell did but now encrypted, or by a public key, where the client signs a challenge with a private key that never leaves the laptop and the server checks the signature against authorized_keys; the log line is Accepted publickey for dev, ED25519, fingerprint. Layer three, connection, RFC 4254: many channels multiplexed on the one encrypted stream: a session running a shell or a command, scp and sftp, a local forward -L, a remote forward -R, and agent forwarding; this answers problem four. A footnote lists what each command in the lesson uses: ssh uses all three; scp and rsync open a session channel; -L, -R, -J open forwarding channels; ssh-agent lives on the laptop and signs the layer-two challenge.">
  <defs>
    <marker id="p1l17a-ar" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker>
  </defs>
  <text x="450" y="26" text-anchor="middle" font-size="14.5" font-weight="700" fill="currentColor">SSH is three layers, and each one answers a problem the plaintext shell has</text>
  <g stroke-linejoin="round" stroke-width="1.7">
    <rect x="40" y="48"  width="820" height="112" rx="10" fill="#0fa07f" fill-opacity="0.10" stroke="#0fa07f"/>
    <rect x="40" y="172" width="820" height="112" rx="10" fill="#e0930f" fill-opacity="0.10" stroke="#e0930f"/>
    <rect x="40" y="296" width="820" height="112" rx="10" fill="#7c5cff" fill-opacity="0.10" stroke="#7c5cff"/>
  </g>
  <g font-size="8.5" fill="currentColor">
    <text x="56" y="70" font-size="10.5" font-weight="700" fill="#0fa07f">1 · TRANSPORT (RFC 4253): a secret agreed, a server identified, everything after encrypted and signed</text>
    <text x="56" y="90">key exchange: kex mlkem768x25519-sha256 on the sandbox: both sides derive a shared secret that never crosses the wire</text>
    <text x="56" y="106">the server signs the exchange with its HOST KEY; the client compares it with ~/.ssh/known_hosts   → problem 3: is this the real server?</text>
    <text x="56" y="122">from here every byte is encrypted (AES-GCM or ChaCha20) and carries a MAC   → problems 1 and 2: nobody reads or alters it</text>
    <text x="56" y="142" opacity="0.75">"REMOTE HOST IDENTIFICATION HAS CHANGED" is this layer refusing: a rebuilt server, or an interception</text>
    <text x="56" y="194" font-size="10.5" font-weight="700" fill="#e0930f">2 · AUTHENTICATION (RFC 4252): the client proves who it is, inside the encrypted channel</text>
    <text x="56" y="214">password: what the plaintext shell did, now encrypted; still guessable from the internet, so servers turn it off</text>
    <text x="56" y="230">publickey: the client SIGNS a challenge with a private key that never leaves the laptop; the server checks it against authorized_keys</text>
    <text x="56" y="246">the server's log: Accepted publickey for dev from ::1 port 34014 ssh2: ED25519 SHA256:/xiGR+mk97C2+uF4onxOVuG4i9avSNycohVyaFtY0yQ</text>
    <text x="56" y="266" opacity="0.75">ssh-agent holds the unlocked private key on the laptop and does the signing, so the passphrase is typed once</text>
    <text x="56" y="318" font-size="10.5" font-weight="700" fill="#7c5cff">3 · CONNECTION (RFC 4254): many channels on one encrypted stream   → problem 4: one byte stream</text>
    <text x="56" y="338">session channels: an interactive shell, or one command (ssh host uptime), or a script piped in</text>
    <text x="56" y="354">scp and sftp: a session channel carrying a file protocol; rsync: a session channel running rsync on the far side</text>
    <text x="56" y="370">forwarding channels: -L (a local port → somewhere the server can reach), -R (the reverse), -D (a SOCKS proxy), -J (a jump)</text>
    <text x="56" y="390" opacity="0.75">agent forwarding (-A) sends signing requests back to your laptop through a channel: convenient, and dangerous on hosts you do not trust</text>
  </g>
  <text x="450" y="436" text-anchor="middle" font-size="10.5" fill="currentColor" opacity="0.9">Phase 2 lesson 10 builds the cryptography (TLS uses the same ideas). This lesson uses it: keys, agent, config, tunnels, files, hardening.</text>
</svg>
```

The **transport** layer runs a key exchange so both sides share a secret that never crosses the wire, has the server sign that exchange with its **host key** (which the client checks against `~/.ssh/known_hosts`), and encrypts and authenticates everything afterwards. The **authentication** layer runs inside that channel: a password, or better, a **public key**, where the client signs a challenge with a private key that never leaves the laptop and the server checks the signature against `~/.ssh/authorized_keys`. The **connection** layer multiplexes channels over the one stream: a shell, a command, a file copy, a port forward, an agent. Every command in this lesson is one of those channels.

### Keys: one per person per machine

`ssh-keygen -t ed25519` makes a key pair: `~/.ssh/id_ed25519`, private, mode 600, never copied anywhere; and `id_ed25519.pub`, one line of public key that you may give to anyone. Installing the public key on a server means appending that line to `~/.ssh/authorized_keys` there (`ssh-copy-id` does it for you), and from then on `ssh` proves your identity by signing, and the server logs which key it accepted, by fingerprint:

```console
$ ssh-keygen -t ed25519 -C "dev@laptop";  cat ~/.ssh/id_ed25519.pub
ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIB89cgJToySckwgB5NMkKS+WtNnrt3ZIJxvCASIyeZi3 dev@laptop
$ ssh -v dev@localhost true 2>&1 | grep -E 'Offering|Server accepts'
debug1: Offering public key: /home/dev/.ssh/id_ed25519 ED25519 SHA256:/xiGR+mk97C2+uF4onxOVuG4i9avSNycohVyaFtY0yQ
debug1: Server accepts key: /home/dev/.ssh/id_ed25519 ED25519 SHA256:/xiGR+mk97C2+uF4onxOVuG4i9avSNycohVyaFtY0yQ
```

The rules that follow from "the private key never leaves the machine": one key per person per laptop, a passphrase on it, a new key for a new laptop and the old one removed from every `authorized_keys`, and file modes that `ssh` itself enforces (a world-readable private key is refused with `UNPROTECTED PRIVATE KEY FILE`). An **agent** (`ssh-agent`, `ssh-add`) holds the unlocked key in memory so the passphrase is typed once per login session, and every `ssh`, `scp` and `git push` after that signs through it.

### known_hosts: the other direction

Keys prove you to the server. The **host key** proves the server to you. On the first connection `ssh` shows the server's fingerprint and asks you to confirm it; the honest answer comes from somewhere other than the prompt (the provider's console, the person who built the box, a published list), and the key is then stored in `known_hosts`. On every later connection the server must sign with the same key, and if it cannot, `ssh` refuses loudly with `REMOTE HOST IDENTIFICATION HAS CHANGED`. That refusal is problem three being solved, and the correct reaction is to find out *why* the key changed (a rebuilt server, or someone in the path) before `ssh-keygen -R host` forgets the old one.

### The config file, and a jump host

`~/.ssh/config` turns command lines into names:

```text
Host box
    HostName localhost
    User dev
    Port 22
    IdentityFile ~/.ssh/id_ed25519
    IdentitiesOnly yes
    ServerAliveInterval 30
```

`ssh box` now does what `ssh -i ~/.ssh/id_ed25519 -p 22 dev@localhost` did, and so do `scp box:...` and `rsync ... box:...`, because they all read the same file. `ssh -G box` prints the effective settings. `Host *` blocks set defaults; `ProxyJump bastion` in a host's block (or `-J bastion` on the command line) routes the connection through a **bastion**: your laptop connects to the bastion, then opens a channel through it to the target, and the target sees a normal SSH connection from your key. Keys stay on your laptop; nothing is forwarded; hosts with no public address become reachable. That is how every production fleet with private subnets is reached.

### Tunnels: a channel that carries a port

A database listens on `127.0.0.1:5432` on the server, unreachable from anywhere else (lesson 14), which is correct. To use it from your laptop:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 420" width="100%" style="max-width:880px" font-family="'JetBrains Mono', ui-monospace, monospace" role="img" aria-label="Three tunnel shapes. -L, a local forward: the laptop runs ssh -L 9090 colon 127.0.0.1 colon 8089 box; ssh listens on the laptop's 127.0.0.1 colon 9090; a client such as curl or psql connects there; the bytes travel inside the encrypted SSH connection to the server, where sshd connects to 127.0.0.1 colon 8089, a port bound to the server's loopback that no firewall exposes; measured here as http 200 via 127.0.0.1 colon 9090. -R, a remote forward: the reverse; ssh -R 9091 colon 127.0.0.1 colon 8089 box makes sshd listen on the server's loopback 9091 and deliver connections back to the laptop's 8089; used to expose a dev machine to a webhook or to a colleague on the server. -J, a jump: ssh -J bastion target opens a connection to the bastion and, through a channel in it, a second SSH connection to the target; the target sees your key directly; no agent forwarding, and the target needs no public address. A footnote: every tunnel is a channel in RFC 4254's connection layer; the far port stays bound to loopback and the firewall stays closed; -N runs a tunnel without a shell and -f backgrounds it.">
  <defs>
    <marker id="p1l17b-ar" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker>
    <marker id="p1l17b-arg" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#0fa07f"/></marker>
  </defs>
  <text x="450" y="26" text-anchor="middle" font-size="14.5" font-weight="700" fill="currentColor">Tunnels: a port on one side, a port on the other, and an encrypted channel between</text>
  <g stroke-linejoin="round" stroke-width="1.6">
    <rect x="30"  y="50" width="270" height="250" rx="10" fill="#0fa07f" fill-opacity="0.08" stroke="#0fa07f"/>
    <rect x="315" y="50" width="270" height="250" rx="10" fill="#e0930f" fill-opacity="0.08" stroke="#e0930f"/>
    <rect x="600" y="50" width="270" height="250" rx="10" fill="#7c5cff" fill-opacity="0.08" stroke="#7c5cff"/>
  </g>
  <g text-anchor="middle" font-size="10" font-weight="700">
    <text x="165" y="72" fill="#0fa07f">-L · local forward</text>
    <text x="450" y="72" fill="#e0930f">-R · remote forward</text>
    <text x="735" y="72" fill="#7c5cff">-J · jump host</text>
  </g>
  <g font-size="8.5" fill="currentColor">
    <text x="46" y="96">ssh -L 9090:127.0.0.1:8089 box</text>
    <text x="46" y="120">laptop: ssh listens on 127.0.0.1:9090</text>
    <text x="46" y="136">curl http://127.0.0.1:9090/  ─┐</text>
    <text x="46" y="152">    (encrypted channel)      │</text>
    <text x="46" y="168">server: sshd connects to    ◄┘</text>
    <text x="46" y="184">127.0.0.1:8089 (loopback only)</text>
    <text x="46" y="210" font-weight="700">http 200 via 127.0.0.1:9090</text>
    <text x="46" y="234" opacity="0.8">the database, the admin UI, the</text>
    <text x="46" y="248" opacity="0.8">metrics port: reachable by key-</text>
    <text x="46" y="262" opacity="0.8">holders, exposed to nobody</text>
    <text x="46" y="284" opacity="0.7">-N: no shell · -f: background</text>

    <text x="331" y="96">ssh -R 9091:127.0.0.1:8089 box</text>
    <text x="331" y="120">server: sshd listens on 127.0.0.1:9091</text>
    <text x="331" y="136">curl on the server → :9091  ─┐</text>
    <text x="331" y="152">    (the same channel, reversed) │</text>
    <text x="331" y="168">laptop: ssh connects to       ◄┘</text>
    <text x="331" y="184">127.0.0.1:8089 on the laptop</text>
    <text x="331" y="210" font-weight="700">from the server side: http 200</text>
    <text x="331" y="234" opacity="0.8">a webhook into your dev box,</text>
    <text x="331" y="248" opacity="0.8">a demo for a colleague on the</text>
    <text x="331" y="262" opacity="0.8">server; GatewayPorts for more</text>
    <text x="331" y="284" opacity="0.7">the server's loopback by default</text>

    <text x="616" y="96">ssh -J bastion target</text>
    <text x="616" y="120">laptop → bastion: one SSH connection</text>
    <text x="616" y="136">inside it, a channel to target:22</text>
    <text x="616" y="152">laptop → target: a second SSH</text>
    <text x="616" y="168">connection, through that channel</text>
    <text x="616" y="184">target sees YOUR key, not the bastion's</text>
    <text x="616" y="210" font-weight="700">arrived via a jump host as dev</text>
    <text x="616" y="234" opacity="0.8">private subnets, no public address,</text>
    <text x="616" y="248" opacity="0.8">no agent forwarding needed;</text>
    <text x="616" y="262" opacity="0.8">ProxyJump in ~/.ssh/config</text>
    <text x="616" y="284" opacity="0.7">-A (agent forwarding) is the risky alternative</text>
  </g>
  <text x="450" y="336" text-anchor="middle" font-size="10.5" fill="currentColor" opacity="0.9">A tunnel is a channel: the far port stays on loopback, the firewall stays shut, only key-holders get through.</text>
  <text x="450" y="358" text-anchor="middle" font-size="9.5" fill="currentColor" opacity="0.72">A tunnel to a database is how you run psql against production without the database ever having a public port (lesson 14's ss -tlnp shows 127.0.0.1:5432).</text>
  <text x="450" y="380" text-anchor="middle" font-size="9.5" fill="currentColor" opacity="0.72">ssh -D 1080 makes a SOCKS proxy through the same channel: a whole browser, or curl -x socks5h://, through the bastion.</text>
</svg>
```

`ssh -L 9090:127.0.0.1:8089 box` makes `ssh` listen on your laptop's port 9090 and deliver each connection, through the encrypted channel, to `127.0.0.1:8089` *as seen from the server*. `-R` is the reverse: a port on the server delivered back to your laptop. `-D` makes a SOCKS proxy. `-N` opens the tunnel without a shell and `-f` backgrounds it. The database never gets a public port, the firewall never opens, and only people with a key on the box can reach it. Lesson 14's rule that a service bound to `127.0.0.1` is invisible from outside is exactly what makes this safe.

### Files: scp and rsync

`scp file box:/path` copies a file over a session channel; `-r` copies a tree; `-P` sets the port (capital, unlike `ssh -p`). It is fine for one file and wasteful for a tree, because it copies everything every time. `rsync -a src/ box:/dst/` runs `rsync` on both ends, compares the trees, and sends **only the differences**, preserving modes, owners and times (`-a`), with `-v` to narrate, `-z` to compress on the wire, `-n` to dry-run, `--delete` to mirror removals (dry-run first, always), and `--exclude` for `.git` and the like. The **Use It** section shows the second run moving one changed file, which is why a code deploy, a backup and a log collection are all `rsync`. The slash rule from lesson 05's checklist applies: `src/` copies the contents, `src` copies the directory.

### Hardening sshd

A server on a public address receives thousands of password guesses a day. The fix is short and goes in a drop-in file, `/etc/ssh/sshd_config.d/10-hardening.conf`:

```text
PasswordAuthentication no
PermitRootLogin no
MaxAuthTries 3
X11Forwarding no
AllowUsers dev ops
```

Keys only, no root (operators are themselves and use `sudo`, lesson 06), a short list of accounts that may connect at all. `sshd -t` checks the syntax before you reload, because a broken `sshd_config` is a locked door; `sshd -T` prints the effective values; `systemctl reload ssh` applies them without dropping your session; `journalctl -u ssh` records every `Accepted publickey` and `Failed password` with its source address, which lesson 08's tools count. Set `PasswordAuthentication no` only *after* your key works, and keep a second key-holder, because with keys only and a lost key the provider's console is the only remaining door.

### Long-running work, and what not to forward

`ssh host command` runs one command and exits; `ssh -t host top` allocates a terminal for an interactive program; `ssh host bash < script.sh` runs a local script remotely. Anything that must outlive the connection runs in **`tmux`** (`tmux new -s work`, `Ctrl+b d` to detach, `tmux attach`) or as a unit (lesson 11); lesson 10 explained what `SIGHUP` does to everything else. And `-A`, agent forwarding, lets the far host use your agent to sign: convenient for `git pull` on a server, and a way for that server's root to act as you anywhere your key is installed. Use `-J` instead wherever a jump would do, and a dedicated deploy key with a `command=` restriction for automation.

## Build It

The script for this lesson is [`code/plainshell.py`](../code/plainshell.py): the remote shell SSH replaced, with the sniffer from lesson 14 turned on its own traffic. It runs on macOS and Linux; the sniffing needs the sandbox (Linux, root):

```bash
python3 phases/01-linux-and-the-command-line/17-ssh-keys-tunnels-and-rsync/code/plainshell.py
make shell   # then the same, to see the bytes
```

The server is a socket, a password compare, and `subprocess.run` with `shell=True`:

```python
f.write(b"password: ")
if f.readline().strip() != PASSWORD.encode():                  # problem 1: the password crosses the wire as-is
    f.write(b"denied\n"); return
for line in f:                                                 # problem 2: every command and result, readable
    out = subprocess.run(line.decode().strip(), shell=True, capture_output=True, text=True)
    f.write((out.stdout + out.stderr).encode() + b"<end>\n")   # problem 4: one stream, nothing else
```

And the client connects to an address and trusts whatever answers, which is problem three. The sandbox transcript above is what a third party sees. The final block of the script's output maps the four problems to the four SSH mechanisms, which is the whole reason the protocol has the shape it has.

## Use It

On the booted `systemd` box from lesson 11 (`docker exec -it sysd bash`), with `openssh-server` installed and a user `dev`. The server's identity, and a key pair for the user:

```console
$ ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub
256 SHA256:Dl1Rdzffr4RlJ3v417daP5uZn84pYFzSWud29O6mSxo root@0970caef98b3 (ED25519)
$ su - dev
$ ssh-keygen -t ed25519 -N '' -C 'dev@laptop' -f ~/.ssh/id_ed25519 -q;  ls -la ~/.ssh
drwx------ 1 dev dev  48 Sep  5 05:21 .
-rw------- 1 dev dev 399 Sep  5 05:21 id_ed25519
-rw-r--r-- 1 dev dev  92 Sep  5 05:21 id_ed25519.pub
$ cat ~/.ssh/id_ed25519.pub >> ~/.ssh/authorized_keys;  chmod 600 ~/.ssh/authorized_keys
```

The first connection records the host key; a verbose login shows the key exchange, the known host, the offer and the acceptance; and the server's journal has the other side of it, including an earlier failed password attempt:

```console
$ ssh -o StrictHostKeyChecking=accept-new dev@localhost true
Warning: Permanently added 'localhost' (ED25519) to the list of known hosts.
$ ssh -v dev@localhost true 2>&1 | grep -E 'kex: algorithm|is known|Authentications|Offering|Server accepts'
debug1: kex: algorithm: mlkem768x25519-sha256
debug1: Host 'localhost' is known and matches the ED25519 host key.
debug1: Authentications that can continue: publickey,password
debug1: Offering public key: /home/dev/.ssh/id_ed25519 ED25519 SHA256:/xiGR+mk97C2+uF4onxOVuG4i9avSNycohVyaFtY0yQ
debug1: Server accepts key: /home/dev/.ssh/id_ed25519 ED25519 SHA256:/xiGR+mk97C2+uF4onxOVuG4i9avSNycohVyaFtY0yQ
$ journalctl -u ssh | grep -E 'Accepted|Failed' | tail -2
Sep 05 05:21:01 0970caef98b3 sshd-session[5619]: Failed password for dev from ::1 port 34008 ssh2
Sep 05 05:21:01 0970caef98b3 sshd-session[5644]: Accepted publickey for dev from ::1 port 34014 ssh2: ED25519 SHA256:/xiGR+mk97C2+uF4onxOVuG4i9avSNycohVyaFtY0yQ
```

The mode check `ssh` enforces on its own, the agent, and the config file:

```console
$ cp ~/.ssh/id_ed25519 /tmp/loose_key;  chmod 644 /tmp/loose_key;  ssh -i /tmp/loose_key dev@localhost true
@         WARNING: UNPROTECTED PRIVATE KEY FILE!          @
Permissions 0644 for '/tmp/loose_key' are too open.
$ eval $(ssh-agent -s);  ssh-add ~/.ssh/id_ed25519;  ssh-add -l
Identity added: /home/dev/.ssh/id_ed25519 (dev@laptop)
256 SHA256:/xiGR+mk97C2+uF4onxOVuG4i9avSNycohVyaFtY0yQ dev@laptop (ED25519)
$ cat ~/.ssh/config
Host box
    HostName localhost
    User dev
    IdentityFile ~/.ssh/id_ed25519
    IdentitiesOnly yes
    ServerAliveInterval 30
$ ssh box 'echo hello from $(hostname) as $(id -un)';  ssh -G box | grep -E '^(hostname|user|identityfile) '
hello from 0970caef98b3 as dev
user dev
hostname localhost
identityfile ~/.ssh/id_ed25519
```

One command, a script over the wire, and the terminal question:

```console
$ ssh box uptime
 05:21:01 up 3 days,  6:26,  0 users,  load average: 0.68, 0.92, 0.66
$ echo 'echo script ran as $(id -un) in $(pwd)' | ssh box bash
script ran as dev in /home/dev
$ ssh box 'tty || echo no-tty';  ssh -t box tty
not a tty
no-tty
/dev/pts/1
```

A tunnel to a port bound to the server's loopback (a small HTTP server on 8089 that nothing outside can reach), the reverse tunnel, and a jump:

```console
$ ssh -f -N -L 9090:127.0.0.1:8089 box
$ curl -s -o /dev/null -w 'through the tunnel: http %{http_code} via %{remote_ip}:%{remote_port}\n' http://127.0.0.1:9090/
through the tunnel: http 200 via 127.0.0.1:9090
$ ss -tlnp | grep -E '9090|8089' | awk '{print $4, $6}'
127.0.0.1:8089
127.0.0.1:9090 users:(("ssh",pid=5783,fd=5))
$ ssh -f -N -R 9091:127.0.0.1:8089 box;  ssh box 'curl -s -o /dev/null -w "from the server side: http %{http_code}\n" http://127.0.0.1:9091/'
from the server side: http 200
$ ssh -J box box 'echo arrived via a jump host as $(id -un)'
arrived via a jump host as dev
```

Files: `scp` for one, `rsync` for a tree, and the second `rsync` run moving only what changed:

```console
$ scp -q src/a.txt box:/tmp/a-copy.txt;  scp -q -r src box:/tmp/src-copy;  ls /tmp/src-copy
a.txt  sub
$ rsync -a --stats src/ box:/tmp/src-rsync/ | grep -E 'Number of files|regular files transferred|Total transferred'
Number of files: 4 (reg: 2, dir: 2)
Number of regular files transferred: 2
Total transferred file size: 3,895 bytes
$ echo c >> src/a.txt;  rsync -a --stats src/ box:/tmp/src-rsync/ | grep -E 'regular files transferred'
Number of regular files transferred: 1
$ rsync -avn --delete src/ box:/tmp/src-rsync/ | head -2
sending incremental file list
```

Hardening, checked before it is applied, and the proof that passwords are now refused:

```console
$ cat /etc/ssh/sshd_config.d/10-hardening.conf
PasswordAuthentication no
PermitRootLogin no
MaxAuthTries 3
X11Forwarding no
AllowUsers dev ops
$ sshd -t && echo 'sshd -t: config ok';  systemctl reload ssh;  sshd -T | grep -E '^(passwordauthentication|permitrootlogin|maxauthtries) '
sshd -t: config ok
maxauthtries 3
permitrootlogin no
passwordauthentication no
$ ssh -o PreferredAuthentications=password -o PubkeyAuthentication=no dev@localhost true
dev@localhost: Permission denied (publickey).
$ journalctl -u ssh | tail -1
Sep 05 05:21:04 0970caef98b3 sshd-session[5935]: Connection closed by authenticating user dev ::1 port 37406 [preauth]
```

And a session that survives you leaving: `tmux new -d -s work 'sleep 300'; tmux ls` shows `work: 1 windows`, and `tmux attach -t work` from the next login finds it still running.

## Ship It

The artifact for this lesson is a checklist: [`outputs/checklist-ssh-setup-and-hardening.md`](../outputs/checklist-ssh-setup-and-hardening.md). Your side: one ed25519 key per person per laptop with a passphrase, the modes `ssh` demands, the agent and why agent forwarding is a risk, a config file with `Host *` defaults, a bastion via `ProxyJump`, and how to treat a first-connection fingerprint. The server: the hardening drop-in (keys only, no root, `AllowUsers`, `MaxAuthTries`), `sshd -t` and `sshd -T`, the journal, host keys as the box's identity, and when certificates beat `authorized_keys`. Tunnels for databases and webhooks, `scp` and `rsync` with the slash rule and `--delete` dry runs, `tmux` for long work, `command=` keys for automation, and the six-step diagnosis for a refused login.

## Think about it

1. A colleague runs `ssh -A prod-web` daily to `git pull`. Describe what a compromised `prod-web` can do with that, and the two changes (one flag, one config line) that remove the risk while keeping the workflow.
2. `ssh app-prod` shows `REMOTE HOST IDENTIFICATION HAS CHANGED` the morning after the infrastructure team rebuilt the box. Name the two explanations, the one command that distinguishes them, and why `ssh-keygen -R` should not be your first move.
3. You set `PasswordAuthentication no` and `AllowUsers ops`, reload, and your own session keeps working. Which two things should you test from a *second* terminal before closing this one, and what happens if you skip them?
4. A nightly `rsync -a --delete` mirrors `/var/lib/app/` to a backup host. One night someone runs it with `/var/lib/app` (no trailing slash) by mistake. What ends up on the backup host, what is deleted there, and which flag would have shown the difference first?

## Key takeaways

- The plaintext remote shell has **four problems**: the password is readable, everything after it is readable and alterable, nothing proves the server, and one stream can carry only one thing. SSH's **transport**, **authentication** and **connection** layers answer them in that order.
- **Keys**: `ssh-keygen -t ed25519`, one per person per machine, passphrase on, private key never leaves; the public line goes into `authorized_keys` on the server; the server logs `Accepted publickey` with the fingerprint. **ssh-agent** signs so the passphrase is typed once.
- **known_hosts** is the server proving itself; a changed host key is a question, not an annoyance.
- **`~/.ssh/config`** turns options into names, and `ProxyJump` (`-J`) reaches private hosts through a bastion without forwarding your agent.
- **Tunnels**: `-L` brings a server-side port to your laptop, `-R` the reverse, `-D` a SOCKS proxy; the far port stays on loopback and the firewall stays shut.
- **`scp`** for a file, **`rsync -a`** for a tree (only differences, second run moved one file), `-n` before `--delete`, mind the trailing slash.
- **Harden sshd** in a drop-in: keys only, no root, `AllowUsers`, `MaxAuthTries`; `sshd -t` before `reload`; read `journalctl -u ssh`. **`tmux`** or a unit for anything that must outlive the connection.

Next: [Capstone: Blank Box to Backend](../18-capstone-blank-box-to-running-backend/). Every tool in this phase, once, in order, on a box that starts empty: users, packages, the code, the unit, the firewall, `sshd`, log rotation, a health check, and then four things broken on purpose and found with `journalctl`, `ss`, `strace` and `curl`.
