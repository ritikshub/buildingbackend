# Injection & the OWASP Top 10 for Backends

> XSS, in the last lesson, was untrusted data getting interpreted as code — in the *browser*. This lesson meets the same root cause on the *server*, where it's older and often more devastating: **injection**. SQL injection, command injection, SSRF, and path traversal are all one mistake — user data crossing into an interpreter (a database, a shell, a URL fetcher, the filesystem) that can't tell your instructions from the attacker's. You'll run each attack against real code and fix it with the one durable defense — **separate code from data** — and then use the **OWASP Top 10** as a map of everything this entire phase has been dismantling.

**Type:** Build
**Languages:** Python
**Prerequisites:** [The Browser Trust Boundary: CORS, CSRF & XSS](../10-browser-trust-boundary-cors-csrf-xss/) · [Authentication, Authorization & the Security Mindset](../01-authn-authz-and-the-security-mindset/)
**Time:** ~70 minutes

## The Problem

A user-search endpoint builds its query the obvious way — by putting the search term into the SQL string:

```python
name = request.args["name"]
cursor.execute("SELECT id, email FROM users WHERE name = '" + name + "'")
```

It works perfectly for `name=Alice`. Then someone searches for `' OR '1'='1`, and the query the database actually runs becomes:

```sql
SELECT id, email FROM users WHERE name = '' OR '1'='1'
```

The `OR '1'='1'` is always true, so it returns **every user in the table**. The attacker just dumped your entire user list through a search box. And it gets worse: `'; DROP TABLE users; --` ends the statement and issues a second one; a `UNION SELECT password_hash, email FROM users --` grafts another table's columns onto the results; a blind, time-based variant (`' OR (SELECT sleep(5)) --`) exfiltrates data one bit at a time by measuring response delays. This is **SQL injection**, and it has topped vulnerability lists for over two decades — not because it's clever, but because the fix is counterintuitive to how everyone first learns to build strings.

The same mistake wears different costumes across the backend. A "ping this host" feature runs `os.system("ping " + host)` — and `host = "8.8.8.8; rm -rf /"` runs your shell as a second instruction (**command injection**). An avatar-preview feature fetches a user-supplied URL — and the URL `http://169.254.169.254/latest/meta-data/` makes *your server* retrieve its own cloud credentials from the internal metadata endpoint and hand them to the attacker (**SSRF**, Server-Side Request Forgery). A file-download endpoint opens `"uploads/" + filename` — and `filename = "../../etc/passwd"` walks out of the uploads directory and reads system files (**path traversal**).

Four different features, four different "interpreters" — the SQL engine, the shell, the HTTP client, the filesystem — and **one root cause**: user-controlled data was concatenated into a string that an interpreter then parsed, so the interpreter could not tell *your* code from *the attacker's data*. Every fix in this lesson is a variation on restoring that boundary. And because injection is one entry on a longer list of the mistakes that break backends, the lesson ends by mapping the whole **OWASP Top 10** onto the defenses you've built across this phase.

## The Concept

### Injection is a code/data confusion

An **interpreter** takes a string and parses it into instructions: SQL, a shell command line, a URL, a file path, an LDAP query, an HTML page. **Injection** happens when attacker-controlled data is placed into that string *as if it were part of the instructions*, so the interpreter executes the attacker's data as code. The root cause is always the same and so is the cure: **keep code and data separate** — the instructions come from you, fixed and trusted; the data goes into designated *slots* that the interpreter treats as inert values, never as syntax. Everything below is that one idea applied to four interpreters.

### SQL injection, and the fix that is not "escaping"

