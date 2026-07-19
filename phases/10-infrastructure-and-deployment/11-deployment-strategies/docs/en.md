# Deployment Strategies: Rolling, Blue-Green & Canary

> The same fleet, the same traffic, the same broken release — pushed four different ways. Recreate cost **9,689 user-facing errors**, rolling **452**, blue-green **162**, and a 5% canary with automated analysis **20**. Blue-green *detected the problem fastest of the three that got a signal at all* and still cost 8.1× more than the canary, because blast radius is exposure × time and it optimised only the clock. Then the part nobody measures: a 1% canary baked for five minutes on a 60 req/s service sees 180 requests, has **41.9% statistical power**, and promoted a genuinely broken release **five times out of eight**.

**Type:** Build
**Languages:** Python
**Prerequisites:** [Reverse Proxies, Load Balancers & Ingress](../09-reverse-proxies-and-load-balancers/), [Orchestration: Control Loops, Schedulers & Kubernetes](../07-orchestration-and-kubernetes/), [SLIs, SLOs & Error Budgets](../../09-logging-monitoring-and-observability/09-slis-slos-and-error-budgets/)
**Time:** ~85 minutes

## The Problem

Two scenes. Both real. The loud one is the one everybody remembers, and the quiet one is the one that costs more.

**11:00 on a Tuesday.** Someone runs the deploy. The old process stops, the new one starts, and for four minutes the site is a connection-refused error. The graph is a cliff. The incident channel fills up. Somebody says "we should really do zero-downtime deploys" and everyone agrees, and it goes on the backlog. This failure is *loud* — it announces itself, it is trivially attributable, and it is over in four minutes. It is the cheapest kind of outage you will ever have.

**14:40 on a Thursday.** The deploy "succeeds". The rollout controller reports all replicas updated and healthy. Every dashboard is green. CPU is normal, memory is normal, latency is normal, the deploy pipeline is a wall of green ticks, and the person who shipped it goes to a meeting.

Three percent of requests are failing. They have been failing since 14:22.

They are not visible because 3% of your traffic is inside the noise band of every graph you own. Your error-rate panel is scaled to a y-axis that makes 3% a thickening of the line. Your alert threshold is 5%, chosen in a meeting nobody remembers, and 3% is comfortably under it. Your synthetic checks pass, because they exercise the happy path. Your p99 latency is *fine*, because failing fast is fast.

It runs for **six hours**. Twenty thousand people hit an error, most of them retry, some of them succeed, and a handful open support tickets that get triaged as "user error" because nobody can reproduce it. At 20:50 an engineer investigating something else notices a spike in a log field and connects it to the 14:22 deploy. Time to detection: 6 hours 28 minutes. Time to mitigation after detection: 90 seconds, because rolling back is one command.

**The gap between those two numbers is the entire subject of this lesson.** The four minutes of downtime was a capacity problem, and capacity problems are easy — you can see them. The six hours was an *observation* problem: the deploy strategy exposed 100% of users to a bad version and then had nothing watching the one signal that would have shown it. Nobody was measuring, because "the deploy succeeded" and success was defined as "the pods are running."

A deployment strategy is not a preference about downtime. It is a decision about **how many users are exposed to a change you have not yet verified, for how long, and what evidence you will require before exposing more.**

## The Concept

### A deploy is a state transition of a fleet

Forget the tooling for a moment. You have N machines serving traffic on version A. You want N machines serving traffic on version B. Every deployment strategy is a different **path** between those two states, and each path trades four things against each other:

- **Capacity** — how much serving capability you have at the worst moment of the transition.
- **Cost** — how many machines you pay for at the peak.
- **Blast radius** — how many users touch the new version before you know whether it works.
- **Time** — how long the transition takes, and how long a rollback takes.

There is no strategy that wins on all four. That is the whole design space, and once you can see it, the named strategies stop being a menu and become points on a surface. The rest of this section walks the points.

Two definitions we will use throughout. An **SLO** (Service Level Objective) is the reliability target you promise — here, 99.9% of requests succeed. The **error budget** is its complement: 0.1% of requests may fail. A **burn rate** is how fast you are consuming that budget relative to spending it evenly over the period; a burn rate of 14.4× means you would exhaust a 30-day budget in about two days, and it is the standard fast-burn alerting threshold from the Google SRE Workbook (ch. 5, "Alerting on SLOs"). At a 0.1% budget, a 14.4× burn is an error ratio of **1.44%** — that single number is the abort signal for everything below.

### Recreate: stop all, start all

Terminate every instance, then start the new ones. Downtime equals startup time, exactly, with no cleverness available to reduce it.

It is not a mistake in every context. **Use it when concurrent versions are unsafe**: a batch worker holding an exclusive lock, a singleton scheduler, a process that owns a file that must not be written by two versions at once, a migration runner. In those cases "both versions running simultaneously" is the failure, and buying downtime to prevent it is correct.

Never use it for anything a user is waiting on. And there is a second, subtler reason beyond the downtime, which the Build It measures: **during a recreate you have no traffic, and therefore no signal.** Your error-*ratio* SLI is errors divided by requests. When the denominator is zero, the ratio is undefined and a ratio-based alert cannot fire at all. A recreate blinds the exact instrument you would use to decide whether the new version is safe, and hands it back to you only after 100% of users are already on it.

### Rolling: batches, and the capacity arithmetic nobody does

Replace instances a few at a time. Two knobs govern it, and they are the most consequential numbers in this lesson:

- **`maxUnavailable`** — how far below the desired replica count availability may drop.
- **`maxSurge`** — how far above the desired replica count the total may rise.

Kubernetes rounds `maxUnavailable` **down** and `maxSurge` **up**, both computed from the replica count (Kubernetes API reference, `RollingUpdateDeployment`). On 10 replicas, `25%` means `maxUnavailable: 2` and `maxSurge: 3`.

Now do the arithmetic that almost nobody does. **`maxUnavailable: 25%` means you run at 75% capacity during every single deploy.** If your steady-state utilisation is 40%, 75% capacity puts you at 53% and nothing happens. If your steady-state utilisation is 85%, 75% capacity puts you at **113%** — and 113% is not a percentage, it is a deficit that accumulates for the whole length of the rollout. You have arranged for every deploy to be a self-inflicted overload, complete with the queueing collapse from [Backpressure, Queueing & Load Shedding](../../08-concurrency-and-performance/11-backpressure-and-load-shedding/): as utilisation ρ approaches 1, latency goes to infinity, and past 1 the queue simply grows until something dies.

The Build It sweeps this and prints the exact crossover. The rule that falls out:

> **At high utilisation, `maxUnavailable > 0` means every deploy is an outage you scheduled yourself.** `maxSurge` buys the capacity back — for money.

