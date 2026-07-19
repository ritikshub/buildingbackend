# TLS, Certificates & mTLS

> TCP delivers your bytes reliably — but in the clear, to whoever answers. TLS wraps that same stream so it is private, tamper-evident, and provably going to the server you meant.

**Type:** Build
**Languages:** Python
**Prerequisites:** Lessons 05, 08–09 — TCP and HTTP. You should know that TCP (Transmission Control Protocol) gives you a reliable byte stream, and that HTTP (HyperText Transfer Protocol) is text sent over it. HTTPS is simply HTTP over TLS.
**Time:** ~90 minutes

## The Problem

You built a TCP echo server in Lesson 05 and spoke HTTP over it in Lessons 08–09.
Both work — and both are wide open. Every byte crosses the network as plaintext,
so anyone on the path (the coffee-shop Wi-Fi, a compromised router, your ISP) can
do three things:

- **Read it.** Your password, your session cookie, the JSON body — all visible.
- **Change it.** Flip a `0` to a `1`, inject a `<script>` tag, rewrite the amount on a transfer. The receiver has no way to notice.
- **Impersonate the server.** You typed `bank.example`, but who actually answered? Plain TCP will happily connect you to an attacker who says "sure, I'm the bank."

Reliable delivery to the *wrong* party, in the *clear*, is worse than no
delivery at all. What we need is a layer that sits between TCP and the
application and fixes all three problems at once — without the application
having to think about it. That layer is **TLS** (Transport Layer Security), and
by the end of this lesson you will have opened an encrypted channel by hand,
read back the exact version, cipher, and certificate that secured it, and made
*both* ends prove who they are.

## The Concept

