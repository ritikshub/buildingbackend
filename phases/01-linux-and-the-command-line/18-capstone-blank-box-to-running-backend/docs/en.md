# Capstone: Blank Box to Backend

> A fresh Debian box with nothing on it but `systemd` and `apt`. Nine seconds and one script later it has a service user, the code under `/opt`, config under `/etc` that the service can read and not write, a unit that restarts it and limits it, a firewall that drops everything but `22`, `80` and `443`, `sshd` that accepts one operator's key and nothing else, and an API answering `{"status": "ok"}` as uid **995**. Then the box is broken four ways on purpose, `kill -9`, an unwritable data file, a stolen port, a bad config value, and each one is found with `journalctl`, `stat`, `ss` and `strace`, the way this phase taught, in under a minute each.

## The Problem

Seventeen lessons, seventeen tools, each one built by hand and then used for real. The capstone is the test of whether they add up: can you take a machine you have never seen and make it run a backend the way a backend should be run, and can you then find what is wrong when it breaks? Not "install Docker and paste a compose file"; Phase 11 is that, and it stands on exactly this. This is the box itself.

There is one script, `provision.sh`, that does the whole thing, and one, `verify.sh`, that checks it. Read the first before running it: every step is a lesson number, and the point of the capstone is that you could have written it. Then break the result, because the second half of operating a service is the half nobody scripts.

## The Concept

### The shape of a correctly deployed service

