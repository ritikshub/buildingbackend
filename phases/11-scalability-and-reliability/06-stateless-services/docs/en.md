# Stateless Services: Where the State Actually Went

> "Stateless" does not mean there is no state. It means no state that only **one** instance has. Scaling a working service from one instance to six is measured here to produce an **85.0% logout rate**, a rate limiter that enforces **600 requests per minute against a written policy of 100**, and a nightly job that runs **126 times instead of 21** — all from code that was correct, tested, and unchanged. This lesson is the inventory of where the state has to go instead, and what each destination actually costs you.

**Type:** Build
**Languages:** Python
**Prerequisites:** [Service Discovery, Client-Side Balancing & Subsetting](../05-service-discovery-and-subsetting/), [Sessions & Secure Cookies](../../07-auth-and-security/05-sessions-and-secure-cookies/)
**Time:** ~70 minutes

## The Problem

The service has been in production for nine months on a single instance and it has been flawless. Today marketing bought a television spot, so at 11:00 you set the replica count to six. The deploy is green. Every health check passes. Then this happens, in this order.

**11:04 — people start getting logged out.** Not everyone, and not consistently. A user signs in, browses two pages, and on the third gets bounced to the login screen. They sign in again and it works. Support tickets say "the site keeps logging me out" and nobody can reproduce it, because reproducing it requires being unlucky in exactly the right way — and on your laptop, running one instance, you are never unlucky.

**11:09 — a shopping cart empties itself.** A customer adds eleven items over four minutes and checks out with two of them. Not zero — two. That detail matters, because "the cart is broken" would be a bug you could find. "The cart is *mostly* broken, sometimes" is a bug that looks like flakiness, and flakiness gets a retry button rather than an investigation.

**11:15 — the rate limiter stops limiting.** Your API (Application Programming Interface) has enforced 100 requests per minute per key since launch. A scraper that has been politely bouncing off that limit all year suddenly gets through. Nobody changed the limiter. Nobody changed the policy. The limit is now 600 per minute and there is no configuration file anywhere that says 600.

**11:31 — uploaded files 404.** A user uploads a profile photo, sees it render, refreshes, and gets a broken image. Refreshes again and it is back. The file is on disk — you can SSH in and `ls` it. It is just on the disk of one machine out of six, and the load balancer does not know or care which.

**02:00 — the nightly job runs, and every customer receives six invoice emails.** Six charges are attempted. Six rows are written. The job is a scheduler inside the application process, and there are now six application processes, and every one of them woke up at 02:00 and did its job perfectly.

Five different bugs, five different subsystems, five different on-call engineers. They are the same bug. Every one of them is a piece of state that lives inside one process, on a fleet where the balancer will not send the next request to that process. **The second instance is where the state you forgot about announces itself** — and it announces itself as five unrelated incidents rather than one, which is why this is so often diagnosed slowly.

The tests did not catch any of it, and that is not negligence. The test environment runs one instance, and at one instance every one of these behaviours is *correct*. There is no unit test you could have written, because the bug is not in a unit. It is in the arithmetic of routing, and routing has no opinion about your code.

## The Concept

### The definition that is actually useful

The textbook definition — "a stateless service stores no state" — is false about every service you will ever run. Your service stores state. It has a database. Here is the definition that survives contact with production:

> **A service is stateless if any instance can serve any request, and losing an instance loses nothing but the work currently in flight.**

Two clauses, both load-bearing. *Any instance can serve any request* means the balancer is free — it can route on load, on latency, on whatever Lesson 3 taught it, and never has to ask "does this instance know this user?" *Losing an instance loses nothing* means a `SIGTERM`, a spot-instance reclamation, a node failure, or a rolling deploy costs you only the requests currently executing, which retry.

The corollary is the whole lesson: **the state did not disappear.** It exists, someone must hold it, and if it is not the instance then it is something else. So name that something. The rest of this section is the inventory, and the honest accounting of the bill each destination sends you.

This constraint is not new. It is the *stateless* constraint of REST — Fielding, *Architectural Styles and the Design of Network-based Software Architectures* (UC Irvine, 2000), §5.1.3 — and it is why HTTP (HyperText Transfer Protocol) itself carries every request's full context in the request. HTTP was designed this way in 1991 for reasons of intermediary caching and visibility. You get horizontal scaling as a side effect, and only if you do not fight the design.

The two failures from the incident are worth measuring before anything else, because both have the same shape and neither has anything to do with load:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 430" width="100%" style="max-width:840px" role="img" aria-label="Two measured bar charts. On the left, the fraction of authenticated requests that return 401 when sessions live in process memory, plotted against the number of instances: 0 percent at one instance, 50 percent at two, 70 at three, 75 at four, 85 at six and 95 at twelve. On the right, the rate limit a fleet actually enforces when each instance keeps its own counter: 100 per minute at one instance rising to 1600 per minute at sixteen, against a written policy of 100 per minute drawn as a flat green line. Neither failure depends on load; both scale with instance count.">
  <text x="440" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">Both bugs scale with the fleet, not with the traffic</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <text x="235" y="52" text-anchor="middle" font-size="11" font-weight="700" fill="#d64545">sessions in a dict: share of requests that 401</text>
    <text x="665" y="52" text-anchor="middle" font-size="11" font-weight="700" fill="#d64545">counter in a dict: rate limit actually enforced</text>

    <g fill="none" stroke="currentColor" stroke-width="1.5">
      <path d="M60 300 L 410 300"/><path d="M60 300 L 60 76"/>
      <path d="M490 300 L 850 300"/><path d="M490 300 L 490 76"/>
    </g>
    <g fill="none" stroke="currentColor" stroke-width="1" opacity="0.35">
      <path d="M60 244 L 410 244"/><path d="M60 188 L 410 188"/><path d="M60 132 L 410 132"/><path d="M60 76 L 410 76"/>
      <path d="M490 244 L 850 244"/><path d="M490 188 L 850 188"/><path d="M490 132 L 850 132"/><path d="M490 76 L 850 76"/>
    </g>

    <g stroke-width="1.6">
      <rect x="75" y="299" width="34" height="1" fill="#0fa07f" stroke="#0fa07f"/>
      <rect x="128" y="188" width="34" height="112" fill="#d64545" fill-opacity="0.32" stroke="#d64545"/>
      <rect x="181" y="143" width="34" height="157" fill="#d64545" fill-opacity="0.32" stroke="#d64545"/>
      <rect x="234" y="132" width="34" height="168" fill="#d64545" fill-opacity="0.32" stroke="#d64545"/>
      <rect x="287" y="110" width="34" height="190" fill="#d64545" fill-opacity="0.42" stroke="#d64545"/>
      <rect x="340" y="87" width="34" height="213" fill="#d64545" fill-opacity="0.32" stroke="#d64545"/>
    </g>
    <g fill="currentColor" font-size="9.5" text-anchor="middle" font-weight="700">
      <text x="92" y="292" fill="#0fa07f">0.0%</text><text x="145" y="182">50.0%</text><text x="198" y="137">70.0%</text><text x="251" y="126">75.0%</text><text x="304" y="104" fill="#d64545">85.0%</text><text x="357" y="81">95.0%</text>
    </g>
    <g fill="currentColor" font-size="9.5" text-anchor="middle" opacity="0.85">
      <text x="92" y="316">1</text><text x="145" y="316">2</text><text x="198" y="316">3</text><text x="251" y="316">4</text><text x="304" y="316">6</text><text x="357" y="316">12</text>
    </g>
    <g fill="currentColor" font-size="9" text-anchor="end" opacity="0.7">
      <text x="54" y="304">0%</text><text x="54" y="248">25%</text><text x="54" y="192">50%</text><text x="54" y="136">75%</text><text x="54" y="80">100%</text>
    </g>

    <g stroke-width="1.6">
      <rect x="505" y="286" width="34" height="14" fill="#e0930f" fill-opacity="0.30" stroke="#e0930f"/>
      <rect x="558" y="272" width="34" height="28" fill="#d64545" fill-opacity="0.30" stroke="#d64545"/>
      <rect x="611" y="244" width="34" height="56" fill="#d64545" fill-opacity="0.30" stroke="#d64545"/>
      <rect x="664" y="216" width="34" height="84" fill="#d64545" fill-opacity="0.42" stroke="#d64545"/>
      <rect x="717" y="188" width="34" height="112" fill="#d64545" fill-opacity="0.30" stroke="#d64545"/>
      <rect x="770" y="76" width="34" height="224" fill="#d64545" fill-opacity="0.30" stroke="#d64545"/>
    </g>
    <path d="M490 286 L 850 286" fill="none" stroke="#0fa07f" stroke-width="2" stroke-dasharray="6 4"/>
    <path d="M502 92 L 530 92" fill="none" stroke="#0fa07f" stroke-width="2" stroke-dasharray="6 4"/>
    <text x="536" y="96" font-size="9.5" font-weight="700" fill="#0fa07f">the policy you wrote: 100/min</text>
    <g fill="currentColor" font-size="9.5" text-anchor="middle" font-weight="700">
      <text x="522" y="280">100</text><text x="575" y="266">200</text><text x="628" y="238">400</text><text x="681" y="210" fill="#d64545">600</text><text x="734" y="182">800</text><text x="787" y="70">1600</text>
    </g>
    <g fill="currentColor" font-size="9.5" text-anchor="middle" opacity="0.85">
      <text x="522" y="316">1</text><text x="575" y="316">2</text><text x="628" y="316">4</text><text x="681" y="316">6</text><text x="734" y="316">8</text><text x="787" y="316">16</text>
    </g>
    <g fill="currentColor" font-size="9" text-anchor="end" opacity="0.7">
      <text x="484" y="304">0</text><text x="484" y="248">400</text><text x="484" y="192">800</text><text x="484" y="136">1200</text><text x="484" y="80">1600</text>
    </g>

    <text x="235" y="338" font-size="10" text-anchor="middle" fill="currentColor" opacity="0.85">instances behind the balancer</text>
    <text x="665" y="338" font-size="10" text-anchor="middle" fill="currentColor" opacity="0.85">instances behind the balancer</text>

    <g fill="none" stroke-width="1.8">
      <rect x="60" y="356" width="790" height="42" rx="9" fill="#e0930f" fill-opacity="0.11" stroke="#e0930f"/>
    </g>
    <g fill="currentColor" font-size="10">
      <text x="76" y="374"><tspan font-weight="700" fill="#e0930f">The test suite runs one instance.</tspan> At N = 1 the logout rate is 0.0% and the limiter enforces exactly 100/min.</text>
      <text x="76" y="390">Both numbers are correct, both are measured, and neither of them is about your code.</text>
    </g>
    <text x="440" y="418" font-size="11" text-anchor="middle" fill="currentColor" opacity="0.9">Round-robin returns 1 request in N to the instance holding the session: the 401 rate is 1 - floor(20/N)/20, exactly.</text>
  </g>