The instinct after seeing SQL injection is to *escape* the input — strip quotes, backslash-escape specials. This is the wrong fix: escaping is a blocklist you will get wrong (numeric contexts, different quoting, Unicode tricks, second-order injection where escaped data is later concatenated again). The right fix is **parameterized queries** (also called prepared statements or bound parameters), where the query *template* is sent to the database separately from the data:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 356" width="100%" style="max-width:880px" role="img" aria-label="SQL injection versus parameterized query. In the vulnerable version, the input quote OR 1=1 is concatenated into the query string, so the database parses the injected OR 1 equals 1 as SQL code and returns every row. In the safe version, the query template with a question-mark placeholder is compiled first with the placeholder as a data slot, and the same input is bound as a literal value; the database looks for a user literally named quote OR 1=1 and finds none. The template is fixed code; the data can never become syntax.">
  <text x="450" y="24" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="15" font-weight="700" fill="currentColor">The fix isn't escaping — it's keeping the query template separate from the data</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <rect x="20" y="46" width="860" height="130" rx="11" fill="#d64545" fill-opacity="0.06" stroke="#d64545" stroke-opacity="0.7"/>
    <text x="36" y="68" font-size="12" font-weight="700" fill="#d64545">VULNERABLE — concatenation (code and data mixed)</text>
    <text x="36" y="92" font-size="10" fill="currentColor">q = "SELECT * FROM users WHERE name = '" + input + "'"</text>
    <text x="36" y="112" font-size="10" fill="currentColor">input = <tspan fill="#d64545">' OR '1'='1</tspan></text>
    <text x="36" y="134" font-size="10" fill="currentColor">→ SELECT * FROM users WHERE name = ''<tspan fill="#d64545" font-weight="700"> OR '1'='1'</tspan>   ← the DB parses this as SQL</text>
    <text x="36" y="158" font-size="10" fill="#d64545" font-weight="700">result: every row returned (or DROP TABLE, or UNION-exfiltrate). The attacker's data became code.</text>

    <rect x="20" y="192" width="860" height="140" rx="11" fill="#0fa07f" fill-opacity="0.06" stroke="#0fa07f" stroke-opacity="0.7"/>
    <text x="36" y="214" font-size="12" font-weight="700" fill="#0fa07f">SAFE — parameterized query (code and data separated)</text>
    <text x="36" y="238" font-size="10" fill="currentColor">q = "SELECT * FROM users WHERE name = <tspan font-weight="700">?</tspan>"        ← template compiled first, ? is a DATA slot</text>
    <text x="36" y="258" font-size="10" fill="currentColor">execute(q, [input])                              ← input is BOUND as a value, never parsed as SQL</text>
    <text x="36" y="278" font-size="10" fill="currentColor">input = <tspan fill="#0fa07f">' OR '1'='1</tspan></text>
    <text x="36" y="298" font-size="10" fill="currentColor">→ the DB looks for a user literally named "' OR '1'='1"  → <tspan font-weight="700" fill="#0fa07f">finds none</tspan></text>
    <text x="36" y="320" font-size="10" fill="#0fa07f" font-weight="700">The template is fixed; the data can never change the query's structure. This is THE fix.</text>
  </g>