Everything the phase taught converges on one picture, and it is worth having it in one place:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 560" width="100%" style="max-width:880px" font-family="'JetBrains Mono', ui-monospace, monospace" role="img" aria-label="One deployed service drawn as a box diagram. At the top, the operator's laptop reaches the box over SSH on port 22 with an ed25519 key as user ops; the firewall, nftables with a default drop policy, lets in 22, 80 and 443 and nothing else; the app's port 8080 is bound to 127.0.0.1 and never exposed. Inside the box, PID 1 systemd supervises app.service: Type simple, User app, Restart on-failure, TimeoutStopSec, LimitNOFILE, MemoryMax, ProtectSystem strict. The service process runs as uid 995, reads /opt/app/server.py owned by root, reads /etc/app/app.env owned by root with group app and mode 640, writes only to /var/lib/app and /var/log/app which it owns, and logs to stdout which journald stores. The operator uses sudo for exactly systemctl restart, status, reload and journalctl, and sudo -u app to inspect the service's files. Lesson numbers are attached to every part: 06 for users and modes, 04 for the layout, 11 for the unit and the journal, 14 for the firewall and the bind address, 17 for SSH, 05 for the atomic config write, 13 for the packages.">
  <defs>
    <marker id="p1l18a-ar" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker>
  </defs>
  <text x="450" y="26" text-anchor="middle" font-size="14.5" font-weight="700" fill="currentColor">One service, deployed the way the phase taught: every arrow is a lesson</text>
  <!-- laptop -->
  <rect x="40" y="50" width="200" height="60" rx="9" fill="#7c5cff" fill-opacity="0.12" stroke="#7c5cff" stroke-width="1.7" stroke-linejoin="round"/>
  <text x="140" y="72" text-anchor="middle" font-size="10" font-weight="700" fill="#7c5cff">THE OPERATOR'S LAPTOP</text>
  <text x="140" y="88" text-anchor="middle" font-size="8.5" fill="currentColor">ssh ops@box · ed25519 key · ssh-agent</text>
  <text x="140" y="102" text-anchor="middle" font-size="8" fill="currentColor" opacity="0.7">lesson 17</text>
  <!-- firewall -->
  <rect x="290" y="50" width="570" height="60" rx="9" fill="#d64545" fill-opacity="0.08" stroke="#d64545" stroke-width="1.7" stroke-linejoin="round"/>
  <text x="575" y="72" text-anchor="middle" font-size="10" font-weight="700" fill="#d64545">THE FIREWALL · nftables, policy drop</text>
  <text x="575" y="88" text-anchor="middle" font-size="8.5" fill="currentColor">in: established · lo · icmp · tcp 22 · tcp 80, 443 · nothing else. 8080 is not a hole because 8080 is not on the network</text>
  <text x="575" y="102" text-anchor="middle" font-size="8" fill="currentColor" opacity="0.7">lesson 14 · (Phase 11 puts a reverse proxy on 443 in front of 8080)</text>
  <path d="M242 80 L286 80" fill="none" stroke="currentColor" stroke-width="1.6" marker-end="url(#p1l18a-ar)"/>
  <!-- the box -->
  <rect x="40" y="130" width="820" height="380" rx="12" fill="#7f7f7f" fill-opacity="0.06" stroke="currentColor" stroke-opacity="0.35" stroke-width="1.5" stroke-linejoin="round"/>
  <text x="56" y="150" font-size="9.5" font-weight="700" fill="currentColor" opacity="0.8">THE BOX · Debian 13 · kernel from the host, PID 1 systemd (lessons 01, 02, 11)</text>
  <!-- sshd -->
  <rect x="60" y="164" width="230" height="70" rx="9" fill="#7c5cff" fill-opacity="0.10" stroke="#7c5cff" stroke-width="1.5" stroke-linejoin="round"/>
  <text x="175" y="184" text-anchor="middle" font-size="9.5" font-weight="700" fill="#7c5cff">sshd · keys only</text>
  <text x="175" y="200" text-anchor="middle" font-size="8" fill="currentColor">PasswordAuthentication no</text>
  <text x="175" y="212" text-anchor="middle" font-size="8" fill="currentColor">PermitRootLogin no · AllowUsers ops</text>
  <text x="175" y="226" text-anchor="middle" font-size="8" fill="currentColor" opacity="0.7">journalctl -u ssh: Accepted publickey</text>
  <!-- ops -->
  <rect x="60" y="250" width="230" height="90" rx="9" fill="#0fa07f" fill-opacity="0.10" stroke="#0fa07f" stroke-width="1.5" stroke-linejoin="round"/>
  <text x="175" y="270" text-anchor="middle" font-size="9.5" font-weight="700" fill="#0fa07f">ops · uid 1000, group app</text>
  <text x="175" y="286" text-anchor="middle" font-size="8" fill="currentColor">sudo: systemctl restart|status|reload app,</text>
  <text x="175" y="298" text-anchor="middle" font-size="8" fill="currentColor">journalctl · sudo -u app for its files</text>
  <text x="175" y="314" text-anchor="middle" font-size="8" fill="currentColor">sudo cat /etc/app/app.env: not allowed</text>
  <text x="175" y="330" text-anchor="middle" font-size="8" fill="currentColor" opacity="0.7">lesson 06</text>
  <!-- systemd -->
  <rect x="320" y="164" width="250" height="176" rx="9" fill="#c94a12" fill-opacity="0.10" stroke="#c94a12" stroke-width="1.7" stroke-linejoin="round"/>
  <text x="445" y="184" text-anchor="middle" font-size="9.5" font-weight="700" fill="#c94a12">systemd · app.service</text>
  <g text-anchor="middle" font-size="8" fill="currentColor">
    <text x="445" y="202">Type=simple · User=app · UMask=027</text>
    <text x="445" y="216">Restart=on-failure · RestartSec=2</text>
    <text x="445" y="230">StartLimitBurst=5 · TimeoutStopSec=15</text>
    <text x="445" y="244">LimitNOFILE=65536 · MemoryMax=256M</text>
    <text x="445" y="258">ProtectSystem=strict · PrivateTmp</text>
    <text x="445" y="272">StateDirectory · LogsDirectory · RuntimeDirectory</text>
    <text x="445" y="292">stdout → journald → journalctl -u app</text>
    <text x="445" y="306">TERM → drain → exit 0 · HUP → reload</text>
    <text x="445" y="326" opacity="0.7">lessons 10, 11, 12</text>
  </g>
  <!-- the process -->
  <rect x="600" y="164" width="240" height="176" rx="9" fill="#0fa07f" fill-opacity="0.12" stroke="#0fa07f" stroke-width="1.7" stroke-linejoin="round"/>
  <text x="720" y="184" text-anchor="middle" font-size="9.5" font-weight="700" fill="#0fa07f">python3 server.py · uid 995 (app)</text>
  <g text-anchor="middle" font-size="8" fill="currentColor">
    <text x="720" y="202">listens 127.0.0.1:8080 (BIND from the env)</text>
    <text x="720" y="216">/health · GET, POST /api/notes</text>
    <text x="720" y="234">refuses to start as root</text>
    <text x="720" y="248">reads config, cannot write it</text>
    <text x="720" y="262">writes only under /var/lib/app</text>
    <text x="720" y="276">O_APPEND for the notes file</text>
    <text x="720" y="292">print(..., flush=True) → journal</text>
    <text x="720" y="306">a request is one accept4, one openat,</text>
    <text x="720" y="320">one write, one sendto (strace)</text>
  </g>
  <path d="M572 250 L596 250" fill="none" stroke="currentColor" stroke-width="1.6" marker-end="url(#p1l18a-ar)"/>
  <!-- filesystem -->
  <rect x="60" y="356" width="780" height="140" rx="9" fill="#e0930f" fill-opacity="0.10" stroke="#e0930f" stroke-width="1.5" stroke-linejoin="round"/>
  <text x="450" y="376" text-anchor="middle" font-size="9.5" font-weight="700" fill="#e0930f">THE FILESYSTEM · read-only half on the left, runtime half on the right (lesson 04)</text>
  <g font-size="8.5" fill="currentColor">
    <text x="76" y="400">/opt/app/server.py      -rw-r--r-- root:root    the code: root owns it, the service reads it</text>
    <text x="76" y="416">/etc/app/app.env        -rw-r----- root:app     the config: written atomically (tmp + mv), readable via the group, 640</text>
    <text x="76" y="432">/etc/systemd/system/app.service · /etc/sudoers.d/ops · /etc/nftables.conf · /etc/logrotate.d/app · /etc/ssh/sshd_config.d/10-hardening.conf</text>
    <text x="76" y="456">/var/lib/app/notes.jsonl  -rw-r----- app:app   the data (StateDirectory=)      /var/log/app  app:app   rotated by logrotate, HUP to reopen</text>
    <text x="76" y="472">/run/app  app:app  RuntimeDirectory=, gone at boot      /var/cache/app  regenerable      packages from apt only (lesson 13)</text>
    <text x="76" y="488" opacity="0.75">every file has an owner you can name; nothing the service writes is under /etc, /usr or /opt; nothing it needs is under /tmp</text>
  </g>
  <text x="450" y="532" text-anchor="middle" font-size="10.5" fill="currentColor" opacity="0.9">provision.sh builds this in eight steps and nine seconds; verify.sh checks twenty-one facts about it; the fault table finds what breaks it.</text>
  <text x="450" y="550" text-anchor="middle" font-size="9.5" fill="currentColor" opacity="0.72">Phase 11 wraps this same shape in an image, a volume and an orchestrator. The shape does not change.</text>
