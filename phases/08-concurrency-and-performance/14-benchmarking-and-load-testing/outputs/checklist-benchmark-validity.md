---
name: checklist-benchmark-validity
description: A validity checklist to run before believing — or publishing — any performance number, covering environment control, warmup, representative inputs, trial count, percentiles over means, effect-versus-noise, open-loop generation, coordinated omission, achieved-versus-intended rate, goodput, generator saturation and baseline comparison
phase: 08
lesson: 14
---

# Benchmark & Load-Test Validity Checklist

Paste into the PR description, the performance report, or the capacity plan. Any box you cannot tick is a
caveat you owe the reader. A number with no environment, no spread and no baseline is not a result.

## 0 — State the claim

- [ ] The claim is a **comparison**, not an absolute: *"X is N% faster than baseline `abc1234`"*, not
      *"X takes 12 ms"*. Absolute numbers are true only of the machine that produced them.
- [ ] If it will appear in a contract, an SLO or a customer-facing doc, say so — the bar below goes up.

## 1 — Environment controlled and stated

- [ ] Ran on a **dedicated machine**, not a laptop with a browser and a build running.
- [ ] Pasted into the report: CPU model, core count, instance type, kernel, runtime version, container
      CPU/memory limits, and confirmation the box was otherwise idle.
- [ ] **Frequency scaling** pinned or turbo disabled (or named as uncontrolled); thermal state consistent;
      no cgroup CPU quota that throttles mid-run (`cat /sys/fs/cgroup/cpu.max`).
- [ ] Both sides of the comparison ran on the **same machine, same session**, ideally interleaved.

```bash
uname -a; nproc; lscpu | grep -E 'Model name|MHz'; python3 -VV; uptime   # load avg ~0 before you start
```

## 2 — Warmup done

- [ ] Warmup iterations are **discarded, not averaged in**. One lazy import plus a table build can make
      iteration 1 cost 100x steady state and inflate a 40-iteration mean by ~4x.
- [ ] Warmup covers lazy imports, first-call attribute/method resolution, connection-pool fill, cache
      population, and page-in of large working sets.
- [ ] On a **JIT runtime** (JVM, .NET, V8, PyPy): thousands of iterations, and you confirmed the number
      stopped moving before measurement started.

## 3 — Inputs representative and varied

- [ ] Inputs **vary between iterations**. A repeated input measures your memoization, the CPU cache and the
      OS page cache — not your code.
- [ ] **Size** matches production (row counts, payload sizes, collection lengths), not a convenient 10.
- [ ] **Distribution** matches production: pre-sorted vs random vs mostly-ordered, uniform vs skewed. A sort
      benchmark on sorted data can reverse which implementation wins.
- [ ] **Cardinality** stated (distinct keys, concentration on the hottest) and **cache hit rate** matches
      production's measured rate — a 100% hit rate benchmarks a dictionary.
- [ ] Request **mix** matches production (read/write ratio, endpoint mix), not one hot path; and in
      compiled/JIT languages the result is consumed via a blackhole so it cannot be optimized away.

## 4 — Timing done correctly

- [ ] **Monotonic, high-resolution** clock (`time.perf_counter`, `System.nanoTime`, `steady_clock`).
      Never a wall clock (`time.time`) — NTP can move it backwards and produce negative durations.
- [ ] Each timed **batch is far larger than one clock tick** (≥ 1 ms, or ≥ ~100 ticks). Timing a
      sub-microsecond operation once measures the clock and can read 20x high.

## 5 — Multiple trials, and the noise is measured

- [ ] **5-10 independent trials**, not one long run. Iterations within a trial re-measure the same
      environmental state; only separate trials re-sample the environment.
- [ ] For serious claims, **separate processes** (`pyperf`) — also re-randomizes hash seed and layout.
- [ ] **Noise measured on unchanged code**: baseline against itself, spread recorded. That is your detection
      floor; nothing smaller is reportable.

## 6 — Percentiles, not means

- [ ] **No mean anywhere in the report.** Median, p95, p99, p99.9, max.
- [ ] **Spread reported** (stdev, IQR, or min/max) and **sample count reported** — a p99 over 300 samples is
      three data points.
- [ ] Percentiles were **not averaged** across workers, shards, machines or time windows. Merge the
      histograms, then compute the percentile once.

## 7 — The difference exceeds the noise

- [ ] Per-trial medians of the two sides **do not overlap**, and the gap is **≥ 3x the combined spread**.
- [ ] If either fails, the finding is written as **"no detectable change"**, not as a small improvement.
- [ ] `pyperf compare_to` printing *"Not significant!"* is treated as a verdict, not a formatting quirk.

