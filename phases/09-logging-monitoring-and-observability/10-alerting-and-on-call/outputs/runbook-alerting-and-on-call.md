---
name: runbook-alerting-and-on-call
description: The working set for a humane on-call practice — an alert review checklist with a delete criterion, the runbook template every page must link to, the incident response quick-reference, and a postmortem template with action-item tracking
phase: 09
lesson: 10
---

# Alerting & On-Call Runbook

Four artifacts you will actually reuse: **review** your alerts, **document** the ones that survive,
**respond** when they fire, and **learn** afterwards.

## 1 — Alert review checklist

Run this monthly or quarterly against every alert that can notify a human. One pass per alert.

**Destination test** — answer in order; the first `no` decides where it goes.

- [ ] **Is a user affected right now?** No → **dashboard only**, no notification.
- [ ] **Is it urgent — does waiting until morning make it worse?** No → **ticket**.
- [ ] **Can a human act in the next hour to change the outcome?** No → **ticket**, or automate it.
      "Acknowledge and go back to sleep" is not an action.
- [ ] **Is there a runbook and a named owning team?** No → **ticket**, and write the runbook.
- [ ] All four yes → **page**.

**Quality test** — for anything that survives as a page:

- [ ] The alert measures a **symptom** (errors, latency, budget burn, queue drain), not a cause
      (CPU, memory, restarts). Cause alerts are allowed only as *predictive* resource-exhaustion
      warnings — disk, certificates, quota — and those are tickets.
- [ ] It has a `for` (or equivalent pending duration) long enough that transients don't fire it.
- [ ] It has `severity`, an owning `team`, and the SLO it defends as labels.
- [ ] The summary annotation contains **actual values**, not a category.
- [ ] It carries a `runbook_url` and a `dashboard_url`, and both resolve.
- [ ] Firing it does not also fire five other alerts (grouping and inhibition are configured).

**Delete criterion** — apply without sentiment:

- [ ] Fired **3+ times in 90 days with no action taken** → delete or demote to a ticket.
- [ ] **Never fired in 6 months** and nobody can state what it would catch → delete.
- [ ] Duplicates another alert's coverage → delete the noisier one.
- [ ] Threshold was tuned for traffic levels that no longer exist → retune or delete.

**Track two numbers per rotation:** page-to-incident ratio (below ~50% means the pager is being
disbelieved) and pages per shift (against a ceiling of ~2 per 12-hour shift).

## 2 — Runbook template

Every page links to one of these. If you cannot fill it in, the alert is not a page.

```markdown
# Runbook: <AlertName>

**Owning team:** <team>   ·   **Severity:** page | ticket   ·   **Dashboard:** <url>

## What this means in user terms
One sentence. "Checkout is failing for a measurable share of users."

## How to confirm it is real
The exact query, dashboard panel, or synthetic check. What a false positive looks like.

## Mitigations, in order (do these BEFORE diagnosing)
1. Roll back the most recent deploy:  <command / link>
2. Fail over to <region / replica>:   <command / link>
3. Disable the feature flag <name>:   <link>
4. Shed load / scale out:             <command>

## Diagnosis, once users are safe
Where to look, in order: traces → logs for the failing span → the cause dashboards.

## Escalation
Secondary on-call → <team> → <upstream vendor + contact / support tier>.

## Known false positives / recent history
Link to past incidents where this fired.
```

## 3 — Incident response quick-reference

| Severity | Criteria | Response |
|---|---|---|
| **SEV1** | Core user journey fully or nearly fully broken for most users; data loss; security breach | Page now · assign an Incident Commander · war room · public status page · notify leadership · updates every 30 min |
| **SEV2** | Significant degradation, or a full break for one region / tenant / platform; workaround exists | Page the owning team · IC if it runs past ~30 min · internal comms · updates hourly |
| **SEV3** | Contained or cosmetic; no meaningful user impact; slow-burn budget alert | Ticket · business hours · no page |

**Roles** (one person may wear all three on a small incident):

- **Incident Commander** — owns the incident, not the fix. Decides, delegates, keeps the timeline,
  calls escalation and stand-down. **Does not debug.**
- **Operations Lead** — the only person making changes to the system.
- **Communications Lead** — status page, stakeholders, support team.

**The rules:**

- [ ] **Mitigate before you diagnose.** Roll back, fail over, shed load, flip the flag. Restore the
      user first; understand later. The cause will still be there tomorrow.
- [ ] One incident channel, one running **timeline**, every action timestamped.
- [ ] One person changing production at a time.
- [ ] Status page updated **early** and on an **announced cadence**, even when the update is
      "still investigating."
- [ ] Declare the severity out loud, and downgrade explicitly when it improves.

## 4 — Postmortem template

```markdown
# Postmortem: <short title>            Date: <date>   ·   Severity: SEV<n>

## Impact
Users affected: <n or %>   ·   Duration: <mm:ss>   ·   Error budget burned: <%>
What the user actually experienced, in one sentence.

## Timeline
| Time (UTC) | Event |
|---|---|
| 14:02 | Deploy 3f21c reaches 100% |
| 14:11 | CheckoutBudgetFastBurn fires |
| 14:22 | Rollback started |
| 14:31 | Error ratio back under budget |

## Contributing factors
Not "root cause" — list every factor that had to be true. Include detection and response
delays, not just the trigger.

## What went well · What went badly · Where we got lucky

## Action items
| # | Action | Type (prevent / detect faster / mitigate faster) | Owner (a person) | Due | Ticket |
|---|---|---|---|---|---|
| 1 | | | | | |
```

Blameless by design: no individual is named as a cause. Ask how the system made the mistake easy,
available and unnoticed. **Track action-item completion rate** — below ~70% and the process is
theatre.

## Decision shortcut

> Page only on what a **user** feels, and only when it is **urgent**, **actionable**, and has a
> **runbook** — everything else is a ticket or a dashboard. Alert on **error-budget burn rate** over
> two windows rather than a static threshold, let Alertmanager **group and inhibit** so 200 alerts
> become one call, cap the pager at **~2 pages per shift** and fix the alerts when you exceed it,
> **mitigate before you diagnose**, and keep postmortems **blameless** so the information survives.
> Any alert that fired three times without producing an action is noise: delete it.
