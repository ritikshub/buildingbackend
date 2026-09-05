# curl: Requests

> `curl --help all` lists **269** options. Every one of them changes a header, a body, a connection setting, or what curl prints; nothing else exists. This lesson builds a mini `curl` on `http.client` that prints the request it sends with `>` and the response it gets with `<`, exactly as `curl -v` does, and runs it against a local echo server that shows what arrived. Then it teaches the thirty real options that cover most of what a backend engineer types: `-v -i -I -H -d --json -F -u -b -c -L -o -O -f -s -A -e`, what each puts on the wire, and the mistake beside each one.

## The Problem

`curl` is the tool you will use more than any other in this phase, and most people use it as a slower browser: `curl url`, look, done. Then a deploy needs a health check with a token, a bug needs the exact bytes a client sent, a colleague's API wants a multipart upload, a login needs a cookie jar, and the script that "worked" saved a 404 page as `release.tar.gz` because nobody told curl that an HTTP error is an error.

The way out is not memorising 269 options. It is knowing that HTTP is text (Phase 2 lesson 08 reads it; lesson 09 writes a server for it), that a request is a method, a path, headers and maybe a body, and that every `curl` option is one of those four things or a note about where to put the answer. Once you can see the request, the options become obvious, and `-v` lets you see it every time.

## The Concept

### Every option is a line on the wire

Run `curl -v` and it prints the request it sent, one `>` per line, and the response it received, one `<` per line. Read those lines and you have read the whole protocol:

```console
$ curl -v http://127.0.0.1:8089/
> GET / HTTP/1.1
> Host: 127.0.0.1:8089
> User-Agent: curl/8.14.1
> Accept: */*
>
< HTTP/1.1 200 OK
< Server: echo/1.0 Python/3.12.14
< Content-Type: text/plain; charset=utf-8
< Content-Length: 113
<
you sent: GET / HTTP/1.1
...
```

