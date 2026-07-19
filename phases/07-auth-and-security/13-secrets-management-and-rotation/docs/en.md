# Secrets Management & Rotation

> This entire phase runs on secrets: the JWT signing key, the password pepper, API keys, webhook secrets, the database password, TLS private keys. Every mechanism you built assumed those secrets were, well, *secret* — and the fastest way to undo all of it is to commit one to git. This final lesson is about the keys that guard everything else: where they must never live, where they should, how they're encrypted with **envelope encryption**, and how to **rotate** them so a leaked key doesn't stay valid forever. Secrets management is where a well-built security system quietly succeeds or catastrophically fails.

**Type:** Build
**Languages:** Python
**Prerequisites:** [Cryptographic Building Blocks](../02-cryptographic-building-blocks/) · [API Keys, HMAC Signing & Webhooks](../08-api-keys-hmac-and-webhooks/)
**Time:** ~65 minutes

## The Problem

Count the secrets this phase has already relied on: the HMAC key that signs JWTs ([Lesson 6](../06-jwt-and-token-auth/)), the pepper that protects password hashes ([Lesson 3](../03-password-storage-and-hashing/)), API keys and the webhook signing secret ([Lesson 8](../08-api-keys-hmac-and-webhooks/)), OAuth client secrets ([Lesson 7](../07-oauth2-and-oidc/)), the session-signing key ([Lesson 5](../05-sessions-and-secure-cookies/)), plus the database password and TLS private key underneath it all. Every one is a master key to something important, and every one leaks the same handful of ways:

- **Hardcoded in source.** `SIGNING_KEY = "s3cr3t-key-prod"` in a file that gets committed. This is the classic disaster: the moment it's pushed to a repo — even a private one, even one later made public for five minutes — it's compromised, because automated scanners crawl every public commit on GitHub within *seconds* and attackers harvest cloud keys the same way. Git never forgets, so "delete it in the next commit" doesn't help — the secret is in the history forever, and the only real fix is to rotate it.
- **A `.env` file committed by accident**, or copied into a Docker image layer that ships to a registry.
- **Printed in a log or error**, an env dump, a crash report, an analytics event ([Phase 9 logging hygiene](../../09-logging-monitoring-and-observability/02-structured-logging/)).
- **Passed on the command line**, where any user on the box sees it in `ps`.
- **Never rotated**, so a secret that leaked in 2019 still unlocks production in 2025.
- **Reused everywhere** — one key for signing, encryption, and the database — so a single leak is a *total* compromise.

The through-line is that a secret is only secret while you control every copy of it, and the default developer workflow — put the config next to the code — puts a copy in the one place designed to be shared and remembered forever. Fixing this needs a real system: a place to store secrets **encrypted and access-controlled**, a way to **inject** them into the app at runtime without them touching source or images, the discipline to **rotate** them on a schedule and immediately on a leak, and **detection** for when one escapes anyway. That system — secrets managers, envelope encryption, rotation, and dynamic secrets — is this lesson, and it's the last brick in the phase because it protects every other brick.

## The Concept

### Where secrets must not live — and where they should

