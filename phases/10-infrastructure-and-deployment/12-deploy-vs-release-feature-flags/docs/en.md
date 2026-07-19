# Deploy ≠ Release: Feature Flags & Progressive Delivery

> A rollback that cannot happen: your deploy carried 40 merged changes, one of them is erroring, and reverting removes all 40 — including the fix another team shipped this morning. The cause is not the bad change. It is that **deploy and release were the same event**, so the only lever you own is all-or-nothing. Measured here: separating them takes time-to-mitigate from **304 seconds to 4.3 seconds (71×)**, and doing the separation wrong — re-rolling the dice on every request — turns a 10% rollout into one that reaches **98.52% of your users**.

**Type:** Build
**Languages:** Python
**Prerequisites:** [Deployment Strategies: Rolling, Blue-Green & Canary](../11-deployment-strategies/), [Config, Environments & the Twelve-Factor App](../05-config-and-twelve-factor/)
**Time:** ~70 minutes

## The Problem

It is 14:31. The graph that matters — errors on `POST /checkout` — went from flat to 4% eleven minutes ago, and eleven minutes ago is exactly when your deploy finished. So you know what did it. You are already typing the rollback command.

Then someone asks the question that costs you the next four hours.

**"What else is in that build?"**

You look. The artifact you are about to revert contains **40 merged pull requests**, because your team merges to `main` all week and deploys on Tuesday. One of them is the checkout change that is erroring. Another is a fix the fraud team shipped this morning for a bug that was letting through duplicate refunds. Another is a database migration. Another is a copy change that legal asked for in writing. You cannot revert one of them. The unit of rollback is the artifact, and the artifact is all 40.

So you take the meeting. Someone proposes a forward fix, which needs a build, a test run, a review, and a deploy — call it 25 minutes on a good day, and this is not a good day. Someone else proposes reverting anyway and telling the fraud team. Someone else asks whether the migration is reversible, and nobody is sure. Meanwhile the errors continue, because the discussion is not a mitigation.

Here is the thing to notice. **Nothing in that story is a technical failure.** Continuous integration worked. The tests passed. The rollout was a healthy rolling update. The artifact is byte-identical to the one that passed staging. What failed is a *coupling*: the moment code entered production was also the moment users could reach it, so every change inherited the blast radius of every other change in the same batch, and the only control surface anyone had was a binary — this artifact, or the previous one.

That coupling produces a second, slower failure too. If shipping is risky, teams ship less often. If teams ship less often, each ship contains more changes. If each ship contains more changes, shipping is riskier. The end state of that loop is the **three-month feature branch**, where the merge is itself the outage: months of divergence, a conflict resolution nobody can review, and a first-ever production exercise of thousands of lines on the day of the release. The branch was created to reduce risk. It concentrated it into a single event and then hid it until that event.

The way out is not better testing. It is to notice that "the code is running in production" and "users are getting this behaviour" are two different facts, and to stop shipping them as one.

## The Concept

### Deploy is not release

Two words that get used interchangeably, and separating them is the whole lesson:

- **Deploy** — the artifact is running in production. The process started, the health checks pass, it is taking traffic. The new code path exists in the binary. **Nobody can reach it.**
- **Release** — some population of users is now served by that code path. Exposure, not installation.

When those are the same event, you have one lever with two positions. When they are separate, you have two levers, and they move at completely different speeds and costs.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 470" width="100%" style="max-width:840px" role="img" aria-label="A timeline with two independent lanes. The upper lane shows six deploys landing over nine days, every one of them dark: the code is in production but no user can reach it. The lower lane shows exposure ramping separately from zero to one percent to ten percent to fifty percent. An incident on the new path at fifty percent exposure is mitigated by dropping exposure back to zero, an exposure change rather than a deploy, so all six builds stay in production. Exposure later resumes and finishes at one hundred percent, fully released. A pair of boxes underneath contrasts the coupled model, where deploy equals release and one lever reverts forty changes, with the decoupled model of two independent levers.">
  <defs>
    <marker id="l12-a1" markerWidth="10" markerHeight="10" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker>
    <marker id="l12-a1r" markerWidth="10" markerHeight="10" refX="6.5" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#d64545"/></marker>
  </defs>
  <text x="440" y="24" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">Two lanes, two levers: the artifact moves, the exposure moves separately</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">

    <text x="110" y="48" font-size="10" fill="currentColor" opacity="0.85">six deploys land — every one of them DARK: in production, reachable by nobody</text>
    <g fill="none" stroke-width="1.8">
      <rect x="135" y="60" width="34" height="22" rx="5" fill="#7c5cff" fill-opacity="0.16" stroke="#7c5cff"/>
      <rect x="220" y="60" width="34" height="22" rx="5" fill="#7c5cff" fill-opacity="0.16" stroke="#7c5cff"/>
      <rect x="315" y="60" width="34" height="22" rx="5" fill="#7c5cff" fill-opacity="0.16" stroke="#7c5cff"/>
      <rect x="440" y="60" width="34" height="22" rx="5" fill="#7c5cff" fill-opacity="0.16" stroke="#7c5cff"/>
      <rect x="570" y="60" width="34" height="22" rx="5" fill="#7c5cff" fill-opacity="0.16" stroke="#7c5cff"/>
      <rect x="730" y="60" width="34" height="22" rx="5" fill="#7c5cff" fill-opacity="0.16" stroke="#7c5cff"/>
    </g>
    <g fill="#7c5cff" font-size="9.5" font-weight="700" text-anchor="middle">
      <text x="152" y="75">d1</text><text x="237" y="75">d2</text><text x="332" y="75">d3</text>
      <text x="457" y="75">d4</text><text x="587" y="75">d5</text><text x="747" y="75">d6</text>
    </g>
    <g fill="currentColor">
      <text x="8" y="66" font-size="10" font-weight="700">DEPLOY</text>
      <text x="8" y="79" font-size="8.5" opacity="0.7">the artifact</text>
      <text x="8" y="236" font-size="10" font-weight="700">RELEASE</text>
      <text x="8" y="249" font-size="8.5" opacity="0.7">% of users</text>
      <text x="8" y="261" font-size="8.5" opacity="0.7">who can</text>
      <text x="8" y="273" font-size="8.5" opacity="0.7">reach the</text>
      <text x="8" y="285" font-size="8.5" opacity="0.7">new path</text>
    </g>

    <g fill="none" stroke="currentColor" stroke-width="1.1" stroke-dasharray="3 4" opacity="0.3">
      <path d="M152 84 L 152 322"/><path d="M237 84 L 237 322"/><path d="M332 84 L 332 322"/>
      <path d="M457 84 L 457 322"/><path d="M587 84 L 587 322"/><path d="M747 84 L 747 322"/>
    </g>

    <path d="M110 322 L250 322 L250 292 L370 292 L370 258 L500 258 L500 218 L620 218 L620 322 Z" fill="#e0930f" fill-opacity="0.13" stroke="none"/>
    <path d="M800 322 L800 178 L856 178 L856 322 Z" fill="#0fa07f" fill-opacity="0.15" stroke="none"/>

    <path d="M110 322 L250 322 L250 292 L370 292 L370 258 L500 258 L500 218 L620 218" fill="none" stroke="#e0930f" stroke-width="2.8" stroke-linejoin="round"/>
    <path d="M620 218 L620 322 L800 322" fill="none" stroke="#d64545" stroke-width="2.8" stroke-linejoin="round"/>
    <path d="M800 322 L800 178 L856 178" fill="none" stroke="#0fa07f" stroke-width="2.8" stroke-linejoin="round"/>

    <path d="M110 322 L 862 322" fill="none" stroke="currentColor" stroke-width="1.4" marker-end="url(#l12-a1)"/>
    <path d="M110 322 L 110 168" fill="none" stroke="currentColor" stroke-width="1.4"/>
    <g fill="currentColor" font-size="9" text-anchor="end" opacity="0.75">
      <text x="104" y="182">100%</text><text x="104" y="222">50%</text><text x="104" y="262">10%</text><text x="104" y="296">1%</text><text x="104" y="326">0%</text>
    </g>
    <g fill="currentColor" font-size="9" opacity="0.75">
      <text x="110" y="340">day 1</text><text x="300" y="340" text-anchor="middle">day 3</text><text x="490" y="340" text-anchor="middle">day 5</text><text x="680" y="340" text-anchor="middle">day 7</text><text x="856" y="340" text-anchor="end">day 9</text>
    </g>

    <path d="M620 138 L 620 214" fill="none" stroke="#d64545" stroke-width="1.6" stroke-dasharray="5 4"/>
    <circle cx="620" cy="218" r="5" fill="#d64545"/>
    <text x="632" y="134" font-size="10" font-weight="700" fill="#d64545">14:31 · the new path starts erroring</text>

    <text x="126" y="192" font-size="10.5" font-weight="700" fill="#d64545">mitigation = an EXPOSURE change: 50% -&gt; 0% in 4.3 s</text>
    <text x="126" y="209" font-size="9.5" fill="currentColor" opacity="0.9">No deploy, no build, no approval queue. Builds d1-d6</text>
    <text x="126" y="223" font-size="9.5" fill="currentColor" opacity="0.9">stay live, so no other team's change is reverted.</text>
    <path d="M470 228 C 540 246, 566 262, 606 274" fill="none" stroke="#d64545" stroke-width="1.8" marker-end="url(#l12-a1r)"/>

    <text x="256" y="286" font-size="9" fill="currentColor" opacity="0.8">internal staff</text>
    <text x="376" y="252" font-size="9" fill="currentColor" opacity="0.8">measured ramp</text>
    <text x="636" y="314" font-size="9" fill="#d64545" font-weight="700">dark again while d6 ships</text>
    <text x="812" y="172" font-size="9.5" font-weight="700" fill="#0fa07f">RELEASED</text>

    <g fill="none" stroke-width="1.8">
      <rect x="110" y="360" width="360" height="62" rx="9" fill="#d64545" fill-opacity="0.09" stroke="#d64545"/>
      <rect x="496" y="360" width="360" height="62" rx="9" fill="#0fa07f" fill-opacity="0.10" stroke="#0fa07f"/>
    </g>
    <g fill="currentColor">
      <text x="126" y="379" font-size="10.5" font-weight="700" fill="#d64545">COUPLED: deploy == release</text>
      <text x="126" y="395" font-size="9.5" opacity="0.9">One lever. 40 merged changes ship together,</text>
      <text x="126" y="409" font-size="9.5" opacity="0.9">so mitigating one of them reverts all 40.</text>
      <text x="512" y="379" font-size="10.5" font-weight="700" fill="#0fa07f">DECOUPLED: two levers</text>
      <text x="512" y="395" font-size="9.5" opacity="0.9">Deploy continuously and dark; expose one</text>
      <text x="512" y="409" font-size="9.5" opacity="0.9">change at a time; mitigate without a build.</text>
    </g>
    <text x="440" y="448" font-size="11" text-anchor="middle" fill="currentColor" opacity="0.9">Deploy puts code in production. Release lets a user reach it. Keeping them the same event is what makes rollback all-or-nothing.</text>
  </g>
