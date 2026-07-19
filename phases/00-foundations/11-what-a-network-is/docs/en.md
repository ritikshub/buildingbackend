# What a Network Is

> Everything so far happened inside one computer. Backend engineering is about computers talking to each other. A network is just that: a way for one machine to send bytes to another.

**Type:** Learn
**Languages:** —
**Prerequisites:** [How a Computer Runs a Program](../09-how-a-computer-runs-a-program/)
**Time:** ~45 minutes

## The Problem

One computer is useful. But the whole point of backend engineering is *many* computers
cooperating: your phone talking to a server across the world, that server talking to a
database on another machine. So the central question of everything ahead is:

**How do two separate computers exchange bytes?**

This lesson is the big-picture answer. The next few lessons zoom into the details (the
layers, addresses, and the journey of a request), but you need the map before the
close-ups.

## The Concept

### A network is just connected computers

A **network** is two or more computers connected so they can exchange data. The
simplest network is two computers joined by a cable. Add more and you get a **local
network** — the devices in your home joined through a **router** (your Wi-Fi box).

The bytes you send are the same bytes from lesson 1. A network is simply plumbing that
carries them from one machine to another.

### Client and server are roles, not machines

Two computers talking, one asks and one answers:

- The one that **asks** for something is the **client**.
- The one that **answers** is the **server**.

These are **roles, not special hardware**. Your laptop is a client when it loads a web
page and can be a server when it shares a file. **A backend is simply a program playing
the server role**: it starts up, waits, and answers requests. Hold onto that — it's the
one-sentence definition of everything you're going to build.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 760 338" width="100%" style="max-width:720px" role="img" aria-label="One exchange between a client and a server, drawn as a sequence. Two actors stand at the top with dashed lifelines dropping from each: on the left, the Client, which asks; on the right, the Server, which answers. Before anything happens, a note over the server's lifeline says it is already running and waiting for a request — the server was started earlier and does nothing until it is asked. The first arrow is the request: it travels left to right, from the client to the server, because the client asks, unprompted. A note over the server then says it does the work and replies. The second arrow is the response: it travels right to left, from the server back to the client. A band underneath states that these are roles, not hardware — the same laptop is a client when it loads a web page, and a server when it shares a file. The takeaway is that a backend is simply a program playing the server role: it starts up, waits, and answers requests.">
  <defs>
    <marker id="p0l11a-arb" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#3553ff"/></marker>
    <marker id="p0l11a-arg" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#0fa07f"/></marker>
  </defs>
  <text x="380" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="15" font-weight="700" fill="currentColor">The one that asks is the client; the one that answers is the server</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <!-- actor headers -->
    <g fill="none" stroke-width="1.7" stroke-linejoin="round">
      <rect x="120" y="44" width="140" height="46" rx="10" fill="#3553ff" fill-opacity="0.12" stroke="#3553ff"/>
      <rect x="500" y="44" width="140" height="46" rx="10" fill="#0fa07f" fill-opacity="0.12" stroke="#0fa07f"/>
    </g>
    <g text-anchor="middle">
      <text x="190" y="64" font-size="11.5" font-weight="700" fill="#3553ff">Client</text>
      <text x="190" y="80" font-size="9" fill="currentColor" opacity="0.8">(asks)</text>
      <text x="570" y="64" font-size="11.5" font-weight="700" fill="#0fa07f">Server</text>
      <text x="570" y="80" font-size="9" fill="currentColor" opacity="0.8">(answers)</text>
    </g>
    <!-- lifelines -->
    <g stroke="currentColor" stroke-opacity="0.25" stroke-width="1.3" stroke-dasharray="4 5">
      <path d="M190 90 L190 252"/>
      <path d="M570 90 L570 102"/>
      <path d="M570 126 L570 180"/>
      <path d="M570 204 L570 252"/>
    </g>
    <!-- note over the server: it was started earlier and is idle -->
    <rect x="428" y="102" width="284" height="24" rx="6" fill="#7f7f7f" fill-opacity="0.1" stroke="currentColor" stroke-opacity="0.25" stroke-width="1"/>
    <text x="570" y="118" text-anchor="middle" font-size="9.5" fill="currentColor" opacity="0.8">already running · waiting for a request</text>
    <!-- request: client to server -->
    <text x="380" y="156" text-anchor="middle" font-size="10" fill="currentColor">request · the client asks, unprompted</text>
    <g fill="none" stroke="#3553ff" stroke-width="1.7">
      <path d="M196 163 L564 163" marker-end="url(#p0l11a-arb)"/>
    </g>
    <!-- note over the server: it acts only after being asked -->
    <rect x="442" y="180" width="256" height="24" rx="6" fill="#0fa07f" fill-opacity="0.1" stroke="#0fa07f" stroke-opacity="0.55" stroke-width="1"/>
    <text x="570" y="196" text-anchor="middle" font-size="9.5" fill="currentColor" opacity="0.9">does the work, then replies</text>
    <!-- response: server back to client -->
    <text x="380" y="232" text-anchor="middle" font-size="10" fill="currentColor">response · the server answers</text>
    <g fill="none" stroke="#0fa07f" stroke-width="1.7">
      <path d="M564 239 L196 239" marker-end="url(#p0l11a-arg)"/>
    </g>
    <!-- roles, not hardware -->
    <rect x="60" y="262" width="640" height="38" rx="8" fill="#7f7f7f" fill-opacity="0.07" stroke="currentColor" stroke-opacity="0.22" stroke-width="1"/>
    <g text-anchor="middle" fill="currentColor" font-size="9.5" opacity="0.85">
      <text x="380" y="279">Roles, not hardware — the same laptop is a client when it loads a web page,</text>
      <text x="380" y="293">and a server when it shares a file.</text>
    </g>
    <!-- takeaway -->
    <text x="380" y="322" text-anchor="middle" font-size="10" fill="currentColor" opacity="0.78">A backend is simply a program playing the server role: it starts up, waits, and answers requests.</text>
  </g>
