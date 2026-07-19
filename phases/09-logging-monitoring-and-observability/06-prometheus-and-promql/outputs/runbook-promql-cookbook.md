---
name: runbook-promql-cookbook
description: A working PromQL reference — golden-signal queries, the rate-before-sum rule, histogram_quantile patterns, counter-reset gotchas, recording-rule naming, and a checklist for when a query returns nothing.
phase: 09
lesson: 06
---

# PromQL cookbook & debugging runbook

Assumes a 15s `scrape_interval`. Substitute your own metric names.

## The four golden signals

```text
# TRAFFIC — requests per second, per route, whole fleet
sum by (route) (rate(http_requests_total[5m]))

# ERRORS — fraction of requests failing (vector matching drops the differing label)
sum by (route) (rate(http_requests_total{status=~"5.."}[5m]))
  / ignoring(status) sum by (route) (rate(http_requests_total[5m]))

# LATENCY — p99 seconds, per route (keep `le`!)
histogram_quantile(0.99,
  sum by (le, route) (rate(http_request_duration_seconds_bucket[5m])))

# SATURATION — how full the constrained resource is
max by (instance) (db_pool_in_use / db_pool_size)
```

## Non-negotiable rules

- [ ] **`rate` before `sum`.** `sum(rate(x[5m]))` — never sum counters then rate. Summing hides a single instance's reset behind the thirty-nine that kept climbing, and you get a silently deflated number with no error.
- [ ] **Range ≥ 4 × scrape interval.** At 15s scrapes, `[1m]` is the floor and `[5m]` is the default. Fewer than two samples in the window and `rate()` returns nothing at all.
- [ ] **Keep `le` in every histogram aggregation.** `sum by (le, route)`, never `sum by (route)`.
- [ ] **`rate()` for graphs and alerts, `irate()` for spiky debugging, `increase()` for totals.** `irate()` uses only the last two samples and is far too jumpy to alert on.
- [ ] **Never put an unbounded value in a label.** No `user_id`, `order_id`, email, raw URL, or exception message. Route *templates* (`/orders/{id}`), status *classes*, region, version — that's it.
- [ ] **Counters end in `_total`, durations in `_seconds`, sizes in `_bytes`.** Base units, always seconds not milliseconds.

## Counter-reset gotchas

| Symptom | Cause | Fix |
|---|---|---|
| Negative rate | Naive `last - first` across a restart | Use `rate()`, which adds the pre-reset value back |
| Rate dips at every deploy | Window shorter than the restart gap, or `sum` applied before `rate` | Widen the window; rate first |
| Traffic "missing" around a restart | Requests served between the last scrape and the crash were never recorded | Unfixable by query — scrape more often |
| `increase()` returns 3.4 requests | Extrapolation to the window edges | Expected. Round for display only |

## Recording rules

Name them `level:metric:operation` — aggregation level, what's measured, what was done.

```yaml
- record: job:http_requests:rate5m
  expr: sum by (job, route) (rate(http_requests_total[5m]))
- record: job:http_latency:p99_5m
  expr: histogram_quantile(0.99,
          sum by (job, route, le) (rate(http_request_duration_seconds_bucket[5m])))
```

- [ ] Record anything a dashboard runs more than once, or any expression an alert evaluates every 15s.
- [ ] Keep the rule's `interval` ≥ the scrape interval; 30s–1m is typical.
- [ ] Never record a raw counter sum — record the *rate*, so nobody downstream can violate rate-before-sum.
- [ ] Recording rules are evaluated forward only; they do not backfill. A new rule has no history.

## "My query returns nothing" — work down this list

1. **Does the raw selector match?** Strip everything: query just `http_requests_total`. Empty means the problem is the metric name or the labels, not the functions.
2. **Is the metric name exactly right?** Client libraries append `_total` to counters and `_bucket`/`_sum`/`_count` to histograms. You want `http_requests_total`, not `http_requests`.
3. **Are the label values exactly right?** Matching is exact and case-sensitive. Try `{__name__="http_requests_total"}` with no other matchers, then add one at a time.
4. **Is the target actually up?** `up{job="api"}` — if it's `0` or absent, this is a scrape problem, not a query problem. Check the Targets page for the scrape error.
5. **Enough samples in the window?** `rate(x[30s])` at a 15s interval may catch only one sample and returns nothing. Widen to `[5m]`.
6. **Is the data stale?** An instant query looks back at most 5 minutes. If the target died 10 minutes ago the series is gone. Use a range query over a window that includes live data.
7. **Did an aggregation drop the label you're grouping by?** `sum by (pod)` after something already folded `pod` away yields one empty group.
8. **Do the two sides of a binary operator have matching label sets?** Unequal label sets silently produce an empty result. Run each side alone, compare their labels, then add `on(...)`, `ignoring(...)`, or `group_left`.
9. **Was it relabelled away?** Check `metric_relabel_configs` for a `drop` action, and `sample_limit` for a target being rejected wholesale.
10. **Is it a `for:` that never elapsed?** An alert can be correct and still never fire if the condition doesn't hold continuously for the full duration.

## Operational queries worth bookmarking

```text
up == 0                                       # targets down right now
absent(up{job="api"})                         # the job vanished from discovery
changes(process_start_time_seconds[1h]) > 0   # anything restart in the last hour?
count by (job) ({__name__=~".+"})             # series count per job — your cardinality bill
topk(10, count by (__name__) ({__name__=~".+"}))   # which metric is eating the memory
prometheus_tsdb_head_series                   # total active series
rate(prometheus_target_scrapes_exceeded_sample_limit_total[5m]) > 0   # targets being rejected
predict_linear(node_filesystem_avail_bytes{mountpoint="/"}[6h], 4*3600) < 0   # disk full in 4h
```

> ## Decision shortcut
>
> **Rate first, aggregate second, keep `le`.** If a number looks wrong, check those three before anything else — they cause most bad PromQL. If a query returns *nothing*, strip it back to the bare selector and add one piece at a time; the failure is almost always a label that doesn't match, a window too short for `rate()`, or a target that isn't `up`.