</svg>
```

Read the left panel as an argument about testing. At one instance the logout rate is **0.0%**. At two it is **50.0%**. There is no gradual degradation, no warning band, no "we noticed it getting worse" — the bug arrives at full strength the moment a second process exists. And the arithmetic is exact rather than statistical: with strict round-robin, one request in every N returns to the instance that holds the session, so the failure rate is `1 − floor(20/N)/20` for a 20-request user session. At six instances that is **85.0%**, measured.

The right panel is the same shape with a different symptom. The limiter's *code* is correct; every instance faithfully enforces 100 per minute. There are six of them, so the policy the outside world experiences is 600 per minute, and at sixteen instances it is **1,600** — a number that appears in no config file and no design document. Your rate limit silently became a function of your autoscaler.

### The inventory of hidden state

This is the part to keep. Ten places state hides, what each does to a fleet of six, and where it has to go instead.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 536" width="100%" style="max-width:840px" role="img" aria-label="An inventory of ten kinds of state that live in one process, each with the symptom it produces on a fleet of six instances and the shared service it has to move to. Sessions in a dict produce an eighty-five percent 401 rate; an in-memory cache makes six instances hold six different answers; in-memory rate-limit counters enforce six hundred per minute instead of one hundred; files on local disk 404 on five reads in six; a threading lock excludes one process out of six; an in-process scheduler runs the job one hundred and twenty-six times instead of twenty-one; an in-memory dedupe set lets a retry charge the customer twice; a WebSocket connection map drops messages between instances; a sequential id counter collides; and mutated feature flags make behaviour depend on routing. Every row moves to a shared store, object storage, a distributed lock with a fencing token, a lease-based leader, pub/sub, or a config service.">
  <text x="440" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">The inventory: state is never deleted, only moved — and the move has a bill</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <g fill="currentColor" font-size="9" font-weight="700" opacity="0.65">
      <text x="42" y="58">STATE THAT LIVES IN ONE PROCESS</text><text x="318" y="58">WHAT IT DOES TO A FLEET OF SIX</text><text x="634" y="58">WHERE IT HAS TO MOVE</text>
    </g>
    <path d="M32 64 L 848 64" fill="none" stroke="currentColor" stroke-width="1.2" opacity="0.4"/>

    <g fill="none" stroke-width="1.6">
      <rect x="32" y="70" width="272" height="38" rx="7" fill="#e0930f" fill-opacity="0.12" stroke="#e0930f"/>
      <rect x="32" y="114" width="272" height="38" rx="7" fill="#e0930f" fill-opacity="0.12" stroke="#e0930f"/>
      <rect x="32" y="158" width="272" height="38" rx="7" fill="#e0930f" fill-opacity="0.12" stroke="#e0930f"/>
      <rect x="32" y="202" width="272" height="38" rx="7" fill="#e0930f" fill-opacity="0.12" stroke="#e0930f"/>
      <rect x="32" y="246" width="272" height="38" rx="7" fill="#e0930f" fill-opacity="0.12" stroke="#e0930f"/>
      <rect x="32" y="290" width="272" height="38" rx="7" fill="#e0930f" fill-opacity="0.12" stroke="#e0930f"/>
      <rect x="32" y="334" width="272" height="38" rx="7" fill="#e0930f" fill-opacity="0.12" stroke="#e0930f"/>
      <rect x="32" y="378" width="272" height="38" rx="7" fill="#e0930f" fill-opacity="0.12" stroke="#e0930f"/>
      <rect x="32" y="422" width="272" height="38" rx="7" fill="#e0930f" fill-opacity="0.12" stroke="#e0930f"/>
      <rect x="32" y="466" width="272" height="38" rx="7" fill="#e0930f" fill-opacity="0.12" stroke="#e0930f"/>
    </g>
    <g fill="none" stroke-width="1.6">
      <rect x="628" y="70" width="220" height="38" rx="7" fill="#0fa07f" fill-opacity="0.12" stroke="#0fa07f"/>
      <rect x="628" y="114" width="220" height="38" rx="7" fill="#0fa07f" fill-opacity="0.12" stroke="#0fa07f"/>
      <rect x="628" y="158" width="220" height="38" rx="7" fill="#0fa07f" fill-opacity="0.12" stroke="#0fa07f"/>
      <rect x="628" y="202" width="220" height="38" rx="7" fill="#0fa07f" fill-opacity="0.12" stroke="#0fa07f"/>
      <rect x="628" y="246" width="220" height="38" rx="7" fill="#0fa07f" fill-opacity="0.12" stroke="#0fa07f"/>
      <rect x="628" y="290" width="220" height="38" rx="7" fill="#0fa07f" fill-opacity="0.12" stroke="#0fa07f"/>
      <rect x="628" y="334" width="220" height="38" rx="7" fill="#0fa07f" fill-opacity="0.12" stroke="#0fa07f"/>
      <rect x="628" y="378" width="220" height="38" rx="7" fill="#0fa07f" fill-opacity="0.12" stroke="#0fa07f"/>
      <rect x="628" y="422" width="220" height="38" rx="7" fill="#0fa07f" fill-opacity="0.12" stroke="#0fa07f"/>
      <rect x="628" y="466" width="220" height="38" rx="7" fill="#0fa07f" fill-opacity="0.12" stroke="#0fa07f"/>
    </g>

    <g fill="currentColor" font-size="10">
      <text x="44" y="88" font-weight="700">sessions in a dict</text><text x="44" y="101" font-size="8.5" opacity="0.75">self.sessions[sid] = user</text>
      <text x="44" y="132" font-weight="700">an in-memory cache</text><text x="44" y="145" font-size="8.5" opacity="0.75">@lru_cache, a module-level dict</text>
      <text x="44" y="176" font-weight="700">rate-limit counters</text><text x="44" y="189" font-size="8.5" opacity="0.75">hits[key] += 1</text>
      <text x="44" y="220" font-weight="700">files on local disk</text><text x="44" y="233" font-size="8.5" opacity="0.75">uploads, generated PDFs, SQLite</text>
      <text x="44" y="264" font-weight="700">threading.Lock()</text><text x="44" y="277" font-size="8.5" opacity="0.75">with self.lock:</text>
      <text x="44" y="308" font-weight="700">an in-process scheduler</text><text x="44" y="321" font-size="8.5" opacity="0.75">a cron thread inside the app</text>
      <text x="44" y="352" font-weight="700">idempotency / dedupe keys</text><text x="44" y="365" font-size="8.5" opacity="0.75">seen = set()</text>
      <text x="44" y="396" font-weight="700">WebSocket connection map</text><text x="44" y="409" font-size="8.5" opacity="0.75">self.clients[user] = socket</text>
      <text x="44" y="440" font-weight="700">a sequential id counter</text><text x="44" y="453" font-size="8.5" opacity="0.75">self.next_id += 1</text>
      <text x="44" y="484" font-weight="700">mutated config / flags</text><text x="44" y="497" font-size="8.5" opacity="0.75">FLAGS["x"] = True at runtime</text>
    </g>

    <g fill="currentColor" font-size="9">
      <text x="318" y="86" font-weight="700" fill="#d64545">85.0% of authenticated requests 401 (measured)</text><text x="318" y="99" opacity="0.85">1 request in N lands on the instance that has you</text>
      <text x="318" y="130" font-weight="700" fill="#d64545">six instances hold six different answers</text><text x="318" y="143" opacity="0.85">an invalidation reaches 1 of 6; reads flip versions</text>
      <text x="318" y="174" font-weight="700" fill="#d64545">the 100/min policy is enforced as 600/min</text><text x="318" y="187" opacity="0.85">measured; 1600/min once the autoscaler reaches 16</text>
      <text x="318" y="218" font-weight="700" fill="#d64545">the file exists on 1 instance, so 5 reads in 6 404</text><text x="318" y="231" opacity="0.85">and scale-in deletes the only copy, permanently</text>
      <text x="318" y="262" font-weight="700" fill="#d64545">excludes 1 process, permits the other 5</text><text x="318" y="275" opacity="0.85">the critical section is only critical locally</text>
      <text x="318" y="306" font-weight="700" fill="#d64545">126 executions for 21 ticks (measured)</text><text x="318" y="319" opacity="0.85">six invoices, six emails, six charges, per tick</text>
      <text x="318" y="350" font-weight="700" fill="#d64545">the retry lands elsewhere and the key is absent</text><text x="318" y="363" opacity="0.85">so the safe-to-retry POST charges the card twice</text>
      <text x="318" y="394" font-weight="700" fill="#d64545">a publish on instance 3 never reaches instance 5</text><text x="318" y="407" opacity="0.85">delivery becomes 1-in-N instead of at-least-once</text>
      <text x="318" y="438" font-weight="700" fill="#d64545">six instances all hand out id 1</text><text x="318" y="451" opacity="0.85">primary-key collisions, or silent overwrites</text>
      <text x="318" y="482" font-weight="700" fill="#d64545">the flag is on for 1 instance in 6</text><text x="318" y="495" opacity="0.85">behaviour depends on routing; bugs never reproduce</text>
    </g>

    <g fill="currentColor" font-size="9">
      <text x="640" y="86" font-weight="700" fill="#0fa07f">shared session store</text><text x="640" y="99" opacity="0.8">or a signed token (Ph 7 L06)</text>
      <text x="640" y="130" font-weight="700" fill="#0fa07f">shared cache tier</text><text x="640" y="143" opacity="0.8">+ pub/sub invalidation (Ph 5)</text>
      <text x="640" y="174" font-weight="700" fill="#0fa07f">one shared counter</text><text x="640" y="187" opacity="0.8">atomic INCR + TTL (Ph 2 L09)</text>
      <text x="640" y="218" font-weight="700" fill="#0fa07f">object storage</text><text x="640" y="231" opacity="0.8">S3-compatible, versioned</text>
      <text x="640" y="262" font-weight="700" fill="#0fa07f">distributed lock</text><text x="640" y="275" opacity="0.8">+ a FENCING TOKEN, always</text>
      <text x="640" y="306" font-weight="700" fill="#0fa07f">leader election</text><text x="640" y="319" opacity="0.8">a renewable lease, + fencing</text>
      <text x="640" y="350" font-weight="700" fill="#0fa07f">shared idempotency store</text><text x="640" y="363" opacity="0.8">TTL &gt;= the client retry window</text>
      <text x="640" y="394" font-weight="700" fill="#0fa07f">pub/sub fan-out</text><text x="640" y="407" opacity="0.8">every instance subscribes (Ph 6)</text>
      <text x="640" y="438" font-weight="700" fill="#0fa07f">DB sequence or UUIDv7</text><text x="640" y="451" opacity="0.8">no coordination per id</text>
      <text x="640" y="482" font-weight="700" fill="#0fa07f">config service, read-only</text><text x="640" y="495" opacity="0.8">pulled at boot, versioned</text>
    </g>
    <text x="440" y="526" font-size="11" text-anchor="middle" fill="currentColor" opacity="0.9">The left column is free and wrong. The right column is correct and is now a dependency you must run, size and page for.</text>
  </g>
</svg>
```

