# CI/CD: From Commit to Artifact to Environment

> The pipeline takes 40 minutes and is red about a third of the time for reasons unrelated to the change, so the team's reflex on red is to press re-run rather than read it. Measured here: a 20-job pipeline of 95%-reliable jobs is green **35.8% of the time** with nobody having written a bug; auto-retrying the failed job buys 97% green and drops detection of a real race from **59.5% to 9.1%**. Then the deeper failure — because it is slow and untrusted, someone ships from a laptop, and the bytes in production were built on a machine nobody can reproduce. This lesson builds the pipeline that earns the trust back: one artifact, promoted.

**Type:** Build
**Languages:** Python
**Prerequisites:** [Registries, Digests & the Software Supply Chain](../04-registries-and-supply-chain/), [Config, Environments & the Twelve-Factor App](../05-config-and-twelve-factor/)
**Time:** ~80 minutes

## The Problem

**Tuesday, 11:40.** You push a two-line fix. CI (continuous integration — the practice of merging everyone's work to a shared branch continuously, and the system that builds and tests each merge) picks it up. The pipeline takes about forty minutes on a good day, so you go to lunch.

**12:22.** Red. You open the run. The failure is `integration-shard-3`, in a test that has nothing to do with your two lines — it asserts on the ordering of two rows that come back from a query with no `ORDER BY`. You know this test. Everyone knows this test.

You press **Re-run failed jobs**. This is the moment the lesson is about. Not the flaky test — the *reflex*. Your team has learned, correctly and empirically, that a red pipeline is more likely to be noise than signal. That learning is rational and it is fatal, because it applies to every red, including the ones that are real. The pipeline is no longer a signal. It is a toll booth.

**13:05.** Green. You merge.

**13:20.** A colleague needs a hotfix in production for a customer escalation. The pipeline is forty minutes, and it is red a third of the time, so the realistic wait is over an hour. They have a working laptop, Docker, and the registry credentials. They build the image locally, push it, and update the deployment. It works. It takes four minutes. Everyone is relieved.

**Thursday, 03:10.** Production is broken in a way staging is not. Someone asks the only question that matters: *what is actually running?* The answer is a digest — a content hash naming exact bytes — that appears in no CI run, was built from a working tree nobody can reconstruct, on a machine with a different base image cached, a different Python patch release, and one uncommitted file. There is no build log. There is no test result for those bytes, because those bytes have never been tested by anything. The commit it claims to come from builds to a *different* digest today.

Nobody was reckless here. Every individual decision was locally reasonable. Follow the causality backwards and it is one chain:

**Slow pipeline → untrusted pipeline → people route around it → the artifact in production has no provenance.** A pipeline nobody trusts does not merely fail to help; it actively creates the conditions for the outage, because the pressure it applies is real and the only relief valve is bypassing it. And the bypass is invisible right up to the moment you need the audit trail.

This lesson is about the three properties that fix that chain: a pipeline that is **fast** (the critical path, measured), **trustworthy** (flakes as arithmetic, not luck), and **honest** (one artifact, built once, promoted — so the thing you tested is provably the thing you shipped).

## The Concept

### CI, continuous delivery and continuous deployment are three different things

These get used interchangeably in job descriptions and they mean genuinely different commitments. Getting them straight is not pedantry — teams routinely claim one and practise another, and the gap is where the incidents live.

**Continuous integration (CI)** is a *developer* practice with a tooling consequence. Everyone merges to trunk frequently — at least daily, in small increments — and every merge is automatically built and tested. The point is not the build server. The point is that **integration happens continuously instead of in a big scary lump**, so merge conflicts and semantic incompatibilities surface while they are still one afternoon's work. A team with a beautiful build server and six long-lived feature branches is not doing CI. A team on trunk with a shell script is.

**Continuous delivery (CD)** means **every build that passes is *releasable***, and getting it into production is a business decision one button away. The artifact is built, tested, signed, and sitting in a registry. Whether to ship it on a Friday is a judgement call someone makes; the *ability* to ship it is not in question and requires no engineering work.

**Continuous deployment** (also CD, which is why the acronym is a mess) removes the button. Every green build goes to production automatically, with no human gate.

Most teams want **continuous delivery**, and should say so. It gives you the entire benefit — a short, boring, rehearsed path from commit to production — without requiring the automated rollback, progressive rollout and observability maturity that make gateless deployment safe rather than exciting. Continuous deployment is a fine goal *after* Lesson 11's canary and Lesson 12's feature flags exist, because those are what make an automatic push survivable. Doing it before is not maturity; it is removing the brake because you like the pedal on the right.

There is a fourth idea, and it is a discipline rather than a pipeline stage: **trunk-based development**. Short-lived branches, merged within a day or two, behind flags if incomplete. It exists because CI's guarantee is only as good as the frequency of integration. Research on delivery performance (Forsgren, Humble and Kim, *Accelerate*, 2018, which formalised the four DORA metrics — deployment frequency, lead time for changes, change failure rate, and time to restore service) found trunk-based development and comprehensive automated testing among the strongest predictors of both throughput *and* stability. That pairing is the finding worth remembering: on delivery, speed and safety are not a trade-off. The same practices produce both.

### The central rule: build once, promote the same artifact

Everything else in this lesson is negotiable. This is not.

> **The pipeline builds the artifact exactly once. Every environment afterwards receives that same immutable artifact, referenced by digest. Only configuration changes between environments.**

Lesson 04 established that a digest names exact bytes and a tag names whatever someone pushed last. Lesson 05 established that `release = build + config` and that the pair needs its own identity. Put them together and you get **promotion**: moving one unchanging digest through dev, staging and production, pairing it with a different config at each stop, and stamping a distinct release id for each pair.

The alternative — a `build` step inside each environment's deploy job — feels tidier. Each environment's job is self-contained; you can re-run prod's deploy without touching staging. It is also **the single most common way to void every test you ran**, because a build is a function of far more than your source:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 520" width="100%" style="max-width:840px" role="img" aria-label="Two panels comparing promotion with rebuilding. On the left, one artifact is built once on commit with digest sha256 48fe3fe6, and is combined with three different environment configurations to produce three distinct release identifiers for dev, staging and production, each behind its own gate. The bytes that passed integration tests are the bytes serving production. On the right, the anti-pattern rebuilds inside each environment's job: three builds from identical source produce three different digests, none of which matches the artifact that was tested, because a build argument and a timestamp were enough to change the bytes.">
  <defs>
    <marker id="l10-a2" markerWidth="9" markerHeight="9" refX="5.5" refY="3" orient="auto"><path d="M0,0 L6.5,3 L0,6 Z" fill="currentColor"/></marker>
    <marker id="l10-a2r" markerWidth="9" markerHeight="9" refX="5.5" refY="3" orient="auto"><path d="M0,0 L6.5,3 L0,6 Z" fill="#d64545"/></marker>
  </defs>
  <text x="440" y="25" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">Build once and promote the digest — or void every test you ran</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">

    <g stroke-width="2" stroke-linejoin="round">
      <rect x="12" y="42" width="424" height="424" rx="13" fill="#0fa07f" fill-opacity="0.07" stroke="#0fa07f"/><rect x="444" y="42" width="424" height="424" rx="13" fill="#d64545" fill-opacity="0.07" stroke="#d64545"/>
    </g>
    <text x="224" y="68" font-size="12.5" font-weight="700" text-anchor="middle" fill="#0fa07f">BUILD ONCE, PROMOTE MANY</text><text x="656" y="68" font-size="12.5" font-weight="700" text-anchor="middle" fill="#d64545">ANTI-PATTERN: REBUILD PER ENVIRONMENT</text><text x="224" y="84" font-size="9" text-anchor="middle" fill="currentColor" opacity="0.85">one build job, on the merge commit</text>
    <text x="656" y="84" font-size="9" text-anchor="middle" fill="currentColor" opacity="0.85">a 'build' step inside each environment's job</text>

    <rect x="60" y="98" width="328" height="52" rx="9" fill="#7c5cff" fill-opacity="0.16" stroke="#7c5cff" stroke-width="2.2"/><text x="224" y="117" font-size="10" font-weight="700" text-anchor="middle" fill="currentColor">THE ARTIFACT — immutable, content-addressed</text><text x="224" y="136" font-size="10" text-anchor="middle" fill="#7c5cff" font-weight="700">sha256:48fe3fe6596779c797b22dc3</text>

    <text x="224" y="170" font-size="9" text-anchor="middle" fill="currentColor" opacity="0.9">tested here, once — lint, types, units, integration, scan</text>

    <g fill="none" stroke="currentColor" stroke-width="1.5" opacity="0.75">
      <path d="M120 178 C 90 194, 76 198, 70 208" marker-end="url(#l10-a2)"/><path d="M224 178 L 224 208" marker-end="url(#l10-a2)"/><path d="M328 178 C 358 194, 372 198, 378 208" marker-end="url(#l10-a2)"/>
    </g>

    <g font-size="8.5" font-weight="700" fill="currentColor" opacity="0.65">
      <text x="30" y="228">ENV</text><text x="86" y="228">CONFIG (all that moves)</text><text x="262" y="228">RELEASE = build + config</text>
    </g>

    <g stroke-width="1.8" stroke-linejoin="round">
      <rect x="86" y="236" width="164" height="38" rx="7" fill="#e0930f" fill-opacity="0.15" stroke="#e0930f"/><rect x="258" y="236" width="164" height="38" rx="7" fill="#0fa07f" fill-opacity="0.15" stroke="#0fa07f"/><rect x="86" y="286" width="164" height="38" rx="7" fill="#e0930f" fill-opacity="0.15" stroke="#e0930f"/>
      <rect x="258" y="286" width="164" height="38" rx="7" fill="#0fa07f" fill-opacity="0.15" stroke="#0fa07f"/><rect x="86" y="336" width="164" height="38" rx="7" fill="#e0930f" fill-opacity="0.15" stroke="#e0930f"/><rect x="258" y="336" width="164" height="38" rx="7" fill="#0fa07f" fill-opacity="0.15" stroke="#0fa07f"/>
    </g>

    <g fill="currentColor">
      <text x="30" y="259" font-size="10" font-weight="700">dev</text><text x="30" y="309" font-size="10" font-weight="700">stg</text><text x="30" y="359" font-size="10" font-weight="700">prod</text>

      <text x="96" y="252" font-size="9">cfg 3e2b90f12b47c560</text><text x="96" y="266" font-size="8" opacity="0.8">LOG=debug POOL=2 T=5000ms</text><text x="96" y="302" font-size="9">cfg 429ac0e6b9179d06</text><text x="96" y="316" font-size="8" opacity="0.8">LOG=info POOL=10 T=2000ms</text><text x="96" y="352" font-size="9">cfg 042781866f6b6484</text><text x="96" y="366" font-size="8" opacity="0.8">LOG=warn POOL=60 T=1500ms</text>

      <text x="268" y="252" font-size="9.5" font-weight="700" fill="#0fa07f">rel-e601a6c92d0c</text><text x="268" y="266" font-size="8" opacity="0.85">gate: auto on merge</text><text x="268" y="302" font-size="9.5" font-weight="700" fill="#0fa07f">rel-c2e00caa33bc</text><text x="268" y="316" font-size="8" opacity="0.85">gate: auto, smoke tests</text><text x="268" y="352" font-size="9.5" font-weight="700" fill="#0fa07f">rel-7c05407b84d8</text><text x="268" y="366" font-size="8" opacity="0.85">gate: manual approval</text>
    </g>

    <g fill="currentColor" font-size="11" font-weight="700" text-anchor="middle" opacity="0.7">
      <text x="254" y="259">+</text><text x="254" y="309">+</text><text x="254" y="359">+</text>
    </g>

    <rect x="34" y="390" width="380" height="60" rx="8" fill="#0fa07f" fill-opacity="0.12" stroke="#0fa07f" stroke-width="1.8"/>
    <g fill="currentColor">
      <text x="224" y="410" font-size="10.5" font-weight="700" text-anchor="middle">1 digest &#8195; 3 release ids &#8195; 3 promotions</text><text x="224" y="426" font-size="9" text-anchor="middle" opacity="0.9">promotion is a pointer move, not a build. Nothing recompiles.</text><text x="224" y="442" font-size="9" text-anchor="middle" opacity="0.9">The bytes that passed integration-tests are the bytes in production.</text>
    </g>

    <g stroke-width="1.8" stroke-linejoin="round">
      <rect x="466" y="104" width="122" height="34" rx="7" fill="#7f7f7f" fill-opacity="0.10" stroke="currentColor" stroke-opacity="0.5"/><rect x="624" y="104" width="122" height="34" rx="7" fill="#7f7f7f" fill-opacity="0.10" stroke="currentColor" stroke-opacity="0.5"/>
    </g>
    <text x="527" y="120" font-size="9" text-anchor="middle" fill="currentColor" font-weight="700">same commit</text><text x="527" y="132" font-size="8" text-anchor="middle" fill="currentColor" opacity="0.8">identical source</text><text x="685" y="120" font-size="9" text-anchor="middle" fill="currentColor" font-weight="700">3 build jobs</text>
    <text x="685" y="132" font-size="8" text-anchor="middle" fill="currentColor" opacity="0.8">one per environment</text><path d="M592 121 L 618 121" fill="none" stroke="currentColor" stroke-width="1.4" opacity="0.7" marker-end="url(#l10-a2)"/>

    <text x="656" y="164" font-size="9" text-anchor="middle" fill="currentColor" opacity="0.9">each job passes --build-arg ENV=&lt;name&gt; and stamps a build time</text>

    <g fill="none" stroke="#d64545" stroke-width="1.5" opacity="0.8">
      <path d="M600 172 C 560 190, 520 196, 512 230" marker-end="url(#l10-a2r)"/><path d="M656 172 L 656 230" marker-end="url(#l10-a2r)"/><path d="M712 172 C 752 190, 792 196, 800 230" marker-end="url(#l10-a2r)"/>
    </g>

    <g stroke-width="1.8" stroke-linejoin="round">
      <rect x="466" y="236" width="384" height="38" rx="7" fill="#d64545" fill-opacity="0.13" stroke="#d64545"/><rect x="466" y="286" width="384" height="38" rx="7" fill="#d64545" fill-opacity="0.13" stroke="#d64545"/><rect x="466" y="336" width="384" height="38" rx="7" fill="#d64545" fill-opacity="0.13" stroke="#d64545"/>
    </g>
    <g fill="currentColor">
      <text x="478" y="252" font-size="9" font-weight="700">dev</text><text x="510" y="252" font-size="9" fill="#d64545" font-weight="700">sha256:c9eab2a1fd1ad8b490a0f5c3</text><text x="478" y="266" font-size="8" opacity="0.85">built at 09:12:00Z &#8195; does NOT match the tested artifact</text><text x="478" y="302" font-size="9" font-weight="700">stg</text><text x="510" y="302" font-size="9" fill="#d64545" font-weight="700">sha256:8d33c9aaac6e4bc805c71f91</text><text x="478" y="316" font-size="8" opacity="0.85">built at 09:19:00Z &#8195; does NOT match the tested artifact</text>
      <text x="478" y="352" font-size="9" font-weight="700">prod</text><text x="510" y="352" font-size="9" fill="#d64545" font-weight="700">sha256:ff9e2ac1d72f071b87ba569d</text><text x="478" y="366" font-size="8" opacity="0.85">built at 09:26:00Z &#8195; does NOT match the tested artifact</text>
    </g>

    <rect x="466" y="390" width="380" height="60" rx="8" fill="#d64545" fill-opacity="0.12" stroke="#d64545" stroke-width="1.8"/>
    <g fill="currentColor">
      <text x="656" y="410" font-size="10.5" font-weight="700" text-anchor="middle">3 rebuilds &#8195; 3 distinct digests &#8195; 0 match</text><text x="656" y="426" font-size="9" text-anchor="middle" opacity="0.9">a build arg and a timestamp were enough. So is a floating base</text><text x="656" y="442" font-size="9" text-anchor="middle" opacity="0.9">tag, a new transitive patch, or a different runner image.</text>
    </g>

    <text x="440" y="490" font-size="11.5" text-anchor="middle" fill="currentColor" font-weight="700">Rebuilding per environment means the thing you tested is provably not the thing you shipped.</text><text x="440" y="508" font-size="10.5" text-anchor="middle" fill="currentColor" opacity="0.9">Every guarantee the tests bought is spent the moment a second build runs.</text>
  </g>
</svg>
```

The Build It measures the right-hand panel: three builds from **identical source** produce **three distinct digests, none matching the tested artifact**. A build argument and a timestamp were enough. In a real pipeline the list of things that differ between two builds of the same commit is longer and less visible — a floating base image tag that got a new push, a transitive dependency that published a patch release an hour ago, a runner image that rolled to a new Ubuntu minor, a compiler embedding a build path.

**Promotion is a pointer move, not a build.** `deploy(prod, sha256:48fe…)` copies nothing and compiles nothing; it changes which digest an environment points at. That is why it takes seconds, why it is trivially reversible (point back at the previous digest — the subject of Lesson 14), and why it preserves the test guarantee. Rebuilding destroys all three properties at once.

### A pipeline is a DAG, and only its critical path is your wait

A pipeline is not a list of scripts. It is a **DAG — a directed acyclic graph**: nodes are stages, edges are "must finish before", and *acyclic* means no stage can transitively depend on itself. Once you see it that way, two numbers separate, and confusing them is the reason most pipeline-speed efforts fail:

- **Total work** — the sum of every stage's duration. This is what you *pay* the CI provider.
- **Wall time** — the length of the longest path through the graph. This is what the developer *waits*.

Our pipeline's total work is **1,250 seconds (20.8 minutes of billed runner time)**, but its wall time on four runners is **780 seconds (13.0 minutes)** — a parallelism of **1.60×**.

That longest path is the **critical path**, and every stage on it has zero **slack** — the amount you could delay or lengthen that stage without moving the finish. Here it is `deps-install → build-image → integration-tests → push-artifact`, and it is exactly 780 s. Everything else has slack: lint has **515 s**, typecheck **465 s**, unit-tests **350 s**, security-scan **180 s**.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 500" width="100%" style="max-width:840px" role="img" aria-label="The eight-stage pipeline drawn as a directed acyclic graph on a time axis. The critical path — deps-install, build-image, integration-tests, push-artifact — forms one contiguous bar 780 seconds long, which is the developer's wall clock. Lint, typecheck, unit-tests and security-scan sit off the path with 515, 465, 350 and 180 seconds of slack shown as dashed extensions, all converging on the moment push-artifact begins. A dashed box marks the four stages that run concurrently once dependencies install. Below, the same pipeline on a warm cache after editing one test file: six stages restore from cache in five seconds each and only unit-tests and push-artifact re-execute, cutting wall time from 780 seconds to 255.">
  <defs>
    <marker id="l10-a1" markerWidth="9" markerHeight="9" refX="5.5" refY="3" orient="auto"><path d="M0,0 L6.5,3 L0,6 Z" fill="currentColor"/></marker>
  </defs>
  <text x="440" y="25" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">A pipeline is a DAG, and only its longest path is your wait</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">

    <g font-size="9" font-weight="700" fill="currentColor" opacity="0.7">
      <text x="12" y="48">COLD CACHE — 8 stages, 4 runners, nothing ever built</text><text x="868" y="48" text-anchor="end">amber = cache MISS (re-executed)</text>
    </g>
    <path d="M12 54 L 868 54" fill="none" stroke="currentColor" stroke-width="1.1" opacity="0.35"/>

    <rect x="252" y="70" width="196" height="180" rx="9" fill="none" stroke="currentColor" stroke-width="1.3" stroke-dasharray="5 4" opacity="0.38"/><text x="352" y="264" font-size="8.5" text-anchor="middle" fill="currentColor" opacity="0.75">4 runners busy — the graph decided that, not the config</text>

    <g stroke-width="2.4" stroke-linejoin="round">
      <rect x="128" y="76" width="130" height="34" rx="6" fill="#e0930f" fill-opacity="0.16" stroke="#3553ff"/><rect x="258" y="76" width="187" height="34" rx="6" fill="#e0930f" fill-opacity="0.16" stroke="#3553ff"/><rect x="445" y="76" width="216" height="34" rx="6" fill="#e0930f" fill-opacity="0.16" stroke="#3553ff"/>
      <rect x="661" y="76" width="29" height="34" rx="6" fill="#e0930f" fill-opacity="0.16" stroke="#3553ff"/>
    </g>
    <path d="M128 114 L 690 114" fill="none" stroke="#3553ff" stroke-width="3"/>

    <g fill="currentColor" font-size="9.5">
      <text x="138" y="91">deps-install</text><text x="138" y="104" font-size="8.5" opacity="0.8">180s</text><text x="268" y="91">build-image</text><text x="268" y="104" font-size="8.5" opacity="0.8">260s</text>
      <text x="455" y="91">integration-tests</text><text x="455" y="104" font-size="8.5" opacity="0.8">300s</text><text x="698" y="91" font-size="9">push-artifact</text><text x="698" y="104" font-size="8.5" opacity="0.8">40s</text>
    </g>
    <text x="12" y="97" font-size="9.5" font-weight="700" fill="#3553ff">CRITICAL</text><text x="12" y="109" font-size="8" fill="#3553ff" opacity="0.85">0 slack</text>

    <g stroke-width="1.6" stroke-linejoin="round">
      <rect x="258" y="132" width="32" height="24" rx="5" fill="#e0930f" fill-opacity="0.16" stroke="#e0930f"/><rect x="258" y="164" width="68" height="24" rx="5" fill="#e0930f" fill-opacity="0.16" stroke="#e0930f"/><rect x="258" y="196" width="151" height="24" rx="5" fill="#e0930f" fill-opacity="0.16" stroke="#e0930f"/>
      <rect x="445" y="228" width="86" height="24" rx="5" fill="#e0930f" fill-opacity="0.16" stroke="#e0930f"/>
    </g>
    <g fill="none" stroke="#7f7f7f" stroke-width="1.4" stroke-dasharray="4 4" opacity="0.85">
      <path d="M290 144 L 661 144"/><path d="M326 176 L 661 176"/><path d="M409 208 L 661 208"/><path d="M531 240 L 661 240"/>
    </g>
    <g fill="none" stroke="#7f7f7f" stroke-width="1.2" opacity="0.7">
      <path d="M661 138 L 661 246"/>
    </g>

    <g fill="currentColor" font-size="9.5">
      <text x="12" y="148">lint</text><text x="12" y="180">typecheck</text><text x="12" y="212">unit-tests</text><text x="12" y="244">security-scan</text>
    </g>
    <g fill="currentColor" font-size="8.5" opacity="0.85">
      <text x="700" y="148">45s &#8195; slack 515s</text><text x="700" y="180">95s &#8195; slack 465s</text><text x="700" y="212">210s &#8195; slack 350s</text><text x="700" y="244">120s &#8195; slack 180s</text>
    </g>

    <g fill="none" stroke="currentColor" stroke-width="1.4" opacity="0.85">
      <path d="M128 282 L 700 282" marker-end="url(#l10-a1)"/><path d="M128 278 L 128 286"/><path d="M258 278 L 258 286"/><path d="M445 278 L 445 286"/><path d="M661 278 L 661 286"/><path d="M690 278 L 690 286"/>
    </g>
    <g fill="currentColor" font-size="8.5" opacity="0.8" text-anchor="middle">
      <text x="128" y="298">0s</text><text x="258" y="298">180s</text><text x="445" y="298">440s</text><text x="655" y="298">740s</text><text x="712" y="298">780s</text>
    </g>

    <g font-size="9" font-weight="700" fill="currentColor" opacity="0.7">
      <text x="12" y="330">WARM CACHE — the same pipeline after editing one test file</text><text x="868" y="330" text-anchor="end">green = cache HIT (5s to restore)</text>
    </g>
    <path d="M12 336 L 868 336" fill="none" stroke="currentColor" stroke-width="1.1" opacity="0.35"/>

    <g stroke-width="1.6" stroke-linejoin="round">
      <rect x="128" y="350" width="4" height="22" rx="1.5" fill="#0fa07f" fill-opacity="0.5" stroke="#0fa07f"/><rect x="132" y="350" width="4" height="22" rx="1.5" fill="#0fa07f" fill-opacity="0.5" stroke="#0fa07f"/><rect x="136" y="350" width="4" height="22" rx="1.5" fill="#0fa07f" fill-opacity="0.5" stroke="#0fa07f"/>
      <rect x="132" y="380" width="151" height="24" rx="5" fill="#e0930f" fill-opacity="0.18" stroke="#e0930f"/><rect x="283" y="380" width="29" height="24" rx="5" fill="#e0930f" fill-opacity="0.18" stroke="#e0930f"/>
    </g>
    <g fill="currentColor" font-size="8.5">
      <text x="150" y="365">6 stages restored from cache, 5s each — deps, lint, typecheck, build-image, integration, security</text><text x="320" y="390">unit-tests 210s + push-artifact 40s: the only bytes that changed</text><text x="320" y="401" opacity="0.75">their inputs changed, so their content-derived keys missed</text>
    </g>
    <g fill="none" stroke="currentColor" stroke-width="1.4" opacity="0.85">
      <path d="M128 416 L 700 416" marker-end="url(#l10-a1)"/><path d="M128 412 L 128 420"/><path d="M312 412 L 312 420"/><path d="M690 412 L 690 420"/>
    </g>
    <g fill="currentColor" font-size="8.5" opacity="0.8" text-anchor="middle">
      <text x="128" y="432">0s</text><text x="312" y="432" font-weight="700" fill="#0fa07f">255s</text><text x="690" y="432" opacity="0.6">780s (cold)</text>
    </g>

    <g stroke-width="1.6">
      <rect x="12" y="444" width="856" height="30" rx="7" fill="#7f7f7f" fill-opacity="0.07" stroke="currentColor" stroke-opacity="0.3"/>
    </g>
    <g fill="currentColor" font-size="9.5">
      <text x="26" y="463">1250s of billed runner time &#8195;·&#8195; 780s of developer wait &#8195;·&#8195; parallelism 1.60x &#8195;·&#8195; warm 255s = 3.06x faster, 80% of work skipped</text>
    </g>
    <text x="440" y="492" font-size="11" text-anchor="middle" fill="currentColor" opacity="0.9">Halving unit-tests removes 105s of billed work and saves the developer zero. Only the blue bar is your wait.</text>
  </g>
</svg>
```

Now the senior insight, and it is the one that saves quarters of engineering effort: **optimising a stage that is not on the critical path buys you exactly nothing.** The Build It halves two stages and measures both. Halving `unit-tests` — 210 s, off the path, with 350 s of slack — removes **105 s of billed work and saves the developer 0 seconds.** Halving `integration-tests` — 300 s, on the path — removes 150 s of work and saves **exactly 150 s** of wall time.

The same logic bounds parallelism. Going from 1 runner to 2 takes wall time from 1,250 s to 780 s. Going from 2 to 4, or to 8, changes it by **nothing at all**, because at 2 runners you have already hit the critical-path floor. Every runner past that point is idle money. This is the single most common wasted CI spend: buying concurrency for a graph whose shape cannot use it.

The practical procedure is short. Find the longest path. Ask of each stage on it, in order: can this be shorter, can it start earlier, does it need to be on the path at all? `integration-tests` depends on `build-image` — but if it only needs a *test* image rather than the production one, that edge might be severable, which is worth more than any amount of tuning inside the stage.

### Caching and hermeticity: the key must come from the inputs

A cache turns "did this exact work already happen?" into a lookup. It only works if you can answer that question honestly, and the honest answer is a **content hash of everything the stage reads**: the stage's identity, its tool versions, and the bytes of each input file. Nothing else. The Build It computes exactly that:

```python
def cache_key(name: str, workspace: Mapping[str, str]) -> str:
    """H(stage identity + tool version + content of every effective input).

    Nothing ambient goes in: no hostname, no timestamp, no build number. A key
    that depends on the machine is a key that can never hit on another machine.
    """
```

That comment is the definition of **hermeticity**: a build is hermetic when it depends only on declared inputs, and on nothing about the machine that runs it. A build that reads the system clock, resolves a floating dependency version at build time, embeds a hostname, or picks up a globally installed tool is not hermetic, and the consequences compound. It cannot be reproduced, so a debugging session cannot recreate it. It cannot be cached correctly, because either the key ignores the ambient input (and you get a *wrong* hit — the worst outcome, a stale result presented as fresh) or it includes it (and you never hit at all).

Two rules follow. **Key on content, never on a branch name, a date, or a build number** — those change when the content did not, and stay the same when the content did. And **a cache hit is not free**: our model charges 5 s to restore one, because a tarball still has to move over the network and be unpacked. A "cache" whose restore costs more than the stage it skips is a cache you should delete, and they exist in real pipelines more often than anyone admits.

Caching also inherits Lesson 03's invalidation cascade, now at pipeline scope. A stage's effective inputs include everything its dependencies read, transitively. So the blast radius of a change depends entirely on *which file* changed, and the range is enormous: editing one test file skipped **80% of the work and cut wall time by 67%**, while editing one line of `requirements.lock` invalidated **8 of 8 stages** and produced no saving whatsoever. Same one-line diff, from the cache's point of view a completely different event.

### Feedback latency is a behavioural property, not a performance metric

Here is the part that is not about computers. **The length of your pipeline determines whether a human being stays in context.**

Under roughly ten minutes, people wait. They keep the change in their head, watch the run, and fix a failure with everything still loaded. Substantially beyond it, they start something else — and now a failure arrives to a person who has swapped out, is halfway into another task, and must reload the entire context to act on it. The cost of a 40-minute pipeline is not 40 minutes. It is 40 minutes plus a context switch, multiplied by every red, and it changes behaviour: bigger batches (because merging is expensive, so people accumulate), and the re-run reflex (because reading a failure you have swapped out of is expensive, so guessing is cheaper).

The ten-minute target is the long-standing design rule from *Continuous Delivery* (Humble and Farley, 2010) and it is a target for the **critical path**, not for total work. Our pipeline's critical path is 13.0 minutes, which is over budget — and the diagnosis follows immediately from the DAG: `integration-tests` at 300 s and `build-image` at 260 s are the two places where any minute exists to be won. Nothing you do to lint, typecheck, unit-tests or security-scan moves that number by a single second.

The usual resolution is **staged feedback**: a fast gate (lint, types, unit tests, a subset of integration) that must pass before merge and stays inside ten minutes, and a slower, thorough suite (full integration, end-to-end, performance, security) that runs after merge or on a schedule. You are explicitly trading some risk for a working feedback loop. State that trade rather than pretending the 40-minute suite is a pre-merge gate that people respect, because they do not.

### Flaky tests are a trust problem, and the arithmetic is brutal

A **flaky test** passes and fails on identical input. The cause is almost always an undeclared dependency on something real — wall-clock time, ordering that was never guaranteed, a port or fixture shared between parallel jobs, a network call, a race that only sometimes loses.

The arithmetic is the part that surprises people. If a pipeline has *n* independent jobs each passing with probability *p*, the pipeline is green with probability *pⁿ*. Measured over 60,000 simulated runs per cell:

```text
  PER-JOB p       n = 5        n = 10       n = 20
     0.99         95.1%        90.4%        81.8%
     0.95         77.4%        59.9%        35.8%
     0.90         59.0%        34.9%        12.2%
```

**Twenty jobs that are each 95% reliable produce a green pipeline 35.8% of the time.** Nobody wrote a bug. Every job, examined alone, looks basically fine — 95% would be a respectable number in most contexts. The pipeline is red about two runs in three, and it is *nobody's* fault in particular, which is precisely why it never gets fixed: there is no owner, because there is no single culprit.

Then comes the response, and this is where teams silently trade away the thing they built the pipeline for. The Build It compares four responses on a 20-job pipeline where one job is 70% reliable and the other 19 are 99.8%:

| Response | Green on clean | Job-runs | Race caught | Bug in flaky job caught |
|---|---|---|---|---|
| do nothing | 67.7% | 20.0 | **59.5%** | 100% |
| press re-run (whole pipeline ×3) | 96.6% | 28.6 | 21.0% | 100% |
| auto-retry each failed job ×3 | **97.4%** | 20.4 | **9.1%** | 100% |
| quarantine the flaky job, then fix | 96.3% | 20.0 | 42.1% | **3.7%** |

Read the columns in the right order. A **deterministic** regression is caught 100% of the time by every response — retries cannot hide a failure that happens every single time, which is exactly why retrying feels harmless. The column that matters is the **race**: a genuine concurrency bug that manifests in 40% of runs. Doing nothing catches it **59.5%** of the time. Auto-retrying each failed job three times catches it **9.1%**.

That is the whole argument in two numbers. **Retrying until green is retrying until the race hides**, and the definition of "the race hid" is "you merged it." A retry policy cannot distinguish a flaky test from a flaky *product*, so it suppresses both. And it is not even cheap: pressing re-run costs **28.6 job-runs per pipeline, 1.43× the compute**, to buy 97% green.

**Quarantine** is the honest answer: mark the flaky job non-gating, keep running it and reporting it, and assign an owner and a deadline to fix it. It buys 96.3% green at **1.00× compute** and preserves **42.1%** race detection. But look at the last column, because that is quarantine's real price and it should be stated plainly: a genuine bug living *inside* the quarantined job is caught **3.7%** of the time — and those catches are incidental reds from unrelated jobs, not from the bug. A quarantined test protects nothing. It is a debt instrument with a name attached, which is strictly better than a retry (an unnamed debt) and strictly worse than a fix.

### Secrets and identity in CI

Your CI system builds, signs and deploys everything you ship. That makes it the highest-value target in your infrastructure, and it is routinely the least-defended.

The core problem is the **standing secret**. A long-lived cloud access key stored in CI variables exists forever, works from anywhere, is copied into the environment of jobs that have no business seeing it, and — because it never expires — has no natural moment at which anyone reconsiders it. If it leaks, you find out when the bill arrives or the data does not.

**OIDC federation removes it.** OIDC (OpenID Connect, an identity layer on top of OAuth 2.0 — the mechanics are in [OAuth 2.0 & OIDC](../../07-auth-and-security/07-oauth2-and-oidc/)) lets your CI provider act as an **identity provider**. At the start of a job it mints a short-lived, signed JWT (JSON Web Token) asserting verifiable facts: this repository, this branch or tag, this workflow file, this environment, this run. Your cloud account is configured to trust that issuer and to exchange such a token for temporary credentials — but only when the claims match a policy you wrote. The result:

- **No standing secret exists.** There is nothing in CI variables to steal, and nothing to rotate.
- **Credentials are minutes-long**, so a leaked token is worth almost nothing almost immediately.
- **Authorisation is claim-based**, so "only the `main` branch of `org/repo`, only in the `production` environment, may assume the deploy role" is enforced by the cloud provider rather than by convention.

Four more controls make the rest of the surface defensible:

- **Least-privilege runners.** A job that runs tests needs no deploy credential. Scope permissions per job, default them to read-only, and grant write only where the job actually pushes something.
- **Protected branches and required checks.** The branch a release is cut from cannot be force-pushed or pushed to directly; merges require review and the named checks must pass. This is where a pipeline stops being advisory.
- **Never run untrusted code with secrets in scope.** This is the sharpest edge in CI security. A pull request from a fork is code an anonymous person wrote, and a build step is arbitrary code execution by design. If that job has your registry token in its environment, you have handed a stranger your registry. Run fork PRs in a restricted context with no secrets; require an explicit approval before anything privileged touches them; and never let a PR modify the workflow file that grants its own permissions.
- **Pin your third-party actions by commit SHA, not by tag.** This is Lesson 04's tag-versus-digest argument applied to your pipeline's own dependencies: `uses: some/action@v3` is a mutable pointer someone else controls, and it runs with whatever permissions your job holds. Supply-chain compromises of popular CI actions have followed exactly this path.

### GitOps: Lesson 07's control loop, pointed at deployment

Lesson 07 established the control loop: a controller continuously compares **desired state** to **observed state** and acts to close the gap, forever, level-triggered rather than reacting to events. **GitOps is that control loop applied to deployment.** Desired state lives in a git repository. A controller running inside the cluster watches it, compares it to what is actually running, and reconciles.

The consequences of that one move are larger than they look. Because the loop is continuous, **drift is corrected rather than merely detected** — someone's emergency `kubectl edit` gets reverted within a reconcile interval, and the manifest in git is not a description of what you deployed once, it is a live, enforced statement of what is running now. Because desired state is a git repository, deployment inherits the review, history and revert semantics you already have: rollback is `git revert`.

The security consequence is the bigger one, and it turns on the direction of the arrow:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 500" width="100%" style="max-width:840px" role="img" aria-label="Push deploys compared with pull deploys, with the credential blast radius marked on each. On the left, the CI runner holds a production cluster credential and pushes changes into the cluster, so the blast radius covers the whole CI system: every job, every action, every fork pull request that can reach the secret can reach production. On the right, CI only pushes an artifact to the registry and writes desired state to a git repository, and a reconciling controller inside the cluster pulls both, so no production credential exists outside the cluster and the blast radius is limited to write access on the git repository.">
  <defs>
    <marker id="l10-a3" markerWidth="9" markerHeight="9" refX="5.5" refY="3" orient="auto"><path d="M0,0 L6.5,3 L0,6 Z" fill="currentColor"/></marker>
    <marker id="l10-a3r" markerWidth="9" markerHeight="9" refX="5.5" refY="3" orient="auto"><path d="M0,0 L6.5,3 L0,6 Z" fill="#d64545"/></marker>
    <marker id="l10-a3g" markerWidth="9" markerHeight="9" refX="5.5" refY="3" orient="auto"><path d="M0,0 L6.5,3 L0,6 Z" fill="#0fa07f"/></marker>
  </defs>
  <text x="440" y="25" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">Who holds the production credential decides the blast radius</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">

    <g stroke-width="2" stroke-linejoin="round">
      <rect x="12" y="42" width="424" height="392" rx="13" fill="#7f7f7f" fill-opacity="0.05" stroke="currentColor" stroke-opacity="0.35"/><rect x="444" y="42" width="424" height="392" rx="13" fill="#7f7f7f" fill-opacity="0.05" stroke="currentColor" stroke-opacity="0.35"/>
    </g>
    <text x="224" y="66" font-size="12.5" font-weight="700" text-anchor="middle" fill="#d64545">PUSH — CI deploys into the cluster</text><text x="656" y="66" font-size="12.5" font-weight="700" text-anchor="middle" fill="#0fa07f">PULL (GitOps) — the cluster deploys itself</text>

    <rect x="34" y="82" width="150" height="40" rx="7" fill="#3553ff" fill-opacity="0.13" stroke="#3553ff" stroke-width="1.8"/><text x="109" y="100" font-size="9.5" font-weight="700" text-anchor="middle" fill="currentColor">developer</text><text x="109" y="113" font-size="8" text-anchor="middle" fill="currentColor" opacity="0.85">merges to trunk</text>

    <rect x="466" y="82" width="150" height="40" rx="7" fill="#3553ff" fill-opacity="0.13" stroke="#3553ff" stroke-width="1.8"/><text x="541" y="100" font-size="9.5" font-weight="700" text-anchor="middle" fill="currentColor">developer</text><text x="541" y="113" font-size="8" text-anchor="middle" fill="currentColor" opacity="0.85">merges to trunk</text>

    <rect x="34" y="164" width="150" height="52" rx="7" fill="#e0930f" fill-opacity="0.14" stroke="#e0930f" stroke-width="1.8"/><text x="109" y="182" font-size="9.5" font-weight="700" text-anchor="middle" fill="currentColor">CI runner</text><text x="109" y="195" font-size="8" text-anchor="middle" fill="currentColor" opacity="0.85">builds, tests, pushes</text>
    <text x="109" y="208" font-size="8" text-anchor="middle" fill="currentColor" opacity="0.85">then runs kubectl apply</text>

    <rect x="466" y="164" width="150" height="52" rx="7" fill="#e0930f" fill-opacity="0.14" stroke="#e0930f" stroke-width="1.8"/><text x="541" y="182" font-size="9.5" font-weight="700" text-anchor="middle" fill="currentColor">CI runner</text><text x="541" y="195" font-size="8" text-anchor="middle" fill="currentColor" opacity="0.85">builds, tests, pushes</text>
    <text x="541" y="208" font-size="8" text-anchor="middle" fill="currentColor" opacity="0.85">then edits one YAML line</text>

    <rect x="252" y="164" width="164" height="52" rx="7" fill="#7c5cff" fill-opacity="0.14" stroke="#7c5cff" stroke-width="1.8"/><text x="334" y="182" font-size="9.5" font-weight="700" text-anchor="middle" fill="currentColor">registry</text><text x="334" y="196" font-size="8" text-anchor="middle" fill="currentColor" opacity="0.85">app@sha256:48fe3fe6…</text>
    <text x="334" y="209" font-size="8" text-anchor="middle" fill="currentColor" opacity="0.85">the immutable artifact</text>

    <rect x="684" y="164" width="164" height="52" rx="7" fill="#7c5cff" fill-opacity="0.14" stroke="#7c5cff" stroke-width="1.8"/><text x="766" y="182" font-size="9.5" font-weight="700" text-anchor="middle" fill="currentColor">registry + state repo</text><text x="766" y="196" font-size="8" text-anchor="middle" fill="currentColor" opacity="0.85">app@sha256:48fe3fe6…</text>
    <text x="766" y="209" font-size="8" text-anchor="middle" fill="currentColor" opacity="0.85">desired state, in git</text>

    <g fill="none" stroke="currentColor" stroke-width="1.5" opacity="0.8">
      <path d="M109 124 L 109 158" marker-end="url(#l10-a3)"/><path d="M541 124 L 541 158" marker-end="url(#l10-a3)"/><path d="M186 190 L 246 190" marker-end="url(#l10-a3)"/><path d="M618 190 L 678 190" marker-end="url(#l10-a3)"/>
    </g>

    <rect x="34" y="300" width="382" height="66" rx="9" fill="#d64545" fill-opacity="0.10" stroke="#d64545" stroke-width="2"/><text x="225" y="320" font-size="10" font-weight="700" text-anchor="middle" fill="currentColor">PRODUCTION CLUSTER</text><text x="225" y="336" font-size="8.5" text-anchor="middle" fill="currentColor" opacity="0.85">accepts writes from anything holding the kubeconfig</text>
    <text x="225" y="352" font-size="8.5" text-anchor="middle" fill="currentColor" opacity="0.85">no continuous reconciliation — drift is invisible until it bites</text>

    <rect x="466" y="300" width="382" height="66" rx="9" fill="#0fa07f" fill-opacity="0.10" stroke="#0fa07f" stroke-width="2"/><text x="657" y="320" font-size="10" font-weight="700" text-anchor="middle" fill="currentColor">PRODUCTION CLUSTER  ·  reconciling controller inside</text><text x="657" y="336" font-size="8.5" text-anchor="middle" fill="currentColor" opacity="0.85">watches git, compares to live state, converges — every 30s, forever</text>
    <text x="657" y="352" font-size="8.5" text-anchor="middle" fill="currentColor" opacity="0.85">this is lesson 07's control loop, pointed at deployment</text>

    <path d="M109 224 L 109 294" fill="none" stroke="#d64545" stroke-width="2.4" marker-end="url(#l10-a3r)"/><text x="118" y="252" font-size="9" font-weight="700" fill="#d64545">kubectl apply</text><text x="118" y="265" font-size="8" fill="#d64545" opacity="0.9">CI holds the</text><text x="118" y="277" font-size="8" fill="#d64545" opacity="0.9">prod kubeconfig</text>

    <path d="M700 294 L 700 224" fill="none" stroke="#0fa07f" stroke-width="2.4" marker-end="url(#l10-a3g)"/><text x="712" y="252" font-size="9" font-weight="700" fill="#0fa07f">the cluster PULLS</text><text x="712" y="265" font-size="8" fill="#0fa07f" opacity="0.9">outbound only — read</text><text x="712" y="277" font-size="8" fill="#0fa07f" opacity="0.9">access, no inbound path</text>

    <rect x="26" y="146" width="176" height="150" rx="10" fill="none" stroke="#d64545" stroke-width="2" stroke-dasharray="6 4"/><text x="109" y="140" font-size="9" font-weight="700" text-anchor="middle" fill="#d64545">BLAST RADIUS</text>

    <rect x="458" y="146" width="166" height="76" rx="10" fill="none" stroke="#e0930f" stroke-width="2" stroke-dasharray="6 4"/><text x="541" y="140" font-size="9" font-weight="700" text-anchor="middle" fill="#e0930f">BLAST RADIUS</text>

    <g fill="currentColor">
      <text x="34" y="388" font-size="9" font-weight="700" fill="#d64545">Everything inside the dashed box can reach production:</text><text x="34" y="402" font-size="8.5" opacity="0.9">every job, every third-party action, every workflow file, every</text><text x="34" y="414" font-size="8.5" opacity="0.9">maintainer — and any fork PR you let run with secrets in scope.</text>
      <text x="34" y="428" font-size="8.5" font-weight="700">Compromise CI once and you own the cluster.</text>

      <text x="466" y="388" font-size="9" font-weight="700" fill="#0fa07f">CI can only push an image and open a commit:</text><text x="466" y="402" font-size="8.5" opacity="0.9">no production credential exists outside the cluster at all, so</text><text x="466" y="414" font-size="8.5" opacity="0.9">there is none to steal. The remaining target is git write access,</text>
      <text x="466" y="428" font-size="8.5" font-weight="700">which is reviewable, signable and revertible.</text>
    </g>

    <text x="440" y="464" font-size="11.5" text-anchor="middle" fill="currentColor" font-weight="700">A standing production credential in CI is the single most valuable secret most orgs hold.</text><text x="440" y="484" font-size="10.5" text-anchor="middle" fill="currentColor" opacity="0.9">Pull deploys delete it. OIDC federation deletes the standing cloud key the same way.</text>
  </g>
</svg>
```

In a **push** deploy, CI holds a production cluster credential and writes into the cluster. The blast radius is the entire CI system: every job, every third-party action, every workflow file, every maintainer, and any fork PR that runs with secrets in scope. In a **pull** deploy, CI's most privileged capability is "push an image and open a commit". The cluster reaches *out* to fetch desired state, so there is no inbound path and **no production credential exists outside the cluster to be stolen.**

GitOps is not free, and the costs are worth naming. Anything that is not declarative fits badly — database migrations and one-off jobs need a separate story (Lesson 13). Secrets cannot go in git as plaintext, so you need sealed/encrypted secrets or an external secret operator ([Secrets Management & Rotation](../../07-auth-and-security/13-secrets-management-and-rotation/)). And "deployed" becomes asynchronous: your pipeline's commit succeeds well before the cluster has converged, so you need to *watch* the controller's sync status to know whether the release actually landed.

## Build It

[`code/pipeline.py`](code/pipeline.py) is five numbered arguments. Standard library only, seeded, about 4 seconds. Stage durations are seconds on a virtual clock — that is the one thing modelled rather than executed, so a 13-minute pipeline schedules exactly and instantly. Everything else is real: real topological scheduling, real content-derived cache keys, real critical-path arithmetic, real seeded Monte-Carlo simulation, real hashing.

**The scheduler** is an event loop over a bounded runner pool. Ready stages are dispatched longest-first, which is a genuine heuristic — the long pole should start as early as it can:

```python
while len(timeline) < len(PIPELINE) or running:
    ready = sorted((n for n, d in waiting.items() if not d and n not in started),
                   key=lambda n: (-durations[n], n))
    while free and ready:
        name = ready.pop(0)
        started.add(name)
        end = now + durations[name]
        heapq.heappush(running, (end, name))
        timeline.append((name, now, end))
        free -= 1
    now = running[0][0]
    while running and running[0][0] == now:
        _, finished = heapq.heappop(running)
        free += 1
        for deps in waiting.values():
            deps.discard(finished)
```

**The cache key** is the hermeticity argument in code, and the interesting half is `effective_inputs` — a stage reads its own declared inputs *plus everything its dependencies transitively read*. That single recursion is the entire invalidation cascade:

```python
def effective_inputs(name: str) -> Set[str]:
    """Own declared inputs, plus every input its dependencies transitively read."""
    stage = BY_NAME[name]
    acc: Set[str] = set(stage.inputs)
    for dep in stage.deps:
        acc |= effective_inputs(dep)
    return acc
```

**The critical path** is the standard forward/backward pass. Earliest finish forward through a topological order, latest finish backward from the project end, and slack is the difference; the path is the chain of zero-slack stages:

```python
late_finish: Dict[str, int] = {}
for name in reversed(order):
    if not successors[name]:
        late_finish[name] = project
    else:
        late_finish[name] = min(late_finish[x] - durations[x] for x in successors[name])
slack = {n: late_finish[n] - early_finish[n] for n in order}
```

**The flake simulation** runs one pipeline under one policy and returns whether it went green and how many job-runs it burned. The `defect` parameter is what makes the table honest — it injects a real bug and asks whether each policy still catches it:

```python
for _ in range(attempts_allowed):
    pipeline_red = False
    for job in range(N_JOBS):
        tries = 3 if policy == "retry-job" else 1
        passed = False
        for _ in range(tries):
            cost += 1
            ok = rng.random() < job_reliability(job)
            if job == REGRESSION_JOB and defect == "race" and rng.random() < RACE_MANIFEST:
                ok = False
            if ok:
                passed = True
                break
        gating = not (policy == "quarantine" and job == FLAKY_JOB)
        if not passed and gating:
            pipeline_red = True
```

Run it:

```bash
docker compose exec -T app python \
  phases/10-infrastructure-and-deployment/10-ci-cd-pipelines/code/pipeline.py
```

```console
== 1 · A PIPELINE IS A DAG, NOT A LIST OF SCRIPTS ==
  8 stages, 4 runners, cold cache (nothing has ever been built)
  STAGE                START    END  CACHE    TIMELINE (each block = 15s)
  deps-install            0s   180s  miss     |############
  build-image           180s   440s  miss     |            #################
  lint                  180s   225s  miss     |            ###
  typecheck             180s   275s  miss     |            ######
  unit-tests            180s   390s  miss     |            ##############
  integration-tests     440s   740s  miss     |                             ####################
  security-scan         440s   560s  miss     |                             ########
  push-artifact         740s   780s  miss     |                                              ##
  total work across all stages :  1250s  (20.8 min of runner time billed)
  wall time on 4 runners       :   780s  (13.0 min the developer waits)
  parallelism actually achieved : 1.60x
  4 stages ran concurrently at t=180s; the graph, not the config, decided that.

== 2 · CACHING, MEASURED: THE INVALIDATION CASCADE ==
  cache keys are H(stage + tool version + content of every effective input).
  three changes, each one file, each a bigger blast radius:

  CHANGE                         deps-i lint   typech unit-t build- integr securi push-a
  edit tests/unit/test_cart.py   HIT    HIT    HIT    miss   HIT    HIT    HIT    miss
  edit src/app/handlers.py       HIT    miss   miss   miss   miss   miss   miss   miss
  edit requirements.lock         miss   miss   miss   miss   miss   miss   miss   miss

  CHANGE                         STAGES    WORK SKIPPED     WALL SPEED-UP
  (cold build, nothing cached)       8/8   1250s      0s     780s    1.00x
  edit tests/unit/test_cart.py       2/8    280s   1000s     255s    3.06x
  edit src/app/handlers.py           7/8   1075s    180s     605s    1.29x
  edit requirements.lock             8/8   1250s      0s     780s    1.00x
  a test-file edit skipped 80% of the work and cut wall time 67%.
  a source edit skipped only 14% of the work yet cut wall time 22% --
  because the one stage it DID skip (deps-install) sits on the critical path.
  one line in requirements.lock invalidated 8/8 stages: the manifest is an
  input to deps-install, and every other stage transitively reads it.
  (a cache HIT is charged 5s here -- restoring a cache still moves bytes;
   a cache 'hit' that costs more than the stage is a cache you should delete.)

== 3 · THE CRITICAL PATH IS THE ONLY STAGE LIST THAT MATTERS ==
  critical path : deps-install -> build-image -> integration-tests -> push-artifact
  its length    : 780s   total work across all stages: 1250s  (ratio 1.60x)

  STAGE                SECONDS   SLACK   ON PATH?
  deps-install            180s      0s   CRITICAL
  lint                     45s    515s          -
  typecheck                95s    465s          -
  unit-tests              210s    350s          -
  build-image             260s      0s   CRITICAL
  integration-tests       300s      0s   CRITICAL
  security-scan           120s    180s          -
  push-artifact            40s      0s   CRITICAL

  more runners never beat the critical path:
  RUNNERS        WALL
  1            1250s
  2             780s  <- floor reached; every runner after this is idle money
  3             780s
  4             780s
  6             780s
  8             780s

  now halve one stage's duration, twice -- once off the path, once on it:
  SCENARIO                                       WORK     WALL     SAVED
  baseline                                      1250s     780s        0s
  halve unit-tests (not on path)                1145s     780s        0s
  halve integration-tests (CRITICAL)            1100s     630s      150s
  halving unit-tests removed 105s (8%) of billed work and saved the
  developer ZERO seconds. Halving integration-tests removed 150s and
  saved exactly 150s. Optimise the path or do not bother.

== 4 · FLAKY TESTS ARE ARITHMETIC, NOT BAD LUCK ==
  P(green pipeline) = p^n for n independent jobs each p reliable
  PER-JOB p      n = 5 jobs              n = 10 jobs             n = 20 jobs
                 analytic   simulated    analytic   simulated    analytic   simulated
  0.99              95.1%      95.2%        90.4%      90.3%        81.8%      81.8%
  0.95              77.4%      77.2%        59.9%      59.8%        35.8%      35.9%
  0.90              59.0%      59.3%        34.9%      35.1%        12.2%      12.1%
  (60,000 runs per cell, seeded; simulation tracks the analytic value to <0.5pp)
  a 20-job pipeline of 95%-reliable jobs is green 35.8% of the time.
  nobody wrote a bug. Every job is 'basically fine'. The pipeline is not.

  now one concrete pipeline: 20 jobs, job 12 ('integration-shard-3') is
  70% reliable, the other 19 are 99.8%. Four responses:

  RESPONSE                            GREEN  JOB-RUNS   det. bug   RACE 40% bug in the
                                   on clean   per run     caught     caught  flaky job
  do nothing                          67.7%      20.0     100.0%      59.5%     100.0%
  press re-run (whole pipeline x3)    96.6%      28.6     100.0%      21.0%     100.0%
  auto-retry each failed job x3       97.4%      20.4     100.0%       9.1%     100.0%
  quarantine job 12, then fix         96.3%      20.0     100.0%      42.1%       3.7%
  'caught' = the change was blocked and never merged.
  a deterministic regression survives nothing: every response catches it 100%.
  read the RACE column instead -- that is what retries silently trade away.

== 5 · BUILD ONCE, PROMOTE THE SAME DIGEST ==
  built ONCE on commit. build-image cache key 4b438cb6d8fa == this artifact:
  artifact digest: sha256:48fe3fe6596779c797b22dc364716e471b3eb0608a458cbea92bf87916efca24

  ENV       ARTIFACT DIGEST            CONFIG HASH        RELEASE ID         GATE
  dev       sha256:48fe3fe6596779c797b 3e2b90f12b47c560   rel-e601a6c92d0c   auto on merge
  staging   sha256:48fe3fe6596779c797b 429ac0e6b9179d06   rel-c2e00caa33bc   auto, smoke tests
  prod      sha256:48fe3fe6596779c797b 042781866f6b6484   rel-7c05407b84d8   manual approval
  1 artifact digest, 3 distinct release ids. Only the config moved.
  the bytes that passed integration-tests are the bytes serving production.

  THE ANTI-PATTERN -- a 'build' step inside each environment's job:
  ENV       ARTIFACT DIGEST                                      MATCHES TESTED?
  dev       sha256:c9eab2a1fd1ad8b490a0f5c3c8b26024c01413052ab88 NO
  staging   sha256:8d33c9aaac6e4bc805c71f91b28891c7e1af692b8664c NO
  prod      sha256:ff9e2ac1d72f071b87ba569d094cd6c2cb1f3eb39d54c NO
  3 rebuilds, 3 distinct digests, 0 matching the artifact that was tested.
```

Read what each section proves.

**Section 1** separates the two numbers. **1,250 s of billed runner time, 780 s of developer wait, parallelism 1.60×.** Four stages run concurrently at t=180 s — and note that nobody configured that. The graph implied it; the scheduler discovered it. If you find yourself hand-ordering stages in a config file, you are doing by hand what the dependency edges should be doing for you, and you will get it wrong the moment someone adds a stage.

**Section 2** is the cache doing three very different things to three one-line diffs. Editing a **test file** invalidates `unit-tests` (which reads it) and `push-artifact` (which transitively depends on it) — 2 of 8 stages, **80% of work skipped, 255 s wall, 3.06× faster**. Editing a **source file** invalidates 7 of 8 and skips only **14% of the work** — yet still cuts wall time **22%**, because the one stage it skipped, `deps-install`, is on the critical path. That inversion is worth sitting with: percentage of work skipped and percentage of time saved are not the same quantity and can move in opposite directions. Editing one line of **`requirements.lock`** invalidates **8 of 8** and saves nothing, because the manifest is an input to `deps-install` and every other stage transitively reads it. Same size diff, three completely different pipelines.

**Section 3** is the argument the whole lesson turns on. The critical path is 780 s against 1,250 s of total work — a ratio of **1.60×**, which is also the hard ceiling on what parallelism can ever buy you here. The runner table makes it concrete: **1 runner → 1,250 s, 2 runners → 780 s, and 3, 4, 6, and 8 runners → 780 s.** The floor is reached at two. Then the two halvings. `unit-tests` has 350 s of slack; halving it removes **105 s of billed work and saves the developer exactly 0 seconds.** `integration-tests` has none; halving it saves **exactly 150 s**. Both are "make a test suite twice as fast", a quarter of engineering effort either way. One of them is invisible to every human being.

**Section 4** is the trust argument. The analytic and simulated columns agree to under 0.5 percentage points across 60,000 runs per cell, so *pⁿ* is not a metaphor: **20 jobs at 95% each is green 35.8% of the time.** Then the policy table, and the column to read is the race. Doing nothing catches a 40%-manifesting concurrency bug **59.5%** of the time. Auto-retrying each failed job three times catches it **9.1%** — and it looks *better* on every metric a dashboard shows you, at 97.4% green for only 1.02× compute. That is the trap in one row: the response that most improves your green rate is the one that most degrades your ability to catch real defects, and nothing in your CI UI will tell you. Quarantine holds **42.1%** race detection at 1.00× compute, and pays for it honestly in the last column — a real bug inside the quarantined job is caught **3.7%** of the time.

**Section 5** is the payoff. One artifact digest, three configurations, **3 distinct release ids** — the `release = build + config` identity from Lesson 05, now produced by a pipeline. The digest string is byte-identical across all three rows; only the config hash and the gate differ. Then the anti-pattern, from **identical source**: **3 rebuilds, 3 distinct digests, 0 matching the artifact that was tested.** Nothing exotic caused that — a `--build-arg` and a timestamp. Every test result you have refers to bytes that are in no environment.

## Use It

### A real pipeline, with the shape above

GitHub Actions is the example; the shape maps to GitLab CI, CircleCI, Buildkite and Jenkins with different nouns. Read the comments — each one names the primitive it implements.

```yaml
name: build-and-promote
on:
  push: { branches: [main] }
  pull_request:

# Least privilege by default. id-token: write is what enables OIDC federation;
# it does NOT grant cloud access on its own — the cloud-side trust policy does.
permissions:
  contents: read
  id-token: write
  packages: write

jobs:
  # ---- fast gate: everything with slack, in parallel, no secrets in scope ----
  test:
    runs-on: ubuntu-24.04
    strategy:
      fail-fast: false          # one shard failing must not hide the others
      matrix:
        shard: [1, 2, 3, 4]     # test splitting: 4 shards of one suite
    steps:
      # Pin third-party actions by commit SHA. A tag is a mutable pointer
      # someone else controls, and this step runs with your job's permissions.
      - uses: actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683  # v4.2.2
      - uses: actions/setup-python@0b93645e9fea7318ecaed2b359559ac225c90a2b # v5.3.0
        with:
          python-version: '3.12'
          cache: pip
          # THE cache key: derived from the content of the lock file. Not the
          # branch, not the date. This is section 2's invalidation cascade —
          # change one line here and every downstream stage rightly misses.
          cache-dependency-path: requirements.lock
      - run: pip install -r requirements.lock
      - run: pytest --shard-id=${{ matrix.shard }} --num-shards=4 --durations=25

  # ---- build ONCE. The only job that produces an artifact. ----
  build:
    runs-on: ubuntu-24.04
    outputs:
      digest: ${{ steps.push.outputs.digest }}   # the promotion handle
    steps:
      - uses: actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683
      - uses: docker/setup-buildx-action@c47758b77c9736f4b2ef4073d4d51994fabfe349 # v3.7.1
      - uses: docker/login-action@9780b0c442fbb1117ed29e0efdff1e18412f7567 # v3.3.0
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}   # scoped to this repo, expires with the job
      - id: push
        uses: docker/build-push-action@4f58ea79222b3b9dc2c8bbdd6debcef730109a75 # v6.9.0
        with:
          push: ${{ github.event_name != 'pull_request' }}
          tags: ghcr.io/${{ github.repository }}:${{ github.sha }}
          # Layer cache keyed on content, held in the registry so it is shared
          # across runners rather than trapped on one machine.
          cache-from: type=registry,ref=ghcr.io/${{ github.repository }}:buildcache
          cache-to: type=registry,ref=ghcr.io/${{ github.repository }}:buildcache,mode=max
          provenance: true      # SLSA build provenance, attached to the digest
          sbom: true            # SBOM = software bill of materials (Lesson 04)

  # ---- promote the DIGEST. No build step exists below this line. ----
  deploy-staging:
    needs: [test, build]
    if: github.ref == 'refs/heads/main'
    runs-on: ubuntu-24.04
    environment: staging
    steps:
      # OIDC federation: no AWS_ACCESS_KEY_ID exists anywhere in this repo.
      # The runner presents a signed token asserting repo, ref and environment;
      # AWS's trust policy checks those claims and returns a ~1h credential.
      - uses: aws-actions/configure-aws-credentials@e3dd6a429d7300a6a4c196c26e071d42e0343502 # v4.0.2
        with:
          role-to-assume: arn:aws:iam::111122223333:role/deploy-staging
          aws-region: eu-west-1
      - run: ./deploy.sh staging "${{ needs.build.outputs.digest }}"

  deploy-prod:
    needs: [deploy-staging, build]
    runs-on: ubuntu-24.04
    # Required reviewers live on the ENVIRONMENT, not in this file — so a PR
    # cannot edit its own approval away. This is continuous delivery's button.
    environment: production
    steps:
      - uses: aws-actions/configure-aws-credentials@e3dd6a429d7300a6a4c196c26e071d42e0343502
        with:
          role-to-assume: arn:aws:iam::111122223333:role/deploy-prod
          aws-region: eu-west-1
      # The SAME digest staging ran. Not a tag, not a rebuild, not "latest".
      - run: ./deploy.sh production "${{ needs.build.outputs.digest }}"
