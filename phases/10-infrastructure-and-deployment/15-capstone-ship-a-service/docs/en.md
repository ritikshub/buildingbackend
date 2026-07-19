# Capstone: Ship a Service End to End

> Fourteen lessons built the stages. This one runs one service through all of them — commit, image, registry, declared infrastructure, orchestrated fleet, routed traffic — and then lands a change that needs **both** a schema migration and a new code path, three different ways. Staged properly it costs **0 user-facing errors**. Shipped as "one migration and one deploy" it costs **48,983 5xx and 32,259 silent bad reads**, because the rollout does not fail — it *waits*. Canaried the way most teams canary, it costs **0 errors and 57,614 wrong prices**, because the canary watched one instance for 600 seconds and only **250 of its 24,600 requests** ever executed the code being tested. Then an incident, where a tidy-up done nine minutes early takes time-to-mitigate from **6.7 s to 849 s**.

**Type:** Build
**Languages:** Python
**Prerequisites:** [Rollback, Backups & Disaster Recovery](../14-rollback-backups-and-disaster-recovery/) · [Deployment Strategies: Rolling, Blue-Green & Canary](../11-deployment-strategies/)
**Time:** ~110 minutes

## The Problem

Every lesson in this phase built one stage and measured it in isolation, which is the only way to learn a stage. It is not how anything breaks.

Here is the service. It is a checkout endpoint, it takes **250 requests a second**, it runs on six instances behind a router, and it works. Fourteen lessons' worth of machinery stands behind it: a content-addressed image built from a dependency-ordered Containerfile, a signed digest with provenance, admission control at the cluster door, configuration held outside the artifact, infrastructure declared in code, a control loop keeping six replicas alive, a registry of healthy endpoints, a proxy that drains before it kills, a pipeline that builds once and promotes, a rollout strategy, a flag system, a migration runner, and a backup you have actually restored.

Every one of those is configured correctly. This lesson is about the **seams**.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 980 648" width="100%" style="max-width:940px" role="img" aria-label="The whole path a service takes, drawn as eight stacked stages from a source tree to users, with the lesson that built each stage and the measured result from this capstone's run: build produces one digest and a 493 times faster rebuild, the registry admits one of five references, one artifact plus three configs makes three release ids, the declared infrastructure plan is refused because three of four resources would be replaced, the control loop converges in twenty-six seconds and reverts drift in one tick, the router severs 480 requests because the drain window is shorter than the client's connection lifetime, and 250 requests a second reach users. A column on the right shows the change itself moving through the lower half of the stack: rollout, flag, schema and rollback.">
  <defs>
    <marker id="l15-a1" markerWidth="10" markerHeight="10" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker>
    <marker id="l15-a2" markerWidth="9" markerHeight="9" refX="5.5" refY="3" orient="auto"><path d="M0,0 L6.5,3 L0,6 Z" fill="#e0930f"/></marker>
  </defs>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <text x="490" y="26" text-anchor="middle" font-size="14.5" font-weight="700" fill="currentColor">One service, the whole distance — and the lesson that built each stage</text>
    <text x="490" y="44" text-anchor="middle" font-size="10" fill="currentColor" opacity="0.85">Every figure below is printed by code/ship_it.py. Times are simulated seconds.</text>

    <g fill="none" stroke="currentColor" stroke-width="1.6" opacity="0.75">
      <path d="M96 112 L96 126" marker-end="url(#l15-a1)"/>
      <path d="M96 180 L96 194" marker-end="url(#l15-a1)"/>
      <path d="M96 248 L96 262" marker-end="url(#l15-a1)"/>
      <path d="M96 316 L96 330" marker-end="url(#l15-a1)"/>
      <path d="M96 384 L96 398" marker-end="url(#l15-a1)"/>
      <path d="M96 452 L96 466" marker-end="url(#l15-a1)"/>
      <path d="M96 520 L96 534" marker-end="url(#l15-a1)"/>
    </g>

    <g stroke-width="1.9" stroke-linejoin="round">
      <rect x="30" y="58" width="600" height="54" rx="9" fill="#3553ff" fill-opacity="0.12" stroke="#3553ff"/>
      <rect x="30" y="126" width="600" height="54" rx="9" fill="#7c5cff" fill-opacity="0.13" stroke="#7c5cff"/>
      <rect x="30" y="194" width="600" height="54" rx="9" fill="#7c5cff" fill-opacity="0.13" stroke="#7c5cff"/>
      <rect x="30" y="262" width="600" height="54" rx="9" fill="#7c5cff" fill-opacity="0.13" stroke="#7c5cff"/>
      <rect x="30" y="330" width="600" height="54" rx="9" fill="#7c5cff" fill-opacity="0.13" stroke="#7c5cff"/>
      <rect x="30" y="398" width="600" height="54" rx="9" fill="#7c5cff" fill-opacity="0.13" stroke="#7c5cff"/>
      <rect x="30" y="466" width="600" height="54" rx="9" fill="#7f7f7f" fill-opacity="0.11" stroke="#7f7f7f"/>
      <rect x="30" y="534" width="600" height="54" rx="9" fill="#3553ff" fill-opacity="0.12" stroke="#3553ff"/>
    </g>

    <g fill="currentColor">
      <text x="44" y="80" font-size="11.5" font-weight="700">COMMIT &#8195; the source tree</text>
      <text x="44" y="98" font-size="9" opacity="0.9">7 files, one lockfile, one line of app/checkout.py about to change</text>
      <text x="44" y="148" font-size="11.5" font-weight="700">BUILD &#8195; content-addressed layers</text>
      <text x="44" y="166" font-size="9" opacity="0.9">one-line edit: 0.8 s dependency-ordered vs 394.2 s under COPY . .</text>
      <text x="44" y="216" font-size="11.5" font-weight="700">REGISTRY &#8195; digest, signature, provenance</text>
      <text x="44" y="234" font-size="9" opacity="0.9">admission: 1 of 5 candidate references admitted; 2 were mutable tags</text>
      <text x="44" y="284" font-size="11.5" font-weight="700">RELEASE &#8195; release = build + config</text>
      <text x="44" y="302" font-size="9" opacity="0.9">1 artifact digest, 3 configs, 3 release ids — a config edit IS a release</text>
      <text x="44" y="352" font-size="11.5" font-weight="700">INFRASTRUCTURE &#8195; declared, planned, applied</text>
      <text x="44" y="370" font-size="9" opacity="0.9">the plan replaced 3 of 4 resources; prevent_destroy refused the apply</text>
      <text x="44" y="420" font-size="11.5" font-weight="700">ORCHESTRATOR &#8195; a level-triggered loop</text>
      <text x="44" y="438" font-size="9" opacity="0.9">converged to 6 ready at t=26 s; reverted a hand-scaled 7th in 1 tick</text>
      <text x="44" y="488" font-size="11.5" font-weight="700">ROUTER &#8195; discovery, health, draining</text>
      <text x="44" y="506" font-size="9" opacity="0.9">480 requests severed: the 5 s drain is shorter than the client's pool</text>
      <text x="44" y="556" font-size="11.5" font-weight="700">USERS &#8195; 250 requests per second</text>
      <text x="44" y="574" font-size="9" opacity="0.9">the only place any of the numbers above is felt</text>
    </g>

    <g font-size="9.5" font-weight="700" text-anchor="end">
      <text x="618" y="80" fill="#3553ff">L 3</text>
      <text x="618" y="148" fill="#7c5cff">L 3</text>
      <text x="618" y="216" fill="#7c5cff">L 4</text>
      <text x="618" y="284" fill="#7c5cff">L 5 · 10</text>
      <text x="618" y="352" fill="#7c5cff">L 6</text>
      <text x="618" y="420" fill="#7c5cff">L 7</text>
      <text x="618" y="488" fill="#7f7f7f">L 8 · 9</text>
      <text x="618" y="556" fill="#3553ff">L 1 · 2</text>
    </g>

    <g font-size="9" text-anchor="end" fill="currentColor" opacity="0.75">
      <text x="618" y="96">493x</text>
      <text x="618" y="164">sha256:93514296ca7e</text>
      <text x="618" y="232">1 of 5</text>
      <text x="618" y="300">3 release ids</text>
      <text x="618" y="368">3 of 4</text>
      <text x="618" y="436">26 s</text>
      <text x="618" y="504" fill="#d64545" font-weight="700">480 severed</text>
      <text x="618" y="572">16.13% error rate, later</text>
    </g>

    <rect x="662" y="262" width="288" height="326" rx="11" fill="#e0930f" fill-opacity="0.10" stroke="#e0930f" stroke-width="2" stroke-dasharray="7 4"/>
    <text x="806" y="284" font-size="11" font-weight="700" text-anchor="middle" fill="#e0930f">THE CHANGE MOVING THROUGH</text>
    <text x="806" y="298" font-size="8.5" text-anchor="middle" fill="currentColor" opacity="0.85">a new column AND a new code path</text>

    <g fill="none" stroke="#e0930f" stroke-width="1.5" stroke-dasharray="4 3">
      <path d="M660 352 L636 352" marker-end="url(#l15-a2)"/>
      <path d="M660 420 L636 420" marker-end="url(#l15-a2)"/>
      <path d="M660 488 L636 488" marker-end="url(#l15-a2)"/>
      <path d="M660 556 L636 556" marker-end="url(#l15-a2)"/>
    </g>

    <g stroke-width="1.7" stroke-linejoin="round">
      <rect x="676" y="310" width="260" height="44" rx="7" fill="#0fa07f" fill-opacity="0.12" stroke="#0fa07f"/>
      <rect x="676" y="360" width="260" height="44" rx="7" fill="#0fa07f" fill-opacity="0.12" stroke="#0fa07f"/>
      <rect x="676" y="410" width="260" height="44" rx="7" fill="#0fa07f" fill-opacity="0.12" stroke="#0fa07f"/>
      <rect x="676" y="460" width="260" height="44" rx="7" fill="#0fa07f" fill-opacity="0.12" stroke="#0fa07f"/>
      <rect x="676" y="510" width="260" height="64" rx="7" fill="#d64545" fill-opacity="0.11" stroke="#d64545"/>
    </g>
    <g fill="currentColor">
      <text x="688" y="328" font-size="10" font-weight="700">L11 &#8195; rolling, then canary</text>
      <text x="688" y="344" font-size="8.5" opacity="0.9">promoted on 302 new-path samples</text>
      <text x="688" y="378" font-size="10" font-weight="700">L12 &#8195; deploy, then release</text>
      <text x="688" y="394" font-size="8.5" opacity="0.9">17,250 requests served, dark</text>
      <text x="688" y="428" font-size="10" font-weight="700">L13 &#8195; expand / migrate / contract</text>
      <text x="688" y="444" font-size="8.5" opacity="0.9">0 errors; the one-step version: 48,983</text>
      <text x="688" y="478" font-size="10" font-weight="700">L14 &#8195; the reachable set</text>
      <text x="688" y="494" font-size="8.5" opacity="0.9">computed BEFORE the contract shipped</text>
      <text x="688" y="530" font-size="10" font-weight="700" fill="#d64545">L15 &#8195; the interaction failures</text>
      <text x="688" y="546" font-size="8.5" opacity="0.95">no single stage above can show them.</text>
      <text x="688" y="560" font-size="8.5" opacity="0.95">Each one lives in a JOIN between two</text>
      <text x="688" y="570" font-size="8.5" opacity="0.95">stages owned by two different teams.</text>
    </g>

    <text x="490" y="616" font-size="11" text-anchor="middle" fill="currentColor" opacity="0.9">Every stage worked. The three failures in this capstone are all in the seams: drain vs pool, canary vs flag, contract vs kill switch.</text>
    <text x="490" y="634" font-size="11" text-anchor="middle" fill="currentColor" opacity="0.9">11 of 12 guards held. The one that did not was a number two teams each set correctly and nobody compared.</text>
  </g>