The other defining property of rolling, and the one with the longest tail of consequences: **both versions serve production traffic at the same time.** For minutes. This is not a detail, it is a contract. Version A and version B must both be able to read and write the same database, honour the same API responses, and consume the same message formats — in both directions, because a request handled by B might be followed by one handled by A. That constraint is called N/N+1 compatibility and it is the subject of lesson 13; every "expand/contract" migration pattern exists because of the paragraph you just read.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 540" width="100%" style="max-width:840px" role="img" aria-label="Four deployment strategies drawn as fleet timelines over 110 simulated seconds, with bar height showing how many of the ten instances are running and the colour showing which version they serve. Recreate has two twenty-second periods of zero capacity separated by seven seconds of the bad version at full exposure. Rolling replaces instances in waves, dipping to eight available and reaching seventy-five percent bad-version exposure before it is aborted at forty-two seconds. Blue-green runs twenty instances at once and cuts the router over to a hundred percent bad exposure for twelve seconds. Canary adds one instance and sends it five percent of traffic for twenty-two seconds. Each row lists its detection time, its mitigation time, and its point of no return.">
  <text x="440" y="24" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">Four paths through the same state transition — and what each one exposes</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">

    <g font-size="9">
      <rect x="150" y="44" width="11" height="11" rx="2" fill="#0fa07f" fill-opacity="0.55" stroke="#0fa07f" stroke-width="1.2"/>
      <text x="166" y="53" fill="currentColor" opacity="0.9">old version, serving</text>
      <rect x="300" y="44" width="11" height="11" rx="2" fill="#e0930f" fill-opacity="0.55" stroke="#e0930f" stroke-width="1.2"/>
      <text x="316" y="53" fill="currentColor" opacity="0.9">booting, no traffic yet</text>
      <rect x="466" y="44" width="11" height="11" rx="2" fill="#d64545" fill-opacity="0.62" stroke="#d64545" stroke-width="1.2"/>
      <text x="482" y="53" fill="currentColor" opacity="0.9">new version, serving users</text>
      <rect x="662" y="44" width="11" height="11" rx="2" fill="#7f7f7f" fill-opacity="0.35" stroke="#7f7f7f" stroke-width="1.2"/>
      <text x="678" y="53" fill="currentColor" opacity="0.9">idle, still billed</text>
    </g>
    <text x="150" y="70" font-size="9" fill="currentColor" opacity="0.7">bar height = instances running (1 instance = 4 px, fleet = 10)</text>

    <g fill="none" stroke="currentColor" stroke-width="1" opacity="0.18">
      <path d="M273.6 82 L 273.6 430"/><path d="M397.2 82 L 397.2 430"/><path d="M520.8 82 L 520.8 430"/><path d="M644.4 82 L 644.4 430"/><path d="M768 82 L 768 430"/>
    </g>

    <g font-size="11" font-weight="700" fill="currentColor">
      <text x="14" y="106">RECREATE</text><text x="14" y="192">ROLLING</text><text x="14" y="290">BLUE-GREEN</text><text x="14" y="390">CANARY</text>
    </g>
    <g font-size="8.5" fill="currentColor" opacity="0.85">
      <text x="14" y="119">detect 25s</text><text x="14" y="131">fixed  47s</text>
      <text x="14" y="205">detect 40s</text><text x="14" y="217">fixed  82s</text>
      <text x="14" y="303">detect 30s</text><text x="14" y="315">fixed  32s</text>
      <text x="14" y="403">detect 40s</text><text x="14" y="415">fixed  42s</text>
    </g>
    <g font-size="8.5" font-weight="700">
      <text x="14" y="143" fill="#d64545">9,689 errors</text><text x="14" y="229" fill="#d64545">452 errors</text><text x="14" y="327" fill="#e0930f">162 errors</text><text x="14" y="427" fill="#0fa07f">20 errors</text>
    </g>

    <rect x="150" y="100" width="123.6" height="40" rx="3" fill="#d64545" fill-opacity="0.12" stroke="#d64545" stroke-width="1.6" stroke-dasharray="5 4"/>
    <rect x="273.6" y="100" width="43.3" height="40" rx="3" fill="#d64545" fill-opacity="0.62" stroke="#d64545" stroke-width="1.4"/>
    <rect x="316.9" y="100" width="123.6" height="40" rx="3" fill="#d64545" fill-opacity="0.12" stroke="#d64545" stroke-width="1.6" stroke-dasharray="5 4"/>
    <rect x="440.5" y="100" width="389.5" height="40" rx="3" fill="#0fa07f" fill-opacity="0.55" stroke="#0fa07f" stroke-width="1.4"/>
    <text x="211" y="124" font-size="9.5" font-weight="700" text-anchor="middle" fill="#d64545">ZERO CAPACITY 20s</text>
    <text x="378" y="124" font-size="9.5" font-weight="700" text-anchor="middle" fill="#d64545">ZERO CAPACITY 20s</text>
    <text x="295" y="92" font-size="8.5" font-weight="700" text-anchor="middle" fill="#d64545">100%</text>

    <g stroke-width="1.1">
      <rect x="150" y="192" width="123.6" height="32" fill="#0fa07f" fill-opacity="0.55" stroke="#0fa07f"/>
      <rect x="150" y="180" width="123.6" height="12" fill="#e0930f" fill-opacity="0.55" stroke="#e0930f"/>
      <rect x="273.6" y="204" width="123.6" height="20" fill="#0fa07f" fill-opacity="0.55" stroke="#0fa07f"/>
      <rect x="273.6" y="192" width="123.6" height="12" fill="#d64545" fill-opacity="0.62" stroke="#d64545"/>
      <rect x="273.6" y="180" width="123.6" height="12" fill="#e0930f" fill-opacity="0.55" stroke="#e0930f"/>
      <rect x="397.2" y="216" width="136" height="8" fill="#0fa07f" fill-opacity="0.55" stroke="#0fa07f"/>
      <rect x="397.2" y="192" width="136" height="24" fill="#d64545" fill-opacity="0.62" stroke="#d64545"/>
      <rect x="397.2" y="180" width="136" height="12" fill="#e0930f" fill-opacity="0.55" stroke="#e0930f"/>
      <rect x="533.2" y="204" width="123.6" height="20" fill="#0fa07f" fill-opacity="0.55" stroke="#0fa07f"/>
      <rect x="533.2" y="192" width="123.6" height="12" fill="#d64545" fill-opacity="0.62" stroke="#d64545"/>
      <rect x="533.2" y="180" width="123.6" height="12" fill="#e0930f" fill-opacity="0.55" stroke="#e0930f"/>
      <rect x="656.8" y="192" width="123.6" height="32" fill="#0fa07f" fill-opacity="0.55" stroke="#0fa07f"/>
      <rect x="656.8" y="184" width="123.6" height="8" fill="#e0930f" fill-opacity="0.55" stroke="#e0930f"/>
      <rect x="780.4" y="184" width="49.6" height="40" fill="#0fa07f" fill-opacity="0.55" stroke="#0fa07f"/>
    </g>
    <text x="465" y="174" font-size="8.5" font-weight="700" text-anchor="middle" fill="#d64545">75% of users on the bad version</text>
    <path d="M409.6 226 L 409.6 236" stroke="#3553ff" stroke-width="2"/>
    <text x="412" y="245" font-size="8.5" font-weight="700" fill="#3553ff">abort 42s</text>

    <g stroke-width="1.1">
      <rect x="150" y="296" width="123.6" height="40" fill="#0fa07f" fill-opacity="0.55" stroke="#0fa07f"/>
      <rect x="150" y="256" width="123.6" height="40" fill="#e0930f" fill-opacity="0.55" stroke="#e0930f"/>
      <rect x="273.6" y="296" width="74.2" height="40" fill="#7f7f7f" fill-opacity="0.35" stroke="#7f7f7f"/>
      <rect x="273.6" y="256" width="74.2" height="40" fill="#d64545" fill-opacity="0.62" stroke="#d64545"/>
      <rect x="347.8" y="296" width="482.2" height="40" fill="#0fa07f" fill-opacity="0.55" stroke="#0fa07f"/>
      <rect x="347.8" y="256" width="185.4" height="40" fill="#7f7f7f" fill-opacity="0.35" stroke="#7f7f7f"/>
    </g>
    <g font-size="8.5" fill="currentColor">
      <text x="158" y="320" font-weight="700">BLUE env — 10 inst</text><text x="158" y="278" font-weight="700" opacity="0.9">GREEN env — booting</text>
      <text x="357" y="280" opacity="0.8">idle, still billed -&gt; deleted</text>
      <text x="310.7" y="250" font-size="8.5" font-weight="700" text-anchor="middle" fill="#d64545">100% cut over</text>
    </g>
    <text x="273.6" y="348" font-size="8.5" font-weight="700" fill="#d64545">20 instances billed for 32 s</text>

    <g stroke-width="1.1">
      <rect x="150" y="380" width="123.6" height="40" fill="#0fa07f" fill-opacity="0.55" stroke="#0fa07f"/>
      <rect x="150" y="374" width="123.6" height="6" fill="#e0930f" fill-opacity="0.55" stroke="#e0930f"/>
      <rect x="273.6" y="380" width="136" height="40" fill="#0fa07f" fill-opacity="0.55" stroke="#0fa07f"/>
      <rect x="273.6" y="374" width="136" height="6" fill="#d64545" fill-opacity="0.72" stroke="#d64545"/>
      <rect x="409.6" y="380" width="420.4" height="40" fill="#0fa07f" fill-opacity="0.55" stroke="#0fa07f"/>
    </g>
    <path d="M470 368 L 400 374" fill="none" stroke="#d64545" stroke-width="1.3"/>
    <text x="474" y="366" font-size="8.5" font-weight="700" fill="#d64545">1 instance, 5% weight, 264 requests total</text>
    <text x="158" y="404" font-size="8.5" font-weight="700" fill="currentColor">10 instances untouched throughout</text>

    <path d="M150 430 L 836 430" fill="none" stroke="currentColor" stroke-width="1.4"/>
    <g fill="currentColor" font-size="9" opacity="0.75" text-anchor="middle">
      <text x="150" y="444">0s</text><text x="273.6" y="444">20s</text><text x="397.2" y="444">40s</text><text x="520.8" y="444">60s</text><text x="644.4" y="444">80s</text><text x="768" y="444">100s</text>
    </g>

    <text x="14" y="472" font-size="9.5" font-weight="700" fill="#7c5cff">POINT OF</text>
    <text x="14" y="484" font-size="9.5" font-weight="700" fill="#7c5cff">NO RETURN</text>
    <g font-size="9" fill="currentColor">
      <text x="150" y="468">recreate   t = 0. The old pods are gone; a rollback is a second full outage.</text>
      <text x="150" y="482">rolling    when the old ReplicaSet reaches 0 (t = 60 here). Before that, undo is a reverse roll.</text>
      <text x="150" y="496">blue-green none while blue is still running — that is exactly what the doubled bill buys.</text>
      <text x="150" y="510">canary     none. 95% of the fleet was never touched.</text>
    </g>
    <text x="440" y="532" font-size="11" text-anchor="middle" fill="currentColor" opacity="0.9">Same fleet, same traffic, same bad version. Only the path differs — and the path is the blast radius.</text>
  </g>