Start with the geography, because most secret leaks are a placement mistake, not a cryptographic one:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 340" width="100%" style="max-width:880px" role="img" aria-label="Where secrets leak versus where they should live. On the left, the hall of shame: hardcoded in source code, which gets committed to git and found by scanners in seconds; a dot-env file committed by accident; baked into a Docker image layer; printed in logs or crash reports; passed on the command line where ps reveals it. On the right, the secure path: secrets live in a secrets manager, encrypted, access-controlled, audited, and versioned; they are injected into the app at runtime as environment variables or mounted files; the app holds them only in memory and never writes them to disk, logs, git, or images.">
  <defs>
    <marker id="l13w-ar" markerWidth="10" markerHeight="10" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker>
  </defs>
  <text x="450" y="24" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="15" font-weight="700" fill="currentColor">A secret is only secret while you control every copy of it</text>
  <g fill="none" stroke-linejoin="round" stroke-width="2">
    <rect x="20" y="44" width="424" height="284" rx="12" fill="#d64545" fill-opacity="0.06" stroke="#d64545" stroke-opacity="0.8"/>
    <rect x="460" y="44" width="424" height="284" rx="12" fill="#0fa07f" fill-opacity="0.06" stroke="#0fa07f" stroke-opacity="0.8"/>
  </g>
  <g font-family="'JetBrains Mono', ui-monospace, monospace" fill="currentColor">
    <text x="232" y="70" font-size="12.5" font-weight="700" text-anchor="middle" fill="#d64545">WHERE SECRETS LEAK</text>
    <text x="36" y="98" font-size="9.5">✗ hardcoded in source</text>
    <text x="52" y="114" font-size="8.5" opacity="0.8">→ committed to git → in history FOREVER</text>
    <text x="52" y="128" font-size="8.5" opacity="0.8">→ scanners/attackers find it in seconds</text>
    <text x="36" y="152" font-size="9.5">✗ a .env committed by accident</text>
    <text x="36" y="176" font-size="9.5">✗ baked into a Docker image layer</text>
    <text x="52" y="190" font-size="8.5" opacity="0.8">→ ships to the registry with the secret inside</text>
    <text x="36" y="214" font-size="9.5">✗ printed in a log / crash report</text>
    <text x="36" y="238" font-size="9.5">✗ passed on the command line</text>
    <text x="52" y="252" font-size="8.5" opacity="0.8">→ visible to anyone in `ps`</text>
    <text x="232" y="296" font-size="9" text-anchor="middle" fill="#d64545" opacity="0.9">git delete ≠ fix — the only fix is ROTATE</text>

    <text x="672" y="70" font-size="12.5" font-weight="700" text-anchor="middle" fill="#0fa07f">WHERE THEY SHOULD LIVE</text>
    <text x="672" y="104" font-size="10" text-anchor="middle" font-weight="700">SECRETS MANAGER</text>
    <text x="672" y="122" font-size="9" text-anchor="middle">encrypted · access-controlled</text>
    <text x="672" y="136" font-size="9" text-anchor="middle">audited · versioned</text>
  </g>
  <g fill="none" stroke="#0fa07f" stroke-width="1.7">
    <path d="M672 148 L 672 176" marker-end="url(#l13w-ar)"/>
    <path d="M672 214 L 672 242" marker-end="url(#l13w-ar)"/>
  </g>
  <g font-family="'JetBrains Mono', ui-monospace, monospace" fill="currentColor">
    <text x="672" y="192" font-size="9.5" text-anchor="middle" font-weight="700">injected at RUNTIME</text>
    <text x="672" y="208" font-size="9" text-anchor="middle">env var / mounted file / sidecar</text>
    <text x="672" y="258" font-size="9.5" text-anchor="middle" font-weight="700">held in memory only</text>
    <text x="672" y="274" font-size="9" text-anchor="middle">never on disk, in logs,</text>
    <text x="672" y="288" font-size="9" text-anchor="middle">in git, or in the image</text>
    <text x="672" y="312" font-size="8.5" text-anchor="middle" opacity="0.8">config comes from the environment (12-factor)</text>
  </g>
