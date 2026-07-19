---
name: runbook-defining-an-slo
description: A one-hour meeting agenda for taking a service from "we should be reliable" to a written SLO, error budget, burn-rate alerts, and an agreed budget policy.
phase: 09
lesson: 09
---

# Runbook: defining an SLO in one hour

Who must be in the room: one product owner, one engineer who owns the service, one person who carries the pager. If any of the three is missing, stop — an SLO nobody agreed to is a preference with a decimal point.

Timebox each step. You are producing a first draft to run for a quarter, not a permanent truth.

---

## Step 1 — Name the user journey (10 min)

- [ ] Write one sentence: **"A `<user>` does `<action>` and expects `<outcome>`."**
      *e.g. "A shopper submits checkout and expects an order confirmation."*
- [ ] Confirm a real human would complain if this got worse. If not, it is not a journey worth an SLO.
- [ ] Pick **one to three** journeys total for the service. Stop there.

> Anti-pattern: a journey per endpoint. You will end up with forty budgets, one of which is always exhausted, and a freeze policy nobody obeys.

## Step 2 — Choose the SLI and define good / valid exactly (15 min)

- [ ] Pick a category: **availability · latency · quality · freshness · throughput**.
- [ ] Write the ratio so a stranger could implement it:

```text
valid   =  <requests in scope>
           minus  /healthz, /readyz, /metrics        (your own probes)
           minus  known crawler / scanner user-agents
           minus  400, 401, 403, 404, 422            (client sent nonsense)

good    =  valid requests with status < 500
           AND duration < <threshold>
```

- [ ] **Never exclude 429** — that is your load shedding, not the client's mistake.
- [ ] Add a separate 4xx-rate alert so a self-inflicted 404/401 spike can't hide in the exclusion.
- [ ] Decide **request-based** (default; tracks human harm) or **window-based** (matches contractual "uptime" language).

## Step 3 — Choose where you measure it (5 min)

- [ ] Availability SLI from the **load balancer or CDN**, not the app. An expired TLS certificate reads as 100% server-side.
- [ ] Add a **black-box probe** from outside your network, several regions, on a schedule.
- [ ] Add **RUM** if you have a client you control — the only honest latency number.

## Step 4 — Pick the threshold and the window (10 min)

- [ ] Latency threshold: a number, never an average. *"99% under 300 ms."*
- [ ] **Check your histogram buckets contain that threshold.** If `le="0.3"` does not exist, you cannot measure your own SLO — add the bucket before you publish.
- [ ] Window: **28 rolling days** (four exact weeks; no calendar cliff).
- [ ] Set the target where **users start complaining**, not at your current performance. An SLO equal to your typical performance is breached by roughly half of all windows by definition.
- [ ] If you have an SLA, set the SLO **strictly tighter** (SLA 99.5% → SLO 99.9%).

### Reference: the nines table

| SLO | budget | per day | per 7 days | per 30 days | per 365 days |
|---|---|---|---|---|---|
| 99% | 1% | 14m 24s | 1h 40m 48s | 7h 12m | 3d 15h 36m |
| 99.5% | 0.5% | 7m 12s | 50m 24s | 3h 36m | 1d 19h 48m |
| 99.9% | 0.1% | 1m 26s | 10m 5s | 43m 12s | 8h 45m 36s |
| 99.95% | 0.05% | 43.2s | 5m 2s | 21m 36s | 4h 22m 48s |
| 99.99% | 0.01% | 8.6s | 1m 1s | 4m 19s | 52m 34s |
| 99.999% | 0.001% | 0.9s | 6.0s | 25.9s | 5m 15s |

## Step 5 — Compute the error budget, both ways (5 min)

Fill this in on the whiteboard, out loud:

```text
window        = <days> x 24 x 60                =        minutes
error budget  = (100% - SLO)                    =        %
  as TIME     = budget% x window minutes        =        minutes of badness
  as REQUESTS = budget% x <valid reqs / window> =        requests may fail

# worked example — 99.9% over 28 days, 10M requests
  window   = 40,320 min ;  budget = 0.1%
  time     = 0.001 x 40,320     = 40.3 minutes
  requests = 0.001 x 10,000,000 = 10,000 requests
```

- [ ] Say the request number aloud. "We are allowed to fail 10,000 checkouts this month" is the sentence that makes the budget real.

## Step 6 — Write the burn-rate alerts (10 min)

`burn rate = observed error ratio / (1 - SLO)`. Rate 1 exhausts the budget exactly at the window's end; a total outage burns at 1000×.

| burn rate | long window | short window | budget consumed | response |
|---|---|---|---|---|
| **14.4×** | 1 hour | 5 min | 2% | page |
| **6×** | 6 hours | 30 min | 5% | page |
| **1×** | 3 days | 6 hours | 10% | ticket |

- [ ] Both windows must be over threshold. The **long** one suppresses blips; the **short** one clears the alert within minutes of recovery.
- [ ] Write the query for your metrics backend and check it returns a number *today*, before you rely on it.

## Step 7 — Agree the budget policy, in advance (10 min)

Write these four lines down and get verbal agreement from all three people:

- [ ] **Budget > 50%** → ship freely; risky changes, migrations, chaos experiments allowed.
- [ ] **Budget 50–25%** → risky launches need a named reviewer.
- [ ] **Budget < 25%** → no risky changes; next work item is reliability.
- [ ] **Budget exhausted** → freeze non-essential changes until it recovers.
- [ ] **Named exceptions**, decided now: security patches and data-loss fixes always ship. Write the list; do not negotiate it during an incident.

## Step 8 — Schedule the review

- [ ] Put the burndown chart somewhere both rooms see it weekly.
- [ ] Review the SLO itself **quarterly**: is it too tight (constant freeze, no shipping) or too loose (budget always 90% unspent, so you could be shipping faster)?
- [ ] Never move the SLO *during* a breach to end the breach.

---

> ## Decision shortcut
>
> **If it isn't a symptom a user would complain about, it isn't an SLI.** If it has no window, it isn't an SLO. If it has no money attached, it isn't an SLA. If nobody agreed to the policy *before* the incident, you don't have an error budget — you have a chart. And if your histogram has no bucket at your threshold, you don't have a measurement at all.
