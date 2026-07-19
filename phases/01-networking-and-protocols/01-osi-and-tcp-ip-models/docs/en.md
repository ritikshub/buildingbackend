# The Two Maps: OSI & TCP/IP Models

> Networking works because nobody builds the whole thing at once. It is sliced into layers, each doing one job and trusting the layer below — so you can swap your Wi-Fi for a cable and every app keeps running, untouched.

**Type:** Build
**Languages:** Python
**Prerequisites:** none — this is the first lesson of Phase 1. If you have never met the word *packet*, you are in the right place; we define every term as it appears.
**Time:** ~50 minutes

## The Problem

Right now, bytes are leaving your machine, crossing Wi-Fi to a router, hopping through fiber under an ocean, passing through a dozen machines built by different companies in different decades, and arriving — in order, intact — at a server you have never seen. Nobody coordinated all of that. No single program knows the whole route. Yet it works billions of times a second.

It works because the people who built the internet refused to build it as one giant program. Imagine if the code that drew a web page also had to know how to modulate a radio signal onto the 5 GHz band. Then switching from Wi-Fi to an Ethernet cable would mean rewriting your browser. Adding a new kind of physical link — 5G, satellite, carrier pigeon — would mean rewriting every application on Earth.

So instead of one program, networking is a **stack of layers**. Each layer does one small job, hands its result to the layer below, and knows nothing about how that lower layer works — only what it promises. Your browser hands bytes to the transport layer and says "get these to program X on machine Y." It does not know or care whether those bytes will travel over copper, glass, or air. That ignorance is the whole point: it is what lets one layer change without disturbing the others.

There are two famous **maps** of these layers. The **OSI model** has seven layers and is the vocabulary everyone argues in ("that's a layer-7 problem"). The **TCP/IP model** has four layers and is what the internet actually runs. This lesson is the map-reading lesson: learn both, learn how they line up, and — the part that makes it click — build the exact mechanism that ties the layers together, called *encapsulation*, by hand in Python.

## The Concept

First, three words we will use constantly. A **bit** is a single `0` or `1` — the smallest piece of information. Eight bits grouped together are a **byte**, which can represent a number from 0 to 255 or a single character like `H`. When data crosses a network it does not go all at once; it goes in small chunks, and to each chunk a layer attaches a **header** — a short, fixed block of bytes stuck *in front of* your data that says who it is for and how to handle it. Hold those three: bit, byte, header. Everything below is built from them.

### Why layering exists

A layer is a contract. It promises a service to the layer above and demands a service from the layer below, and it hides how it delivers on that promise. Three concrete payoffs follow:

- **Swap a layer without touching the others.** The layer that moves bits over Wi-Fi and the layer that moves them over a fiber cable are different implementations of the *same contract* ("carry these bytes to the next machine"). The application above cannot tell which one ran, so you can change it freely.
- **Divide the work.** The team designing how routers find paths across the globe never has to think about voltage levels on a wire. Each layer is a self-contained problem.
- **Reuse.** One transport layer serves web browsers, email clients, and databases alike, because it does not know or care what the bytes mean.

The price is a little overhead — every layer adds its own header — but that overhead buys an internet that can evolve one piece at a time. That is the trade the whole field is built on.

### The seven OSI layers

**OSI** (Open Systems Interconnection) is a reference model published by the ISO (International Organization for Standardization) and ITU-T as a common vocabulary for network functions. It defines seven layers, numbered from the wire up. Read it bottom-to-top — that is the order data is built as it heads for the network card:

| # | Layer | One-line job | Example |
|---|---|---|---|
| 7 | Application | The protocol the app itself speaks | HTTP, DNS, SMTP |
| 6 | Presentation | Data format: encoding, compression, encryption | TLS, character encodings |
| 5 | Session | Set up, maintain, and tear down a dialog | Named pipes, RPC sessions |
| 4 | Transport | Deliver to the right *program*; reliability & ordering | TCP, UDP |
| 3 | Network | Deliver to the right *machine* across networks; routing | IP, ICMP |
| 2 | Data Link | Move a frame to the next device on the local link | Ethernet, Wi-Fi (802.11) |
| 1 | Physical | Turn bits into signals on a medium | Copper, fiber, radio |

