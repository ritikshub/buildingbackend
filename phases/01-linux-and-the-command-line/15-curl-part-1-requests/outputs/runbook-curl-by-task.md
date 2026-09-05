---
name: runbook-curl-by-task
description: curl organised by the job you are trying to do — call a JSON API, log in, upload, download, follow redirects, send cookies and headers, hit a server that DNS does not know yet, script it safely — with the exact flags, what each puts on the wire, and the mistake beside it
phase: 01
lesson: 15
---

# curl, by task

Every entry is a complete command. Read the flag, then the line under it
that says what it changed on the wire; that is the whole of curl. Part 2
(lesson 16) covers timing, TLS, retries and debugging flags.

## 1 · Look at something

```bash
curl https://api.example.com/health                     # GET, body to stdout
curl -i https://api.example.com/health                  # -i: include the status line and response headers
curl -I https://api.example.com/health                  # -I: HEAD only: headers, no body, no download
curl -s https://api.example.com/health                  # -s: no progress meter (use in scripts)
curl -sS https://api.example.com/health                 # -S: but still print errors
curl -v https://api.example.com/health                  # -v: the request (>) and response (<) headers, and the TLS handshake
curl -o /dev/null -s -w '%{http_code}\n' https://api.example.com/health   # just the status code
```

- `-i` and `-I` are different: `-I` sends `HEAD`, and some servers answer `HEAD` differently from `GET` (or not at all: 405).
- The progress meter goes to stderr, so `curl url > file` works without `-s`, but `-s` keeps logs clean.

## 2 · Call a JSON API

```bash
curl -s https://api.example.com/users/42 | jq .                         # pretty-print (lesson 08)
curl -s -H 'Accept: application/json' https://api.example.com/users/42
curl -s --json '{"name":"ada"}' https://api.example.com/users             # POST, Content-Type and Accept set to application/json
curl -s -X PUT --json '{"name":"ada"}' https://api.example.com/users/42
curl -s -X PATCH --json '{"active":false}' https://api.example.com/users/42
curl -s -X DELETE https://api.example.com/users/42
curl -s --json @payload.json https://api.example.com/users                # body from a file
curl -s -H 'Content-Type: application/json' -d '{"name":"ada"}' https://api.example.com/users   # the pre-7.82 spelling of --json
```

- `-d` **implies POST** and sets `Content-Type: application/x-www-form-urlencoded`; for JSON you must set the header yourself, or use `--json` which does.
- `-X POST` with `-d` is redundant; `-X GET` with `-d` sends a GET with a body, which is almost never what you want. Let `-d` choose the method unless you mean PUT or PATCH.
- Quote the JSON in single quotes so the shell leaves the double quotes alone (lesson 03). A `$` inside needs single quotes too.
- `-d @file` reads the body from a file; `-d @-` from stdin: `jq -n '{a:1}' | curl --json @- url`.

## 3 · Send a form

```bash
curl -d 'name=ada' -d 'lang=python' https://example.com/signup           # two -d: joined with &
curl --data-urlencode 'q=a & b' https://example.com/search              # encodes the value: & becomes %26, space %20
curl -G --data-urlencode 'q=a & b' https://example.com/search           # -G: put the -d data in the query string of a GET
curl -F 'name=ada' -F 'avatar=@photo.png' https://example.com/profile   # -F: multipart/form-data, the browser's file-upload format
curl -F 'avatar=@photo.png;type=image/png' https://example.com/profile  # with an explicit content type
```

- `-d` is `application/x-www-form-urlencoded`, `-F` is `multipart/form-data`. HTML forms use the first without files and the second with; APIs that want a file upload usually want `-F`.
- `@` in `-d` means "read this file as the body"; in `-F` it means "attach this file as a part". `-d 'name=@foo'` will surprise you: use `--data-urlencode`.

## 4 · Authenticate

```bash
curl -u user:secret https://api.example.com/me                          # Basic: base64(user:secret) in Authorization
curl -u user https://api.example.com/me                                 # prompts for the password: not on the command line, not in history
curl -H 'Authorization: Bearer eyJhbGciOi...' https://api.example.com/me   # a token (Phase 8, lesson 06)
curl -H "Authorization: Bearer $TOKEN" https://api.example.com/me       # from a variable; double quotes so it expands
curl -H "X-API-Key: $API_KEY" https://api.example.com/me                # an API key header
curl -n https://api.example.com/me                                      # credentials from ~/.netrc (machine api.example.com login user password secret), mode 600
```

