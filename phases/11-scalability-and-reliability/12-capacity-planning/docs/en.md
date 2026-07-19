# Capacity Planning: Headroom, Peak & What to Actually Buy

> "Why are we running 135 instances when the dashboard says 33%?" is a completely reasonable question, and most teams cannot answer it. Measured here: the same 4,454 req/s peak needs 45 machines if you size against the number a load test prints, and 135 once you write down the failure you must survive — a **3.00× multiplier**, every point of it accounted for. The fleet sized to the sensible-sounding middle answer served **61.6% of requests** during an availability-zone loss. This lesson turns headroom from an opinion into arithmetic you can defend in a budget review.

**Type:** Build
**Languages:** Python
**Prerequisites:** [The Universal Scalability Law](../02-universal-scalability-law/), [Failure Domains, Blast Radius & Shuffle Sharding](../09-failure-domains-and-shuffle-sharding/), [Benchmarking & Load Testing](../../08-concurrency-and-performance/14-benchmarking-and-load-testing/)
**Time:** ~70 minutes

## The Problem

It is a quarterly budget review. The compute line has gone up again, and someone from finance — who is being helpful, not hostile — puts a graph on the screen and asks the obvious question.

"We're running 135 instances. Your own dashboard says CPU peaks at 33% and averages 12%. What are the other two thirds for?"

Nobody in the room has an answer. Not because the fleet is wrong — it happens to be exactly right — but because **nobody wrote down why**. The number came from a migration two years ago, plus a few panicked additions after incidents nobody documented. The best anyone offers is "headroom," which sounds like a synonym for "waste" to everyone who is not an engineer, and honestly sounds like one to some of the engineers too.

So the room does something reasonable. Someone points out that the queueing chapter everyone read says latency stays fine up to about 70% utilization. The peak is 4,454 requests per second. Each instance handles about 100. So 4,454 ÷ (100 × 0.71) = **63 instances**. That is a defensible-sounding number derived from an actual principle, and it cuts the bill by more than half. It ships.

Six weeks later, on a Tuesday at 20:40 — the top of the evening peak — an availability zone goes away. Not a hard outage: elevated error rates and packet loss in one of three zones, the kind of event a cloud provider posts about an hour later.

Here is what the arithmetic does, in order.

**20:40 — the survivors inherit the load.** 63 instances spread across three zones is 21 each. One zone is gone, so 42 instances now carry all 4,454 req/s. That is 106 req/s each, against a saturation ceiling of 100. Not "high utilization" — **over the ceiling**, a deficit that accumulates forever.

**20:40:30 — the queues convert to latency, and then to errors.** p99 crosses the 320 ms objective within seconds and keeps going. Requests start timing out at the client's one-second deadline.

**20:41 — the retry echo.** Every timed-out request comes back. The client library's three-attempt policy is sane, reviewed, and identical across every mobile app and browser in the fleet. Offered load does not stay at 4,454; the measured fixed point is **1.53× that, 6,800 req/s of attempts against 4,200 req/s of surviving capacity**. Phase 8 built this loop inside one process; this is the same loop with an entire zone's worth of clients in it.

**20:44 — the numbers.** The simulation in this lesson runs exactly this scenario. The 63-instance fleet serves **61.6% of attempts** — a 38% error rate — at a p99 of **426.7 ms**. Because clients retry three times, 94.3% of users eventually get an answer, each after sitting through a full one-second timeout first. The site is not *down*. It is worse than down in one specific way: it looks like it is working, so nobody rolls anything back.

Both decisions in this story were made without a model. The original 135 was undefended, and the cut to 63 was defended with *half* a model — the half about latency, and none of the half about failure. **Capacity planning is the discipline of being able to defend a number.** The number is usually much larger than average utilization suggests, and every part of the gap can be written down, measured, and argued about on its merits. That is what this lesson builds.

## The Concept

### Peak, not average

The first correction, and the one that changes the answer the most: **you do not provision for average load, because your users do not arrive on average.**

Traffic is diurnal (it follows the day) and weekly (it follows the week). The **peak-to-average ratio** — the busiest instant divided by the mean — is the number that converts one into the other. For consumer traffic it typically sits between 2× and 4×; it goes higher when your users are concentrated in one time zone, and lower when they are spread across the globe, because someone is always awake. The Build It generates 126 days of realistic demand and measures **2.68×**.

That ratio is the whole argument. Here is what it does to the machine count, measured:

```text
  provision to        req/s    x avg   instances (at the measured maximum)
  weekly average      1,661     1.00x          17
  p95 bucket          3,361     2.02x          34
  routine peak        4,454     2.68x          45
```

