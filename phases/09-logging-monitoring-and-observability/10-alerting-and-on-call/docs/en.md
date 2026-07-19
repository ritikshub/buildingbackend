# Alerting & On-Call That Doesn't Burn People Out

> An alert is not a message. It is an **interrupt on a human being's life** — it ends a dinner, ends a night's sleep, ends the only two hours of deep work someone got today. That is an extraordinarily expensive thing to spend, and most of what teams alert on is not worth it. This lesson is about spending it well: what earns a page, what earns a ticket, what earns nothing at all, and how to run an on-call rotation people can survive for years.

**Type:** Learn
**Languages:** —
**Prerequisites:** [SLIs, SLOs & Error Budgets](../09-slis-slos-and-error-budgets/), [Prometheus: Pull, Exposition & PromQL](../06-prometheus-and-promql/)
**Time:** ~60 minutes

## The Problem

It is 06:40 and Priya has been on-call for three days. She counts what arrived overnight: **41
alerts**. Nineteen are `HighCPU` — `node_cpu_utilization > 80%` on a batch-scoring service that is
*supposed* to sit at 85% and has never once caused a user-visible problem. Fourteen are one root
cause fanned out: a Kafka broker lost its network for ninety seconds, and every consumer group,
every publisher and every downstream readiness probe fired independently. Six fired and
auto-resolved before anyone could have opened a laptop.

That leaves **one**. At 04:12 `PaymentGatewayErrorRatio` fired, and Priya swiped it away without
reading it — half asleep, after forty other buzzes that had meant nothing. Checkout returned errors
to 4% of users for the next two hours and eighteen minutes.

Be precise about what failed. The monitoring worked: the rule evaluated correctly, the notification
was delivered, the phone rang. The system failed at the last hop — **in the human** — because the
previous forty alerts had taught her, correctly, that alerts don't mean anything. Alert fatigue is
not a morale problem first; it is a **detection failure with a human in the loop**, and what caused
it is *the alerts themselves*.

Now the symmetric failure, three weeks earlier. Everything green: CPU (central processing unit)
normal, memory normal, every pod `Running`, every health check passing, no alert anywhere. Checkout
had been broken for 40 minutes, because the third-party payment API (application programming
interface) had started returning **HTTP 200 OK with an error body** —
`{"status":"declined","reason":"internal"}` — for every card. Nothing crashed, nothing was slow, no
machine was unhappy, so no machine noticed. Nobody had written a check for it because nobody had
imagined it: Lesson 1's unknown unknowns, arriving in the alerting layer.

Both stories reduce to one sentence. **An alert is an interrupt on a human being's life; the bar for
firing one is therefore extremely high; and most of what teams alert on does not clear it.**

## The Concept

### Symptom, not cause

