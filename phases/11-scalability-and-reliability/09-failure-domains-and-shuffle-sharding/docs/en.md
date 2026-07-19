# Failure Domains, Blast Radius & Shuffle Sharding

> One customer ships a bug. Not an attack — a regex that backtracks. On a shared fleet of 8 workers it took down **all 800 customers**. Split into 4 fixed shards it took down **189**. Assigned a random 2-of-8 combination it took down **21 — 2.63%** — and 339 more ran at half capacity without a single failed request. Same hardware, same bug, same afternoon. The difference is one line of assignment logic and a piece of combinatorics you can do on paper.

**Type:** Build
**Languages:** Python
**Prerequisites:** [Sharding the Data Tier](../08-sharding-the-data-tier/), [What One Machine Can Actually Do](../01-what-one-machine-can-do/)
**Time:** ~80 minutes

## The Problem

You run a document-processing API. Eight worker machines behind a load balancer, 800 paying customers, and a comfortable 40% CPU. The architecture diagram has the word "horizontally scalable" on it and it is not lying.

**09:41:03.** A customer — call them customer 0 — deploys a change to their own integration. Their new code calls your `/extract` endpoint with a filename their user typed. Your endpoint validates filenames with a regular expression. That regular expression has nested quantifiers in it, and on this particular 40-character input it backtracks into roughly 2⁴⁰ paths. The request does not error. It does not time out at your edge, because your edge timeout is 30 seconds and this is going to take considerably longer than that. It simply occupies one worker, at 100% of one CPU, indefinitely.

**09:41:04.** The customer's integration is a loop over their user's documents. It sends the next request. Your load balancer, running least-connections, notices worker 3 is busy and helpfully routes it to worker 5.

**09:41:09.** Six seconds in, every one of your eight workers is executing one of these requests. Your fleet has a total capacity of zero. Not degraded — **zero**. Requests from the other 799 customers are queueing behind a set of workers that will never finish what they are doing.

**09:41:27.** The retries arrive. Every client library in front of you — yours, your customers', the mobile SDK — sees a timeout and does the sane, documented, thoroughly reviewed thing: it tries again. Your offered load is now three times what it was, against zero capacity.

**09:42:10.** Your health checks start failing. This is the part that is genuinely cruel. The health checker asks each worker "are you alive?", the worker has no CPU left to answer, and the check times out. Your orchestrator concludes that all eight workers are unhealthy, ejects them from the pool, and starts replacing them. The replacements come up healthy, join the pool, receive the retried requests that are still queued, and pin themselves within seconds. **The outage now outlives the request that caused it**, because you have built a machine for feeding the poison to every new worker you create.

**10:15.** Someone finally reads a stack dump, finds the regex, and ships a fix. Thirty-four minutes. Eight hundred customers. One customer's typo-adjacent bug.

Now the uncomfortable review-meeting question, and it is not "why was the regex bad". Regexes will be bad. Queries will be unbounded. Someone will allocate a gigabyte in a request handler. The question is:

> **When something fails, how much of your system does it take with it — and can you choose that number in advance?**

The answer is yes, you can choose it, and the choosing is cheap. That is what this lesson is about.

## The Concept

### Failure domains and blast radius are two different numbers

A **failure domain** is a set of things that fail together. It is a property of your topology: if these two machines are in the same rack and the rack's power supply dies, that rack is a failure domain. If these two services share a database, that database is a failure domain regardless of where the machines are.

**Blast radius** is the consequence: the fraction of your users affected when one failure domain fails. It is a number between 0 and 1, and it is the number your customers experience.

The two are related but not the same, and conflating them is how teams end up with an impressive-looking architecture and a 100% blast radius. In the incident above, your failure domain was "the fleet" — all eight workers failed together — and your blast radius was 100%. Note that **nothing was redundant-less**. You had eight workers. You had replicas. You had, on paper, tolerance for seven simultaneous machine failures. None of it helped, because the failure did not arrive one machine at a time; it arrived as a request that any worker would accept.

Here is the reframe the rest of the lesson depends on:

> **You cannot prevent failure. You can choose its granularity.** And that choice is made at design time, in how you assign work to machines — not at 3am, in how fast you respond.

This is an architecture decision, not an operations decision. No amount of monitoring, on-call rotation or runbook quality changes the fraction of customers who go down when a worker dies. The assignment does.

### The physical hierarchy: rack, zone, region, provider

Cloud providers sell you a hierarchy of failure domains. Bottom to top:

- **Host** — one machine. Fails constantly, and everyone plans for it.
- **Rack** — a few dozen hosts sharing a top-of-rack switch, a power distribution unit, and a cooling path. Any of those three kills the rack.
- **Availability Zone (AZ)** — an independent datacenter (or a small cluster of them) with its **own power, own cooling and own network**, within a region. AZs in a region are close enough for low-latency synchronous replication — typically single-digit milliseconds — and far enough apart that one flooding, burning or losing utility power does not affect the others.
- **Region** — a geographic area containing several AZs. Separate regions share almost nothing physical.
- **Provider** — one company. One control plane, one status page, one billing system, one set of engineers pushing changes.

That list is what you are buying. Here is what you are actually getting, which is the part that matters: **the independence is real at the physical layer and largely fictional above it.** Within one region, all AZs typically share a regional API endpoint, a control plane, a network fabric, the provider's own deploy pipeline, and — for you — a DNS (Domain Name System) provider, a certificate authority (CA), and your own CI/CD pipeline. None of those stop at an AZ boundary.

This wrecks the arithmetic everyone does. The naive calculation says: if one instance is available 99.9% of the time, two independent instances are unavailable only when both are, so `0.001 × 0.001 = 0.000001` — availability 99.9999%, six nines, from two cheap machines. The Build It computes it properly. Model an instance's unavailability `p = 0.001` as having a **common-cause fraction `c`**: with probability `c·p` a shared cause takes *every* instance at once, and the rest is independent. Then

```text
P(system down) = c*p + (1 - c*p) * ((1-c)*p)^n
```

Run it and the illusion collapses:

```text
      c     2 instances   nines     3 instances   nines       ceiling
  0.000    99.9999000%    6.00    99.9999999%    9.00          none
  0.010    99.9989020%    4.96    99.9989999%    5.00         5.00n
  0.100    99.9899190%    4.00    99.9899999%    4.00         4.00n
```

At `c = 0` you get your six nines. At **`c = 0.01` — one failure in a hundred is shared — two instances give 4.96 nines, not 6.00.** And the punchline is the third column: **adding a third instance moves it to 5.00 nines, and a fourth, a fifth or a hundredth moves it nowhere at all.** The ceiling is `1 − c·p`, and no amount of replication goes above it. Redundancy multiplies the independent term; it does nothing whatsoever to the shared one.

Lesson 1 promised this arithmetic when it said that one machine's limits are not fixed by adding machines. Here it is, and it generalises: **when you cannot make failures independent, buying more copies stops working.** Which raises the question of what the shared causes actually are.

### The failure domains that are not physical

These are the ones that cause the outages that make the news, and not one of them respects an AZ boundary:

- **A global config push.** One value, applied fleet-wide in seconds, by design. This is the single most common cause of total-fleet outages at large providers, because config changes feel safe and therefore skip the process that code changes get.
- **A bad deploy reaching every instance.** Same shape, with a build step.
- **A schema migration.** The migration runs once, against the database every instance shares. Multi-AZ does not give you multiple schemas. See [Zero-Downtime Schema Changes](../../10-infrastructure-and-deployment/13-zero-downtime-schema-changes/) for the expand/contract discipline that makes this survivable.
- **A shared feature-flag service.** You added it to make changes safer. It is now a synchronous dependency on your request path, in every zone, and when it is slow, you are slow. Cache last-known-good and fail open, or it is a global kill switch you did not mean to install. [Deploy vs Release: Feature Flags](../../10-infrastructure-and-deployment/12-deploy-vs-release-feature-flags/) covers the mechanics.
- **A poisoned cache entry.** One bad value, replicated to every cache node, served to everyone until someone finds it. [Cache Stampede](../../05-caching/06-cache-stampede/) covers the related failure where the cache tier's *absence* becomes the outage.
- **A single shared database.** The most honest item on the list. If every cell, zone and region talks to one primary, you have one failure domain wearing a costume.

This is why **"we're multi-AZ" is not an answer.** It is an answer to power, cooling, switches, fires and floods. It is not an answer to anything in that list, and the things in that list are what actually takes you down.

Deploys deserve a specific note, because they are the failure domain you have the most control over. A deploy that reaches every instance at once has a blast radius of 100% by construction. A deploy that reaches 5% of instances, bakes, then 25%, then the rest, has a blast radius of 5% *if you are watching the right signal during the bake*. That is a **staged or waved rollout**, and Phase 10's [Deployment Strategies](../../10-infrastructure-and-deployment/11-deployment-strategies/) covers the canary mechanics — how to pick the canary population, what to compare, and how to automate the rollback. What this lesson adds is the fleet-shaped version of the same idea: the wave should be a *cell*, and the reason is below.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 540" width="100%" style="max-width:840px" role="img" aria-label="The physical failure-domain hierarchy — provider, region, three availability zones, racks and hosts — drawn as nested boxes, with two red bands running straight through all three availability zones. The upper band is the global config push, the feature-flag service and the deploy pipeline; the lower band is the shared control plane, the single primary database and the DNS provider and certificate authority. Neither band stops at an availability zone boundary, which is why being multi-AZ is not an answer to them. A panel underneath lists the six non-physical failure domains and the containment that actually works for each.">
  <g font-family="'JetBrains Mono', ui-monospace, monospace"> <text x="440" y="26" text-anchor="middle" font-size="14.5" font-weight="700" fill="currentColor">The boundaries you paid for, and the two that ignore them</text> <text x="440" y="44" text-anchor="middle" font-size="10" fill="currentColor" opacity="0.75">AZ = Availability Zone: an independent datacenter — own power, own cooling, own network — inside one region</text>
    <rect x="24" y="58" width="832" height="266" rx="12" fill="#7f7f7f" fill-opacity="0.06" stroke="currentColor" stroke-opacity="0.45" stroke-width="1.6"/> <text x="38" y="76" font-size="10" font-weight="700" fill="currentColor" opacity="0.75">PROVIDER — one company, one control plane, one status page, one billing system</text>
    <rect x="40" y="84" width="800" height="228" rx="10" fill="#7f7f7f" fill-opacity="0.06" stroke="currentColor" stroke-opacity="0.45" stroke-width="1.5"/> <text x="52" y="101" font-size="10" font-weight="700" fill="currentColor" opacity="0.75">REGION us-east-1 — one shared network fabric, one regional API endpoint</text> <g fill="none" stroke="#7c5cff" stroke-width="2"> <rect x="60" y="108" width="244" height="196" rx="9" fill="#7c5cff" fill-opacity="0.08"/>
      <rect x="318" y="108" width="244" height="196" rx="9" fill="#7c5cff" fill-opacity="0.08"/> <rect x="576" y="108" width="244" height="196" rx="9" fill="#7c5cff" fill-opacity="0.08"/> </g> <g font-size="10.5" font-weight="700" fill="#7c5cff"> <text x="74" y="127">AZ-a</text><text x="332" y="127">AZ-b</text><text x="590" y="127">AZ-c</text> </g> <g font-size="8" fill="currentColor" opacity="0.75">
      <text x="118" y="127">own power · cooling · network</text><text x="376" y="127">own power · cooling · network</text><text x="634" y="127">own power · cooling · network</text> </g> <g fill="none" stroke="currentColor" stroke-opacity="0.4" stroke-width="1.3"> <rect x="74" y="136" width="216" height="46" rx="6"/><rect x="332" y="136" width="216" height="46" rx="6"/><rect x="590" y="136" width="216" height="46" rx="6"/>
      <rect x="74" y="222" width="216" height="46" rx="6"/><rect x="332" y="222" width="216" height="46" rx="6"/><rect x="590" y="222" width="216" height="46" rx="6"/> </g> <g font-size="7.5" fill="currentColor" opacity="0.6"> <text x="80" y="147">rack 1</text><text x="338" y="147">rack 1</text><text x="596" y="147">rack 1</text> <text x="80" y="233">rack 2</text><text x="338" y="233">rack 2</text><text x="596" y="233">rack 2</text> </g>
    <g fill="#0fa07f" fill-opacity="0.16" stroke="#0fa07f" stroke-width="1.2"> <rect x="82" y="152" width="48" height="24" rx="4"/><rect x="136" y="152" width="48" height="24" rx="4"/><rect x="190" y="152" width="48" height="24" rx="4"/><rect x="244" y="152" width="40" height="24" rx="4"/>
      <rect x="340" y="152" width="48" height="24" rx="4"/><rect x="394" y="152" width="48" height="24" rx="4"/><rect x="448" y="152" width="48" height="24" rx="4"/><rect x="502" y="152" width="40" height="24" rx="4"/> <rect x="598" y="152" width="48" height="24" rx="4"/><rect x="652" y="152" width="48" height="24" rx="4"/><rect x="706" y="152" width="48" height="24" rx="4"/><rect x="760" y="152" width="40" height="24" rx="4"/>
      <rect x="82" y="238" width="48" height="24" rx="4"/><rect x="136" y="238" width="48" height="24" rx="4"/><rect x="190" y="238" width="48" height="24" rx="4"/><rect x="244" y="238" width="40" height="24" rx="4"/> <rect x="340" y="238" width="48" height="24" rx="4"/><rect x="394" y="238" width="48" height="24" rx="4"/><rect x="448" y="238" width="48" height="24" rx="4"/><rect x="502" y="238" width="40" height="24" rx="4"/>
      <rect x="598" y="238" width="48" height="24" rx="4"/><rect x="652" y="238" width="48" height="24" rx="4"/><rect x="706" y="238" width="48" height="24" rx="4"/><rect x="760" y="238" width="40" height="24" rx="4"/> </g> <rect x="34" y="188" width="812" height="28" rx="7" fill="#d64545" fill-opacity="0.20" stroke="#d64545" stroke-width="1.9"/>
    <text x="440" y="206" font-size="10.5" font-weight="700" text-anchor="middle" fill="#d64545">global config push&#8195;·&#8195;the feature-flag service&#8195;·&#8195;the deploy pipeline</text> <rect x="34" y="274" width="812" height="28" rx="7" fill="#d64545" fill-opacity="0.20" stroke="#d64545" stroke-width="1.9"/>
    <text x="440" y="292" font-size="10.5" font-weight="700" text-anchor="middle" fill="#d64545">the shared control plane&#8195;·&#8195;the one primary database&#8195;·&#8195;DNS + the certificate authority</text> <text x="24" y="344" font-size="10" fill="#0fa07f" font-weight="700">An AZ boundary stops:</text>
    <text x="196" y="344" font-size="10" fill="currentColor" opacity="0.9">a power failure, a cooling failure, a top-of-rack switch, a flooded room, a fire, a fibre cut.</text> <text x="24" y="362" font-size="10" fill="#d64545" font-weight="700">It stops neither red band.</text> <text x="230" y="362" font-size="10" fill="currentColor" opacity="0.9">Those reach every host in every zone in seconds. "We are multi-AZ" is not an answer to them.</text>
    <rect x="24" y="378" width="832" height="102" rx="10" fill="#e0930f" fill-opacity="0.08" stroke="#e0930f" stroke-width="1.6"/> <text x="40" y="397" font-size="10.5" font-weight="700" fill="#e0930f">the non-physical failure domains, and the containment that actually works for each</text> <g font-size="9" font-weight="700" fill="#d64545">
      <text x="40" y="418">config push</text><text x="40" y="437">deploy to every instance</text><text x="40" y="456">shared feature-flag service</text> <text x="452" y="418">schema migration</text><text x="452" y="437">one shared database</text><text x="452" y="456">DNS provider / cert authority</text> </g> <g font-size="9" fill="currentColor" opacity="0.9">
      <text x="228" y="418">-&gt; version it, wave it cell by cell</text><text x="228" y="437">-&gt; one cell first, bake, then the rest</text><text x="228" y="456">-&gt; cache last-known-good, fail open</text> <text x="644" y="418">-&gt; expand / contract, never one step</text><text x="644" y="437">-&gt; one database per cell</text><text x="644" y="456">-&gt; expiry as an SLO, two providers</text> </g>
    <text x="440" y="502" font-size="11" text-anchor="middle" fill="currentColor" opacity="0.9">Every domain in the amber panel was created by software and can be removed by software.</text> <text x="440" y="520" font-size="11" text-anchor="middle" fill="currentColor" opacity="0.9">The AZ boundary you rent cannot help with a single one of them.</text> </g>