```

Three details carry most of the weight. `build` is the **only** job that produces an artifact, and it exports `digest` as an output — that string is the promotion handle, and every job downstream consumes it rather than referring to a tag. **No deploy job contains a build step**, which is the rule from section 5 expressed as file structure rather than as a policy document. And `environment: production` is where required reviewers and deployment branch restrictions are configured — deliberately *outside* the workflow file, so a pull request cannot modify the gate that governs it.

The corresponding cloud-side trust policy is the other half of OIDC, and the `sub` condition is the whole security property:

```json
{
  "Effect": "Allow",
  "Principal": { "Federated": "arn:aws:iam::111122223333:oidc-provider/token.actions.githubusercontent.com" },
  "Action": "sts:AssumeRoleWithWebIdentity",
  "Condition": {
    "StringEquals": {
      "token.actions.githubusercontent.com:aud": "sts.amazonaws.com",
      "token.actions.githubusercontent.com:sub": "repo:acme/api:environment:production"
    }
  }
}
```

Match on the **full** subject claim. A wildcard such as `repo:acme/*` grants every repository in the organisation the right to assume your production role, and a condition on `repo:acme/api:*` grants it to every branch, including one an attacker just pushed. The claim format is defined by OpenID Connect Core 1.0; what varies per provider is which claims are populated.

### Branch protection, required checks, and merge queues

A pipeline that can be bypassed is documentation. Make the checks structural:

- **Require pull requests** to the release branch; no direct pushes, no force pushes.
- **Require named status checks** to pass. Not "CI passed" in the abstract — the specific job names, so deleting a job from the workflow does not silently satisfy the requirement.
- **Require branches to be up to date** before merging, which is what makes the next item necessary.
- **Include administrators.** A rule you can bypass is a rule that gets bypassed at 03:00, by the person under the most pressure, in the situation with the least review.

Then **merge queues**, which exist for a failure mode that is not obvious until it bites you. Two pull requests each pass CI against `main`. Individually green. Merged together, red — because PR A renamed a function and PR B added a new call to the old name, and neither branch ever contained both changes. **Testing a change against the branch it was written from does not test the state that will exist after it merges.** A merge queue serialises this: it builds the *prospective* merge result, tests that, and merges only if it is green, batching where it can and bisecting a failed batch to eject the guilty change. It is the direct answer to "we require branches to be up to date" turning into every author rebasing and re-running a 40-minute pipeline in a loop whenever the repository is busy.

### Argo CD and Flux: pull-based GitOps

Two mature controllers implement the pull model. Argo CD's `Application` names a source repo and a destination cluster:

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: checkout-api
  namespace: argocd
spec:
  project: default
  source:
    repoURL: https://github.com/acme/deploy-state.git
    targetRevision: main          # desired state lives here, reviewed like code
    path: envs/production
  destination:
    server: https://kubernetes.default.svc
    namespace: checkout
  syncPolicy:
    automated:
      prune: true                 # resources deleted from git are deleted here
      selfHeal: true              # THE control loop: manual kubectl edits revert
    syncOptions: [CreateNamespace=true]
```

`selfHeal: true` is Lesson 07's control loop in one line: the controller does not merely apply once, it continuously reconciles, so out-of-band changes are corrected rather than merely detected. `prune: true` is the other half and deserves a moment of fear — deleting a file from git deletes the resource from the cluster. That is correct, it is what "git is the desired state" means, and it will delete something you did not intend the first time somebody moves a directory.

Flux expresses the same thing as a set of small controllers (`GitRepository`, `Kustomization`, `HelmRelease`, `ImagePolicy`). Both support automated image updates: a controller watches the registry, and when a new digest matches your policy, it **writes a commit back to the state repo**. Your pipeline never touches the cluster at all; it pushes an image, and the update to production arrives as a reviewable commit.

Either way, the promotion primitive is one line in git:

```yaml
# envs/production/kustomization.yaml — promotion is this diff, and only this diff
images:
  - name: ghcr.io/acme/api
    digest: sha256:48fe3fe6596779c797b22dc364716e471b3eb0608a458cbea92bf87916efca24
```

Promoting staging to production is copying that digest from one directory to another. It is a pull request. It has an author, a reviewer, a timestamp and a revert button, and it cannot possibly rebuild anything.

### Making it faster, in priority order

1. **Measure the critical path first.** Most CI providers show per-job duration; almost none show the path. Compute it — the forward/backward pass in section 3 is thirty lines. Optimising off-path stages is the default mistake and it is free to avoid.
2. **Cache on content hashes.** Dependencies keyed on the lock file's hash; build layers keyed on their inputs. Store the cache where every runner can reach it, not on one machine's local disk.
3. **Split tests, then balance by measured duration.** Sharding by file count gives you shards that finish at wildly different times, and a matrix job's wall time is its *slowest* shard. Record per-test durations and pack shards by time (`pytest --durations`, `--splitting-algorithm=least_duration`, or the equivalent).
4. **Run only what the change affects** — for a monorepo, a build graph tool (Bazel, Nx, Turborepo, Pants) that knows which targets a file feeds. This is `effective_inputs` from the Build It, at repository scale.
5. **Right-size runners and pre-bake their images.** A job that spends 90 s installing the same toolchain on every run should have that toolchain in the runner image.
6. **Then, and only then, buy concurrency.** Our pipeline hits its floor at **2 runners**; the 3rd through 8th changed wall time by 0 seconds.

### Production rules

- **Build once, promote the digest.** One build job per commit, its digest exported as an output, and no build step anywhere downstream. If a deploy job can build, someone will eventually ship bytes that no test ever saw.
- **Keep the critical path under ten minutes.** Not total work — the path. Beyond it people context-switch, and the pipeline stops being a feedback loop and becomes a queue.
- **Cache on content hashes, never on branch names or dates.** And measure your restore times: a cache that costs more than the stage it skips is a cache to delete.
- **Quarantine flakes; never retry blindly.** A blanket retry took race detection from 59.5% to 9.1% while making every dashboard look better. Quarantine with a named owner and a deadline, track the count as a first-class metric, and treat a rising flake count as a broken pipeline rather than as weather.
- **Never put a long-lived cloud key in CI.** Use OIDC federation with a trust policy matched on the full subject claim. If your provider cannot do it, use short-lived credentials issued per job, and rotate on a schedule you actually keep.
- **Require the same checks for everyone, including yourself.** Enable "include administrators". The bypass exists for emergencies, and emergencies are exactly when the checks are most valuable.
- **Prefer pull-based deploys for production.** If the cluster pulls, no production credential exists outside it. If you must push, isolate the credential in a job that runs nothing but the deploy, gated on an environment with required reviewers.
- **Never run fork pull-request code with secrets in scope**, and pin third-party actions by commit SHA. A build step is arbitrary code execution with your job's permissions.

## Think about it

1. Your critical path is 13 minutes and `integration-tests` (300 s) is on it. You can shard it four ways, but each shard needs its own database, and provisioning one takes 90 s. Compute the new critical path under 4 runners and under 8. At what shard count does provisioning overtake the saving, and what does that imply about the relationship between parallelism and per-shard fixed cost?
2. Auto-retrying failed jobs raised the green rate to 97.4% and dropped race detection to 9.1%. Design a retry policy that captures some of the first without the second. What must the CI system record for your policy to be enforceable, and what class of defect will still get through?
3. A team argues that rebuilding per environment is safe because they pin the base image by digest and use a lock file, so builds are reproducible. Grant them both premises. List what can still differ between two builds of the same commit, and explain what promotion gives you that reproducibility alone does not.
4. Your `deploy-prod` job assumes a role via OIDC with `sub` matched to `repo:acme/api:environment:production`. An engineer opens a PR that adds a step to that workflow file printing the assumed credentials. Trace what happens, and identify every control that has to be in place for the answer to be "nothing". Which single one of them is the last line of defence?
5. You move to pull-based GitOps with `selfHeal: true`. It is 03:00, production is down, and the fix is a one-line change to a resource limit. Describe what happens if you `kubectl edit` it, and design the break-glass procedure you would want to exist — including what stops it from becoming the normal path within a month.

## Key takeaways

- **Total work and wall time are different numbers, and only one of them is your wait.** The pipeline billed **1,250 s of runner time** and made the developer wait **780 s** — a parallelism of **1.60×**, which is also the hard ceiling on what concurrency can buy. Wall time hit its floor at **2 runners**; the 3rd through 8th each changed it by exactly **0 seconds**.
- **Optimise the critical path or do not bother.** Halving `unit-tests` (350 s of slack) removed **105 s of billed work and saved zero seconds**. Halving `integration-tests` (0 slack) removed 150 s and saved **exactly 150 s**. Identical effort; one of the two is invisible to every human being who uses the pipeline.
- **Cache keys must come from input content, and the blast radius is not the diff size.** Editing one test file skipped **80% of the work and cut wall time 67% (3.06×)**; editing one source file skipped only **14% of the work yet still cut wall time 22%**, because the stage it skipped was on the path; editing one line of the dependency manifest invalidated **8 of 8 stages** and saved nothing. A key that depends on the machine can never hit on another machine.
- **Flakiness is arithmetic and retries buy green by selling detection.** Twenty jobs at 95% reliability each are green **35.8%** of the time with nobody having written a bug. Auto-retrying failed jobs raised green to **97.4%** while dropping detection of a 40%-manifesting race from **59.5% to 9.1%** — and pressing re-run costs **1.43× compute** for a worse result. Quarantine holds **42.1%** detection at **1.00× compute**, and pays honestly: a real bug inside the quarantined job is caught **3.7%** of the time.
- **Build once and promote the digest, or your test results describe bytes that are nowhere.** One artifact plus three configs produced **1 digest and 3 distinct release ids**, with the digest byte-identical across every environment. Rebuilding per environment from **identical source** produced **3 distinct digests, 0 matching the tested artifact** — a build arg and a timestamp were enough.
- **Who holds the production credential decides the blast radius.** A long-lived cloud key in CI variables is reachable by every job, every third-party action and every fork PR that runs with secrets in scope. **OIDC federation removes the standing secret entirely** — a short-lived token whose claims the cloud provider checks — and pull-based GitOps removes the production credential from CI altogether, because the cluster reaches out and nothing reaches in.

Next: [Deployment Strategies: Rolling, Blue-Green & Canary](../11-deployment-strategies/) — you can now produce one trustworthy artifact and move it to an environment on purpose; the next question is how to replace what is running with it while people are using it.