The highest-leverage decision in alerting is *what you point the alert at*, and there are two
choices. A **cause alert** watches a machine: CPU, memory, disk input/output, pod restarts,
garbage-collection pauses. A **symptom alert** watches a user: are requests failing, are they slow,
is checkout completing. The rule, from Google's *Site Reliability Engineering* (Beyer et al.,
O'Reilly 2016, ch. 6), is **page on symptoms, not causes** — because cause alerts are wrong in *both*
directions and symptom alerts are wrong in neither.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 860 404" width="100%" style="max-width:800px" role="img" aria-label="A comparison of cause alerting and symptom alerting. Alerting on CPU produces false pages when the machine is busy but users are fine, and misses outages when the machine looks normal but users are suffering. A symptom alert on checkout errors fires exactly when users are hurt, with cause metrics demoted to diagnostics consulted afterwards.">
  <defs>
    <marker id="l10-a1" markerWidth="10" markerHeight="10" refX="6" refY="3" orient="auto">
      <path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/>
    </marker>
  </defs>
  <text x="430" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">What you point the alert at decides how often it lies</text>
  <g fill="none" stroke-linejoin="round" stroke-width="2">
    <rect x="24" y="44" width="402" height="310" rx="14" fill="#7f7f7f" fill-opacity="0.07" stroke="currentColor" stroke-opacity="0.5"/>
    <rect x="442" y="44" width="394" height="310" rx="14" fill="#7f7f7f" fill-opacity="0.07" stroke="currentColor" stroke-opacity="0.5"/>
    <rect x="138" y="96" width="130" height="74" rx="9" fill="#e0930f" fill-opacity="0.18" stroke="#e0930f"/>
    <rect x="272" y="96" width="130" height="74" rx="9" fill="#0fa07f" fill-opacity="0.14" stroke="#0fa07f"/>
    <rect x="138" y="174" width="130" height="74" rx="9" fill="#7f7f7f" fill-opacity="0.10" stroke="currentColor" stroke-opacity="0.45"/>
    <rect x="272" y="174" width="130" height="74" rx="9" fill="#7c5cff" fill-opacity="0.18" stroke="#7c5cff"/>
    <rect x="464" y="94" width="350" height="58" rx="10" fill="#0fa07f" fill-opacity="0.16" stroke="#0fa07f"/>
    <rect x="464" y="206" width="110" height="48" rx="9" fill="#3553ff" fill-opacity="0.11" stroke="#3553ff"/>
    <rect x="584" y="206" width="110" height="48" rx="9" fill="#3553ff" fill-opacity="0.11" stroke="#3553ff"/>
    <rect x="704" y="206" width="110" height="48" rx="9" fill="#3553ff" fill-opacity="0.11" stroke="#3553ff"/>
  </g>
  <path d="M639 152 L 639 178" fill="none" stroke="currentColor" stroke-width="1.6" marker-end="url(#l10-a1)"/>
  <g font-family="'JetBrains Mono', ui-monospace, monospace" fill="currentColor">
    <text x="225" y="72" font-size="12.5" font-weight="700" text-anchor="middle" fill="#e0930f">CAUSE ALERT:  cpu &gt; 80% for 5m</text>
    <text x="146" y="112" font-size="9" opacity="0.6">A</text>
    <text x="280" y="190" font-size="9" opacity="0.6">D</text>
    <text x="203" y="128" font-size="10.5" font-weight="700" text-anchor="middle">FALSE PAGE</text>
    <text x="203" y="145" font-size="9" text-anchor="middle" opacity="0.9">phone rings at 04:00</text>
    <text x="203" y="159" font-size="9" text-anchor="middle" opacity="0.9">nothing is wrong</text>
    <text x="337" y="128" font-size="10.5" font-weight="700" text-anchor="middle">a real hit</text>
    <text x="337" y="145" font-size="9" text-anchor="middle" opacity="0.9">but the symptom alert</text>
    <text x="337" y="159" font-size="9" text-anchor="middle" opacity="0.9">caught this one too</text>
    <text x="203" y="215" font-size="10.5" text-anchor="middle" opacity="0.8">correctly quiet</text>
    <text x="337" y="206" font-size="10.5" font-weight="700" text-anchor="middle">MISS</text>
    <text x="337" y="223" font-size="9" text-anchor="middle" opacity="0.9">payments 200-OK with</text>
    <text x="337" y="237" font-size="9" text-anchor="middle" opacity="0.9">an error body. Silence.</text>
    <text x="130" y="137" font-size="9.5" text-anchor="end" opacity="0.85">cpu HIGH</text>
    <text x="130" y="215" font-size="9.5" text-anchor="end" opacity="0.85">cpu normal</text>
    <text x="203" y="266" font-size="9.5" text-anchor="middle" opacity="0.85">users FINE</text>
    <text x="337" y="266" font-size="9.5" text-anchor="middle" opacity="0.85">users SUFFERING</text>
    <text x="225" y="298" font-size="9.5" text-anchor="middle" opacity="0.9">Wrong in two directions: it pages when</text>
    <text x="225" y="315" font-size="9.5" text-anchor="middle" opacity="0.9">nothing hurts (A) and stays silent while</text>
    <text x="225" y="332" font-size="9.5" text-anchor="middle" opacity="0.9">everything does (D).</text>
    <text x="639" y="72" font-size="12.5" font-weight="700" text-anchor="middle" fill="#0fa07f">SYMPTOM ALERT:  checkout failing</text>
    <text x="639" y="118" font-size="11" font-weight="700" text-anchor="middle">PAGE — 2.1% of checkouts erroring</text>
    <text x="639" y="136" font-size="9.5" text-anchor="middle" opacity="0.9">burning the 30-day budget 14.4x too fast</text>
    <text x="639" y="196" font-size="9.5" text-anchor="middle" opacity="0.85">once you are awake, look at the causes:</text>
    <text x="519" y="228" font-size="10" font-weight="700" text-anchor="middle">cpu</text>
    <text x="519" y="243" font-size="8.5" text-anchor="middle" opacity="0.85">saturation</text>
    <text x="639" y="228" font-size="10" font-weight="700" text-anchor="middle">restarts</text>
    <text x="639" y="243" font-size="8.5" text-anchor="middle" opacity="0.85">crashloops</text>
    <text x="759" y="228" font-size="10" font-weight="700" text-anchor="middle">db pool</text>
    <text x="759" y="243" font-size="8.5" text-anchor="middle" opacity="0.85">wait time</text>
    <text x="639" y="286" font-size="10" font-weight="700" text-anchor="middle">Causes are DIAGNOSTICS, not pages.</text>
    <text x="639" y="306" font-size="9.5" text-anchor="middle" opacity="0.9">One alert — and it fires for failure modes</text>
    <text x="639" y="322" font-size="9.5" text-anchor="middle" opacity="0.9">nobody predicted, including the ones that</text>
    <text x="639" y="338" font-size="9.5" text-anchor="middle" opacity="0.9">leave every machine metric green.</text>
    <text x="430" y="386" font-size="11" text-anchor="middle" opacity="0.9">Alert on what the user feels. Demote what the machine feels to the dashboard you open afterwards.</text>
  </g>
</svg>
```

Cell **A** is Priya's nineteen `HighCPU` pages: machine busy, users happy, human woken for a number.
Cell **D** is the payment-gateway outage: every machine metric normal, every user broken, total
silence. A cause alert is a *proxy* for user pain, and the correlation between "CPU is high" and
"users are suffering" is real but weak — the cells where it breaks are exactly the ones that cost
you. The symptom alert has one property no cause alert can have: **it covers failure modes you never
enumerated.** You didn't need to imagine "the payment provider returns 200 with a declined body";
you needed to measure "did checkout succeed," and that measurement catches that failure and the next
one. Cause metrics aren't worthless — they are the *first thing you look at* once a symptom alert
has woken you, so they belong on the dashboard you open at 04:13 (Lesson 11 builds it) and in
tickets, not on the pager.

One honest exception: **predictive alerts on resource exhaustion, where the symptom arrives too late
to act on.** If the disk fills, the symptom is total failure and you get zero minutes — so alert on
the *trajectory* instead:

```yaml
- alert: DiskWillFillIn4Hours
  # predict_linear extrapolates the last 6h trend forward 4h (Lesson 6's PromQL)
  expr: predict_linear(node_filesystem_avail_bytes{mountpoint="/data"}[6h], 4*3600) < 0
  for: 30m
  labels: { severity: ticket, team: platform }   # NOT a page — you have four hours