Acronyms in that table, defined once: **HTTP** = HyperText Transfer Protocol; **DNS** = Domain Name System; **SMTP** = Simple Mail Transfer Protocol; **TLS** = Transport Layer Security; **TCP** = Transmission Control Protocol; **UDP** = User Datagram Protocol; **IP** = Internet Protocol; **ICMP** = Internet Control Message Protocol; **RPC** = Remote Procedure Call.

A useful memory aid, top to bottom: **A**ll **P**eople **S**eem **T**o **N**eed **D**ata **P**rocessing (Application, Presentation, Session, Transport, Network, Data Link, Physical). The key intuition is the shift at the middle: layers 1–3 move bytes *toward a machine*, layer 4 hands them *to a program*, and layers 5–7 are the application's own concern.

### The four TCP/IP layers

The OSI model is a teaching tool. The internet actually runs on the **TCP/IP model** (named after its two core protocols, Transmission Control Protocol and Internet Protocol), described for host software in RFC 1122. It collapses the seven into four, because in practice several OSI layers are handled together by one piece of software:

| Layer | One-line job | Example |
|---|---|---|
| Application | Everything the app cares about: protocol, format, session | HTTP, DNS, TLS |
| Transport | Program-to-program delivery, with or without guarantees | TCP, UDP |
| Internet | Machine-to-machine delivery across networks; routing | IP |
| Link | Move a frame across one physical hop | Ethernet, Wi-Fi |

Fewer boxes, same journey. The four-layer model is closer to how the code is actually organized: your program, the operating system's transport and IP code, and the network driver.

### Mapping the two models

