# Names on the Network: DNS

> You type a name; the machine needs a number. DNS is the distributed database that turns `example.com` into `93.184.216.34` — and it is just a request-and-reply protocol you can build by hand.

**Type:** Build
**Languages:** Python
**Prerequisites:** Lessons 04–05 — IP and the transport layer. You should know that an IP (Internet Protocol) address identifies a machine, and that DNS uses UDP (User Datagram Protocol) port 53.
**Time:** ~60 minutes

## The Problem

Every connection your computer makes ends at an IP address — a number like
`93.184.216.34`. But you never type numbers. You type `example.com`,
`api.github.com`, `mail.google.com`. Somewhere between the name you type and the
packet that leaves your network card, a name became a number.

That translation is not stored on your machine. There are hundreds of millions of
domain names, they change constantly, and no one owns the whole list. So the
lookup has to be a **network request** to a system that does hold the answer — and
that system is itself spread across thousands of servers run by different
organizations around the world. Ask it for a name and it will find the number,
even though no single server knows them all.

That system is **DNS** (Domain Name System, defined in RFC 1035). By the end of
this lesson you will understand how a name gets resolved through a chain of
servers, and you will have built a real DNS query — byte for byte — and decoded a
real DNS response to pull an IP address out of it, all without a library.

## The Concept

DNS is a **distributed, hierarchical database** with one job: map a name to
records (usually an address). "Distributed" means no server holds everything;
"hierarchical" means the name itself tells you which servers to ask, reading
right to left.

### Names, addresses, and the resolver chain

A name like `www.example.com` is read **right to left**, from most general to
most specific. The trailing dot is the invisible **root**; then `.com` is the
**TLD** (Top-Level Domain); then `example` is the domain; then `www` is a host
inside it. Written in full with the root dot — `www.example.com.` — it is called a
**FQDN** (Fully Qualified Domain Name).

Your application does not do the lookup itself. It calls a **stub resolver** (a
thin client built into your operating system) which hands the question to a
**recursive resolver** — a server, usually run by your ISP or a public provider
like `1.1.1.1`, whose job is to do the legwork and come back with a final answer.
The recursive resolver is the one that walks the tree.

### Walking the tree: root, TLD, authoritative