</svg>
```

### Blue-green: two environments, one router change

Stand up a complete second environment ("green") alongside the running one ("blue"). Verify it out of band. Then change one thing — the router's target — and 100% of traffic moves. Roll back by changing it back.

**Near-instant rollback is the entire point**, and it is a real one: in the measured run, mitigation took **2 seconds** from decision, against 42 seconds for a rolling rollback that had to boot replacement instances. You are not deploying code at cutover time; you are deploying a *pointer*.

Two costs. The obvious one is money: you pay for **twice the fleet** during the transition — 20 instances instead of 10 in the measurement. The unobvious one is the one that gets skipped in every summary of this technique:

> **The database is almost always shared between blue and green.** Blue-green gives you instant *code* rollback and **no schema rollback at all.**

If green ran a migration that dropped a column, blue cannot serve after you cut back. If green wrote rows in a format blue cannot parse, cutting back gives you a *different* outage. The router flip is atomic; the data is not. Whether your rollback path includes the database is a question you must answer *before* you start, not during, and the honest answer for most teams is "no" — which is why lesson 13 exists and why every schema change is expand-then-contract.

Blue-green also does nothing for blast radius. It exposes **100% of users at once**, on purpose. It converts a slow bad deploy into a fast bad deploy that you can undo quickly, which is a genuine improvement, and is not the same thing as not breaking people.

### Canary: route a fraction, measure, decide

Send a small slice of real traffic to the new version. **Measure it.** Promote or abort on the evidence.

The mechanism is a weighted router (Phase 10 lesson 9 built the load balancer this sits on). The *discipline* is everything else. State the failure mode plainly, because it is the single most common way canary deployments disappoint:

> **A canary without automated analysis is just a slow deploy.** If the promotion decision is a human glancing at a dashboard and saying "looks fine," you have added latency to your pipeline and bought approximately nothing.

Two properties make a canary work, and both are quantitative:

**The abort signal must be tied to your SLO, not to a human's judgement.** "Error rate looks a bit high" is not a decision procedure. "Error ratio over the last 30 seconds exceeds a 14.4× burn of the error budget" is — it is computable, it fires at 03:00 without anyone awake, and it is denominated in the thing you actually promised users. The Build It measures the difference between an automated abort and a modelled human loop, and it is not close.

**The canary must be big enough and baked long enough to see the thing you are looking for.** This is the part that gets skipped, and it is the senior insight of the lesson, so it gets its own section below.

The measured payoff: at 5% exposure with automated analysis, the same bad release cost **20 user-facing errors** against blue-green's **162** — 8.1× smaller — even though blue-green *detected it 10 seconds sooner*.

### Shadow traffic: measure without exposing anyone

**Shadow** (or mirrored) deployment copies real production requests to the new version and **discards its responses**. Users are served entirely by the old version and cannot be affected by the new one. You get real traffic shapes, real payloads, real cardinality — the things synthetic load never reproduces — at zero user risk.

The trap is side effects, and it is severe: **the shadow copy will do everything the request tells it to do.** It will write rows. It will charge cards. It will send emails. It will publish messages that downstream consumers act on. It will increment your metrics twice. Shadowing is safe only for genuinely read-only paths, or after you have stubbed every write, every outbound call, and every publish — which is a real engineering project, not a config flag. Shadow also doubles the load on any dependency you did *not* stub, which is its own way of causing the incident you were trying to avoid.

Use it for: performance comparison, deserialization and parsing changes, rewrite-in-a-new-language projects, cache-hit-rate comparisons. Do not use it as a substitute for a canary, because it can never tell you whether the response was *correct* from the user's point of view — nobody received it.

### A/B testing is not a canary

These use the same routing mechanism and share nothing else. Getting them confused leads to teams believing they have release safety when what they have is a product experiment.

**A canary is a release-safety mechanism.** It measures **system health** — error rate, latency, saturation. It compares the new version against the old version *of the same code*. It runs for minutes. It is evaluated by an automated job against a threshold derived from your error budget, and the possible outcomes are "promote" and "abort". Assignment can be arbitrary, because you are measuring the *server*.

**An A/B test is a product experiment.** It measures **user behaviour** — conversion, click-through, retention, revenue per session. It compares two intentional product variants, both of which are working correctly. It runs for days or weeks, because behavioural effects are small and human variance is large. It is evaluated by a product decision, and the possible outcomes are "ship variant B" and "keep variant A". Assignment must be *sticky per user*, because a user who sees a different variant on every page load is not in an experiment, they are in a bug.

One is asking "is this build broken?". The other is asking "do people like this more?". A green A/B test tells you nothing about whether your release is safe, and a green canary tells you nothing about whether the feature is good.

### Bake time: why promotion needs a waiting period

**Bake time** is the minimum observation window before a rollout step is allowed to advance. It exists because several classes of failure are invisible immediately after a process starts:

- **Memory leaks and file-descriptor leaks** need time to accumulate to a visible level.
- **Cold caches** make a new instance look slow for the first minutes and then look fine — and can equally mask a real regression under a warming curve.
- **Periodic work** — a cron, a five-minute batch flush, an hourly report — only breaks when it fires.
- **Connection-pool exhaustion** appears at the point where the pool saturates, not at start-up.
- **Statistical significance**, which is the one everybody forgets, and which sets a hard floor on bake time regardless of the other four.

That last item is the link to the next section. Bake time is not a vibe. It is `required_sample_size / (canary_fraction × request_rate)`, and if the number that comes out is longer than you are willing to wait, your canary fraction is too small — not your patience.

## Build It

[`code/deploy_strategies.py`](code/deploy_strategies.py) is a discrete-time fleet simulator: ten instances, a weighted router, one bad version, and five numbered arguments. Standard library only, seeded with `random.Random(7)`, runs in well under a second.

Everything is held constant except the rollout path:

```text
fleet          10 instances x 40 req/s = 400 req/s capacity
offered load   240 req/s  ->  utilisation 0.60
instance boot  20 s from launch to ready (identical for every strategy)
old version    error rate 0.0500%
NEW version    error rate 6.0000%   <-- 120x worse. Nobody knows yet.
SLO 99.9% availability -> error budget 0.10%
abort signal   14.4x burn rate = error ratio > 1.44% over a 30s window,
               evaluated every 5s, minimum 200 requests, 2s to act
```

Each strategy is a small controller answering three questions every simulated second: how many old instances are ready, how many new ones are, and what fraction of traffic the router is sending to the new version. Recreate is the shortest, and it is the shape of the whole file:

```python
class Recreate(Rollout):
    """Stop all, start all. Downtime == startup time, by construction."""

    def tick(self, t: int) -> None:
        if self.phase == "pending" and t >= 0:
            self.old, self.booting = 0, N          # everything dies at once
            self.ready_at, self.phase = t + STARTUP, "boot-new"
        elif self.phase == "boot-new" and t >= self.ready_at:
            self.booting, self.new, self.phase = 0, N, "serving-new"
        elif self.phase == "boot-old" and t >= self.ready_at:
            self.booting, self.old, self.phase = 0, N, "rolled-back"

    def abort(self, t: int) -> None:
        # Rolling back a recreate is another recreate: a second full outage.
        self.new, self.booting = 0, N
        self.ready_at, self.phase = t + STARTUP, "boot-old"
```

The rolling controller is the only one with real arithmetic in it, and the two lines that matter are the invariants — they are what `maxSurge` and `maxUnavailable` actually *mean*:

```python
def _wave(self, t: int) -> bool:
    w = self.surge if self.surge > 0 else self.unavail
    want = (N - self.new) if self.direction == "forward" else (N - self.old)
    k = min(w, want)
    if k <= 0:
        self.booting, self.boot_kind = 0, None
        return False
    self.booting = k
    self.boot_kind = "new" if self.direction == "forward" else "old"
    # Terminate old capacity only while we stay above the availability floor.
    headroom = max(0, (self.old + self.new) - (N - self.unavail))
    if self.direction == "forward":
        self.old -= min(self.unavail, k, self.old, headroom)
    else:
        self.new -= min(self.unavail, k, self.new, headroom)
    self.ready_at = t + STARTUP
    return True