</svg>
```

### Cell-based architecture

A **cell** is a complete, independent copy of your stack — load balancer, application instances, cache, database, queues, everything on the request path — serving a fixed subset of your customers. You run several. A customer belongs to exactly one.

Four rules make it work, and the third is the one people get wrong:

**Everything on the request path lives inside the cell.** If serving a request requires a call outside the cell, that outside thing is a shared failure domain and you have not built cells; you have built a confusing deployment topology. A cell that calls another cell is not a cell.

**The cell router is the one shared component, and it must be dumb.** Something has to map a customer to a cell. That something is now the single point of failure for your entire system, so it gets the opposite of the usual engineering instinct: no database lookup, no service call, no business logic, no dynamic membership protocol. A static map — ideally a versioned file, deployed like code, cached at every layer, and readable from memory. It should be boring enough that you can describe its failure modes in one sentence.

**Cells are sized by two opposing constraints.** Small enough that losing one is survivable and the blast radius is acceptable; big enough to be operationally and economically sensible. A 3-instance cell spends a third of its capacity on its own spare host. Four hundred cells is four hundred things to patch, monitor and page about.

**You deploy to one cell first.** This is the benefit that pays for the whole architecture. A bad deploy has a blast radius of one cell, and you find out during the bake instead of during the incident.

The Build It prices the trade exactly, for 24,000 customers and 240,000 req/s at peak:

```text
 cells  cust/cell  inst/cell  instances  overhead  deploy blast  deploy time
     1     24,000        243        243     1.2%       100.00%        20 min
     4      6,000         62        248     3.3%        25.00%        80 min
    24      1,000         12        288    20.0%         4.17%       480 min
   120        200          4        480   100.0%         0.83%      2400 min
```

Read the overhead column, because it is not linear. Going from 1 cell to 24 costs **18.8 percentage points of extra hardware (288 instances instead of 243)** and takes the deploy blast radius from **100% to 4.17%**. That is an outstanding trade. Going from 24 to 120 costs another **80 points — you double your entire fleet** — to move blast radius from 4.17% to 0.83%. That is usually a bad trade. The reason overhead climbs slowly and then vertically is that each cell must carry its own headroom (statistical multiplexing gets worse as the pool shrinks: headroom scales with `√demand`, so total headroom scales with `√cells`) *and* its own spare host. Once a cell is down to two or three instances, **the spare host is the cell**.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 518" width="100%" style="max-width:840px" role="img" aria-label="A cell-based architecture: 24,000 customers arrive at a thin static cell router which maps each customer id to one of four cells. Each cell is a complete independent copy of the stack — its own load balancer, three application instances, its own cache and its own database — serving 6,000 customers. A bad deploy of version 1.4.3 has been rolled out to cell 2 only and is drawn in red; the other three cells are still on 1.4.2 and are unaffected, so the blast radius of the bad deploy is one cell.">
  <defs> <marker id="p11-09-d4a" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L6.5,3 L0,6 Z" fill="currentColor"/></marker> </defs> <g font-family="'JetBrains Mono', ui-monospace, monospace"> <text x="440" y="26" text-anchor="middle" font-size="14.5" font-weight="700" fill="currentColor">A cell is a whole stack. A bad deploy can only be as big as one.</text>
    <text x="440" y="44" text-anchor="middle" font-size="10" fill="currentColor" opacity="0.75">24,000 customers, 240,000 req/s at peak — the measured trade is at the bottom</text> <rect x="330" y="58" width="220" height="26" rx="7" fill="#3553ff" fill-opacity="0.12" stroke="#3553ff" stroke-width="1.7"/> <text x="440" y="76" font-size="10.5" font-weight="700" text-anchor="middle" fill="#3553ff">24,000 customers</text>
    <path d="M440 84 L 440 98" fill="none" stroke="currentColor" stroke-width="1.5" marker-end="url(#p11-09-d4a)"/> <rect x="120" y="102" width="640" height="46" rx="9" fill="#7c5cff" fill-opacity="0.12" stroke="#7c5cff" stroke-width="2"/> <text x="440" y="120" font-size="11.5" font-weight="700" text-anchor="middle" fill="#7c5cff">CELL ROUTER — the one thing every customer shares</text>
    <text x="440" y="138" font-size="9.5" text-anchor="middle" fill="currentColor" opacity="0.9">cell = static_map[customer_id]. No database. No service call. No business logic. Cached everywhere.</text> <g fill="none" stroke="currentColor" stroke-width="1.4" opacity="0.7">
      <path d="M135 148 L 135 176" marker-end="url(#p11-09-d4a)"/><path d="M347 148 L 347 176" marker-end="url(#p11-09-d4a)"/><path d="M559 148 L 559 176" marker-end="url(#p11-09-d4a)"/><path d="M771 148 L 771 176" marker-end="url(#p11-09-d4a)"/> </g> <g fill="none" stroke-width="2"> <rect x="40" y="178" width="190" height="196" rx="11" fill="#0fa07f" fill-opacity="0.07" stroke="#0fa07f"/>
      <rect x="252" y="178" width="190" height="196" rx="11" fill="#d64545" fill-opacity="0.09" stroke="#d64545"/> <rect x="464" y="178" width="190" height="196" rx="11" fill="#0fa07f" fill-opacity="0.07" stroke="#0fa07f"/> <rect x="676" y="178" width="190" height="196" rx="11" fill="#0fa07f" fill-opacity="0.07" stroke="#0fa07f"/> </g> <g font-size="11" font-weight="700">
      <text x="54" y="198" fill="#0fa07f">CELL 1</text><text x="266" y="198" fill="#d64545">CELL 2</text><text x="478" y="198" fill="#0fa07f">CELL 3</text><text x="690" y="198" fill="#0fa07f">CELL 4</text> </g> <g font-size="8.5" fill="currentColor" opacity="0.8"> <text x="54" y="211">6,000 customers</text><text x="266" y="211">6,000 customers</text><text x="478" y="211">6,000 customers</text><text x="690" y="211">6,000 customers</text> </g>
    <g font-size="9" font-weight="700" text-anchor="end"> <text x="216" y="198" fill="#0fa07f">v1.4.2</text><text x="428" y="198" fill="#d64545">v1.4.3</text><text x="640" y="198" fill="#0fa07f">v1.4.2</text><text x="852" y="198" fill="#0fa07f">v1.4.2</text> </g> <g fill="none" stroke-width="1.5"> <rect x="54" y="218" width="162" height="24" rx="6" fill="#7c5cff" fill-opacity="0.11" stroke="#7c5cff"/>
      <rect x="266" y="218" width="162" height="24" rx="6" fill="#7c5cff" fill-opacity="0.11" stroke="#7c5cff"/> <rect x="478" y="218" width="162" height="24" rx="6" fill="#7c5cff" fill-opacity="0.11" stroke="#7c5cff"/> <rect x="690" y="218" width="162" height="24" rx="6" fill="#7c5cff" fill-opacity="0.11" stroke="#7c5cff"/> </g> <g font-size="9" text-anchor="middle" fill="currentColor">
      <text x="135" y="234">load balancer</text><text x="347" y="234">load balancer</text><text x="559" y="234">load balancer</text><text x="771" y="234">load balancer</text> </g> <g fill="none" stroke-width="1.5">
      <rect x="54" y="250" width="48" height="30" rx="6" fill="#0fa07f" fill-opacity="0.16" stroke="#0fa07f"/><rect x="108" y="250" width="48" height="30" rx="6" fill="#0fa07f" fill-opacity="0.16" stroke="#0fa07f"/><rect x="162" y="250" width="48" height="30" rx="6" fill="#0fa07f" fill-opacity="0.16" stroke="#0fa07f"/>
      <rect x="266" y="250" width="48" height="30" rx="6" fill="#d64545" fill-opacity="0.24" stroke="#d64545"/><rect x="320" y="250" width="48" height="30" rx="6" fill="#d64545" fill-opacity="0.24" stroke="#d64545"/><rect x="374" y="250" width="48" height="30" rx="6" fill="#d64545" fill-opacity="0.24" stroke="#d64545"/>
      <rect x="478" y="250" width="48" height="30" rx="6" fill="#0fa07f" fill-opacity="0.16" stroke="#0fa07f"/><rect x="532" y="250" width="48" height="30" rx="6" fill="#0fa07f" fill-opacity="0.16" stroke="#0fa07f"/><rect x="586" y="250" width="48" height="30" rx="6" fill="#0fa07f" fill-opacity="0.16" stroke="#0fa07f"/>
      <rect x="690" y="250" width="48" height="30" rx="6" fill="#0fa07f" fill-opacity="0.16" stroke="#0fa07f"/><rect x="744" y="250" width="48" height="30" rx="6" fill="#0fa07f" fill-opacity="0.16" stroke="#0fa07f"/><rect x="798" y="250" width="48" height="30" rx="6" fill="#0fa07f" fill-opacity="0.16" stroke="#0fa07f"/> </g> <g font-size="9" text-anchor="middle" fill="currentColor">
      <text x="78" y="269">app</text><text x="132" y="269">app</text><text x="186" y="269">app</text> <text x="290" y="269" fill="#d64545" font-weight="700">app</text><text x="344" y="269" fill="#d64545" font-weight="700">app</text><text x="398" y="269" fill="#d64545" font-weight="700">app</text> <text x="502" y="269">app</text><text x="556" y="269">app</text><text x="610" y="269">app</text>
      <text x="714" y="269">app</text><text x="768" y="269">app</text><text x="822" y="269">app</text> </g> <g fill="none" stroke-width="1.5"> <rect x="54" y="290" width="78" height="28" rx="6" fill="#0fa07f" fill-opacity="0.11" stroke="#0fa07f"/><rect x="138" y="290" width="78" height="28" rx="6" fill="#0fa07f" fill-opacity="0.11" stroke="#0fa07f"/>
      <rect x="266" y="290" width="78" height="28" rx="6" fill="#0fa07f" fill-opacity="0.11" stroke="#0fa07f"/><rect x="350" y="290" width="78" height="28" rx="6" fill="#0fa07f" fill-opacity="0.11" stroke="#0fa07f"/> <rect x="478" y="290" width="78" height="28" rx="6" fill="#0fa07f" fill-opacity="0.11" stroke="#0fa07f"/><rect x="562" y="290" width="78" height="28" rx="6" fill="#0fa07f" fill-opacity="0.11" stroke="#0fa07f"/>
      <rect x="690" y="290" width="78" height="28" rx="6" fill="#0fa07f" fill-opacity="0.11" stroke="#0fa07f"/><rect x="774" y="290" width="78" height="28" rx="6" fill="#0fa07f" fill-opacity="0.11" stroke="#0fa07f"/> </g> <g font-size="9" text-anchor="middle" fill="currentColor">
      <text x="93" y="308">cache</text><text x="177" y="308">db</text><text x="305" y="308">cache</text><text x="389" y="308">db</text><text x="517" y="308">cache</text><text x="601" y="308">db</text><text x="729" y="308">cache</text><text x="813" y="308">db</text> </g> <g font-size="8.5" fill="currentColor" opacity="0.75"> <text x="54" y="334">everything on the</text><text x="54" y="345">request path lives</text><text x="54" y="356">inside the cell</text>
      <text x="478" y="334">no cross-cell calls.</text><text x="478" y="345">A cell that calls another</text><text x="478" y="356">cell is not a cell.</text> <text x="690" y="334">sized so losing one</text><text x="690" y="345">is survivable and</text><text x="690" y="356">running it is efficient</text> </g> <g font-size="8.5" font-weight="700" fill="#d64545">
      <text x="266" y="334">BAD DEPLOY LANDS HERE</text><text x="266" y="345">6,000 of 24,000 = 25.0%</text><text x="266" y="356">at 24 cells it is 4.17%</text> </g> <rect x="24" y="386" width="832" height="70" rx="10" fill="#e0930f" fill-opacity="0.09" stroke="#e0930f" stroke-width="1.6"/> <g fill="currentColor"> <text x="40" y="405" font-size="10.5" font-weight="700" fill="#e0930f">measured: what 24 cells cost and what they buy</text>
      <text x="40" y="422" font-size="9.5" opacity="0.9">1 cell&#8195;&#8195;243 instances&#8195;&#8195;+1.2% capacity overhead&#8195;&#8195;100.00% deploy blast radius&#8195;&#8195;20 min to roll out</text> <text x="40" y="438" font-size="9.5" opacity="0.9">24 cells&#8195;&#8195;288 instances&#8195;&#8195;+20.0% capacity overhead&#8195;&#8195;&#8195;4.17% deploy blast radius&#8195;&#8195;8 h to roll out</text>
      <text x="40" y="452" font-size="9" opacity="0.75">each cell must carry its own headroom and its own spare host, so overhead climbs slowly and then vertically.</text> </g> <text x="440" y="478" font-size="11" text-anchor="middle" fill="currentColor" opacity="0.9">The router is the only shared component. Keep it dumb, static and cached —</text>
    <text x="440" y="496" font-size="11" text-anchor="middle" fill="currentColor" opacity="0.9">it is the one thing in this picture that can take all four cells down at once.</text> </g>
</svg>
```