```

The same shape covers TLS (Transport Layer Security) certificate expiry at 30 days out, cloud quota
exhaustion, and database connection limits. Note the severity: these are **tickets, not pages**,
precisely because the point was to find out early enough to handle it in working hours. An alert
that buys four hours of warning and still wakes you has thrown away its own advantage.

### The three destinations

Every condition worth detecting ends in exactly one of three places, and confusing them is what
produces a 41-alert night.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 780 742" width="100%" style="max-width:660px" role="img" aria-label="A decision tree for triaging an alert. From a condition becoming true, four questions are asked in order: is a user affected right now, is it urgent, can a human act within the hour, and is there a runbook and an owning team. Answering no to any question routes the condition to a dashboard or a ticket; only answering yes to all four produces a page.">
  <defs>
    <marker id="l10-a2" markerWidth="10" markerHeight="10" refX="6" refY="3" orient="auto">
      <path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/>
    </marker>
  </defs>
  <text x="390" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">Four questions between a condition and a ringing phone</text>
  <g fill="none" stroke="currentColor" stroke-width="1.6">
    <path d="M300 86 L 300 99" marker-end="url(#l10-a2)"/>
    <path d="M300 210 L 300 233" marker-end="url(#l10-a2)"/>
    <path d="M300 344 L 300 367" marker-end="url(#l10-a2)"/>
    <path d="M300 478 L 300 501" marker-end="url(#l10-a2)"/>
    <path d="M300 612 L 300 637" marker-end="url(#l10-a2)"/>
    <path d="M430 156 L 508 156" marker-end="url(#l10-a2)"/>
    <path d="M430 290 L 508 290" marker-end="url(#l10-a2)"/>
    <path d="M430 424 L 508 424" marker-end="url(#l10-a2)"/>
    <path d="M430 558 L 508 558" marker-end="url(#l10-a2)"/>
  </g>
  <g fill="none" stroke-linejoin="round" stroke-width="2">
    <rect x="170" y="44" width="260" height="42" rx="9" fill="#3553ff" fill-opacity="0.12" stroke="#3553ff"/>
    <path d="M300 102 L430 156 L300 210 L170 156 Z" fill="#7f7f7f" fill-opacity="0.07" stroke="currentColor"/>
    <path d="M300 236 L430 290 L300 344 L170 290 Z" fill="#7f7f7f" fill-opacity="0.07" stroke="currentColor"/>
    <path d="M300 370 L430 424 L300 478 L170 424 Z" fill="#7f7f7f" fill-opacity="0.07" stroke="currentColor"/>
    <path d="M300 504 L430 558 L300 612 L170 558 Z" fill="#7f7f7f" fill-opacity="0.07" stroke="currentColor"/>
    <rect x="512" y="132" width="232" height="48" rx="9" fill="#7f7f7f" fill-opacity="0.12" stroke="currentColor" stroke-opacity="0.6"/>
    <rect x="512" y="266" width="232" height="48" rx="9" fill="#e0930f" fill-opacity="0.15" stroke="#e0930f"/>
    <rect x="512" y="400" width="232" height="48" rx="9" fill="#e0930f" fill-opacity="0.15" stroke="#e0930f"/>
    <rect x="512" y="534" width="232" height="48" rx="9" fill="#e0930f" fill-opacity="0.15" stroke="#e0930f"/>
    <rect x="170" y="640" width="260" height="54" rx="10" fill="#0fa07f" fill-opacity="0.16" stroke="#0fa07f"/>
  </g>
  <g font-family="'JetBrains Mono', ui-monospace, monospace" fill="currentColor" text-anchor="middle">
    <text x="300" y="71" font-size="11.5" font-weight="700">a condition becomes true</text>
    <text x="300" y="150" font-size="10.5">Is a USER affected</text>
    <text x="300" y="167" font-size="10.5">right now?</text>
    <text x="300" y="284" font-size="10.5">Is it URGENT — does</text>
    <text x="300" y="301" font-size="10.5">waiting make it worse?</text>
    <text x="300" y="418" font-size="10.5">Can a human ACT</text>
    <text x="300" y="435" font-size="10.5">in the next hour?</text>
    <text x="300" y="552" font-size="10.5">Is there a RUNBOOK</text>
    <text x="300" y="569" font-size="10.5">and an owning team?</text>
    <text x="628" y="153" font-size="10.5" font-weight="700">DASHBOARD ONLY</text>
    <text x="628" y="170" font-size="9" opacity="0.9">graph it, never notify on it</text>
    <text x="628" y="287" font-size="10.5" font-weight="700">TICKET</text>
    <text x="628" y="304" font-size="9" opacity="0.9">real, but it waits for daylight</text>
    <text x="628" y="421" font-size="10.5" font-weight="700">TICKET · or AUTOMATE</text>
    <text x="628" y="438" font-size="9" opacity="0.9">self-healing beats a woken human</text>
    <text x="628" y="555" font-size="10.5" font-weight="700">TICKET · write the runbook</text>
    <text x="628" y="572" font-size="9" opacity="0.9">no runbook means it is not a page</text>
    <text x="300" y="664" font-size="12" font-weight="700" fill="#0fa07f">PAGE</text>
    <text x="300" y="682" font-size="9.5" opacity="0.9">wake a human, right now</text>
    <text x="466" y="148" font-size="9" opacity="0.75">no</text>
    <text x="466" y="282" font-size="9" opacity="0.75">no</text>
    <text x="466" y="416" font-size="9" opacity="0.75">no</text>
    <text x="466" y="550" font-size="9" opacity="0.75">no</text>
    <text x="313" y="228" font-size="9" opacity="0.75" text-anchor="start">yes, all the way down</text>
    <text x="390" y="724" font-size="11" opacity="0.9">Run every existing alert through this. Most come out the right-hand side.</text>
  </g>
</svg>
```