Four lines went out: a **request line** (method, path, version) and three headers curl adds by itself (`Host` from the URL, its own `User-Agent`, `Accept: */*`), then a blank line meaning "no body." The options in this lesson change exactly those lines:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 470" width="100%" style="max-width:880px" font-family="'JetBrains Mono', ui-monospace, monospace" role="img" aria-label="An HTTP request as curl -v prints it, with the curl option that produces each line drawn beside it. The request line GET slash HTTP 1.1: the method comes from -X, or is implied as POST by -d, -F and --json, or HEAD by -I; the path comes from the URL, and -G moves -d data into the query string. Host: from the URL, overridable with -H Host or --resolve. User-Agent: curl by default, -A changes it. Accept star slash star: default, -H Accept changes it, --json sets application/json. Optional lines: Authorization from -u as Basic or -H for a Bearer token; Cookie from -b; Referer from -e; Content-Type and Content-Length from -d, --json or -F; any header at all from -H. Then the blank line and the body: form-encoded from -d, JSON from --json, multipart from -F, a raw file from -T. On the response side, -i includes the status line and headers in the output, -I asks for headers only, -o and -O save the body, -L follows a Location header, -c saves Set-Cookie, and -f turns a 4xx or 5xx status into an exit code.">
  <text x="450" y="26" text-anchor="middle" font-size="14.5" font-weight="700" fill="currentColor">The request curl -v shows you, and the option behind every line of it</text>
  <rect x="40" y="48" width="400" height="330" rx="10" fill="#7c5cff" fill-opacity="0.08" stroke="#7c5cff" stroke-width="1.7" stroke-linejoin="round"/>
  <text x="240" y="70" text-anchor="middle" font-size="10" font-weight="700" fill="#7c5cff">WHAT GOES OUT (&gt; lines)</text>
  <g font-size="9.5" fill="currentColor">
    <text x="56" y="96">&gt; POST /anything?q=x HTTP/1.1</text>
    <text x="56" y="118">&gt; Host: 127.0.0.1:8089</text>
    <text x="56" y="140">&gt; User-Agent: curl/8.14.1</text>
    <text x="56" y="162">&gt; Accept: application/json</text>
    <text x="56" y="184">&gt; Authorization: Basic dXNlcjpzZWNyZXQ=</text>
    <text x="56" y="206">&gt; Cookie: session=abc123</text>
    <text x="56" y="228">&gt; Referer: https://example.com/</text>
    <text x="56" y="250">&gt; X-Request-Id: abc-123</text>
    <text x="56" y="272">&gt; Content-Type: application/json</text>
    <text x="56" y="294">&gt; Content-Length: 15</text>
    <text x="56" y="316">&gt;</text>
    <text x="56" y="338">{"user": "ada"}</text>
  </g>
  <g font-size="7.5" fill="#7c5cff">
    <text x="286" y="96">-X · implied by -d/-F/--json · -I</text>
    <text x="286" y="118">the URL · --resolve (lesson 16)</text>
    <text x="286" y="140">-A</text>
    <text x="286" y="162">-H 'Accept: ...' · --json sets it</text>
    <text x="286" y="184">-u · -H 'Authorization: Bearer ..'</text>
    <text x="286" y="206">-b jar-or-string</text>
    <text x="286" y="228">-e</text>
    <text x="286" y="250">-H 'Name: value' (any header)</text>
    <text x="286" y="272">-d / --json / -F set it</text>
    <text x="286" y="294">computed from the body</text>
    <text x="286" y="316">the blank line: headers end here</text>
    <text x="286" y="338">-d · --json · -F · -T · @file · @-</text>
  </g>
  <rect x="460" y="48" width="400" height="330" rx="10" fill="#0fa07f" fill-opacity="0.08" stroke="#0fa07f" stroke-width="1.7" stroke-linejoin="round"/>
  <text x="660" y="70" text-anchor="middle" font-size="10" font-weight="700" fill="#0fa07f">WHAT COMES BACK (&lt; lines), AND WHERE IT GOES</text>
  <g font-size="9.5" fill="currentColor">
    <text x="476" y="96">&lt; HTTP/1.1 200 OK</text>
    <text x="476" y="118">&lt; Content-Type: application/json</text>
    <text x="476" y="140">&lt; Content-Length: 74</text>
    <text x="476" y="162">&lt; Set-Cookie: session=abc123; Path=/</text>
    <text x="476" y="184">&lt; Location: /somewhere-else</text>
    <text x="476" y="206">&lt; WWW-Authenticate: Basic realm="echo"</text>
    <text x="476" y="228">&lt;</text>
    <text x="476" y="250">{"service": "echo", ...}</text>
  </g>
  <g font-size="8.5" fill="#0fa07f">
    <text x="476" y="278">-i  prints the status line and headers before the body</text>
    <text x="476" y="294">-I  sends HEAD: headers only, no body at all</text>
    <text x="476" y="310">-o file / -O  save the body instead of printing it</text>
    <text x="476" y="326">-L  follow Location (30x); -c jar  save Set-Cookie</text>
    <text x="476" y="342">-f  a 4xx or 5xx becomes exit 22 instead of a saved error page</text>
    <text x="476" y="358">-s  no progress meter · -S  but still show errors · -w  print facts</text>
  </g>
  <text x="450" y="406" text-anchor="middle" font-size="10.5" fill="currentColor" opacity="0.9">Every option is a line on the left, a line on the right, or a decision about where the right side goes.</text>
  <text x="450" y="426" text-anchor="middle" font-size="10.5" fill="currentColor" opacity="0.9">When a request misbehaves, -v shows you which line is wrong; there is nothing curl does that -v does not print.</text>
  <text x="450" y="452" text-anchor="middle" font-size="9.5" fill="currentColor" opacity="0.72">Phase 2 lesson 08 is the meaning of each header; this lesson is how to put it there.</text>
</svg>
```

### Seeing: -v, -i, -I, -s, -o

`-v` is the request and response headers (and the connection and TLS steps) on stderr, with the body on stdout as usual. `-i` includes the response's status line and headers *in the output*, before the body. `-I` sends a `HEAD` request instead of `GET`: headers only, no body, no download, which is how you check a 5 GB file's size or a redirect's target without fetching it. `-s` hides the progress meter that curl prints on stderr when stdout is not a terminal, `-S` re-enables error messages, and `-sS` is what belongs in scripts. `-o file` saves the body under a name you give; `-O` saves it under the remote name; `-o /dev/null` discards it when you only want the headers or the status.

### Headers: -H, -A, -e, and what curl adds on its own

`-H 'Name: value'` adds any header, and repeats. Three have shortcuts: `-A` for `User-Agent`, `-e` for `Referer`, `-u` for `Authorization` (below). Curl sends `Host`, `User-Agent` and `Accept` without being asked; `-H 'Accept: application/json'` replaces the default, and `-H 'Accept:'` with an empty value removes it entirely. The echo server prints what arrived, which is the only test of a header that matters:

```console
$ curl -s -H 'X-Request-Id: abc-123' -H 'Accept: application/json' http://127.0.0.1:8089/ | grep -E 'X-Request|Accept'
  Accept: application/json
  X-Request-Id: abc-123