</svg>
```

Point at any box in that picture and you can name the lesson that built it. That is the deliverable of the phase. What the picture cannot show — and what this lesson is for — is that **none of the three real failures in this capstone lives inside a box.** They live in the arrows.

The drain window is correct and the client's connection pool outlives it, so a rollout that "drops zero requests" severs **480**. The canary is correct and the flag it is supposed to be testing is off for almost everyone it watches, so it reports a clean result for a code path it executed **250 times out of 24,600**. The contract step is correct and it runs nine minutes before an incident, so the kill switch is still in the console and no longer connected to anything.

Each of those is a fact about two stages, held by two teams, agreeing separately and disagreeing jointly. You have spent fourteen lessons learning the stages. This one is about learning to look at the joins.

## The Concept

### A release is three things, and they roll back separately

Lesson 5 gave the identity `release = build + config`. Lesson 13 added the third term. The whole phase reduces to this: a release is an **artifact**, a **configuration**, and a **schema**, and they have different speeds, different owners, and different failure modes.

The build measures the identity directly. One artifact digest, three configurations, three distinct release ids:

```console
  release = build + config   (one artifact, three releases)
    staging       config 432d9fb23b  ->  rel-046274f1f5ab
    production    config 5acb8cb10c  ->  rel-a2f561ea7b1d
    production+1  config 59ff1cf2e6  ->  rel-faecf6a08fbc
```

The last two share the same bytes and differ by one key — a connection-pool size going from 8 to 24. **That is a deploy.** It has a release id, it needs a version, it belongs on the deploy-annotation line of your dashboard, and it can cause an incident on its own. The sentence "we didn't deploy anything" is one of the most expensive sentences in operations, and it is usually said by someone who is telling the truth about the artifact.

### The guard that makes a rollout safe is the same guard that makes an outage unbounded

This is the first integration result and it is the one that surprises people most.

A readiness probe exists so that traffic is never sent to an instance that cannot serve it. A rolling update with `maxUnavailable: 1` exists so that the fleet never drops below capacity. Both are correct. Put them together and you get a property nobody chose:

> **If a new instance never becomes ready, the rollout does not fail. It waits — and it waits with half the fleet on the old version, for as long as it takes.**

Lesson 13 established that the overlap window during a rolling deploy is *unbounded* and told you to design for that. Lesson 7 established that a level-triggered control loop re-derives its work from state every tick and never gives up, which is exactly what makes it robust. The capstone puts a schema change in the middle of the two, and the result is that a half-migrated fleet stays alive indefinitely by design. Kubernetes has `progressDeadlineSeconds` (default 600) for this, and it is worth knowing precisely what it does: after the deadline the Deployment's condition flips to `ProgressDeadlineExceeded`. **It reports. It does not roll back.** In the measured run, that costs **48,983 5xx and 32,259 silent bad reads** before a human is involved.

### A canary measures whatever it can reach, and says nothing about the rest

The second integration result. Lesson 11 built the instance canary: put the new artifact on one instance, compare its error rate and latency to the baseline, promote or abort. Lesson 12 built the flag ramp: keep the artifact everywhere and move *exposure*. Both are correct, and they answer different questions — **the artifact canary asks "is this build healthy?", the flag ramp asks "is this behaviour healthy?"**

Run an artifact canary on a change whose new path is gated by a flag that is at 1%, and the canary answers its own question honestly and gives you a completely misleading result for the question you actually asked. In the measured run the canary instance served **24,600 requests over 600 seconds with zero errors and flat latency**, and **250 of them — 1.02% — executed the code being tested**. It promoted. It was right, about the artifact.

The fix is a single line of arithmetic in the analysis, and it is the most valuable line in this lesson: **count the requests that executed the new path, not the requests that arrived.** The correct run refuses to promote until it has observed 300 new-path samples; it gets there in 198 seconds and aborts on a 2.98% divergence it would otherwise never have seen.

### A kill switch is a code path, and a code path needs its data

The third integration result, and the one with the largest measured consequence.

Lesson 12 taught that mitigation should be an exposure change: flip the flag, exposure drops to zero, users stop being hurt in seconds. Lesson 13 taught expand/migrate/contract, in which **contract** — dropping the old column — is the final tidy-up. Lesson 14 taught that contract is irreversible and that you should compute the reachable rollback set before you deploy.

Put them together and a constraint falls out that no single lesson states:

> **A kill switch and a contracted schema are mutually exclusive. The flag-off path reads the old shape. Drop the old shape and the switch still exists, still flips, and no longer works.**

So the soak window between "exposure is at 100%" and "we dropped the old column" is not administrative slack. **It is the entire period during which you have a fast mitigation.** Contract closes it deliberately, and closing it should be a decision somebody makes out loud, in a pull request, with the sentence "after this merges, the fastest mitigation for this feature is a 14-minute roll-forward" written down.

### Reachability, computed rather than assumed

The word every runbook leans on is *reachable*, and almost nobody computes it. It is a static question — for each candidate mitigation, does everything that mitigation's code reads still exist? — and the build answers it in a set comparison:

```python
old_path_present = "shipping_fee" in columns          # is the kill switch wired to anything?
rollback_ok = prev_build_reads <= columns             # can the previous artifact run at all?
```

Two subset checks. That is the whole of it, and running them in CI against your migration history and each build's declared column set would have made both of the expensive scenes in Lesson 14 impossible. Nothing in a deployment pipeline does this for you. **Your pipeline knows how to put the previous image back. It has no idea that the previous image cannot run.**

## Build It

[`code/ship_it.py`](code/ship_it.py) is one file, standard library only, seeded with `random.Random(7)`, and it runs the whole pipeline in six acts in well under a second of wall time. **Time inside it is simulated in whole seconds** — every `s` in the output below is a simulated second, so a 909-second stall is a real 909 seconds of modelled user pain and not a number the script waited out.

```bash
docker compose exec -T app python \
  phases/10-infrastructure-and-deployment/15-capstone-ship-a-service/code/ship_it.py
```

Two things are modelled rather than executed, and it is worth being explicit about both. The image build models layer costs from a table of modelled seconds rather than actually running `pip install`, because the point is the **cache chain**, not the installer. And the mitigation timings are modelled from their component stages — an operator's decision, a control-plane write, a streaming push, a cache TTL — rather than measured against a real flag vendor. Everything else, including every error count, is the outcome of running requests through a simulated fleet one simulated second at a time.

### Act 1 — build once, pin the result

```console
== 1 · BUILD & PIN  (lessons 3, 4, 5, 10) ==
  cold build, dependency-ordered:   6/6 layers built,  468.2 s
  one-line edit to app/checkout.py: 2/6 layers built,    0.8 s
  the same edit, COPY . . on top:   2/4 layers built,  394.2 s
  layer ordering alone: 0.8 s vs 394.2 s for the identical change (493x)
  determinism, same source built twice on two machines:
    as people write it   83918a55e32e  f28d342b466e  identical=False
    normalised           93514296ca7e  93514296ca7e  identical=True
  artifact digest      sha256:93514296ca7ec82dce52133e3c52c0b940aef4f8091b9e63eaea457373d61f0c
  signature            15942df40e3d6061...  verifies=True
  provenance           builder=ci-runner-prod commit=9f31c0a7b4de materials=7
  admission control at the cluster door:
    DENY   checkout:latest                  not pinned by digest
    DENY   checkout:4.2.0                   not pinned by digest
    DENY   checkout@93514296 (key rotated)  no valid signature
    DENY   checkout@93514296 (laptop)       no provenance from a trusted builder
    ADMIT  checkout@93514296
  1 of 5 candidate references admitted