</svg>
```

Four consequences fall out of the split, and they are worth stating individually because teams usually adopt the mechanism and miss two of them.

**Batch size collapses.** Merging becomes safe, because merging no longer exposes anything. You go from a Tuesday artifact containing 40 changes to a continuous stream of artifacts containing one or two. Lesson 11 measured what a small blast radius buys you during a rollout; this is how you get one in the first place.

**Exposure becomes a dial, not a switch.** Internal staff, then 1%, then 10%, then 50%, then everyone — each step a measurement, not a leap of faith. And a dial turns both ways.

**Mitigation stops requiring a deploy.** This is the one that changes what an incident feels like. If your only tool is "ship a new artifact", your time-to-mitigate is the length of your deploy pipeline no matter how fast you diagnose. If you can change exposure, the pipeline is not in the critical path at all.

**Deployment becomes boring.** A deploy that changes nothing observable is a deploy you can do at 3pm on a Tuesday, forty times a day, without a change advisory board. That is the point. **Dark launching** — shipping code that runs in production but affects nobody — is the practice described in Humble and Farley's *Continuous Delivery* (2010) as the prerequisite for continuous release, and it is the reason the strategy exists at all.

### Trunk-based development is the practice this enables

If merging is safe, long-lived branches lose their purpose. **Trunk-based development** means every engineer merges to one shared branch at least daily, and the branch is always releasable. The half-finished feature lives in production behind a flag that is off, instead of living on a branch that is diverging.

That trade is real and worth naming honestly. You have moved the complexity from *version control* to *runtime*. Instead of an unmerged branch you now have an `if` statement in production, and unlike a branch, that `if` is reachable by real users if someone gets a targeting rule wrong. The reason this trade is still overwhelmingly worth it: a merge conflict resolved after three months is resolved by someone reading unfamiliar code under deadline pressure, while a flag is a named, observable, reversible object with an owner. One of those two things you can turn off.

For a change too large to hide behind a single boolean — swapping a storage engine, replacing a pricing algorithm — the technique is **branch by abstraction**: introduce an interface over the old implementation, add the new implementation behind the same interface, switch between them with a flag, then delete the loser. The abstraction lives in the trunk from day one, so there is never a big-bang merge.

### Four kinds of flag, four different lifetimes

The single biggest cause of flag systems rotting is treating all flags as one thing. They are not. They differ in who owns them, how long they live, and what happens if you forget about them:

| Kind | Lifetime | Owner | Deleted when | Danger if forgotten |
|---|---|---|---|---|
| **Release toggle** | days to weeks | the feature team | the rollout hits 100% | dead code paths, untested combinations |
| **Operational toggle / kill switch** | permanent | whoever is on call | never | goes stale, nobody tests it, fails when used |
| **Experiment flag** | the life of the experiment | product / data science | the experiment concludes | users stuck in a variant nobody remembers |
| **Permission / entitlement flag** | permanent | the product | never — it is business logic | treated as debt and deleted, removing a paid feature |

A **release toggle** guards a half-built or newly built code path during a rollout. It is short-lived by construction, and **deleting it is part of the definition of done** — not a follow-up ticket.

An **operational toggle** exists to be flipped during an incident: turn off the recommendations panel to shed load, disable the expensive personalisation query, stop writing to the analytics sink. A **kill switch** is the special case where the known-good value is *on* and you flip it off under duress. These are the flags [Backpressure & Load Shedding](../../08-concurrency-and-performance/11-backpressure-and-load-shedding/) assumed you had when it said "there must be a switch, and it must work at 100% CPU." Their danger is decay: a kill switch nobody has exercised in eleven months is a code path nobody has exercised in eleven months.

An **experiment flag** exists to split traffic and measure a difference. Its correctness requirement is stricter than a release toggle's, because a user who moves between variants mid-experiment does not just have a bad session — they corrupt the measurement.

A **permission flag** is not release machinery at all. `if user.plan == "enterprise"` is business logic wearing a flag's clothes. It is permanent, it belongs under test, and the failure mode is that a well-meaning cleanup deletes it because it looks like debt and takes a paid feature away from paying customers. If your system cannot distinguish these four kinds, it will apply one policy — usually "never delete anything" — to all of them. Related but distinct: authorization decides *may this user do this*, which [Authorization: RBAC, ABAC & ReBAC](../../07-auth-and-security/09-authorization-rbac-abac-rebac/) covers properly. A flag decides *is this behaviour available at all*. When those two get conflated in one system, you end up with your permission model spread across a flag console and a policy engine, and no single place that answers "why was this allowed?"

### Where the flag is evaluated decides what breaks

There are two architectures, and the difference is not a performance detail — it is a dependency decision.

**A network call per evaluation.** Your code asks a remote service "is `checkout_v2` on for user X?" and waits. This is simple, always fresh, and puts a third party's availability *and latency* inside your request path. If you evaluate three flags per request you have added three round trips, and a service you do not operate is now able to make your checkout endpoint time out. The exemplar failure is a flag SDK (software development kit — the client library a vendor ships) configured with no timeout: the vendor has a bad ten minutes and your threads are all parked on their socket.

**Local evaluation against a cached ruleset.** The SDK holds the full rule set in memory and evaluates it in-process, in microseconds, with no network call on the request path at all. A background connection — streaming or polling — keeps the rule set current. This is the architecture every serious flag system converged on, and it is the one worth insisting on when you evaluate vendors. It also changes the failure mode completely: if the control plane disappears, you keep evaluating correctly against the last rules you received, and you go stale rather than wrong.

### What happens when the flag service is unreachable is a decision you must make explicitly

If you have not chosen, you have chosen anyway — badly. Four behaviours, in increasing order of thoughtfulness:

1. **Hard dependency.** The flag call fails, the request fails. Someone else's outage becomes your 5xx. Measured in the Build It: a 2,500-request outage window produced **2,500 of your own errors**, from a service that was working perfectly.
2. **Fail open** — assume the feature is on. Correct for a kill switch, whose known-good state is *on*. **Catastrophic for a new code path**, because you have just released an unfinished feature to 100% of users at the exact moment you cannot observe anything.
3. **Fail closed** — assume the feature is off. Correct for a risky new path. Wrong for a kill switch: you turn off the recommendations panel for everyone because the flag service is unreachable, converting their outage into your degradation.
4. **Cached ruleset plus local evaluation.** You still know the rules, so you still get the right answer for every user. Wrong **zero** times in the measurement.

The rule underneath all four: **the coded default must be the known-good value for that specific flag, and that value differs per flag.** There is no global "safe" direction. Write the default into the call site — `get_boolean("new_pricing_engine", default=False)` — and treat it as a design decision that gets reviewed, because it is the value your users will get on the worst day.

### Sticky bucketing: the same user must get the same variant

Here is the mechanism that separates a feature-flag system from an `if random() < 0.1`, and it is the part people get wrong first.

A percentage rollout has to answer "is this user in the 10%?" on every single evaluation. If you answer it by drawing a fresh random number, the answer changes every time. The user gets the new checkout, then the old one, then the new one again — within one session, sometimes within one page load if two services evaluate the same flag.

The damage is not cosmetic:

- **Sessions break.** The new flow wrote state the old flow does not understand, and the user hits the old flow on the next click.
- **Funnels become meaningless.** A user counted in "saw new checkout" is also in "saw old checkout". Every conversion metric is now an average of two things.
- **Bugs become unreproducible.** The report says "the price was wrong"; you load the same user and see the old path; you close the ticket as not-reproducible. It happens again tomorrow.
- **Experiments measure nothing.** The whole premise of an A/B test is that a user is in exactly one arm.

The fix is one line: replace the coin flip with a **deterministic hash of a stable identifier**. Hash `"<flag-salt>:<user-id>"` with SHA-256 (Secure Hash Algorithm 256-bit, specified in NIST FIPS 180-4), read the first 8 bytes as an integer, and take it modulo 10,000 to get a bucket in **basis points** — 10,000 slots, so a rollout has 0.01% granularity. The user is in the rollout if their bucket is below the cut. Same user, same flag, same answer — forever, with no state stored anywhere, on every machine independently.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 532" width="100%" style="max-width:840px" role="img" aria-label="Two panels comparing bucketing schemes over 200,000 measured evaluations of a ten percent rollout. On the left, a fresh random draw per request makes one user flip between the new and old path across consecutive requests: 98.52 percent of users saw both variants and there were 35,073 variant switches, so a ten percent rollout exposed 98.52 percent of users. On the right, hashing the flag salt with the user id gives the same user the same bucket every time: zero flicker, zero switches, and 10.86 percent of users equals 10.86 percent of requests. Below, two population bars show that with a per-flag salt two flags at ten percent select different cohorts overlapping 9.74 percent, while with no salt both flags select the identical 4,972 users, a 100 percent overlap.">
  <defs>
    <marker id="l12-a2" markerWidth="9" markerHeight="9" refX="5.5" refY="3" orient="auto"><path d="M0,0 L6.5,3 L0,6 Z" fill="currentColor"/></marker>
  </defs>
  <text x="440" y="24" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">A 10% rollout that reached 98.52% of users — and the one-line fix</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">

    <g fill="none" stroke-width="2" stroke-linejoin="round">
      <rect x="18" y="42" width="414" height="232" rx="12" fill="#d64545" fill-opacity="0.08" stroke="#d64545"/>
      <rect x="448" y="42" width="414" height="232" rx="12" fill="#0fa07f" fill-opacity="0.09" stroke="#0fa07f"/>
    </g>
    <text x="225" y="66" font-size="12.5" font-weight="700" text-anchor="middle" fill="#d64545">rng.random() * 100 &lt; 10  — per request</text>
    <text x="655" y="66" font-size="12.5" font-weight="700" text-anchor="middle" fill="#0fa07f">sha256("checkout_v2:" + user id) % 10000 &lt; 1000</text>
    <text x="225" y="84" font-size="9.5" text-anchor="middle" fill="currentColor" opacity="0.85">a fresh coin flip every time the flag is read</text>
    <text x="655" y="84" font-size="9.5" text-anchor="middle" fill="currentColor" opacity="0.85">user-000002 -&gt; bucket 239 -&gt; 239 &lt; 1000 -&gt; ON, forever</text>

    <text x="36" y="112" font-size="9.5" fill="currentColor" opacity="0.8">user-000002, eight consecutive requests:</text>
    <text x="466" y="112" font-size="9.5" fill="currentColor" opacity="0.8">user-000002, eight consecutive requests:</text>

    <g fill="none" stroke-width="1.6">
      <rect x="36" y="122" width="42" height="26" rx="5" fill="#7f7f7f" fill-opacity="0.14" stroke="#7f7f7f"/>
      <rect x="84" y="122" width="42" height="26" rx="5" fill="#0fa07f" fill-opacity="0.28" stroke="#0fa07f"/>
      <rect x="132" y="122" width="42" height="26" rx="5" fill="#7f7f7f" fill-opacity="0.14" stroke="#7f7f7f"/>
      <rect x="180" y="122" width="42" height="26" rx="5" fill="#7f7f7f" fill-opacity="0.14" stroke="#7f7f7f"/>
      <rect x="228" y="122" width="42" height="26" rx="5" fill="#0fa07f" fill-opacity="0.28" stroke="#0fa07f"/>
      <rect x="276" y="122" width="42" height="26" rx="5" fill="#7f7f7f" fill-opacity="0.14" stroke="#7f7f7f"/>
      <rect x="324" y="122" width="42" height="26" rx="5" fill="#0fa07f" fill-opacity="0.28" stroke="#0fa07f"/>
      <rect x="372" y="122" width="42" height="26" rx="5" fill="#7f7f7f" fill-opacity="0.14" stroke="#7f7f7f"/>
    </g>
    <g font-size="9.5" font-weight="700" text-anchor="middle">
      <text x="57" y="139" fill="currentColor" opacity="0.6">old</text><text x="105" y="139" fill="#0fa07f">NEW</text><text x="153" y="139" fill="currentColor" opacity="0.6">old</text><text x="201" y="139" fill="currentColor" opacity="0.6">old</text>
      <text x="249" y="139" fill="#0fa07f">NEW</text><text x="297" y="139" fill="currentColor" opacity="0.6">old</text><text x="345" y="139" fill="#0fa07f">NEW</text><text x="393" y="139" fill="currentColor" opacity="0.6">old</text>
    </g>
    <g fill="none" stroke="#d64545" stroke-width="1.6">
      <path d="M81 152 L 81 162"/><path d="M129 152 L 129 162"/><path d="M225 152 L 225 162"/><path d="M273 152 L 273 162"/><path d="M321 152 L 321 162"/><path d="M369 152 L 369 162"/>
    </g>
    <text x="36" y="178" font-size="9.5" font-weight="700" fill="#d64545">6 switches in 8 requests — one broken session</text>

    <g fill="none" stroke-width="1.6">
      <rect x="466" y="122" width="42" height="26" rx="5" fill="#0fa07f" fill-opacity="0.28" stroke="#0fa07f"/>
      <rect x="514" y="122" width="42" height="26" rx="5" fill="#0fa07f" fill-opacity="0.28" stroke="#0fa07f"/>
      <rect x="562" y="122" width="42" height="26" rx="5" fill="#0fa07f" fill-opacity="0.28" stroke="#0fa07f"/>
      <rect x="610" y="122" width="42" height="26" rx="5" fill="#0fa07f" fill-opacity="0.28" stroke="#0fa07f"/>
      <rect x="658" y="122" width="42" height="26" rx="5" fill="#0fa07f" fill-opacity="0.28" stroke="#0fa07f"/>
      <rect x="706" y="122" width="42" height="26" rx="5" fill="#0fa07f" fill-opacity="0.28" stroke="#0fa07f"/>
      <rect x="754" y="122" width="42" height="26" rx="5" fill="#0fa07f" fill-opacity="0.28" stroke="#0fa07f"/>
      <rect x="802" y="122" width="42" height="26" rx="5" fill="#0fa07f" fill-opacity="0.28" stroke="#0fa07f"/>
    </g>
    <g font-size="9.5" font-weight="700" text-anchor="middle" fill="#0fa07f">
      <text x="487" y="139">NEW</text><text x="535" y="139">NEW</text><text x="583" y="139">NEW</text><text x="631" y="139">NEW</text>
      <text x="679" y="139">NEW</text><text x="727" y="139">NEW</text><text x="775" y="139">NEW</text><text x="823" y="139">NEW</text>
    </g>
    <text x="466" y="178" font-size="9.5" font-weight="700" fill="#0fa07f">0 switches — the bucket is a pure function of the id</text>

    <g fill="currentColor" font-size="10">
      <text x="36" y="202">flicker (users who saw BOTH)</text><text x="414" y="202" text-anchor="end" font-weight="700" fill="#d64545">98.52%</text>
      <text x="36" y="220">variant switches</text><text x="414" y="220" text-anchor="end" font-weight="700" fill="#d64545">35,073</text>
      <text x="36" y="238">% of requests on the new path</text><text x="414" y="238" text-anchor="end" font-weight="700">9.97%</text>
      <text x="36" y="256">% of USERS ever on the new path</text><text x="414" y="256" text-anchor="end" font-weight="700" fill="#d64545">98.52%</text>
      <text x="466" y="202">flicker (users who saw BOTH)</text><text x="844" y="202" text-anchor="end" font-weight="700" fill="#0fa07f">0.00%</text>
      <text x="466" y="220">variant switches</text><text x="844" y="220" text-anchor="end" font-weight="700" fill="#0fa07f">0</text>
      <text x="466" y="238">% of requests on the new path</text><text x="844" y="238" text-anchor="end" font-weight="700">10.86%</text>
      <text x="466" y="256">% of USERS ever on the new path</text><text x="844" y="256" text-anchor="end" font-weight="700" fill="#0fa07f">10.86%</text>
    </g>

    <text x="440" y="298" font-size="12.5" font-weight="700" text-anchor="middle" fill="currentColor">deterministic is not enough — the salt decides WHICH 10%</text>
    <text x="440" y="316" font-size="9.5" text-anchor="middle" fill="currentColor" opacity="0.85">two flags, both at 10%, over the same 50,000 users. Each tick is a cohort member.</text>

    <g fill="none" stroke-width="1.8">
      <rect x="18" y="330" width="844" height="76" rx="10" fill="#0fa07f" fill-opacity="0.08" stroke="#0fa07f"/>
      <rect x="18" y="416" width="844" height="76" rx="10" fill="#d64545" fill-opacity="0.08" stroke="#d64545"/>
    </g>
    <g fill="currentColor" font-size="10">
      <text x="34" y="350" font-weight="700" fill="#0fa07f">per-flag salt</text>
      <text x="34" y="364" font-size="8.5" opacity="0.8">sha256(key + id)</text>
      <text x="34" y="436" font-weight="700" fill="#d64545">no salt</text>
      <text x="34" y="450" font-size="8.5" opacity="0.8">sha256(id) only</text>
      <text x="150" y="362" font-size="9">flag A</text><text x="150" y="392" font-size="9">flag B</text>
      <text x="150" y="448" font-size="9">flag A</text><text x="150" y="478" font-size="9">flag B</text>
    </g>

    <g fill="none" stroke="currentColor" stroke-width="1.2" stroke-opacity="0.35">
      <rect x="196" y="348" width="434" height="16" rx="4"/><rect x="196" y="378" width="434" height="16" rx="4"/>
      <rect x="196" y="434" width="434" height="16" rx="4"/><rect x="196" y="464" width="434" height="16" rx="4"/>
    </g>

    <g stroke="#3553ff" stroke-width="3.4">
      <path d="M212 349 L 212 363"/><path d="M240 349 L 240 363"/><path d="M272 349 L 272 363"/><path d="M296 349 L 296 363"/><path d="M330 349 L 330 363"/>
      <path d="M356 349 L 356 363"/><path d="M388 349 L 388 363"/><path d="M414 349 L 414 363"/><path d="M448 349 L 448 363"/>
      <path d="M502 349 L 502 363"/><path d="M530 349 L 530 363"/><path d="M560 349 L 560 363"/><path d="M590 349 L 590 363"/>
      <path d="M222 379 L 222 393"/><path d="M252 379 L 252 393"/><path d="M282 379 L 282 393"/><path d="M310 379 L 310 393"/><path d="M340 379 L 340 393"/>
      <path d="M368 379 L 368 393"/><path d="M400 379 L 400 393"/><path d="M430 379 L 430 393"/><path d="M512 379 L 512 393"/><path d="M542 379 L 542 393"/>
      <path d="M572 379 L 572 393"/><path d="M604 379 L 604 393"/>
    </g>
    <g stroke="#e0930f" stroke-width="3.4">
      <path d="M476 349 L 476 363"/><path d="M476 379 L 476 393"/>
    </g>
    <circle cx="476" cy="371" r="10" fill="none" stroke="#e0930f" stroke-width="1.6"/>

    <text x="648" y="345" font-size="8.5" font-weight="700" fill="#e0930f">amber tick = in both cohorts</text>
    <text x="648" y="364" font-size="11.5" font-weight="700" fill="#0fa07f">overlap 9.74%</text>
    <text x="648" y="380" font-size="9" fill="currentColor" opacity="0.9">486 of 4,992 users —</text>
    <text x="648" y="393" font-size="9" fill="currentColor" opacity="0.9">what independence predicts</text>

    <g stroke="#e0930f" stroke-width="3.4">
      <path d="M212 435 L 212 449"/><path d="M240 435 L 240 449"/><path d="M272 435 L 272 449"/><path d="M296 435 L 296 449"/><path d="M330 435 L 330 449"/>
      <path d="M356 435 L 356 449"/><path d="M388 435 L 388 449"/><path d="M414 435 L 414 449"/><path d="M448 435 L 448 449"/><path d="M476 435 L 476 449"/>
      <path d="M502 435 L 502 449"/><path d="M530 435 L 530 449"/><path d="M560 435 L 560 449"/><path d="M590 435 L 590 449"/>
      <path d="M212 465 L 212 479"/><path d="M240 465 L 240 479"/><path d="M272 465 L 272 479"/><path d="M296 465 L 296 479"/><path d="M330 465 L 330 479"/>
      <path d="M356 465 L 356 479"/><path d="M388 465 L 388 479"/><path d="M414 465 L 414 479"/><path d="M448 465 L 448 479"/><path d="M476 465 L 476 479"/>
      <path d="M502 465 L 502 479"/><path d="M530 465 L 530 479"/><path d="M560 465 L 560 479"/><path d="M590 465 L 590 479"/>
    </g>
    <text x="648" y="434" font-size="11.5" font-weight="700" fill="#d64545">overlap 100.00%</text>
    <text x="648" y="451" font-size="9" fill="currentColor" opacity="0.9">the SAME 4,972 people are</text>
    <text x="648" y="464" font-size="9" fill="currentColor" opacity="0.9">every flag's test subjects —</text>
    <text x="648" y="477" font-size="9" fill="currentColor" opacity="0.9">they meet every bug first</text>
    <text x="440" y="514" font-size="11" text-anchor="middle" fill="currentColor" opacity="0.9">Sticky bucketing costs one SHA-256 per evaluation. Randomising costs you the session, the funnel, and the experiment.</text>
  </g>
</svg>
```

