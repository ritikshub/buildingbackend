# Autoscaling: Control Loops That Don't Oscillate

> An autoscaler is a feedback control loop, and every complaint you have about yours is a named control-theory phenomenon with a known cause. Measured here: the same controller against the same traffic, changed in exactly one way — 210 seconds of dead time instead of zero — went from parking on the correct 24 instances all afternoon to swinging between 6 and 145 on a plateau where the traffic never moved, launching **539 instances instead of 33** and missing the latency objective for **42.7% of requests**. Then the one that ends outages badly: during a retry storm, the autoscaler added capacity until its connection pools cut the database's own throughput from **426 to 247 queries per second**, and goodput stayed at **exactly zero for the entire run**.

**Type:** Build
**Languages:** Python
**Prerequisites:** [Capacity Planning](../12-capacity-planning/), [Stateless Services](../06-stateless-services/), [Backpressure, Queueing & Load Shedding](../../08-concurrency-and-performance/11-backpressure-and-load-shedding/)
**Time:** ~75 minutes

## The Problem

Your service holds CPU at 60%. That is the setpoint somebody typed into a form eighteen months ago, and it has been fine.

**13:40 — the ramp starts.** Traffic begins climbing toward the afternoon peak. Nothing unusual; it does this every day.

**13:44 — CPU is 85%.** Not 60%. The autoscaler has not failed to act — it has not yet been *told*. Your metric agent scrapes every 60 seconds. The monitoring system averages over the last 5 minutes. The scaling policy evaluates once a minute. By the time a decision is made, the number it is deciding on describes a fleet that existed several minutes ago. An instance takes 90 seconds to boot, and another 60 seconds after that before its cache is warm and its JIT (Just-In-Time compiler — the runtime component that compiles hot code paths to machine code as the process runs) has compiled the hot paths. **The loop is steering by a mirror that shows where you were four minutes ago.**

**13:47 — it acts, hard.** It sees 85% against a 60% target, computes that it needs 1.4× the fleet, and orders 10 more instances. A minute later the metric still says 85%, because the 10 instances it ordered are still booting and have not served a single request. So it applies the same 1.4× ratio to a fleet size that *already includes the ten it ordered*, and orders fourteen more. Then twenty. This is not a bug in your configuration. It is the formula, run twice before the first answer arrived.

**13:52 — 40 instances, CPU 25%.** You are now paying for a fleet nearly twice the size you need, and every one of those instances is real, healthy, and idle. The controller notices, correctly, that 25% is well under 60%, and begins terminating. It terminates fast, because nothing told it not to.

**13:56 — 12 instances, CPU 95%, latency in the seconds.** And it starts again.

The fleet oscillates between 12 and 40 for the rest of the afternoon. Your p99 latency is *worse* than it would have been if the autoscaler had been switched off and the fleet pinned at 24. Your bill is higher. The graph looks like a heartbeat, and every engineer who sees it says "huh, that's weird" and moves on, because the service is technically up.

Then, three weeks later, the version that gets written up.

**02:14 — the recommendations database fails over.** Your service starts returning 503s. Every request now fails in 5 milliseconds instead of succeeding in 12, and **failing is cheap** — no query, no serialisation, no template render. CPU per instance drops to a few percent.

**02:19 — the autoscaler begins terminating instances.** It is doing exactly what it was configured to do. Utilisation is far below the setpoint, so the fleet must be too large. Over the next twenty-five minutes it takes you from 18 instances to 9.

**02:47 — the database comes back.** Real traffic — which never stopped arriving — meets a fleet half the size it needs. The service, which was about to recover, instead saturates. Your outage does not end when the dependency is fixed; it ends **270 seconds later**, and the last four and a half minutes of it were caused entirely by your own scaling policy.

Everything in both stories was standard configuration. The setpoint was reasonable, the metric was the default, the scrape interval was the default, and nobody made a mistake. This lesson is about why that is not enough, and it starts from one idea: **an autoscaler is a feedback control loop, and control loops have laws.**

## The Concept

### An autoscaler is a control loop, and dead time is the whole story

Strip away the cloud vocabulary and you have the oldest object in engineering:

- **Process variable (PV)** — what you measure. CPU utilisation, in-flight requests, queue depth.
- **Setpoint (SP)** — what you want it to be. "60% CPU."
- **Controller** — the rule that converts the error `PV − SP` into an action.
- **Actuator** — the thing that changes the world. Launching and terminating instances.
- **Plant** — the system being controlled. Your fleet.

The controller almost everyone runs is **target tracking**, and it is one line:

```text
desired_replicas = ceil( current_replicas × current_metric / target_metric )
```

That is not a simplification. It is verbatim what the Kubernetes Horizontal Pod Autoscaler computes. And with no delay anywhere, it is *exact*: if 10 instances are at 120% of a 60% target, then 20 instances will be at 60%, and the ratio cancels perfectly to `demand / per-instance-capacity`. The measured run confirms it — with zero delay the loop parks on the correct 24 instances and stays there, 33 launches in the whole hour, 100.0% of requests inside the objective.

Now introduce **dead time**: the delay between acting and being able to observe the effect of that action. This is the single most important number in the system, and in autoscaling it is enormous:

```text
metric scrape and pipeline                60 s
+ half the averaging window (60 s avg)    30 s     you see the middle of the window, not its end
+ half the decision interval (60 s)       30 s     on average you wait half an interval to be looked at
+ instance boot                           90 s
+ cache and JIT warmup                    60 s
-------------------------------------------------
TOTAL DEAD TIME                          270 s  =  4.5 minutes
```

Against a control loop that reacts every 60 seconds.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 496" width="100%" style="max-width:840px" role="img" aria-label="A block diagram of the autoscaling control loop drawn as four stages - fleet, metric pipeline, controller and provisioning - with the delay each stage adds written on it: 60 seconds of scrape and pipeline, 30 seconds for half the averaging window, 30 seconds for half the decision interval, 90 seconds of boot and 60 seconds of warmup, totalling 270 seconds or 4.5 minutes on the feedback path. Below it, the measured fleet size over a window where traffic is flat at 2400 requests per second: with zero dead time the fleet parks on the correct 24 instances, and with 210 seconds of dead time the same controller swings between 6 and 145 instances.">
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <text x="440" y="26" text-anchor="middle" font-size="14.5" font-weight="700" fill="currentColor">An autoscaler is a control loop, and its feedback path is 4.5 minutes long</text>
    <defs><marker id="p11-13-a1" markerWidth="10" markerHeight="10" refX="7" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker></defs>
    <defs><marker id="p11-13-a1r" markerWidth="10" markerHeight="10" refX="7" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#d64545"/></marker></defs>
    <rect x="36" y="56" width="166" height="74" rx="8" fill="#0fa07f" fill-opacity="0.12" stroke="#0fa07f" stroke-width="1.8"/>
    <text x="119" y="78" font-size="11.5" fill="#0fa07f" text-anchor="middle" font-weight="700">FLEET</text><text x="119" y="95" font-size="9" fill="currentColor" text-anchor="middle" opacity="0.9">the plant</text>
    <text x="119" y="110" font-size="9" fill="currentColor" text-anchor="middle" opacity="0.75">N instances serving</text>
    <text x="119" y="124" font-size="9.5" fill="#e0930f" text-anchor="middle" font-weight="700">dead time +0 s</text>
    <rect x="250" y="56" width="166" height="74" rx="8" fill="#7c5cff" fill-opacity="0.12" stroke="#7c5cff" stroke-width="1.8"/>
    <text x="333" y="78" font-size="11.5" fill="#7c5cff" text-anchor="middle" font-weight="700">METRIC PIPELINE</text>
    <text x="333" y="95" font-size="9" fill="currentColor" text-anchor="middle" opacity="0.9">scrape + 60 s average</text>
    <text x="333" y="110" font-size="9" fill="currentColor" text-anchor="middle" opacity="0.75">you see the past</text>
    <text x="333" y="124" font-size="9.5" fill="#e0930f" text-anchor="middle" font-weight="700">dead time +90 s</text>
    <rect x="464" y="56" width="166" height="74" rx="8" fill="#7c5cff" fill-opacity="0.12" stroke="#7c5cff" stroke-width="1.8"/>
    <text x="547" y="78" font-size="11.5" fill="#7c5cff" text-anchor="middle" font-weight="700">CONTROLLER</text>
    <text x="547" y="95" font-size="9" fill="currentColor" text-anchor="middle" opacity="0.9">compare to setpoint</text>
    <text x="547" y="110" font-size="9" fill="currentColor" text-anchor="middle" opacity="0.75">runs every 60 s</text>
    <text x="547" y="124" font-size="9.5" fill="#e0930f" text-anchor="middle" font-weight="700">dead time +30 s</text>
    <rect x="678" y="56" width="166" height="74" rx="8" fill="#7c5cff" fill-opacity="0.12" stroke="#7c5cff" stroke-width="1.8"/>
    <text x="761" y="78" font-size="11.5" fill="#7c5cff" text-anchor="middle" font-weight="700">PROVISIONING</text>
    <text x="761" y="95" font-size="9" fill="currentColor" text-anchor="middle" opacity="0.9">boot 90 s, warm 60 s</text>
    <text x="761" y="110" font-size="9" fill="currentColor" text-anchor="middle" opacity="0.75">then it is capacity</text>
    <text x="761" y="124" font-size="9.5" fill="#e0930f" text-anchor="middle" font-weight="700">dead time +150 s</text>
    <path d="M202 93 L 246 93" fill="none" stroke="currentColor" stroke-width="1.8" marker-end="url(#p11-13-a1)"/>
    <path d="M416 93 L 460 93" fill="none" stroke="currentColor" stroke-width="1.8" marker-end="url(#p11-13-a1)"/>
    <path d="M630 93 L 674 93" fill="none" stroke="currentColor" stroke-width="1.8" marker-end="url(#p11-13-a1)"/>
    <path d="M844 130 C 866 176, 866 186, 830 186 L 130 186 C 96 186, 92 176, 92 136" fill="none" stroke="#d64545" stroke-width="1.8" marker-end="url(#p11-13-a1r)"/>
    <text x="468" y="179" font-size="10" fill="#d64545" text-anchor="middle" font-weight="700">the actuation lands 4.5 minutes after the load changed</text>
    <rect x="36" y="200" width="808" height="36" rx="7" fill="#e0930f" fill-opacity="0.10" stroke="#e0930f" stroke-width="1.8"/>
    <text x="116" y="217" font-size="9" fill="currentColor" text-anchor="middle" opacity="0.85">scrape + pipeline</text>
    <text x="116" y="230" font-size="10" fill="#e0930f" text-anchor="middle" font-weight="700">60 s</text>
    <text x="262" y="217" font-size="9" fill="currentColor" text-anchor="middle" opacity="0.85">+ half the average</text>
    <text x="262" y="230" font-size="10" fill="#e0930f" text-anchor="middle" font-weight="700">30 s</text>
    <text x="412" y="217" font-size="9" fill="currentColor" text-anchor="middle" opacity="0.85">+ half the interval</text>
    <text x="412" y="230" font-size="10" fill="#e0930f" text-anchor="middle" font-weight="700">30 s</text><text x="540" y="217" font-size="9" fill="currentColor" text-anchor="middle" opacity="0.85">+ boot</text>
    <text x="540" y="230" font-size="10" fill="#e0930f" text-anchor="middle" font-weight="700">90 s</text><text x="644" y="217" font-size="9" fill="currentColor" text-anchor="middle" opacity="0.85">+ warm</text>
    <text x="644" y="230" font-size="10" fill="#e0930f" text-anchor="middle" font-weight="700">60 s</text><text x="768" y="217" font-size="9" fill="currentColor" text-anchor="middle" opacity="0.85">TOTAL</text>
    <text x="768" y="230" font-size="10" fill="#d64545" text-anchor="middle" font-weight="700">270 s = 4.5 min</text>
    <path d="M96 268 L 96 396 M96 396 L 844 396" fill="none" stroke="currentColor" stroke-width="1.4"/><path d="M96 375.5 L 844 375.5" fill="none" stroke="#7f7f7f" stroke-width="1.3" stroke-dasharray="5 4"/>
    <path d="M96 297.0 L 111 334.6 L 126 334.6 L 141 372.1 L 156 372.1 L 171 387.5 L 186 387.5 L 201 389.2 L 216 389.2 L 231 384.9 L 246 384.9 L 261 377.2 L 276 377.2 L 290 364.4 L 305 364.4 L 320 343.1 L 335 343.1 L 350 307.3 L 365 307.3 L 380 276.5 L 395 276.5 L 410 295.3 L 425 295.3 L 440 344.8 L 455 344.8 L 470 380.6 L 485 380.6 L 500 390.0 L 515 390.0 L 530 388.3 L 545 388.3 L 560 383.2 L 575 383.2 L 590 374.7 L 605 374.7 L 620 360.2 L 635 360.2 L 650 336.3 L 664 336.3 L 679 296.2 L 694 296.2 L 709 272.3 L 724 272.3 L 739 304.7 L 754 304.7 L 769 355.9 L 784 355.9 L 799 384.9 L 814 384.9 L 829 390.9 L 844 390.9" fill="none" stroke="#d64545" stroke-width="2.4"/>
    <path d="M96 376.4 L 111 375.5 L 126 375.5 L 141 374.7 L 156 374.7 L 171 375.5 L 186 375.5 L 201 375.5 L 216 375.5 L 231 375.5 L 246 375.5 L 261 374.7 L 276 374.7 L 290 374.7 L 305 374.7 L 320 374.7 L 335 374.7 L 350 375.5 L 365 375.5 L 380 375.5 L 395 375.5 L 410 374.7 L 425 374.7 L 440 374.7 L 455 374.7 L 470 374.7 L 485 374.7 L 500 374.7 L 515 374.7 L 530 375.5 L 545 375.5 L 560 374.7 L 575 374.7 L 590 374.7 L 605 374.7 L 620 375.5 L 635 375.5 L 650 374.7 L 664 374.7 L 679 374.7 L 694 374.7 L 709 374.7 L 724 374.7 L 739 375.5 L 754 375.5 L 769 375.5 L 784 375.5 L 799 375.5 L 814 375.5 L 829 375.5 L 844 375.5" fill="none" stroke="#0fa07f" stroke-width="2.4"/>
    <text x="96" y="410" font-size="9" fill="currentColor" opacity="0.7">1500 s</text><text x="844" y="410" font-size="9" fill="currentColor" text-anchor="end" opacity="0.7">3000 s</text>
    <text x="470" y="410" font-size="9" fill="currentColor" text-anchor="middle" opacity="0.75">traffic is FLAT at 2400 req/s across this whole window</text>
    <text x="90" y="272" font-size="9" fill="currentColor" text-anchor="end" opacity="0.7">150</text><text x="90" y="399" font-size="9" fill="currentColor" text-anchor="end" opacity="0.7">0</text>
    <text x="90" y="378.52" font-size="9" fill="#7f7f7f" text-anchor="end" font-weight="700">24</text><text x="96" y="258" font-size="9.5" fill="currentColor" opacity="0.85">instances</text>
    <text x="844" y="258" font-size="9.5" fill="currentColor" text-anchor="end" font-weight="700" opacity="0.9">measured, same traffic, same controller</text>
    <rect x="96" y="424" width="366" height="42" rx="7" fill="#0fa07f" fill-opacity="0.10" stroke="#0fa07f" stroke-width="1.8"/>
    <rect x="478" y="424" width="366" height="42" rx="7" fill="#d64545" fill-opacity="0.10" stroke="#d64545" stroke-width="1.8"/>
    <text x="110" y="441" font-size="10" fill="#0fa07f" font-weight="700">dead time 0 s: parks on 24</text>
    <text x="110" y="456" font-size="9.3" fill="currentColor" opacity="0.92">33 launches all hour, SLO 100.0%</text>
    <text x="492" y="441" font-size="10" fill="#d64545" font-weight="700">dead time 210 s: swings 6 to 145</text>
    <text x="492" y="456" font-size="9.3" fill="currentColor" opacity="0.92">539 launches, SLO 57.3%, 2.1x the bill</text>
    <text x="440" y="482" font-size="11" text-anchor="middle" fill="currentColor" opacity="0.9">Dead time decides whether the loop is a controller or an oscillator.</text>
  </g>