- **Page** — a phone rings, a human wakes. Reserved for conditions that are **user-visible**,
  **urgent**, **actionable**, and **not self-healing**. Those are the four questions; a page passes
  all four.
- **Ticket** — into the backlog; someone looks tomorrow. Real, not urgent. Disk at 70%. One pod that
  restarted twice. A slow-burn budget alert.
- **Dashboard only** — no notification at all. A number you want available when you go looking:
  request rate, cache hit ratio, queue depth on a healthy day.

Run this honestly against an existing alert set and a very large fraction of alerts move down; that
is the expected outcome, not a sign you did it wrong. Two of the questions get skipped, so be
explicit. **"Actionable"** means a specific human can do something *now* that changes the outcome —
if the only available response is "acknowledge and go back to sleep," it was never a page. And
**"not self-healing"**: six of Priya's alerts resolved on their own, and a condition that reliably
clears itself within minutes needs a longer `for` clause, not a pager.

### Burn-rate alerting: the modern default

Lesson 9 gave you the SLO (Service Level Objective) and the **error budget** — the finite quantity
of failure you may spend in a window. This lesson is what you *do* with it: **alert on how fast you
are spending it.** Compare the naive threshold everyone writes first:

```yaml
# Don't do this.
- alert: HighErrorRate
  expr: rate(http_requests_total{status=~"5.."}[5m]) / rate(http_requests_total[5m]) > 0.01
  for: 5m
```