</svg>
```

The **environment variable** is the baseline improvement over hardcoding — it follows the twelve-factor app's rule that config (and secrets) come from the environment, not the code ([Phase 9, Lesson 2 references twelve-factor logs](../../09-logging-monitoring-and-observability/02-structured-logging/)). It gets the secret out of source control, which is the biggest single win. But env vars have real limits: they're visible to child processes, they often leak into crash dumps and error pages, they're easy to `printenv` in a debug endpoint, and they don't solve *access control, rotation, or audit*. So env vars are how a secret is **injected**, not where it's **managed** — the value in the env var should come *from* a secrets manager at boot, not from a committed file.

### Secrets managers: one place, controlled and audited

A **secrets manager** — HashiCorp **Vault**, **AWS Secrets Manager**, **GCP Secret Manager**, **Azure Key Vault** — is a dedicated service that stores secrets **encrypted at rest** and adds the four things env vars can't: **access control** (which service/identity may read which secret, via IAM), **audit logging** (every access recorded — who read what, when), **versioning** (fetch the current secret, roll back, or run two versions during rotation), and **rotation** (often automated, e.g. rotating a database password on a schedule). The app authenticates to the manager at startup (with a workload identity, not another hardcoded secret — more on that below) and fetches what it needs into memory. This centralization is the point: one auditable, access-controlled place, instead of secrets scattered across configs, images, and CI variables.

### Envelope encryption: how the manager encrypts at scale

How does a secrets manager (or your own database column) encrypt data without the encryption key itself becoming a secret-management problem? The answer is **envelope encryption**, and it's the standard pattern behind every cloud KMS:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 350" width="100%" style="max-width:880px" role="img" aria-label="Envelope encryption. To encrypt data, generate a fresh data encryption key (DEK) and encrypt the data with it, producing ciphertext. Then encrypt (wrap) the DEK with a key encryption key (KEK) that lives inside a KMS and never leaves it, producing a wrapped DEK. Store the ciphertext and the wrapped DEK together. To decrypt, send the wrapped DEK to the KMS, which unwraps it with the KEK and returns the plaintext DEK, then decrypt the ciphertext locally. Benefits: the KEK never leaves the KMS, so a stolen database holds only wrapped DEKs that are useless without KMS access; you can rotate the KEK by re-wrapping DEKs without re-encrypting all the data; and KMS centralizes access control and audit for the one key that matters.">
  <defs>
    <marker id="l13e-ar" markerWidth="10" markerHeight="10" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker>
  </defs>
  <text x="450" y="24" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="15" font-weight="700" fill="currentColor">Envelope encryption — the key that matters (the KEK) never leaves the KMS</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <g fill="none" stroke-linejoin="round" stroke-width="1.8">
      <rect x="30" y="58" width="150" height="50" rx="9" fill="#7f7f7f" fill-opacity="0.10" stroke="currentColor" stroke-opacity="0.5"/>
      <rect x="260" y="58" width="170" height="50" rx="9" fill="#3553ff" fill-opacity="0.11" stroke="#3553ff"/>
      <rect x="30" y="150" width="150" height="50" rx="9" fill="#e0930f" fill-opacity="0.12" stroke="#e0930f"/>
      <rect x="260" y="150" width="170" height="50" rx="9" fill="#3553ff" fill-opacity="0.08" stroke="#3553ff" stroke-opacity="0.7"/>
      <rect x="560" y="98" width="310" height="120" rx="11" fill="#0fa07f" fill-opacity="0.08" stroke="#0fa07f"/>
    </g>
    <text x="105" y="80" font-size="9.5" text-anchor="middle">data</text>
    <text x="105" y="94" font-size="8" text-anchor="middle" opacity="0.7">(a secret / a row)</text>
    <text x="345" y="80" font-size="9" text-anchor="middle">encrypt with DEK</text>
    <text x="345" y="94" font-size="8" text-anchor="middle" opacity="0.7">→ ciphertext (stored)</text>
    <text x="105" y="172" font-size="9.5" text-anchor="middle" fill="#e0930f">DEK</text>
    <text x="105" y="186" font-size="8" text-anchor="middle" opacity="0.7">fresh, per-data</text>
    <text x="345" y="172" font-size="9" text-anchor="middle">wrap with KEK</text>
    <text x="345" y="186" font-size="8" text-anchor="middle" opacity="0.7">→ wrapped DEK (stored)</text>
    <text x="715" y="122" font-size="11" text-anchor="middle" font-weight="700" fill="#0fa07f">KMS</text>
    <text x="715" y="142" font-size="9" text-anchor="middle">holds the KEK — it NEVER leaves</text>
    <text x="715" y="160" font-size="9" text-anchor="middle">wrap / unwrap happens here</text>
    <text x="715" y="182" font-size="9" text-anchor="middle">access-controlled + audited</text>
    <text x="715" y="204" font-size="8.5" text-anchor="middle" opacity="0.75">to decrypt: send wrapped DEK → get DEK back</text>
  </g>
  <g fill="none" stroke="currentColor" stroke-width="1.6">
    <path d="M180 83 L 256 83" marker-end="url(#l13e-ar)"/>
    <path d="M180 175 L 256 175" marker-end="url(#l13e-ar)"/>
    <path d="M430 175 L 556 165" marker-end="url(#l13e-ar)"/>
  </g>
  <text x="450" y="248" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="10.5" fill="currentColor" opacity="0.9">Store together: ciphertext + wrapped DEK. A stolen database holds only WRAPPED DEKs — useless without KMS access.</text>
  <text x="450" y="272" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="10.5" fill="currentColor" opacity="0.9">Rotate the KEK by re-wrapping the small DEKs — no need to re-encrypt terabytes of data. This is why every KMS works this way.</text>
  <text x="450" y="296" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="10" fill="currentColor" opacity="0.75">One key, one purpose (Lesson 2): the DEK encrypts data; the KEK only wraps DEKs. A leaked DEK exposes one blob, not everything.</text>
</svg>
```