- Anything on the command line is in `ps` output for every user on the box and in your shell history. Use `-u user` (prompt), `-n` with `~/.netrc`, or a variable loaded from a file of mode 600 (lesson 06).
- Basic auth over plain `http://` sends the password in clear text. Only over `https://`.
- A `401` with `WWW-Authenticate: Basic` means the server wants `-u`; a `403` means it knows who you are and still says no.

## 5 · Cookies and sessions

```bash
curl -c jar.txt -d 'user=ada&pass=secret' https://example.com/login     # -c: save Set-Cookie responses to a jar
curl -b jar.txt https://example.com/dashboard                            # -b: send the jar's cookies
curl -b 'session=abc123' https://example.com/dashboard                   # -b with a literal cookie string
curl -c jar.txt -b jar.txt https://example.com/step2                     # both: read and update, like a browser
```

- The jar is a text file (Netscape format); read it to see exactly what the server set: name, value, domain, path, expiry, flags.
- `-b` without `-c` sends but never updates; a session that rotates its cookie on each response needs both.

## 6 · Redirects

```bash
curl -L https://example.com/old                                          # follow 3xx Location headers (up to 50 hops)
curl -L --max-redirs 3 https://example.com/old
curl -I -L https://example.com/old                                       # see each hop's headers
curl -L -o out.html https://example.com/old
```

- Without `-L`, curl prints the redirect's (usually empty) body and exits 0. A script that "worked" but got nothing is often this.
- On 301, 302 and 303, curl changes a POST to a GET and drops the body when following, as browsers do. 307 and 308 keep the method. `--post301` / `--post302` override.
- `-L` follows to whatever host the `Location` names, including plain `http://`; check `-I -L` output before sending credentials through a redirect.

## 7 · Download and upload files

```bash
curl -o app.tar.gz https://example.com/releases/app-1.2.tar.gz          # -o: save as this name
curl -O https://example.com/releases/app-1.2.tar.gz                      # -O: save with the remote name
curl -sSfL -o app.tar.gz https://example.com/releases/app-1.2.tar.gz     # the script form: silent, show errors, fail on 4xx/5xx, follow
curl -C - -O https://example.com/big.iso                                 # resume a partial download
curl -T local.bin https://example.com/upload/local.bin                   # -T: PUT a file as the body (not multipart)
curl --limit-rate 1M -O https://example.com/big.iso                      # be polite on a shared link
curl -sSf -o /dev/null https://example.com/health                        # download nothing; just check
```

- `-f` (`--fail`) makes a 4xx or 5xx an error exit (22) instead of saving the error page as your file. Every download in a script needs it.
- `-O` with a URL that ends in `/` has no name to use; `-o` explicitly.
- After a download, verify: `sha256sum -c app.tar.gz.sha256` (lesson 09, lesson 13).

## 8 · Talk to a server DNS does not know yet

```bash
curl --resolve api.example.com:443:10.0.0.7 https://api.example.com/health    # send the request to 10.0.0.7 with the right Host and SNI
curl -H 'Host: api.example.com' http://10.0.0.7/health                        # plain HTTP: the Host header alone is enough
curl --connect-to api.example.com:443:staging.internal:8443 https://api.example.com/health   # any host and port, same name
```

- This is how you test a new server, a canary, or a load-balancer backend before changing DNS, and how you tell "the box is wrong" from "DNS is wrong" (lesson 14). Lesson 16 goes further.

## 9 · In scripts

```bash
status=$(curl -s -o /dev/null -w '%{http_code}' https://api.example.com/health)   # the code, nothing else
[ "$status" = 200 ] || echo "unhealthy: $status" >&2
curl -sSf --max-time 10 --retry 3 --retry-delay 2 https://api.example.com/health >/dev/null   # bounded, retried, failing loudly
body=$(curl -sSf https://api.example.com/users/42) && echo "$body" | jq -r .name
```

- Always `--max-time` in a script (default: forever) and `-f` so that HTTP errors are exit codes; `-sS` so that only real errors reach the log. Lesson 16 covers `--retry` and the timing flags.
- Exit codes: 0 ok; 6 could not resolve; 7 could not connect; 22 HTTP error with `-f`; 28 timeout; 35 TLS handshake; 60 certificate not trusted. `man curl` lists them all.
- `curl --help all | wc -l` is about 260 lines. You now know the 30 that matter.