```

### Bodies: -d, --data-urlencode, --json, -F

A body needs three things: the bytes, a `Content-Type` that says how they are encoded, and a `Content-Length` (or chunking). Curl computes the length; the option you choose decides the other two, and this is where most curl mistakes live:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 440" width="100%" style="max-width:880px" font-family="'JetBrains Mono', ui-monospace, monospace" role="img" aria-label="Three body encodings side by side, each with the curl option that produces it, the Content-Type it sets, and the bytes on the wire. Left, -d: application/x-www-form-urlencoded, key equals value pairs joined by ampersands, values must be percent-encoded, which --data-urlencode does and plain -d does not; used by HTML forms and many login endpoints; -d implies POST. Middle, --json: application/json plus Accept application/json, the bytes exactly as given, from a string, a file with at sign, or stdin with at sign dash; used by every JSON API; the pre-7.82 spelling was -H Content-Type application/json with -d. Right, -F: multipart/form-data with a generated boundary, one part per -F, a part with at sign carries a file with its filename and a Content-Type; used for file uploads and browser-style forms; the body is hundreds of bytes for a one-line file. A footnote: -X GET with -d sends a GET with a body, almost never intended; -G moves -d data into the query string instead; and -d with at sign reads a file as the body while -F with at sign attaches it as a part.">
  <text x="450" y="26" text-anchor="middle" font-size="14.5" font-weight="700" fill="currentColor">Three ways to send a body: the option decides the Content-Type and the encoding</text>
  <g stroke-linejoin="round" stroke-width="1.7">
    <rect x="30"  y="48" width="270" height="300" rx="10" fill="#e0930f" fill-opacity="0.10" stroke="#e0930f"/>
    <rect x="315" y="48" width="270" height="300" rx="10" fill="#0fa07f" fill-opacity="0.10" stroke="#0fa07f"/>
    <rect x="600" y="48" width="270" height="300" rx="10" fill="#7c5cff" fill-opacity="0.10" stroke="#7c5cff"/>
  </g>
  <g text-anchor="middle" font-size="10.5" font-weight="700">
    <text x="165" y="70" fill="#e0930f">-d  (a form)</text>
    <text x="450" y="70" fill="#0fa07f">--json  (an API)</text>
    <text x="735" y="70" fill="#7c5cff">-F  (a file upload)</text>
  </g>
  <g font-size="8.5" fill="currentColor">
    <text x="46" y="94" font-weight="700">Content-Type:</text>
    <text x="46" y="108">application/x-www-form-urlencoded</text>
    <text x="46" y="130" font-weight="700">on the wire:</text>
    <text x="46" y="146">name=ada&amp;lang=python</text>
    <text x="46" y="170">two -d are joined with &amp;</text>
    <text x="46" y="184">values are NOT encoded by -d:</text>
    <text x="46" y="198">use --data-urlencode 'q=a&amp;b'</text>
    <text x="46" y="212">→ q=a%26b</text>
    <text x="46" y="236">implies POST</text>
    <text x="46" y="250">-G moves it into ?query= of a GET</text>
    <text x="46" y="264">-d @file reads the file as the body</text>
    <text x="46" y="288" opacity="0.75">HTML forms, login endpoints,</text>
    <text x="46" y="302" opacity="0.75">OAuth token requests (Phase 8)</text>
    <text x="46" y="326" opacity="0.75">20 bytes for two fields</text>

    <text x="331" y="94" font-weight="700">Content-Type: application/json</text>
    <text x="331" y="108">Accept: application/json  (both set)</text>
    <text x="331" y="130" font-weight="700">on the wire:</text>
    <text x="331" y="146">{"user": "ada"}</text>
    <text x="331" y="170">exactly the bytes you gave</text>
    <text x="331" y="184">--json @file · --json @- (stdin)</text>
    <text x="331" y="198">single-quote it in the shell so</text>
    <text x="331" y="212">the double quotes survive</text>
    <text x="331" y="236">implies POST; -X PUT / PATCH to change</text>
    <text x="331" y="250">before curl 7.82: -H 'Content-Type:</text>
    <text x="331" y="264">application/json' -d '...'</text>
    <text x="331" y="288" opacity="0.75">every JSON API (Phase 3)</text>
    <text x="331" y="302" opacity="0.75">pipe the answer to jq (lesson 08)</text>
    <text x="331" y="326" opacity="0.75">15 bytes for one field</text>

    <text x="616" y="94" font-weight="700">Content-Type: multipart/form-data;</text>
    <text x="616" y="108">boundary=----------------9JeUVYL0m...</text>
    <text x="616" y="130" font-weight="700">on the wire:</text>
    <text x="616" y="146">--boundary</text>
    <text x="616" y="160">Content-Disposition: form-data;</text>
    <text x="616" y="174">  name="file"; filename="up.txt"</text>
    <text x="616" y="188">Content-Type: text/plain</text>
    <text x="616" y="202">(blank line, then the file's bytes)</text>
    <text x="616" y="216">--boundary--</text>
    <text x="616" y="236">one part per -F; @path attaches a file</text>
    <text x="616" y="250">;type=image/png sets the part's type</text>
    <text x="616" y="264">-T file is different: a raw PUT body</text>
    <text x="616" y="288" opacity="0.75">file uploads, browser-style forms,</text>
    <text x="616" y="302" opacity="0.75">RFC 7578</text>
    <text x="616" y="326" opacity="0.75">313 bytes for a 13-byte file</text>
  </g>
  <rect x="30" y="364" width="840" height="46" rx="9" fill="#d64545" fill-opacity="0.07" stroke="#d64545" stroke-width="1.4" stroke-linejoin="round"/>
  <g text-anchor="middle" font-size="8.5" fill="currentColor">
    <text x="450" y="384">-X GET with -d sends a GET with a body (almost never intended). -X POST with -d is redundant. Let the body option choose the method unless you mean PUT or PATCH.</text>
    <text x="450" y="400">-d @file means "this file IS the body"; -F name=@file means "attach this file as a part". Mixing them up is the most common upload bug.</text>
  </g>
  <text x="450" y="432" text-anchor="middle" font-size="10" fill="currentColor" opacity="0.85">When in doubt, -v and read the Content-Type line: it tells you which of the three you actually sent.</text>
</svg>
```