Look at the left-hand column, because it contains the trap in its purest form. **The random scheme hit its target.** 9.97% of requests were served the new path — dead on 10%, exactly what the dashboard would show, exactly what the rollout plan asked for. And **98.52% of users touched the new code path at least once.** A 10% rollout that is, from the point of view of blast radius, a 100% rollout. The metric you were watching was *requests*, and the thing you were trying to limit was *users*.

Two properties are needed and they are not the same property. **Determinism** means the same input gives the same output. **Uniformity** means the outputs are spread evenly, so a 10% cut really is 10% of people and not 3% or 30%. A hash gives you both; `hash(user_id) % 100 < 10` on Python's built-in `hash()` gives you neither across processes, because `str.__hash__` is randomised per interpreter by default (see `PYTHONHASHSEED`), so the same user lands in a different bucket on every process and every restart. **Use a cryptographic hash for bucketing, not the language's built-in one.** The Build It measures uniformity directly: 50,000 users spread over 100 buckets land between **441 and 549 against a mean of 500 — the worst bucket is 11.8% off**, which is ordinary sampling noise, not bias.

### The per-flag salt

Determinism alone creates a second, subtler bug. If the bucket is `hash(user_id)`, then *every flag at 10% selects the same 10% of users*. The same people are in the first cohort of every rollout you ever do. They meet every new bug first, their experience of your product is a permanent beta, and every experiment you run is contaminated by every other experiment they are simultaneously enrolled in.

