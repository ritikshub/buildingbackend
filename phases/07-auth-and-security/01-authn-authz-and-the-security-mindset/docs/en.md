# Authentication, Authorization & the Security Mindset

> Every request your backend serves arrives with two questions attached, and almost every breach is a wrong answer to one of them: *who is this?* (authentication) and *what are they allowed to do?* (authorization). This lesson pulls those two apart — they fail differently, they return different status codes, they are fixed by different code — and then hands you the five ideas the rest of the phase runs on: the CIA triad, trust boundaries, threat modeling, least privilege, and the one rule that outranks all the others, *never trust the client*.

**Type:** Learn
**Languages:** —
**Prerequisites:** [HTTP in Depth](../../01-networking-and-protocols/08-http-in-depth/) and [TLS, Certificates & mTLS](../../01-networking-and-protocols/10-tls-certificates-mtls/) give useful background, but this lesson starts from first principles.
**Time:** ~50 minutes

## The Problem

A two-person team ships **AcmeNotes**, a tiny JSON API for private notes. It has a login endpoint that returns a token, and a notes endpoint that returns a note. It worked in the demo, the investors clapped, and it went live on a Friday. Here is what an attacker did to it over the weekend, in the order they found it:

```http
GET /notes/42 HTTP/1.1
Host: api.acmenotes.com
```

```json
{ "id": 42, "owner": "u_5501", "title": "Series A cap table", "body": "..." }
```

No token. No cookie. The endpoint just answered. The team had built a *login* screen and assumed that building the screen secured the data behind it — but the `/notes/{id}` handler never checks for a caller at all. **That is a missing authentication check**, and it is the most common serious bug there is.

The team pushes a fix on Saturday: every endpoint now requires a valid token. The attacker logs in as themselves — a real, paying user — gets a real token, and tries again:

```http
GET /notes/42 HTTP/1.1
Authorization: Bearer <the attacker's own valid token>
```

It still returns note 42, which belongs to `u_5501`, not to the attacker. The token proved *who the attacker was*; nothing checked *whether this person may read this particular note*. Change the number in the URL — `/notes/43`, `/notes/44` — and you walk the entire database one row at a time. **This is a broken authorization check**, and it has a name: **IDOR** (Insecure Direct Object Reference). Requiring a login did not fix it, because it was never a login problem.

The attacker looks closer at the token itself. It is this:

```text
eyJ1c2VyIjoiYXR0YWNrZXIifQ==
```

That is not encryption. It is **Base64** — a reversible *encoding*, readable by anyone. Decoded, it says `{"user":"attacker"}`. So the attacker re-encodes `{"user":"admin"}`, sends *that*, and the server — which only ever decoded the token and trusted its contents — treats them as the administrator. The team confused *encoding* (making bytes safe to transport) with *integrity* (making them impossible to forge). We fix that confusion for good in [Lesson 2](../02-cryptographic-building-blocks/) and [Lesson 6](../06-jwt-and-token-auth/).

By Sunday the attacker has found the `/admin/users` endpoint — not linked anywhere in the UI, but reachable by anyone who guesses the path — dumped the users table, and discovered the passwords were stored as raw **MD5** hashes, which a consumer GPU reverses at billions of guesses per second ([Lesson 3](../03-password-storage-and-hashing/)). And in the server's log file, helpfully, every request logged its full `Authorization` header in plaintext.

Six findings, and here is the thing to sit with: **they are six *different* problems, and no single feature fixes them.** Adding a login screen fixed none of the deep ones. "Encrypting the token" wouldn't fix the IDOR. A web application firewall wouldn't fix the MD5. Security is not a component you bolt on — a login box, a firewall, an SSL certificate. It is a *property of the whole system*, and it comes from answering four questions correctly on **every single request**:

- **Authentication** — who is making this request, and can they prove it?
- **Authorization** — is *this* identity allowed to perform *this* action on *this* resource?
- **Integrity & confidentiality** — can the data be read or altered by someone who shouldn't, in transit or at rest?
- **Accountability** — if something goes wrong, can we reconstruct who did what?

