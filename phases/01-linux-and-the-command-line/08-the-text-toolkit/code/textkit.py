"""
The Text Toolkit — grep, awk, cut, sort | uniq -c, tr and a jq-shaped
extractor, rebuilt as streaming filters.

Every tool in this lesson is the lesson 05 loop with one more idea: it
works one LINE at a time, so it can process a file larger than RAM and
start printing before the input has finished arriving. grep is a regex
test per line; awk is "split the line into fields, then run a small
program"; cut is a field or column slice; sort | uniq -c is the counting
idiom (and sort is the one that cannot stream); tr is a byte map; jq is
"parse the JSON on this line, then walk a path". The script generates a
realistic web-server log, then answers the questions an on-call engineer
asks of one, first with these functions and (in the docs) with the real
tools, producing identical output. Self-terminating.

Docs: phases/01-linux-and-the-command-line/08-the-text-toolkit/docs/en.md
Spec: POSIX.1-2017 grep, awk, cut, sort, uniq, tr, sed (XCU); POSIX
      Extended Regular Expressions (XBD 9.4); RFC 8259 (JSON)

Run:
    python textkit.py            # builds access.log in a temp dir and analyses it
    python textkit.py --keep     # leaves access.log so you can run the real tools on it
"""

import collections
import json
import os
import random
import re
import sys
import tempfile
import time


def banner(title):
    line = "=" * 72
    print(f"\n{line}\n{title}\n{line}")


# ─── the filters ─────────────────────────────────────────────────────────────
def lines(path):
    """The loop under every tool here: yield one line at a time, never the whole file."""
    with open(path, "rb") as f:
        for raw in f:
            yield raw.rstrip(b"\n").decode("utf-8", "replace")


def grep(pattern, src, invert=False, ignore_case=False, count=False, only=False):
    """grep: a compiled regex tested against each line; print the ones that match."""
    rx = re.compile(pattern, re.IGNORECASE if ignore_case else 0)
    n = 0
    for line in src:
        m = rx.search(line)
        if bool(m) != invert:
            n += 1
            if not count:
                yield m.group(0) if (only and m) else line
    if count:
        yield str(n)


def awk(src, program, sep=None):
    """awk: split each line into $1..$NF on whitespace (or sep), run `program(fields)`.
    The program returns a string to print, or None to print nothing."""
    for line in src:
        fields = line.split(sep) if sep else line.split()
        out = program(fields, line)
        if out is not None:
            yield out


def cut(src, fields=None, delim=" ", chars=None):
    """cut -d delim -f N, or cut -c a-b: slice by delimiter or by column."""
    for line in src:
        if chars:
            a, b = chars
            yield line[a - 1:b]
        else:
            parts = line.split(delim)
            yield delim.join(parts[i - 1] for i in fields if i - 1 < len(parts))


def sort_uniq_c(src, reverse=True, top=None):
    """sort | uniq -c | sort -rn, as one Counter. sort cannot stream: it must see every line."""
    counts = collections.Counter(src)
    rows = counts.most_common(top) if reverse else sorted(counts.items())
    for value, n in rows:
        yield f"{n:7d} {value}"


def tr(src, frm, to):
    """tr: a byte-for-byte character map; the same length on both sides."""
    table = str.maketrans(frm, to)
    for line in src:
        yield line.translate(table)


def sed_s(src, pattern, repl, flags=""):
    """sed 's/pattern/repl/' per line; the 'g' flag replaces every match."""
    rx = re.compile(pattern)
    for line in src:
        yield rx.sub(repl, line, count=0 if "g" in flags else 1)


def jq(src, path):
    """jq '.a.b[0]': parse each line as JSON and walk a path of keys and indexes."""
    steps = [int(p) if p.isdigit() else p for p in re.findall(r"[A-Za-z_]\w*|\d+", path)]
    for line in src:
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        for step in steps:
            obj = obj[step] if isinstance(obj, (dict, list)) else None
            if obj is None:
                break
        yield json.dumps(obj) if not isinstance(obj, str) else obj