The two maps describe the same territory. TCP/IP's **Application** layer swallows OSI's top three (Application, Presentation, Session) — in real software, formatting and session state are just part of the app. The middle two line up one-to-one (Transport ↔ Transport, Internet ↔ Network), and TCP/IP's **Link** layer covers OSI's bottom two (Data Link and Physical):

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 720 470" width="100%" style="max-width:700px" role="img" aria-label="Two maps of the same layered network stack. OSI has seven layers — Application, Presentation, Session, Transport, Network, Data Link, Physical. TCP/IP has four. TCP/IP's Application layer covers OSI's top three (Application, Presentation, Session); Transport maps one-to-one to OSI Transport; Internet maps to OSI Network; and TCP/IP's Link layer covers OSI's Data Link and Physical layers.">
  <text x="360" y="28" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">Two maps of the same territory — TCP/IP groups what OSI splits</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <text x="140" y="62" text-anchor="middle" font-size="12" font-weight="700" fill="currentColor">OSI — 7 layers</text>
    <text x="575" y="62" text-anchor="middle" font-size="12" font-weight="700" fill="currentColor">TCP/IP — 4 layers</text>
    <g fill="none" stroke-width="1.6">
      <path d="M240 101 L470 149" stroke="#3553ff" stroke-opacity="0.5"/>
      <path d="M240 149 L470 149" stroke="#3553ff" stroke-opacity="0.5"/>
      <path d="M240 197 L470 149" stroke="#3553ff" stroke-opacity="0.5"/>
      <path d="M240 245 L470 245" stroke="#0fa07f" stroke-opacity="0.55"/>
      <path d="M240 293 L470 293" stroke="#e0930f" stroke-opacity="0.55"/>
      <path d="M240 341 L470 365" stroke="#7c5cff" stroke-opacity="0.5"/>
      <path d="M240 389 L470 365" stroke="#7c5cff" stroke-opacity="0.5"/>
    </g>
    <g stroke-width="1.5" stroke-linejoin="round">
      <rect x="40" y="80"  width="200" height="42" rx="8" fill="#3553ff" fill-opacity="0.10" stroke="#3553ff"/>
      <rect x="40" y="128" width="200" height="42" rx="8" fill="#3553ff" fill-opacity="0.10" stroke="#3553ff"/>
      <rect x="40" y="176" width="200" height="42" rx="8" fill="#3553ff" fill-opacity="0.10" stroke="#3553ff"/>
      <rect x="40" y="224" width="200" height="42" rx="8" fill="#0fa07f" fill-opacity="0.11" stroke="#0fa07f"/>
      <rect x="40" y="272" width="200" height="42" rx="8" fill="#e0930f" fill-opacity="0.11" stroke="#e0930f"/>
      <rect x="40" y="320" width="200" height="42" rx="8" fill="#7c5cff" fill-opacity="0.11" stroke="#7c5cff"/>
      <rect x="40" y="368" width="200" height="42" rx="8" fill="#7c5cff" fill-opacity="0.11" stroke="#7c5cff"/>
    </g>
    <g fill="currentColor" text-anchor="middle">
      <text x="140" y="98"  font-size="11.5">7 · Application</text>
      <text x="140" y="112" font-size="7.5" opacity="0.6">HTTP · DNS · SMTP</text>
      <text x="140" y="146" font-size="11.5">6 · Presentation</text>
      <text x="140" y="160" font-size="7.5" opacity="0.6">TLS · encodings</text>
      <text x="140" y="194" font-size="11.5">5 · Session</text>
      <text x="140" y="208" font-size="7.5" opacity="0.6">RPC · sockets</text>
      <text x="140" y="242" font-size="11.5">4 · Transport</text>
      <text x="140" y="256" font-size="7.5" opacity="0.6">TCP · UDP</text>
      <text x="140" y="290" font-size="11.5">3 · Network</text>
      <text x="140" y="304" font-size="7.5" opacity="0.6">IP · ICMP</text>
      <text x="140" y="338" font-size="11.5">2 · Data Link</text>
      <text x="140" y="352" font-size="7.5" opacity="0.6">Ethernet · Wi-Fi</text>
      <text x="140" y="386" font-size="11.5">1 · Physical</text>
      <text x="140" y="400" font-size="7.5" opacity="0.6">copper · fiber · radio</text>
    </g>
    <g stroke-width="2" stroke-linejoin="round">
      <rect x="470" y="80"  width="210" height="138" rx="10" fill="#3553ff" fill-opacity="0.13" stroke="#3553ff"/>
      <rect x="470" y="224" width="210" height="42"  rx="10" fill="#0fa07f" fill-opacity="0.14" stroke="#0fa07f"/>
      <rect x="470" y="272" width="210" height="42"  rx="10" fill="#e0930f" fill-opacity="0.14" stroke="#e0930f"/>
      <rect x="470" y="320" width="210" height="90"  rx="10" fill="#7c5cff" fill-opacity="0.14" stroke="#7c5cff"/>
    </g>
    <g fill="currentColor" text-anchor="middle">
      <text x="575" y="136" font-size="13" font-weight="700">Application</text>
      <text x="575" y="154" font-size="8.5" opacity="0.85">= OSI  7 · 6 · 5</text>
      <text x="575" y="170" font-size="7.5" opacity="0.6">protocol, format, session</text>
      <text x="575" y="241" font-size="13" font-weight="700">Transport</text>
      <text x="575" y="256" font-size="7.5" opacity="0.7">= OSI 4 · ports</text>
      <text x="575" y="289" font-size="13" font-weight="700">Internet</text>
      <text x="575" y="304" font-size="7.5" opacity="0.7">= OSI 3 · IP</text>
      <text x="575" y="358" font-size="13" font-weight="700">Link</text>
      <text x="575" y="375" font-size="8.5" opacity="0.85">= OSI  2 · 1</text>
      <text x="575" y="391" font-size="7.5" opacity="0.6">frame across one hop</text>
    </g>
    <text x="360" y="436" text-anchor="middle" font-size="10" fill="currentColor" opacity="0.9">"Layer 7", "layer 4", "layer 3": engineers always count in OSI's numbers —</text>
    <text x="360" y="453" text-anchor="middle" font-size="10" fill="currentColor" opacity="0.9">even when the system underneath is really the four-layer TCP/IP stack.</text>
  </g>