</svg>
```

With a parameterized query the database **compiles the query template first** — with the `?` as a placeholder — and then binds your input into that slot as a pure value. The attacker's `' OR '1'='1` is looked up as a literal name (which matches no one) rather than parsed as syntax, because by the time the data arrives, the query's structure is already fixed. This is not a mitigation or a filter; it is a structural guarantee, and it's why **every database library supports parameters and why you must always use them**. The only place parameters can't go is an *identifier* (a table or column name) — for those, use a strict **allowlist** of known-good names, never string interpolation.

### Command injection and SSRF: the same bug, other interpreters

**Command injection** is SQL injection against the *shell*. Building a command line with user input (`os.system("ping " + host)`) lets shell metacharacters — `;`, `|`, `&&`, `$(...)`, backticks — inject a second command. The fix mirrors parameterization: **don't invoke a shell at all.** Pass the command as an argument *list* (`subprocess.run(["ping", "-c", "1", host])`, `shell=False`), so the OS treats `host` as a single argument to `ping`, never as shell syntax. The shell is the interpreter; removing it removes the injection.

**SSRF** is subtler because there's no obvious "interpreter" — until you realize the attacker is making *your server* the confused deputy. Your server sits inside the network's trust boundary, so it can reach things the attacker can't: cloud metadata endpoints, internal admin panels, databases, other services. If your server fetches a URL the user supplies, the attacker points it inward:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 340" width="100%" style="max-width:880px" role="img" aria-label="SSRF. A user submits a URL for the server to fetch, for an avatar preview or webhook test. The attacker submits an internal URL: the cloud metadata endpoint 169.254.169.254, or an internal service like the Redis port on localhost, or an internal admin panel. Because the server sits inside the trust boundary, it fetches these internal resources the attacker could never reach directly, and returns or acts on the data, leaking cloud credentials or internal state. Defenses: allowlist the destinations you actually need, block private, loopback, and link-local IP ranges after resolving DNS, and disable redirects.">
  <defs>
    <marker id="l11s-ar" markerWidth="10" markerHeight="10" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker>
  </defs>
  <text x="450" y="24" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="15" font-weight="700" fill="currentColor">SSRF: your server is inside the trust boundary — so the attacker aims it inward</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <g fill="none" stroke-linejoin="round" stroke-width="1.8">
      <rect x="30" y="66" width="150" height="60" rx="10" fill="#d64545" fill-opacity="0.10" stroke="#d64545"/>
      <rect x="270" y="66" width="180" height="60" rx="10" fill="#3553ff" fill-opacity="0.10" stroke="#3553ff"/>
      <rect x="560" y="52" width="310" height="180" rx="11" fill="#e0930f" fill-opacity="0.06" stroke="#e0930f" stroke-opacity="0.7"/>
    </g>
    <text x="105" y="90" font-size="10" font-weight="700" text-anchor="middle" fill="#d64545">attacker</text>
    <text x="105" y="108" font-size="8" text-anchor="middle">submits a URL for</text>
    <text x="105" y="120" font-size="8" text-anchor="middle">the server to fetch</text>
    <text x="360" y="90" font-size="10" font-weight="700" text-anchor="middle" fill="#3553ff">YOUR SERVER</text>
    <text x="360" y="108" font-size="8" text-anchor="middle">fetches the URL</text>
    <text x="360" y="120" font-size="8" text-anchor="middle">(avatar / webhook test)</text>
    <text x="715" y="74" font-size="10" font-weight="700" text-anchor="middle" fill="#e0930f">INTERNAL (attacker can't reach directly)</text>
    <text x="575" y="98" font-size="9" fill="currentColor">• http://169.254.169.254/  cloud metadata → creds</text>
    <text x="575" y="120" font-size="9" fill="currentColor">• http://localhost:6379/    internal Redis</text>
    <text x="575" y="142" font-size="9" fill="currentColor">• http://10.0.0.5/admin     internal panel</text>
    <text x="575" y="164" font-size="9" fill="currentColor">• file:///etc/passwd        local files</text>
    <text x="715" y="196" font-size="8.5" text-anchor="middle" opacity="0.7">the server returns / acts on what it fetched</text>
    <text x="715" y="212" font-size="8.5" text-anchor="middle" opacity="0.7">→ credential &amp; internal-data leak</text>
  </g>
  <g fill="none" stroke="currentColor" stroke-width="1.6">
    <path d="M180 96 L 266 96" marker-end="url(#l11s-ar)"/>
    <path d="M450 96 L 556 96" marker-end="url(#l11s-ar)"/>
  </g>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <rect x="30" y="254" width="840" height="72" rx="10" fill="#0fa07f" fill-opacity="0.06" stroke="#0fa07f" stroke-opacity="0.6"/>
    <text x="44" y="276" font-size="10.5" font-weight="700" fill="#0fa07f">Defenses</text>
    <text x="44" y="296" font-size="9.5">• <tspan font-weight="700">Allowlist</tspan> the destinations you actually need (specific hosts/schemes) — deny by default, don't blocklist.</text>
    <text x="44" y="314" font-size="9.5">• <tspan font-weight="700">Resolve DNS and block private / loopback / link-local ranges</tspan> (re-check after resolution — DNS rebinding), <tspan font-weight="700">disable redirects</tspan>, drop file:// and gopher://.</text>
  </g>
</svg>
```