```

Three results, none of them new, all of them load-bearing for what follows.

**The cache chain.** `0.8 s` versus `394.2 s` for the identical one-line source edit — **493×** — and the only difference is whether `COPY . .` sits above `pip install`. The mechanism is that a layer's cache key includes its parent's key, so a miss invalidates everything below it. The second column is the one to read: the good ordering rebuilt **2 of 6** layers and the bad ordering rebuilt **2 of 4**, which sounds similar and is not, because one of the bad ordering's two is the 393-second install.

**Determinism.** The same seven source files, built on two machines with different clocks and different `readdir()` ordering, produce two different digests as most people write a build and **one** digest once mtimes are fixed and entries are sorted. This matters here for a reason beyond reproducibility: **the digest is the identifier every later stage keys on.** If your build is non-deterministic, "the same artifact" is a phrase without a referent, and build-once-promote-many degenerates into build-four-times-and-hope.

**Admission.** Four of five references are refused at the door, and the two most interesting refusals are the pinned ones. A rotated signing key and a laptop build both carry the correct digest — the bytes are right — and are still denied, because pinning answers *which* bytes and says nothing about *whose*. Note also that `checkout:4.2.0` is denied. A version tag feels immutable and is not; it is a pointer, and anyone with push access can move it.

Then the identity that the incident in act 5 depends on:

```console
  release = build + config   (one artifact, three releases)
    staging       config 432d9fb23b  ->  rel-046274f1f5ab
    production    config 5acb8cb10c  ->  rel-a2f561ea7b1d
    production+1  config 59ff1cf2e6  ->  rel-faecf6a08fbc
```

### Act 2 — declare it, then let a loop hold it

```console
== 2 · DECLARE & CONVERGE  (lessons 6, 7) ==
  plan (as submitted):
    replace  database.orders      forced by engine
    replace  dns.public           service.checkout.id is (known after apply)
    replace  service.checkout     database.orders.id is (known after apply)
  Plan: 3 to add, 0 to change, 3 to destroy
  APPLY REFUSED: prevent_destroy on database.orders
    one edited attribute — a minor-version bump — was IMMUTABLE, so the
    verb is 'replace', not 'update': the 100 GB production database is
    destroyed and recreated empty. Its new id is (known after apply),
    which is a CHANGED value for everything downstream, so 3 of 4
    resources are replaced by one line nobody thought was risky.
```

One edited attribute, **3 of 4 resources replaced**. The cascade is the part worth re-reading: a replaced resource's identifier becomes `(known after apply)`, which is a *changed* value for anything that references it, which forces the dependant to be replaced too, transitively, until the chain hits an attribute that can be updated in place. The plan headline reads `3 to add, 0 to change, 3 to destroy` — and a replace is counted once in each column, so the scariest plan in your history may well have a `0 to change` in the middle of it.

`prevent_destroy` is one line on one resource and it stopped the whole apply. This is the cheapest guard in the entire phase.

```console
  control loop, level-triggered, reconciling to 6 ready:
    t=  0s  desired=6  running=0  ready=0  pending=6
    t=  1s  desired=6  running=1  ready=0  pending=5
    t=  2s  desired=6  running=3  ready=0  pending=3
    t=  3s  desired=6  running=6  ready=0  pending=0
    t= 24s  desired=6  running=6  ready=1  pending=0
    t= 26s  desired=6  running=6  ready=6  pending=0
    CONVERGED at t=26s.
  drift: someone scaled to 7 by hand at 02:40.
    level-triggered loop re-derived the diff from STATE, not from an event,
    and removed the extra instance in 1 tick.
```

Note the shape of the convergence: **running hits 6 at t=3 s and ready hits 6 at t=26 s.** Those twenty-three seconds are the readiness gap, and it is the single most under-modelled quantity in deployment planning. Every rolling batch pays it. It is also, in act 4, the interval during which an instance that will *never* pass readiness looks exactly like an instance that is about to.

The drift correction is one tick because the loop compares desired state to observed state and does not care how the discrepancy arose. An edge-triggered reconciler that missed the create event would never learn that a seventh instance exists.

### Act 3 — the drain window belongs to somebody else

Draining is the well-understood part of removing an instance: stop sending it new traffic, wait for its in-flight requests to finish, then stop the process. Our server finishes its in-flight work in 400 ms, so a **5-second** grace period is generous. Every instance is replaced once, with 120 pooled clients sending 2 requests a second each.

```console
== 3 · ROUTE  (lessons 8, 9) ==
  client pool setting            drain  failed  severed
  no max connection lifetime        5s     480      120
  max lifetime 30s  (> drain)       5s     480      120
  max lifetime  3s  (< drain)       5s       0        0
  Connection: close at drain        5s       0        0

  bounding the connection lifetime at 30s changed nothing: 480 -> 480.
  the bound has to be SHORTER than the drain window to matter: 0 at 3s.