The mechanics: to encrypt, generate a fresh **DEK** (Data Encryption Key), encrypt the data with it locally, then ask the KMS to **wrap** (encrypt) the DEK with a **KEK** (Key Encryption Key) that lives inside the KMS and *never leaves it*; store the ciphertext and the wrapped DEK together. To decrypt, send the wrapped DEK to the KMS, which unwraps it and returns the plaintext DEK, and you decrypt locally. Three properties make this the universal pattern: the **KEK never leaves the KMS** (so a stolen database holds only wrapped DEKs, useless without KMS access), you can **rotate the KEK cheaply** by re-wrapping the small DEKs instead of re-encrypting terabytes, and the KMS is the single point of **access control and audit** for the one key that matters. It's the *one-key-one-purpose* rule from [Lesson 2](../02-cryptographic-building-blocks/) at architecture scale.

### Rotation: because leaks are inevitable

The uncomfortable premise of this whole lesson is that secrets **will** leak — through a mistaken commit, a compromised dependency, a departing employee, a breached vendor — so the question is not *if* but *how long a leaked secret stays useful*. **Rotation** — replacing a secret with a new one on a regular schedule and immediately on any suspected leak — is what bounds that window. The trick is doing it **without downtime**, which requires a period where *both* the old and new secret are valid:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 330" width="100%" style="max-width:880px" role="img" aria-label="Key rotation with an overlap window, and the leak response. Rotation timeline: at first only key version 1 is active and used for both signing and verifying. Then version 2 is introduced; during the overlap window the system signs with version 2 but verifies with either version 1 or version 2, so tokens signed with the old key still work. After the overlap, version 1 is retired and only version 2 remains; tokens signed with version 1 no longer verify but by then they have expired naturally. Leak response: on detecting a leak, revoke first — immediately disable the leaked key — then rotate in a new one, then investigate. Revoke before rotate because the leaked key is live right now.">
  <text x="450" y="24" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="15" font-weight="700" fill="currentColor">Rotate with an overlap window — no downtime, bounded exposure</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <g fill="none" stroke-linejoin="round" stroke-width="1.8">
      <rect x="30" y="58" width="250" height="66" rx="10" fill="#3553ff" fill-opacity="0.10" stroke="#3553ff"/>
      <rect x="325" y="58" width="250" height="66" rx="10" fill="#7c5cff" fill-opacity="0.11" stroke="#7c5cff"/>
      <rect x="620" y="58" width="250" height="66" rx="10" fill="#0fa07f" fill-opacity="0.11" stroke="#0fa07f"/>
    </g>
    <text x="155" y="80" font-size="10.5" font-weight="700" text-anchor="middle" fill="#3553ff">① only v1</text>
    <text x="155" y="100" font-size="8.5" text-anchor="middle">sign with v1</text>
    <text x="155" y="114" font-size="8.5" text-anchor="middle">verify with v1</text>
    <text x="450" y="80" font-size="10.5" font-weight="700" text-anchor="middle" fill="#7c5cff">② overlap (v1 + v2)</text>
    <text x="450" y="100" font-size="8.5" text-anchor="middle">sign with v2</text>
    <text x="450" y="114" font-size="8.5" text-anchor="middle">verify with v1 OR v2 — old tokens still work</text>
    <text x="745" y="80" font-size="10.5" font-weight="700" text-anchor="middle" fill="#0fa07f">③ retire v1</text>
    <text x="745" y="100" font-size="8.5" text-anchor="middle">sign + verify v2 only</text>
    <text x="745" y="114" font-size="8.5" text-anchor="middle">v1 tokens already expired</text>
  </g>
  <g fill="none" stroke="currentColor" stroke-width="1.6">
    <path d="M280 91 L 322 91" marker-end="url(#l13e-ar)"/>
    <path d="M575 91 L 617 91" marker-end="url(#l13e-ar)"/>
  </g>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <rect x="30" y="150" width="840" height="118" rx="10" fill="#d64545" fill-opacity="0.06" stroke="#d64545" stroke-opacity="0.6"/>
    <text x="44" y="172" font-size="11" font-weight="700" fill="#d64545">Leak response: REVOKE first, then rotate</text>
    <text x="44" y="196" font-size="10">① <tspan font-weight="700">Revoke</tspan> — immediately disable the leaked key/credential (the leaked secret is live RIGHT NOW; every minute is exposure).</text>
    <text x="44" y="218" font-size="10">② <tspan font-weight="700">Rotate</tspan> — issue a fresh secret and deploy it. ③ <tspan font-weight="700">Investigate</tspan> — how did it leak, what did it touch, who accessed it (audit log).</text>
    <text x="44" y="242" font-size="10" opacity="0.85">Short-lived secrets shrink this to nothing: a credential that expires in an hour is barely worth stealing.</text>
    <text x="44" y="260" font-size="9.5" opacity="0.75">Versioning makes this routine: the key is `{version, value}`, verify accepts a set of active versions, and retiring a version is one config change.</text>
  </g>