### Shuffle sharding, built up from ordinary sharding

Now the centrepiece. Go back to 8 workers and 800 customers, and consider three ways to assign customers to workers.

**Shared fleet.** Any customer's request may land on any worker. One poison request pins one worker; a loop of them pins all eight. Measured: **799 of 799 other customers down, 100.00%.**

**Fixed sharding.** Split the 8 workers into 4 shards of 2. Hash each customer to a shard. Now customer 0's poison reaches only its own shard's 2 workers — but every other customer in that shard is *completely* co-located with them, so every one of them is down. Measured: **189 down, 23.65%** (the run put customer 0 on shard 2, workers [4, 5]; the expectation is 25%, and 189 of 799 is ordinary sampling noise).

That is a real 4× improvement and it is where most systems stop. The problem is that it is also the *floor*: with 4 shards, the smallest blast radius available to you is 25%, and the only way to shrink it is more shards — which means smaller shards, which means each customer has fewer workers and less burst capacity and worse tail latency.

**Shuffle sharding.** Do not assign customers to a *shard*. Assign each customer a **random combination** of 2 workers out of the 8, drawn independently. Customer 0 might get {5, 7}; customer 1 might get {0, 5}; customer 2 might get {1, 3}.

Now count. The number of 2-element subsets of an 8-element set is

```text
C(8,2) = 8! / (2! x 6!) = (8 x 7) / (2 x 1) = 28
```

There are **28 distinct subsets**, and a customer is fully co-located with customer 0 only if it drew the *identical* subset — which happens with probability **1/28 = 3.571%**. Everyone else either shares one worker (probability `2 × 6 / 28 = 12/28 = 42.857%`) or shares nothing (`C(6,2)/28 = 15/28 = 53.571%`).

Measured over the same 799 customers: **21 fully down (2.63%), 339 degraded (42.43%), 439 untouched (54.94%)** — against theory of 3.57% / 42.86% / 53.57%. With 28 buckets and 799 draws, 21 against an expected 28.5 is **1.4 standard deviations** (sigma = 5.25). Ordinary sampling noise, and the program prints it as such.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 470" width="100%" style="max-width:840px" role="img" aria-label="Three placement strategies over the same eight workers, with the workers one poison customer can reach drawn in red and the measured outcome for the other 799 customers drawn as a proportional bar. A shared fleet lets the poison customer reach all eight workers and 100 percent of customers go down. Four fixed shards of two confine it to one shard and 23.65 percent go down. A shuffle shard of two workers out of eight confines it to two workers and only 2.63 percent go down, 42.43 percent are degraded to half capacity, and 54.94 percent never notice.">
  <g font-family="'JetBrains Mono', ui-monospace, monospace"> <text x="440" y="26" text-anchor="middle" font-size="14.5" font-weight="700" fill="currentColor">Same 8 workers, same bug, three blast radii</text> <text x="440" y="44" text-anchor="middle" font-size="10" fill="currentColor" opacity="0.75">customer 0 sends a request that pins every worker it can reach — 800 customers, seed 7</text> <g font-size="9" font-weight="700" fill="currentColor" opacity="0.6">
      <text x="24" y="70">PLACEMENT</text><text x="210" y="70">THE 8 WORKERS</text><text x="620" y="70">WHAT HAPPENS TO THE OTHER 799</text> </g> <path d="M24 76 L 856 76" fill="none" stroke="currentColor" stroke-width="1.1" opacity="0.35"/> <g fill="none" stroke-width="1.8">
      <rect x="210" y="94" width="36" height="36" rx="6" fill="#d64545" fill-opacity="0.14" stroke="#d64545"/><rect x="256" y="94" width="36" height="36" rx="6" fill="#d64545" fill-opacity="0.14" stroke="#d64545"/><rect x="302" y="94" width="36" height="36" rx="6" fill="#d64545" fill-opacity="0.14" stroke="#d64545"/><rect x="348" y="94" width="36" height="36" rx="6" fill="#d64545" fill-opacity="0.14" stroke="#d64545"/>
      <rect x="394" y="94" width="36" height="36" rx="6" fill="#d64545" fill-opacity="0.14" stroke="#d64545"/><rect x="440" y="94" width="36" height="36" rx="6" fill="#d64545" fill-opacity="0.14" stroke="#d64545"/><rect x="486" y="94" width="36" height="36" rx="6" fill="#d64545" fill-opacity="0.14" stroke="#d64545"/><rect x="532" y="94" width="36" height="36" rx="6" fill="#d64545" fill-opacity="0.14" stroke="#d64545"/> </g>
    <g font-size="10" font-weight="700" fill="#d64545" text-anchor="middle"> <text x="228" y="117">0</text><text x="274" y="117">1</text><text x="320" y="117">2</text><text x="366" y="117">3</text><text x="412" y="117">4</text><text x="458" y="117">5</text><text x="504" y="117">6</text><text x="550" y="117">7</text> </g> <g fill="currentColor">
      <text x="24" y="104" font-size="11.5" font-weight="700">shared fleet</text><text x="24" y="120" font-size="9" opacity="0.8">any request, any worker</text><text x="24" y="134" font-size="9" opacity="0.8">"we have 8 replicas!"</text> </g> <rect x="620" y="96" width="240" height="22" rx="3" fill="#d64545" fill-opacity="0.55" stroke="#d64545" stroke-width="1.3"/>
    <g fill="currentColor"><text x="740" y="111" font-size="10" font-weight="700" text-anchor="middle" fill="#d64545">799 DOWN</text><text x="620" y="134" font-size="12" font-weight="700" fill="#d64545">100.00% blast radius</text></g> <path d="M24 152 L 856 152" fill="none" stroke="currentColor" stroke-width="1" opacity="0.18"/> <g fill="none" stroke-width="1.8">
      <rect x="210" y="176" width="36" height="36" rx="6" fill="#0fa07f" fill-opacity="0.12" stroke="#0fa07f"/><rect x="256" y="176" width="36" height="36" rx="6" fill="#0fa07f" fill-opacity="0.12" stroke="#0fa07f"/><rect x="302" y="176" width="36" height="36" rx="6" fill="#0fa07f" fill-opacity="0.12" stroke="#0fa07f"/><rect x="348" y="176" width="36" height="36" rx="6" fill="#0fa07f" fill-opacity="0.12" stroke="#0fa07f"/>
      <rect x="394" y="176" width="36" height="36" rx="6" fill="#d64545" fill-opacity="0.16" stroke="#d64545"/><rect x="440" y="176" width="36" height="36" rx="6" fill="#d64545" fill-opacity="0.16" stroke="#d64545"/><rect x="486" y="176" width="36" height="36" rx="6" fill="#0fa07f" fill-opacity="0.12" stroke="#0fa07f"/><rect x="532" y="176" width="36" height="36" rx="6" fill="#0fa07f" fill-opacity="0.12" stroke="#0fa07f"/> </g>
    <g fill="none" stroke-dasharray="4 3" stroke-width="1.3" opacity="0.7"> <rect x="204" y="168" width="94" height="52" rx="7" stroke="currentColor"/><rect x="296" y="168" width="94" height="52" rx="7" stroke="currentColor"/><rect x="388" y="168" width="94" height="52" rx="7" stroke="#d64545"/><rect x="480" y="168" width="94" height="52" rx="7" stroke="currentColor"/> </g> <g font-size="10" font-weight="700" text-anchor="middle">
      <text x="228" y="199" fill="#0fa07f">0</text><text x="274" y="199" fill="#0fa07f">1</text><text x="320" y="199" fill="#0fa07f">2</text><text x="366" y="199" fill="#0fa07f">3</text><text x="412" y="199" fill="#d64545">4</text><text x="458" y="199" fill="#d64545">5</text><text x="504" y="199" fill="#0fa07f">6</text><text x="550" y="199" fill="#0fa07f">7</text> </g> <g font-size="8" fill="currentColor" opacity="0.6" text-anchor="middle">
      <text x="251" y="232">shard 0</text><text x="343" y="232">shard 1</text><text x="435" y="232" fill="#d64545" opacity="1" font-weight="700">shard 2</text><text x="527" y="232">shard 3</text> </g> <g fill="currentColor"> <text x="24" y="186" font-size="11.5" font-weight="700">4 fixed shards of 2</text><text x="24" y="202" font-size="9" opacity="0.8">hash(customer) -&gt; shard</text><text x="24" y="216" font-size="9" opacity="0.8">everyone shares entirely</text> </g>
    <rect x="620" y="178" width="56.8" height="22" rx="3" fill="#d64545" fill-opacity="0.55" stroke="#d64545" stroke-width="1.3"/> <rect x="676.8" y="178" width="183.2" height="22" rx="3" fill="#0fa07f" fill-opacity="0.35" stroke="#0fa07f" stroke-width="1.3"/>
    <g fill="currentColor"><text x="768" y="193" font-size="9.5" font-weight="700" text-anchor="middle" fill="#0fa07f">610 unaffected</text><text x="620" y="216" font-size="12" font-weight="700" fill="#d64545">23.65% blast radius</text><text x="620" y="232" font-size="9" opacity="0.8">189 customers, all of them fully down</text></g> <path d="M24 250 L 856 250" fill="none" stroke="currentColor" stroke-width="1" opacity="0.18"/> <g fill="none" stroke-width="1.8">
      <rect x="210" y="286" width="36" height="36" rx="6" fill="#0fa07f" fill-opacity="0.12" stroke="#0fa07f"/><rect x="256" y="286" width="36" height="36" rx="6" fill="#0fa07f" fill-opacity="0.12" stroke="#0fa07f"/><rect x="302" y="286" width="36" height="36" rx="6" fill="#0fa07f" fill-opacity="0.12" stroke="#0fa07f"/><rect x="348" y="286" width="36" height="36" rx="6" fill="#0fa07f" fill-opacity="0.12" stroke="#0fa07f"/>
      <rect x="394" y="286" width="36" height="36" rx="6" fill="#0fa07f" fill-opacity="0.12" stroke="#0fa07f"/><rect x="440" y="286" width="36" height="36" rx="6" fill="#d64545" fill-opacity="0.16" stroke="#d64545"/><rect x="486" y="286" width="36" height="36" rx="6" fill="#0fa07f" fill-opacity="0.12" stroke="#0fa07f"/><rect x="532" y="286" width="36" height="36" rx="6" fill="#d64545" fill-opacity="0.16" stroke="#d64545"/> </g>
    <g font-size="10" font-weight="700" text-anchor="middle"> <text x="228" y="309" fill="#0fa07f">0</text><text x="274" y="309" fill="#0fa07f">1</text><text x="320" y="309" fill="#0fa07f">2</text><text x="366" y="309" fill="#0fa07f">3</text><text x="412" y="309" fill="#0fa07f">4</text><text x="458" y="309" fill="#d64545">5</text><text x="504" y="309" fill="#0fa07f">6</text><text x="550" y="309" fill="#d64545">7</text> </g>
    <path d="M458 282 C 458 270, 550 270, 550 282" fill="none" stroke="#d64545" stroke-width="1.6"/> <text x="504" y="264" font-size="9" font-weight="700" text-anchor="middle" fill="#d64545">customer 0 drew {5, 7}</text> <g fill="currentColor"> <text x="24" y="296" font-size="11.5" font-weight="700">shuffle shard, 2 of 8</text><text x="24" y="312" font-size="9" opacity="0.8">a random COMBINATION</text><text x="24" y="326" font-size="9" opacity="0.8">C(8,2) = 28 of them</text>
    </g> <rect x="620" y="288" width="6.3" height="22" rx="1.5" fill="#d64545" fill-opacity="0.7" stroke="#d64545" stroke-width="1.2"/> <rect x="626.3" y="288" width="101.8" height="22" rx="3" fill="#e0930f" fill-opacity="0.4" stroke="#e0930f" stroke-width="1.3"/> <rect x="728.1" y="288" width="131.9" height="22" rx="3" fill="#0fa07f" fill-opacity="0.35" stroke="#0fa07f" stroke-width="1.3"/> <g fill="currentColor">
      <text x="677" y="303" font-size="9" font-weight="700" text-anchor="middle" fill="#e0930f">339 at half speed</text><text x="794" y="303" font-size="9" font-weight="700" text-anchor="middle" fill="#0fa07f">439 unaffected</text> <text x="620" y="326" font-size="12" font-weight="700" fill="#d64545">2.63% blast radius</text><text x="620" y="342" font-size="9" opacity="0.85">21 customers drew the same pair {5,7}</text> </g>
    <path d="M24 362 L 856 362" fill="none" stroke="currentColor" stroke-width="1" opacity="0.18"/> <g fill="none" stroke-width="1.6"> <rect x="24" y="376" width="832" height="52" rx="9" fill="#e0930f" fill-opacity="0.09" stroke="#e0930f"/> </g> <g fill="currentColor"> <text x="40" y="396" font-size="10.5" font-weight="700" fill="#e0930f">the amber block is the whole idea</text>
      <text x="40" y="412" font-size="9.5" opacity="0.9">Those 339 customers each lost 1 of their 2 workers. That is 50% of their capacity and 0% of their availability —</text> <text x="40" y="424" font-size="9.5" opacity="0.9">but only if the client retries the OTHER member of its own subset. Without that retry they are 339 more outages.</text> </g>
    <text x="440" y="452" font-size="11" text-anchor="middle" fill="currentColor" opacity="0.9">Same hardware, same bug, same 800 customers. 100% -&gt; 23.65% -&gt; 2.63% is a choice you make at assignment time.</text> </g>
