#!/usr/bin/env bash
# Capstone — take a blank Debian box to a running, supervised, firewalled backend.
#
# Idempotent: run it twice and the second run changes nothing. Every step is a
# lesson from this phase, marked in the comments. It only needs root, python3
# and apt; it installs the rest. Tested on the lesson 11 systemd sandbox and
# on a plain Debian 13 VM.
#
# Docs: phases/01-linux-and-the-command-line/18-capstone-blank-box-to-running-backend/docs/en.md
# Run:  sudo bash provision.sh            (from the directory holding app/, app.service, and the config below)

set -euo pipefail                                             # lesson 09
IFS=$'\n\t'

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_USER=app
OPS_USER="${OPS_USER:-ops}"
OPS_PUBKEY="${OPS_PUBKEY:-}"                                  # the operator's public key; empty = keep password login for now
PORT="${PORT:-8080}"

log() { printf '%s %s\n' "$(date +%H:%M:%S)" "$*" >&2; }
die() { log "ERROR: $*"; exit 1; }

[[ "$(id -u)" == 0 ]] || die "run as root (sudo)"             # lesson 06
[[ -f "$HERE/app/server.py" && -f "$HERE/app.service" ]] || die "run from the capstone's code directory"

# ── 1 · packages (lesson 13) ─────────────────────────────────────────────────
log "1/8 packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq --no-install-recommends python3 curl nftables logrotate rsync openssh-server sudo iproute2 procps strace >/dev/null

# ── 2 · users (lesson 06) ────────────────────────────────────────────────────
log "2/8 users"
getent group "$APP_USER" >/dev/null || groupadd --system "$APP_USER"
id "$APP_USER" &>/dev/null || useradd --system --gid "$APP_USER" --home-dir /var/lib/app --shell /usr/sbin/nologin "$APP_USER"
id "$OPS_USER" &>/dev/null || useradd -m -s /bin/bash -G "$APP_USER" "$OPS_USER"
install -d -m 750 -o root -g root /etc/sudoers.d
cat > /etc/sudoers.d/ops <<SUDO
$OPS_USER ALL=(ALL) NOPASSWD: /usr/bin/systemctl restart app, /usr/bin/systemctl status app, /usr/bin/systemctl reload app, /usr/bin/journalctl
$OPS_USER ALL=($APP_USER) NOPASSWD: ALL
SUDO
chmod 440 /etc/sudoers.d/ops
visudo -cf /etc/sudoers.d/ops >/dev/null || die "sudoers syntax"

# ── 3 · the code and its config (lessons 04, 05, 06) ─────────────────────────
log "3/8 code and config"
install -d -m 755 -o root -g root /opt/app                     # read-only half: root owns it
install -m 644 -o root -g root "$HERE/app/server.py" /opt/app/server.py
printf 'A note-taking API. Unit: app.service. Config: /etc/app/app.env. Data: /var/lib/app. Logs: journalctl -u app.\n' > /opt/app/README
install -d -m 750 -o root -g "$APP_USER" /etc/app
if [[ ! -f /etc/app/app.env ]]; then                           # never overwrite an operator's config
  tmp="$(mktemp /etc/app/app.env.XXXXXX)"                       # lesson 05: write beside, then rename
  printf 'PORT=%s\nBIND=127.0.0.1\nSTATE_DIR=/var/lib/app\nGREETING=hello from the capstone\n' "$PORT" > "$tmp"
  chown root:"$APP_USER" "$tmp"; chmod 640 "$tmp"; mv "$tmp" /etc/app/app.env
fi

# ── 4 · the unit (lesson 11) ─────────────────────────────────────────────────
log "4/8 unit"
install -m 644 "$HERE/app.service" /etc/systemd/system/app.service
systemd-analyze verify /etc/systemd/system/app.service
systemctl daemon-reload
systemctl enable --now app >/dev/null 2>&1 || true
systemctl restart app

# ── 5 · log rotation for anything under /var/log/app (lesson 11) ─────────────
log "5/8 logrotate"
cat > /etc/logrotate.d/app <<'LR'
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
LR

# ── 6 · the firewall (lesson 14) ─────────────────────────────────────────────
log "6/8 firewall"
cat > /etc/nftables.conf <<'NFT'
#!/usr/sbin/nft -f
flush ruleset
table inet filter {
    chain input {
        type filter hook input priority 0; policy drop;
        ct state established,related accept
        iif lo accept
        ip protocol icmp accept
        ip6 nexthdr icmpv6 accept
        tcp dport 22 accept
        tcp dport { 80, 443 } accept
        # 8080 is NOT opened: the app binds 127.0.0.1 and a reverse proxy (Phase 11) fronts it
    }
    chain forward { type filter hook forward priority 0; policy drop; }
    chain output  { type filter hook output priority 0; policy accept; }
}
NFT
if nft -c -f /etc/nftables.conf 2>/dev/null; then
  nft -f /etc/nftables.conf
  if ! systemctl enable nftables >/dev/null 2>&1; then log "   (nftables unit not enabled; rules are live)"; fi
  log "   nftables rules loaded"
else
  log "   (nft not permitted here: rules written to /etc/nftables.conf, load on a real box)"
fi

# ── 7 · ssh hardening (lesson 17): keys only, once a key is installed ────────
log "7/8 ssh"
if [[ -n "$OPS_PUBKEY" ]]; then
  install -d -m 700 -o "$OPS_USER" -g "$OPS_USER" "/home/$OPS_USER/.ssh"
  grep -qF "$OPS_PUBKEY" "/home/$OPS_USER/.ssh/authorized_keys" 2>/dev/null || echo "$OPS_PUBKEY" >> "/home/$OPS_USER/.ssh/authorized_keys"
  chown "$OPS_USER:$OPS_USER" "/home/$OPS_USER/.ssh/authorized_keys"; chmod 600 "/home/$OPS_USER/.ssh/authorized_keys"
  printf 'PasswordAuthentication no\nKbdInteractiveAuthentication no\nPermitRootLogin no\nMaxAuthTries 3\nX11Forwarding no\nAllowUsers %s\n' "$OPS_USER" > /etc/ssh/sshd_config.d/10-hardening.conf
  sshd -t && systemctl reload ssh 2>/dev/null || systemctl restart ssh 2>/dev/null || true
  log "   keys only, root login off, AllowUsers $OPS_USER"
else
  log "   OPS_PUBKEY not set: sshd left as installed (set it to harden)"
fi

# ── 8 · verify (lessons 12, 14, 15) ──────────────────────────────────────────
log "8/8 verify"
for _ in 1 2 3 4 5 6 7 8 9 10; do
  curl -sf "http://127.0.0.1:$PORT/health" >/dev/null && break
  sleep 0.5
done
curl -sf "http://127.0.0.1:$PORT/health" || die "health check failed: journalctl -u app -n 30"
systemctl is-active --quiet app || die "unit not active"
log "done: app is active, healthy on 127.0.0.1:$PORT, running as $(ps -o user= -p "$(systemctl show app -p MainPID --value)")"
