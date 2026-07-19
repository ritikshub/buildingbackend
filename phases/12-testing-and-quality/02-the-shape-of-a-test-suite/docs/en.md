# The Shape of a Test Suite: Pyramid, Trophy & the Honest Trade-off

> Two teams, one service, one bug budget. Team A's 4,000 unit tests run in **40 seconds** and have a **hard ceiling of 34%** of the defect population — not a low score, a ceiling, because a unit test's scope is one function and a wiring defect lives on the edge between two. Team B's 180 end-to-end tests reach **95.7%** and turn a clean build green **11.4%** of the time, so nobody reads a red build. Then the result nobody computes: solve the allocation numerically at a fixed CI budget and the optimum is a **pyramid by test count and never a pyramid by CI seconds** — at 600 s it is 6.1% unit tests holding 0.1% of the budget. Same 600 seconds, the best and worst named shapes are **52.6 points of detection apart**.

**Type:** Build
**Languages:** Python
**Prerequisites:** [Why Tests Exist: The Cost of Finding a Bug Late](../01-why-tests-exist/), [CI/CD: From Commit to Artifact to Environment](../../10-infrastructure-and-deployment/10-ci-cd-pipelines/)
**Time:** ~70 minutes

## The Problem

The orders service was split between two teams in a reorg eighteen months ago. Same codebase at the fork, same language, same deploy pipeline, same on-call rota, same rough number of engineers. Nobody wrote a testing strategy document. Both teams just started adding tests, and today the two halves of one service are as different as two companies.

**Team A, 09:12.** Their CI badge says `4,000 passed in 40s` and their coverage gate says **94%**. Both numbers are real. Both are on a dashboard in the team room. The suite is genuinely fast, genuinely green, and genuinely nobody's source of anxiety — a full run costs less than the time it takes to write the commit message.

**Team A, 09:47.** Incident. The refund worker has been writing `amount_cents` into a column that a migration renamed to `total_cents` eleven days ago. Both the worker and the repository have unit tests. Both pass. The worker's test constructs a `Refund` object and asserts the repository is called with the right dictionary; the repository's test constructs a dictionary and asserts the SQL is built correctly. Each test is correct. The *pair* has never run together, and the field name disagrees between them.

This is Team A's fourth production incident this quarter and the fourth one of exactly this shape: two components that are individually correct and jointly wrong.

**Team B, 09:12.** Their suite is 180 end-to-end tests through the real HTTP surface, a real Postgres, a real queue and a stubbed payment sandbox. Wall time is **42 minutes**. It catches things — it caught the `total_cents` rename on the day it landed, because it exercises the actual wiring. It also fails constantly.

**Team B, 11:20.** A pull request is red. The author looks at it for nine seconds, sees `test_checkout_applies_promotion` in the failure list, recognises it as "the flaky one", and clicks re-run. The re-run is green. It merges. Nobody was negligent: the measured per-test flake rate on that suite is **1.2%**, and 180 tests at 1.2% means a clean build comes back green

```text
P(green | nothing is wrong) = (1 - 0.012)^180 = 11.4%
```

**11.4%.** Not "flaky sometimes". Nearly nine builds in ten are red on a tree with no defect in it. In that world, re-running is not laziness; it is the only policy that lets anyone ship, and the cost is that the suite has stopped answering the question it was built to answer. A red build carries almost no information, so nobody spends information-gathering effort on it.

**14:30, joint retro.** Team A proposes the pyramid: mostly unit tests, some integration, few end-to-end. Team B points out that they *have* the thing that catches real bugs and Team A's 94% coverage did not catch a field rename. Team A points at the 42-minute suite. Both are right about the other team and neither has a number.

Here is what nobody in the room has: **Team A's ceiling is not a policy, it is arithmetic.** Their unit tests can reach at most 34% of the defects this service actually produces, and the rest is not "more unit tests away" — it is a set of defect classes that a unit test's environment cannot express at all. And **Team B's 42 minutes is not a fixed price for that reach.** Solved numerically, the same 42 minutes of CI buys 98.4% instead of 95.7% if it is spent differently — and a *quarter* of that budget buys 89.0%.

The argument the two teams are having has an answer, and the answer is not a shape you pick from a diagram:

> **The shape of your suite is not a style choice. It is the solution to an allocation problem, and it is determined by your cost ratios, your flake rates and the capability ceiling of each level — three things you can measure this afternoon.**

## The Concept

Everything below is computed by [`code/suite_shape.py`](code/suite_shape.py) on one model service: a 64-function, 1,765-line call graph with 114 call edges, a 12-class defect population, and four test levels. Nothing here is quoted from a study. The model's inputs are declared in the file header and swept later in the lesson, so you can see which conclusions survive different inputs and which do not.

### The three axes every test trades between

Strip the vocabulary away and every test level is a point on the same three axes.

**Run cost** is how many CI seconds one test consumes. **Failure localisation** is how much code a single red test implicates — the set of lines that could contain the cause. **Flake rate** is the probability that this test reds on a tree where nothing is wrong.

Those three are the trade everyone knows about, and taken alone they say "write unit tests" unanimously. There is a fourth, which is the one that decides the answer, and it is not a trade at all: **reach** — the share of the defect population that this level's *environment* can express. A unit test has no database, so it cannot fail on a `UNIQUE` constraint over a nullable column no matter how well it is written. That is not a low probability. It is zero.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 424" width="100%" style="max-width:840px" role="img" aria-label="The four test levels compared on four measured axes, as four cards. Unit tests cost 0.010 seconds each, implicate 28 lines when they fail, flake on 0.002 percent of clean runs, and can reach at most 34 percent of the defect population. Contract tests cost 0.25 seconds, implicate 24 lines, flake at 0.06 percent, and reach 23 percent. Integration tests cost 0.80 seconds, implicate 171 lines, flake at 0.20 percent, and reach 56 percent. End-to-end tests cost 14.0 seconds, implicate 369 lines across 4.7 layers, flake at 1.20 percent, and are the only level that reaches the whole population. An end-to-end test therefore costs 1400 times a unit test and implicates 13 times as much code.">
  <g id="p12-02-fig1" font-family="'JetBrains Mono', ui-monospace, monospace">
    <text x="440" y="26" text-anchor="middle" font-size="14.5" font-weight="700" fill="currentColor">Every test trades the same three things — and the fourth decides the shape</text>
    <text x="440" y="46" text-anchor="middle" font-size="10" fill="currentColor" opacity="0.8">measured on one 64-function, 1,765-line service with 114 call edges</text>

    <g fill="none" stroke-width="1.8">
      <rect x="22" y="62" width="194" height="268" rx="10" fill="#0fa07f" fill-opacity="0.10" stroke="#0fa07f"/>
      <rect x="236" y="62" width="194" height="268" rx="10" fill="#3553ff" fill-opacity="0.10" stroke="#3553ff"/>
      <rect x="450" y="62" width="194" height="268" rx="10" fill="#7c5cff" fill-opacity="0.10" stroke="#7c5cff"/>
      <rect x="664" y="62" width="194" height="268" rx="10" fill="#e0930f" fill-opacity="0.12" stroke="#e0930f"/>
    </g>
    <g text-anchor="middle" font-size="12" font-weight="700">
      <text x="119" y="86" fill="#0fa07f">unit</text><text x="333" y="86" fill="#3553ff">contract</text><text x="547" y="86" fill="#7c5cff">integration</text><text x="761" y="86" fill="#e0930f">end-to-end</text>
    </g>
    <g fill="none" stroke="currentColor" stroke-width="1" opacity="0.35">
      <path d="M36 96 L 202 96"/><path d="M250 96 L 416 96"/><path d="M464 96 L 630 96"/><path d="M678 96 L 844 96"/>
    </g>

    <g fill="currentColor" font-size="8" font-weight="700" opacity="0.6">
      <text x="36" y="120">RUN COST, CI s</text><text x="250" y="120">RUN COST, CI s</text><text x="464" y="120">RUN COST, CI s</text><text x="678" y="120">RUN COST, CI s</text>
      <text x="36" y="164">LINES IMPLICATED</text><text x="250" y="164">LINES IMPLICATED</text><text x="464" y="164">LINES IMPLICATED</text><text x="678" y="164">LINES IMPLICATED</text>
      <text x="36" y="208">FLAKE PER RUN</text><text x="250" y="208">FLAKE PER RUN</text><text x="464" y="208">FLAKE PER RUN</text><text x="678" y="208">FLAKE PER RUN</text>
      <text x="36" y="252">CEILING: REACHABLE</text><text x="250" y="252">CEILING: REACHABLE</text><text x="464" y="252">CEILING: REACHABLE</text><text x="678" y="252">CEILING: REACHABLE</text>
    </g>
    <g fill="currentColor" font-size="13" font-weight="700" text-anchor="end">
      <text x="202" y="120">0.010</text><text x="416" y="120">0.25</text><text x="630" y="120">0.80</text><text x="844" y="120">14.0</text>
      <text x="202" y="164">28</text><text x="416" y="164">24</text><text x="630" y="164">171</text><text x="844" y="164">369</text>
      <text x="202" y="208">0.002%</text><text x="416" y="208">0.06%</text><text x="630" y="208">0.20%</text><text x="844" y="208">1.20%</text>
      <text x="202" y="252">34%</text><text x="416" y="252">23%</text><text x="630" y="252">56%</text><text x="844" y="252">100%</text>
    </g>

    <g opacity="0.30">
      <rect x="36" y="126" width="166" height="6" rx="3" fill="currentColor"/><rect x="250" y="126" width="166" height="6" rx="3" fill="currentColor"/><rect x="464" y="126" width="166" height="6" rx="3" fill="currentColor"/><rect x="678" y="126" width="166" height="6" rx="3" fill="currentColor"/>
      <rect x="36" y="170" width="166" height="6" rx="3" fill="currentColor"/><rect x="250" y="170" width="166" height="6" rx="3" fill="currentColor"/><rect x="464" y="170" width="166" height="6" rx="3" fill="currentColor"/><rect x="678" y="170" width="166" height="6" rx="3" fill="currentColor"/>
      <rect x="36" y="214" width="166" height="6" rx="3" fill="currentColor"/><rect x="250" y="214" width="166" height="6" rx="3" fill="currentColor"/><rect x="464" y="214" width="166" height="6" rx="3" fill="currentColor"/><rect x="678" y="214" width="166" height="6" rx="3" fill="currentColor"/>
      <rect x="36" y="258" width="166" height="6" rx="3" fill="currentColor"/><rect x="250" y="258" width="166" height="6" rx="3" fill="currentColor"/><rect x="464" y="258" width="166" height="6" rx="3" fill="currentColor"/><rect x="678" y="258" width="166" height="6" rx="3" fill="currentColor"/>
    </g>
    <g>
      <rect x="36" y="126" width="40.0" height="6" rx="3" fill="#0fa07f"/><rect x="250" y="126" width="96.0" height="6" rx="3" fill="#3553ff"/><rect x="464" y="126" width="116.2" height="6" rx="3" fill="#7c5cff"/><rect x="678" y="126" width="166" height="6" rx="3" fill="#e0930f"/>
      <rect x="36" y="170" width="12.6" height="6" rx="3" fill="#0fa07f"/><rect x="250" y="170" width="10.8" height="6" rx="3" fill="#3553ff"/><rect x="464" y="170" width="76.9" height="6" rx="3" fill="#7c5cff"/><rect x="678" y="170" width="166" height="6" rx="3" fill="#e0930f"/>
      <rect x="36" y="214" width="3" height="6" rx="1.5" fill="#0fa07f"/><rect x="250" y="214" width="8.3" height="6" rx="3" fill="#3553ff"/><rect x="464" y="214" width="27.7" height="6" rx="3" fill="#7c5cff"/><rect x="678" y="214" width="166" height="6" rx="3" fill="#e0930f"/>
      <rect x="36" y="258" width="56.4" height="6" rx="3" fill="#0fa07f"/><rect x="250" y="258" width="38.2" height="6" rx="3" fill="#3553ff"/><rect x="464" y="258" width="92.9" height="6" rx="3" fill="#7c5cff"/><rect x="678" y="258" width="166" height="6" rx="3" fill="#e0930f"/>
    </g>

    <g font-size="8.5" fill="currentColor" opacity="0.9">
      <text x="36" y="286">1 function,</text><text x="36" y="298">1 layer, no</text><text x="36" y="310">database at all</text>
      <text x="250" y="286">1 seam node,</text><text x="250" y="298">over the wire,</text><text x="250" y="310">shape not behaviour</text>
      <text x="464" y="286">7.4 functions,</text><text x="464" y="298">3.0 layers,</text><text x="464" y="310">a real database</text>
      <text x="678" y="286">16.0 functions,</text><text x="678" y="298">4.7 layers,</text><text x="678" y="310">the whole world</text>
    </g>

    <rect x="22" y="344" width="836" height="42" rx="9" fill="#7f7f7f" fill-opacity="0.08" stroke="currentColor" stroke-opacity="0.4" stroke-width="1.4"/>
    <text x="40" y="362" font-size="10.5" font-weight="700" fill="currentColor">end-to-end vs unit:</text>
    <text x="196" y="362" font-size="10.5" font-weight="700" fill="#e0930f">1,400x the CI seconds</text>
    <text x="372" y="362" font-size="10.5" font-weight="700" fill="#e0930f">13x the code to read</text>
    <text x="540" y="362" font-size="10.5" font-weight="700" fill="#e0930f">600x the flake rate</text>
    <text x="700" y="362" font-size="10.5" font-weight="700" fill="#0fa07f">3x the reach</text>
    <text x="40" y="378" font-size="9" fill="currentColor" opacity="0.85">Three of those four favour the cheap level. The fourth is a hard capability limit, and it is the one that decides the answer.</text>

    <text x="440" y="410" text-anchor="middle" font-size="11.5" font-weight="700" fill="currentColor">A level is not better or worse. It is a different price for a different reach.</text>
  </g>