The fix is to mix the flag's own key into the hash input: `sha256(flag_key + ":" + user_id)`. Now each flag draws an independent sample. Measured over 50,000 users with two flags at 10%: with a per-flag salt the cohorts overlap by **9.74% — precisely what independence predicts, 10% of 10%**. Without it, the overlap is **100.00%: the identical 4,972 people, every time.**

One consequence worth planning for: because the salt is the flag key, *changing the flag key re-rolls the entire cohort*. Renaming `checkout_v2` to `checkout_v2_final` moves every user to a different bucket, which mid-rollout means everybody's variant changes at once. Keep flag keys immutable once a rollout has started.

And the identifier you hash matters as much as the salt. It must be **stable across the user's whole journey**. A session id changes on logout. A device id changes on reinstall. A raw IP address changes on a train. If you bucket an anonymous visitor by a cookie and then they log in, they cross into a different bucket at exactly the moment they convert — which is exactly the moment you were measuring. Pick the most stable identifier available at the point of evaluation, and where an anonymous-to-authenticated transition matters, carry the anonymous id forward and keep hashing that.

### Flag debt is arithmetic, not an opinion

Every flag is a permanent branch in the code, and branches multiply. **N live flags means up to 2^N reachable configurations of your system.** Your test suite exercises approximately the default one, plus perhaps each flag alone, plus (if you are unusually rigorous) each pair.

That arithmetic is brutal and it is in the Build It: at **10 flags there are 1,024 configurations** and a generous test strategy covers 56 of them — one in 18. At **30 flags there are over a billion configurations** and you cover **one in 2.3 million.** Production picks from all of them, one user at a time, and the combination that breaks is by definition one you did not run.

The second cost is human and shows up at 3am. Every flag is a question the on-call engineer must answer before they can reason about a report: *was this user in that rollout? is that toggle still on in this region? who owns this and can I flip it?* A system with 40 flags has 40 of those questions, and the on-call engineer knows the answer to perhaps six.

So flags need the same lifecycle discipline as any other resource. **An owner, an expiry date, and removal as part of the definition of done.** In the measured inventory, 40 live flags include 22 release toggles and 7 experiment flags, of which **13 are past their expiry date — the oldest release toggle is 190 days old.** Deleting those 13 `if` statements takes 40 flags to 27, and takes reachable configurations from 2^40 to 2^27: an **8,192× reduction in state space for an afternoon's work that ships no features.**

### Progressive delivery = flags + metrics + automation

Lesson 11 built the measured promote-or-abort loop: deploy to a small slice, watch the error rate and latency against a baseline, promote if healthy, abort if not. **Progressive delivery is that same loop with exposure as the thing being ramped instead of instances.** The pattern is identical; the substrate is different, and the difference buys you three things:

- **The slice is a set of users, not a set of machines.** You can canary to internal staff, then one region, then 1% of the free tier, then 1% of everyone. An instance canary cannot express "internal staff first" — an instance serves whoever the load balancer sends it.
- **Reversal is a control-plane write, not a rollout.** Milliseconds to seconds instead of minutes, and no capacity churn.
- **It composes with the deploy canary rather than replacing it.** The instance canary catches what is wrong with the *artifact* — a bad dependency, a memory leak, a broken config. The flag canary catches what is wrong with the *behaviour*. They fail differently, so run both.

The automation half is the same as Lesson 11's: define your success criteria *before* the ramp, in terms of [SLIs, SLOs & error budgets](../../09-logging-monitoring-and-observability/09-slis-slos-and-error-budgets/), and let a controller promote or abort. The Google SRE Workbook's chapter on canarying makes the point that matters here: a canary is only meaningful if you have decided in advance what "bad" looks like and how long you must observe to see it. A 1% ramp watched for ninety seconds is theatre — a 1% slice takes a hundred times longer to accumulate enough events to detect a small regression than a 100% deploy does.

### Mitigation is an exposure change

Everything above converges on one number: how long between deciding to mitigate and the users stopping being hurt.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 500" width="100%" style="max-width:840px" role="img" aria-label="Three mitigation paths for the same failure, drawn to scale on one time axis running from zero to three hundred seconds. A flag flip through a streaming SDK with local evaluation completes in 4.3 seconds, a barely visible sliver. The same flag flip through a thirty second polling SDK takes 33.4 seconds. Rolling back the deploy takes 304 seconds, made of a 45 second human stage, a 10 second control plane trigger, and then four rolling batches of pod start plus readiness plus a thirty second drain each. Below, the flag flip is magnified twenty four times to show its four stages: a 2.0 second operator decision, a 0.4 second control plane write, a 0.9 second streaming push, and a 1.0 second in-process cache time to live.">
  <defs>
    <marker id="l12-a3" markerWidth="10" markerHeight="10" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker>
  </defs>
  <text x="440" y="24" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">Same failure, two mitigations, one time axis: 4.3 s vs 304 s</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">

    <g fill="currentColor" font-size="9" opacity="0.6" font-weight="700">
      <text x="120" y="46">MITIGATION PATH</text>
      <text x="858" y="46" text-anchor="end">TIME TO MITIGATE / BAD REQUESTS AT 850 req/s</text>
    </g>

    <rect x="120" y="58" width="10.2" height="24" rx="3" fill="#0fa07f" fill-opacity="0.45" stroke="#0fa07f" stroke-width="1.6"/>
    <text x="142" y="70" font-size="10.5" font-weight="700" fill="#0fa07f">A · flag flip — streaming SDK + local evaluation</text>
    <text x="142" y="83" font-size="9" fill="currentColor" opacity="0.85">4.3 s &#183; 3,655 bad requests &#183; 149 errors  (magnified below)</text>

    <g stroke-width="1.6">
      <rect x="120" y="96" width="4.7" height="24" rx="2" fill="#3553ff" fill-opacity="0.35" stroke="#3553ff"/>
      <rect x="125.7" y="96" width="70.8" height="24" rx="2" fill="#e0930f" fill-opacity="0.30" stroke="#e0930f"/>
    </g>
    <text x="210" y="108" font-size="10.5" font-weight="700" fill="#e0930f">B · the same flip, 30 s polling SDK</text>
    <text x="210" y="121" font-size="9" fill="currentColor" opacity="0.85">33.4 s &#183; 28,390 bad requests &#183; 1,163 errors — the poll interval IS the outage</text>

    <text x="120" y="144" font-size="10.5" font-weight="700" fill="#7c5cff">C · roll back the deploy — 12 instances, 4 batches of 3</text>
    <g stroke-width="1.5">
      <rect x="120" y="150" width="106.2" height="26" rx="3" fill="#3553ff" fill-opacity="0.32" stroke="#3553ff"/>
      <rect x="226.2" y="150" width="23.6" height="26" rx="3" fill="#7c5cff" fill-opacity="0.30" stroke="#7c5cff"/>
      <rect x="249.8" y="150" width="113.3" height="26" rx="3" fill="#7c5cff" fill-opacity="0.30" stroke="#7c5cff"/>
      <rect x="363.1" y="150" width="70.8" height="26" rx="3" fill="#e0930f" fill-opacity="0.28" stroke="#e0930f"/>
      <rect x="433.9" y="150" width="63.7" height="26" rx="3" fill="#7c5cff" fill-opacity="0.30" stroke="#7c5cff"/>
      <rect x="497.6" y="150" width="70.8" height="26" rx="3" fill="#e0930f" fill-opacity="0.28" stroke="#e0930f"/>
      <rect x="568.4" y="150" width="63.7" height="26" rx="3" fill="#7c5cff" fill-opacity="0.30" stroke="#7c5cff"/>
      <rect x="632.1" y="150" width="70.8" height="26" rx="3" fill="#e0930f" fill-opacity="0.28" stroke="#e0930f"/>
      <rect x="702.9" y="150" width="63.7" height="26" rx="3" fill="#7c5cff" fill-opacity="0.30" stroke="#7c5cff"/>
      <rect x="766.6" y="150" width="70.8" height="26" rx="3" fill="#e0930f" fill-opacity="0.28" stroke="#e0930f"/>
    </g>
    <g font-size="8.5" font-weight="700" text-anchor="middle">
      <text x="173" y="167" fill="#3553ff">human</text>
      <text x="306" y="167" fill="#7c5cff">batch 1</text>
      <text x="398" y="167" fill="#e0930f">drain</text>
      <text x="465" y="167" fill="#7c5cff">batch 2</text>
      <text x="533" y="167" fill="#e0930f">drain</text>
      <text x="600" y="167" fill="#7c5cff">batch 3</text>
      <text x="667" y="167" fill="#e0930f">drain</text>
      <text x="734" y="167" fill="#7c5cff">batch 4</text>
      <text x="802" y="167" fill="#e0930f">drain</text>
    </g>
    <g font-size="8.5" text-anchor="middle" fill="currentColor" opacity="0.85">
      <text x="173" y="189">45 s</text><text x="238" y="189">10 s</text><text x="306" y="189">48 s</text><text x="398" y="189">30 s</text><text x="465" y="189">27 s</text>
      <text x="533" y="189">30 s</text><text x="600" y="189">27 s</text><text x="667" y="189">30 s</text><text x="734" y="189">27 s</text><text x="802" y="189">30 s</text>
    </g>
    <text x="120" y="204" font-size="9" fill="currentColor" opacity="0.85">human = find the last-good digest + approval &#183; 10 s = control plane reconciles &#183; batch = pull + start + readiness</text>
    <text x="120" y="217" font-size="9" fill="currentColor" opacity="0.85">drain = the 30 s deregistration delay &#183; total 304.0 s &#183; 258,400 bad requests &#183; 10,594 errors</text>

    <path d="M120 234 L 862 234" fill="none" stroke="currentColor" stroke-width="1.4" marker-end="url(#l12-a3)"/>
    <g fill="none" stroke="currentColor" stroke-width="1.1" opacity="0.5">
      <path d="M120 234 L 120 240"/><path d="M261.7 234 L 261.7 240"/><path d="M403.3 234 L 403.3 240"/><path d="M545 234 L 545 240"/><path d="M686.6 234 L 686.6 240"/><path d="M828.3 234 L 828.3 240"/>
    </g>
    <g fill="currentColor" font-size="9" opacity="0.75" text-anchor="middle">
      <text x="120" y="252">0 s</text><text x="261.7" y="252">60 s</text><text x="403.3" y="252">120 s</text><text x="545" y="252">180 s</text><text x="686.6" y="252">240 s</text><text x="828.3" y="252">300 s</text>
    </g>

    <rect x="18" y="268" width="844" height="124" rx="11" fill="#0fa07f" fill-opacity="0.07" stroke="#0fa07f" stroke-width="1.8"/>
    <text x="36" y="290" font-size="11.5" font-weight="700" fill="#0fa07f">bar A, magnified 24x — the whole flag flip, stage by stage</text>

    <g stroke-width="1.6">
      <rect x="140" y="304" width="279" height="30" rx="4" fill="#3553ff" fill-opacity="0.32" stroke="#3553ff"/>
      <rect x="419" y="304" width="55.8" height="30" rx="4" fill="#7c5cff" fill-opacity="0.30" stroke="#7c5cff"/>
      <rect x="474.8" y="304" width="125.6" height="30" rx="4" fill="#7c5cff" fill-opacity="0.30" stroke="#7c5cff"/>
      <rect x="600.4" y="304" width="139.5" height="30" rx="4" fill="#e0930f" fill-opacity="0.28" stroke="#e0930f"/>
    </g>
    <g text-anchor="middle">
      <text x="279" y="323" font-size="9.5" font-weight="700" fill="#3553ff">operator decides + flips</text>
      <text x="447" y="319" font-size="8" font-weight="700" fill="#7c5cff">control</text>
      <text x="447" y="329" font-size="8" font-weight="700" fill="#7c5cff">plane</text>
      <text x="537" y="323" font-size="9.5" font-weight="700" fill="#7c5cff">streaming push</text>
      <text x="670" y="323" font-size="9.5" font-weight="700" fill="#e0930f">eval cache TTL</text>
    </g>
    <g font-size="9" text-anchor="middle" fill="currentColor" opacity="0.85">
      <text x="279" y="350">2.0 s</text><text x="447" y="350">0.4 s</text><text x="537" y="350">0.9 s</text><text x="670" y="350">1.0 s</text>
    </g>
    <text x="756" y="323" font-size="11" font-weight="700" fill="#0fa07f">= 4.3 s</text>
    <text x="36" y="374" font-size="9.5" fill="currentColor" opacity="0.9">blue = a human deciding &#183; purple = machinery you cannot skip &#183; amber = a timer you can only wait out</text>

    <g fill="none" stroke-width="1.8">
      <rect x="18" y="404" width="414" height="54" rx="9" fill="#7f7f7f" fill-opacity="0.08" stroke="currentColor" stroke-opacity="0.4"/>
      <rect x="448" y="404" width="414" height="54" rx="9" fill="#d64545" fill-opacity="0.10" stroke="#d64545"/>
    </g>
    <g fill="currentColor">
      <text x="34" y="424" font-size="10.5" font-weight="700">subtract the human from both</text>
      <text x="34" y="440" font-size="9.5" opacity="0.9">45 s vs 2.0 s removed -&gt; the ratio gets WORSE: 113x.</text>
      <text x="34" y="453" font-size="9.5" opacity="0.9">The machinery is the cost, not the decision.</text>
      <text x="464" y="424" font-size="10.5" font-weight="700" fill="#d64545">the 299.7 s you spend waiting</text>
      <text x="464" y="440" font-size="9.5" opacity="0.9">= 10,444 extra failed requests at 850 req/s,</text>
      <text x="464" y="453" font-size="9.5" opacity="0.9">every one of them avoidable.</text>
    </g>
    <text x="440" y="482" font-size="11" text-anchor="middle" fill="currentColor" opacity="0.9">Rollback is 71x the time-to-mitigate of a flag flip — and it reverts every other change riding in the artifact.</text>
  </g>
