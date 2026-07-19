# Capstone: Survive the Region Loss

> Two builds of the same service, the same traffic, the same seven failures injected in the same order. One ends the exercise at **90.10% availability having spent 38.1 error-seconds and needing zero operator restarts**. The other ends at **26.69%**, spends **282.2 error-seconds — 21.5% of an entire month's budget in 6.4 minutes** — and needs three restarts to get through the script at all. Then the ablation: re-run the whole thing with each defence switched off in turn, and find out which of the thirteen lessons actually earned its complexity.

**Type:** Build
**Languages:** Python
**Prerequisites:** [What One Machine Can Actually Do](../01-what-one-machine-can-do/) · [The Universal Scalability Law](../02-universal-scalability-law/) · [Load Balancing Algorithms](../03-load-balancing-algorithms/) · [L4 vs L7, Health Checks & Outlier Ejection](../04-l4-l7-health-checks-and-ejection/) · [Service Discovery & Subsetting](../05-service-discovery-and-subsetting/) · [Stateless Services](../06-stateless-services/) · [Read Replicas & Replication Lag](../07-read-replicas-and-replication-lag/) · [Sharding the Data Tier](../08-sharding-the-data-tier/) · [Failure Domains & Shuffle Sharding](../09-failure-domains-and-shuffle-sharding/) · [Multi-Region: Failover & Data Gravity](../10-multi-region-and-failover/) · [The Tail at Scale](../11-the-tail-at-scale/) · [Capacity Planning](../12-capacity-planning/) · [Autoscaling](../13-autoscaling/)
**Time:** ~120 minutes

## The Problem

It is the second week of the quarter and you have been given an assignment with a date on it.

Your service has **40 million users** and takes **60,000 requests per second** at peak. Last month, leadership signed an availability **SLO** — Service Level Objective, an internal target for a measured number over a stated window — of **99.95%, measured monthly**. The number was chosen in a meeting you were not in. Nobody in that meeting did the arithmetic, so do it now, because it is the only number that matters for the next six weeks:

```text
a month averages 365.25 / 12 = 30.44 days = 43,830 minutes
0.05% of 43,830 minutes = 21.9 minutes of downtime per month
                        = 1,315 error-seconds, for everything
```

**Twenty-one minutes and fifty-four seconds.** Not per incident — per month, for every cause combined. Every deploy that goes sideways, every dependency that has a bad afternoon, every DNS change, every certificate that expires on a Sunday, every fat-fingered `kubectl`, and every fire drill you run on purpose. All of it comes out of the same 21.9 minutes.

And then the second half of the assignment, which arrived as one line in a board deck: **the company wants proof the service survives losing a region.**

Not a design document. Not an architecture diagram with two clouds on it and an arrow in between. Proof — because the CTO was asked "what happens if us-east goes away" in a meeting with the audit committee, said "we're multi-region," and was then asked "when did you last test that." There was no answer. There is now a date.

Here is what makes this hard, and it is not the technology. You have thirteen lessons' worth of technique available: you know how to measure one machine's ceiling, why the fleet scales sub-linearly, why round-robin lies, how outlier ejection works, how to make instances interchangeable, how replicas lag, how to shard, how to contain a blast radius, how to fail over between regions, why the tail is the max and not the mean, how to size headroom, and how to build a control loop that does not oscillate. Every one of those is a thing you can defend in isolation.

What you cannot defend yet is **the composition.** You do not know which of them matter, in what order, or what happens when all of them are switched on at once and something real breaks. You do not know whether your defences interact — whether one of them is load-bearing for another, or whether two of them cancel out. And critically: you do not know which ones are worth their operational cost, because nobody has ever measured a defence by turning it off.

So the exercise is this. Build the system twice — a **naive** build that is entirely reasonable and would pass code review at most companies, and a **hardened** build with the phase's toolkit switched on. Break both, identically, in six escalating ways, ending with the loss of an entire region. Then measure.

You will finish this lesson with three deliverables and they are the three things the board actually wants:

1. **A measured incident table** — seven rows, both configurations, availability and tail latency and goodput for each.
2. **A capacity number you can defend** — not "we have headroom" but the arithmetic that produced the fleet size, and the price tag attached to it.
3. **A runbook** — the ordered steps for an evacuation, with the point of no return marked, that someone who is not you can execute at 03:00.

## The Concept

This section is deliberately short. There is almost no new material here; the weight of this lesson is in the Build It. What follows is the assembly instructions — how the thirteen pieces fit into one structure.

### The reliability stack, bottom to top

Every technique in this phase sits at a level, and each level assumes the one beneath it works. Read this from the bottom.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 512" width="100%" style="max-width:840px" role="img" aria-label="The reliability stack read bottom to top, each layer labelled with the lesson that supplied it: lesson 1 one machine's ceiling, lesson 2 the scaling law, lessons 3 to 5 routing, lesson 6 stateless instances, lessons 7 and 8 the data tier, lesson 9 blast radius containment, lesson 10 geographic survival, lesson 11 tail tolerance, lesson 12 capacity arithmetic and lesson 13 the control loop, with lesson 14 the exercise that proves it. A panel on the right states four ordering dependencies measured in the ablation: shedding must exist before a retry budget helps, statelessness before failover is possible, headroom before an autoscaler has anything to reclaim, and deadlines before hedging is safe.">
  <defs>
    <marker id="p11-14-b1" markerWidth="9" markerHeight="9" refX="5.5" refY="3" orient="auto"><path d="M0,0 L6.5,3 L0,6 Z" fill="currentColor"/></marker>
  </defs>
  <text x="440" y="24" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">The reliability stack — and why the order is not decoration</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <text x="24" y="50" font-size="9" font-weight="700" fill="currentColor" opacity="0.65">READ IT BOTTOM TO TOP. EACH LAYER ASSUMES THE ONE BELOW IT.</text>

    <path d="M14 412 L14 62" fill="none" stroke="currentColor" stroke-width="1.4" opacity="0.5" marker-end="url(#p11-14-b1)"/>

    <g stroke-width="1.6" fill="none">
      <rect x="24" y="60"  width="544" height="28" rx="6" fill="#3553ff" fill-opacity="0.14" stroke="#3553ff"/> <rect x="24" y="92"  width="544" height="28" rx="6" fill="#7c5cff" fill-opacity="0.12" stroke="#7c5cff"/> <rect x="24" y="124" width="544" height="28" rx="6" fill="#7c5cff" fill-opacity="0.12" stroke="#7c5cff"/>
      <rect x="24" y="156" width="544" height="28" rx="6" fill="#e0930f" fill-opacity="0.13" stroke="#e0930f"/> <rect x="24" y="188" width="544" height="28" rx="6" fill="#e0930f" fill-opacity="0.13" stroke="#e0930f"/> <rect x="24" y="220" width="544" height="28" rx="6" fill="#e0930f" fill-opacity="0.13" stroke="#e0930f"/>
      <rect x="24" y="252" width="544" height="28" rx="6" fill="#0fa07f" fill-opacity="0.13" stroke="#0fa07f"/> <rect x="24" y="284" width="544" height="28" rx="6" fill="#0fa07f" fill-opacity="0.13" stroke="#0fa07f"/> <rect x="24" y="316" width="544" height="28" rx="6" fill="#0fa07f" fill-opacity="0.13" stroke="#0fa07f"/>
      <rect x="24" y="348" width="544" height="28" rx="6" fill="#7f7f7f" fill-opacity="0.12" stroke="#7f7f7f"/> <rect x="24" y="380" width="544" height="28" rx="6" fill="#7f7f7f" fill-opacity="0.12" stroke="#7f7f7f"/>
    </g>

    <g fill="currentColor" font-size="9.5" font-weight="700">
      <text x="36" y="79">L14</text><text x="36" y="111">L13</text><text x="36" y="143">L12</text> <text x="36" y="175">L11</text><text x="36" y="207">L10</text><text x="36" y="239">L09</text> <text x="36" y="271">L07/08</text><text x="36" y="303">L06</text><text x="36" y="335">L03/04/05</text>
      <text x="36" y="367">L02</text><text x="36" y="399">L01</text>
    </g>

    <g fill="currentColor" font-size="10.5">
      <text x="112" y="79" font-weight="700">the exercise that proves all of it</text> <text x="112" y="111">the control loop — damped autoscaling</text> <text x="112" y="143">the capacity arithmetic — headroom, pre-bought</text>
      <text x="112" y="175">tail tolerance — fan-out, hedges, deadlines</text> <text x="112" y="207">geographic survival — cross-region replicas</text> <text x="112" y="239">blast-radius containment — shuffle sharding</text>
      <text x="112" y="271">the data tier at scale — replicas and shards</text> <text x="112" y="303">interchangeable instances — state lives elsewhere</text> <text x="112" y="335">routing — least-request, health checks</text>
      <text x="112" y="367">the scaling law — 2x machines is not 2x throughput</text> <text x="112" y="399">one machine's ceiling — measured, not assumed</text>
    </g>

    <g fill="currentColor" font-size="9" text-anchor="end" opacity="0.85">
      <text x="560" y="79" font-weight="700" fill="#3553ff">this lesson</text> <text x="560" y="111">+6.5 err-s</text> <text x="560" y="143">+36.5 err-s</text>
      <text x="560" y="175">+1.5 err-s</text> <text x="560" y="207" font-weight="700" fill="#d64545">+87.6 err-s</text> <text x="560" y="239">blast 29 -&gt; 60</text>
      <text x="560" y="271">RPO 20 writes</text> <text x="560" y="303">failover needs it</text> <text x="560" y="335">+0.2 / +2.4 err-s</text>
      <text x="560" y="367">sub-linear</text> <text x="560" y="399">25 req/s</text>
    </g>

    <rect x="586" y="60" width="270" height="362" rx="10" fill="#d64545" fill-opacity="0.08" stroke="#d64545" stroke-width="1.7"/> <text x="598" y="80" font-size="11" font-weight="700" fill="#d64545">THE ORDER IS A DEPENDENCY, NOT A LIST</text> <text x="598" y="96" font-size="9" fill="currentColor" opacity="0.85">measured as pairs, against the sum of parts</text>

    <g stroke-width="1.4" fill="none">
      <rect x="598" y="108" width="244" height="66" rx="7" fill="#7f7f7f" fill-opacity="0.09" stroke="currentColor" stroke-opacity="0.4"/> <rect x="598" y="182" width="244" height="66" rx="7" fill="#7f7f7f" fill-opacity="0.09" stroke="currentColor" stroke-opacity="0.4"/> <rect x="598" y="256" width="244" height="66" rx="7" fill="#7f7f7f" fill-opacity="0.09" stroke="currentColor" stroke-opacity="0.4"/>
      <rect x="598" y="330" width="244" height="80" rx="7" fill="#7f7f7f" fill-opacity="0.09" stroke="currentColor" stroke-opacity="0.4"/>
    </g>
    <g fill="currentColor" font-size="9.5">
      <text x="608" y="126" font-weight="700">shedding BEFORE a retry budget</text> <text x="608" y="141" opacity="0.88">alone: +46.5 and +11.6. Together:</text>
      <text x="608" y="155" opacity="0.88">+148.5 — <tspan font-weight="700" fill="#d64545">2.6x the sum</tspan>. You shed a</text>
      <text x="608" y="169" opacity="0.88">request and are handed it right back.</text>

      <text x="608" y="200" font-weight="700">headroom BEFORE an autoscaler</text> <text x="608" y="215" opacity="0.88">alone: +36.5 and +6.5. Together: +86.0</text>
      <text x="608" y="229" opacity="0.88">— <tspan font-weight="700" fill="#d64545">2.0x the sum</tspan>. A scaler with nothing</text>
      <text x="608" y="243" opacity="0.88">to reclaim is still booting at t+90 s.</text>

      <text x="608" y="274" font-weight="700">deadlines BEFORE shedding decides</text> <text x="608" y="289" opacity="0.88">alone: 0.0 and +46.5. Together: +66.9</text>
      <text x="608" y="303" opacity="0.88">— <tspan font-weight="700" fill="#d64545">1.4x the sum</tspan>. Without a deadline</text>
      <text x="608" y="317" opacity="0.88">the shedder cannot tell live from dead.</text>

      <text x="608" y="348" font-weight="700">statelessness BEFORE failover</text> <text x="608" y="363" opacity="0.88">not ablatable: it is a precondition.</text> <text x="608" y="377" opacity="0.88">If a request only runs on the machine</text>
      <text x="608" y="391" opacity="0.88">holding its session, there is nowhere</text> <text x="608" y="404" opacity="0.88">to send it.</text>
    </g>

    <text x="24" y="440" font-size="10.5" font-weight="700" fill="currentColor">Availability multiplies down a hard-dependency chain, it does not average:</text>
    <text x="24" y="458" font-size="10.5" fill="currentColor">five dependencies at 99.9% each in series = 0.999^5 = <tspan font-weight="700">99.50%</tspan> = <tspan font-weight="700" fill="#d64545">3 h 39 min a month</tspan>, against a 21.9-minute budget.</text>
    <text x="24" y="476" font-size="10.5" fill="currentColor">You cannot fix that by making each dependency better. You fix it by making fewer of them <tspan font-style="italic">hard</tspan>.</text>
    <text x="440" y="500" font-size="11" text-anchor="middle" fill="currentColor" opacity="0.9">Every layer here is one lesson of this phase. The capstone is the only place they are all switched on at once.</text>
  </g>