```

**480 failed requests on a rollout that drops zero requests**, and the second row is the punchline. Bounding the client's connection lifetime is the standard advice — Lesson 8 measured a blackhole window that never closes without it — and here, set to a perfectly sensible 30 seconds, it changes the number **not at all**.

The reason is arithmetic that nobody performs. A pooled connection is pinned to an instance's address; the router's decision to stop sending *new* connections there does not touch the ones already open. So the instance exits at drain + 5 s with 20 live connections still attached, and those connections break. Whether the client would have recycled them at 30 seconds is irrelevant, because 30 > 5.

> **The drain window must exceed the client's maximum connection lifetime, not the server's in-flight time. It is a property of a config file in a different repository, owned by a different team.**

Two fixes work and they are not equivalent. Shortening the client's lifetime below the drain window (3 s here) gets you to zero, and requires every caller to cooperate. Sending `Connection: close` — or an HTTP/2 `GOAWAY` — at the start of the drain also gets you to zero, and requires only the server, which is why it is the one to reach for. You cannot deploy a change to your callers' connection pools; you can deploy a change to your own shutdown handler.

### Act 4 — one change, landed three ways

The change is the realistic kind: it needs **both** a schema migration and a new code path. `orders.shipping_fee` becomes `orders.shipping_cents`, computed by a new quoting engine. The engine has a bug — it is wrong for the **3.40%** of users in the legacy-north shipping zone — and the bug does not raise. It returns a plausible number, with an HTTP 200, which the application then writes to the ledger.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 980 618" width="100%" style="max-width:940px" role="img" aria-label="Three panels showing the same change — one new column and one new code path — landed three ways. The left panel stages it as expand, deploy dark, canary at one percent, abort, fix, ramp and soak, costing zero 5xx, zero bad reads and nine mispriced orders, detected in 198 seconds. The middle panel runs the migration and the deploy as one release; a readiness probe never passes, the rollout stalls for 600 seconds against the progress deadline and then 240 more while a human diagnoses it, costing 48,983 5xx and 32,259 silent bad reads over 909 seconds, with rollback impossible because the old column was dropped. The right panel expands correctly but canaries one instance instead of the flag cohort, so only 250 of 24,600 canary requests ever executed the new path; it promotes to 100 percent and produces zero errors and 57,614 mispriced orders, found by the finance job 7,200 seconds later.">
  <defs>
  </defs>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <text x="490" y="24" text-anchor="middle" font-size="14.5" font-weight="700" fill="currentColor">The same change, landed three ways — and two of them report zero errors</text>
    <text x="490" y="42" text-anchor="middle" font-size="10" fill="currentColor" opacity="0.85">orders.shipping_fee &#8594; orders.shipping_cents, plus a new quote engine that is wrong for 3.40% of users</text>

    <g stroke-width="2" stroke-linejoin="round">
      <rect x="20" y="56" width="300" height="510" rx="12" fill="#0fa07f" fill-opacity="0.08" stroke="#0fa07f"/>
      <rect x="340" y="56" width="300" height="510" rx="12" fill="#d64545" fill-opacity="0.08" stroke="#d64545"/>
      <rect x="660" y="56" width="300" height="510" rx="12" fill="#e0930f" fill-opacity="0.08" stroke="#e0930f"/>
    </g>
    <text x="170" y="78" font-size="12" font-weight="700" text-anchor="middle" fill="#0fa07f">RUN 1 &#8195; staged</text>
    <text x="490" y="78" font-size="12" font-weight="700" text-anchor="middle" fill="#d64545">RUN 2 &#8195; one migration, one deploy</text>
    <text x="810" y="78" font-size="12" font-weight="700" text-anchor="middle" fill="#e0930f">RUN 3 &#8195; canary that measured nothing</text>

    <g stroke-width="1.5" stroke-linejoin="round">
      <rect x="34" y="90" width="272" height="26" rx="6" fill="#0fa07f" fill-opacity="0.14" stroke="#0fa07f"/>
      <rect x="34" y="122" width="272" height="26" rx="6" fill="#0fa07f" fill-opacity="0.14" stroke="#0fa07f"/>
      <rect x="34" y="154" width="272" height="38" rx="6" fill="#0fa07f" fill-opacity="0.14" stroke="#0fa07f"/>
      <rect x="34" y="198" width="272" height="38" rx="6" fill="#e0930f" fill-opacity="0.16" stroke="#e0930f"/>
      <rect x="34" y="242" width="272" height="26" rx="6" fill="#0fa07f" fill-opacity="0.14" stroke="#0fa07f"/>
      <rect x="34" y="274" width="272" height="38" rx="6" fill="#0fa07f" fill-opacity="0.14" stroke="#0fa07f"/>
      <rect x="34" y="318" width="272" height="38" rx="6" fill="#0fa07f" fill-opacity="0.14" stroke="#0fa07f"/>

      <rect x="354" y="90" width="272" height="38" rx="6" fill="#d64545" fill-opacity="0.15" stroke="#d64545"/>
      <rect x="354" y="134" width="272" height="38" rx="6" fill="#d64545" fill-opacity="0.15" stroke="#d64545"/>
      <rect x="354" y="178" width="272" height="50" rx="6" fill="#d64545" fill-opacity="0.15" stroke="#d64545"/>
      <rect x="354" y="234" width="272" height="38" rx="6" fill="#d64545" fill-opacity="0.15" stroke="#d64545"/>
      <rect x="354" y="278" width="272" height="38" rx="6" fill="#7f7f7f" fill-opacity="0.12" stroke="#7f7f7f"/>
      <rect x="354" y="324" width="272" height="32" rx="6" fill="#d64545" fill-opacity="0.15" stroke="#d64545"/>

      <rect x="674" y="90" width="272" height="26" rx="6" fill="#0fa07f" fill-opacity="0.14" stroke="#0fa07f"/>
      <rect x="674" y="122" width="272" height="26" rx="6" fill="#0fa07f" fill-opacity="0.14" stroke="#0fa07f"/>
      <rect x="674" y="154" width="272" height="62" rx="6" fill="#e0930f" fill-opacity="0.16" stroke="#e0930f"/>
      <rect x="674" y="222" width="272" height="38" rx="6" fill="#d64545" fill-opacity="0.15" stroke="#d64545"/>
      <rect x="674" y="266" width="272" height="46" rx="6" fill="#d64545" fill-opacity="0.15" stroke="#d64545"/>
      <rect x="674" y="318" width="272" height="38" rx="6" fill="#7f7f7f" fill-opacity="0.12" stroke="#7f7f7f"/>
    </g>

    <g fill="currentColor">
      <text x="44" y="107" font-size="9">1 &#183; EXPAND: ADD COLUMN, nullable</text>
      <text x="44" y="139" font-size="9">2 &#183; DEPLOY v2 dual-writing, flag OFF</text>
      <text x="44" y="171" font-size="9">3 &#183; BACKFILL 574 rows, 6 batches</text>
      <text x="44" y="185" font-size="8" opacity="0.8">keyset pagination, commit per batch</text>
      <text x="44" y="215" font-size="9" font-weight="700" fill="#e0930f">4 &#183; CANARY at 1% &#8594; ABORT</text>
      <text x="44" y="229" font-size="8" opacity="0.9">302 new-path samples, 9 diverged (2.98%)</text>
      <text x="44" y="259" font-size="9">5 &#183; fix ships as a new artifact</text>
      <text x="44" y="291" font-size="9">6 &#183; RAMP 1% &#8594; 5% &#8594; 25% &#8594; 100%</text>
      <text x="44" y="305" font-size="8" opacity="0.8">60 s of analysis at every step</text>
      <text x="44" y="335" font-size="9">7 &#183; SOAK, old column still present</text>
      <text x="44" y="349" font-size="8" opacity="0.8">contract is a separate, later decision</text>

      <text x="364" y="107" font-size="9">1 &#183; ADD shipping_cents AND DROP</text>
      <text x="364" y="121" font-size="9">&#8195; shipping_fee, in one migration</text>
      <text x="364" y="151" font-size="9">2 &#183; deploy v3 in the same release</text>
      <text x="364" y="165" font-size="8" opacity="0.85">every v1 instance is now broken</text>
      <text x="364" y="195" font-size="9" font-weight="700">3 &#183; instance 5 never passes readiness</text>
      <text x="364" y="209" font-size="8" opacity="0.9">fail-fast on a config key only staging had.</text>
      <text x="364" y="221" font-size="8" opacity="0.9">maxUnavailable=1 &#8594; the rollout WAITS.</text>
      <text x="364" y="251" font-size="9">4 &#183; 600 s to progressDeadlineExceeded</text>
      <text x="364" y="265" font-size="8" opacity="0.85">which reports. It does not roll back.</text>
      <text x="364" y="295" font-size="9">5 &#183; 240 s for a human to find the key</text>
      <text x="364" y="309" font-size="8" opacity="0.85">on a Saturday, from a green dashboard</text>
      <text x="364" y="344" font-size="9" font-weight="700" fill="#d64545">6 &#183; roll back? shipping_fee is GONE.</text>

      <text x="684" y="107" font-size="9">1 &#183; EXPAND: ADD COLUMN &#8212; correct</text>
      <text x="684" y="139" font-size="9">2 &#183; DEPLOY v2 dual-writing, flag 1%</text>
      <text x="684" y="171" font-size="9" font-weight="700" fill="#e0930f">3 &#183; CANARY 1 INSTANCE for 600 s</text>
      <text x="684" y="185" font-size="8" opacity="0.9">24,600 requests, 0 errors, latency flat.</text>
      <text x="684" y="197" font-size="8" opacity="0.9">Requests that ran the NEW PATH: 250.</text>
      <text x="684" y="209" font-size="8" font-weight="700" fill="#e0930f">1.02% of what it watched. PROMOTE.</text>
      <text x="684" y="239" font-size="9">4 &#183; exposure &#8594; 100%</text>
      <text x="684" y="253" font-size="8" opacity="0.85">0 errors. Flat latency. Nothing alerts.</text>
      <text x="684" y="283" font-size="9" font-weight="700" fill="#d64545">5 &#183; every legacy-north order is wrong</text>
      <text x="684" y="297" font-size="8" opacity="0.9">HTTP 200, a plausible number, persisted</text>
      <text x="684" y="308" font-size="8" opacity="0.9">into the ledger and the warehouse export</text>
      <text x="684" y="335" font-size="9">6 &#183; the finance job, next morning</text>
      <text x="684" y="349" font-size="8" opacity="0.85">7,200 s after exposure went to 100%</text>
    </g>

    <g fill="none" stroke="currentColor" stroke-width="1.2" opacity="0.35">
      <path d="M34 372 L306 372"/><path d="M354 372 L626 372"/><path d="M674 372 L946 372"/>
    </g>

    <g font-size="9" fill="currentColor" opacity="0.7">
      <text x="44" y="390">user-facing 5xx</text><text x="44" y="418">silent bad reads</text>
      <text x="44" y="446">mispriced orders</text><text x="44" y="474">time to detect</text>
      <text x="364" y="390">user-facing 5xx</text><text x="364" y="418">silent bad reads</text>
      <text x="364" y="446">mispriced orders</text><text x="364" y="474">time to mitigate</text>
      <text x="684" y="390">user-facing 5xx</text><text x="684" y="418">silent bad reads</text>
      <text x="684" y="446">mispriced orders</text><text x="684" y="474">time to detect</text>
    </g>
    <g font-size="15" font-weight="700" text-anchor="end">
      <text x="306" y="392" fill="#0fa07f">0</text><text x="306" y="420" fill="#0fa07f">0</text>
      <text x="306" y="448" fill="#0fa07f">9</text><text x="306" y="476" fill="#0fa07f">198 s</text>
      <text x="626" y="392" fill="#d64545">48,983</text><text x="626" y="420" fill="#d64545">32,259</text>
      <text x="626" y="448" fill="#7f7f7f">0</text><text x="626" y="476" fill="#d64545">909 s</text>
      <text x="946" y="392" fill="#0fa07f">0</text><text x="946" y="420" fill="#0fa07f">0</text>
      <text x="946" y="448" fill="#d64545">57,614</text><text x="946" y="476" fill="#d64545">7,200 s</text>
    </g>

    <g stroke-width="1.7" stroke-linejoin="round">
      <rect x="34" y="492" width="272" height="60" rx="7" fill="#0fa07f" fill-opacity="0.13" stroke="#0fa07f"/>
      <rect x="354" y="492" width="272" height="60" rx="7" fill="#d64545" fill-opacity="0.13" stroke="#d64545"/>
      <rect x="674" y="492" width="272" height="60" rx="7" fill="#d64545" fill-opacity="0.13" stroke="#d64545"/>
    </g>
    <g fill="currentColor" font-size="8.5">
      <text x="44" y="509" font-weight="700" fill="#0fa07f">The canary counted the right thing.</text>
      <text x="44" y="523">It refused to promote until it had seen 300</text>
      <text x="44" y="535">requests that actually executed the new path,</text>
      <text x="44" y="547">not 300 requests that merely could have.</text>
      <text x="364" y="509" font-weight="700" fill="#d64545">The orchestrator did not fail. It waited.</text>
      <text x="364" y="523">A level-triggered loop holds a half-migrated</text>
      <text x="364" y="535">fleet alive indefinitely and calls it</text>
      <text x="364" y="547">'progressing'. There is no timeout on wrong.</text>
      <text x="684" y="509" font-weight="700" fill="#d64545">An artifact canary cannot test a behaviour</text>
      <text x="684" y="523">that a flag has turned off. One asks 'is this</text>
      <text x="684" y="535">BUILD healthy'; the other asks 'is this</text>
      <text x="684" y="547">BEHAVIOUR healthy'. Only one was running.</text>
    </g>

    <text x="490" y="586" font-size="11" text-anchor="middle" fill="currentColor" opacity="0.9">Runs 1 and 3 both report a 0.00% error rate. One of them charged 57,614 customers the wrong shipping total.</text>
    <text x="490" y="604" font-size="11" text-anchor="middle" fill="currentColor" opacity="0.9">An error rate measures the requests that failed. It is silent about every request that succeeded and was wrong.</text>
  </g>
</svg>
```