The rest of this phase builds a mechanism for each of those. This lesson builds the mental model that tells you *which* mechanism a given problem needs — because the AcmeNotes team didn't lack effort, they lacked the vocabulary to see that "we added a login" and "the data is protected" are unrelated sentences.

## The Concept

### Authentication vs authorization: identity versus permission

These two words are used interchangeably in hallway conversation and they must never be confused in code, because they answer different questions, fail differently, and are fixed in different places.

**Authentication** (often shortened to **authN**) is the process of proving *who you are*. You present a **credential** — a password, a token, a private key, a fingerprint — and the system verifies it and concludes: this request is from the principal `u_5501`. That's it. Authentication produces an **identity** and stops.

**Authorization** (**authZ**) takes that established identity and answers a second, separate question: *is this identity permitted to do this specific thing?* Read note 42. Delete user 9. Refund payment X. Authorization needs three inputs — the identity, the action, and the resource — and it produces one output: allow or deny.

The order is not negotiable: **you authenticate first, then authorize.** You cannot decide what someone may do until you know who they are. And the two failures are distinct enough that HTTP gives them separate status codes ([Phase 2, Lesson 2](../../02-api-design/02-urls-verbs-status-codes/)):

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 252" width="100%" style="max-width:840px" role="img" aria-label="A request carrying a credential flows left to right through two gates. The first gate is authentication, asking who are you; failing it returns 401 Unauthorized. The second gate is authorization, asking what may you do; failing it returns 403 Forbidden. A request that passes both reaches the resource with 200 OK.">
  <defs>
    <marker id="l1-ar" markerWidth="10" markerHeight="10" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker>
  </defs>
  <text x="440" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="15" font-weight="700" fill="currentColor">Two gates, two questions — authenticate first, then authorize</text>
  <g fill="none" stroke-linejoin="round" stroke-width="2">
    <rect x="20" y="66" width="118" height="66" rx="10" fill="#7f7f7f" fill-opacity="0.10" stroke="currentColor" stroke-opacity="0.6"/>
    <rect x="226" y="58" width="188" height="82" rx="12" fill="#3553ff" fill-opacity="0.13" stroke="#3553ff"/>
    <rect x="498" y="58" width="188" height="82" rx="12" fill="#0fa07f" fill-opacity="0.14" stroke="#0fa07f"/>
    <rect x="762" y="66" width="96" height="66" rx="10" fill="#7f7f7f" fill-opacity="0.10" stroke="currentColor" stroke-opacity="0.6"/>
  </g>
  <g fill="none" stroke="currentColor" stroke-width="1.8">
    <path d="M142 99 L 220 99" marker-end="url(#l1-ar)"/>
    <path d="M418 99 L 492 99" marker-end="url(#l1-ar)"/>
    <path d="M690 99 L 756 99" marker-end="url(#l1-ar)"/>
  </g>
  <g fill="none" stroke="#d64545" stroke-width="1.8" stroke-dasharray="5 4">
    <path d="M320 144 L 320 190" marker-end="url(#l1-ar)"/>
    <path d="M592 144 L 592 190" marker-end="url(#l1-ar)"/>
  </g>
  <g font-family="'JetBrains Mono', ui-monospace, monospace" fill="currentColor">
    <text x="79" y="96" font-size="12" font-weight="700" text-anchor="middle">REQUEST</text>
    <text x="79" y="116" font-size="9" text-anchor="middle" opacity="0.7">+ credential</text>
    <text x="320" y="90" font-size="12.5" font-weight="700" text-anchor="middle" fill="#3553ff">① AUTHENTICATION</text>
    <text x="320" y="110" font-size="10.5" text-anchor="middle">"who are you?"</text>
    <text x="320" y="127" font-size="9" text-anchor="middle" opacity="0.72">verify the credential</text>
    <text x="592" y="90" font-size="12.5" font-weight="700" text-anchor="middle" fill="#0fa07f">② AUTHORIZATION</text>
    <text x="592" y="110" font-size="10.5" text-anchor="middle">"what may you do?"</text>
    <text x="592" y="127" font-size="9" text-anchor="middle" opacity="0.72">identity vs. policy</text>
    <text x="810" y="96" font-size="12" font-weight="700" text-anchor="middle">RESOURCE</text>
    <text x="810" y="116" font-size="9" text-anchor="middle" opacity="0.7">200 OK</text>
    <text x="320" y="208" font-size="11.5" font-weight="700" text-anchor="middle" fill="#d64545">401 Unauthorized</text>
    <text x="320" y="224" font-size="9" text-anchor="middle" opacity="0.82">you have not proven who you are</text>
    <text x="592" y="208" font-size="11.5" font-weight="700" text-anchor="middle" fill="#d64545">403 Forbidden</text>
    <text x="592" y="224" font-size="9" text-anchor="middle" opacity="0.82">we know you — you may not do this</text>
  </g>
