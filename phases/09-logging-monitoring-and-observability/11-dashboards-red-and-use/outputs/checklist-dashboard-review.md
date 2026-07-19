---
name: checklist-dashboard-review
description: A review checklist for an existing dashboard — does every panel answer a named question, is RED/USE coverage complete, and which panels have earned the right to stay
phase: 09
lesson: 11
---

# Dashboard Review Checklist

Run this on an existing dashboard: before you add a panel someone asked for, after any incident
where the dashboard didn't help, and once a quarter on anything anyone still opens. The test is
not "does it look thorough." The test is **"under stress, does this get me to the next question
faster than typing a query would?"**

Budget 20 minutes. Bring the last three incident timelines with you.

## Step 0 — Establish what this dashboard is for

- [ ] It has **one stated audience and one level**: business/journey, service, or resource.
      A dashboard serving all three serves none.
- [ ] Its **name says which** — `checkout · service RED`, not `Service Overview`.
- [ ] There is **exactly one** dashboard for this thing. If there are six variants, find out which
      one people actually open and delete the rest.
- [ ] Someone is **named as owner**. Unowned dashboards are how you end up with 214.

## Step 1 — Every panel answers a named question

- [ ] Every panel **title is a question**: `What fraction of requests are failing?`, not `Errors`.
      A panel whose question you cannot phrase should not exist.
- [ ] No panel exists **only because an incident once needed it**. That's what ad-hoc querying
      is for.
- [ ] Panel count is **under ~16**. Above that nobody reads it under pressure; they scroll past it.
- [ ] **No broken panels.** Every panel returns data right now. An empty graph caused by a renamed
      metric looks exactly like "everything is fine" — this is the most dangerous failure on the list.

## Step 2 — RED coverage (for a service dashboard)

- [ ] **Rate** — requests/sec, `sum by (route) (rate(http_requests_total{...}[5m]))`.
- [ ] **Errors** — as a **ratio** of the rate, not a count. Both sides of the division grouped by
      the same labels so PromQL matches one-to-one.
- [ ] **Duration** — `histogram_quantile(...)` over summed bucket rates, **p50/p90/p99 on one axis**.
- [ ] **Failed-request latency shown separately.** A fast 500 flatters the main latency panel
      exactly when things are worst.
- [ ] **SLO / error-budget status** is on this dashboard, not a different one.
- [ ] Breakdowns are **per route**, and the route label is bounded (no raw URLs with IDs in them).

## Step 3 — USE coverage (for the resources it depends on)

For each constrained resource — CPU, memory, disk, network, connection pool, thread pool, queue:

- [ ] **Utilization** — what fraction is busy.
- [ ] **Saturation** — queue depth, wait time, or blocked callers. **This is the one that's missing.**
      Check every resource individually; do not assume.
- [ ] **Errors** — timeouts, allocation failures, rejections, drops.
- [ ] Saturation is placed **before** utilization in the row. It predicts; utilization only confirms.
- [ ] The **Four Golden Signals audit**: latency, traffic, errors, saturation — can you point at a
      panel for each? Saturation is the usual gap.

## Step 4 — Reading it under stress

- [ ] The **top-left panel answers "do I need to act?"** — error budget or error ratio.
      Not fleet-average CPU. Not uptime.
- [ ] **No averages of latency anywhere.** Search the JSON for `avg(`, `avg_over_time(`, and the
      `_sum / _count` idiom.
- [ ] **Every panel declares a unit.** `0.62` should render as `62%`; `4.1` should say seconds.
- [ ] **Thresholds are drawn** on any panel with a target worth comparing against.
- [ ] **One time range for the whole dashboard.** No panel sets its own `timeFrom` override —
      if panels don't share an x-axis, comparing them produces false conclusions.
- [ ] **Series per panel is small** (roughly under 10). No line-per-instance at fleet scale; use
      aggregate, `topk`, or max-and-median.
- [ ] **Colour is not the only channel** carrying meaning, and red means bad and only bad.
- [ ] **No dual y-axes.** Two scales on one plot manufacture correlations that aren't there.

## Step 5 — The things that turn a picture into a tool

- [ ] **Deploy annotations** overlaid on every time series. Highest-value single feature: it
      answers "what changed at 03:09?" visually, with no query.
- [ ] **Incident/maintenance annotations** too, if you have them.
- [ ] Every panel that can indicate a problem **links to its runbook**.
- [ ] A link to **logs, pre-filtered** to the same service and the same time range.
- [ ] **Exemplars enabled** on the latency panel, wired to your trace store — click the p99 spike,
      land on a real slow trace.
- [ ] The **time range travels** to whatever you drill into. A drill-down that resets to "last 6h"
      throws away the one fact you had established.

## Step 6 — Dashboards as code

- [ ] The dashboard is **JSON in git**, not clicked together in the UI.
- [ ] It is **generated from a template** shared with every other service, so a fix lands everywhere.
- [ ] It is **provisioned from files** with `allowUiUpdates: false` — one source of truth.
- [ ] A **linter runs in CI** over the generated JSON: titles are questions, units present, no
      average-latency, no grid overlaps or gaps, panel count under budget.
- [ ] Changes arrive by **pull request**, so the diff shows which query changed and why.

## Step 7 — The delete criterion

Be ruthless here; this is the step that keeps the other six true.

- [ ] For each panel: **was it looked at during any of the last three incidents?**
      If no — and nobody can name the question it answers — **delete it.**
- [ ] Delete every **vanity metric**: cumulative totals, all-time counts, anything that only goes up.
- [ ] Delete panels that **duplicate an alert**. If it matters enough to stare at, it should page you.
- [ ] Delete **whole dashboards** nobody opened in the last quarter.
- [ ] Deleting is safe **only if the dashboard is generated** — so if you can't delete confidently,
      Step 6 is your real work item, not this one.
- [ ] Add one line to every incident review: *did the dashboard help, and what panel would have
      helped faster?* Then change the **generator**, so every service improves at once.

## Decision shortcut

> **RED for your services, USE for what they depend on, and saturation before utilization.**
> Every panel states its question in its title, shows percentiles rather than averages, carries a
> unit and a threshold, and links out to a runbook, to logs, and to a trace. If a panel wasn't
> looked at in the last three incidents and nobody can name its question, delete it — and if
> deleting feels risky, the fix is to generate the dashboard from code, not to keep the panel.