The recursive resolver starts at the top and follows referrals down. It knows the
addresses of the **root servers** (a small, fixed list baked in). It asks the
root, "where do I find `example.com`?" The root does not know the answer, but it
knows who runs `.com`, so it **refers** the resolver to the `.com` TLD servers.
Those refer it to `example.com`'s **authoritative servers** — the servers that
actually hold the domain's records. That last server gives the real answer.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 418" width="100%" style="max-width:880px" role="img" aria-label="Recursive DNS resolution as a five-lane sequence. The stub resolver (your app) sends one query, A? example.com, to the recursive resolver. The recursive resolver then walks the hierarchy: it asks a root server, which refers it to the .com TLD servers; it asks the .com TLD server, which refers it to example.com's authoritative servers; it asks the authoritative server, which returns 93.184.216.34 with a TTL of 3600 seconds. The recursive resolver returns that address to the stub and caches it. The stub asks once while the recursive resolver does all the legwork.">
  <defs>
    <marker id="l06-ar" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker>
    <marker id="l06-ar2" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor" fill-opacity="0.6"/></marker>
  </defs>
  <text x="450" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">Ask once — the recursive resolver walks the tree for you</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <!-- actor header boxes -->
    <g stroke-width="1.7" stroke-linejoin="round">
      <rect x="15"  y="44" width="150" height="44" rx="9" fill="#3553ff" fill-opacity="0.11" stroke="#3553ff"/>
      <rect x="195" y="44" width="150" height="44" rx="9" fill="#0fa07f" fill-opacity="0.13" stroke="#0fa07f"/>
      <rect x="375" y="44" width="150" height="44" rx="9" fill="#7f7f7f" fill-opacity="0.10" stroke="#7f7f7f"/>
      <rect x="555" y="44" width="150" height="44" rx="9" fill="#e0930f" fill-opacity="0.10" stroke="#e0930f"/>
      <rect x="735" y="44" width="150" height="44" rx="9" fill="#7c5cff" fill-opacity="0.11" stroke="#7c5cff"/>
    </g>
    <!-- actor names -->
    <text x="90"  y="64" text-anchor="middle" font-size="11" font-weight="700" fill="#3553ff">Stub resolver</text>
    <text x="270" y="64" text-anchor="middle" font-size="11" font-weight="700" fill="#0fa07f">Recursive resolver</text>
    <text x="450" y="64" text-anchor="middle" font-size="11" font-weight="700" fill="currentColor">Root server</text>
    <text x="630" y="64" text-anchor="middle" font-size="11" font-weight="700" fill="#e0930f">.com TLD</text>
    <text x="810" y="64" text-anchor="middle" font-size="11" font-weight="700" fill="#7c5cff">example.com</text>
    <g font-size="8.5" text-anchor="middle" fill="currentColor" opacity="0.7">
      <text x="90"  y="79">your app</text>
      <text x="270" y="79">the hub — walks the tree</text>
      <text x="450" y="79">knows .com servers</text>
      <text x="630" y="79">knows example.com</text>
      <text x="810" y="79">auth. server</text>
    </g>
    <!-- lifelines -->
    <g stroke-dasharray="4 5" stroke-width="1.3">
      <path d="M90 88 L90 356"   stroke="currentColor" stroke-opacity="0.22"/>
      <path d="M270 88 L270 356" stroke="#0fa07f" stroke-opacity="0.45"/>
      <path d="M450 88 L450 356" stroke="currentColor" stroke-opacity="0.22"/>
      <path d="M630 88 L630 356" stroke="currentColor" stroke-opacity="0.22"/>
      <path d="M810 88 L810 356" stroke="currentColor" stroke-opacity="0.22"/>
    </g>
    <!-- question arrows (solid) -->
    <g fill="none" stroke="currentColor" stroke-width="1.7">
      <path d="M94 120 L266 120"  marker-end="url(#l06-ar)"/>
      <path d="M274 152 L446 152" marker-end="url(#l06-ar)"/>
      <path d="M274 216 L626 216" marker-end="url(#l06-ar)"/>
      <path d="M274 280 L806 280" marker-end="url(#l06-ar)"/>
    </g>
    <!-- reply / referral arrows (dashed, lighter) -->
    <g fill="none" stroke="currentColor" stroke-width="1.5" stroke-opacity="0.5" stroke-dasharray="5 4">
      <path d="M446 184 L274 184" marker-end="url(#l06-ar2)"/>
      <path d="M626 248 L274 248" marker-end="url(#l06-ar2)"/>
      <path d="M806 312 L274 312" marker-end="url(#l06-ar2)"/>
      <path d="M266 344 L94 344"  marker-end="url(#l06-ar2)"/>
    </g>
    <!-- message labels -->
    <g text-anchor="middle">
      <text x="180" y="112" font-size="9"   fill="currentColor" opacity="0.9">A? example.com</text>
      <text x="360" y="144" font-size="9"   fill="currentColor" opacity="0.9">A? example.com</text>
      <text x="360" y="176" font-size="9"   fill="currentColor" opacity="0.65">don't know &#8594; ask .com</text>
      <text x="450" y="208" font-size="9"   fill="currentColor" opacity="0.9">A? example.com</text>
      <text x="450" y="240" font-size="9"   fill="currentColor" opacity="0.65">referral &#8594; auth. servers</text>
      <text x="540" y="272" font-size="9"   fill="currentColor" opacity="0.9">A? example.com</text>
      <text x="540" y="304" font-size="9"   font-weight="600" fill="#0fa07f">93.184.216.34, TTL 3600</text>
      <text x="180" y="336" font-size="9"   font-weight="600" fill="#0fa07f">93.184.216.34 (cached)</text>
    </g>
    <!-- takeaway -->
    <text x="450" y="382" text-anchor="middle" font-size="10" fill="currentColor" opacity="0.85">The stub asks once; the recursive resolver walks root &#8594; TLD &#8594; authoritative,</text>
    <text x="450" y="399" text-anchor="middle" font-size="10" fill="currentColor" opacity="0.85">caching the answer so the next lookup skips the whole walk.</text>
  </g>