</svg>
```

Rotation is easiest when secrets are **versioned**: a signing key is `{version, value}`, you always *sign* with the newest version, and you *verify* against the set of currently-active versions. Introducing a new version, running an overlap, and retiring the old one is then just membership changes in that set — which is exactly what you'll build. For JWTs this maps onto the `kid` (key ID) header and JWKS ([Lesson 6](../06-jwt-and-token-auth/)): the token names which key signed it, and verifiers keep several active public keys.

### Dynamic secrets and short-lived credentials: the endgame

The most advanced move is to stop having long-lived secrets at all. **Dynamic secrets** (a Vault specialty) are generated **on demand** with a short **lease**: when your app needs database access, Vault creates a brand-new database user valid for, say, one hour, hands it over, and deletes it when the lease expires. There's no static database password to leak, rotation is automatic (every lease is a new credential), and a stolen credential is worthless within the hour. The same idea underlies **cloud workload identity** — **IAM roles**, GCP/Azure workload identity, Kubernetes service-account tokens — where a running workload proves *what it is* to the platform and receives **short-lived, auto-rotated** credentials, so there's no API key sitting in an env var at all. That last point also solves the bootstrapping puzzle ("how does the app authenticate to the secrets manager without a secret?"): the platform vouches for the workload's identity, and short-lived credentials flow from there. Long-lived static secrets are the thing you're trying to eliminate; short-lived, identity-derived credentials are where the field is going.

## Build It

Standard library only — `hmac`, `hashlib`, `secrets`, `os`, `re` — to build the *management* logic (the encryption primitives were [Lesson 2](../02-cryptographic-building-blocks/); real envelope encryption is the `cryptography`/KMS territory in *Use It*): load secrets from the environment (never code) and fail closed if missing, scan a code string for leaked secrets the way GitHub's scanner does, and — the centerpiece — rotate a signing key through a versioned keyring with an overlap window.

Secrets come from the environment, and a missing one fails closed rather than defaulting to something insecure:

```python
def load_secret(name: str) -> str:
    val = os.environ.get(name)
    if not val:
        raise RuntimeError(f"missing secret {name} — refusing to start")   # fail closed, no default
    return val