</svg>
```

Read the three cost axes first. An end-to-end test costs **1,400×** a unit test's CI seconds, implicates **13×** the code when it fails (369 lines across 4.7 architectural layers versus 28 lines in 1), and reds on a clean tree **600×** more often. Every one of those favours the cheap level, decisively.

Now read the fourth. The unit level tops out at **34%** of the defect population; end-to-end reaches **100%**. That single column is why the answer is not "write unit tests", and the rest of the lesson is the arithmetic of trading it off against the other three.

One clarification on the second axis, since it is the one people quote loosest. "Implicated lines" here means the transitive call closure of the test's entry point — the code the test actually executed, and therefore the code that could contain the cause. It is a lower bound on the search. In practice an end-to-end failure implicates more than that, because it can also be the configuration, the container, the network or the test itself, and you usually cannot tell which from the failure message.

### The catch matrix: a capability is a hard zero, not a small number

To turn "reach" into a number you need a model of what a defect *is* and what a test *does*, and the model can be almost embarrassingly simple. A defect is a (class, site) pair — a kind of mistake, at a location in the call graph. A test detects it when three things all hold:

1. **Capability** — the level's environment can express the defect at all. No database, no schema defects.
2. **Scope** — the test actually executes that site. A test's scope is the call closure of its entry point.
3. **Oracle** — the test's assertion observes the resulting difference. Executing a wrong line is not the same as noticing it.

Multiply those three and average over every possible site and every possible test scope, and you get a per-test detection probability for each (level, class) pair. The program does this **exhaustively** — every defect site crossed with every scope a test at that level could have — so the matrix below is a computation over the graph rather than an opinion about how good unit tests are.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 556" width="100%" style="max-width:840px" role="img" aria-label="The catch matrix: the probability that one test at each level detects one defect of each of twelve classes, per thousand, computed exhaustively over every defect site and every possible test scope on the call graph. A grey dash marks a hard zero, meaning that level's environment cannot express that defect at any test count. Unit tests reach only logic and boundary defects, at 3.7 and 4.0 per thousand, and are a hard zero for the other ten classes including wiring, which lives on the edge between two functions. Contract tests reach serialization, contract and auth defects only. Integration tests reach logic, boundary, wiring, schema and migration. End-to-end tests reach every class and are the only level that reaches concurrency, config, duplicate delivery and N plus 1 queries. Summed by class weight the ceilings are 34 percent for unit, 23 percent for contract, 56 percent for integration and 100 percent for end-to-end.">
  <g id="p12-02-fig2" font-family="'JetBrains Mono', ui-monospace, monospace">
    <text x="440" y="26" text-anchor="middle" font-size="14.5" font-weight="700" fill="currentColor">The catch matrix: not "how good is a unit test" but "what can it reach at all"</text>
    <text x="440" y="46" text-anchor="middle" font-size="10" fill="currentColor" opacity="0.8">P(one test detects one defect of this class) x1000 &#183; exhaustive over every site x every scope</text>

    <g fill="currentColor" font-size="8.5" font-weight="700" opacity="0.62">
      <text x="24" y="76">DEFECT CLASS</text><text x="180" y="76" text-anchor="end">WEIGHT</text><text x="248" y="76" text-anchor="middle">unit</text><text x="372" y="76" text-anchor="middle">contract</text><text x="496" y="76" text-anchor="middle">integration</text><text x="620" y="76" text-anchor="middle">end-to-end</text><text x="686" y="76">CAN REACH IT</text>
    </g>
    <path d="M18 82 L 862 82" fill="none" stroke="currentColor" stroke-width="1.3" opacity="0.45"/>

    <g fill="currentColor">
      <text x="24" y="106" font-size="10">logic</text><text x="180" y="106" font-size="9.5" text-anchor="end" opacity="0.75">0.20</text>
      <rect x="192" y="90" width="112" height="22" rx="4" fill="#0fa07f" fill-opacity="0.12" stroke="#0fa07f" stroke-width="1.1"/><text x="248" y="106" font-size="9.5" text-anchor="middle" font-weight="700">3.7</text><path d="M365 101 L 379 101" stroke="#7f7f7f" stroke-width="2" opacity="0.55"/><rect x="440" y="90" width="112" height="22" rx="4" fill="#7c5cff" fill-opacity="0.33" stroke="#7c5cff" stroke-width="1.1"/><text x="496" y="106" font-size="9.5" text-anchor="middle" font-weight="700">46.7</text><rect x="564" y="90" width="112" height="22" rx="4" fill="#e0930f" fill-opacity="0.44" stroke="#e0930f" stroke-width="1.1"/><text x="620" y="106" font-size="9.5" text-anchor="middle" font-weight="700">69.2</text>
      <text x="686" y="106" font-size="8.5" opacity="0.85">unit,integration,e2e</text>
      <text x="24" y="134" font-size="10">boundary</text><text x="180" y="134" font-size="9.5" text-anchor="end" opacity="0.75">0.14</text>
      <rect x="192" y="118" width="112" height="22" rx="4" fill="#0fa07f" fill-opacity="0.12" stroke="#0fa07f" stroke-width="1.1"/><text x="248" y="134" font-size="9.5" text-anchor="middle" font-weight="700">4.0</text><path d="M365 129 L 379 129" stroke="#7f7f7f" stroke-width="2" opacity="0.55"/><rect x="440" y="118" width="112" height="22" rx="4" fill="#7c5cff" fill-opacity="0.31" stroke="#7c5cff" stroke-width="1.1"/><text x="496" y="134" font-size="9.5" text-anchor="middle" font-weight="700">42.7</text><rect x="564" y="118" width="112" height="22" rx="4" fill="#e0930f" fill-opacity="0.41" stroke="#e0930f" stroke-width="1.1"/><text x="620" y="134" font-size="9.5" text-anchor="middle" font-weight="700">62.8</text>
      <text x="686" y="134" font-size="8.5" opacity="0.85">unit,integration,e2e</text>
      <text x="24" y="162" font-size="10">wiring</text><text x="180" y="162" font-size="9.5" text-anchor="end" opacity="0.75">0.11</text>
      <path d="M241 157 L 255 157" stroke="#7f7f7f" stroke-width="2" opacity="0.55"/><path d="M365 157 L 379 157" stroke="#7f7f7f" stroke-width="2" opacity="0.55"/><rect x="440" y="146" width="112" height="22" rx="4" fill="#7c5cff" fill-opacity="0.13" stroke="#7c5cff" stroke-width="1.1"/><text x="496" y="162" font-size="9.5" text-anchor="middle" font-weight="700">6.9</text><rect x="564" y="146" width="112" height="22" rx="4" fill="#e0930f" fill-opacity="0.17" stroke="#e0930f" stroke-width="1.1"/><text x="620" y="162" font-size="9.5" text-anchor="middle" font-weight="700">15.2</text>
      <text x="686" y="162" font-size="8.5" opacity="0.85">integration,e2e</text>
      <text x="24" y="190" font-size="10">serialization</text><text x="180" y="190" font-size="9.5" text-anchor="end" opacity="0.75">0.08</text>
      <path d="M241 185 L 255 185" stroke="#7f7f7f" stroke-width="2" opacity="0.55"/><rect x="316" y="174" width="112" height="22" rx="4" fill="#3553ff" fill-opacity="0.17" stroke="#3553ff" stroke-width="1.1"/><text x="372" y="190" font-size="9.5" text-anchor="middle" font-weight="700">13.7</text><path d="M489 185 L 503 185" stroke="#7f7f7f" stroke-width="2" opacity="0.55"/><rect x="564" y="174" width="112" height="22" rx="4" fill="#e0930f" fill-opacity="0.15" stroke="#e0930f" stroke-width="1.1"/><text x="620" y="190" font-size="9.5" text-anchor="middle" font-weight="700">10.0</text>
      <text x="686" y="190" font-size="8.5" opacity="0.85">contract,e2e</text>
      <text x="24" y="218" font-size="10">contract</text><text x="180" y="218" font-size="9.5" text-anchor="end" opacity="0.75">0.08</text>
      <path d="M241 213 L 255 213" stroke="#7f7f7f" stroke-width="2" opacity="0.55"/><rect x="316" y="202" width="112" height="22" rx="4" fill="#3553ff" fill-opacity="0.19" stroke="#3553ff" stroke-width="1.1"/><text x="372" y="218" font-size="9.5" text-anchor="middle" font-weight="700">17.4</text><path d="M489 213 L 503 213" stroke="#7f7f7f" stroke-width="2" opacity="0.55"/><rect x="564" y="202" width="112" height="22" rx="4" fill="#e0930f" fill-opacity="0.33" stroke="#e0930f" stroke-width="1.1"/><text x="620" y="218" font-size="9.5" text-anchor="middle" font-weight="700">46.9</text>
      <text x="686" y="218" font-size="8.5" opacity="0.85">contract,e2e</text>
      <text x="24" y="246" font-size="10">auth</text><text x="180" y="246" font-size="9.5" text-anchor="end" opacity="0.75">0.07</text>
      <path d="M241 241 L 255 241" stroke="#7f7f7f" stroke-width="2" opacity="0.55"/><rect x="316" y="230" width="112" height="22" rx="4" fill="#3553ff" fill-opacity="0.17" stroke="#3553ff" stroke-width="1.1"/><text x="372" y="246" font-size="9.5" text-anchor="middle" font-weight="700">13.7</text><path d="M489 241 L 503 241" stroke="#7f7f7f" stroke-width="2" opacity="0.55"/><rect x="564" y="230" width="112" height="22" rx="4" fill="#e0930f" fill-opacity="0.15" stroke="#e0930f" stroke-width="1.1"/><text x="620" y="246" font-size="9.5" text-anchor="middle" font-weight="700">10.0</text>
      <text x="686" y="246" font-size="8.5" opacity="0.85">contract,e2e</text>
      <text x="24" y="274" font-size="10">schema</text><text x="180" y="274" font-size="9.5" text-anchor="end" opacity="0.75">0.07</text>
      <path d="M241 269 L 255 269" stroke="#7f7f7f" stroke-width="2" opacity="0.55"/><path d="M365 269 L 379 269" stroke="#7f7f7f" stroke-width="2" opacity="0.55"/><rect x="440" y="258" width="112" height="22" rx="4" fill="#7c5cff" fill-opacity="0.27" stroke="#7c5cff" stroke-width="1.1"/><text x="496" y="274" font-size="9.5" text-anchor="middle" font-weight="700">34.4</text><rect x="564" y="258" width="112" height="22" rx="4" fill="#e0930f" fill-opacity="0.34" stroke="#e0930f" stroke-width="1.1"/><text x="620" y="274" font-size="9.5" text-anchor="middle" font-weight="700">49.5</text>
      <text x="686" y="274" font-size="8.5" opacity="0.85">integration,e2e</text>
      <text x="24" y="302" font-size="10">concurrency</text><text x="180" y="302" font-size="9.5" text-anchor="end" opacity="0.75">0.06</text>
      <path d="M241 297 L 255 297" stroke="#7f7f7f" stroke-width="2" opacity="0.55"/><path d="M365 297 L 379 297" stroke="#7f7f7f" stroke-width="2" opacity="0.55"/><path d="M489 297 L 503 297" stroke="#7f7f7f" stroke-width="2" opacity="0.55"/><rect x="564" y="286" width="112" height="22" rx="4" fill="#e0930f" fill-opacity="0.34" stroke="#e0930f" stroke-width="1.1"/><text x="620" y="302" font-size="9.5" text-anchor="middle" font-weight="700">49.5</text>
      <text x="686" y="302" font-size="8.5" opacity="0.85">e2e</text>
      <text x="24" y="330" font-size="10">config</text><text x="180" y="330" font-size="9.5" text-anchor="end" opacity="0.75">0.05</text>
      <path d="M241 325 L 255 325" stroke="#7f7f7f" stroke-width="2" opacity="0.55"/><path d="M365 325 L 379 325" stroke="#7f7f7f" stroke-width="2" opacity="0.55"/><path d="M489 325 L 503 325" stroke="#7f7f7f" stroke-width="2" opacity="0.55"/><rect x="564" y="314" width="112" height="22" rx="4" fill="#e0930f" fill-opacity="0.27" stroke="#e0930f" stroke-width="1.1"/><text x="620" y="330" font-size="9.5" text-anchor="middle" font-weight="700">34.1</text>
      <text x="686" y="330" font-size="8.5" opacity="0.85">e2e</text>
      <text x="24" y="358" font-size="10">duplicate</text><text x="180" y="358" font-size="9.5" text-anchor="end" opacity="0.75">0.05</text>
      <path d="M241 353 L 255 353" stroke="#7f7f7f" stroke-width="2" opacity="0.55"/><path d="M365 353 L 379 353" stroke="#7f7f7f" stroke-width="2" opacity="0.55"/><path d="M489 353 L 503 353" stroke="#7f7f7f" stroke-width="2" opacity="0.55"/><rect x="564" y="342" width="112" height="22" rx="4" fill="#e0930f" fill-opacity="0.14" stroke="#e0930f" stroke-width="1.1"/><text x="620" y="358" font-size="9.5" text-anchor="middle" font-weight="700">7.9</text>
      <text x="686" y="358" font-size="8.5" opacity="0.85">e2e</text>
      <text x="24" y="386" font-size="10">n_plus_1</text><text x="180" y="386" font-size="9.5" text-anchor="end" opacity="0.75">0.05</text>
      <path d="M241 381 L 255 381" stroke="#7f7f7f" stroke-width="2" opacity="0.55"/><path d="M365 381 L 379 381" stroke="#7f7f7f" stroke-width="2" opacity="0.55"/><path d="M489 381 L 503 381" stroke="#7f7f7f" stroke-width="2" opacity="0.55"/><rect x="564" y="370" width="112" height="22" rx="4" fill="#e0930f" fill-opacity="0.34" stroke="#e0930f" stroke-width="1.1"/><text x="620" y="386" font-size="9.5" text-anchor="middle" font-weight="700">49.5</text>
      <text x="686" y="386" font-size="8.5" opacity="0.85">e2e</text>
      <text x="24" y="414" font-size="10">migration</text><text x="180" y="414" font-size="9.5" text-anchor="end" opacity="0.75">0.04</text>
      <path d="M241 409 L 255 409" stroke="#7f7f7f" stroke-width="2" opacity="0.55"/><path d="M365 409 L 379 409" stroke="#7f7f7f" stroke-width="2" opacity="0.55"/><rect x="440" y="398" width="112" height="22" rx="4" fill="#7c5cff" fill-opacity="0.27" stroke="#7c5cff" stroke-width="1.1"/><text x="496" y="414" font-size="9.5" text-anchor="middle" font-weight="700">34.4</text><rect x="564" y="398" width="112" height="22" rx="4" fill="#e0930f" fill-opacity="0.34" stroke="#e0930f" stroke-width="1.1"/><text x="620" y="414" font-size="9.5" text-anchor="middle" font-weight="700">49.5</text>
      <text x="686" y="414" font-size="8.5" opacity="0.85">integration,e2e</text>
    </g>
    <path d="M18 426 L 862 426" fill="none" stroke="currentColor" stroke-width="1.3" opacity="0.45"/>

    <text x="24" y="450" font-size="10" font-weight="700" fill="currentColor">CEILING, whole population</text>
    <text x="248" y="450" font-size="13" text-anchor="middle" font-weight="700" fill="#0fa07f">34%</text>
    <text x="372" y="450" font-size="13" text-anchor="middle" font-weight="700" fill="#3553ff">23%</text>
    <text x="496" y="450" font-size="13" text-anchor="middle" font-weight="700" fill="#7c5cff">56%</text>
    <text x="620" y="450" font-size="13" text-anchor="middle" font-weight="700" fill="#e0930f">100%</text>
    <text x="686" y="450" font-size="8.5" fill="currentColor" opacity="0.85">at INFINITE test count</text>

    <rect x="18" y="464" width="844" height="58" rx="9" fill="#7f7f7f" fill-opacity="0.08" stroke="currentColor" stroke-opacity="0.4" stroke-width="1.4"/>
    <text x="36" y="484" font-size="10" font-weight="700" fill="#d64545">Read the dashes, not the numbers.</text>
    <text x="36" y="500" font-size="9" fill="currentColor" opacity="0.9">A dash is not "unlikely" &#8212; it is impossible. `wiring` is a dash under unit because a unit test's scope is ONE function and a wiring defect lives</text>
    <text x="36" y="514" font-size="9" fill="currentColor" opacity="0.9">on the edge between two. `schema` needs a database, `config` the real config, `duplicate` a queue. No test count buys a capability.</text>

    <text x="440" y="544" text-anchor="middle" font-size="11.5" font-weight="700" fill="currentColor">Any number of unit tests has a hard ceiling of 34% of this defect population.</text>
  </g>
</svg>
```