`-d` sends a form (`application/x-www-form-urlencoded`), joins repeated `-d`s with `&`, implies `POST`, and does **not** encode your values; `--data-urlencode` does, turning `q=a&b=c d` into `q=a%26b%3Dc+d`. `-G` moves `-d` data into the query string of a `GET`. `--json` sends the bytes as given with `Content-Type` and `Accept` set to `application/json` (it is the modern spelling of `-H 'Content-Type: application/json' -d ...`), from a string, a file (`@body.json`) or stdin (`@-`). `-F` builds a **multipart** body with a generated boundary, one part per `-F`, and `@path` attaches a file with its name and type, which is what browsers send for file uploads. The echo server shows the three encodings side by side in **Use It**, and the mini curl builds the multipart body by hand so you can see there is nothing to it.

### Methods: -X, and when not to use it

The method is `GET` unless a body option makes it `POST` or `-I` makes it `HEAD`. `-X PUT`, `-X PATCH` and `-X DELETE` set it explicitly, and those are the only times you need `-X`. `-X POST -d ...` is redundant, `-X GET -d ...` sends a body with a `GET` (a request most servers ignore or reject), and `-X POST` without a body sends a `POST` with `Content-Length: 0`, which is occasionally what an API wants and usually a sign of a missing `-d`.

### Auth: -u, Bearer tokens, and where the secret lives

`-u user:secret` adds `Authorization: Basic` followed by `base64("user:secret")`, which is not encryption (`echo -n user:secret | base64` reproduces it), so Basic auth belongs only on `https://`. `-u user` with no password prompts for it, keeping it out of your history and out of `ps`. A token goes in a header: `-H "Authorization: Bearer $TOKEN"`, with the token in a variable read from a file of mode 600 (lesson 06). `-n` reads credentials from `~/.netrc`. The server's side of the conversation is a `401` with `WWW-Authenticate` naming the scheme it wants; `403` means it knows who you are and the answer is still no. Phase 8 builds every one of these mechanisms; here you only need to send them.

### Cookies: -c and -b

A cookie is a header the server asks you to send back: `Set-Cookie` in a response, `Cookie` in later requests (RFC 6265). `-c jar.txt` saves what the server sets into a jar file, `-b jar.txt` sends the jar's cookies, `-b 'name=value'` sends a literal one, and `-c jar.txt -b jar.txt` together behave like a browser across a session. The jar is plain text: read it to see the domain, path, expiry and flags the server chose. Lesson 05 of Phase 8 is what the session cookie means; **Use It** shows the round trip.

### Redirects and errors: -L and -f