SSRF is now on the OWASP Top 10 in its own right precisely because cloud metadata endpoints turned it from "read an internal page" into "steal the server's credentials." The defense is deny-by-default: **allowlist** the destinations you genuinely need, and if you must fetch arbitrary user URLs, **resolve the hostname and reject private, loopback, and link-local IP ranges** (re-checking after DNS resolution to defeat DNS rebinding), disable redirects, and restrict schemes to `http`/`https`.

**Path traversal** is the filesystem version: `open("uploads/" + name)` with `name = "../../etc/passwd"` treats the path as an interpreter of `..` segments. The fix is to resolve the final absolute path and verify it stays **within** the intended base directory — treat the base as a boundary, and reject anything that escapes it.

### The general defense, and why validation is second

Across all four, the durable defenses stack in a clear priority. First, **separation of code and data** — parameterized queries, argument lists, allowlisted destinations, path confinement. This is the real fix, because it removes the confusion structurally. Second, **input validation** as defense in depth — a search name is `[A-Za-z ]+`, a host is a valid hostname, a filename has no slashes — using **allowlists** (define what's valid) not blocklists (chase what's dangerous, and lose). Third, **least privilege** on the interpreter itself: the database user the app connects as can't `DROP TABLE` or read other schemas ([Lesson 1](../01-authn-authz-and-the-security-mindset/)), so even a successful injection is contained. Escaping and WAFs (Web Application Firewalls) exist, but they're the *last* line — a blocklist someone maintains — never the first.

### The OWASP Top 10: a map of this phase