The numbers matter less than the dashes. A dash is a hard zero: a capability the environment does not have.

**`wiring` is a dash in the unit column by construction.** A wiring defect — the wrong argument at a call site, the field name that disagrees across a boundary, Team A's `total_cents` — lives on the *edge* between two functions. A unit test's scope is one node. The edge is never inside it. This is not a criticism of unit tests; it is a statement about what the word "unit" means, and it is 11% of the defect population.

Sum each column by class weight and you get the ceilings, which are the whole reason a suite has a shape:

| level | reachable share | what it alone can never see |
|---|---|---|
| unit | **34.0%** | wiring, schema, migration, config, contract, auth, serialization, concurrency, duplicates, N+1 |
| contract | 23.0% | anything that is not a message at a seam |
| integration | 56.0% | config, contract, concurrency, duplicates, N+1 |
| end-to-end | **100.0%** | — |

Team A's line coverage and this 34% *reachable* share are not in tension; they measure different things. Coverage says which lines ran. The ceiling says which defect classes the environment can even produce. [Coverage Lies, Mutation Testing Doesn't](../13-coverage-and-mutation-testing/) is the full treatment of that gap.

Two honest caveats about this matrix, because it is doing a lot of work later. First, the oracle strengths (0.85 unit, 0.80 contract, 0.70 integration, 0.55 end-to-end) are declared parameters, not measurements; they are swept in a later section so you can see how much the conclusion depends on them. Second, the model assumes tests are *randomly targeted*, which is generous to large suites — real tests cluster on the code someone was already thinking about, so real marginal returns diminish faster than this model's.

### Mike Cohn's pyramid, and what it actually claimed

The test pyramid comes from Mike Cohn, *Succeeding with Agile: Software Development Using Scrum* (Addison-Wesley, 2009), and the original claim is narrower and better than the version that gets quoted.

Cohn's argument was about **cost and brittleness**, in a specific historical context: the top of his pyramid was a *UI* test, driven through a record-and-replay tool against a screen, and those tests were slow, expensive to write, and broke whenever anyone moved a button. Given tests at the top that cost hundreds of times more and break for reasons unrelated to correctness, the conclusion "have fewer of them" follows immediately. It is an economic argument, and it was correct.

What it was not is a claim about virtue, and it was never a claim that the ratios are constants. The version that reaches teams today — "70% unit, 20% integration, 10% end-to-end" — attaches numbers Cohn did not give, in units (test counts) that nobody pays in, derived from cost ratios that belong to a different decade's tooling. A modern API-level end-to-end test against a containerised stack is nothing like a 2009 Selenium recording.

So the honest form of the pyramid is a conditional: **if your top level costs hundreds of times more than your bottom level and is much flakier, the optimal composition will have few of them.** That is a testable statement about *your* ratios, and the rest of this lesson tests it.

### The trophy, the honeycomb, and the library-versus-service split

Two later shapes push back, and both are arguments about backends specifically.

The **testing trophy** (named by Kent C. Dodds, 2018) widens the integration band into the largest one, on the argument that integration tests give the most confidence per test for application code. The **honeycomb** (named at Spotify by André Schaffer, 2018) makes essentially the same claim for microservices: a service is mostly *wiring* — HTTP in, database out, queue sideways — so the code that has the fewest bugs per line is precisely the code unit tests are best at.

The catch matrix says exactly why this is not a fashion cycle. Look at what a *library* is versus what a *service* is:

- A sort function, a date parser, a decimal money type — these are almost entirely `logic` and `boundary` defects, and those two classes are 34% of a service's population but nearly 100% of a library's. **For a library the unit ceiling is close to 1.0, and the pyramid is simply correct.**
- A backend service spends most of its lines moving data across boundaries it does not control: an HTTP contract, a database schema, a queue's delivery semantics, a config file, another team's API. Those are the classes with dashes in the unit column.

So "pyramid or trophy" is not a disagreement about testing. It is a disagreement about what kind of code you have, and the catch matrix is how you settle it for your own repo: take last quarter's production defects, classify them, and ask which of them your cheapest level could have expressed at all.

### Failure localisation, quantified

The argument for unit tests that everybody makes as a feeling — *they pin the bug down* — is measurable on the call graph, and it turns out to be worth putting a currency on.

```text
    level        implicated lines     share of   bisection   minutes to
                  mean   p90    max   codebase     steps      diagnose
    unit             28    48     57       1.6%         4.8           9.3
    contract         24    30     32       1.3%         4.6           8.8
    integration     171   303    426       9.7%         7.4          26.5
    e2e             369   537    592      20.9%         8.5          50.3
```

A failing end-to-end test implicates **369 lines** — a fifth of the whole service — against a unit test's **28**. In bisection terms that is only **3.7 extra halvings**, which is the honest version of the claim: localisation is a real advantage and a *logarithmic* one, not the order-of-magnitude difference the folklore implies. The minutes column converts it at 6 minutes to open a failure plus 0.12 minutes per implicated line, giving **9.3 minutes** to diagnose a unit failure against **50.3** for an end-to-end one.

Hold onto that 9.3-versus-50.3, because it is the term that decides an argument later that raw detection counting cannot.

Now the number that complicates the story, from the same run:

```text
    level        detection per CI-second   detection per implicated line
    unit                        129.681                      47.02
    contract                     13.756                     145.56
    integration                  24.837                     116.49
    e2e                           3.041                     115.22
```

Per CI-second the unit level wins by **two orders of magnitude** — 129.681 against 3.041. If detection per second were the objective, the answer would be "buy unit tests until you run out of money". It is not the objective, because of the ceiling. *Most detection per second* and *the suite you want* are different claims, and the next section is what happens when you stop arguing about which one is right and just solve for both at once.

### Budget allocation as an optimisation problem

Here is the question nobody states precisely, stated precisely. You have `B` seconds of CI per build. Choose how many tests to run at each level:

```text
maximise    sum_c  w_c * ( 1 - prod_L (1 - p_Lc)^{n_L} )
subject to  sum_L  n_L * cost_L  <=  B ,      n_L integer >= 0
```

where `w_c` is class `c`'s share of the defect population, `p_Lc` is the per-test detection probability from the catch matrix, and `n_L` is how many tests you buy at level `L`. The objective is the expected share of defects caught. The `prod` is the probability a defect survives *every* level, which is what makes the problem interesting: buying integration tests for schema defects also saturates the logic defects your unit tests were catching, so the levels are not independent purchases.