Provisioning to the average buys 17 instances for a service that needs 45 — and the shortfall is not an unlucky edge case, it lands **every single evening**. Note also that the p95 bucket is not good enough either: 5% of fifteen-minute buckets is 84 buckets a month, which is 21 hours of being under water.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 448" width="100%" style="max-width:840px" role="img" aria-label="One measured week of generated demand at hourly resolution, rising from about 430 requests per second overnight to a nightly evening peak near 3,500, with a live sports final on Friday evening driving a single hour to 7,236 requests per second. Three horizontal capacity lines are drawn across it: a fleet sized to the weekly average carries 1,704 requests per second and is exceeded for most of every day, the region above it shaded red; a fleet cut to the latency knee at peak carries 4,473 and clears the routine peak but not the event; the full headroom stack carries 9,585 and clears everything.">
  <text x="440" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">Provision to the average and you are under water every evening</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <g fill="#d64545" fill-opacity="0.26" stroke="none"><path d="M 141.0 331.2 L 141.0 328.1 L 145.6 327.7 L 145.6 331.2 Z"/><path d="M 164.0 331.2 L 164.0 327.2 L 168.6 310.1 L 173.1 295.6 L 177.7 287.7 L 182.3 291.4 L 186.9 307.7 L 191.5 330.5 L 191.5 331.2 Z"/><path d="M 246.5 331.2 L 246.5 331.0 L 251.1 323.1 L 255.7 319.6 L 260.3 327.1 L 260.3 331.2 Z"/><path d="M 274.1 331.2 L 274.1 324.3 L 278.6 306.9 L 283.2 289.6 L 287.8 274.9 L 292.4 282.4 L 297.0 302.3 L 301.6 325.5 L 301.6 331.2 Z"/><path d="M 361.2 331.2 L 361.2 323.2 L 365.8 320.1 L 370.4 326.5 L 370.4 331.2 Z"/><path d="M 384.1 331.2 L 384.1 326.3 L 388.7 306.0 L 393.3 289.9 L 397.9 275.4 L 402.5 280.2 L 407.1 300.9 L 411.7 326.4 L 411.7 331.2 Z"/><path d="M 466.7 331.2 L 466.7 331.1 L 471.3 322.6 L 475.9 318.2 L 480.5 325.8 L 480.5 331.2 Z"/><path d="M 494.2 331.2 L 494.2 324.1 L 498.8 307.0 L 503.4 288.5 L 508.0 277.0 L 512.6 281.2 L 517.2 300.9 L 521.7 324.3 L 521.7 331.2 Z"/><path d="M 576.8 331.2 L 576.8 323.4 L 581.4 320.2 L 586.0 314.7 L 590.6 322.0 L 595.1 328.3 L 595.1 331.2 Z"/><path d="M 604.3 331.2 L 604.3 316.9 L 608.9 299.2 L 613.5 278.3 L 618.1 159.7 L 622.7 167.7 L 627.2 207.5 L 631.8 282.8 L 631.8 331.2 Z"/><path d="M 686.9 331.2 L 686.9 324.0 L 691.5 316.7 L 696.0 313.3 L 700.6 319.5 L 705.2 323.9 L 709.8 328.2 L 714.4 320.3 L 719.0 296.4 L 723.6 275.7 L 728.2 259.7 L 732.7 272.8 L 737.3 295.9 L 741.9 319.9 L 741.9 331.2 Z"/><path d="M 797.0 331.2 L 797.0 328.8 L 801.5 325.4 L 806.1 321.1 L 810.7 325.9 L 810.7 331.2 Z"/><path d="M 824.5 331.2 L 824.5 324.4 L 829.1 308.8 L 833.7 287.1 L 838.2 278.6 L 842.8 281.6 L 847.4 301.3 L 852.0 323.8 L 852.0 331.2 Z"/></g>
    <g fill="none" stroke="currentColor" stroke-width="1.5"><path d="M 86.0 384.0 L 852.0 384.0"/><path d="M 86.0 384.0 L 86.0 68.0"/></g>
    <g fill="none" stroke="currentColor" stroke-width="1.1" opacity="0.45"><path d="M 86.0 384.0 L 86.0 389.0"/><path d="M 196.1 384.0 L 196.1 389.0"/><path d="M 306.2 384.0 L 306.2 389.0"/><path d="M 416.3 384.0 L 416.3 389.0"/><path d="M 526.3 384.0 L 526.3 389.0"/><path d="M 636.4 384.0 L 636.4 389.0"/><path d="M 746.5 384.0 L 746.5 389.0"/><path d="M 81 384.0 L 86 384.0"/><path d="M 81 322.0 L 86 322.0"/><path d="M 81 260.0 L 86 260.0"/><path d="M 81 198.0 L 86 198.0"/><path d="M 81 136.0 L 86 136.0"/><path d="M 81 74.0 L 86 74.0"/></g>
    <path d="M 86.0 86.9 L 852.0 86.9" fill="none" stroke="#0fa07f" stroke-width="2" stroke-dasharray="7 4"/>
    <path d="M 86.0 245.3 L 852.0 245.3" fill="none" stroke="#e0930f" stroke-width="2" stroke-dasharray="7 4"/>
    <path d="M 86.0 331.2 L 852.0 331.2" fill="none" stroke="#d64545" stroke-width="2" stroke-dasharray="7 4"/>
    <path d="M 86.0 370.4 L 90.6 370.5 L 95.2 370.6 L 99.8 370.2 L 104.3 370.1 L 108.9 367.8 L 113.5 360.8 L 118.1 353.0 L 122.7 343.4 L 127.3 343.5 L 131.9 340.3 L 136.5 335.1 L 141.0 328.1 L 145.6 327.7 L 150.2 331.5 L 154.8 336.5 L 159.4 336.9 L 164.0 327.2 L 168.6 310.1 L 173.1 295.6 L 177.7 287.7 L 182.3 291.4 L 186.9 307.7 L 191.5 330.5 L 196.1 369.7 L 200.7 369.3 L 205.3 370.0 L 209.8 368.7 L 214.4 368.3 L 219.0 365.7 L 223.6 360.0 L 228.2 349.9 L 232.8 342.1 L 237.4 339.5 L 242.0 336.4 L 246.5 331.0 L 251.1 323.1 L 255.7 319.6 L 260.3 327.1 L 264.9 334.4 L 269.5 333.7 L 274.1 324.3 L 278.6 306.9 L 283.2 289.6 L 287.8 274.9 L 292.4 282.4 L 297.0 302.3 L 301.6 325.5 L 306.2 369.7 L 310.8 369.2 L 315.3 369.1 L 319.9 368.8 L 324.5 368.9 L 329.1 366.2 L 333.7 359.6 L 338.3 348.5 L 342.9 341.9 L 347.4 340.2 L 352.0 339.5 L 356.6 331.5 L 361.2 323.2 L 365.8 320.1 L 370.4 326.5 L 375.0 331.6 L 379.6 333.6 L 384.1 326.3 L 388.7 306.0 L 393.3 289.9 L 397.9 275.4 L 402.5 280.2 L 407.1 300.9 L 411.7 326.4 L 416.3 368.7 L 420.8 369.0 L 425.4 369.3 L 430.0 368.8 L 434.6 368.0 L 439.2 366.0 L 443.8 358.3 L 448.4 349.6 L 452.9 340.9 L 457.5 339.1 L 462.1 334.5 L 466.7 331.1 L 471.3 322.6 L 475.9 318.2 L 480.5 325.8 L 485.1 332.6 L 489.6 331.8 L 494.2 324.1 L 498.8 307.0 L 503.4 288.5 L 508.0 277.0 L 512.6 281.2 L 517.2 300.9 L 521.7 324.3 L 526.3 367.8 L 530.9 367.4 L 535.5 367.5 L 540.1 367.9 L 544.7 367.2 L 549.3 364.3 L 553.9 356.9 L 558.4 344.6 L 563.0 338.2 L 567.6 334.3 L 572.2 331.3 L 576.8 323.4 L 581.4 320.2 L 586.0 314.7 L 590.6 322.0 L 595.1 328.3 L 599.7 331.3 L 604.3 316.9 L 608.9 299.2 L 613.5 278.3 L 618.1 159.7 L 622.7 167.7 L 627.2 207.5 L 631.8 282.8 L 636.4 367.1 L 641.0 367.5 L 645.6 367.7 L 650.2 367.2 L 654.8 366.5 L 659.4 363.5 L 663.9 355.8 L 668.5 345.8 L 673.1 336.4 L 677.7 334.5 L 682.3 333.5 L 686.9 324.0 L 691.5 316.7 L 696.0 313.3 L 700.6 319.5 L 705.2 323.9 L 709.8 328.2 L 714.4 320.3 L 719.0 296.4 L 723.6 275.7 L 728.2 259.7 L 732.7 272.8 L 737.3 295.9 L 741.9 319.9 L 746.5 369.5 L 751.1 369.7 L 755.7 369.6 L 760.3 369.6 L 764.9 368.2 L 769.4 366.1 L 774.0 360.0 L 778.6 350.3 L 783.2 342.3 L 787.8 340.2 L 792.4 338.2 L 797.0 328.8 L 801.5 325.4 L 806.1 321.1 L 810.7 325.9 L 815.3 333.9 L 819.9 336.3 L 824.5 324.4 L 829.1 308.8 L 833.7 287.1 L 838.2 278.6 L 842.8 281.6 L 847.4 301.3 L 852.0 323.8" fill="none" stroke="#3553ff" stroke-width="2.2" stroke-linejoin="round"/>
    <circle cx="618.1" cy="159.7" r="5" fill="none" stroke="#7c5cff" stroke-width="2.2"/>
    <path d="M 670.1 135.7 L 627.1 152.7" fill="none" stroke="#7c5cff" stroke-width="1.5"/>
    <g fill="currentColor">
      <text x="141.0" y="402" font-size="9" text-anchor="middle" opacity="0.7">Mon</text><text x="251.1" y="402" font-size="9" text-anchor="middle" opacity="0.7">Tue</text><text x="361.2" y="402" font-size="9" text-anchor="middle" opacity="0.7">Wed</text><text x="471.3" y="402" font-size="9" text-anchor="middle" opacity="0.7">Thu</text><text x="581.4" y="402" font-size="9" text-anchor="middle" opacity="0.7">Fri</text><text x="691.5" y="402" font-size="9" text-anchor="middle" opacity="0.7">Sat</text><text x="801.5" y="402" font-size="9" text-anchor="middle" opacity="0.7">Sun</text><text x="76" y="387.5" font-size="9" text-anchor="end" opacity="0.7">0k</text><text x="76" y="325.5" font-size="9" text-anchor="end" opacity="0.7">2k</text><text x="76" y="263.5" font-size="9" text-anchor="end" opacity="0.7">4k</text><text x="76" y="201.5" font-size="9" text-anchor="end" opacity="0.7">6k</text><text x="76" y="139.5" font-size="9" text-anchor="end" opacity="0.7">8k</text><text x="76" y="77.5" font-size="9" text-anchor="end" opacity="0.7">10k</text>
      <text x="76" y="60" font-size="9.5" text-anchor="end" opacity="0.85">req/s</text>
      <text x="850" y="127.7" font-size="10" font-weight="700" fill="#7c5cff" text-anchor="end">live sports final: 7,236 req/s</text>
      <text x="850" y="140.7" font-size="9" fill="#7c5cff" opacity="0.9" text-anchor="end">4.5x the average, for 4 hours</text>
    </g>
    <rect x="104" y="96" width="386" height="92" rx="9" fill="#7f7f7f" fill-opacity="0.07" stroke="currentColor" stroke-opacity="0.3" stroke-width="1.2"/>
    <g fill="none" stroke-width="2.4" stroke-dasharray="7 4">
      <path d="M 118 118 L 152 118" stroke="#0fa07f"/><path d="M 118 144 L 152 144" stroke="#e0930f"/><path d="M 118 170 L 152 170" stroke="#d64545"/>
    </g>
    <g fill="currentColor">
      <text x="162" y="121" font-size="10" font-weight="700" fill="#0fa07f">135 inst — full headroom stack</text>
      <text x="392" y="121" font-size="10" font-weight="700">9,585 r/s</text>
      <text x="162" y="147" font-size="10" font-weight="700" fill="#e0930f">63 inst — knee at peak only</text>
      <text x="392" y="147" font-size="10" font-weight="700">4,473 r/s</text>
      <text x="162" y="173" font-size="10" font-weight="700" fill="#d64545">24 inst — sized to the average</text>
      <text x="392" y="173" font-size="10" font-weight="700">1,704 r/s</text>
      <text x="118" y="212" font-size="9.5" fill="#d64545" font-weight="700">everything shaded red is demand the 24-instance fleet cannot serve</text>
    </g>
    <text x="440" y="430" font-size="11" text-anchor="middle" fill="currentColor" opacity="0.9">Average 1,661 · p95 bucket 3,361 · routine peak 4,454 · with events 7,492 req/s. The average is not a plan.</text>
  </g>
</svg>
```

Then there are the days that make a mockery of your peak. The Build It injects two, and they are the two every consumer service has:

- **A marketing push notification** (×1.55 for two hours). Someone in growth schedules a send. It is a load test you did not agree to.
- **A live sports final** (×1.90 for three and a half hours). This is the genuinely Netflix-shaped problem: demand driven by an external event you do not control, concentrated in a window, with an audience that all arrives in the same ninety seconds.

Together they push the worst fifteen-minute bucket to **7,492 req/s — 4.51× the average**, which needs 75 instances at the measured maximum where the routine peak needed 45. But you do not buy 75 instances permanently for 5.5 hours a month. You **pre-scale** for events you know about, which is only possible if someone tells you they are happening — the single most valuable capacity-planning artifact at most companies is a shared calendar between marketing and infrastructure.

There is a fourth spike, and it is the one you cause yourself: **the retry echo of your own outage**. When you start shedding, clients retry, and offered load rises above real demand. Phase 8's Lesson 11 built this feedback loop inside a single process; at fleet scale it is measured in section 4 of the Build It, where a partial outage inflates offered load to **1.53×** real demand. Your worst-ever traffic peak is very often a self-portrait.

### The knee, not 100%

The second correction. **You cannot plan to 100% utilization**, and the reason is not caution — it is arithmetic. Phase 8's Lesson 11 derived `W = S / (1 − ρ)`: as utilization ρ approaches 1, waiting time goes to infinity. That lesson taught the derivation. This lesson *uses* it, and the use is a single question:

> **At what throughput does this instance still meet its latency objective?**

That number — not the throughput at which it stops getting faster — is your usable capacity. The gap between the two is large, and it is measured. The Build It load-tests one instance (4 workers, 40 ms mean service time, so a hard ceiling of 100 req/s) against a p99 ≤ 320 ms objective:

```text
      rho    req/s |  textbook (CV^2=1)        |  measured shape (CV^2=2)
                   |    p50      p99   meets?  |    p50      p99   meets?
     0.70       70 |    40.4ms  227.7ms   yes |    38.4ms  313.1ms   yes
     0.71       71 |    41.2ms  231.1ms   yes |    39.5ms  317.4ms   yes  <- knee, measured shape
     0.75       75 |    45.5ms  247.8ms   yes |    44.9ms  348.2ms   NO
     0.83       83 |    59.5ms  318.4ms   yes |    65.0ms  456.4ms   NO   <- knee, textbook