</svg>
```

The same eight machines. The same bug. **100% → 23.65% → 2.63%.** No extra hardware, no new component, no state to store — the assignment is a function of the customer id.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 494" width="100%" style="max-width:840px" role="img" aria-label="A matrix of all 28 two-worker subsets you can draw from eight workers. One cell, the pair five-seven, is the victim's subset and is drawn in red: only a customer drawing that exact pair goes fully down, one chance in 28. Twelve cells share exactly one worker with it and are drawn amber: those customers lose half their capacity but stay up if they retry. Fifteen cells share nothing and are green. The right panel works the arithmetic longhand for C of 8 choose 2 equals 28 and for C of 100 choose 5 equals 75,287,520.">
  <defs> <marker id="p11-09-d2a" markerWidth="10" markerHeight="10" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#d64545"/></marker> </defs> <g font-family="'JetBrains Mono', ui-monospace, monospace"> <text x="440" y="26" text-anchor="middle" font-size="14.5" font-weight="700" fill="currentColor">All 28 subsets, and the one that collides</text>
    <text x="440" y="44" text-anchor="middle" font-size="10" fill="currentColor" opacity="0.75">every cell is one 2-of-8 combination a customer could be assigned. Victim drew {5,7}.</text> <text x="238" y="76" text-anchor="middle" font-size="9.5" font-weight="700" fill="currentColor" opacity="0.65">SECOND WORKER</text>
    <text x="64" y="242" text-anchor="middle" font-size="9.5" font-weight="700" fill="currentColor" opacity="0.65" transform="rotate(-90 64 242)">FIRST WORKER</text>
    <text x="123" y="104" font-size="9.5" text-anchor="middle" fill="currentColor" opacity="0.7" font-weight="700">0</text><text x="157" y="104" font-size="9.5" text-anchor="middle" fill="currentColor" opacity="0.7" font-weight="700">1</text><text x="191" y="104" font-size="9.5" text-anchor="middle" fill="currentColor" opacity="0.7" font-weight="700">2</text><text x="225" y="104" font-size="9.5" text-anchor="middle" fill="currentColor" opacity="0.7" font-weight="700">3</text><text x="259" y="104" font-size="9.5" text-anchor="middle" fill="currentColor" opacity="0.7" font-weight="700">4</text><text x="293" y="104" font-size="9.5" text-anchor="middle" fill="currentColor" opacity="0.7" font-weight="700">5</text><text x="327" y="104" font-size="9.5" text-anchor="middle" fill="currentColor" opacity="0.7" font-weight="700">6</text><text x="361" y="104" font-size="9.5" text-anchor="middle" fill="currentColor" opacity="0.7" font-weight="700">7</text><text x="98" y="131" font-size="9.5" text-anchor="end" fill="currentColor" opacity="0.7" font-weight="700">0</text><text x="98" y="165" font-size="9.5" text-anchor="end" fill="currentColor" opacity="0.7" font-weight="700">1</text><text x="98" y="199" font-size="9.5" text-anchor="end" fill="currentColor" opacity="0.7" font-weight="700">2</text><text x="98" y="233" font-size="9.5" text-anchor="end" fill="currentColor" opacity="0.7" font-weight="700">3</text><text x="98" y="267" font-size="9.5" text-anchor="end" fill="currentColor" opacity="0.7" font-weight="700">4</text><text x="98" y="301" font-size="9.5" text-anchor="end" fill="currentColor" opacity="0.7" font-weight="700">5</text><text x="98" y="335" font-size="9.5" text-anchor="end" fill="currentColor" opacity="0.7" font-weight="700">6</text><text x="98" y="369" font-size="9.5" text-anchor="end" fill="currentColor" opacity="0.7" font-weight="700">7</text>
    <rect x="142" y="112" width="30" height="30" rx="5" fill="#0fa07f" fill-opacity="0.14" stroke="#0fa07f" stroke-width="1.4"/><rect x="176" y="112" width="30" height="30" rx="5" fill="#0fa07f" fill-opacity="0.14" stroke="#0fa07f" stroke-width="1.4"/><rect x="210" y="112" width="30" height="30" rx="5" fill="#0fa07f" fill-opacity="0.14" stroke="#0fa07f" stroke-width="1.4"/><rect x="244" y="112" width="30" height="30" rx="5" fill="#0fa07f" fill-opacity="0.14" stroke="#0fa07f" stroke-width="1.4"/><rect x="278" y="112" width="30" height="30" rx="5" fill="#e0930f" fill-opacity="0.28" stroke="#e0930f" stroke-width="1.4"/><rect x="312" y="112" width="30" height="30" rx="5" fill="#0fa07f" fill-opacity="0.14" stroke="#0fa07f" stroke-width="1.4"/><rect x="346" y="112" width="30" height="30" rx="5" fill="#e0930f" fill-opacity="0.28" stroke="#e0930f" stroke-width="1.4"/><rect x="176" y="146" width="30" height="30" rx="5" fill="#0fa07f" fill-opacity="0.14" stroke="#0fa07f" stroke-width="1.4"/><rect x="210" y="146" width="30" height="30" rx="5" fill="#0fa07f" fill-opacity="0.14" stroke="#0fa07f" stroke-width="1.4"/><rect x="244" y="146" width="30" height="30" rx="5" fill="#0fa07f" fill-opacity="0.14" stroke="#0fa07f" stroke-width="1.4"/><rect x="278" y="146" width="30" height="30" rx="5" fill="#e0930f" fill-opacity="0.28" stroke="#e0930f" stroke-width="1.4"/><rect x="312" y="146" width="30" height="30" rx="5" fill="#0fa07f" fill-opacity="0.14" stroke="#0fa07f" stroke-width="1.4"/><rect x="346" y="146" width="30" height="30" rx="5" fill="#e0930f" fill-opacity="0.28" stroke="#e0930f" stroke-width="1.4"/><rect x="210" y="180" width="30" height="30" rx="5" fill="#0fa07f" fill-opacity="0.14" stroke="#0fa07f" stroke-width="1.4"/><rect x="244" y="180" width="30" height="30" rx="5" fill="#0fa07f" fill-opacity="0.14" stroke="#0fa07f" stroke-width="1.4"/><rect x="278" y="180" width="30" height="30" rx="5" fill="#e0930f" fill-opacity="0.28" stroke="#e0930f" stroke-width="1.4"/><rect x="312" y="180" width="30" height="30" rx="5" fill="#0fa07f" fill-opacity="0.14" stroke="#0fa07f" stroke-width="1.4"/><rect x="346" y="180" width="30" height="30" rx="5" fill="#e0930f" fill-opacity="0.28" stroke="#e0930f" stroke-width="1.4"/><rect x="244" y="214" width="30" height="30" rx="5" fill="#0fa07f" fill-opacity="0.14" stroke="#0fa07f" stroke-width="1.4"/><rect x="278" y="214" width="30" height="30" rx="5" fill="#e0930f" fill-opacity="0.28" stroke="#e0930f" stroke-width="1.4"/><rect x="312" y="214" width="30" height="30" rx="5" fill="#0fa07f" fill-opacity="0.14" stroke="#0fa07f" stroke-width="1.4"/><rect x="346" y="214" width="30" height="30" rx="5" fill="#e0930f" fill-opacity="0.28" stroke="#e0930f" stroke-width="1.4"/><rect x="278" y="248" width="30" height="30" rx="5" fill="#e0930f" fill-opacity="0.28" stroke="#e0930f" stroke-width="1.4"/><rect x="312" y="248" width="30" height="30" rx="5" fill="#0fa07f" fill-opacity="0.14" stroke="#0fa07f" stroke-width="1.4"/><rect x="346" y="248" width="30" height="30" rx="5" fill="#e0930f" fill-opacity="0.28" stroke="#e0930f" stroke-width="1.4"/><rect x="312" y="282" width="30" height="30" rx="5" fill="#e0930f" fill-opacity="0.28" stroke="#e0930f" stroke-width="1.4"/><rect x="346" y="282" width="30" height="30" rx="5" fill="#d64545" fill-opacity="0.55" stroke="#d64545" stroke-width="1.4"/><rect x="346" y="316" width="30" height="30" rx="5" fill="#e0930f" fill-opacity="0.28" stroke="#e0930f" stroke-width="1.4"/>
    <text x="157" y="131" font-size="8.5" text-anchor="middle" fill="currentColor" font-weight="400" opacity="0.65">01</text><text x="191" y="131" font-size="8.5" text-anchor="middle" fill="currentColor" font-weight="400" opacity="0.65">02</text><text x="225" y="131" font-size="8.5" text-anchor="middle" fill="currentColor" font-weight="400" opacity="0.65">03</text><text x="259" y="131" font-size="8.5" text-anchor="middle" fill="currentColor" font-weight="400" opacity="0.65">04</text><text x="293" y="131" font-size="8.5" text-anchor="middle" fill="currentColor" font-weight="400" opacity="1">05</text><text x="327" y="131" font-size="8.5" text-anchor="middle" fill="currentColor" font-weight="400" opacity="0.65">06</text><text x="361" y="131" font-size="8.5" text-anchor="middle" fill="currentColor" font-weight="400" opacity="1">07</text><text x="191" y="165" font-size="8.5" text-anchor="middle" fill="currentColor" font-weight="400" opacity="0.65">12</text><text x="225" y="165" font-size="8.5" text-anchor="middle" fill="currentColor" font-weight="400" opacity="0.65">13</text><text x="259" y="165" font-size="8.5" text-anchor="middle" fill="currentColor" font-weight="400" opacity="0.65">14</text><text x="293" y="165" font-size="8.5" text-anchor="middle" fill="currentColor" font-weight="400" opacity="1">15</text><text x="327" y="165" font-size="8.5" text-anchor="middle" fill="currentColor" font-weight="400" opacity="0.65">16</text><text x="361" y="165" font-size="8.5" text-anchor="middle" fill="currentColor" font-weight="400" opacity="1">17</text><text x="225" y="199" font-size="8.5" text-anchor="middle" fill="currentColor" font-weight="400" opacity="0.65">23</text><text x="259" y="199" font-size="8.5" text-anchor="middle" fill="currentColor" font-weight="400" opacity="0.65">24</text><text x="293" y="199" font-size="8.5" text-anchor="middle" fill="currentColor" font-weight="400" opacity="1">25</text><text x="327" y="199" font-size="8.5" text-anchor="middle" fill="currentColor" font-weight="400" opacity="0.65">26</text><text x="361" y="199" font-size="8.5" text-anchor="middle" fill="currentColor" font-weight="400" opacity="1">27</text><text x="259" y="233" font-size="8.5" text-anchor="middle" fill="currentColor" font-weight="400" opacity="0.65">34</text><text x="293" y="233" font-size="8.5" text-anchor="middle" fill="currentColor" font-weight="400" opacity="1">35</text><text x="327" y="233" font-size="8.5" text-anchor="middle" fill="currentColor" font-weight="400" opacity="0.65">36</text><text x="361" y="233" font-size="8.5" text-anchor="middle" fill="currentColor" font-weight="400" opacity="1">37</text><text x="293" y="267" font-size="8.5" text-anchor="middle" fill="currentColor" font-weight="400" opacity="1">45</text><text x="327" y="267" font-size="8.5" text-anchor="middle" fill="currentColor" font-weight="400" opacity="0.65">46</text><text x="361" y="267" font-size="8.5" text-anchor="middle" fill="currentColor" font-weight="400" opacity="1">47</text><text x="327" y="301" font-size="8.5" text-anchor="middle" fill="currentColor" font-weight="400" opacity="1">56</text><text x="361" y="301" font-size="8.5" text-anchor="middle" fill="#d64545" font-weight="700" opacity="1">57</text><text x="361" y="335" font-size="8.5" text-anchor="middle" fill="currentColor" font-weight="400" opacity="1">67</text>
    <path d="M341 368 L 345 312" fill="none" stroke="#d64545" stroke-width="1.5" marker-end="url(#p11-09-d2a)"/> <text x="330" y="368" font-size="9.5" font-weight="700" text-anchor="end" fill="#d64545">customer 0 was assigned {5,7}</text> <text x="330" y="382" font-size="9.5" text-anchor="end" fill="#d64545" opacity="0.85">the only cell that is a full outage</text> <g fill="none" stroke-width="1.7">
      <rect x="430" y="66" width="426" height="106" rx="10" fill="#3553ff" fill-opacity="0.09" stroke="#3553ff"/> <rect x="430" y="184" width="426" height="116" rx="10" fill="#7f7f7f" fill-opacity="0.07" stroke="currentColor" stroke-opacity="0.4"/> <rect x="430" y="312" width="426" height="106" rx="10" fill="#7c5cff" fill-opacity="0.10" stroke="#7c5cff"/> </g> <g fill="currentColor">
      <text x="446" y="88" font-size="11" font-weight="700" fill="#3553ff">the count, longhand</text> <text x="446" y="108" font-size="10.5">C(8,2) = 8! / (2! x 6!) = (8 x 7) / (2 x 1) = 28</text> <text x="446" y="128" font-size="9.5" opacity="0.9">P(a second customer draws your exact pair) = 1/28 = 3.571%</text> <text x="446" y="146" font-size="9.5" opacity="0.9">P(shares exactly one) = 2 x 6 / 28 = 12/28 = 42.857%</text>
      <text x="446" y="164" font-size="9.5" opacity="0.9">P(shares nothing) = C(6,2)/28 = 15/28 = 53.571%</text> <text x="446" y="206" font-size="11" font-weight="700">measured over 799 customers, seed 7</text> <text x="446" y="226" font-size="9.5" opacity="0.9">fully down (drew {5,7})&#8195;&#8195;21&#8195;&#8195;2.63%&#8195;&#8195;theory 3.57%</text>
      <text x="446" y="244" font-size="9.5" opacity="0.9">degraded (shares one)&#8195;&#8195;&#8195;339&#8195;&#8195;42.43%&#8195;&#8195;theory 42.86%</text> <text x="446" y="262" font-size="9.5" opacity="0.9">never noticed&#8195;&#8195;&#8195;&#8195;&#8195;&#8195;&#8195;439&#8195;&#8195;54.94%&#8195;&#8195;theory 53.57%</text> <text x="446" y="284" font-size="9" opacity="0.7">28 buckets and 799 draws: 21 vs an expected 28.5 is 1.4 sigma. Normal.</text>
      <text x="446" y="334" font-size="11" font-weight="700" fill="#7c5cff">now make the fleet realistic: 100 workers, k = 5</text> <text x="446" y="356" font-size="10.5">C(100,5) = (100 x 99 x 98 x 97 x 96) / (5 x 4 x 3 x 2 x 1)</text> <text x="446" y="374" font-size="10.5">&#8195;&#8195;&#8195;&#8195;&#8195;&#8195; = 9,034,502,400 / 120 = 75,287,520</text>
      <text x="446" y="396" font-size="9.5" opacity="0.9">one customer in 75 million shares your whole subset. You have</text> <text x="446" y="410" font-size="9.5" opacity="0.9">thousands of customers, not tens of millions. Nobody does.</text> </g> <g fill="none" stroke-width="1.5"> <rect x="60" y="432" width="16" height="16" rx="4" fill="#d64545" fill-opacity="0.55" stroke="#d64545"/>
      <rect x="264" y="432" width="16" height="16" rx="4" fill="#e0930f" fill-opacity="0.28" stroke="#e0930f"/> <rect x="536" y="432" width="16" height="16" rx="4" fill="#0fa07f" fill-opacity="0.14" stroke="#0fa07f"/> </g> <g fill="currentColor" font-size="9.5"> <text x="84" y="445">1 cell&#8195;fully down</text><text x="288" y="445">12 cells&#8195;half capacity, still up</text><text x="560" y="445">15 cells&#8195;never noticed</text> </g>
    <text x="440" y="476" font-size="11" text-anchor="middle" fill="currentColor" opacity="0.9">Adding one worker to the pool turns 28 combinations into 36. Blast radius is combinatorial, and combinatorics are cheap.</text> </g>
</svg>
```