## 8 — Load generation model (capacity questions only)

- [ ] The generator is **open-loop / arrival-rate** if the question is capacity, headroom or tail latency.
      Closed-loop generators cannot overload a system at any VU count — the response gates the next request.
- [ ] The model was **chosen, not defaulted**, and you know which one your tool used:
      **open** — `wrk2 -R`, `vegeta -rate`, k6 `constant-arrival-rate`/`ramping-arrival-rate`,
      Gatling `constantUsersPerSec`, JMeter Throughput Shaping Timer.
      **closed** — k6 `constant-vus`, Locust (default), Gatling `atOnceUsers`/`rampUsers`, JMeter thread groups.
- [ ] Closed-loop used only where the question really is *"what do N fixed users experience?"*

## 9 — Coordinated omission addressed

- [ ] Latency measured from each request's **intended start time**, not from when the client managed to send.
- [ ] Recording uses HdrHistogram or equivalent with `record_corrected_value(value, expected_interval)`.
- [ ] No implausible cliff between adjacent percentiles: p99 = 8 ms next to p99.9 = 1,900 ms is a 250x jump
      between neighbours, which is a sampling artifact rather than a distribution.
- [ ] If a closed-loop run is all you have, the back-fill was applied **per virtual user with that user's own
      cycle time**, and the caveat is stated: the correction recovers ~90%, not 100%.

## 10 — Achieved rate verified

- [ ] **Intended and achieved rate both printed**, every run, without exception.
- [ ] Achieved ≥ **95%** of intended, or the run is discarded rather than interpreted.
- [ ] Client-side **scheduling lag** (median and max) recorded — rising lag means the generator is behind and
      therefore silently omitting.

## 11 — Goodput reported

- [ ] **Goodput** (correct *and* inside the deadline) reported next to throughput, with the deadline stated.
- [ ] **Error rate broken down by cause**: shed/rejected, timed out, 5xx, connection failures.
- [ ] Capacity quoted as **maximum useful throughput** (highest rate meeting the SLO), never as peak.
- [ ] Under overload, the pass condition is that the system **sheds fast and cheaply**, not that throughput held.

## 12 — Generator not saturated

- [ ] Generator CPU/memory/fd usage recorded and not pinned; it ran on a **different machine** from the SUT.
- [ ] Generator proven innocent: it hit the target rate against a **null/echo endpoint** at ≥ 1.5x the test rate.
- [ ] Network path is not the limit (bandwidth, PPS, ephemeral ports, conntrack, NAT), and connection reuse is
      configured deliberately — an accidental TLS handshake per request measures handshakes.

## 13 — Baseline comparison

- [ ] Compared against a **specific baseline commit**, same job and same runner — not an absolute threshold
      and not a number from last quarter.
- [ ] Tolerance band **sized from measured noise** (§5) — a 5% gate on a ±15% runner is alarm fatigue.
- [ ] CI gate scoped to **large** regressions; precise numbers come from dedicated hardware on a schedule.
- [ ] **Reproducible**: exact command, seed, dataset and commit are in the report.

```bash
pytest --benchmark-only --benchmark-save=base                       # on the merge-base
pytest --benchmark-only --benchmark-compare=0001 \
       --benchmark-compare-fail=median:20%                          # on the PR
```

## Report template

```text
CLAIM        <X> vs baseline <commit>: median <a> -> <b> (<n>%), p99 <a> -> <b> (<n>%)
VERDICT      REAL / NOT PROVEN  (gap <g>, combined trial noise <n>, ranges disjoint: yes/no)
ENVIRONMENT  <instance/CPU/kernel/runtime>, governor <x>, otherwise idle
METHOD       <k> trials x <m> samples, <w> warmup batches discarded, batch size <n>
DATA         <size>, <distribution>, <cardinality>, cache hit rate <x>%
LOAD MODEL   open-loop, <R> rps intended / <A> rps achieved (<p>%), CO-corrected: yes
LATENCY      p50 <> p95 <> p99 <> p99.9 <> max <>   (n = <samples>)
GOODPUT      <g> rps inside <deadline> ms  |  throughput <t> rps  |  errors <e>%
CAPACITY     max useful throughput <u> rps at p99 <l> ms   (peak <p> rps — not capacity)
GENERATOR    <host>, CPU <x>%, median sched lag <l> ms — not saturated
CAVEATS      <every box above you could not tick>
```