</svg>
```

The ratio is **71×**, and the honest version of that claim is the one that survives the obvious objection. "Your rollback number includes 45 seconds of a human finding the digest and getting approval — that is not fair." Correct, so remove the human stage from *both* sides: 45 seconds off the rollback, 2.0 seconds off the flag flip. The ratio gets **worse, not better: 113×.** The human is the *cheap* part. What you are paying for is image pulls, container starts, readiness gates and deregistration delays, repeated once per batch — machinery that exists for good reasons and cannot be skipped during an incident.

The second lesson in that diagram is that **the SDK's update mechanism is part of your incident response time.** The identical flag flip through a 30-second polling SDK takes **33.4 seconds instead of 4.3** — the poll interval sits directly in the critical path, and at 850 req/s that is the difference between **3,655 and 28,390 requests served by the broken path.** When you evaluate a flag vendor, "how does the ruleset reach my process, and how long is the worst case" is the question that matters most, and the answer you want is *streaming, with a short in-process cache TTL (time to live) on top*.

## Build It

[`code/feature_flags.py`](code/feature_flags.py) is six numbered arguments in stdlib Python — no third-party imports, seeded with `random.Random(7)`, runs in about a second. The interesting parts:

**The bucketing function is the whole mechanism.** Four lines, and every property discussed above comes from them:

```python
def bucket_bp(salt: str, key: str) -> int:
    """Deterministic bucket in [0, 10000) for a (flag, user) pair.

    The salt is what makes two flags at 10% pick DIFFERENT users. Drop it and
    every flag in your system selects the same unlucky cohort forever.
    """
    digest = hashlib.sha256(f"{salt}:{key}".encode()).digest()
    return int.from_bytes(digest[:8], "big") % BP
```

No state, no coordination, no storage. Every process in your fleet computes the same bucket for the same user without talking to any other process — which is why local evaluation is possible at all. `BP` is 10,000, so buckets are basis points and a rollout can be expressed to 0.01%.

**Evaluation returns a reason, not just a value.** This is the part people leave out and regret:

```python
def evaluate(flag: Flag, user: dict[str, Any]) -> tuple[bool, str]:
    """Return (variant, reason). The reason is what you need at 3am."""
    for rule in flag.rules:
        if not rule.targets(user):
            continue
        shown = ",".join(f"{k}={v}" for k, v in rule.when.items()) or "everyone"
        if rule.rollout_pct is None:
            return rule.variant, f"rule '{rule.name}' [{shown}]"
        b = bucket_bp(flag.bucket_salt, user["id"])
        cut = int(rule.rollout_pct * 100)
        if b < cut:
            return rule.variant, f"rule '{rule.name}' [{shown}] bucket {b} < {cut}"
        return flag.default, f"rule '{rule.name}' missed rollout: bucket {b} >= {cut}"
    return flag.default, "no rule matched -> coded default"
```

Rules are ordered and **first match wins**, so the rule order *is* the policy. Note what falls out: a rule that matches but whose rollout excludes the user returns the flag's default and stops — it does not fall through to a later rule. That is deliberate, and it is what lets a narrow rule act as a fence.

**The flicker measurement is the same loop run twice with a different one-line assignment function** — everything else is identical, which is what makes the comparison honest:

```python
random_run = run(lambda uid: rng.random() * 100.0 < pct)
hashed_run = run(lambda uid: bucket_bp("checkout_v2", uid) < cut)
```

**The failure-mode simulation** models the flag service being unreachable for a slice of the request stream, and makes each fallback policy an explicit branch. `truth` is what the user *should* have seen; everything else is a policy choosing what they actually get:

```python
if mode == "hard":
    errors += 1                    # 500: the flag call IS the request
    continue
if mode == "open":
    got = True
elif mode == "closed":
    got = False
else:                              # cached ruleset, local evaluation
    got = truth
wrong_on += got and not truth
wrong_off += truth and not got
```

Run it:

```bash
docker compose exec -T app python \
  phases/10-infrastructure-and-deployment/12-deploy-vs-release-feature-flags/code/feature_flags.py
```

```console
== 1 · A FLAG ENGINE: TARGETING, ROLLOUT, DEFAULT — AND THE REASON ==
  flag 'checkout_v2' kind=release default=False owner=payments  (4 rules, first match wins)
  user      plan        region  ->   why
  u-1041    free        us      off  rule 'general rollout' missed rollout: bucket 9160 >= 1000
  u-2277    free        us      ON   rule 'general rollout' [everyone] bucket 229 < 1000
  u-3313    enterprise  us      ON   rule 'enterprise opt-in beta' [plan=enterprise] bucket 4929 < 5000
  u-4128    enterprise  us      off  rule 'enterprise opt-in beta' missed rollout: bucket 6348 >= 5000
  u-5002    pro         eu      off  rule 'kill for EU while DPA review runs' [region=eu]
  u-6661    pro         us      ON   rule 'internal staff first' [internal=True]
  the rule ORDER is the policy: the EU kill rule sits above the
  rollout, so a region cannot be exposed by a percentage ramp.

== 2 · STICKY BUCKETING: THE SAME USER MUST GET THE SAME VARIANT ==
  5,000 users x 40 requests = 200,000 evaluations of a 10% rollout, run twice
  bucketing                   flicker  switches  % of reqs ON  % users ever ON
  fresh random per request     98.52%    35,073         9.97%           98.52%
  sha256(salt + user id)        0.00%         0        10.86%           10.86%
  random bucketing hit the target 10% of REQUESTS (9.97%) and still exposed
  98.52% of users to the new path at least once — a 10% rollout that
  is really a 100% rollout, 35,073 variant switches deep.
  hashed bucketing: flicker 0.00%, 0 switches, and the
  realised rollout is the same number for users and requests: 10.86%.
  (10.86% and not 10.00%: that is sampling error at 5,000 users, not
   bias — section 3 buckets 50,000 users and lands on 9.98%.)
  distribution over 100 buckets, 50,000 users: min 441  mean 500  max 549
  worst bucket is 11.8% off the mean — deterministic AND fair.

== 3 · THE PER-FLAG SALT: OR ONE COHORT IS EVERY EXPERIMENT'S SUBJECT ==
  two flags, both at 10%, over 50,000 users
  scheme                                   A       B    A n B   overlap
  per-flag salt (sha256(key+id))       4,992   4,966      486     9.74%
  no salt (sha256(id) only)            4,972   4,972    4,972   100.00%
  each cohort is 9.98% of 50,000 users — the 10% rollout, realised.
  salted, the overlap is 9.74% — what independence predicts (10% of 10%).
  unsalted, it is 100%: the SAME 4,972 people are the test subjects for
  every flag you own. They see each new bug first, every single time,
  and your experiment results are confounded by every other experiment.

== 4 · THE FLAG SERVICE GOES AWAY. WHAT DOES YOUR USER SEE? ==
  6,000 requests; the flag service is unreachable for requests 2,000-4,500 (2,500 requests)
  behaviour                                    5xx   wrongly ON  wrongly OFF
  network call per eval, no fallback         2,500            0            0
  fail-open  on kill switch (correct)            0            0            0
  fail-closed on kill switch (WRONG)             0            0        2,500
  fail-open  on new risky path (WRONG)           0        2,261            0
  fail-closed on new risky path (correct)        0            0          239
  cached ruleset + local evaluation              0            0            0
  the hard dependency turned someone else's outage into 2,500 of YOUR 5xx.
  fail-open is right for a kill switch (known-good = feature ON) and
  catastrophic for a new path — it ships 100% of an unfinished feature.
  fail-closed is the mirror image. Neither is 'safe'; the safe default is
  per-flag, and the cached ruleset is wrong 0 times because it still knows
  the rules — that is why local evaluation beats a per-call network hop.

