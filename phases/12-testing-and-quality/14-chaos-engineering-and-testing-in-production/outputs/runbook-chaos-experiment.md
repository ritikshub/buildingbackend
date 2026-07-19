---
name: runbook-chaos-experiment
description: For the engineer running a fault-injection experiment against a system with real users — the four prerequisites to check before touching anything, the hypothesis form to fill in, the injection ladder in order, the abort criteria, and what to write down afterwards.
phase: 12
lesson: 14
---

# Runbook: Running a Chaos Experiment

For the engineer who is about to inject a fault into a system that has users. Work top to
bottom. If any gate in section 0 fails, stop — the exercise below is only an experiment
when all four hold, and is otherwise an outage you scheduled.

Every number quoted here was measured by this lesson's `code/chaos.py`, which needs no
network and exits in about ten seconds. Run it if you want to argue with a number.

---

## 0. The four gates — 10 minutes, before anything else

All four. Not three.

- [ ] **An SLO exists and you can query it right now.** Not "we have dashboards" — a
      specific request-based indicator with a threshold, e.g. *"a request is good if it
      returns without an error in under 400 ms; ≥ 99.5% of requests are good."* A latency
      SLI needs a threshold; an average is the statistic a saturated tail hides in.
- [ ] **You know your monitor's lag.** A one-second window cannot be scored until it has
      closed and its requests have finished. Measured here: **3.0 seconds of structural
      blindness**, which is a floor under every time-to-detect number you will produce and
      under how fast any automatic abort can possibly fire.
- [ ] **The rollback has been executed this quarter.** Not documented — executed. The fault
      injection you cannot turn off is an incident.
- [ ] **The blast radius is a number you can turn down**, plus an automatic abort bound to
      the SLO. Measured: an abort on 3 consecutive breaching windows halted the fault
      **5.0 seconds** in.

```bash
# gate 2, empirically: how long between a request failing and your dashboard showing it?
# fail one request deliberately, then poll:
date -u +%T; curl -s -o /dev/null "$SVC/__fail_once"; \
  while ! promtool query instant "$PROM" 'rate(http_errors_total[1m]) > 0' | grep -q 1; \
  do sleep 1; done; date -u +%T
```

---

## 1. Write the hypothesis down BEFORE you inject

This is the deliverable. The fault is only how you test it. Fill in every field; a blank
is a thing you have not thought about.

```text
EXPERIMENT:      inventory latency +200 ms
STEADY STATE:    >= 99.5% of /orders requests good (no error, < 400 ms), per 1-min window
BLAST RADIUS:    5% of requests, cohort-stable, header-gated
DURATION:        120 s, self-terminating

WE EXPECT:
  - the injected cohort's p99 to rise from ___ ms to ___ ms
  - the control cohort's p50 to be UNCHANGED at ___ ms
  - overall good-request rate to stay above 99.5%
  - the inventory circuit breaker to trip:   yes / no   <- commit to an answer
  - the orders worker pool queue to peak at: ___
  - total error budget spent: < ___ minutes

WE WILL ABORT IF:
  - good-request rate < 99.5% for 3 consecutive windows, OR
  - any dependency other than inventory shows elevated latency, OR
  - anyone in the room wants to
ROLLBACK:        DELETE the toxic / set duration to 0 / flip flag `chaos.inventory.latency`
OWNER:           ____   OBSERVER: ____   START: ____   HARD STOP: ____
```

**Commit to the breaker answer in writing.** Measured on this lesson's system, the breaker
tripped **10 times** against a hard kill and **0 times** against a 5× slowdown — it counts
errors, and a slow dependency produces none. If your written guess and the result disagree,
that gap is the experiment's entire yield.

---

## 2. The injection ladder — in this order, one rung per session

Do not skip ahead. Do not move up until the rung below is boring.