```

**Your usable capacity is not your measured maximum throughput.** The instance saturates at 100 req/s and is usable to **71**. Planning on the maximum over-states every machine by **1.41×**, which means a fleet sized that way is 41% too small — and it will discover this at the worst possible moment, because a fleet that is too small only fails at peak.

The second column is the part that gets skipped, and it is worth more than the first. Both runs have the **identical mean service time of 40 ms**. The only difference is the *shape* of the distribution: the left column is the textbook exponential (CV² = 1, squared coefficient of variation, variance over mean squared), the right is a lognormal with CV² = 2 — a body of fast responses with a multiplicative tail, which is what a real handler with a cache, a variable result set and an occasional slow dependency actually looks like. Variability alone costs **12 req/s per instance, 14% of usable capacity, for free**. Averages are not enough; you have to measure the distribution.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 432" width="100%" style="max-width:840px" role="img" aria-label="Measured p99 latency plotted against offered throughput for one four-worker instance. Both curves are flat and then bend sharply upward. With textbook exponential service times the curve crosses the 320 millisecond objective at 83 requests per second; with the measured lognormal shape, whose squared coefficient of variation is two, the same curve crosses at 71. The instance saturates at 100 requests per second, so the usable fraction is 0.83 and 0.71 respectively, and the 29 requests per second between 71 and 100 is throughput the load test reports but the objective forbids you to use.">
  <defs><marker id="p11-12-a4" markerWidth="10" markerHeight="10" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#d64545"/></marker><marker id="p11-12-a4b" markerWidth="10" markerHeight="10" refX="6" refY="3" orient="auto-start-reverse"><path d="M0,0 L7,3 L0,6 Z" fill="#d64545"/></marker></defs>
  <text x="440" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">Your usable capacity is not your measured maximum throughput</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <rect x="523.7" y="74" width="176.3" height="282" fill="#d64545" fill-opacity="0.09"/>
    <g fill="none" stroke="currentColor" stroke-width="1.5"><path d="M 92.0 356.0 L 708 356.0"/><path d="M 92.0 356.0 L 92.0 70"/></g>
    <g fill="none" stroke="currentColor" stroke-width="1.1" opacity="0.45"><path d="M 92.0 356.0 L 92.0 361.0"/><path d="M 213.6 356.0 L 213.6 361.0"/><path d="M 335.2 356.0 L 335.2 361.0"/><path d="M 456.8 356.0 L 456.8 361.0"/><path d="M 578.4 356.0 L 578.4 361.0"/><path d="M 700.0 356.0 L 700.0 361.0"/><path d="M 87 356.0 L 92 356.0"/><path d="M 87 286.5 L 92 286.5"/><path d="M 87 217.0 L 92 217.0"/><path d="M 87 147.5 L 92 147.5"/><path d="M 87 78.0 L 92 78.0"/></g>
    <path d="M 92.0 244.8 L 708 244.8" fill="none" stroke="#d64545" stroke-width="1.8" stroke-dasharray="6 4"/>
    <path d="M 700.0 356.0 L 700.0 74" fill="none" stroke="currentColor" stroke-width="1.6" stroke-dasharray="4 4" opacity="0.6"/>
    <path d="M 92.0 287.7 L 274.4 287.4 L 335.2 287.0 L 396.0 286.1 L 426.4 285.0 L 456.8 283.2 L 487.2 280.6 L 517.6 276.9 L 523.7 275.7 L 548.0 269.9 L 578.4 256.3 L 596.6 245.4 L 608.8 236.5 L 627.0 218.8 L 639.2 202.8 L 651.4 181.2" fill="none" stroke="#0fa07f" stroke-width="2.6" stroke-linejoin="round"/>
    <path d="M 92.0 263.8 L 274.4 263.7 L 335.2 262.9 L 396.0 261.1 L 426.4 260.0 L 456.8 257.9 L 487.2 253.4 L 517.6 247.2 L 523.7 245.7 L 548.0 235.0 L 578.4 214.6 L 596.6 197.4 L 608.8 184.2 L 627.0 154.5 L 639.2 124.9 L 651.4 92.5" fill="none" stroke="#e0930f" stroke-width="2.6" stroke-linejoin="round" stroke-dasharray="8 4"/>
    <g fill="none" stroke-width="2"><circle cx="596.6" cy="245.4" r="7.5" stroke="#0fa07f"/><circle cx="523.7" cy="245.7" r="7.5" stroke="#e0930f"/></g>
    <g fill="none" stroke-width="1.5" stroke-dasharray="3 3" opacity="0.85"><path d="M 596.6 253.4 L 596.6 356.0" stroke="#0fa07f"/><path d="M 523.7 253.7 L 523.7 356.0" stroke="#e0930f"/></g>
    <path d="M 525.7 322 L 698.0 322" fill="none" stroke="#d64545" stroke-width="1.6" marker-end="url(#p11-12-a4)" marker-start="url(#p11-12-a4b)"/>
    <g fill="currentColor">
      <text x="92.0" y="374" font-size="9" text-anchor="middle" opacity="0.7">0</text><text x="213.6" y="374" font-size="9" text-anchor="middle" opacity="0.7">20</text><text x="335.2" y="374" font-size="9" text-anchor="middle" opacity="0.7">40</text><text x="456.8" y="374" font-size="9" text-anchor="middle" opacity="0.7">60</text><text x="578.4" y="374" font-size="9" text-anchor="middle" opacity="0.7">80</text><text x="700.0" y="374" font-size="9" text-anchor="middle" opacity="0.7">100</text><text x="82" y="359.5" font-size="9" text-anchor="end" opacity="0.7">0</text><text x="82" y="290.0" font-size="9" text-anchor="end" opacity="0.7">200</text><text x="82" y="220.5" font-size="9" text-anchor="end" opacity="0.7">400</text><text x="82" y="151.0" font-size="9" text-anchor="end" opacity="0.7">600</text><text x="82" y="81.5" font-size="9" text-anchor="end" opacity="0.7">800</text>
      <text x="396" y="396" font-size="10.5" text-anchor="middle" opacity="0.85">offered throughput, requests/second, one 4-worker instance</text>
      <text x="32" y="217" font-size="10.5" opacity="0.85" transform="rotate(-90 32 217)" text-anchor="middle">measured p99 latency (ms)</text>
      <text x="100" y="235.8" font-size="10.5" font-weight="700" fill="#d64545">latency objective: p99 &#8804; 320 ms</text>
      <text x="611.8" y="342" font-size="10" font-weight="700" fill="#d64545" text-anchor="middle">29 req/s you cannot spend</text>
      <text x="152" y="112" font-size="10.5" font-weight="700">the dashed line at 100 req/s is saturation</text>
      <text x="152" y="128" font-size="9" opacity="0.85">4 workers / 40 ms service time. It is what a load</text>
      <text x="152" y="142" font-size="9" opacity="0.85">test reports as "max throughput", and it is the</text>
      <text x="152" y="156" font-size="9" opacity="0.85">one number you must never put in a capacity model.</text>
    </g>
    <g fill="none" stroke-width="1.9" stroke-linejoin="round">
      <rect x="716" y="86" width="150" height="80" rx="9" fill="#0fa07f" fill-opacity="0.11" stroke="#0fa07f"/>
      <rect x="716" y="178" width="150" height="80" rx="9" fill="#e0930f" fill-opacity="0.12" stroke="#e0930f"/>
    </g>
    <g fill="currentColor">
      <text x="730" y="106" font-size="10.5" font-weight="700" fill="#0fa07f">textbook</text>
      <text x="730" y="121" font-size="9" opacity="0.9">CV&#178; = 1 exponential</text>
      <text x="730" y="140" font-size="12" font-weight="700">83 req/s</text>
      <text x="730" y="156" font-size="9.5" opacity="0.9">fraction 0.83</text>
      <text x="730" y="198" font-size="10.5" font-weight="700" fill="#e0930f">measured shape</text>
      <text x="730" y="213" font-size="9" opacity="0.9">CV&#178; = 2 lognormal</text>
      <text x="730" y="232" font-size="12" font-weight="700">71 req/s</text>
      <text x="730" y="248" font-size="9.5" opacity="0.9">fraction 0.71</text>
      <text x="722" y="284" font-size="9.5" font-weight="700" fill="#d64545">identical mean</text>
      <text x="722" y="298" font-size="9.5" font-weight="700" fill="#d64545">service time.</text>
      <text x="722" y="312" font-size="9.5" font-weight="700" fill="#d64545">12 req/s lost to</text>
      <text x="722" y="326" font-size="9.5" font-weight="700" fill="#d64545">variance alone.</text>
    </g>
    <text x="440" y="418" font-size="11" text-anchor="middle" fill="currentColor" opacity="0.9">Plan on 71, not 100. Planning on the measured maximum over-states every instance by 1.41x.</text>
  </g>
</svg>
```

Lesson 2's Universal Scalability Law says the same thing from the other direction: adding workers to one machine does not add throughput linearly, because of contention and coherency. Both effects mean the same practical thing — **there is a number between "idle" and "maximum" that is the real capacity of a machine, and you have to measure it.**

### N+1, N+2 and the AZ arithmetic

This is the heart of the lesson, and it is the part the budget review does not know.

An **availability zone (AZ)** is a cloud provider's unit of physical isolation — a distinct datacenter (or set of them) with independent power, cooling and network, close enough to its siblings for low-latency replication. Lesson 9 called this a failure domain. Zones fail. They fail as a unit, which is the entire point of the abstraction: you are supposed to lose one and stay up.

So write down the requirement: **survive the loss of one of N failure domains, at peak, without breaching the SLO.** The arithmetic falls straight out. If N domains share the load evenly and one disappears, the survivors carry `N/(N−1)` times what they carried before. So each domain may run at no more than:

```text
max steady-state utilization = (N − 1) / N
```

| Zones N | max steady util | you must buy | combined with the 0.71 knee |
|---|---|---|---|
| 2 | 50.0% | 2.00× | 35.5% |
| 3 | 66.7% | 1.50× | 47.3% |
| 4 | 75.0% | 1.33× | 53.2% |
| 5 | 80.0% | 1.25× | 56.8% |
| 6 | 83.3% | 1.20× | 59.2% |

Two zones means you buy **twice** the capacity you need. This is why two-zone deployments are a trap: they look redundant and cost double to actually be redundant. Three is the usual sweet spot, and the returns flatten fast after four.

Now combine the two corrections, because they multiply. Your latency-safe utilization is 0.71 and you need to survive one of three zones:

> **0.71 × 2/3 = 47%**