A few rows deserve more than a table cell.

**In-memory caches are the sneakiest**, because they do not fail — they *disagree*. Six instances each cache the product price independently, a price changes, and the invalidation message reaches exactly the instance that processed it. Now one user in six sees the new price and refreshing the page flips between the two, which is far worse than a stale cache everywhere, because at least a uniformly stale cache is *consistent* and expires. [Invalidation & TTLs](../../05-caching/05-invalidation-and-ttls/) covers cache strategy properly; the fleet-specific point is only this: a per-instance cache multiplies your invalidation problem by the instance count, and the number of instances is not a constant.

**Local locks protect nothing.** `threading.Lock` is a promise about one process's threads. On six instances you have six locks, each perfectly excluding one sixth of your concurrency. The most dangerous version is the check-then-act that "was fine" for a year: `if not exists(x): create(x)` under a local lock creates `x` up to six times.

**In-memory idempotency keys are the expensive one.** Phase 2's [Idempotency & Safe Retries](../../02-api-design/07-idempotency-safe-retries/) builds the key mechanism; the fleet failure is that a retry is, by design, a *new connection* and therefore usually a *different instance*. A dedupe `set()` in memory is checked on an instance that has never heard of the key, so the duplicate charge goes through — and the entire point of the idempotency key was to prevent exactly that.

**WebSocket connection maps break in a way that produces no errors at all.** A user's browser holds a long-lived socket to instance 5 ([WebSockets & SSE](../../01-networking-and-protocols/12-websockets-and-sse/)). Another user posts a chat message and that HTTP request lands on instance 3. Instance 3 looks up the recipient in its own connection map, finds nothing, and returns `200 OK`. Nothing logs. The message is simply never delivered, to roughly `(N−1)/N` of recipients.

### Sticky sessions: the tempting fix that transfers the problem

There is an obvious fix, and every load balancer ships it: make the balancer send a user back to the same instance every time. This is **session affinity**, or "sticky sessions", and it comes in two forms. **Cookie-based** affinity has the balancer set its own cookie naming the chosen backend, then reads it on later requests. **IP-hash** affinity hashes the client's source address to a backend and stores nothing — which sounds elegant until you remember that mobile clients change addresses mid-session and that whole corporate networks arrive from one NAT (Network Address Translation) address.

It works. The 85% logout rate goes to zero. It also transfers the problem into four new ones, and here are all four, measured.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 492" width="100%" style="max-width:840px" role="img" aria-label="Measured sticky-session load across six instances and what a routine scale-in destroys. The top panel shows the requests each instance carries under session affinity: 9526, 11038, 9536, 7066, 9412 and 9020, a max over min ratio of 1.56, against a flat green line at 9266 to 9267 requests which is what per-request routing achieves on every instance. Instances five and six are terminated by the autoscaler and drawn crossed out in red; the 18432 requests and 1361 sessions pinned to them are destroyed. The bottom panel compares sessions lost by affinity mechanism: hash of cookie modulo N loses 66.6 percent because every key rehashes, consistent hashing loses 34.0 percent which is only the removed instances' share, and a stateless fleet with a shared store loses zero.">
  <text x="440" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">Sticky sessions: the skew you buy, and what one scale-in destroys</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <text x="60" y="50" font-size="11" font-weight="700" fill="currentColor" opacity="0.85">measured load per instance — 4,000 sessions, 55,598 requests, affinity by session id</text>

    <path d="M62 66 L 90 66" fill="none" stroke="#0fa07f" stroke-width="2" stroke-dasharray="6 4"/>
    <text x="98" y="70" font-size="9.5" font-weight="700" fill="#0fa07f">stateless, per-request routing: 9,266 – 9,267 on every instance — max/min 1.00x</text>
    <rect x="62" y="80" width="28" height="9" rx="2" fill="#e0930f" fill-opacity="0.18" stroke="#e0930f" stroke-width="1.4"/>
    <text x="98" y="88" font-size="9.5" font-weight="700" fill="#e0930f">sticky: busiest 11,038, quietest 7,066 — max/min 1.56x, and you cannot split a session</text>

    <path d="M50 262 L 820 262" fill="none" stroke="currentColor" stroke-width="1.5"/>
    <g stroke-width="1.8">
      <rect x="60" y="141" width="90" height="121" fill="#7c5cff" fill-opacity="0.14" stroke="#7c5cff"/>
      <rect x="190" y="122" width="90" height="140" fill="#e0930f" fill-opacity="0.18" stroke="#e0930f"/>
      <rect x="320" y="141" width="90" height="121" fill="#7c5cff" fill-opacity="0.14" stroke="#7c5cff"/>
      <rect x="450" y="172" width="90" height="90" fill="#e0930f" fill-opacity="0.18" stroke="#e0930f"/>
      <rect x="580" y="143" width="90" height="119" fill="#d64545" fill-opacity="0.20" stroke="#d64545"/>
      <rect x="710" y="148" width="90" height="114" fill="#d64545" fill-opacity="0.20" stroke="#d64545"/>
    </g>
    <g stroke="#d64545" stroke-width="2.2" fill="none" opacity="0.9">
      <path d="M588 151 L 662 254"/><path d="M662 151 L 588 254"/>
      <path d="M718 156 L 792 254"/><path d="M792 156 L 718 254"/>
    </g>
    <path d="M50 144 L 820 144" fill="none" stroke="#0fa07f" stroke-width="2" stroke-dasharray="6 4"/>

    <g fill="currentColor" font-size="10" text-anchor="middle" font-weight="700">
      <text x="105" y="135">9,526</text><text x="235" y="116">11,038</text><text x="365" y="135">9,536</text><text x="495" y="166">7,066</text><text x="625" y="137" fill="#d64545">9,412</text><text x="755" y="142" fill="#d64545">9,020</text>
    </g>
    <g fill="currentColor" font-size="9.5" text-anchor="middle" opacity="0.9">
      <text x="105" y="278">inst-1</text><text x="235" y="278">inst-2</text><text x="365" y="278">inst-3</text><text x="495" y="278">inst-4</text>
      <text x="625" y="278" fill="#d64545" font-weight="700">inst-5</text><text x="755" y="278" fill="#d64545" font-weight="700">inst-6</text>
    </g>
    <text x="820" y="298" font-size="10" text-anchor="end" font-weight="700" fill="#d64545">SIGTERM 02:14 — the autoscaler scaled 6 → 4. Nothing had failed.</text>

    <path d="M50 318 L 820 318" fill="none" stroke="currentColor" stroke-width="1" opacity="0.35"/>
    <text x="60" y="338" font-size="11" font-weight="700" fill="currentColor" opacity="0.85">sessions destroyed by that one scale-in, by affinity mechanism</text>

    <g stroke-width="1.8">
      <rect x="300" y="352" width="266" height="24" rx="4" fill="#d64545" fill-opacity="0.22" stroke="#d64545"/>
      <rect x="300" y="388" width="136" height="24" rx="4" fill="#e0930f" fill-opacity="0.20" stroke="#e0930f"/>
      <rect x="300" y="424" width="3" height="24" rx="1" fill="#0fa07f" fill-opacity="0.30" stroke="#0fa07f"/>
    </g>
    <g fill="currentColor" font-size="10" font-weight="700" text-anchor="end">
      <text x="290" y="368">hash(cookie) % N</text><text x="290" y="404">consistent hashing</text><text x="290" y="440">stateless + shared store</text>
    </g>
    <g font-size="10" font-weight="700">
      <text x="576" y="368" fill="#d64545">66.6% — 2,663 sessions, 36,246 requests</text>
      <text x="446" y="404" fill="#e0930f">34.0% — 1,361 sessions, 18,432 requests</text>
      <text x="313" y="440" fill="#0fa07f">0.0% — nothing was pinned to anything</text>
    </g>
    <text x="440" y="476" font-size="11" text-anchor="middle" fill="currentColor" opacity="0.9">A rolling deploy restarts all six, so it destroys 100%. Affinity is a cache optimisation, not a correctness mechanism.</text>
  </g>