**Run 1 — staged.**

```console
  --- RUN 1: expand -> deploy dark -> canary -> ramp -> soak ---
  t=   2s  EXPAND: ADD COLUMN shipping_cents (nullable), lock_timeout=50ms
  t=  71s  DEPLOY v2 everywhere, dual-writing, flag at 0% — nobody can reach it
  t=  77s  BACKFILL 574 legacy rows in 6 bounded batches (keyset, not OFFSET)
  t= 198s  CANARY at 1%: 302 new-path requests observed, 9 disagreed with the
          old path's quote (2.98%). Threshold 0.50% -> ABORT, exposure -> 0%.
  t=1105s  fix shipped as a new artifact, re-ramped from 1%
  t=1165s  exposure   1.0% — analysis green, promote
  t=1225s  exposure   5.0% — analysis green, promote
  t=1285s  exposure  25.0% — analysis green, promote
  t=1345s  exposure 100.0% — analysis green, promote
  t=3145s  soak at 100% for 1800 s with the old column still present
  cost: 0 5xx, 0 silent bad reads, 9 mispriced orders
```

Read the shape rather than the total. The migration and the deploy are **separate events** — `t=2s` and `t=71s` — and the deploy is dark: **17,250 requests are served by the new artifact before any user can reach the new path.** That separation is what makes the canary meaningful, because it means "the artifact is healthy" and "the behaviour is healthy" are two questions that can be asked at two different times.

The canary aborts at `t=198s` on **302 new-path samples with 9 divergences, 2.98% against a 0.50% threshold**. Nine mispriced orders is the entire cost of the bug in this run. That is not luck; it is the sample-count gate. And note that the analysis compares the new path's answer against the old path's answer for the same order — an *outcome* comparison, not an error-rate comparison — because the bug produces no errors at all. **A canary that only watches error rate and latency is blind to exactly the class of bug that lives in this lesson.**

**Run 2 — "it's one migration and one deploy."**

```console
  t=   0s  one migration: ADD shipping_cents, DROP shipping_fee
  t=  46s  4 of 6 on v3. Instance 5 never passes readiness: the new build
          fail-fasts on a missing QUOTE_API_KEY that only staging ever had.
          maxUnavailable=1, so the rollout will NOT take down instance 6.
  t= 646s  progressDeadlineSeconds=600 elapsed. The Deployment condition flips to
          ProgressDeadlineExceeded. It does not roll back. It reports.
  t= 886s  human diagnoses the missing config key (240 s of a Saturday)
  t= 909s  key set, rollout finishes, errors stop. Rollback was never an option:
          shipping_fee is gone, so v1 cannot run at all
  cost: 48983 5xx, 32259 silent bad reads, 0 mispriced orders, TTM 909 s
```

Four things happened here and only one of them is a bug.

The migration is a rename in disguise, which Lesson 13 named as the cheapest and most dangerous operation in the recipe table. The config guard **worked**: the new build refused to start because a required key was absent, which is Lesson 5's fail-fast doing precisely its job and is enormously better than starting with a wrong default. The rolling update **worked**: `maxUnavailable: 1` protected capacity by refusing to take down another old instance until the new one was ready. The control loop **worked**: level-triggered, it kept retrying forever.

And the composition of three correct behaviours is a fleet frozen at four-of-six for as long as nobody looks, running two instances whose code references a column that no longer exists.

The damage splits the way Lesson 13 said it would. **48,983 requests raised an error on the write path** — loud, paged, self-healing the moment the rollout completes. **32,259 read-path requests returned a silent default**, because the read is `SELECT *` followed by a key lookup and a missing key is `None`, not an exception. Those do not heal. They are written into exports and downstream systems as facts.

And the last line is the one that turns an incident into a bad night: **rollback was never available.** The runbook's first instruction was unexecutable from the moment the migration ran, and nobody computed that in review.

**Run 3 — the canary that measured nothing.**

```console
  t=   2s  EXPAND: ADD COLUMN shipping_cents — correct, additive
  t=  71s  DEPLOY v2 everywhere, dual-writing, flag quote_engine_v2 at 1%
  t= 671s  instance canary (1 of 6) watched for 600 s:
          24600 requests, 0 errors, latency flat vs the other five. PROMOTE.
          requests that executed the NEW PATH: 250 of 24600 (1.02%).
  t=7871s  exposure -> 100%. Nothing alerts: 0 errors, flat latency.
  t=7871s  the nightly finance reconciliation flags the first bad shipping totals.
  cost: 0 5xx, 0 silent bad reads, 57614 mispriced orders, TTD 7200 s
```

The schema work in run 3 is **correct** — additive expand, dual-write, no rename. The deploy is correct. The flag exists and is sticky-bucketed. What is wrong is one sentence in a runbook: *"canary the deploy for ten minutes, then ramp."*

The canary instance is chosen by the router, so it serves whoever the load balancer sends it — roughly a sixth of everyone. The flag cohort is chosen by a hash of the user id, so it is 1% of everyone. Those two populations intersect in **250 requests out of 24,600**, and the canary's verdict — zero errors, flat latency, promote — is an accurate statement about 250 requests and a meaningless one about the change.

`57,614` mispriced orders, and a time-to-detect of **7,200 seconds** because the only thing that can find a wrong-but-successful request is a reconciliation job, not a dashboard.

```console
  run                              5xx  bad reads  mispriced  detected in  by
  1 expand/dark/canary/ramp          0          0          9        198 s  canary, 302 new-path samples
  2 migration+deploy together    48983      32259          0        909 s  a human, on a Saturday
  3 instance canary of a flag        0          0      57614       7200 s  the finance job, next day
  runs 1 and 3 both report ZERO user-facing errors. One of them charged
  57614 customers the wrong shipping total and nothing on any dashboard moved.
```

That table is the lesson. Sort it by error rate and run 3 ties for first place. Sort it by damage and run 3 is worst. **An error rate measures the requests that failed. It says nothing about the requests that succeeded and were wrong**, and every mechanism in this phase that people rely on for safety — the canary, the alert, the SLO burn rate — is built on the first kind.

### Act 5 — the incident, and which doors are still open

Two hours after the ramp finishes, organic traffic grows from 250 to 310 requests a second. The new quoting path calls a partner's quote API once per request, and the partner's quota is 260 a second.

```console
== 5 · THE INCIDENT  (lessons 12, 14) ==
  two hours after the ramp finished, traffic grows 250 -> 310 req/s.
  the new path calls the partner's quote API once per request. The partner's
  quota is 260/s. 50/s are now rejected: a 16.13% error rate, and it is ours.
  the highest partner rate at ANY point during the ramp was 250/s — 96% of quota.
  no exposure step could have found this. The fault is a function of ABSOLUTE
  volume; the largest volume the ramp ever produced was its own final step.
```

