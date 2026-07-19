# The Universal Scalability Law: Why 2× the Machines Isn't 2× the Throughput

> Everyone knows about Amdahl's Law and the serial fraction that caps your speedup. Almost nobody knows about the second term — the one that makes throughput go *down*. Measured here on a simulated fleet: doubling from 32 machines to 64 cost **17.8% of throughput** and 2.43× the cost per request, and **removing** those 32 machines recovered **+21.7%** in one deploy. Amdahl's Law predicted a ceiling of 41× and told you to keep buying. The real peak was 10.96× at 32 machines. This lesson teaches you to fit both terms to your own load test and find your peak before your traffic finds it for you.

**Type:** Build
**Languages:** Python
**Prerequisites:** [What One Machine Can Actually Do](../01-what-one-machine-can-do/), [Why Concurrency? Latency, Throughput & Little's Law](../../08-concurrency-and-performance/01-why-concurrency/)
**Time:** ~75 minutes

## The Problem

It is 09:40 on the morning of a product launch. You run a fleet of 24 instances behind a load balancer, doing about 19,000 requests per second. Marketing sends the email at 10:00 and you are expecting roughly double the traffic, so at 09:40 you do the responsible thing and pre-scale. You take the fleet from 24 instances to 48.

**09:44 — the new instances are healthy.** All 48 pass their readiness probes. The load balancer has them all in rotation. CPU per instance drops from 61% to 34%, exactly as arithmetic says it should when you halve each machine's share of the work. Your dashboard is a wall of green. You go and get a coffee.

**09:52 — throughput is 17,400 req/s.** Not 19,000. Not the 20,000-odd you would expect from a bit of extra headroom. **Less than before you scaled.** You refresh, assuming a stale panel. It is not stale. Requests per second across the fleet has fallen by 8% while the number of machines serving them doubled.

**09:55 — p99 is up from 240 ms to 505 ms.** This makes no sense against everything else on the screen. Each instance is *less* busy than it was an hour ago. There is no error. There is no restart loop. The database's CPU is *down*, its connection count is up but well inside `max_connections`, and its slowest query is the same slow query it has been all week. Nothing is saturated. Nothing is broken. The system is simply slower with more of it.

**10:00 — the traffic arrives.** Now you are past the point where you can think. The fleet is at 48 instances doing 17,400 req/s against demand that has just doubled, so the queues start filling, and everything you learned in Phase 8 about the utilization knee and metastable failure begins to happen on schedule.

**10:06 — someone suggests scaling to 96.** It is the obvious move. It is the only move anybody has. Every incident playbook, every autoscaler, every instinct built over a career says *the fleet is not keeping up, add capacity*. You have a dashboard that shows CPU per instance at 34% and a throughput number that is falling, and the standard reading of those two facts together is "add machines."

It is the wrong move, and it will make the outage worse. **The right move is to scale in — to delete 24 of the 48 instances you just created.** Nothing on any dashboard you own will suggest that, because the dashboards were built by people who believe capacity is additive.

Here is what actually happened. Your throughput as a function of fleet size is not a straight line and it is not even a curve that flattens out. It is a curve that **rises, peaks, and comes back down**, and at 09:40 you were sitting a little to the left of its peak. Scaling to 48 carried you over the top and down the far side. There was never a version of this morning in which 48 instances did more work than 24 — that outcome was determined by the shape of the curve long before the launch, and the only thing the launch did was make you find out.

Nobody told you the curve had a peak. That is the entire lesson. By the end of it you will be able to measure your own curve, fit the two coefficients that define it, compute where its peak is, and compare that number to the size of the fleet you are running right now.

## The Concept

### Linear scaling is the assumption nobody states

Write down how you plan capacity. It probably looks like this: *one instance handles 800 req/s, we need 19,000 req/s, so we need 24 instances.* That arithmetic contains an assumption so basic that it never gets said out loud:

```text
C(N) = N
```

`C(N)` is **capacity**, or more precisely the **relative capacity**: the throughput of an N-machine system divided by the throughput of a one-machine system. Linear scaling says that ratio is just N. Two machines do twice the work of one. A hundred do a hundred times.

This is never true, and everything else in this lesson is a correction term bolted onto it. There are exactly two corrections that matter, and they behave completely differently. The first one you have probably heard of. The second one is the one that ends launches.

### Amdahl's Law: the serial fraction (σ)

Gene Amdahl's 1967 argument was about parallel computers, but it is really about any job you split across workers. Take a unit of work that costs 1 unit of time on a single machine. Some fraction of it **cannot be split** — it has to happen once, on its own, no matter how many machines you own. Call that fraction **σ** (sigma), the **serial fraction**. The rest, `1 − σ`, splits perfectly.

Run it on N machines. The serial part still costs σ. The parallel part costs `(1 − σ)/N`. So:

```text
time(N)  =  σ + (1 − σ)/N
C(N)     =  time(1) / time(N)  =  1 / (σ + (1 − σ)/N)
```

Multiply top and bottom by N and you get the form worth memorising:

```text
C(N)  =  N / (1 + σ(N − 1))                    Amdahl's Law
```

Work it longhand at **σ = 0.05** — five percent of the job is serialized, which sounds like almost nothing:

```text
N = 100:   time = 0.05 + 0.95/100 = 0.05 + 0.0095 = 0.0595
           C    = 1 / 0.0595 = 16.81
```

**A hundred machines bought you 16.81× the throughput.** You paid for 100 and received 16.81, and 83 of those machines produced nothing. Now push N to infinity: `(1 − σ)/N` goes to zero and the time bottoms out at σ itself, so

```text
C(∞)  =  1/σ  =  1/0.05  =  20×
```

**Twenty times, forever.** Not twenty times at a hundred machines — twenty times at a *thousand* machines, at a million, at any number you can afford. The serial fraction is a hard ceiling and you cannot buy your way past it. Five percent of your work being serialized costs you 95% of a hundred-machine fleet.

The important question is not the formula, it is: *what is σ in a real backend?* It is never one thing labelled "the serial fraction". It is:

- **The one primary database.** Every write in your system funnels through a single process that applies them in order. That is σ, and it is usually the biggest one.
- **The single leader.** A partition leader, a lock manager, a scheduler, the one node allowed to assign IDs.
- **The lock.** Any mutex, any `SELECT … FOR UPDATE`, any row every request has to touch — the inventory count, the account balance, the rate-limit counter for your biggest customer.
- **The one queue.** A topic with one partition is a serial resource wearing a distributed system's clothing.
- **The config service every instance reads at startup.** Invisible at steady state; it is why deploying 300 instances at once takes longer than 300× deploying one.

Notice what all of these have in common: **you can point at them.** A σ problem has an address. Something is at 100% utilization and everything else is queued behind it. That is a bad day, but it is a *legible* bad day, and every profiling and monitoring instinct you have will find it.

### The coherency term (κ): why it gets WORSE, not just flat

Here is what Amdahl's Law cannot express: **it never goes down.** `N / (1 + σ(N−1))` is monotonically increasing in N. It flattens, it approaches 1/σ, it wastes your money — but every machine you add makes the number go up by *something*, however small. If Amdahl's Law were the whole story, over-provisioning would only ever be a waste, never a hazard, and the worst outcome of scaling out would be a large bill.

Neil Gunther's **Universal Scalability Law** (*Guerrilla Capacity Planning*, Springer, 2007) adds one term:

```text
C(N)  =  N / (1 + σ(N − 1) + κN(N − 1))       the USL
                └ contention ┘  └ coherency ┘
```

**κ** (kappa) is the **coherency coefficient**, and the thing to stare at is that it multiplies `N(N − 1)` — a term **quadratic** in N, while the serial term is only linear. The reason is not mathematical convenience. It is a count of something real.

`N(N − 1)/2` is the number of **pairs** of nodes. `N(N − 1)` is the number of **directed exchanges** between them — once in each direction. When work requires nodes to agree with one another, the cost is not proportional to the number of nodes; it is proportional to the number of *relationships* between nodes, and relationships grow as the square:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 442" width="100%" style="max-width:840px" role="img" aria-label="Three coordination topologies drawn as node graphs. Four nodes fully connected have six pairs and twelve directed exchanges. Eight nodes fully connected have twenty-eight pairs and fifty-six exchanges, so doubling the node count multiplied the pairs by 4.7. Eight nodes with a fixed fanout of three peers have only twelve pairs and twenty-four exchanges, and that count grows linearly rather than quadratically. A table underneath shows pairs growing from 6 at N equals 4 to 2016 at N equals 64 under all-to-all, against 96 and 192 under a fixed fanout of three.">
  <text x="440" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">You are not adding nodes. You are adding PAIRS — and pairs grow as N squared.</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <g fill="none" stroke="#7f7f7f" stroke-width="1.3" opacity="0.75"><path d="M150.0 114.0 L208.0 172.0"/><path d="M150.0 114.0 L150.0 230.0"/><path d="M150.0 114.0 L92.0 172.0"/><path d="M208.0 172.0 L150.0 230.0"/><path d="M208.0 172.0 L92.0 172.0"/><path d="M150.0 230.0 L92.0 172.0"/></g>
    <g fill="none" stroke="#d64545" stroke-width="1.1" opacity="0.6"><path d="M440.0 106.0 L486.7 125.3"/><path d="M440.0 106.0 L506.0 172.0"/><path d="M440.0 106.0 L486.7 218.7"/><path d="M440.0 106.0 L440.0 238.0"/><path d="M440.0 106.0 L393.3 218.7"/><path d="M440.0 106.0 L374.0 172.0"/><path d="M440.0 106.0 L393.3 125.3"/><path d="M486.7 125.3 L506.0 172.0"/><path d="M486.7 125.3 L486.7 218.7"/><path d="M486.7 125.3 L440.0 238.0"/><path d="M486.7 125.3 L393.3 218.7"/><path d="M486.7 125.3 L374.0 172.0"/><path d="M486.7 125.3 L393.3 125.3"/><path d="M506.0 172.0 L486.7 218.7"/><path d="M506.0 172.0 L440.0 238.0"/><path d="M506.0 172.0 L393.3 218.7"/><path d="M506.0 172.0 L374.0 172.0"/><path d="M506.0 172.0 L393.3 125.3"/><path d="M486.7 218.7 L440.0 238.0"/><path d="M486.7 218.7 L393.3 218.7"/><path d="M486.7 218.7 L374.0 172.0"/><path d="M486.7 218.7 L393.3 125.3"/><path d="M440.0 238.0 L393.3 218.7"/><path d="M440.0 238.0 L374.0 172.0"/><path d="M440.0 238.0 L393.3 125.3"/><path d="M393.3 218.7 L374.0 172.0"/><path d="M393.3 218.7 L393.3 125.3"/><path d="M374.0 172.0 L393.3 125.3"/></g>
    <g fill="none" stroke="#0fa07f" stroke-width="1.6" opacity="0.85"><path d="M730.0 106.0 L776.7 125.3"/><path d="M730.0 106.0 L730.0 238.0"/><path d="M776.7 125.3 L796.0 172.0"/><path d="M683.3 125.3 L776.7 125.3"/><path d="M796.0 172.0 L776.7 218.7"/><path d="M664.0 172.0 L796.0 172.0"/><path d="M776.7 218.7 L730.0 238.0"/><path d="M683.3 218.7 L776.7 218.7"/><path d="M683.3 218.7 L730.0 238.0"/><path d="M664.0 172.0 L683.3 218.7"/><path d="M664.0 172.0 L683.3 125.3"/><path d="M683.3 125.3 L730.0 106.0"/></g>
    <circle cx="150.0" cy="114.0" r="7" fill="#3553ff" fill-opacity="0.9" stroke="#3553ff" stroke-width="1.5"/><circle cx="208.0" cy="172.0" r="7" fill="#3553ff" fill-opacity="0.9" stroke="#3553ff" stroke-width="1.5"/><circle cx="150.0" cy="230.0" r="7" fill="#3553ff" fill-opacity="0.9" stroke="#3553ff" stroke-width="1.5"/><circle cx="92.0" cy="172.0" r="7" fill="#3553ff" fill-opacity="0.9" stroke="#3553ff" stroke-width="1.5"/><circle cx="440.0" cy="106.0" r="7" fill="#3553ff" fill-opacity="0.9" stroke="#3553ff" stroke-width="1.5"/><circle cx="486.7" cy="125.3" r="7" fill="#3553ff" fill-opacity="0.9" stroke="#3553ff" stroke-width="1.5"/><circle cx="506.0" cy="172.0" r="7" fill="#3553ff" fill-opacity="0.9" stroke="#3553ff" stroke-width="1.5"/><circle cx="486.7" cy="218.7" r="7" fill="#3553ff" fill-opacity="0.9" stroke="#3553ff" stroke-width="1.5"/><circle cx="440.0" cy="238.0" r="7" fill="#3553ff" fill-opacity="0.9" stroke="#3553ff" stroke-width="1.5"/><circle cx="393.3" cy="218.7" r="7" fill="#3553ff" fill-opacity="0.9" stroke="#3553ff" stroke-width="1.5"/><circle cx="374.0" cy="172.0" r="7" fill="#3553ff" fill-opacity="0.9" stroke="#3553ff" stroke-width="1.5"/><circle cx="393.3" cy="125.3" r="7" fill="#3553ff" fill-opacity="0.9" stroke="#3553ff" stroke-width="1.5"/><circle cx="730.0" cy="106.0" r="7" fill="#3553ff" fill-opacity="0.9" stroke="#3553ff" stroke-width="1.5"/><circle cx="776.7" cy="125.3" r="7" fill="#3553ff" fill-opacity="0.9" stroke="#3553ff" stroke-width="1.5"/><circle cx="796.0" cy="172.0" r="7" fill="#3553ff" fill-opacity="0.9" stroke="#3553ff" stroke-width="1.5"/><circle cx="776.7" cy="218.7" r="7" fill="#3553ff" fill-opacity="0.9" stroke="#3553ff" stroke-width="1.5"/><circle cx="730.0" cy="238.0" r="7" fill="#3553ff" fill-opacity="0.9" stroke="#3553ff" stroke-width="1.5"/><circle cx="683.3" cy="218.7" r="7" fill="#3553ff" fill-opacity="0.9" stroke="#3553ff" stroke-width="1.5"/><circle cx="664.0" cy="172.0" r="7" fill="#3553ff" fill-opacity="0.9" stroke="#3553ff" stroke-width="1.5"/><circle cx="683.3" cy="125.3" r="7" fill="#3553ff" fill-opacity="0.9" stroke="#3553ff" stroke-width="1.5"/>

    <g fill="currentColor" text-anchor="middle">
      <text x="150" y="272" font-size="12" font-weight="700">N = 4, all-to-all</text><text x="150" y="292" font-size="10.5" opacity="0.9">pairs = 4x3/2 = 6</text><text x="150" y="308" font-size="10.5" opacity="0.9">exchanges = 4x3 = 12</text><text x="440" y="272" font-size="12" font-weight="700" fill="#d64545">N = 8, all-to-all</text><text x="440" y="292" font-size="10.5" opacity="0.9">pairs = 8x7/2 = 28</text>
      <text x="440" y="308" font-size="10.5" opacity="0.9">exchanges = 8x7 = 56</text><text x="730" y="272" font-size="12" font-weight="700" fill="#0fa07f">N = 8, fanout 3</text><text x="730" y="292" font-size="10.5" opacity="0.9">pairs = 8x3/2 = 12</text><text x="730" y="308" font-size="10.5" opacity="0.9">exchanges = 8x3 = 24</text>
    </g>
    <text x="295" y="180" font-size="11" font-weight="700" fill="#d64545" text-anchor="middle">2x the nodes</text><text x="295" y="196" font-size="11" font-weight="700" fill="#d64545" text-anchor="middle">4.7x the pairs</text><text x="585" y="180" font-size="11" font-weight="700" fill="#0fa07f" text-anchor="middle">same nodes</text><text x="585" y="196" font-size="11" font-weight="700" fill="#0fa07f" text-anchor="middle">2.3x fewer pairs</text>

    <g fill="none" stroke-width="1.8">
      <rect x="60" y="332" width="760" height="76" rx="10" fill="#7f7f7f" fill-opacity="0.07" stroke="currentColor" stroke-opacity="0.4"/>
    </g>
    <g fill="currentColor" font-size="10.5">
      <text x="78" y="352" font-size="9" font-weight="700" opacity="0.65">N</text>
      <text x="196" y="352" font-size="9" font-weight="700" opacity="0.65">4</text><text x="290" y="352" font-size="9" font-weight="700" opacity="0.65">8</text><text x="384" y="352" font-size="9" font-weight="700" opacity="0.65">16</text><text x="478" y="352" font-size="9" font-weight="700" opacity="0.65">32</text><text x="572" y="352" font-size="9" font-weight="700" opacity="0.65">64</text><text x="666" y="352" font-size="9" font-weight="700" opacity="0.65">128</text><text x="760" y="352" font-size="9" font-weight="700" opacity="0.65">256</text>
      <text x="78" y="374" font-size="10" fill="#d64545" font-weight="700">all-to-all pairs</text><text x="196" y="374" fill="#d64545">6</text><text x="290" y="374" fill="#d64545">28</text><text x="384" y="374" fill="#d64545">120</text><text x="478" y="374" fill="#d64545">496</text><text x="572" y="374" fill="#d64545">2,016</text><text x="666" y="374" fill="#d64545">8,128</text><text x="760" y="374" fill="#d64545">32,640</text>
      <text x="78" y="396" font-size="10" fill="#0fa07f" font-weight="700">fanout 3 pairs</text><text x="196" y="396" fill="#0fa07f">6</text><text x="290" y="396" fill="#0fa07f">12</text><text x="384" y="396" fill="#0fa07f">24</text><text x="478" y="396" fill="#0fa07f">48</text><text x="572" y="396" fill="#0fa07f">96</text><text x="666" y="396" fill="#0fa07f">192</text><text x="760" y="396" fill="#0fa07f">384</text>
    </g>
    <text x="440" y="430" font-size="11" text-anchor="middle" fill="currentColor" opacity="0.9">N(N−1)/2 is the whole coherency term. Cap each node's peers and the same count becomes 3N/2 — a line, not a parabola.</text>
  </g>
</svg>
```

Read the bottom table across. Going from 4 nodes to 8 doubles the machines and multiplies the pairs by **4.7** (6 → 28). Going from 32 to 64 doubles the machines and multiplies the pairs by **4.1** (496 → 2,016). At 256 nodes there are **32,640** pairs. If each pair costs you even a microsecond of somebody's time, you are now spending 33 milliseconds per round on nothing but nodes telling each other what they know.

That is the difference between the two terms, and it is worth saying in one line:

> **σ is a cost you pay once per machine. κ is a cost you pay once per pair of machines.** The first divides your gains. The second eventually exceeds them.

### Where the peak is, and how to find it by hand

Because the κ term grows faster than the numerator, `C(N)` must eventually turn over. You can find exactly where with school calculus. Write the denominator as `D(N)`:

```text
D(N)  =  1 + σ(N − 1) + κN(N − 1)  =  (1 − σ) + σN + κN² − κN
D'(N) =  σ + 2κN − κ
```

`C = N/D` is at a maximum when `D − N·D' = 0`:

```text
(1 − σ) + σN + κN² − κN  −  N(σ + 2κN − κ)  =  0
(1 − σ) + σN + κN² − κN  −  σN − 2κN² + κN  =  0
(1 − σ) − κN²                                =  0
```

which leaves the one formula to carry out of this lesson:

```text
N*  =  sqrt( (1 − σ) / κ )                    the peak
```

Work it with **σ = 0.05 and κ = 0.001** — the numbers section 1 of the code prints:

```text
N*    = sqrt(0.95 / 0.001) = sqrt(950) = 30.8

C(31) = 31 / (1 + 0.05×30 + 0.001×31×30)
      = 31 / (1 + 1.5 + 0.93)  =  31 / 3.43  =  9.04

C(62) = 62 / (1 + 0.05×61 + 0.001×62×61)
      = 62 / (1 + 3.05 + 3.782) = 62 / 7.832 =  7.92     ← −12.4% for 2× the machines

C(100)= 100 / (1 + 4.95 + 9.9)  = 100 / 15.85 =  6.31
```

Three things fall out of those four lines, and each is worth its own sentence. **First**, a κ of 0.001 — one part in a thousand — caps you at 9.04× no matter what you spend. **Second**, the Amdahl ceiling for the same σ is `1/0.05 = 20×`, so a model without the κ term would tell you there is another 2.2× available if you keep buying, which there is not. **Third**, at N = 100 you are down to **6.31×** — you are spending on a hundred machines to get less than you got from thirty-one.

And the number that matters operationally: **κ = 0.001 is a small number.** If you cannot name a coordination cost in your system that is one part in a thousand of a request, you are not looking hard enough. The next section is a list of places it hides.

### Retrograde scaling, and how to recognise it at 3 a.m.

Past `N*`, `C(N)` decreases. This is called **retrograde scaling** and it is the only part of capacity planning that is genuinely counter-intuitive, because it inverts the sign of the action you have spent your whole career taking.

Here is the measured version, from the code in this lesson — a simulated fleet, its throughput sampled at 16 fleet sizes and three seeds each, with the fitted USL curve drawn through the points:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 470" width="100%" style="max-width:840px" role="img" aria-label="Three capacity models plotted against fleet size N from 1 to 64. The linear model runs off the top of the chart. Amdahl's Law with sigma 0.0247 rises steeply and also leaves the top of the chart, heading for a ceiling of 41 times. The fitted Universal Scalability Law curve rises to a peak of 11.06 times at N equals 29.2 and then falls away to 8.93 times at N equals 64. Sixteen measured simulation points sit on the USL curve, peaking at 10.96 times at N equals 32. The region to the right of N star is shaded red and labelled retrograde.">
  <defs>
    <marker id="p11-02-a1" markerWidth="10" markerHeight="10" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker>
  </defs>
  <text x="440" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">Amdahl says you plateau. The measurements say you go backwards.</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <rect x="414" y="62" width="386" height="278" fill="#d64545" fill-opacity="0.09"/>
    <g fill="none" stroke="currentColor" stroke-width="1.5">
      <path d="M90 340 L 800 340"/><path d="M90 340 L 90 62"/>
    </g>
    <g fill="none" stroke="currentColor" stroke-width="1.1" opacity="0.4">
      <path d="M178.8 340 L 178.8 345"/><path d="M267.5 340 L 267.5 345"/><path d="M356.3 340 L 356.3 345"/><path d="M445 340 L 445 345"/><path d="M533.8 340 L 533.8 345"/><path d="M622.5 340 L 622.5 345"/><path d="M711.2 340 L 711.2 345"/><path d="M800 340 L 800 345"/>
      <path d="M85 300.3 L 90 300.3"/><path d="M85 260.6 L 90 260.6"/><path d="M85 220.9 L 90 220.9"/><path d="M85 181.1 L 90 181.1"/><path d="M85 141.4 L 90 141.4"/><path d="M85 101.7 L 90 101.7"/><path d="M85 62 L 90 62"/>
    </g>

    <path d="M90 340 L 245.3 62" fill="none" stroke="#7f7f7f" stroke-width="2.2" stroke-dasharray="3 4"/>
    <path d="M101.1 320.1 L 134.4 266 L 178.8 204.6 L 223.1 152.6 L 267.5 108.3 L 311.9 69.7 L 321.5 62" fill="none" stroke="#e0930f" stroke-width="2.4" stroke-linejoin="round"/>
    <path d="M101.1 320.1 L 112.2 301.3 L 134.4 267 L 156.6 237.1 L 178.8 211.6 L 223.1 172.5 L 267.5 140.2 L 311.9 131.4 L 356.3 123.3 L 411.7 120.3 L 445 120.8 L 489.4 123.8 L 533.8 128 L 622.5 138.9 L 711.2 150.9 L 800 162.6" fill="none" stroke="#0fa07f" stroke-width="2.8" stroke-linejoin="round"/>

    <g fill="#3553ff" fill-opacity="0.4" stroke="#3553ff" stroke-width="1.5">
      <circle cx="101.1" cy="320.1" r="4"/><circle cx="112.2" cy="301.1" r="4"/><circle cx="134.4" cy="265.3" r="4"/><circle cx="156.6" cy="233.9" r="4"/><circle cx="178.8" cy="208.7" r="4"/><circle cx="223.1" cy="168.4" r="4"/><circle cx="267.5" cy="144.8" r="4"/><circle cx="311.9" cy="130.7" r="4"/>
      <circle cx="356.3" cy="126.9" r="4"/><circle cx="400.6" cy="123.2" r="4"/><circle cx="445" cy="122.4" r="4"/><circle cx="489.4" cy="124.2" r="4"/><circle cx="533.8" cy="129.3" r="4"/><circle cx="622.5" cy="137.8" r="4"/><circle cx="711.2" cy="148.6" r="4"/><circle cx="800" cy="161.1" r="4"/>
    </g>

    <path d="M414 340 L 414 108" fill="none" stroke="#d64545" stroke-width="1.8" stroke-dasharray="6 4"/>
    <circle cx="445" cy="122.4" r="9" fill="none" stroke="#d64545" stroke-width="2"/>
    <path d="M498 164 L 456 132" fill="none" stroke="#d64545" stroke-width="1.4" marker-end="url(#p11-02-a1)"/>

    <g fill="currentColor">
      <text x="90" y="359" font-size="9.5" text-anchor="middle" opacity="0.7">0</text><text x="178.8" y="359" font-size="9.5" text-anchor="middle" opacity="0.7">8</text><text x="267.5" y="359" font-size="9.5" text-anchor="middle" opacity="0.7">16</text><text x="356.3" y="359" font-size="9.5" text-anchor="middle" opacity="0.7">24</text><text x="445" y="359" font-size="9.5" text-anchor="middle" opacity="0.7">32</text>
      <text x="533.8" y="359" font-size="9.5" text-anchor="middle" opacity="0.7">40</text><text x="622.5" y="359" font-size="9.5" text-anchor="middle" opacity="0.7">48</text><text x="711.2" y="359" font-size="9.5" text-anchor="middle" opacity="0.7">56</text><text x="800" y="359" font-size="9.5" text-anchor="middle" opacity="0.7">64</text>
      <text x="78" y="344" font-size="9.5" text-anchor="end" opacity="0.7">0</text><text x="78" y="304" font-size="9.5" text-anchor="end" opacity="0.7">2x</text><text x="78" y="264" font-size="9.5" text-anchor="end" opacity="0.7">4x</text><text x="78" y="225" font-size="9.5" text-anchor="end" opacity="0.7">6x</text><text x="78" y="185" font-size="9.5" text-anchor="end" opacity="0.7">8x</text><text x="78" y="145" font-size="9.5" text-anchor="end" opacity="0.7">10x</text><text x="78" y="105" font-size="9.5" text-anchor="end" opacity="0.7">12x</text><text x="78" y="66" font-size="9.5" text-anchor="end" opacity="0.7">14x</text>
      <text x="445" y="378" font-size="10.5" text-anchor="middle" opacity="0.85">N — machines in the fleet</text><text x="26" y="201" font-size="10.5" opacity="0.85" transform="rotate(-90 26 201)" text-anchor="middle">C(N) = X(N) / X(1)</text>
    </g>

    <g fill="currentColor">
      <text x="800" y="76" font-size="9" fill="#7f7f7f" text-anchor="end" font-weight="700">linear — 64x at N=64, off the top of this chart</text><text x="800" y="92" font-size="9" fill="#e0930f" text-anchor="end" font-weight="700">Amdahl only — 25.0x at N=64, ceiling 41x, never turns down</text><text x="504" y="176" font-size="10" font-weight="700" fill="#d64545">measured peak: N=32, 10.96x, 101.9 req/s</text>
      <text x="420" y="332" font-size="9.5" font-weight="700" fill="#d64545">N* = 29.2 (fitted)</text><text x="620" y="200" font-size="11.5" font-weight="700" fill="#d64545" text-anchor="middle">RETROGRADE</text><text x="620" y="216" font-size="9.5" fill="#d64545" text-anchor="middle" opacity="0.95">every machine you add here</text><text x="620" y="229" font-size="9.5" fill="#d64545" text-anchor="middle" opacity="0.95">subtracts throughput</text>
      <text x="640" y="300" font-size="9.5" opacity="0.9">N=64 delivers 83.7 req/s</text><text x="640" y="313" font-size="9.5" opacity="0.9">against 101.9 req/s at N=32</text><text x="640" y="326" font-size="9.5" font-weight="700" fill="#d64545">2x the bill, −17.8% throughput</text>
    </g>

    <g font-size="10.5">
      <path d="M100 396 L 128 396" fill="none" stroke="#7f7f7f" stroke-width="2.2" stroke-dasharray="3 4"/><text x="136" y="400" fill="currentColor">linear  C(N) = N</text>
      <path d="M290 396 L 318 396" fill="none" stroke="#e0930f" stroke-width="2.4"/><text x="326" y="400" fill="currentColor">Amdahl  N / (1 + σ(N−1))</text>
      <path d="M100 420 L 128 420" fill="none" stroke="#0fa07f" stroke-width="2.8"/><text x="136" y="424" fill="currentColor">USL fit  N / (1 + σ(N−1) + κN(N−1)),  σ = 0.0247  κ = 0.001144</text>
      <circle cx="114" cy="440" r="4" fill="#3553ff" fill-opacity="0.4" stroke="#3553ff" stroke-width="1.5"/><text x="136" y="444" fill="currentColor">measured — 16 concurrency levels × 3 seeds; worst point 3.0% off the fit</text>
    </g>
    <text x="440" y="464" font-size="11" text-anchor="middle" fill="currentColor" opacity="0.9">Same σ in both curves. Amdahl promises 41x and never turns down; adding κ predicts the peak to within 9%.</text>
  </g>
</svg>
```

The two curves share the **same σ**. The only difference between the amber line and the green one is a κ of 0.001144, and it is the difference between "you can reach 41× if you keep buying" and "you peaked at 10.96× and everything after this is worse."

Retrograde scaling has a symptom set, and it is specific enough to diagnose from a dashboard:

1. **Throughput falls while you add capacity.** The headline symptom, and the one nobody believes on the first read.
2. **Per-instance utilization falls at the same time.** This is the discriminator. In a σ-limited system the shared resource pins at 100% and stays there. In a κ-limited system the shared resource gets *less* busy as you scale out — the measured run below goes from **80.5% busy at the peak to 67.4% at twice the fleet**, with lower throughput at the second number. Every instance is under-used and the system is slower. That combination has exactly one cause.
3. **Latency rises with no queue you can find.** The time goes into coordination, spread thinly across every node instead of piling up in one visible place.
4. **Rolling back the scale-up fixes it**, within one deploy. If scaling in restores throughput you were past `N*`, and no other explanation fits.
5. **Nothing is erroring.** No stack trace, no saturation alarm, no bad deploy — Phase 9's RED and USE dashboards are all green, because none of them plot throughput against fleet size.

That last point is the trap. **The relationship this lesson is about — throughput as a function of N — is not on anybody's dashboard.** You have throughput over time and you have instance count over time, on separate panels, usually on separate screens. Plotting one against the other is a thing you have to decide to do.

### Fitting the model to your own data

The formula is worthless until it has your numbers in it. Fitting is the practical skill, and it is easier than it sounds because there are only two free parameters.

Run a **concurrency sweep**: hold everything else fixed, vary N, and measure steady-state throughput at each level. You get a table of `(N, X(N))`. Normalise by `X(1)` to get `C(N)`, then search for the (σ, κ) pair that minimises the sum of squared errors between `X(1) × C_USL(N)` and your measurements. Two parameters over a bounded, well-behaved surface means **a grid search is completely adequate** — the code in this lesson does four passes of a 121 × 121 grid, each pass narrowing the bounds around the previous winner. No solver, no library, nothing to misconfigure, and you can see exactly what it searched.

Two requirements on the *data*, and they are where fits actually fail:

**You need at least six points, and they must straddle the knee.** If every point you measured is on the rising side, there is a whole family of (σ, κ) pairs that fit them beautifully and disagree wildly about where the peak is. The code demonstrates this rather than asserting it: fitting only the points at N ≤ 16 produces σ = 0.0163 and κ = 0.001599, **fits all seven points**, and then predicts 70.2 req/s at N = 64 where the truth is 83.7 — **off by 16%**. A fit that never sampled past the knee cannot tell you where the knee is. Sample well past where you think your peak is, including sizes you would never run in production. That is the entire point of the exercise.

**Each point must be steady state, not a ramp.** Discard the warm-up, run each level long enough that queues settle, and repeat each level on more than one run — the code averages three seeds per level for exactly this reason. Phase 8's [Benchmarking & Load Testing](../../08-concurrency-and-performance/14-benchmarking-and-load-testing/) covers how to run a load test whose numbers mean anything, including the coordinated-omission trap that makes an open-loop generator lie to you about latency during exactly the overload you are trying to measure. Do not re-derive that here; go and get the methodology, then come back and sweep.

One honest caveat about σ, because it will bite you and the code makes it visible. **You cannot read σ off your source code.** The simulated system's serial section is 8 ms out of a 108 ms request — a serial *demand fraction* of 0.0741 — but the fit recovers σ = 0.0247. Both numbers are correct and they mean different things. The demand fraction is Amdahl's worst case and it correctly predicts the **ceiling**: with coordination switched off, the same system tops out at **13.8×** against the `1/0.0741 = 13.5×` the fraction predicts. The fitted σ is what that serialization actually *costs* you at the concurrency levels you ran. Meanwhile κ, which has no such ambiguity, is recovered to within **17.6%** of the value the mechanism charges. The lesson: measure the curve, do not compute it from a code review.

### What each term costs you, and how to attack it

The two terms fail differently, are diagnosed differently, and are fixed differently:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 506" width="100%" style="max-width:840px" role="img" aria-label="A two-column diagnostic. The shared symptom at the top is that adding machines did not add throughput. The left column covers a dominant sigma term: the throughput curve flattens and stays flat, the shared resource pins at one hundred percent utilization, the cause is one database or leader or lock, and the attack is sharding or read replicas. The right column covers a dominant kappa term: the curve peaks and falls, the shared resource gets LESS busy as you add machines, the cause is all-to-all chatter such as connection fan-out or cache invalidation broadcast, and the attack is subsetting, cells and hierarchy. The discriminating question is whether the curve past the knee is flat or falling.">
  <text x="440" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">Past the knee: is the curve FLAT, or is it FALLING? That is the whole diagnosis.</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <rect x="40" y="42" width="800" height="38" rx="9" fill="#e0930f" fill-opacity="0.13" stroke="#e0930f" stroke-width="1.8"/>
    <text x="440" y="60" font-size="11" font-weight="700" text-anchor="middle" fill="#e0930f">SYMPTOM — you grew the fleet and throughput did not grow with it</text><text x="440" y="74" font-size="9.5" text-anchor="middle" fill="currentColor" opacity="0.9">every instance is healthy · error rate 0.00% · CPU per instance is DOWN · nothing to roll back</text>

    <rect x="40" y="94" width="385" height="366" rx="11" fill="#e0930f" fill-opacity="0.09" stroke="#e0930f" stroke-width="1.8"/>
    <rect x="455" y="94" width="385" height="366" rx="11" fill="#d64545" fill-opacity="0.09" stroke="#d64545" stroke-width="1.8"/>

    <text x="232" y="118" font-size="12.5" font-weight="700" text-anchor="middle" fill="#e0930f">σ DOMINANT — one thing is serialized</text><text x="647" y="118" font-size="12.5" font-weight="700" text-anchor="middle" fill="#d64545">κ DOMINANT — everything talks to everything</text>

    <g fill="none" stroke="currentColor" stroke-width="1.2" opacity="0.45">
      <path d="M70 212 L 400 212"/><path d="M70 212 L 70 138"/><path d="M485 212 L 815 212"/><path d="M485 212 L 485 138"/>
    </g>
    <path d="M70 208 L 100 180 L 130 164 L 170 154 L 220 150 L 290 149 L 400 149" fill="none" stroke="#e0930f" stroke-width="2.6" stroke-linejoin="round"/>
    <path d="M485 208 L 515 180 L 545 164 L 585 152 L 630 148 L 680 152 L 740 164 L 815 182" fill="none" stroke="#d64545" stroke-width="2.6" stroke-linejoin="round"/>
    <path d="M70 143 L 282 143" fill="none" stroke="#e0930f" stroke-width="1.1" stroke-dasharray="4 4" opacity="0.8"/>
    <g fill="currentColor">
      <text x="290" y="140" font-size="9" fill="#e0930f" font-weight="700">ceiling = 1/σ</text><text x="410" y="167" font-size="9.5" text-anchor="end" opacity="0.85">flat forever</text><text x="700" y="200" font-size="9.5" fill="#d64545" font-weight="700">and DOWN</text><text x="76" y="226" font-size="9" opacity="0.6">N —&gt;</text><text x="491" y="226" font-size="9" opacity="0.6">N —&gt;</text>
    </g>

    <g stroke="currentColor" stroke-opacity="0.35" stroke-width="1"><path d="M56 238 L 409 238"/><path d="M471 238 L 824 238"/><path d="M56 318 L 409 318"/><path d="M471 318 L 824 318"/><path d="M56 386 L 409 386"/><path d="M471 386 L 824 386"/></g>

    <g fill="currentColor">
      <text x="56" y="254" font-size="9" font-weight="700" opacity="0.65">THE SECOND DIAGNOSTIC</text><text x="56" y="270" font-size="9.5" opacity="0.95">the shared resource climbs toward 100% busy and</text><text x="56" y="284" font-size="9.5" opacity="0.95">pins there. Latency at that one hop rises. Total</text><text x="56" y="298" font-size="9.5" opacity="0.95">throughput is flat; per-node throughput falls.</text>
      <text x="56" y="312" font-size="9.5" font-weight="700" fill="#e0930f">removing machines changes nothing.</text>

      <text x="471" y="254" font-size="9" font-weight="700" opacity="0.65">THE SECOND DIAGNOSTIC</text><text x="471" y="270" font-size="9.5" opacity="0.95">the shared resource gets LESS busy as you add</text><text x="471" y="284" font-size="9.5" opacity="0.95">machines — measured here: 80.5% busy at the peak,</text><text x="471" y="298" font-size="9.5" opacity="0.95">67.4% at 2x the fleet, with lower throughput.</text>
      <text x="471" y="312" font-size="9.5" font-weight="700" fill="#d64545">removing machines FIXES it. +21.7%, measured.</text>

      <text x="56" y="334" font-size="9" font-weight="700" opacity="0.65">WHERE IT LIVES</text><text x="56" y="350" font-size="9.5" opacity="0.95">one primary database · one leader · one lock ·</text><text x="56" y="364" font-size="9.5" opacity="0.95">one queue · one sequence · the config service</text><text x="56" y="378" font-size="9.5" opacity="0.95">every instance reads at startup</text>

      <text x="471" y="334" font-size="9" font-weight="700" opacity="0.65">WHERE IT LIVES</text><text x="471" y="350" font-size="9.5" opacity="0.95">N instances x M replicas of connections · cache</text><text x="471" y="364" font-size="9.5" opacity="0.95">invalidation broadcast · full-mesh discovery ·</text><text x="471" y="378" font-size="9.5" opacity="0.95">distributed locks · gossip · election churn</text>

      <text x="56" y="402" font-size="9" font-weight="700" opacity="0.65">THE ATTACK</text><text x="56" y="418" font-size="9.5" opacity="0.95">shard it (L8) · read replicas (L7) · take the</text><text x="56" y="432" font-size="9.5" opacity="0.95">shared step off the hot path · batch so fewer</text><text x="56" y="446" font-size="9.5" opacity="0.95">trips hold it. Measured: σ/2 bought +13.7%.</text>

      <text x="471" y="402" font-size="9" font-weight="700" opacity="0.65">THE ATTACK</text><text x="471" y="418" font-size="9.5" opacity="0.95">subsetting (L5) · cells (L9) · a pooler in front</text><text x="471" y="432" font-size="9.5" opacity="0.95">of the DB · hierarchy instead of broadcast.</text><text x="471" y="446" font-size="9.5" opacity="0.95">Measured: fanout 8 moved N* from 29 to 52.</text>
    </g>

    <text x="440" y="482" font-size="11.5" font-weight="700" text-anchor="middle" fill="currentColor">σ caps you at 1/σ. κ takes throughput back at N* = sqrt((1−σ)/κ). Fix κ first.</text><text x="440" y="499" font-size="11" text-anchor="middle" fill="currentColor" opacity="0.9">A σ problem costs you money. A κ problem costs you the outage, and scaling up is what triggers it.</text>
  </g>
</svg>
```

The asymmetry is worth stating as a rule you can act on: **σ caps you, κ kills you.**

A σ problem is expensive and stable. You buy machines that do nothing and your throughput sits on a plateau, which is a budget problem with an operational disguise. You can live there for years. A κ problem is a *cliff with your fleet size as the coordinate*, and the standard response to load — scale out — is the thing that pushes you over it. Worse, κ problems are self-concealing: they only appear at fleet sizes you have not run yet, so they are invisible right up until the launch, the failover, or the autoscaler that decides at 03:00 to double your instance count.

The lesson's code measures both attacks on the same system. Sharding the serial resource in two **halved σ from 0.0249 to 0.0098** and bought **+13.7%** peak throughput — but the peak stayed at N = 32. Subsetting the coordination graph so each worker talks to 8 peers instead of all N−1 **cut κ from 0.001145 to 0.000360** and pushed `N*` from 29 to **52**. Doing both reached **238.0 req/s at N = 96 and was still climbing**, against a baseline that had fallen to 63.7 by then — **3.7×**.

### Where κ comes from in ordinary systems

None of this is exotic. Every item here is in a boring three-tier service:

- **Connection fan-out.** N application instances each holding a pool of connections to M database replicas is `N × M` connections, and it grows as you scale *either* side. Postgres allocates a backend process per connection; at some count the cost of scheduling and lock-manager contention across those backends exceeds the work they do. This is the single most common κ term in ordinary systems, and it is precisely why connection poolers exist as a product category.
- **Cache invalidation broadcast.** Instance *i* writes a key and tells everyone else to drop it. One write becomes N−1 messages, N writes per second become `N(N−1)` messages per second, and each instance now spends time processing invalidations proportional to the size of the fleet. See [Invalidation & TTLs](../../05-caching/05-invalidation-and-ttls/) for the correctness side; this is the scaling side of the same mechanism.
- **Full-mesh service discovery and health checks.** Every instance of A watching every instance of B, probing in both directions: `N × M` streams, and every deploy of either side re-converges all of them. Innocuous at N = 10; at N = 500 against M = 500 it is 250,000 req/s of pure overhead that produces no user-visible work. Lesson 5 covers the fix.
- **Distributed locks.** A lock is a serial resource (σ) *and* the lease renewal, fencing-token and failure-detection traffic around it is coordination (κ). It contributes to both terms, which is why lock-heavy designs scale so much worse than their authors expect.
- **Leader election churn.** Every membership change makes every node re-evaluate, and larger fleets change membership more often — more deploys, more spot reclaims, more health-check flaps — so the *rate* of coordination rises with N as well as its cost.

Phase 8 Lesson 11 built a circuit breaker inside one process. Notice what the same object becomes here: 300 breakers, each independently probing a recovering dependency, are a κ term — the coordination cost of a fleet re-discovering a fact together. What is one state machine at N = 1 is a thundering herd at N = 300, and the mechanism that converts one into the other is exactly the pairwise arithmetic above.

## Build It

[`code/scalability_law.py`](code/scalability_law.py) is five numbered arguments. Standard library only, seeded with `random.Random(7)`, about 13 seconds. The interesting parts:

**The mechanism, not the formula.** Section 2 is the heart of the lesson and the thing that makes it more than an algebra exercise. It is a discrete-event simulation of N workers, each looping over three phases, in which **nothing computes a USL curve** — the curve is what comes out:

```python
while done < warmup + measure:
    t, _, kind, w = heapq.heappop(events)
    if kind == 0:                                   # done working alone
        s = rng.randrange(shards)
        shard_of[w] = s
        if busy[s]:
            waiting[s].append(w)                    # contention, measured
        else:
            busy[s] = True
            d = hold()
            push(t + d, 1, w)
    elif kind == 1:                                 # released the serial resource
        ...
        push(t + round_ms, 2, w)                    # wait out the round
```

The σ term is not a parameter here; it is a **FIFO queue in front of a shared resource**, and the wait a worker experiences is however long the other workers actually made it. The κ term is the `round_ms` delay, and it is computed by counting:

```python
peers = (n - 1) if fanout is None else min(fanout, n - 1)
round_ms = msg * n * peers          # the whole coordination round, in ms
```

`n * peers` is the number of directed exchanges the medium has to carry — `N(N−1)` when everyone talks to everyone, which is twice the `N(N−1)/2` pairs, once in each direction. Set `fanout` to a constant and the same line produces `n * 8`, which is **linear in N**. That one substitution is the entire subsetting result in section 5.

**The fit is a grid, deliberately.** Two parameters, a bounded surface, and four narrowing passes:

```python
for _ in range(passes):
    ds, dk = (s_hi - s_lo) / steps, (k_hi - k_lo) / steps
    best = (1e18, 0.0, 0.0)
    for i in range(steps + 1):
        s = s_lo + i * ds
        for j in range(steps + 1):
            k = k_lo + j * dk
            err = 0.0
            for n, x in meas.items():
                err += (x1 * usl(n, s, k) - x) ** 2
            if err < best[0]:
                best = (err, s, k)
    _, s, k = best
    s_lo, s_hi = max(0.0, s - 2 * ds), s + 2 * ds
    k_lo, k_hi = max(0.0, k - 2 * dk), k + 2 * dk
```

There is no reason to reach for an optimiser. You can read this, you can see the search bounds, and you can tell at a glance whether the answer sits on a boundary — which is the one failure mode a grid search has and the one an opaque solver hides from you.

Run it:

```bash
docker compose exec -T app python \
  phases/11-scalability-and-reliability/02-universal-scalability-law/code/scalability_law.py
```

```console
== 1 · THREE MODELS OF WHAT N MACHINES BUY YOU ==
  sigma = 0.05  (5% of the work is serialized)
  kappa = 0.001  (every PAIR of nodes costs a little coordination)
  Amdahl ceiling 1/sigma = 20x     USL peak N* = sqrt((1-sigma)/kappa) = 30.8

       N     linear      Amdahl         USL    USL/linear   marginal gain
       1       1.00        1.00        1.00       100.0%
       2       2.00        1.90        1.90        95.1%        +0.901/node
       8       8.00        5.93        5.69        71.1%        +0.562/node
      16      16.00        9.14        8.04        50.3%        +0.226/node
      28      28.00       11.91        9.01        32.2%        +0.033/node
      31      31.00       12.40        9.04        29.2%        +0.008/node
      32      32.00       12.55        9.03        28.2%        -0.003/node
      64      64.00       15.42        7.82        12.2%        -0.047/node

  at N=100 Amdahl says 16.81x and the USL says 6.31x.
  the USL peaks at N=30.8 with 9.04x, then goes DOWN:
    N=31 -> 9.04x    N=62 -> 7.92x (-12.4% for 2x the machines)
  the marginal-gain column is the one to read: it goes negative at N=31.

== 2 · A SYSTEM WHOSE CURVE NOBODY CHOSE ==
  N workers. Each request = 100 ms alone + 8 ms holding ONE shared
  serial resource (bursty, CV^2 ~ 5) + a coordination round in which the
  medium must carry every directed exchange at 0.15 ms each.
  Nothing below is computed from the USL. It is what the simulation did.

       N   throughput    C(N)=X(N)/X(1)   per-node    serial busy   pair exchanges
       1       9.3/s           1.00x      9.29/s          7.5%              0
       4      34.9/s           3.76x      8.73/s         28.0%             12
       8      61.4/s           6.61x      7.68/s         49.7%             56
      16      91.3/s           9.83x      5.71/s         72.5%            240
      24      99.7/s          10.73x      4.15/s         80.3%            552
      28     101.5/s          10.92x      3.63/s         81.1%            756
      32     101.9/s          10.96x      3.18/s         80.5%            992
      40      98.5/s          10.61x      2.46/s         79.1%          1,560
      48      94.6/s          10.18x      1.97/s         75.5%          2,256
      64      83.7/s           9.01x      1.31/s         67.4%          4,032

  one worker does 9.3 req/s with the serial resource 7.5% busy.
  measured peak: N=32 at 101.9 req/s (10.96x).
  N=64 does 83.7 req/s -- -17.8% against N=32,
  with per-node throughput down from 3.18/s to 1.31/s
  and the serial resource 67.4% busy against 80.5% at the peak --
  LESS contended, and slower. Every worker is healthy. Nothing errored.

== 3 · FITTING SIGMA AND KAPPA TO THE MEASUREMENTS ==
  16 concurrency levels x 3 seeds, N = 1..64, both sides of the knee.

              fitted    from the mechanism
    sigma      0.0247      0.0741    serial ms / total ms -- an UPPER bound
    kappa    0.001144    0.001389    one exchange / total ms -- exact
    kappa recovered to within 17.6% of what the mechanism charges.

  control: the SAME system with the coordination round switched off (msg=0).
    it rises to 13.8x (peak N=36) and NEVER turns down.
    the serial fraction 0.0741 predicts a ceiling of 1/sigma = 13.5x; measured 13.8x.
    an Amdahl-only fit (kappa pinned to 0) gives sigma = 0.0491.
    so: the number you can read off the code gives you the CEILING. It does
    not give you the curve, and nothing about it gives you a peak.

       N   measured    USL fit    error       linear      Amdahl-only
       1       9.3/s      9.3/s   +0.0%        9.3/s        9.3/s
       8      61.4/s     60.1/s   -2.2%       74.3/s       63.4/s
      16      91.3/s     90.4/s   -1.0%      148.7/s      108.5/s
      24      99.7/s    101.4/s   +1.7%      223.0/s      142.3/s
      32     101.9/s    102.5/s   +0.7%      297.3/s      168.5/s
      48      94.6/s     94.1/s   -0.6%      446.0/s      206.6/s
      64      83.7/s     83.0/s   -0.9%      594.6/s      232.9/s

  worst point off by 3.0%.
  predicted peak N* = sqrt((1-0.0247)/0.001144) = 29.2
  measured peak     = N=32   -> the model found the peak to within 9%.
  Amdahl alone would predict a ceiling of 1/sigma = 41x and tell you
  to keep buying. The system actually peaks at 10.96x.

  the same fit, using ONLY the points below the knee (N <= 16):
    sigma = 0.0163   kappa = 0.001599   N* = 25
    it predicts 70.2 req/s at N=64; the truth is 83.7 -- off by 16%.
    seven points, all on the rising side, and every one of them fits. A fit
    that never sampled past the knee cannot tell you where the knee is.

== 4 · RETROGRADE: THE FIX IS TO REMOVE MACHINES ==
  you are running N=32 and you need more throughput. You double the fleet.

       N   throughput   vs N=32   per-node   $/req (relative)   verdict
      32     101.9/s    +0.0%     3.18/s            1.00x   the peak
      48      94.6/s    -7.1%     1.97/s            1.61x   worse
      64      83.7/s   -17.8%     1.31/s            2.43x   worse

  64 machines cost 2x and deliver -17.8%. Per request you are
  paying 2.43x what you paid at N=32.

  now the incident-response version -- you are at N=64 and throughput is falling:
      action              N       throughput    change vs now
      (nothing)          64         83.7/s              --
      scale in to 48     48         94.6/s          +13.1%
      scale in to 40     40         98.5/s          +17.8%
      scale in to 32     32        101.9/s          +21.7%

  removing 32 machines recovered +21.7% of throughput and cut the
  bill in half. There is no dashboard on which that is the obvious move.

== 5 · ATTACKING EACH TERM ==
  three changes to the SAME system, measured the same way:
    shard   : two independent serial resources instead of one -> sigma / 2
    subset  : each worker coordinates with 8 peers, not N-1  -> round is LINEAR in N
    both    : shard the serial resource AND subset the coordination graph

       N     baseline        shard         subset          both
       8      61.4/s       64.7/s       61.4/s       64.7/s
      24      99.7/s      115.2/s      115.5/s      148.8/s
      32     101.9/s      115.9/s      125.5/s      172.1/s
      48      94.6/s      103.3/s      125.6/s      204.8/s
      64      83.7/s       88.1/s      123.7/s      220.6/s
      96      63.7/s       64.7/s      124.9/s      238.0/s

    config       sigma      kappa        N*     peak N   peak req/s   vs baseline
    baseline      0.0249   0.001145      29        32      101.9/s        +0.0%
    shard         0.0098   0.001277      28        32      115.9/s       +13.7%
    subset        0.0343   0.000360      52        48      125.6/s       +23.3%
    both          0.0207   0.000089     105        96      238.0/s      +133.7%

  sharding the serial resource cut sigma 0.0249 -> 0.0098 and lifted peak
    throughput +13.7% -- but the peak is still at N=32. Sharding raised the
    ceiling; it did not move the cliff, because the cliff is kappa's.
  subsetting cut kappa 0.001145 -> 0.000360 (69%), which is the whole game:
    at N=96 the baseline does 63.7 req/s and the subset does 124.9 req/s (1.96x).
    coordination round at N=96: 9,120 exchanges all-to-all vs 768 with a fanout of 8 (11.9x less).
    note the subset row's sigma went UP (0.0249 -> 0.0343). Subsetting did not
    delete the coordination cost, it made it LINEAR in N -- and a cost linear in
    N is exactly what the sigma term is. A ceiling you can live with, not a cliff.
  sigma caps you. kappa kills you. Attack them in that order of severity,
  not in the order they are easy.
```

*(The N = 1..64 tables are shown trimmed; the program prints every level.)*

**Section 1** is the three models with nothing measured — pure arithmetic, printed so the divergence is numbers before it is a picture. The column to read is the last one: **marginal gain per node**. It is `+0.901` at N = 2, `+0.226` at N = 16, `+0.008` at N = 31, and **negative from N = 32 onward**. That column is the derivative, and the derivative changing sign is the only event in capacity planning that matters. Notice also that at N = 64 the three models say **64.00×, 15.42× and 7.82×** for the same hardware. Your capacity plan is a bet on which of those three columns you believe.

**Section 2 is the argument.** Sixteen fleet sizes, three seeds each, and a mechanism that has never heard of Gunther. The system rises convincingly through N = 16 (9.83×), decelerates through the twenties, peaks at **N = 32 with 101.9 req/s (10.96×)**, and then comes back down to **83.7 req/s at N = 64**. Now look across the row rather than down the column. At the peak the serial resource is **80.5% busy**; at N = 64 it is **67.4% busy** — *less* contended — and throughput is 17.8% lower. Per-node throughput has collapsed from 3.18/s to 1.31/s. **There is no saturated resource to find.** If your only diagnostic instinct is "look for the thing at 100%", this system will defeat it, because the cost is in the `4,032` pairwise exchanges in the last column, spread evenly across every node so that none of them looks guilty.

**Section 3 is the proof.** The fit recovers σ = 0.0247 and κ = 0.001144, and the residual column shows the fitted curve tracking the measurements with a **worst-case error of 3.0%** across a 64× range of fleet sizes — including the entire retrograde half, which no two-parameter model without a κ term can produce at all. Then `N* = sqrt((1 − 0.0247)/0.001144) = 29.2` against a measured peak of 32: **within 9%**, and the curve is flat enough between 28 and 36 that this is as precise as the question deserves. The control run is the part to dwell on. Switch the coordination round off and the *identical* system rises to 13.8× and **never turns down** — matching the `1/0.0741 = 13.5×` ceiling that its serial fraction predicts. The retrograde region is not the lock. It is the coordination, and only the coordination.

And then the under-sampled fit, which is the honest failure mode. Seven points, all below the knee, all fitted well, producing a model that is **16% wrong at N = 64 and wrong in the direction that buys hardware.** Any fit you do on production data will look like this unless you deliberately measure past where you think the peak is.

**Section 4 is the operational payload.** You are at 32 machines and you need more throughput, so you double. You get **−17.8%**, and your cost per request goes to **2.43×** what it was. Then the table nobody writes: from N = 64, scaling *in* to 48 recovers **+13.1%**, to 40 recovers **+17.8%**, and to 32 recovers **+21.7%** — while halving the bill. Every step of that is a normal deploy. The obstacle is not technical, it is that no runbook in your organisation contains the sentence "throughput is falling, delete half the fleet."

**Section 5 attacks each term and measures what you get.** Sharding the serial resource in two does what sharding does: σ falls **0.0249 → 0.0098** and peak throughput rises **+13.7%** — but `N*` stays at 32, because the position of the peak is set by κ and sharding did not touch κ. **You raised the ceiling and left the cliff exactly where it was.** Subsetting is the other story: κ falls **0.001145 → 0.000360**, `N*` moves from 29 to **52**, and the curve stops falling — at N = 96 the subset configuration delivers **124.9 req/s against the baseline's 63.7 (1.96×)**, because its coordination round is **768 exchanges instead of 9,120**. Do both and you get **238.0 req/s at N = 96, still climbing, with a predicted `N*` of 105** — 3.7× the baseline at the same fleet size:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 470" width="100%" style="max-width:840px" role="img" aria-label="Measured throughput against fleet size for four versions of the same simulated system. The baseline peaks at 101.9 requests per second at N equals 32 and then falls to 63.7 at N equals 96. Sharding the serial resource into two lifts the peak to 115.9 but leaves it at N equals 32. Subsetting the coordination graph to a fanout of 8 flattens the curve at about 125 requests per second and pushes the predicted peak out to N equals 52. Doing both reaches 238.0 requests per second at N equals 96 and is still rising, with a predicted peak at N equals 105.">
  <defs>
    <marker id="p11-02-a4" markerWidth="10" markerHeight="10" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker>
  </defs>
  <text x="440" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">Sharding raises the ceiling. Subsetting moves the cliff. Only one of them scales.</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <g fill="none" stroke="currentColor" stroke-width="1.5"><path d="M90 340 L 800 340"/><path d="M90 340 L 90 62"/></g>
    <g fill="none" stroke="currentColor" stroke-width="1.1" opacity="0.4">
      <path d="M208.3 340 L 208.3 345"/><path d="M326.7 340 L 326.7 345"/><path d="M445 340 L 445 345"/><path d="M563.3 340 L 563.3 345"/><path d="M681.7 340 L 681.7 345"/><path d="M800 340 L 800 345"/>
      <path d="M85 284.4 L 90 284.4"/><path d="M85 228.8 L 90 228.8"/><path d="M85 173.2 L 90 173.2"/><path d="M85 117.6 L 90 117.6"/><path d="M85 62 L 90 62"/>
    </g>

    <path d="M149.2 271.7 L 208.3 238.5 L 267.5 229.2 L 326.7 226.7 L 385.8 230.4 L 445 234.8 L 563.3 246.9 L 681.7 258.5 L 800 269.2" fill="none" stroke="#d64545" stroke-width="2.8" stroke-linejoin="round"/>
    <path d="M149.2 268.1 L 208.3 227 L 267.5 211.9 L 326.7 211.1 L 385.8 216.5 L 445 225.1 L 563.3 242 L 681.7 256.5 L 800 268.1" fill="none" stroke="#e0930f" stroke-width="2.4" stroke-linejoin="round" stroke-dasharray="7 4"/>
    <path d="M149.2 271.7 L 208.3 230.2 L 267.5 211.6 L 326.7 200.4 L 385.8 201.4 L 445 200.3 L 563.3 202.4 L 681.7 202 L 800 201.1" fill="none" stroke="#7c5cff" stroke-width="2.6" stroke-linejoin="round"/>
    <path d="M149.2 268.1 L 208.3 215.2 L 267.5 174.5 L 326.7 148.6 L 385.8 126.7 L 445 112.3 L 563.3 94.7 L 681.7 82.3 L 800 75.4" fill="none" stroke="#0fa07f" stroke-width="3" stroke-linejoin="round"/>

    <g stroke-width="1.5">
      <g fill="#d64545" stroke="#d64545" fill-opacity="0.5"><circle cx="149.2" cy="271.7" r="3.4"/><circle cx="208.3" cy="238.5" r="3.4"/><circle cx="267.5" cy="229.2" r="3.4"/><circle cx="326.7" cy="226.7" r="3.4"/><circle cx="385.8" cy="230.4" r="3.4"/><circle cx="445" cy="234.8" r="3.4"/><circle cx="563.3" cy="246.9" r="3.4"/><circle cx="681.7" cy="258.5" r="3.4"/><circle cx="800" cy="269.2" r="3.4"/></g>
      <g fill="#0fa07f" stroke="#0fa07f" fill-opacity="0.5"><circle cx="149.2" cy="268.1" r="3.4"/><circle cx="208.3" cy="215.2" r="3.4"/><circle cx="267.5" cy="174.5" r="3.4"/><circle cx="326.7" cy="148.6" r="3.4"/><circle cx="385.8" cy="126.7" r="3.4"/><circle cx="445" cy="112.3" r="3.4"/><circle cx="563.3" cy="94.7" r="3.4"/><circle cx="681.7" cy="82.3" r="3.4"/><circle cx="800" cy="75.4" r="3.4"/></g>
    </g>

    <path d="M326.7 226.7 L 326.7 278" fill="none" stroke="#d64545" stroke-width="1.2" stroke-dasharray="4 4" opacity="0.6"/>
    <g fill="none" stroke="currentColor" stroke-width="1.3">
      <path d="M772 80 L 797 80"/><path d="M772 272 L 797 272"/>
      <path d="M772 176 L 772 88" marker-end="url(#p11-02-a4)"/>
      <path d="M772 176 L 772 264" marker-end="url(#p11-02-a4)"/>
    </g>

    <g fill="currentColor">
      <text x="90" y="359" font-size="9.5" text-anchor="middle" opacity="0.7">0</text><text x="208.3" y="359" font-size="9.5" text-anchor="middle" opacity="0.7">16</text><text x="326.7" y="359" font-size="9.5" text-anchor="middle" opacity="0.7">32</text><text x="445" y="359" font-size="9.5" text-anchor="middle" opacity="0.7">48</text><text x="563.3" y="359" font-size="9.5" text-anchor="middle" opacity="0.7">64</text><text x="681.7" y="359" font-size="9.5" text-anchor="middle" opacity="0.7">80</text><text x="800" y="359" font-size="9.5" text-anchor="middle" opacity="0.7">96</text>
      <text x="78" y="344" font-size="9.5" text-anchor="end" opacity="0.7">0</text><text x="78" y="288" font-size="9.5" text-anchor="end" opacity="0.7">50</text><text x="78" y="232" font-size="9.5" text-anchor="end" opacity="0.7">100</text><text x="78" y="177" font-size="9.5" text-anchor="end" opacity="0.7">150</text><text x="78" y="121" font-size="9.5" text-anchor="end" opacity="0.7">200</text><text x="78" y="66" font-size="9.5" text-anchor="end" opacity="0.7">250</text>
      <text x="445" y="378" font-size="10.5" text-anchor="middle" opacity="0.85">N — machines in the fleet</text><text x="26" y="201" font-size="10.5" opacity="0.85" transform="rotate(-90 26 201)" text-anchor="middle">measured throughput (req/s)</text><text x="332" y="272" font-size="9" fill="#d64545" font-weight="700">baseline N* = 29</text><text x="762" y="163" font-size="10" font-weight="700" text-anchor="end">3.7x at N=96</text>
      <text x="762" y="176" font-size="9" text-anchor="end" opacity="0.9">238.0 vs 63.7 req/s</text>
    </g>

    <g fill="currentColor">
      <text x="112" y="290" font-size="10" font-weight="700" fill="#d64545">baseline: peak 101.9 req/s at N=32, then retrograde</text><text x="112" y="304" font-size="10" font-weight="700" fill="#e0930f">shard: peak 115.9 req/s — still at N=32. Higher, not further.</text><text x="112" y="318" font-size="10" font-weight="700" fill="#7c5cff">subset: flat at ~125 req/s, never falls — N* = 52</text>
      <text x="112" y="332" font-size="10" font-weight="700" fill="#0fa07f">both: 238.0 req/s at N=96 and still climbing — N* = 105</text>
    </g>

    <g font-size="10.5">
      <path d="M100 400 L 128 400" fill="none" stroke="#d64545" stroke-width="2.8"/><text x="136" y="404" fill="currentColor">baseline  one serial resource, all-to-all</text>
      <path d="M100 422 L 128 422" fill="none" stroke="#e0930f" stroke-width="2.4" stroke-dasharray="7 4"/><text x="136" y="426" fill="currentColor">shard  two serial resources — attacks σ</text>
      <path d="M470 422 L 498 422" fill="none" stroke="#7c5cff" stroke-width="2.6"/><text x="506" y="426" fill="currentColor">subset  fanout 8 — attacks κ</text>
      <path d="M470 400 L 498 400" fill="none" stroke="#0fa07f" stroke-width="3"/><text x="506" y="404" fill="currentColor">both  σ/2 and fanout 8 together</text>
    </g>
    <text x="440" y="452" font-size="11" text-anchor="middle" fill="currentColor" opacity="0.9">κ fell 0.001145 → 0.000089 (92%). At N=96 the coordination round is 768 exchanges instead of 9,120.</text>
  </g>
</svg>
```

One detail in that table repays attention: **the subset run's fitted σ went *up*, from 0.0249 to 0.0343.** Subsetting did not delete the coordination cost. It converted it from a cost proportional to `N²` into a cost proportional to `N` — and a cost proportional to N *is* the σ term. You traded a cliff for a ceiling. That is the trade you want every time, but it is a trade, not a free lunch, and the fitted parameters are honest about it.

## Use It

Nothing above needs a framework, but every κ term in the list has a well-known product built specifically to cut it.

**Database connection fan-out is the classic.** N application instances × M connections each is a number that grows when you scale *either* dimension, and Postgres allocates a full backend process per connection. The knob and its default:

```sql
SHOW max_connections;      -- 100 by default. Not a target; a fuse.
SELECT count(*), state FROM pg_stat_activity GROUP BY state;
```

Scaling from 24 app instances to 48 at a pool size of 20 takes you from 480 connections to 960. If `max_connections` is 500 you get errors, which is the *good* outcome because at least it is visible. If it is 2000 you get no errors and a database spending an increasing share of its time on process scheduling and lock-manager contention across 960 mostly-idle backends. **A connection pooler is a κ-reduction device**, and that is the cleanest way to understand what it is for:

```text
; pgbouncer.ini — N x M collapses to N x (a small constant)
[databases]
app = host=primary port=5432 pool_size=25

[pgbouncer]
pool_mode = transaction     ; the setting that makes this work at all
max_client_conn = 5000      ; what the fleet may open TO pgbouncer
default_pool_size = 25      ; what pgbouncer opens to POSTGRES
```

`pool_mode = transaction` is load-bearing: in `session` mode a client holds a server connection for its whole session and you have moved the problem rather than solved it. The cost, stated plainly: transaction mode breaks session-scoped state — prepared statements, `SET` for the session, advisory locks, `LISTEN`/`NOTIFY`. [Connection Pooling & N+1](../../03-relational-databases/14-connection-pooling-and-n-plus-1/) and [Connection & Resource Pooling](../../08-concurrency-and-performance/12-connection-and-resource-pooling/) build the pool itself; the point *here* is only that the fleet-wide connection count is a κ term and the pooler exists to make it constant in N.

**Service discovery is the other classic.** A full mesh where every client watches every server is `N × M` health-check streams and `N × M` re-convergences on every deploy. The fix is **subsetting** — each client is given a deterministic random subset of the backends, typically 20 to 100 of them, rather than all of them. Envoy calls it exactly that:

```yaml
clusters:
  - name: payments
    lb_subset_config: {}
    # deterministic subsetting: each proxy talks to a slice, not the fleet
    lb_policy: LEAST_REQUEST
    common_lb_config:
      subset_selectors: []
      healthy_panic_threshold: { value: 50 }
```

Lesson 5 of this phase builds subsetting properly, including the trap that makes a naive implementation worse than no subsetting: if the subsets are chosen badly, load lands unevenly and some backends are in nobody's subset. Do not roll your own from this paragraph.

**Cache invalidation fan-out** is a κ term you convert rather than remove: broadcasting every invalidation to every instance is `N(N−1)` messages, while publishing to a shared channel each instance consumes is `N` deliveries per event — still linear in N, but linear is a ceiling and quadratic is a cliff. Short TTLs plus request coalescing removes most broadcast invalidation entirely, at the cost of staleness you have to be willing to name. **Distributed locks** contribute to *both* terms and are worth avoiding for that reason alone; if you need one, partition the lock space so instances contend only within a partition, converting one global σ into K smaller ones exactly like section 5's sharding.

**Now the procedure**, which is the part to actually take away. Getting a trustworthy curve is a load-test problem, and Phase 8's [Benchmarking & Load Testing](../../08-concurrency-and-performance/14-benchmarking-and-load-testing/) already covers how to run one that does not lie — open versus closed loop, warm-up, steady state, and the coordinated-omission problem where a load generator that waits for a slow response stops *sending* during exactly the window you needed to measure. Use that methodology. Then:

1. **Pick your N.** It is whatever you scale: application instances, worker replicas, consumer group members, database connections. Vary one thing.
2. **Sweep at least 8 levels, and go past where you think the peak is.** If you run 24 in production, measure 1, 2, 4, 8, 16, 24, 32, 48, 64. **Measuring only up to your current size guarantees a fit that tells you to keep buying** — the code proves this: seven well-fitted points below the knee produced a prediction 16% wrong at 2× the range.
3. **Hold everything else fixed.** Same data set, same request mix, same client count, same instance type. If you change two things you have measured nothing. Drive the load from enough client capacity that the *generator* is never the bottleneck.
4. **Discard warm-up and measure steady state at each level.** JIT, caches, connection pools and autoscalers all need to settle. Repeat each level at least three times and take the mean; if the runs disagree by more than a few percent, your test harness is the thing you are measuring.
5. **Fit σ and κ.** The grid search in `code/scalability_law.py` transfers unchanged — replace the simulated measurements with your `(N, throughput)` table.
6. **Compute `N* = sqrt((1 − σ)/κ)` and compare it to your current fleet size.** This is the deliverable. If `N*` is 30 and you run 24, you have almost no room and your next scale-up event is a hazard. If `N*` is 400 and you run 24, σ is your problem and κ can wait.
7. **Check the fit before you believe it.** Plot the residuals. If the worst point is more than about 10% off, or if the fitted parameters landed on a search boundary, the model has not described your system and `N*` is a fantasy. The measured run here came in at **3.0% worst-case**, which is what a fit that means something looks like.

Then put the two numbers where people will see them. `N*` belongs in the same document as your autoscaler's `maxReplicas`, and **`maxReplicas` should be below `N*`** — an autoscaler that can cross your peak is a machine for converting a traffic spike into an outage. Lesson 13 covers the control-loop side of that; Lesson 12 turns `N*` into an actual purchase decision.

## Think about it

1. Your fit gives σ = 0.02 and κ = 0.00005. Compute `N*` and the Amdahl ceiling. Which term should you spend the next quarter attacking, and what would you need to measure to be sure you attacked the right one?
2. Section 5 halved σ and peak throughput rose 13.7%, but `N*` did not move. Explain why in terms of the formula, and describe a system where halving σ *would* move the peak substantially.
3. Your autoscaler is configured with `minReplicas: 10, maxReplicas: 200`. You have just fitted your service and found `N* = 64`. Describe what happens during a traffic spike under the current configuration, and what you would change — including what breaks if you simply set `maxReplicas: 64` and walk away.
4. You measure a sweep and the fit comes back with κ = 0 and an excellent residual. Give two completely different explanations for that result, and say what single additional measurement would distinguish them.
5. A colleague argues the USL is irrelevant to their stateless HTTP service, since instances never talk to each other. List three κ terms their service has anyway, and say which one you would measure first and how.

## Key takeaways

- **Capacity planning silently assumes `C(N) = N`, and there are two correction terms.** `C(N) = N / (1 + σ(N−1) + κN(N−1))`. The first is Amdahl's serial fraction; the second is Gunther's coherency term, and only the second can make throughput fall. At N = 64 with σ = 0.05 and κ = 0.001 the three models predict **64.00×, 15.42× and 7.82×** for identical hardware.
- **σ caps you at `1/σ`, forever.** Five percent serialization means 100 machines deliver **16.81×** and infinite machines deliver **20×**. σ has an address you can point at — the one primary, the one leader, the one lock, the one queue — and its signature is a shared resource pinned at 100% while total throughput sits on a plateau.
- **κ is quadratic because it counts pairs, not nodes.** `N(N−1)/2` pairs: 6 at N = 4, 28 at N = 8, 496 at N = 32, **32,640 at N = 256**. Doubling the fleet roughly *quadruples* the coordination. A κ of 0.001 — one part in a thousand — caps you at **9.04×** and puts your peak at 31 machines.
- **The peak is `N* = sqrt((1 − σ)/κ)`, and past it more machines means less throughput.** Measured: a simulated fleet peaked at **N = 32, 101.9 req/s**; doubling to 64 gave **83.7 req/s (−17.8%)** at **2.43× the cost per request**, and scaling back in recovered **+21.7%** in one deploy. The diagnostic that distinguishes κ from σ is per-node utilization: the serial resource went from **80.5% busy at the peak to 67.4% at 2× the fleet** — less contended, and slower.
- **Fit the curve; do not compute it from a code review.** The simulated system's serial section is 7.41% of a request, but the fitted σ is **0.0247**; the demand fraction correctly predicts the *ceiling* (measured 13.8× against 13.5× predicted) and nothing else. κ was recovered to within **17.6%**, `N*` to within **9%**, with a **3.0%** worst-case residual across 16 fleet sizes.
- **A fit that never sampled past the knee cannot find the knee.** Seven points at N ≤ 16, all fitted well, predicted **70.2 req/s at N = 64 against a true 83.7 — 16% wrong, in the direction that buys hardware.** Sweep at least 8 levels, well past your current fleet size, at steady state, repeated.
- **σ caps you; κ kills you — so attack κ first.** Sharding the serial resource halved σ (0.0249 → 0.0098) and bought **+13.7%**, but left the peak at N = 32: a higher ceiling, the same cliff. Subsetting the coordination graph to a fanout of 8 cut κ **0.001145 → 0.000360** and moved `N*` from 29 to **52**; both together reached **238.0 req/s at N = 96 and were still climbing (3.7× the baseline)**. Subsetting does not delete the cost — it makes it linear, which is why the subset run's σ *rose* to 0.0343.
- **`N*` belongs next to your autoscaler's `maxReplicas`, and it must be larger.** An autoscaler permitted to scale past your peak will respond to a traffic spike by making throughput worse, and every dashboard you own will agree that the fix is to scale further.

Next: [Load Balancing Algorithms: Why Round-Robin Lies](../03-load-balancing-algorithms/) — you now know how big the fleet should be; the next question is how requests get distributed across it, and why the default algorithm sends work to the machine least able to do it.