</svg>
```

**One — load skews, because sessions are not uniform.** Per-request routing splits 55,598 requests into six piles of 9,266 or 9,267: a max/min ratio of **1.00x**. Affinity cannot split a session, so it distributes *sessions* and hopes the requests follow. They do not, because real session weights are heavy-tailed — most users click twice and a few never leave. Measured: the busiest instance carried **11,038** requests and the quietest **7,066**, a **1.56x** imbalance, with the single hottest session accounting for **6.4%** of its instance's entire load. You now provision for the busiest instance and pay for the difference on all six.

**Two — scale-in destroys sessions.** This is the serious one. Take those six instances down to four, which is a routine, successful, unremarkable autoscaler action at 02:14 on a Sunday. Everything pinned to the two departing instances is gone. Measured with consistent hashing: **1,361 of 4,000 sessions destroyed — 34.0%**, carrying **18,432 requests, 33.2%** of the traffic. And if your affinity is the naive `hash(cookie) % N` — which is what you write if nobody tells you otherwise — then changing N rehashes *everything*, and the loss is **66.6% of sessions and 65.2% of requests**. Two thirds of your users logged out by a scale-in event that your monitoring will record as a success.

**Three — deploys become disruptive for exactly the same reason.** A rolling deploy replaces every instance. That is not 34%; it is **100%**, spread over the rollout window. Phase 10's deployment strategies assume instances are disposable; sticky sessions withdraw that assumption, which is how a team ends up doing deploys at 3am for a stateless web tier that did not need to be stateful in the first place.

**Four — a hot user pins to a single instance.** One customer running an aggressive integration is one session, and one session is one instance. You cannot spread that load without breaking the affinity that is holding their session together. The balancer's cleverest algorithm is powerless against a routing decision that was already made.

**The honest verdict:** affinity is fine, even good, as a **cache-locality optimisation** — routing a user to the instance whose local cache is already warm for them genuinely reduces latency and backend load, and if the routing changes you lose warmth, not correctness. Affinity is **unacceptable as a correctness mechanism**, because it converts every instance into a single point of failure for the users pinned to it, and instances are supposed to be the disposable part.

If you do want affinity, use the version Lesson 3 built: **consistent hashing with bounded loads** (Karger et al., *Consistent Hashing and Random Trees*, STOC 1997; Mirrokni, Thorup & Zadimoghaddam, *Consistent Hashing with Bounded Loads*, SODA 2018). It halves the disruption on a topology change (34.0% versus 66.6%, measured) and its load bound directly attacks the 1.56x skew. It is strictly the better mechanism — and it still loses a third of your sessions on a scale-in, which is why it is an optimisation and not an answer.

### Where session state can live, compared

Three options. Phase 7 built two of them — [Sessions & Secure Cookies](../../07-auth-and-security/05-sessions-and-secure-cookies/) for the cookie mechanics and [JWT & Token Auth](../../07-auth-and-security/06-jwt-and-token-auth/) for the token format and its signing. None of that is repeated here. The fleet question is different: **who does the reading, and how fast can you take access away?**

| | client-side token | server-side session store | hybrid (token + denylist) |
|---|---|---|---|
| where the state is | in the client's cookie/header | in Redis/Postgres/DynamoDB | signed token, shared revocation list |
| store reads per request | 0 (only at refresh) | 1, always | 1 per instance per refresh interval |
| **measured lookups / 1000 req** | **177.9** (15-min TTL) | **1000.0** | **202.7** (30 s denylist pull) |
| size on the wire | 300–1000+ bytes, every request | ~40 bytes | 300–1000+ bytes |
| store outage means | logins fail, sessions survive | **everything fails** | logins fail, denylist goes stale |
| **revocation** | **impossible before expiry** | immediate, next request | bounded by the pull interval |
| **measured revocation window** | **880 s** (15-min TTL) | **0 s** | **29 s** |

The row everybody forgets is the bold one. **A signed token cannot be un-issued.** It is a bearer credential that any instance will accept because the signature is valid, and validity is a property of the token, not of your opinion of the user. That means logout, a permission downgrade, a fired employee, and a leaked credential all have the same answer: *you wait*. Measured, with a 15-minute TTL (Time To Live) and 120 users revoked mid-hour, revoked users made **1,130 further successful requests**, and the worst case kept access for **880 seconds** — just under the full 15 minutes, exactly as the arithmetic requires.

The trade is continuous, not a choice between two designs:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 478" width="100%" style="max-width:840px" role="img" aria-label="A measured trade-off curve plotting the worst-case revocation window in seconds against store lookups per one thousand requests, from a simulated hour of 29012 requests across 400 users on six instances. A server-side session store sits at 1000 lookups per 1000 requests with a zero second revocation window. Signed tokens move down the curve as their TTL grows: 434.8 lookups and a 54 second window at a 60 second TTL, 251.1 lookups and 281 seconds at 300 seconds, 177.9 lookups and 880 seconds at 900 seconds, and 90.5 lookups with a 3121 second window at a one hour TTL, which is off the top of the chart. A hybrid of a 15-minute token plus a denylist pulled every 30 seconds sits off the curve at 202.7 lookups and a 29 second window, buying the window back by putting load back on the store.">
  <defs>
    <marker id="p11-06-c1" markerWidth="10" markerHeight="10" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#3553ff"/></marker>
  </defs>
  <text x="440" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">You do not choose a token or a store. You choose a point on this curve.</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <text x="440" y="46" text-anchor="middle" font-size="10" fill="currentColor" opacity="0.8">measured: 400 users, 29,012 requests over one simulated hour, 6 instances, 120 users revoked mid-hour</text>

    <g fill="none" stroke="currentColor" stroke-width="1.5">
      <path d="M110 350 L 830 350"/><path d="M110 350 L 110 74"/>
    </g>
    <g fill="none" stroke="currentColor" stroke-width="1" opacity="0.28">
      <path d="M110 298 L 830 298"/><path d="M110 246 L 830 246"/><path d="M110 194 L 830 194"/><path d="M110 142 L 830 142"/><path d="M110 90 L 830 90"/>
      <path d="M254 74 L 254 350"/><path d="M398 74 L 398 350"/><path d="M542 74 L 542 350"/><path d="M686 74 L 686 350"/>
    </g>

    <path d="M175 84 C 210 200, 238 292, 293 328 C 400 346, 560 350, 826 350" fill="none" stroke="#3553ff" stroke-width="2.2" stroke-dasharray="7 5" opacity="0.75"/>

    <g fill="#3553ff" fill-opacity="0.30" stroke="#3553ff" stroke-width="2">
      <circle cx="830" cy="350" r="6.5"/>
      <circle cx="423" cy="336" r="6.5"/>
      <circle cx="291" cy="277" r="6.5"/>
      <circle cx="238" cy="121" r="6.5"/>
    </g>
    <g fill="#e0930f" fill-opacity="0.30" stroke="#e0930f" stroke-width="2">
      <circle cx="175" cy="82" r="6.5"/>
    </g>
    <g fill="#0fa07f" fill-opacity="0.35" stroke="#0fa07f" stroke-width="2.4">
      <circle cx="256" cy="343" r="7.5"/>
    </g>

    <g fill="currentColor" font-size="9.5">
      <text x="822" y="306" text-anchor="end" font-weight="700" fill="#3553ff">server-side session store</text>
      <text x="822" y="318" text-anchor="end" opacity="0.85">1000 lookups / 1000 req · window 0 s</text>
      <text x="822" y="330" text-anchor="end" opacity="0.85">every single request pays the store</text>
      <text x="437" y="320" font-weight="700" fill="#3553ff">token, TTL 60 s</text>
      <text x="437" y="332" opacity="0.85">434.8 lookups · 54 s</text>
      <text x="305" y="262" font-weight="700" fill="#3553ff">token, TTL 300 s</text>
      <text x="305" y="274" opacity="0.85">251.1 lookups · 281 s</text>
      <text x="252" y="112" font-weight="700" fill="#3553ff">token, TTL 900 s</text>
      <text x="252" y="124" opacity="0.85">177.9 lookups · 880 s</text>
      <text x="190" y="72" font-weight="700" fill="#e0930f">token, TTL 3600 s → 90.5 lookups, window 3121 s (off the chart)</text>
    </g>

    <path d="M330 408 L 266 356" fill="none" stroke="#0fa07f" stroke-width="1.6" marker-end="url(#p11-06-c1)"/>
    <g fill="currentColor" font-size="9.5">
      <text x="338" y="404" font-weight="700" fill="#0fa07f">hybrid: 15-min token + a denylist pulled every 30 s</text>
      <text x="338" y="417" opacity="0.9">202.7 lookups / 1000 req · window 29 s — it leaves the curve,</text>
      <text x="338" y="430" opacity="0.9">and it pays for that with load on the store you were avoiding.</text>
    </g>

    <g fill="currentColor" font-size="9" text-anchor="end" opacity="0.75">
      <text x="102" y="354">0</text><text x="102" y="302">200</text><text x="102" y="250">400</text><text x="102" y="198">600</text><text x="102" y="146">800</text><text x="102" y="94">1000</text>
    </g>
    <text x="46" y="212" font-size="10" transform="rotate(-90 46 212)" text-anchor="middle" fill="currentColor" opacity="0.85">worst-case revocation window (s)</text>
    <g fill="currentColor" font-size="9" text-anchor="middle" opacity="0.75">
      <text x="110" y="368">0</text><text x="254" y="368">200</text><text x="398" y="368">400</text><text x="542" y="368">600</text><text x="686" y="368">800</text><text x="830" y="368">1000</text>
    </g>
    <text x="470" y="386" font-size="10" text-anchor="middle" fill="currentColor" opacity="0.85">store lookups per 1,000 requests</text>

    <text x="822" y="150" font-size="9.5" font-weight="700" text-anchor="end" fill="#d64545">up and to the left: fewer store lookups,</text>
    <text x="822" y="163" font-size="9.5" font-weight="700" text-anchor="end" fill="#d64545">and longer that a revoked user still works</text>

    <text x="440" y="460" font-size="11" text-anchor="middle" fill="currentColor" opacity="0.9">A signed token cannot be un-issued. Revocation is bought with either a short TTL or a shared lookup — there is no third option.</text>
  </g>
</svg>
```