def head(src, n):
    for i, line in enumerate(src):
        if i >= n:
            return
        yield line


# ─── a realistic log to ask questions of ─────────────────────────────────────
def make_log(path, n=20000):
    random.seed(7)
    ips = [f"10.0.{random.randint(0, 3)}.{random.randint(1, 250)}" for _ in range(60)] + ["203.0.113.9"] * 6
    paths = ["/", "/login", "/api/orders", "/api/orders/42", "/api/users/me", "/static/app.js", "/health", "/checkout", "/admin"]
    ua = ["curl/8.5.0", "Mozilla/5.0 (X11; Linux x86_64)", "python-requests/2.32", "Go-http-client/2.0"]
    t0 = time.mktime((2026, 9, 5, 3, 0, 0, 0, 0, 0))
    with open(path, "w") as f, open(path + ".jsonl", "w") as j:
        for i in range(n):
            ip = random.choice(ips)
            p = random.choice(paths)
            method = "POST" if p in ("/login", "/checkout") else "GET"
            status = random.choices([200, 200, 200, 200, 301, 404, 500, 502], weights=[70, 10, 8, 4, 2, 4, 1.5, 0.5])[0]
            if p == "/admin":
                status = 403 if random.random() < 0.9 else 200
            if ip == "203.0.113.9" and p == "/login":
                status = 401
            ms = int(random.lognormvariate(3.2, 0.9)) + (900 if status >= 500 else 0)
            size = random.randint(120, 48000)
            ts = time.strftime("%d/%b/%Y:%H:%M:%S +0000", time.gmtime(t0 + i * 0.36))
            f.write(f'{ip} - - [{ts}] "{method} {p} HTTP/1.1" {status} {size} "-" "{random.choice(ua)}" {ms}ms\n')
            j.write(json.dumps({"ts": ts, "ip": ip, "req": {"method": method, "path": p}, "status": status, "ms": ms}) + "\n")