</svg>
```

### The Internet is a network of networks

Your home network is small. A company has its own. A data center has thousands of
machines. The magic is that all these separate networks are **linked together** — and
that's literally what the word means: **inter-net = a network** *of* **networks**.

There is **no central computer** running the internet. It's a vast mesh of independent
networks that agree to pass each other's traffic. When your phone in one country reaches
a server in another, the bytes hop across many networks owned by many different
organizations, cooperating only because they follow the same **rules** (protocols — more
soon).

### Data travels in packets

You might imagine your message flowing across the wire in one continuous stream. It
doesn't. The data is chopped into small chunks called **packets**, and **each packet is
sent independently**. Packets may take different routes and can even arrive out of
order; the receiving machine reassembles them.

Why bother chopping it up?

- **Sharing.** Many conversations share the same wires. Small packets let everyone's
  traffic interleave instead of one big transfer hogging the line.
- **Resilience.** If one packet is lost or one path fails, only that packet is resent —
  not the whole message. Packets can route around problems.

Each packet carries not just a slice of your data but also **addressing information** —
where it's from and where it's going — so the network can steer it. (How that addressing
works — IP addresses — comes in Phase 1.)

### Switches and routers move the packets

Two devices do the steering:

- A **switch** connects devices *within one local network* and passes packets between
  them.
- A **router** connects *different networks* and forwards packets from one toward the
  next, **hop by hop**, until they reach the destination network. The internet is,
  mechanically, a huge chain of routers handing packets along.

### Two numbers that describe any network: bandwidth and latency

People blur these together; they're different, and both matter:

- **Bandwidth** — *how much* data per second the connection can carry. The **width** of
  the pipe. (Measured in bits per second: Mbps, Gbps.)
- **Latency** — *how long* one packet takes to travel there (or there and back). The
  **length** of the pipe. (Measured in milliseconds.)

A fat pipe with high latency (a satellite link) moves lots of data but each round trip
feels slow. A thin pipe with low latency feels snappy but can't move much at once.
Backend performance work is constantly trading against these two.

### Why latency usually hurts more than bandwidth

Here's the counterintuitive part, with real numbers. Round-trip time depends mostly on
*distance* (signals can't beat the speed of light):

| Path | Typical round trip |
|---|---|
| Same data center | ~0.5 ms |
| Same city | ~5 ms |
| Across a continent | ~60 ms |
| Across the world | ~150 ms |

Now suppose loading a page needs **5 sequential round trips** (a **DNS** — domain name
system — lookup, then connect, encrypt, request, a follow-up). Across the world that's 5 × 150 ms = **0.75 seconds of pure
waiting** — before a single useful byte of content, no matter how fat your pipe is.
Bandwidth helps you move *big* payloads; latency taxes every *back-and-forth*. That's why
backend design fights to **reduce round trips** — reusing connections, batching requests,
and caching nearby — a theme you'll see again and again.

### It only works because everyone follows the same rules

Millions of machines from thousands of vendors interoperate only because they agree on
**protocols** — shared rulebooks for how to format and exchange bytes. There are a lot
of rules (how to address a packet, how to ensure delivery, how to speak HTTP), so
they're organized into **layers**, each handling one job and building on the one below. (One
of those rules is how to speak **HTTP** — hypertext transfer protocol — the language of the
web.)

That layered model is the single most useful mental model in all of networking — and
it's the next lesson.

## Think about it

1. Is a "server" a special kind of computer? What actually makes something a server?
2. Why does the network chop your data into packets instead of sending one continuous
   stream? Give both reasons.
3. Your video call has plenty of bandwidth but everyone talks over each other with a
   delay. Which of the two numbers — bandwidth or latency — is the problem?

## Key takeaways

- A **network** is connected computers exchanging bytes; the **Internet** is a *network of
  networks* with no central controller.
- **Client** and **server** are **roles**: the client asks, the server answers. A backend
  is a program playing the server role.
- Data travels in independent **packets** (for sharing and resilience), steered by
  **switches** (within a network) and **routers** (between networks), hop by hop.
- **Bandwidth** (how much per second) and **latency** (how long per trip) are different
  and both matter.
- It all works only because machines follow shared **protocols**, organized into **layers**.

**That completes the Foundations.** Next comes **Phase 1 — Networking & Protocols**, where the
network gets the full treatment: the layered model and every layer with working code, the
protocols that ride on top, and how real servers actually talk to each other.