</svg>
```

When someone says "layer 7," they mean OSI numbering (the application). "Layer 4" is transport, "layer 3" is the network/IP. Those numbers are the OSI map even when the thing they are describing is a TCP/IP system — the vocabulary stuck.

### Encapsulation: wrapping data on the way down

Here is the mechanism that connects the layers. When you send data, it travels *down* the stack, and at each layer the software takes whatever it received from above and puts its own header in front of it. This wrapping is called **encapsulation**. The layer above's entire output — header and all — becomes the *payload* (the carried contents) of the layer below. Like a letter placed in an envelope, which is placed in a mailbag, which is placed in a truck: each container wraps the last without reading it.

Concretely, sending a small web request:

1. **Application** produces the message, e.g. `GET /index.html HTTP/1.1`.
2. **Transport** prepends a header with **port numbers** — a port is a 16-bit number that picks which *program* on the machine the bytes are for. Now the bytes plus that header are a *segment*.
3. **Network** prepends a header with **IP addresses** — the source and destination *machine* addresses. Now it is a *packet*.
4. **Link** prepends a header with **MAC addresses** (Media Access Control — the hardware address of a network card, identifying the next device on the local wire). Now it is a *frame*.
5. **Physical** turns that frame into signals — bits on the wire.

Each layer adds a fixed number of bytes in front. Nothing rewrites the payload; the message you started with is still in there, buried under three headers.

### Protocol Data Units: bits, frames, packets, segments, data

The chunk of data has a different name at each layer — its **PDU** (Protocol Data Unit, the formal name for "the unit of data this layer deals with"). The names are worth memorizing because engineers use them precisely: saying "packet" when you mean "frame" points at the wrong layer.

| Layer (TCP/IP) | PDU name | What it is |
|---|---|---|
| Application | **data** (or message) | The raw bytes the app produced |
| Transport | **segment** (TCP) / **datagram** (UDP) | Data + a transport header (ports) |
| Internet | **packet** | Segment + an IP header (addresses) |
| Link | **frame** | Packet + a MAC header (and a trailer) |
| Physical | **bits** | The frame as signals on the medium |

Read top to bottom, that is the growth of the thing you are sending: **data → segment → packet → frame → bits**. Read bottom to top, it is what the receiver unwraps.

### Decapsulation: unwrapping on the way up

The receiver runs the whole process in reverse, called **decapsulation**. Bits arrive at the physical layer and are reassembled into a frame. The link layer reads its MAC header, confirms the frame is for this machine, strips the header, and hands the rest up. The network layer reads and strips the IP header; the transport layer reads and strips the port header and thus knows which program to deliver to; the application receives exactly the original bytes. Every header that was added on the way down is removed, in the opposite order, on the way up:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 780 414" width="100%" style="max-width:760px" role="img" aria-label="Encapsulation and decapsulation. On the sender the message travels down the stack and each layer prepends its own header: a 24-byte data block becomes a 28-byte segment when the transport layer adds a 4-byte port header, a 36-byte packet when the network layer adds an 8-byte IP header, and a 48-byte frame when the link layer adds a 12-byte MAC header, then leaves as bits on the wire. On the receiver the bits arrive and each layer strips its header in the exact reverse order — frame to packet to segment to data — recovering the original 24-byte message byte-for-byte.">
  <defs>
    <marker id="l1e-ar" markerWidth="9" markerHeight="9" refX="5.5" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker>
  </defs>
  <text x="390" y="24" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="13.5" font-weight="700" fill="currentColor">Wrap on the way down, unwrap in the exact reverse order on the way up</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <text x="218" y="52" text-anchor="middle" font-size="12" font-weight="700" fill="#3553ff">SENDER · encapsulate ↓</text>
    <text x="580" y="52" text-anchor="middle" font-size="12" font-weight="700" fill="#0fa07f">RECEIVER · decapsulate ↑</text>

    <path d="M22 82 L22 316" fill="none" stroke="currentColor" stroke-opacity="0.5" stroke-width="1.4" marker-end="url(#l1e-ar)"/>
    <path d="M758 316 L758 82" fill="none" stroke="currentColor" stroke-opacity="0.5" stroke-width="1.4" marker-end="url(#l1e-ar)"/>

    <!-- sender layer names -->
    <g fill="currentColor" opacity="0.85" text-anchor="end" font-size="8.5">
      <text x="92" y="93">Application</text>
      <text x="92" y="151">Transport</text>
      <text x="92" y="209">Network</text>
      <text x="92" y="267">Link</text>
      <text x="92" y="325">Physical</text>
    </g>
    <!-- sender bars -->
    <g stroke-width="1.2" stroke-linejoin="round">
      <rect x="98"  y="75"  width="120" height="30" rx="4" fill="#3553ff" fill-opacity="0.16" stroke="#3553ff"/>
      <rect x="98"  y="133" width="20"  height="30" rx="4" fill="#0fa07f" fill-opacity="0.2"  stroke="#0fa07f"/>
      <rect x="118" y="133" width="120" height="30" rx="4" fill="#3553ff" fill-opacity="0.16" stroke="#3553ff"/>
      <rect x="98"  y="191" width="40"  height="30" rx="4" fill="#e0930f" fill-opacity="0.2"  stroke="#e0930f"/>
      <rect x="138" y="191" width="20"  height="30" rx="4" fill="#0fa07f" fill-opacity="0.2"  stroke="#0fa07f"/>
      <rect x="158" y="191" width="120" height="30" rx="4" fill="#3553ff" fill-opacity="0.16" stroke="#3553ff"/>
      <rect x="98"  y="249" width="60"  height="30" rx="4" fill="#7c5cff" fill-opacity="0.2"  stroke="#7c5cff"/>
      <rect x="158" y="249" width="40"  height="30" rx="4" fill="#e0930f" fill-opacity="0.2"  stroke="#e0930f"/>
      <rect x="198" y="249" width="20"  height="30" rx="4" fill="#0fa07f" fill-opacity="0.2"  stroke="#0fa07f"/>
      <rect x="218" y="249" width="120" height="30" rx="4" fill="#3553ff" fill-opacity="0.16" stroke="#3553ff"/>
      <rect x="98"  y="307" width="240" height="30" rx="4" fill="#7f7f7f" fill-opacity="0.1" stroke="currentColor" stroke-opacity="0.4" stroke-dasharray="4 4"/>
    </g>
    <!-- sender segment labels -->
    <g fill="currentColor" text-anchor="middle" font-size="7.5">
      <text x="158" y="94">DATA</text>
      <text x="178" y="152">DATA</text>
      <text x="118" y="210">IP</text><text x="218" y="210">DATA</text>
      <text x="128" y="268">MAC</text><text x="178" y="268">IP</text><text x="278" y="268">DATA</text>
      <text x="218" y="326" opacity="0.55">0100110 1 00101 110 01001010 …</text>
    </g>
    <!-- sender PDU + size labels -->
    <g fill="currentColor" opacity="0.75" text-anchor="start" font-size="8">
      <text x="346" y="93">data · 24 B</text>
      <text x="346" y="151">segment · 28 B</text>
      <text x="346" y="209">packet · 36 B</text>
      <text x="346" y="267">frame · 48 B</text>
      <text x="346" y="325">bits</text>
    </g>

    <!-- receiver bars -->
    <g stroke-width="1.2" stroke-linejoin="round">
      <rect x="580" y="75"  width="120" height="30" rx="4" fill="#3553ff" fill-opacity="0.16" stroke="#3553ff"/>
      <rect x="560" y="133" width="20"  height="30" rx="4" fill="#0fa07f" fill-opacity="0.2"  stroke="#0fa07f"/>
      <rect x="580" y="133" width="120" height="30" rx="4" fill="#3553ff" fill-opacity="0.16" stroke="#3553ff"/>
      <rect x="520" y="191" width="40"  height="30" rx="4" fill="#e0930f" fill-opacity="0.2"  stroke="#e0930f"/>
      <rect x="560" y="191" width="20"  height="30" rx="4" fill="#0fa07f" fill-opacity="0.2"  stroke="#0fa07f"/>
      <rect x="580" y="191" width="120" height="30" rx="4" fill="#3553ff" fill-opacity="0.16" stroke="#3553ff"/>
      <rect x="460" y="249" width="60"  height="30" rx="4" fill="#7c5cff" fill-opacity="0.2"  stroke="#7c5cff"/>
      <rect x="520" y="249" width="40"  height="30" rx="4" fill="#e0930f" fill-opacity="0.2"  stroke="#e0930f"/>
      <rect x="560" y="249" width="20"  height="30" rx="4" fill="#0fa07f" fill-opacity="0.2"  stroke="#0fa07f"/>
      <rect x="580" y="249" width="120" height="30" rx="4" fill="#3553ff" fill-opacity="0.16" stroke="#3553ff"/>
      <rect x="460" y="307" width="240" height="30" rx="4" fill="#7f7f7f" fill-opacity="0.1" stroke="currentColor" stroke-opacity="0.4" stroke-dasharray="4 4"/>
    </g>
    <!-- receiver segment labels -->
    <g fill="currentColor" text-anchor="middle" font-size="7.5">
      <text x="640" y="94">DATA</text>
      <text x="640" y="152">DATA</text>
      <text x="540" y="210">IP</text><text x="640" y="210">DATA</text>
      <text x="490" y="268">MAC</text><text x="540" y="268">IP</text><text x="640" y="268">DATA</text>
      <text x="580" y="326" opacity="0.55">… 01001010 011 01 100 0100110</text>
    </g>
    <!-- receiver PDU labels (stripped, reverse) -->
    <g fill="currentColor" opacity="0.7" text-anchor="end" font-size="8">
      <text x="574" y="93">strip → data</text>
      <text x="554" y="151">strip → segment</text>
      <text x="514" y="209">strip → packet</text>
      <text x="454" y="267">frame</text>
      <text x="454" y="325">bits arrive</text>
    </g>

    <!-- across the wire -->
    <path d="M218 339 L218 358 L580 358 L580 341" fill="none" stroke="currentColor" stroke-width="1.6" marker-end="url(#l1e-ar)"/>
    <text x="399" y="353" text-anchor="middle" font-size="9" fill="currentColor" opacity="0.85">bits travel across the network</text>

    <text x="390" y="384" text-anchor="middle" font-size="10" fill="currentColor" opacity="0.9">24 → 28 → 36 → 48 bytes as three headers go on; 48 → 24 as they come back off —</text>
    <text x="390" y="401" text-anchor="middle" font-size="10" fill="currentColor" opacity="0.9">the message the receiver hands up is byte-for-byte identical to the one the sender wrote.</text>
  </g>
</svg>
```