TLS is a protocol that turns a plain TCP connection into a secure one. The
current version is **TLS 1.3**, defined by **RFC 8446** (RFC = Request for
Comments, the IETF's standards series). It runs *on top of* TCP: TCP moves the
bytes, TLS decides what those bytes mean and keeps them safe.

### The three guarantees: confidentiality, integrity, authentication

Every secure channel TLS builds gives you exactly three properties. Keep these
straight and the rest of the protocol is just machinery that delivers them:

| Guarantee | What it means | What it stops |
|---|---|---|
| **Confidentiality** | The data is *encrypted*; only the two endpoints can read it. | Eavesdropping (reading your traffic). |
| **Integrity** | Any change to the bytes in flight is *detected* and the connection fails. | Tampering (silently editing your traffic). |
| **Authentication** | The server *proves its identity* with a certificate before you trust it. | Impersonation (a fake server in the middle). |

Confidentiality and integrity protect the *bytes*; authentication protects your
choice of *who you are talking to*. Encryption without authentication is a
locked conversation with a stranger who might be the attacker — which is why the
certificate (below) is not optional.

### The TLS handshake

Before any application data moves, the two sides run a **handshake**: a short
negotiation that agrees on a TLS version and a **cipher suite** (the exact set of
cryptographic algorithms to use), verifies the server's certificate, and
establishes a shared secret key. In TLS 1.3 this takes a single round trip:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 474" width="100%" style="max-width:780px" role="img" aria-label="TLS 1.3 handshake sequence between Client and Server, running on top of an already-established TCP connection. The client sends ClientHello with its supported versions, cipher suites, and key share. The server replies ServerHello with the chosen version and cipher and its own key share, then sends Certificate and CertificateVerify to prove its identity, then Finished. Both sides now derive the same symmetric key. The client sends Finished. From here encrypted application data flows both ways: the client sends an encrypted GET slash and the server returns an encrypted 200 OK.">
  <defs>
    <marker id="l10a-ar" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker>
    <marker id="l10a-arg" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#0fa07f"/></marker>
  </defs>
  <text x="400" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14" font-weight="700" fill="currentColor">One round trip: negotiate, authenticate, then everything is encrypted</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <!-- actor headers -->
    <g stroke-width="1.7" stroke-linejoin="round">
      <rect x="130" y="42" width="140" height="30" rx="8" fill="#3553ff" fill-opacity="0.12" stroke="#3553ff"/>
      <rect x="530" y="42" width="140" height="30" rx="8" fill="#0fa07f" fill-opacity="0.12" stroke="#0fa07f"/>
    </g>
    <text x="200" y="61" text-anchor="middle" font-size="11.5" font-weight="700" fill="#3553ff">Client</text>
    <text x="600" y="61" text-anchor="middle" font-size="11.5" font-weight="700" fill="#0fa07f">Server</text>
    <!-- lifelines -->
    <g stroke-width="1.3" stroke-dasharray="4 5">
      <path d="M200 72 L200 420" stroke="#3553ff" stroke-opacity="0.35"/>
      <path d="M600 72 L600 420" stroke="#0fa07f" stroke-opacity="0.35"/>
    </g>
    <!-- note band 1: TCP -->
    <rect x="110" y="84" width="580" height="22" rx="6" fill="#7f7f7f" fill-opacity="0.1" stroke="currentColor" stroke-opacity="0.25" stroke-width="1"/>
    <text x="400" y="99" text-anchor="middle" font-size="9" fill="currentColor" opacity="0.8">Running on top of an established TCP connection</text>
    <!-- handshake arrows -->
    <g fill="none" stroke="currentColor" stroke-width="1.6">
      <path d="M206 136 L594 136" marker-end="url(#l10a-ar)"/>
      <path d="M594 170 L206 170" marker-end="url(#l10a-ar)"/>
      <path d="M594 204 L206 204" marker-end="url(#l10a-ar)"/>
      <path d="M594 238 L206 238" marker-end="url(#l10a-ar)"/>
      <path d="M206 304 L594 304" marker-end="url(#l10a-ar)"/>
    </g>
    <!-- handshake labels -->
    <g fill="currentColor" text-anchor="middle" font-size="9.5">
      <text x="400" y="130"><tspan font-weight="700">ClientHello</tspan>&#8195;supported versions, cipher suites, client key share</text>
      <text x="400" y="164"><tspan font-weight="700">ServerHello</tspan>&#8195;chosen version + cipher, server key share</text>
      <text x="400" y="198"><tspan font-weight="700">Certificate + CertificateVerify</tspan>&#8195;"here is my identity, signed"</text>
      <text x="400" y="232"><tspan font-weight="700">Finished</tspan>&#8195;handshake is authenticated</text>
      <text x="400" y="298"><tspan font-weight="700">Finished</tspan></text>
    </g>
    <!-- note band 2: shared key -->
    <rect x="110" y="252" width="580" height="22" rx="6" fill="#7f7f7f" fill-opacity="0.1" stroke="currentColor" stroke-opacity="0.25" stroke-width="1"/>
    <text x="400" y="267" text-anchor="middle" font-size="9" fill="currentColor" opacity="0.85">Both sides now derive the SAME symmetric key</text>
    <!-- note band 3: encrypted channel up (green) -->
    <rect x="110" y="318" width="580" height="22" rx="6" fill="#0fa07f" fill-opacity="0.12" stroke="#0fa07f" stroke-opacity="0.6" stroke-width="1"/>
    <text x="400" y="333" text-anchor="middle" font-size="9" fill="currentColor" opacity="0.9">Encrypted application data flows both ways</text>
    <!-- encrypted data arrows (green) -->
    <g fill="none" stroke="#0fa07f" stroke-width="1.6">
      <path d="M206 370 L594 370" marker-end="url(#l10a-arg)"/>
      <path d="M594 404 L206 404" marker-end="url(#l10a-arg)"/>
    </g>
    <g text-anchor="middle" font-size="9.5" font-weight="600" fill="#0fa07f">
      <text x="400" y="364">GET /&#8195;(encrypted)</text>
      <text x="400" y="398">200 OK&#8195;(encrypted)</text>
    </g>
    <!-- takeaway -->
    <text x="400" y="442" text-anchor="middle" font-size="10" fill="currentColor" opacity="0.9">Negotiation and the certificate check happen in the clear; the moment keys are derived,</text>
    <text x="400" y="459" text-anchor="middle" font-size="10" fill="currentColor" opacity="0.9">every byte — including the HTTP request and response — is encrypted.</text>
  </g>
</svg>
```

The **ClientHello** offers what the client can do; the **ServerHello** picks
from that list. Crucially, each side also sends a **key share** — a public value
that lets both independently compute the *same* secret without ever sending the
secret itself. The server then proves its identity with its **certificate**, and
from that point on every byte is encrypted.

### Symmetric vs. asymmetric keys

TLS uses two kinds of cryptography, and the handshake is a hand-off from one to
the other:

- **Asymmetric (public-key) cryptography** uses a *pair* of keys: a **public
  key** anyone can have and a **private key** the owner keeps secret. What one
  key locks, only the other unlocks. It is secure but *slow*. TLS uses it only
  during the handshake — to agree on a shared secret and to let the server prove
  it holds the private key matching its certificate.
- **Symmetric cryptography** uses *one* shared key for both encryption and
  decryption. It is *fast*, so all the actual application data uses it.

The handshake's whole job is to bootstrap a shared **symmetric** key using
**asymmetric** math, so the bulk transfer can be fast *and* private. You get the
security of public-key crypto for setup and the speed of symmetric crypto for
the payload.

### Certificates and X.509

A **certificate** is a small signed document that binds a **public key** to a
**name** (like `bank.example`). Its format is **X.509** (RFC 5280). A certificate
says, in effect: *"the entity named `bank.example` owns this public key — and I,
the signer, vouch for that."* The signer is a **CA** (Certificate Authority): an
organization trusted to verify identities and sign certificates.

During the handshake the server sends its certificate and then proves, using the
matching *private* key, that it truly owns the public key inside — so an attacker
who merely *copies* a certificate still cannot use it. A certificate carries at
least:

| Field | Purpose |
|---|---|
| **Subject** | The name this certificate is for (e.g. Common Name `localhost`, or Subject Alternative Names). |
| **Public key** | The key the subject owns. |
| **Issuer** | The CA that signed this certificate. |
| **Validity** | "Not before" / "not after" dates — certificates expire. |
| **Signature** | The issuer's cryptographic signature over all of the above. |

Our demo uses a **self-signed** certificate: the issuer *is* the subject, so it
vouches only for itself. That is fine for a localhost demo but useless on the
public internet, because no one else already trusts it.

### The chain of trust

You cannot possibly know every server's public key in advance. The fix is a
**chain of trust**, part of a **PKI** (Public Key Infrastructure). Your operating
system and browser ship with a built-in list of a few hundred **root CAs** they
trust absolutely. Root keys are precious, so roots rarely sign server
certificates directly — instead a root signs an **intermediate CA**, and the
intermediate signs the server's **leaf** certificate:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 760 372" width="100%" style="max-width:740px" role="img" aria-label="A certificate chain of trust drawn as a vertical three-node chain. The Root CA, which lives in the OS and browser trust store, signs the Intermediate CA. The Intermediate CA, signed by the root, signs the Leaf certificate — the server's identity, for example bank.example. A dashed arrow curves back up the right side from the leaf to the root, showing that the client verifies each signature up to a trusted root.">
  <defs>
    <marker id="l10b-ar" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker>
    <marker id="l10b-ard" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor" fill-opacity="0.55"/></marker>
  </defs>
  <text x="380" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14" font-weight="700" fill="currentColor">A chain of trust: each certificate is signed by the one above it</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <!-- signs arrows (down) -->
    <g fill="none" stroke="currentColor" stroke-width="1.7">
      <path d="M280 102 L280 144" marker-end="url(#l10b-ar)"/>
      <path d="M280 198 L280 240" marker-end="url(#l10b-ar)"/>
    </g>
    <g fill="currentColor" text-anchor="start" font-size="9.5" font-weight="600" opacity="0.85">
      <text x="292" y="127">signs</text>
      <text x="292" y="223">signs</text>
    </g>
    <!-- verify arrow (dashed, up the right side) -->
    <path d="M430 268 C 550 246, 550 110, 432 84" fill="none" stroke="currentColor" stroke-width="1.5" stroke-opacity="0.55" stroke-dasharray="5 4" marker-end="url(#l10b-ard)"/>
    <g fill="currentColor" text-anchor="start" font-size="8" opacity="0.75">
      <text x="560" y="163">client verifies each</text>
      <text x="560" y="177">signature up to a</text>
      <text x="560" y="191">trusted root</text>
    </g>
    <!-- nodes -->
    <g stroke-width="1.8" stroke-linejoin="round">
      <rect x="130" y="50"  width="300" height="52" rx="12" fill="#0fa07f" fill-opacity="0.12" stroke="#0fa07f"/>
      <rect x="130" y="146" width="300" height="52" rx="12" fill="#7f7f7f" fill-opacity="0.12" stroke="#7f7f7f"/>
      <rect x="130" y="242" width="300" height="52" rx="12" fill="#3553ff" fill-opacity="0.11" stroke="#3553ff"/>
    </g>
    <g text-anchor="middle">
      <text x="280" y="74"  font-size="12.5" font-weight="700" fill="#0fa07f">Root CA</text>
      <text x="280" y="90"  font-size="8" fill="currentColor" opacity="0.7">in the OS / browser trust store</text>
      <text x="280" y="170" font-size="12.5" font-weight="700" fill="currentColor">Intermediate CA</text>
      <text x="280" y="186" font-size="8" fill="currentColor" opacity="0.7">signed by the root</text>
      <text x="280" y="266" font-size="12.5" font-weight="700" fill="#3553ff">Leaf certificate</text>
      <text x="280" y="282" font-size="8" fill="currentColor" opacity="0.7">the server's identity — bank.example</text>
    </g>
    <!-- takeaway -->
    <text x="380" y="336" text-anchor="middle" font-size="10" fill="currentColor" opacity="0.9">Trust flows down by signing; verification climbs back up — each link</text>
    <text x="380" y="353" text-anchor="middle" font-size="10" fill="currentColor" opacity="0.9">checked until it reaches a root already in the trust store.</text>
  </g>
</svg>
```

To validate a server, the client walks the chain *upward*: the leaf must be
signed by the intermediate, the intermediate by the root, and the root must be
one it already trusts. If every signature checks out and the root is trusted, the
identity is proven. Break any link — an expired cert, a wrong name, an untrusted
root — and the connection is refused. That refusal is the whole point of
authentication working.

### HTTPS and SNI

**HTTPS** (HTTP Secure) is nothing more than **HTTP inside TLS**. The browser
opens a TCP connection to port **443** (the IANA-assigned port for HTTPS, versus
80 for plain HTTP), runs the TLS handshake, and then sends the ordinary HTTP
request *inside* the encrypted channel. The `https://` URI scheme is defined by
RFC 9110. Everything you learned about HTTP still applies — it is just wrapped.

One complication: a single IP address often hosts many sites. Since the TLS
handshake happens *before* the HTTP request (which carries the `Host:` header),
how does the server know *which* certificate to present? The answer is **SNI**
(Server Name Indication, RFC 6066): the client puts the hostname it wants right
in the ClientHello, so the server can select the matching certificate before the
handshake completes.

### mTLS: mutual authentication

In ordinary TLS only the **server** presents a certificate — the client verifies
the server, but the server has no cryptographic proof of who the client is (it
relies on a password or token *inside* the channel). **mTLS** (mutual TLS)
closes that gap: the **client presents a certificate too**, so *both* sides
authenticate before any data flows. RFC 8446 §4.4.2 defines the client
certificate step.

You would not want a browser prompting every human for a certificate, so mTLS is
most common for **service-to-service** traffic: microservice A and microservice B
each hold a certificate, and each refuses to talk to anyone whose certificate is
not signed by a CA it trusts. Identity is enforced by the transport itself, not
bolted on above it.

## Build It

The full implementations are in [`code/`](../code/). Each file starts a TLS
server on a background thread, runs a client against it on localhost, prints the
exchange, and exits — using only Python's standard-library [`ssl`](https://docs.python.org/3/library/ssl.html)
module. A throwaway self-signed certificate ships alongside them as
`code/cert.pem` and `code/key.pem` (Common Name `localhost`).

### One server certificate — `tls_echo.py`

[`code/tls_echo.py`](../code/tls_echo.py). The server gives itself an identity
with `load_cert_chain`, then `wrap_socket` runs the handshake on top of an
already-accepted TCP connection:

```python
import ssl

# Server: present a certificate + prove ownership with the private key.
context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
context.load_cert_chain(certfile=CERT, keyfile=KEY)
tls_conn = context.wrap_socket(raw_conn, server_side=True)  # runs the handshake
```

The client is where the security decision lives. Because our certificate is
self-signed, real verification would (correctly) fail, so the demo turns it off —
and the code says loudly why, and that you must never do this in production:

```python
# DEMO ONLY. CERT_NONE = "trust any certificate", which defeats authentication
# and invites a man-in-the-middle attack. Real clients keep the defaults
# (check_hostname=True, CERT_REQUIRED) so a forged certificate is rejected.
context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
context.check_hostname = False        # must clear this BEFORE setting CERT_NONE
context.verify_mode = ssl.CERT_NONE
```

After the handshake the client reports exactly what it negotiated — the version,
the cipher suite, and the certificate the server presented:

```python
print(tls.version())                       # e.g. TLSv1.3 or TLSv1.2
print(tls.cipher()[0])                      # the negotiated cipher suite
der = tls.getpeercert(binary_form=True)     # the server's cert, raw DER bytes
```

Run it:

```bash
python3 code/tls_echo.py
```

```console
[client] negotiated TLS version : TLSv1.3
[client] negotiated cipher suite: TLS_AES_256_GCM_SHA384 (256-bit)
[client] server presented a 680-byte certificate (matches cert.pem)
[client] certificate subject    : commonName=localhost
```

The exact version and cipher you see depend on what your Python's underlying
crypto library supports — a modern OpenSSL negotiates **TLS 1.3**, while an older
build (such as the LibreSSL that ships on some macOS systems) caps at **TLS 1.2**.
Either way the `ssl` module negotiates the best both sides offer, which is
precisely the ClientHello/ServerHello negotiation from the diagram. The
certificate arrives as **DER** (Distinguished Encoding Rules, the binary
encoding of X.509); `cert.pem` on disk is the same bytes in **PEM** (a
base64-wrapped text form) — the code confirms the two match.

### Both sides authenticate — `mtls_echo.py`

[`code/mtls_echo.py`](../code/mtls_echo.py) upgrades the demo to mTLS. The
difference is two settings on *each* side: present a certificate, and require one
from the peer. Because our cert is self-signed, it doubles as its own CA, so both
ends trust it as the root that must have signed whatever the peer presents:

```python
# Server now REQUIRES a client certificate signed by a CA it trusts.
context.verify_mode = ssl.CERT_REQUIRED
context.load_verify_locations(cafile=CA)     # trust this CA for client certs

# Client now PRESENTS its own certificate, and still verifies the server's.
context.load_cert_chain(certfile=CERT, keyfile=KEY)   # the client's identity
context.load_verify_locations(cafile=CA)
context.verify_mode = ssl.CERT_REQUIRED
```

Run it:

```bash
python3 code/mtls_echo.py
```

```console
[server] verified the client's certificate: commonName=localhost
[client] verified the server's certificate: commonName=localhost
[client] channel: TLSv1.3 / TLS_AES_256_GCM_SHA384
```

Now `getpeercert()` returns a populated certificate on *both* ends — proof that
each verified the other. If you deleted the client's `load_cert_chain` line, the
handshake would fail at the server with a "certificate required" alert: the
transport itself now enforces identity.

## Use It

You almost never wire up `SSLContext` by hand. In production the server sits
behind a framework or a reverse proxy that **terminates TLS** for you — you point
it at a certificate and key, and it does everything above. The exact same
concepts drive the configuration:

```python
# A production ASGI server (uvicorn) terminating TLS for an app:
#   uvicorn app:api --ssl-certfile cert.pem --ssl-keyfile key.pem --port 443
# Under the hood this is the same load_cert_chain + wrap_socket you just wrote.
```

On the *client* side, libraries like `httpx` or `requests` verify certificates
**by default** — the opposite of our demo — using the system trust store you saw
in the chain-of-trust diagram:

```python
import httpx
httpx.get("https://example.com")            # verifies the chain automatically
httpx.get("https://localhost", verify=False)  # the CERT_NONE escape hatch — dev only
```

For mTLS between services, a **service mesh** (or a load balancer configured for
client certificates) issues a certificate to every workload and rotates them
automatically — turning the two `load_cert_chain` calls you wrote into
infrastructure. Knowing what those calls *do* is what lets you debug the mesh
when a handshake fails.

## Ship It

The artifact for this lesson is a TLS triage prompt:
[`outputs/prompt-tls-triage.md`](../outputs/prompt-tls-triage.md) — it maps a
symptom (`certificate verify failed`, hostname mismatch, expired cert, protocol
or cipher mismatch, an mTLS `certificate required` alert) to the exact link in
the chain of trust that broke, and the command that confirms it. You can read it
because you just built both a server-authenticated and a mutually-authenticated
channel by hand.

## Key takeaways

- **TLS** (Transport Layer Security, RFC 8446) wraps a TCP stream to provide three guarantees at once: **confidentiality** (encryption), **integrity** (tamper detection), and **authentication** (a verified server identity).
- The **handshake** negotiates a version and cipher (ClientHello/ServerHello), verifies the server's certificate, and uses **asymmetric** cryptography to establish a shared **symmetric** key — fast crypto for the data, public-key crypto only for setup.
- A **certificate** (X.509, RFC 5280) binds a public key to a name and is signed by a **CA**. Clients trust a server by walking the **chain of trust** from its leaf up to a root CA already in their trust store.
- **HTTPS** is just HTTP inside TLS on port 443; **SNI** lets one IP address serve many certificates by naming the wanted host in the ClientHello.
- **mTLS** makes the *client* present a certificate too, so both sides authenticate — the default for service-to-service traffic. `CERT_NONE` disables verification and must never leave a demo.