And it gets dramatically better with scale, because the combinatorics are super-linear. Take a realistic fleet — 100 workers, subsets of 5:

```text
C(100,5) = (100 x 99 x 98 x 97 x 96) / (5 x 4 x 3 x 2 x 1)
         = 9,034,502,400 / 120 = 75,287,520
```

**Seventy-five million distinct subsets, from a hundred machines.** The probability that any given customer shares your entire subset is `1.328e-08`. You do not have 75 million customers. Nobody does. With 100 workers and `k = 8` there are 186,087,894,300 combinations; with 1,000 workers and `k = 5` there are 8,250,291,250,200. This is the part that feels like a trick, and it is worth being clear that it is not: you are not creating capacity or reliability out of nothing. You are **spending the entropy in the assignment** to make complete co-location astronomically unlikely.

### Partial overlap is survivable — and that is the whole technique

Here is the objection, and it is the correct objection: *most customers share at least one worker with the victim*. At N = 100 and k = 5, the Build It measures **23.07% of customers sharing at least one worker**. That is not a small number. If sharing one worker meant going down, shuffle sharding would be a disaster.

It does not mean going down, **provided the client retries a different member of its own subset.** A customer that shares 1 of its 5 workers with the poison customer has 4 healthy workers. It has lost 20% of its capacity and 0% of its availability. The metric that matters is therefore not "probability of any overlap" — which is high, and is the number sceptics quote — but **"probability of *full* overlap"**, which is `1/C(N,k)` and is minuscule. The mechanism that converts the first number into the second is **retry-with-failover**, and it is not optional garnish. It is the technique.

The Build It makes this exact, over 200,000 simulated customers:

```text
 shared   customers   measured   analytic  errors: no  errors: w/  capacity
workers                  share      share    failover    failover      left
      0     153,862  76.9310%  76.9590%         0%         0%     100%
      1      42,308  21.1540%  21.1426%        20%         0%      80%
      2       3,681   1.8405%   1.8385%        40%         0%      60%
      3         148   0.0740%   0.0593%        60%         0%      40%
      4           1   0.0005%   0.0006%        80%         0%      20%
      5           0   0.0000%   0.0000%       100%       100%       0%
```

And then the comparison that should decide the argument:

```text
scheme                              customers    customers   fleet-wide
                                    w/ errors   fully down   error rate
fixed shard of 5 (20 shards)          5.0000%      5.0000%      5.0000%
shuffle shard, NO failover           23.0690%      0.0000%      5.0118%
shuffle shard + failover retry        0.0000%      0.0000%     1.33e-08
```

Read the middle row, because it is the honest one and it is usually left out. **Without failover, shuffle sharding produces the same fleet-wide error volume as a fixed shard — 5.0118% against 5.0000%, both of which are just `k/N` — and spreads it across 4.6× more customers.** It is not an improvement. It is *worse*: the same number of failed requests, distributed so that four and a half times as many customers notice and open tickets.