```

The keyring is the heart of rotation: always sign with the current version, verify against every active version, and rotation is just adding a new current and later retiring the old:

```python
class KeyRing:
    def __init__(self):
        self.keys: dict[int, bytes] = {}     # version -> key
        self.current = 0

    def add(self, version: int, key: bytes):        # introduce a new version (starts the overlap)
        self.keys[version] = key
        self.current = version

    def retire(self, version: int):                 # end the overlap — old tokens now fail
        self.keys.pop(version, None)

    def sign(self, msg: bytes) -> tuple[int, str]:  # always sign with the CURRENT version
        tag = hmac.new(self.keys[self.current], msg, hashlib.sha256).hexdigest()
        return self.current, tag

    def verify(self, msg: bytes, version: int, tag: str) -> bool:
        key = self.keys.get(version)                # verify against whichever ACTIVE version signed it
        if key is None:
            return False                            # retired/unknown version → reject
        expected = hmac.new(key, msg, hashlib.sha256).hexdigest()
        return hmac.compare_digest(tag, expected)   # constant-time
```

The full script — env-based loading, a secret scanner catching an AWS key and an `sk_live_` key in source, and the rotation lifecycle (sign with v1, introduce v2, verify both during overlap, retire v1 and watch old tokens fail) — is in [`code/secrets_rotation.py`](code/secrets_rotation.py). Run it:

```console
$ python3 secrets_rotation.py
== 1 · SECRETS FROM THE ENVIRONMENT, FAIL CLOSED ==
  load_secret('SIGNING_KEY')     -> loaded from env (len 32)
  load_secret('MISSING_SECRET')  -> RuntimeError: missing secret MISSING_SECRET — refusing to start