</svg>
```

"Recursive" describes the resolver's promise to the stub: *you ask once, I return
the final answer.* The step-by-step walk it performs — ask, get a referral, ask
the next server — is called **iterative** resolution.

### Caching and TTL

Walking the whole tree for every lookup would be slow and would hammer the root
servers. So every answer carries a **TTL** (Time To Live): a number of seconds the
answer may be cached. The recursive resolver caches what it learns, and so does
your stub resolver and often your browser. The next lookup of `example.com` within
the TTL skips the walk entirely and returns from cache.

TTL is the central trade-off of DNS operations. A long TTL means fast lookups and
light load but slow propagation when you change a record; a short TTL means
changes take effect quickly but every cache expires sooner and asks again. When
you migrate a server, you lower the TTL *first*, wait for old cached copies to
expire, then make the change.

### Record types: A, AAAA, CNAME, MX, NS, TXT, SOA, PTR

A name does not map to just one thing. A DNS zone holds typed **resource
records**, and you query for the type you want:

| Type | Number | Maps a name to |
|---|---|---|
| A | 1 | an IPv4 address (4 bytes) |
| AAAA | 28 | an IPv6 address (16 bytes) |
| CNAME | 5 | another name — an alias (Canonical NAME) |
| MX | 15 | a mail server and a priority (Mail eXchange) |
| NS | 2 | an authoritative NameServer for the zone |
| TXT | 16 | arbitrary text (domain verification, email policy) |
| SOA | 6 | zone metadata (Start Of Authority: primary server, serial, timers) |
| PTR | 12 | a name, from an IP address (a PoinTeR, used for reverse lookups) |

A **CNAME** is worth calling out: it says "this name is really an alias for that
name — go resolve *that* instead." That is how `www.example.com` can point at
`example.com`, or a name can point at a cloud provider's hostname, without copying
the address.

### Transport: UDP and TCP on port 53

DNS runs on **port 53**. A normal query is small — a question and a short answer —
so it goes over **UDP** (User Datagram Protocol): one datagram out, one datagram
back, no connection setup. UDP has no delivery guarantee, so if no reply arrives
the client simply asks again. That is the right trade for a tiny, latency-sensitive
lookup.

DNS falls back to **TCP** (Transmission Control Protocol) on the same port 53 when
a response is too large for one datagram (the server sets the **TC**, or
truncated, flag to say "ask again over TCP"), and for **zone transfers**, where a
secondary server copies an entire zone from the primary and needs TCP's reliable,
ordered stream.

### The DNS message format

Query and response share one format: a fixed **12-byte header** followed by a
variable number of sections. The header counts what follows.

| Field | Size | What it does |
|---|---|---|
| ID | 16 bits | Query identifier; the reply echoes it so the client matches reply to request |
| Flags | 16 bits | QR (query/response), Opcode, AA (authoritative), TC (truncated), RD (recursion desired), RA (recursion available), RCODE (result code) |
| QDCOUNT | 16 bits | Number of entries in the question section |
| ANCOUNT | 16 bits | Number of resource records in the answer section |
| NSCOUNT | 16 bits | Number of records in the authority section |
| ARCOUNT | 16 bits | Number of records in the additional section |

After the header comes the **question section**: the **QNAME** (the name, encoded
as length-prefixed labels), a 16-bit **QTYPE** (A, MX, …) and a 16-bit **QCLASS**
(always `IN`, for Internet). A response repeats the question and then adds the
**answer section**: one or more **resource records**, each carrying a name, type,
class, TTL, a length, and the record data (RDATA) — for an A record, four bytes of
IPv4 address.

There is one clever detail. Names repeat all over a message, so RFC 1035 defines
**name compression**: instead of spelling a name out again, a record can use a
2-byte **pointer** (its top two bits set) that says "the name continues at byte
offset N earlier in this message." The decoder you build has to follow it.

## Build It

The full implementation is in [`code/`](../code/). We do not depend on a live
resolver — the grader has no network — so the core file builds a query and decodes
a **hardcoded real response** entirely offline and deterministically.

### Encode a name as length-prefixed labels

On the wire there are no dots. A name is a run of **labels**, each one a length
byte followed by that many characters, ending in a zero byte (the root). This is
[`code/dns_message.py`](../code/dns_message.py):

```python
def encode_qname(name: str) -> bytes:
    out = bytearray()
    for label in name.split("."):
        out.append(len(label))          # one length byte per label
        out.extend(label.encode("ascii"))
    out.append(0)                       # the root label ends the name
    return bytes(out)
```

`example.com` becomes `07 'example' 03 'com' 00`. The lengths replace the dots.

### Pack the 12-byte header and build the query

The header is six 16-bit fields, packed big-endian with `struct`. Setting the flags
to `0x0100` turns on just **RD** (Recursion Desired) — "resolver, do the walk for
me":

```python
import struct

header = struct.pack(
    ">HHHHHH",
    0x1234,     # ID: the reply must echo this
    0x0100,     # flags: QR=0 (query), RD=1
    1,          # QDCOUNT: one question
    0, 0, 0,    # ANCOUNT, NSCOUNT, ARCOUNT
)
question = encode_qname("example.com") + struct.pack(">HH", 1, 1)  # QTYPE A, QCLASS IN
query = header + question
```

Run it and you get the exact 29 bytes that would go on the wire:

```bash
python code/dns_message.py
```

```console
DNS query for example.com — 29 bytes
  hex: 123401000001000000000000076578616d706c6503636f6d0000010001