Walk the curve. A **60-second** token costs **434.8 lookups per 1,000 requests** and holds the revocation window to **54 seconds** — you have bought back most of the security and given back most of the savings, because at that TTL a large share of requests arrive to find an expired token and go to the store anyway. A **15-minute** token costs **177.9 per 1,000** — a **6x** reduction in store traffic against the session store's 1,000 — and the window is **880 seconds**. An hour-long token costs **90.5 per 1,000** and lets a revoked user work for **3,121 seconds** while making **3,079 further successful requests**.

The hybrid is the honest one, and it is the design most large systems land on: keep the token, but have each instance pull a **revocation denylist** every 30 seconds and check it locally. Measured, that closes the window to **29 seconds** at **202.7 lookups per 1,000 requests** — better than the 15-minute token on *both* axes at this request volume, because the denylist cost is `instances × (3600 / 30) = 720` fixed reads per hour rather than a per-request cost. Note what that implies: **the hybrid's store load is independent of traffic and proportional to fleet size.** At 10x the traffic it is nearly free; at 10x the instance count it is 10x more expensive.

And note what you have just done. You added a shared store to a design whose stated purpose was to avoid a shared store. That is not a failure of reasoning; it is the actual shape of the problem. **There is no configuration that removes the trade** — you are choosing a point on a curve, and the only wrong move is choosing without knowing which point you picked.

### Externalising the other kinds of state

Sessions are the famous case. The rest are shorter but not easier.

**Files** go to **object storage** — S3 or an S3-compatible API. Every instance can read and write it, it survives instance death, and it is versioned. The application-level change is that you stop returning a local path and start returning a key plus, usually, a pre-signed URL so the download does not transit your service at all.

**Rate-limit counters** go to a **shared store with an atomic increment**, because `INCR` returning the new value is a read-modify-write that six clients cannot corrupt. [Rate Limiting & Quotas](../../02-api-design/09-rate-limiting-quotas/) builds the token bucket; the only fleet-level addition is that the bucket must be one bucket.

**WebSocket fan-out** goes to **pub/sub**. Every instance subscribes to the topics for the connections it holds; a publish from any instance reaches all of them, and each delivers to its own local sockets. [Pub/Sub: Topics & Fan-Out](../../06-messaging-and-pub-sub/04-pub-sub-topics-and-fan-out/) is the mechanism. The connection map stays in memory — it has to, it holds file descriptors — but it is now a *local index of a global topic*, which is exactly the "warmth, not correctness" category from later in this section.

**Scheduled jobs** need **leader election**: exactly one instance runs the tick. The standard implementation is a **lease** (Gray & Cheriton, *Leases: An Efficient Fault-Tolerant Mechanism for Distributed File Cache Consistency*, SOSP 1989): a lock with an expiry that the holder renews. If the holder dies, the lease expires and someone else takes over without any human involvement. This is correct, it is what Kubernetes uses, and it has a hazard that most treatments skip entirely.

> **A lease TTL bounds how long the lock is *held*. It does not bound how long the holder *believes* it holds the lock.**

The gap between those two sentences is where two leaders come from:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 494" width="100%" style="max-width:840px" role="img" aria-label="A timeline of the lock-expiry hazard. Instance A holds a lease with a fifteen second TTL, renewed every five seconds, and runs the scheduled job at each of eleven ticks up to t equals fifty. At t equals fifty A renews, passes the am-I-the-leader guard, and is then descheduled for thirty seconds by a garbage collection pause. Its lease expires at t equals sixty-five, so instance B acquires the lease with fencing token two and runs the next eight ticks. Between t equals sixty-five and eighty there are two leaders. A resumes at t equals eighty still believing it leads and replays six catch-up ticks carrying the stale token one. Without fencing that produces twenty-five executions for twenty-one ticks, four of them duplicated. The resource keeps the highest token it has seen, which is two, so every write carrying token one is rejected: nineteen executions and zero duplicates. Two ticks ran zero times either way, which fencing does not fix.">
  <text x="440" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">A lease bounds how long the lock is held — not how long the holder believes it</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <text x="70" y="48" font-size="10" fill="currentColor" opacity="0.85">lease TTL 15 s · renewed every 5 s · the job ticks every 5 s · six instances, one leader</text>

    <rect x="485" y="96" width="207" height="250" fill="#e0930f" fill-opacity="0.10" stroke="none"/>
    <rect x="588" y="96" width="104" height="250" fill="#d64545" fill-opacity="0.12" stroke="none"/>
    <text x="830" y="70" font-size="9.5" text-anchor="end" font-weight="700" fill="#e0930f">t=50…80: A is descheduled — GC pause, CPU throttle, live migration</text>
    <text x="600" y="88" font-size="9.5" font-weight="700" fill="#d64545">t=65: A's lease expires. Nobody tells A.</text>

    <path d="M485 96 L 485 346" fill="none" stroke="#e0930f" stroke-width="1.6" stroke-dasharray="5 4"/>
    <path d="M588 96 L 588 346" fill="none" stroke="#d64545" stroke-width="1.8" stroke-dasharray="5 4"/>

    <text x="130" y="118" font-size="10.5" font-weight="700" text-anchor="end" fill="currentColor">instance A</text>
    <rect x="140" y="104" width="448" height="22" rx="5" fill="#0fa07f" fill-opacity="0.14" stroke="#0fa07f" stroke-width="1.8"/>
    <text x="250" y="119" font-size="9.5" font-weight="700" fill="#0fa07f">A holds the lease · fencing token 1</text>
    <g fill="#0fa07f">
      <circle cx="140" cy="142" r="3.5"/><circle cx="174" cy="142" r="3.5"/><circle cx="209" cy="142" r="3.5"/><circle cx="243" cy="142" r="3.5"/><circle cx="278" cy="142" r="3.5"/><circle cx="312" cy="142" r="3.5"/><circle cx="347" cy="142" r="3.5"/><circle cx="381" cy="142" r="3.5"/><circle cx="416" cy="142" r="3.5"/><circle cx="450" cy="142" r="3.5"/><circle cx="485" cy="142" r="3.5"/>
    </g>
    <text x="140" y="160" font-size="9" fill="currentColor" opacity="0.8">11 ticks, run correctly, once each</text>

    <g font-size="9.5" font-weight="700" fill="#e0930f" text-anchor="end">
      <text x="478" y="184">t=50: A renews (expiry 65) and passes</text>
      <text x="478" y="196">the "am I the leader?" guard — then STOPS</text>
    </g>
    <g font-size="9.5" font-weight="700" fill="#d64545">
      <text x="600" y="184">t=80: A resumes, still believing it leads,</text>
      <text x="600" y="196">and replays 6 catch-up ticks with token 1</text>
    </g>

    <text x="130" y="228" font-size="10.5" font-weight="700" text-anchor="end" fill="currentColor">instance B</text>
    <rect x="588" y="214" width="242" height="22" rx="5" fill="#0fa07f" fill-opacity="0.14" stroke="#0fa07f" stroke-width="1.8"/>
    <text x="618" y="229" font-size="9.5" font-weight="700" fill="#0fa07f">B acquires · token 2</text>
    <g fill="#0fa07f">
      <circle cx="588" cy="252" r="3.5"/><circle cx="623" cy="252" r="3.5"/><circle cx="657" cy="252" r="3.5"/><circle cx="692" cy="252" r="3.5"/><circle cx="726" cy="252" r="3.5"/><circle cx="761" cy="252" r="3.5"/><circle cx="795" cy="252" r="3.5"/><circle cx="830" cy="252" r="3.5"/>
    </g>
    <text x="600" y="270" font-size="9" fill="currentColor" opacity="0.8">8 ticks</text>
    <text x="640" y="290" font-size="11" text-anchor="middle" font-weight="700" fill="#d64545">t = 65 … 80: TWO LEADERS</text>

    <text x="130" y="314" font-size="10.5" font-weight="700" text-anchor="end" fill="currentColor">the resource</text>
    <rect x="140" y="300" width="448" height="22" rx="5" fill="#7c5cff" fill-opacity="0.12" stroke="#7c5cff" stroke-width="1.6"/>
    <rect x="588" y="300" width="242" height="22" rx="5" fill="#7c5cff" fill-opacity="0.12" stroke="#7c5cff" stroke-width="1.6"/>
    <text x="156" y="315" font-size="9.5" font-weight="700" fill="#7c5cff">max_token_seen = 1</text>
    <text x="596" y="315" font-size="8.5" font-weight="700" fill="#7c5cff">max_token_seen = 2 · token-1 writes <tspan fill="#d64545">REJECTED</tspan></text>

    <path d="M140 346 L 830 346" fill="none" stroke="currentColor" stroke-width="1.5"/>
    <g fill="none" stroke="currentColor" stroke-width="1" opacity="0.4">
      <path d="M140 346 L 140 352"/><path d="M278 346 L 278 352"/><path d="M416 346 L 416 352"/><path d="M485 346 L 485 352"/><path d="M554 346 L 554 352"/><path d="M623 346 L 623 352"/><path d="M692 346 L 692 352"/><path d="M830 346 L 830 352"/>
    </g>
    <g fill="currentColor" font-size="9" text-anchor="middle" opacity="0.75">
      <text x="140" y="364">t=0</text><text x="278" y="364">20</text><text x="416" y="364">40</text><text x="485" y="364">50</text><text x="554" y="364">60</text><text x="623" y="364">70</text><text x="692" y="364">80</text><text x="830" y="364">100 s</text>
    </g>

    <g fill="none" stroke-width="1.8">
      <rect x="70" y="382" width="368" height="60" rx="9" fill="#d64545" fill-opacity="0.10" stroke="#d64545"/>
      <rect x="462" y="382" width="368" height="60" rx="9" fill="#0fa07f" fill-opacity="0.11" stroke="#0fa07f"/>
    </g>
    <g fill="currentColor" font-size="9.5">
      <text x="86" y="400" font-size="10.5" font-weight="700" fill="#d64545">lease only — measured</text>
      <text x="86" y="416">25 executions for 21 ticks · 4 ticks ran TWICE</text>
      <text x="86" y="432">4 duplicate invoices, charges and emails · 2 missed</text>
      <text x="478" y="400" font-size="10.5" font-weight="700" fill="#0fa07f">lease + fencing token — measured</text>
      <text x="478" y="416">19 executions · 0 duplicates · A's 6 writes rejected</text>
      <text x="478" y="432">2 ticks still ran ZERO times — fencing does not fix that</text>
    </g>
    <text x="440" y="472" font-size="11" text-anchor="middle" fill="currentColor" opacity="0.9">A lock with a TTL is a hint, not mutual exclusion. Anything a stale holder can still write must be fenced or idempotent.</text>
  </g>