Add the retry and the same placement gives a fleet-wide error rate of **1.33e-08**. Nothing about the assignment changed. The client did.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 592" width="100%" style="max-width:840px" role="img" aria-label="A log-scale histogram of how many of 200,000 shuffle-sharded customers share exactly zero, one, two, three, four or five workers with the poison customer, for 100 workers and subsets of five. 153,862 share none, 42,308 share one, 3,681 share two, 148 share three, one shares four and none share all five. Beneath each bar are two bands: without failover those customers lose 0, 20, 40, 60, 80 and 100 percent of their requests, giving a fleet-wide error rate of 5.0118 percent; with a client that retries another member of its own subset every band except the last is zero, giving a fleet-wide error rate of 1.33 times ten to the minus eight.">
  <g font-family="'JetBrains Mono', ui-monospace, monospace"> <text x="440" y="26" text-anchor="middle" font-size="14.5" font-weight="700" fill="currentColor">Partial overlap is everywhere. Full overlap is nowhere.</text> <text x="440" y="44" text-anchor="middle" font-size="10" fill="currentColor" opacity="0.75">measured: 200,000 customers, N = 100 workers, k = 5, seed 11. Log scale — each gridline is 10x.</text>
    <text x="30" y="74" font-size="9.5" font-weight="700" fill="currentColor" opacity="0.65">CUSTOMERS</text>
    <path d="M110 340 L 830 340" fill="none" stroke="currentColor" stroke-width="1" opacity="0.5"/><path d="M110 298 L 830 298" fill="none" stroke="currentColor" stroke-width="1" opacity="0.16"/><path d="M110 256 L 830 256" fill="none" stroke="currentColor" stroke-width="1" opacity="0.16"/><path d="M110 214 L 830 214" fill="none" stroke="currentColor" stroke-width="1" opacity="0.16"/><path d="M110 172 L 830 172" fill="none" stroke="currentColor" stroke-width="1" opacity="0.16"/><path d="M110 130 L 830 130" fill="none" stroke="currentColor" stroke-width="1" opacity="0.16"/><text x="100" y="343" font-size="9" text-anchor="end" fill="currentColor" opacity="0.65">1</text><text x="100" y="301" font-size="9" text-anchor="end" fill="currentColor" opacity="0.65">10</text><text x="100" y="259" font-size="9" text-anchor="end" fill="currentColor" opacity="0.65">100</text><text x="100" y="217" font-size="9" text-anchor="end" fill="currentColor" opacity="0.65">1k</text><text x="100" y="175" font-size="9" text-anchor="end" fill="currentColor" opacity="0.65">10k</text><text x="100" y="133" font-size="9" text-anchor="end" fill="currentColor" opacity="0.65">100k</text><rect x="110" y="122.1" width="100" height="217.9" rx="4" fill="#0fa07f" fill-opacity="0.30" stroke="#0fa07f" stroke-width="1.8"/><rect x="232" y="145.7" width="100" height="194.3" rx="4" fill="#e0930f" fill-opacity="0.30" stroke="#e0930f" stroke-width="1.8"/><rect x="354" y="190.2" width="100" height="149.8" rx="4" fill="#e0930f" fill-opacity="0.30" stroke="#e0930f" stroke-width="1.8"/><rect x="476" y="248.8" width="100" height="91.2" rx="4" fill="#e0930f" fill-opacity="0.30" stroke="#e0930f" stroke-width="1.8"/><rect x="598" y="336.0" width="100" height="4.0" rx="4" fill="#e0930f" fill-opacity="0.30" stroke="#e0930f" stroke-width="1.8"/><rect x="720" y="336.0" width="100" height="4" rx="2" fill="#d64545" fill-opacity="0.30" stroke="#d64545" stroke-width="1.8" stroke-dasharray="4 3"/><text x="160" y="114" font-size="10.5" font-weight="700" text-anchor="middle" fill="#0fa07f">153,862</text><text x="282" y="138" font-size="10.5" font-weight="700" text-anchor="middle" fill="#e0930f">42,308</text><text x="404" y="182" font-size="10.5" font-weight="700" text-anchor="middle" fill="#e0930f">3,681</text><text x="526" y="241" font-size="10.5" font-weight="700" text-anchor="middle" fill="#e0930f">148</text><text x="648" y="328" font-size="10.5" font-weight="700" text-anchor="middle" fill="#e0930f">1</text><text x="770" y="326" font-size="10.5" font-weight="700" text-anchor="middle" fill="#d64545">0</text>
    <text x="440" y="362" font-size="9.5" font-weight="700" text-anchor="middle" fill="currentColor" opacity="0.65">WORKERS SHARED WITH THE POISON CUSTOMER  (j)</text>
    <text x="160" y="384" font-size="15" font-weight="700" text-anchor="middle" fill="currentColor">0</text><text x="282" y="384" font-size="15" font-weight="700" text-anchor="middle" fill="currentColor">1</text><text x="404" y="384" font-size="15" font-weight="700" text-anchor="middle" fill="currentColor">2</text><text x="526" y="384" font-size="15" font-weight="700" text-anchor="middle" fill="currentColor">3</text><text x="648" y="384" font-size="15" font-weight="700" text-anchor="middle" fill="currentColor">4</text><text x="770" y="384" font-size="15" font-weight="700" text-anchor="middle" fill="currentColor">5</text>
    <text x="160" y="400" font-size="9.5" font-weight="400" text-anchor="middle" fill="currentColor">76.9310%</text><text x="282" y="400" font-size="9.5" font-weight="400" text-anchor="middle" fill="currentColor">21.1540%</text><text x="404" y="400" font-size="9.5" font-weight="400" text-anchor="middle" fill="currentColor">1.8405%</text><text x="526" y="400" font-size="9.5" font-weight="400" text-anchor="middle" fill="currentColor">0.0740%</text><text x="648" y="400" font-size="9.5" font-weight="400" text-anchor="middle" fill="currentColor">0.0005%</text><text x="770" y="400" font-size="9.5" font-weight="400" text-anchor="middle" fill="currentColor">0.0000%</text>
    <text x="100" y="400" font-size="9" text-anchor="end" fill="currentColor" opacity="0.6">of all</text> <rect x="110" y="412" width="720" height="34" rx="7" fill="#d64545" fill-opacity="0.10" stroke="#d64545" stroke-width="1.6"/> <rect x="110" y="454" width="720" height="34" rx="7" fill="#0fa07f" fill-opacity="0.11" stroke="#0fa07f" stroke-width="1.6"/> <text x="100" y="427" font-size="9" text-anchor="end" fill="#d64545" font-weight="700">NO failover</text>
    <text x="100" y="439" font-size="8.5" text-anchor="end" fill="currentColor" opacity="0.7">requests failed</text> <text x="100" y="469" font-size="9" text-anchor="end" fill="#0fa07f" font-weight="700">WITH failover</text> <text x="100" y="481" font-size="8.5" text-anchor="end" fill="currentColor" opacity="0.7">requests failed</text>
    <text x="160" y="434" font-size="12.5" font-weight="700" text-anchor="middle" fill="#0fa07f">0%</text><text x="282" y="434" font-size="12.5" font-weight="700" text-anchor="middle" fill="#d64545">20%</text><text x="404" y="434" font-size="12.5" font-weight="700" text-anchor="middle" fill="#d64545">40%</text><text x="526" y="434" font-size="12.5" font-weight="700" text-anchor="middle" fill="#d64545">60%</text><text x="648" y="434" font-size="12.5" font-weight="700" text-anchor="middle" fill="#d64545">80%</text><text x="770" y="434" font-size="12.5" font-weight="700" text-anchor="middle" fill="#d64545">100%</text>
    <text x="160" y="476" font-size="12.5" font-weight="700" text-anchor="middle" fill="#0fa07f">0%</text><text x="282" y="476" font-size="12.5" font-weight="700" text-anchor="middle" fill="#0fa07f">0%</text><text x="404" y="476" font-size="12.5" font-weight="700" text-anchor="middle" fill="#0fa07f">0%</text><text x="526" y="476" font-size="12.5" font-weight="700" text-anchor="middle" fill="#0fa07f">0%</text><text x="648" y="476" font-size="12.5" font-weight="700" text-anchor="middle" fill="#0fa07f">0%</text><text x="770" y="476" font-size="12.5" font-weight="700" text-anchor="middle" fill="#d64545">100%</text>
    <text x="160" y="510" font-size="10" font-weight="700" text-anchor="middle" fill="currentColor">100%</text><text x="282" y="510" font-size="10" font-weight="700" text-anchor="middle" fill="currentColor">80%</text><text x="404" y="510" font-size="10" font-weight="700" text-anchor="middle" fill="currentColor">60%</text><text x="526" y="510" font-size="10" font-weight="700" text-anchor="middle" fill="currentColor">40%</text><text x="648" y="510" font-size="10" font-weight="700" text-anchor="middle" fill="currentColor">20%</text><text x="770" y="510" font-size="10" font-weight="700" text-anchor="middle" fill="currentColor">0%</text>
    <text x="100" y="510" font-size="9" text-anchor="end" fill="currentColor" opacity="0.7">capacity left</text> <text x="440" y="538" font-size="10.5" text-anchor="middle" fill="currentColor">fleet-wide error rate&#8195;&#8195;NO failover <tspan font-weight="700" fill="#d64545">5.0118%</tspan>&#8195;&#8195;WITH failover <tspan font-weight="700" fill="#0fa07f">1.33e-08</tspan>&#8195;&#8195;a fixed shard of 5 gives <tspan font-weight="700">5.0000%</tspan></text>
    <text x="440" y="560" font-size="11" text-anchor="middle" fill="currentColor" opacity="0.9">Without the retry, shuffle sharding spreads the same 5% of failures over 4.6x more customers.</text> <text x="440" y="576" font-size="11" text-anchor="middle" fill="currentColor" opacity="0.9">The retry is not an optimisation — it IS the technique.</text> </g>
</svg>
```

### What shuffle sharding does not do

Every technique has a shape, and knowing the shape is what separates using it from cargo-culting it. Shuffle sharding assumes **the failure is caused by the customer's own traffic and follows that customer around.** A poison request, a pathological query, a tenant whose workload is simply too heavy — these travel with the customer, so confining the customer confines them.

It does nothing at all against:

- **A bad deploy.** The new binary goes to every worker in every subset. Cells and waved rollouts are the answer here, not shuffle sharding.
- **A shared dependency.** If all 100 workers call one database and the database is unwell, your subset is 5 sick workers instead of 100. Congratulations.
- **A globally exhausted resource.** A licence server, a connection limit at the database, an IP pool, a rate limit on a downstream API — anything where the resource is fleet-wide.
- **A correlated input.** If a poison *document format* arrives from 200 customers at once because they all use the same upstream vendor, the "one customer" premise is false and the failure is fleet-wide again.

Shuffle sharding is one tool for one failure mode. It happens to be a very cheap tool for a very common failure mode.

### Bulkheads at fleet scale

Lesson 11 of Phase 8 built a **bulkhead** inside a single process: a separate thread pool per dependency, so one slow downstream could not consume every worker thread. It measured an endpoint that called nothing at all going from a 905 ms p99 to a 5 ms p99 purely by refusing to share threads. See [Backpressure, Queueing & Load Shedding](../../08-concurrency-and-performance/11-backpressure-and-load-shedding/) for that build.

The fleet-level version is the same idea with machines instead of threads, and it separates three things:

- **Tenants.** Shuffle sharding is the fine-grained version. The coarse version is a **quarantine fleet**: when you identify a tenant that is abusive, broken or simply enormous, you move them onto their own capacity. This is a button you want to have built *before* you need it, and it needs to be a config change, not a deploy.
- **Criticality tiers.** Checkout and analytics should not share instances. If they do, then during overload your load shedder is choosing between them at request granularity — which works, but only if it is correct under pressure. Separate fleets make it structural.
- **Traffic classes.** The most valuable split in practice is **control plane vs data plane**. The control plane is where you create, configure and delete things; the data plane is where requests get served. They have completely different load profiles, availability requirements and change rates, and the data plane must keep working when the control plane is down. Which is the next idea.

### Static stability

**Static stability** is an AWS design principle worth naming precisely: *a system should continue to operate correctly during a failure without needing to make any changes.* No scaling up, no reconfiguration, no lookups, no calls to a control plane.

The reasoning is uncomfortable and correct: **anything you must do during a failure is a dependency that will be unavailable exactly when you need it.** The API you would call to launch instances is in the same region that is having the problem. The service discovery system you would query to find the surviving replicas is running on the hosts that just went away. The config service you would consult to flip to degraded mode is behind the load balancer that is currently timing out.

In practice this means three things:

- **Pre-provisioned capacity, not autoscaling into an outage.** If you run in 3 AZs and want to survive losing one, run each AZ at 50% of total demand — 150% total. Do not run at 105% and plan to scale.
- **Cached configuration.** Every instance holds the last-known-good config on local disk and boots from it. A config service that is down should be invisible.
- **A data plane that works without the control plane.** Serving requests must not require the ability to create, modify or discover anything.

The Build It simulates losing one AZ of three under both strategies, with a realistic reaction budget — 60 s of metric aggregation, 60 s of alarm evaluation, 180 s of instance launch and health-check and load-balancer registration, then new capacity arriving in throttled batches because the control plane is in the outage too:

```text
  t (s)  static cap   served  elastic cap   served   note
      0       150.0    100%        105.0    100%
     60       100.0    100%         70.0     70%   <-- AZ-2 gone
    300       100.0    100%         70.0     70%
    360       100.0    100%         75.0     75%   <-- first new instance in service
    510       100.0    100%        100.0    100%
```

The pre-provisioned fleet is a flat line at 100%. It did nothing, which was the entire plan. The elastic fleet fell to **70% for five full minutes before a single replacement instance entered service**, and did not recover until **t = 510 s — 450 seconds of degradation and 11,250 lost requests** against the static fleet's zero. The static fleet costs **43% more hardware**. That is the price, stated plainly: you are buying idle capacity, and what you get for it is a system with no dependencies at the moment it has the fewest.

Lesson 13 pays this off from the other side, where autoscaling is the right answer and the control loop is the problem.

## Build It

[`code/blast_radius.py`](code/blast_radius.py) is six numbered arguments in the standard library, seeded with `random.Random(7)`, finishing in about 13 seconds. The interesting parts:

**Assignment is one line, and it is the whole lesson.** Fixed sharding versus shuffle sharding differs by which of these two you call:

```python
# fixed shards: hash(customer) -> one of 4 shards of 2
assign_shard = [rng.randrange(N_SHARDS) for _ in range(N_CUSTOMERS)]