| # | Inject | Why here | What you are looking for |
|---|---|---|---|
| 1 | **+200 ms latency, 5% of calls, one dependency** | the fault your staging has never produced, and the one that costs most | pool queue depth, p99 of the injected cohort, whether the breaker fires |
| 2 | **Same, for 30 s, then remove it** | the metastability check | does recovery take longer than the fault? Measured: `never` vs `4.0 s` |
| 3 | **Hard-kill the dependency** | third, not first — your code most likely already handles it | that the fallback runs at all |
| 4 | Resource exhaustion (pool, FDs, memory) | the failure latency *causes*, one hop away | which pool bounds first |
| 5 | Dependency loss / zone loss | fleet scale | see Phase 11 Lesson 9 |
| 6 | Clock skew, packet loss, disk full, DNS | the forgotten ones | that your *observability* survives them |

**Rung 2 is the one that changes a config file.** If the system does not return on its own
after the trigger is removed, you have a sustaining effect. Measured: naive 3× retry burned
**267.8 minutes** of error budget and never recovered; the same fault with a retry budget,
full jitter and a breaker burned **101.8 minutes** and recovered in **2.7 seconds**.

**Rung 6's trap:** a disk-full or DNS failure often disables the logging pipeline before it
disables the service, putting your instrument inside the blast radius. Verify observability
is out of scope before injecting these.

---

## 3. Injection, with real commands

### Toxiproxy — the first tool, works in CI, no cluster

```bash
docker run -d --name toxiproxy -p 8474:8474 -p 25432:25432 ghcr.io/shopify/toxiproxy

curl -s -XPOST http://localhost:8474/proxies -d '{
  "name": "inventory", "listen": "0.0.0.0:25432", "upstream": "inventory:5432"
}'

# rung 1: grey failure on 5% of connections
curl -s -XPOST http://localhost:8474/proxies/inventory/toxics -d '{
  "name": "grey", "type": "latency", "stream": "downstream",
  "toxicity": 0.05, "attributes": {"latency": 200, "jitter": 50}
}'

# ABORT — have this in your shell history before you run the line above
curl -s -XDELETE http://localhost:8474/proxies/inventory/toxics/grey
```

- `toxicity` is the blast-radius dial. **A toxic with no `toxicity` defaults to 1.0** — 100%.
- `stream: downstream` delays responses. `upstream` delays your requests: a different experiment.
- Rung 3 is `POST /proxies/inventory` with `{"enabled": false}`.
- `timeout` (accepts and never answers) is the toxic that finds missing timeouts.
- `slicer` splits a response into delayed pieces and finds partial-read bugs nothing else does.

### Envoy — percentage-based, header-gated, no new infrastructure

```yaml
- name: envoy.filters.http.fault
  typed_config:
    "@type": type.googleapis.com/envoy.extensions.filters.http.fault.v3.HTTPFault
    delay:
      fixed_delay: 0.2s
      percentage: { numerator: 5, denominator: HUNDRED }
    headers:
      - name: x-chaos-experiment
        string_match: { exact: "inventory-grey-failure" }
```

`denominator` also takes `TEN_THOUSAND` and `MILLION` for sub-1% radii. Put the filter on
the **upstream** cluster's listener, not your own — "my dependency is slow" and "I am slow"
are different experiments. The `router` filter must remain last in the chain.

### Chaos Mesh — set `duration`, always

```yaml
apiVersion: chaos-mesh.org/v1alpha1
kind: NetworkChaos
metadata: { name: inventory-grey-failure, namespace: prod }
spec:
  action: delay
  mode: fixed-percent
  value: "5"
  duration: 120s          # it stops itself even if you lose your laptop
  direction: to
  selector:
    namespaces: [prod]
    labelSelectors: { app: inventory }
  delay: { latency: 200ms, jitter: 50ms, correlation: "50" }
```

### AWS FIS — bind the stop condition to the USER-FACING alarm

Not to an alarm on the resource you are attacking. The point of a stop condition is that
something other than the person running the experiment can end it.

---

## 4. While it runs — what to watch, in this order

- [ ] **The SLI first, the fault second.** Your steady-state metric is the experiment's
      output. Everything else is diagnosis.