A `3xx` response carries a `Location` header and, without `-L`, curl prints its usually-empty body and exits 0, which is the most common way a script "succeeds" with nothing. `-L` follows the chain (up to 50 hops; `--max-redirs` caps it), and `-v -L` shows every hop. Following a `301`, `302` or `303` after a `POST`, curl switches to `GET` and drops the body, as browsers do; `307` and `308` keep the method, and `--post302` overrides. `-f` (`--fail`) makes a `4xx` or `5xx` status an error exit (22) rather than a body saved to your file; every download in a script needs it. The other exit codes you will meet: 6 could not resolve, 7 could not connect, 28 timed out, 35 TLS handshake, 60 certificate not trusted (lesson 16).

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 360" width="100%" style="max-width:880px" font-family="'JetBrains Mono', ui-monospace, monospace" role="img" aria-label="Three round trips that need a second request, drawn as client-server exchanges. Cookies: the client sends GET /login with -c jar; the server answers 200 with Set-Cookie session equals abc123; the client stores it in the jar; the next request with -b jar carries Cookie session equals abc123 and the server recognises the session. Redirects: the client sends GET /old; the server answers 302 with Location slash new; without -L curl stops and prints an empty body with exit 0; with -L it sends GET slash new and gets 200; a POST followed through a 302 becomes a GET. Auth: the client sends GET /auth with no credentials; the server answers 401 with WWW-Authenticate Basic; the client resends with -u user colon secret, which becomes Authorization Basic base64; the server answers 200. A note: each of these is two requests, and -v shows both.">
  <defs>
    <marker id="p1l15c-ar" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker>
  </defs>
  <text x="450" y="26" text-anchor="middle" font-size="14.5" font-weight="700" fill="currentColor">Cookies, redirects, auth: three conversations that take two requests</text>
  <g stroke-linejoin="round" stroke-width="1.6">
    <rect x="30"  y="48" width="270" height="250" rx="10" fill="#0fa07f" fill-opacity="0.08" stroke="#0fa07f"/>
    <rect x="315" y="48" width="270" height="250" rx="10" fill="#e0930f" fill-opacity="0.08" stroke="#e0930f"/>
    <rect x="600" y="48" width="270" height="250" rx="10" fill="#7c5cff" fill-opacity="0.08" stroke="#7c5cff"/>
  </g>
  <g text-anchor="middle" font-size="10" font-weight="700">
    <text x="165" y="70" fill="#0fa07f">COOKIES · -c then -b</text>
    <text x="450" y="70" fill="#e0930f">REDIRECTS · -L</text>
    <text x="735" y="70" fill="#7c5cff">AUTH · -u</text>
  </g>
  <g font-size="8.5" fill="currentColor">
    <text x="46" y="96">&gt; GET /cookie            (-c jar.txt)</text>
    <text x="46" y="112">&lt; 200 OK</text>
    <text x="46" y="126">&lt; Set-Cookie: session=abc123; Path=/</text>
    <text x="46" y="150" font-weight="700">jar.txt now holds session=abc123</text>
    <text x="46" y="174">&gt; GET /cookie            (-b jar.txt)</text>
    <text x="46" y="188">&gt; Cookie: session=abc123</text>
    <text x="46" y="202">&lt; 200 OK · "cookies you sent: session=abc123"</text>
    <text x="46" y="230" opacity="0.8">-b alone sends, never updates;</text>
    <text x="46" y="244" opacity="0.8">-c -b together is a browser</text>
    <text x="46" y="272" opacity="0.7">RFC 6265 · Phase 8, lesson 05</text>

    <text x="331" y="96">&gt; GET /redirect3</text>
    <text x="331" y="112">&lt; 302 Found</text>
    <text x="331" y="126">&lt; Location: /redirect2</text>
    <text x="331" y="150" font-weight="700">without -L: stop here, empty body, exit 0</text>
    <text x="331" y="174">with -L:</text>
    <text x="331" y="188">&gt; GET /redirect2 → 302 → &gt; GET /redirect1</text>
    <text x="331" y="202">→ 302 → &gt; GET / → &lt; 200 OK</text>
    <text x="331" y="230" opacity="0.8">POST + 301/302/303 → GET, body dropped</text>
    <text x="331" y="244" opacity="0.8">307/308 keep the method; --post302 overrides</text>
    <text x="331" y="272" opacity="0.7">RFC 9110 §15.4 · -I -L shows each hop</text>

    <text x="616" y="96">&gt; GET /auth</text>
    <text x="616" y="112">&lt; 401 Unauthorized</text>
    <text x="616" y="126">&lt; WWW-Authenticate: Basic realm="echo"</text>
    <text x="616" y="150" font-weight="700">the server names the scheme it wants</text>
    <text x="616" y="174">&gt; GET /auth                (-u user:secret)</text>
    <text x="616" y="188">&gt; Authorization: Basic dXNlcjpzZWNyZXQ=</text>
    <text x="616" y="202">&lt; 200 OK · "welcome, user"</text>
    <text x="616" y="230" opacity="0.8">base64, not encryption: https only</text>
    <text x="616" y="244" opacity="0.8">a token: -H "Authorization: Bearer $T"</text>
    <text x="616" y="272" opacity="0.7">RFC 7617 · Phase 8, lessons 03 and 06</text>
  </g>
  <text x="450" y="326" text-anchor="middle" font-size="10.5" fill="currentColor" opacity="0.9">Each is two requests and one header. -v shows both requests; the echo server shows what the second one carried.</text>
  <text x="450" y="346" text-anchor="middle" font-size="9.5" fill="currentColor" opacity="0.72">A script that forgets -L, -f or -c gets a 302, a 404 page, or a logged-out session, and exit 0 for all three.</text>