# shuffle shards: hash(customer) -> one of C(8,2) = 28 combinations
assign_sub = [frozenset(rng.sample(pool, SUBSET_K)) for _ in range(N_CUSTOMERS)]
```

Everything downstream — worker count, customer count, the poison customer, the seed — is identical between the two. Then the outcome for every other customer is decided by a set intersection, and the distinction between "down" and "degraded" is whether that intersection is the customer's *whole* subset:

```python
overlap = len(assign_sub[c] & vset)
if overlap == SUBSET_K:
    shuf_down += 1          # every worker this customer has is poisoned
elif overlap:
    shuf_degraded += 1      # some are: survivable IF the client fails over
```

**The analytic number is verified by sampling, not asserted.** Section 2 draws a victim subset, then draws millions of random customers and counts exact collisions. Analytic and empirical agreement is what makes the closed form trustworthy at scales sampling cannot reach:

```python
hits = 0
for _ in range(m):
    if set(rng.sample(pool, k)) == victim:
        hits += 1
analytic = 1.0 / math.comb(n, k)
empirical = hits / m
stderr = math.sqrt(max(hits, 1)) / m
```

**Correlated failure is modelled explicitly**, because the whole point is that it is not an afterthought:

```python
down = c * P_INSTANCE + (1 - c * P_INSTANCE) * ((1 - c) * P_INSTANCE) ** n
```

The first term is the shared cause — it does not have an exponent, which is precisely why replication cannot touch it. The second is the independent one, and `n` is the only place your redundancy appears.

Run it:

```bash
docker compose exec -T app python \
  phases/11-scalability-and-reliability/09-failure-domains-and-shuffle-sharding/code/blast_radius.py
```

```console
FAILURE DOMAINS, BLAST RADIUS & SHUFFLE SHARDING — measured
Phase 11 · Lesson 09 · seed=7 · stdlib only

== 1 · ONE CUSTOMER'S BUG, THREE PLACEMENT STRATEGIES ==
  800 customers, 8 workers, 1 poison customer.
  'down' = every worker the customer can reach is pinned.
  'degraded' = some but not all of them are.

  placement                      workers hit    down    blast   degraded
  shared fleet (no isolation)              8     799  100.00%          0
  4 fixed shards of 2                      2     189   23.65%          0
  shuffle shard, 2 of 8                    2      21    2.63%        339

  fixed sharding put the poison customer on shard 2 = workers [4, 5].
  shuffle sharding drew it workers [5, 7].

  outcome for the other 799           down      degraded     untouched
  measured                       21  2.63%   339 42.43%   439 54.94%
  theory  1/28, 12/28, 15/28         3.57%       42.86%       53.57%

  C(8,2) = 28 possible subsets, so an unlucky twin
  is drawn about 1 time in 28: expected 28.5 of 799, measured 21
  (sigma = 5.25, so the run sits 1.4 standard deviations low —
   ordinary sampling noise, not a result).
  339 more customers lost 1 of their 2 workers — 50% of their
  capacity, 0% of their availability IF the client retries the other one.

== 2 · THE COMBINATORICS: C(N,k) AND THE ODDS OF A FULL COLLISION ==
  P(another customer draws YOUR exact subset) = 1 / C(N,k)

       N   k                C(N,k)   P(full overlap)    reach
       8   2                    28         3.571e-02   25.0%
      16   3                   560         1.786e-03   18.8%
      24   4                10,626         9.411e-05   16.7%
      50   4               230,300         4.342e-06    8.0%
     100   2                 4,950         2.020e-04    2.0%
     100   3               161,700         6.184e-06    3.0%
     100   4             3,921,225         2.550e-07    4.0%
     100   5            75,287,520         1.328e-08    5.0%
     100   8       186,087,894,300         5.374e-12    8.0%
    1000   5     8,250,291,250,200         1.212e-13    0.5%
  'reach' = k/N, the fraction of the fleet one customer can touch —
  which is also the fraction it can damage. Bigger k buys isolation
  from your neighbours and costs you exposure to your own bugs.

  Monte-Carlo: draw a victim subset, then draw M customers at random
  and count how many landed on the identical subset. The +/- column is
  one standard error of the sample, so the analytic number should sit
  inside it.

       N   k     samples    hits    analytic   empirical  +/- 1 s.e.  emp/exact  s.e. off
       8   2     300,000   10737   3.571e-02   3.579e-02     3.5e-04      1.00x     -0.2
      16   3     800,000    1420   1.786e-03   1.775e-03     4.7e-05      0.99x      0.2
      24   4   4,000,000     340   9.411e-05   8.500e-05     4.6e-06      0.90x      2.0

  sampling agrees with the closed form, so the closed form can be
  trusted where sampling cannot reach: at N=100, k=5 you would need
  ~75 million draws to expect a single collision.

== 3 · OVERLAP DISTRIBUTION: PARTIAL IS COMMON, FULL IS NOT ==
  N = 100 workers, k = 5 per customer, 200,000 simulated customers.
  the poison customer pins all 5 of ITS workers. For everyone else:
  no failover  -> j/k of your requests hit a dead worker and fail.
  with failover-> the client retries a live member; you lose j/k of
                  your capacity but 0% of your availability.

   shared   customers   measured   analytic  errors: no  errors: w/  capacity
  workers                  share      share    failover    failover      left
        0     153,862  76.9310%  76.9590%         0%         0%     100%
        1      42,308  21.1540%  21.1426%        20%         0%      80%
        2       3,681   1.8405%   1.8385%        40%         0%      60%
        3         148   0.0740%   0.0593%        60%         0%      40%
        4           1   0.0005%   0.0006%        80%         0%      20%
        5           0   0.0000%   0.0000%       100%       100%       0%

  23.07% of customers share AT LEAST one worker with the
  poison customer. That is the number people quote to argue that
  shuffle sharding does not work. It is the wrong number to look at.

  scheme                              customers    customers   fleet-wide
                                      w/ errors   fully down   error rate
  fixed shard of 5 (20 shards)          5.0000%      5.0000%      5.0000%
  shuffle shard, NO failover           23.0690%      0.0000%      5.0118%
  shuffle shard + failover retry        0.0000%      0.0000%     1.33e-08

  read the middle row carefully. Without failover, shuffle sharding
  produces the SAME fleet-wide error volume as a fixed shard (5.01% vs
  5.00% — both are k/N) and spreads it across 4.6x more customers.
  It is not better. It is worse, and more customers file tickets.
  The retry is what converts it. Full overlap is 1 in 75,287,520;
  200,000 sampled customers produced 0, and the
  expected count was 0.0027.
  Shuffle sharding is not a placement trick. It is a placement trick
  PLUS a client that retries a different member of its own subset.

== 4 · CORRELATED FAILURE DESTROYS NAIVE AVAILABILITY MATH ==
  each instance is up 99.900% of the time (p = 0.001).
  c = the fraction of an instance's downtime that is COMMON CAUSE:
  a global config push, a deploy, a control plane, a DNS provider,
  a certificate expiry — things an availability zone boundary does
  not stop.

        c     2 instances   nines     3 instances   nines       ceiling
    0.000    99.9999000%    6.00    99.9999999%    9.00          none
    0.001    99.9998002%    5.70    99.9998999%    6.00         6.00n
    0.005    99.9994010%    5.22    99.9994999%    5.30         5.30n
    0.010    99.9989020%    4.96    99.9989999%    5.00         5.00n
    0.050    99.9949098%    4.29    99.9949999%    4.30         4.30n
    0.100    99.9899190%    4.00    99.9899999%    4.00         4.00n
    0.250    99.9749438%    3.60    99.9750000%    3.60         3.60n
    0.500    99.9499750%    3.30    99.9500000%    3.30         3.30n

  with c = 0, two 99.9% instances give 99.999900% — the 6.0 nines
  every capacity plan quietly assumes.
  with c = 0.01 — one failure in a hundred is shared — the same pair
  gives 99.99890%: 4.96 nines, not 6.00.
  adding a THIRD instance moves it to 5.00 nines. Adding a fourth,
  a fifth, a hundredth moves it nowhere: the ceiling is 1 - c*p.
  Redundancy multiplies the independent term and does nothing at all
  to the shared one. Lesson 01 promised this arithmetic; here it is.

== 5 · CELLS: WHAT A SMALLER BLAST RADIUS COSTS IN CAPACITY ==
  24,000 customers, 240,000 req/s at peak, 1,000 req/s per instance.
  each cell is provisioned for its OWN peak (mean + 3 sigma, Poisson arrivals)
  plus one spare instance so it survives losing a host.

   cells  cust/cell  inst/cell  instances  overhead  deploy blast  deploy time
       1     24,000        243        243     1.2%       100.00%        20 min
       2     12,000        123        246     2.5%        50.00%        40 min
       4      6,000         62        248     3.3%        25.00%        80 min
       8      3,000         32        256     6.7%        12.50%       160 min
      12      2,000         22        264    10.0%         8.33%       240 min
      24      1,000         12        288    20.0%         4.17%       480 min
      48        500          7        336    40.0%         2.08%       960 min
     120        200          4        480   100.0%         0.83%      2400 min

  one big fleet: a bad deploy that reaches every instance is a 100% outage.
  24 cells, deployed one cell at a time: the same bad deploy is a 4.17%
  outage, caught after 20 minutes of bake, and it costs 18.8% more
  hardware (288 instances instead of 243) and 8h to roll out.
  Note the shape: overhead climbs slowly, then vertically, because
  once a cell is down to 2-3 instances the +1 spare IS the cell.

== 6 · STATIC STABILITY: PRE-PROVISIONED VS AUTOSCALING INTO AN OUTAGE ==
  constant demand 100 units, 3 availability zones, AZ-2 lost at t=60s.
  static  : 50.0 units per AZ = 150.0 total (50% over demand). Does nothing.
  elastic : 35.0 units per AZ = 105.0 total (5% over demand). Must react.
  reaction budget: 60s metrics + 60s alarm + 180s launch, then
  5 units every 30s (the control plane is throttling — it is in the outage too).

    t (s)  static cap   served  elastic cap   served   note
        0       150.0    100%        105.0    100%
       30       150.0    100%        105.0    100%
       60       100.0    100%         70.0     70%   <-- AZ-2 gone
       90       100.0    100%         70.0     70%
     ...
      300       100.0    100%         70.0     70%
      330       100.0    100%         70.0     70%
      360       100.0    100%         75.0     75%   <-- first new instance in service
      390       100.0    100%         80.0     80%
      420       100.0    100%         85.0     85%
      450       100.0    100%         90.0     90%
      480       100.0    100%         95.0     95%
      510       100.0    100%        100.0    100%
      540       100.0    100%        100.0    100%
      570       100.0    100%        100.0    100%
      600       100.0    100%        100.0    100%

  static  : served 100% throughout. 0 requests lost.
  elastic : dropped to 70% at t=60s and did not recover until t=510s
            — 450s of degradation, 11,250 requests lost.
  the static fleet costs 43% more hardware and has zero dependencies
  during the failure. The elastic fleet is cheaper right up to the
  minute it needs an API that is having the same bad day it is.

  (total wall time 13.0 s)