</svg>
```

The **401 vs 403** split is the single most useful diagnostic in web auth, and its naming is famously backwards: **401 Unauthorized actually means *un-authenticated*** — you didn't prove who you are, so try again with a credential. **403 Forbidden means *authenticated but not permitted*** — we know exactly who you are, and the answer is still no, so re-sending the credential won't help. When you see a 401 you go looking at the authentication layer; when you see a 403 you go looking at the authorization policy. Getting them backwards sends every future debugging session to the wrong half of the system.

| | Authentication (authN) | Authorization (authZ) |
|---|---|---|
| **Question** | Who are you? | What may you do? |
| **Checks** | a credential (password, token, key) | identity + action + resource, against a policy |
| **Produces** | an identity (a principal) | a decision: allow or deny |
| **Runs** | first, once per request | after authN, on **every** access |
| **Typical bug** | accepts a forged or replayed credential | IDOR — reads a resource that isn't yours |
| **HTTP failure** | 401 Unauthorized | 403 Forbidden |
| **Built in** | Lessons 3–8 | Lesson 9 |

### Identity, credentials, and claims

Three words get used loosely; precision here pays off in every later lesson.

An **identity** (or **principal**, or **subject**) is the *who* — and it is not always a person. It can be a user, but also a **service** calling another service, a background job, a device, or a bot. A surprising amount of production auth is machine-to-machine, which is why [Lesson 8](../08-api-keys-hmac-and-webhooks/) exists.

A **credential** is the secret or proof used to establish that identity. Credentials come in three classic **factors**, and the whole idea of multi-factor auth ([Lesson 4](../04-multi-factor-auth-totp-and-passkeys/)) is to combine factors from *different* categories so that stealing one isn't enough:

- **Something you know** — a password, a PIN, an answer to a question. Cheap, and the weakest, because knowledge copies perfectly and invisibly.
- **Something you have** — a phone running an authenticator app, a hardware security key, a client certificate.
- **Something you are** — a fingerprint, a face, a voiceprint. A biometric.

A **claim** is a *statement about* an identity — `role = admin`, `email = a@b.com`, `tier = premium` — asserted by some **issuer**. The critical discipline: **a claim is only worth as much as your trust in who issued it and your ability to verify they issued it unchanged.** The AcmeNotes token carried the claim `user = admin` with *no* verifiable issuer, so anyone could mint it. A signed token ([Lesson 6](../06-jwt-and-token-auth/)) carries claims you can cryptographically verify came from your own auth server and weren't edited en route. "Trust the claim" and "verify the signature on the claim" are the difference between a breach and a boring Tuesday.

### The CIA triad: what "secure" actually protects

"Is it secure?" is an unanswerable question until you say *secure against what*. The classic decomposition — old, imperfect, and still the most useful starting frame — is the **CIA triad**. It names the three properties security exists to preserve:

- **Confidentiality** — only authorized parties can *read* the data. Broken by a leak, an over-permissive query, a log line with a card number. Defended with encryption ([Lesson 2](../02-cryptographic-building-blocks/), [13](../13-secrets-management-and-rotation/)), TLS in transit ([Phase 1, Lesson 10](../../01-networking-and-protocols/10-tls-certificates-mtls/)), and access control.
- **Integrity** — data cannot be *altered* undetectably. Broken by the editable Base64 token, by a tampered webhook, by a man-in-the-middle rewriting a response. Defended with hashes, HMACs, and signatures ([Lessons 2](../02-cryptographic-building-blocks/), [6](../06-jwt-and-token-auth/), [8](../08-api-keys-hmac-and-webhooks/)).
- **Availability** — the system stays *usable by legitimate users*. Broken by a denial-of-service flood, a credential-stuffing storm, a resource-exhaustion bug. Defended with rate limits and abuse prevention ([Lesson 12](../12-abuse-prevention/), [Phase 2 Lesson 9](../../02-api-design/09-rate-limiting-quotas/)).

Two more properties are important enough that people often bolt them on as an extended set. **Authenticity** — the assurance that a principal really is who they claim (this is exactly what authentication provides). And **non-repudiation / accountability** — the ability to prove, after the fact, that a specific principal took a specific action, so they can't credibly deny it. That one is why security and observability meet: a tamper-evident **audit log** ([Phase 9](../../09-logging-monitoring-and-observability/02-structured-logging/)) is a security control, not just an ops convenience.

### Threat modeling: think like the attacker, on purpose

You cannot defend against threats you have never named. **Threat modeling** is the discipline of systematically asking *what can go wrong* before you ship, rather than discovering it in an incident review. Adam Shostack's framing reduces it to four honest questions:

1. **What are we building?** (a data-flow diagram: where does data come from, where does it go, what's trusted)
2. **What can go wrong?** (enumerate threats against each flow)
3. **What are we going to do about it?** (a control for each threat, or an accepted risk)
4. **Did we do a good job?** (review it — threat models rot as the system changes)

For step 2 the industry-standard checklist is **STRIDE**, six threat categories, each of which maps cleanly onto a property from the last section *and* onto a lesson in this phase. This table is, quite literally, a map of everything you're about to build:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 430" width="100%" style="max-width:880px" role="img" aria-label="The six STRIDE threat categories, each mapped to what the attacker does, the security property it violates, and the defense with the lesson that builds it. Spoofing violates authenticity, defended by passwords, MFA and tokens. Tampering violates integrity, defended by hashing, HMAC and signatures. Repudiation violates accountability, defended by signed audit logs. Information disclosure violates confidentiality, defended by TLS, encryption and access control. Denial of service violates availability, defended by rate limits and quotas. Elevation of privilege violates authorization, defended by RBAC, ABAC and least privilege.">
  <text x="450" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="15" font-weight="700" fill="currentColor">STRIDE — every threat maps to a property and a defense (this is the phase)</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace" fill="currentColor">
    <text x="20" y="58" font-size="10" opacity="0.7">THREAT</text>
    <text x="230" y="58" font-size="10" opacity="0.7">WHAT THE ATTACKER DOES</text>
    <text x="500" y="58" font-size="10" opacity="0.7">VIOLATES</text>
    <text x="648" y="58" font-size="10" opacity="0.7">DEFENSE · WHERE YOU BUILD IT</text>
  </g>
  <g stroke="currentColor" stroke-width="1" opacity="0.18">
    <line x1="20" y1="66" x2="880" y2="66"/>
    <line x1="20" y1="116" x2="880" y2="116"/><line x1="20" y1="166" x2="880" y2="166"/><line x1="20" y1="216" x2="880" y2="216"/>
    <line x1="20" y1="266" x2="880" y2="266"/><line x1="20" y1="316" x2="880" y2="316"/><line x1="20" y1="366" x2="880" y2="366"/>
  </g>
  <g font-family="'JetBrains Mono', ui-monospace, monospace" font-size="10.5" fill="currentColor">
    <text x="20" y="95" font-size="12" font-weight="700" fill="#3553ff">S · Spoofing</text>
    <text x="230" y="95">pretend to be another user or service</text>
    <text x="500" y="95" font-weight="700">Authenticity</text>
    <text x="648" y="95">passwords · MFA · tokens — L3–L7</text>

    <text x="20" y="145" font-size="12" font-weight="700" fill="#e0930f">T · Tampering</text>
    <text x="230" y="145">alter data or a message in flight</text>
    <text x="500" y="145" font-weight="700">Integrity</text>
    <text x="648" y="145">hashing · HMAC · signatures — L2·L6·L8</text>

    <text x="20" y="195" font-size="12" font-weight="700" fill="#7c5cff">R · Repudiation</text>
    <text x="230" y="195">deny having done an action</text>
    <text x="500" y="195" font-weight="700">Accountability</text>
    <text x="648" y="195">signed audit logs — L6 · Phase 9</text>

    <text x="20" y="245" font-size="12" font-weight="700" fill="#0fa07f">I · Info disclosure</text>
    <text x="230" y="245">read data meant to stay secret</text>
    <text x="500" y="245" font-weight="700">Confidentiality</text>
    <text x="648" y="245">TLS · encryption · access ctl — L2·L13</text>

    <text x="20" y="295" font-size="12" font-weight="700" fill="#d64545">D · Denial of service</text>
    <text x="230" y="295">exhaust the system, deny others</text>
    <text x="500" y="295" font-weight="700">Availability</text>
    <text x="648" y="295">rate limits · quotas — L12 · Phase 2</text>

    <text x="20" y="345" font-size="12" font-weight="700" fill="#c2497a">E · Elevation of priv.</text>
    <text x="230" y="345">gain rights you were never granted</text>
    <text x="500" y="345" font-weight="700">Authorization</text>
    <text x="648" y="345">RBAC/ABAC · least privilege — L9</text>
  </g>
  <text x="450" y="395" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="10.5" fill="currentColor" opacity="0.85">Confidentiality, Integrity, Availability are rows I, T, D — the classic CIA triad. Authenticity and</text>
  <text x="450" y="413" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="10.5" fill="currentColor" opacity="0.85">Accountability (rows S, R) extend it; Elevation (E) is the authorization failure the whole phase guards.</text>
</svg>
```

