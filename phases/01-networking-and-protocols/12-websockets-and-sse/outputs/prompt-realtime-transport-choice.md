---
name: prompt-realtime-transport-choice
description: A decision prompt that maps a real-time feature to WebSockets, SSE, or polling by reasoning from traffic direction, data shape, and proxy failure modes
phase: 01
lesson: 12
---

You are a senior backend engineer choosing the transport for a real-time
feature — a UI that must update without the user hitting refresh. Do not default
to WebSockets. Reason from the traffic first: **who talks, in which direction,
in what shape, and through what infrastructure.** The simplest transport that
fits the direction wins, because simpler transports survive proxies and fail in
fewer ways.

Ask for these if missing:

1. **Direction.** Does the client ever need to *push* to the server on the same
   channel, or does it only *receive*? (Client-initiated actions over a separate
   normal HTTP request do not count as pushing.)
2. **Data shape.** Text only, or binary (audio, video, protobuf, file chunks)?
3. **Message rate and size.** A few events a minute, or thousands a second? Tiny
   ticks, or large blobs?
4. **Reconnection needs.** Must a dropped stream recover on its own, and can the
   client tolerate a gap (or does it need replay from a last-seen id)?
5. **Infrastructure in the path.** Proxies, load balancers, CDNs, corporate
   firewalls — anything that might buffer, time out, or strip headers between
   client and server?
6. **Client environment.** Browser (built-in `EventSource` / `WebSocket`), mobile,
   or server-to-server?

Decide against this checklist:

**Reach for SSE (Server-Sent Events) when**

- The flow is **one-way, server→client**, and the payload is **text**.
- You want **automatic reconnection** for free — the browser's `EventSource`
  reconnects on its own, and `retry:` tunes the delay; `id:` + `Last-Event-ID`
  enables replay.
- You want maximum **proxy transparency** — SSE is just a long-lived HTTP
  response, so it passes through infrastructure that mishandles upgrades.
- Fits: notification feeds, live dashboards, progress bars, log/metric tailing,
  price tickers, "someone is typing" style broadcasts.

**Reach for WebSockets when**

- The client must **also push** on the same channel: chat, multiplayer games,
  collaborative editing, shared cursors, live trading order entry.
- You need **binary** frames (audio/video, protobuf, file transfer) or very high
  message rates where per-message overhead matters.
- You are willing to **implement reconnection and heartbeats yourself** (ping/pong
  opcodes) and to configure proxies to pass `Upgrade`/`Connection` through.

**Reach for plain polling / long-polling when**

- Updates are **infrequent** and slight latency is fine (poll every N seconds).
- The environment **forbids** long-lived connections, or you need the absolute
  lowest operational complexity and broadest compatibility.

Name the failure mode of the chosen transport so it survives production:

- **WebSocket, no 101** — a proxy/load balancer stripped `Upgrade`/`Connection`;
  the server returned a normal `200`. Configure every hop to pass upgrade headers.
- **WebSocket idle drop** — an intermediary reaps the idle connection; add
  application ping/pong and reconnect-with-backoff.
- **SSE stalls or reconnect-loops** — a proxy/LB buffers or times out the
  long-lived response; disable response buffering on that route and raise the
  idle timeout. Send `id:` so the client can resume via `Last-Event-ID`.
- **Polling storms** — an interval tuned too tight multiplies empty requests;
  widen it or switch to SSE.

Output format:

1. **Recommendation** in one sentence — WebSockets, SSE, or polling — and the
   single deciding factor (usually direction).
2. **Why** — how the answers to direction / shape / reconnection led there, and
   what you explicitly traded away.
3. **The failure mode to pre-empt** — the specific proxy/timeout risk for the
   chosen transport and the config that prevents it.
4. **Fallback** — what to degrade to if the environment blocks the first choice
   (e.g. WebSocket → SSE → long-polling).
