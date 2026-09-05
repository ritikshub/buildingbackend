"""
curl, Part 1 — a mini curl on http.client that prints exactly what goes on
the wire, so that every option is a header, a body or a follow-up request
you can see.

Supports the options this lesson teaches: -X, -H, -d, --data-urlencode,
--json, -F (multipart), -u (Basic), -b (send cookies), -c (save them),
-A, -e, -o, -O, -L, -i, -I, -s, -v. With -v it prints the request lines
prefixed with ">" and the response lines with "<", which is curl's own
convention. Runs a scripted tour against the echo server by default;
pass a URL and options to use it as a tool.

Docs: phases/01-linux-and-the-command-line/15-curl-part-1-requests/docs/en.md
Spec: RFC 9110 (HTTP semantics: methods, headers, status codes, redirects),
      RFC 9112 (HTTP/1.1 message syntax), RFC 7617 (Basic auth),
      RFC 6265 (cookies), RFC 7578 (multipart/form-data)

Run:
    python echo_server.py &            # in another terminal, or backgrounded
    python minicurl.py                 # the tour
    python minicurl.py -v -X POST --json '{"a":1}' http://127.0.0.1:8089/anything
"""

import base64
import http.client
import json
import os
import ssl
import sys
import uuid
from urllib.parse import urlencode, urlparse


def build(argv):
    """Parse a curl-shaped argv into a request description."""
    req = {"method": None, "headers": {}, "body": None, "url": None, "follow": False, "include": False,
           "head": False, "verbose": False, "silent": False, "out": None, "cookie_jar": None, "form": []}
    i = 0
    while i < len(argv):
        a = argv[i]
        nxt = argv[i + 1] if i + 1 < len(argv) else None
        if a == "-X":
            req["method"] = nxt; i += 1
        elif a == "-H":
            k, _, v = nxt.partition(":"); req["headers"][k.strip()] = v.strip(); i += 1
        elif a in ("-d", "--data", "--data-raw"):
            req["body"] = (req["body"] + "&" if req["body"] else "") + nxt          # -d implies POST and a form body
            req["headers"].setdefault("Content-Type", "application/x-www-form-urlencoded"); i += 1
        elif a == "--data-urlencode":
            k, _, v = nxt.partition("="); piece = urlencode({k: v}) if k else urlencode({"": v})[1:]
            req["body"] = (req["body"] + "&" if req["body"] else "") + piece
            req["headers"].setdefault("Content-Type", "application/x-www-form-urlencoded"); i += 1
        elif a == "--json":
            req["body"] = nxt; req["headers"]["Content-Type"] = "application/json"
            req["headers"].setdefault("Accept", "application/json"); i += 1
        elif a == "-F":
            req["form"].append(nxt); i += 1
        elif a == "-u":
            user_pass = nxt.encode(); req["headers"]["Authorization"] = "Basic " + base64.b64encode(user_pass).decode(); i += 1
        elif a == "-b":
            req["headers"]["Cookie"] = open(nxt).read().strip() if os.path.exists(nxt) else nxt; i += 1
        elif a == "-c":
            req["cookie_jar"] = nxt; i += 1
        elif a == "-A":
            req["headers"]["User-Agent"] = nxt; i += 1
        elif a == "-e":
            req["headers"]["Referer"] = nxt; i += 1
        elif a == "-o":
            req["out"] = nxt; i += 1
        elif a == "-O":
            req["out"] = "remote-name"
        elif a == "-L":
            req["follow"] = True
        elif a == "-i":
            req["include"] = True
        elif a == "-I":
            req["head"] = True
        elif a == "-v":
            req["verbose"] = True
        elif a in ("-s", "-sS"):
            req["silent"] = True
        elif a.startswith("-"):
            sys.exit(f"minicurl: unknown option {a}")
        else:
            req["url"] = a
        i += 1
    if req["form"]:                                                   # multipart/form-data, RFC 7578
        boundary = "------------------------" + uuid.uuid4().hex[:16]
        parts = []
        for f in req["form"]:
            name, _, value = f.partition("=")
            if value.startswith("@"):
                path = value[1:]
                with open(path, "rb") as fh:
                    data = fh.read()
                parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"; filename="{os.path.basename(path)}"\r\nContent-Type: application/octet-stream\r\n\r\n'.encode() + data + b"\r\n")
            else:
                parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
        req["body"] = b"".join(parts) + f"--{boundary}--\r\n".encode()
        req["headers"]["Content-Type"] = f"multipart/form-data; boundary={boundary}"
    if req["method"] is None:
        req["method"] = "HEAD" if req["head"] else ("POST" if req["body"] is not None else "GET")
    return req