</svg>
```

Follow it once. Instance A holds a 15-second lease, renews it at `t=50`, checks "am I the leader?", gets `yes`, and is then **descheduled for 30 seconds**. Nothing exotic caused that: a stop-the-world garbage collection, a container hitting its CPU quota and being throttled, a hypervisor live-migrating the VM, or a machine that swapped. A pause longer than a lease TTL is an ordinary event, not a rare one.

At `t=65` the lease expires. **Nobody tells A**, because there is no mechanism that could — A is not executing. Instance B does exactly what it should: observes the expiry, acquires the lease, and starts running ticks. From `t=65` to `t=80` **there are two leaders**, and both of them are behaving correctly according to everything they know.

At `t=80` A resumes mid-function, immediately after the guard that told it `yes`, and does its work — including catching up the ticks it missed. Measured: **25 executions for 21 ticks, with 4 ticks executed twice.** Four duplicate invoices. The lease did not fail; it did its job. The gap was between the check and the act, and no TTL can close it.

The fix is a **fencing token** — Chubby calls it a *sequencer* (Burrows, *The Chubby Lock Service for Loosely-Coupled Distributed Systems*, OSDI 2006, §2.4). Every lease acquisition increments a counter. The holder attaches that number to every write. **The protected resource remembers the highest token it has seen and rejects anything lower.** A carries token 1, B carries token 2, and once B has written, all six of A's catch-up writes arrive with token 1 and are refused: **19 executions, 0 duplicates**, measured.

Now the part that must be said in the same breath. Fencing requires the *resource* to participate — your database, your queue, your file store must be willing to compare a token and refuse. If the resource is a third-party payment API, it cannot, and no amount of locking will save you. In that case the only remaining defence is **idempotency**: make the operation safe to execute twice, with an idempotency key the downstream honours. And note the honest residue in the measurement: with fencing, **2 ticks ran zero times** — the ticks that fell inside the pause with nobody to run them. Fencing prevents double execution; it does not resurrect work the pause ate. If missed runs matter, you need catch-up logic that is *itself* fenced or idempotent.

### What a stateless fleet buys you

The payoff, stated concretely, because every remaining lesson in this phase assumes it:

- **Horizontal scaling is a number change.** Six to sixty is a config edit that takes effect in seconds, because a new instance needs no data, no warm-up for correctness, and no coordination.
- **Instances are disposable.** Spot instances, preemptible VMs and aggressive scale-in become viable. Losing one costs you its in-flight requests, which retry.
- **Deploys are trivially rolling.** Kill one, start one, repeat. No drain phase for session migration, no session replication, no maintenance window.
- **There is no recovery step.** A crashed stateless instance is replaced, not repaired. There is no state to rebuild, no consistency check, no "did it come back clean?"
- **Instances can be rescheduled anywhere.** Any node, any availability zone, any region. Lesson 9's failure domains and Lesson 10's multi-region failover are only possible because instances are fungible; Lesson 13's autoscaling control loops assume adding an instance is instant and removing one is free.

Everything above is downstream of one property: **any instance can serve any request.**

### When state SHOULD live on the instance

Resist the dogma. "Stateless" is not "the process may remember nothing" — that would be absurd and slow. Several things belong in instance memory and should stay there:

- **Connection pools.** Sockets to your database are inherently per-process; they cannot be shared and should not be.
- **Prepared statements and compiled artifacts.** Compiled regexes, parsed templates, prepared statement handles.
- **Warmed local caches.** A read-through cache in front of the shared cache — the JVM and Go worlds call it a near cache — genuinely reduces latency and shared-tier load.
- **Read-only reference data.** Currency tables, country lists, feature-flag *snapshots* loaded at boot. Note the word *snapshot*: it is loaded, not mutated.

The test is one question:

> **If this instance dies right now, does the system lose correctness, or only warmth?**

Losing **warmth** is fine. A new instance starts cold, misses its cache for a while, is slower for thirty seconds, and converges. Losing **correctness** — a session, an unflushed counter, the only copy of an upload — is not fine, and nothing about the deploy process will tell you which one you had.

But do not pretend warmth is free either. At scale-out, every new instance starts cold, and a cold instance behind an even load balancer gets its full share of traffic immediately while serving it slowly. Add twenty instances during a traffic spike and you have added twenty slow instances at the exact moment you needed fast ones — occasionally making the spike worse before it gets better. Lesson 13 pays for this again when it tunes autoscaling control loops; the fix lives in Lesson 4's health-check and readiness machinery plus a warm-up period, not in keeping state on the box.

## Build It

[`code/stateless.py`](code/stateless.py) runs a fleet of six instances behind a balancer through the same request stream twice: once with the state in memory, once with it moved out. Standard library only, seeded, and it finishes in about a tenth of a second. The interesting parts:

**The session bug is four lines.** The entire difference between the broken and correct runs is which dictionary the lookup goes to:

```python
for item in range(reqs):
    i = next(rr) % instances                  # every later request
    table = store if shared else local[i]
    sess = table.get(sid)
    if sess is None:
        fail += 1                             # 401 -> "you were logged out"
    else:
        ok += 1
        sess["cart"].append(item)             # POST /cart/add
```

Note that the cart append is inside the `else`. That is not a simplification — it is what actually happens. A `POST /cart/add` that arrives without a session does not add to a cart on another machine; it adds to nothing. Measured: of 12,000 cart writes, **1,800 (15.0%) were stored at all**, and because the checkout read is also routed independently, the expected number **visible at checkout is 300 of 12,000 — 2.5%**. That is the "cart lost most but not all of its items" symptom, quantified.

**The sticky-session comparison needs real consistent hashing**, not a stand-in, or the 34% figure would be invented rather than measured. The ring is twelve lines:

```python
class Ring:
    """Consistent hashing (Karger et al., STOC 1997), 160 vnodes per instance."""

    def __init__(self, nodes, vnodes: int = 160):
        self.points = sorted((h(f"{n}#{v}", "ring"), n) for n in nodes for v in range(vnodes))

    def route(self, key: str):
        k = h(key, "ring")
        lo, hi = 0, len(self.points)
        while lo < hi:                                # bisect on the ring
            mid = (lo + hi) // 2
            if self.points[mid][0] < k:
                lo = mid + 1
            else:
                hi = mid
        return self.points[lo % len(self.points)][1]