**That is the steady-state utilization a correctly sized fleet targets**, and it is the answer to the question in The Problem. A well-run fleet *is supposed to* look about half idle on the dashboard, because the idle half is doing a job: it is the capacity that absorbs a zone. At exactly 47%, losing a zone puts you at 47% × 1.5 = 71% — precisely the knee, with nothing to spare. Add the other headroom terms below and the real fleet sits lower still, at 33%.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 470" width="100%" style="max-width:840px" role="img" aria-label="The availability-zone arithmetic. A 135-instance fleet is spread 45 instances to each of three zones, carrying 33 requests per second per instance at the 4,454 per second peak. Zone C fails; its 1,485 requests per second redistribute to the two survivors, which now carry 49.5 requests per second per instance, still below the measured knee of 71. Below, a table gives the maximum steady-state utilization for two through six zones as N minus one over N, the resulting provisioning multiplier, and the combined target once the 0.71 latency knee is included: with three zones that combined target is 47 percent, which is why a correctly sized fleet looks half idle.">
  <defs><marker id="p11-12-a2" markerWidth="10" markerHeight="10" refX="7" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#e0930f"/></marker></defs>
  <text x="440" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">To survive losing 1 of N zones, each may run at (N&#8722;1)/N</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <g fill="none" stroke-width="2.2" stroke-linejoin="round">
      <rect x="72" y="62" width="184" height="86" rx="10" fill="#0fa07f" fill-opacity="0.12" stroke="#0fa07f"/>
      <rect x="288" y="62" width="184" height="86" rx="10" fill="#0fa07f" fill-opacity="0.12" stroke="#0fa07f"/>
      <rect x="504" y="62" width="184" height="86" rx="10" fill="#d64545" fill-opacity="0.12" stroke="#d64545" stroke-dasharray="7 4"/>
    </g>
    <g text-anchor="middle" fill="currentColor">
      <text x="164" y="84" font-size="12.5" font-weight="700" fill="#0fa07f">AZ-A</text>
      <text x="380" y="84" font-size="12.5" font-weight="700" fill="#0fa07f">AZ-B</text>
      <text x="596" y="84" font-size="12.5" font-weight="700" fill="#d64545">AZ-C &#8212; GONE</text>
      <text x="164" y="104" font-size="11" font-weight="700">45 instances</text>
      <text x="380" y="104" font-size="11" font-weight="700">45 instances</text>
      <text x="596" y="104" font-size="11" font-weight="700" opacity="0.55">45 instances</text>
      <text x="164" y="122" font-size="10" opacity="0.9">was 1,485 req/s</text>
      <text x="380" y="122" font-size="10" opacity="0.9">was 1,485 req/s</text>
      <text x="596" y="122" font-size="10" opacity="0.55">was 1,485 req/s</text>
      <text x="164" y="139" font-size="11" font-weight="700" fill="#e0930f">now 2,227 req/s</text>
      <text x="380" y="139" font-size="11" font-weight="700" fill="#e0930f">now 2,227 req/s</text>
      <text x="596" y="139" font-size="11" font-weight="700" fill="#d64545">now 0 req/s</text>
    </g>
    <path d="M 504 132 L 508 168 L 168 168 L 166 154" fill="none" stroke="#e0930f" stroke-width="1.8" marker-end="url(#p11-12-a2)"/>
    <path d="M 540 152 L 540 168 L 384 168 L 382 154" fill="none" stroke="#e0930f" stroke-width="1.8" marker-end="url(#p11-12-a2)"/>
    <path d="M 528 74 L 664 136" fill="none" stroke="#d64545" stroke-width="2.4"/>
    <path d="M 664 74 L 528 136" fill="none" stroke="#d64545" stroke-width="2.4"/>
    <g fill="none" stroke-width="1.9" stroke-linejoin="round">
      <rect x="712" y="62" width="152" height="132" rx="9" fill="#3553ff" fill-opacity="0.10" stroke="#3553ff"/>
    </g>
    <g fill="currentColor">
      <text x="726" y="82" font-size="10.5" font-weight="700" fill="#3553ff">per instance</text>
      <text x="726" y="102" font-size="9.5" opacity="0.9">all 3 zones up</text>
      <text x="726" y="118" font-size="13" font-weight="700">33.0 req/s</text>
      <text x="726" y="140" font-size="9.5" opacity="0.9">one zone gone</text>
      <text x="726" y="156" font-size="13" font-weight="700" fill="#e0930f">49.5 req/s</text>
      <text x="726" y="178" font-size="9.5" font-weight="700" fill="#0fa07f">knee is 71 &#8212; safe</text>
    </g>
    <text x="350" y="196" font-size="11" text-anchor="middle" fill="currentColor" opacity="0.95">4,454 req/s &#247; 90 surviving = 49.5 each. The load did not change; the denominator did.</text>
    <path d="M 72 218 L 808 218" fill="none" stroke="currentColor" stroke-width="1" opacity="0.3"/>
    <g fill="currentColor" font-size="9.5" font-weight="700" opacity="0.7">
      <text x="112" y="248" text-anchor="middle">ZONES N</text>
      <text x="238" y="248" text-anchor="middle">MAX STEADY UTIL</text>
      <text x="360" y="248" text-anchor="middle">YOU BUY</text>
      <text x="474" y="248" text-anchor="middle">x KNEE 0.71</text>
    </g>
    <g fill="currentColor" font-size="8.5" opacity="0.6">
      <text x="238" y="262" text-anchor="middle">(N&#8722;1)/N</text>
      <text x="360" y="262" text-anchor="middle">N/(N&#8722;1)</text>
      <text x="474" y="262" text-anchor="middle">= steady target</text>
    </g>
    <path d="M 72 272 L 512 272" fill="none" stroke="currentColor" stroke-width="1.2" opacity="0.4"/>
    <g><text x="112" y="322" font-size="11" font-weight="400" text-anchor="middle" fill="currentColor">2</text><text x="238" y="322" font-size="11" font-weight="400" text-anchor="middle" fill="currentColor">50.0%</text><text x="360" y="322" font-size="11" font-weight="400" text-anchor="middle" fill="currentColor">2.00x</text><text x="474" y="322" font-size="11" font-weight="700" text-anchor="middle" fill="currentColor">35.5%</text><rect x="72" y="331" width="440" height="25" rx="5" fill="#0fa07f" fill-opacity="0.15" stroke="#0fa07f" stroke-width="1.6"/><text x="112" y="349" font-size="11" font-weight="700" text-anchor="middle" fill="currentColor">3</text><text x="238" y="349" font-size="11" font-weight="700" text-anchor="middle" fill="currentColor">66.7%</text><text x="360" y="349" font-size="11" font-weight="700" text-anchor="middle" fill="currentColor">1.50x</text><text x="474" y="349" font-size="11" font-weight="700" text-anchor="middle" fill="#0fa07f">47.3%</text><text x="112" y="376" font-size="11" font-weight="400" text-anchor="middle" fill="currentColor">4</text><text x="238" y="376" font-size="11" font-weight="400" text-anchor="middle" fill="currentColor">75.0%</text><text x="360" y="376" font-size="11" font-weight="400" text-anchor="middle" fill="currentColor">1.33x</text><text x="474" y="376" font-size="11" font-weight="700" text-anchor="middle" fill="currentColor">53.2%</text><text x="112" y="403" font-size="11" font-weight="400" text-anchor="middle" fill="currentColor">5</text><text x="238" y="403" font-size="11" font-weight="400" text-anchor="middle" fill="currentColor">80.0%</text><text x="360" y="403" font-size="11" font-weight="400" text-anchor="middle" fill="currentColor">1.25x</text><text x="474" y="403" font-size="11" font-weight="700" text-anchor="middle" fill="currentColor">56.8%</text><text x="112" y="430" font-size="11" font-weight="400" text-anchor="middle" fill="currentColor">6</text><text x="238" y="430" font-size="11" font-weight="400" text-anchor="middle" fill="currentColor">83.3%</text><text x="360" y="430" font-size="11" font-weight="400" text-anchor="middle" fill="currentColor">1.20x</text><text x="474" y="430" font-size="11" font-weight="700" text-anchor="middle" fill="currentColor">59.2%</text></g>
    <g fill="none" stroke-width="2" stroke-linejoin="round">
      <rect x="546" y="240" width="292" height="200" rx="10" fill="#0fa07f" fill-opacity="0.10" stroke="#0fa07f"/>
    </g>
    <g fill="currentColor">
      <text x="562" y="264" font-size="11.5" font-weight="700" fill="#0fa07f">the number to remember</text>
      <text x="562" y="292" font-size="15" font-weight="700">0.71 &#215; 2/3 = 47%</text>
      <text x="562" y="314" font-size="9.5" opacity="0.9">latency knee &#215; AZ survival = the</text>
      <text x="562" y="328" font-size="9.5" opacity="0.9">steady-state utilization you target.</text>
      <text x="562" y="352" font-size="9.5" opacity="0.9">At 47% an AZ loss lands you exactly</text>
      <text x="562" y="366" font-size="9.5" opacity="0.9">on the knee: 47% &#215; 1.5 = 71%.</text>
      <text x="562" y="390" font-size="9.5" opacity="0.9">Add deploy surge and forecast and</text>
      <text x="562" y="404" font-size="9.5" opacity="0.9">the real fleet sits at 33%.</text>
      <text x="562" y="428" font-size="10" font-weight="700" fill="#0fa07f">A well-run fleet looks half idle.</text>
    </g>
    <text x="440" y="460" font-size="11" text-anchor="middle" fill="currentColor" opacity="0.9">Two zones means you buy 2x. Six zones means you buy 1.2x &#8212; but six zones is six of everything else too.</text>
  </g>
</svg>
```

The same logic extends to regions (Lesson 10). **Active-active across two regions means each region must be able to carry everything**, because the whole point is surviving the loss of one — so you are buying 2× at the region level *on top of* the zone-level headroom inside each region. That is why true active-active is expensive, and why many teams choose active-passive with a warm standby, accepting a failover time in exchange for not paying twice. Say which one you are buying; do not discover it during a region event.

### Little's Law as the sizing tool

Little's Law (J. D. C. Little, *A Proof for the Queuing Formula L = λW*, Operations Research 9(3), 1961) is the other half of the sizing arithmetic, and Phase 8's Lesson 1 introduced it. Here it is a tool:

```text
L = lambda x W        L = items in the system, lambda = arrival rate, W = time in system
```

Applied to a fleet, `L` is **concurrency**, which is what machines actually supply. The measured chain, end to end:

```text
lambda = 4,454 req/s at the routine peak
W      = 64.5 ms measured mean latency at rho = 0.71
L      = 4,454 x 0.0645 = 287.2 requests in the system at any instant
```

To convert that into machines, apply the law to the *service* stage only, since that is what a worker occupies: `busy workers = λ × S = 4,454 × 0.040 = 178.1`. Each instance has 4 workers and you will run them at ρ = 0.71, so each instance supplies `4 × 0.71 = 2.8` usable workers. That gives `178.1 / 2.8 = 63` instances.

**Sixty-three — the same number the knee-only row of the headroom stack produced, by a completely different route.** Two derivations agreeing is how you know the model is not just arithmetic that happens to terminate.

Now the part that should make you nervous. Latency is in the numerator, which means **a latency regression is a capacity regression**:

```text
baseline           S = 40.0 ms   busy workers = 178.1  ->  63 instances bare, 135 with headroom
+20 ms regression  S = 60.0 ms   busy workers = 267.2  ->  95 instances bare, 201 with headroom
```

Twenty milliseconds of extra p50 — a well-intentioned change that adds one more database round trip, or a JSON payload that grew — costs **51% of your fleet: 63 → 95 bare, 135 → 201 with the full stack**. And *nothing alerts*. The p99 is still comfortably inside the 320 ms objective. The error rate is zero. Every dashboard is green. The first thing that notices is the invoice, six weeks later, and by then nobody remembers which deploy did it.

### Building a capacity model

The procedure, in the order that makes it work:

1. **Load-test one instance to find its safe throughput at your latency SLO — not its maximum.** Phase 8's Lesson 14 covers the methodology: a concurrency sweep, open-loop load generation, coordinated-omission-free measurement. The output you want is not "it does 100 req/s"; it is "it does 71 req/s with p99 under 320 ms."
2. **Identify the binding resource.** Lesson 1 measured the four walls — CPU, memory, I/O, network. Capacity is set by whichever saturates first, and it is frequently not CPU. Sizing on CPU when you are bound by connection count or memory bandwidth produces a model that is confidently wrong.
3. **Convert business metrics into technical load, with a measured ratio.** This is the step teams skip, and it is what makes a forecast possible at all. The Build It pins the whole model to `4,200,000 daily actives × 28 requests each = 117.6M requests/day = 1,661 req/s average`. Measure requests per active user, queries per request, bytes per response — then your capacity conversation becomes *"we can support 4.2M daily actives on this fleet"*, which is a sentence a product manager can plan against and a finance partner can price. Without step 3 you cannot forecast, because nobody forecasts requests per second; they forecast users.
4. **Forecast demand** over a horizon longer than your lead time (below).
5. **Apply headroom** for the knee, the failure domains, deploy surge and forecast error.
6. **Validate against reality and re-measure.** A capacity model is a *model*. Check the fleet's actual utilization at last week's peak against what the model predicted. When they diverge, the model is wrong, not reality.

### Forecasting honestly

Fit a trend and a seasonality. The Build It fits `log(daily peak) = level + linear trend + day-of-week effect` on twelve weeks of history and validates on the six weeks it never saw:

```text
  trend      : +1.51% per week recovered (the series was generated at +1.20%)
  seasonality: Mon..Sun  -5.6%  -3.8%  -4.1%  -1.5%  +2.1%  +9.4%  +4.3%
  residual sd: 4.0%  -> p90/p50 forecast ratio = 1.053
```

Two things there deserve attention. The recovered trend is **+1.51%/week against a true +1.20%** — the fit is honest, the data is noisy, and twelve weeks is not enough to pin a growth rate precisely. And the Saturday effect is **+9.4%**, which means a capacity plan that ignores day-of-week is wrong by nearly a tenth on the day it matters most.

Now the crucial part: **forecast error is itself a headroom input.**

> A p50 forecast is, by construction, wrong half the time. Provision to a high quantile of the forecast, not its centre.

Measured over the held-out horizon:

```text
  scenario      horizon        p50 fcst  p90 fcst |  days short of  days short of   worst
  trend holds   days 84-104        3670      3866 |     28.6%           4.8%         1.01x
  trend breaks  days 105-125       3839      4044 |     52.4%          19.0%         1.09x
```

Provisioning to the p50 leaves you short on **29% of days even when the trend holds perfectly**, and on **52% of days** in the scenario where growth quietly accelerates from 1.2% to 2.0% per week after the fit window. The p90 buy costs **5.3% more capacity** and cuts the exposure to 4.8% and 19% respectively. That 5.3% is the cheapest term in the entire headroom stack — cheaper than the knee, far cheaper than AZ survival — and it is the one people leave out because it feels like pessimism. It is not pessimism. It is pricing.

**Lead time is what makes all of this binding.** If new capacity takes six weeks to arrive — reserved-instance terms, a quota increase that needs a support ticket and an account manager, GPU supply, physical hardware in a colocation facility — then **your forecast horizon must exceed six weeks**, because a forecast that only sees four weeks ahead cannot trigger an order that takes six. Cloud elasticity genuinely changes this: on-demand instances arrive in minutes, so the lead time for *ordinary* scale-up is effectively zero and Lesson 13's autoscaling takes over. It changes nothing for the things that are still queued behind a human: service quotas, committed-use discounts, capacity reservations in a specific zone, and any hardware that is scarce this quarter. Cloud elasticity moved the problem; it did not remove it.

### Unit economics

Fleet cost is a big number that nobody can reason about. **Cost per request** is a small number that anyone can:

```text
$3.891 per million requests  ·  $0.0040 per active user per month
```

Pick the denominator that matches your business — per request, per active user, per stream, per order — and put it on a dashboard next to your latency graphs. Three things become possible at once. Finance can compare it to revenue per user. Product can price a new feature before building it. And, most usefully for engineers: **a code change that doubles CPU per request doubles your fleet, and that is a regression you can catch.**

The 20 ms latency regression from the Little's Law section raises cost per million requests from **$3.891 to $5.836 — a 50% cost regression, $100,521 a year** — for a diff that passed code review with a green build. If your CI catches a 5% latency regression but not a 50% cost regression, your CI is measuring the wrong thing.

### The things that eat headroom silently

This is where real fleets go wrong, because each of these is invisible until it is load-bearing:

- **Deploy surge.** A rolling deploy removes capacity while it runs. If your strategy takes 25% of instances out at a time, that 25% is capacity you must *own* — it is in the stack above and it costs 31 machines. Worse, deploys are when instances die, so "AZ failure during a deploy" is not two independent events being pessimistically multiplied; it is one common scenario.
- **Cold caches on new instances.** A freshly started instance is slower than a warm one until its caches fill. Lesson 6 called this the cost of warmth. During a scale-up or a rolling deploy, a meaningful fraction of your fleet is running at reduced capacity precisely when you need it most — and an autoscaler that does not know this will add instances that make things briefly worse (Lesson 13).
- **Background jobs and batch colliding with peak.** The nightly report, the reindex, the data export. If they run at 20:00 they are competing with your busiest hour. Schedule them against the traffic curve, not against a human's idea of "night".
- **Noisy neighbours.** On shared hardware, your measured per-instance capacity has someone else's workload baked into it. The 71 req/s you measured on a quiet Tuesday may be 60 on a busy one.
- **Retry amplification during any degradation.** Measured at **1.53×** in the AZ-loss scenario. Your capacity model's demand input is not real demand; it is real demand times whatever your clients do when they are unhappy.

## Build It

[`code/capacity.py`](code/capacity.py) is a working capacity model in seven numbered sections — standard library only, seeded, about nine seconds. It is meant to be adapted: change the constants at the top to your service's numbers and it produces your fleet size.

**The demand generator** pins everything to the business math, so the model is a *conversion* rather than an invention:

```python
base = DAILY_ACTIVES * REQ_PER_ACTIVE_PER_DAY / 86400.0
...
lam = base * shape * dow * g * day_noise * bucket_noise
```

`shape` is the diurnal curve, `dow` the day-of-week factor, `g` compounding growth. Change `DAILY_ACTIVES` and every downstream number moves, which is exactly the property that makes capacity planning a business conversation.

**The queueing simulator** is an exact FIFO M/G/c queue in six lines, using a heap of per-worker free-times. This is what produces the knee:

```python
for i in range(n_req):
    t += rng.expovariate(lam)
    start = t if free[0] < t else free[0]      # wait for the first free worker
    finish = start + svc()
    heapq.heapreplace(free, finish)
    if i >= warm:
        lat.append(finish - t)                 # what the caller measures
```

Service times are lognormal, parameterised by the squared coefficient of variation, because that is the shape real handlers have. Note the memoisation in `sweep_point`: the printed table and the knee search share one measurement, so the table can never disagree with the conclusion drawn from it — a small thing that matters when a p99 estimate is noisy.

**The retry echo** in section 4 is a fixed point, not a guess. With up to three attempts and a per-attempt failure rate `f`, each real request is offered `1 + f + f²` times, and `f` itself depends on how much is offered:

```python
for _ in range(200):
    f = max(0.0, 1.0 - capacity / offered)
    offered = peak * (1.0 + f + f * f)
```

**The headroom stack** is the artifact of the lesson, and the whole trick is that each step divides the *per-instance budget* rather than multiplying the demand — which keeps every step independently arguable:

```python
budget = MAX_PER_INSTANCE * rho_safe * surv * (1 - DEPLOY_SURGE)
```

Run it:

```bash
docker compose exec -T app python \
  phases/11-scalability-and-reliability/12-capacity-planning/code/capacity.py
```

```console
== 1 · PEAK, NOT AVERAGE — WHAT THE DASHBOARD AVERAGE HIDES ==
  business input : 4,200,000 daily actives × 28 requests each
  =              : 117.6M requests/day = 1,661 req/s on average
  history        : 126 days at 96 buckets/day (last 28 shown); one instance sustains 100 req/s

  provision to        req/s    x avg   instances (at the measured maximum)
  weekly average      1,661     1.00x          17
  p95 bucket          3,361     2.02x          34
  routine peak        4,454     2.68x          45
  peak incl. events   7,492     4.51x          75

  peak-to-average ratio (routine) = 2.68x — provisioning to the average
  buys 28 too few instances, and the shortfall lands every single evening.
  event: day 104 19.0-21.0h  ×1.55  marketing push notification
  event: day 117 20.0-23.5h  ×1.90  live sports final
  the events push the worst bucket to 4.51x average — 75 instances for 5.5 hours of the month.
  that is a scheduled pre-scale, not standing capacity (see section 6).

== 2 · THE KNEE, NOT 100% — USABLE CAPACITY IS NOT MEASURED MAXIMUM ==
  one instance: 4 workers × 40 ms mean service = 100 req/s saturation ceiling
  latency objective: p99 ≤ 320 ms (8× service time)

      rho    req/s |  textbook (CV^2=1)        |  measured shape (CV^2=2)
                   |    p50      p99   meets?  |    p50      p99   meets?
       ~0         0 |    28.4ms  196.6ms   yes |    23.2ms  265.2ms   yes
     0.50       50 |    31.6ms  201.2ms   yes |    27.2ms  273.0ms   yes
     0.60       60 |    34.8ms  209.4ms   yes |    30.9ms  282.4ms   yes
     0.70       70 |    40.4ms  227.7ms   yes |    38.4ms  313.1ms   yes
     0.71       71 |    41.2ms  231.1ms   yes |    39.5ms  317.4ms   yes  <- knee, measured shape
     0.75       75 |    45.5ms  247.8ms   yes |    44.9ms  348.2ms   NO
     0.80       80 |    52.9ms  286.8ms   yes |    55.0ms  406.9ms   NO
     0.83       83 |    59.5ms  318.4ms   yes |    65.0ms  456.4ms   NO   <- knee, textbook
     0.85       85 |    65.8ms  343.9ms   NO  |    74.4ms  494.3ms   NO
     0.90       90 |    93.6ms  440.9ms   NO  |   114.8ms  665.0ms   NO

  textbook (CV^2=1): max 100 req/s, usable    83 req/s at p99 318.4 ms → fraction 0.83
  measured (CV^2=2): max 100 req/s, usable    71 req/s at p99 317.4 ms → fraction 0.71
  variability alone costs 12 req/s per instance (14% of usable
  capacity), with no change whatsoever in the mean service time.
  every number after this uses rho_safe = 0.71, the measured shape, not the textbook one.
  planning to the measured maximum would over-state each instance by 1.41x.

== 3 · THE HEADROOM STACK — WHERE EVERY MACHINE ACTUALLY GOES ==
  required throughput at the routine peak: 4,454 req/s

  step                          per-instance   instances   x naive    util at
                                  budget r/s                        routine peak
  0  naive: measured maximum        100.0          45     1.00x       99.0%
  1  + latency knee (rho≤0.71)       71.0          63     1.40x       70.7%
  2  + survive 1 of 3 AZs            47.3          95     2.11x       46.9%
  3  + deploy surge (25%)            35.5         126     2.80x       35.3%
  4  + forecast p90 (×1.05)          35.5         133     2.96x       33.5%
  5  + balance across 3 AZs             —         135     3.00x       33.0%

  total: 135 instances where naive sizing said 45 — a 3.00× multiplier.
  steady-state utilization at the routine peak: 33.0%.
  that is the number the budget review objects to, and every point of it is spoken for.
  honest caveat: steps 2 and 3 are multiplied here. Taking max() instead of the product
  gives 100 instances and saves 35 machines — it is a bet that an AZ never fails
  during a deploy. Deploys are when instances die, so the two events are not independent.

== 4 · THE AZ ARITHMETIC — AND WHAT AN AZ LOSS DOES AT PEAK ==
   AZs   max steady util   provisioning x   combined target with the knee
     2           50.0%            2.00x                 35.5%
     3           66.7%            1.50x                 47.3%
     4           75.0%            1.33x                 53.2%
     5           80.0%            1.25x                 56.8%
     6           83.3%            1.20x                 59.2%
  with a latency-safe rho of 0.71 and 3 AZs, the steady-state target is 0.71 × 0.67 = 47%.
  a correctly sized fleet is SUPPOSED to look half idle.

  now lose one of 3 AZs at the 4,454 req/s routine peak.
  clients retry up to 3x, so shedding feeds back into offered load.

  fleet sizing                  N   left   offered x   per inst   served   p99(ok)   users OK
  sized by the model         135     90        1.00x         49    100.0%    268.0ms     100.0%
  cut to the knee at peak     63     42        1.53x        163     61.6%    426.7ms      94.3%
  sized to the average        24     16        2.61x        725     13.7%    434.8ms      35.8%
  'served' is per ATTEMPT — it is your error rate. 'users OK' assumes 3 tries,
  and those extra tries are exactly what inflated 'offered x' in the first place
  (Phase 8 Lesson 11's retry storm, now with 3 AZs' worth of clients in it).
  every retried user also paid a full 1.0 s client timeout before trying again.

== 5 · LITTLE'S LAW AS THE SIZING TOOL — L = lambda × W ==
  lambda = 4,454 req/s (routine peak)
  W      = 64.5 ms measured mean latency at rho=0.71 (service 40 ms + queueing)
  L      = lambda × W = 287.2 requests in the system at any instant

  turning concurrency into machines:
  baseline                 S= 40.0 ms   busy workers = 4,454 × 0.040 =  178.1
                           at 0.71 × 4 = 2.8 usable/instance → 63 bare, 135 with headroom
  +20 ms regression        S= 60.0 ms   busy workers = 4,454 × 0.060 =  267.2
                           at 0.71 × 4 = 2.8 usable/instance → 95 bare, 201 with headroom

  a 20 ms regression costs 51% of the fleet: 63 → 95 instances bare
  (+32), 135 → 201 with the full headroom stack (+66).
  nothing alerts: p99 is still inside the 320 ms SLO and the error rate is zero.
  the invoice notices first. Cross-check: Little's Law says 63 instances and the knee-only
  row of section 3 said 63. Two independent derivations, one number.

== 6 · FORECASTING HONESTLY — FORECAST ERROR IS A HEADROOM INPUT ==
  fit on days 0-83 (known one-off events excluded from the fit),
  validated on days 84-125 — a 42-day (6-week) capacity lead time.
  trend      : +1.51% per week recovered (the series was generated at +1.20%)
  seasonality: Mon..Sun  -5.6%  -3.8%  -4.1%  -1.5%  +2.1%  +9.4%  +4.3%
  residual sd: 4.0%  → p90/p50 forecast ratio = 1.053

  scenario      horizon        p50 fcst  p90 fcst |  days short of  days short of   worst
                                  req/s     req/s |   the p50 buy    the p90 buy     miss
  trend holds   days 84-104        3670      3866 |     28.6%           4.8%         1.01x
  trend holds   days 105-125       3839      4044 |     28.6%           4.8%         1.05x
  trend breaks  days 84-104        3670      3866 |     38.1%           4.8%         1.03x
  trend breaks  days 105-125       3839      4044 |     52.4%          19.0%         1.09x

  read the first two rows: even with the trend holding exactly, the p50 buy is short on
  29% of days in both halves of the horizon. It is a coin flip by construction,
  and the fitted trend adds its own error on top (+1.51%/wk recovered vs +1.20%/wk true,
  from an 84-day window).
  the last two rows are the same forecast against demand whose growth rose to +2.0%/wk
  on day 84: the p50 buy is short 52% of the far horizon and even the p90 buy fails 19%.
  the p90 buy costs 5.3% more capacity — that is the forecast-error term in the
  headroom stack, and it is the cheapest term in it. Buying it is not pessimism, it is pricing.
  lead time is what makes this binding: with 42 days between 'we need capacity' and
  'capacity exists', your forecast horizon must exceed 42 days or the forecast is decorative.
  cloud elasticity shortens that lead time to minutes for on-demand instances
  and changes nothing for quota increases, reserved terms or scarce hardware.

== 7 · UNIT ECONOMICS — WHAT TO ACTUALLY BUY ==
  price: $0.0425 per vCPU-hour on demand; 1 worker = 1 vCPU.  730 hours/month.
  capacity per instance is USL-derated (Lesson 02, sigma=0.02, kappa=0.0004) and pays a
  fixed 0.55 vCPU platform tax for the runtime, log shipper and mesh sidecar.

  family   vCPU    max r/s   safe r/s   inst   $/month    $/M req   $/user/mo   AZ-safe
  c-2       2       43.9       31.2    303     18,801     4.366      0.0045     yes
  c-4       4      100.0       71.0    135     16,754     3.891      0.0040     yes
  c-8       8      197.5      140.2     69     17,126     3.977      0.0041     yes
  c-16     16      340.3      241.6     39     19,360     4.496      0.0046     yes
  c-32     32      477.7      339.1     30     29,784     6.917      0.0071     yes

  cheapest family that meets the p99 SLO and survives an AZ loss: c-4 × 135 = $16,754/month
  the 32-vCPU box is not cheaper per request: USL coherency loss outruns
  the platform tax it saves, and it makes your AZ rounding coarser too.

  on demand           $   16,754/mo   $ 3.891/M req   no commitment
  1-yr savings plan   $   10,387/mo   $ 2.412/M req   commitment = a capacity forecast you signed
  3-yr savings plan   $    7,372/mo   $ 1.712/M req   cheaper than any code change you will ship
  30% spot            $   13,487/mo   $ 3.132/M req   saves $3,267/mo
  but count the domains: AZ loss leaves 90 instances; AZ loss WHILE spot is being
  reclaimed leaves 62, which carries 4,402 req/s against a 4,454 req/s peak — a -1.2% margin.
  spot reclamation is a CORRELATED failure: one capacity pool, one price
  signal, every instance in it leaves inside the same two minutes. It is a
  failure domain that happens to be cheap, not a discount on the fleet you have.

  the unit that makes this legible to people who do not read latency graphs:
    $3.891 per million requests · $0.0040 per active user per month
  a change that adds 20 ms of p50 (section 5) raises that to $5.836/M req — a 50% cost regression,
  which is $100,521 a year for a diff that passed code review.
```

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 500" width="100%" style="max-width:840px" role="img" aria-label="A waterfall of the headroom stack for a 4,454 requests per second peak. Naive sizing against the measured maximum of 100 requests per second per instance gives 45 instances at 99 percent utilization. Applying the measured latency knee of 0.71 adds 18 instances to reach 63. Surviving the loss of one of three availability zones adds 32 more to reach 95. A 25 percent deploy surge adds 31 to reach 126. The p90 forecast adds 7 to reach 133, and balancing across three zones adds 2 to reach 135. The final fleet runs at 33 percent utilization at peak and is exactly three times the naive number.">
  <text x="440" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">Where every one of the 135 machines goes</text>
  <text x="440" y="45" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="10.5" fill="currentColor" opacity="0.85">required: 4,454 req/s at the routine peak &#183; each step divides the per-instance budget, never the demand</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <path d="M 68 392.0 L 856 392.0" fill="none" stroke="currentColor" stroke-width="1.5"/>
    <g fill="none" stroke="currentColor" stroke-width="1.2" stroke-dasharray="4 4" opacity="0.5"><path d="M 157.0 303.2 L 203.0 303.2"/><path d="M 281.0 267.7 L 327.0 267.7"/><path d="M 405.0 204.5 L 451.0 204.5"/><path d="M 529.0 143.4 L 575.0 143.4"/><path d="M 653.0 129.5 L 699.0 129.5"/></g>
    <rect x="79.0" y="303.2" width="78.0" height="88.8" rx="3" fill="#7f7f7f" fill-opacity="0.30" stroke="#7f7f7f" stroke-width="2"/><rect x="203.0" y="303.2" width="78.0" height="88.8" rx="3" fill="#7f7f7f" fill-opacity="0.10" stroke="currentColor" stroke-opacity="0.28" stroke-width="1.1"/><rect x="203.0" y="267.7" width="78.0" height="35.5" rx="3" fill="#e0930f" fill-opacity="0.30" stroke="#e0930f" stroke-width="2"/><rect x="327.0" y="267.7" width="78.0" height="124.3" rx="3" fill="#7f7f7f" fill-opacity="0.10" stroke="currentColor" stroke-opacity="0.28" stroke-width="1.1"/><rect x="327.0" y="204.5" width="78.0" height="63.1" rx="3" fill="#d64545" fill-opacity="0.30" stroke="#d64545" stroke-width="2"/><rect x="451.0" y="204.5" width="78.0" height="187.5" rx="3" fill="#7f7f7f" fill-opacity="0.10" stroke="currentColor" stroke-opacity="0.28" stroke-width="1.1"/><rect x="451.0" y="143.4" width="78.0" height="61.2" rx="3" fill="#7c5cff" fill-opacity="0.30" stroke="#7c5cff" stroke-width="2"/><rect x="575.0" y="143.4" width="78.0" height="248.6" rx="3" fill="#7f7f7f" fill-opacity="0.10" stroke="currentColor" stroke-opacity="0.28" stroke-width="1.1"/><rect x="575.0" y="129.5" width="78.0" height="13.8" rx="3" fill="#3553ff" fill-opacity="0.30" stroke="#3553ff" stroke-width="2"/><rect x="699.0" y="129.5" width="78.0" height="262.5" rx="3" fill="#7f7f7f" fill-opacity="0.10" stroke="currentColor" stroke-opacity="0.28" stroke-width="1.1"/><rect x="699.0" y="125.6" width="78.0" height="3.9" rx="3" fill="#0fa07f" fill-opacity="0.30" stroke="#0fa07f" stroke-width="2"/>
    <g><text x="118.0" y="281.2" font-size="16" font-weight="700" text-anchor="middle" fill="currentColor">45</text><text x="118.0" y="295.2" font-size="9.5" text-anchor="middle" fill="currentColor" opacity="0.7">instances</text><text x="118.0" y="414" font-size="10.5" font-weight="700" text-anchor="middle" fill="#7f7f7f">naive</text><text x="118.0" y="428" font-size="9" text-anchor="middle" fill="currentColor" opacity="0.8">measured maximum</text><text x="118.0" y="444" font-size="9" text-anchor="middle" fill="currentColor" opacity="0.75">budget 100.0 req/s</text><text x="118.0" y="458" font-size="9.5" font-weight="700" text-anchor="middle" fill="currentColor" opacity="0.9">util 99.0%</text><text x="242.0" y="245.7" font-size="16" font-weight="700" text-anchor="middle" fill="currentColor">63</text><text x="242.0" y="259.7" font-size="10.5" font-weight="700" text-anchor="middle" fill="#e0930f">+18</text><text x="242.0" y="414" font-size="10.5" font-weight="700" text-anchor="middle" fill="#e0930f">+ knee</text><text x="242.0" y="428" font-size="9" text-anchor="middle" fill="currentColor" opacity="0.8">rho &#8804; 0.71</text><text x="242.0" y="444" font-size="9" text-anchor="middle" fill="currentColor" opacity="0.75">budget 71.0 req/s</text><text x="242.0" y="458" font-size="9.5" font-weight="700" text-anchor="middle" fill="currentColor" opacity="0.9">util 70.7%</text><text x="366.0" y="182.5" font-size="16" font-weight="700" text-anchor="middle" fill="currentColor">95</text><text x="366.0" y="196.5" font-size="10.5" font-weight="700" text-anchor="middle" fill="#d64545">+32</text><text x="366.0" y="414" font-size="10.5" font-weight="700" text-anchor="middle" fill="#d64545">+ AZ survival</text><text x="366.0" y="428" font-size="9" text-anchor="middle" fill="currentColor" opacity="0.8">lose 1 of 3</text><text x="366.0" y="444" font-size="9" text-anchor="middle" fill="currentColor" opacity="0.75">budget 47.3 req/s</text><text x="366.0" y="458" font-size="9.5" font-weight="700" text-anchor="middle" fill="currentColor" opacity="0.9">util 46.9%</text><text x="490.0" y="121.4" font-size="16" font-weight="700" text-anchor="middle" fill="currentColor">126</text><text x="490.0" y="135.4" font-size="10.5" font-weight="700" text-anchor="middle" fill="#7c5cff">+31</text><text x="490.0" y="414" font-size="10.5" font-weight="700" text-anchor="middle" fill="#7c5cff">+ deploy surge</text><text x="490.0" y="428" font-size="9" text-anchor="middle" fill="currentColor" opacity="0.8">25% out</text><text x="490.0" y="444" font-size="9" text-anchor="middle" fill="currentColor" opacity="0.75">budget 35.5 req/s</text><text x="490.0" y="458" font-size="9.5" font-weight="700" text-anchor="middle" fill="currentColor" opacity="0.9">util 35.3%</text><text x="614.0" y="107.5" font-size="16" font-weight="700" text-anchor="middle" fill="currentColor">133</text><text x="614.0" y="121.5" font-size="10.5" font-weight="700" text-anchor="middle" fill="#3553ff">+7</text><text x="614.0" y="414" font-size="10.5" font-weight="700" text-anchor="middle" fill="#3553ff">+ forecast p90</text><text x="614.0" y="428" font-size="9" text-anchor="middle" fill="currentColor" opacity="0.8">x1.05 demand</text><text x="614.0" y="444" font-size="9" text-anchor="middle" fill="currentColor" opacity="0.75">budget 35.5 req/s</text><text x="614.0" y="458" font-size="9.5" font-weight="700" text-anchor="middle" fill="currentColor" opacity="0.9">util 33.5%</text><text x="738.0" y="103.6" font-size="16" font-weight="700" text-anchor="middle" fill="currentColor">135</text><text x="738.0" y="117.6" font-size="10.5" font-weight="700" text-anchor="middle" fill="#0fa07f">+2</text><text x="738.0" y="414" font-size="10.5" font-weight="700" text-anchor="middle" fill="#0fa07f">+ AZ balance</text><text x="738.0" y="428" font-size="9" text-anchor="middle" fill="currentColor" opacity="0.8">multiple of 3</text><text x="738.0" y="444" font-size="9" text-anchor="middle" fill="currentColor" opacity="0.75">budget 35.5 req/s</text><text x="738.0" y="458" font-size="9.5" font-weight="700" text-anchor="middle" fill="currentColor" opacity="0.9">util 33.0%</text></g>
    <path d="M 68 476 L 856 476" fill="none" stroke="currentColor" stroke-width="1" opacity="0.3"/>
    <text x="440" y="494" font-size="11" text-anchor="middle" fill="currentColor" opacity="0.95">45 answers "what does peak demand need?" &#183; 135 answers "survive an AZ loss, mid-deploy, on a forecast" &#8212; exactly 3.00x</text>
  </g>
</svg>
```

Read the output as an argument, because that is what it is.

**Section 1** establishes that the average is not a plan: a **2.68× peak-to-average ratio** turns 17 instances into 45, and the two injected events turn 45 into 75 for 5.5 hours a month. **Section 2** is the correction that costs the most per line of code: the instance saturates at 100 req/s and is *usable* to **71**, and switching from the textbook service-time distribution to a realistically variable one — **at the same mean** — moves the knee from 83 to 71.

**Section 3 is the artifact.** Each row divides the per-instance budget by one more factor and reports what it costs: the knee is +18 machines, AZ survival is +32, deploy surge is +31, the p90 forecast is +7, AZ balancing is +2. **45 → 135, exactly 3.00×**, ending at 33.0% utilization at peak. Every one of those 90 extra machines has a name and a reason, which is precisely what The Problem's budget review needed and did not have. The caveat printed underneath is the honest part: steps 2 and 3 are *multiplied*, and taking `max()` instead would save 35 machines. That is a real, defensible choice — but it is a bet that a zone never fails during a deploy, and since deploys are when instances die, those two events are not independent.

**Section 4 is the payoff and the vindication of section 3.** The AZ table is pure arithmetic — 2 zones means 2.00×, 3 means 1.50× — and combining it with the knee gives the number to remember: **0.71 × 0.67 = 47%**. Then the simulation drops a zone at peak against three differently sized fleets. The model-sized fleet serves **100.0%** at a **268 ms** p99, sitting at 49 req/s per instance against a knee of 71. The fleet cut to "the knee at peak" — the reasonable-sounding decision from The Problem — sees offered load inflate to **1.53×** through retries, serves **61.6% of attempts** at a **426.7 ms** p99, and gets 94.3% of users through only because they each retried through a full one-second timeout. The average-sized fleet serves **13.7%**, and **only 35.8% of users get an answer at all**.

**Section 5** shows Little's Law arriving at 63 instances independently, and then the sensitivity that should change your code review habits: **+20 ms of p50 costs 51% of the fleet**, silently, with every dashboard green. **Section 6** validates the forecast on data it never saw and prices forecast error at **5.3%** — the cheapest headroom you will ever buy — while showing that the p50 buy is short on 29% to 52% of days.

**Section 7** answers "what should we buy." The 4-vCPU family wins at **$16,754/month, $3.891 per million requests**, and the interesting part is *why the extremes lose*. Small instances pay a fixed platform tax (runtime, log shipper, mesh sidecar) on every box, so 303 tiny instances waste 303 copies of it. Large instances pay Lesson 2's USL coherency penalty: the 32-vCPU box delivers 477.7 req/s where linear scaling from the 4-vCPU box would predict 800. The optimum is in the middle, and it is measurable rather than a matter of taste. The spot row is the trap: 30% spot saves $3,267/month and still survives an AZ loss — but an AZ loss **during** a reclamation event leaves 62 instances carrying 4,402 req/s against a 4,454 req/s peak, a **−1.2% margin**. Spot is not a discount on the fleet you have; it is a fourth failure domain that happens to be cheap.

## Use It

**What to measure, and where it comes from.** Everything above needs four inputs, and Phase 9 already built the pipes for all of them:

| Input | Where it comes from | Trap |
|---|---|---|
| requests per active user per day | your metrics backend, divided by your analytics DAU | must be the *same* definition of "active" both sides |
| CPU-seconds per request | `rate(process_cpu_seconds_total[5m]) / rate(http_requests_total[5m])` | throttled containers under-report; see below |
| safe throughput per instance | a concurrency sweep at your SLO | not the number the load test calls "max" |
| connections per instance | connection-pool gauges | often the real binding resource, not CPU |

See [Metrics from Scratch](../../09-logging-monitoring-and-observability/05-metrics-from-scratch/) and [Prometheus: Pull, Exposition & PromQL](../../09-logging-monitoring-and-observability/06-prometheus-and-promql/) for the collection mechanics, and [SLIs, SLOs & Error Budgets](../../09-logging-monitoring-and-observability/09-slis-slos-and-error-budgets/) for the objective the whole model is measured against. **Your capacity plan is downstream of your SLO — if you have not written the SLO, you do not have a capacity target, you have a preference.**

**The concurrency sweep that produces the per-instance number.** This is the one measurement you must do yourself ([Benchmarking & Load Testing](../../08-concurrency-and-performance/14-benchmarking-and-load-testing/) has the methodology):

```bash
# Open-loop, one instance, fixed duration per step. Record p99 at each rate.
for rate in 20 30 40 50 60 65 70 75 80 85 90; do
  echo -n "$rate req/s -> "
  vegeta attack -rate="${rate}/1s" -duration=120s -targets=targets.txt \
    | vegeta report -type=json | jq -r '.latencies.p99 / 1000000 | floor'
done
```

Take the **highest rate whose p99 is still inside your objective**, not the highest rate that completes. Run it for at least two minutes per step — queues take time to reach steady state, and a 30-second step will flatter you. Run it against a *warm* instance and then against a *cold* one; the difference is the cold-start cost you must budget for during deploys and scale-ups.

**Instance families and price/performance.** Compare families on **cost per unit of *your* work**, never on vCPU count or on price. Benchmark the same workload on three or four candidates and divide monthly cost by requests served — the winner is frequently not the one with the best spec sheet, because your workload's mix of memory bandwidth, cache behaviour and clock speed does not resemble the vendor's benchmark. Re-run it when a new generation ships; a generation change is often 15-20% price/performance for the cost of an AMI change.

**Purchasing: on-demand, committed, spot.**

- **On-demand** is the baseline and the most expensive per hour. Use it for the part of the fleet that moves.
- **Reserved instances / savings plans** trade a commitment for 30-55% off (measured above: **$16,754 → $10,387 at one year, $7,372 at three**). A commitment is a capacity forecast you signed your name to. Commit to your *floor* — the load you are confident about, typically your trough plus a margin — and buy the peak on demand. Over-committing is worse than under-committing, because you pay for it either way.
- **Spot / preemptible** is 60-90% off with the provider's right to take it back on short notice. The critical property, which pricing pages do not put in bold: **spot reclamation is a correlated failure.** All the instances in one pool share one price signal, and they leave together, inside the same two minutes. Spread spot across pools and families, cap it at a fraction of the fleet that you have verified you can survive losing simultaneously, and — this is the part the Build It measures — **check the combination of a spot reclamation and an AZ loss**, not each in isolation. Treat it as a failure domain in the (N−1)/N arithmetic, not as a discount applied afterwards.

**Quota limits are a capacity constraint, and they are the one people forget until a failover hits one.** Cloud accounts have per-region, per-instance-family limits on vCPUs, IP addresses, load-balancer targets, NAT gateway bandwidth and API call rates. They are usually generous enough that you never notice — until you try to double a region's fleet during an incident and the API returns a quota error. Audit them:

```bash
aws service-quotas list-service-quotas --service-code ec2 \
  --query 'Quotas[?contains(QuotaName, `On-Demand`)].[QuotaName,Value]' --output table
```

Then raise every quota in your failover region to what a **full regional failover** would require, and re-check quarterly. A quota increase is a support ticket with a human in the loop — it is the six-week lead time in disguise.

**Kubernetes: requests vs limits is *the* capacity concept in an orchestrated fleet.** Phase 10 covers the mechanics ([Orchestration & Kubernetes](../../10-infrastructure-and-deployment/07-orchestration-and-kubernetes/)); here is what they mean for capacity:

```yaml
resources:
  requests:            # what the SCHEDULER reserves. This is what you pay for.
    cpu: "1000m"       # 1 core reserved on some node, whether you use it or not
    memory: "512Mi"
  limits:              # where the KERNEL throttles you. Not a reservation.
    cpu: "2000m"       # above this, CFS throttling — a latency bug that looks like code
    memory: "1Gi"      # above this, OOMKill — not throttling, death
```

- **`requests` is your capacity model's unit.** Cluster capacity is the sum of requests, not the sum of usage. A cluster at 40% CPU usage can be 100% *scheduled* and unable to place a single new pod. If your capacity model tracks usage and your scheduler tracks requests, the two will disagree at the worst moment.
- **`limits` is where you get throttled**, and CPU throttling is the single most commonly misdiagnosed latency problem in Kubernetes. A container that exceeds its CPU limit is not killed; it is **paused until the next 100 ms scheduling period**. The result is a p99 latency spike with no corresponding CPU graph, no error, and no stack trace — it looks exactly like a slow dependency. Check `container_cpu_cfs_throttled_seconds_total` before you go looking in the code.
- **Memory has no throttling — only OOMKill.** Set `requests` = `limits` for memory on anything latency-sensitive.
- **Setting `requests` far below actual usage** oversubscribes the node and makes every pod on it a noisy neighbour. Setting it far above wastes the difference on every replica. Measure the p95 of actual usage and set requests there.

**A quarterly capacity review — what a team should bring.** Fifteen minutes, four artifacts, no slides:

1. **Last quarter's forecast vs actual**, on one chart. Say the error out loud as a percentage. This is the only agenda item that improves the model.
2. **The current headroom stack**, as the table from section 3: naive count, then each factor, then the fleet. If a factor changed (a new deploy strategy, a fourth AZ, a measured knee that moved), say which and why.
3. **The unit economics trend**: cost per million requests, quarter over quarter. A rise with flat traffic is a code regression that nobody caught.
4. **The next-quarter ask**, with the business metric attached: *"we forecast 5.1M daily actives at p90, which is 168 instances, which is $20,800/month, and our current quota in the failover region tops out at 140."*

Bring the number you can defend and the assumption it rests on. That is the whole job.

## Key takeaways

- **The headroom you need is set by the failure you must survive, not by your average load.** Measured: the same 4,454 req/s peak needs **45 instances** sized against the load test's maximum and **135** once the knee, one-AZ survival, deploy surge and forecast error are written down — a **3.00× multiplier** in which every machine has a named reason.
- **Your usable capacity is not your measured maximum throughput.** One instance saturated at **100 req/s** and was usable to **71** at a p99 ≤ 320 ms objective — planning on the maximum over-states every machine by **1.41×**. Service-time *variability* alone (CV² 1 → 2, identical mean) moved the knee from **83 to 71 req/s**, costing 14% of usable capacity for free.
- **To survive losing 1 of N domains, each may run at (N−1)/N.** 2 AZs → 50% (you buy 2×), 3 → 67%, 4 → 75%, 6 → 83%. Combine with the knee and you get the number to remember: **0.71 × 2/3 = 47% steady-state utilization**. A correctly sized fleet is *supposed* to look half idle; that idle half is the zone you are going to lose.
- **Sizing to "the knee at peak" is the most dangerous plausible answer.** It ignores failure entirely. Measured under a one-AZ loss at peak, that 63-instance fleet saw retries inflate offered load to **1.53×**, served **61.6% of attempts** at a **426.7 ms** p99, and only got 94.3% of users through because each of them sat out a one-second timeout first. The 135-instance fleet served **100%** at **268 ms**.
- **A latency regression is a capacity regression, and nothing alerts on it.** Little's Law: `busy workers = λ × S`. Twenty milliseconds of extra p50 took the fleet from **63 to 95 instances bare (135 → 201 with headroom), +51%**, and raised cost from **$3.891 to $5.836 per million requests — $100,521 a year** — while p99 stayed inside the SLO and the error rate stayed at zero.
- **Forecast error is a headroom input, and it is the cheapest one.** A p50 forecast was short on **29% of days when the trend held exactly** and **52%** when growth accelerated after the fit window. The p90 buy costs **5.3% more capacity** and cuts that to 4.8% and 19%. Buy it — and make your forecast horizon exceed your lead time, because you cannot buy six-week-lead capacity in week five.
- **Convert business metrics to technical load with a measured ratio, or you have no model.** `4.2M daily actives × 28 requests each = 1,661 req/s average`. That single line is what turns capacity planning from a guessing game into the sentence *"we can support 4.2M daily actives on this fleet"* — which is the only form in which anyone outside engineering can agree to it.
- **Price the fleet per request, and count spot as a failure domain.** The 4-vCPU family won at **$3.891/M requests**; the 32-vCPU box cost **$6.917** because USL coherency loss outran the platform tax it saved. 30% spot saved $3,267/month and still survived an AZ loss — but an AZ loss *during* a reclamation left a **−1.2% capacity margin**. Correlated discounts are not discounts.

Next: [Autoscaling: Control Loops That Don't Oscillate](../13-autoscaling/) — this lesson sized a fleet for the peak you can predict; the next one builds the control loop that tracks the demand you cannot, and explains why the naive version oscillates, lags, and scales down right before it needed the capacity.