if __name__ == "__main__":
    work = tempfile.mkdtemp(prefix="textkit-")
    log = os.path.join(work, "access.log")
    make_log(log)
    n_lines = sum(1 for _ in lines(log))
    print(f"wrote {log}: {n_lines:,} lines, {os.path.getsize(log):,} bytes, plus access.log.jsonl")
    print('one line: ' + next(lines(log)))

    banner("1 · grep: which lines mention 500?  (a regex per line; the file is never in memory)")
    for l in head(grep(r'" 50[0-9] ', lines(log)), 3):
        print("   " + l)
    print("   ...", next(grep(r'" 50[0-9] ', lines(log), count=True)), "lines with a 5xx status   <- grep -c")
    print("   grep -v 200 | wc -l ->", sum(1 for _ in grep(r'" 200 ', lines(log), invert=True)), "non-200 lines")
    print("   grep -o 'GET [^ ]*' | head -2 ->", list(head(grep(r"GET [^ ]*", lines(log), only=True), 2)))

    banner("2 · awk: split into fields, then a tiny program per line")
    print("   awk '{print $1}' | head -3 ->", list(head(awk(lines(log), lambda f, _: f[0]), 3)))
    print("   awk '$9 >= 500' | wc -l ->", sum(1 for _ in awk(lines(log), lambda f, _: f[8] if int(f[8]) >= 500 else None)), "  (field 9 is the status; a condition with no action prints the line)")
    total = 0.0
    for v in awk(lines(log), lambda f, _: f[-1].rstrip("ms")):
        total += float(v)
    print(f"   awk '{{s += $NF}} END {{print s / NR}}' -> {total / n_lines:.1f} ms average latency   ($NF is the last field; END runs once)")
    slow = list(awk(lines(log), lambda f, _: f"{f[6]} {f[-1]}" if int(f[-1].rstrip("ms")) > 1000 else None))
    print(f"   awk '$NF+0 > 1000 {{print $7, $NF}}' -> {len(slow)} requests over 1 s; first: {slow[:2]}")

    banner("3 · cut: a column slice, when the fields are regular")
    print("   cut -d' ' -f1,9 | head -3 ->", list(head(cut(lines(log), fields=[1, 9]), 3)))
    print("   cut -c1-15 | head -2      ->", list(head(cut(lines(log), chars=(1, 15)), 2)))
    print("   cut cannot do what awk can: it splits on ONE character, so runs of spaces make empty fields")

    banner("4 · sort | uniq -c | sort -rn: the counting idiom (the one stage that cannot stream)")
    print("   top client IPs:  awk '{print $1}' | sort | uniq -c | sort -rn | head -5")
    for row in sort_uniq_c(awk(lines(log), lambda f, _: f[0]), top=5):
        print("   " + row)
    print("   status histogram:  awk '{print $9}' | sort | uniq -c | sort -rn")
    for row in sort_uniq_c(awk(lines(log), lambda f, _: f[8])):
        print("   " + row)
    print("   which paths 5xx:  grep '\" 50' | awk '{print $7}' | sort | uniq -c | sort -rn | head -3")
    for row in sort_uniq_c(awk(grep(r'" 50[0-9] ', lines(log)), lambda f, _: f[6]), top=3):
        print("   " + row)

    banner("5 · The on-call question: who is hammering /login and failing?")
    print("   grep 'POST /login' | grep ' 401 ' | awk '{print $1}' | sort | uniq -c | sort -rn | head -3")
    for row in sort_uniq_c(awk(grep(r" 401 ", grep(r"POST /login", lines(log))), lambda f, _: f[0]), top=3):
        print("   " + row)
    print("   one IP, hundreds of failed logins: that is a credential-stuffing attempt (Phase 8, lesson 12), found in one pipeline")

    banner("6 · Requests per minute: cut the timestamp, count it")
    print("   awk '{print substr($4, 2, 17)}' | uniq -c | head -3   (uniq alone works because the log is already in time order)")
    rows = list(head(sort_uniq_c(awk(lines(log), lambda f, _: f[3][1:18]), reverse=False), 3))
    for row in rows:
        print("   " + row)

    banner("7 · sed and tr: rewriting instead of selecting")
    print("   sed 's/10\\.0\\./INTERNAL./' | head -1 ->", next(sed_s(lines(log), r"10\.0\.", "INTERNAL.")))
    print("   tr 'a-z' 'A-Z' | head -1            ->", next(tr(head(lines(log), 1), "abcdefghijklmnopqrstuvwxyz", "ABCDEFGHIJKLMNOPQRSTUVWXYZ"))[:60] + "...")
    print("   tr -d '\"'  removes characters; tr -s ' ' squeezes repeats; both are byte maps, not regexes")

    banner("8 · jq: the same questions when the log is JSON lines")
    jl = log + ".jsonl"
    print("   first line:", next(lines(jl))[:100] + "...")
    print("   jq -r '.req.path' | head -3 ->", list(head(jq(lines(jl), ".req.path"), 3)))
    print("   jq -r 'select(.status >= 500) | .req.path' | sort | uniq -c:")
    def sel(line):
        o = json.loads(line)
        return o["req"]["path"] if o["status"] >= 500 else None
    for row in sort_uniq_c(awk(lines(jl), lambda f, line: sel(line)), top=3):
        print("   " + row)
    print("   a JSON log needs no field numbers: names survive when someone adds a column, which $9 does not")

    if "--keep" in sys.argv:
        print(f"\nkept {work}; try the real tools:  cd {work} && awk '{{print $9}}' access.log | sort | uniq -c | sort -rn")
    else:
        import shutil
        shutil.rmtree(work)
        print(f"\nremoved {work}")