</svg>
```

The bottom two layers are not defences at all — they are **measurements that make every layer above them possible.** Lesson 1's ceiling (25 requests per second per instance, in the simulator here) is the only number in the entire stack obtained by measuring a real thing rather than deriving it. Lesson 2's scaling law is why you cannot simply multiply that number by the fleet size and go home. Everything above is a choice you make; those two are facts you discover.

### The order of defences is a dependency, not a list

This is the part you cannot get from any single lesson, and the ablation at the end of the Build It measures it directly. Four of these dependencies are real and one is a null result:

**Shedding must exist before a retry budget is worth anything, and vice versa.** Measured separately, removing load shedding costs 46.5 error-seconds and removing the retry budget costs 11.6 — together they should cost 58.1. Removing both actually costs **148.5, which is 2.6× the sum.** The mechanism is not subtle once you see it: a shedder without a retry budget rejects a request in zero milliseconds and is handed the same request back 200 ms later, forever. It is not shedding load, it is *recirculating* it.

**Headroom must be pre-provisioned before an autoscaler can help.** Separately: 36.5 and 6.5 error-seconds, 43.0 together. Measured together: **86.0, or 2.0× the sum.** An autoscaler is a machine for converting headroom into money when you do not need it. It is not a machine for producing capacity during an incident, because instances take 90 seconds to boot and the deadline is 400 milliseconds.

**Deadlines must propagate before shedding can decide anything.** Separately 0.0 and 46.5; together **66.9, or 1.4× the sum.** Deadline propagation on its own measures as worth exactly nothing here, which is a genuinely useful result — the shedder was already bounding the queue, so nothing ever aged out. But take both away and the shedder loses the only signal that distinguishes a request someone is waiting for from one that was abandoned.

**Statelessness must exist before failover is possible at all.** This one is not in the ablation table because it cannot be ablated: it is not a defence, it is a precondition. If a request only works on the machine holding its session, there is no other machine to send it to, and every technique above it in the stack is decoration.

And the honest fifth: **least-request balancing and outlier ejection do not interact** against this failure script. Separately +0.2 and +2.4 error-seconds; together −0.0. Predicted an interaction, did not find one, reporting it anyway — because a table that contains only the interactions that worked is not a measurement, it is an argument.

### What availability actually multiplies to

Here is the arithmetic that reframes the whole SLO conversation, and almost nobody does it before signing the number.

Availability composes down a chain of **hard dependencies** by multiplication, not by averaging. If your request path touches five services and each of them is independently available 99.9% of the time, and your request fails when any one of them fails:

```text
0.999^5 = 0.99500999...  =  99.50%

unavailability          = 1 - 0.99501 = 0.499%
0.499% of 43,830 min    = 218.7 minutes per month
                        = 3 hours 39 minutes