This is worth sitting with, because it is the honest limit of progressive delivery. A ramp measures the behaviour **at that exposure**. A fault that is a function of *fraction* — a bad code path, a wrong query, a broken serialisation — shows up at 1%. A fault that is a function of *absolute volume* — a rate limit, a connection pool, a quota, a lock, a disk — cannot show up until the volume exists, and the largest volume any ramp ever produces is its own last step. The service went to 100% at **250 req/s, 96% of a quota nobody was watching**, and nothing anywhere alerted, because a saturation alert on a resource you do not own is a thing somebody has to think to build.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 980 600" width="100%" style="max-width:940px" role="img" aria-label="The same incident in two worlds, drawn to scale on one time axis from zero to nine hundred seconds. In world A the contract has not run: the flag kill switch mitigates in 6.7 seconds costing 335 errors, a rollback takes 109 seconds and 5,450 errors, and rolling forward takes 849 seconds and 42,450 errors. In world B the old column was dropped in the same release as the hundred percent ramp, so the kill switch and the rollback are both unreachable and only rolling forward remains: 849 seconds and 42,450 errors, 127 times slower for the same incident. A magnified strip shows the 6.7 second flip as operator decision 3.0, control-plane write 0.5, streaming push 1.2 and in-process cache time to live 2.0 seconds.">
  <defs>
    <marker id="l15-c1" markerWidth="10" markerHeight="10" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker>
    <pattern id="l15-c2" width="7" height="7" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
      <line x1="0" y1="0" x2="0" y2="7" stroke="#d64545" stroke-width="2.4" stroke-opacity="0.45"/>
    </pattern>
  </defs>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <text x="490" y="24" text-anchor="middle" font-size="14.5" font-weight="700" fill="currentColor">Which doors are still open — and which one a tidy-up closed nine minutes earlier</text>
    <text x="490" y="42" text-anchor="middle" font-size="10" fill="currentColor" opacity="0.85">Traffic grew 250 &#8594; 310 req/s. The partner's quote quota is 260/s. 50 req/s now fail: a 16.13% error rate, and it is ours.</text>

    <rect x="20" y="56" width="940" height="30" rx="8" fill="#7f7f7f" fill-opacity="0.09" stroke="currentColor" stroke-opacity="0.4" stroke-width="1.4"/>
    <text x="34" y="76" font-size="9.5" fill="currentColor" opacity="0.95">The ramp could not have found this. The highest partner rate at ANY exposure step was 250/s &#8212; 96% of quota. The fault is a function of ABSOLUTE volume.</text>

    <g fill="none" stroke="currentColor" stroke-width="1.4">
      <path d="M150 512 L950 512" marker-end="url(#l15-c1)"/>
      <path d="M150 506 L150 518"/><path d="M328 506 L328 518"/><path d="M506 506 L506 518"/><path d="M684 506 L684 518"/><path d="M862 506 L862 518"/>
    </g>
    <g font-size="8.5" fill="currentColor" opacity="0.7" text-anchor="middle">
      <text x="150" y="530">0 s</text><text x="328" y="530">200 s</text><text x="506" y="530">400 s</text><text x="684" y="530">600 s</text><text x="862" y="530">800 s</text>
    </g>
    <g fill="none" stroke="currentColor" stroke-width="1" stroke-dasharray="3 5" opacity="0.22">
      <path d="M328 108 L328 430"/><path d="M506 108 L506 430"/><path d="M684 108 L684 430"/><path d="M862 108 L862 430"/>
    </g>

    <text x="20" y="122" font-size="12" font-weight="700" fill="#0fa07f">WORLD A &#8195; the soak window &#8212; CONTRACT HAS NOT RUN</text>
    <g stroke-width="1.8" stroke-linejoin="round">
      <rect x="150" y="134" width="6.1" height="30" rx="2" fill="#0fa07f" fill-opacity="0.9" stroke="#0fa07f"/>
      <rect x="150" y="176" width="99.3" height="30" rx="4" fill="#e0930f" fill-opacity="0.30" stroke="#e0930f"/>
      <rect x="150" y="218" width="773.5" height="30" rx="4" fill="#d64545" fill-opacity="0.20" stroke="#d64545"/>
    </g>
    <g fill="currentColor">
      <text x="20" y="154" font-size="9.5" font-weight="700">flag kill switch</text>
      <text x="20" y="196" font-size="9.5" font-weight="700">rollback</text>
      <text x="20" y="238" font-size="9.5" font-weight="700">roll forward</text>
      <text x="166" y="147" font-size="10" font-weight="700" fill="#0fa07f">6.7 s &#8195; 335 errors &#8195; REACHABLE</text>
      <text x="166" y="160" font-size="8.5" opacity="0.85">the flag-off path still has a column to read</text>
      <text x="258" y="189" font-size="10" font-weight="700" fill="#e0930f">109.0 s &#8195; 5,450 errors &#8195; REACHABLE</text>
      <text x="258" y="202" font-size="8.5" opacity="0.85">partial relief at 58 s &#8212; and it reverts every other change in that artifact</text>
      <text x="166" y="238" font-size="10" font-weight="700" fill="#d64545">849.0 s &#8195; 42,450 errors</text>
      <text x="600" y="238" font-size="9" opacity="0.9">decision 30 + write 240 + review 180 + CI 320 + deploy 74</text>
    </g>

    <text x="20" y="292" font-size="12" font-weight="700" fill="#d64545">WORLD B &#8195; &#8216;while we are in here&#8217; &#8212; DROP COLUMN shipped with the 100% ramp</text>
    <g stroke-width="1.8" stroke-linejoin="round">
      <rect x="150" y="304" width="6.1" height="30" rx="2" fill="url(#l15-c2)" stroke="#d64545" stroke-dasharray="4 3"/>
      <rect x="150" y="346" width="99.3" height="30" rx="4" fill="url(#l15-c2)" stroke="#d64545" stroke-dasharray="4 3"/>
      <rect x="150" y="388" width="773.5" height="30" rx="4" fill="#d64545" fill-opacity="0.20" stroke="#d64545"/>
    </g>
    <g fill="currentColor">
      <text x="20" y="324" font-size="9.5" font-weight="700">flag kill switch</text>
      <text x="20" y="366" font-size="9.5" font-weight="700">rollback</text>
      <text x="20" y="408" font-size="9.5" font-weight="700">roll forward</text>
      <text x="166" y="317" font-size="10" font-weight="700" fill="#d64545">UNREACHABLE &#8195; the flag-off path reads shipping_fee, which is DROPPED</text>
      <text x="166" y="330" font-size="8.5" opacity="0.9">the switch is still in the console. It is no longer connected to anything.</text>
      <text x="258" y="359" font-size="10" font-weight="700" fill="#d64545">UNREACHABLE &#8195; the previous build reads shipping_fee too</text>
      <text x="258" y="372" font-size="8.5" opacity="0.9">one DROP COLUMN removed both mitigations at once, from two different layers</text>
      <text x="166" y="408" font-size="10" font-weight="700" fill="#d64545">849.0 s &#8195; 42,450 errors &#8195; the only option left</text>
    </g>

    <rect x="20" y="438" width="500" height="56" rx="9" fill="#0fa07f" fill-opacity="0.11" stroke="#0fa07f" stroke-width="1.8"/>
    <g fill="currentColor">
      <text x="34" y="456" font-size="9.5" font-weight="700" fill="#0fa07f">the 6.7 s flip, magnified &#8212; every term is machinery, not deliberation</text>
      <text x="34" y="472" font-size="9">operator decision 3.0 s &#8195; control-plane write 0.5 s</text>
      <text x="34" y="486" font-size="9">streaming push to SDKs 1.2 s &#8195; in-process cache TTL 2.0 s</text>
    </g>
    <rect x="536" y="438" width="424" height="56" rx="9" fill="#d64545" fill-opacity="0.11" stroke="#d64545" stroke-width="1.8"/>
    <g fill="currentColor">
      <text x="550" y="456" font-size="9.5" font-weight="700" fill="#d64545">127&#215; slower. 126&#215; the damage. Same incident, same code.</text>
      <text x="550" y="472" font-size="9">A kill switch is a CODE PATH, and a code path needs its data.</text>
      <text x="550" y="486" font-size="9">Contract and kill switch cannot both be true at the same time.</text>
    </g>

    <text x="490" y="562" font-size="11" text-anchor="middle" fill="currentColor" opacity="0.9">The reachable set is a static question &#8212; what does this build read, versus what has been dropped &#8212; and it is answerable before you deploy.</text>
    <text x="490" y="580" font-size="11" text-anchor="middle" fill="currentColor" opacity="0.9">Nothing in a deployment pipeline computes it. It knows how to put the old image back. It does not know the old image cannot run.</text>
  </g>
</svg>
```

The build runs the same incident in two worlds that differ by one statement.

```console
  --- world A: the soak window. CONTRACT HAS NOT RUN. ---
  option                              TTM   reachable  errors  why
  flag kill switch (exposure -> 0%)    6.7s  YES          335  the flag-off path still has a column to read
  rollback to the previous release   109.0s  YES         5450  the previous build's columns all still exist
  roll forward with a fix            849.0s  YES        42450  always available, never fast
  the 6.7 s flip breaks down as operator decision 3.0s + control-plane write 0.5s
    + streaming push to SDKs 1.2s + in-process cache TTL 2.0s
  the rollback reaches PARTIAL relief at 58 s: with 2 of 6 instances back on
  the old path the partner rate is 206/s, under the 260/s quota.

  --- world B: 'while we are in here' — contract shipped with the 100% ramp ---
  option                              TTM   reachable  errors  why
  flag kill switch (exposure -> 0%)    6.7s  NO             -  flag-off path reads shipping_fee: DROPPED
  rollback to the previous release   109.0s  NO             -  previous build reads shipping_fee: DROPPED
  roll forward with a fix            849.0s  YES        42450  always available, never fast
```

**In world A there are three doors and the fastest is 6.7 seconds. In world B there is one, and it is 849 seconds — 127× slower and 126× the damage, from a `DROP COLUMN` that ran nine minutes earlier and was described in its pull request as cleanup.**

Two details in that output repay attention. First, the 6.7-second flip decomposes into an operator decision of 3.0 s and **3.7 s of machinery** — a control-plane write, a streaming push, an in-process cache TTL. Every one of those is a number you chose. Swap a streaming SDK for one that polls every 30 seconds and your fastest mitigation becomes 33 seconds without anything else changing.

Second, the rollback's **partial relief at 58 s** is a genuinely useful property that people forget to reason about: as soon as two of six instances are back on the old path, the partner rate falls to **206/s**, under quota, and the errors stop — long before the rollout completes. A rolling rollback mitigates progressively. It also reverts *every other change* in that artifact, which is the cost the flag flip does not pay.

And then the option nobody needed, priced anyway, because pricing it in daylight is the entire point of Lesson 14:

```console
  and the option nobody had to use: restore. Measured restore throughput
  28.4 MB/s against a 240 GB database is 2h 24m — the honest RTO for the
  case where a migration had destroyed data instead of merely blocking a path.