</svg>
```

Read it from the outside in. An operator reaches the box with a key, as themselves (lesson 17, lesson 06). The firewall admits three ports and drops the rest; the service's own port is bound to loopback and is not one of them (lesson 14). PID 1 supervises a unit that says who the service is, what it may use, how it restarts and how it stops (lessons 10, 11, 12). The process runs as a system user that can read its config and cannot change it, can write its data and nothing else, and logs to stdout, which the journal keeps (lessons 04, 06, 07). And the filesystem has a read-only half and a runtime half, each file with an owner you can name (lessons 04, 05, 13). Phase 11 will wrap this same shape in an image and an orchestrator; the shape is the thing.

### Eight steps, each a lesson

`provision.sh` is idempotent (lesson 09): run it twice and the second run changes nothing. Its steps, in order, with the lesson each comes from:

1. **Packages** (lesson 13): `apt-get install --no-install-recommends` of exactly what the box needs, written down.
2. **Users** (lesson 06): a system user and group for the service with `nologin`; a human operator in the service's group; a `sudoers.d` file listing the operator's four commands and `sudo -u app`, validated with `visudo -cf`.
3. **Code and config** (lessons 04, 05, 06): `install` puts the code under `/opt/app` owned by root and creates `/etc/app` as `root:app 750`; the config is written to a temp file and renamed into place (never overwriting an operator's edits), `root:app 640`.
4. **The unit** (lesson 11): `install`, `systemd-analyze verify`, `daemon-reload`, `enable --now`.
5. **Log rotation** (lessons 04, 11): a `logrotate` stanza with a `HUP` in `postrotate`.
6. **The firewall** (lesson 14): an `nftables` ruleset with a default drop, checked with `nft -c` before loading.
7. **SSH** (lesson 17): the operator's key installed, then the hardening drop-in, checked with `sshd -t` before reload, and only if a key was supplied.
8. **Verify** (lessons 12, 14, 15): `curl -sf /health` in a retry loop, `systemctl is-active`, and the user the main process runs as.

`verify.sh` then checks twenty-one facts, grouped by lesson: the identity and modes, the unit and its policies, the bind address and the endpoints, the journal and rotation, `sshd`. It exits 0 only if all pass, so it can be a CI step or a post-deploy check.

### The four faults, and the four commands

The second half of the capstone breaks the box on purpose. Each fault is one that happens for real, and each is found by one tool from the phase:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 400" width="100%" style="max-width:880px" font-family="'JetBrains Mono', ui-monospace, monospace" role="img" aria-label="Four faults injected into the deployed service, each with the symptom, the command that finds it, and what it shows. One, kill -9 the main process: the symptom is a gap in service; systemctl show app -p NRestarts reads 1 and journalctl shows code=killed, status=9/KILL then Scheduled restart job; the supervisor handled it; the question is who sent the signal. Two, the data file made root-owned and mode 600: /health is fine but POST returns nothing; journalctl shows PermissionError on notes.jsonl; stat shows root:root -rw------- and sudo -u app cannot append; the fix is chown app:app. Three, another process takes port 8080: the unit stays activating and the journal shows Errno 98 Address already in use; ss -tlnp sport = :8080 names the impostor's PID; the fix is to stop it and reset-failed. Four, PORT=eighty in the config: the app crashes at start with ValueError, five restarts in twelve seconds, then Start request repeated too quickly and Result exit-code; journalctl -u app shows the traceback; the fix is the config, then reset-failed and start. A fifth panel: the service is up and slow, so strace -p on the main PID during one request shows accept4, openat of notes.jsonl with O_APPEND, one write of 49 bytes, and the log line, in order.">
  <text x="450" y="26" text-anchor="middle" font-size="14.5" font-weight="700" fill="currentColor">Four faults, four tools: what breaks, what finds it, what it says</text>
  <g stroke-linejoin="round" stroke-width="1.6">
    <rect x="30"  y="48" width="205" height="270" rx="10" fill="#7f7f7f" fill-opacity="0.12" stroke="#7f7f7f"/>
    <rect x="245" y="48" width="205" height="270" rx="10" fill="#e0930f" fill-opacity="0.10" stroke="#e0930f"/>
    <rect x="460" y="48" width="205" height="270" rx="10" fill="#c94a12" fill-opacity="0.10" stroke="#c94a12"/>
    <rect x="675" y="48" width="195" height="270" rx="10" fill="#d64545" fill-opacity="0.08" stroke="#d64545"/>
  </g>
  <g text-anchor="middle" font-size="9.5" font-weight="700">
    <text x="132" y="70" fill="currentColor">1 · kill -9 the app</text>
    <text x="347" y="70" fill="#e0930f">2 · data file unwritable</text>
    <text x="562" y="70" fill="#c94a12">3 · port taken</text>
    <text x="772" y="70" fill="#d64545">4 · PORT=eighty</text>
  </g>
  <g font-size="8" fill="currentColor">
    <text x="42" y="94" font-weight="700">symptom</text>
    <text x="42" y="108">a 2 s gap; then it is back</text>
    <text x="42" y="130" font-weight="700">find it</text>
    <text x="42" y="144">systemctl show app -p NRestarts</text>
    <text x="42" y="158">journalctl -u app</text>
    <text x="42" y="180" font-weight="700">it says</text>
    <text x="42" y="194">code=killed, status=9/KILL</text>
    <text x="42" y="208">Scheduled restart job,</text>
    <text x="42" y="222">restart counter is at 1</text>
    <text x="42" y="244" font-weight="700">meaning</text>
    <text x="42" y="258">Restart=on-failure worked;</text>
    <text x="42" y="272">who sent 9? (OOM: journalctl -k)</text>
    <text x="42" y="296" opacity="0.7">lessons 10, 11, 12</text>

    <text x="257" y="94" font-weight="700">symptom</text>
    <text x="257" y="108">/health ok, POST gets nothing</text>
    <text x="257" y="130" font-weight="700">find it</text>
    <text x="257" y="144">journalctl -u app | grep Error</text>
    <text x="257" y="158">stat -c '%A %U:%G' the file</text>
    <text x="257" y="180" font-weight="700">it says</text>
    <text x="257" y="194">PermissionError: [Errno 13]</text>
    <text x="257" y="208">-rw------- root:root notes.jsonl</text>
    <text x="257" y="222">sudo -u app: Permission denied</text>
    <text x="257" y="244" font-weight="700">fix</text>
    <text x="257" y="258">chown app:app; chmod 640</text>
    <text x="257" y="272">POST → 201 again</text>
    <text x="257" y="296" opacity="0.7">lessons 06, 08</text>

    <text x="472" y="94" font-weight="700">symptom</text>
    <text x="472" y="108">unit stuck in activating</text>
    <text x="472" y="130" font-weight="700">find it</text>
    <text x="472" y="144">journalctl -u app | tail</text>
    <text x="472" y="158">ss -tlnp 'sport = :8080'</text>
    <text x="472" y="180" font-weight="700">it says</text>
    <text x="472" y="194">OSError: [Errno 98]</text>
    <text x="472" y="208">Address already in use</text>
    <text x="472" y="222">users:(("python3",pid=1766))</text>
    <text x="472" y="244" font-weight="700">fix</text>
    <text x="472" y="258">stop the holder; reset-failed;</text>
    <text x="472" y="272">start → active in 1.5 s</text>
    <text x="472" y="296" opacity="0.7">lessons 10, 14</text>

    <text x="687" y="94" font-weight="700">symptom</text>
    <text x="687" y="108">failed after 12 s of trying</text>
    <text x="687" y="130" font-weight="700">find it</text>
    <text x="687" y="144">systemctl status app</text>
    <text x="687" y="158">journalctl -u app -n 50</text>
    <text x="687" y="180" font-weight="700">it says</text>
    <text x="687" y="194">Start request repeated too quickly</text>
    <text x="687" y="208">NRestarts=4 · Result=exit-code</text>
    <text x="687" y="222">ValueError: invalid literal ... 'eighty'</text>
    <text x="687" y="244" font-weight="700">fix</text>
    <text x="687" y="258">the config; reset-failed; start</text>
    <text x="687" y="272">the brake protected the box</text>
    <text x="687" y="296" opacity="0.7">lessons 09, 11</text>
  </g>
  <rect x="30" y="330" width="840" height="46" rx="9" fill="#0fa07f" fill-opacity="0.10" stroke="#0fa07f" stroke-width="1.5" stroke-linejoin="round"/>
  <text x="450" y="350" text-anchor="middle" font-size="9.5" font-weight="700" fill="#0fa07f">5 · up but slow: strace -f -p MAINPID -e trace=accept4,openat,write,sendto during one request</text>
  <text x="450" y="366" text-anchor="middle" font-size="8.5" fill="currentColor">accept4 → openat("/var/lib/app/notes.jsonl", O_WRONLY|O_CREAT|O_APPEND) → write(5, ..., 49) → write(1, "request ...") : one request, four syscalls, in order (lessons 01, 07)</text>
  <text x="450" y="392" text-anchor="middle" font-size="9.5" fill="currentColor" opacity="0.72">Nothing in these five columns is new. The capstone is the phase's tools, pointed at the phase's own deployment.</text>
</svg>
```