The objective is concave in each `n_L` and submodular overall, so greedy on marginal value per second plus local search gets very close. Rather than assert that, the program checks it — at a 60-second budget it enumerates every feasible composition and compares:

```text
    exhaustive  [609, 110, 33, 0]      -> 61.5815%
    greedy      [745, 111, 31, 0]      -> 61.5252%
    gap 0.0562 percentage points.
```

Two different compositions, essentially the same value — which is itself informative, and we come back to it. Now the sweep, which is the headline result of the lesson.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 600" width="100%" style="max-width:840px" role="img" aria-label="The headline result: the suite composition that maximises expected defects caught, solved numerically at eight CI budgets, drawn twice. The left panel shows each optimum as a share of CI seconds; the right panel shows the identical optimum as a share of test count. By test count the optimum is a pyramid at small budgets, 91.7 percent unit tests at a 30 second budget, and stops being one as the budget grows, reaching only 42.4 percent contract and 36.1 percent end-to-end at 4800 seconds. By CI seconds it is never a pyramid: unit tests take 26.1 percent of a 30 second budget and 0.1 percent of a 600 second budget, while end-to-end tests take 65.3 percent at 600 seconds and 94.8 percent at 4800 seconds. Detection climbs from 50.1 percent to 99.6 percent while the probability that a clean build comes back green collapses from 93.3 percent to 1.1 percent.">
  <g id="p12-02-fig3" font-family="'JetBrains Mono', ui-monospace, monospace">
    <text x="440" y="26" text-anchor="middle" font-size="14.5" font-weight="700" fill="currentColor">The optimal suite is a pyramid by test count and never one by CI seconds</text>
    <text x="440" y="46" text-anchor="middle" font-size="10" fill="currentColor" opacity="0.8">the SAME eight optima, drawn twice &#183; greedy + local search, verified against exhaustive enumeration</text>

    <g font-size="10.5" font-weight="700">
      <text x="272" y="76" text-anchor="middle" fill="currentColor">share of CI SECONDS &#8212; what you pay</text>
      <text x="592" y="76" text-anchor="middle" fill="currentColor">share of TEST COUNT &#8212; what you draw</text>
    </g>
    <g fill="currentColor" font-size="8.5" font-weight="700" opacity="0.62">
      <text x="120" y="106" text-anchor="end">BUDGET</text><text x="792" y="106" text-anchor="end">CAUGHT</text><text x="862" y="106" text-anchor="end">GREEN</text>
    </g>
    <g fill="none" stroke="currentColor" stroke-width="1" opacity="0.25">
      <path d="M202 112 L 202 442"/><path d="M272 112 L 272 442"/><path d="M342 112 L 342 442"/><path d="M522 112 L 522 442"/><path d="M592 112 L 592 442"/><path d="M662 112 L 662 442"/>
    </g>

    <g fill="currentColor">
      <text x="120" y="134" font-size="10" text-anchor="end" font-weight="700">30 s</text>
      <rect x="132.0" y="118" width="73.1" height="24" fill="#0fa07f" fill-opacity="0.38" stroke="#0fa07f" stroke-width="1"/><rect x="205.1" y="118" width="147.0" height="24" fill="#3553ff" fill-opacity="0.38" stroke="#3553ff" stroke-width="1"/><rect x="352.1" y="118" width="59.6" height="24" fill="#7c5cff" fill-opacity="0.38" stroke="#7c5cff" stroke-width="1"/>
      <rect x="452.0" y="118" width="256.8" height="24" fill="#0fa07f" fill-opacity="0.38" stroke="#0fa07f" stroke-width="1"/><rect x="708.8" y="118" width="20.7" height="24" fill="#3553ff" fill-opacity="0.38" stroke="#3553ff" stroke-width="1"/><rect x="729.5" y="118" width="2.5" height="24" fill="#7c5cff" fill-opacity="0.38" stroke="#7c5cff" stroke-width="1"/>
      <text x="792" y="134" font-size="10.5" text-anchor="end" font-weight="700">50.1%</text><text x="862" y="134" font-size="10" text-anchor="end" opacity="0.8">93.3%</text>
      <text x="120" y="174" font-size="10" text-anchor="end" font-weight="700">60 s</text>
      <rect x="132.0" y="158" width="34.7" height="24" fill="#0fa07f" fill-opacity="0.38" stroke="#0fa07f" stroke-width="1"/><rect x="166.7" y="158" width="129.4" height="24" fill="#3553ff" fill-opacity="0.38" stroke="#3553ff" stroke-width="1"/><rect x="296.1" y="158" width="115.6" height="24" fill="#7c5cff" fill-opacity="0.38" stroke="#7c5cff" stroke-width="1"/>
      <rect x="452.0" y="158" width="235.2" height="24" fill="#0fa07f" fill-opacity="0.38" stroke="#0fa07f" stroke-width="1"/><rect x="687.2" y="158" width="35.0" height="24" fill="#3553ff" fill-opacity="0.38" stroke="#3553ff" stroke-width="1"/><rect x="722.2" y="158" width="9.8" height="24" fill="#7c5cff" fill-opacity="0.38" stroke="#7c5cff" stroke-width="1"/>
      <text x="792" y="174" font-size="10.5" text-anchor="end" font-weight="700">61.5%</text><text x="862" y="174" font-size="10" text-anchor="end" opacity="0.8">86.6%</text>
      <text x="120" y="214" font-size="10" text-anchor="end" font-weight="700">120 s</text>
      <rect x="132.0" y="198" width="6.7" height="24" fill="#0fa07f" fill-opacity="0.38" stroke="#0fa07f" stroke-width="1"/><rect x="138.7" y="198" width="110.9" height="24" fill="#3553ff" fill-opacity="0.38" stroke="#3553ff" stroke-width="1"/><rect x="249.6" y="198" width="162.4" height="24" fill="#7c5cff" fill-opacity="0.38" stroke="#7c5cff" stroke-width="1"/>
      <rect x="452.0" y="198" width="143.1" height="24" fill="#0fa07f" fill-opacity="0.38" stroke="#0fa07f" stroke-width="1"/><rect x="595.1" y="198" width="94.1" height="24" fill="#3553ff" fill-opacity="0.38" stroke="#3553ff" stroke-width="1"/><rect x="689.2" y="198" width="43.1" height="24" fill="#7c5cff" fill-opacity="0.38" stroke="#7c5cff" stroke-width="1"/>
      <text x="792" y="214" font-size="10.5" text-anchor="end" font-weight="700">70.8%</text><text x="862" y="214" font-size="10" text-anchor="end" opacity="0.8">74.5%</text>
      <text x="120" y="254" font-size="10" text-anchor="end" font-weight="700">240 s</text>
      <rect x="132.0" y="238" width="0.6" height="24" fill="#0fa07f" fill-opacity="0.38" stroke="#0fa07f" stroke-width="1"/><rect x="132.6" y="238" width="66.6" height="24" fill="#3553ff" fill-opacity="0.38" stroke="#3553ff" stroke-width="1"/><rect x="199.2" y="238" width="114.8" height="24" fill="#7c5cff" fill-opacity="0.38" stroke="#7c5cff" stroke-width="1"/><rect x="314.0" y="238" width="98.0" height="24" fill="#e0930f" fill-opacity="0.38" stroke="#e0930f" stroke-width="1"/>
      <rect x="452.0" y="238" width="39.8" height="24" fill="#0fa07f" fill-opacity="0.38" stroke="#0fa07f" stroke-width="1"/><rect x="491.8" y="238" width="153.4" height="24" fill="#3553ff" fill-opacity="0.38" stroke="#3553ff" stroke-width="1"/><rect x="645.2" y="238" width="82.9" height="24" fill="#7c5cff" fill-opacity="0.38" stroke="#7c5cff" stroke-width="1"/><rect x="728.1" y="238" width="3.9" height="24" fill="#e0930f" fill-opacity="0.38" stroke="#e0930f" stroke-width="1"/>
      <text x="792" y="254" font-size="10.5" text-anchor="end" font-weight="700">77.9%</text><text x="862" y="254" font-size="10" text-anchor="end" opacity="0.8">63.3%</text>
      <text x="120" y="294" font-size="10" text-anchor="end" font-weight="700">600 s</text>
      <rect x="132.3" y="278" width="30.2" height="24" fill="#3553ff" fill-opacity="0.38" stroke="#3553ff" stroke-width="1"/><rect x="162.5" y="278" width="66.9" height="24" fill="#7c5cff" fill-opacity="0.38" stroke="#7c5cff" stroke-width="1"/><rect x="229.4" y="278" width="182.8" height="24" fill="#e0930f" fill-opacity="0.38" stroke="#e0930f" stroke-width="1"/>
      <rect x="452.0" y="278" width="17.1" height="24" fill="#0fa07f" fill-opacity="0.38" stroke="#0fa07f" stroke-width="1"/><rect x="469.1" y="278" width="145.9" height="24" fill="#3553ff" fill-opacity="0.38" stroke="#3553ff" stroke-width="1"/><rect x="615.0" y="278" width="101.4" height="24" fill="#7c5cff" fill-opacity="0.38" stroke="#7c5cff" stroke-width="1"/><rect x="716.3" y="278" width="16.0" height="24" fill="#e0930f" fill-opacity="0.38" stroke="#e0930f" stroke-width="1"/>
      <text x="792" y="294" font-size="10.5" text-anchor="end" font-weight="700">89.0%</text><text x="862" y="294" font-size="10" text-anchor="end" opacity="0.8">42.7%</text>
      <text x="120" y="334" font-size="10" text-anchor="end" font-weight="700">1200 s</text>
      <rect x="132.0" y="318" width="18.5" height="24" fill="#3553ff" fill-opacity="0.38" stroke="#3553ff" stroke-width="1"/><rect x="150.5" y="318" width="52.4" height="24" fill="#7c5cff" fill-opacity="0.38" stroke="#7c5cff" stroke-width="1"/><rect x="202.8" y="318" width="209.2" height="24" fill="#e0930f" fill-opacity="0.38" stroke="#e0930f" stroke-width="1"/>
      <rect x="452.0" y="318" width="19.6" height="24" fill="#0fa07f" fill-opacity="0.38" stroke="#0fa07f" stroke-width="1"/><rect x="471.6" y="318" width="125.2" height="24" fill="#3553ff" fill-opacity="0.38" stroke="#3553ff" stroke-width="1"/><rect x="596.8" y="318" width="110.0" height="24" fill="#7c5cff" fill-opacity="0.38" stroke="#7c5cff" stroke-width="1"/><rect x="706.8" y="318" width="25.2" height="24" fill="#e0930f" fill-opacity="0.38" stroke="#e0930f" stroke-width="1"/>
      <text x="792" y="334" font-size="10.5" text-anchor="end" font-weight="700">95.3%</text><text x="862" y="334" font-size="10" text-anchor="end" opacity="0.8">21.8%</text>
      <text x="120" y="374" font-size="10" text-anchor="end" font-weight="700">2400 s</text>
      <rect x="132.0" y="358" width="11.5" height="24" fill="#3553ff" fill-opacity="0.38" stroke="#3553ff" stroke-width="1"/><rect x="143.5" y="358" width="33.0" height="24" fill="#7c5cff" fill-opacity="0.38" stroke="#7c5cff" stroke-width="1"/><rect x="176.5" y="358" width="235.2" height="24" fill="#e0930f" fill-opacity="0.38" stroke="#e0930f" stroke-width="1"/>
      <rect x="452.0" y="358" width="14.3" height="24" fill="#0fa07f" fill-opacity="0.38" stroke="#0fa07f" stroke-width="1"/><rect x="466.3" y="358" width="117.9" height="24" fill="#3553ff" fill-opacity="0.38" stroke="#3553ff" stroke-width="1"/><rect x="584.2" y="358" width="105.3" height="24" fill="#7c5cff" fill-opacity="0.38" stroke="#7c5cff" stroke-width="1"/><rect x="689.4" y="358" width="42.6" height="24" fill="#e0930f" fill-opacity="0.38" stroke="#e0930f" stroke-width="1"/>
      <text x="792" y="374" font-size="10.5" text-anchor="end" font-weight="700">98.3%</text><text x="862" y="374" font-size="10" text-anchor="end" opacity="0.8">6.8%</text>
      <text x="120" y="414" font-size="10" text-anchor="end" font-weight="700">4800 s</text>
      <rect x="132.0" y="398" width="5.6" height="24" fill="#3553ff" fill-opacity="0.38" stroke="#3553ff" stroke-width="1"/><rect x="137.6" y="398" width="9.0" height="24" fill="#7c5cff" fill-opacity="0.38" stroke="#7c5cff" stroke-width="1"/><rect x="146.6" y="398" width="265.4" height="24" fill="#e0930f" fill-opacity="0.38" stroke="#e0930f" stroke-width="1"/>
      <rect x="452.0" y="398" width="118.7" height="24" fill="#3553ff" fill-opacity="0.38" stroke="#3553ff" stroke-width="1"/><rect x="570.7" y="398" width="59.9" height="24" fill="#7c5cff" fill-opacity="0.38" stroke="#7c5cff" stroke-width="1"/><rect x="630.6" y="398" width="101.1" height="24" fill="#e0930f" fill-opacity="0.38" stroke="#e0930f" stroke-width="1"/>
      <text x="792" y="414" font-size="10.5" text-anchor="end" font-weight="700">99.6%</text><text x="862" y="414" font-size="10" text-anchor="end" opacity="0.8">1.1%</text>
    </g>

    <g fill="none" stroke="currentColor" stroke-width="1.2" opacity="0.5">
      <path d="M132 444 L 412 444"/><path d="M452 444 L 732 444"/>
    </g>
    <g fill="currentColor" font-size="8.5" text-anchor="middle" opacity="0.7">
      <text x="132" y="458">0%</text><text x="272" y="458">50%</text><text x="412" y="458">100%</text><text x="452" y="458">0%</text><text x="592" y="458">50%</text><text x="732" y="458">100%</text>
    </g>

    <g font-size="9.5" font-weight="700">
      <rect x="132" y="470" width="12" height="12" rx="3" fill="#0fa07f" fill-opacity="0.38" stroke="#0fa07f" stroke-width="1"/><text x="150" y="480" fill="#0fa07f">unit</text>
      <rect x="204" y="470" width="12" height="12" rx="3" fill="#3553ff" fill-opacity="0.38" stroke="#3553ff" stroke-width="1"/><text x="222" y="480" fill="#3553ff">contract</text>
      <rect x="308" y="470" width="12" height="12" rx="3" fill="#7c5cff" fill-opacity="0.38" stroke="#7c5cff" stroke-width="1"/><text x="326" y="480" fill="#7c5cff">integration</text>
      <rect x="440" y="470" width="12" height="12" rx="3" fill="#e0930f" fill-opacity="0.38" stroke="#e0930f" stroke-width="1"/><text x="458" y="480" fill="#e0930f">end-to-end</text>
    </g>

    <rect x="18" y="496" width="844" height="60" rx="9" fill="#7f7f7f" fill-opacity="0.08" stroke="currentColor" stroke-opacity="0.4" stroke-width="1.4"/>
    <text x="36" y="516" font-size="10" font-weight="700" fill="currentColor">the same row, read twice &#8212; budget 600 s:</text>
    <text x="326" y="516" font-size="10" font-weight="700" fill="#0fa07f">6.1% of the TESTS are unit</text>
    <text x="570" y="516" font-size="10" font-weight="700" fill="#e0930f">0.1% of the SECONDS are unit</text>
    <text x="36" y="532" font-size="9" fill="currentColor" opacity="0.9">Both statements describe one suite: 30 unit, 258 contract, 179 integration, 28 end-to-end. Every published shape is drawn in the units on the right.</text>
    <text x="36" y="546" font-size="9" fill="currentColor" opacity="0.9">Your CI bill, your feedback latency and your flake budget are all denominated in the units on the left.</text>

    <text x="440" y="580" text-anchor="middle" font-size="11.5" font-weight="700" fill="currentColor">Detection climbs 50.1% &#8594; 99.6%. A clean build going green collapses 93.3% &#8594; 1.1%.</text>
  </g>