</svg>
```

Here is the rule that follows, and it explains almost every autoscaling complaint you will ever hear:

> **A control loop cannot stabilise a plant whose dead time exceeds its reaction period.** It will oscillate. Not "might" — the phase lag introduced by the delay eventually exceeds the loop's phase margin and the negative feedback becomes positive feedback at some frequency. Åström and Murray work the general case in *Feedback Systems* (Princeton, 2008), chapter 10; the practical consequence for you is that a delayed loop settles into a **limit cycle** with a period of roughly twice the dead time.

The simulator sweeps dead time with everything else held identical. The reaction period is 60 seconds throughout:

| dead time | plateau fleet | swing | direction flips | launches | SLO | cost |
|---|---|---|---|---|---|---|
| 0 s | 24–25 | 1 | 0 | 33 | 100.0% | 1206 inst-min |
| 60 s | 24–26 | 2 | 0 | 32 | 100.0% | 1229 |
| 120 s | 23–29 | 6 | 3 | 69 | 100.0% | 1291 |
| **210 s** | **6–145** | **139** | 3 | **539** | **57.3%** | **2547** |
| 360 s | 5–400 | 395 | 3 | 802 | 65.2% | 3956 |

The traffic across the measured plateau is **flat**. The demand does not change. At 60 seconds of dead time — equal to the reaction period — the loop still settles. At 120 seconds it starts hunting: the fleet is never still, though nothing breaks yet. At 210 seconds, which is what a real cloud gives you before you have tuned anything, the same controller swings 139 instances and misses the objective for 42.7% of requests. The 360-second row looks *better* on SLO than the 210-second row, and that is not a mercy: it only got there by slamming into the 400-instance ceiling and staying there, buying the SLO back at **3.3× the bill**. Neither row is a controller. One is an oscillator and the other is an oscillator with its head against the wall.

The theory predicts the period, too. For 210 seconds of dead time, `2 × D = 7.0 minutes`; the measured plateau limit cycle runs at **9.6 minutes**. Close enough to confirm the mechanism, and the gap is the extra lag the averaging window and the discrete decision interval add on top.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 468" width="100%" style="max-width:840px" role="img" aria-label="Measured fleet size over a 70 minute run for two identical target-tracking autoscalers that differ only in dead time, plotted against the dashed demand curve that shows how many instances are actually needed. With zero dead time the green curve tracks demand exactly and settles at 24 instances on the flat plateau. With 210 seconds of dead time the red curve overshoots to 145 instances and collapses to 6, repeatedly, while the traffic underneath it does not change.">
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <text x="440" y="26" text-anchor="middle" font-size="14.5" font-weight="700" fill="currentColor">Same traffic, same controller, same setpoint. Only the dead time differs.</text>
    <path d="M92 62 L 92 306 M92 306 L 844 306" fill="none" stroke="currentColor" stroke-width="1.4"/><path d="M92 257.2 L 844 257.2" fill="none" stroke="currentColor" stroke-width="1" opacity="0.15"/>
    <text x="86" y="260.2" font-size="9" fill="currentColor" text-anchor="end" opacity="0.7">30</text><path d="M92 208.4 L 844 208.4" fill="none" stroke="currentColor" stroke-width="1" opacity="0.15"/>
    <text x="86" y="211.4" font-size="9" fill="currentColor" text-anchor="end" opacity="0.7">60</text><path d="M92 159.6 L 844 159.6" fill="none" stroke="currentColor" stroke-width="1" opacity="0.15"/>
    <text x="86" y="162.6" font-size="9" fill="currentColor" text-anchor="end" opacity="0.7">90</text><path d="M92 110.8 L 844 110.8" fill="none" stroke="currentColor" stroke-width="1" opacity="0.15"/>
    <text x="86" y="113.80000000000001" font-size="9" fill="currentColor" text-anchor="end" opacity="0.7">120</text><path d="M92 62.0 L 844 62.0" fill="none" stroke="currentColor" stroke-width="1" opacity="0.15"/>
    <text x="86" y="65.0" font-size="9" fill="currentColor" text-anchor="end" opacity="0.7">150</text><text x="86" y="309" font-size="9" fill="currentColor" text-anchor="end" opacity="0.7">0</text>
    <path d="M92 296.3 L 103 295.9 L 113 296.7 L 124 296.5 L 135 296.1 L 146 296.4 L 156 294.9 L 167 293.1 L 178 291.9 L 189 290.1 L 199 288.6 L 210 286.7 L 221 287.1 L 232 283.8 L 242 282.7 L 253 283.0 L 264 281.2 L 275 278.6 L 285 278.0 L 296 275.9 L 307 275.0 L 318 272.7 L 328 270.6 L 339 269.9 L 350 269.7 L 361 266.6 L 371 267.2 L 382 267.0 L 393 267.4 L 404 266.2 L 414 266.0 L 425 263.7 L 436 266.7 L 447 268.2 L 457 267.0 L 468 265.8 L 479 266.5 L 489 265.3 L 500 265.3 L 511 266.6 L 522 267.0 L 532 269.2 L 543 267.2 L 554 266.3 L 565 268.9 L 575 266.8 L 586 268.0 L 597 269.7 L 608 269.6 L 618 266.2 L 629 265.9 L 640 269.1 L 651 271.6 L 661 274.8 L 672 278.1 L 683 279.5 L 694 283.9 L 704 286.1 L 715 286.6 L 726 289.5 L 737 293.0 L 747 292.7 L 758 293.2 L 769 293.0 L 780 292.8 L 790 293.4 L 801 293.3 L 812 293.0 L 823 293.0 L 833 293.1" fill="none" stroke="#3553ff" stroke-width="2" stroke-dasharray="6 4"/>
    <path d="M92 296.2 L 103 296.2 L 113 296.2 L 124 296.2 L 135 294.6 L 146 294.6 L 156 294.6 L 167 293.0 L 178 293.0 L 189 291.4 L 199 288.1 L 210 283.2 L 221 276.7 L 232 268.6 L 242 262.1 L 253 262.1 L 264 267.0 L 275 278.3 L 285 288.1 L 296 288.1 L 307 278.3 L 318 260.5 L 328 229.5 L 339 177.5 L 350 118.9 L 361 117.3 L 371 188.9 L 382 260.5 L 393 289.7 L 404 293.0 L 414 284.9 L 425 270.2 L 436 245.8 L 447 205.1 L 457 136.8 L 468 78.3 L 479 114.1 L 489 208.4 L 500 276.7 L 511 294.6 L 522 291.4 L 532 281.6 L 543 265.3 L 554 237.7 L 565 192.1 L 575 115.7 L 586 70.1 L 597 131.9 L 608 229.5 L 618 284.9 L 629 296.2 L 640 291.4 L 651 281.6 L 661 265.3 L 672 237.7 L 683 192.1 L 694 145.0 L 704 164.5 L 715 237.7 L 726 288.1 L 737 299.5 L 747 299.5 L 758 294.6 L 769 286.5 L 780 273.5 L 790 250.7 L 801 227.9 L 812 237.7 L 823 271.8 L 833 294.6" fill="none" stroke="#d64545" stroke-width="2.4"/>
    <path d="M92 296.2 L 103 296.2 L 113 296.2 L 124 294.6 L 135 294.6 L 146 296.2 L 156 296.2 L 167 294.6 L 178 293.0 L 189 291.4 L 199 289.7 L 210 288.1 L 221 286.5 L 232 286.5 L 242 284.9 L 253 281.6 L 264 281.6 L 275 280.0 L 285 278.3 L 296 276.7 L 307 275.1 L 318 273.5 L 328 271.8 L 339 270.2 L 350 268.6 L 361 268.6 L 371 267.0 L 382 265.3 L 393 267.0 L 404 267.0 L 414 267.0 L 425 265.3 L 436 265.3 L 447 265.3 L 457 267.0 L 468 267.0 L 479 265.3 L 489 265.3 L 500 265.3 L 511 265.3 L 522 267.0 L 532 265.3 L 543 265.3 L 554 267.0 L 565 265.3 L 575 265.3 L 586 265.3 L 597 267.0 L 608 267.0 L 618 267.0 L 629 267.0 L 640 265.3 L 651 267.0 L 661 270.2 L 672 273.5 L 683 275.1 L 694 278.3 L 704 280.0 L 715 283.2 L 726 286.5 L 737 288.1 L 747 291.4 L 758 293.0 L 769 293.0 L 780 293.0 L 790 291.4 L 801 291.4 L 812 293.0 L 823 293.0 L 833 291.4" fill="none" stroke="#0fa07f" stroke-width="2.4"/>
    <path d="M145.7 306 L 145.7 312" fill="none" stroke="currentColor" stroke-width="1.2"/>
    <text x="145.71428571428572" y="324" font-size="8.5" fill="currentColor" text-anchor="middle" opacity="0.75">ramp starts</text>
    <path d="M360.6 306 L 360.6 312" fill="none" stroke="currentColor" stroke-width="1.2"/>
    <text x="360.57142857142856" y="324" font-size="8.5" fill="currentColor" text-anchor="middle" opacity="0.75">plateau: FLAT traffic</text>
    <path d="M629.1 306 L 629.1 312" fill="none" stroke="currentColor" stroke-width="1.2"/>
    <text x="629.1428571428571" y="324" font-size="8.5" fill="currentColor" text-anchor="middle" opacity="0.75">ramp down</text><text x="92" y="338" font-size="9" fill="currentColor" opacity="0.7">0 s</text>
    <text x="844" y="338" font-size="9" fill="currentColor" text-anchor="end" opacity="0.7">4200 s</text><text x="92" y="54" font-size="9.5" fill="currentColor" opacity="0.85">instances</text>
    <text x="112" y="82" font-size="10" fill="#3553ff" font-weight="700">- -  demand / 100 req-per-instance = the fleet you need</text>
    <text x="112" y="100" font-size="10" fill="#0fa07f" font-weight="700">dead time 0 s</text><text x="112" y="118" font-size="10" fill="#d64545" font-weight="700">dead time 210 s (the cloud default)</text>
    <rect x="92" y="356" width="366" height="84" rx="8" fill="#0fa07f" fill-opacity="0.10" stroke="#0fa07f" stroke-width="1.8"/>
    <rect x="478" y="356" width="366" height="84" rx="8" fill="#d64545" fill-opacity="0.10" stroke="#d64545" stroke-width="1.8"/>
    <text x="108" y="376" font-size="11" fill="#0fa07f" font-weight="700">STABLE - dead time 0 s</text><text x="108" y="396" font-size="9.5" fill="currentColor" opacity="0.92">plateau 24-25, swing 1, 0 flips</text>
    <text x="108" y="411" font-size="9.5" fill="currentColor" opacity="0.92">33 launches in the whole hour</text>
    <text x="108" y="426" font-size="9.5" fill="currentColor" opacity="0.92">SLO 100.0%, 1206 instance-minutes</text>
    <text x="494" y="376" font-size="11" fill="#d64545" font-weight="700">OSCILLATING - dead time 210 s</text>
    <text x="494" y="396" font-size="9.5" fill="currentColor" opacity="0.92">plateau 6-145, swing 139, 3 flips</text>
    <text x="494" y="411" font-size="9.5" fill="currentColor" opacity="0.92">539 launches - 16x the churn</text>
    <text x="494" y="426" font-size="9.5" fill="currentColor" opacity="0.92">SLO 57.3%, 2547 instance-minutes</text>
    <text x="440" y="454" font-size="11" text-anchor="middle" fill="currentColor" opacity="0.9">On the plateau the traffic is constant and the fleet still swings 6 to 145.</text>
  </g>
</svg>
```

**Everything else in this lesson is a way of coping with that number.** You can reduce the dead time (faster boots, shorter scrape intervals, pre-warmed instances), or you can slow the loop down until its reaction period exceeds the dead time. There is no third option, and every knob in the next sections is one of those two wearing a different name.

### Choosing the metric — the part everyone gets wrong

CPU is the default in every tool. It is usually the wrong signal, for three independent reasons.

**It is not proportional to load for anything I/O-bound.** An instance waiting on a database is consuming almost no CPU and is completely full: every worker thread is blocked on a socket, and the next request queues. The simulator models a service with 8 worker slots and 6 ms of CPU per request. Normally the service time is 12 ms, so CPU is the binding constraint at 166.7 req/s and the 60% CPU setpoint lands you at a comfortable 100 req/s per instance. Then the dependency degrades and service time rises to 120 ms. Now the slots bind first: `8 / 0.120 = 67 req/s`, and **at 67 req/s — completely saturated — that instance reports 40% CPU.** The controller reads "idle" and *scales in*.