```

**Three hours and thirty-nine minutes, against a budget of twenty-one point nine.** Every single dependency is beating its own SLO. The composition is ten times outside yours. This is why "all our services are at three nines" is not an answer to "what is our availability," and why the first useful question in a reliability review is not *how good is each dependency* but *how many of them are hard*.

There are exactly two ways out and only one of them scales:

- **Reduce the number of hard dependencies.** Fewer synchronous calls on the critical path. This is real work and it is usually the right work.
- **Make the dependency soft** — return a degraded response instead of a failure when it is unavailable. A soft dependency contributes nothing to the multiplication because its failure is not your failure. Phase 8's [Backpressure, Queueing & Load Shedding](../../08-concurrency-and-performance/11-backpressure-and-load-shedding/) builds the degradation tiers and the fallback machinery; this lesson only uses them. Note what the arithmetic says about *where* to spend: converting one of those five hard dependencies to soft moves you from 99.50% to 99.60%, which is 44 minutes a month, more than the entire budget. Converting one of them from 99.9% to 99.99% moves you to 99.59%. **The structural change beats the reliability improvement**, and it is usually cheaper.

The same multiplication is what makes fan-out dangerous, which is Lesson 11's subject and shows up in the simulator directly: a read that touches 5 of 8 shards succeeds only if all five succeed. When four shards vanish with their region, the probability is not "reduced" — it is `C(4,5)/C(8,5) = 0/56 = 0`. You cannot choose 5 things from 4.

### The system, and the failure sequence

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 610" width="100%" style="max-width:840px" role="img" aria-label="The full system under test: clients reach a health-checked global load balancer, which splits traffic across two regions of three availability zones each. Each region holds a fleet of ten instances per zone behind a least-request layer-7 balancer with outlier ejection, tenants are pinned to three-instance shuffle shards, and each region owns four data shards whose primaries replicate asynchronously to a standby replica in the other region. Every component is annotated with the lesson that introduced its defence, from lesson 1's single-machine ceiling to lesson 13's autoscaler.">
  <defs>
    <marker id="p11-14-a1" markerWidth="9" markerHeight="9" refX="5.5" refY="3" orient="auto"><path d="M0,0 L6.5,3 L0,6 Z" fill="currentColor"/></marker>
    <marker id="p11-14-a2" markerWidth="9" markerHeight="9" refX="5.5" refY="3" orient="auto"><path d="M0,0 L6.5,3 L0,6 Z" fill="#e0930f"/></marker>
  </defs>
  <text x="440" y="24" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">The system under test — and the lesson that supplied every defence on it</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">

    <rect x="286" y="42" width="308" height="30" rx="8" fill="#3553ff" fill-opacity="0.12" stroke="#3553ff" stroke-width="1.8"/> <text x="440" y="62" font-size="11" text-anchor="middle" fill="currentColor" font-weight="700">40M users · 60,000 req/s peak · 400 ms deadline</text>

    <rect x="230" y="88" width="420" height="42" rx="9" fill="#7c5cff" fill-opacity="0.13" stroke="#7c5cff" stroke-width="1.8"/> <text x="440" y="106" font-size="11.5" text-anchor="middle" fill="currentColor" font-weight="700">GSLB — health-checked global DNS</text> <text x="440" y="121" font-size="9" text-anchor="middle" fill="currentColor" opacity="0.85">detect 15 s · TTL 60 s · 1.8% of resolvers never move (RFC 8767)</text>
    <text x="664" y="112" font-size="9.5" fill="#7c5cff" font-weight="700">L10</text>

    <path d="M440 72 L440 84" fill="none" stroke="currentColor" stroke-width="1.6" marker-end="url(#p11-14-a1)"/> <path d="M320 130 L228 168" fill="none" stroke="currentColor" stroke-width="1.6" marker-end="url(#p11-14-a1)"/> <path d="M560 130 L652 168" fill="none" stroke="currentColor" stroke-width="1.6" marker-end="url(#p11-14-a1)"/>
    <text x="268" y="150" font-size="9" fill="currentColor" opacity="0.8">50%</text> <text x="586" y="150" font-size="9" fill="currentColor" opacity="0.8">50%</text>

    <g stroke-width="2" fill="none">
      <rect x="24" y="176" width="404" height="204" rx="12" fill="#0fa07f" fill-opacity="0.07" stroke="#0fa07f"/> <rect x="452" y="176" width="404" height="204" rx="12" fill="#0fa07f" fill-opacity="0.07" stroke="#0fa07f"/>
    </g>
    <text x="40" y="196" font-size="11.5" font-weight="700" fill="#0fa07f">REGION us-east</text> <text x="468" y="196" font-size="11.5" font-weight="700" fill="#0fa07f">REGION eu-west</text> <text x="412" y="196" font-size="9" text-anchor="end" fill="currentColor" opacity="0.7">30 instances = 750 req/s</text>
    <text x="840" y="196" font-size="9" text-anchor="end" fill="currentColor" opacity="0.7">30 instances = 750 req/s</text>

    <g stroke-width="1.6" fill="none">
      <rect x="40" y="206" width="372" height="30" rx="7" fill="#7c5cff" fill-opacity="0.12" stroke="#7c5cff"/> <rect x="468" y="206" width="372" height="30" rx="7" fill="#7c5cff" fill-opacity="0.12" stroke="#7c5cff"/>
    </g>
    <text x="52" y="225" font-size="10" fill="currentColor">L7 LB · least-request · outlier ejection</text> <text x="400" y="225" font-size="9" text-anchor="end" fill="#7c5cff" font-weight="700">L03 L04 L05</text> <text x="480" y="225" font-size="10" fill="currentColor">L7 LB · least-request · outlier ejection</text>
    <text x="828" y="225" font-size="9" text-anchor="end" fill="#7c5cff" font-weight="700">L03 L04 L05</text>

    <g stroke-width="1.6" fill="none">
      <rect x="40"  y="248" width="118" height="58" rx="7" fill="#0fa07f" fill-opacity="0.13" stroke="#0fa07f"/> <rect x="167" y="248" width="118" height="58" rx="7" fill="#0fa07f" fill-opacity="0.13" stroke="#0fa07f"/> <rect x="294" y="248" width="118" height="58" rx="7" fill="#d64545" fill-opacity="0.13" stroke="#d64545" stroke-dasharray="6 4"/>
      <rect x="468" y="248" width="118" height="58" rx="7" fill="#0fa07f" fill-opacity="0.13" stroke="#0fa07f"/> <rect x="595" y="248" width="118" height="58" rx="7" fill="#0fa07f" fill-opacity="0.13" stroke="#0fa07f"/> <rect x="722" y="248" width="118" height="58" rx="7" fill="#0fa07f" fill-opacity="0.13" stroke="#0fa07f"/>
    </g>
    <g fill="currentColor" font-size="9.5" text-anchor="middle">
      <text x="99"  y="266" font-weight="700">AZ 1a</text><text x="226" y="266" font-weight="700">AZ 1b</text> <text x="353" y="266" font-weight="700" fill="#d64545">AZ 1c</text> <text x="527" y="266" font-weight="700">AZ 2a</text><text x="654" y="266" font-weight="700">AZ 2b</text><text x="781" y="266" font-weight="700">AZ 2c</text>
    </g>
    <g fill="currentColor" font-size="9" text-anchor="middle" opacity="0.85">
      <text x="99"  y="282">10 stateless</text><text x="226" y="282">10 stateless</text> <text x="353" y="282" fill="#d64545">stage 6:</text> <text x="527" y="282">10 stateless</text><text x="654" y="282">10 stateless</text><text x="781" y="282">10 stateless</text>
      <text x="99"  y="296">instances</text><text x="226" y="296">instances</text> <text x="353" y="296" fill="#d64545" font-weight="700">LOST</text> <text x="527" y="296">instances</text><text x="654" y="296">instances</text><text x="781" y="296">instances</text>
    </g>
    <text x="40" y="326" font-size="9" fill="currentColor" opacity="0.85">sessions in the store, not the process</text> <text x="412" y="326" font-size="9" text-anchor="end" fill="#0fa07f" font-weight="700">L06</text> <text x="40" y="342" font-size="9" fill="currentColor" opacity="0.85">tenants pinned to 3-instance shuffle shards</text>
    <text x="412" y="342" font-size="9" text-anchor="end" fill="#0fa07f" font-weight="700">L09</text> <text x="40" y="358" font-size="9" fill="currentColor" opacity="0.85">deadline + shed + retry budget + hedge</text> <text x="412" y="358" font-size="9" text-anchor="end" fill="#0fa07f" font-weight="700">L11 · Ph8 L11</text>
    <text x="40" y="374" font-size="9" fill="currentColor" opacity="0.85">autoscaler: damped, 90 s boot, max 54</text> <text x="412" y="374" font-size="9" text-anchor="end" fill="#0fa07f" font-weight="700">L12 L13</text> <text x="468" y="326" font-size="9" fill="currentColor" opacity="0.85">one machine's ceiling: 25 req/s each</text>
    <text x="840" y="326" font-size="9" text-anchor="end" fill="#0fa07f" font-weight="700">L01</text> <text x="468" y="342" font-size="9" fill="currentColor" opacity="0.85">the fleet is sub-linear, not linear</text> <text x="840" y="342" font-size="9" text-anchor="end" fill="#0fa07f" font-weight="700">L02</text>
    <text x="468" y="358" font-size="9" fill="currentColor" opacity="0.85">sized peak/(cap x 0.80) x R/(R-1) = 2.0x</text> <text x="840" y="358" font-size="9" text-anchor="end" fill="#0fa07f" font-weight="700">L12</text> <text x="468" y="374" font-size="9" fill="currentColor" opacity="0.85">either region alone runs 100% at 80%</text>
    <text x="840" y="374" font-size="9" text-anchor="end" fill="#0fa07f" font-weight="700">L10</text>

    <path d="M226 380 L226 400" fill="none" stroke="currentColor" stroke-width="1.5" marker-end="url(#p11-14-a1)"/> <path d="M654 380 L654 400" fill="none" stroke="currentColor" stroke-width="1.5" marker-end="url(#p11-14-a1)"/> <text x="240" y="396" font-size="9" fill="currentColor" opacity="0.8">each read fans out to 5 of 8 shards</text>
    <text x="668" y="396" font-size="9" fill="#e0930f" font-weight="700">L11 — the tail is the max of 5</text>

    <g stroke-width="1.7" fill="none">
      <rect x="24" y="406" width="404" height="76" rx="10" fill="#e0930f" fill-opacity="0.10" stroke="#e0930f"/> <rect x="452" y="406" width="404" height="76" rx="10" fill="#e0930f" fill-opacity="0.10" stroke="#e0930f"/>
    </g>
    <text x="40" y="424" font-size="10.5" font-weight="700" fill="currentColor">DATA TIER — shards 0-3 primary</text> <text x="468" y="424" font-size="10.5" font-weight="700" fill="currentColor">DATA TIER — shards 4-7 primary</text> <text x="412" y="424" font-size="9" text-anchor="end" fill="#e0930f" font-weight="700">L07 L08</text>
    <text x="840" y="424" font-size="9" text-anchor="end" fill="#e0930f" font-weight="700">L07 L08</text>
    <g stroke-width="1.5" fill="none">
      <rect x="40"  y="434" width="86" height="24" rx="5" fill="#e0930f" fill-opacity="0.16" stroke="#e0930f"/> <rect x="132" y="434" width="86" height="24" rx="5" fill="#e0930f" fill-opacity="0.16" stroke="#e0930f"/> <rect x="224" y="434" width="86" height="24" rx="5" fill="#e0930f" fill-opacity="0.16" stroke="#e0930f"/>
      <rect x="316" y="434" width="96" height="24" rx="5" fill="#7f7f7f" fill-opacity="0.12" stroke="#7f7f7f"/> <rect x="468" y="434" width="86" height="24" rx="5" fill="#e0930f" fill-opacity="0.16" stroke="#e0930f"/> <rect x="560" y="434" width="86" height="24" rx="5" fill="#e0930f" fill-opacity="0.16" stroke="#e0930f"/>
      <rect x="652" y="434" width="86" height="24" rx="5" fill="#e0930f" fill-opacity="0.16" stroke="#e0930f"/> <rect x="744" y="434" width="96" height="24" rx="5" fill="#7f7f7f" fill-opacity="0.12" stroke="#7f7f7f"/>
    </g>
    <g fill="currentColor" font-size="9" text-anchor="middle">
      <text x="83"  y="450">s0 P</text><text x="175" y="450">s1 P</text><text x="267" y="450">s2 P</text> <text x="364" y="450" opacity="0.8">s4-7 replica</text> <text x="511" y="450">s4 P</text><text x="603" y="450">s5 P</text><text x="695" y="450">s6 P</text>
      <text x="792" y="450" opacity="0.8">s0-3 replica</text>
    </g>
    <text x="40" y="474" font-size="9" fill="currentColor" opacity="0.85">async replication · lag 0.45 s · promotion 45 s · RPO 20 writes</text> <text x="468" y="474" font-size="9" fill="currentColor" opacity="0.85">the replica in the OTHER region is the whole plan</text>

    <path d="M412 446 C 436 446, 436 446, 460 446" fill="none" stroke="#e0930f" stroke-width="2" marker-end="url(#p11-14-a2)"/> <path d="M460 462 C 436 462, 436 462, 412 462" fill="none" stroke="#e0930f" stroke-width="2" marker-end="url(#p11-14-a2)"/>

    <rect x="24" y="496" width="832" height="60" rx="9" fill="#d64545" fill-opacity="0.09" stroke="#d64545" stroke-width="1.7"/> <text x="40" y="514" font-size="10.5" font-weight="700" fill="#d64545">THE NAIVE BUILD IS THE SAME PICTURE WITH FOUR THINGS DELETED</text> <text x="40" y="531" font-size="9.5" fill="currentColor" opacity="0.9">half the instances (30, no headroom) · round-robin behind a layer-4 probe · no shuffle shards ·</text>
    <text x="40" y="546" font-size="9.5" fill="currentColor" opacity="0.9">and both replicas of every shard sitting inside their own region.</text>

    <text x="440" y="582" font-size="11" text-anchor="middle" fill="currentColor" opacity="0.9">The last one is the expensive mistake: it makes the compute plan irrelevant, because the data is not there to serve.</text> <text x="440" y="600" font-size="11" text-anchor="middle" fill="currentColor" opacity="0.9">A read that fans out to 5 of 8 shards cannot be answered from 4 — C(4,5)/C(8,5) = 0 — so the surviving region serves nothing.</text>
  </g>
</svg>
```

Both builds run the same simulated service: two regions, three availability zones each (AZ = Availability Zone, a separately-powered failure domain inside a region), a fleet per zone, a routing layer, eight data shards with replicas, and a read path that fans out across five of them. The naive build is the same picture with four things deleted — half the instances, round-robin behind a layer-4 health check, no shuffle sharding, and both replicas of every shard sitting inside their own region.

Seven stages, escalating, each testing something specific:

| # | Stage | What it tests | Lesson |
|---|---|---|---|
| 1 | Baseline at peak | steady state: p50, p99, goodput, utilization, cost | L01 L02 L12 |
| 2 | One instance stops answering | health checking and ejection — of a process that is hung, not dead | L04 |
| 3 | Grey failure: 6.7% of the fleet at 8× service time | least-request vs round-robin; passive outlier detection | L03 L04 |
| 4 | A poison tenant, 200× cost per request | shuffle sharding and blast-radius containment | L09 |
| 5 | Dependency at 55% capacity, then restored | deadlines, retry budgets, shedding, metastability | L11 L13 · Ph8 L11 |
| 6 | An entire AZ is lost | the N/(N−1) capacity headroom arithmetic | L12 |
| 7 | The region is lost | evacuation: DNS long tail, replica promotion, RPO | L10 L07 |