</svg>
```

Read the two panels against each other, because they are the *same eight suites* drawn in two different units.

**By test count, the optimum is a pyramid — at small budgets.** At 30 seconds it is 91.7% unit tests. And then it stops being one: by 600 seconds unit tests are 6.1% of the count, and by 4,800 seconds they are 0.0%.

**By CI seconds — the units you actually pay in — it is never a pyramid at all.** Unit tests take 26.1% of a 30-second budget, 2.4% of a 120-second one, and **0.1% of a 600-second one**. The bottom of the pyramid is not big in the currency that matters. It was never big in that currency. It is enormous in *count* precisely because it is negligible in *cost*, which is the same fact stated twice.

This is the point at which every diagram of the pyramid you have ever seen becomes ambiguous. A triangle with a wide base is drawn in *counts*. Your CI bill, your feedback latency and your flake budget are all denominated in *seconds*. The two pictures of a healthy suite are almost mirror images, and teams argue past each other for years without noticing they are using different axes.

Two more things fall out of that table.

**The optimum buys end-to-end tests, and it buys few of them.** Not zero — at 600 seconds it buys 28 — because they are the only level that reaches `config`, `concurrency`, `duplicate` and `n_plus_1`, which are 21% of the population between them. And not many, because at 14 seconds each they eat the budget. "A handful of end-to-end tests" turns out to be a numerical result, not a slogan.

**The marginal budget is brutally convex.** The first 30 seconds buys 50.1% of the population. The 4,200 seconds between 600 s and 4,800 s buys **10.6 more points**, and costs you a suite that goes green on a clean tree 1.1% of the time. Every suite stops somewhere, and it stops because of that curve, not because of virtue.

And now the finding that complicates the picture, which the program checks explicitly rather than hiding. At 600 seconds the optimiser reports 30 unit tests. Force it higher and pay out of the contract level:

```text
    forced unit count      resulting composition        caught
                 0       [0, 259, 179, 28]           89.019%
               500       [500, 239, 179, 28]         88.910%
              1000       [1000, 219, 179, 28]        88.763%
              2000       [2000, 179, 179, 28]        88.309%
              4000       [4000, 99, 179, 28]         86.098%
```

**The objective is nearly flat in the unit count.** Zero unit tests and two thousand unit tests differ by 0.7 points of detection. Once you have bought integration tests for the schema defects, those integration tests have already saturated the logic and boundary defects your unit tests were for — so on a pure detection objective, unit tests are close to worthless at the margin. That is a real result and I am not going to bury it. It is also *wrong as advice*, and the section that fixes it is the one that stops counting defects and starts counting minutes.

### Every named shape, priced at one budget

The named shapes are ratios of test counts. Scale each one to fill the identical 600-second budget and score them on the same population.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 500" width="100%" style="max-width:840px" role="img" aria-label="Every named test-suite shape scaled to fill the same 600-second CI budget, compared on the share of the defect population caught. All unit, which is 60,000 unit tests at this budget, catches 34.0 percent and cannot go higher. The ice-cream cone catches 77.4 percent, the 70/20/10 pyramid 78.1 percent, the 80/15/5 pyramid 78.1 percent, the honeycomb 78.9 percent, the testing trophy 86.6 percent, and the numerically optimal composition of 30 unit, 258 contract, 179 integration and 28 end-to-end tests catches 89.0 percent. The spread between the best and worst named shape at an identical budget is 52.6 percent of the defect population.">
  <g id="p12-02-fig4" font-family="'JetBrains Mono', ui-monospace, monospace">
    <text x="440" y="26" text-anchor="middle" font-size="14.5" font-weight="700" fill="currentColor">Same 600 seconds. Same code. Same engineers. 52.6 points apart.</text>
    <text x="440" y="46" text-anchor="middle" font-size="10" fill="currentColor" opacity="0.8">each named shape is a ratio of TEST COUNTS, scaled here to fill the identical CI budget</text>

    <g fill="currentColor" font-size="8.5" font-weight="700" opacity="0.62">
      <text x="24" y="94">SHAPE</text><text x="330" y="94" text-anchor="end">unit/ctrt/intg/e2e</text><text x="360" y="94">SHARE OF THE DEFECT POPULATION CAUGHT</text>
    </g>
    <g fill="none" stroke="currentColor" stroke-width="1" opacity="0.25">
      <path d="M454.5 100 L 454.5 390"/><path d="M557 100 L 557 390"/><path d="M659.5 100 L 659.5 390"/>
    </g>

    <g fill="currentColor">
      <text x="24" y="126" font-size="10.5" fill="#d64545" font-weight="700">all unit</text><text x="344" y="126" font-size="8.5" text-anchor="end" opacity="0.7">60,000 / 0 / 0 / 0</text><rect x="352.0" y="108" width="139.4" height="26" rx="4" fill="#d64545" fill-opacity="0.30" stroke="#d64545" stroke-width="1.6"/><text x="499.4" y="126" font-size="11" fill="#d64545">34.0%</text>
      <text x="24" y="168" font-size="10.5" fill="#e0930f" font-weight="700">ice-cream cone</text><text x="344" y="168" font-size="8.5" text-anchor="end" opacity="0.7">1409 / 6 / 13 / 41</text><rect x="352.0" y="150" width="317.3" height="26" rx="4" fill="#e0930f" fill-opacity="0.30" stroke="#e0930f" stroke-width="1.6"/><text x="677.3" y="168" font-size="11" fill="#e0930f">77.4%</text>
      <text x="24" y="210" font-size="10.5" fill="#7f7f7f" font-weight="700">pyramid 70/20/10</text><text x="344" y="210" font-size="8.5" text-anchor="end" opacity="0.7">719 / 0 / 76 / 38</text><rect x="352.0" y="192" width="320.2" height="26" rx="4" fill="#7f7f7f" fill-opacity="0.30" stroke="#7f7f7f" stroke-width="1.6"/><text x="680.2" y="210" font-size="11" fill="#7f7f7f">78.1%</text>
      <text x="24" y="252" font-size="10.5" fill="#7f7f7f" font-weight="700">pyramid 80/15/5</text><text x="344" y="252" font-size="8.5" text-anchor="end" opacity="0.7">959 / 0 / 108 / 36</text><rect x="352.0" y="234" width="320.2" height="26" rx="4" fill="#7f7f7f" fill-opacity="0.30" stroke="#7f7f7f" stroke-width="1.6"/><text x="680.2" y="252" font-size="11" fill="#7f7f7f">78.1%</text>
      <text x="24" y="294" font-size="10.5" fill="#7c5cff" font-weight="700">honeycomb</text><text x="344" y="294" font-size="8.5" text-anchor="end" opacity="0.7">905 / 23 / 329 / 23</text><rect x="352.0" y="276" width="323.5" height="26" rx="4" fill="#7c5cff" fill-opacity="0.30" stroke="#7c5cff" stroke-width="1.6"/><text x="683.5" y="294" font-size="11" fill="#7c5cff">78.9%</text>
      <text x="24" y="336" font-size="10.5" fill="#3553ff" font-weight="700">testing trophy</text><text x="344" y="336" font-size="8.5" text-anchor="end" opacity="0.7">200 / 104 / 260 / 26</text><rect x="352.0" y="318" width="355.1" height="26" rx="4" fill="#3553ff" fill-opacity="0.30" stroke="#3553ff" stroke-width="1.6"/><text x="715.1" y="336" font-size="11" fill="#3553ff">86.6%</text>
      <text x="24" y="378" font-size="10.5" fill="#0fa07f" font-weight="700">OPTIMUM (measured)</text><text x="344" y="378" font-size="8.5" text-anchor="end" opacity="0.7">30 / 258 / 179 / 28</text><rect x="352.0" y="360" width="364.9" height="26" rx="4" fill="#0fa07f" fill-opacity="0.30" stroke="#0fa07f" stroke-width="1.6"/><text x="724.9" y="378" font-size="11" fill="#0fa07f" font-weight="700">89.0%</text>
    </g>

    <g fill="none" stroke="currentColor" stroke-width="1.2" opacity="0.5"><path d="M352 392 L 762 392"/></g>
    <g fill="currentColor" font-size="8.5" text-anchor="middle" opacity="0.7">
      <text x="352" y="406">0%</text><text x="454.5" y="406">25%</text><text x="557" y="406">50%</text><text x="659.5" y="406">75%</text><text x="762" y="406">100%</text>
    </g>

    <rect x="18" y="418" width="844" height="44" rx="9" fill="#7f7f7f" fill-opacity="0.08" stroke="currentColor" stroke-opacity="0.4" stroke-width="1.4"/>
    <text x="36" y="438" font-size="9.5" fill="currentColor" opacity="0.92">The trophy wins among the named shapes because it is the only one that buys CONTRACT tests &#8212; the cheap route to serialization,</text>
    <text x="36" y="452" font-size="9.5" fill="currentColor" opacity="0.92">auth and provider defects, 23% of the population no unit test can reach. Both pyramids tie because their extra unit tests buy nothing.</text>

    <text x="440" y="486" text-anchor="middle" font-size="11.5" font-weight="700" fill="currentColor">Naming a shape is not a strategy. The optimum is 2.4 points past the best named one.</text>
  </g>
</svg>
```