```

The hash is `blake2b`, not Python's built-in `hash()`, because `hash()` on a `str` is salted per process — the results would not be reproducible across runs, and a lesson whose numbers change every run is a lesson with no numbers.

**The token simulation is one shared request stream** run through every configuration, so the comparison is not confounded by different arrival patterns. The core of it is the branch that decides whether a request touches the store at all:

```python
if ttl is None:                               # server-side session
    lookups += 1
    if revoked_at is not None and t >= revoked_at:
        continue
    last_ok[u] = t
else:                                         # signed token
    if issued.get(u, -1.0) <= t:              # expired -> refresh
        lookups += 1
        if revoked_at is not None and t >= revoked_at:
            continue                          # refresh refused
        issued[u] = t + ttl
```

The `if issued.get(u, -1.0) <= t` guard is the entire economic argument for tokens: a store read happens only when the token has expired. Everything else — the 6x reduction in store traffic and the 880-second revocation window — falls out of that one line and the value of `ttl`.

Run it:

```bash
docker compose exec -T app python \
  phases/11-scalability-and-reliability/06-stateless-services/code/stateless.py
```

```console
==========================================================================
STATELESS SERVICES: WHERE THE STATE ACTUALLY WENT
seed=20260718 · stdlib only · every number below is measured, not asserted
==========================================================================

== 1 · THE SESSION BUG: THE SECOND INSTANCE IS WHERE STATE ANNOUNCES ITSELF ==
  600 users. Each logs in once, then makes 20 authenticated requests.
  The balancer round-robins every request. Sessions live in a dict.
   instances  requests    401s   logout rate   1 - floor(20/N)/20
           1     12000       0         0.0%                0.0%
           2     12000    6000        50.0%               50.0%
           3     12000    8400        70.0%               70.0%
           4     12000    9000        75.0%               75.0%
           6     12000   10200        85.0%               85.0%
          12     12000   11400        95.0%               95.0%
  round-robin sends exactly 1 request in N back to the instance holding
  the session, so the logout rate is 1 - floor(20/N)/20 exactly.

  6 instances               logout rate        cart writes kept  cart visible at checkout
  in-memory sessions              85.0%      1800/12000 = 15.0%          300/12000 = 2.5%
  shared session store             0.0%    12000/12000 = 100.0%      12000/12000 = 100.0%
  the code did not change between the two runs. The dict moved.
  at 1 instance the logout rate is 0.0% -- which is why the tests passed.

== 2 · THE RATE LIMITER THAT ISN'T: 100/min BECOMES 100 x N/min ==
  policy: 100 requests per minute per API key. One attacker, 2000 requests,
  round-robined across the fleet. Each instance holds its own counter.
   instances   admitted (local)   effective limit   x intended   admitted (shared)
           1                100               100         1.0x                 100
           2                200               200         2.0x                 100
           4                400               400         4.0x                 100
           6                600               600         6.0x                 100
           8                800               800         8.0x                 100
          16               1600              1600        16.0x                 100
  the policy document says 100. The fleet enforces 100 x N, and N is a
  number the autoscaler changes without telling anyone.
  a per-instance limit of 100/N is not the fix: it throttles every key to
  100/N whenever routing is uneven, and routing is always uneven.

== 3 · STICKY SESSIONS: THE SKEW YOU BUY, THE SESSIONS YOU LOSE ==
  4000 sessions, 55598 requests, per-session request count
  drawn from a Pareto tail (alpha=1.3, capped at 600; median 6).
  routing                             busiest  quietest   max/min
  sticky (session -> instance)          11038      7066     1.56x
  stateless (request -> instance)        9267      9266     1.00x
  per-instance load, sticky            9526   11038    9536    7066    9412    9020
  per-instance load, stateless         9267    9267    9266    9266    9266    9266
  the single hottest session is 6.4% of its instance's entire load.
  affinity cannot balance what it cannot split.

  now a routine scale-in: 6 instances -> 4. Nothing failed. The autoscaler
  did what it was told, at 02:00, on a Sunday.
  affinity mechanism                   sessions lost   requests lost
  hash(cookie) % N                      2663 = 66.6%    36246 = 65.2%
  consistent hashing (Lesson 3)         1361 = 34.0%    18432 = 33.2%
  stateless + shared store                 0 =  0.0%        0 =  0.0%
  a rolling deploy restarts all 6 instances, so it destroys 100% of them --
  which is why a sticky fleet's deploys are 'disruptive' rather than 'rolling'.

== 4 · THE NIGHTLY JOB THAT RAN SIX TIMES, AND THE TWO LEADERS ==
  the job is scheduled every 5 s; the run covers 100 s = 21 ticks.
  design                                    executions  per tick
  in-process scheduler on every instance           126         6
  leader-elected (lease), no faults                 21         1
  every customer got 6 copies of the email. The code was correct on one instance.

  THE HAZARD: a lease TTL bounds how long a lock is HELD, not how long the
  holder believes it holds it. Lease TTL = 15 s, renewed every 5 s.
  Instance A is descheduled at t=50 (GC pause / CPU-throttled container /
  live migration) and resumes at t=80, then catches up its missed ticks.
      t  who  token  what
      0  A        1  acquires lease, token 1
     50  A        1  renews (expiry 65), passes the guard, then PAUSES
     65  B        2  lease expired -> acquires, token 2
     70  B        2  runs tick 70
     80  A        1  resumes, still believes it is leader, writes
  during t=[65,80] there were TWO leaders.
  outcome                                   executions  duplicated  missed
  lease only, no fencing                            25           4       2
  lease + fencing token                             19           0       2
  the resource keeps max_token_seen. B wrote with 2, so all 6 of A's writes
  arrive with token 1 < 2 and are rejected. Duplicates: 0.
  the honest residue: ticks [55, 60] ran ZERO times. Fencing prevents
  double execution; it does not resurrect the work the pause ate.

== 5 · TOKEN VS SESSION STORE: STORE LOAD AGAINST THE REVOCATION WINDOW ==
  400 users, 29012 requests over 1 simulated hour, 6 instances.
  120 of those users are revoked mid-hour (logout, role change, or a
  leaked credential). The stream is identical across every row.
  design                             store lookups  per 1000 req  served after  worst window
  server-side session store                  29012        1000.0             0           0 s
  signed token, TTL 60 s                     12613         434.8            39          54 s
  signed token, TTL 300 s                     7284         251.1           322         281 s
  signed token, TTL 900 s                     5160         177.9          1130         880 s
  signed token, TTL 3600 s                    2627          90.5          3079        3121 s
  token + denylist, 30 s pull                 5880         202.7            26          29 s
  the token cuts store traffic 6x (1000 -> 177.9 lookups per 1000 requests)
  and buys a 880-second window in which a revoked user still has full access.
  the denylist closes the window to 29 s -- and puts 202.7 lookups per 1000
  requests back on the store, which is the store you moved the state to
  in order to avoid. There is no configuration that removes the trade.

==========================================================================
SUMMARY · the same request stream, the same code, the state moved
  in-memory sessions @ 6 instances        logout rate 85.0%  -> shared store 0.0%
  in-memory rate limit 100/min @ 6        enforced    600/min   -> shared 100/min
  sticky affinity, 6 -> 4 scale-in        sessions lost 34.0%  -> stateless 0.0%
  in-process schedule @ 6 instances       126 runs for 21 ticks -> leader 21
  lease without fencing, one 30 s pause   4 duplicate runs  -> fencing 0
  15-minute token vs session store        177.9 vs 1000 lookups/1000 req, 880 s vs 0 s revocation
  (total wall time 0.09 s)