### A byte's round trip

Put it together and follow one request. Your browser writes `GET /index.html HTTP/1.1` (application). The transport layer wraps it with the destination port `80` (which conventionally means "a web server") and an ephemeral source port so the reply can find its way back — now a segment. The network layer wraps that with your IP and the server's IP — now a packet. The link layer wraps that with your card's MAC and the router's MAC — now a frame. The physical layer sends the bits.

At the server, the same envelopes come off in reverse: link checks the MAC and strips it, network checks the IP and strips it, transport reads port `80` and hands the bytes to the web-server program, which finally sees `GET /index.html HTTP/1.1` — the very bytes the browser wrote, with every layer's header added and removed cleanly in between. That symmetry — wrap on the way down, unwrap in the exact reverse order on the way up — is what you will now build.

## Build It

The full implementation is in [`code/encapsulation.py`](../code/encapsulation.py). It models a tiny four-layer stack: it takes an application message as bytes, wraps it with a mock transport header, then a network header, then a link header — each a real byte prefix built with Python's `struct` module — printing the growing frame and its size at every step. Then it decapsulates: it peels each header off, prints what each layer sees, recovers the original message, and asserts it is byte-for-byte identical to what went in.

`struct` is the standard-library tool for turning Python values into fixed-layout bytes and back, exactly like a real protocol header. Each layer here is one `struct.Struct` describing its header's byte layout:

```python
import struct

TRANSPORT = struct.Struct(">HH")    # src port, dst port      -> 4 bytes
NETWORK = struct.Struct(">4s4s")    # src IPv4, dst IPv4       -> 8 bytes
LINK = struct.Struct(">6s6s")       # src MAC, dst MAC         -> 12 bytes
```

The format string is the header's shape: `>` means big-endian (network byte order — the order bytes travel in on a network, most-significant first); `H` is a 16-bit unsigned integer (a port); `4s` is a 4-byte string (an IPv4 address); `6s` is a 6-byte string (a MAC address). Encapsulation is then just prepending each packed header to the payload below it:

```python
segment = TRANSPORT.pack(49152, 80) + message                 # data -> segment
packet = NETWORK.pack(src_ip, dst_ip) + segment               # segment -> packet
frame = LINK.pack(src_mac, dst_mac) + packet                  # packet -> frame
```

Decapsulation reverses it exactly — read a header off the front, keep the rest:

```python
src_mac, dst_mac = LINK.unpack(frame[:LINK.size])             # frame -> packet
packet = frame[LINK.size:]
src_ip, dst_ip = NETWORK.unpack(packet[:NETWORK.size])        # packet -> segment
segment = packet[NETWORK.size:]
src_port, dst_port = TRANSPORT.unpack(segment[:TRANSPORT.size])# segment -> data
message = segment[TRANSPORT.size:]
```