**All unit** — Team A's shape — buys **34.0%**, which is its ceiling, and 60,000 unit tests do not move it. Every other named shape lands between **77.4% and 78.9%** except the trophy, which reaches **86.6%**, and the measured optimum, at **89.0%**.

The trophy wins among the named shapes for a specific, checkable reason: it is the only one that buys **contract tests**, and contract tests are the cheap route to `serialization`, `auth` and provider defects — 23% of the population that no unit test can reach, at 0.25 s each instead of 14. That is not a vindication of the trophy as a philosophy; it is a vindication of one line item in it. [Contract Testing: The Seam Between Services](../10-contract-testing/) is where that level is built properly.

Three details worth pausing on. The two pyramid variants score **identically** (78.1% both), because the difference between them is unit tests and unit tests are on the flat part of the curve. The **ice-cream cone** — the shape everyone treats as a punchline — scores **77.4%**, essentially tied with both pyramids on detection; its problems are elsewhere, and we get to them. And the spread between the best and worst named shape at an identical budget is **52.6 points of the defect population**: same minutes, same money, same engineers, same code.

Naming a shape is not a strategy. The measured optimum is 2.4 points past the best named one, and more usefully, it tells you *which* line item to change.

### The shape is a shadow cast by your cost ratios

If the pyramid is an economic argument, then changing the economics must change the shape — and if it does not, the argument was never economic. Sweep the price of an end-to-end test, hold everything else, re-solve at 600 seconds:

```text
    e2e cost   x unit cost     unit  ctrt  intg  e2e   e2e share s   caught
         1.0s          100x       24   115     0  571         95.2%    99.9%
         2.0s          200x       49   190     0  276         92.0%    99.2%
         4.0s          400x       19   236    76  120         80.0%    96.8%
         7.0s          700x       30   254   154   59         68.8%    93.9%
        14.0s         1400x       30   258   179   28         65.3%    89.0%
        28.0s         2800x       15   297   237   12         56.0%    84.1%
        60.0s         6000x       44   347   341    4         40.0%    80.7%
       120.0s        12000x       54   401   474    1         20.0%    79.3%
```

At 1 second per end-to-end test the optimiser buys **571** of them and catches 99.9%. At 120 seconds it buys **one**. Nothing about the tests' *value* changed across those rows — the catch matrix is identical throughout. Only the price moved.

**The pyramid is not a value judgement about test types. It is a shadow cast by a cost ratio.** Which means the highest-leverage work on a test suite is often not writing or deleting tests at all: it is making an expensive level cheaper. A session-scoped container instead of a per-test one, a template database instead of a migration run, a fixture that boots the app once — each of those moves you up this table, and the optimiser will then spend your budget differently on its own.

The second sensitivity is the one an honest reader demands, because the model's soft parameter is the oracle strength and the result depends on it. Push the assumption hard the other way: make unit assertions near-perfect and higher-level assertions half-blind.

```text
    unit/intg/e2e oracle     unit  ctrt  intg  e2e   unit share s   caught
     0.85 / 0.70 / 0.55           30   258   179   28          0.1%    89.0%
     0.90 / 0.55 / 0.42           10   278   208   26          0.0%    86.2%
     0.95 / 0.40 / 0.30           29   274   244   24          0.0%    82.7%
     0.98 / 0.25 / 0.20          344   295   321   19          0.6%    78.6%
```

Even when unit tests are given a 0.98 oracle and end-to-end tests a 0.20, the unit level never takes more than **0.6%** of the budget. The conclusion is robust for a reason that is structural rather than numerical: **no oracle strength buys a capability.** Making your unit assertions better does not put a database in the process.

### Flake changes the answer, and it changes the budget

Everything so far counted defects. Teams do not spend defects; they spend engineer-minutes, and a suite has three of those terms, not one.

- A defect caught before merge saves **480 minutes** — the production incident it did not become — *minus* the minutes to diagnose it at the level that caught it: 9.3 at unit, 8.8 at contract, 26.5 at integration, **50.3 at end-to-end**.
- A false red costs 14 minutes of noticing, re-running and context-switching, plus part of that same diagnosis cost: **17.3 minutes** for a flaky unit test, **31.6** for a flaky end-to-end one.
- Everyone waits for the wall clock.

Re-solve the identical allocation on net minutes per build and two things move at once:

```text
    composition                 unit  ctrt  intg  e2e    CI time        caught   green   net/build
    600s max detection             30   258   179   28      600s   10.0m   89.0%   42.7%       53.1
    600s max net value            900   204    76   20      401s    6.7m   83.3%   58.6%       56.0
    1200s max detection            50   318   280   64     1200s   20.0m   95.3%   21.8%       45.5
    1200s max net value           600   216    80   19      390s    6.5m   83.2%   58.8%       56.0
    2400s max detection            48   398   355  144     2400s   40.0m   98.3%    6.8%       33.7
    2400s max net value          1200   192    75   20      400s    6.7m   83.2%   58.8%       55.9
```

**The value-maximising suite buys unit tests back by the thousand.** Not for detection — the previous section proved they barely move it — but because they move the *catch* to a level that costs 9.3 minutes to diagnose instead of 50.3. This is failure localisation finally expressed as money, and it is the numerical form of the argument everyone makes qualitatively. The marginal table makes it starkest: at the 600 s optimum, one more unit test adds **0.000000** to detection and is still the **only** level with positive marginal net value.

**And the value-maximising suite refuses the budget it was offered.** Given 1,200 or 2,400 seconds it still builds the same ~400-second suite, because past that point one more test buys more false reds than defects. The break-even flake rates say the same thing from the other side: at the 600-second detection optimum, contract, integration and end-to-end are all *already past* break-even (headroom 0.51×, 0.53×, 0.75×), and only unit tests have room (10.30×).

The obvious next question is what flake actually costs you, so sweep it:

```text
    e2e flake   1 red per N runs   unit  ctrt  intg  e2e   CI s   caught   net
      0.01200               83     900   204    76   20    401    83.3%   56.0
      0.00600              167     755   217    60   35    600    87.8%   60.4
      0.00300              333     774   216    60   35    600    87.8%   63.2
      0.00150              667     779   188    34   37    600    86.9%   65.1
      0.00050             2000     779   188    34   37    600    86.9%   66.2
      0.00010            10000     779   188    34   37    600    86.9%   66.7
```

Flake does not *ban* the expensive level — it **rations** it, and it rations the whole budget with it. At Team B's 1.2% per-test flake the optimiser buys 20 end-to-end tests and refuses to spend more than **401 of its 600 seconds**. Take the same tests to 0.15% and it buys **37**, spends the whole budget, and gains 3.6 points of detection and **9.1 minutes per build**.

That is the sentence to take to a planning meeting. **Flake work is not hygiene you do after the suite is built; it is what makes the suite affordable.** A team that has not fixed its flake cannot buy the coverage it wants at any budget, because the budget stops being worth spending. [Flaky Tests: The Trust Arithmetic](../09-flaky-tests/) is the full development of this, including what a red build is actually worth after N false alarms.

### The ice-cream cone accretes; nobody chooses it

No team has ever decided to invert its pyramid. The inversion is what a perfectly reasonable local policy produces when it is run for two years.

The policy is the one in every postmortem template: *a defect reached production, so add an end-to-end test to make sure it cannot happen again.* Simulate 200 sprints against an identical defect stream, with both policies also adding 12 unit and 1 integration test per sprint for new features, and vary only that one sentence.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 476" width="100%" style="max-width:840px" role="img" aria-label="Two hundred sprints of accretion under two postmortem policies, drawn as stacked bars by test count and by CI seconds. Under policy A, add an end-to-end test after every escaped defect, the suite ends with 48 end-to-end tests: 1.6 percent of the test count but 76.6 percent of the CI seconds. Drawn by count it is still a pyramid; drawn by seconds it is an ice-cream cone. The suite takes 14.6 minutes and a clean build goes green only 34.0 percent of the time. Under policy B, add a test at the cheapest level that could have caught it, the suite ends with 23 end-to-end tests at 56.9 percent of the seconds, takes 9.4 minutes, goes green 41.8 percent of the time, catches the same 84 percent, and cost 28,951 fewer engineer-minutes.">
  <g id="p12-02-fig5" font-family="'JetBrains Mono', ui-monospace, monospace">
    <text x="440" y="26" text-anchor="middle" font-size="14.5" font-weight="700" fill="currentColor">Nobody chose the cone. Every step of policy A was approved in a meeting.</text>
    <text x="440" y="46" text-anchor="middle" font-size="10" fill="currentColor" opacity="0.8">200 sprints &#183; 208 defects &#183; identical defect stream &#183; one sentence different in the postmortem template</text>

    <text x="24" y="96" font-size="11" font-weight="700" fill="#d64545">POLICY A &#8212; "add an end-to-end test so this cannot happen again"</text>
    <g fill="currentColor" font-size="9" text-anchor="end" opacity="0.85">
      <text x="278" y="136">by TEST COUNT</text><text x="278" y="176">by CI SECONDS</text>
    </g>
      <rect x="286.0" y="118" width="455.7" height="26" fill="#0fa07f" fill-opacity="0.38" stroke="#0fa07f" stroke-width="1"/><rect x="741.7" y="118" width="0.7" height="26" fill="#3553ff" fill-opacity="0.38" stroke="#3553ff" stroke-width="1"/><rect x="742.4" y="118" width="35.8" height="26" fill="#7c5cff" fill-opacity="0.38" stroke="#7c5cff" stroke-width="1"/><rect x="778.2" y="118" width="7.8" height="26" fill="#e0930f" fill-opacity="0.38" stroke="#e0930f" stroke-width="1"/>
      <rect x="286.0" y="158" width="16.0" height="26" fill="#0fa07f" fill-opacity="0.38" stroke="#0fa07f" stroke-width="1"/><rect x="302.0" y="158" width="0.6" height="26" fill="#3553ff" fill-opacity="0.38" stroke="#3553ff" stroke-width="1"/><rect x="302.5" y="158" width="100.3" height="26" fill="#7c5cff" fill-opacity="0.38" stroke="#7c5cff" stroke-width="1"/><rect x="402.9" y="158" width="383.1" height="26" fill="#e0930f" fill-opacity="0.38" stroke="#e0930f" stroke-width="1"/>
      
    <g font-size="9.5" font-weight="700">
      <text x="794" y="136" fill="#e0930f">1.6% e2e</text><text x="794" y="176" fill="#d64545">76.6% e2e</text>
    </g>
    <text x="24" y="206" font-size="9" fill="currentColor" opacity="0.9">3,072 tests &#183; 48 end-to-end &#183; 14.6 min of CI &#183; clean build green 34.0% of the time &#183; 46 escapes &#183; 153,248 engineer-minutes</text>

    <path d="M18 224 L 862 224" fill="none" stroke="currentColor" stroke-width="1" opacity="0.3"/>

    <text x="24" y="248" font-size="11" font-weight="700" fill="#0fa07f">POLICY B &#8212; "add a test at the cheapest level that could have caught it"</text>
    <g fill="currentColor" font-size="9" text-anchor="end" opacity="0.85">
      <text x="278" y="274">by TEST COUNT</text><text x="278" y="314">by CI SECONDS</text>
    </g>
      <rect x="286.0" y="256" width="444.3" height="26" fill="#0fa07f" fill-opacity="0.38" stroke="#0fa07f" stroke-width="1"/><rect x="730.3" y="256" width="13.3" height="26" fill="#3553ff" fill-opacity="0.38" stroke="#3553ff" stroke-width="1"/><rect x="743.6" y="256" width="38.7" height="26" fill="#7c5cff" fill-opacity="0.38" stroke="#7c5cff" stroke-width="1"/><rect x="782.4" y="256" width="3.6" height="26" fill="#e0930f" fill-opacity="0.38" stroke="#e0930f" stroke-width="1"/>
      <rect x="286.0" y="296" width="24.7" height="26" fill="#0fa07f" fill-opacity="0.38" stroke="#0fa07f" stroke-width="1"/><rect x="310.7" y="296" width="18.5" height="26" fill="#3553ff" fill-opacity="0.38" stroke="#3553ff" stroke-width="1"/><rect x="329.3" y="296" width="172.4" height="26" fill="#7c5cff" fill-opacity="0.38" stroke="#7c5cff" stroke-width="1"/><rect x="501.6" y="296" width="284.4" height="26" fill="#e0930f" fill-opacity="0.38" stroke="#e0930f" stroke-width="1"/>
    <g font-size="9.5" font-weight="700">
      <text x="794" y="274" fill="#e0930f">0.7% e2e</text><text x="794" y="314" fill="#e0930f">56.9% e2e</text>
    </g>
    <text x="24" y="344" font-size="9" fill="currentColor" opacity="0.9">3,151 tests &#183; 23 end-to-end &#183; 9.4 min of CI &#183; clean build green 41.8% of the time &#183; 47 escapes &#183; 124,296 engineer-minutes</text>

    <rect x="18" y="360" width="844" height="58" rx="9" fill="#7f7f7f" fill-opacity="0.08" stroke="currentColor" stroke-opacity="0.4" stroke-width="1.4"/>
    <text x="36" y="380" font-size="10" font-weight="700" fill="currentColor">The inversion is invisible in the row everyone draws.</text>
    <text x="36" y="396" font-size="9" fill="currentColor" opacity="0.9">By test count policy A is still 91% unit tests &#8212; a textbook pyramid, and anyone auditing the suite that way will report it as healthy. The same</text>
    <text x="36" y="410" font-size="9" fill="currentColor" opacity="0.9">suite spends three quarters of its CI seconds in 1.6% of its tests. Same detection as policy B, 55% more CI, and 483 engineer-hours burned.</text>

    <text x="440" y="446" text-anchor="middle" font-size="11.5" font-weight="700" fill="currentColor">An ice-cream cone is a pyramid that was never measured in the units it is paid for.</text>
    <g font-size="9.5" font-weight="700">
      <rect x="200" y="460" width="11" height="11" rx="3" fill="#0fa07f" fill-opacity="0.38" stroke="#0fa07f" stroke-width="1"/><text x="217" y="469" fill="#0fa07f">unit</text>
      <rect x="266" y="460" width="11" height="11" rx="3" fill="#3553ff" fill-opacity="0.38" stroke="#3553ff" stroke-width="1"/><text x="283" y="469" fill="#3553ff">contract</text>
      <rect x="366" y="460" width="11" height="11" rx="3" fill="#7c5cff" fill-opacity="0.38" stroke="#7c5cff" stroke-width="1"/><text x="383" y="469" fill="#7c5cff">integration</text>
      <rect x="490" y="460" width="11" height="11" rx="3" fill="#e0930f" fill-opacity="0.38" stroke="#e0930f" stroke-width="1"/><text x="507" y="469" fill="#e0930f">end-to-end</text>
    </g>
  </g>