The **OWASP Top 10** (Open Worldwide Application Security Project) is the industry's consensus list of the most critical web-application security risks, refreshed every few years. It's worth knowing not as trivia but as a **checklist and a vocabulary** — and, satisfyingly, almost every entry is something this phase built a defense for:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 428" width="100%" style="max-width:880px" role="img" aria-label="The OWASP Top 10 for 2021 mapped to this phase's lessons. A01 Broken Access Control maps to Lesson 9, the IDOR and authorization. A02 Cryptographic Failures maps to Lessons 2, 3, and 13. A03 Injection is this lesson, plus XSS from Lesson 10. A04 Insecure Design maps to Lesson 1, threat modeling. A05 Security Misconfiguration maps to Lessons 10 and 13. A06 Vulnerable and Outdated Components maps to dependency scanning. A07 Identification and Authentication Failures map to Lessons 3 through 6. A08 Software and Data Integrity Failures map to Lessons 6 and 8, signing. A09 Security Logging and Monitoring Failures map to Phase 9 and Lesson 1. A10 Server-Side Request Forgery is this lesson.">
  <text x="450" y="22" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="15" font-weight="700" fill="currentColor">OWASP Top 10 (2021) — a map of the defenses in this phase</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace" font-size="10.5" fill="currentColor">
    <g stroke="currentColor" stroke-width="1" opacity="0.12">
      <line x1="20" y1="40" x2="880" y2="40"/>
      <line x1="20" y1="76" x2="880" y2="76"/><line x1="20" y1="112" x2="880" y2="112"/><line x1="20" y1="148" x2="880" y2="148"/>
      <line x1="20" y1="184" x2="880" y2="184"/><line x1="20" y1="220" x2="880" y2="220"/><line x1="20" y1="256" x2="880" y2="256"/>
      <line x1="20" y1="292" x2="880" y2="292"/><line x1="20" y1="328" x2="880" y2="328"/><line x1="20" y1="364" x2="880" y2="364"/>
    </g>
    <text x="28" y="64" font-weight="700" fill="#d64545">A01 · Broken Access Control</text><text x="470" y="64">→ IDOR, deny-by-default, object-level authz</text><text x="820" y="64" text-anchor="end" font-weight="700" fill="#0fa07f">L9</text>
    <text x="28" y="100" font-weight="700">A02 · Cryptographic Failures</text><text x="470" y="100">→ weak/no crypto, plaintext secrets, bad hashing</text><text x="820" y="100" text-anchor="end" font-weight="700" fill="#0fa07f">L2·L3·L13</text>
    <text x="28" y="136" font-weight="700" fill="#e0930f">A03 · Injection</text><text x="470" y="136">→ SQLi, command inj, path traversal, XSS</text><text x="820" y="136" text-anchor="end" font-weight="700" fill="#0fa07f">L11·L10</text>
    <text x="28" y="172" font-weight="700">A04 · Insecure Design</text><text x="470" y="172">→ threat modeling, secure defaults</text><text x="820" y="172" text-anchor="end" font-weight="700" fill="#0fa07f">L1</text>
    <text x="28" y="208" font-weight="700">A05 · Security Misconfiguration</text><text x="470" y="208">→ CORS/headers, open defaults, verbose errors</text><text x="820" y="208" text-anchor="end" font-weight="700" fill="#0fa07f">L10·L13</text>
    <text x="28" y="244" font-weight="700">A06 · Vulnerable Components</text><text x="470" y="244">→ dependency scanning, patching (SCA)</text><text x="820" y="244" text-anchor="end" font-weight="700" fill="#0fa07f">Use It</text>
    <text x="28" y="280" font-weight="700" fill="#3553ff">A07 · Auth Failures</text><text x="470" y="280">→ weak passwords, sessions, MFA, tokens</text><text x="820" y="280" text-anchor="end" font-weight="700" fill="#0fa07f">L3–L6</text>
    <text x="28" y="316" font-weight="700">A08 · Integrity Failures</text><text x="470" y="316">→ signing, JWT verification, supply chain</text><text x="820" y="316" text-anchor="end" font-weight="700" fill="#0fa07f">L6·L8</text>
    <text x="28" y="352" font-weight="700">A09 · Logging &amp; Monitoring</text><text x="470" y="352">→ audit trails, detection, accountability</text><text x="820" y="352" text-anchor="end" font-weight="700" fill="#0fa07f">P10·L1</text>
    <text x="28" y="388" font-weight="700" fill="#e0930f">A10 · SSRF</text><text x="470" y="388">→ allowlist, block internal ranges</text><text x="820" y="388" text-anchor="end" font-weight="700" fill="#0fa07f">L11</text>
  </g>
  <text x="450" y="416" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="10" fill="currentColor" opacity="0.85">The Top 10 isn't ten tricks — it's the ranked shape of how backends actually get breached. This phase is the toolkit.</text>
</svg>
```

Read the map as a certificate for the phase: **broken access control** (#1) was [Lesson 9](../09-authorization-rbac-abac-rebac/); **auth failures** (#7) were Lessons [3](../03-password-storage-and-hashing/)–[6](../06-jwt-and-token-auth/); **cryptographic failures** (#2) were Lessons [2](../02-cryptographic-building-blocks/), [3](../03-password-storage-and-hashing/), and [13](../13-secrets-management-and-rotation/); **integrity failures** (#8) were the signing of Lessons [6](../06-jwt-and-token-auth/) and [8](../08-api-keys-hmac-and-webhooks/); **injection** (#3) and **SSRF** (#10) are this one. The two you haven't built code for — **A06 vulnerable components** (keep dependencies patched, scan them) and **A09 logging failures** (you did build this, in [Phase 9](../../09-logging-monitoring-and-observability/01-why-systems-go-dark/)) — round out the list. The Top 10 is the shape of how backends get breached; the phase is the toolkit that answers it.

## Build It

Standard library only — `sqlite3` (a real database!), `subprocess`, `os.path`, `ipaddress`, `urllib.parse` — to *run* SQL injection and see it fixed, dodge command injection by dropping the shell, confine a path, and block an SSRF target.

The SQL injection is real, not a diagram — the vulnerable query returns every row, the parameterized one returns none:

```python
# VULNERABLE — the input becomes part of the SQL
cur.execute("SELECT * FROM users WHERE name = '" + name + "'")   # name = "' OR '1'='1"  -> all rows

