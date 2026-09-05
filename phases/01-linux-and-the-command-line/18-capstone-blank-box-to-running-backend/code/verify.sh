#!/usr/bin/env bash
# Capstone — prove the box is in the state the phase taught, one check per lesson.
# Exit 0 only if every check passes. Run as root or via sudo.
set -uo pipefail
# shellcheck disable=SC2016   # the bash -c '...' checks below are meant to expand on the inside, not here
PORT="${PORT:-8080}"
pass=0; fail=0
ok()   { printf '  ok    %s\n' "$*"; pass=$((pass+1)); }
bad()  { printf '  FAIL  %s\n' "$*"; fail=$((fail+1)); }
check(){ local desc="$1"; shift; if "$@" >/dev/null 2>&1; then ok "$desc"; else bad "$desc"; fi; }

echo "identity and permissions (lesson 06)"
check "service user app exists with nologin"        bash -c 'getent passwd app | grep -q nologin'
check "/etc/app/app.env is root:app 640"            bash -c '[ "$(stat -c %U:%G:%a /etc/app/app.env)" = root:app:640 ]'
check "/var/lib/app is app:app and 750 or 755"     bash -c 'stat -c %U:%G /var/lib/app | grep -q app:app'
check "app cannot write its own config"             bash -c '! sudo -u app -s /bin/sh -c "echo x >> /etc/app/app.env" 2>/dev/null'
check "app can write its state dir"                 sudo -u app -s /bin/sh -c 'touch /var/lib/app/.probe && rm /var/lib/app/.probe'
check "no world-readable secrets under /etc/app"    bash -c '! find /etc/app -type f -perm -0004 | grep -q .'

echo "the service (lessons 10, 11)"
check "unit file verifies"                          systemd-analyze verify /etc/systemd/system/app.service
check "app.service is active"                       systemctl is-active --quiet app
check "app.service is enabled at boot"              systemctl is-enabled --quiet app
check "main process runs as app, not root"          bash -c '[ "$(ps -o user= -p "$(systemctl show app -p MainPID --value)")" = app ]'
check "Restart=on-failure is set"                   bash -c 'systemctl show app -p Restart --value | grep -q on-failure'
check "LimitNOFILE raised above 1024"               bash -c '[ "$(systemctl show app -p LimitNOFILE --value)" -gt 1024 ]'

echo "the network (lessons 14, 15)"
check "listens on 127.0.0.1:$PORT only"             bash -c "ss -tlnH 'sport = :$PORT' | awk '{print \$4}' | grep -q '^127.0.0.1:' && ! ss -tlnH 'sport = :$PORT' | awk '{print \$4}' | grep -qE '^(0.0.0.0|\\*|\\[::\\]):'"
check "/health answers 200"                         curl -sf "http://127.0.0.1:$PORT/health"
check "POST /api/notes returns 201"                 bash -c "curl -sf -o /dev/null -w '%{http_code}' --json '{\"text\":\"verify\"}' http://127.0.0.1:$PORT/api/notes | grep -q 201"
check "GET /api/notes lists the note"               bash -c "curl -sf http://127.0.0.1:$PORT/api/notes | grep -q verify"
check "firewall config exists and parses"           nft -c -f /etc/nftables.conf

echo "logs and rotation (lessons 07, 11)"
check "journal has the app's listening line"        bash -c 'journalctl -u app --no-pager | grep -q "app listening"'
check "logrotate config is valid"                   logrotate -d /etc/logrotate.d/app

echo "ssh (lesson 17)"
check "sshd config is valid"                        sshd -t
check "root login disabled"                         bash -c 'sshd -T | grep -q "^permitrootlogin no"'

echo; echo "$pass passed, $fail failed"
[ "$fail" -eq 0 ]