```

`headroom` is the whole safety property: the controller will not terminate another instance once availability has reached `N − maxUnavailable`, no matter how much it wants to make progress. Note that `_wave` runs in both directions — a rollback is another rolling update, back to the previous spec, with the same knobs. That symmetry is why the rolling rollback in the measurement takes 42 seconds.

The detector is deliberately the same code for all four strategies, and the only parameter that differs is *what it looks at*:

```python
obs, err = (srv_new, e_new) if scope == "canary" else (srv_new + srv_old,
                                                      e_new + e_old)
win.append((t, obs, err))
while win and win[0][0] <= t - WINDOW:
    win.popleft()

if t >= 0 and t % EVAL_EVERY == 0 and detect_at is None:
    n = sum(o for _, o, _ in win)
    k = sum(e for _, _, e in win)
    if n >= MIN_SAMPLES and k / n > THRESHOLD:
        detect_at = t
        abort_at = t + lag
```

A fleet-scoped detector sees the bad version **diluted** by every instance still on the old one. A canary-scoped detector sees it undiluted. That is one `if` expression and it is worth more than any other line in the file. The `n >= MIN_SAMPLES` guard is the sample-size gate; section 4 is about what happens when you leave it out or set it by feel.

Run it:

```bash
docker compose exec -T app python \
  phases/10-infrastructure-and-deployment/11-deployment-strategies/code/deploy_strategies.py