== 5 · MITIGATING THE SAME FAILURE TWO WAYS, TIMED ==
  A · flag flip, streaming SDK + local evaluation
        2.0s  operator flips the flag in the console               t+   2.0s
        0.4s  control plane writes + validates the ruleset         t+   2.4s
        0.9s  streaming push to every SDK (p95 fan-out)            t+   3.3s
        1.0s  in-process eval cache TTL expires                    t+   4.3s
  B · flag flip, 30 s polling SDK
        2.0s  operator flips the flag in the console               t+   2.0s
        0.4s  control plane writes + validates the ruleset         t+   2.4s
       30.0s  SDK polling interval (worst case)                    t+  32.4s
        1.0s  in-process eval cache TTL expires                    t+  33.4s
  C · roll back the deploy (12 instances, 4 batches of 3)
       45.0s  find the last-good image digest, get approval        t+  45.0s
       10.0s  trigger the rollout, control plane reconciles        t+  55.0s
       48.0s  batch 1/4: image pull 25s + start 8s + readiness 15s t+ 103.0s
       30.0s  batch 1/4: drain old pods (30s deregistration delay) t+ 133.0s
       27.0s  batch 2/4: pull (cached) 4s + start 8s + readiness 15s t+ 160.0s
       30.0s  batch 2/4: drain old pods                            t+ 190.0s
       27.0s  batch 3/4: start + readiness                         t+ 217.0s
       30.0s  batch 3/4: drain old pods                            t+ 247.0s
       27.0s  batch 4/4: start + readiness                         t+ 274.0s
       30.0s  batch 4/4: drain old pods                            t+ 304.0s
  mitigation                                         TTM   bad requests    errors
  flag flip (streaming + local eval)                4.3s          3,655       149
  flag flip (30 s polling SDK)                     33.4s         28,390     1,163
  deploy rollback                                 304.0s        258,400    10,594
  time-to-mitigate ratio: rollback is 71x the flag flip (304s vs 4.3s).
  at 850 req/s that is 10,444 extra failed requests, and the
  rollback also reverts every OTHER change in the same artifact.
  subtract the human stage from both (45s vs 2s) and the ratio gets WORSE,
  not better: 113x. The machinery is the cost, not the decision.

== 6 · FLAG DEBT IS ARITHMETIC, NOT AN OPINION ==
   live flags N    configurations 2^N   tested (1+N+pairs)   you cover 1 in
              5                    32                   16                2
             10                 1,024                   56               18
             20             1,048,576                  211            4,969
             30         1,073,741,824                  466        2,304,167
             40     1,099,511,627,776                  821    1,339,234,625
  the pair column is generous — almost nobody tests pairs. Even if you do,
  at 30 flags you exercise 1 configuration in 2.3 million. Production
  picks from all of them, one user at a time.

  a real inventory: 40 live flags
  kind            count   expiry  past expiry   who owns it, and for how long
  release            22      60d            9   feature team, delete after rollout
  experiment          7      90d            4   product, life of the test
  operational         6       --            0   whoever is on call, permanent
  permission          5       --            0   permanent — it is business logic
  13 of 40 flags are past their expiry date and are pure debt.
  the oldest release toggle is 190 days old — it was 'temporary'.
  removing them: 40 flags -> 27 flags, 2^40 = 1,099,511,627,776 configurations -> 2^27 = 134,217,728
  that is a 8,192x reduction in reachable states from deleting 13 if-statements.
  8,192x, for work that ships no features and takes an afternoon.

== SUMMARY ==
  flicker rate       random 98.52%   hashed 0.00%
  cohort overlap     salted 9.74%   unsalted 100%
  time to mitigate   flag 4.3s   rollback 304s (71x)
  flag debt          40 flags -> 27 after expiry = 8,192x fewer states
```

**Section 1** is the engine, and the column to read is the last one. Every decision comes back with *which rule matched and why* — `bucket 9160 >= 1000` is the difference between an on-call engineer answering a customer in ten seconds and an on-call engineer guessing. Two users on the same plan in the same region get opposite answers (`u-1041` off at bucket 9160, `u-2277` on at bucket 229) and the output says exactly why. Notice `u-5002`: the rule `kill for EU while DPA review runs` (DPA = data processing agreement, the contract governing how a processor handles personal data) sits *above* the general rollout, so an EU user cannot be caught by a percentage ramp no matter how far it advances. **Rule order is a safety mechanism, not a formatting choice.**

**Section 2 is the load-bearing measurement of this lesson.** Two hundred thousand evaluations, identical in every respect except how the bucket is chosen. Random-per-request produced **9.97% of requests on the new path** — a perfect-looking 10% rollout — while **98.52% of users touched it at least once**, across **35,073 variant switches**. Hashed bucketing produced **0.00% flicker, 0 switches**, and the number that matters: **the user percentage and the request percentage are the same number, 10.86%.** That equality is the property you are actually buying. When user-share and request-share agree, "10% rollout" means what you think it means, and your blast radius is what you planned. The 10.86% rather than 10.00% is sampling error at 5,000 users, not bias — at 50,000 users the same function lands on 9.98%, and the bucket histogram (**min 441, max 549 against a mean of 500, worst bucket 11.8% off**) shows the hash is uniform, not merely repeatable.

**Section 3** isolates the salt. Two flags, both at 10%, same population. Salted: **4,992 and 4,966 users, 486 in common — a 9.74% overlap**, which is what you would get by drawing two independent 10% samples. Unsalted: **4,972 and 4,972, all 4,972 in common — 100%.** Those 4,972 people are, permanently and invisibly, the first users to meet every change you ever ship. If you run experiments, every result you produce is confounded by every other experiment those same people are in.

**Section 4** puts a price on the fallback decision. The hard dependency converted a 2,500-request window of *someone else's* unavailability into **2,500 of your own 5xx responses** — a self-inflicted outage caused by a service that only ever answers a yes/no question. Then the symmetry: **fail-open is exactly right for the kill switch (0 wrong) and exactly wrong for the risky new path (2,261 users wrongly ON** — an unfinished feature shipped to everyone, at the moment your control plane is down). **Fail-closed is the mirror image** — 0 wrong on the risky path except the 239 users who legitimately had it, and 2,500 wrong on the kill switch. Neither direction is safe in general; safety is per-flag. The cached ruleset is wrong **zero** times in both cases, because it is the only option that still knows the *rules* rather than guessing at the *answer*.

**Section 5** is the argument for putting a kill switch on anything risky, and section 6 is the argument for taking it out afterwards. The debt table's middle column is deliberately generous — it assumes you test every flag alone *and* every pair, which almost nobody does — and even then, **at 30 flags you exercise one configuration in 2.3 million.** The inventory shows where those flags come from: 22 release toggles that were each supposed to live 60 days, of which 9 have not. **13 of 40 flags are pure debt, the oldest release toggle is 190 days old**, and deleting them shrinks the reachable state space by **8,192×**.

## Use It

### The vendor-neutral interface: OpenFeature

**OpenFeature** is a CNCF (Cloud Native Computing Foundation) specification defining a standard flag-evaluation API and a provider interface, so your application code does not import a vendor. You write against the SDK; a *provider* plugs in LaunchDarkly, Unleash, Flagsmith, a config file, or an in-memory map for tests. Changing vendors becomes a startup-wiring change instead of a codebase-wide rewrite.

```python
import os
from openfeature import api
from openfeature.evaluation_context import EvaluationContext

# One line of vendor-specific wiring, at startup, and nowhere else.
api.set_provider(YourVendorProvider(sdk_key=os.environ["FLAG_SDK_KEY"]))
client = api.get_client()

def checkout(user, cart):
    ctx = EvaluationContext(
        targeting_key=user.id,                 # the STABLE id — this is what gets hashed
        attributes={"plan": user.plan, "region": user.region,
                    "internal": user.is_staff},
    )
    # The second argument is the coded default: the value on the worst day.
    # For a risky new path it is False. For a kill switch it would be True.
    if client.get_boolean_value("checkout_v2", False, ctx):
        return checkout_v2(user, cart)
    return checkout_v1(user, cart)