== 2 · SECRET SCANNING (catch leaks before they're committed) ==
  scanning a source file for hardcoded secrets:
    line 3: AWS access key   AKIAIOSFODNN7EXAMPLE
    line 4: Stripe live key   sk_live_EXAMPLE-not-a-real-key
    line 7: high-entropy string assigned to a *_KEY / *_SECRET / *_TOKEN name
  -> 3 findings: block the commit, rotate anything real

== 3 · KEY ROTATION WITH AN OVERLAP WINDOW ==
  v1 active. token signed with v1.
  verify (only v1)          -> True
  introduce v2 (overlap): sign new tokens with v2
  old v1 token verifies?    -> True    (overlap: both active)
  new v2 token verifies?    -> True
  retire v1.
  old v1 token verifies?    -> False   (v1 retired — but it had already expired)
  new v2 token verifies?    -> True    (rotation complete, no downtime)
```

**Section 1** shows the baseline: secrets come from the environment, and an absent one *refuses to start* rather than silently using an insecure default. **Section 2** is the safety net — a scanner that recognizes an AWS `AKIA` key, a Stripe `sk_live_` key, and a high-entropy value assigned to a `*_KEY`/`*_SECRET` name, exactly the patterns GitHub and GitGuardian flag. **Section 3** is the rotation lifecycle end to end: a token signed with v1 keeps verifying while v2 is introduced (the overlap), and stops the moment v1 is retired — no downtime, and a bounded window in which any leaked v1 key is useful.

## Use It

In production you assemble managed services, and the goal is that **no long-lived secret ever sits in your source, your image, or your CI config**. Use a **secrets manager** — **HashiCorp Vault**, **AWS Secrets Manager**, **GCP Secret Manager**, **Azure Key Vault** — as the store, and fetch secrets at boot into the environment or a mounted file (a Vault sidecar/agent, the External Secrets Operator on Kubernetes, or the cloud SDK). For **encryption**, use a **cloud KMS** (AWS KMS, GCP KMS, Azure Key Vault) with the envelope pattern — the SDK's `GenerateDataKey`/`Decrypt` calls implement exactly the DEK/KEK dance above, and libraries like `cryptography`'s `AESGCM` or AWS's **Encryption SDK** handle the local encrypt/decrypt. For **rotation**, prefer the manager's automated rotation for database and service credentials, and for signing keys use versioning (`kid` + JWKS for JWTs). For the strongest posture, adopt **dynamic secrets** (Vault-generated, short-lived DB creds) and **workload identity** (IAM roles, GKE/EKS/AKS workload identity) so the app authenticates by *what it is* and receives short-lived credentials — eliminating static keys and the bootstrap problem in one move.

Two operational must-haves complete the picture. **Secret scanning**: turn on GitHub secret scanning (and push protection), or GitGuardian/`trufflehog`, so a hardcoded secret is caught before or immediately after it's committed — and treat any hit as a real leak (revoke-then-rotate, because git history is forever). And **logging hygiene** ([Phase 9](../../09-logging-monitoring-and-observability/02-structured-logging/)): redact secrets from logs, errors, and traces, and keep them out of debug endpoints and env dumps. The rules to carry out of this final lesson: **no secrets in source, git, or images; store them in a manager with access control and audit; encrypt with envelope encryption so the master key stays in a KMS; rotate on a schedule and immediately on leak, with an overlap window for zero downtime; prefer short-lived, identity-derived credentials over long-lived keys; and scan for leaks continuously** — because every mechanism in this phase depends on the secret staying secret, and this is how you keep it that way.

## Think about it

1. A developer commits an API key, notices immediately, and pushes a second commit removing it. Explain why the key must still be considered compromised, what "the fix" actually is, and how short-lived credentials would have changed the severity.
2. Environment variables are a big improvement over hardcoding secrets, yet they're described as "how a secret is injected, not where it's managed." Give three concrete limitations of env vars that a secrets manager addresses.
3. Walk through envelope encryption for encrypting a million database rows. Why encrypt each row's data with a DEK and only wrap the DEKs with the KEK, rather than encrypting every row directly with the KEK? What does this let you do cheaply that direct encryption wouldn't?
4. Zero-downtime key rotation requires an overlap window where both the old and new key verify. Explain what breaks if you skip the overlap and just swap the key, and why you *sign* with only the new key during the overlap but *verify* with both.
5. "Dynamic secrets" and "workload identity" both aim to eliminate long-lived secrets. Explain how each removes a static credential, and how workload identity solves the bootstrapping problem of "how does the app authenticate to the secrets manager without already having a secret?"

## Key takeaways

- **This phase runs on secrets, and they all leak the same ways** — hardcoded in source (→ git history forever → found by scanners in seconds), committed `.env` files, baked into images, printed in logs, or passed on the CLI. A secret is only secret while you control every copy, and "delete it in the next commit" is not a fix — **rotation** is.
- **Env vars are the injection baseline** (twelve-factor: config from the environment, out of source control), but they don't provide access control, rotation, or audit. The value should come *from* a **secrets manager** (Vault, AWS/GCP/Azure) at runtime, not from a committed file.
- **A secrets manager centralizes storage with encryption at rest, access control (IAM), audit logging, versioning, and rotation** — the four things env vars can't give you.
- **Envelope encryption is the universal KMS pattern**: encrypt data with a fresh **DEK**, wrap the DEK with a **KEK** that never leaves the **KMS**, store ciphertext + wrapped DEK together. A stolen database holds only wrapped DEKs (useless without KMS), and you rotate the KEK by re-wrapping small DEKs instead of re-encrypting everything.
- **Rotate on a schedule and immediately on leak, with an overlap window for zero downtime**: version keys, always sign with the current version, verify against all active versions, and retire old ones after the overlap. On a leak, **revoke first, then rotate, then investigate** — the leaked secret is live right now.
- **The endgame is no long-lived secrets:** **dynamic secrets** (short-lived, auto-generated DB creds) and **workload identity** (IAM roles / short-lived, identity-derived credentials) make a stolen secret worthless within the hour and solve the bootstrap problem. Back it all with **continuous secret scanning** and **logging hygiene** — the keys that protect everything must not become the thing that leaks.

You've reached the end of Phase 7. You can now answer the phase's opening questions in full — *who are you* (passwords, MFA, sessions, tokens, OAuth, keys), *what may you do* (RBAC/ABAC/ReBAC, enforced at the object level), and *how do we not leak it* (crypto done right, the browser boundary defended, injection closed, abuse priced out, and the secrets that guard it all managed and rotated). Next comes **Phase 8: Concurrency and Performance** — doing many things at once without corrupting any of them.