```

```console
== 2 · BLAST RADIUS: THE SAME BAD VERSION, FOUR ROLLOUT PATHS ==
  identical fleet, identical traffic, identical bad version.
  the only difference is the path the deploy takes through the fleet.

  strategy      user errors   dropped   detect  mitigate   peak exp   min cap   peak inst
  recreate            9689      9600      25s       47s      100%        0%       10
  rolling              452         0      40s       82s       75%       80%       11
  blue-green           162         0      30s       32s      100%      100%       20
  canary                20         0      40s       42s        5%      100%       11
  'user errors' = requests the DEPLOY broke: dropped for want of capacity,
  plus failures served by the new version. (46 more happened in
  the same window at the old version's baseline rate, deploy or no deploy.)

  requests SERVED BY THE BAD VERSION before it was pulled:
    recreate        1680
    rolling         7560
    blue-green      2880
    canary           264

  blast radius is exposure x time, and strategies trade one for the other:
    blue-green detected in 30s — fastest of the three that got a signal, at 100% of users exposed
    canary     detected in 40s — slower, at 5% of users exposed
    and the canary still wins, because 40s x 5% beats 30s x 100%:
    canary vs recreate      9689 user errors ->   20   =  484.4x smaller blast radius
    canary vs rolling        452 user errors ->   20   =   22.6x smaller blast radius
    canary vs blue-green     162 user errors ->   20   =    8.1x smaller blast radius

  recreate detected fastest of all (25s) and it bought nothing:
  9600 of its 9689 errors came from having ZERO instances, and
  rolling back a recreate is another recreate — a second 20s outage.
  during those first 20s the fleet served 0 requests, so the error RATIO
  had a zero denominator and the alert could not fire at all: a ratio-based
  SLI can stay silent through the worst minute of your year.
```

Read the table twice, because the second reading is where the lesson is.

**First reading: the ranking.** Recreate 9,689 errors, rolling 452, blue-green 162, canary 20. The canary's blast radius is **484× smaller than recreate's, 22.6× smaller than rolling's, and 8.1× smaller than blue-green's**. That is the headline and it is what you would expect.

**Second reading: recreate detected fastest and it did not matter.** Recreate got its signal at **25 seconds**, sooner than rolling (40 s) or blue-green (30 s), because once its instances finally came up, 100% of a 6% error rate is impossible to miss. And **9,600 of its 9,689 errors were requests that reached no instance at all** — the bad version was almost irrelevant to the damage. Detection bought nothing because the rollback was another 20-second outage. **Recreate is the only strategy here whose blast radius is unrelated to whether the release was any good.**

**Third reading, and the one worth arguing about: blue-green detected 10 seconds before the canary and cost 8.1× more.** This is the result that corrects most people's intuition, because most incident post-mortems optimise time-to-detect and stop there. Blast radius is a product:

```text
blue-green:  30 s of detection + 2 s to act, at 100% exposure  ->  2,880 bad requests served
canary:      40 s of detection + 2 s to act, at   5% exposure  ->    264 bad requests served
```

The canary was *slower* on the clock and still served **11× fewer requests to the broken version**, because it was multiplying by 0.05 the whole time. Optimising only detection time optimises half the product. It is also worth noting where rolling lands: it served **7,560 requests to the bad version — more than any other strategy, including blue-green** — because it sat at intermediate exposure for a long time and then took 42 seconds to unwind. Rolling's low error count relative to recreate comes from never losing capacity, not from limiting exposure.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 470" width="100%" style="max-width:840px" role="img" aria-label="Measured blast radius of one bad deploy under four rollout strategies, drawn on a logarithmic axis. Recreate caused 9689 user-facing errors, rolling 452, blue-green 162 and canary 20. A table below gives detection time, mitigation time, peak user exposure, minimum serving capacity and peak instance count for each: recreate detected in 25 seconds but had zero capacity for forty seconds; rolling detected in 40 seconds and took 82 seconds to mitigate at 75 percent peak exposure; blue-green detected in 30 seconds and mitigated in 32 by flipping the router, at double the instance cost; canary detected in 40 seconds and mitigated in 42 at five percent exposure and one extra instance.">
  <text x="440" y="24" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">Blast radius, measured: user-facing errors from one bad deploy</text>
  <text x="440" y="42" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="10" fill="currentColor" opacity="0.85">10 instances · 240 req/s · new version fails 6% of requests · abort at a 14.4x error-budget burn rate</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">

    <g fill="none" stroke="currentColor" stroke-width="1" opacity="0.22">
      <path d="M120 62 L 120 236"/><path d="M346.7 62 L 346.7 236"/><path d="M573.3 62 L 573.3 236"/><path d="M800 62 L 800 236"/>
    </g>
    <g fill="currentColor" font-size="9" opacity="0.7" text-anchor="middle">
      <text x="120" y="252">10</text><text x="346.7" y="252">100</text><text x="573.3" y="252">1,000</text><text x="800" y="252">10,000</text>
    </g>
    <text x="460" y="266" font-size="9.5" text-anchor="middle" fill="currentColor" opacity="0.8">user-facing errors caused by the deploy (log scale)</text>

    <g stroke-width="1.5">
      <rect x="120" y="72" width="677" height="26" rx="4" fill="#d64545" fill-opacity="0.55" stroke="#d64545"/>
      <rect x="120" y="112" width="375" height="26" rx="4" fill="#e0930f" fill-opacity="0.5" stroke="#e0930f"/>
      <rect x="120" y="152" width="274" height="26" rx="4" fill="#e0930f" fill-opacity="0.5" stroke="#e0930f"/>
      <rect x="120" y="192" width="68" height="26" rx="4" fill="#0fa07f" fill-opacity="0.55" stroke="#0fa07f"/>
    </g>
    <g fill="currentColor" font-size="10.5" font-weight="700" text-anchor="end">
      <text x="112" y="90">recreate</text><text x="112" y="130">rolling</text><text x="112" y="170">blue-green</text><text x="112" y="210">canary</text>
    </g>
    <g font-size="11" font-weight="700">
      <text x="807" y="90" fill="#d64545">9,689</text><text x="505" y="130" fill="#e0930f">452</text><text x="404" y="170" fill="#e0930f">162</text><text x="198" y="210" fill="#0fa07f">20</text>
    </g>
    <g font-size="9" fill="currentColor" opacity="0.85">
      <text x="606" y="200">the canary's blast radius:</text><text x="606" y="212">8.1x smaller than blue-green</text><text x="606" y="224">22.6x smaller than rolling</text><text x="606" y="236">484x smaller than recreate</text>
    </g>
    <text x="130" y="90" font-size="9" fill="currentColor" opacity="0.9">9,600 of these are requests that hit NO instance at all</text>

    <g fill="none" stroke-width="1.6">
      <rect x="14" y="286" width="852" height="128" rx="10" fill="#7f7f7f" fill-opacity="0.07" stroke="currentColor" stroke-opacity="0.35"/>
    </g>
    <g fill="currentColor" font-size="9" font-weight="700" opacity="0.7">
      <text x="30" y="306">STRATEGY</text><text x="200" y="306">DETECTED</text><text x="308" y="306">MITIGATED</text><text x="424" y="306">PEAK EXPOSURE</text><text x="580" y="306">MIN CAPACITY</text><text x="720" y="306">PEAK INSTANCES</text>
    </g>
    <path d="M26 312 L 854 312" fill="none" stroke="currentColor" stroke-width="1" opacity="0.3"/>
    <g fill="currentColor" font-size="10">
      <text x="30" y="330" font-weight="700">recreate</text><text x="200" y="330">25 s</text><text x="308" y="330">47 s</text><text x="424" y="330" fill="#d64545" font-weight="700">100%</text><text x="580" y="330" fill="#d64545" font-weight="700">0%</text><text x="720" y="330">10</text>
      <text x="30" y="352" font-weight="700">rolling</text><text x="200" y="352">40 s</text><text x="308" y="352" fill="#d64545" font-weight="700">82 s</text><text x="424" y="352" fill="#e0930f" font-weight="700">75%</text><text x="580" y="352" fill="#e0930f" font-weight="700">80%</text><text x="720" y="352">11</text>
      <text x="30" y="374" font-weight="700">blue-green</text><text x="200" y="374" fill="#0fa07f" font-weight="700">30 s</text><text x="308" y="374" fill="#0fa07f" font-weight="700">32 s</text><text x="424" y="374" fill="#d64545" font-weight="700">100%</text><text x="580" y="374" fill="#0fa07f" font-weight="700">100%</text><text x="720" y="374" fill="#d64545" font-weight="700">20</text>
      <text x="30" y="396" font-weight="700">canary</text><text x="200" y="396">40 s</text><text x="308" y="396" fill="#0fa07f" font-weight="700">42 s</text><text x="424" y="396" fill="#0fa07f" font-weight="700">5%</text><text x="580" y="396" fill="#0fa07f" font-weight="700">100%</text><text x="720" y="396">11</text>
    </g>

    <text x="440" y="438" font-size="11" text-anchor="middle" fill="currentColor" opacity="0.95">Blue-green detected FASTEST and still cost 8.1x more: 30 s at 100% exposure loses to 40 s at 5%.</text>
    <text x="440" y="456" font-size="11" text-anchor="middle" fill="currentColor" opacity="0.95">Blast radius is exposure x time. Optimising only the clock optimises half the product.</text>
  </g>
</svg>
```

### The rolling capacity arithmetic

Section 3 does no simulation at all — it is arithmetic you can do on a whiteboard, which is exactly why it is worth printing:

```console
== 3 · ROLLING CAPACITY ARITHMETIC: THE DEPLOY IS THE OVERLOAD ==
  Kubernetes rounds maxUnavailable DOWN and maxSurge UP, both from replicas=10.
  invariants: available >= replicas - maxUnavailable;  total <= replicas + maxSurge

  maxUnav  maxSurge   min avail   serving cap   peak inst   waves   rollout
       0%       25%      10/10      400 req/s           13       4      80 s
      10%        0%       9/10      360 req/s           10      10     200 s
      25%        0%       8/10      320 req/s           10       5     100 s
      25%       25%       8/10      320 req/s           11       4      80 s
      50%        0%       5/10      200 req/s           10       2      40 s

  utilisation DURING the deploy = offered / (min available x per-instance cap)
  offered   steady      u0%/s25%   u10%/s0%   u25%/s0%  u25%/s25%   u50%/s0%
   160/s      40%       0.40       0.44       0.50       0.50       0.80
   240/s      60%       0.60       0.67       0.75       0.75       1.20!!
   340/s      85%       0.85       0.94       1.06!!     1.06!!     1.70!!
  !! = rho >= 1.0: the deploy itself pushes the fleet into overload.

  W/S = 1/(1-rho), the queueing multiplier from Phase 8, at 85% steady load:
    maxUnavailable   0%, maxSurge  25%:  rho  0.85   latency x  6.7 for  80 s
    maxUnavailable  10%, maxSurge   0%:  rho  0.94   latency x 18.0 for 200 s
    maxUnavailable  25%, maxSurge   0%:  rho  1.06   UNBOUNDED:  20 req/s deficit x 100 s = 2000 shed
    maxUnavailable  25%, maxSurge  25%:  rho  1.06   UNBOUNDED:  20 req/s deficit x  80 s = 1600 shed
    maxUnavailable  50%, maxSurge   0%:  rho  1.70   UNBOUNDED: 140 req/s deficit x  40 s = 5600 shed
```

Three things to take from this.

**The Kubernetes default is a trap at high utilisation.** `maxSurge: 25%, maxUnavailable: 25%` is the shipped default, and on a fleet running at 85% it puts you at **ρ = 1.06 for the entire 80-second rollout** — a 20 req/s deficit accumulating into 1,600 requests with nowhere to go. At 40% steady load the identical config is completely harmless (ρ = 0.50). **The config is not safe or unsafe; the config *times your utilisation* is.** Nobody writes down their utilisation before choosing these numbers.

**The intermediate cases are worse than they look.** `maxUnavailable: 10%` at 85% load gives ρ = 0.94 — technically survivable, no requests dropped. And `W/S = 1/(1−ρ)` says your latency multiplier is **18×** for **200 seconds**, because a smaller batch size means a longer rollout. You did not cause an outage; you caused a three-and-a-half-minute latency event on every deploy, which is the kind of thing that shows up as "our p99 is spiky" and never gets attributed.

**`maxSurge` is the answer and it costs money.** `maxUnavailable: 0, maxSurge: 25%` holds capacity at **100% throughout**, finishes in the **fastest time in the table (80 s)** because bigger batches, and peaks at **13 instances instead of 10**. You are buying safety and speed with 30% extra compute for 80 seconds. (`maxUnavailable: 0` together with `maxSurge: 0` is rejected by the API — you cannot make progress without either spare capacity or lost capacity. There is no free option; there is only choosing which one you spend.)

### Canary statistical power: the 1% canary that detects nothing

Now the part that separates a canary that works from a canary that is theatre. A different, more realistic service: 60 req/s, a baseline error rate of 0.20%, and a new version at 0.80% — four times worse, and enough to burn a 99.9% error budget eight times over. Not a catastrophe. A regression. The kind that runs for six hours.

```console
== 4 · CANARY STATISTICAL POWER: THE 1% CANARY THAT DETECTS NOTHING ==
  service 60 req/s;  baseline errors 0.20%;  new version 0.80% (4x)
  test: one-sided, alpha=0.05, target power=80%, z_alpha=1.645, z_beta=0.842
  n >= (z_a*sqrt(p0*q0) + z_b*sqrt(p1*q1))^2 / (p1-p0)^2
  REQUIRED CANARY SAMPLE SIZE = 613 requests
  at 1% of 60 req/s that is 17.0 minutes of bake time. Nobody waits that long.

  canary  bake   samples  vs need   trips at   power on BAD   false alarm   verdict
      1%   5min      180      29%      2 errs         41.9%          5.0%     UNDER-POWERED
      1%  18min      647     106%      4 errs         76.0%          3.9%     ADEQUATE
      5%   4min      720     117%      4 errs         82.5%          6.0%     ADEQUATE
     10%   5min     1800     294%      7 errs         99.0%          7.8%     ADEQUATE
  'power on BAD' is the detection rate over 4000 simulated canaries against
  a version that really is 4x worse; 'false alarm' is the same test against
  a version identical to baseline. Both are measured, not assumed.
  note two ways the arithmetic lies to you: the 1%/18min row clears the required n
  and still reaches only 76.0% power, and the false-alarm rate drifts to 7.8% at large n
  against a nominal 5%. Error counts are integers; the normal approximation is a
  convenience, not a fact. Validate an analysis config by simulating it.
  a 1% canary for 5 minutes is a coin flip on a genuinely broken release.

  eight independent canaries of each shape, same bad version, same analysis:
   trial    1% / 5 min  (n=180)              5% / 4 min  (n=720)
       1     2 err 1.111% z= 2.74 ABORT                4 err 0.556% z= 2.14 ABORT
       2     1 err 0.556% z= 1.07 PROMOTE <-MISSED IT  5 err 0.694% z= 2.97 ABORT
       3     0 err 0.000% z=-0.60 PROMOTE <-MISSED IT  5 err 0.694% z= 2.97 ABORT
       4     0 err 0.000% z=-0.60 PROMOTE <-MISSED IT  6 err 0.833% z= 3.80 ABORT
       5     1 err 0.556% z= 1.07 PROMOTE <-MISSED IT  4 err 0.556% z= 2.14 ABORT
       6     2 err 1.111% z= 2.74 ABORT                4 err 0.556% z= 2.14 ABORT
       7     1 err 0.556% z= 1.07 PROMOTE <-MISSED IT  8 err 1.111% z= 5.47 ABORT
       8     3 err 1.667% z= 4.40 ABORT                5 err 0.694% z= 2.97 ABORT
  the version is BAD in all sixteen runs. The 1% canary promoted it 5 of 8 times;
  the 5% canary promoted it 0 of 8. Neither test changed — only n did.
  expected errors at 0.80%: 1.44 in the small canary, 5.76 in the large one.
  when the expected number of errors is near 1, a clean run is the MOST LIKELY
  outcome for a broken release. That is the whole failure mode.
```

**A 1% canary baked for five minutes on this service sees 180 requests and has 41.9% statistical power.** Read that again: given a release that really is four times worse, the analysis job fails to notice it **more often than it notices it**. And it does not fail loudly — it *promotes*. It writes "canary analysis passed" into your deployment log and moves the weight to 100%. You now have a green pipeline, a passed safety gate, and a broken release in front of every user, which is materially worse than having no canary at all, because you have manufactured confidence.

The eight-trial table is the mechanism, made visible. **In three of eight runs the 1% canary observed literally zero errors** from a version failing 0.8% of requests — and zero errors is not a fluke, it is the *expected shape* of the data. The expected error count is **1.44**. When the expected count is near one, a clean run is not surprising; it is the single most likely outcome, and Poisson noise dominates everything. The identical analysis code on **720 samples caught it 8 times out of 8.** Nothing changed except `n`.

The arithmetic that fixes it is one line, and it belongs in your rollout config, not in your head:

```text
n >= (z_alpha * sqrt(p0*q0) + z_beta * sqrt(p1*q1))^2 / (p1 - p0)^2
```

where `p0` is your baseline error rate, `p1` is the smallest degradation you insist on catching, `z_alpha` sets your tolerance for false aborts (1.645 for a one-sided 5%) and `z_beta` your tolerance for misses (0.842 for 80% power). Here that gives **n = 613 requests**, which at 1% of 60 req/s is **17.0 minutes of bake time** — and nobody waits 17 minutes, which is precisely why the 1% is wrong rather than the patience. At 5% it is 3.4 minutes.

> **Canary percentage and bake time are derived from traffic volume and the effect size you need to detect. "1% for 5 minutes" is not a policy, it is a wish.**

Two smaller findings in that output are worth keeping, because they are the kind of thing that makes people distrust an analysis system for the wrong reasons. The `1% / 18 min` row **clears the required sample size and still only reaches 76.0% power**, and the `10% / 5 min` row has a **7.8% false-alarm rate against a nominal 5%**. Both are discreteness: error counts are integers, the test can only trip at 2 errors or 4 errors or 7 errors, and the normal approximation smooths over a distribution that is anything but smooth. The practical consequence: **do not trust a canary analysis config you have not simulated.** The formula sizes it; a few thousand simulated rollouts tell you what it will actually do.

### Automated analysis, and what a human costs

```console
      t   canary req   errors   err rate   burn rate   p99      lat ratio   verdict
     20           12        2    16.67%      166.7x    310ms       2.58x   WAIT (12 < 200 samples)
     25           72        3     4.17%       41.7x    310ms       2.58x   WAIT (72 < 200 samples)
     30          132        4     3.03%       30.3x    310ms       2.58x   WAIT (132 < 200 samples)
     35          192        5     2.60%       26.0x    310ms       2.58x   WAIT (192 < 200 samples)
     40          252        8     3.17%       31.7x    310ms       2.58x   ABORT on burn + latency

  rollout       abort path      detect   mitigated   user errors   vs automated
  canary        automated         40s      42s            19              —
  canary        human-in-loop     40s     582s           380            20x
  blue-green    automated         30s      32s           182              —
  blue-green    human-in-loop     30s     572s          7993            44x
```

The `WAIT` rows are the sample-size gate from section 4, enforced. At `t = 20` the canary had served **twelve requests, two of which failed — a 16.67% error rate and a 166.7× burn rate.** Every threshold in the system is screaming. The correct action is to do nothing, because twelve requests cannot distinguish a broken release from an unlucky Tuesday, and an analysis job that aborts on twelve requests will abort on healthy releases roughly as often. The gate holds until `t = 40`, when 252 requests are in the window, and then both signals — burn rate and p99 latency ratio — trip together.

The bottom table separates detection from action, and that separation is the point. **Detection time is identical in every row.** The only thing that changes is how long it takes for something to *happen* after the signal exists. The human loop here is modelled — page-to-acknowledge 300 s plus diagnose-and-decide 240 s, parameters you should replace with your own team's measured numbers — but the structure of the result does not depend on the exact values: **the same canary, with the same detection, cost 19 errors automated and 380 with a human in the loop, a 20× difference.** Under blue-green, where 100% of users are exposed while the human reads the graph, the same delay costs **7,993 errors instead of 182 — 44×**.

The two numbers compound in the obvious direction: exposure multiplies the clock. A human-in-the-loop canary is survivable because the exposure is small. A human-in-the-loop blue-green is an outage with a paging delay in front of it.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 480" width="100%" style="max-width:840px" role="img" aria-label="The canary analysis loop. Live traffic enters a weighted router that sends ninety-five percent to the baseline fleet and five percent to a single canary instance. An analysis job runs every five seconds, comparing the canary's error ratio and p99 latency against the baseline, and refuses to decide until it has at least two hundred canary requests. If the error-budget burn rate exceeds 14.4 times or the latency ratio exceeds 1.5 it aborts by setting the canary weight to zero, otherwise it promotes by stepping the weight up and baking again. Below, a panel shows the sample-size arithmetic that sets the canary percentage and the bake time: to catch a fourfold error-rate rise from 0.2 to 0.8 percent at eighty percent power you need 613 canary requests, which is seventeen minutes at one percent of a sixty request per second service but 3.4 minutes at five percent.">
  <defs>
    <marker id="l11d-a1" markerWidth="10" markerHeight="10" refX="6.5" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker>
    <marker id="l11d-a2" markerWidth="10" markerHeight="10" refX="6.5" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#d64545"/></marker>
    <marker id="l11d-a3" markerWidth="10" markerHeight="10" refX="6.5" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#0fa07f"/></marker>
  </defs>
  <text x="440" y="24" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">The canary analysis loop — and the gate that decides if it can see anything</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">

    <g fill="none" stroke-width="1.9" stroke-linejoin="round">
      <rect x="16" y="88" width="104" height="52" rx="9" fill="#3553ff" fill-opacity="0.12" stroke="#3553ff"/>
      <rect x="152" y="78" width="98" height="72" rx="9" fill="#7c5cff" fill-opacity="0.13" stroke="#7c5cff"/>
      <rect x="300" y="54" width="164" height="52" rx="9" fill="#0fa07f" fill-opacity="0.13" stroke="#0fa07f"/>
      <rect x="300" y="124" width="164" height="52" rx="9" fill="#d64545" fill-opacity="0.13" stroke="#d64545"/>
      <rect x="504" y="54" width="196" height="122" rx="9" fill="#e0930f" fill-opacity="0.12" stroke="#e0930f"/>
      <rect x="726" y="54" width="136" height="52" rx="9" fill="#d64545" fill-opacity="0.15" stroke="#d64545"/>
      <rect x="726" y="124" width="136" height="52" rx="9" fill="#0fa07f" fill-opacity="0.15" stroke="#0fa07f"/>
    </g>

    <g fill="currentColor" text-anchor="middle">
      <text x="68" y="112" font-size="10.5" font-weight="700" fill="#3553ff">LIVE TRAFFIC</text>
      <text x="68" y="128" font-size="9.5" opacity="0.9">60 req/s</text>
      <text x="201" y="104" font-size="10" font-weight="700" fill="#7c5cff">WEIGHTED</text>
      <text x="201" y="118" font-size="10" font-weight="700" fill="#7c5cff">ROUTER</text>
      <text x="201" y="136" font-size="8.5" opacity="0.8">one weight</text>
      <text x="382" y="72" font-size="10.5" font-weight="700" fill="#0fa07f">BASELINE, 10 inst</text>
      <text x="382" y="88" font-size="9.5" opacity="0.9">old version · 57 req/s</text>
      <text x="382" y="100" font-size="8.5" opacity="0.8">the control group</text>
      <text x="382" y="142" font-size="10.5" font-weight="700" fill="#d64545">CANARY, 1 inst</text>
      <text x="382" y="158" font-size="9.5" opacity="0.9">new version · 3 req/s</text>
      <text x="382" y="170" font-size="8.5" opacity="0.8">the only users at risk</text>
    </g>

    <g fill="none" stroke="currentColor" stroke-width="1.6">
      <path d="M120 114 L 146 114" marker-end="url(#l11d-a1)"/>
      <path d="M250 100 C 274 100, 276 80, 294 80" marker-end="url(#l11d-a1)"/>
      <path d="M250 128 C 274 128, 276 150, 294 150" marker-end="url(#l11d-a1)"/>
      <path d="M464 80 C 484 80, 486 100, 498 100" marker-end="url(#l11d-a1)"/>
      <path d="M464 150 C 484 150, 486 130, 498 130" marker-end="url(#l11d-a1)"/>
    </g>
    <text x="272" y="70" font-size="9.5" font-weight="700" fill="#0fa07f" text-anchor="middle">95%</text>
    <text x="272" y="170" font-size="9.5" font-weight="700" fill="#d64545" text-anchor="middle">5%</text>

    <g fill="currentColor">
      <text x="602" y="72" font-size="10.5" font-weight="700" text-anchor="middle" fill="#e0930f">AUTOMATED ANALYSIS</text>
      <text x="516" y="90" font-size="9" opacity="0.9">runs every 5 s, comparing</text>
      <text x="516" y="103" font-size="9" opacity="0.9">canary against baseline:</text>
      <text x="516" y="120" font-size="9">· burn rate = errors / 0.10%</text>
      <text x="516" y="133" font-size="9">· latency = p99 vs base p99</text>
      <text x="516" y="151" font-size="9" font-weight="700" fill="#7c5cff">GATE: n &gt;= 200 requests</text>
      <text x="516" y="164" font-size="8.5" opacity="0.85">it may not decide below that</text>
    </g>

    <g fill="none" stroke-width="1.7">
      <path d="M700 92 L 720 84" stroke="#d64545" marker-end="url(#l11d-a2)"/>
      <path d="M700 138 L 720 146" stroke="#0fa07f" marker-end="url(#l11d-a3)"/>
    </g>
    <g text-anchor="middle">
      <text x="794" y="74" font-size="10.5" font-weight="700" fill="#d64545">ABORT</text>
      <text x="794" y="90" font-size="8.5" fill="currentColor" opacity="0.9">weight -&gt; 0, one step</text>
      <text x="794" y="101" font-size="8.5" fill="currentColor" opacity="0.9">measured: 42 s</text>
      <text x="794" y="144" font-size="10.5" font-weight="700" fill="#0fa07f">PROMOTE</text>
      <text x="794" y="160" font-size="8.5" fill="currentColor" opacity="0.9">5% -&gt; 25% -&gt; 50% -&gt; 100%</text>
      <text x="794" y="171" font-size="8.5" fill="currentColor" opacity="0.9">bake again at each step</text>
    </g>

    <path d="M794 176 C 794 200, 700 206, 540 206 L 240 206 C 210 206, 201 190, 201 156" fill="none" stroke="#0fa07f" stroke-width="1.7" stroke-dasharray="6 4" marker-end="url(#l11d-a3)"/>
    <text x="470" y="200" font-size="9" font-weight="700" text-anchor="middle" fill="#0fa07f">promote = raise the weight, bake again — the loop IS the deploy</text>

    <g fill="none" stroke-width="1.8" stroke-linejoin="round">
      <rect x="16" y="224" width="846" height="190" rx="11" fill="#7c5cff" fill-opacity="0.07" stroke="#7c5cff" stroke-opacity="0.6"/>
      <rect x="32" y="258" width="256" height="146" rx="8" fill="#7f7f7f" fill-opacity="0.07" stroke="currentColor" stroke-opacity="0.35"/>
      <rect x="304" y="258" width="256" height="146" rx="8" fill="#7f7f7f" fill-opacity="0.07" stroke="currentColor" stroke-opacity="0.35"/>
      <rect x="576" y="258" width="270" height="146" rx="8" fill="#7f7f7f" fill-opacity="0.07" stroke="currentColor" stroke-opacity="0.35"/>
    </g>
    <text x="440" y="246" font-size="12" font-weight="700" text-anchor="middle" fill="#7c5cff">The canary % and the bake time are DERIVED, not chosen</text>

    <g fill="currentColor">
      <text x="46" y="280" font-size="10" font-weight="700">1 · the effect you must catch</text>
      <text x="46" y="302" font-size="9.5" opacity="0.9">baseline error rate p0 = 0.20%</text>
      <text x="46" y="318" font-size="9.5" opacity="0.9">bad version    p1 = 0.80% (4x)</text>
      <text x="46" y="342" font-size="9" opacity="0.8">smaller effect -&gt; more samples.</text>
      <text x="46" y="356" font-size="9" opacity="0.8">Decide this BEFORE the rollout,</text>
      <text x="46" y="370" font-size="9" opacity="0.8">from your error budget.</text>

      <text x="318" y="280" font-size="10" font-weight="700">2 · required sample size</text>
      <text x="318" y="302" font-size="9">n &gt;= (z_a*sqrt(p0*q0)</text>
      <text x="318" y="316" font-size="9">      + z_b*sqrt(p1*q1))^2 / (p1-p0)^2</text>
      <text x="318" y="340" font-size="11" font-weight="700" fill="#7c5cff">n = 613 canary requests</text>
      <text x="318" y="358" font-size="9" opacity="0.85">alpha 0.05 one-sided, power 80%</text>
      <text x="318" y="374" font-size="9" opacity="0.85">measured power at n=720: 82.5%</text>

      <text x="590" y="280" font-size="10" font-weight="700">3 · bake = n / (pct x req/s)</text>
      <text x="590" y="302" font-size="9.5" fill="#d64545" font-weight="700">1% of 60 req/s -&gt; 17.0 minutes</text>
      <text x="590" y="318" font-size="9.5" fill="#0fa07f" font-weight="700">5% of 60 req/s -&gt; 3.4 minutes</text>
      <text x="590" y="342" font-size="9" opacity="0.9">a 1% canary baked 5 min sees 180</text>
      <text x="590" y="356" font-size="9" opacity="0.9">requests, 1.4 expected errors:</text>
      <text x="590" y="374" font-size="9.5" font-weight="700" fill="#d64545">41.9% power — MISSED 5 of 8</text>
    </g>

    <text x="440" y="442" font-size="11" text-anchor="middle" fill="currentColor" opacity="0.95">A canary without automated analysis is a slow deploy. A canary without enough samples is a slow deploy</text>
    <text x="440" y="460" font-size="11" text-anchor="middle" fill="currentColor" opacity="0.95">that also tells you the release is fine.</text>
  </g>
</svg>
```

## Use It

Everything above is mechanism. Here is where the knobs live.

**Kubernetes `Deployment`** gives you exactly two of the four strategies natively — `Recreate` and `RollingUpdate` — and the two fields most people never set are the interesting ones:

```yaml
apiVersion: apps/v1
kind: Deployment
spec:
  replicas: 10
  # minReadySeconds is BAKE TIME, per pod. A pod must stay Ready this long
  # before the controller counts it as available and proceeds to the next
  # batch. Default 0 = a pod that passes one readiness probe and then
  # crashes still counted, and the rollout marched on over its corpse.
  minReadySeconds: 30
  # progressDeadlineSeconds is GIVE-UP TIME, per rollout. If no progress is
  # made for this long the Deployment is marked Failed. Default 600.
  # NOTE: it marks it failed. It does NOT roll back. You need tooling for that.
  progressDeadlineSeconds: 300
  strategy:
    type: RollingUpdate          # or Recreate, for exclusive-lock workloads
    rollingUpdate:
      maxSurge: 25%              # rounded UP   -> 3 extra pods, 13 total
      maxUnavailable: 0          # <- the number from section 3.
                                 #    0 keeps you at 100% capacity throughout.
```

`maxUnavailable: 0` is the change to make today if your steady-state utilisation is above ~70%. It costs you `maxSurge` extra pods for the length of the rollout and removes the self-inflicted overload entirely.

**A progressive-delivery controller** — Argo Rollouts, Flagger, or a cloud equivalent — is what turns "canary" from a manual traffic-splitting exercise into the automated loop from section 5. The shape is always the same: a list of steps, and an analysis run that can abort them.

```yaml
# Argo Rollouts, canary strategy. The steps ARE the diagram above.
strategy:
  canary:
    steps:
      - setWeight: 5
      - pause: {duration: 5m}       # bake time: derive it, do not round it
      - analysis: {templates: [{templateName: error-rate-and-latency}]}
      - setWeight: 25
      - pause: {duration: 10m}
      - setWeight: 50
      - pause: {duration: 10m}
      - setWeight: 100
---
kind: AnalysisTemplate
metadata: {name: error-rate-and-latency}
spec:
  metrics:
    - name: error-ratio
      interval: 1m
      count: 5                    # 5 measurements before it may pass
      failureLimit: 1             # 1 failed measurement aborts the rollout
      # 14.4x burn of a 0.1% budget = 1.44%. Tie the number to the SLO,
      # not to a round figure someone liked.
      successCondition: result[0] < 0.0144
      provider:
        prometheus:
          query: |
            sum(rate(http_requests_total{job="api",canary="true",code=~"5.."}[2m]))
              / sum(rate(http_requests_total{job="api",canary="true"}[2m]))
```

Two things to check in any template like this. First, **the query must be scoped to the canary** — the `canary="true"` selector is what makes the detector undiluted rather than fleet-wide, and it is the difference between the 5% row and the 100% row of the blast-radius table. Second, **`interval × count` must exceed the bake time your sample-size arithmetic demands.** Five one-minute measurements at 3 req/s is 900 requests; at 0.5 req/s it is 150, and section 4 already told you what 150 buys you.

**The traffic split itself** happens at a layer below the controller, and every option is a weighted route:

```yaml
# Envoy / Istio / a service mesh: weights on a route
- route:
    - destination: {host: api, subset: stable}
      weight: 95
    - destination: {host: api, subset: canary}
      weight: 5

# AWS ALB, GCP backend services, nginx `split_clients` and Cloudflare all
# express the same primitive: N% of requests to a different backend pool.
```

Whatever splits the traffic, the rollout depends on the drain behaviour from lesson 9: **connection draining (deregistration delay) is why a rolling replace does not drop requests.** When an instance is removed from rotation, the load balancer stops sending it *new* connections but lets in-flight ones finish, and the instance keeps serving until they do. Without it, `maxUnavailable` does not mean "80% capacity", it means "80% capacity plus every request that was in flight on the 20%". Set the drain window longer than your slowest request, and set `terminationGracePeriodSeconds` longer than the drain window — the graceful-shutdown sequence in [Health Checks, Readiness & Graceful Shutdown](../../09-logging-monitoring-and-observability/08-health-checks-and-probes/) is the process-side half of the same handshake.

Rules that survive contact with an incident:

- **Never deploy at peak with `maxUnavailable > 0`.** Write down your steady-state utilisation, divide by `(replicas − maxUnavailable) / replicas`, and if the result is anywhere near 1.0, set `maxUnavailable: 0` and pay for `maxSurge`. At 85% utilisation the Kubernetes default puts you at ρ = 1.06 for the whole rollout.
- **Make the abort automatic and tie it to an SLO.** A threshold in a burn-rate query, not a person watching a graph. The same detection cost 19 errors automated and 380 with a human in the loop — and 7,993 when the human was watching a blue-green cutover. Wire it to the same error budget your alerts use ([Alerting & On-Call](../../09-logging-monitoring-and-observability/10-alerting-and-on-call/)) so there is exactly one definition of "bad" in the organisation.
- **Size the canary from traffic volume, not from a round number.** Compute `n` from `p0`, `p1` and the power you want; divide by `pct × req/s` to get bake time. If that time is unacceptable, raise the percentage — do not shorten the bake. A 1% canary on a low-traffic service detects nothing and reports success.
- **Give every rollout a bake time and a progress deadline.** `minReadySeconds` stops the controller marching over pods that pass one probe and then die. `progressDeadlineSeconds` stops a stuck rollout from being stuck forever — but note that it only *marks* the Deployment failed; automatic rollback is your controller's job, not the API's.
- **Know before you start whether your rollback path includes the database.** Blue-green and instant router flips give you code rollback and nothing else. If the new version migrated the schema, "roll back" is a sentence with no referent. Answer this in the change description, not in the incident.
- **Do not run a canary and an A/B test through the same decision process.** One measures whether the server is healthy over minutes with automated abort; the other measures whether humans behave differently over weeks with sticky assignment. Sharing a router is fine. Sharing a conclusion is not.

## Think about it

1. Your service runs at 45% utilisation with `maxUnavailable: 25%`, and deploys have never caused a problem. Traffic grows 60% over two quarters and nobody changes the deploy config. Compute the utilisation during a deploy before and after the growth. What is the first symptom you would see, on which dashboard, and why would nobody attribute it to the deploy?
2. Section 2 showed blue-green detecting 10 seconds sooner than the canary and costing 8.1× more. Construct a concrete scenario — traffic rate, failure mode, effect size — where blue-green genuinely is the better choice for release safety, not just for cost or simplicity. What property of the failure makes the canary lose?
3. A 1% canary at 5 minutes had 41.9% power against a 4× error-rate rise. You are asked to catch a regression that raises p99 latency by 15% with no change in error rate. Sketch how the sample-size question changes when the metric is a *latency percentile* rather than a proportion — and say what makes p99 harder to canary than an error rate.
4. Your canary analysis compares the canary against the current production fleet. The canary runs on newly-provisioned nodes with cold caches, an empty connection pool and a JIT that has not warmed. List the ways this biases the comparison, in both directions, and describe a canary design that removes the bias. What does your design cost?
5. You run blue-green with a shared database. A release adds a `NOT NULL` column with a default and starts writing to it. Ninety seconds after cutover you need to roll back. Walk through exactly what happens to requests served by blue, and state the rule you would write down so that this deploy would have been safe to reverse.

## Key takeaways

- **A deploy is a path through a state transition, and the path is the blast radius.** Identical fleet, identical traffic, identical bad version, four paths: recreate **9,689** user-facing errors, rolling **452**, blue-green **162**, canary **20**. That is a **484× spread** produced entirely by rollout mechanics — not by code quality, testing, or how good the engineers were.
- **Blast radius is exposure × time, and optimising only the clock optimises half of it.** Blue-green detected the problem in **30 s** against the canary's **40 s** and still cost **8.1× more**, because it detected it at 100% exposure while the canary was multiplying by 0.05. Rolling served **7,560 requests to the bad version — more than any other strategy** — by sitting at intermediate exposure and taking 42 s to unwind.
- **`maxUnavailable: 25%` means running at 75% capacity during every deploy, and whether that is fine depends on a number you have not written down.** At 40% steady utilisation the Kubernetes default is harmless (ρ = 0.50); at 85% it puts you at **ρ = 1.06 for the entire 80-second rollout** — 1,600 requests with nowhere to go. `maxUnavailable: 0` with `maxSurge: 25%` holds capacity at **100%**, finishes **fastest (80 s)**, and costs 3 extra instances.
- **A 1% canary on a 60 req/s service is not a safety mechanism.** Five minutes gives **180 requests**, **1.44 expected errors** from a version failing 0.8%, and **41.9% statistical power** — it **promoted a genuinely broken release in 5 of 8 runs**, three times observing zero errors. The identical analysis on **720 samples caught it 8 of 8**. Required n = **613**, which is **17.0 minutes at 1%** and **3.4 minutes at 5%**: derive the percentage and the bake time, never round them.
- **A canary without automated analysis is a slow deploy.** With a modelled human loop of 300 s to acknowledge plus 240 s to decide, the same detection at the same moment cost **19 errors automated versus 380 with a human — 20×** — and under blue-green's 100% exposure, **182 versus 7,993 — 44×**. The gate matters too: at 12 requests the canary showed a **166.7× burn rate**, and the correct action was to wait.
- **Know what your rollback actually reverses.** Blue-green's near-instant mitigation (**2 s from decision**, against 42 s for a rolling undo) is a router change and reverses *code only* — the database is shared. Recreate detected fastest of all (**25 s**) and it bought nothing, because **9,600 of its 9,689 errors came from having zero instances** and the rollback was a second 20-second outage. During that outage the error *ratio* had a zero denominator, so a ratio-based SLI could not fire at all.

Next: [Deploy ≠ Release: Feature Flags & Progressive Delivery](../12-deploy-vs-release-feature-flags/) — every strategy here ties exposure to *where the code is running*; feature flags cut that link, so you can ship to 100% of servers and release to 1% of users, and roll back without touching a single instance.