```

**Section 1** is the headline and it is measured, not stipulated. Note what does *not* change between the three rows: eight workers, 800 customers, one bug, one seed. The only difference is which workers a customer is allowed to touch. The shared fleet takes **799 of 799** — total loss with eight healthy-looking replicas. Fixed shards take **189 (23.65%)**. Shuffle shards take **21 (2.63%)**, and the 339 "degraded" customers are the interesting ones: each lost exactly one of two workers, which is 50% of their capacity and 0% of their availability *if and only if* their client tries the other one.

**Section 2** is the proof. The Monte-Carlo columns exist so you do not have to take `1/C(N,k)` on faith. At (8, 2) the sampled rate is **3.579e-02 against an exact 3.571e-02** over 300,000 draws. At (16, 3), **1.775e-03 against 1.786e-03** over 800,000. At (24, 4) the exact answer is 9.411e-05 and four million draws produced **340 hits — an empirical 8.500e-05 with a standard error of 4.6e-06.** That last one sits **2.0 standard errors low**, which is what a rare event looks like when you have only 340 of them; the program prints the deviation rather than tuning it away. The point is that the closed form survives contact with sampling, so it can be trusted at (100, 5), where confirming it empirically would need roughly 75 million draws.

**Section 3 is the section to reread.** The histogram matches the hypergeometric prediction to three decimal places in the buckets that have enough mass to be meaningful (76.9310% measured against 76.9590% analytic; 21.1540% against 21.1426%). Then the comparison table does the thing most explanations of shuffle sharding skip: it prices the *no-failover* case honestly. **5.0118% fleet-wide errors against a fixed shard's 5.0000%** — identical, because both are `k/N` — spread over **4.6× more customers**. Shuffle sharding without client failover is a downgrade. With it, the same placement gives **1.33e-08**, and the 200,000 sampled customers produced zero full collisions against an expected count of 0.0027.

**Section 4** is why "we have three copies" is not a reliability argument. With truly independent failures, two 99.9% instances give **99.9999000% — 6.00 nines**. Introduce a common-cause fraction of just **1%** and the same pair gives **99.9989020%, 4.96 nines**. Adding a third instance takes it to **5.00 nines** and that is the end of the road: the ceiling is `1 − c·p` and further replication is decoration. Look at the `c = 0.5` row — where half of all downtime is shared — and note that two instances and three instances give **the same 3.30 nines to three significant figures.** The shared term dominates completely.

**Section 5** prices cells. The line to internalise is the shape of the overhead column: **1.2% → 3.3% → 20.0% → 100.0%** as you go 1 → 4 → 24 → 120 cells, against blast radius **100% → 25% → 4.17% → 0.83%**. There is a knee, it is somewhere around 24 cells for this fleet, and the reason is that each cell pays for its own `√demand` headroom and its own spare host. The deploy-time column is the other cost nobody budgets for: 24 cells at a 20-minute bake is **8 hours** to get a change out, which changes how you think about hotfixes.

**Section 6** is static stability with a stopwatch. The elastic fleet's 450 seconds of degradation is not pessimism — it is **60 s of metric aggregation + 60 s of alarm evaluation + 180 s of launch and registration** before the first replacement instance serves a single request, and then a throttled ramp. Every one of those delays is normal, documented, and unavoidable if your response to a failure is to ask a control plane for something. The static fleet's flat line cost 43% more hardware and required no decisions, no API calls and no luck.

## Use It

**Shuffle sharding in production.** The canonical description is AWS Builders' Library, *Workload isolation using shuffle-sharding*, which documents its use in **Amazon Route 53**: each customer's hosted zone is assigned 4 name servers from a large pool, so a query flood or a poison zone aimed at one customer reaches a tiny, randomised slice of the fleet. AWS also applies it in the AWS Shield / CloudFront request-routing layers. **Cell-based architecture** is documented by AWS as a general pattern and is used to structure many of their own services; **Slack** has published on migrating to a cell-based topology to contain AZ-level and dependency-level failures; **Netflix** organises around per-service isolation, dedicated capacity for critical paths and aggressive regional evacuation.

**Computing a customer's subset deterministically.** The subset must be a *pure function of the customer id* — no storage, no lookup, recomputable identically on every instance and stable across deploys and restarts. The standard construction is hash → seed a PRNG → shuffle → take `k`:

```python
import hashlib, random

def subset_for(customer_id: str, workers: list[str], k: int) -> list[str]:
    """Deterministic, stateless, stable across deploys and processes."""
    # A STABLE hash: Python's hash() is randomised per process (PYTHONHASHSEED)
    # and will hand the same customer a different subset on every restart.
    digest = hashlib.sha256(customer_id.encode()).digest()
    seed = int.from_bytes(digest[:8], "big")
    pool = sorted(workers)            # sort: input order must not matter
    random.Random(seed).shuffle(pool) # seeded shuffle: same id -> same order
    return pool[:k]
```

Three details are load-bearing. **Use a stable hash** — `hashlib`, not the built-in `hash()`, which is randomised per process by `PYTHONHASHSEED` and will silently re-shard every customer on every restart. **Sort the worker list first**, so that discovery returning members in a different order does not change anybody's subset. And **do not store the assignment**: a subset you can recompute needs no database, no cache and no migration, and it cannot drift between instances.

The uncomfortable part of a deterministic function is that the fleet changes. When a worker is removed, every customer whose subset contained it must get a replacement, and you want *that* to be a small, local change rather than a global reshuffle. This is the same problem Lesson 8 solved for data with consistent hashing and virtual nodes, and the same remedy applies: hash into a ring or use rendezvous (highest-random-weight) hashing to pick the `k` members, so removing one worker only moves the customers who had it.

**Re-shuffling after an incident.** Sometimes a customer draws a genuinely unlucky subset — they collided with a noisy neighbour, or their subset happens to contain two hosts on the same bad rack. You need a manual override, and the right shape for it is a small, versioned exception map consulted before the hash:

```python
OVERRIDES = {"cust_8842": ["w-17", "w-31", "w-44", "w-58", "w-73"]}

def subset_v2(customer_id, workers, k):
    if customer_id in OVERRIDES:
        return OVERRIDES[customer_id]
    return subset_for(customer_id, workers, k)
```

Keep it small, review it, and put an expiry date on every entry — an override list that only grows becomes a second, undocumented placement system. The alternative construction is to add a **shuffle epoch** to the hash input (`sha256(f"{customer_id}:{epoch}")`), letting you re-roll one customer, or everyone, by bumping a number.

**Combining with the balancing algorithms from Lesson 3.** Shuffle sharding chooses *which* workers a customer may use; it says nothing about which one to send a given request to. Use **power-of-two-choices (P2C) within the subset**: pick two members of the customer's `k` at random, send to the one with fewer in-flight requests. Lesson 3 measured why round-robin's tail is bad and why P2C fixes most of it; the composition is natural because a subset of 5 is exactly the kind of small pool P2C is good at. Then **failover is the piece that makes the isolation real**: on timeout or error, retry against a *different* member of the subset, never the same one, and mark the failed member unhealthy locally for a short window. Without that retry, section 3's numbers say you have made things worse. Cap retries with a budget so this does not become a retry storm — Phase 8 Lesson 11 covers the budget mechanics, and only retry operations that are safe to repeat ([Idempotency & Safe Retries](../../02-api-design/07-idempotency-safe-retries/)).

**AZ-aware balancing and zone affinity.** Cross-AZ traffic costs real money (typically charged per GB in both directions) and adds latency, so you want requests served in-zone — but not at the cost of losing failover. The production pattern is **zone-local preference with automatic spill**: prefer in-zone members of the subset, spill to other zones when in-zone capacity is unhealthy or insufficient. Envoy implements this as `zone_aware_routing`, which routes locally while the local zone has enough healthy hosts and degrades to cross-zone as that stops being true:

```yaml
common_lb_config:
  zone_aware_lb_config:
    routing_enabled: { value: 100 }
    min_cluster_size: 6        # below this, zone-aware routing switches off
  healthy_panic_threshold:
    value: 50                  # if <50% of hosts are healthy, ignore health
                               # and spray to everyone — panic mode
```

`healthy_panic_threshold` is worth understanding before you meet it: when fewer than half of hosts look healthy, Envoy assumes the *health checking* is what is broken and sends traffic everywhere rather than hammering the few "healthy" ones. It is a deliberate blast-radius trade in the opposite direction, and it is the correct one. Kubernetes has a coarser version in `spec.internalTrafficPolicy: Local` and topology-aware routing hints; make sure you have enough replicas per zone before enabling either, or you will concentrate all your traffic onto one pod.

**Choosing `k`.** This is the one real tuning decision, and it is a three-way trade: bigger `k` means more burst capacity per customer and better tail latency, fewer full collisions, and a *larger* fraction of the fleet one customer can damage. The exact combinatorics (printed by section 2) for a 100-worker fleet:

| `k` | `C(100,k)` combinations | P(full overlap) | Reach `k/N` | Use when |
|---|---|---|---|---|
| 2 | 4,950 | 2.020e-04 | 2.0% | Many small tenants, poison risk high, per-tenant burst irrelevant |
| 3 | 161,700 | 6.184e-06 | 3.0% | A sensible default for tenant counts in the thousands |
| 4 | 3,921,225 | 2.550e-07 | 4.0% | Route 53's choice for name servers |
| 5 | 75,287,520 | 1.328e-08 | 5.0% | Good balance: collisions vanish, reach still small |
| 8 | 186,087,894,300 | 5.374e-12 | 8.0% | Tenants need real burst headroom; you accept 8% reach |

Practical rules: pick the smallest `k` that gives a customer enough capacity for their p99 burst, check that `1/C(N,k)` is comfortably smaller than `1/(number of tenants)²`, and remember that **`k` must be at least 2 or there is no failover target and the whole scheme collapses to fixed sharding with extra steps.** If you have very few workers, shuffle sharding buys little — at `N = 8, k = 2` you get 28 combinations, which is real but modest. The technique wants a fleet of dozens or hundreds.

**Where cells and shuffle sharding compose.** They solve different failure modes, so use both: cells contain deploys, config pushes and shared-dependency failures; shuffle sharding inside each cell contains poison tenants. A common production shape is a few dozen cells, each internally shuffle-sharded, with the router doing nothing but a static map lookup.

## Think about it

1. Your service is multi-AZ, three zones, and your last four outages were a config push, a bad deploy, a certificate expiry and a schema migration. Compute the effective common-cause fraction `c` that would explain four fleet-wide outages against your instance-level failure record — and say what the AZ spend actually bought you.
2. Section 3 shows that shuffle sharding without failover is *worse* than fixed sharding. Your client is a third-party SDK you do not control and it does not retry against a different endpoint. What is your migration order — and is there a server-side-only change that recovers most of the benefit?
3. You have 40 workers and 5,000 tenants. Choose `k`, and justify it with both `1/C(40,k)` and the fraction of the fleet one tenant can reach. Then say what changes if 12 of those tenants are 100× larger than the other 4,988.
4. Your cell router is a static file baked into every instance. A customer must move from cell 3 to cell 7 because they outgrew it. Write the sequence of steps that moves them without dropping a request, and identify the moment during which the system has two answers to "which cell owns this customer".
5. Static stability costs 43% more hardware in section 6. Your finance team wants that back. Which of the three static-stability practices (pre-provisioned capacity, cached config, control-plane-free data plane) would you give up first, and what is the failure that decision buys you?

## Key takeaways

- **Blast radius is a design parameter, not an outcome.** The same 8 workers, the same bug and the same 800 customers produced **100.00%, 23.65% and 2.63%** blast radii under a shared fleet, 4 fixed shards, and 2-of-8 shuffle sharding. The only difference is the assignment function, which is stateless and costs nothing to run.
- **Shuffle sharding is combinatorics you can do on paper.** `C(8,2) = 28` means a twin is drawn 1 time in 28; `C(100,5) = 75,287,520` means it effectively never happens. Monte-Carlo confirmed the closed form at (8,2), (16,3) and (24,4) — **3.579e-02 vs 3.571e-02** over 300,000 draws — so it can be trusted where sampling cannot reach.
- **Partial overlap is the common case and it is survivable; full overlap is the outage and it is astronomically rare.** At N=100, k=5, **23.07% of customers share at least one worker** but the chance of sharing all five is **1.33e-08**. Quote the second number, not the first.
- **Without retry-to-another-member, shuffle sharding is a downgrade.** Measured: **5.0118% fleet-wide errors with no failover against a fixed shard's 5.0000%** — the same `k/N` volume spread over **4.6× more customers**. The client-side failover is not a refinement of the technique; it *is* the technique.
- **Correlated failure eats redundancy for breakfast.** Two 99.9% instances give **6.00 nines** if failures are independent and **4.96 nines** at a 1% common-cause fraction. A third instance buys **0.04 nines** and a hundredth buys nothing — the ceiling is `1 − c·p`. Config pushes, deploys, schemas, flag services and shared databases all ignore AZ boundaries, which is why "we're multi-AZ" is not an answer to any of them.
- **Cells convert a 100% deploy blast radius into `1/C`, and the price curve has a knee.** 1 cell → 24 cells cost **18.8 points of capacity overhead (243 → 288 instances)** for **100% → 4.17%**. 24 → 120 cells cost another **80 points — a doubled fleet** — for 4.17% → 0.83%. Keep the router dumb and static; it is the one component that can take everything down.
- **Static stability means needing nothing during a failure.** Losing 1 of 3 AZs cost the pre-provisioned fleet **nothing** and the autoscaling fleet **450 seconds at 70% and 11,250 requests**, because 60 s of metrics + 60 s of alarm + 180 s of launch all happen before the first replacement serves anything — and the control plane you are calling is in the same outage. The flat line costs 43% more hardware.
- **Know the shape of the tool.** Shuffle sharding contains failures that are *caused by and follow a customer*. It does nothing against a bad deploy, a shared dependency or a globally exhausted resource. Use cells for those, and use both together.

Next: [Multi-Region: Global Traffic, Failover & Data Gravity](../10-multi-region-and-failover/) — what changes when the failure domain is an entire region, why data gravity makes failover asymmetric, and how to route global traffic to somewhere that is still alive.