</svg>
```

Policy A ends with 48 end-to-end tests. That is **1.6% of the test count** and **76.6% of the CI seconds**. Drawn by count it is still a textbook pyramid — 91% unit tests — and anyone auditing the suite in those units will report it as healthy. The same suite spends three quarters of its budget in 1.6% of its tests, takes 14.6 minutes, and goes green on a clean tree **34.0%** of the time.

**An ice-cream cone is a pyramid that was never measured in the units it is paid for.**

Policy B changes one word: add a test at the *cheapest level that could have caught it*. Same defects, same sprints, same postmortems. It lands at 9.4 minutes instead of 14.6, goes green 41.8% instead of 34.0%, catches the same share — **47 escapes against 46, which is a tie** — and costs **28,951 fewer engineer-minutes**, 483 hours, over the same period.

Note carefully what policy A is *not*. It is not wrong about any individual test: each end-to-end test it added genuinely did raise detection, which is why every one of them was approved. The failure is that a local decision was made 46 times with no global budget, in a unit nobody was tracking. That is how every ice-cream cone in the world got built, and it is why the fix is a *policy* — "which level" is part of the action item — rather than an occasional cleanup sprint.

### Feedback latency, and what the budget should actually be

There is one term left, and it is the one that is not about computers. [CI/CD: From Commit to Artifact to Environment](../../10-infrastructure-and-deployment/10-ci-cd-pipelines/) establishes it: under roughly ten minutes people wait and stay in context; substantially beyond it they start something else, and a failure then arrives to someone who has swapped out. The ten-minute target is Humble and Farley's, from *Continuous Delivery* (Addison-Wesley, 2010), and it is a target for the pipeline's critical path.

Feed that into the model as a plain cost — everyone waits for the wall clock — and then remove the budget constraint entirely. Do not tell the optimiser how long the suite may be; let it choose:

```text
    unconstrained optimum        3000   240   114   16      405s    6.8m   83.3%   53.5%       54.9
    wall time on 8 workers: 51 s = 0.8 min (inside the 10-minute feedback rule)
```

**The budget is an output of the model, not an input to it.** Nobody has to legislate "the suite must be under ten minutes". Price a caught defect, a false red and a minute of waiting, and a length falls out — here 405 CI-seconds, 51 seconds of wall time across 8 workers, catching 83.3%.

Which reframes the ten-minute rule usefully. It is not an arbitrary target you are failing; it is roughly where a sensible cost model lands on its own, and if your suite is far past it, the model is telling you that the marginal tests up there are not paying for themselves. That is a much easier conversation than "we should have fewer tests".

## Build It

[`code/suite_shape.py`](code/suite_shape.py) is seven numbered sections, standard library only, seed `20260718`, and it finishes in well under a second. Two runs produce byte-identical output; there is no sampling anywhere in the core result, because the detection matrix is computed by **exhaustive enumeration** over every defect site crossed with every possible test scope.

The whole model rests on one object: a layered call graph, built once and never mutated. A test's scope is a closure over it, and everything else is arithmetic on scopes.

```python
def scopes_for(g: Graph) -> tuple[tuple[frozenset[int], ...], ...]:
    unit = tuple(frozenset({v}) for v in range(len(g.layer)))
    contract = tuple(frozenset({v}) for v in g.by_layer["client"] + g.by_layer["route"])
    integration = tuple(closure(g, e, NO_CLIENT)
                        for e in g.by_layer["service"] + g.by_layer["worker"])
    e2e = tuple(closure(g, e) for e in g.by_layer["route"] + g.by_layer["worker"])
    return unit, contract, integration, e2e
```

Four lines, four levels, and the entire difference between them is *how much of the graph one test runs*. A unit scope is a singleton. An integration scope is a closure with the outbound client excluded — because that is what "double the external dependency" means structurally. An end-to-end scope is the unrestricted closure. This is why the localisation numbers and the detection numbers come from one source rather than two tables of assumptions.

Defect sites are the other half, and the wiring case is the one that carries the lesson:

```python
def sites_for(g: Graph, sel: str) -> list[tuple[int, ...]]:
    """A node-sited defect is a 1-tuple; a wiring defect is a 2-tuple, because a
    wrong argument at a call site is only wrong when BOTH functions run — which is
    why no unit test can see it."""
    if sel == "edge":
        return [(u, v) for u, v in g.edges
                if g.layer[u] in ("route", "service", "worker")]
```

Detection then falls out of one expression, and the `all(v in sc ...)` is where a unit test's zero for wiring comes from — a singleton scope can never contain both endpoints of an edge:

```python
for ci, bc in enumerate(CLASSES):
    sites = sites_for(g, bc.sites)
    for li in range(len(LEVELS)):
        if not bc.needs <= CAPS[li]:
            continue                      # hard zero: the environment cannot express it
        acc = 0.0
        for site in sites:
            inv_cases = 1.0 / g.cases[site[0]]
            for sc in scopes[li]:
                if all(v in sc for v in site):
                    acc += inv_cases
        p[li][ci] = ORACLE[li] * acc / (len(sites) * len(scopes[li]))
```

The optimiser is greedy on marginal value per CI-second in blocks worth `budget/steps`, followed by local search that moves tests between levels until nothing improves. What matters is that it is *checked* rather than trusted — `exhaustive()` enumerates every feasible composition at a small budget and the two are compared in the output.

The objective itself is four lines, and the `prod` over levels is the part that makes the problem interesting: buying a test at one level changes what a test at another level is worth.

```python
def expected_catch(n: Sequence[int], logq: list[list[float]]) -> float:
    tot = 0.0
    for ci in range(NC):
        s = (n[0] * logq[0][ci] + n[1] * logq[1][ci]
             + n[2] * logq[2][ci] + n[3] * logq[3][ci])
        tot += CLASS_W[ci] * -math.expm1(s)
    return tot
```

`logq[L][c]` is precomputed `log(1 - p)`, so a whole composition is scored with twelve `exp` calls instead of forty-eight `pow`s. That is what makes an eight-budget sweep, an eight-point cost sweep, a four-point oracle sweep and a six-point flake sweep all fit inside a second.

The `net_minutes` objective is where localisation stops being a talking point. It needs to know *which* level caught each defect, so the levels are attributed in cost order — the order a real pipeline runs its gates:

```python
def attribution(n, logq) -> tuple[list[float], float]:
    """P(a defect is first caught at level L), levels tried in cost order."""
    order = sorted(range(4), key=lambda i: COST[i])
    share, escaped = [0.0] * 4, 0.0
    for ci in range(NC):
        surv = 1.0
        for li in order:
            passed = math.exp(n[li] * logq[li][ci])
            share[li] += CLASS_W[ci] * surv * (1.0 - passed)
            surv *= passed
        escaped += CLASS_W[ci] * surv
    return share, escaped
```

Once you have that split, a caught defect is worth `480 − DEBUG[level]` minutes rather than a flat 480, and a unit test that adds no detection at all can still have positive value by moving a catch from the 50-minute level to the 9-minute one. That single change is what flips the answer between the two halves of the lesson.

Run it:

```bash
python3 phases/12-testing-and-quality/02-the-shape-of-a-test-suite/code/suite_shape.py
```

```console
== 2 · THE CATCH MATRIX: WHAT ONE TEST AT EACH LEVEL IS WORTH ==
  P(one test detects one defect of this class) x1000. A dot is a HARD zero:
  the level's environment cannot express that defect at ANY test count.

    class          weight      unit  contract  integr'n      e2e   levels that can reach it
    logic           0.20      3.66       .   46.74   69.23   unit,integration,e2e
    boundary        0.14      4.03       .   42.73   62.82   unit,integration,e2e
    wiring          0.11         .       .    6.86   15.22   integration,e2e
    serialization   0.08         .   13.67       .   10.02   contract,e2e
    contract        0.08         .   17.36       .   46.85   contract,e2e
    auth            0.07         .   13.67       .   10.02   contract,e2e
    schema          0.07         .       .   34.42   49.54   integration,e2e
    concurrency     0.06         .       .       .   49.54   e2e
    config          0.05         .       .       .   34.10   e2e
    duplicate       0.05         .       .       .    7.94   e2e
    n_plus_1        0.05         .       .       .   49.54   e2e
    migration       0.04         .       .   34.42   49.54   integration,e2e

    unit         reaches 34.0% of the defect population at INFINITE test count
    contract     reaches 23.0% of the defect population at INFINITE test count
    integration  reaches 56.0% of the defect population at INFINITE test count
    e2e          reaches 100.0% of the defect population at INFINITE test count

== 4 · BUDGET ALLOCATION AS AN OPTIMISATION — THE HEADLINE ==
  verification first. At a 60 s budget, exhaustive enumeration over
  18144 feasible compositions against the greedy + local-search optimiser:
    exhaustive  [609, 110, 33, 0]      -> 61.5815%
    greedy      [745, 111, 31, 0]      -> 61.5252%
    gap 0.0562 percentage points. The greedy is trusted below.

  the optimal suite at each CI budget, and how its SHAPE moves:
    composition                 unit  ctrt  intg  e2e    CI time        caught   green   net/build
    budget     30s                784    63     8    0       30s    0.5m   50.1%   93.3%       41.0
    budget     60s                745   111    31    0       60s    1.0m   61.5%   86.6%       48.9
    budget    120s                289   190    87    0      120s    2.0m   70.8%   74.5%       53.3
    budget    240s                 59   228   123    6      240s    4.0m   77.9%   63.3%       54.3
    budget    600s                 30   258   179   28      600s   10.0m   89.0%   42.7%       53.1
    budget   1200s                 50   318   280   64     1200s   20.0m   95.3%   21.8%       45.5
    budget   2400s                 48   398   355  144     2400s   40.0m   98.3%    6.8%       33.7
    budget   4800s                  0   382   193  325     4800s   80.0m   99.6%    1.1%       29.1

    budget     share of CI SECONDS            share of TEST COUNT
               unit  ctrt  intg   e2e      unit  ctrt  intg   e2e
         30  26.1% 52.5% 21.3%  0.0%    91.7%  7.4%  0.9%  0.0%
        120   2.4% 39.6% 58.0%  0.0%    51.1% 33.6% 15.4%  0.0%
        600   0.1% 10.8% 23.9% 65.3%     6.1% 52.1% 36.2%  5.7%
       4800   0.0%  2.0%  3.2% 94.8%     0.0% 42.4% 21.4% 36.1%