Threat modeling is not a heavyweight ceremony reserved for banks. For a single new endpoint it can be four minutes at a whiteboard: *what crosses a trust boundary here, and one line of STRIDE per input.* The `outputs/` artifact for this lesson is exactly that worksheet.

### Trust boundaries and the attack surface

A **trust boundary** is any line data crosses to move from a less-trusted zone into a more-trusted one: the internet into your load balancer, a browser into your API, one microservice into another, a third-party webhook into your handler. **The defining rule of security engineering is that every input crossing a trust boundary must be authenticated and validated at the boundary**, because on the other side of that line you have no control over what was sent. The AcmeNotes team trusted the token's contents *after* it crossed the client→server boundary without verifying it — the boundary was there, but nothing stood on it.

The **attack surface** is the sum of every point where an attacker can feed you input: every endpoint, every parameter, every header, every cookie, every queue message, every dependency you import. A blunt but reliable truth: **the smaller the attack surface, the less can go wrong.** Fewer endpoints, fewer parameters, fewer privileges, fewer dependencies — each deletion is a class of bug that can no longer exist. "Reduce the attack surface" is why an internal admin API should not be reachable from the public internet at all, rather than merely being password-protected.

### The principles that outrank the mechanisms

Tools change — bcrypt gives way to argon2, sessions give way to tokens, RBAC gives way to policy engines. The principles underneath, most of them first written down by Saltzer and Schroeder in 1975, do not. Internalize these and you will make good calls about tools you have never seen:

- **Never trust the client.** Anything the client controls is attacker-controlled: URL parameters, form fields, headers, cookies, hidden inputs, the JavaScript you shipped, the price in the cart. Validate and enforce **on the server, every time.** This single rule would have prevented four of the six AcmeNotes bugs. It is the most important sentence in this phase.
- **Least privilege.** Every identity — user, service, token, database account — gets the *minimum* access needed to do its job, and nothing more. When something is inevitably compromised, least privilege is what bounds the blast radius from "everything" to "a little."
- **Defense in depth.** No single control is your only control. If the firewall misses it, input validation catches it; if that misses, least privilege limits it; if that fails, the audit log lets you find it. Layers, so that one failure is not a breach.
- **Fail closed (secure by default).** When something breaks or is ambiguous — the authorization service times out, a config is missing, an exception is thrown mid-check — the safe default is to **deny**. A security check that crashes must not accidentally allow. The dangerous version reads `if not is_denied(): allow()`; the safe version proves *allow* explicitly and denies everything else.
- **No security through obscurity.** A hidden endpoint, an undocumented parameter, a secret algorithm — none of these is a security control, because attackers enumerate paths, read your minified JavaScript, and decompile your app. Assume the attacker knows exactly how your system works (**Kerckhoffs's principle**); the *only* thing that may be secret is the **keys**, never the design. AcmeNotes' `/admin/users` was "protected" by not being linked. It was not protected.
- **Complete mediation.** Check authorization on *every* access, not just the first. Bugs love the cached "yes" — the object you authorized on load and then mutated ten requests later without re-checking.

### Where auth lives: the whole request lifecycle

Because security is a property of the system and not a feature, the controls are spread across the entire path a request travels — which is also, conveniently, a table of contents for this phase. Read this top to bottom as one request's journey, and notice that defense in depth means a hostile request has to get past *all* of these, not one:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 760 566" width="100%" style="max-width:660px" role="img" aria-label="A request travels top to bottom through eight layers, each enforcing a security control. Transport TLS for confidentiality in transit. Edge gateway and WAF to filter malicious traffic. Rate limiting to protect availability. Authentication to establish who. Authorization to decide what may be done. Input validation to stop injection. Business logic applying least privilege on every data access. Data and secrets with encryption at rest. On the way out, output is encoded and secrets are stripped from logs and errors.">
  <defs>
    <marker id="l1-dn" markerWidth="10" markerHeight="10" refX="5" refY="6" orient="auto"><path d="M2,0 L8,0 L5,7 Z" fill="currentColor"/></marker>
  </defs>
  <text x="380" y="24" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="15" font-weight="700" fill="currentColor">One request, eight layers of defense</text>
  <text x="380" y="44" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="10" fill="currentColor" opacity="0.7">a hostile request must pass every layer — that is defense in depth</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <g>
      <rect x="150" y="58" width="460" height="46" rx="9" fill="#7c5cff" fill-opacity="0.10" stroke="#7c5cff" stroke-width="1.5"/>
      <rect x="150" y="58" width="6" height="46" rx="3" fill="#7c5cff"/>
      <text x="170" y="78" font-size="11.5" font-weight="700" fill="currentColor">1 · Transport (TLS)</text>
      <text x="170" y="95" font-size="9" fill="currentColor" opacity="0.78">encrypts the connection — confidentiality &amp; integrity in transit</text>
      <text x="596" y="86" font-size="10" text-anchor="end" fill="#7c5cff">P1·L10</text>
    </g>
    <g>
      <rect x="150" y="116" width="460" height="46" rx="9" fill="#d64545" fill-opacity="0.10" stroke="#d64545" stroke-width="1.5"/>
      <rect x="150" y="116" width="6" height="46" rx="3" fill="#d64545"/>
      <text x="170" y="136" font-size="11.5" font-weight="700" fill="currentColor">2 · Edge (Gateway / WAF)</text>
      <text x="170" y="153" font-size="9" fill="currentColor" opacity="0.78">filters obviously-malicious traffic before it reaches your code</text>
      <text x="596" y="144" font-size="10" text-anchor="end" fill="#d64545">L11·L12</text>
    </g>
    <g>
      <rect x="150" y="174" width="460" height="46" rx="9" fill="#e0930f" fill-opacity="0.10" stroke="#e0930f" stroke-width="1.5"/>
      <rect x="150" y="174" width="6" height="46" rx="3" fill="#e0930f"/>
      <text x="170" y="194" font-size="11.5" font-weight="700" fill="currentColor">3 · Rate limiting</text>
      <text x="170" y="211" font-size="9" fill="currentColor" opacity="0.78">protects availability from floods and brute-force</text>
      <text x="596" y="202" font-size="10" text-anchor="end" fill="#e0930f">L12 · P2·L9</text>
    </g>
    <g>
      <rect x="150" y="232" width="460" height="46" rx="9" fill="#3553ff" fill-opacity="0.11" stroke="#3553ff" stroke-width="1.5"/>
      <rect x="150" y="232" width="6" height="46" rx="3" fill="#3553ff"/>
      <text x="170" y="252" font-size="11.5" font-weight="700" fill="currentColor">4 · Authentication</text>
      <text x="170" y="269" font-size="9" fill="currentColor" opacity="0.78">establishes WHO — sessions, JWT, OAuth, API keys</text>
      <text x="596" y="260" font-size="10" text-anchor="end" fill="#3553ff">L4–L8</text>
    </g>
    <g>
      <rect x="150" y="290" width="460" height="46" rx="9" fill="#0fa07f" fill-opacity="0.12" stroke="#0fa07f" stroke-width="1.5"/>
      <rect x="150" y="290" width="6" height="46" rx="3" fill="#0fa07f"/>
      <text x="170" y="310" font-size="11.5" font-weight="700" fill="currentColor">5 · Authorization</text>
      <text x="170" y="327" font-size="9" fill="currentColor" opacity="0.78">decides WHAT MAY BE DONE — RBAC / ABAC / ReBAC</text>
      <text x="596" y="318" font-size="10" text-anchor="end" fill="#0fa07f">L9</text>
    </g>
    <g>
      <rect x="150" y="348" width="460" height="46" rx="9" fill="#e0930f" fill-opacity="0.10" stroke="#e0930f" stroke-width="1.5"/>
      <rect x="150" y="348" width="6" height="46" rx="3" fill="#e0930f"/>
      <text x="170" y="368" font-size="11.5" font-weight="700" fill="currentColor">6 · Input validation</text>
      <text x="170" y="385" font-size="9" fill="currentColor" opacity="0.78">stops injection, SSRF, path traversal at the boundary</text>
      <text x="596" y="376" font-size="10" text-anchor="end" fill="#e0930f">L10·L11</text>
    </g>
    <g>
      <rect x="150" y="406" width="460" height="46" rx="9" fill="#7f7f7f" fill-opacity="0.10" stroke="currentColor" stroke-opacity="0.5" stroke-width="1.5"/>
      <rect x="150" y="406" width="6" height="46" rx="3" fill="currentColor"/>
      <text x="170" y="426" font-size="11.5" font-weight="700" fill="currentColor">7 · Business logic</text>
      <text x="170" y="443" font-size="9" fill="currentColor" opacity="0.78">least privilege on every data access — the IDOR check lives here</text>
      <text x="596" y="434" font-size="10" text-anchor="end" fill="currentColor" opacity="0.7">L9</text>
    </g>
    <g>
      <rect x="150" y="464" width="460" height="46" rx="9" fill="#7c5cff" fill-opacity="0.10" stroke="#7c5cff" stroke-width="1.5"/>
      <rect x="150" y="464" width="6" height="46" rx="3" fill="#7c5cff"/>
      <text x="170" y="484" font-size="11.5" font-weight="700" fill="currentColor">8 · Data &amp; secrets</text>
      <text x="170" y="501" font-size="9" fill="currentColor" opacity="0.78">encryption at rest, key management, rotation</text>
      <text x="596" y="492" font-size="10" text-anchor="end" fill="#7c5cff">L2·L13</text>
    </g>
  </g>
  <g fill="none" stroke="currentColor" stroke-width="1.6" opacity="0.55">
    <path d="M380 104 L 380 114" marker-end="url(#l1-dn)"/><path d="M380 162 L 380 172" marker-end="url(#l1-dn)"/>
    <path d="M380 220 L 380 230" marker-end="url(#l1-dn)"/><path d="M380 278 L 380 288" marker-end="url(#l1-dn)"/>
    <path d="M380 336 L 380 346" marker-end="url(#l1-dn)"/><path d="M380 394 L 380 404" marker-end="url(#l1-dn)"/>
    <path d="M380 452 L 380 462" marker-end="url(#l1-dn)"/>
  </g>
  <text x="380" y="536" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="9.5" fill="currentColor" opacity="0.85">On the way out: encode output against XSS (L10), and strip secrets from logs &amp; error bodies (L13, P10).</text>
  <text x="380" y="554" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="9.5" fill="currentColor" opacity="0.85">Accountability runs across all eight: a tamper-evident audit log records who did what (Phase 9).</text>
</svg>
```

The AcmeNotes disaster is now legible as a *layer* diagram: the missing token check was layer 4 absent, the IDOR was layer 7 absent, the forgeable token was layer 4 done without integrity, the exposed admin endpoint was layer 2 plus layer 5 absent, the MD5 was layer 8 done wrong, and the logged `Authorization` header was the outbound rule ignored. Not one bug — six holes across six layers. That is what "security is a property of the whole system" means in practice, and it is why this phase is thirteen lessons and not one.

## Think about it

1. A junior engineer "adds security" by requiring a valid token on every endpoint, then closes the ticket. The IDOR from *The Problem* — any logged-in user reading `/notes/{anyone}` — is untouched. Which of the two questions did they answer, which did they skip, and what status code should `/notes/{someone-elses-id}` return to a valid but unauthorized user?
2. Your load balancer terminates TLS and forwards an `X-User-Id` header to your app, which reads it and trusts it as the caller's identity. Explain why this is a spoofing vulnerability in STRIDE terms. Where exactly is the trust boundary, and what is standing on it?
3. An attacker completes a fraudulent transaction and then deletes the log entries that recorded it. Name the STRIDE category, the property (from the CIA-plus set) it violates, and one control that would have preserved the evidence.
4. A teammate argues: "Our internal admin API is safe because the URL isn't documented anywhere and nobody knows the endpoint names." Name the principle this violates, and give two concrete ways an attacker finds undocumented endpoints anyway.
5. Your authorization service is slow and occasionally times out under load. Engineer A proposes: on timeout, **deny** the request. Engineer B proposes: on timeout, **allow** it, "so the site doesn't break for real users." State which principle decides this, which engineer is right, and describe the business pressure that pushes teams toward the wrong answer.

## Key takeaways

- **Authentication answers *who are you* and produces an identity; authorization answers *what may you do* and produces an allow/deny decision.** They fail differently (401 vs 403), are fixed in different code, and you always authenticate first, then authorize *every* access. Confusing them is the root of the most common serious web bug, IDOR.
- **A credential is only as trustworthy as your ability to verify it, and a claim only as trustworthy as its issuer.** Base64 is encoding, not integrity; a forgeable token is no better than no token. Multi-factor auth combines credentials from *different* factors so one theft isn't enough.
- **The CIA triad — confidentiality, integrity, availability, plus authenticity and accountability — names *what* you protect.** Every lesson in this phase builds a mechanism for one of these, and "is it secure?" has no meaning until you say *against what*.
- **Threat modeling with STRIDE turns vague worry into a checklist** — spoofing, tampering, repudiation, information disclosure, denial of service, elevation of privilege — where each threat maps to a property and a concrete defense. Do it at the trust boundaries, where untrusted input crosses into trusted code.
- **The principles outrank the mechanisms:** never trust the client, least privilege, defense in depth, fail closed, no security through obscurity, complete mediation. They will still be true when today's libraries are gone — and "never trust the client, enforce on the server" alone prevents a large fraction of real breaches.
- **Security is a property of the whole request lifecycle,** enforced in layers from TLS to the data store, not a login function you add at the end. A breach is usually several small holes across several layers — which is exactly why one feature never "makes it secure."

Next: [Cryptographic Building Blocks](../02-cryptographic-building-blocks/) — you now know that encoding is not integrity and that a claim needs a verifiable signature; next you build the primitives — hashing, HMAC, symmetric and asymmetric encryption, and a safe random generator — that every mechanism in this phase is made of.