Fault 1 is the supervisor doing its job, and the real question it leaves is who sent signal 9 (lesson 12's kernel log if it was the OOM killer). Fault 2 is the one that hides: the service starts, `/health` is green, and the first write fails; the journal has the traceback and `stat` has the cause. Fault 3 is lesson 14's `EADDRINUSE` with `ss -tlnp` naming the holder. Fault 4 is a crash loop caught by the start limit, which is what the brake in lesson 11 was for. And fault 5 is not a fault at all, it is the habit: `strace` on the main process during one request shows the four syscalls that request is made of, which is where a slow request is measured.

## Build It

The capstone's code is in [`code/`](../code/): [`provision.sh`](../code/provision.sh), [`verify.sh`](../code/verify.sh), [`app.service`](../code/app.service) and [`app/server.py`](../code/app/server.py), the small note-taking API from the diagram (it reads its config from the environment, writes under `STATE_DIR`, logs to stdout, drains on `TERM`, reloads on `HUP`, and refuses to start as root). Run it on the booted `systemd` box from lesson 11, fresh:

```bash
docker rm -f sysd 2>/dev/null;  docker run -d --rm --privileged --name sysd -v "$PWD":/workspace:ro --tmpfs /run --tmpfs /run/lock phase1-systemd
docker exec -it sysd bash
cd /workspace/phases/01-linux-and-the-command-line/18-capstone-blank-box-to-running-backend/code
useradd -m -s /bin/bash ops;  su - ops -c "ssh-keygen -t ed25519 -N '' -f ~/.ssh/id_ed25519 -q -C ops@laptop"     # the operator's key
OPS_PUBKEY="$(cat /home/ops/.ssh/id_ed25519.pub)" bash provision.sh
bash verify.sh
```

The script's shape is lesson 09's: strict mode, a `log` and a `die`, absolute paths, guards, and each step idempotent. Two excerpts carry most of the phase. The config is written beside its target and renamed, and never overwrites what an operator changed:

```bash
install -d -m 750 -o root -g "$APP_USER" /etc/app
if [[ ! -f /etc/app/app.env ]]; then                           # never overwrite an operator's config
  tmp="$(mktemp /etc/app/app.env.XXXXXX)"                       # lesson 05: write beside, then rename
  printf 'PORT=%s\nBIND=127.0.0.1\nSTATE_DIR=/var/lib/app\nGREETING=hello from the capstone\n' "$PORT" > "$tmp"
  chown root:"$APP_USER" "$tmp"; chmod 640 "$tmp"; mv "$tmp" /etc/app/app.env
fi
```

And the firewall is checked before it is loaded, because a wrong rule on a remote box is a locked door:

```bash
if nft -c -f /etc/nftables.conf 2>/dev/null; then
  nft -f /etc/nftables.conf
  ...
```

The first run, on a box that has nothing:

```console
$ cat /proc/1/comm;  id app;  ls /etc/app
systemd
id: 'app': no such user
ls: cannot access '/etc/app': No such file or directory
$ time bash provision.sh
05:26:00 1/8 packages
05:26:09 2/8 users
05:26:10 3/8 code and config
05:26:10 4/8 unit
05:26:10 5/8 logrotate
05:26:10 6/8 firewall
05:26:10    nftables rules loaded
05:26:10 7/8 ssh
05:26:10    keys only, root login off, AllowUsers ops
05:26:10 8/8 verify
{"status": "ok", "uptime_s": 0.0, "pid": 757, "uid": 995}
05:26:10 done: app is active, healthy on 127.0.0.1:8080, running as app
real    0m9.290s
```

Nine seconds, most of it `apt`. The second run prints the same eight lines and changes nothing. Then the check:

```console
$ bash verify.sh
identity and permissions (lesson 06)
  ok    service user app exists with nologin
  ok    /etc/app/app.env is root:app 640
  ok    app cannot write its own config
  ok    app can write its state dir
  ok    no world-readable secrets under /etc/app
the service (lessons 10, 11)
  ok    unit file verifies
  ok    app.service is active
  ok    app.service is enabled at boot
  ok    main process runs as app, not root
  ok    Restart=on-failure is set
  ok    LimitNOFILE raised above 1024
the network (lessons 14, 15)
  ok    listens on 127.0.0.1:8080 only
  ok    /health answers 200
  ok    POST /api/notes returns 201
  ok    GET /api/notes lists the note
  ok    firewall config exists and parses
logs and rotation (lessons 07, 11)
  ok    journal has the app's listening line
  ok    logrotate config is valid
ssh (lesson 17)
  ok    sshd config is valid
  ok    root login disabled

21 passed, 0 failed
```

## Use It

The box, inspected with the phase's tools. The layout and its owners, exactly as lesson 04's rule said:

```console
$ ls -la /opt/app /etc/app;  ls -ld /var/lib/app /var/log/app /run/app
/etc/app:
drwxr-x--- 1 root app   14 Sep  5 05:26 .
-rw-r----- 1 root app   81 Sep  5 05:26 app.env
/opt/app:
-rw-r--r-- 1 root root  109 Sep  5 05:27 README
-rw-r--r-- 1 root root 3338 Sep  5 05:27 server.py
drwxr-xr-x 2 app app 40 Sep  5 05:27 /run/app
drwxr-xr-x 1 app app 22 Sep  5 05:27 /var/lib/app
drwxr-xr-x 1 app app  0 Sep  5 05:26 /var/log/app
$ stat -c '%A %U:%G %n' /etc/app/app.env /var/lib/app/notes.jsonl
-rw-r----- root:app /etc/app/app.env
-rw-r----- app:app /var/lib/app/notes.jsonl
```

The firewall as loaded, and the operator's login with the exact `sudo` they were given and no more:

```console
$ nft list ruleset | head -9
table inet filter {
        chain input {
                type filter hook input priority filter; policy drop;
                ct state established,related accept
                iif "lo" accept
                ip protocol icmp accept
                ip6 nexthdr ipv6-icmp accept
                tcp dport 22 accept
                tcp dport { 80, 443 } accept
$ su - ops -c 'ssh ops@localhost "id; sudo -n systemctl status app | head -2; sudo -n -u app ls -l /var/lib/app | tail -1; sudo -n cat /etc/app/app.env"'
uid=1000(ops) gid=1000(ops) groups=1000(ops),996(app)
● app.service - App API (capstone)
     Loaded: loaded (/etc/systemd/system/app.service; enabled; preset: enabled)
-rw-r----- 1 app  app  196 Sep  5 05:28 notes.jsonl
sudo: a password is required
```

`ops` may restart, inspect and read logs, may look at the service's files as the service, and may not read the config as root. Now the faults. **Kill it**, and read the supervisor's account:

```console
$ kill -9 $(systemctl show app -p MainPID --value);  sleep 3;  systemctl show app -p MainPID,NRestarts,ActiveState
MainPID=1191
NRestarts=1
ActiveState=active
$ journalctl -u app | grep -E 'code=killed|Scheduled restart|app listening' | tail -3
Sep 05 05:27:16 52da7c3bea79 systemd[1]: app.service: Main process exited, code=killed, status=9/KILL
Sep 05 05:27:18 52da7c3bea79 systemd[1]: app.service: Scheduled restart job, restart counter is at 1.
Sep 05 05:27:18 52da7c3bea79 python3[1191]: app listening on 127.0.0.1:8080 as uid 995, state in /var/lib/app
```

**Make the data file unwritable**, which is the fault that stays green on the dashboard:

```console
$ chown root:root /var/lib/app/notes.jsonl;  chmod 600 /var/lib/app/notes.jsonl
$ curl -s http://127.0.0.1:8080/health
{"status": "ok", "uptime_s": 0.2, "pid": 1606, "uid": 995}
$ curl -s -o /dev/null -w 'POST -> http %{http_code}\n' --json '{"text":"fails"}' http://127.0.0.1:8080/api/notes
POST -> http 000
$ journalctl -u app | grep PermissionError | tail -1
Sep 05 05:28:45 52da7c3bea79 python3[1606]: PermissionError: [Errno 13] Permission denied: '/var/lib/app/notes.jsonl'
$ ps -o user= -p $(systemctl show app -p MainPID --value);  stat -c '%A %U:%G %n' /var/lib/app/notes.jsonl;  sudo -u app sh -c 'echo >> /var/lib/app/notes.jsonl'
app
-rw------- root:root /var/lib/app/notes.jsonl
sh: 1: cannot create /var/lib/app/notes.jsonl: Permission denied
$ chown app:app /var/lib/app/notes.jsonl;  chmod 640 /var/lib/app/notes.jsonl;  curl -s -o /dev/null -w 'POST -> http %{http_code}\n' --json '{"text":"works again"}' http://127.0.0.1:8080/api/notes
POST -> http 201
```

**Steal the port**, and let `ss` name the thief:

```console
$ systemctl stop app;  python3 -m http.server 8080 --bind 127.0.0.1 &  systemctl start app;  sleep 4;  systemctl is-active app
activating
$ journalctl -u app | grep 'Errno 98' | tail -1
Sep 05 05:28:48 52da7c3bea79 python3[1777]: OSError: [Errno 98] Address already in use
$ ss -tlnp 'sport = :8080'
State  Recv-Q Send-Q Local Address:Port Peer Address:Port Process
LISTEN 0      5          127.0.0.1:8080      0.0.0.0:*    users:(("python3",pid=1766,fd=3))
$ kill 1766;  systemctl reset-failed app;  systemctl start app;  sleep 1.5;  systemctl is-active app
active
```

**Break the config**, and watch the start limit hold:

```console
$ sed -i 's/^PORT=.*/PORT=eighty/' /etc/app/app.env;  systemctl restart app;  sleep 12;  systemctl status app | grep -E 'Active|repeated'
     Active: failed (Result: exit-code) since Sat 2026-09-05 05:27:37 UTC; 3s ago
Sep 05 05:27:37 52da7c3bea79 systemd[1]: app.service: Start request repeated too quickly.
$ systemctl show app -p NRestarts,Result;  journalctl -u app | grep ValueError | tail -1
NRestarts=4
Result=exit-code
Sep 05 05:27:35 52da7c3bea79 python3[1287]: ValueError: invalid literal for int() with base 10: 'eighty'
$ sed -i 's/^PORT=.*/PORT=8080/' /etc/app/app.env;  systemctl reset-failed app;  systemctl start app;  sleep 1.5;  curl -s http://127.0.0.1:8080/health
{"status": "ok", "uptime_s": 1.5, "pid": 1304, "uid": 995}
```

**Watch one request** at the syscall level, the way lesson 01 started:

```console
$ strace -f -p $(systemctl show app -p MainPID --value) -e trace=accept4,openat,write,sendto -o /tmp/app.trace &
$ curl -s --json '{"text":"traced"}' http://127.0.0.1:8080/api/notes >/dev/null;  grep -E 'accept4|notes.jsonl|write\(' /tmp/app.trace | head -4
1792  accept4(3, {sa_family=AF_INET, sin_port=htons(33552), sin_addr=inet_addr("127.0.0.1")}, [16], SOCK_CLOEXEC) = 4
1808  openat(AT_FDCWD, "/var/lib/app/notes.jsonl", O_WRONLY|O_CREAT|O_APPEND|O_CLOEXEC, 0666) = 5
1808  write(5, "{\"text\": \"traced\", \"at\": \"2026-0"..., 49) = 49
1808  write(1, "request 127.0.0.1 \"POST /api/not"..., 50) = 50
```

Accept the connection, open the data file with `O_APPEND`, write 49 bytes of note, write the log line to descriptor 1 for the journal. That is the request. And through all of it, the data survived and the counters tell the story:

```console
$ curl -s http://127.0.0.1:8080/api/notes | python3 -c 'import json,sys; d=json.load(sys.stdin); print(len(d["notes"]), "notes survived")';  systemctl show app -p NRestarts --value;  journalctl -u app | wc -l
6 notes survived
1
188
```

Finally a reload and a clean stop, the two signals the phase promised a service would honour:

```console
$ sed -i 's/^GREETING=.*/GREETING=hello after reload/' /etc/app/app.env;  systemctl reload app;  journalctl -u app | tail -1
Sep 05 05:27:43 52da7c3bea79 python3[1304]: SIGHUP: config reloaded
$ systemctl stop app;  journalctl -u app | tail -3
Sep 05 05:27:43 52da7c3bea79 python3[1304]: SIGTERM: draining and exiting 0
Sep 05 05:27:43 52da7c3bea79 systemd[1]: app.service: Deactivated successfully.
Sep 05 05:27:43 52da7c3bea79 systemd[1]: Stopped app.service - App API (capstone).
```

`docker stop sysd` when you are done. Everything you saw happens the same way on a real Debian or Ubuntu server, because a real server is what the box was pretending to be.

## Ship It

The artifact for this lesson is a runbook: [`outputs/runbook-blank-box-to-running-backend.md`](../outputs/runbook-blank-box-to-running-backend.md). It is `provision.sh` at human speed: the eight steps as commands, the lesson each comes from, and the check that proves each one, so that you can do it by hand once and read the script afterwards. Its last section is the fault table for the months that follow: thirteen symptoms, the first command for each, what you will see, and the lesson that explains it. Every row is `journalctl`, `ss`, `stat`, `strace`, `curl` or `nft`, and there is no tool in the table that this phase did not build once by hand.

## Think about it

1. `verify.sh` passes, and a week later `/health` returns 200 while every `POST` fails. Which check would you add to `verify.sh` so that fault 2 cannot hide behind a green health endpoint, and where in `server.py` would you make `/health` itself catch it?
2. The firewall opens 80 and 443 but nothing listens there yet; the app is on 8080 behind loopback. Describe what Phase 11's reverse proxy adds to this box, which lines of `nftables.conf` and `app.env` change, and which do not.
3. `provision.sh` hardens `sshd` only when `OPS_PUBKEY` is set. Explain the lockout that the unconditional version would cause, and the two-terminal test from lesson 17 that the script's design replaces.
4. Rewrite fault 4 so that the crash loop does *not* hit the start limit but the service is still useless. Which unit directive would you have to change, why would that be worse, and what does that say about `Restart=always`?

## Key takeaways

- A correctly deployed service is one picture: **an operator with a key, a firewall with a default drop, a supervised unit, a system user that reads config and writes only its own state, logs on stdout, and a filesystem with a read-only half and a runtime half.** Every part is one lesson of this phase.
- **Provisioning is a script** that is idempotent, checks its inputs before applying them (`visudo -cf`, `systemd-analyze verify`, `nft -c`, `sshd -t`), writes config atomically, never overwrites an operator's edits, and ends with a health check. Nine seconds from blank to healthy.
- **Verification is a script too**: twenty-one facts, grouped by lesson, exit 0 only when all hold. Run it after every deploy.
- The faults that happen are the ones the phase named: a signal, a permission, a port, a config value, and slowness. **`journalctl -u`, `stat`, `ss -tlnp`, `systemctl show`, `strace -p`** find each of them in under a minute, and `reset-failed` plus `start` is the way back after the brake holds.
- **A green health check is not a working service.** The write path is where permissions bite; test it.
- Phase 11 wraps this box in an image, a volume and an orchestrator, and Phase 2 gives the network the full treatment. Neither changes the shape you just built.

**That completes Phase 1.** Next comes [Phase 2: Networking and Protocols](../../02-networking-and-protocols/01-osi-and-tcp-ip-models/), where the packets you watched with `tcpdump` get built from the wire up, layer by layer, in Python.