```

### Decode a real response, following the pointer

The file includes a real captured response as raw bytes and decodes it field by
field with `struct.unpack`. The answer's name is a **compression pointer**, so the
decoder detects the two high bits and follows the offset before reading the record:

```python
def read_name(msg: bytes, offset: int) -> tuple[str, int]:
    labels = []
    while True:
        length = msg[offset]
        if length & 0xC0 == 0xC0:                       # a 2-byte compression pointer
            pointer = ((length & 0x3F) << 8) | msg[offset + 1]
            offset = pointer
            continue
        if length == 0:                                 # root label — name ends
            break
        offset += 1
        labels.append(msg[offset:offset + length].decode("ascii"))
        offset += length
    return ".".join(labels), offset
```

(The file's version also returns the offset *just past* the pointer, so parsing
resumes at the right place.) The A record's RDATA is four bytes; joining them with
dots gives the address:

```console
DNS response — 45 bytes
  id .................. 0x1234
  flags ............... 0x8180  -> QR=response, RD=yes, RA=yes, RCODE=0
  counts .............. QD=1 AN=1 NS=0 AR=0
  question ............ example.com  TYPE=A CLASS=1
  answer .............. example.com A TTL=3600s -> 93.184.216.34

Resolved example.com -> 93.184.216.34
```

That is a full DNS round trip decoded from bytes — the same parse a resolver does.

## Use It

In real code you almost never build DNS packets. The standard library resolves
names for you the moment you open a socket; `socket.getaddrinfo` is the portable
call underneath every connection:

```python
import socket

for family, _type, _proto, _canon, sockaddr in socket.getaddrinfo(
    "example.com", 443, proto=socket.IPPROTO_TCP
):
    print(family.name, sockaddr[0])   # AF_INET 93.184.216.34, AF_INET6 2606:2800:...
```

`getaddrinfo` runs your stub resolver, which asks a recursive resolver, which does
exactly the walk you diagrammed — and returns both A (IPv4) and AAAA (IPv6)
answers, honoring TTLs and the OS cache. You get the number without ever seeing
the packet.

When you *do* need to see the packet — debugging a stale record, a wrong answer, a
slow resolver — you reach for `dig`, which is your `dns_message.py` with every
field exposed:

```bash
dig +noall +answer example.com A
```

```console
example.com.  3600  IN  A  93.184.216.34
```

That one line is the header's answer count, the question's name, the record's TTL,
class, type, and RDATA — the same fields you just unpacked by hand. Add `+trace`
and `dig` performs the root → TLD → authoritative walk step by step in front of
you.

The optional [`code/dns_live.py`](../code/dns_live.py) sends the query you built
to a public resolver over real UDP with a 2-second timeout. It needs network, so
every socket call is wrapped: no network or no reply prints a friendly note and
still exits cleanly — because with UDP, "no answer" is a normal outcome, not a
crash.

## Ship It

The artifact for this lesson is a DNS triage prompt:
[`outputs/prompt-dns-triage.md`](../outputs/prompt-dns-triage.md). It walks from a
symptom — `NXDOMAIN`, a stale record that won't update, a resolver that hangs, "it
works on my machine but not in production" — to the layer responsible: the record,
the TTL and caches, the resolver, or the transport. You can read it critically
because you now know what a query and a response actually contain.

## Key takeaways

- **DNS** (RFC 1035) is a distributed, hierarchical database that maps names to typed records; a name is read right to left, from the root down through the **TLD** to the domain's **authoritative** servers.
- A **stub resolver** asks a **recursive resolver**, which walks **root → TLD → authoritative** and caches the answer for its **TTL**. Long TTL = fast but slow to change; short TTL = quick to change but more lookups.
- Records are typed: **A** (IPv4), **AAAA** (IPv6), **CNAME** (alias), **MX** (mail), **NS** (nameserver), **TXT**, **SOA**, **PTR** (reverse).
- DNS uses **UDP port 53** for normal small queries (retry on loss) and **TCP port 53** for truncated (large) responses and zone transfers.
- A DNS message is a **12-byte header** (ID, flags, four section counts) plus a question (QNAME as length-prefixed labels, QTYPE, QCLASS) and answer records; **name compression** lets a name be a 2-byte pointer to an earlier offset.