def do_request(req, url):
    u = urlparse(url)
    conn_cls = http.client.HTTPSConnection if u.scheme == "https" else http.client.HTTPConnection
    kwargs = {"context": ssl.create_default_context()} if u.scheme == "https" else {}
    conn = conn_cls(u.hostname, u.port or (443 if u.scheme == "https" else 80), timeout=10, **kwargs)
    path = (u.path or "/") + (("?" + u.query) if u.query else "")
    headers = {"Host": u.netloc, "User-Agent": "minicurl/0.1", "Accept": "*/*", **req["headers"]}
    body = req["body"].encode() if isinstance(req["body"], str) else req["body"]
    if body is not None:
        headers["Content-Length"] = str(len(body))
    if req["verbose"]:
        print(f"> {req['method']} {path} HTTP/1.1", file=sys.stderr)
        for k, v in headers.items():
            print(f"> {k}: {v}", file=sys.stderr)
        print(">", file=sys.stderr)
        if body and len(body) <= 200 and req["headers"].get("Content-Type", "").startswith(("application/x-www-form", "application/json")):
            print(f"> {body.decode(errors='replace')}", file=sys.stderr)
    conn.putrequest(req["method"], path, skip_host=True, skip_accept_encoding=True)
    for k, v in headers.items():
        conn.putheader(k, v)
    conn.endheaders(body)
    resp = conn.getresponse()
    data = resp.read() if req["method"] != "HEAD" else b""
    if req["verbose"]:
        print(f"< HTTP/1.1 {resp.status} {resp.reason}", file=sys.stderr)
        for k, v in resp.getheaders():
            print(f"< {k}: {v}", file=sys.stderr)
        print("<", file=sys.stderr)
    conn.close()
    return resp, data


def run(argv):
    req = build(argv)
    url = req["url"]
    for hop in range(10):
        resp, data = do_request(req, url)
        if req["cookie_jar"]:
            for k, v in resp.getheaders():
                if k.lower() == "set-cookie":
                    with open(req["cookie_jar"], "w") as f:
                        f.write(v.split(";")[0] + "\n")
        if req["follow"] and resp.status in (301, 302, 303, 307, 308) and resp.getheader("Location"):
            loc = resp.getheader("Location")
            u = urlparse(url)
            url = loc if loc.startswith("http") else f"{u.scheme}://{u.netloc}{loc}"
            if resp.status in (301, 302, 303) and req["method"] not in ("GET", "HEAD"):
                req["method"], req["body"] = "GET", None                   # what curl does on 30x without --post301
            continue
        break
    out = b""
    if req["include"] or req["head"]:
        out += f"HTTP/1.1 {resp.status} {resp.reason}\r\n".encode() + "".join(f"{k}: {v}\r\n" for k, v in resp.getheaders()).encode() + b"\r\n"
    out += data
    if req["out"]:
        name = os.path.basename(urlparse(url).path) or "index.html" if req["out"] == "remote-name" else req["out"]
        with open(name, "wb") as f:
            f.write(data)
        if not req["silent"]:
            print(f"minicurl: saved {len(data)} bytes to {name}", file=sys.stderr)
    else:
        sys.stdout.write(out.decode(errors="replace"))
        sys.stdout.flush()
    return resp.status


TOUR = [
    ("GET, verbose: the whole exchange", ["-v", "http://127.0.0.1:8089/"]),
    ("-I: HEAD, headers only", ["-I", "http://127.0.0.1:8089/json"]),
    ("-i: the status line and headers, then the body", ["-i", "http://127.0.0.1:8089/json"]),
    ("-H: any header you like", ["-H", "X-Request-Id: abc-123", "-H", "Accept: application/json", "http://127.0.0.1:8089/"]),
    ("-d: a form body, and POST is implied", ["-d", "name=ada", "-d", "lang=python", "http://127.0.0.1:8089/anything"]),
    ("--data-urlencode: the & and = in your value survive", ["--data-urlencode", "q=a&b=c d", "http://127.0.0.1:8089/anything"]),
    ("--json: a JSON body with the two headers set", ["--json", '{"user": "ada", "tags": ["x", "y"]}', "http://127.0.0.1:8089/anything"]),
    ("-X PUT with a body", ["-X", "PUT", "--json", '{"v": 2}', "http://127.0.0.1:8089/items/42"]),
    ("-F: multipart form with a file", ["-F", "note=hello", "-F", "file=@/tmp/minicurl-upload.txt", "http://127.0.0.1:8089/upload"]),
    ("-u: Basic auth", ["-u", "user:secret", "http://127.0.0.1:8089/auth"]),
    ("-u with the wrong password: 401", ["-i", "-u", "user:nope", "http://127.0.0.1:8089/auth"]),
    ("-c then -b: save a cookie, send it back", ["-c", "/tmp/jar.txt", "http://127.0.0.1:8089/cookie"]),
    ("-b: sending the saved cookie", ["-b", "/tmp/jar.txt", "http://127.0.0.1:8089/cookie"]),
    ("-L: follow redirects (three hops)", ["-v", "-L", "http://127.0.0.1:8089/redirect3"]),
    ("no -L: a redirect is just a 302 with a Location header", ["-i", "http://127.0.0.1:8089/redirect"]),
    ("-o: save the body to a file", ["-o", "/tmp/json.out", "http://127.0.0.1:8089/json"]),
    ("-A and -e: user agent and referer", ["-A", "Mozilla/5.0 (pretend)", "-e", "https://example.com/", "http://127.0.0.1:8089/"]),
]

if __name__ == "__main__":
    sys.stdout.reconfigure(line_buffering=True)                  # keep our stdout in step with the -v lines on stderr
    if len(sys.argv) > 1:
        sys.exit(0 if run(sys.argv[1:]) < 400 else 22)
    with open("/tmp/minicurl-upload.txt", "w") as f:
        f.write("a small file to upload\n")
    for title, argv in TOUR:
        print(f"\n=== {title}\n$ minicurl {' '.join(repr(a) if ' ' in a or '{' in a else a for a in argv)}")
        try:
            run(argv)
        except (ConnectionRefusedError, OSError) as e:
            sys.exit(f"echo server not running? ({e}). Start it: python echo_server.py &")