</svg>
```

## Build It

Two files. [`code/echo_server.py`](../code/echo_server.py) is a small HTTP server that answers with what it received (method, path, headers, cookies, body), plus routes for JSON, redirects, Basic auth, cookies, arbitrary status codes, slow and large responses (lesson 16 uses those). [`code/minicurl.py`](../code/minicurl.py) is a curl with the options of this lesson, built on `http.client`, that prints `>` and `<` lines with `-v`. Start the server, run the tour:

```bash
python3 phases/01-linux-and-the-command-line/15-curl-part-1-requests/code/echo_server.py &
python3 phases/01-linux-and-the-command-line/15-curl-part-1-requests/code/minicurl.py                # the tour
python3 phases/01-linux-and-the-command-line/15-curl-part-1-requests/code/minicurl.py -v --json '{"a":1}' http://127.0.0.1:8089/anything
```

**Parsing** is a loop that turns each option into a header, a body, or a flag; the body options set the `Content-Type`, and the method is decided last, exactly as curl decides it:

```python
elif a in ("-d", "--data"):
    req["body"] = (req["body"] + "&" if req["body"] else "") + nxt          # -d implies POST and a form body
    req["headers"].setdefault("Content-Type", "application/x-www-form-urlencoded")
elif a == "--json":
    req["body"] = nxt; req["headers"]["Content-Type"] = "application/json"
    req["headers"].setdefault("Accept", "application/json")
elif a == "-u":
    req["headers"]["Authorization"] = "Basic " + base64.b64encode(nxt.encode()).decode()
...
if req["method"] is None:
    req["method"] = "HEAD" if req["head"] else ("POST" if req["body"] is not None else "GET")
```

**Multipart** is string assembly with a boundary, which is all `-F` does:

```python
boundary = "------------------------" + uuid.uuid4().hex[:16]
parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"; filename="{basename}"\r\n'
             f'Content-Type: application/octet-stream\r\n\r\n'.encode() + data + b"\r\n")
req["body"] = b"".join(parts) + f"--{boundary}--\r\n".encode()
req["headers"]["Content-Type"] = f"multipart/form-data; boundary={boundary}"
```

**Sending** writes the request line and headers with `http.client`, prints them with `>` first, and reads the response back with `<`; **following** a redirect is a loop on `Location`, switching to `GET` on `301`/`302`/`303` the way curl does. The tour runs seventeen requests and the echo server reports each one. The multipart upload, seen from the server, is the diagram's right-hand column:

```console
=== -F: multipart form with a file
$ minicurl -F note=hello -F file=@/tmp/minicurl-upload.txt http://127.0.0.1:8089/upload
you sent: POST /upload
content-type: multipart/form-data; boundary=------------------------9ec4ca0e6272488d
body (332 bytes):
--------------------------9ec4ca0e6272488d
Content-Disposition: form-data; name="note"

hello
--------------------------9ec4ca0e6272488d
Content-Disposition: form-data; name="file"; filename="minicurl-upload.txt"
Content-Type: application/octet-stream