# SAFE — the template is fixed, the input is bound as data
cur.execute("SELECT * FROM users WHERE name = ?", (name,))       # same input -> looked up literally, 0 rows
```

Command injection dies when you remove the shell; a path is confined by resolving and range-checking it:

```python
subprocess.run(["ping", "-c", "1", host], shell=False)           # host is ONE arg, never shell syntax

def safe_path(base: str, name: str) -> str | None:
    full = os.path.realpath(os.path.join(base, name))            # resolve .. and symlinks
    return full if full.startswith(os.path.realpath(base) + os.sep) else None   # must stay inside base

def ssrf_ok(url: str) -> bool:
    host = urllib.parse.urlparse(url).hostname
    ip = ipaddress.ip_address(socket.gethostbyname(host))        # resolve, then check
    return not (ip.is_private or ip.is_loopback or ip.is_link_local)   # block internal ranges
```

The full script — the live SQLi and its fix, a command-injection attempt blocked by `shell=False`, a path-traversal attempt confined, and an SSRF target rejected — is in [`code/injection.py`](code/injection.py). Run it:

```console
$ python3 injection.py
== 1 · SQL INJECTION (real sqlite3) ==
  users table has 3 rows (alice, bob, carol)
  search 'alice'         -> 1 row   [('alice', 'alice@acme.com')]
  VULNERABLE  name="' OR '1'='1"  -> 3 rows   ✗ dumped the whole table
  PARAMETERIZED name="' OR '1'='1" -> 0 rows   ✓ treated as a literal name

== 2 · COMMAND INJECTION (drop the shell) ==
  host="8.8.8.8; echo PWNED"  (using echo instead of ping — harmless demo)
  shell=True  -> output: 'pinging 8.8.8.8\nPWNED'   ✗ (the injected 'echo PWNED' ran)
  shell=False -> output: 'pinging 8.8.8.8; echo PWNED'   ✓ (one literal argument)

== 3 · PATH TRAVERSAL (confine to a base dir) ==
  base=/srv/uploads   name="report.pdf"         -> /srv/uploads/report.pdf   ✓ allowed
  base=/srv/uploads   name="../../etc/passwd"   -> blocked (escapes base)     ✓

== 4 · SSRF (allowlist / block internal ranges) ==
  https://api.partner.com/hook                 -> allowed (public, allowlisted)   ✓
  http://169.254.169.254/latest/meta-data/     -> blocked (link-local: internal)   ✓
  http://localhost:6379/                       -> blocked (loopback: internal)   ✓