Run it:

```bash
python code/encapsulation.py
```

You will see a 24-byte message grow to 28 (transport), 36 (network), then 48 bytes (link) on the way down, and shrink back to 24 on the way up, ending in the assertion that the recovered bytes equal the original. Watching the size climb by exactly 4, then 8, then 12 bytes — and watching the same message fall back out the top — is what makes encapsulation stop being a diagram and start being a fact.

## Use It

You never write the encapsulation loop above in production, because the operating system's networking stack *is* that loop, running in the kernel. When you open a socket, you are handing bytes in at the application layer and letting the kernel add the transport, network, and link headers for you. The same standard-library `socket` call touches all four layers at once:

```python
import socket

# AF_INET selects the Internet (IPv4) network layer; SOCK_STREAM selects the
# TCP transport layer. One call, and the kernel wires up the whole stack below.
sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.connect(("example.com", 80))   # network + transport handshake happen here
sock.sendall(b"GET / HTTP/1.1\r\nHost: example.com\r\n\r\n")  # you hand in L7 data
sock.close()
```

`AF_INET` (Address Family: Internet) picks IPv4 at the network layer; `SOCK_STREAM` picks TCP at the transport layer. Every header you built by hand — ports, IP addresses, MAC addresses — the kernel now builds and strips for you, invisibly, for every one of the thousands of frames this connection may produce. The layering you just modeled is not an abstraction on top of the real system; it *is* the real system's structure, and knowing it is how you reason about where a failure lives.

That is also why the model earns its keep when things break. "The connection is refused" is a transport-layer answer (layer 4). "The host name won't resolve" is application-layer (DNS). "It works on Wi-Fi but not on the cable" is link/physical (layer 1–2). The layers tell you which tool to reach for and which team owns the problem — which is exactly what the artifact for this lesson helps you do.

## Ship It

The reusable artifact for this lesson is a layer-locator prompt: [`outputs/prompt-layer-locator.md`](../outputs/prompt-layer-locator.md). Feed it a symptom — "connection refused," "name won't resolve," "TLS handshake fails," "works on one network but not another" — and it walks you to the single OSI/TCP-IP layer most likely responsible, tells you which PDU and header are involved, and names the command to confirm it. It works because you now hold the whole map: you know what each layer promises, so you know which promise a given symptom breaks.

## Key takeaways

- **Layering exists so one layer can change without disturbing the others** — swap Wi-Fi for a cable and every app keeps running, because each layer only depends on the *contract* of the layer below, not its implementation.
- **OSI has seven layers** (Physical, Data Link, Network, Transport, Session, Presentation, Application); **TCP/IP has four** (Link, Internet, Transport, Application). TCP/IP's Application layer covers OSI's top three, and its Link layer covers OSI's bottom two; the middle two map one-to-one.
- **Encapsulation** wraps data on the way down: each layer prepends its own header, turning the layer above's whole output into its payload. **Decapsulation** unwraps it on the way up, stripping headers in the exact reverse order.
- **The PDU name changes by layer**: data → segment/datagram → packet → frame → bits going down, and back up on the receiver.
- **The kernel runs this stack for you** — one `socket()` call spans all four layers — but the model is what tells you *which* layer a failure lives in.