Stage 2 deserves a note now, because the fault is chosen deliberately. The instance does not crash. **The process stays up, accepts the TCP connection, and never sends a response.** This is the common failure — a deadlocked thread pool, an exhausted connection pool, a GC death spiral — and it is precisely the one a layer-4 health check cannot detect, because a layer-4 check asks "is the port open" and the port is open.

## Build It

[`code/survive_region_loss.py`](code/survive_region_loss.py) is one file: a discrete-time simulator of the whole system, the seven-stage failure script, and the ablation harness. Standard library only, seeded with `random.Random(7)`, and it runs the full script twenty-two times — two configurations plus twenty ablation and interaction runs — in about ten seconds.

```bash
docker compose exec -T app python \
  phases/11-scalability-and-reliability/14-capstone-survive-the-region-loss/code/survive_region_loss.py
```

Three things in the code are worth reading before the output.

**The scale, stated up front.** The simulator runs at 1:100 — 600 req/s and 60 instances rather than 60,000 and 6,000. That is a legitimate simplification only because every quantity this lesson reports is a **ratio**: utilization, availability, blast radius as a fraction of customers, error budget as a fraction of a month. Ratios are scale-invariant; absolute throughput is not, and no absolute throughput number is claimed anywhere.

**The admission controller sizes itself from the deadline, not from a constant.** This is the single most important piece of code in the file, and it is four lines. A queue bound expressed as a number of items is wrong the moment your service time changes — which is exactly when you need it. Invert the queueing formula instead:

```python
# Admission control sized from the DEADLINE, not from a constant.
# W = S*rho/(1-rho) <= wb  =>  rho <= wb / (S + wb)
rho_max = wb / (svc + wb)
room = max(0.0, rho_max * cap_rate * TICK - q[i])
if arr_w[i] > room:
    shed_w = arr_w[i] - room
```

`wb` is the wait budget — the deadline, minus the measured p99 of the current service-time distribution, minus a small safety margin. `svc` is the current service time, `1/cap_rate`. When the dependency degrades and service time doubles, `rho_max` drops automatically, and the shedder starts refusing load at a *lower* utilization because the same utilization now buys more waiting. Nobody tunes it. That is the whole point: **a threshold that has to be re-tuned when conditions change is a threshold that will be wrong during the incident.**

**Retries are counted honestly, and this matters more than it sounds.** A retry lands at least one tick — 500 ms — after the attempt it replaces, which is already past the 400 ms deadline. So a retry that eventually succeeds is *not* a user-visible success:

```python
# A retry lands at least one tick (500 ms) after the attempt it replaces,
# which is past the 400 ms deadline, so a retry that succeeds is never a
# user-visible success. Availability is therefore the FIRST-ATTEMPT
# success rate applied to real user demand -- retries only ever add load.
attempts = tick_req or 1.0
avg_frac = tick_ok / attempts
user_ok = offered_users * (1.0 - blackhole) * avg_frac
```

Get this wrong and the naive build looks *better* than it is, because its retry storm generates a large number of eventually-successful attempts. Availability is measured per **user request**, never per attempt. This is the same trap as Phase 8's coordinated omission, wearing different clothes: an instrument that counts the system's activity rather than the user's experience will flatter the system exactly when the user is suffering most.

### Stage 1 — baseline, and the price of a quiet Tuesday

```console
== 1 . STAGE 1 - BASELINE AT PEAK ==
                                NAIVE  p99 ms  good/s  | HARDENED  p99 ms  good/s
  steady state, 600 req/s     100.00%     238     600  |   99.24%     181     595
    fleet utilization      naive 80%        hardened 40%
    p50 latency            naive 177 ms      hardened 54 ms
```

Both builds meet the SLO. Nothing is broken. And the naive build is already **3.3× slower at the median and 31% worse at the tail** — 177 ms against 54 ms, 238 ms against 181 ms — for no reason other than that it is running at 80% utilization instead of 40%.

That is `W = S/(1−ρ)` charging rent. At ρ = 0.80 the queueing wait is 5× the service time; at ρ = 0.40 it is 1.67×. This is worth stating plainly because it is the argument you will actually have to make when someone asks why the fleet is twice as big as the load requires: **headroom is not only insurance against the bad day. You are paid in latency every single day, on every request, including all the days nothing happens.**

### Stage 2 — the process that stops answering

```console
== 2 . STAGE 2 - ONE INSTANCE STOPS ANSWERING ==
  1 of 30 / 1 of 60 hung       96.66%     286     580  |   98.75%     178     592
    ejected after   hardened 6.0 s  (L7 probe, 3 failures x 2 s)
                    naive    never within the stage  (L4 TCP probe, 3 x 30 s = 90 s)
```

One instance in each fleet stops responding. The hardened build's layer-7 probe — an actual HTTP request with an actual response check, every 2 seconds, three failures to eject — removes it after **6.0 seconds**. The naive build's layer-4 probe checks that the TCP port accepts a connection, every 30 seconds, and the port accepts connections perfectly, so it never ejects it at all. Naive loses 3.34% of its traffic for the whole stage; every one of those requests burns the full 400 ms deadline before failing, because a socket that never answers is indistinguishable from a slow one until the clock runs out.

Note the asymmetry in the header and do not let it slide by: one instance is 1/30 of the naive fleet and 1/60 of the hardened one. That is not the experiment being unfair — **it is a finding.** A smaller fleet has a larger per-instance blast radius, which is Lesson 9's argument arriving from an unexpected direction. Halving your instance count doubles what each instance's death costs you.

### Stage 3 — grey failure, and round-robin's signature

```console
== 3 . STAGE 3 - GREY FAILURE: SLOW, NOT DEAD ==
    6.7% of EACH fleet (2 naive, 4 hardened -- a bigger fleet must
    not get an easier fault) degrades to 8x its normal service time.
  8x slow: RR vs P2C           93.29%     348     560  |   96.59%     284     580
    goodput gap     +20 req/s   (1.04x)
    naive lost 6.71% of its traffic. The sick fraction of
    its fleet is 6.67%. Those two numbers are the same number, and
    that is round-robin's signature: its failure rate equals the
    fraction of the fleet that is broken, by construction.
    ejected after   hardened 12.0 s  (passive outlier detection on latency)
                    naive    never     -- a TCP check cannot see a slow process
```

Here the fault is injected as a *fraction* of each fleet so the comparison is fair. The result is the cleanest single line in the run: **naive lost 6.71% of its traffic and 6.67% of its fleet was sick.** Those are the same number, and they are the same number for a structural reason.

Round-robin does not measure anything. It hands out requests in order, so it sends exactly `1/N` of your traffic to each instance regardless of whether that instance is healthy, slow, or a black hole. **Its failure rate under grey failure is not a function of how bad the sick instance is — it is a function of how many there are.** An instance that is 8× slow and one that is infinitely slow cost you the same fraction, because round-robin will keep feeding both at the same rate forever.

Least-request cannot fail this way, and not because it is cleverer: it reads a number it already has. The sick instance's outstanding-request count climbs because responses are not coming back, and power-of-two-choices simply stops picking it. The signal is free. Then passive outlier detection ejects it at **12.0 seconds** on the latency distribution, which the layer-4 check will never do, because the process is answering — just slowly, which is not a state a port check has a word for.

The goodput gap is honest and modest: 580 against 560 req/s, 1.04×. The availability gap is the real one, and the mechanism is what you should take away rather than the ratio.

### Stage 4 — one customer, the whole fleet

```console
== 4 . STAGE 4 - A POISON TENANT ==
    customer #17 of 60 hits a path costing 200x a normal request
  200x cost, 1 of 60 tenants    0.63%     365       4  |   95.46%     216     573
    BLAST RADIUS -- how many of the 60 customers felt it:
                  <99% (touched)  <95% (degraded)  <50% (down)
      naive              60/60            60/60        60/60
      hardened           47/60            29/60         1/60
      worst-hit customer:  naive 0.0%    hardened 3.5%
      the customer who CAUSED it: naive 0.0%, hardened 3.5%
```

One customer of sixty triggers a code path costing 200× a normal request — an unindexed scan on the one account with four hundred thousand rows in it. No deploy, no bug, no attack. Same API, same code, a different `WHERE` clause hitting different data.

The naive fleet, where every customer shares every instance, goes to **0.63% availability. All sixty customers are effectively down.** One customer's bad query became every customer's bad query, and the mechanism is nothing more exotic than a shared queue.

The hardened fleet pins each tenant to a **shuffle shard** of 3 instances drawn from the 30 in each region. The poison lands on the poisoned tenant's own three instances, which saturate and shed. Read the three bands: 47 customers were *touched* (measurably below 99%), 29 were *degraded* (below 95%), and exactly **one was down** — and it is the customer who caused it, at 3.5%. The combinatorics are the whole technique: sharing 2 of 3 instances with any particular tenant has probability 2.0%, and sharing all 3 is 1 in 4,060.

Notice what shuffle sharding does *not* do, because the ablation makes it explicit later: it does not reduce the total damage. It relocates it onto the party responsible.

### Stage 5 — the trigger leaves and the outage stays

```console
== 5 . STAGE 5 - A DEPENDENCY DEGRADES, THEN THE RETRIES ARRIVE ==
    the data tier loses 55% of its capacity for 30 s and is then
    fully restored. Watch what happens AFTER it is restored.
  dep -55%, retry storm         0.00%     n/a       0  |   85.12%     371     511
    peak offered load     naive 4800 req/s    hardened 660 req/s   (real demand 600)
    load shed on purpose  naive 0          hardened 6321 requests
    availability WHILE the dependency was degraded:
      naive     0.0%         hardened 66.1%
    time to recover once the trigger was removed:
      hardened  0.0 s  (inside one 0.5 s tick: it never left the healthy state)
      naive     NEVER -- still collapsed 40 s later
```

This is the stage that ends careers, and Phase 8 Lesson 11 named the mechanism: **metastable failure** (Bronson et al., *Metastable Failures in Distributed Systems*, HotOS 2021). A system pushed into a bad state that it then sustains on its own, through a feedback loop built out of correct components.