a small file to upload
--------------------------9ec4ca0e6272488d--
```

And the redirect chain with `-v -L` prints four `>` request lines and four `<` status lines, the last one `200`. Compare each block of the tour with the real curl below: the server cannot tell them apart, because on the wire there is nothing to tell.

## Use It

Real curl against the same echo server inside `make shell` (start it with `python3 .../echo_server.py &` first). The count, and the four lines curl sends by itself:

```console
$ curl --version | head -1
curl 8.14.1 (aarch64-unknown-linux-gnu) libcurl/8.14.1 OpenSSL/3.5.7 zlib/1.3.1 ... nghttp2/1.64.0 nghttp3/1.8.0
$ curl --help all | grep -c '^ *-'
269
$ curl -sv http://127.0.0.1:8089/ 2>&1 | grep '^> '
> GET / HTTP/1.1
> Host: 127.0.0.1:8089
> User-Agent: curl/8.14.1
> Accept: */*
>
```

Bodies, three ways, and the two headers `--json` sets for you:

```console
$ curl -s -d name=ada -d lang=python http://127.0.0.1:8089/anything
you sent: POST /anything
content-type: application/x-www-form-urlencoded
body (20 bytes):
name=ada&lang=python
$ curl -s --data-urlencode 'q=a&b=c d' http://127.0.0.1:8089/anything | tail -1;  curl -s -G --data-urlencode 'q=a & b' http://127.0.0.1:8089/ | head -1
q=a%26b%3Dc+d
you sent: GET /?q=a+%26+b HTTP/1.1
$ curl -sv --json '{}' http://127.0.0.1:8089/anything 2>&1 | grep -E '^> (Content-Type|Accept)'
> Content-Type: application/json
> Accept: application/json
$ echo '{"from": "stdin"}' | curl -s --json @- http://127.0.0.1:8089/anything | grep from
{"from": "stdin"}
$ curl -s -F note=hello -F file=@up.txt http://127.0.0.1:8089/upload | head -3
you sent: POST /upload
content-type: multipart/form-data; boundary=------------------------9JeUVYL0mHmKga09hS7GW9
body (313 bytes):
```

Auth, seen as the header it becomes, and the cookie jar as a file:

```console
$ curl -s -u user:secret http://127.0.0.1:8089/auth;  curl -si -u user:nope http://127.0.0.1:8089/auth | grep -E 'HTTP/|WWW-Auth'
welcome, user
HTTP/1.1 401 Unauthorized
WWW-Authenticate: Basic realm="echo"
$ curl -sv -u user:secret http://127.0.0.1:8089/auth 2>&1 | grep '^> Authorization';  echo -n user:secret | base64
> Authorization: Basic dXNlcjpzZWNyZXQ=
dXNlcjpzZWNyZXQ=
$ curl -s -c jar.txt http://127.0.0.1:8089/cookie;  grep -v '^#' jar.txt;  curl -s -b jar.txt http://127.0.0.1:8089/cookie
cookies you sent: (none)
127.0.0.1       FALSE   /       FALSE   0       session abc123
cookies you sent: session=abc123
```

Redirects with and without `-L`, and the method change through a `302`:

```console
$ curl -si http://127.0.0.1:8089/redirect | head -2
HTTP/1.1 302 Found
Server: echo/1.0 Python/3.12.14
$ curl -sv -L http://127.0.0.1:8089/redirect3 2>&1 | grep -E '^(> GET|< HTTP|< Location)'
> GET /redirect3 HTTP/1.1
< HTTP/1.1 302 Found
< Location: /redirect2
> GET /redirect2 HTTP/1.1
< HTTP/1.1 302 Found
< Location: /redirect1
> GET /redirect1 HTTP/1.1
< HTTP/1.1 302 Found
< Location: /
> GET / HTTP/1.1
< HTTP/1.1 200 OK
$ curl -sv -L -d x=1 http://127.0.0.1:8089/status/302 2>&1 | grep -E '^(> [A-Z]+ /|> Content-Length|< HTTP)'
> POST /status/302 HTTP/1.1
> Content-Length: 3
< HTTP/1.1 302 Found
> GET / HTTP/1.1                        <- the POST became a GET and the body was dropped
< HTTP/1.1 200 OK
$ curl -sv -L -d x=1 http://127.0.0.1:8089/status/307 2>&1 | grep -E '^(> [A-Z]+ /|> Content-Length|< HTTP)'
> POST /status/307 HTTP/1.1
> Content-Length: 3
< HTTP/1.1 307 Temporary Redirect
> POST / HTTP/1.1                       <- 307 keeps the method and the body
> Content-Length: 3
< HTTP/1.1 200 OK
```

Saving, failing, and the exit codes a script depends on:

```console
$ curl -s -o out.json http://127.0.0.1:8089/json;  wc -c out.json;  curl -sO http://127.0.0.1:8089/json;  ls json
74 out.json
json
$ curl -s http://127.0.0.1:8089/status/500;  echo "exit without -f: $?"
status 500 as requested
exit without -f: 0
$ curl -sf http://127.0.0.1:8089/status/500;  echo "exit with -f: $?"
exit with -f: 22
$ curl -s http://127.0.0.1:1/;  echo "refused: $?";  curl -s http://nonexistent.invalid/;  echo "no DNS: $?"
refused: 7
no DNS: 6
```

Finally the same options against a real site over HTTPS, where `-v` also prints the TLS handshake (lesson 16's subject) and `-w` prints what the exchange cost:

```console
$ curl -sv https://deb.debian.org/ -o /dev/null 2>&1 | grep -E 'SSL connection|subject:|expire|^> GET'
* SSL connection using TLSv1.3 / TLS_AES_128_GCM_SHA256 / X25519MLKEM768 / RSASSA-PSS
*  subject: CN=cdn-fastly.deb.debian.org
*  expire date: Nov  7 01:03:16 2026 GMT
> GET / HTTP/2
$ curl -s -o /dev/null -w 'status %{http_code}  size %{size_download}B  total %{time_total}s  remote %{remote_ip}:%{remote_port}\n' http://127.0.0.1:8089/json
status 200  size 74B  total 0.000962s  remote 127.0.0.1:8089
```

## Ship It

The artifact for this lesson is a runbook: [`outputs/runbook-curl-by-task.md`](../outputs/runbook-curl-by-task.md). It is curl organised by what you are trying to do: look at something (`-i`, `-I`, `-v`, `-w`), call a JSON API (`--json`, `-X`, `@file`, `@-`), send a form (`-d`, `--data-urlencode`, `-G`, `-F`), authenticate (`-u`, a Bearer header, `-n`, and where the secret must not be), cookies (`-c`, `-b`), redirects (`-L`, the method change), download and upload (`-o`, `-O`, `-f`, `-C -`, `-T`), talk to a server DNS does not know (`--resolve`), and the script form (`-sSf --max-time --retry`) with the exit codes. Each entry is a complete command with the line under it saying what it changed on the wire.

## Think about it

1. `curl -X GET -d '{"q":"x"}' https://api/search` returns a 400. `curl -G --data-urlencode 'q=x' https://api/search` works. Explain both with the request line and the `Content-Type` header.
2. A deploy script runs `curl -o release.tar.gz https://releases.example.com/v2.tar.gz` and later `tar` fails with "not in gzip format". What did curl save, which flag would have caught it, and what exit code would it have given?
3. `curl -d 'user=ada&pass=secret' https://example.com/login` returns `200` and `Set-Cookie`, but the next `curl https://example.com/dashboard` returns `302` to `/login`. Which two flags are missing, and what does the second request lack on the wire?
4. Your colleague pastes `curl -u admin:Hunter2 https://...` into a shared channel and runs it on the server. List three places the password now exists, and the two curl forms that would have kept it out of all of them.

## Key takeaways

- A request is a **method, a path, headers, and maybe a body**; every curl option changes one of those or decides where the response goes. **`-v`** prints the request with `>` and the response with `<`; there is nothing curl does that `-v` does not show.
- **See**: `-i` includes headers in the output, `-I` sends `HEAD`, `-s`/`-sS` for scripts, `-o`/`-O` save, `-o /dev/null -w '%{http_code}'` for just the status.
- **Headers**: `-H 'Name: value'` for anything, `-A` and `-e` for two common ones; curl sends `Host`, `User-Agent` and `Accept` by itself.
- **Bodies**: `-d` is a form and implies `POST` (encode values with `--data-urlencode`; `-G` moves them to the query string); `--json` sets both JSON headers; `-F` builds multipart and `@` attaches a file. `-X` only for `PUT`, `PATCH`, `DELETE`.
- **Auth**: `-u` is Basic, base64 not encryption, `https` only; tokens go in `-H 'Authorization: Bearer ...'` from a variable, never on a shared command line; `401` names the scheme, `403` is a real no.
- **Cookies**: `-c` saves `Set-Cookie` into a jar, `-b` sends it; both together is a session.
- **Redirects and errors**: `-L` follows `Location` (a `POST` becomes a `GET` on `301`/`302`/`303`); **`-f`** makes `4xx`/`5xx` exit 22 instead of saving the error page. Exit 6 is DNS, 7 is connect, 22 is HTTP with `-f`, 28 is timeout.

Next: [curl: Debugging & Timing](../16-curl-part-2-debugging/). You can send anything. Now measure it: where the time goes between DNS, connect, TLS and first byte, how to hit a server before DNS knows it, what the certificate errors mean, and how to make curl retry without lying to you.
