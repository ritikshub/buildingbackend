# Password Storage & Hashing

> Plan for the day your user table leaks, because eventually one will. When it does, the difference between a footnote and a front-page breach is entirely how you stored the passwords. This lesson turns a password into something that survives theft — salted so identical passwords don't match and rainbow tables die, and *deliberately slow and memory-hard* so a GPU that guesses ten billion fast hashes a second manages only a few thousand of yours. You'll build a real salted, work-factored hasher from the standard library, then ship Argon2.

**Type:** Build
**Languages:** Python
**Prerequisites:** [Cryptographic Building Blocks](../02-cryptographic-building-blocks/)
**Time:** ~70 minutes

## The Problem

A mid-sized company's `users` table leaks — a backup left on a public bucket, an SQL injection, a compromised admin laptop. This is not a hypothetical; it is the single most common way credentials reach attackers, and it happens to careful teams. The only variable you control ahead of time is *what the attacker gets when they open that file.* Here is the same leak under four storage schemes, from the attacker's side of the table:

**Plaintext.** `password: hunter2`. There is no work to do. Every account is compromised the instant the file is copied — including every account where the user reused that password on their bank and their email. Nobody defends this on purpose, yet it keeps happening through debug logs, analytics events, and "temporary" columns.

**A fast hash, no salt** (`md5`, `sha1`, `sha256`). The column now holds `ef92b778…` instead of `hunter2`, which *feels* safe. It is not, for two independent reasons. First, the hash is deterministic and unsalted, so two users with the same password have the **same hash** — the attacker sorts the column and cracks the ten thousand accounts sharing the most common hash all at once, and precomputed **rainbow tables** (giant reverse lookups of hash → password) turn common passwords into instant lookups. Second, and worse, SHA-256 is *fast by design*: a single gaming GPU computes on the order of **10 billion SHA-256 hashes per second**, so the attacker simply tries every candidate. Every password on a typical wordlist falls in seconds; eight-character passwords fall in hours.