The dependency loses 55% of its capacity for 30 seconds and is then **fully restored.** Real demand never changes: 600 req/s, all the way through. The naive build's offered load peaks at **4,800 req/s — eight times real demand** — every bit of it retries chasing requests that timed out because of retries. When the trigger is removed the load is still 8× and the capacity is back to normal, which is not enough, so nothing recovers. Forty seconds later it is still at zero. Three restarts were needed across the whole exercise to get the naive build through the script at all; the hardened build needed none.

The hardened build degrades to **66.1% while the dependency is degraded** and returns to healthy **within a single 0.5-second tick** of the trigger being removed. It never entered the collapsed state, so it had no state to escape from. It got there by shedding **6,321 requests on purpose**, which is the sentence to sit with: the build that deliberately refused thousands of requests is the build that served more of them.

Note what the naive build shed: **zero.** It has no mechanism for refusing work. Its only available response to overload was to accept everything, and its only available recovery was a restart — which is shedding 100% of the load at once, with a cold cache afterwards and an outage in the middle.

### Stage 6 — the AZ, and the arithmetic that decides everything

```console
== 6 . STAGE 6 - AN ENTIRE AZ IS LOST ==
    the arithmetic that matters is PER REGION, not fleet-wide: DNS is
    still splitting traffic 50/50, so us-east must serve 300 req/s
    with 2 of its 3 zones.
    naive     10 instances left = 250 req/s vs 300 offered = rho 1.20
    hardened  20 instances left = 500 req/s vs 300 offered = rho 0.60
  us-east-1c gone               2.93%     392      18  |   98.17%     313     589
```

The arithmetic is the lesson, and the trap is doing it fleet-wide. Fleet-wide, naive loses 5 of 30 instances and has 83% of its capacity left for 100% of its load — uncomfortable but survivable. That reasoning is wrong, because **DNS is still splitting traffic 50/50 and does not know an AZ died.** us-east must still serve its 300 req/s, and it must now do it with 2 zones instead of 3.

```text
naive     10 instances x 25 req/s = 250 req/s  vs 300 offered  ->  rho = 1.20
hardened  20 instances x 25 req/s = 500 req/s  vs 300 offered  ->  rho = 0.60
```

ρ = 1.20 is not a utilization. It is a **deficit of 50 requests per second that accumulates forever**, and the naive region collapses to 2.93%. The hardened build sits at 0.60 and does not notice — 98.17%, with the tail moving from 181 ms to 313 ms and nothing else happening.

This is what Lesson 12's `N/(N−1)` rule buys, and it is why the rule is stated per failure domain rather than per fleet. Sizing so that any one of N zones can vanish means provisioning `N/(N−1)` of your peak requirement *inside each region*: with 3 zones, 1.5× — and you must then ask the same question one level up, where the domain is the region and N = 2.

### Stage 7 — the region

```console
== 7 . STAGE 7 - THE REGION IS LOST ==
  us-east gone: evacuate        0.00%     n/a       0  |   79.66%     455     478
    naive     shard primaries AND their replicas both lived in us-east.
              4 of 8 shards are gone, and a read that fans out to 5 of 8
              cannot be satisfied from 4: C(4,5)/C(8,5) = 0.
              Data gravity beat the compute plan -- even the SURVIVING
              region serves 0%.
    hardened  GSLB health check fails the region out after 15 s;
              resolvers decay with tau = 22 s toward a 1.8% floor that
              never clears (RFC 8767). The edge re-routes those anyway,
              at +80 ms. Replica promotion took 45 s; writes to the 4
              promoted shards failed for that window.
              RPO = 20 acknowledged writes lost (45 writes/s to the
              affected shards x 0.45 s of replication lag at the cut).
              autoscaler added capacity to the survivor: 30 -> 69 instances
              at a 90 s boot delay.

    served fraction, 10-second buckets from the moment of the loss:
      naive        0    0    0    0    0    0    0    0    0    0    0
      hardened    46   63   79   79   82   86   86   85   86   90   95
      t+ (s)       0   10   20   30   40   50   60   70   80   90  100
```

The naive build serves **zero percent** — and the reason is the most expensive lesson in the phase, because it has nothing to do with compute. The naive build had replicas. It had two of them per shard. Both of them lived in the same region as the primary, because that is where the low-latency network is and that is what the default configuration does.

So when us-east goes, four of eight shards go with it. And a read that fans out to 5 of 8 shards cannot be satisfied from 4: `C(4,5)/C(8,5) = 0/56 = 0`. **The surviving region is completely healthy, fully provisioned, and serves nothing**, because the data it needs is in the region that is gone. Every compute decision in the naive build — the fleet size, the balancing, the health checks — is irrelevant. Data gravity beat the compute plan.

The hardened evacuation is measured end to end and it is worth reading the curve rather than the summary, because it is not instant and pretending otherwise is how runbooks get written that do not work:

- **t+0 to t+15 s:** the GSLB has not noticed yet. Traffic is still being sent into a dead region and timing out. Served fraction 46%.
- **t+15 s:** the health check fails the region out. The edge starts re-routing to eu-west at +80 ms of extra latency.
- **t+15 to t+60 s:** resolvers decay toward the new answer with τ = 22 s, toward a floor of **1.8% that never clears** — resolvers that ignore TTL entirely, which [RFC 8767](https://www.rfc-editor.org/rfc/rfc8767) documents as deliberate stale-serving behaviour. Those are re-routed at the edge rather than lost, which is the only reason the floor is survivable.
- **t+45 s:** replica promotion completes. For those 45 seconds, writes to the four affected shards failed. **RPO = 20 acknowledged writes lost** — 45 writes/s to those shards × 0.45 s of replication lag at the moment of the cut. Those writes were acknowledged to users. They are gone.
- **t+90 s:** the autoscaler's instances finish booting, 30 → 69, and the survivor drops off the knee. Served fraction reaches **95%**.

The shape of that curve is the honest answer to "does failover work." It works, and it takes ninety seconds, and it costs twenty writes, and for the first fifteen seconds it does nothing at all because nothing had noticed yet.

### The whole exercise on one axis

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 418" width="100%" style="max-width:840px" role="img" aria-label="Measured served-traffic fraction over the whole 385-second failure script, naive against hardened, with the seven stages marked on one time axis. The hardened curve stays above 85 percent until the region is lost and recovers to 95 percent; the naive curve steps down at every stage, reaches zero during the retry storm and never returns, requiring three operator restarts, and stays at zero for the entire region loss.">
  <text x="440" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">Seven failures, one axis: the divergence is the whole phase</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <g fill="none" stroke="currentColor" stroke-width="1" stroke-dasharray="4 5" opacity="0.22">
      <path d="M92 96 L856 96"/><path d="M92 209 L856 209"/>
    </g>
    <path d="M92 82 L92 328" stroke="currentColor" stroke-width="1" stroke-dasharray="3 4" opacity="0.35" fill="none"/><text x="122" y="76" font-size="9" text-anchor="middle" font-weight="700" fill="currentColor" opacity="0.8">1</text><path d="M152 82 L152 328" stroke="currentColor" stroke-width="1" stroke-dasharray="3 4" opacity="0.35" fill="none"/><text x="181" y="76" font-size="9" text-anchor="middle" font-weight="700" fill="currentColor" opacity="0.8">2</text><path d="M211 82 L211 328" stroke="currentColor" stroke-width="1" stroke-dasharray="3 4" opacity="0.35" fill="none"/><text x="256" y="76" font-size="9" text-anchor="middle" font-weight="700" fill="currentColor" opacity="0.8">3</text><path d="M300 82 L300 328" stroke="currentColor" stroke-width="1" stroke-dasharray="3 4" opacity="0.35" fill="none"/><text x="350" y="76" font-size="9" text-anchor="middle" font-weight="700" fill="currentColor" opacity="0.8">4</text><path d="M400 82 L400 328" stroke="currentColor" stroke-width="1" stroke-dasharray="3 4" opacity="0.35" fill="none"/><text x="469" y="76" font-size="9" text-anchor="middle" font-weight="700" fill="currentColor" opacity="0.8">5</text><path d="M538 82 L538 328" stroke="currentColor" stroke-width="1" stroke-dasharray="3 4" opacity="0.35" fill="none"/><text x="588" y="76" font-size="9" text-anchor="middle" font-weight="700" fill="currentColor" opacity="0.8">6</text><path d="M638 82 L638 328" stroke="currentColor" stroke-width="1" stroke-dasharray="3 4" opacity="0.35" fill="none"/><text x="747" y="76" font-size="9" text-anchor="middle" font-weight="700" fill="currentColor" opacity="0.8">7</text><text x="122" y="342" font-size="8.5" text-anchor="middle" fill="currentColor" opacity="0.75">baseline</text><text x="181" y="342" font-size="8.5" text-anchor="middle" fill="currentColor" opacity="0.75">1 hung</text><text x="256" y="342" font-size="8.5" text-anchor="middle" fill="currentColor" opacity="0.75">grey 8x</text><text x="350" y="342" font-size="8.5" text-anchor="middle" fill="currentColor" opacity="0.75">poison</text><text x="469" y="342" font-size="8.5" text-anchor="middle" fill="currentColor" opacity="0.75">retry storm</text><text x="588" y="342" font-size="8.5" text-anchor="middle" fill="currentColor" opacity="0.75">AZ lost</text><text x="747" y="342" font-size="8.5" text-anchor="middle" fill="currentColor" opacity="0.75">REGION LOST</text>
    <path d="M400 322 L400 90" stroke="#d64545" stroke-width="1.4" stroke-dasharray="2 3" opacity="0.85" fill="none"/><text x="400" y="64" font-size="8" text-anchor="middle" fill="#d64545" font-weight="700">restart</text><path d="M538 322 L538 90" stroke="#d64545" stroke-width="1.4" stroke-dasharray="2 3" opacity="0.85" fill="none"/><text x="538" y="64" font-size="8" text-anchor="middle" fill="#d64545" font-weight="700">restart</text><path d="M638 322 L638 90" stroke="#d64545" stroke-width="1.4" stroke-dasharray="2 3" opacity="0.85" fill="none"/><text x="638" y="64" font-size="8" text-anchor="middle" fill="#d64545" font-weight="700">restart</text>
    <path d="M92 322 L856 322" fill="none" stroke="currentColor" stroke-width="1.4"/>
    <path d="M92 322 L92 86" fill="none" stroke="currentColor" stroke-width="1.2" opacity="0.6"/>
    <polyline points="92,98 98,98 104,97 110,98 116,98 122,97 128,99 134,98 140,97 146,97 152,102 157,103 163,99 169,98 175,97 181,97 187,99 193,98 199,97 205,97 211,116 217,114 223,112 229,113 235,101 241,99 247,100 253,99 259,99 265,101 271,100 277,100 283,99 288,102 294,100 300,116 306,115 312,120 318,115 324,114 330,113 336,112 342,113 348,103 354,99 360,97 366,97 372,97 378,99 384,99 390,98 396,149 402,192 408,168 413,166 419,167 425,165 431,169 437,167 443,169 449,167 455,145 461,97 467,97 473,98 479,97 485,99 491,97 497,98 503,98 509,98 515,97 521,97 527,97 533,97 538,100 544,101 550,100 556,101 562,100 568,100 574,99 580,100 586,101 592,99 598,104 604,100 610,99 616,100 622,99 628,100 634,139 640,218 646,220 652,218 658,220 664,192 669,143 675,142 681,142 687,144 693,144 699,144 705,145 711,141 717,147 723,137 729,127 735,131 741,129 747,126 753,127 759,130 765,127 771,127 777,131 783,133 789,125 794,130 800,126 806,128 812,128 818,129 824,116 830,106 836,107 842,107 848,108" fill="none" stroke="#0fa07f" stroke-width="2.4" stroke-linejoin="round"/>
    <polyline points="92,96 98,96 104,96 110,96 116,96 122,96 128,96 134,96 140,96 146,96 152,104 157,104 163,104 169,104 175,104 181,104 187,104 193,104 199,104 205,104 211,111 217,111 223,111 229,111 235,111 241,111 247,111 253,111 259,111 265,111 271,111 277,111 283,111 288,111 294,111 300,298 306,322 312,322 318,322 324,322 330,322 336,322 342,322 348,322 354,322 360,322 366,322 372,322 378,322 384,322 390,322 396,322 402,322 408,322 413,322 419,322 425,322 431,322 437,322 443,322 449,322 455,322 461,322 467,322 473,322 479,322 485,322 491,322 497,322 503,322 509,322 515,322 521,322 527,322 533,322 538,212 544,322 550,322 556,322 562,322 568,322 574,322 580,322 586,322 592,322 598,322 604,322 610,322 616,322 622,322 628,322 634,322 640,322 646,322 652,322 658,322 664,322 669,322 675,322 681,322 687,322 693,322 699,322 705,322 711,322 717,322 723,322 729,322 735,322 741,322 747,322 753,322 759,322 765,322 771,322 777,322 783,322 789,322 794,322 800,322 806,322 812,322 818,322 824,322 830,322 836,322 842,322 848,322" fill="none" stroke="#d64545" stroke-width="2.4" stroke-linejoin="round"/>
    <g fill="currentColor" font-size="9" opacity="0.65" text-anchor="end">
      <text x="86" y="100">100%</text><text x="86" y="213">50%</text><text x="86" y="326">0%</text>
    </g>
    <text x="34" y="215" font-size="10" fill="currentColor" opacity="0.85" transform="rotate(-90 34 215)" text-anchor="middle">served fraction</text>
    <g font-size="11" font-weight="700">
      <text x="112" y="368" fill="#0fa07f">HARDENED  90.10% over the run, 38.1 error-seconds, 0 restarts</text>
      <text x="112" y="386" fill="#d64545">NAIVE     26.69% over the run, 282.2 error-seconds, 3 restarts</text>
    </g>
    <rect x="92" y="359" width="12" height="3" fill="#0fa07f"/><rect x="92" y="377" width="12" height="3" fill="#d64545"/>
    <text x="440" y="410" font-size="11" text-anchor="middle" fill="currentColor" opacity="0.9">Same traffic, same seven faults, same code paths. Every step down on the red line is a defence that was not there.</text>
  </g>
</svg>
```

```console
== 8 . THE SEVEN STAGES, SIDE BY SIDE ==
  stage                  NAIVE    p99  good/s   util |  HARDENED    p99  good/s   util
  1 baseline           100.00%    238     600    80% |    99.24%    181     595    40%
  2 instance dies       96.66%    286     580    83% |    98.75%    178     592    41%
  3 grey failure        93.29%    348     560    91% |    96.59%    284     580    44%
  4 poison tenant        0.63%    365       4   999% |    95.46%    216     573   119%
  5 retry storm          0.00%    n/a       0   624% |    85.12%    371     511    41%
  6 AZ lost              2.93%    392      18   720% |    98.17%    313     589    41%
  7 region lost          0.00%    n/a       0   999% |    79.66%    455     478    65%
  WHOLE RUN             26.69%                       |    90.10%
```

Read down the naive column and watch the failure mode change character. Stages 2 and 3 are *proportional* — it loses roughly what broke, 3.3% and 6.7%. From stage 4 onward it is *total*, and the transition happens the moment a fault pushes utilization past 1.0. There is no gentle middle. That is the knee, and the naive build was parked at 80% with nowhere to go.

### The error budget, which is the answer to the assignment

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 400" width="100%" style="max-width:840px" role="img" aria-label="Cumulative error budget consumed over the 385-second exercise, plotted as a percentage of the 99.95 percent monthly budget of 21.9 minutes. The naive configuration climbs steadily to 21.5 percent of the entire month's budget, while the hardened configuration reaches only 2.9 percent, a factor of 7.4. A dashed line marks the 8.3 percent level that one exercise may consume if twelve are run per month.">
  <text x="440" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">Error budget burn: 6.4 minutes of failure against a 21.9-minute month</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <g fill="none" stroke="currentColor" stroke-width="1" stroke-dasharray="4 5" opacity="0.2">
      <path d="M92 273 L856 273"/>
      <path d="M92 228 L856 228"/>
      <path d="M92 182 L856 182"/>
      <path d="M92 137 L856 137"/>
    </g>
    <path d="M92 243 L856 243" fill="none" stroke="#e0930f" stroke-width="1.6" stroke-dasharray="7 4" opacity="0.9"/>
    <text x="100" y="236" font-size="9" fill="#e0930f" font-weight="700">8.3% - all one exercise may cost if you run 12 a month</text>
    <path d="M92 318 L856 318" fill="none" stroke="currentColor" stroke-width="1.4"/>
    <path d="M92 318 L92 82" fill="none" stroke="currentColor" stroke-width="1.2" opacity="0.6"/>
    <polyline points="92,318 98,318 104,318 110,318 116,318 122,318 128,318 134,318 140,318 146,318 152,318 157,318 163,318 169,318 175,318 181,318 187,318 193,317 199,317 205,317 211,317 217,317 223,317 229,317 235,317 241,317 247,316 253,316 259,316 265,316 271,316 277,316 283,316 288,315 294,315 300,314 306,312 312,310 318,308 324,306 330,304 336,302 342,300 348,298 354,296 360,294 366,292 372,290 378,287 384,285 390,283 396,281 402,279 408,277 413,275 419,273 425,271 431,269 437,267 443,265 449,263 455,261 461,259 467,257 473,254 479,252 485,250 491,248 497,246 503,244 509,242 515,240 521,238 527,236 533,234 538,233 544,231 550,229 556,227 562,225 568,222 574,220 580,218 586,216 592,214 598,212 604,210 610,208 616,206 622,204 628,202 634,200 640,198 646,196 652,194 658,192 664,189 669,187 675,185 681,183 687,181 693,179 699,177 705,175 711,173 717,171 723,169 729,167 735,165 741,163 747,161 753,159 759,156 765,154 771,152 777,150 783,148 789,146 794,144 800,142 806,140 812,138 818,136 824,134 830,132 836,130 842,128 848,126" fill="none" stroke="#d64545" stroke-width="2.6" stroke-linejoin="round"/>
    <polyline points="92,318 98,318 104,318 110,318 116,318 122,318 128,318 134,318 140,318 146,318 152,318 157,318 163,318 169,318 175,318 181,318 187,318 193,318 199,318 205,318 211,317 217,317 223,317 229,317 235,317 241,317 247,317 253,317 259,317 265,317 271,317 277,317 283,317 288,317 294,317 300,316 306,316 312,316 318,316 324,316 330,316 336,315 342,315 348,315 354,315 360,315 366,315 372,315 378,315 384,315 390,315 396,315 402,314 408,313 413,313 419,312 425,311 431,311 437,310 443,309 449,309 455,308 461,308 467,308 473,308 479,308 485,308 491,308 497,308 503,308 509,308 515,308 521,308 527,308 533,308 538,308 544,308 550,308 556,308 562,308 568,308 574,308 580,308 586,307 592,307 598,307 604,307 610,307 616,307 622,307 628,307 634,307 640,306 646,305 652,304 658,303 664,302 669,301 675,301 681,300 687,300 693,299 699,299 705,299 711,298 717,298 723,297 729,297 735,297 741,296 747,296 753,296 759,296 765,295 771,295 777,295 783,294 789,294 794,294 800,293 806,293 812,293 818,293 824,292 830,292 836,292 842,292 848,292" fill="none" stroke="#0fa07f" stroke-width="2.6" stroke-linejoin="round"/>
    <g fill="currentColor" font-size="9" opacity="0.65" text-anchor="end">
      <text x="86" y="141">20%</text>
      <text x="86" y="186">15%</text>
      <text x="86" y="232">10%</text>
      <text x="86" y="277">5%</text>
      <text x="86" y="322">0</text>
    </g>
    <g font-size="8.5" fill="currentColor" opacity="0.7" text-anchor="middle">
      <text x="92" y="336">0 s</text><text x="300" y="336">105</text>
      <text x="538" y="336">225</text><text x="638" y="336">275</text><text x="856" y="336">385 s</text>
    </g>
    <text x="30" y="205" font-size="10" fill="currentColor" opacity="0.85" transform="rotate(-90 30 205)" text-anchor="middle">% of the monthly budget</text>
    <text x="320" y="144" font-size="10.5" font-weight="700" fill="#d64545">NAIVE - 21.5% of a whole month, in 6.4 minutes</text>
    <text x="390" y="276" font-size="10.5" font-weight="700" fill="#0fa07f">HARDENED - 2.9%</text>
    <g fill="currentColor" font-size="10">
      <text x="112" y="352">budget = 0.05% x 43,830 min = <tspan font-weight="700">21.9 min = 1,315 error-seconds per month</tspan></text>
      <text x="112" y="368">naive spent <tspan font-weight="700" fill="#d64545">282.2 s</tspan>; hardened spent <tspan font-weight="700" fill="#0fa07f">38.1 s</tspan>. One is 4.7 exercises a month, the other 34.5.</text>
    </g>
    <text x="440" y="392" font-size="11" text-anchor="middle" fill="currentColor" opacity="0.9">A budget is not spent only by outages. Every deploy, dependency and game day comes out of the same 21.9 minutes.</text>
  </g>
</svg>
```

```console
== 9 . ERROR BUDGET ACCOUNTING ==
  the budget: 99.95% x 43,830 min/month = 21.9 min = 1315 error-seconds
  the exercise: 385 simulated seconds (6.4 min) of
  deliberate failure injection, identical for both configurations.

              error-seconds   minutes  % of budget   exercises/month
  naive               282.2      4.70       21.5%               4.7
  hardened             38.1      0.64        2.9%              34.5
```

This is the number the board asked for. Six minutes and twenty-five seconds of deliberate failure injection cost the naive build **21.5% of an entire month's error budget.** It could afford 4.7 such days per month and nothing else could ever go wrong — no deploy, no dependency incident, no expired certificate, no human error. The hardened build could afford 34.5.

That reframing is the most useful thing to take into a planning meeting. An error budget is not a measure of how bad your outages were. It is a **spending account**, and every game day, every risky deploy and every dependency's bad afternoon draws on the same balance. If a single fire drill costs a fifth of the month, you cannot run fire drills, which means you cannot know whether your failover works, which is how you arrive at a board meeting with no answer.

### The ablation — which defences actually earned their complexity

Now the most valuable output. Re-run the identical seven-stage script with exactly **one defence disabled at a time** and measure the delta.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 470" width="100%" style="max-width:840px" role="img" aria-label="Ranked chart of the measured availability contribution of each defence, obtained by re-running the whole failure script with one defence disabled at a time. Cross-region replicas cost 87.6 extra error-seconds when removed, load shedding 46.5, capacity headroom 36.5, retry budget 11.6, autoscaling 6.5, outlier ejection 2.4, hedged reads 1.5, least-request balancing 0.2 and deadline propagation none. Shuffle sharding is negative at minus 12 error-seconds, meaning removing it improved aggregate availability while raising the number of customers driven below 95 percent from 29 to all 60.">
  <text x="440" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">Ablation: what each defence was actually worth, measured</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <g fill="currentColor" font-size="9" font-weight="700" opacity="0.65">
      <text x="24" y="56">DEFENCE REMOVED (and the lesson it came from)</text> <text x="352" y="56">EXTRA ERROR-SECONDS CAUSED BY REMOVING IT</text> <text x="856" y="56" text-anchor="end">CUSTOMERS &lt;95%</text>
    </g>
    <path d="M20 62 L860 62" fill="none" stroke="currentColor" stroke-width="1.1" opacity="0.4"/> <path d="M352 70 L352 400" fill="none" stroke="currentColor" stroke-width="1.3" opacity="0.55"/> <text x="352" y="416" font-size="9" text-anchor="middle" fill="currentColor" opacity="0.7">0</text>
    <text x="404" y="416" font-size="9" text-anchor="middle" fill="currentColor" opacity="0.7">+10</text> <text x="612" y="416" font-size="9" text-anchor="middle" fill="currentColor" opacity="0.7">+50</text> <text x="820" y="416" font-size="9" text-anchor="middle" fill="currentColor" opacity="0.7">+90</text>
    <text x="290" y="416" font-size="9" text-anchor="middle" fill="currentColor" opacity="0.7">-12</text>
    <g fill="none" stroke="currentColor" stroke-width="1" stroke-dasharray="3 5" opacity="0.2">
      <path d="M404 70 L404 400"/><path d="M508 70 L508 400"/><path d="M612 70 L612 400"/><path d="M716 70 L716 400"/><path d="M820 70 L820 400"/>
    </g>

    <g stroke-width="1.6">
      <rect x="352" y="74"  width="455" height="22" rx="3" fill="#d64545" fill-opacity="0.22" stroke="#d64545"/> <rect x="352" y="106" width="242" height="22" rx="3" fill="#d64545" fill-opacity="0.18" stroke="#d64545"/> <rect x="352" y="138" width="190" height="22" rx="3" fill="#d64545" fill-opacity="0.18" stroke="#d64545"/>
      <rect x="352" y="170" width="60"  height="22" rx="3" fill="#e0930f" fill-opacity="0.18" stroke="#e0930f"/> <rect x="352" y="202" width="34"  height="22" rx="3" fill="#e0930f" fill-opacity="0.16" stroke="#e0930f"/> <rect x="352" y="234" width="12"  height="22" rx="3" fill="#7f7f7f" fill-opacity="0.16" stroke="#7f7f7f"/>
      <rect x="352" y="266" width="8"   height="22" rx="3" fill="#7f7f7f" fill-opacity="0.16" stroke="#7f7f7f"/> <rect x="352" y="298" width="3"   height="22" rx="1" fill="#7f7f7f" fill-opacity="0.16" stroke="#7f7f7f"/> <rect x="352" y="330" width="2"   height="22" rx="1" fill="#7f7f7f" fill-opacity="0.16" stroke="#7f7f7f"/>
      <rect x="290" y="362" width="62"  height="22" rx="3" fill="#3553ff" fill-opacity="0.18" stroke="#3553ff"/>
    </g>

    <g fill="currentColor" font-size="10.5">
      <text x="24" y="89">cross-region replicas</text> <text x="24" y="121">load shedding</text> <text x="24" y="153">capacity headroom</text>
      <text x="24" y="185">retry budget</text> <text x="24" y="217">autoscaling</text> <text x="24" y="249">outlier ejection</text>
      <text x="24" y="281">hedged reads</text> <text x="24" y="313">least-request balancing</text> <text x="24" y="345">deadline propagation</text>
      <text x="24" y="377">shuffle sharding</text>
    </g>
    <g fill="currentColor" font-size="9" opacity="0.6">
      <text x="222" y="89">L10</text><text x="222" y="121">Ph8 L11</text><text x="222" y="153">L12</text> <text x="222" y="185">Ph8 L11</text><text x="222" y="217">L13</text><text x="222" y="249">L04</text> <text x="222" y="281">L11</text><text x="222" y="313">L03</text><text x="222" y="345">L11</text>
      <text x="222" y="377">L09</text>
    </g>
    <g font-size="10" font-weight="700">
      <text x="797" y="89" text-anchor="end" fill="#d64545">+87.6</text> <text x="602" y="121" fill="#d64545">+46.5</text> <text x="550" y="153" fill="#d64545">+36.5</text>
      <text x="420" y="185" fill="#e0930f">+11.6</text> <text x="394" y="217" fill="#e0930f">+6.5</text> <text x="372" y="249" fill="currentColor" opacity="0.8">+2.4</text>
      <text x="368" y="281" fill="currentColor" opacity="0.8">+1.5</text> <text x="362" y="313" fill="currentColor" opacity="0.8">+0.2</text> <text x="362" y="345" fill="currentColor" opacity="0.8">0.0</text>
      <text x="282" y="377" text-anchor="end" fill="#3553ff">-12.0</text>
    </g>
    <g fill="currentColor" font-size="10" text-anchor="end" opacity="0.9">
      <text x="856" y="89">29/60</text><text x="856" y="121">35/60</text> <text x="856" y="153" font-weight="700" fill="#d64545">60/60</text> <text x="856" y="185">29/60</text><text x="856" y="217">29/60</text><text x="856" y="249">29/60</text>
      <text x="856" y="281">29/60</text><text x="856" y="313">29/60</text><text x="856" y="345">29/60</text> <text x="856" y="377" font-weight="700" fill="#d64545">60/60</text>
    </g>

    <path d="M20 396 L860 396" fill="none" stroke="currentColor" stroke-width="1" opacity="0.35"/>
    <g fill="currentColor" font-size="10">
      <text x="24" y="440" font-weight="700" fill="#3553ff">Read the last row in BOTH columns.</text> <text x="256" y="440">Removing shuffle sharding raised fleet availability 90.10% -&gt; 93.21%</text> <text x="24" y="456">and took customers below 95% from 29 to 60. It does not reduce damage; it decides who receives it.</text>
    </g>
  </g>
</svg>
```

```console
  defence removed               avail   cost of removing it   blast
  cross-region replicas L10    67.34%          +87.6 err-s   29/60  ########################
  load shedding      P8L11     78.02%          +46.5 err-s   35/60  #############...........
  capacity headroom    L12     80.63%          +36.5 err-s   60/60  ##########..............
  retry budget       P8L11     87.08%          +11.6 err-s   29/60  ###.....................
  autoscaling          L13     88.41%           +6.5 err-s   29/60  ##......................
  outlier ejection     L04     89.48%           +2.4 err-s   29/60  #.......................
  hedged reads         L11     89.70%           +1.5 err-s   29/60  ........................
  least-request LB     L03     90.04%           +0.2 err-s   29/60  ........................
  deadline propagation L11     90.10%           +0.0 err-s   29/60  ........................
  shuffle sharding     L09     93.21%          -12.0 err-s   60/60  ........................
  -- none (hardened) --        90.10%           +0.0 err-s   29/60
```

Three things in that table are worth more than the ranking itself.

**The top of the list is not where most engineering effort goes.** Cross-region replicas cost **87.6 error-seconds** to remove — more than the next two combined. It is a data-tier decision, made once, mostly invisible, and worth more than every routing algorithm in the phase put together. Load shedding is second at 46.5, capacity headroom third at 36.5. These are structural, boring, and expensive. The clever things are at the bottom.

**The bottom of the list is honest, not embarrassing.** Least-request balancing measured at +0.2 error-seconds. Deadline propagation at +0.0. That does not mean they are wrong — it means that against *this* failure script, with *this* much headroom and *these* other defences already present, they had almost nothing left to do. A defence can be correct, well built, and worth nothing right up until the day the specific failure it exists for arrives. What the ablation buys you is knowing *which* of your defences are in that category, so you can decide deliberately whether to keep paying for them.

**And one row is negative.** Removing shuffle sharding *improved* aggregate availability, 90.10% → 93.21%. That is not a bug and it is the most useful line in the table. Read it together with the blast column: customers driven below 95% went from **29 to 60**. Shuffle sharding does not reduce total damage — with enough headroom, spreading a poison tenant thinly across sixty instances genuinely hurts less in aggregate than concentrating it on three. What it does is **decide who receives the damage**, and it decides in favour of the fifty-nine customers who did nothing wrong. That is a real trade with a real price, and the only reason you know the price is that you turned it off and measured.

```console
  == the order of defences: measured interactions ==
  pair removed                 measured  sum of parts  interaction
  shedding + retry budget       +148.5        +58.1         2.6x
  headroom + autoscaling         +86.0        +43.0         2.0x
  shedding + deadlines           +66.9        +46.5         1.4x
  least-request + ejection        -0.0         +2.6        -0.0x
```

And the interactions, which is where the "order of defences" claim stops being an opinion. Three pairs cost substantially more than the sum of their parts — they are dependencies, not additions. The fourth is the null result, reported because it was predicted and did not appear.

### The bill

```console
== 11 . THE BILL ==
  instance-seconds consumed across the run (autoscaling included):
    naive          9,650
    hardened      20,815   (2.16x)
  extrapolated at $0.096 per instance-hour, at 1:100 scale, per month:
    naive     $     175,790
    hardened  $     379,178   (+$203,388/month)

  operator restarts needed to get through the exercise:
    naive      3   after: 4 poison tenant (t=155.0 s), 5 retry storm (t=225.0 s), 6 AZ lost (t=275.0 s)
    hardened   0
```

**7× less error budget burned, for 2.2× the compute spend, at about two hundred thousand dollars a month.** Whether that trade is correct is a business decision and not an engineering one — but it is now a decision with two numbers in it instead of an argument between someone who wants a bigger fleet and someone who wants a smaller bill.

And the last two lines are the ones to put in the summary. The naive build needed **three full fleet restarts** to get through a six-minute exercise. A restart is not a recovery; it is the absence of any other option, and each one costs you every warm cache and every in-flight request you had.

## Use It

You will not have a simulator at work. You will have a real system, real customers, and a very reasonable colleague asking why you want to break it on purpose. What follows is how this exercise transfers.

### Run it as a game day, and write the hypothesis first

A **game day** is a scheduled exercise in which you inject a known failure into a real system and observe what happens. The single discipline that separates a game day from an outage is this:

> **Write down what you expect to happen, in numbers, before you inject anything.**

Not "we expect it to fail over." Write: *"We expect the GSLB to fail us-east out within 30 seconds. We expect served traffic to dip to no less than 40% and to recover above 95% within 3 minutes. We expect fewer than 50 acknowledged writes to be lost. We expect no customer to drop below 90% availability for more than 60 seconds."*

Three reasons this matters, and only the first is obvious. It converts the exercise from a demonstration into an **experiment** — a demonstration can only confirm what you believe, an experiment can refute it. It gives you an **abort condition** that is a number rather than a feeling, so the decision to stop is not made by whoever is most anxious. And it is the only way to learn the most valuable thing a game day produces, which is not "the system failed" but **"the system behaved differently from how the people who operate it believe it behaves."** That gap is where your next incident lives, and you cannot find it without writing the belief down first.

### What to inject, in what order

Escalate exactly as the simulator does, and do not skip ahead. Each stage should be a separate exercise, days or weeks apart, and you should not move up until the previous one is boring.

| Order | Inject | Where | Expect |
|---|---|---|---|
| 1 | Kill one instance | `kubectl delete pod`, terminate an EC2 instance | Ejection inside one health-check window; no user-visible error |
| 2 | **Hang** one instance | `SIGSTOP` the process, or a fault-injection filter returning no response | This is the real test. A layer-4 check will not see it |
| 3 | Slow one instance | `tc qdisc add ... netem delay 300ms`, or a CPU-burn sidecar | Least-request starves it; outlier ejection removes it |
| 4 | Concentrate load on one tenant | replay a heavy customer's traffic at 10× | Blast radius stays inside that tenant's shard |
| 5 | Degrade a dependency | fault-injection latency on a service mesh route | Shedding engages; offered load does **not** multiply |
| 6 | Remove an AZ | drain nodes, or block the subnet at the NACL | Absorbed with no traffic shift needed |
| 7 | Remove a region | fail the GSLB health check for that region | The full runbook, timed |

Stage 5 has a specific check that is easy to forget and is the whole point of that stage: **measure your own offered load during the injection.** If it rises, your retry configuration is amplifying, and you will find that out here for the price of a scheduled exercise rather than at 03:00 for the price of an outage.

### How to abort safely

- **Define the abort condition numerically, before you start**, and give exactly one person — the incident commander — the authority to call it. Anyone may *request* an abort; one person decides.
- **Know your abort latency.** If reverting takes 90 seconds, your abort threshold must trigger 90 seconds before the point where customer impact becomes unacceptable, not at it.
- **Do the first run in a lower environment**, then in production at a low-traffic hour, then at peak. The exercise that only ever runs at 03:00 on a Sunday has told you about your Sunday system.
- **Never inject two faults at once** until each one individually is boring. The ablation in this lesson exists precisely because compound failures are not the sum of their parts; you cannot attribute anything in a compound test.
- **Have the abort be one command**, tested, in the runbook, that someone who is not the author has executed at least once.

Phase 12 covers [chaos engineering as a testing practice](../../../README.md#phase-12) — how to make this continuous and automated rather than scheduled and manual. This lesson is the manual version, and you should be fluent at the manual version first, because an automated chaos experiment that nobody understands is a scheduled outage.

### An evacuation exercise schedule

Regional evacuation is the one exercise that decays fastest, because it depends on configuration in a dozen systems that all drift independently.

| Cadence | Exercise |
|---|---|
| Weekly | Automated: kill instances at random during business hours |
| Monthly | Remove one AZ from one region, announced, at peak |
| Quarterly | **Full regional evacuation, announced.** Time every step against the runbook |
| Annually | Full regional evacuation, **unannounced**, during business hours |
| Every evacuation | Measure RPO against what you claim. Compare RTO to the runbook's estimate |

The gap between the quarterly announced test and the annual unannounced one is where most organisations actually live, and it is where the interesting failures are — not in the system, in the humans and the paging and the fact that the one person who knows how to promote the replica is on a plane.

### What you need in place before any of this works

- **Phase 9's observability.** You cannot run any of these exercises without per-region, per-AZ, per-tenant SLIs measured at the edge. If your only availability metric is fleet-wide, stage 6 is invisible to you — the naive build's fleet-wide utilization looked survivable while one region was at ρ = 1.20. Per-customer availability is what makes the stage 4 blast-radius number exist at all. See [SLIs, SLOs & Error Budgets](../../09-logging-monitoring-and-observability/09-slis-slos-and-error-budgets/).
- **Phase 10's deployment machinery.** The evacuation runbook assumes you can scale a region out, shift traffic, and roll back, all without a deploy. If any of those requires a code change, your evacuation time is your deploy pipeline's duration and the runbook is fiction.
- **The degradation tiers from [Phase 8 Lesson 11](../../08-concurrency-and-performance/11-backpressure-and-load-shedding/).** Shedding is only survivable because not all traffic is equal. Decide the tiers now.

### A maturity ladder

Find your own system on it honestly. Most organisations are one level lower than they say they are, because the claim is about the architecture and the level is about the last time it was tested.

| Level | Where you are |
|---|---|
| **1** | Single region. Backups exist. Nobody has restored one. Your RPO is a guess. |
| **2** | Multi-AZ within one region, tested by accident when an AZ had a bad day. A second region exists in a Terraform file. |
| **3** | Two regions, active-passive. A written evacuation runbook. It has been executed once, in a lower environment, by its author. |
| **4** | Active-active, quarterly announced evacuation exercises, measured RPO and RTO, and the runbook is corrected after each one. |
| **5** | Unannounced regional evacuations during business hours, on a routine cadence, with no customer-visible impact and no change to the on-call roster. |

The jump from 3 to 4 is the one that matters and it is almost entirely organisational. Level 3 has all the same technology as level 4. The difference is whether anyone is allowed to spend error budget proving it works.

## Key takeaways

These are the takeaways of the whole phase.

- **The composition is the system, not the parts.** Two builds with identical traffic and an identical seven-stage failure script finished at **90.10% and 26.69%** availability, **38.1 against 282.2 error-seconds**, and **0 against 3 operator restarts**. Every individual technique in the hardened build is one you could have argued for on its own; none of them produced that gap alone.
- **Your error budget is a spending account, and a fire drill draws on it.** 99.95% is **21.9 minutes a month** — `0.05% × 43,830` — for deploys, dependencies, DNS, humans and tests combined. Six minutes of injected failure cost the naive build **21.5% of the month.** If one exercise costs a fifth of your budget, you cannot afford to know whether your failover works.
- **Data gravity beats every compute decision you will make.** The naive build lost a region and served **0%** — from the *surviving* region, which was healthy and fully provisioned — because both replicas of every shard lived beside their primary and a fan-out read needs 5 of 8 shards: `C(4,5)/C(8,5) = 0`. Cross-region replicas were the single most valuable defence measured, at **+87.6 error-seconds** to remove, worth more than the next two combined.
- **Round-robin's failure rate equals the broken fraction of your fleet, by construction.** Measured: **6.71% of traffic lost against 6.67% of the fleet sick.** It does not measure anything, so it cannot route around anything. And a layer-4 health check never ejected the 8×-slow instance at all, because the port was open — **6.0 seconds** to eject a hung process with a layer-7 probe, **never** with a TCP one.
- **Shedding is what recovery is made of, and the build that refuses more requests serves more users.** The hardened build shed **6,321 requests on purpose**, degraded to **66.1%** during the trigger, and recovered **within one 0.5-second tick** of its removal. The naive build shed **zero**, drove its own offered load to **4,800 req/s against 600 of real demand**, and never recovered — the trigger left, the outage stayed.
- **Utilization has no gentle middle; it has a knee.** Naive lost proportionally at stages 2 and 3 (3.3%, 6.7%) and totally from stage 4 on, and the transition is exactly where per-region ρ crossed 1.0. Losing one of three zones took us-east to **ρ = 1.20 — a 50 req/s deficit that accumulates forever.** Do the arithmetic per failure domain, never fleet-wide: fleet-wide it looked like 83% capacity remaining.
- **The order of defences is a measured dependency, not a stylistic preference.** Removing shedding and the retry budget together cost **148.5 error-seconds against a 58.1 sum — 2.6×**. Headroom and autoscaling: **86.0 against 43.0, 2.0×**. Headroom is what an autoscaler reclaims, not what it produces; 90 seconds of instance boot does not help a 400 ms deadline.
- **Ablate, and publish the negative results.** Shuffle sharding *reduced* aggregate availability (90.10% → 93.21% when removed) while taking customers below 95% from **29 to 60**: it does not reduce damage, it decides who receives it. Least-request measured **+0.2** and deadline propagation **+0.0** against this script. You only know which of your defences are currently earning their complexity by switching them off one at a time and measuring — everything else is a story.

You have reached the end of Phase 11. **Next comes Phase 12: Testing and Quality.** This phase proved the system survives the failures you injected on purpose — seven of them, chosen by you, in an order you controlled, with a runbook open. The next phase is about the failures you did not think to inject: the ones that arrive as a regression in a code path nobody tested, a contract that changed underneath you, or a query that was fine until the data grew. You have measured what your system does when you break it deliberately. The remaining question is what it does when it breaks itself.