```

**Section 1** is the whole lesson in two rows against a real SQLite database: the concatenated query returns all three users for `' OR '1'='1`, and the parameterized query returns zero because it searches for a user *named* `' OR '1'='1`. **Section 2** shows the injected second command becoming a harmless single argument once the shell is gone. **Sections 3 and 4** confine the filesystem and block the classic SSRF targets — the cloud metadata address and an internal port.

## Use It

In production, the good news is that the primary defenses are the *default* path in modern tools — the job is to stay on it. **ORMs and query builders parameterize automatically**: SQLAlchemy, Django's ORM, and every mature data layer bind parameters, so you get SQLi safety for free — the danger is `raw()`/`text()`/f-string SQL, which each framework documents as "you are now responsible." For **shell commands**, use `subprocess` with a list and `shell=False` (or avoid spawning processes entirely). For **SSRF**, put outbound fetches behind an allowlist or a vetted SSRF-protection layer, block link-local/private ranges, and in the cloud enforce **IMDSv2** (the metadata service's session-token defense) so a stray SSRF can't grab credentials. For **XSS/path/injection generally**, lean on framework escaping and path libraries.

Beyond code, the OWASP Top 10 implies a toolchain: **SAST** (static analysis) and **DAST** (dynamic scanning) to find injection and misconfig automatically; **dependency scanning / SCA** (Dependabot, `pip-audit`, Snyk) for A06 vulnerable components; **secret scanning** for leaked keys ([Lesson 13](../13-secrets-management-and-rotation/)); and a **WAF** as a backstop that buys time, never as the fix. The durable rules to carry: **separate code from data everywhere an interpreter is involved** (parameterize, argument-list, allowlist, confine), **validate input with allowlists** as defense in depth, run every interpreter under **least privilege**, keep **dependencies patched**, and treat the **OWASP Top 10 as your review checklist** — because it is, quite literally, the ranked list of how the systems this phase secures actually get broken.

## Think about it

1. A developer "fixes" SQL injection by escaping single quotes in the input. Give two distinct ways an attacker still injects (think: numeric context, and data that's escaped once but concatenated again later), and explain why parameterization has neither problem.
2. Command injection is fixed by passing an argument list with `shell=False`. Walk through *why* `["ping","-c","1", "8.8.8.8; rm -rf /"]` is safe — what does the OS do with that last element, and where did the shell's role go?
3. SSRF is described as "your server is the confused deputy." Explain what makes the server a more powerful attacker than the actual attacker, why the cloud metadata endpoint turned SSRF from medium to critical severity, and why blocklisting `169.254.169.254` alone is insufficient.
4. Injection, path traversal, SSRF, and XSS are called "the same bug." State the single sentence that describes all four, and for each name the interpreter and the "keep code and data separate" fix.
5. Pick any three OWASP Top 10 entries and, without looking, name the lesson in this phase that defends each and one concrete control it teaches. Which entry is *not* primarily a coding problem, and what does defending it require instead?

## Key takeaways

- **Injection is a code/data confusion**: user-controlled data is placed into a string an interpreter parses (SQL, shell, URL, filesystem), so the interpreter runs the attacker's data as instructions. SQLi, command injection, SSRF, and path traversal are one bug against four interpreters.
- **The fix is structural separation of code and data, not escaping.** For SQL, **parameterized queries** send the template and the data separately, so input can never change the query's structure — always use them; allowlist identifiers that can't be parameters.
- **The same fix generalizes:** drop the shell (**argument lists**, `shell=False`) for command injection; **allowlist destinations and block internal IP ranges** for SSRF; **confine paths to a base directory** for traversal. Remove the interpreter's ability to treat data as syntax.
- **Defenses stack in priority:** separation of code and data first, **input validation with allowlists** (not blocklists) as defense in depth, and **least privilege** on the interpreter (a DB user that can't `DROP TABLE`) so a breach is contained. Escaping and WAFs are the last line, not the first.
- **SSRF is critical because your server is inside the trust boundary** — it can reach cloud metadata (credentials!), internal services, and local files the attacker can't. Deny by default, resolve-then-check IPs (DNS rebinding), disable redirects, and enforce IMDSv2.
- **The OWASP Top 10 is a map of how backends get breached — and of this phase.** Broken access control (L9), crypto failures (L2/L3/L13), injection & SSRF (this lesson), auth failures (L3–L6), integrity (L6/L8), logging (Phase 9), plus keeping components patched (A06). Use it as your security review checklist.

Next: [Abuse Prevention: Bots, Credential Stuffing & Account Takeover](../12-abuse-prevention/) — you've closed the injection and access holes; next you defend against attackers who use your system exactly as designed but at scale and in bulk — credential stuffing, scraping, fake signups, and the account-takeover economy.