== 5 · THE TWO TEAMS, THE NAMED SHAPES, AND WHETHER ANY OF IT SURVIVES ==
    composition                 unit  ctrt  intg  e2e    CI time        caught   green   net/build
    Team A: 4,000 unit           4000     0     0    0       40s    0.7m   34.0%   92.3%       27.4
      detection-optimum here      800    80    15    0       40s    0.7m   54.8%   91.0%       44.4
    Team B: 180 e2e                 0     0     0  180     2520s   42.0m   95.7%   11.4%       40.7
      detection-optimum here       35   389   333  154     2520s   42.0m   98.4%    6.3%       33.5

  every named shape scaled to the SAME 600 s budget:
    pyramid 70/20/10              719     0    76   38      600s   10.0m   78.1%   53.5%       47.1
    testing trophy                200   104   260   26      600s   10.0m   86.6%   40.6%       50.9
    ice-cream cone               1409     6    13   41      600s   10.0m   77.4%   57.5%       48.0
    all unit                    60000     0     0    0      600s   10.0m   34.0%   30.1%       15.5
    OPTIMUM (measured)             30   258   179   28      600s   10.0m   89.0%   42.7%       53.1

== 6 · FLAKE AND LOCALISATION, PRICED IN ENGINEER-MINUTES ==
    net value of ONE more test, at the margin, from the 600 s optimum:
      level      delta caught   value min   flake cost   CI cost      NET
      unit            0.000000      0.0036       0.0003    0.0000   0.0032
      contract        0.000048      0.0058       0.0103    0.0005  -0.0050
      integration      0.000146      0.0263       0.0465    0.0017  -0.0219
      e2e             0.002641      0.3131       0.3794    0.0292  -0.0955

== 7 · THE ICE-CREAM CONE IS NOT A CHOICE — IT ACCRETES ==
    policy                     escapes   engineer-minutes   e2e share of CI s
    A: always an e2e test          46             153248              76.6%
    B: cheapest able level         47             124296              56.9%
```

Two lines in that output are arguments rather than demonstrations. The **`unit` row of the marginal table** — `delta caught 0.000000`, `NET +0.0032`, the only positive one — is failure localisation earning its keep with no detection at all. And **`escapes 46` versus `47`** is the honest version of the ice-cream-cone story: policy B is not better at catching things. It is exactly as good, for 35% less CI and 483 engineer-hours saved.

## Use It

You are not going to run this optimiser in production. What you will do is measure four numbers and change three settings, and pytest gives you all of them.

**Measure your cost per level.** `--durations` is the only input that matters and almost nobody looks at it:

```bash
pytest --durations=25 --durations-min=0.05
pytest -m unit --durations=0 -q | tail -5     # per-level totals
```

Split your suite with **markers**, declared strictly so a typo fails the run instead of silently selecting nothing:

```ini
# pytest.ini
[pytest]
addopts = --strict-markers --strict-config -ra
markers =
    unit: no I/O, no database, no network — must run in under 20 ms
    contract: verifies one seam; runs against a recorded pact or a live provider
    integration: real database, doubled outbound HTTP
    e2e: full stack; the expensive level — justify every single one
```

`--strict-markers` is not optional. Without it `@pytest.mark.integraton` is a silently ignored typo, and `-m "not integraton"` selects your whole suite while looking like it selected a subset. Then selection is `pytest -m "unit or contract"` for the fast gate and `pytest -m "integration or e2e"` for the slow one.

**Parallelise, and know what it breaks.** `pytest-xdist` with `-n auto` divides tests across worker processes:

```bash
pytest -n auto --dist loadscope -m "integration"
```

Two defaults bite here. First, **session-scoped fixtures run once per worker, not once per session** — eight workers means eight containers, eight schema migrations, eight of whatever you thought you were amortising, and if that fixture writes to a shared resource you have just built a race. The fix is a per-worker resource keyed on the `PYTEST_XDIST_WORKER` environment variable (`test_db_gw0`, `test_db_gw1`, …); [Integration Testing Against a Real Database](../06-integration-testing-real-database/) builds that properly. Second, `--dist load` scatters tests arbitrarily, so `--dist loadscope` (group by module or class) or `--dist loadfile` is usually what you want when setup is expensive.

Note what parallelism does and does not buy in this lesson's model. It divides **wall time**, which is the feedback-latency term — the unconstrained optimum's 405 CI-seconds became 51 seconds of wall clock on 8 workers. It does not divide **CI seconds**, which is what you are billed for, and it does not touch the flake term at all. Parallelism buys you the cheapest of the three costs.

**Split the CI jobs along the same line, and gate differently.**

```yaml
jobs:
  fast:                       # required check — must stay inside the feedback window
    steps:
      - run: pytest -m "unit or contract" -n auto -q --durations=10
  slow:                       # required check, but allowed to be slower
    steps:
      - run: pytest -m "integration" -n auto --dist loadscope
  e2e:                        # the expensive level: fewest tests, strictest budget
    steps:
      - run: pytest -m e2e -n 4 --timeout=120 --durations=0
```

Make `fast` and `slow` **required checks** on the branch protection rule. Whether `e2e` is required is the real decision, and this lesson gives you the number to make it with: required-and-flaky is how you get the re-run reflex, which is how a suite stops meaning anything. If your e2e flake rate is above roughly **0.6%** per test, the model says you cannot afford them as a gate — fix the flake or move the job to post-merge, and read [Flaky Tests: The Trust Arithmetic](../09-flaky-tests/) before choosing.

Two tools worth naming for the levels themselves. **`testcontainers-python`** with a session-scoped container and function-scoped data is what moves your integration cost from tens of seconds to hundreds of milliseconds — which, per the cost sweep, is what lets the optimiser buy more of them. And **Pact** or **`schemathesis`** is what makes the contract level exist at all; without it the trophy's advantage in the measured table is unavailable to you.

Everything about *load* belongs elsewhere: throughput, coordinated omission and the latency knee are [Benchmarking & Load Testing](../../08-concurrency-and-performance/14-benchmarking-and-load-testing/), and a performance suite is not a correctness suite.

**What to actually do.** For a backend service, target something close to the measured optimum's *character* rather than its exact counts: a large, near-free unit layer that you keep for localisation rather than detection; a real contract layer, because 23% of your defects live at seams and it is the cheapest way to reach them; an integration layer against a real database that carries most of your detection; and a deliberately small end-to-end layer whose size you justify in *seconds*, not in tests.

And measure exactly three numbers first:

1. **Median CI seconds per test, per level.** `--durations=0`, grouped by marker. This is the ratio that determines your shape, and it is usually not the one you assumed.
2. **Flake rate per test, per level.** Re-run the suite ten times on an unchanged commit and count. Below 0.6% at the e2e level you can gate on it; above, you cannot afford it.
3. **The capability ceiling of your cheapest level.** Take last quarter's production defects, classify them, and count how many your unit tests could not have expressed *at any test count*. If that number is large, no amount of coverage will help, and you have found the level to invest in.

## Think about it

1. The detection-maximising suite at 600 s holds 30 unit tests; the value-maximising suite at the same budget holds 900. Both are optimal for their objective. Which objective is your team's CI actually configured to maximise, and what would you have to change to make it the other one?
2. Forcing the unit count from 0 to 2,000 at the 600-second optimum changed detection by 0.7 points. Given that, construct the strongest possible argument for still writing unit tests — using only numbers from this lesson — and then say what it implies about *which* unit tests are worth writing.
3. The cost sweep showed the optimiser buying 571 end-to-end tests at 1 s each and 1 at 120 s each. Estimate your own e2e cost, find your row, and say what the table predicts your suite should look like. Now say why your actual suite does not look like that.
4. Policy A and policy B ended with 46 and 47 escapes — a tie on detection — but a 28,951-minute cost difference. If you can only measure one of "defects escaped" and "engineer-minutes spent", which do you instrument, and what does the other one being invisible let a team get away with?
5. The unit level's ceiling of 34% is a property of the *model service* — mostly wiring, mostly boundaries it does not own. Describe a real codebase where that ceiling would be above 90%, and say precisely which of this lesson's conclusions would reverse for it.

## Key takeaways

- **A capability is a hard zero, not a small number.** Measured over every defect site crossed with every possible test scope, the unit level reaches **34.0%** of this service's defect population, contract 23.0%, integration 56.0%, end-to-end 100%. `wiring` is zero at the unit level *by construction* — a unit test's scope is one function, a wiring defect lives on the edge between two — and no test count, coverage target or assertion quality changes that.
- **The optimum is a pyramid by test count and never a pyramid by CI seconds.** Solved numerically at eight budgets: unit tests are **91.7% of the count at 30 s** and **6.1% at 600 s**, while holding **26.1% and 0.1% of the seconds** respectively. Every published shape is drawn in counts; your CI bill, feedback latency and flake budget are denominated in seconds. Teams argue past each other because the two pictures are near mirror images.
- **The shape is a shadow cast by your cost ratios, not a value judgement.** Hold the catch matrix fixed and sweep only the price of an end-to-end test: the optimiser buys **571** of them at 1 s each and **1** at 120 s each. The highest-leverage change to a suite is therefore often making an expensive level cheaper — a session-scoped container, a template database — after which the allocation fixes itself.
- **Naming a shape is not a strategy: 52.6 points separate the best and worst named shape at an identical 600 s budget.** All-unit buys **34.0%** and cannot buy more at any price; both pyramid variants tie at **78.1%**; the trophy reaches **86.6%** purely because it is the only one that buys contract tests; the measured optimum is **89.0%**.
- **Failure localisation is worth money, and it is the only thing that justifies unit tests at the margin.** A failing end-to-end test implicates **369 lines across 4.7 layers** against a unit test's **28 in 1** — 13× the reading, 3.7 extra bisection halvings, **50.3 versus 9.3 minutes** to diagnose. At the 600 s detection optimum one more unit test adds **0.000000** detection and is still the **only** level with positive net value, because it moves the catch somewhere cheap to read.
- **Flake rations the expensive level and rations the whole budget with it.** At a 1.2% per-test e2e flake rate the value-maximising suite buys 20 end-to-end tests and refuses to spend more than **401 of its 600 seconds**; at 0.15% it buys **37**, spends the full budget, and gains 3.6 points of detection and **9.1 minutes per build**. Flake work is not hygiene done after the suite — it is what makes the suite affordable.
- **The budget is an output of the model, not an input.** Price a caught defect at 480 minutes, a false red at 14 plus diagnosis, and a minute of waiting at a minute, then remove the budget constraint: the optimum is **405 CI-seconds, 51 seconds of wall clock on 8 workers, catching 83.3%** — comfortably inside the ten-minute feedback rule (Humble & Farley, *Continuous Delivery*, 2010) without anyone legislating it.
- **The ice-cream cone accretes from a policy nobody would defend if it were stated globally.** "Add an end-to-end test after each incident", run for 200 sprints, produces 48 e2e tests holding **1.6% of the count and 76.6% of the CI seconds** — still a textbook pyramid in the units most teams audit. Changing one word to "add a test at the cheapest level that could have caught it" gave the same detection (47 escapes versus 46) for **35% less CI and 483 engineer-hours**.
- **Measure three numbers before you argue about shape:** median CI seconds per test per level (`--durations=0` by marker), per-test flake rate per level (re-run an unchanged commit ten times), and how many of last quarter's production defects your cheapest level could not have expressed at any test count.

Next: [Anatomy of a Unit Test](../03-anatomy-of-a-unit-test/) — down one level from the shape of the suite to the shape of a single test, where a PR with 31 green tests turns out to contain no test of anything.