**A fast hash, salted.** Add a unique random **salt** per user and hash `salt ∥ password`. This kills rainbow tables (they'd need one per salt) and breaks the identical-hash correlation — real, necessary progress. But it changes nothing about *throughput*: the GPU still does ten billion guesses a second, now aimed at one salted hash at a time. Weak and medium passwords still fall, just without the bulk discount. **Salt fixes precomputation; it does nothing about speed.**

**A slow, memory-hard hash** (bcrypt, scrypt, Argon2). Now each single guess is engineered to cost ~100 milliseconds of CPU *and* tens of megabytes of RAM. The GPU's ten-billion-per-second collapses to a few thousand per second, because the memory requirement starves the thousands of parallel cores that made it fast, and there isn't enough RAM to run them at once. A strong password that would take hours against SHA-256 now takes **centuries**, and the economics flip: cracking the database stops being worth the electricity.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 372" width="100%" style="max-width:880px" role="img" aria-label="Four password storage schemes ranked by how fast an attacker who stole the database can guess. Plaintext: already cracked, no work. Fast unsalted hash such as SHA-256: about ten billion guesses per second plus rainbow tables, whole database in hours. Fast salted hash: rainbow tables defeated but still about ten billion guesses per second, weak passwords in hours. Slow memory-hard hash such as Argon2: only thousands of guesses per second, strong passwords infeasible for centuries.">
  <text x="450" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="15" font-weight="700" fill="currentColor">Same stolen database, four storage schemes — attacker guess rate</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <text x="20" y="66" font-size="10.5" font-weight="700" fill="#d64545">PLAINTEXT</text>
    <rect x="20" y="74" width="700" height="26" rx="5" fill="#d64545" fill-opacity="0.75" stroke="none"/>
    <text x="30" y="92" font-size="10.5" fill="#ffffff">already cracked — 100% of accounts, instantly, zero work</text>
    <text x="730" y="92" font-size="10" fill="currentColor" opacity="0.85">cost: $0</text>

    <text x="20" y="132" font-size="10.5" font-weight="700" fill="#e0930f">FAST HASH · NO SALT  (md5, sha256)</text>
    <rect x="20" y="140" width="640" height="26" rx="5" fill="#e0930f" fill-opacity="0.7" stroke="none"/>
    <text x="30" y="158" font-size="10.5" fill="currentColor">~10,000,000,000 / sec  +  rainbow tables  +  identical hashes crack together</text>
    <text x="730" y="158" font-size="10" fill="currentColor" opacity="0.85">whole DB: hours</text>

    <text x="20" y="198" font-size="10.5" font-weight="700" fill="#3553ff">FAST HASH · SALTED</text>
    <rect x="20" y="206" width="600" height="26" rx="5" fill="#3553ff" fill-opacity="0.6" stroke="none"/>
    <text x="30" y="224" font-size="10.5" fill="currentColor">rainbow tables dead, no bulk cracking — but still ~10,000,000,000 / sec</text>
    <text x="730" y="224" font-size="10" fill="currentColor" opacity="0.85">weak pw: hours</text>

    <text x="20" y="264" font-size="10.5" font-weight="700" fill="#0fa07f">SLOW · MEMORY-HARD  (bcrypt, scrypt, argon2)</text>
    <rect x="20" y="272" width="22" height="26" rx="5" fill="#0fa07f" fill-opacity="0.85" stroke="none"/>
    <text x="52" y="290" font-size="10.5" fill="currentColor">~1,000–10,000 / sec — memory starves the GPU's parallel cores</text>
    <text x="730" y="290" font-size="10" fill="currentColor" opacity="0.85">strong pw: centuries</text>
  </g>
  <line x1="20" y1="316" x2="880" y2="316" stroke="currentColor" stroke-opacity="0.2" stroke-width="1"/>
  <text x="450" y="338" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="10.5" fill="currentColor" opacity="0.9">Bar length = attacker throughput = your risk. Salt removes the shortcuts; only a slow, memory-hard</text>
  <text x="450" y="356" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="10.5" fill="currentColor" opacity="0.9">hash attacks the throughput itself. You need both: a unique salt AND a deliberately expensive hash.</text>
</svg>
```

The lesson is in the last two rows: **salting and slowness are different defenses against different attacks, and you need both.** Everything below builds up to a hash that has them.

## The Concept

### Assume the database will leak

Every other lesson in this phase protects data in transit or controls who may act. Password storage is the one place you design explicitly for the assumption that **the attacker already has your database** — the hashes, the salts, the schema, all of it. Under that assumption, transport security (TLS) is irrelevant and access control is already lost; the *only* thing standing between the leak and the user's other accounts is how expensive you made reversing the hash. This is why "we use HTTPS" is not an answer to "how do you store passwords," and why the threat model here is unusually concrete: assume worst case, then measure the attacker's cost in dollars and years.

### Never plaintext, never reversible encryption

Two non-starters. **Plaintext** needs no elaboration, but note that it leaks through side doors — a `logger.info(f"login {user} {password}")`, an analytics payload, an error report — not just the password column ([Phase 9 logging hygiene](../../09-logging-monitoring-and-observability/02-structured-logging/)). **Reversible encryption** is subtler and tempting: "we'll AES-encrypt the passwords." Don't. Encryption implies a key, the key lives near the data (in the app, in an env var, in the same breach), and the moment it leaks *every password is instantly recovered*. You never need to read a password back — you only need to check whether a login attempt matches — so a **one-way hash** is exactly right and reversibility is a liability, not a feature. Passwords get **hashed**, not encrypted.

### Why a fast hash is the wrong hash

Here is the counterintuitive core of the lesson: for passwords, the speed that makes SHA-256 excellent everywhere else makes it dangerous. A general-purpose hash is *designed* to be fast — you want to fingerprint a gigabyte instantly. But "verify a password" happens once per login, so you can afford to make it take 100 ms — and the attacker doing a billion guesses cannot. **A password hash's slowness is a feature aimed squarely at the attacker's throughput.** SHA-256 gives the attacker 10¹⁰ guesses/second; a tuned Argon2 gives them 10³–10⁴. That six-orders-of-magnitude gap is the entire game, and it's why you must use a hash *built to be slow* (bcrypt, scrypt, Argon2), never SHA-256 or MD5 — not even "SHA-256 a few times."

### Salt: a unique random value per password

A **salt** is a unique, random value generated per password (from a CSPRNG, [Lesson 2](../02-cryptographic-building-blocks/)) and hashed together with it: `hash(salt ∥ password)`. It is **not secret** — you store it in plaintext right next to the hash — because its job isn't secrecy, it's *uniqueness*. Two consequences follow. First, **rainbow tables die**: a precomputed table is built for one salt, so a unique per-user salt forces the attacker to start over for every single account. Second, **identical passwords get different hashes**, so the attacker can't see that ten thousand users share a password, can't crack them as a batch, and can't learn anything from the hash column's structure. A 16-byte random salt is standard; the modern hash functions generate and embed it for you.

### Pepper: a secret the leak doesn't contain

A **pepper** is salt's less-common cousin: a single secret value, the same for all users, mixed into the hash — but stored **separately from the database** (in a secrets manager or HSM, [Lesson 13](../13-secrets-management-and-rotation/)), so a database-only leak doesn't include it. Implemented as `HMAC(pepper, password)` before the slow hash, it means an attacker who steals *only* the database still cannot begin cracking, because they're missing an input. It's defense in depth, not a replacement for slowness or salt: if the attacker gets both the DB and the pepper, you're back to relying on the work factor. Use it when you can keep the pepper genuinely out of the breached blast radius.

### Work factor and memory-hardness: pricing the attacker out

Slowness is tunable, and the knob is the **work factor** (also *cost factor* or *iterations*): how much computation one hash costs. You set it so a single hash takes ~100–250 ms on your server — unnoticeable at one login, ruinous at a billion guesses — and you *raise it over time* as hardware gets faster (bcrypt cost went from 10 to 12+ over the years). But CPU-cost alone has a weakness: attackers don't use CPUs, they use **GPUs and ASICs** with thousands of tiny parallel cores. The counter is **memory-hardness**: make each hash also require a large chunk of RAM (tens of MB). A GPU has thousands of cores but not thousands × tens-of-MB of fast memory, so the memory requirement *starves the parallelism* that made the hardware cheap. That's why the modern recommendation is a **memory-hard** function (scrypt, Argon2) over a CPU-only one (bcrypt, PBKDF2).

### The algorithms, ranked for today

Four names, in the order a 2020s backend should prefer them:

- **Argon2id** — winner of the 2015 Password Hashing Competition and the current default recommendation (OWASP, RFC 9106). Memory-hard, tunable on memory, time, and parallelism, resistant to both GPU and side-channel attacks. Use this for new systems.
- **scrypt** — memory-hard, older, well-understood, and available in Python's standard library as `hashlib.scrypt` *when Python is built against OpenSSL's scrypt* (not guaranteed on every build). A solid choice.
- **bcrypt** — battle-tested since 1999, CPU-cost-only (not memory-hard), and carrying a historical quirk: it silently truncates passwords to **72 bytes**. Still acceptable, still everywhere, but not the first pick for new code.
- **PBKDF2** — CPU-only and not memory-hard, so the weakest of the four against GPUs, but FIPS-approved and **guaranteed present in every stdlib build** (`hashlib.pbkdf2_hmac`) — which is exactly why you'll build with it below, then upgrade to memory-hard Argon2 in production.

Never on this list: MD5, SHA-1, SHA-256, SHA-3, or any general-purpose hash, with or without "rounds."

### The encoded hash: one self-describing string

You don't store the hash alone — you store a single string that also records *which algorithm and parameters produced it*, plus the salt. The de-facto standard is the **PHC string format**, and reading one tells you everything needed to verify a password (and whether it's time to upgrade):

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 236" width="100%" style="max-width:880px" role="img" aria-label="An Argon2 PHC-format hash string broken into its parts: dollar-argon2id names the algorithm, v=19 the version, m=65536 t=3 p=4 the memory time and parallelism parameters, then a Base64 salt, then the Base64 hash. Everything needed to verify and to decide whether to upgrade is embedded in the one field.">
  <text x="450" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="15" font-weight="700" fill="currentColor">Anatomy of a stored password (PHC string format)</text>
  <text x="450" y="66" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14" fill="currentColor">$argon2id$v=19$m=65536,t=3,p=4$c29tZXNhbHQ$RdescudvJCsgt3ub+b+dWRWJTmaQzFYWZBVfoc2Rgds</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace" font-size="10.5">
    <g fill="none" stroke-width="1.6">
      <path d="M120 78 L 120 104 L 150 104" stroke="#7c5cff"/>
      <path d="M200 78 L 200 128 L 230 128" stroke="#3553ff"/>
      <path d="M300 78 L 300 152 L 330 152" stroke="#e0930f"/>
      <path d="M470 78 L 470 104 L 500 104" stroke="#0fa07f"/>
      <path d="M660 78 L 660 128 L 690 128" stroke="#d64545"/>
    </g>
    <text x="156" y="108" fill="#7c5cff" font-weight="700">algorithm — argon2id (the memory-hard variant)</text>
    <text x="236" y="132" fill="#3553ff" font-weight="700">version — 0x13 = 19</text>
    <text x="336" y="156" fill="#e0930f" font-weight="700">parameters — memory 64 MiB, time 3 passes, parallelism 4</text>
    <text x="506" y="108" fill="#0fa07f" font-weight="700">salt (Base64) — unique per user, not secret</text>
    <text x="696" y="132" fill="#d64545" font-weight="700">the hash (Base64)</text>
  </g>
  <text x="450" y="206" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="10.5" fill="currentColor" opacity="0.9">Self-describing: verification reads the algorithm, params, and salt straight from the string —</text>
  <text x="450" y="224" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="10.5" fill="currentColor" opacity="0.9">and if the params are weaker than today's policy, you re-hash the password on the user's next login.</text>
</svg>
```

Because the parameters travel with the hash, you can **upgrade security transparently**: raise the work factor in config, and on each user's next successful login you notice their stored hash used the old (weaker) parameters, and silently re-hash their password with the new ones. Over a login cycle the whole table strengthens with no password resets. This *rehash-on-login* is the register-verify flow's third path:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 316" width="100%" style="max-width:880px" role="img" aria-label="Register flow: a password plus a fresh random salt and current parameters go through a slow memory-hard hash, and the encoded string of parameters, salt, and hash is stored. Verify flow: an incoming password is hashed with the salt and parameters read from the stored string, and the result is compared in constant time; a match with outdated parameters triggers a transparent re-hash with today's parameters.">
  <defs>
    <marker id="l3-ar" markerWidth="10" markerHeight="10" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker>
  </defs>
  <text x="450" y="24" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="15" font-weight="700" fill="currentColor">Register, verify, and transparent upgrade</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <text x="30" y="66" font-size="12" font-weight="700" fill="#3553ff">REGISTER</text>
    <g fill="none" stroke-linejoin="round" stroke-width="1.8">
      <rect x="30" y="76" width="120" height="34" rx="7" fill="#7f7f7f" fill-opacity="0.10" stroke="currentColor" stroke-opacity="0.5"/>
      <rect x="30" y="118" width="120" height="30" rx="7" fill="#0fa07f" fill-opacity="0.12" stroke="#0fa07f"/>
      <rect x="250" y="86" width="150" height="42" rx="8" fill="#e0930f" fill-opacity="0.13" stroke="#e0930f"/>
      <rect x="470" y="88" width="410" height="38" rx="8" fill="#3553ff" fill-opacity="0.10" stroke="#3553ff"/>
    </g>
    <g fill="none" stroke="currentColor" stroke-width="1.6">
      <path d="M150 100 L 246 100" marker-end="url(#l3-ar)"/>
      <path d="M150 132 L 200 132 L 200 110 L 246 110" marker-end="url(#l3-ar)"/>
      <path d="M400 107 L 466 107" marker-end="url(#l3-ar)"/>
    </g>
    <text x="90" y="97" font-size="9.5" text-anchor="middle">password</text>
    <text x="90" y="137" font-size="8.5" text-anchor="middle">+ CSPRNG salt</text>
    <text x="325" y="103" font-size="9.5" text-anchor="middle">slow hash</text>
    <text x="325" y="117" font-size="8" text-anchor="middle" opacity="0.7">m,t,p params</text>
    <text x="675" y="103" font-size="9" text-anchor="middle">store  $argon2id$…$salt$hash</text>
    <text x="675" y="117" font-size="8" text-anchor="middle" opacity="0.7">one self-describing column</text>
  </g>
  <line x1="30" y1="170" x2="870" y2="170" stroke="currentColor" stroke-opacity="0.18" stroke-width="1"/>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <text x="30" y="200" font-size="12" font-weight="700" fill="#0fa07f">VERIFY (login)</text>
    <g fill="none" stroke-linejoin="round" stroke-width="1.8">
      <rect x="30" y="210" width="120" height="34" rx="7" fill="#7f7f7f" fill-opacity="0.10" stroke="currentColor" stroke-opacity="0.5"/>
      <rect x="250" y="204" width="150" height="46" rx="8" fill="#e0930f" fill-opacity="0.13" stroke="#e0930f"/>
      <rect x="470" y="210" width="180" height="34" rx="8" fill="#0fa07f" fill-opacity="0.12" stroke="#0fa07f"/>
      <rect x="700" y="210" width="180" height="34" rx="8" fill="#7c5cff" fill-opacity="0.12" stroke="#7c5cff"/>
    </g>
    <g fill="none" stroke="currentColor" stroke-width="1.6">
      <path d="M150 227 L 246 227" marker-end="url(#l3-ar)"/>
      <path d="M400 227 L 466 227" marker-end="url(#l3-ar)"/>
      <path d="M650 227 L 696 227" marker-end="url(#l3-ar)"/>
    </g>
    <text x="90" y="231" font-size="9.5" text-anchor="middle">password</text>
    <text x="325" y="224" font-size="9" text-anchor="middle">hash with stored</text>
    <text x="325" y="238" font-size="9" text-anchor="middle">salt + params</text>
    <text x="560" y="224" font-size="9" text-anchor="middle">compare_digest</text>
    <text x="560" y="238" font-size="8" text-anchor="middle" opacity="0.7">constant-time</text>
    <text x="790" y="224" font-size="9" text-anchor="middle">match + old params?</text>
    <text x="790" y="238" font-size="8" text-anchor="middle" opacity="0.72">→ re-hash silently</text>
  </g>
  <text x="450" y="300" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="10" fill="currentColor" opacity="0.85">A pepper (one secret, stored outside the DB) is applied as HMAC(pepper, password) before the slow hash in both lanes.</text>
</svg>
```

### Storage isn't the whole story

Even a perfect hash doesn't stop *online* guessing — an attacker hammering your login endpoint with `password123` across a million usernames (**credential stuffing**). Storage protects the stolen file; the login endpoint needs its own defenses: **rate limiting and lockout** ([Lesson 12](../12-abuse-prevention/)), **MFA** ([Lesson 4](../04-multi-factor-auth-totp-and-passkeys/)), and **breach checking** — comparing new passwords against known-leaked lists so users can't pick a password that's already on every wordlist. The gold-standard breach check is **Have I Been Pwned's k-anonymity API**: hash the password with SHA-1, send only the *first five hex characters* of the hash, receive every leaked suffix sharing that prefix, and check locally — so you learn if the password is breached without ever sending it. And on policy, modern guidance (**NIST SP 800-63B**) is the opposite of the old rules: **favor length over complexity** (allow long passphrases, screen against breach lists), **don't force periodic rotation** (it produces `Password1!` → `Password2!`), drop composition rules, and allow paste so password managers work.

## Build It

Standard library only. `hashlib.pbkdf2_hmac` gives a slow, work-factored hash that's present in *every* Python build, `secrets` the salt, `hmac.compare_digest` the constant-time check — enough to build a real hasher with a self-describing encoded string, verification, transparent upgrade, and a from-scratch demonstration of the k-anonymity idea. (PBKDF2 is CPU-hard, not memory-hard — the memory-hardness that finishes the job is exactly what Argon2 adds in *Use It*.)

First, the failure the lesson turns on: an unsalted fast hash makes identical passwords visibly identical, and salt fixes it.

```python
# Two users, same password — a fast unsalted hash exposes it; a salt hides it.
h1 = hashlib.sha256(b"hunter2").hexdigest()
h2 = hashlib.sha256(b"hunter2").hexdigest()
print(h1 == h2)                                    # True  <- attacker cracks both at once
salted1 = hashlib.sha256(secrets.token_bytes(16) + b"hunter2").hexdigest()
salted2 = hashlib.sha256(secrets.token_bytes(16) + b"hunter2").hexdigest()
print(salted1 == salted2)                          # False <- but sha256 is still too fast
```

The real hasher uses a slow, memory-hard function and stores everything needed to verify in one string:

```python
ITERATIONS = 600_000                               # the work factor (OWASP 2023 PBKDF2 floor)

def hash_password(password: str, *, pepper: bytes = b"") -> str:
    salt = secrets.token_bytes(16)                 # unique, random, per password
    pre = hmac.new(pepper, password.encode(), hashlib.sha256).digest() if pepper else password.encode()
    dk = hashlib.pbkdf2_hmac("sha256", pre, salt, ITERATIONS, dklen=32)
    return f"pbkdf2-sha256${ITERATIONS}${b64(salt)}${b64(dk)}"          # self-describing

def verify_password(password: str, encoded: str, *, pepper: bytes = b"") -> bool:
    algo, iters, salt_b64, dk_b64 = encoded.split("$")
    salt, expected = ub64(salt_b64), ub64(dk_b64)
    pre = hmac.new(pepper, password.encode(), hashlib.sha256).digest() if pepper else password.encode()
    actual = hashlib.pbkdf2_hmac("sha256", pre, salt, int(iters), dklen=len(expected))
    return hmac.compare_digest(actual, expected)   # constant-time, always
```

Verification re-derives the salt and iteration count *from the stored string* — never from current config — so old hashes keep verifying after you raise the work factor, and a `needs_rehash` check (iterations below today's policy?) drives the silent upgrade. The full script — the salt demonstration, the hasher, verify, `needs_rehash`, a timing comparison of SHA-256 vs scrypt guesses-per-second, and a local k-anonymity demo — is in [`code/password_hashing.py`](code/password_hashing.py). Run it:

```console
$ python3 password_hashing.py
== 1 · UNSALTED FAST HASH LEAKS EQUAL PASSWORDS ==
  user A sha256(hunter2): f52f...
  user B sha256(hunter2): f52f...   equal? True   <- both crack as one
  with per-user salt      equal? False             <- but sha256 is still ~10^10/s

== 2 · A REAL HASH: SLOW, SALTED, SELF-DESCRIBING ==
  stored: pbkdf2-sha256$600000$pFpY7ddpqyIlwrOr83-hgA$q1F8...   (algorithm, iterations, salt, hash)
  verify correct 's3cr3t-passphrase' -> True
  verify wrong   'wrong-guess'       -> False

== 3 · WORK FACTOR = GUESSES PER SECOND (the whole game) ==
  sha256          :    1,237,676 hashes/sec   (a GPU does ~1000x this)
  pbkdf2 (600k)   :         2.04 hashes/sec   (~0.49s/hash, ~605,221x slower per guess, on purpose)

== 4 · TRANSPARENT UPGRADE (rehash on login) ==
  old hash used 100000 iterations; policy now 600000
  needs_rehash? True  -> re-hashed on successful login, no password reset

== 5 · PEPPER: A SECRET THE DB LEAK DOESN'T INCLUDE ==
  verify WITH pepper: True   verify WITHOUT (db-only attacker): False
  db-only attacker is missing the pepper -> cannot begin cracking

== 6 · BREACH CHECK WITHOUT SENDING THE PASSWORD (k-anonymity) ==
  sha1('password') = 5BAA61E4C9B93F3F0682250B6CF8331B7EE68FD8
  send prefix '5BAA6' only; match suffix locally -> breached? True
  sha1('7$Kq!v09-zLm2') prefix '823A3' -> breached? False
```
(Absolute rates vary by machine — the ratio is the point.)

**Section 3** is the argument of the whole lesson in two numbers: the same machine does over a million SHA-256 hashes a second but only ~2 PBKDF2 hashes at 600k iterations — a ~600,000× gap — and a real cracking GPU widens it by another thousandfold (which is why memory-hard Argon2, in *Use It*, is the real target). **Section 4** shows the upgrade path: raise the iteration count, and the next login silently re-hashes. **Section 6** shows the k-anonymity trick end to end — `password`'s SHA-1 prefix reveals it's breached without the server ever seeing the password.

## Use It

You won't ship the scrypt wrapper — you'll ship **Argon2id**, the current default, through the `argon2-cffi` library, which chooses a safe format, generates the salt, encodes the PHC string, and gives you a one-call rehash check:

```python
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

ph = PasswordHasher(memory_cost=65536, time_cost=3, parallelism=4)   # 64 MiB, 3 passes

encoded = ph.hash("correct horse battery staple")
# '$argon2id$v=19$m=65536,t=3,p=4$c29tZXNhbHQ$RdescudvJ...'  <- salt + params embedded

try:
    ph.verify(encoded, submitted_password)         # raises on mismatch; constant-time inside
    if ph.check_needs_rehash(encoded):             # params below current policy?
        encoded = ph.hash(submitted_password)      # transparent upgrade, store the new string
except VerifyMismatchError:
    reject_login()
```

Tune the parameters to *your* hardware: raise `memory_cost` and `time_cost` until a single hash takes ~100–250 ms on your login server, then hold there and revisit yearly. The `check_needs_rehash` call is the whole upgrade story — no migration, no reset, the table strengthens as users log in.

For the ecosystem: **bcrypt** is fine where it's already deployed (mind the 72-byte truncation — pre-hash long inputs with SHA-256 and Base64 if you must), **`passlib`** used to be the standard multi-algorithm wrapper (now lightly maintained; `argon2-cffi` directly is the cleaner path), and every language has the equivalents — Argon2 or bcrypt bindings in Go, Node, Rust, everywhere. The **breach check** is a real, free HTTP call to Have I Been Pwned's range API using the k-anonymity protocol you built by hand — hash with SHA-1, send five hex chars, match suffixes locally — so you can reject known-compromised passwords at registration without ever transmitting them. And the login endpoint still needs [rate limiting](../12-abuse-prevention/) and ideally [MFA](../04-multi-factor-auth-totp-and-passkeys/): storage is only the half of the problem that assumes the file is already stolen.

## Think about it

1. A teammate proposes AES-encrypting passwords instead of hashing them, arguing "then we can detect if two users picked the same password, and we can help them recover it." Give the security reason this is exactly backwards on both counts.
2. Salts are stored in plaintext next to the hashes, and peppers are stored separately from the database. Explain why the salt gains nothing from being secret, while the pepper gains everything — and what the pepper buys you that a bigger work factor doesn't.
3. Your login takes 250 ms because of Argon2, and a product manager asks you to "cache the hash result to make login instant." What are they actually asking you to break, and what's the correct way to make login feel fast without weakening the hash?
4. You raise the Argon2 work factor. Users who never log in again keep their old, weaker hashes forever. Is that a problem? What (if anything) would you do about the dormant accounts, and what's the risk of the obvious fix?
5. An attacker steals your database, which uses per-user salts and Argon2id at 64 MiB. They have a list of the 10,000 most common passwords. Which accounts are still at real risk, which are safe, and what single additional control most reduces the remaining risk?

## Key takeaways

- **Store passwords assuming the database will leak.** Not plaintext (it leaks through logs and analytics too), and not reversible encryption (the key leaks with the data) — a **one-way hash**, because you only ever need to *check* a password, never read it back.
- **A general-purpose hash (MD5, SHA-256) is the wrong tool** precisely because it's fast: a GPU computes ~10¹⁰ a second. Use a hash *built to be slow and memory-hard* — **Argon2id** first, then scrypt, then bcrypt, then PBKDF2 — never SHA with "rounds."
- **Salt and slowness defend against different attacks, and you need both.** A unique per-user **salt** (random, not secret) kills rainbow tables and hides identical passwords; a tuned **work factor** and **memory-hardness** attack the attacker's throughput itself, collapsing 10¹⁰ guesses/second to 10³–10⁴.
- **Store a self-describing PHC string** (algorithm, parameters, salt, hash) and verify in **constant time**. Because the parameters travel with the hash, you **upgrade transparently**: raise the work factor and silently re-hash each password on the user's next login.
- **A pepper** — one secret kept *outside* the database — means a database-only leak is missing an input and can't begin cracking; it's defense in depth on top of salt and slowness, not a substitute.
- **Storage is only half the problem.** It protects the stolen file; the live login endpoint still needs **rate limiting**, **breach checking** (HIBP k-anonymity — check without transmitting the password), and ideally **MFA**, and password *policy* should favor length over complexity and drop forced rotation (NIST 800-63B).

Next: [Multi-Factor Authentication: TOTP & Passkeys](../04-multi-factor-auth-totp-and-passkeys/) — a strong hash protects the password after a breach, but passwords get phished and reused regardless; next you add a second factor the attacker can't steal from your database, and then a first factor (passkeys) there's no shared secret to steal at all.