It fails in both directions, structurally. A 40-second burst at 30% errors — a rolling restart, a
brief upstream blip — drags the 5-minute rate over 1% and pages someone about damage already over.
Meanwhile a **slow bleed** of 0.9% errors sustained for a week never crosses 1%, never fires, and
quietly eats the whole month's budget. The threshold has no idea how much budget exists or how fast
it is going. A **burn rate** does: burn rate 1 spends exactly your budget over the SLO window, 14.4
spends it 14.4 times faster. Lesson 9 derived those numbers; here they are as real Prometheus rules
in the **multi-window, multi-burn-rate** pattern (*The Site Reliability Workbook*, Beyer et al.,
O'Reilly 2018, ch. 5) — a **long window** for confidence plus a **short window**, conventionally
one-twelfth of it, that must *also* be burning so the alert clears fast once the problem stops:

```yaml
groups:
  - name: checkout-availability-slo
    rules:
      # FAST BURN — 14.4x: 2% of a 30-day budget gone in one hour. Wake someone.
      - alert: CheckoutBudgetFastBurn        # 1. the name states the SYMPTOM, not a cause
        expr: |
          slo:checkout_error_ratio:rate1h > (14.4 * 0.001)
            and
          slo:checkout_error_ratio:rate5m > (14.4 * 0.001)
        for: 2m                              # 2. entry hysteresis: must hold continuously
        keep_firing_for: 10m                 # 3. exit hysteresis: no resolve/refire storm
        labels:
          severity: page                     # 4. decides the destination (the route tree)
          team: payments                     # 5. decides WHO — routing needs an owner
          slo: checkout-availability         # 6. ties it to the objective it defends
        annotations:
          summary: >-                        # 7. the actual VALUES, not a category
            Checkout error ratio is {{ $value | humanizePercentage }} (budget allows 0.1%)
            — 14.4x burn against the 30-day SLO.
          runbook_url: "https://runbooks.internal/checkout-availability"     # 8. what to DO
          dashboard_url: "https://grafana.internal/d/checkout/checkout-slo"  # 9. where to LOOK

      # SLOW BURN — 6x: the whole month's budget gone in 5 days. A ticket, not a page.
      - alert: CheckoutBudgetSlowBurn
        expr: |
          slo:checkout_error_ratio:rate6h  > (6 * 0.001)
            and
          slo:checkout_error_ratio:rate30m > (6 * 0.001)
        for: 15m
        labels: { severity: ticket, team: payments, slo: checkout-availability }
        annotations:
          summary: "Checkout error budget bleeding at 6x — the month's budget is gone in 5 days"
          runbook_url: "https://runbooks.internal/checkout-availability"
```

`0.001` is the budget: a 99.9% objective permits a 0.1% error ratio, so `14.4 * 0.001` is 1.44%.
`slo:checkout_error_ratio:rate1h` is a **recording rule** — a pre-computed series (Lesson 6) — so
the ratio is defined once instead of copy-pasted into four expressions that then drift apart. Read
what the pair buys: fast-burn ignores the 40-second blip (a 1-hour window barely moves) but catches
a genuine outage in minutes, and slow-burn catches the 0.9% bleed the naive threshold slept
through — routed to the backlog, because a leak that needs five days to drain the budget does not
need anyone awake at 04:00. Two rules, covering both failures the single threshold had.

### The mechanics of not flapping

Six of Priya's alerts fired and resolved before anyone could act. The `for` clause prevents that,
and it does not do what most people assume. Prometheus evaluates each rule group every
`evaluation_interval` (commonly 15 or 30 seconds). When an expression starts returning a series, the
alert enters **pending** and Prometheus records `activeAt`; it becomes **firing** — and only then is
it sent anywhere — once `now - activeAt >= for`. Crucially: **if the expression stops returning that
series at any single evaluation, the alert drops straight back to inactive and the clock resets to
zero.** That is genuinely different from a five-minute average:

```text
error ratio, one sample every 30s, threshold 1%:
   12%   0.1%  0.1%  0.1%  0.1%  0.1%  0.1%  0.1%  0.1%  0.1%
   \__ a 30-second burst, over before anyone could act
   avg_over_time(...[5m]) > 0.01  ->  average is 1.29%  ->  FIRES.   A useless page.
   ratio > 0.01  for: 5m          ->  sample 2 is under ->  resets.  Correctly silent.
```

`for` demands the condition hold *continuously*; an average lets one spike drag the whole window
over the line. The mirror-image problem is flapping on the way *out* — a condition oscillating
around the threshold produces firing/resolved/firing/resolved, and every transition notifies.
Prometheus 2.42 added **`keep_firing_for`**, holding an alert firing for an extra duration after the
condition clears. Different thresholds for entering and leaving a state is **hysteresis** — the same
trick a thermostat uses so it doesn't click on and off every twenty seconds.

### The Alertmanager model

Fourteen of Priya's alerts were one Kafka broker, fanned out. Prometheus doesn't fix that; it only
evaluates and fires. Everything between "an alert is firing" and "a human is interrupted" happens in
a separate component, **Alertmanager**, the reference implementation of four ideas you would
otherwise have to invent.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 856 440" width="100%" style="max-width:820px" role="img" aria-label="The alert lifecycle as a pipeline: Prometheus evaluates a rule, holds it pending for the for-duration, then fires it. Alertmanager groups related alerts, applies inhibition and silences, and routes by severity. A notification is then delivered, acknowledged by a human, and resolved. The grouping, inhibition and routing stages form the highlighted noise-reduction band.">
  <defs>
    <marker id="l10-a3" markerWidth="10" markerHeight="10" refX="6" refY="3" orient="auto">
      <path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/>
    </marker>
  </defs>
  <text x="428" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">From a true expression to a ringing phone — and everything that stops it</text>
  <g fill="none" stroke-linejoin="round" stroke-width="2">
    <rect x="40" y="160" width="776" height="136" rx="14" fill="#e0930f" fill-opacity="0.10" stroke="#e0930f" stroke-dasharray="8 6"/>
    <rect x="40" y="56" width="248" height="72" rx="11" fill="#3553ff" fill-opacity="0.12" stroke="#3553ff"/>
    <rect x="304" y="56" width="248" height="72" rx="11" fill="#3553ff" fill-opacity="0.12" stroke="#3553ff"/>
    <rect x="568" y="56" width="248" height="72" rx="11" fill="#3553ff" fill-opacity="0.12" stroke="#3553ff"/>
    <rect x="60" y="200" width="240" height="76" rx="11" fill="#e0930f" fill-opacity="0.16" stroke="#e0930f"/>
    <rect x="316" y="200" width="240" height="76" rx="11" fill="#e0930f" fill-opacity="0.16" stroke="#e0930f"/>
    <rect x="572" y="200" width="224" height="76" rx="11" fill="#e0930f" fill-opacity="0.16" stroke="#e0930f"/>
    <rect x="40" y="328" width="248" height="64" rx="11" fill="#0fa07f" fill-opacity="0.14" stroke="#0fa07f"/>
    <rect x="304" y="328" width="248" height="64" rx="11" fill="#0fa07f" fill-opacity="0.14" stroke="#0fa07f"/>
    <rect x="568" y="328" width="248" height="64" rx="11" fill="#0fa07f" fill-opacity="0.14" stroke="#0fa07f"/>
  </g>
  <g fill="none" stroke="currentColor" stroke-width="1.6">
    <path d="M288 92 L 299 92" marker-end="url(#l10-a3)"/>
    <path d="M552 92 L 563 92" marker-end="url(#l10-a3)"/>
    <path d="M300 238 L 311 238" marker-end="url(#l10-a3)"/>
    <path d="M556 238 L 567 238" marker-end="url(#l10-a3)"/>
    <path d="M288 360 L 299 360" marker-end="url(#l10-a3)"/>
    <path d="M552 360 L 563 360" marker-end="url(#l10-a3)"/>
    <path d="M816 92 L 834 92 L 834 152 L 22 152 L 22 238 L 54 238" marker-end="url(#l10-a3)"/>
    <path d="M796 238 L 834 238 L 834 308 L 22 308 L 22 360 L 34 360" marker-end="url(#l10-a3)"/>
  </g>
  <g font-family="'JetBrains Mono', ui-monospace, monospace" fill="currentColor" text-anchor="middle">
    <text x="164" y="82" font-size="11.5" font-weight="700">1 · EVALUATE</text>
    <text x="164" y="102" font-size="9" opacity="0.9">the rule query runs every</text>
    <text x="164" y="117" font-size="9" opacity="0.9">15s inside Prometheus</text>
    <text x="428" y="82" font-size="11.5" font-weight="700">2 · PENDING</text>
    <text x="428" y="102" font-size="9" opacity="0.9">true, but not yet for the</text>
    <text x="428" y="117" font-size="9" opacity="0.9">full for: — nothing sent</text>
    <text x="692" y="82" font-size="11.5" font-weight="700">3 · FIRING</text>
    <text x="692" y="102" font-size="9" opacity="0.9">held the whole for: window</text>
    <text x="692" y="117" font-size="9" opacity="0.9">pushed to Alertmanager</text>
    <text x="428" y="184" font-size="11" font-weight="700" fill="#e0930f">ALERTMANAGER — the noise-reduction band</text>
    <text x="180" y="226" font-size="11" font-weight="700">4 · GROUP</text>
    <text x="180" y="246" font-size="9" opacity="0.9">group_by: alertname, cluster</text>
    <text x="180" y="261" font-size="9" opacity="0.9">200 alerts in, 1 message out</text>
    <text x="436" y="226" font-size="11" font-weight="700">5 · INHIBIT / SILENCE</text>
    <text x="436" y="246" font-size="9" opacity="0.9">drop symptoms under a known</text>
    <text x="436" y="261" font-size="9" opacity="0.9">cause, or a maintenance mute</text>
    <text x="684" y="226" font-size="11" font-weight="700">6 · ROUTE</text>
    <text x="684" y="246" font-size="9" opacity="0.9">match severity and team</text>
    <text x="684" y="261" font-size="9" opacity="0.9">pager vs ticket vs chat</text>
    <text x="164" y="352" font-size="11" font-weight="700">7 · NOTIFY</text>
    <text x="164" y="372" font-size="9" opacity="0.9">PagerDuty · Slack · email</text>
    <text x="428" y="352" font-size="11" font-weight="700">8 · ACKNOWLEDGE</text>
    <text x="428" y="372" font-size="9" opacity="0.9">a human owns it; escalation stops</text>
    <text x="692" y="352" font-size="11" font-weight="700">9 · RESOLVE</text>
    <text x="692" y="372" font-size="9" opacity="0.9">expression clears, resolved sent</text>
    <text x="428" y="418" font-size="11" opacity="0.9">Stages 4-6 are pure noise reduction. This is the band where 200 firing alerts become one phone call.</text>
  </g>
</svg>
```

**Grouping** collapses related alerts into one notification: `group_by` names the labels that define
"the same thing", `group_wait` holds the first notification of a new group so the other 199 alerts
arriving seconds later land in the same message, `group_interval` bounds updates to a changed group.
**Inhibition** suppresses downstream alerts while an upstream cause fires — one `ClusterUnreachable`
page, not that plus 60 `InstanceDown` plus every dependent service's error alert. **Silences** are
time-boxed, label-matched mutes for planned maintenance. **Routing** is a tree: an alert enters at
the root and walks to the most specific matching node, inheriting what it doesn't override.

```yaml
route:
  group_by: ['alertname', 'cluster', 'service']
  group_wait: 30s          # hold the first notification of a new group this long
  group_interval: 5m       # then at most one update per group per 5m
  repeat_interval: 4h      # re-notify about a still-firing group this often
  receiver: slack-noise    # the default: nothing unrouted ever reaches a pager
  routes:
    - matchers: ['severity = page']
      receiver: pagerduty
      group_wait: 10s      # a page should not wait 30s to batch
      repeat_interval: 30m # nag every 30m until acknowledged
      routes:
        - matchers: ['team = payments']
          receiver: pagerduty-payments
        - matchers: ['team = platform']
          receiver: pagerduty-platform
    - matchers: ['severity = ticket']
      receiver: jira-backlog
      group_interval: 30m
      repeat_interval: 24h

inhibit_rules:
  # A whole cluster being down must not also page for every service inside it.
  - source_matchers: ['alertname = ClusterUnreachable']
    target_matchers: ['severity =~ "page|ticket"']
    equal: ['cluster']                       # ...but only within the SAME cluster
  # A firing page suppresses the ticket-level version of the same alert.
  - source_matchers: ['severity = page']
    target_matchers: ['severity = ticket']
    equal: ['alertname', 'service']
```

`equal` is the field people get wrong: without it a `ClusterUnreachable` in `eu-west` would suppress
alerts in `us-east` too. `repeat_interval` needs its own thought — too short and an unacknowledged
page becomes its own noise source, too long and something acknowledged-then-forgotten stays
forgotten. A planned silence carries a mandatory author and reason, so that in three weeks someone
can find out why this alert is muted:

```bash
amtool silence add service=checkout alertname=~"CheckoutBudget.*" \
  --duration=2h --author="priya" --comment="planned payment-gateway migration, OPS-4412"
```

### Anatomy of a good alert

Go back and read the nine numbered comments on `CheckoutBudgetFastBurn` above: they are the whole
checklist. An alert's job is not to say "something is wrong" — it is to hand a half-asleep person
everything they need to start acting inside sixty seconds, which takes a symptom-shaped name, a
severity, an owning team, the objective it defends, a summary carrying **values**, a runbook link
and a dashboard link. Two of those are load-bearing beyond the obvious.

**The summary must contain values, not categories.** "Error rate is high" adds nothing to the
alert's name; "error ratio is 2.1%, budget allows 0.1%" gives magnitude, and magnitude decides
whether you roll back immediately or look for five minutes first. Prometheus templates
`{{ $value }}` and `{{ $labels.x }}` into annotations for exactly this.

**The runbook is the enforcement mechanism for everything else in this lesson**, hence the hard
rule: **if there is no runbook, it is not a page.** Writing one forces you to answer "what should
this person actually do?" — and if you can't answer that, the alert was never actionable, so by the
decision tree it was never a page. Requiring a runbook makes the unactionable page impossible to
ship. It needs only four things: what the alert means in user terms, how to confirm it's real,
mitigations in order, and who to escalate to. Template in
[`outputs/runbook-alerting-and-on-call.md`](outputs/runbook-alerting-and-on-call.md).

### On-call as a system, not a rota

A rota is a spreadsheet of names. An on-call *system* is a set of deliberate choices about load,
escalation, fairness and feedback, and the difference shows up in whether your engineers are still
there in two years.

- **Primary and secondary.** The primary takes the page; unacknowledged after 5-15 minutes it
  escalates automatically. Phones fail and tunnels have no signal — and knowing there is a backstop
  is most of what makes on-call bearable.
- **Rotation length.** One week is the common unit: long enough that handoffs are rare, short enough
  that a bad week ends. Shorter rotations cut fatigue but add handoffs, and handoffs leak context.
- **Follow-the-sun vs one timezone.** Teams in two or three regions ~8 hours apart can make every
  shift somebody's working day, so nobody is paged at night. Best outcome for humans, and expensive:
  it needs genuinely shared ownership across regions, not a "night team" paged for code it cannot
  change.
- **The load ceiling.** A widely used SRE (Site Reliability Engineering) guideline is at most **two
  incidents per 12-hour shift** — time to handle each properly, write it up, and still do the day
  job. Consistently over it? **Fix the alerts, don't hire more people**: adding humans to absorb
  noise scales your costs with your noise, deleting the noise doesn't.
- **Compensation and handoff.** On-call is work even when the pager is silent — no drinking, no
  travel, never more than a laptop from connectivity — so pay it or give time back. End every
  rotation with a written handoff: what fired, what's open, which silences expire when, what's
  fragile.
- **The people who write the code carry the pager**, not a separate ops team. That's incentives, not
  fairness: when the author of a noisy alert is the person it wakes, it gets fixed within a week;
  when somebody else absorbs it, it survives for years, because nobody who can delete it ever feels
  it.

### Incident response: roles before heroics

When something big breaks, the failure mode isn't "nobody knows what to do." It's six people acting
at once across three chat threads, two making conflicting changes to production, while nobody talks
to the support team fielding tickets. **Severity levels** exist so everyone agrees how hard to pull
the rope, and they need concrete criteria, not adjectives:

| Severity | Criteria | Response |
|---|---|---|
| **SEV1** | A core user journey fully or nearly fully broken for most users; or data loss; or a security breach | Page now, assign an Incident Commander, open a war room, update the public status page, notify leadership |
| **SEV2** | Significant degradation, or a full break for a subset (one region, tenant, or platform); a workaround exists | Page the owning team, assign an IC if it runs past ~30 min, internal comms |
| **SEV3** | Contained or cosmetic; no meaningful user impact; a slow-burn budget alert | Ticket, business hours, no page |

Three roles, once an incident outgrows one person. The **Incident Commander (IC)** owns the
*incident*, not the fix: decides, delegates, keeps the timeline, calls escalation and stand-down.
**The IC does not debug** — the moment the IC opens a terminal they stop coordinating, and within
ten minutes nobody knows who is doing what. The **Operations Lead** is the *only* person changing
the system, so the timeline stays accurate and two people don't roll back and forward at once. The
**Communications Lead** owns the status page and stakeholder updates, so "any news?" doesn't
interrupt the fixing. On a small incident one person wears all three hats; naming them matters so
that when it grows, everyone knows what to split off. Everything happens in **one incident channel
with a running timeline** — every action timestamped ("14:22 rolled back deploy 3f21c", "14:26 error
ratio falling"), because that is the raw material for the postmortem and memory of an incident is
reliably wrong.

Then the rule that most separates experienced responders from new ones: **mitigate before you
diagnose.** The instinct is to understand the bug first; resist it. Roll back the deploy, fail over
the region, shed load, flip the feature flag, drain the bad node — **restore the user first,
understand later.** The cause will still be in the logs and traces at 10:00 tomorrow; the customers
currently failing to check out will not. And **post to the status page early, on an announced
cadence** (every 30 minutes for a SEV1, hourly for a SEV2) even when the update is "still
investigating." Users forgive outages; they do not forgive silence.

### Postmortems, and why blame destroys the data

The write-up must be **blameless**, for a mechanical rather than a moral reason. Its only asset is
honest information from the people closest to the failure — what they saw, assumed, typed, and why
it looked reasonable at the time. If naming a person has consequences for that person, the next
person rounds their account off, omits the embarrassing step, and describes what they *should* have
done. **Blame destroys exactly the data the postmortem exists to collect.** The blameless version
asks how the system made the mistake easy, available and unnoticed: a deploy tool with no
confirmation, an alert firing into a channel nobody watched, a runbook three months stale.

The second habit to break is **"root cause," singular.** Real failures come from a combination of
contributing factors, none individually sufficient (Richard Cook, *How Complex Systems Fail*, 1998).
"The deploy caused it" is almost never true; "the deploy contained a regression, the canary window
was too short to catch it, the rollback was manual and took eleven minutes, and the alert that would
have caught it had been silenced in March" *is* true — and yields four fixes instead of one. So a
useful postmortem carries a timestamped timeline, impact quantified (how many users, how long, how
much budget burned), what went well and badly, where you got lucky, and **action items with a named
owner and a due date**, each classified *prevent*, *detect faster*, or *mitigate faster*. And the
honest part: **a postmortem whose action items never ship converted an outage into a document.**
Track completion rate like any other metric; below about 70%, the process is theatre.

### Toil, hygiene, and deleting things

**Toil** is work that is manual, repetitive, automatable, tactical, devoid of enduring value, and —
critically — **scales linearly with the size of the system** (Google SRE, ch. 5). Restarting a stuck
worker, draining a queue by hand, re-running a failed nightly job: each instance is small, but the
total grows with traffic, services and customers while headcount does not, which is why toil is an
engineering problem and not a staffing one. Google's guideline caps SRE toil at 50% of time.

The connection to alerting: **every alert you resolve with the same manual fix is a written
specification for automation.** The condition is the trigger; the runbook is the algorithm. If the
runbook says "SSH in, run `systemctl restart scoring`, confirm the queue drains," the script is
already specified — and once it runs automatically the page becomes a ticket ("auto-remediated four
times this week, itself now worth investigating") and eventually a dashboard. So the third triage
question has a sharper form: **if a human can act, and always acts the same way, a machine should be
acting instead.**

The rest is hygiene, because alerts rot: the service was rewritten, the threshold was tuned for
traffic from two years ago, the person who understood it left. Nobody deletes them — deleting an
alert feels like removing a safety net — so the set only grows, and that is how you reach forty-one
a night. The fix is a **standing alert review**, monthly or quarterly, putting every alert that can
notify a human through three questions: **did it fire** in the last 90 days; **when it fired, did a
human do anything**, or was every response "acknowledge and go back to sleep"; and **did it map to
real user impact** rather than a scare. Then apply the delete criterion without sentiment: **an
alert that fired three or more times with no action taken is deleted or demoted to a ticket**, and
an alert that hasn't fired in six months and whose purpose nobody can explain is deleted. You can
always add it back; you cannot get back the nights it cost.

Two numbers make this reviewable rather than argumentative. The **page-to-incident ratio** — the
fraction of pages that corresponded to real user impact — tells you whether the team is being
trained to disbelieve the pager; below half, you are one bad night from Priya's 04:12. And **pages
per shift**, against the ~2 ceiling, belongs on a leadership dashboard, because it turns "on-call is
rough" into a trend line somebody has to answer for.

## Think about it

1. Your team has an alert `PodRestartCount > 3 in 10m` that pages. Walk it through the four triage
   questions. Where does it land, and what symptom-level alert would catch the same real incidents?
2. Fast-burn and slow-burn alerts on the same SLO will both fire during a large outage. Which
   Alertmanager feature stops that becoming two notifications, and what would you write to configure
   it?
3. An engineer argues that `for: 5m` and `avg_over_time(...[5m])` are "basically the same thing."
   Construct a sample sequence that fires the average but not the `for`, and one that does the
   reverse.
4. Your postmortems are excellent documents and page volume hasn't dropped in a year. What single
   measurement would you add to find out why, and what do you expect it to show?
5. A manager proposes fixing on-call fatigue by adding a third person to the rotation. Argue for and
   against — and name the number that actually decides it.

## Key takeaways

- **An alert is an interrupt on a human's life.** To justify a page it must be **user-visible,
  urgent, actionable, and not self-healing**; everything else is a **ticket** or **dashboard-only**.
  Alert fatigue is a detection failure with a human in the loop, caused by the alerts themselves.
- **Page on symptoms, not causes.** Cause alerts are wrong in both directions — false pages when the
  machine is busy and users are fine, silence when users are broken and every metric is green —
  while a symptom alert catches failure modes nobody imagined. The honest exception is **predictive
  resource-exhaustion** alerts (disk, certificates, quota), and those are **tickets**.
- **Burn-rate alerting is the modern default**: rather than a static threshold that fires on
  30-second blips and sleeps through slow bleeds, alert on how fast the error budget is going over a
  **long window plus a short window** — fast burn pages, slow burn tickets. **`for` requires the
  condition to hold continuously** (one evaluation below the line resets the clock), unlike an
  average over the same window; **`keep_firing_for`** is the matching hysteresis on the way out.
- **Alertmanager is where 200 alerts become 1 notification**: `group_by`/`group_wait`/
  `group_interval` collapse duplicates, `inhibit_rules` with `equal` suppress downstream symptoms
  under a known cause, silences cover maintenance, and the route tree sends `severity: page` to a
  pager and `severity: ticket` to a backlog.
- **Every page carries a runbook link, an owning team, a dashboard link, and real values** — and
  **if there's no runbook, it isn't a page**, because a page you can't write a runbook for was never
  actionable. Every alert resolved by the same manual fix is a **specification for automation**.
- **On-call is a system**: primary/secondary escalation, defined rotations, written handoffs, real
  compensation, a ceiling of about **two pages per shift** (fix the alerts, don't hire more people),
  and code authors carrying their own pager. Incidents get defined **severities**, an **Incident
  Commander who does not debug**, and **mitigation before diagnosis**; postmortems are **blameless
  because blame destroys the information you need**, name contributing factors over a single root
  cause, and are worthless unless the action items ship.

Next: [Dashboards: RED, USE & Grafana](../11-dashboards-red-and-use/) — the other half of this
lesson, since every cause metric you just demoted off the pager has to live somewhere you can
actually read it at 04:13.