**It falls when your service starts failing.** Returning an error is dramatically cheaper than serving a request. During an incident, CPU goes down. Any controller that treats "CPU below setpoint" as "too many instances" will shrink your fleet in the middle of an outage. This is the second scenario in The Problem, and it is measured in section 4.

**It is lagging.** CPU rises after queues have already formed. By the time it moves, the latency damage is done.

The better signals, in order:

1. **Concurrency — in-flight requests per instance.** This is the most directly proportional to load there is, and it is [Little's Law](../../08-concurrency-and-performance/01-why-concurrency/) made operational: `L = λ × W`. The number of requests in flight is the arrival rate multiplied by how long each one takes. It rises when traffic rises *and* when the dependency slows, which is exactly the behaviour you want, because both of those reduce how much traffic one instance can take.
2. **Queue depth, or the age of the oldest item, for worker fleets.** For anything consuming from a queue this is the right answer and it is not close. [Backpressure, Consumer Lag & Flow Control](../../06-messaging-and-pub-sub/09-backpressure-lag-and-flow-control/) covers consumer lag as a signal; [Backpressure, Queueing & Load Shedding](../../08-concurrency-and-performance/11-backpressure-and-load-shedding/) explains why **age** beats **depth** — a count is meaningless without a rate, and the rate moves.
3. **Requests per second per instance**, but only when the cost of a request is uniform. The moment you have a cheap endpoint and an expensive one behind the same autoscaling group, RPS stops being a capacity signal.
4. **Latency — as a guardrail only, never as the primary signal.** This one needs saying properly, because scaling on latency is intuitive and wrong. Latency is **not monotonic in capacity**: it rises for many reasons that adding instances cannot fix — a slow dependency, a lock, a bad query plan, a garbage-collection pause, a saturated NAT gateway. A loop that adds machines whenever latency rises will respond to *someone else's* outage by tripling your fleet, and if the shared bottleneck is downstream it will make things worse (see the metastable failure below). Use latency as a *veto* — "do not scale in while p99 is elevated" — never as the thing you divide by.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 434" width="100%" style="max-width:840px" role="img" aria-label="Measured fleet size for four autoscalers driven by four different metrics against the same traffic, with the grey dashed line showing how many instances are actually required. The shaded region is a phase where the database slows a request from 12 to 120 milliseconds while its CPU cost stays at 6 milliseconds. In that region the CPU-driven scaler stays flat and far below the required line while every worker slot is occupied; the in-flight scaler overshoots to 266 instances; the backlog-age scaler responds late; and the max of CPU and in-flight tracks the required line most closely for the least money.">
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <text x="440" y="26" text-anchor="middle" font-size="14.5" font-weight="700" fill="currentColor">The metric decides. CPU falls when an I/O-bound service saturates.</text>
    <rect x="246.3" y="62" width="231.4" height="238" fill="#e0930f" fill-opacity="0.11"/><path d="M92 62 L 92 300 M92 300 L 632 300" fill="none" stroke="currentColor" stroke-width="1.4"/>
    <path d="M92 220.7 L 632 220.7" fill="none" stroke="currentColor" stroke-width="1" opacity="0.15"/>
    <text x="86" y="223.66666666666669" font-size="9" fill="currentColor" text-anchor="end" opacity="0.7">100</text>
    <path d="M92 141.3 L 632 141.3" fill="none" stroke="currentColor" stroke-width="1" opacity="0.15"/>
    <text x="86" y="144.33333333333334" font-size="9" fill="currentColor" text-anchor="end" opacity="0.7">200</text><path d="M92 62.0 L 632 62.0" fill="none" stroke="currentColor" stroke-width="1" opacity="0.15"/>
    <text x="86" y="65.0" font-size="9" fill="currentColor" text-anchor="end" opacity="0.7">300</text><text x="86" y="303" font-size="9" fill="currentColor" text-anchor="end" opacity="0.7">0</text>
    <path d="M92 296.8 L 100 296.8 L 107 296.8 L 115 296.8 L 123 296.8 L 131 296.8 L 138 296.4 L 146 295.9 L 154 295.4 L 161 294.9 L 169 294.4 L 177 294.0 L 185 293.5 L 192 293.0 L 200 292.5 L 208 292.1 L 215 291.6 L 223 291.1 L 231 290.6 L 239 290.2 L 246 289.7 L 254 289.2 L 262 288.7 L 269 288.3 L 277 286.0 L 285 282.5 L 293 279.7 L 300 276.8 L 308 274.0 L 316 271.1 L 323 268.3 L 331 268.3 L 339 268.3 L 347 268.3 L 354 268.3 L 362 268.3 L 370 268.3 L 377 268.3 L 385 268.3 L 393 268.3 L 401 268.3 L 408 268.3 L 416 268.3 L 424 268.3 L 431 268.3 L 439 268.3 L 447 274.0 L 455 279.7 L 462 285.4 L 470 287.3 L 478 287.3 L 485 288.2 L 493 289.0 L 501 289.8 L 509 290.7 L 516 291.5 L 524 292.4 L 532 293.2 L 539 294.1 L 547 294.9 L 555 295.8 L 563 295.8 L 570 295.8 L 578 295.8 L 586 295.8 L 593 295.8 L 601 295.8 L 609 295.8 L 617 295.8 L 624 295.8" fill="none" stroke="#7f7f7f" stroke-width="2.2" stroke-dasharray="6 4"/>
    <path d="M92 295.2 L 100 295.2 L 107 295.2 L 115 295.2 L 123 295.2 L 131 295.2 L 138 295.2 L 146 295.2 L 154 294.4 L 161 293.7 L 169 292.9 L 177 292.1 L 185 291.3 L 192 290.5 L 200 290.5 L 208 288.9 L 215 288.1 L 223 287.3 L 231 287.3 L 239 287.3 L 246 286.5 L 254 285.7 L 262 284.1 L 269 276.2 L 277 258.7 L 285 246.1 L 293 223.8 L 300 199.2 L 308 184.2 L 316 151.6 L 323 141.3 L 331 116.7 L 339 116.7 L 347 113.6 L 354 111.2 L 362 111.2 L 370 111.2 L 377 111.2 L 385 111.2 L 393 111.2 L 401 111.2 L 408 111.2 L 416 111.2 L 424 111.2 L 431 111.2 L 439 111.2 L 447 111.2 L 455 89.0 L 462 89.0 L 470 110.4 L 478 110.4 L 485 110.4 L 493 110.4 L 501 110.4 L 509 129.4 L 516 129.4 L 524 129.4 L 532 129.4 L 539 129.4 L 547 146.9 L 555 146.9 L 563 146.9 L 570 146.9 L 578 146.9 L 586 162.8 L 593 162.8 L 601 162.8 L 609 162.8 L 617 162.8 L 624 177.0" fill="none" stroke="#e0930f" stroke-width="2.2"/>
    <path d="M92 295.2 L 100 295.2 L 107 296.0 L 115 296.0 L 123 296.0 L 131 296.0 L 138 296.0 L 146 296.8 L 154 296.8 L 161 293.7 L 169 289.7 L 177 289.7 L 185 289.7 L 192 289.7 L 200 291.3 L 208 291.3 L 215 291.3 L 223 291.3 L 231 291.3 L 239 292.9 L 246 292.9 L 254 285.7 L 262 277.8 L 269 277.8 L 277 277.0 L 285 277.0 L 293 279.4 L 300 279.4 L 308 279.4 L 316 279.4 L 323 258.7 L 331 231.8 L 339 231.8 L 347 231.8 L 354 231.8 L 362 238.9 L 370 238.9 L 377 238.9 L 385 238.9 L 393 238.9 L 401 245.3 L 408 245.3 L 416 245.3 L 424 245.3 L 431 245.3 L 439 250.8 L 447 250.8 L 455 250.8 L 462 250.8 L 470 250.8 L 478 256.4 L 485 256.4 L 493 256.4 L 501 256.4 L 509 256.4 L 516 261.1 L 524 261.1 L 532 261.1 L 539 261.1 L 547 261.1 L 555 265.1 L 563 265.1 L 570 265.1 L 578 265.1 L 586 265.1 L 593 269.1 L 601 269.1 L 609 269.1 L 617 269.1 L 624 269.1" fill="none" stroke="#7c5cff" stroke-width="2.2"/>
    <path d="M92 295.2 L 100 295.2 L 107 295.2 L 115 295.2 L 123 295.2 L 131 295.2 L 138 295.2 L 146 295.2 L 154 294.4 L 161 293.7 L 169 292.9 L 177 292.1 L 185 291.3 L 192 290.5 L 200 290.5 L 208 288.9 L 215 288.1 L 223 287.3 L 231 287.3 L 239 287.3 L 246 286.5 L 254 285.7 L 262 284.1 L 269 283.3 L 277 282.5 L 285 282.5 L 293 281.0 L 300 275.4 L 308 273.0 L 316 266.7 L 323 266.7 L 331 258.7 L 339 258.7 L 347 254.0 L 354 252.4 L 362 252.4 L 370 249.2 L 377 249.2 L 385 249.2 L 393 249.2 L 401 249.2 L 408 249.2 L 416 249.2 L 424 249.2 L 431 249.2 L 439 249.2 L 447 249.2 L 455 249.2 L 462 249.2 L 470 254.8 L 478 254.8 L 485 254.8 L 493 254.8 L 501 254.8 L 509 259.5 L 516 259.5 L 524 259.5 L 532 259.5 L 539 259.5 L 547 264.3 L 555 264.3 L 563 264.3 L 570 264.3 L 578 264.3 L 586 268.3 L 593 268.3 L 601 268.3 L 609 268.3 L 617 268.3 L 624 271.4" fill="none" stroke="#0fa07f" stroke-width="2.6"/>
    <path d="M92 295.2 L 100 295.2 L 107 295.2 L 115 295.2 L 123 295.2 L 131 295.2 L 138 295.2 L 146 295.2 L 154 294.4 L 161 293.7 L 169 292.9 L 177 292.1 L 185 291.3 L 192 290.5 L 200 290.5 L 208 288.9 L 215 288.1 L 223 287.3 L 231 287.3 L 239 287.3 L 246 286.5 L 254 285.7 L 262 284.1 L 269 283.3 L 277 282.5 L 285 282.5 L 293 281.0 L 300 280.2 L 308 280.2 L 316 280.2 L 323 280.2 L 331 280.2 L 339 282.5 L 347 282.5 L 354 282.5 L 362 282.5 L 370 282.5 L 377 284.9 L 385 284.9 L 393 284.9 L 401 284.9 L 408 284.9 L 416 286.5 L 424 286.5 L 431 286.5 L 439 286.5 L 447 286.5 L 455 286.5 L 462 288.1 L 470 288.1 L 478 284.9 L 485 281.8 L 493 279.4 L 501 279.4 L 509 279.4 L 516 279.4 L 524 279.4 L 532 281.8 L 539 281.8 L 547 281.8 L 555 281.8 L 563 281.8 L 570 284.1 L 578 284.1 L 586 284.1 L 593 284.1 L 601 284.1 L 609 285.7 L 617 285.7 L 624 285.7" fill="none" stroke="#d64545" stroke-width="2.6"/>
    <text x="362.0" y="54" font-size="9" fill="#e0930f" text-anchor="middle" font-weight="700">dependency slow: 12 ms -> 120 ms</text>
    <text x="92" y="54" font-size="9.5" fill="currentColor" opacity="0.85">instances</text><text x="92" y="316" font-size="9" fill="currentColor" opacity="0.7">0 s</text>
    <text x="632" y="316" font-size="9" fill="currentColor" text-anchor="end" opacity="0.7">4200 s</text>
    <rect x="648" y="62" width="196" height="132" rx="8" fill="#d64545" fill-opacity="0.10" stroke="#d64545" stroke-width="1.8"/>
    <text x="660" y="82" font-size="10" fill="#d64545" font-weight="700">CPU SCALES IN</text><text x="660" y="98" font-size="8.8" fill="currentColor" opacity="0.92">In the shaded phase every</text>
    <text x="660" y="112" font-size="8.8" fill="currentColor" opacity="0.92">worker slot is full and CPU</text><text x="660" y="126" font-size="8.8" fill="currentColor" opacity="0.92">utilisation reads 40%</text>
    <text x="660" y="140" font-size="8.8" fill="currentColor" opacity="0.92">because the CPU is</text><text x="660" y="154" font-size="8.8" fill="currentColor" opacity="0.92">WAITING, not working.</text>
    <text x="660" y="182" font-size="9.5" fill="#d64545" font-weight="700">worst rho = 2.33</text>
    <rect x="648" y="206" width="196" height="94" rx="8" fill="#e0930f" fill-opacity="0.10" stroke="#e0930f" stroke-width="1.8"/>
    <text x="660" y="226" font-size="10" fill="#e0930f" font-weight="700">IN-FLIGHT OVERSHOOTS</text><text x="660" y="242" font-size="8.8" fill="currentColor" opacity="0.92">it is proportional to</text>
    <text x="660" y="256" font-size="8.8" fill="currentColor" opacity="0.92">lambda x W, so a 10x</text><text x="660" y="270" font-size="8.8" fill="currentColor" opacity="0.92">slower W buys 10x the</text>
    <text x="660" y="284" font-size="8.8" fill="currentColor" opacity="0.92">fleet. Safe. Expensive.</text>
    <rect x="92" y="330" width="752" height="70" rx="8" fill="#7f7f7f" fill-opacity="0.06" stroke="#7f7f7f" stroke-width="1.8"/>
    <text x="104" y="348" font-size="9.5" fill="#7f7f7f" font-weight="700">- -  the fleet actually needed</text><text x="104" y="368" font-size="9.5" fill="#d64545" font-weight="700">CPU 60%</text>
    <text x="304" y="368" font-size="9.2" fill="currentColor" opacity="0.9">SLO 45.1%   1251 inst-min</text><text x="104" y="390" font-size="9.5" fill="#e0930f" font-weight="700">in-flight 1.2/instance</text>
    <text x="304" y="390" font-size="9.2" fill="currentColor" opacity="0.9">SLO 98.7%   9857 inst-min</text><text x="480" y="368" font-size="9.5" fill="#7c5cff" font-weight="700">backlog age 0.30 s</text>
    <text x="680" y="368" font-size="9.2" fill="currentColor" opacity="0.9">SLO 76.3%   2809 inst-min</text><text x="480" y="390" font-size="9.5" fill="#0fa07f" font-weight="700">max(CPU, in-flight)</text>
    <text x="680" y="390" font-size="9.2" fill="currentColor" opacity="0.9">SLO 86.4%   2627 inst-min</text>
    <text x="440" y="420" font-size="11" text-anchor="middle" fill="currentColor" opacity="0.9">An instance waiting on a database is at 40% CPU and completely full.</text>
  </g>
</svg>
```

The measurement runs the same workload through four controllers while the dependency degrades from 12 ms to 120 ms over ten minutes and recovers:

| metric | fleet in the slow phase | worst ρ | SLO | cost |
|---|---|---|---|---|
| CPU 60% | 15–25 | **2.33** | **45.1%** | 1251 inst-min |
| in-flight = 1.2 per instance | 200–266 | 0.87 | 98.7% | **9857** |
| backlog age 0.30 s | 52–86 | 1.63 | 76.3% | 2809 |
| **max(CPU, in-flight)** | 42–64 | 1.42 | 86.4% | 2627 |

Read the failure modes, not just the winners. **CPU does not lag here — it points the wrong way**, holding the fleet at 15–25 instances while utilisation runs at 2.33× capacity, and delivering 45.1%. **In-flight concurrency never under-provisions** — worst ρ of 0.87, the only row that stays under capacity throughout — but its setpoint encodes an assumption about service time, so when `W` rises tenfold it buys tenfold the fleet, and 9857 instance-minutes is nearly 8× the CPU row's bill. That is the honest trade: **concurrency errs toward over-provisioning, which costs money; CPU errs toward under-provisioning, which costs an outage.** **Backlog age** only speaks once you are already behind; that makes it right for worker fleets, where a queue is the normal state, and late for a user-facing request path.

The answer to ship is the last row: **scale on whichever resource is actually saturated.** `max(CPU utilisation, slot utilisation)` tracks the required fleet in both regimes, because the bottleneck *moved* and the controller followed it. Every serious autoscaler supports multiple metrics and takes the maximum of the resulting recommendations. Use that.

### Reactive, scheduled and predictive

**Reactive** is what everything above describes: observe, compare, act. It is always late by the dead time, by construction. It cannot be otherwise — it is responding to something that already happened.

**Scheduled** sets capacity by the clock. It has zero lag for the part of your load you can predict, which is usually most of it: the morning ramp, the evening decline, the Monday spike, the marketing send that went into a calendar three weeks ago. It is the highest-value, lowest-technology fix available, and it is a cron entry.

**Predictive** forecasts ahead from history and provisions before the load arrives. Real, useful when your pattern is strongly periodic, and worth exactly nothing on the day the pattern breaks — which is the day you needed it.

The recommendation mature fleets converge on is **scheduled for the envelope, reactive for the residual**: put a floor under the predictable shape so the reactive loop never has to chase a large, fast, foreseeable change, and let it handle only the noise on top. Section 7 measures it over a simulated day with a known 12:00 campaign send. Reactive alone attained **98.56%** with **1,187,371 requests outside the objective**. Adding two scheduled floors — a daytime minimum of 14, and 42 for the 75 minutes around the campaign — reached **100.00%, zero violating requests, for 20.1% more instance-minutes**. You bought the last 1.44 points of SLO for a fifth of the fleet, and the mechanism is a schedule, not an algorithm.

### Stopping the oscillation, and what each knob costs

Every stabiliser trades responsiveness for stability. State the cost in the same breath as the benefit, or you will end up with an autoscaler that is beautifully stable and permanently four minutes behind.

**Count what you measured, not what you have.** This is first because it is free and because almost nobody does it. The HPA formula multiplies `current_replicas` by a ratio derived from a metric that came off the fleet you had a dead time *ago*. When 15 instances are still booting, `current_replicas` already contains them, and the ratio orders them a second time. Dividing by the fleet size that actually produced the measurement removes the double-count entirely, at zero cost in lag. Measured against a flash crowd with 360 seconds of dead time, this one change took the plateau swing from **395 to 19**, launches from **1216 to 60**, and the SLO from **49.4% to 80.0%**.

**Asymmetric rates: scale out fast, scale in slowly.** The cost of being too small is an outage. The cost of being too large is money. These are not the same units and should never get the same time constant. Scale out immediately; scale in over minutes.

**Cooldown / stabilisation windows.** After acting, refuse to act again for a fixed period — long on scale-in (300 s is a good default), short or zero on scale-out. Cost: you cannot respond to a real change inside the window.

**Hysteresis.** Separate thresholds per direction — out above 1.10× the setpoint, in below 0.70×, nothing in between. This is what stops the loop chasing measurement noise; measured, it cut direction flips from 5 to 1 and launches from 58 to 46. Cost: you tolerate being off-target inside the dead band.

**Rate limits on change per interval.** At most 2× out, 10% in. This mostly buys *insurance* — it bounds the blast radius of one bad metric scrape. Measured, rate limits alone on the naive formula took launches from 1216 to 291 and capped the peak at 194 instead of 400.

**Smoothing the input signal.** Longer averaging windows do reduce swing. **They also add lag, which is the thing causing the problem.** A 300-second average adds roughly 150 seconds of dead time. In the measurement it took 6 instances off the swing and cost **13.3 points of SLO**. This is the last knob to reach for, and the first one people reach for.

The cumulative ladder, all against 360 seconds of dead time and a flash crowd:

| configuration | swing | flips | launches | SLO | cost |
|---|---|---|---|---|---|
| naive HPA formula | 395 | 3 | 1216 | 49.4% | 5368 |
| + divide by the fleet you measured | 19 | 5 | 60 | 80.0% | 1280 |
| + scale-in cooldown 300 s | 19 | 5 | 58 | 80.0% | 1309 |
| + hysteresis (out > 1.10, in < 0.70) | 21 | 1 | 46 | 80.5% | 1422 |
| + asymmetric rates (out ×2, in 10%) | 18 | 1 | 46 | 80.5% | 1762 |
| + 300 s metric smoothing | 12 | 1 | 38 | **67.2%** | 1554 |

Note what the last three rows do and do not buy. They take the churn out — flips from 5 to 1 — and cost 24% more money, and they move the SLO by half a point. **Stabilisers fix oscillation. They do not fix lag.** The 80% ceiling in that table is the dead time itself, and no amount of cooldown will move it. That is why the next lever is scheduling, and the one after that is making the instance boot faster.

Recommended starting values, to be measured and then changed:

```text
target                    50-60% CPU, or 60-70% of the concurrency limit
scale-out stabilisation   0 s      (never delay growth)
scale-in stabilisation    300 s
scale-out rate limit      double every 60 s, or +4 instances per 60 s
scale-in rate limit       10% of the fleet per 60 s
hysteresis / tolerance    +/- 10% around the setpoint
metric window             60 s     (longer only if the signal is genuinely noisy)
minimum size              enough to survive the loss of one failure domain
```

### Scale-in is the dangerous direction

Scaling out costs money and takes time. Scaling in breaks things, and here is the list:

- **In-flight requests.** Terminating an instance kills the requests it is serving unless you drain first. You need connection draining at the load balancer and graceful shutdown in the process — deregister, stop accepting, finish what you have, then exit. [Health Checks & Probes](../../09-logging-monitoring-and-observability/08-health-checks-and-probes/) builds this; the autoscaling-specific part is that the *termination hook* must be longer than your longest request, and it usually is not.
- **Sticky sessions.** Lesson 6 covered where the state actually went. If anything is pinned to an instance, terminating it loses that thing. This is the single best argument for the statelessness that lesson argued for.
- **Cold caches on whatever replaces it.** You did not remove one instance's load — you redistributed it onto instances whose caches are sized for their old share, and then you brought a cold one back an hour later.
- **Long-running work.** An instance processing a 40-minute batch job must not be selected for termination because the fleet average dipped. Every autoscaler has instance scale-in protection or an equivalent; a worker that takes a job should set it, and clear it when the job finishes.
- **The spike you cannot absorb.** Scaling in during a lull is exactly when you lose the headroom to absorb the next burst, and bursts do not announce themselves.

### The failure modes that matter

#### Scaling in during an outage

Covered in the story above; here it is measured. Constant 1800 req/s, the stabilised controller, and a dependency that dies for 25 minutes. Requests now fail in 5 ms instead of succeeding in 12, so CPU per instance collapses.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 426" width="100%" style="max-width:840px" role="img" aria-label="A measured timeline of fleet size through a 25 minute dependency outage. The shaded band marks the outage. Without a guard the fleet falls from 18 instances to 9 while the dependency is down, because failing fast is cheap and CPU utilisation collapses, so the controller reads the fleet as idle and scales in. When the dependency recovers, real traffic meets a fleet half the size it needs and the SLO stays breached for a further 270 seconds. With an error-rate guard the dashed green line holds at 18 throughout and no requests miss the SLO.">
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <text x="440" y="26" text-anchor="middle" font-size="14.5" font-weight="700" fill="currentColor">The scale-in trap: the autoscaler shrinks the fleet during the outage</text>
    <defs><marker id="p11-13-a5" markerWidth="10" markerHeight="10" refX="7" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#e0930f"/></marker></defs>
    <rect x="264.9" y="76" width="281.5" height="216" fill="#d64545" fill-opacity="0.11"/><path d="M96 76 L 96 292 M96 292 L 828 292" fill="none" stroke="currentColor" stroke-width="1.4"/>
    <path d="M96 238.0 L 828 238.0" fill="none" stroke="currentColor" stroke-width="1" opacity="0.15"/><text x="90" y="241.0" font-size="9" fill="currentColor" text-anchor="end" opacity="0.7">6</text>
    <path d="M96 184.0 L 828 184.0" fill="none" stroke="currentColor" stroke-width="1" opacity="0.15"/><text x="90" y="187.0" font-size="9" fill="currentColor" text-anchor="end" opacity="0.7">12</text>
    <path d="M96 130.0 L 828 130.0" fill="none" stroke="currentColor" stroke-width="1" opacity="0.15"/><text x="90" y="133.0" font-size="9" fill="currentColor" text-anchor="end" opacity="0.7">18</text>
    <path d="M96 76.0 L 828 76.0" fill="none" stroke="currentColor" stroke-width="1" opacity="0.15"/><text x="90" y="79.0" font-size="9" fill="currentColor" text-anchor="end" opacity="0.7">24</text>
    <text x="90" y="295" font-size="9" fill="currentColor" text-anchor="end" opacity="0.7">0</text>
    <path d="M96 130.0 L 102 130.0 L 107 130.0 L 113 130.0 L 119 130.0 L 124 130.0 L 130 130.0 L 135 130.0 L 141 130.0 L 147 130.0 L 152 130.0 L 158 130.0 L 164 130.0 L 169 130.0 L 175 130.0 L 180 130.0 L 186 130.0 L 192 130.0 L 197 130.0 L 203 130.0 L 209 130.0 L 214 130.0 L 220 130.0 L 226 130.0 L 231 130.0 L 237 130.0 L 242 130.0 L 248 130.0 L 254 130.0 L 259 130.0 L 265 130.0 L 271 130.0 L 276 130.0 L 282 130.0 L 287 130.0 L 293 148.0 L 299 148.0 L 304 148.0 L 310 148.0 L 316 148.0 L 321 148.0 L 327 148.0 L 332 148.0 L 338 148.0 L 344 148.0 L 349 166.0 L 355 166.0 L 361 166.0 L 366 166.0 L 372 166.0 L 378 166.0 L 383 166.0 L 389 166.0 L 394 166.0 L 400 166.0 L 406 184.0 L 411 184.0 L 417 184.0 L 423 184.0 L 428 184.0 L 434 184.0 L 439 184.0 L 445 184.0 L 451 184.0 L 456 184.0 L 462 202.0 L 468 202.0 L 473 202.0 L 479 202.0 L 485 202.0 L 490 202.0 L 496 202.0 L 501 202.0 L 507 202.0 L 513 202.0 L 518 211.0 L 524 211.0 L 530 211.0 L 535 211.0 L 541 211.0 L 546 211.0 L 552 211.0 L 558 211.0 L 563 211.0 L 569 211.0 L 575 148.0 L 580 148.0 L 586 148.0 L 592 148.0 L 597 148.0 L 603 148.0 L 608 148.0 L 614 148.0 L 620 112.0 L 625 112.0 L 631 112.0 L 637 112.0 L 642 112.0 L 648 112.0 L 653 112.0 L 659 112.0 L 665 112.0 L 670 112.0 L 676 112.0 L 682 112.0 L 687 112.0 L 693 112.0 L 698 112.0 L 704 112.0 L 710 112.0 L 715 112.0 L 721 112.0 L 727 112.0 L 732 112.0 L 738 112.0 L 744 112.0 L 749 112.0 L 755 112.0 L 760 112.0 L 766 112.0 L 772 112.0 L 777 112.0 L 783 112.0 L 789 112.0 L 794 112.0 L 800 112.0 L 805 112.0 L 811 112.0 L 817 112.0 L 822 112.0" fill="none" stroke="#d64545" stroke-width="2.6"/>
    <path d="M96 130.0 L 102 130.0 L 107 130.0 L 113 130.0 L 119 130.0 L 124 130.0 L 130 130.0 L 135 130.0 L 141 130.0 L 147 130.0 L 152 130.0 L 158 130.0 L 164 130.0 L 169 130.0 L 175 130.0 L 180 130.0 L 186 130.0 L 192 130.0 L 197 130.0 L 203 130.0 L 209 130.0 L 214 130.0 L 220 130.0 L 226 130.0 L 231 130.0 L 237 130.0 L 242 130.0 L 248 130.0 L 254 130.0 L 259 130.0 L 265 130.0 L 271 130.0 L 276 130.0 L 282 130.0 L 287 130.0 L 293 130.0 L 299 130.0 L 304 130.0 L 310 130.0 L 316 130.0 L 321 130.0 L 327 130.0 L 332 130.0 L 338 130.0 L 344 130.0 L 349 130.0 L 355 130.0 L 361 130.0 L 366 130.0 L 372 130.0 L 378 130.0 L 383 130.0 L 389 130.0 L 394 130.0 L 400 130.0 L 406 130.0 L 411 130.0 L 417 130.0 L 423 130.0 L 428 130.0 L 434 130.0 L 439 130.0 L 445 130.0 L 451 130.0 L 456 130.0 L 462 130.0 L 468 130.0 L 473 130.0 L 479 130.0 L 485 130.0 L 490 130.0 L 496 130.0 L 501 130.0 L 507 130.0 L 513 130.0 L 518 130.0 L 524 130.0 L 530 130.0 L 535 130.0 L 541 130.0 L 546 130.0 L 552 130.0 L 558 130.0 L 563 130.0 L 569 130.0 L 575 130.0 L 580 130.0 L 586 130.0 L 592 130.0 L 597 130.0 L 603 130.0 L 608 130.0 L 614 130.0 L 620 112.0 L 625 112.0 L 631 112.0 L 637 112.0 L 642 112.0 L 648 112.0 L 653 112.0 L 659 112.0 L 665 112.0 L 670 112.0 L 676 112.0 L 682 112.0 L 687 112.0 L 693 112.0 L 698 112.0 L 704 112.0 L 710 112.0 L 715 112.0 L 721 112.0 L 727 112.0 L 732 112.0 L 738 112.0 L 744 112.0 L 749 112.0 L 755 112.0 L 760 112.0 L 766 112.0 L 772 112.0 L 777 112.0 L 783 112.0 L 789 112.0 L 794 112.0 L 800 112.0 L 805 112.0 L 811 112.0 L 817 112.0 L 822 112.0" fill="none" stroke="#0fa07f" stroke-width="2.6" stroke-dasharray="7 4"/>
    <text x="405.6923076923077" y="68" font-size="10" fill="#d64545" text-anchor="middle" font-weight="700">DEPENDENCY DOWN - every request fails in 5 ms</text>
    <text x="102" y="96" font-size="9" fill="currentColor" opacity="0.85">18 instances, CPU 60%, healthy</text><text x="96" y="68" font-size="9.5" fill="currentColor" opacity="0.85">instances</text>
    <text x="274.9230769230769" y="222" font-size="9.5" fill="#d64545" font-weight="700">1 · requests fail fast, 5 ms each</text>
    <text x="274.9230769230769" y="237" font-size="9.5" fill="#d64545" font-weight="700">2 · CPU falls to a few percent</text>
    <text x="274.9230769230769" y="252" font-size="9.5" fill="#d64545" font-weight="700">3 · the loop reads 'idle'</text>
    <text x="274.9230769230769" y="267" font-size="9.5" fill="#d64545" font-weight="700">4 · it scales IN, 10% per interval</text>
    <path d="M552.5 250 L 590.5 250" fill="none" stroke="#e0930f" stroke-width="1.8" marker-end="url(#p11-13-a5)"/>
    <text x="598.4615384615385" y="236" font-size="9.5" fill="#e0930f" font-weight="700">5 · the dependency returns</text>
    <text x="598.4615384615385" y="250" font-size="9.5" fill="#e0930f">to a fleet 2.0x too small:</text>
    <text x="598.4615384615385" y="264" font-size="9.5" fill="#e0930f" font-weight="700">270 s of further SLO breach</text><text x="96" y="308" font-size="9" fill="currentColor" opacity="0.7">0 s</text>
    <text x="828" y="308" font-size="9" fill="currentColor" text-anchor="end" opacity="0.7">3900 s</text>
    <rect x="96" y="324" width="356" height="74" rx="8" fill="#d64545" fill-opacity="0.10" stroke="#d64545" stroke-width="1.8"/>
    <rect x="472" y="324" width="356" height="74" rx="8" fill="#0fa07f" fill-opacity="0.10" stroke="#0fa07f" stroke-width="1.8"/><text x="114" y="344" font-size="11" fill="#d64545" font-weight="700">NO GUARD</text>
    <text x="114" y="362" font-size="9.3" fill="currentColor" opacity="0.92">fleet 18 -> 9 during the incident</text>
    <text x="114" y="376" font-size="9.3" fill="currentColor" opacity="0.92">6.9% of all requests missed the SLO</text>
    <text x="114" y="390" font-size="9.3" fill="currentColor" opacity="0.92">270 s of breach AFTER recovery</text><text x="490" y="344" font-size="11" fill="#0fa07f" font-weight="700">ERROR-RATE GUARD</text>
    <text x="490" y="362" font-size="9.3" fill="currentColor" opacity="0.92">floor held at 18 throughout</text>
    <text x="490" y="376" font-size="9.3" fill="currentColor" opacity="0.92">0.0% of requests missed the SLO</text>
    <text x="490" y="390" font-size="9.3" fill="currentColor" opacity="0.92">0 s of breach after recovery</text>
    <text x="440" y="412" font-size="11" text-anchor="middle" fill="currentColor" opacity="0.9">Never scale in on a metric that goes DOWN when things go wrong.</text>
  </g>
</svg>
```

Unguarded, the fleet fell **from 18 to 9** — and note what stopped it going to the floor of 4: the 10%-per-interval scale-in rate limit added two sections ago. *The knob you installed for oscillation is the only thing standing between an outage and an empty fleet.* When the dependency returned, real traffic met a fleet 2.0× too small: **270 further seconds of SLO breach after the incident was over**, and **6.9%** of all requests in the run outside the objective. With the guard, the floor held at 18, post-recovery breach was **0 s**, and **0.0%** of requests missed.

The guard is two clauses, and the second is the one people leave out:

1. Never scale **in** while the error rate is elevated.
2. Keep the block for `metric_delay + metric_window + decision_interval` after errors clear — because the cheap, low-CPU samples taken *during* the outage are still sitting inside the averaging window, and lifting the guard the instant errors stop just hands the controller the same poisoned average.

The deeper fix is to prefer a load signal that **rises** under failure rather than falling. In-flight concurrency rises when a dependency hangs. Queue age rises. CPU falls. That asymmetry is the whole argument.

#### Autoscaling into a metastable failure

This is the sharpest one, and it is where autoscaling stops being neutral and becomes an active participant in the outage.

[Phase 8's lesson on backpressure](../../08-concurrency-and-performance/11-backpressure-and-load-shedding/) defined a **metastable failure** (Bronson et al., *Metastable Failures in Distributed Systems*, HotOS 2021): a system that stays in a degraded, near-zero-goodput state **after the trigger has been removed**, because it has entered a sustaining feedback loop. Retries are the classic engine: requests time out, clients retry, arrivals rise, more requests time out.

Now add an autoscaler. During a retry storm, the arrival rate is inflated by the system's **own retries**. The autoscaler cannot tell a retry from a request — nothing at that layer can — so it sees 3× the load and adds 3× the capacity. And here is the trap: **serving a retry quickly does not reduce retries.** A retry goes away when the original request *succeeds*. If the actual bottleneck is downstream, the new instances do not relieve it. They make it worse, because each one opens a connection pool.

The measurement makes this concrete with the Universal Scalability Law from Lesson 2. A database's throughput is not linear in concurrency; it peaks and then declines, because contention and coherency costs grow faster than the parallelism (Gunther, *Guerrilla Capacity Planning*, Springer 2007):

```text
 44 connections ->  537 q/s   <- the peak
100 connections ->  459 q/s   (85% of peak)
200 connections ->  324 q/s   (60% of peak)
300 connections ->  247 q/s   (46% of peak)   <- max_connections
```

Every app instance opens a pool of 20. Past 44 connections — that is, past **2.2 instances** — adding app instances *subtracts* database capacity.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 414" width="100%" style="max-width:840px" role="img" aria-label="Two measured 600 second runs of the same retry storm side by side. On the left the app tier autoscales: instance count climbs from 6 to 20, past the dashed line at 15 instances where the pools exhaust the database's 300 connection limit, the database's own capacity falls from 426 to 247 queries per second along the Universal Scalability Law curve, and goodput stays flat at zero for the whole run. On the right the app sheds load instead and the autoscaler stays pinned at 6 instances: connections stay at 120, the database holds 426 queries per second, and goodput returns to the full 400 requests per second five seconds after the trigger clears.">
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <text x="440" y="26" text-anchor="middle" font-size="14.5" font-weight="700" fill="currentColor">Autoscaling into a metastable failure: capacity up, goodput zero</text>
    <rect x="22" y="48" width="412" height="336" rx="10" fill="#d64545" fill-opacity="0.07" stroke="#d64545" stroke-width="2"/>
    <text x="228" y="68" font-size="12" fill="#d64545" text-anchor="middle" font-weight="700">A · AUTOSCALE INTO IT</text>
    <path d="M74 88 L 74 176 M74 176 L 426 176" fill="none" stroke="currentColor" stroke-width="1.4"/><path d="M74 121.0 L 426 121.0" fill="none" stroke="#d64545" stroke-width="1.4" stroke-dasharray="5 4"/>
    <path d="M74 154.0 L 80 154.0 L 86 154.0 L 92 154.0 L 97 154.0 L 103 154.0 L 109 154.0 L 115 150.3 L 121 150.3 L 127 150.3 L 133 146.7 L 139 146.7 L 144 146.7 L 150 102.7 L 156 102.7 L 162 102.7 L 168 102.7 L 174 102.7 L 180 102.7 L 185 102.7 L 191 102.7 L 197 102.7 L 203 102.7 L 209 102.7 L 215 102.7 L 221 102.7 L 227 102.7 L 232 102.7 L 238 102.7 L 244 102.7 L 250 102.7 L 256 102.7 L 262 102.7 L 268 102.7 L 273 102.7 L 279 102.7 L 285 102.7 L 291 102.7 L 297 102.7 L 303 102.7 L 309 102.7 L 315 102.7 L 320 102.7 L 326 102.7 L 332 102.7 L 338 102.7 L 344 102.7 L 350 102.7 L 356 102.7 L 361 102.7 L 367 102.7 L 373 102.7 L 379 102.7 L 385 102.7 L 391 102.7 L 397 102.7 L 403 102.7 L 408 102.7 L 414 102.7 L 420 102.7" fill="none" stroke="#7c5cff" stroke-width="2.6"/>
    <text x="68" y="92" font-size="8.5" fill="currentColor" text-anchor="end" opacity="0.7">24</text><text x="68" y="179" font-size="8.5" fill="currentColor" text-anchor="end" opacity="0.7">0</text>
    <text x="68" y="124.0" font-size="8.5" fill="#d64545" text-anchor="end" font-weight="700">15</text><text x="78" y="84" font-size="9" fill="#7c5cff" font-weight="700">app instances</text>
    <text x="426" y="84" font-size="8.4" fill="#d64545" text-anchor="end" font-weight="700">15 = the max_connections ceiling</text>
    <path d="M74 208 L 74 300 M74 300 L 426 300" fill="none" stroke="currentColor" stroke-width="1.4"/>
    <path d="M74 230.0 L 80 230.0 L 86 230.0 L 92 230.0 L 97 230.0 L 103 230.0 L 109 230.0 L 115 235.0 L 121 235.0 L 127 235.0 L 133 239.3 L 139 239.3 L 144 269.7 L 150 279.7 L 156 279.7 L 162 279.7 L 168 279.7 L 174 279.7 L 180 259.5 L 185 259.5 L 191 259.5 L 197 259.5 L 203 259.5 L 209 259.5 L 215 259.5 L 221 259.5 L 227 259.5 L 232 259.5 L 238 259.5 L 244 259.5 L 250 259.5 L 256 259.5 L 262 259.5 L 268 259.5 L 273 259.5 L 279 259.5 L 285 259.5 L 291 259.5 L 297 259.5 L 303 259.5 L 309 259.5 L 315 259.5 L 320 259.5 L 326 259.5 L 332 259.5 L 338 259.5 L 344 259.5 L 350 259.5 L 356 259.5 L 361 259.5 L 367 259.5 L 373 259.5 L 379 259.5 L 385 259.5 L 391 259.5 L 397 259.5 L 403 259.5 L 408 259.5 L 414 259.5 L 420 259.5" fill="none" stroke="#e0930f" stroke-width="1.8" stroke-dasharray="5 3"/>
    <path d="M74 234.3 L 80 234.3 L 86 234.3 L 92 234.3 L 97 234.3 L 103 234.3 L 109 234.3 L 115 235.0 L 121 235.0 L 127 300.0 L 133 300.0 L 139 300.0 L 144 300.0 L 150 300.0 L 156 300.0 L 162 300.0 L 168 300.0 L 174 300.0 L 180 300.0 L 185 300.0 L 191 300.0 L 197 300.0 L 203 300.0 L 209 300.0 L 215 300.0 L 221 300.0 L 227 300.0 L 232 300.0 L 238 300.0 L 244 300.0 L 250 300.0 L 256 300.0 L 262 300.0 L 268 300.0 L 273 300.0 L 279 300.0 L 285 300.0 L 291 300.0 L 297 300.0 L 303 300.0 L 309 300.0 L 315 300.0 L 320 300.0 L 326 300.0 L 332 300.0 L 338 300.0 L 344 300.0 L 350 300.0 L 356 300.0 L 361 300.0 L 367 300.0 L 373 300.0 L 379 300.0 L 385 300.0 L 391 300.0 L 397 300.0 L 403 300.0 L 408 300.0 L 414 300.0 L 420 300.0" fill="none" stroke="#d64545" stroke-width="2.6"/>
    <text x="68" y="212" font-size="8.5" fill="currentColor" text-anchor="end" opacity="0.7">560</text><text x="68" y="303" font-size="8.5" fill="currentColor" text-anchor="end" opacity="0.7">0</text>
    <text x="78" y="204" font-size="9" fill="#d64545" font-weight="700">goodput req/s</text>
    <text x="426" y="204" font-size="8.4" fill="#e0930f" text-anchor="end" font-weight="700">- - what the database delivers</text>
    <rect x="144.4" y="88" width="35.2" height="212" fill="#e0930f" fill-opacity="0.14"/><text x="162.0" y="318" font-size="8.5" fill="#e0930f" text-anchor="middle" font-weight="700">60 s hiccup</text>
    <text x="74" y="318" font-size="8.5" fill="currentColor" opacity="0.7">0 s</text><text x="426" y="318" font-size="8.5" fill="currentColor" text-anchor="end" opacity="0.7">600 s</text>
    <text x="228" y="338" font-size="9.5" fill="#d64545" text-anchor="middle" font-weight="700">goodput after the trigger: 0 req/s</text>
    <text x="228" y="352" font-size="9" fill="currentColor" text-anchor="middle" opacity="0.92">recovery: NEVER · 172 instance-minutes</text>
    <text x="228" y="365" font-size="9" fill="currentColor" text-anchor="middle" opacity="0.92">400 conns wanted, 300 granted</text>
    <text x="228" y="378" font-size="9" fill="currentColor" text-anchor="middle" opacity="0.92">database 426 -> 247 q/s  (-42%)</text>
    <rect x="450" y="48" width="412" height="336" rx="10" fill="#0fa07f" fill-opacity="0.07" stroke="#0fa07f" stroke-width="2"/>
    <text x="656" y="68" font-size="12" fill="#0fa07f" text-anchor="middle" font-weight="700">B · SHED INSTEAD</text>
    <path d="M502 88 L 502 176 M502 176 L 854 176" fill="none" stroke="currentColor" stroke-width="1.4"/><path d="M502 121.0 L 854 121.0" fill="none" stroke="#d64545" stroke-width="1.4" stroke-dasharray="5 4"/>
    <path d="M502 154.0 L 508 154.0 L 514 154.0 L 520 154.0 L 525 154.0 L 531 154.0 L 537 154.0 L 543 154.0 L 549 154.0 L 555 154.0 L 561 154.0 L 567 154.0 L 572 154.0 L 578 154.0 L 584 154.0 L 590 154.0 L 596 154.0 L 602 154.0 L 608 154.0 L 613 154.0 L 619 154.0 L 625 154.0 L 631 154.0 L 637 154.0 L 643 154.0 L 649 154.0 L 655 154.0 L 660 154.0 L 666 154.0 L 672 154.0 L 678 154.0 L 684 154.0 L 690 154.0 L 696 154.0 L 701 154.0 L 707 154.0 L 713 154.0 L 719 154.0 L 725 154.0 L 731 154.0 L 737 154.0 L 743 154.0 L 748 154.0 L 754 154.0 L 760 154.0 L 766 154.0 L 772 154.0 L 778 154.0 L 784 154.0 L 789 154.0 L 795 154.0 L 801 154.0 L 807 154.0 L 813 154.0 L 819 154.0 L 825 154.0 L 831 154.0 L 836 154.0 L 842 154.0 L 848 154.0" fill="none" stroke="#7c5cff" stroke-width="2.6"/>
    <text x="496" y="92" font-size="8.5" fill="currentColor" text-anchor="end" opacity="0.7">24</text><text x="496" y="179" font-size="8.5" fill="currentColor" text-anchor="end" opacity="0.7">0</text>
    <text x="496" y="124.0" font-size="8.5" fill="#d64545" text-anchor="end" font-weight="700">15</text><text x="506" y="84" font-size="9" fill="#7c5cff" font-weight="700">app instances</text>
    <text x="854" y="84" font-size="8.4" fill="#d64545" text-anchor="end" font-weight="700">15 = the max_connections ceiling</text>
    <path d="M502 208 L 502 300 M502 300 L 854 300" fill="none" stroke="currentColor" stroke-width="1.4"/>
    <path d="M502 230.0 L 508 230.0 L 514 230.0 L 520 230.0 L 525 230.0 L 531 230.0 L 537 230.0 L 543 230.0 L 549 230.0 L 555 230.0 L 561 230.0 L 567 230.0 L 572 265.0 L 578 265.0 L 584 265.0 L 590 265.0 L 596 265.0 L 602 265.0 L 608 230.0 L 613 230.0 L 619 230.0 L 625 230.0 L 631 230.0 L 637 230.0 L 643 230.0 L 649 230.0 L 655 230.0 L 660 230.0 L 666 230.0 L 672 230.0 L 678 230.0 L 684 230.0 L 690 230.0 L 696 230.0 L 701 230.0 L 707 230.0 L 713 230.0 L 719 230.0 L 725 230.0 L 731 230.0 L 737 230.0 L 743 230.0 L 748 230.0 L 754 230.0 L 760 230.0 L 766 230.0 L 772 230.0 L 778 230.0 L 784 230.0 L 789 230.0 L 795 230.0 L 801 230.0 L 807 230.0 L 813 230.0 L 819 230.0 L 825 230.0 L 831 230.0 L 836 230.0 L 842 230.0 L 848 230.0" fill="none" stroke="#e0930f" stroke-width="1.8" stroke-dasharray="5 3"/>
    <path d="M502 234.3 L 508 234.3 L 514 234.3 L 520 234.3 L 525 234.3 L 531 234.3 L 537 234.3 L 543 234.3 L 549 234.3 L 555 234.3 L 561 234.3 L 567 234.3 L 572 265.0 L 578 265.0 L 584 265.0 L 590 265.0 L 596 265.0 L 602 265.0 L 608 230.0 L 613 230.0 L 619 230.0 L 625 230.0 L 631 230.0 L 637 234.3 L 643 234.3 L 649 234.3 L 655 234.3 L 660 234.3 L 666 234.3 L 672 234.3 L 678 234.3 L 684 234.3 L 690 234.3 L 696 234.3 L 701 234.3 L 707 234.3 L 713 234.3 L 719 234.3 L 725 234.3 L 731 234.3 L 737 234.3 L 743 234.3 L 748 234.3 L 754 234.3 L 760 234.3 L 766 234.3 L 772 234.3 L 778 234.3 L 784 234.3 L 789 234.3 L 795 234.3 L 801 234.3 L 807 234.3 L 813 234.3 L 819 234.3 L 825 234.3 L 831 234.3 L 836 234.3 L 842 234.3 L 848 234.3" fill="none" stroke="#0fa07f" stroke-width="2.6"/>
    <text x="496" y="212" font-size="8.5" fill="currentColor" text-anchor="end" opacity="0.7">560</text><text x="496" y="303" font-size="8.5" fill="currentColor" text-anchor="end" opacity="0.7">0</text>
    <text x="506" y="204" font-size="9" fill="#0fa07f" font-weight="700">goodput req/s</text>
    <text x="854" y="204" font-size="8.4" fill="#e0930f" text-anchor="end" font-weight="700">- - what the database delivers</text>
    <rect x="572.4" y="88" width="35.2" height="212" fill="#e0930f" fill-opacity="0.14"/><text x="590.0" y="318" font-size="8.5" fill="#e0930f" text-anchor="middle" font-weight="700">60 s hiccup</text>
    <text x="502" y="318" font-size="8.5" fill="currentColor" opacity="0.7">0 s</text><text x="854" y="318" font-size="8.5" fill="currentColor" text-anchor="end" opacity="0.7">600 s</text>
    <text x="656" y="338" font-size="9.5" fill="#0fa07f" text-anchor="middle" font-weight="700">goodput after the trigger: 400 req/s</text>
    <text x="656" y="352" font-size="9" fill="currentColor" text-anchor="middle" opacity="0.92">recovery: 5 s · 60 instance-minutes</text>
    <text x="656" y="365" font-size="9" fill="currentColor" text-anchor="middle" opacity="0.92">120 conns, never more</text>
    <text x="656" y="378" font-size="9" fill="currentColor" text-anchor="middle" opacity="0.92">database held at 426 q/s</text>
    <text x="440" y="400" font-size="11" text-anchor="middle" fill="currentColor" opacity="0.9">The autoscaler added capacity to serve retries. Retries end by succeeding.</text>
  </g>
</svg>
```

Two runs, identical trigger: 400 req/s of real user demand, a 1-second client timeout, 3 attempts, and a 60-second database hiccup at t=120 s.

| | reactive autoscaling | load shedding, autoscaler pinned |
|---|---|---|
| goodput after the trigger cleared | **0 req/s** | **400 req/s** (full demand) |
| recovery | **NEVER** | 5 s after the hiccup ended |
| peak offered load | 1200 req/s (3.0× demand) | 951 req/s (2.4×) |
| connections | **400 wanted, 300 granted** | 120, never more |
| database throughput | **247 q/s** (baseline 426) | 426 q/s, held |
| instance-minutes billed | **172** | 60 |

The autoscaler took the app tier from 6 instances to 20, wanted 400 connections against a `max_connections` of 300 — so a quarter of connection attempts were refused outright — and dragged the database from 426 to 247 queries per second, **a 42% cut in the capacity of the only tier that mattered.** It then held that state for the rest of the run. Goodput: zero, for **2.9× the bill.** The shed run pinned the fleet, admitted only what the database was actually delivering, rejected the rest in zero milliseconds, and was back to full goodput five seconds after the trigger cleared.

State it plainly: **autoscaling did not cause the metastable failure. It paid the loop's running costs so the loop never had to end.** It kept supplying just enough capacity to sustain the storm. The exit is load shedding — the ability to say no — and scaling is not a substitute for it. When you are in a retry storm, adding capacity is not neutral; it is the wrong direction.

#### Scaling the wrong tier

The general form of the above, and a genuine, common, self-inflicted outage. Adding stateless app instances when the bottleneck is the database makes things worse, and the arithmetic is one multiplication you can do before the incident:

```text
N instances  ×  pool size  vs  the database's max_connections
```

Postgres ships with `max_connections = 100`. A fleet that autoscales to 30 instances with a pool of 10 wants 300. You will get `FATAL: sorry, too many clients already`, and the failure will present as an application error at 03:00 with no obvious cause. Even below the hard limit, the USL curve above is already taking throughput away from you. [Connection & Resource Pooling](../../08-concurrency-and-performance/12-connection-and-resource-pooling/) covers sizing; the autoscaling rule is that **your maximum fleet size and your pool size are a single coupled decision with the database's connection limit**, and if you set `max_size` without doing that multiplication you have configured an outage with a delay fuse. A connection proxy such as PgBouncer decouples them, which is why fleets that autoscale aggressively almost always run one.

#### Cold start and the warmup penalty

A launched instance is not capacity. The simulator's instance boots for 90 seconds delivering nothing, then runs at 25% capacity for 60 seconds while its caches fill and its JIT compiles, and only then delivers its full 100 req/s:

```text
second since launch   state        capacity the LB can use
     0 s              booting        0.0 req/s
    60 s              booting        0.0 req/s
    90 s              warming       25.0 req/s
   145 s              warming       25.0 req/s
   150 s              in service   100.0 req/s
```

**Averaged over its first 150 seconds it is worth 10% of an instance, and you are billed for 100% of it from second zero.** Plan capacity in instance-seconds, not instances.

Worse, what the load balancer does with it decides whether it helps or hurts. Give a warming instance a full equal share of traffic and it is four times as loaded as its peers, so it is slow, and it may fail its own health check and get ejected — after which the autoscaler launches a replacement, which does the same thing. Measured across the same scale-out events:

| what the LB sends a warming instance | SLO | requests missing it | cost |
|---|---|---|---|
| full share the moment it listens | 97.3% | 192,719 | 1504 |
| **slow start: weight ∝ capacity** | **99.3%** | **48,966** | 1461 |
| gated: no traffic until fully warm | 98.7% | 89,606 | 1433 |

Slow start wins, and it beats gating, which is the interesting part: gating throws away the 25% the instance *could* have contributed for a minute, and in a scale-out event that minute is exactly when you need it. Lesson 4 covered the health-check and slow-start mechanics; the autoscaling-specific instruction is to make sure your warmup period is configured to match reality, so the controller does not count an instance as capacity before it is one.

### The floor matters more than the ceiling

Everyone tunes `max_size`. `max_size` is a spend limit and a blast-radius limit; it is worth setting, and it is not where the reliability lives.

**The reliability lives in `min_size`**, for two reasons.

First, a floor keeps you above the knee. Everything in [Phase 8's queueing lesson](../../08-concurrency-and-performance/11-backpressure-and-load-shedding/) about `W = S/(1−ρ)` applies to a fleet as much as to a thread pool: a fleet running at 90% is one traffic bump away from a latency cliff, and the autoscaler's response to that bump arrives 4.5 minutes late. The floor is what absorbs the spike while the loop catches up.

Second — and this is the thesis of the lesson — **during a failure, autoscaling is a dependency that may not work.** When an availability zone fails, everyone in that region tries to scale out at the same instant. The control plane is saturated with requests from every other customer doing the same thing. The capacity pool for your instance type in the surviving zones is contended. Your account quota binds. The API returns `InsufficientInstanceCapacity`, and it returns it to you at the exact moment your runbook says "the autoscaler will handle it."

Lesson 9 called this **static stability**: a system is statically stable if it keeps working during a failure *without needing to change anything*. Autoscaling is the opposite of static stability. It is a control action, taken by a control plane, drawing on a shared pool, under the worst conditions the system will ever see.

> **Autoscaling is for cost, not for reliability.** Every column in this lesson's measurements is a cost column. Buy reliability with a floor you have already paid for — capacity that is running, warm, and in the load balancer before the incident starts — and use the autoscaler to take that floor away when nothing is wrong.

This contradicts what most people assume autoscaling is for, and it is the mature view. The pre-provisioned fleet is what survives the region loss. The autoscaler is what stops you paying for it at 04:00 on a Sunday.

## Build It

[`code/autoscaling.py`](code/autoscaling.py) is a discrete-time control-loop simulator with dead time as an explicit knob. Standard library only, seeded with `random.Random(7)`, runs in well under a second. Every configuration sees the identical traffic-noise sequence and the identical metric-jitter sequence, so any difference between two rows is caused by the thing being changed and nothing else.

Run it:

```bash
docker compose exec -T app python \
  phases/11-scalability-and-reliability/13-autoscaling/code/autoscaling.py
```

**The modelled instance** is the part worth reading first, because every result depends on it and none of it is arbitrary:

```python
CPU_RPS = 166.7      # 6 ms of CPU per request -> 166.7 req/s at 100% CPU
SLOTS   = 8.0        # concurrent request slots (worker threads) per instance
S_FAST  = 0.012      # service time with a healthy dependency: 6 ms CPU + 6 ms wait
SLO_RHO = 0.90       # W = S/(1-rho); at rho = 0.90, W = 10 x S = 120 ms = the SLO
```

The SLO is **derived, not asserted.** Phase 8's lesson measured `W = S/(1−ρ)` to within 3% of theory, so at ρ = 0.90 the response time is exactly ten times the service time. A tick in which an instance runs above ρ = 0.90 is a tick in which its requests miss the 120 ms objective, and that is what the `SLO%` column counts. Capacity per instance is `min(cpu_capacity, slots / service_time)` — **which resource binds depends on the service time**, and that single line is what makes section 3 work.

**The dead time** is implemented in two places. Measurement delay is a window into the past:

```python
lo = t - cfg.metric_delay - cfg.metric_window
hi = t - cfg.metric_delay
win = [h for h in hist if lo <= h[0] <= hi] or [hist[0]]
```

Provisioning delay is a launch timestamp per instance; an instance contributes nothing until `boot_s` has elapsed and nothing at full capacity until `boot_s + warm_s` has:

```python
for launch in fleet:
    age = t - launch
    if age < cfg.boot_s:
        continue                            # booting: billed, serves nothing
    if age < cfg.boot_s + cfg.warm_s:
        if cfg.gated:
            continue                        # not in the load balancer yet
        fracs.append(cfg.warm_frac)
    else:
        fracs.append(1.0)
```

**The controller** is the Kubernetes formula, with the one-line fix as a flag. This is the most important code in the file:

```python
# Kubernetes HPA: desired = ceil(replicas * metric / target). `replicas` is
# what you have NOW; the metric came from the fleet you had a dead time ago.
# That mismatch is the overshoot. `normalize` fixes it by dividing by the
# fleet size that actually produced the measurement.
base = max(1.0, m_ready) if cfg.normalize else float(max(1, n_now))
want = int(math.ceil(base * ratio))
```

`m_ready` is the average number of serving instances *across the metric window* — the denominator the ratio was actually computed against. Nothing else changes. That is the difference between 1216 launches and 60.

**Section 5** is a separate model because the physics are different: the plant is a database, not a fleet, and its capacity curve bends the wrong way.

```python
def db_capacity(conns: int) -> float:
    """Universal Scalability Law (Gunther 2007). It peaks, then it goes DOWN."""
    n = max(1, min(conns, DB_MAX_CONN))
    return DB_CONN_QPS * n / (1.0 + DB_ALPHA * (n - 1) + DB_BETA * n * (n - 1))
```

`DB_ALPHA` is contention (work that must serialise) and `DB_BETA` is coherency (the cost of connections having to agree with each other). The `β·n(n−1)` term grows quadratically, which is why the curve turns over — at `sqrt((1−α)/β) ≈ 44` connections. The retry model tracks three attempt generations as separate arrival streams so the amplification ceiling is exactly 3.0×, not an assumption. The shedding run's admission limit is the adaptive concurrency limit from Phase 8's lesson, in one line: admit what the database is actually delivering right now, reject the rest instantly.

The full output:

```console
== 1 · DEAD TIME IS WHAT MAKES AN AUTOSCALER OSCILLATE ==
  identical traffic, identical target-tracking controller (hold CPU at 60%),
  decision interval 60 s, no stabilisers. The only variable is total dead
  time: metric pipeline + boot + warmup, split 60:90:60 like a real fleet.
  the plateau needs exactly 24 instances (2400 req/s / 100 req/s each).

   dead time  metric boot warm |  plateau min/max  swing  flips  launches |   SLO%   inst-min
       0 s        0    0    0 |       24 / 25        1      0        33 |  100.0       1206
      60 s       20   30   20 |       24 / 26        2      0        32 |  100.0       1229
     120 s       30   50   30 |       23 / 29        6      3        69 |  100.0       1291
     210 s       60   90   60 |        6 / 145     139      3       539 |   57.3       2547  <- cloud default
     360 s      100  150  100 |        5 / 400     395      3       802 |   65.2       3956

  ...
  at D = 210 s - the number you actually get from a cloud provider - the
  same controller swings 139 instances on a plateau of CONSTANT traffic,
  launches 539 instances instead of 33, and misses the SLO for 42.7% of
  requests. At D = 360 s it swings 395 and misses 34.8%.

  ...
  Astrom & Murray predict a limit cycle of period ~2 x dead time:
    D = 210 s -> predicted 7.0 min, measured 9.6 min
    D = 360 s -> predicted 12.0 min, measured n/a (clipped at max_size)

== 2 · THE STABILISERS, ADDED ONE AT A TIME ==
  same controller and the same 360 s of dead time, now against traffic
  with a 150 s flash crowd on the plateau (2400 -> 4400 req/s at t=2000 s).

   configuration                        plateau min/max  swing  flips  launches    SLO%   inst-min
   naive HPA formula                       5 / 400     395      3      1216    49.4       5368
   + divide by the fleet you measured     21 / 40       19      5        60    80.0       1280
   + scale-in cooldown 300 s              21 / 40       19      5        58    80.0       1309
   + hysteresis out>1.10 in<0.70          25 / 46       21      1        46    80.5       1422
   + asymmetric rates out x2 in 10%       28 / 46       18      1        46    80.5       1762
   + 300 s metric smoothing               26 / 38       12      1        38    67.2       1554
   naive HPA + rate limits ONLY           19 / 194     175      2       291    89.5       3563

  ...

== 3 · THE METRIC IS THE DECISION, AND CPU IS THE WRONG ONE ==
  same traffic, stabilised controller, dead time 210 s. From t=1200 s the
  database degrades over 10 min: service time 12 ms -> 120 ms, recovering
  by t=3000 s. The CPU cost of a request never changes: 6 ms throughout.
  an instance then saturates at 8 slots / 0.120 s = 67 req/s,
  and at 67 req/s its CPU reads 40%. It is FULL and it looks IDLE.

   scaling metric                fleet in slow phase  worst rho   SLO%   inst-min
   CPU 60%  (the default)             15 / 25           2.33   45.1       1251
   in-flight per instance = 1.2      200 / 266          0.87   98.7       9857
   backlog age 0.30 s                 52 / 86           1.63   76.3       2809
   max(CPU, in-flight)                42 / 64           1.42   86.4       2627  <- ship this

  ...

== 4 · THE AUTOSCALER SCALES IN DURING THE OUTAGE ==
  constant 1800 req/s, stabilised controller. At t=900 s the dependency
  dies: requests now fail in 5 ms instead of succeeding in 12 ms, and
  failing fast is CHEAP, so CPU per instance collapses to a few percent.
  the controller reads 'idle'. The dependency returns at t=2400 s.

      t | dep  |  no guard                 |  error-guarded
    600 | up   |   18 ##########            |   18 ##########
    900 | DOWN |   18 ##########            |   18 ##########
   1140 | DOWN |   16 #########             |   18 ##########
   1440 | DOWN |   14 ########              |   18 ##########
   1740 | DOWN |   12 #######               |   18 ##########
   2040 | DOWN |   10 ######                |   18 ##########
   2340 | DOWN |    9 #####                 |   18 ##########
   2460 | up   |    9 #####                 |   18 ##########
   2640 | up   |   16 #########             |   18 ##########
   2940 | up   |   20 ###########           |   20 ###########
   3600 | up   |   20 ###########           |   20 ###########

  unguarded: the fleet fell from 18 to 9 during the outage. When the
             dependency came back, real traffic met a fleet 2.0x too small:
             SLO breached for a further 270 s AFTER recovery, and 6.9%
             of all requests in the run missed it.
  guarded:   floor held at 18, 0 s of post-recovery breach, 0.0% missed.
  ...

== 5 · AUTOSCALING INTO A METASTABLE FAILURE ==
  one database behind the app tier, max_connections = 300.
  its throughput follows the Universal Scalability Law (Phase 11 L02):
     44 connections ->   537 q/s  (100% of peak)   <- peak
    100 connections ->   459 q/s  ( 85% of peak)
    200 connections ->   324 q/s  ( 60% of peak)
    300 connections ->   247 q/s  ( 46% of peak)
  every app instance opens a pool of 20. Adding instances does not add
  database capacity. Past 44 connections it SUBTRACTS it.
  real user demand 400 req/s, client timeout 1.0 s, 3 attempts, jitter.
  trigger: a 60 s database hiccup at t=120 s (per-connection q/s halved).

  --- A · REACTIVE AUTOSCALING (the default) ---
      t | offered  inst  db-conn   db q/s  goodput   shed | goodput
     60 |     400     6      120      426      400      0 | ################
    115 |    1200     8      160      369        0      0 | 
    150 |    1200    20      400      123        0      0 | 
    185 |    1200    20      400      247        0      0 | 
    215 |    1200    20      400      247        0      0 | 
    260 |    1200    20      400      247        0      0 | 
    350 |    1200    20      400      247        0      0 | 
    450 |    1200    20      400      247        0      0 | 
    595 |    1200    20      400      247        0      0 | 
    after the trigger cleared (t > 300 s):
      goodput               0 req/s of 400 real demand
      peak offered       1200 req/s = 3.0x real demand (retries)
      peak connections    400 wanted, 300 granted
      database q/s        247  (healthy baseline 426)
      instance-minutes    172
      recovery         NEVER

  --- B · LOAD SHEDDING, AUTOSCALER PINNED AT 6 ---
      t | offered  inst  db-conn   db q/s  goodput   shed | goodput
     60 |     400     6      120      426      400      0 | ################
    115 |     400     6      120      426      400      0 | ################
    150 |     947     6      120      213      213    734 | #########
    185 |     793     6      120      426      426    367 | #################
    215 |     475     6      120      426      426     49 | #################
    260 |     400     6      120      426      400      0 | ################
    350 |     400     6      120      426      400      0 | ################
    450 |     400     6      120      426      400      0 | ################
    595 |     400     6      120      426      400      0 | ################
    after the trigger cleared (t > 300 s):
      goodput             400 req/s of 400 real demand
      peak offered        951 req/s = 2.4x real demand (retries)
      peak connections    120 wanted, 120 granted
      database q/s        426  (healthy baseline 426)
      instance-minutes     60
      recovery         5 s after the hiccup ended

  ...

== 6 · A NEW INSTANCE IS NOT CAPACITY FOR 60 SECONDS ==
  identical scale-out events. A booted instance needs 60 s to warm its
  page cache, connection pool and JIT; during that window it runs at 25%
  of capacity. The only variable is what the load balancer sends it.

   traffic policy for a warming instance        SLO%   missed req   inst-min
   full share the moment it listens           97.3      192719       1504
   slow start: LB weight ~ capacity           99.3       48966       1461
   gated: no traffic at all until warm        98.7       89606       1433

   second since launch   state      capacity the LB can actually use
        0 s              booting      0.0 req/s  
       30 s              booting      0.0 req/s  
       60 s              booting      0.0 req/s  
       90 s              warming     25.0 req/s  #####
      120 s              warming     25.0 req/s  #####
      145 s              warming     25.0 req/s  #####
      150 s              in service 100.0 req/s  ####################
      180 s              in service 100.0 req/s  ####################
  the autoscaler counted this instance as 1 the moment it launched and the
  bill started at the same instant. It delivered 0 req/s for 90 s and
  25 req/s for the next 60 s. Averaged over its first 150 s it is worth
  10% of an instance. Plan capacity in instance-SECONDS, not instances.

== 7 · SCHEDULED FOR THE ENVELOPE, REACTIVE FOR THE RESIDUAL ==
  a 24 h diurnal curve with a 12:00 campaign send (+2200 req/s for 30 min)
  that marketing told you about three weeks ago. Both runs use the identical
  stabilised reactive controller with 210 s of dead time.

   policy                  SLO%   missed req   inst-min   peak fleet
   reactive only          98.56      1187371      16141           52
   scheduled + reactive  100.00            0      19391           51

   hour  demand   reactive only              scheduled + reactive
    5.0     411     5 ##                         5 ##
    6.0     399     5 ##                         5 ##
    7.0     516     6 ##                        14 #####
    8.0     751     9 ###                       14 #####
   11.0    1533    18 #######                   18 #######
   12.0    3836    22 ########                  42 ###############
   12.5    1885    46 #################         45 ################
   13.0    1868    25 #########                 42 ###############
   18.0    1048    12 ####                      14 #####
   23.0     383     4 #                          4 #

  the schedule removes the lag for the part of the day you can predict, and
  the reactive loop handles only the residual. Cost +20.1% instance-minutes,
  requests missing the SLO down 100%. It is the highest-value, lowest-
  technology fix in this lesson, and it is a cron entry.

  THESIS: every column above is a cost column. Autoscaling is an
  optimisation for SPEND. It is itself a dependency - a control plane, a
  capacity pool, a quota - and it is slowest at exactly the moment you need
  it fastest. Buy reliability with a floor you have already paid for.
```

Five of these are arguments rather than demos.

**Section 1 is the foundation.** The traffic on the measured plateau is constant, so every movement of the fleet is the controller arguing with itself. At zero dead time the loop is exact and parks on 24. At 60 s — equal to the reaction period — it still settles. At 120 s it hunts without breaking anything, which is the state most fleets are actually in and nobody investigates. At 210 s it is a limit cycle: **139 instances of swing, 539 launches instead of 33, 57.3% SLO**, with a measured period of 9.6 minutes against a predicted 7.0 — the right order, which confirms the mechanism rather than the constant.

**Section 2 locates the overshoot.** The fix that matters is not a cooldown; it is arithmetic. Divide by the fleet that produced the measurement and swing goes 395 → 19, launches 1216 → 60, SLO 49.4% → 80.0%, **at zero cost in responsiveness**. The rest of the ladder buys stability (flips 5 → 1) for 24% more money and half a point of SLO — and the last row is the uncomfortable one, where 300-second smoothing spends **13.3 points of SLO** to remove 6 instances of swing. The extra row at the bottom is the insurance argument: rate limits alone, bolted onto the naive formula with nothing else fixed, take launches from 1216 to 291 and cap the peak at 194 instead of 400. They do not make the loop correct; they bound how wrong it gets in one step, which is what you want at 03:00.

**Section 3 is the metric argument, and the CPU row is the one to stare at.** The fleet sits at 15–25 instances while utilisation runs at **2.33× capacity**. The controller is not confused or slow — it is reading a number that is genuinely falling, 40% CPU on a completely full instance, and responding to it correctly. If you take one configuration change from this lesson, it is to add a concurrency metric alongside CPU and let the autoscaler take the maximum of the two recommendations.

**Section 5 is the headline.** Both runs get the identical 60-second hiccup on a database that was comfortably serving 400 req/s against a capacity of 426. The autoscaling run's goodput after the trigger clears is **exactly zero**, it never recovers, and it costs **172 instance-minutes** to achieve that. The shedding run holds 120 connections, keeps the database at 426 q/s, and is back to full goodput **five seconds** after the hiccup ends for 60 instance-minutes. Same trigger, same demand, same retry policy. The only difference is whether the app tier answered overload by growing or by refusing.

**Section 7** closes it. Reactive alone lets 1,187,371 requests miss the objective, almost all of them in the two windows where load changed fastest — the morning ramp and the campaign. Two scheduled floors take that to **zero** for 20.1% more spend. There is no algorithm in that improvement, only the removal of lag from the part of the day that was never uncertain.

## Use It

### Kubernetes HPA

The Horizontal Pod Autoscaler is target tracking with the formula from section 2 and a default 10% tolerance (hysteresis). What you must change:

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: checkout
spec:
  scaleTargetRef: { apiVersion: apps/v1, kind: Deployment, name: checkout }
  minReplicas: 12                      # the FLOOR. survives one zone, absorbs a spike.
  maxReplicas: 60                      # 60 x pool 10 = 600 conns. CHECK max_connections.
  metrics:
    - type: Pods                       # concurrency, via the custom-metrics adapter
      pods:
        metric: { name: http_inflight_requests }
        target: { type: AverageValue, averageValue: "12" }
    - type: Resource                   # CPU as the SECOND opinion, not the only one
      resource:
        name: cpu
        target: { type: Utilization, averageUtilization: 60 }
  behavior:
    scaleUp:
      stabilizationWindowSeconds: 0    # never delay growth
      policies:
        - { type: Percent, value: 100, periodSeconds: 60 }   # at most 2x per minute
        - { type: Pods,    value: 8,   periodSeconds: 60 }
      selectPolicy: Max
    scaleDown:
      stabilizationWindowSeconds: 300  # the asymmetry, in one field
      policies:
        - { type: Percent, value: 10, periodSeconds: 60 }    # at most 10% per minute
```

Four notes. **HPA takes the maximum recommendation across metrics** — listing both `http_inflight_requests` and CPU gives you exactly section 3's winning row, and it is the single highest-value change in this document. Serving a custom metric requires a metrics adapter (`prometheus-adapter` or the KEDA metrics server); the alternative, `type: External`, scales on something outside the cluster entirely, such as a cloud queue's depth. **`scaleDown.stabilizationWindowSeconds` defaults to 300 and `scaleUp`'s to 0** — the asymmetry is already correct out of the box; do not "fix" it. **`--horizontal-pod-autoscaler-sync-period` defaults to 15 s** and the metric pipeline behind it is typically 30–60 s, so your dead time is dominated by pod start time, which means the highest-leverage optimisation is a smaller image and a faster readiness probe. And **set `readinessProbe` to mean "warm", not "listening"** — a pod that is Ready gets full traffic immediately, so if it needs a minute to fill caches, the probe must not pass until it has.

### KEDA, for anything queue-driven

For worker fleets, scale on the queue, not on the workers. KEDA (Kubernetes Event-Driven Autoscaling) does this and adds the one thing HPA cannot: **scale to zero.**

```yaml
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata: { name: order-workers }
spec:
  scaleTargetRef: { name: order-worker }
  minReplicaCount: 2                  # not 0, if a cold start is user-visible
  maxReplicaCount: 40
  cooldownPeriod: 300
  triggers:
    - type: kafka
      metadata:
        topic: orders
        consumerGroup: order-workers
        lagThreshold: "200"           # target lag PER REPLICA
```

`lagThreshold` is a per-replica target, exactly like an HPA `averageValue`. [Phase 6's lesson on consumer lag](../../06-messaging-and-pub-sub/09-backpressure-lag-and-flow-control/) explains why lag is the right signal and what it does not tell you. Two traps specific to autoscaling here: **you cannot have more useful consumers than partitions**, so `maxReplicaCount` above the partition count buys idle pods; and scaling a consumer group triggers a **rebalance**, which pauses consumption, which raises lag, which can make the autoscaler scale again. Cooldowns matter more here than anywhere else.

### The layer below: Cluster Autoscaler and Karpenter

Pods do not run on nothing. When the HPA asks for pods and there is no room, a second autoscaler must add nodes — and **you now have two control loops in series, and their dead times add.** The pod autoscaler reacts in ~30 s; the node autoscaler must call a cloud API, wait for an instance to boot, join the cluster, and pull images, which is 60–180 s on top. Total dead time for a scale-out that needs new nodes is comfortably 4–6 minutes, and that is the number to plan against, not the pod number.

Two mitigations are worth knowing. **Overprovisioning with pause pods**: run a deployment of low-priority pods that do nothing, sized to a node or two. When real pods need room, the scheduler preempts the placeholders and the real pods start *immediately* on already-warm nodes, while the node autoscaler backfills in the background. It converts node-provisioning latency into a constant cost, which is a trade you can actually reason about. And **Karpenter**, which provisions instances directly from pending pods rather than resizing fixed node groups, is materially faster and picks instance types to fit, but it does not remove the boot time — it removes the group-management round trip.

### AWS Auto Scaling groups

```bash
# Target tracking: the same formula, with warmup built in.
aws autoscaling put-scaling-policy \
  --auto-scaling-group-name checkout-asg \
  --policy-name track-alb-rps \
  --policy-type TargetTrackingScaling \
  --estimated-instance-warmup 150 \
  --target-tracking-configuration '{
      "PredefinedMetricSpecification": {
        "PredefinedMetricType": "ALBRequestCountPerTarget",
        "ResourceLabel": "app/checkout-alb/xxx/targetgroup/checkout-tg/yyy" },
      "TargetValue": 100.0,
      "DisableScaleIn": false }'
```

`--estimated-instance-warmup` is the field that matters most and the one most often left at its default. It tells the ASG to **exclude an instance from the metric aggregation until it has been in service that long** — which is precisely the "count what you measured" fix from section 2, offered to you as a config value. Set it to boot time plus warm time, measured, not guessed. `ALBRequestCountPerTarget` is requests-per-instance, which is a better default than CPU whenever request cost is uniform; for anything else, publish a custom concurrency metric.

**Warm pools** (`aws autoscaling put-warm-pool`) keep pre-initialised instances in `Stopped` state at roughly storage-only cost, with the boot already done. They cut provisioning dead time from ~150 s to ~30 s and are the correct answer for a service with a genuinely slow start. **Predictive scaling** (`--policy-type PredictiveScaling`) forecasts from 14 days of history and provisions ahead; run it in `ForecastOnly` mode for a couple of weeks first and look at whether the forecast would have been right, because the answer for a bursty service is usually no. And **instance scale-in protection** (`aws autoscaling set-instance-protection`) is what a worker sets when it picks up a long job.

### Serverless: the extreme case

A function-as-a-service platform is autoscaling with the dead time driven almost to zero — a new execution environment in tens or hundreds of milliseconds, and no fleet to manage. It is also the purest demonstration of the wrong-tier failure in this lesson.

**A function that scales to 1,000 concurrent executions opens 1,000 database connections.** There is no pool to share, because there is no long-lived process to share it. Your Postgres has `max_connections = 100`. This is not a subtle interaction; it is section 5 with the safety rails removed, and it is why every serverless platform now ships a connection proxy (RDS Proxy, Data API, PgBouncer in front) and why **reserved concurrency is a database-protection mechanism, not a cost control.** Set it to a number your data tier can survive, and treat that number as the real limit on the whole system.

The other two things to configure: **provisioned concurrency** for anything user-facing, which keeps environments initialised and removes the cold start from the critical path at the cost of paying for idle; and a **reserved concurrency floor** on critical functions so that a burst in an unimportant function cannot consume the account-wide concurrency limit that your checkout path also draws from. That last one is a bulkhead ([Phase 8, Lesson 11](../../08-concurrency-and-performance/11-backpressure-and-load-shedding/)) applied to a quota.

### Reviewing an existing autoscaling policy

Run this against a policy you already have. Most fail four or more.

1. **What is the total dead time?** Add the scrape interval, the averaging window, the evaluation period, the instance boot, and the warmup. If you cannot state the number, that is the finding. If it exceeds twice the evaluation period, the loop is oscillating whether or not anyone has noticed.
2. **Does the metric go UP when the service is in trouble?** If it is CPU, the answer is no, and you will scale in during your next incident.
3. **Is there a concurrency or queue metric alongside CPU?** If not, add one and take the maximum. This is the highest-value single change available.
4. **Is scale-in slower than scale-out?** Different stabilisation windows, different rate limits. If they are symmetric, they are wrong.
5. **`max_replicas × pool_size` vs `max_connections`?** Do the multiplication now, in the review, on the actual numbers. This one has caused real outages.
6. **Does the instance get traffic before it is warm?** Check what the readiness probe actually asserts. "The port is open" is not warm.
7. **Is `min_replicas` sized to survive the loss of one failure domain, at peak, with no scaling action?** Lesson 9's static-stability argument. If losing a zone requires the autoscaler to work, you have a dependency on a control plane during the exact event that saturates it.
8. **Is there a guard against scaling in while the error rate is elevated?** And does the guard outlast the metric window?
9. **What is the scale-in termination grace period, and is it longer than the slowest request?** Otherwise every scale-in event drops in-flight work.
10. **Has anyone graphed fleet size on the same axes as demand for a full week?** The oscillation is invisible on a utilisation dashboard and obvious the moment you plot the two together.

For the metrics pipeline behind all of this — scrape intervals, aggregation windows, what a gauge can miss — see [Phase 9](../../09-logging-monitoring-and-observability/). For the deployment mechanics that decide how fast an instance can boot, see [Phase 10](../../10-infrastructure-and-deployment/).

## Think about it

1. Your autoscaler holds CPU at 60% and your fleet oscillates between 12 and 40 twice an hour. You are offered three fixes: a longer averaging window, a scale-in cooldown, or a base image that boots in 20 seconds instead of 90. Rank them by effect on the oscillation, and say which one also improves your SLO rather than trading it away.
2. Section 3's concurrency-based scaler achieved 98.7% SLO for 9857 instance-minutes, and `max(CPU, in-flight)` achieved 86.4% for 2627. Under what business conditions is the first one the right purchase? What would you need to know about your error budget to decide?
3. Your service autoscales on queue depth and scales to zero overnight. At 06:00 a batch job dumps 200,000 messages in one second. Trace what happens over the next ten minutes, including what the downstream database sees. What would you change, and what does your answer imply about `minReplicaCount`?
4. Section 5's autoscaling run never recovers. You are on call, the trigger is long gone, and you cannot restart (the fleet holds warm state). List the actions that break the loop, in the order you would try them, and say for each whether it reduces arrivals, increases capacity, or neither.
5. Your `min_size` is 4 and each instance can serve 100 req/s. You run in three availability zones and your peak is 900 req/s. Compute the minimum fleet that survives losing one zone at peak with no scaling action at all, and then argue for or against paying for it at 04:00 on a Sunday.

## Key takeaways

- **An autoscaler is a feedback control loop, and dead time is its dominant property.** Metric pipeline (60 s) + half the averaging window (30 s) + half the decision interval (30 s) + boot (90 s) + warmup (60 s) = **270 s = 4.5 minutes** against a loop that reacts in 60 s. A control loop cannot stabilise a plant whose dead time exceeds its reaction period; measured, the same controller on the same flat traffic went from **swing 1 / 33 launches / 100.0% SLO at zero dead time to swing 139 / 539 launches / 57.3% at 210 s**, with a limit cycle of 9.6 minutes against a predicted `2 × D` of 7.0.
- **The biggest single bug in target tracking is arithmetic, not tuning.** `desired = ceil(replicas × metric / target)` multiplies the fleet you have *now* by a ratio measured off the fleet you had a dead time ago, so instances still booting get ordered twice. Dividing by the fleet size that produced the measurement is free — no lag, no cooldown — and moved swing **395 → 19**, launches **1216 → 60**, SLO **49.4% → 80.0%**.
- **CPU is the default metric and usually the wrong one.** It is not proportional to load for I/O-bound work — a saturated instance at 8 slots / 120 ms reads **40% CPU** — and it *falls* when your service starts failing. In the measurement CPU delivered **45.1% SLO at ρ = 2.33**, in-flight concurrency delivered **98.7% at 7.9× the cost**, and **`max(CPU, in-flight)` delivered 86.4% at 2627 instance-minutes**, because the bottleneck moved and only that controller followed it.
- **Every stabiliser trades responsiveness for stability; smoothing trades it badly.** Cooldowns and hysteresis took direction flips from 5 to 1 for 24% more money. A **300-second averaging window cost 13.3 points of SLO** to remove 6 instances of swing, because a longer average *is* more dead time. Scale out fast, scale in slowly, and reach for smoothing last.
- **Scaling in is the dangerous direction, and an outage makes it worse.** With no guard, a 25-minute dependency failure took the fleet **from 18 to 9** — the 10%-per-interval rate limit was the only thing preventing a collapse to the floor — and cost **270 seconds of further SLO breach after the dependency recovered**, versus **0 s** with a two-clause guard that blocks scale-in while errors are elevated *and* for one full metric window afterwards.
- **Autoscaling into a retry storm sustains it.** The autoscaler cannot distinguish a retry from a request, and a retry ends by succeeding, not by being served quickly. Measured: the fleet grew 6 → 20, wanted **400 connections against a `max_connections` of 300**, and dragged the database from **426 to 247 q/s** along the USL curve — **goodput exactly zero, never recovering, for 172 instance-minutes**. The same trigger with load shedding and the fleet pinned: **400 req/s of goodput, recovery in 5 s, 60 instance-minutes.** Check `max_replicas × pool_size` against `max_connections` before you ship.
- **A launched instance is not capacity.** 90 s booting at 0 req/s, then 60 s warming at 25 req/s: **worth 10% of an instance over its first 150 seconds, billed at 100% from second zero.** Slow start (LB weight ∝ capacity) beat both full traffic (**99.3% vs 97.3%**) and gating (98.7%), because gating throws away the quarter-instance you had exactly when you needed it.
- **Autoscaling is for cost; buy reliability with a floor.** Scheduled floors on a predictable diurnal curve took a reactive-only policy from **98.56% and 1,187,371 missed requests to 100.00% and zero, for 20.1% more spend**. And during a real failure the autoscaler is a dependency — contended control plane, contended capacity pool, binding quota — so `min_size` must be large enough to survive the loss of a failure domain *with no scaling action at all*. Tune `max_size` to bound your bill; tune `min_size` to bound your outage.

Next: [Capstone: Survive the Region Loss](../14-capstone-survive-the-region-loss/) — every mechanism in this phase assembled into one system, and then the region it lives in is taken away.