```

### Act 6 — the scorecard

```console
== 6 · THE SCORECARD ==
  stage           lsn    guard                                     held  what it bought
  build           L3     dependency-ordered layers                 yes   493x faster rebuild (0.8 s vs 394.2 s)
  build           L3     reproducible build: fixed mtime + sorted  yes   two machines agreed on one digest instead of two
  registry        L4     admission: pinned + signed + provenance   yes   rejected 4 of 5 references, including 2 mutable tags
  pipeline        L10    build once, promote the same digest       yes   3 releases across 3 environments from 1 tested artifact
  infrastructure  L6     prevent_destroy on stateful resources     yes   blocked a replace of the 100 GB orders database
  orchestration   L7     level-triggered reconciliation            yes   reverted out-of-band drift in 1 tick with no event delivered
  routing         L8/L9  drain window vs client connection lifetim no    would have saved 480 severed requests per full rollout
  deployment      L11    canary gated on NEW-PATH sample count     yes   aborted at 1% on 302 samples; run 3's canary saw 250
  release         L12    deploy != release (flag defaults off)     yes   17250 requests served by the new artifact, reachable by nobody
  config          L5     fail-fast on a missing required key       yes   run 2: refused to serve rather than serve wrong
  schema          L13    expand/migrate/contract, separate deploys yes   run 2's one-step version cost 48983 5xx and 32259 bad reads
  rollback        L14    reachable-set computed before the contrac yes   kept the kill switch alive: 6.7 s instead of 849.0 s

  11 of 12 guards held. 1 was absent:
    drain window vs client connection lifetime — would have saved 480 severed requests per full rollout.
```

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 980 588" width="100%" style="max-width:940px" role="img" aria-label="The scorecard: twelve guards from lessons three to fourteen, laid out as cards, eleven of which held and one of which was absent. The guards that held are the dependency-ordered layer cache, the reproducible build, admission control on pinned and signed images, build-once-promote-many, fail-fast configuration, prevent_destroy on the database, level-triggered reconciliation, canary analysis gated on new-path sample count, deploy separated from release, expand-migrate-contract as separate deploys, and computing the reachable rollback set before contracting. The absent one is comparing the drain window against the client's connection lifetime, which cost 480 severed requests on every full rollout.">
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <text x="490" y="24" text-anchor="middle" font-size="14.5" font-weight="700" fill="currentColor">Twelve guards. Eleven held. Every one is a number somebody wrote down on purpose.</text>
    <text x="490" y="42" text-anchor="middle" font-size="10" fill="currentColor" opacity="0.85">None of these is a tool you buy. Each is one line of configuration or one check in CI.</text>

    <g stroke-width="1.7" stroke-linejoin="round">
      <rect x="20" y="58" width="460" height="66" rx="9" fill="#0fa07f" fill-opacity="0.10" stroke="#0fa07f"/>
      <rect x="20" y="134" width="460" height="66" rx="9" fill="#0fa07f" fill-opacity="0.10" stroke="#0fa07f"/>
      <rect x="20" y="210" width="460" height="66" rx="9" fill="#0fa07f" fill-opacity="0.10" stroke="#0fa07f"/>
      <rect x="20" y="286" width="460" height="66" rx="9" fill="#0fa07f" fill-opacity="0.10" stroke="#0fa07f"/>
      <rect x="20" y="362" width="460" height="66" rx="9" fill="#0fa07f" fill-opacity="0.10" stroke="#0fa07f"/>
      <rect x="20" y="438" width="460" height="66" rx="9" fill="#0fa07f" fill-opacity="0.10" stroke="#0fa07f"/>
      <rect x="500" y="58" width="460" height="66" rx="9" fill="#0fa07f" fill-opacity="0.10" stroke="#0fa07f"/>
      <rect x="500" y="134" width="460" height="66" rx="9" fill="#0fa07f" fill-opacity="0.10" stroke="#0fa07f"/>
      <rect x="500" y="210" width="460" height="66" rx="9" fill="#0fa07f" fill-opacity="0.10" stroke="#0fa07f"/>
      <rect x="500" y="286" width="460" height="66" rx="9" fill="#0fa07f" fill-opacity="0.10" stroke="#0fa07f"/>
      <rect x="500" y="362" width="460" height="66" rx="9" fill="#0fa07f" fill-opacity="0.10" stroke="#0fa07f"/>
      <rect x="500" y="438" width="460" height="66" rx="9" fill="#d64545" fill-opacity="0.12" stroke="#d64545" stroke-dasharray="7 4"/>
    </g>

    <g fill="currentColor">
      <text x="40" y="78" font-size="10.5" font-weight="700">L3 &#8195; dependency-ordered layers</text>
      <text x="40" y="94" font-size="9" opacity="0.9">a one-line source edit rebuilds 2 of 6 layers, not 4 of 4</text>
      <text x="40" y="112" font-size="11" font-weight="700" fill="#0fa07f">0.8 s instead of 394.2 s &#8195; 493&#215;</text>

      <text x="40" y="154" font-size="10.5" font-weight="700">L3 &#8195; reproducible build</text>
      <text x="40" y="170" font-size="9" opacity="0.9">fixed mtimes, sorted entries, pinned versions</text>
      <text x="40" y="188" font-size="11" font-weight="700" fill="#0fa07f">2 machines, 1 digest &#8212; not 2</text>

      <text x="40" y="230" font-size="10.5" font-weight="700">L4 &#8195; admission: pinned + signed + provenance</text>
      <text x="40" y="246" font-size="9" opacity="0.9">a mutable tag resolves to different bytes on different days</text>
      <text x="40" y="264" font-size="11" font-weight="700" fill="#0fa07f">1 of 5 references admitted</text>

      <text x="40" y="306" font-size="10.5" font-weight="700">L10 &#8195; build once, promote the same digest</text>
      <text x="40" y="322" font-size="9" opacity="0.9">rebuilding per environment voids every test you ran</text>
      <text x="40" y="340" font-size="11" font-weight="700" fill="#0fa07f">3 environments, 1 artifact</text>

      <text x="40" y="382" font-size="10.5" font-weight="700">L5 &#8195; fail-fast on a missing required key</text>
      <text x="40" y="398" font-size="9" opacity="0.9">refused to serve rather than serve a wrong default</text>
      <text x="40" y="416" font-size="11" font-weight="700" fill="#0fa07f">and it is why run 2 stalled loudly</text>

      <text x="40" y="458" font-size="10.5" font-weight="700">L6 &#8195; prevent_destroy on stateful resources</text>
      <text x="40" y="474" font-size="9" opacity="0.9">an immutable attribute turns 'update' into 'replace'</text>
      <text x="40" y="492" font-size="11" font-weight="700" fill="#0fa07f">blocked 3 of 4 replaces, incl. the DB</text>

      <text x="520" y="78" font-size="10.5" font-weight="700">L7 &#8195; level-triggered reconciliation</text>
      <text x="520" y="94" font-size="9" opacity="0.9">re-derives the diff from state; no event to miss</text>
      <text x="520" y="112" font-size="11" font-weight="700" fill="#0fa07f">drift reverted in 1 tick</text>

      <text x="520" y="154" font-size="10.5" font-weight="700">L11 &#8195; canary gated on NEW-PATH samples</text>
      <text x="520" y="170" font-size="9" opacity="0.9">count what executed the change, not what could have</text>
      <text x="520" y="188" font-size="11" font-weight="700" fill="#0fa07f">aborted on 302 samples; run 3 had 250</text>

      <text x="520" y="230" font-size="10.5" font-weight="700">L12 &#8195; deploy, then release</text>
      <text x="520" y="246" font-size="9" opacity="0.9">the artifact ships with the flag defaulted off</text>
      <text x="520" y="264" font-size="11" font-weight="700" fill="#0fa07f">17,250 requests served, dark</text>

      <text x="520" y="306" font-size="10.5" font-weight="700">L13 &#8195; expand/migrate/contract, separately</text>
      <text x="520" y="322" font-size="9" opacity="0.9">every step compatible with the one before and after</text>
      <text x="520" y="340" font-size="11" font-weight="700" fill="#0fa07f">0 errors vs 48,983 in one step</text>

      <text x="520" y="382" font-size="10.5" font-weight="700">L14 &#8195; reachable set, computed first</text>
      <text x="520" y="398" font-size="9" opacity="0.9">contract is its own release, taken after a soak</text>
      <text x="520" y="416" font-size="11" font-weight="700" fill="#0fa07f">kill switch alive: 6.7 s, not 849.0 s</text>

      <text x="520" y="458" font-size="10.5" font-weight="700" fill="#d64545">L8 + L9 &#8195; drain window vs pool lifetime &#8195; ABSENT</text>
      <text x="520" y="474" font-size="9" opacity="0.9">two numbers, two teams' config, never compared</text>
      <text x="520" y="492" font-size="11" font-weight="700" fill="#d64545">480 requests severed, every rollout</text>
    </g>

    <text x="490" y="536" font-size="11" text-anchor="middle" fill="currentColor" opacity="0.9">The guards that held are boring, cheap and specific. The one that failed is the one that lives between two teams.</text>
    <text x="490" y="554" font-size="11" text-anchor="middle" fill="currentColor" opacity="0.9">Bounding the connection lifetime at 30 s changed the number not at all: 480 &#8594; 480. The bound has to be shorter than the drain.</text>
    <text x="490" y="572" font-size="11" text-anchor="middle" fill="currentColor" opacity="0.9">Take this table to work and fill in your own column. The empty rows are the interesting part.</text>
  </g>
</svg>
```

**11 of 12 guards held.** Look at what they cost: a line of Containerfile ordering, an environment variable pinning mtimes, an admission policy, one `prevent_destroy`, a required-key check at boot, a sample-count threshold in a canary analyser, a flag defaulted off, a migration split into five steps, and two subset comparisons run in CI. Not one is a product you buy. Every one is a number somebody decided to write down.

And the one that failed is instructive precisely because both halves of it were configured *well*. The server drains. The client bounds its connection lifetime. Neither team is wrong. The **relation** between the two numbers was never anybody's job.

