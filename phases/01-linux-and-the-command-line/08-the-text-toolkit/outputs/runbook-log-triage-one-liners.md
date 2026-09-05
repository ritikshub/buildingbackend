---
name: runbook-log-triage-one-liners
description: The one-liners an on-call engineer runs on a raw log in the first ten minutes — error rate, top offenders, slowest endpoints, requests per minute, a single request's full story, and the JSON-log equivalents with jq — each built from grep, awk, cut, sort, uniq, tr and sed, with the trap beside it
phase: 01
lesson: 08
---

# Log triage in one line

Assume a web-server or application log with one request per line, fields
separated by spaces, in the common format:

```text
10.0.2.17 - - [05/Sep/2026:03:12:44 +0000] "GET /api/orders HTTP/1.1" 500 1834 "-" "curl/8.5.0" 1207ms
$1 (ip)      $4 (time)                    $6 $7 (method path)         $9 $10                 $NF (latency)
```

Adjust the field numbers once with `awk '{print $9}' | head -3` and the
rest follows. Every command streams, so it works on a file bigger than RAM
and on `tail -f` output; only `sort` has to see everything.

## 1 · Is it broken, and how badly?

```bash
# error rate right now (5xx per minute over the last 2,000 lines)
tail -n 2000 access.log | awk '$9 >= 500' | wc -l

# status histogram
awk '{print $9}' access.log | sort | uniq -c | sort -rn

# 5xx by endpoint: WHICH thing is broken
awk '$9 >= 500 {print $7}' access.log | sort | uniq -c | sort -rn | head

# 5xx over time, per minute: WHEN it broke
awk '$9 >= 500 {print substr($4, 2, 17)}' access.log | uniq -c

# live: errors as they happen
tail -f access.log | grep --line-buffered ' 50[0-9] '
```

Traps: `$9 >= 500` compares numbers because awk sees digits; a field with a stray quote compares as a string and matches nothing, so check `awk '{print $9}' | sort -u` first. `grep 500` also matches a 500-byte response size; anchor it with the spaces or use awk.

## 2 · Who is doing it?

```bash
# top client IPs
awk '{print $1}' access.log | sort | uniq -c | sort -rn | head

# top IPs among failures only
awk '$9 >= 400 {print $1}' access.log | sort | uniq -c | sort -rn | head

# one IP's whole day, in order
grep -F '203.0.113.9 ' access.log | less

# failed logins per IP (credential stuffing shows up here)
grep 'POST /login' access.log | awk '$9 == 401 {print $1}' | sort | uniq -c | sort -rn | head

# user agents: bots, scrapers, a broken client version
awk -F'"' '{print $6}' access.log | sort | uniq -c | sort -rn | head
```

Traps: `grep -F` for literal text (dots in an IP are regex "any character" otherwise). `-F'"'` in awk splits on the double quote, which is the easy way to pull a quoted field.

## 3 · What is slow?

```bash
# average latency
awk '{s += $NF} END {print s / NR " ms"}' access.log       # if $NF is like 1207ms, awk reads the number and stops at the m

# slowest 10 requests
sort -t' ' -k12 -rn access.log | head        # sort by the latency column; -t sets the separator, -k picks the field

# p95 latency (sort the numbers, take the row 95% of the way down)
awk '{print $NF+0}' access.log | sort -n | awk '{a[NR]=$1} END {print a[int(NR*0.95)] " ms"}'

# latency by endpoint (average)
awk '{n[$7]++; s[$7] += $NF} END {for (p in n) printf "%8.1f ms %6d  %s\n", s[p]/n[p], n[p], p}' access.log | sort -rn | head

# requests taking over 2 s, with their path
awk '$NF+0 > 2000 {print $NF, $7}' access.log | sort -rn | head
```

Traps: `$NF+0` forces a numeric comparison (`"900ms" > 2000` as strings is wrong). `sort -n` for numbers, `sort -h` for `1.5G`-style sizes, `sort -k` for a field, and `sort` reads the whole input; on a 20 GB file, `grep` first to shrink it.

## 4 · How much traffic?

```bash
# requests per minute
awk '{print substr($4, 2, 17)}' access.log | uniq -c

# requests per second, peak
awk '{print substr($4, 2, 20)}' access.log | uniq -c | sort -rn | head -3

# bytes served per endpoint
awk '{b[$7] += $10} END {for (p in b) print b[p], p}' access.log | sort -rn | head

# distinct clients
awk '{print $1}' access.log | sort -u | wc -l
```

`uniq -c` without a preceding `sort` works only when equal lines are adjacent, which is true for timestamps in a log written in order.

## 5 · One request's whole story

```bash
# everything with this request id, across every log, in time order
grep -rh 'req-8f2a91' /var/log/app/ | sort

# the 20 lines before and after an error
grep -n -B20 -A20 'OutOfMemory' app.log | less

# the first and last time something appeared
grep 'connection refused' app.log | head -1;  grep 'connection refused' app.log | tail -1

# a stack trace: from the exception line to the next blank line
awk '/Traceback/,/^$/' app.log | head -60

# what changed between two runs' logs
diff <(grep -v '^20' run1.log | sort) <(grep -v '^20' run2.log | sort) | head
```

Traps: `grep -r` follows the directory; `-h` drops the filename prefix so `sort` sees clean lines; `-n` gives line numbers you can `sed -n '1200,1260p'` around.

## 6 · Rotated and compressed logs

```bash
zgrep ' 502 ' /var/log/app/access.log.*.gz | wc -l      # grep inside .gz without extracting
zcat access.log.3.gz | awk '{print $9}' | sort | uniq -c
journalctl -u app --since '1 hour ago' -o cat | grep ERROR   # systemd's journal as plain lines (lesson 11)
```

## 7 · JSON logs: the same questions with jq

One JSON object per line (`{"ts":..., "ip":..., "req":{"method":"GET","path":"/x"}, "status":500, "ms":1207}`):

```bash
jq -r '.status' app.jsonl | sort | uniq -c | sort -rn                 # status histogram
jq -r 'select(.status >= 500) | .req.path' app.jsonl | sort | uniq -c | sort -rn   # 5xx by path
jq -r 'select(.ms > 2000) | "\(.ms) \(.req.path)"' app.jsonl | sort -rn | head    # slow, formatted
jq -r '.ip' app.jsonl | sort | uniq -c | sort -rn | head               # top IPs
jq -c 'select(.ip == "203.0.113.9")' app.jsonl                          # one client, whole objects
jq -r '[.ts, .status, .req.path] | @tsv' app.jsonl | head              # to columns, for awk or a spreadsheet
jq -s 'map(.ms) | add / length' app.jsonl                               # average (-s slurps the whole file: not streaming)
```

Traps: `-r` prints strings raw (no quotes); without it every value is JSON. `select()` filters objects; `.a.b` walks keys; `.[0]` indexes arrays; `//` gives a default (`.user // "anon"`). Names survive schema changes; `$9` does not.

## 8 · Making a one-liner permanent

- Put it in a script with a shebang, `set -euo pipefail`, and a comment saying what question it answers (lesson 09).
- If it has an `awk` longer than one screen, it is a Python script now.
- If you run it more than daily, it is a metric (Phase 10): count it at the source instead of grepping for it after.