==========================================================================
```

Four things in that output are worth more than the numbers themselves.

**The logout rate is not noisy, not probabilistic, not "under load"** — it is `1 − floor(20/N)/20`, exactly, at every N tested. No staging environment running one replica can catch it, and that is the actual lesson: the correctness of the code and the correctness of the deployment are different properties, and your tests only check the first.

**The obvious fix to section 2 is wrong.** Setting each instance's limit to `100/N` looks right and fails, because it assumes uniform routing. When routing is uneven — and Lesson 3 measured exactly how uneven — you have simultaneously under-enforced globally *and* over-throttled the keys unlucky enough to concentrate on one instance.

**Section 3's skew is irreducible, not a bad algorithm.** Read the per-instance row: 9,526 / 11,038 / 9,536 / 7,066 / 9,412 / 9,020. No routing algorithm can flatten those, because the unit of assignment is a session and sessions are not the same size.

**Section 5's hybrid scales with your fleet, not your traffic** — 720 fixed reads an hour regardless of load. That is the property that makes it the right default for most services and the wrong one for a fleet of 3,000 instances.

## Use It

**The Twelve-Factor App** (Adam Wiggins, 2011) states this as factor VI, *Processes*: "Twelve-factor processes are stateless and share-nothing. Any data that needs to persist must be stored in a stateful backing service, typically a database." Phase 10 covers twelve-factor as a whole in [Config & Twelve-Factor](../../10-infrastructure-and-deployment/05-config-and-twelve-factor/); the only part that concerns us is the sentence's second half. Factor VI explicitly names the memory and filesystem of a process as a **single-transaction cache** and nothing more — it may be used within one request, and must not be assumed to survive to the next one.

**Redis as a session store** is the default answer, and it is a good one — until you notice what you built. A single shared session store is a **single point of failure that you created while removing single points of failure**. If Redis is down, every request is unauthenticated, on all six instances at once. So decide these four things before you need them:

- **Replicate it.** Redis Sentinel or a managed cluster with automatic failover across availability zones. A single-AZ (Availability Zone) session store makes your whole service single-AZ regardless of where your instances run.
- **Decide fail-open or fail-closed, in advance.** Fail-closed (no store, no auth) is correct for anything touching money or personal data. Fail-open is a security incident with a schedule. There is a third option worth considering: fall back to accepting *unexpired signed tokens* while the store is unreachable, which degrades you to the token model's revocation window instead of to zero availability.
- **Cache validated sessions in-process for a few seconds.** A 5-second local cache of "this session id is valid until T" cuts store reads dramatically and gives you a short survival window during a store blip. You have re-derived the hybrid from section 5, with all of its trade-offs.
- **Set a TTL on every session key** and let the store expire them. Sessions without expiry are a memory leak with a login page.

**Files go to object storage.** S3, or any S3-compatible API (MinIO, R2, GCS with the S3 interface). Two rules: never write to the container filesystem for anything a later request must read, and prefer pre-signed URLs so uploads and downloads bypass your service entirely rather than occupying a worker for the duration of a transfer.

**Kubernetes: Deployment versus StatefulSet.** This choice is misunderstood often enough to be worth stating precisely. A **StatefulSet** guarantees exactly three things:

1. **Stable, ordinal network identity.** Pods are `app-0`, `app-1`, `app-2`, and `app-0` is always `app-0` with a stable DNS name, even after rescheduling.
2. **Stable storage.** Each ordinal keeps its own PersistentVolumeClaim across restarts and reschedules — `app-1` gets `data-app-1` back.
3. **Ordered, predictable lifecycle.** Pods are created in order 0, 1, 2 and terminated in reverse, so a pod that must bootstrap from its predecessor can.

That is the entire list. A StatefulSet does **not** replicate your data, does **not** make your application correct, and does **not** help a web tier — it makes scale-in slower and deploys serialised, which is a real cost paid for guarantees a stateless service does not use. StatefulSets are for the databases, brokers and consensus members that genuinely need a durable identity. **If your service could use a Deployment and does not, you are paying for the wrong thing.**

```yaml
# The affinity knob, and what its default actually is.
apiVersion: v1
kind: Service
spec:
  sessionAffinity: ClientIP           # default: None
  sessionAffinityConfig:
    clientIP:
      timeoutSeconds: 10800           # the default: 3 hours of pinning
```

`ClientIP` affinity hashes the source address in kube-proxy. Note what it cannot see: if traffic arrives through an ingress controller or a cloud load balancer, the source address kube-proxy sees may be the *proxy's*, so every user hashes to one backend. On AWS, an Application Load Balancer's target group has `stickiness.enabled` (default `false`) with `stickiness.lb_cookie.duration_seconds` defaulting to **86400 — one day**. A one-day pin is a one-day commitment that the instance will still exist, on infrastructure explicitly designed to replace instances.

```yaml
# nginx: prefer consistent hashing over ip_hash if you must have affinity.
upstream app {
    hash $cookie_session consistent;   # ketama ring: only ~1/N moves when N changes
    server app1:8000;
    server app2:8000;
    server app3:8000;
}
```

**Leader election via a lease** is a solved problem — use the platform's. On Kubernetes it is the `coordination.k8s.io/v1` **Lease** object, which is exactly the lease-with-renewal from section 4 and is what the control plane itself uses for its own components:

```yaml
apiVersion: coordination.k8s.io/v1
kind: Lease
metadata:
  name: nightly-invoice-job
spec:
  holderIdentity: app-7d9f-x4k2         # who thinks they hold it
  leaseDurationSeconds: 15              # expiry if not renewed
  renewTime: "2026-07-18T02:00:07.000Z"
  leaseTransitions: 42                  # <- monotonic: your fencing token
```

`leaseTransitions` increments on every handover, which makes it usable as the fencing token — pass it to whatever the job writes to, and have that resource reject anything lower. Without a platform, a database row works identically:

```sql
-- Acquire or steal an expired lease, and get a fencing token back. One statement,
-- so two instances cannot both win: the UPDATE takes a row lock.
UPDATE job_leases
   SET holder      = $1,
       expires_at  = now() + interval '15 seconds',
       fence_token = fence_token + 1
 WHERE job_name    = 'nightly-invoice'
   AND (holder = $1 OR expires_at < now())
RETURNING fence_token;

-- And the resource enforces it, or the token was decoration:
UPDATE invoice_runs SET status = 'done', last_token = $2
 WHERE run_date = $3 AND last_token < $2;   -- 0 rows updated = you are stale. Stop.
```

The `last_token < $2` predicate is the whole mechanism. Without it you have a number you pass around and nobody checks.

**Migrating an existing stateful service, without a big-bang rewrite.** Four phases, each independently revertible, none requiring a flag day:

1. **Dual-write.** On every session mutation, write to the in-memory dict *and* the store. Keep reading from memory only. Nothing about request handling changes, so this cannot break anything. Deploy, then verify the store is receiving the writes you expect: compare `session_store_writes_total` against your login rate.
2. **Read from the store, fall back to memory.** Read the store first; on a miss, fall back to the local dict and *repair* the store from it. Emit a counter for the fallback path. When that counter reaches zero and stays there across a full session-TTL window, the store is authoritative in practice.
3. **Remove the in-memory read**, then the in-memory write. Now turn off sticky sessions at the load balancer and watch your 401 rate. This is the step that proves the migration: if the 401 rate does not move, the state is genuinely external.
4. **Remove the affinity configuration entirely**, and only then let the autoscaler scale in. Repeat the whole procedure for the *next* item on the inventory — rate-limit counters, then the scheduler, then uploads. One kind of state per deployment, so that when something breaks you know which move broke it.

The order matters at the end: teams routinely disable stickiness at step 2 because "the store is working now", and discover the fallback path was carrying more traffic than they thought.

## Think about it

1. Your service uses 15-minute JWTs. Security asks: "if we discover a compromised account, how fast can we cut off access?" Using the measured numbers, give the honest answer, then design the change that gets it under 60 seconds — and state exactly what that change costs in store load and in new failure modes.
2. Section 3 measured a 1.56x load imbalance from session affinity. Suppose you keep affinity for cache locality but move sessions to a shared store. Which of the four costs of stickiness do you still pay, and which disappear? What now happens on scale-in?
3. The fencing token fixed duplicate execution because the resource checked it. List three resources your services write to that *cannot* check a fencing token, and say what you would do for each instead.
4. Your session store goes down. Walk through what happens under each of the three designs from the comparison table — pure token, pure session store, hybrid — for a user who logged in an hour ago, and for a user trying to log in now. Which failure would you rather explain?
5. You are asked to make an existing WebSocket chat service stateless. The connection map cannot leave the instance holding the sockets. Describe what does move, what stays, and what a scale-in event now costs the user — and decide whether that residual cost is "warmth" or "correctness."

## Key takeaways

- **"Stateless" means no state that only one instance has, not no state.** The working definition is: any instance can serve any request, and losing an instance loses only in-flight work. Everything else in this phase — autoscaling, multi-region failover, disposable instances, rolling deploys — is a consequence of that one property.
- **The bug arrives at instance two, at full strength.** Measured with in-memory sessions and round-robin routing: **0.0% logout rate at one instance, 50.0% at two, 85.0% at six** (`1 − floor(20/N)/20`, exactly). Of 12,000 cart writes only **15.0% were stored** and **2.5% were visible at checkout**. Your tests pass because they run one replica; the code is correct and the deployment is not.
- **In-memory rate limiting enforces `limit × N`.** A written policy of **100/min was enforced as 600/min at six instances and 1,600/min at sixteen** — a security control whose real value is set by your autoscaler. Dividing by N is not the fix, because routing is never uniform.
- **Sticky sessions transfer the problem and add three more.** Measured: **1.56x** load skew versus **1.00x** for per-request routing; a routine 6→4 scale-in destroyed **34.0% of sessions** with consistent hashing and **66.6%** with `hash % N`; a rolling deploy destroys **100%**. Affinity is a legitimate cache-locality optimisation and an illegitimate correctness mechanism.
- **A lease TTL does not give you mutual exclusion.** One 30-second pause on the leader — GC, CPU throttling, live migration — produced **two leaders for 15 seconds and 4 duplicated job executions**. A **fencing token** checked *by the resource* took duplicates to **0**; anything that cannot check a token must be idempotent instead. And fencing does not recover the **2 ticks that ran zero times**.
- **Revocation is the property everyone forgets, and it is a curve, not a choice.** A signed token cannot be un-issued: measured, a 15-minute TTL cut store traffic **6x (1,000 → 177.9 lookups per 1,000 requests)** and let revoked users work for up to **880 seconds** and **1,130 further requests**. A denylist pulled every 30 s closed the window to **29 s** for **202.7 lookups per 1,000** — cost proportional to fleet size, not traffic.
- **The shared store you just created is a new single point of failure.** Replicate it across AZs, set a TTL on every key, cache validation in-process for a few seconds, and decide *now* whether an unreachable store fails open or closed. Making a service stateless does not remove risk; it relocates risk into something you can replicate.
- **Some state belongs on the instance.** Connection pools, prepared statements, warm caches and read-only reference data are all correctly instance-local. The test is whether losing the instance loses **correctness** or only **warmth** — warmth is fine to lose, but it is not free, because scaling out adds cold instances at exactly the moment you needed fast ones.

Next: [Read Replicas & Replication Lag](../07-read-replicas-and-replication-lag/) — you have moved the state into a shared database, so every instance now reads from one place. The next lesson adds replicas to survive that, and measures the new bug it introduces: a user who writes and then cannot read what they just wrote.