## Use It

You will not build any of this by hand. Here is what the same path looks like assembled from real components, and where the gaps usually are.

### The assembled shape

| Stage | In this lesson | In a real stack |
|---|---|---|
| Source | a dict of 7 files | a Git repository, trunk-based, protected branch |
| Build | a Merkle layer chain | `docker buildx` / BuildKit / Kaniko / `ko`, in CI, with `SOURCE_DATE_EPOCH` set |
| Artifact identity | `sha256:…` from a normalised manifest | an **OCI image digest**; the build job outputs it and everything downstream consumes it |
| Trust | HMAC over the digest | **Sigstore / cosign** keyless signing, an **SLSA** provenance attestation, an **SBOM** |
| Admission | a 3-clause check | an admission controller: Kyverno, OPA Gatekeeper, or the registry's own policy |
| Config | a dict merged into a hash | `ConfigMap` + `Secret`, or a config service; secrets via External Secrets / SOPS / a vault |
| Infrastructure | `plan()` over a state file | **Terraform / OpenTofu / Pulumi**, remote state with locking, `plan` posted to the pull request |
| Reconciliation | a while-loop | Kubernetes controllers, plus **Argo CD** or **Flux** reconciling the cluster against Git |
| Discovery | a set of routable names | `Service` + `EndpointSlice`, or Consul; readiness is the registration signal |
| Routing | a dict of pinned connections | an ingress controller or a service mesh — nginx, Envoy, Gateway API |
| Delivery | a `for` loop over exposure | **Argo Rollouts** or **Flagger** driving a canary against metric analysis |
| Release | one boolean and a hash | a flag platform behind **OpenFeature**, evaluated locally against a cached ruleset |
| Migrations | `columns.add()` | a migration runner in a Job that runs *before* the rollout, with `lock_timeout` set |
| Recovery | a subset comparison | a restore-verification job on a schedule, and a reachability check in CI |

The single most valuable line in that table is the last one, because it is the only row most teams have nothing in.

### The five gaps teams most often leave

**1 · Nobody computes the reachable set.** You can build it this afternoon. Each service declares the columns, topics and payload versions it reads; each migration declares what it removes. CI intersects them across the last *N* releases and fails the build when a release takes the reachable set to zero without a written waiver. Forty lines, and it makes Lesson 14's opening scene structurally impossible.

**2 · The canary analyser counts arrivals, not executions.** If a change is gated by a flag, the metric your analysis reads must be emitted **by the new path**, tagged with the flag's variant. Then "we observed 300 samples" means 300 samples of the thing you are testing. Without that tag, an instance canary and a flag ramp compose into a confident answer about nothing.

**3 · Nobody owns the relation between the drain window and the client's connection lifetime.** Write both numbers on the same page. Then make the server end the argument: send `Connection: close` or an HTTP/2 `GOAWAY` at the start of the drain, so correctness stops depending on every caller's configuration. The corresponding Kubernetes shape is a `preStop` hook that sleeps longer than the endpoint-propagation delay, `terminationGracePeriodSeconds` set above that, and — the part people miss — a maximum connection duration configured at the proxy.

**4 · Contract is treated as cleanup rather than as a release.** It is the only irreversible step, it deletes your kill switch, and it is usually done by whoever is tidying up two weeks later. Give it its own pull request, its own soak requirement, and a template line: *"after this merges, the fastest mitigation for feature X is a roll-forward taking N minutes."* If nobody can fill in N, it is not ready to merge.

**5 · There is no saturation alert on the resources you do not own.** Partner quotas, third-party rate limits, connection pools at the other end. The incident in act 5 ran at **96% of a quota** through an entire ramp and nothing anywhere said so. Utilisation above ~80% for ten minutes should be a ticket, and that applies to somebody else's limit exactly as much as it applies to yours. This is the [dashboards](../../09-logging-monitoring-and-observability/11-dashboards-red-and-use/) lesson's USE panel, pointed outward.

### What this phase deliberately did not cover

Being honest about the edges is part of the deliverable.

**Autoscaling.** The fleet in this capstone is a fixed six. Deciding *how many* — horizontal pod autoscaling, scaling signals that are not CPU, the interaction between an autoscaler and a rollout, cold-start cost — is Phase 11.

**Load-balancing algorithms.** Lesson 9 routed round-robin and said so. Least-connections, latency-weighted EWMA, power-of-two-choices and consistent hashing are choices with measurable and surprising consequences, and they belong with the capacity material in Phase 11.

**Circuit breakers, retries and hedging.** The partner quota in act 5 is exactly the situation a circuit breaker exists for, and this phase gave you a kill switch instead. That is a legitimate mitigation and a poor substitute for the pattern. Phase 11.

**Capacity planning and queueing.** [Phase 8's capstone](../../08-concurrency-and-performance/15-capstone-make-a-slow-service-fast/) established Little's Law and the knee of the latency curve; turning that into a headroom policy and a cost model is Phase 11.

**Testing strategy.** Every run here assumed the artifact was correct in the ways CI checks and wrong in a way it did not. Contract testing, integration testing against real dependencies, and how to test a migration are Phase 12.

**Multi-region and data locality.** Everything above is one region. Cross-region traffic management, replication lag as a correctness constraint, and the failover decision are Phase 11 and beyond.

## Think about it

1. The canary in run 3 was correct about the artifact and useless about the change. Design the *smallest* change to your metrics pipeline that would make an artifact canary and a flag ramp compose safely — and then say what it does to your metric cardinality, and at what number of live flags that cost becomes the binding constraint.
2. Act 5 shows a fault that is a function of absolute volume, so no exposure step could find it. Enumerate the classes of fault with this property, and for each one propose a measurement you could take *during* a 1% ramp that would still predict the failure at 100%. Which of your proposals require a load test rather than an observation?
3. Run 2's rollout stalled because three correct guards composed into an unbounded overlap window. You may add exactly one automated behaviour to the orchestrator. Give the precise trigger condition and the action, then describe the production incident your new behaviour causes — because it will cause one.
4. The soak window between "100% exposure" and "contract" is the only period during which a kill switch exists. How would you decide its length for a specific feature? Name the evidence you would require before contracting, say who owns the decision, and explain what changes if the feature's users include a partner integration you do not deploy.
5. Every failure in this capstone lives between two teams' configuration. Pick any two adjacent stages in the diagram at the top and write down the pair of numbers that must be compared for the join to be safe. Where would that comparison live so that it is checked automatically, and what does it cost the team that has to keep it accurate?

## Key takeaways

- **A release is an artifact, a configuration and a schema, and only one of them rolls back cleanly.** One digest and three configurations produced **three distinct release ids**; the last two differ by a single pool-size key. "We didn't deploy anything" is a true statement about bytes and a false statement about releases, and the deploy-annotation line on your dashboard should show all three.
- **The guards that make a rollout safe are the same guards that make a bad rollout unbounded.** A readiness probe plus `maxUnavailable: 1` plus a level-triggered control loop means a fleet that cannot make progress **does not fail — it waits**, at four-of-six, indefinitely. `progressDeadlineSeconds` reports after 600 s and does not act. Measured cost of that composition with a contracted schema in the middle of it: **48,983 5xx and 32,259 silent bad reads over 909 s**, with rollback unavailable from the first second.
- **A canary measures what it can reach.** An instance canary watching a flag-gated change served **24,600 requests with zero errors** while executing the new path **250 times — 1.02%** — and promoted. The same change gated on new-path sample count aborted at 1% exposure after **302 samples and 9 divergences (2.98%)**, for a total cost of **9 mispriced orders instead of 57,614**. Count executions, not arrivals.
- **An error rate is silent about every request that succeeded and was wrong.** Two of the three runs reported a **0.00% user-facing error rate**; one of them mispriced **57,614** orders and was found by a reconciliation job **7,200 s** later. A missing column is an exception on the write path and a silent `None` on the read path, which is why run 2's damage split **48,983 loud / 32,259 quiet** and only the loud half healed on its own.
- **A kill switch is a code path, so contracting the schema deletes it.** In the soak window the fastest mitigation was a flag flip at **6.7 s and 335 errors**; with the `DROP COLUMN` already shipped, both the flip and the rollback were unreachable and the only option left cost **849 s and 42,450 errors — 127× slower for the same incident**. Reachability is two subset comparisons and belongs in CI, because nothing in a deployment pipeline computes it.
- **The number that hurt most was one two teams each got right.** The server drained for 5 s, correctly sized from its 400 ms of in-flight work; the client bounded its connection lifetime at 30 s, correctly following the standard advice. Together they severed **480 requests on every full rollout**, and tightening the client's bound to 30 s changed that number **not at all — 480 to 480**. A drain window is only meaningful relative to the client's connection lifetime, and `Connection: close` at drain start is the fix you can ship without asking anyone.

You have reached the end of Phase 10. You started with code that ran on a laptop and finished having built the image, pinned it by digest, signed it, declared the infrastructure it needs, watched a control loop hold that infrastructure against drift, routed real traffic through it, landed a change that touched both the schema and the code without a single user-facing error, taken an incident, and priced every way out of it before choosing one.

Next comes **Phase 11: Scalability and Reliability** — this phase kept one fixed fleet serving one steady load correctly through change. The next one asks what happens when the load is not steady and the fleet is not fixed: autoscaling and its interaction with rollouts, load-balancing algorithms that are not round-robin, circuit breakers and retry budgets for exactly the partner quota that broke us here, and the capacity planning that turns "96% of a quota nobody was watching" into a number on a dashboard with an owner.