- [ ] **The control cohort's p50.** If it moves, your blast radius is bigger than you set
      it. Measured: at 25% injection the *uninjected* cohort's p50 rose from **90 ms to
      252 ms**, and the experiment lost its own baseline (measured z fell 10.3 → 9.8).
- [ ] **Queue depth on every pool between you and the fault, including your own workers.**
      Saturation propagates *upward*, away from the fault: the injected edge's pool peaked
      at 10 while `orders`' own workers peaked at **675**.
- [ ] **Wire attempts per second to the faulted dependency.** If this rises while goodput
      falls, you are watching a retry storm form. Measured: 110 attempts/s against a flat
      70 req/s of real demand, with goodput at exactly 0.
- [ ] **Breaker state.** If it is closed and everything is broken, the fault is grey.

---

## 5. Abort criteria — decided in advance, not in the moment

Abort immediately on any of these. Nobody needs to justify an abort.

- [ ] Good-request rate below the SLO for **3 consecutive windows**.
- [ ] Error budget spend passes the number in section 1. Convert before you start: at
      70 req/s a 99.5% objective permits **0.35 bad requests per second**, so N failures
      cost N/0.35 seconds of the month's budget. 2,744 failures = **130.7 minutes**.
- [ ] Any dependency you did not inject shows elevated latency.
- [ ] The control cohort is affected.
- [ ] Anyone present is uncomfortable. No debate.

**After an abort, expect a tail.** Removing the trigger is not the same as recovering:
measured, a 20-second fault took **21.0 seconds** to recover from after it was already
gone, and a 30-second one with naive retries never recovered at all. Hold the room until
three consecutive good windows, not until the injection is deleted.

---

## 6. Afterwards — the part that is the actual deliverable

- [ ] **Record each prediction against each measurement**, including the ones you got right.
- [ ] **Name every gap.** A gap between what the operators believe and what the system does
      is where the next incident lives. That gap is the yield; "it survived" is not.
- [ ] **Convert damage to budget minutes** and put it in the write-up. A programme that
      cannot state its own price gets cancelled by someone who can.
- [ ] **File the config changes the experiment implied**, with the number attached:

| finding | the change |
|---|---|
| the breaker never tripped on a slow dependency | add a latency-based ejection or a tighter timeout; the breaker cannot see slow |
| pool queue grew unbounded | set the pool-acquire timeout, not just the read timeout |
| recovery outlasted the fault | cap retry amplification with a budget; measured 1.24× vs 1.64× decided it |
| retries present, budget absent | a retry without a budget burned **267.8 min** vs **230.1** for no defence at all |
| queue limit never fired | you are paying for a defence you do not own — verify or remove it |

- [ ] **Schedule the next rung**, and automate this one at ≤ 5% if it was boring twice.

---

## 7. What this does not cover

Chaos experiments find **emergent, systemic** failures: saturation, feedback loops, missing
fallbacks, defences that were never executed. They cannot find a logic bug. Nothing in this
runbook would catch a `<` that should be `<=`, a provider renaming a status string, or a
consumer double-charging on a redelivered message. Those need a unit test, a contract test
and a duplicate-delivery test, and this replaces none of them.

The two rules that survive everything else here:

1. **Write the number down before you inject.** Otherwise whatever happened becomes what
   you expected, and a demonstration can only ever agree with you.
2. **Turn the dial down.** A 1% experiment recovered a Mann-Whitney z of **6.2** for **2**
   failed requests where 100% recovered **22.7** for **637** — 3.7× the signal for 318× the
   damage. Save the large radius for the emergent effects that genuinely need it, with
   humans watching.

---

**Sources:** Basiri, Behnam, de Rooij, Hochstein, Kosewski, Reynolds & Rosenthal, *Chaos
Engineering*, IEEE Software 33(3), 2016 · Bronson, Aghayev, Charapko & Zhu, *Metastable
Failures in Distributed Systems*, HotOS 2021 · Little, *A Proof for the Queuing Formula
L = λW*, Operations Research 9(3), 1961 · Mann & Whitney, *Annals of Mathematical
Statistics* 18(1), 1947 · Wald, *Sequential Analysis*, Wiley, 1947.