```

Three things in that snippet are the lesson, not the API. `targeting_key` is OpenFeature's name for the stable identifier — it is the thing that gets hashed, and picking it well is the whole of sticky bucketing. The `False` is the coded default from section 4, evaluated when the provider cannot answer; it belongs in code review. And the flag key is read exactly once per request path, into a local variable if you need it twice — **never call the flag twice in one request**, because two evaluations can straddle a ruleset update and give you two different answers within one response.

Configuration for the provider itself comes from the environment, which is Lesson 5's twelve-factor rule: the SDK key is a secret, the environment name (`production`, `staging`) is config, and the flag *rules* are neither — they are runtime state owned by the control plane.

### The implementations, and the property to insist on

- **LaunchDarkly** — commercial, streaming ruleset updates over Server-Sent Events, local evaluation, a relay proxy for air-gapped or high-fan-out deployments.
- **Unleash** — open source with a commercial tier, self-hostable, polling by default with local evaluation of the fetched rules.
- **Flagsmith** — open source, self-hostable, offers both remote evaluation and local evaluation with a cached environment document.

Whichever you pick, the architecture to insist on is the same: **the ruleset streams to the process and evaluation happens in-process.** Ask three questions during evaluation. How does an update reach a running process, and what is the worst-case delay (section 5: 4.3 s versus 33.4 s)? What happens when the control plane is unreachable — does the SDK serve from its last known ruleset, and does it persist that ruleset across a process restart? And is there a bounded timeout on initialization, so a slow control plane at boot cannot stop your service from starting?

That last one is a real outage shape: an SDK that blocks on initialization with no timeout turns "the flag vendor is slow" into "our pods never pass readiness", which is how a soft dependency becomes a hard one. [Health Checks & Probes](../../09-logging-monitoring-and-observability/08-health-checks-and-probes/) has the classification: a flag service is a **soft** dependency, and your startup path must treat it as one.

### Flags as a per-user canary

Lesson 11's canary picks *instances*. A flag picks *users*, and the two compose:

```yaml
# The deploy canary (Lesson 11) answers: is this ARTIFACT healthy?
# It ships the code with every new flag defaulted OFF.
strategy:
  canary:
    steps: [{setWeight: 5}, {pause: {duration: 10m}}, {setWeight: 50}, {pause: {duration: 10m}}]

# The release ramp answers: is this BEHAVIOUR healthy?
# Same artifact everywhere; only exposure moves.
#   internal=true      ->  100%    (staff, day 1)
#   region=eu          ->  0%      (blocked pending DPA review)
#   plan=enterprise    ->  5%      (day 2, with an owner watching)
#   everyone           ->  1% -> 5% -> 25% -> 100%   (days 3-9)
```

The ramp schedule is only as good as the criteria attached to it. Write down, before the first step: which metric decides, what threshold aborts, and **how long each step must run to see the effect**. That last one is where ramps are most often wrong — at 1% exposure you are collecting 1% of the events, so detecting a small regression takes a hundred times longer than it would at full traffic, and a ten-minute soak at 1% frequently proves nothing at all.

Two composition rules. **Never ramp exposure during a deploy.** If both the artifact and the exposure are changing, an anomaly has two candidate causes and you will spend the incident arguing about which. And **flags must be evaluated consistently across services**: if your API gateway and your checkout service both evaluate `checkout_v2` for the same request, they must agree, which means both must use the same stable identifier and the same salt. Propagate the *decision*, not the flag key, where you can — pass the evaluated variant in the request context ([Correlation & Request Context](../../09-logging-monitoring-and-observability/03-correlation-and-request-context/)) so downstream services inherit an answer instead of recomputing one against a ruleset that may have updated in between.

### Flags and the database

A flag that changes *which column is read* is not a pure exposure change — it is a schema dependency. If the new code path reads `price_cents` and the old one reads `price`, then flipping the flag on requires `price_cents` to already exist and be populated, and flipping it *off* again requires `price` to still be there. That constraint is precisely the expand/contract window Lesson 13 builds: expand the schema so both shapes work, migrate behind the flag, and only contract once the flag is gone and deleted. **A flag is only reversible inside that window.** Outside it, flipping the flag back is a data error, and you have quietly rebuilt the all-or-nothing rollback you were trying to escape.

The same applies to anything the new path writes that the old path cannot read: a new event schema, a new cache key format ([Invalidation & TTLs](../../05-caching/05-invalidation-and-ttls/)), a new message payload. Before you ship a flag, answer one question in writing: **if I flip this back after an hour of traffic, is every row and message the new path produced still readable by the old path?** If the answer is no, the flag is a one-way door wearing a two-way door's costume.

### Flag hygiene, and the rules that survive an incident

- **Every flag has an owner and an expiry date, recorded at creation.** Not a wiki page — a required field, enforced by the tool or by a pre-commit check on your flag definitions. A flag with no owner is a flag nobody will dare to delete.
- **Removal is in the definition of done.** The rollout is not finished when exposure hits 100%; it is finished when the flag and the dead branch are gone from the code and the console. Book the cleanup ticket in the same sprint as the rollout, not the next one.
- **Run a stale-flag dashboard and look at it weekly.** Flags past expiry, flags at 100% for more than a week, flags at 0% for more than a month, flags with no evaluations in 30 days. Each of those has a different meaning and a different fix.
- **Never let a release toggle silently become business logic.** If a "temporary" flag has been at 30% for six months because the team likes it that way, it is now a product decision living in an incident-response tool with no tests. Either finish the rollout or move it into the code as an explicit, tested rule.
- **Test both branches, and test the default.** Both sides of the flag belong in CI (continuous integration). So does the coded fallback: write a test that runs with the provider unavailable and asserts the value your users would get.
- **Exercise your kill switches on a schedule.** A kill switch that has not been flipped in a year is untested code on the path you need most. Flip it in staging monthly, and in production during a quiet window at least once a quarter.
- **Log the evaluated variant with request context.** The evaluated value, the flag key, the rule that matched, and the trace/request id, on every request that hits a flagged path. Without it, "what did this user see?" is unanswerable, and that is the first question in every incident involving a flag.
- **Alert on exposure, not just on errors.** A flag that jumped from 5% to 100% because someone fat-fingered a rule should page you *on the exposure change*, before the error rate catches up.

Five rules to carry out of this lesson: **evaluate locally**, **default safely and per-flag**, **bucket deterministically with a per-flag salt**, **log the evaluated variant with request context**, and **delete flags on a schedule.**

## Think about it

1. Your rollout is at 10%, sticky-bucketed on `user.id`. Marketing asks you to also expose "everyone in the beta programme", which is 6% of users and heavily overlaps with paying customers. If you add that as a second rule, what is your realised exposure, and what does that do to the experiment you were running on the same flag? What would you need to change to keep the 10% measurable?
2. A user reports that the new checkout worked yesterday and is gone today. Nothing was flipped: exposure has been at 10% all week. List every mechanism that could produce that symptom under *correct* sticky bucketing, and say which log line would distinguish them.
3. Section 4 shows fail-open and fail-closed are each right for exactly one kind of flag. Design the rule you would enforce in code review to make sure a new flag's default is chosen deliberately — and describe how it fails when someone changes a release toggle into a kill switch six months later.
4. Your flag SDK evaluates locally against a cached ruleset with a 1-second TTL, and your service is behind a CDN that caches responses for 60 seconds. You flip a flag to 0%. When does the last affected user actually stop seeing the broken behaviour, and which of the two caches is the one you can do something about?
5. You have 40 live flags and a mandate to get to 27. Order the 13 deletions, and say what evidence you would require before deleting each of the four kinds. Which kind is the most dangerous to delete, and what would you check that has nothing to do with the flag system?

## Key takeaways

- **Deploy and release are different events, and coupling them is what makes rollback all-or-nothing.** An artifact carrying 40 merged changes has exactly one lever, so mitigating one change reverts the other 39. Separating them lets code ship continuously and dark while exposure moves independently — and turns mitigation into a control-plane write rather than a build.
- **A percentage rollout without sticky bucketing is not a rollout.** Measured over 200,000 evaluations, a fresh random draw per request hit a perfect-looking **9.97% of requests** while exposing **98.52% of users** to the new path, with **35,073 variant switches**. Hashing `sha256(flag_salt + ":" + user_id)` gave **0.00% flicker, 0 switches**, and made the user share and request share the same number (**10.86%**) — which is the property that makes "10%" mean anything.
- **The salt makes cohorts independent; without it you have one permanent test population.** Two flags at 10% over 50,000 users overlapped **9.74%** with a per-flag salt — exactly what independence predicts — and **100.00%** without one: the identical **4,972 people** meeting every change first, and confounding every experiment.
- **What happens when the flag service is unreachable is a per-flag design decision.** A hard dependency turned a 2,500-request outage window into **2,500 of your own 5xx**. Fail-open is correct for a kill switch and shipped an unfinished feature to **2,261 users** on a new path; fail-closed is the mirror image. A cached ruleset with local evaluation was wrong **zero** times, because it still knows the rules instead of guessing the answer.
- **On a risky path, a kill switch is not a convenience — it is the difference.** Mitigating by flag flip took **4.3 s**; rolling back the same deploy took **304 s (71×)**, or **10,444 extra failed requests at 850 req/s**. Remove the human decision from both and the ratio gets *worse* (**113×**): the cost is machinery, not deliberation. A 30-second polling SDK instead of a streaming one costs **33.4 s instead of 4.3 s** for the identical flip.
- **Flag debt is arithmetic.** N flags means 2^N reachable configurations; at 30 flags a generous test strategy covers **one in 2.3 million.** In a 40-flag inventory, **13 were past expiry and the oldest release toggle was 190 days old** — deleting them shrinks the state space **8,192×** for an afternoon's work. Give every flag an owner and an expiry, and put removal in the definition of done.

Next: [Zero-Downtime Schema & Contract Changes](../13-zero-downtime-schema-changes/) — a flag is only reversible while both the old and new data shapes work, so the next lesson builds the expand/contract window that makes flipping back safe.
