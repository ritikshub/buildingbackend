# Contract Testing: The Seam Between Services

> A consumer that tolerantly coerces whatever the provider sends raised **zero exceptions across twelve consecutive provider releases** — and issued **226 wrong receipts**, understating what it billed by **101,132,788 minor units**, with nothing in any log. The strict consumer next to it went down loudly on six of those twelve. Neither of them noticed the release where `total_cents` quietly started meaning dollars. Meanwhile the shared integration environment that was supposed to catch all of this could answer a question on **42.4% of days**, with a longest unbroken red stretch of **52 days**. This lesson builds the thing that works instead: a contract recorded by the consumer, verified by the provider, alone, in about 150 lines.

**Type:** Build
**Languages:** Python
**Prerequisites:** [Test Doubles: Mocks, Stubs, Fakes & the Lies They Tell](../04-test-doubles/), [OpenAPI & Contract-First Design](../../02-api-design/06-openapi-contract-first/), [Schema Evolution & Event Contracts](../../06-messaging-and-pub-sub/12-schema-evolution-and-event-contracts/)
**Time:** ~75 minutes

## The Problem

**14:20.** The orders team ships `orders@4.2.0`. The change is one line in a serializer: the JSON field `total_cents` becomes `amount_cents`, because "cents" was wrong for the three markets that do not have cents and somebody finally cleaned it up. It is behind a minor version bump, which the team believes is fine, because they checked and nothing in *their* repository reads the old name.

Their test suite is green. It was always going to be green. They wrote both halves of it: the code that emits the field and the test that asserts on the field, in the same commit, from the same understanding. A suite in which you own both sides of an interface can only ever tell you that you are self-consistent.

**14:23.** The receipts service starts throwing `KeyError: 'total_cents'`. It is not a graceful degradation; the receipt worker crashes on every message, the retry puts it back, and the dead-letter queue starts filling.

**14:31.** Finance notices that the daily settlement export is short. Not empty — *short*. A second consumer, the reconciliation job, does not use `body["total_cents"]`; it uses `body.get("total_cents", 0)`, because someone once had a null and this made the alert stop. It has been writing zeroes into the ledger for eleven minutes and it has logged nothing at all, because from its point of view nothing has gone wrong.

**14:44.** A third consumer is found. Nobody on the orders team knew it existed.

Someone asks the reasonable question: *why did the integration environment not catch this?* It is right there in the pipeline, it runs all eleven services together, and that is precisely the scenario it exists for. Somebody pulls it up. It has been red since the 9th. Not for this reason — for an unrelated reason, in a service nobody on this call owns, which was itself blocked behind a different service being redeployed.

That is not bad luck, and this lesson's program measures why. Model a shared environment as eleven services, each of which breaks it with probability 0.02 per day and is repaired with probability 0.25 per day — a service that breaks the shared environment about every fifty days and takes about four days to fix. Every member is then healthy `0.25 / (0.25 + 0.02)` = 92.6% of the time, which is a number nobody would escalate. Over 20,000 simulated days the *environment* was usable on **42.4%** of them, and its longest unbroken red stretch was **52 days**. The closed form agrees with the simulation exactly: `0.926^11` = **42.9%**.

The environment is not broken. The environment is an `AND` of eleven things, and an `AND` of eleven things is a product.

So there were three separate failures at 14:20, and only one of them looks like a bug. The provider could not know who read `total_cents`. The tolerant consumer converted a crash into wrong money. And the gate that was supposed to catch it had stopped being a gate months earlier, because a signal that is red on the other **57.6%** of days — `100% − 42.4%` — for reasons unrelated to your change is not a signal.

> **You cannot test an integration by assembling the system. You can only test it at the seam, one pair at a time, from an artifact both sides agree on.**

## The Concept

### Why the shared integration environment stops scaling

Take `N` services, each with `M` versions live at any moment — one in production, one in staging, one on the branch under review. The question "does the system work?" is not a question about a service. It is a question about a **combination**: one chosen version of every service, all running together. There are `M^N` such combinations.

Contract testing asks a different question, and the difference is the whole argument. It asks, for each **dependency edge**, "can this provider satisfy this consumer?" There are `E` edges, where `E` is a property of your architecture diagram, not of your release calendar.

Measured over a plain layered graph where service `i` calls `i+1` and `i+2`:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 494" width="100%" style="max-width:840px" role="img" aria-label="Two measured panels. The upper panel compares, on a logarithmic scale, the number of whole-system version combinations against the number of contracts, for four system sizes with three live versions per service: three services give 27 combinations against 3 contracts, five give 243 against 7, eleven give 177,147 against 19, and thirty give 2.06 times ten to the fourteen against 57 contracts. Combinations multiply with the system while contracts add with the wiring. The lower panel shows a twenty-thousand-day simulation of a shared integration environment in which each service breaks it with probability 0.02 per day and is repaired with probability 0.25 per day: with three services it is usable on 78.5 percent of days, with five 68.9 percent, with eleven 42.4 percent and with thirty 10.0 percent, and the longest unbroken red stretch grows from 29 days to 161 days.">
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <text x="440" y="26" text-anchor="middle" font-size="14.5" font-weight="700" fill="currentColor">Combinations multiply with the system. Contracts add with the wiring.</text>

    <text x="30" y="56" font-size="11.5" font-weight="700" fill="#e0930f">what a shared environment must certify — M = 3 live versions per service</text>
    <text x="850" y="56" font-size="8.5" text-anchor="end" fill="currentColor" opacity="0.65">bar length is log scale</text>

    <g fill="none" stroke="currentColor" stroke-width="1.2" opacity="0.45">
      <path d="M132 66 L 132 232"/>
    </g>

    <g fill="#e0930f" fill-opacity="0.30" stroke="#e0930f" stroke-width="1.4">
      <rect x="132" y="72" width="30" height="13"/>
      <rect x="132" y="112" width="50" height="13"/>
      <rect x="132" y="152" width="110" height="13"/>
      <rect x="132" y="192" width="301" height="13"/>
    </g>
    <g fill="#0fa07f" fill-opacity="0.45" stroke="#0fa07f" stroke-width="1.4">
      <rect x="132" y="88" width="10" height="13"/>
      <rect x="132" y="128" width="18" height="13"/>
      <rect x="132" y="168" width="27" height="13"/>
      <rect x="132" y="208" width="37" height="13"/>
    </g>

    <g fill="currentColor" font-size="9.5" text-anchor="end">
      <text x="124" y="90">3 services</text>
      <text x="124" y="130">5 services</text>
      <text x="124" y="170">11 services</text>
      <text x="124" y="210">30 services</text>
    </g>
    <g font-size="9.5" font-weight="700">
      <text x="170" y="83" fill="#e0930f">27 version combinations</text>
      <text x="150" y="99" fill="#0fa07f">3 contracts</text>
      <text x="190" y="123" fill="#e0930f">243</text>
      <text x="158" y="139" fill="#0fa07f">7</text>
      <text x="250" y="163" fill="#e0930f">177,147</text>
      <text x="167" y="179" fill="#0fa07f">19</text>
      <text x="441" y="203" fill="#e0930f">2.06e+14</text>
      <text x="177" y="219" fill="#0fa07f">57</text>
    </g>
    <g font-size="8.5" fill="currentColor" opacity="0.75">
      <text x="530" y="163">a shared environment holds</text>
      <text x="530" y="176">exactly ONE of these at a time</text>
      <text x="530" y="203">9,324x more combinations</text>
      <text x="530" y="216">than contracts, at 11 services</text>
    </g>

    <path d="M30 250 L 850 250" fill="none" stroke="currentColor" stroke-width="1.2" opacity="0.35"/>

    <text x="30" y="278" font-size="11.5" font-weight="700" fill="#d64545">and how often that one environment can answer a question</text>
    <text x="30" y="295" font-size="9" fill="currentColor" opacity="0.82">20,000 simulated days · each service breaks it with p = 0.02/day and is repaired with p = 0.25/day · green only when EVERY member is green</text>

    <g fill="none" stroke="currentColor" stroke-width="1.2" opacity="0.45">
      <path d="M132 316 L 132 430"/>
    </g>
    <g fill="#0fa07f" fill-opacity="0.30" stroke="#0fa07f" stroke-width="1.4">
      <rect x="132" y="320" width="255" height="18"/>
      <rect x="132" y="348" width="224" height="18"/>
    </g>
    <g fill="#d64545" fill-opacity="0.30" stroke="#d64545" stroke-width="1.4">
      <rect x="132" y="376" width="138" height="18"/>
      <rect x="132" y="404" width="33" height="18"/>
    </g>
    <path d="M457 314 L 457 430" fill="none" stroke="currentColor" stroke-width="1.3" stroke-dasharray="5 4" opacity="0.55"/>

    <g fill="currentColor" font-size="9.5" text-anchor="end">
      <text x="124" y="333">3 services</text>
      <text x="124" y="361">5 services</text>
      <text x="124" y="389">11 services</text>
      <text x="124" y="417">30 services</text>
    </g>
    <g font-size="10" font-weight="700">
      <text x="395" y="333" fill="#0fa07f">78.5%</text>
      <text x="364" y="361" fill="#0fa07f">68.9%</text>
      <text x="278" y="389" fill="#d64545">42.4%</text>
      <text x="173" y="417" fill="#d64545">10.0%</text>
    </g>
    <text x="457" y="444" font-size="8.5" fill="currentColor" opacity="0.65" text-anchor="middle">100% of days</text>
    <g fill="currentColor" font-size="9">
      <text x="530" y="311" font-size="8.5" font-weight="700" opacity="0.7">LONGEST UNBROKEN RED STRETCH</text>
      <text x="530" y="333">29 days</text>
      <text x="530" y="361">39 days</text>
      <text x="530" y="389" font-weight="700" fill="#d64545">52 days</text>
      <text x="530" y="417" font-weight="700" fill="#d64545">161 days</text>
      <text x="650" y="333" opacity="0.7">closed form 79.4%</text>
      <text x="650" y="361" opacity="0.7">closed form 68.1%</text>
      <text x="650" y="389" opacity="0.7">closed form 42.9%</text>
      <text x="650" y="417" opacity="0.7">closed form 9.9%</text>
    </g>

    <text x="440" y="466" text-anchor="middle" font-size="11.5" font-weight="700" fill="currentColor">Availability is a PRODUCT over members: it decays exponentially while every member stays healthy.</text>
    <text x="440" y="484" text-anchor="middle" font-size="10.5" fill="currentColor" opacity="0.9">A gate that answers on 42.4% of days, 52 days late, is not a gate. It is a thing people learn to ignore.</text>
  </g>
</svg>
```

At eleven services with three live versions each there are **177,147** whole-system version combinations and **19** contracts — a ratio of **9,324×**. At thirty services it is **2.06 × 10¹⁴** against **57**. A shared environment holds exactly one of those combinations at a time, for as long as it takes to redeploy something into it.

There is a second cost, and in practice it is the one that hurts sooner. If the only certification you trust is "the whole system passed together", then nothing can ship until the whole system passes together, which makes eleven independent services into **one release train**: 5 deploys per week for the entire system rather than 55 — an **11×** reduction in how often any change reaches a user. Everything Phase 10's [CI/CD Pipelines](../../10-infrastructure-and-deployment/10-ci-cd-pipelines/) says about feedback latency applies here, multiplied by the number of teams waiting.

And then the availability arithmetic above finishes the job. **A gate that answers on 42.4% of days, 52 days late, is not a gate; it is a thing people learn to route around.** The failure in The Problem was not that the environment was red. It was that being red had stopped being informative.

### Provider, consumer, contract — defined precisely

Three words, used loosely everywhere, that need to be exact for the rest of this lesson.

The **provider** is the service that owns and serves the interface — it *writes* the response. The **consumer** is the service that calls it — it *reads* the response. Note that these names describe roles in one interaction, not org charts: a service is a provider on one edge and a consumer on three others, and the roles reverse within a single HTTP request, because the consumer writes the request body that the provider reads.

The **contract** is a machine-readable artifact that states what the consumer requires of the provider — nothing more. It is not the provider's schema. It is not documentation. Its defining property is that it is **the only thing both sides share**, and it is a file, so it can be versioned, published and verified asynchronously without either side being deployed anywhere.

Here is the part that surprises people the first time they see the numbers. The provider in this lesson returns **11 top-level fields**. The consumer's contract constrains **4** of them:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 486" width="100%" style="max-width:840px" role="img" aria-label="The consumer-driven contract flow in three stages. First the consumer's own test runs its real receipt-building code against a mock it controls and records three interactions. That produces a 1,916 byte JSON contract file carrying three provider states and six matching rules. The provider's own continuous integration then replays every interaction against the real service. Below, the eleven top-level fields the provider returns are shown as chips, with only four of them constrained by the contract, and the four matching rules are listed as type and pattern rules rather than literal values. At the bottom, four provider builds are verified: the recorded baseline passes three of three, a build that renames total_cents to amount_cents fails two of three with the message that total_cents is missing from the response, a build that adds three new fields still passes three of three, and a build that emits total_cents as a string fails two of three on the type. The consumer's own hand-written mock stays green on all four builds, including the two broken ones.">
  <defs>
    <marker id="p12-10-a1" markerWidth="10" markerHeight="10" refX="6.5" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#7f7f7f"/></marker>
  </defs>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <text x="440" y="26" text-anchor="middle" font-size="14.5" font-weight="700" fill="currentColor">The consumer records what it uses. The provider replays it, alone, in its own CI.</text>

    <g fill="none" stroke-width="1.9" stroke-linejoin="round">
      <rect x="20" y="46" width="248" height="72" rx="10" fill="#3553ff" fill-opacity="0.12" stroke="#3553ff"/>
      <rect x="316" y="46" width="248" height="72" rx="10" fill="#7f7f7f" fill-opacity="0.10" stroke="#7f7f7f"/>
      <rect x="612" y="46" width="248" height="72" rx="10" fill="#7c5cff" fill-opacity="0.12" stroke="#7c5cff"/>
    </g>
    <g fill="none" stroke="#7f7f7f" stroke-width="1.9">
      <path d="M268 82 L 310 82" marker-end="url(#p12-10-a1)"/>
      <path d="M564 82 L 606 82" marker-end="url(#p12-10-a1)"/>
    </g>
    <g fill="currentColor" text-anchor="middle">
      <text x="144" y="66" font-size="10.5" font-weight="700" fill="#3553ff">1 · THE CONSUMER'S OWN TEST</text>
      <text x="144" y="83" font-size="8.8" opacity="0.9">build_receipt() — the real function —</text>
      <text x="144" y="96" font-size="8.8" opacity="0.9">runs against a mock it controls and</text>
      <text x="144" y="109" font-size="8.8" opacity="0.9">records 3 interactions it exercised</text>
      <text x="440" y="66" font-size="10.5" font-weight="700" fill="#7f7f7f">2 · THE CONTRACT</text>
      <text x="440" y="83" font-size="8.8" opacity="0.9">the only shared artifact — 1,916 bytes</text>
      <text x="440" y="96" font-size="8.8" opacity="0.9">of JSON: 3 requests, 3 provider states,</text>
      <text x="440" y="109" font-size="8.8" opacity="0.9">6 matching rules. No environment.</text>
      <text x="736" y="66" font-size="10.5" font-weight="700" fill="#7c5cff">3 · THE PROVIDER VERIFIES</text>
      <text x="736" y="83" font-size="8.8" opacity="0.9">its CI sets each state, replays each</text>
      <text x="736" y="96" font-size="8.8" opacity="0.9">request against the real service and</text>
      <text x="736" y="109" font-size="8.8" opacity="0.9">matches the response — asynchronously</text>
    </g>

    <text x="20" y="146" font-size="11" font-weight="700" fill="currentColor">what the contract actually constrains: 4 of the provider's 11 top-level fields</text>

    <g stroke-width="1.5">
      <rect x="20" y="158" width="27" height="21" rx="5" fill="#3553ff" fill-opacity="0.16" stroke="#3553ff"/>
      <rect x="57" y="158" width="48" height="21" rx="5" fill="#3553ff" fill-opacity="0.16" stroke="#3553ff"/>
      <rect x="115" y="158" width="75" height="21" rx="5" fill="#3553ff" fill-opacity="0.16" stroke="#3553ff"/>
      <rect x="200" y="158" width="59" height="21" rx="5" fill="#3553ff" fill-opacity="0.16" stroke="#3553ff"/>
      <rect x="269" y="158" width="70" height="21" rx="5" fill="#7f7f7f" fill-opacity="0.10" stroke="currentColor" stroke-opacity="0.4"/>
      <rect x="349" y="158" width="75" height="21" rx="5" fill="#7f7f7f" fill-opacity="0.10" stroke="currentColor" stroke-opacity="0.4"/>
      <rect x="434" y="158" width="54" height="21" rx="5" fill="#7f7f7f" fill-opacity="0.10" stroke="currentColor" stroke-opacity="0.4"/>
      <rect x="20" y="188" width="92" height="21" rx="5" fill="#7f7f7f" fill-opacity="0.10" stroke="currentColor" stroke-opacity="0.4"/>
      <rect x="122" y="188" width="65" height="21" rx="5" fill="#7f7f7f" fill-opacity="0.10" stroke="currentColor" stroke-opacity="0.4"/>
      <rect x="197" y="188" width="65" height="21" rx="5" fill="#7f7f7f" fill-opacity="0.10" stroke="currentColor" stroke-opacity="0.4"/>
      <rect x="272" y="188" width="43" height="21" rx="5" fill="#7f7f7f" fill-opacity="0.10" stroke="currentColor" stroke-opacity="0.4"/>
    </g>
    <g font-size="9" fill="currentColor">
      <text x="26" y="173" font-weight="700" fill="#3553ff">id</text>
      <text x="63" y="173" font-weight="700" fill="#3553ff">status</text>
      <text x="121" y="173" font-weight="700" fill="#3553ff">total_cents</text>
      <text x="206" y="173" font-weight="700" fill="#3553ff">currency</text>
      <text x="275" y="173" opacity="0.7">created_at</text>
      <text x="355" y="173" opacity="0.7">customer_id</text>
      <text x="440" y="173" opacity="0.7">channel</text>
      <text x="26" y="203" opacity="0.7">shipping_cents</text>
      <text x="128" y="203" opacity="0.7">tax_cents</text>
      <text x="203" y="203" opacity="0.7">warehouse</text>
      <text x="278" y="203" opacity="0.7">lines</text>
    </g>
    <text x="20" y="230" font-size="9" fill="currentColor" opacity="0.85">the 7 grey fields may change, be renamed or vanish. Nobody recorded them.</text>

    <rect x="520" y="150" width="340" height="88" rx="9" fill="#7f7f7f" fill-opacity="0.07" stroke="currentColor" stroke-opacity="0.4" stroke-width="1.4"/>
    <g font-size="9" fill="currentColor">
      <text x="534" y="166" font-size="8.5" font-weight="700" opacity="0.7">THE 4 MATCHING RULES — TYPE AND PATTERN, NEVER VALUE</text>
      <text x="534" y="184">$.id</text><text x="680" y="184" opacity="0.85">type: string</text>
      <text x="534" y="200">$.status</text><text x="680" y="200" opacity="0.85">exact: "confirmed"</text>
      <text x="534" y="216">$.total_cents</text><text x="680" y="216" opacity="0.85">type: integer</text>
      <text x="534" y="232">$.currency</text><text x="680" y="232" opacity="0.85">regex: [A-Z]{3}</text>
    </g>

    <path d="M20 254 L 860 254" fill="none" stroke="currentColor" stroke-width="1.2" opacity="0.35"/>

    <text x="20" y="278" font-size="11" font-weight="700" fill="currentColor">the same contract replayed against four provider builds</text>
    <g fill="currentColor" font-size="8.5" font-weight="700" opacity="0.65">
      <text x="20" y="298">PROVIDER BUILD</text><text x="410" y="298">FIELDS</text><text x="486" y="298">VERIFIED</text><text x="580" y="298">WHAT THE VERIFIER SAID</text>
    </g>
    <g fill="none" stroke="currentColor" stroke-width="1" opacity="0.2">
      <path d="M20 304 L 860 304"/><path d="M20 330 L 860 330"/><path d="M20 356 L 860 356"/><path d="M20 382 L 860 382"/>
    </g>
    <g stroke-width="4" stroke-linecap="round">
      <path d="M22 310 L 22 324" stroke="#0fa07f"/><path d="M22 336 L 22 350" stroke="#d64545"/>
      <path d="M22 362 L 22 376" stroke="#0fa07f"/><path d="M22 388 L 22 402" stroke="#d64545"/>
    </g>
    <g fill="currentColor" font-size="9.5">
      <text x="34" y="321">v1  the recorded baseline</text><text x="410" y="321">11</text><text x="486" y="321" font-weight="700" fill="#0fa07f">3/3</text><text x="580" y="321" opacity="0.8">—</text>
      <text x="34" y="347" font-weight="700" fill="#d64545">v2  total_cents -&gt; amount_cents</text><text x="410" y="347">11</text><text x="486" y="347" font-weight="700" fill="#d64545">1/3</text><text x="580" y="347" fill="#d64545">$.total_cents: MISSING from the response</text>
      <text x="34" y="373">v3  adds 3 new fields</text><text x="410" y="373" font-weight="700" fill="#0fa07f">14</text><text x="486" y="373" font-weight="700" fill="#0fa07f">3/3</text><text x="580" y="373" opacity="0.8">additive changes are free, by construction</text>
      <text x="34" y="399" font-weight="700" fill="#d64545">v4  total_cents as a string</text><text x="410" y="399">11</text><text x="486" y="399" font-weight="700" fill="#d64545">1/3</text><text x="580" y="399" fill="#d64545">$.total_cents: expected integer, got string</text>
    </g>

    <rect x="20" y="414" width="840" height="30" rx="8" fill="#e0930f" fill-opacity="0.12" stroke="#e0930f" stroke-width="1.5"/>
    <text x="440" y="433" text-anchor="middle" font-size="10.5" font-weight="700" fill="#e0930f">meanwhile the consumer's own unit suite, over its hand-written mock: 4 of 4 GREEN — including both broken builds.</text>
    <text x="440" y="466" text-anchor="middle" font-size="11.5" font-weight="700" fill="currentColor">A contract is a floor, not a schema: it says what must not disappear, and nothing about what may appear.</text>
  </g>
</svg>
```

The other seven are not in the contract because the consumer never reads them, and a field nobody reads cannot break anybody. That is why the build that added three new fields — growing the response from 11 fields to 14 — verified **3/3** with no change to the contract at all, while the build that renamed one field the consumer *does* read failed **2 of 3 interactions** with an exact location: `$.total_cents: MISSING from the provider response`.

**A contract is a floor, not a schema.** It says what must not disappear and says nothing whatsoever about what may appear. That asymmetry is deliberate and it is what makes the technique usable: a provider that could not add a field without renegotiating with every consumer would simply stop adding fields.

### Consumer-driven: the flip that removes the shared environment

Now the non-obvious part, which is worth reading twice because it inverts the direction people expect.

The naive arrangement is that the provider publishes a spec and consumers test against it. **Consumer-driven contract testing reverses the ownership.** The *consumer's* own test suite records what it actually asked for and actually used. That recording is published. The *provider's* CI then replays it against the real provider and fails the provider's build.

Three consequences follow, and each one is the reason a step in The Problem could not have happened.

**The recording is produced by running the consumer's real code.** In the program, `build_receipt()` — the same function that runs in production — is executed against a mock the consumer's test controls. Whatever request it actually issues is what gets recorded, and the mock refuses any request that was not declared. You cannot record an interaction your code does not make, which is exactly the failure mode of a hand-written double.

**The verification runs in the provider's pipeline, on the provider's clock, with no environment.** The provider needs the contract file and itself. Nothing else is deployed. That is why it can run on every commit rather than on 42.4% of days.

**The provider learns who reads what.** "Nobody in our repository reads `total_cents`" was a true statement and an irrelevant one. The contract makes the dependency explicit, machine-readable, and un-ignorable — it is a failing build in the provider's own repository rather than a Slack message from a team they have never met.

The counterweight, stated honestly: contract testing tells you nothing about consumers who have not published a contract. It converts "unknown consumers" into "consumers who opted in", which is a large improvement and not a guarantee. The third consumer in The Problem — the one nobody knew existed — is still invisible until it publishes something.

### What each gate actually proves

Three mechanisms get called "contract testing" in conversation and they prove three genuinely different things. The program runs six real defects through all three, executing each gate rather than assuming its result.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 452" width="100%" style="max-width:840px" role="img" aria-label="Six real cross-service defects run through three gates. A spec diff on the published API description caught four of six, a consumer-driven contract test caught three of six, and an end-to-end run against the shared environment caught four of six. The rename and the removed currency were caught by all three. The error contract change, where a 404 became a 200 with a null body, was caught by the spec diff and the contract but not by the end-to-end suite, whose happy path never requests a missing order. The redenomination into dollars and the reordered line array were caught only by the end-to-end gate, because only it asserts on a value. The removal of a field no consumer reads was flagged only by the spec diff, a breaking-change alarm that broke nobody. Because the shared environment is green on only 42.4 percent of days, the end-to-end gate's effective rate is 1.69 of 6 per attempt against the contract gate's 3 of 6 every time.">
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <text x="440" y="24" text-anchor="middle" font-size="14.5" font-weight="700" fill="currentColor">Three gates, three different guarantees — and none of them is a superset</text>

    <g fill="none" stroke-width="1.6" stroke-linejoin="round">
      <rect x="310" y="42" width="112" height="42" rx="8" fill="#7f7f7f" fill-opacity="0.10" stroke="#7f7f7f"/>
      <rect x="440" y="42" width="112" height="42" rx="8" fill="#3553ff" fill-opacity="0.12" stroke="#3553ff"/>
      <rect x="570" y="42" width="112" height="42" rx="8" fill="#e0930f" fill-opacity="0.12" stroke="#e0930f"/>
    </g>
    <g text-anchor="middle" fill="currentColor">
      <text x="366" y="58" font-size="10" font-weight="700" fill="#7f7f7f">SPEC DIFF</text>
      <text x="366" y="72" font-size="8" opacity="0.85">shape of the</text>
      <text x="366" y="81" font-size="8" opacity="0.85">published API</text>
      <text x="496" y="58" font-size="10" font-weight="700" fill="#3553ff">CONTRACT</text>
      <text x="496" y="72" font-size="8" opacity="0.85">what a consumer</text>
      <text x="496" y="81" font-size="8" opacity="0.85">actually reads</text>
      <text x="626" y="58" font-size="10" font-weight="700" fill="#e0930f">END-TO-END</text>
      <text x="626" y="72" font-size="8" opacity="0.85">the values the</text>
      <text x="626" y="81" font-size="8" opacity="0.85">system produces</text>
    </g>

    <g fill="none" stroke="currentColor" stroke-width="1.1" opacity="0.4">
      <path d="M16 96 L 864 96"/><path d="M16 268 L 864 268"/>
    </g>

    <g stroke-width="1.3">
      <rect x="310" y="106" width="112" height="18" rx="4" fill="#0fa07f" fill-opacity="0.22" stroke="#0fa07f"/><rect x="440" y="106" width="112" height="18" rx="4" fill="#0fa07f" fill-opacity="0.22" stroke="#0fa07f"/><rect x="570" y="106" width="112" height="18" rx="4" fill="#0fa07f" fill-opacity="0.22" stroke="#0fa07f"/>
      <rect x="310" y="134" width="112" height="18" rx="4" fill="#0fa07f" fill-opacity="0.22" stroke="#0fa07f"/><rect x="440" y="134" width="112" height="18" rx="4" fill="#0fa07f" fill-opacity="0.22" stroke="#0fa07f"/><rect x="570" y="134" width="112" height="18" rx="4" fill="#0fa07f" fill-opacity="0.22" stroke="#0fa07f"/>
      <rect x="310" y="162" width="112" height="18" rx="4" fill="#0fa07f" fill-opacity="0.22" stroke="#0fa07f"/><rect x="440" y="162" width="112" height="18" rx="4" fill="#0fa07f" fill-opacity="0.22" stroke="#0fa07f"/><rect x="570" y="162" width="112" height="18" rx="4" fill="#d64545" fill-opacity="0.14" stroke="#d64545" stroke-opacity="0.55"/>
      <rect x="310" y="190" width="112" height="18" rx="4" fill="#d64545" fill-opacity="0.14" stroke="#d64545" stroke-opacity="0.55"/><rect x="440" y="190" width="112" height="18" rx="4" fill="#d64545" fill-opacity="0.14" stroke="#d64545" stroke-opacity="0.55"/><rect x="570" y="190" width="112" height="18" rx="4" fill="#0fa07f" fill-opacity="0.22" stroke="#0fa07f"/>
      <rect x="310" y="218" width="112" height="18" rx="4" fill="#d64545" fill-opacity="0.14" stroke="#d64545" stroke-opacity="0.55"/><rect x="440" y="218" width="112" height="18" rx="4" fill="#d64545" fill-opacity="0.14" stroke="#d64545" stroke-opacity="0.55"/><rect x="570" y="218" width="112" height="18" rx="4" fill="#0fa07f" fill-opacity="0.22" stroke="#0fa07f"/>
      <rect x="310" y="246" width="112" height="18" rx="4" fill="#e0930f" fill-opacity="0.24" stroke="#e0930f"/><rect x="440" y="246" width="112" height="18" rx="4" fill="#d64545" fill-opacity="0.14" stroke="#d64545" stroke-opacity="0.55"/><rect x="570" y="246" width="112" height="18" rx="4" fill="#d64545" fill-opacity="0.14" stroke="#d64545" stroke-opacity="0.55"/>
    </g>

    <g fill="currentColor" font-size="8.8">
      <text x="20" y="119">d1</text><text x="50" y="119">rename total_cents -&gt; amount_cents</text>
      <text x="20" y="147">d2</text><text x="50" y="147">remove currency from the response</text>
      <text x="20" y="175">d3</text><text x="50" y="175">404 becomes 200 with a null body</text>
      <text x="20" y="203">d4</text><text x="50" y="203" font-weight="700">total_cents redenominated in DOLLARS</text>
      <text x="20" y="231">d5</text><text x="50" y="231" font-weight="700">lines[] returned in a different order</text>
      <text x="20" y="259">d6</text><text x="50" y="259">shipping_cents removed — nobody reads it</text>
    </g>
    <g fill="currentColor" font-size="8.5" text-anchor="middle" font-weight="700">
      <text x="366" y="119" fill="#0fa07f">caught</text><text x="496" y="119" fill="#0fa07f">caught</text><text x="626" y="119" fill="#0fa07f">caught</text>
      <text x="366" y="147" fill="#0fa07f">caught</text><text x="496" y="147" fill="#0fa07f">caught</text><text x="626" y="147" fill="#0fa07f">caught</text>
      <text x="366" y="175" fill="#0fa07f">caught</text><text x="496" y="175" fill="#0fa07f">caught</text><text x="626" y="175" fill="#d64545" opacity="0.8">missed</text>
      <text x="366" y="203" fill="#d64545" opacity="0.8">missed</text><text x="496" y="203" fill="#d64545" opacity="0.8">missed</text><text x="626" y="203" fill="#0fa07f">caught</text>
      <text x="366" y="231" fill="#d64545" opacity="0.8">missed</text><text x="496" y="231" fill="#d64545" opacity="0.8">missed</text><text x="626" y="231" fill="#0fa07f">caught</text>
      <text x="366" y="259" fill="#e0930f">caught</text><text x="496" y="259" fill="#d64545" opacity="0.8">missed</text><text x="626" y="259" fill="#d64545" opacity="0.8">missed</text>
    </g>
    <g fill="currentColor" font-size="8.2" opacity="0.85">
      <text x="700" y="175">the happy path never</text><text x="700" y="185">asks for a missing order</text>
      <text x="700" y="203">a change of MEANING —</text><text x="700" y="213">only a value sees it</text>
      <text x="700" y="252" fill="#e0930f" font-weight="700">a false alarm: it broke</text><text x="700" y="262" fill="#e0930f" font-weight="700">nobody at all</text>
    </g>

    <g font-size="11" font-weight="700" text-anchor="middle">
      <text x="366" y="288" fill="#7f7f7f">4 / 6</text><text x="496" y="288" fill="#3553ff">3 / 6</text><text x="626" y="288" fill="#e0930f">4 / 6</text>
    </g>
    <text x="20" y="288" font-size="9" font-weight="700" fill="currentColor" opacity="0.7">CAUGHT, OUT OF SIX</text>

    <rect x="16" y="306" width="848" height="76" rx="9" fill="#7f7f7f" fill-opacity="0.07" stroke="currentColor" stroke-opacity="0.4" stroke-width="1.5"/>
    <g fill="currentColor" font-size="9.5">
      <text x="32" y="326" font-weight="700">and then multiply the end-to-end column by how often its environment can answer:</text>
      <text x="32" y="346">end-to-end</text><text x="180" y="346" fill="#e0930f" font-weight="700">4/6 x 0.424 = 1.69/6</text><text x="360" y="346" opacity="0.85">per attempt — it needs 11 services green at once</text>
      <text x="32" y="364">contract</text><text x="180" y="364" fill="#0fa07f" font-weight="700">3/6, every time</text><text x="360" y="364" opacity="0.85">— it runs in the provider's own CI, sharing nothing</text>
    </g>

    <text x="440" y="406" text-anchor="middle" font-size="11.5" font-weight="700" fill="currentColor">The contract gate is not the strongest gate. It is the strongest gate that always runs.</text>
    <text x="440" y="426" text-anchor="middle" font-size="10.5" fill="currentColor" opacity="0.9">Keep a thin end-to-end suite for the two defects only a value assertion can see — and keep it thin, because it is expensive.</text>
    <text x="440" y="444" text-anchor="middle" font-size="9.5" fill="currentColor" opacity="0.75">d6 is the cost of the schema-only gate: the one defect it uniquely caught was not a defect.</text>
  </g>
</svg>
```

**Schema/spec diffing** (`oasdiff`, `openapi-diff`) compares the shape of the published API description between two versions. It caught **4 of 6** — and it is the only gate that flagged `d6`, the removal of `shipping_cents`, a field **no consumer reads**. That is not a defect. It is a false alarm, and false alarms are how a CI gate becomes a channel everyone mutes. A spec diff knows what the API *is* and cannot know what anyone *needs*.

**Consumer-driven contract verification** caught **3 of 6**, and its unique catch is instructive: `d3`, where a `404` became a `200` with a null body. The end-to-end suite missed that one, because its happy path never asks for an order that does not exist, while the consumer explicitly recorded an interaction for it. **A contract carries the error paths a happy-path test never walks.** ([Request Validation & Error Contracts](../../02-api-design/03-request-validation-error-contracts/) is why those paths are part of the interface in the first place.)

**End-to-end** caught **4 of 6**, and it was the only gate to catch `d4` and `d5` — the redenomination into dollars and the reordered line array. Both are changes to *meaning* with no change to shape, and it caught them for exactly one reason: **it asserts on a value.** No schema and no contract can carry a value assertion, because the whole point of a contract is that the provider is free to return any integer.

So end-to-end is genuinely stronger on this defect set. Then multiply it by the environment it needs: `4/6 × 0.424 = **1.69/6** per attempt`, against the contract gate's **3/6, every time**. That is the real comparison, and it is not close.

**The contract gate is not the strongest gate. It is the strongest gate that always runs.** Keep a small end-to-end suite for the value assertions nothing else can make. Keep it small, because you are paying for it in the availability of eleven services at once.

### Compatibility is a question about a pair

"Is this change backward compatible?" is not a well-formed question about a schema. Compatibility is a property of a **(reader, writer) pair**, and the two directions have precise names:

- **Backward compatible** — the **new reader** can read **old data**.
- **Forward compatible** — an **old reader** can read **new data**.
- **Full** — both. **Neither** — you need [expand–contract](../../10-infrastructure-and-deployment/13-zero-downtime-schema-changes/).

The direction names the *data*, not the code. [Schema Evolution & Event Contracts](../../06-messaging-and-pub-sub/12-schema-evolution-and-event-contracts/) derives these for a durable log, where the reader is always new and the data is always old; the twist at a synchronous seam is that **an HTTP interaction has two data flows running in opposite directions at once**.

For a **response**, the provider writes and the consumer reads. For a **request**, the consumer writes and the provider reads. So the same English sentence — "make a required field optional" — has opposite answers depending on which half of the interaction it touches, and the program measures both:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 500" width="100%" style="max-width:840px" role="img" aria-label="Compatibility is a question about a pair of schemas, and deploy order picks the pair. The upper panel shows that for a response the provider writes and the consumer reads, so backward compatibility means the consumer ships first, while for a request the consumer writes and the provider reads, so backward compatibility means the provider ships first. The table below lists twelve schema changes, each decided by round-tripping four hundred records in each direction, with the deploy order the change forces and the failed requests measured in a three-thousand-request rolling deploy. Four hundred records were written and read in each direction for every row. Rows seven, eight and nine are highlighted as the cases where intuition is wrong: adding a value to a response enum is backward compatible and still breaks every consumer, removing a value the provider no longer emits breaks the new reader, and relaxing a required response field to optional is a breaking change. Row twelve, a redenomination of total_cents into dollars, is fully compatible in both directions, produces zero errors in either deploy order, and answers 811 and 2337 requests with a wrong number.">
  <defs>
    <marker id="p12-10-b1" markerWidth="9" markerHeight="9" refX="5.5" refY="3" orient="auto"><path d="M0,0 L6.5,3 L0,6 Z" fill="#7f7f7f"/></marker>
  </defs>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <text x="440" y="24" text-anchor="middle" font-size="14.5" font-weight="700" fill="currentColor">Whoever READS the changed data ships first — and who that is flips with the direction</text>

    <g fill="none" stroke-width="1.7" stroke-linejoin="round">
      <rect x="20" y="38" width="410" height="86" rx="10" fill="#3553ff" fill-opacity="0.08" stroke="#3553ff"/>
      <rect x="450" y="38" width="410" height="86" rx="10" fill="#7c5cff" fill-opacity="0.08" stroke="#7c5cff"/>
      <rect x="52" y="72" width="118" height="26" rx="6" fill="#e0930f" fill-opacity="0.16" stroke="#e0930f"/>
      <rect x="280" y="72" width="118" height="26" rx="6" fill="#0fa07f" fill-opacity="0.16" stroke="#0fa07f"/>
      <rect x="482" y="72" width="118" height="26" rx="6" fill="#e0930f" fill-opacity="0.16" stroke="#e0930f"/>
      <rect x="710" y="72" width="118" height="26" rx="6" fill="#0fa07f" fill-opacity="0.16" stroke="#0fa07f"/>
    </g>
    <g fill="none" stroke="#7f7f7f" stroke-width="1.8">
      <path d="M170 85 L 274 85" marker-end="url(#p12-10-b1)"/>
      <path d="M600 85 L 704 85" marker-end="url(#p12-10-b1)"/>
    </g>
    <g fill="currentColor" text-anchor="middle">
      <text x="225" y="58" font-size="10.5" font-weight="700" fill="#3553ff">a RESPONSE change</text>
      <text x="111" y="89" font-size="9.5" font-weight="700" fill="#e0930f">provider = WRITER</text>
      <text x="339" y="89" font-size="9.5" font-weight="700" fill="#0fa07f">consumer = READER</text>
      <text x="222" y="79" font-size="8" opacity="0.75">data</text>
      <text x="225" y="115" font-size="9.5" font-weight="700">BACKWARD ⇒ the CONSUMER ships first</text>
      <text x="655" y="58" font-size="10.5" font-weight="700" fill="#7c5cff">a REQUEST change</text>
      <text x="541" y="89" font-size="9.5" font-weight="700" fill="#e0930f">consumer = WRITER</text>
      <text x="769" y="89" font-size="9.5" font-weight="700" fill="#0fa07f">provider = READER</text>
      <text x="652" y="79" font-size="8" opacity="0.75">data</text>
      <text x="655" y="115" font-size="9.5" font-weight="700">BACKWARD ⇒ the PROVIDER ships first</text>
    </g>
    <text x="440" y="141" text-anchor="middle" font-size="9.5" fill="currentColor" opacity="0.9">BACKWARD = the new READER can read old data, so the reader may ship first  ·  FORWARD = old readers can read new data, so the writer may ship first</text>

    <g fill="#e0930f" fill-opacity="0.09">
      <rect x="16" y="296" width="848" height="60"/>
    </g>
    <rect x="16" y="396" width="848" height="20" fill="#d64545" fill-opacity="0.09"/>

    <g fill="currentColor" font-size="8" font-weight="700" opacity="0.65">
      <text x="20" y="168">#</text><text x="40" y="168">THE CHANGE</text><text x="298" y="168">DIR</text><text x="344" y="168">BACKWARD</text><text x="424" y="168">FORWARD</text><text x="500" y="168">VERDICT</text><text x="592" y="168">SHIP FIRST</text><text x="682" y="168">FAILED REQUESTS  CONS-1st / PROV-1st</text>
    </g>
    <g fill="none" stroke="currentColor" stroke-width="1.1" opacity="0.4">
      <path d="M16 174 L 864 174"/><path d="M16 418 L 864 418"/>
    </g>

    <g fill="currentColor" font-size="8.6">
      <text x="20" y="190">1</text><text x="40" y="190">add an optional response field with a default</text><text x="298" y="190" opacity="0.7">resp</text><text x="344" y="190">400/400</text><text x="424" y="190">400/400</text><text x="500" y="190" font-weight="700" fill="#0fa07f">FULL</text><text x="592" y="190">either</text><text x="700" y="190">0 / 0</text>
      <text x="20" y="210">2</text><text x="40" y="210">remove an optional response field</text><text x="298" y="210" opacity="0.7">resp</text><text x="344" y="210">400/400</text><text x="424" y="210">400/400</text><text x="500" y="210" font-weight="700" fill="#0fa07f">FULL</text><text x="592" y="210">either</text><text x="700" y="210">0 / 0</text>
      <text x="20" y="230">3</text><text x="40" y="230">remove a required response field</text><text x="298" y="230" opacity="0.7">resp</text><text x="344" y="230">400/400</text><text x="424" y="230" fill="#d64545">0/400</text><text x="500" y="230" font-weight="700" fill="#3553ff">BACKWARD</text><text x="592" y="230">consumer</text><text x="700" y="230">0 / 1,489</text>
      <text x="20" y="250">4</text><text x="40" y="250">rename a response field</text><text x="298" y="250" opacity="0.7">resp</text><text x="344" y="250" fill="#d64545">0/400</text><text x="424" y="250" fill="#d64545">0/400</text><text x="500" y="250" font-weight="700" fill="#d64545">NEITHER</text><text x="592" y="250" font-weight="700" fill="#d64545">no safe order</text><text x="700" y="250" fill="#d64545">1,521 / 1,546</text>
      <text x="20" y="270">5</text><text x="40" y="270">widen a response type   integer -&gt; number</text><text x="298" y="270" opacity="0.7">resp</text><text x="344" y="270">400/400</text><text x="424" y="270" fill="#d64545">0/400</text><text x="500" y="270" font-weight="700" fill="#3553ff">BACKWARD</text><text x="592" y="270">consumer</text><text x="700" y="270">0 / 1,523</text>
      <text x="20" y="290">6</text><text x="40" y="290">narrow a response type  number -&gt; integer</text><text x="298" y="290" opacity="0.7">resp</text><text x="344" y="290" fill="#d64545">104/400</text><text x="424" y="290">400/400</text><text x="500" y="290" font-weight="700" fill="#7c5cff">FORWARD</text><text x="592" y="290">provider</text><text x="700" y="290">1,059 / 0</text>
      <text x="20" y="310" font-weight="700">7</text><text x="40" y="310" font-weight="700">add a value to a response enum</text><text x="298" y="310" opacity="0.7">resp</text><text x="344" y="310">400/400</text><text x="424" y="310" fill="#d64545">318/400</text><text x="500" y="310" font-weight="700" fill="#3553ff">BACKWARD</text><text x="592" y="310">consumer</text><text x="700" y="310">0 / 323</text>
      <text x="20" y="330" font-weight="700">8</text><text x="40" y="330" font-weight="700">remove a value from a response enum</text><text x="298" y="330" opacity="0.7">resp</text><text x="344" y="330" fill="#d64545">296/400</text><text x="424" y="330">400/400</text><text x="500" y="330" font-weight="700" fill="#7c5cff">FORWARD</text><text x="592" y="330">provider</text><text x="700" y="330">384 / 0</text>
      <text x="20" y="350" font-weight="700">9</text><text x="40" y="350" font-weight="700">make a required response field OPTIONAL</text><text x="298" y="350" opacity="0.7">resp</text><text x="344" y="350">400/400</text><text x="424" y="350" fill="#d64545">296/400</text><text x="500" y="350" font-weight="700" fill="#3553ff">BACKWARD</text><text x="592" y="350">consumer</text><text x="700" y="350">0 / 447</text>
      <text x="20" y="370">10</text><text x="40" y="370">add a required request field</text><text x="298" y="370" font-weight="700" fill="#7c5cff">req</text><text x="344" y="370" fill="#d64545">0/400</text><text x="424" y="370">400/400</text><text x="500" y="370" font-weight="700" fill="#7c5cff">FORWARD</text><text x="592" y="370" font-weight="700" fill="#7c5cff">consumer</text><text x="700" y="370">0 / 1,505</text>
      <text x="20" y="390">11</text><text x="40" y="390">make a required request field optional</text><text x="298" y="390" font-weight="700" fill="#7c5cff">req</text><text x="344" y="390">400/400</text><text x="424" y="390" fill="#d64545">282/400</text><text x="500" y="390" font-weight="700" fill="#3553ff">BACKWARD</text><text x="592" y="390" font-weight="700" fill="#7c5cff">provider</text><text x="700" y="390">451 / 0</text>
      <text x="20" y="410" font-weight="700">12</text><text x="40" y="410" font-weight="700" fill="#d64545">redenominate total_cents in DOLLARS (same type)</text><text x="298" y="410" opacity="0.7">resp</text><text x="344" y="410" fill="#0fa07f">400/400</text><text x="424" y="410" fill="#0fa07f">400/400</text><text x="500" y="410" font-weight="700" fill="#0fa07f">FULL</text><text x="592" y="410" font-weight="700" fill="#d64545">SILENT</text><text x="700" y="410" font-weight="700" fill="#d64545">0 / 0 — and 811 / 2,337 WRONG</text>
    </g>

    <text x="20" y="437" font-size="9" fill="#e0930f" font-weight="700">rows 7-9: the provider only added, only removed what it no longer sends, only relaxed a rule — and broke the consumer each time.</text>
    <text x="20" y="452" font-size="9" fill="#7c5cff" font-weight="700">rows 10-11: identical wording, opposite answer, because on a REQUEST the provider is the reader.</text>
    <text x="440" y="476" text-anchor="middle" font-size="11.5" font-weight="700" fill="currentColor">400 records per direction per row, and an independent static classifier, agreed on 12/12 rows.</text>
    <text x="440" y="494" text-anchor="middle" font-size="10.5" fill="currentColor" opacity="0.9">A 3,000-request rolling-deploy simulation then agreed with both of them on 12/12 deploys.</text>
  </g>
</svg>
```

Every verdict in that table was produced by writing **400 records** under one schema and reading them under the other, in both directions, for all twelve rows — **9,600 round-trips** — not by consulting a table. An independent static classifier, which never touches data, agreed on **12/12 rows**. Then a 3,000-request rolling-deploy simulation agreed with both on **12/12 deploys**. Three routes to the same answer is how you know the rule is real rather than remembered.

The rule that falls out is short: **the side that reads the changed data must understand both shapes, so backward compatibility lets the reader ship first and forward compatibility lets the writer ship first.** Rows 10 and 11 are the flip. "Add a required request field" is `FORWARD`-only and needs the **consumer** to ship first; "make a required request field optional" is `BACKWARD`-only and needs the **provider** to ship first. Both are the general rule applied to a data flow that runs the other way.

This is also the honest answer to "should we just version the endpoint?" ([API Versioning](../../02-api-design/05-api-versioning/)). A new major version is what you reach for on row 4 — `NEITHER` — where **1,521 and 1,546 requests failed in the two deploy orders respectively** and there is no ordering that works. For every other row, versioning is a much more expensive way to buy something a deploy order already gives you.

### Breaking or not: the decidable part, and the three rows people get wrong

Most of that table is unsurprising once you hold the reader/writer pair in your head. Three rows are not, and all three share a shape: **the provider believed it had only made the interface more permissive.**

**Row 7 — adding a value to an enum is breaking for the consumer.** The provider added `partially_shipped` to `status`. Backward: fine, **400/400** — the new reader knows every old symbol. Forward: **318/400**, because an old consumer with an exhaustive `match`/`switch` and no default arm meets a symbol that did not exist when it was compiled. The asymmetry is the point: *adding* to your output is a *restriction* on your reader's assumptions. Every consumer that enumerated your values is now wrong, and none of them changed.

**Row 8 — removing a value you no longer emit is also breaking.** The mirror image, and it feels safe precisely because the provider has already stopped producing the symbol. Backward: **296/400**. During the rollout, providers still running the old build are still emitting `pending`, and the new consumer's narrowed enum rejects it. The change is only safe once no *instance* and no *stored row* can still produce the value — which is later than you think.

**Row 9 — relaxing `required` to `optional` on a response is breaking.** This is the one that reliably surprises people, because relaxing a constraint sounds monotonically safe. Forward: **296/400**. The old consumer still demands the field and still dereferences it; making it optional means the provider may now omit it. Relaxation is safe on the **request** side (row 11, where the provider is the reader) and unsafe on the **response** side. Same word, opposite consequence, and the direction of the data is the only thing that distinguishes them.

The generalisation worth carrying: **a change is breaking if it invalidates an assumption the other side was entitled to make**, and "entitled" is decided by which side reads. Nothing about permissive-versus-restrictive survives that test on its own.

### Postel's law is a liability at a contract boundary

RFC 761 (Postel, *Transmission Control Protocol*, 1980), §2.10: *"be conservative in what you do, be liberal in what you accept from others."* It is the most-quoted sentence in protocol design and it is excellent advice for a protocol that must interoperate with implementations you will never meet.

At a contract boundary inside your own system, it is a mechanism for converting exceptions into wrong numbers. The program measures exactly that: twelve provider releases, two frozen consumers, 200 orders per release, each release measured in isolation so every row prices one change.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 520" width="100%" style="max-width:840px" role="img" aria-label="Twelve provider releases measured against two frozen consumers, two hundred orders each, every release in isolation. A strict consumer rejected data in six of the twelve releases: a string-encoded total, a new status value, a null currency, an upper-cased status, a paginated lines object and a renamed total field. A tolerant consumer raised no exception in any of the twelve, but produced wrong receipts in three of them: the new status value, the redenomination into dollars, and the rename. Five releases were free for both. Of the six changes the strict reader would have rejected, tolerance handled four correctly and turned two into silent corruption. In total the tolerant consumer issued 226 wrong receipts and understated what it billed by 101,132,788 minor units, with zero exceptions raised.">
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <text x="440" y="24" text-anchor="middle" font-size="14.5" font-weight="700" fill="currentColor">Tolerance does not remove the breakage. It changes what the breakage looks like.</text>
    <text x="440" y="44" text-anchor="middle" font-size="9.5" fill="currentColor" opacity="0.85">12 provider releases · 200 orders each · two frozen consumers · every release measured in isolation, so each row prices one change</text>

    <g stroke-width="1.4">
      <rect x="196" y="58" width="14" height="12" rx="3" fill="#0fa07f" fill-opacity="0.35" stroke="#0fa07f"/>
      <rect x="336" y="58" width="14" height="12" rx="3" fill="#e0930f" fill-opacity="0.35" stroke="#e0930f"/>
      <rect x="524" y="58" width="14" height="12" rx="3" fill="#d64545" fill-opacity="0.35" stroke="#d64545"/>
    </g>
    <g fill="currentColor" font-size="9">
      <text x="216" y="68">handled correctly</text><text x="356" y="68">rejected loudly — an outage</text><text x="544" y="68">wrong number, no exception</text>
    </g>

    <g fill="currentColor" font-size="8" font-weight="700" opacity="0.65">
      <text x="20" y="98">REL</text><text x="58" y="98">WHAT THE PROVIDER SHIPPED</text><text x="300" y="98">STRICT CONSUMER</text><text x="440" y="98">TOLERANT CONSUMER</text><text x="592" y="98">OUTCOME</text>
    </g>
    <g fill="none" stroke="currentColor" stroke-width="1.1" opacity="0.4">
      <path d="M16 104 L 864 104"/><path d="M16 372 L 864 372"/>
    </g>

    <g stroke-width="1.3">
      <rect x="300" y="107" width="120" height="18" rx="4" fill="#0fa07f" fill-opacity="0.20" stroke="#0fa07f"/><rect x="440" y="107" width="120" height="18" rx="4" fill="#0fa07f" fill-opacity="0.20" stroke="#0fa07f"/>
      <rect x="300" y="129" width="120" height="18" rx="4" fill="#0fa07f" fill-opacity="0.20" stroke="#0fa07f"/><rect x="440" y="129" width="120" height="18" rx="4" fill="#0fa07f" fill-opacity="0.20" stroke="#0fa07f"/>
      <rect x="300" y="151" width="120" height="18" rx="4" fill="#e0930f" fill-opacity="0.28" stroke="#e0930f"/><rect x="440" y="151" width="120" height="18" rx="4" fill="#0fa07f" fill-opacity="0.20" stroke="#0fa07f"/>
      <rect x="300" y="173" width="120" height="18" rx="4" fill="#e0930f" fill-opacity="0.28" stroke="#e0930f"/><rect x="440" y="173" width="120" height="18" rx="4" fill="#d64545" fill-opacity="0.28" stroke="#d64545"/>
      <rect x="300" y="195" width="120" height="18" rx="4" fill="#e0930f" fill-opacity="0.28" stroke="#e0930f"/><rect x="440" y="195" width="120" height="18" rx="4" fill="#0fa07f" fill-opacity="0.20" stroke="#0fa07f"/>
      <rect x="300" y="217" width="120" height="18" rx="4" fill="#0fa07f" fill-opacity="0.20" stroke="#0fa07f"/><rect x="440" y="217" width="120" height="18" rx="4" fill="#0fa07f" fill-opacity="0.20" stroke="#0fa07f"/>
      <rect x="300" y="239" width="120" height="18" rx="4" fill="#0fa07f" fill-opacity="0.20" stroke="#0fa07f"/><rect x="440" y="239" width="120" height="18" rx="4" fill="#0fa07f" fill-opacity="0.20" stroke="#0fa07f"/>
      <rect x="300" y="261" width="120" height="18" rx="4" fill="#0fa07f" fill-opacity="0.20" stroke="#0fa07f"/><rect x="440" y="261" width="120" height="18" rx="4" fill="#d64545" fill-opacity="0.28" stroke="#d64545"/>
      <rect x="300" y="283" width="120" height="18" rx="4" fill="#0fa07f" fill-opacity="0.20" stroke="#0fa07f"/><rect x="440" y="283" width="120" height="18" rx="4" fill="#0fa07f" fill-opacity="0.20" stroke="#0fa07f"/>
      <rect x="300" y="305" width="120" height="18" rx="4" fill="#e0930f" fill-opacity="0.28" stroke="#e0930f"/><rect x="440" y="305" width="120" height="18" rx="4" fill="#0fa07f" fill-opacity="0.20" stroke="#0fa07f"/>
      <rect x="300" y="327" width="120" height="18" rx="4" fill="#e0930f" fill-opacity="0.28" stroke="#e0930f"/><rect x="440" y="327" width="120" height="18" rx="4" fill="#0fa07f" fill-opacity="0.20" stroke="#0fa07f"/>
      <rect x="300" y="349" width="120" height="18" rx="4" fill="#e0930f" fill-opacity="0.28" stroke="#e0930f"/><rect x="440" y="349" width="120" height="18" rx="4" fill="#d64545" fill-opacity="0.28" stroke="#d64545"/>
    </g>

    <g fill="currentColor" font-size="8.6">
      <text x="20" y="120">r01</text><text x="58" y="120">add promised_at</text><text x="360" y="120" text-anchor="middle">0 / 200</text><text x="500" y="120" text-anchor="middle">0 / 200</text><text x="592" y="120" opacity="0.75">free</text>
      <text x="20" y="142">r02</text><text x="58" y="142">add discount_cents</text><text x="360" y="142" text-anchor="middle">0 / 200</text><text x="500" y="142" text-anchor="middle">0 / 200</text><text x="592" y="142" opacity="0.75">free</text>
      <text x="20" y="164">r03</text><text x="58" y="164">total_cents sent as a string</text><text x="360" y="164" text-anchor="middle" font-weight="700">200 / 200</text><text x="500" y="164" text-anchor="middle">0 / 200</text><text x="592" y="164" font-weight="700" fill="#0fa07f">absorbed</text>
      <text x="20" y="186">r04</text><text x="58" y="186">status gains 'partially_shipped'</text><text x="360" y="186" text-anchor="middle" font-weight="700">29 / 200</text><text x="500" y="186" text-anchor="middle" font-weight="700" fill="#d64545">29 / 200</text><text x="592" y="186" font-weight="700" fill="#d64545">DEFERRED</text>
      <text x="20" y="208">r05</text><text x="58" y="208">currency null for domestic orders</text><text x="360" y="208" text-anchor="middle" font-weight="700">86 / 200</text><text x="500" y="208" text-anchor="middle">0 / 200</text><text x="592" y="208" font-weight="700" fill="#0fa07f">absorbed</text>
      <text x="20" y="230">r06</text><text x="58" y="230">rename tax_cents -&gt; tax_amount_cents</text><text x="360" y="230" text-anchor="middle">0 / 200</text><text x="500" y="230" text-anchor="middle">0 / 200</text><text x="592" y="230" opacity="0.75">free</text>
      <text x="20" y="252">r07</text><text x="58" y="252">drop shipping_cents</text><text x="360" y="252" text-anchor="middle">0 / 200</text><text x="500" y="252" text-anchor="middle">0 / 200</text><text x="592" y="252" opacity="0.75">free</text>
      <text x="20" y="274">r08</text><text x="58" y="274" font-weight="700">total_cents redenominated in DOLLARS</text><text x="360" y="274" text-anchor="middle">0 / 200</text><text x="500" y="274" text-anchor="middle" font-weight="700" fill="#d64545">99 / 200</text><text x="592" y="274" font-weight="700" fill="#d64545">INVISIBLE</text>
      <text x="20" y="296">r09</text><text x="58" y="296">created_at gains a +05:30 offset</text><text x="360" y="296" text-anchor="middle">0 / 200</text><text x="500" y="296" text-anchor="middle">0 / 200</text><text x="592" y="296" opacity="0.75">free</text>
      <text x="20" y="318">r10</text><text x="58" y="318">status upper-cased</text><text x="360" y="318" text-anchor="middle" font-weight="700">94 / 200</text><text x="500" y="318" text-anchor="middle">0 / 200</text><text x="592" y="318" font-weight="700" fill="#0fa07f">absorbed</text>
      <text x="20" y="340">r11</text><text x="58" y="340">lines becomes {items:[...]}</text><text x="360" y="340" text-anchor="middle" font-weight="700">200 / 200</text><text x="500" y="340" text-anchor="middle">0 / 200</text><text x="592" y="340" font-weight="700" fill="#0fa07f">absorbed</text>
      <text x="20" y="362">r12</text><text x="58" y="362" font-weight="700">rename total_cents -&gt; amount_cents</text><text x="360" y="362" text-anchor="middle" font-weight="700">200 / 200</text><text x="500" y="362" text-anchor="middle" font-weight="700" fill="#d64545">98 / 200</text><text x="592" y="362" font-weight="700" fill="#d64545">DEFERRED</text>
    </g>

    <g fill="currentColor" font-size="8.4" opacity="0.8">
      <text x="690" y="186">tolerance billed 0</text><text x="690" y="197">for a shipped order</text>
      <text x="690" y="274">neither consumer</text><text x="690" y="285">could ever see this</text>
      <text x="690" y="352">every receipt now</text><text x="690" y="363">reads exactly 0</text>
    </g>

    <rect x="16" y="386" width="416" height="76" rx="9" fill="#e0930f" fill-opacity="0.10" stroke="#e0930f" stroke-width="1.5"/>
    <rect x="448" y="386" width="416" height="76" rx="9" fill="#d64545" fill-opacity="0.10" stroke="#d64545" stroke-width="1.5"/>
    <g fill="currentColor">
      <text x="224" y="404" text-anchor="middle" font-size="10.5" font-weight="700" fill="#e0930f">THE STRICT READER</text>
      <text x="224" y="422" text-anchor="middle" font-size="9.5">rejected data in 6 of 12 releases</text>
      <text x="224" y="438" text-anchor="middle" font-size="9.5">0 wrong receipts, ever</text>
      <text x="224" y="454" text-anchor="middle" font-size="9.5" font-weight="700">each rejection is an outage — say so honestly</text>
      <text x="656" y="404" text-anchor="middle" font-size="10.5" font-weight="700" fill="#d64545">THE TOLERANT READER</text>
      <text x="656" y="422" text-anchor="middle" font-size="9.5">0 exceptions raised in 12 of 12 releases</text>
      <text x="656" y="438" text-anchor="middle" font-size="9.5" font-weight="700">226 wrong receipts · 101,132,788 minor units</text>
      <text x="656" y="454" text-anchor="middle" font-size="9.5">understated, with nothing in any log</text>
    </g>

    <text x="440" y="486" text-anchor="middle" font-size="11.5" font-weight="700" fill="currentColor">Of the 6 changes a strict reader would have rejected, tolerance handled 4 correctly and corrupted 2.</text>
    <text x="440" y="506" text-anchor="middle" font-size="10.5" fill="currentColor" opacity="0.9">The 4 it handled are exactly the evidence that persuaded the provider the other 2 were safe. (RFC 9413, 2023.)</text>
  </g>
</svg>
```

Read the four buckets, because the result is more interesting than "tolerance is bad".

**Five releases were free for both** — adding fields, renaming a field nobody reads, dropping a field nobody reads, changing a date format nobody parses. This is the baseline: most provider changes touch nothing.

**Four releases the tolerant reader absorbed correctly.** A string-encoded total, a null currency, an upper-cased status, a paginated `lines` object. The strict consumer rejected **200, 86, 94 and 200 records** on those; the tolerant one coerced and got the right answer every time. Tolerance genuinely bought availability here, and any honest account has to say so: **each of those strict rejections is an outage** until somebody ships a fix.

**Two releases it converted from an exception into a wrong number.** On `r04` it billed **0** for 29 orders that were `partially_shipped` and genuinely owed money — because its `else` branch treats an unknown status as "not billable". On `r12`, the rename from The Problem, every receipt became **exactly 0**: `body.get("total_cents", 0)` did precisely what it was written to do, 98 times, in silence.

**One release neither consumer could see.** `r08`, the redenomination.

Now the argument, which is the one RFC 9413 (Thomson & Pauly, *Maintaining Robust Protocols*, IETF, 2023) makes at protocol scale: **the four absorptions are what caused the two corruptions.** A provider whose changes keep landing without complaint concludes, correctly from the evidence available to it, that its consumers are fine with changes of this kind. Tolerance removes the feedback that would have stopped the next change. RFC 9413's framing is that unused or leniently-handled protocol elements atrophy until they no longer work at all, and the deployments that depend on the lenient behaviour become the de-facto specification.

The totals are the sentence to remember: **0 exceptions raised across 12 of 12 releases, and 226 wrong receipts understating the bill by 101,132,788 minor units.** A strict reader's failure is an incident with a stack trace and a timestamp. A tolerant reader's failure is a number in a ledger, and the only thing in this entire lesson that ever detects it is a reconciliation against an independent source of truth.

The synthesis is not "be strict" but **strict about your slice, tolerant about the rest** — which is what the contract in this lesson encodes literally. Ignore unknown fields (all seven of them). Validate, exactly and loudly, the four you read. Never write `.get(field, default)` for a field that is required by your contract: that line is where an exception becomes a wrong number.

### Contracts for events, where there is nothing to negotiate with

Everything above assumed a request and a response. A consumer of a Kafka topic has neither. It cannot record "when I ask for X you return Y", because it never asks: it is handed whatever was written, possibly months ago, possibly by a producer version that no longer exists.

So the mechanism moves. For events the **schema registry is the contract**, the compatibility mode on the subject is the enforcement, and the check runs at *registration* time rather than at verification time. The `BACKWARD`/`FORWARD`/`FULL` semantics are the same three directions derived above — with the crucial extra that on a retained log the reader may be arbitrarily far in the future, which is what the `*_TRANSITIVE` modes exist for. [Schema Evolution & Event Contracts](../../06-messaging-and-pub-sub/12-schema-evolution-and-event-contracts/) builds that machinery properly, including the registry, upcasters and the six modes; the connection to make here is that **consumer-driven contracts and a schema registry are the same idea against different plumbing** — publish what you require, check it before the change ships, never after.

The one thing that does not transfer is the request half of the interaction. Rows 10 and 11 of the compatibility table have no analogue in a one-way event flow, which is why event compatibility feels simpler: there is only one data direction, so there is only one reader.

### The provider-state problem

Here is where contract testing gets genuinely hard, and where most adoptions stall.

A recorded interaction says "`GET /orders/ord_7hQ2df` returns a confirmed order". To verify that, the provider must *be in a world where `ord_7hQ2df` exists and is confirmed*. That is not a property of the request; it is a property of the provider's database. The contract therefore carries a **provider state**: a string the consumer declares and the provider implements as a setup hook.

Skip it and verification collapses into noise. Measured: against a provider with no state-setup hook, the same contract verified **1 of 3** interactions — and the two failures were `$.status: expected HTTP 200, got 404`, which tells you nothing about compatibility and everything about an empty database. With the hook implemented, **3 of 3**, over **3 distinct states**.

Then it gets worse at scale, and this is the part to plan for:

```text
consumer      interactions   distinct states   contradiction
receipts                 3                 3   -
shipping                 4                 4   ord_7hQ2df: confirmed vs shipped
analytics                2                 2   ord_7hQ2df: confirmed vs cancelled
fraud                    3                 3   -
4 consumers, 12 interactions, 7 distinct states, 2 contradictory pair(s).
```

Four consumers produced **7 distinct states** and **2 contradictory pairs** — two consumers requiring the same order id to be in two different states. No shared seeded fixture can satisfy both, which is the same shared-fixture trap that [Test Data & Fixtures](../07-test-data-and-fixtures/) prices in general. The fix is structural: **each state is a setup function, run immediately before its own interaction, that builds exactly what that interaction needs.** Not a seed file. Not a snapshot. A function per state, owned by the provider, in the provider's repository — because the provider is the only party that knows how to construct its own data.

Two practices keep this from sprawling. Write states as *conditions* rather than *fixtures* ("an order exists and is confirmed", not "order 7hQ2df with the standard fixture"). And treat the state list as an API: when a consumer invents a fifteenth state, that is a design conversation, not a ticket.

### Where contract testing cannot help: semantics

Be exact about the limit, because overselling this technique is how it gets abandoned.

A contract constrains **structure**: which fields exist, what types they have, what shape the response takes. It cannot constrain **meaning**, because meaning is not on the wire.

The program's row 12 is the demonstration. `total_cents` stays named `total_cents`. It stays an integer. It is still always present. The provider simply starts putting a number of *dollars* in it. Round-trip: **400/400 backward, 400/400 forward — verdict `FULL`**, the strongest structural verdict available. The rolling deploy produces **zero errors in either deploy order**. And the consumer computes **1,857,277** where the provider means **185,747,545** — off by a factor of **100**, on every request, with every check green.

No matcher catches this. `like(129900)` asserts "an integer", and 1299 is an integer. A regex on a number is meaningless. An exact-value matcher would fail on every legitimate order. There is no assertion you can add to a contract that distinguishes a correct integer from an incorrect one, because **the contract's job is to permit any integer**.

Three controls actually work, and only one is automated:

1. **Never redefine a field.** Add `total_amount_minor` alongside `total_cents`, dual-write, migrate consumers, then stop writing the old one. The expand–contract sequence from [Zero-Downtime Schema Changes](../../10-infrastructure-and-deployment/13-zero-downtime-schema-changes/), applied to a JSON field. This is the only real answer.
2. **Put the unit in the name and never let it lie.** `_cents`, `_minor`, `_millis`, `_utc`. A field whose name asserts its unit turns a silent redefinition into an obvious falsehood in code review.
3. **Assert on values somewhere.** A thin end-to-end check with a golden expected amount, or a reconciliation against an independent source. In the measured run these were the only mechanisms that ever detected `d4`/`r08`.

Say the general form out loud, because it applies to every technique in this phase: **contract testing moves an integration failure from runtime to build time for the class of failures that are structural, and does nothing at all for the class that is semantic.** That second class is small in count and large in cost, and the control for it is a human reading a diff.

## Build It

[`code/contract_testing.py`](code/contract_testing.py) is seven numbered arguments. Standard library only, one seed (`SEED = 20260718`), about one second, and nothing written outside a `TemporaryDirectory`. Sections 2 and 7 build and use the contract system; sections 1, 3, 4, 5 and 6 are the measurements.

The contract system proper is about 150 lines and it genuinely works end to end. It has four parts.

**Matchers**, because a contract that asserts on values is a contract that fails on real data. Three of them cover essentially everything, following the Pact Specification v3 shape — an example body plus a map from JSON path to a rule:

```python
def like(example: Any) -> Matcher:
    """Match the TYPE, not the value — the provider may return any integer."""
    return Matcher("type", example)


def term(regex: str, example: str) -> Matcher:
    return Matcher("regex", example, regex)


def each_like(template: Any, min_items: int = 1) -> Matcher:
    return Matcher("eachLike", template, min_items=min_items)
```

`compile_expectation()` then walks the expectation and splits it into two things: a plain-JSON example body, and `{"$.total_cents": {"match": "type"}, ...}`. Both go in the file, which is why the file is readable by a human and by a verifier that has never seen your Python.

**The consumer test**, which is the piece that makes it *consumer-driven*. Note that the assertions are on the consumer's own output, and that `build_receipt` is the real production function:

```python
    client = pact.mock_client()
    assert build_receipt(client, "ord_7hQ2df")["amount_due_cents"] == 129900
    for oid, exc in (("ord_3Xb10p", NotBillable), ("ord_GONE99", OrderNotFound)):
        try:
            build_receipt(client, oid)
            raise AssertionError(f"expected {exc.__name__}")
        except exc:
            pass
```

The mock raises `AssertionError: consumer made an unrecorded request` on anything not declared, so the contract cannot drift below what the code does. It also tracks `used` per interaction, which is how the program reports `3/3` exercised — an interaction the consumer stopped making is a stale constraint on the provider and should be deleted.

**The matcher engine**, and the four lines that carry the whole design:

```python
    if isinstance(expected, dict):
        if not isinstance(actual, dict):
            return [f"{path}: expected an object, got {type_name(actual)}"]
        out: list[str] = []
        for k in sorted(expected):
            if k not in actual:
                out.append(f"{path}.{k}: MISSING from the provider response")
            else:
                out += match_node(expected[k], actual[k], rules, f"{path}.{k}")
        return out
```

It iterates the keys of **`expected`**, never of `actual`. Extra keys in the provider's response are not merely tolerated, they are unobservable — that is the mechanical reason the additive build passes 3/3 while the renaming build fails. Change that loop to iterate `actual` and you have built a schema validator with the false-alarm behaviour measured in section 3.

**The verifier**, which is the provider's half and which is where provider states enter:

```python
    for ix in doc["interactions"]:
        if not provider.set_state(ix["providerState"]):
            results.append((ix["description"],
                            [f"provider state not implemented: {ix['providerState']!r}"]))
            continue
        actual = provider.handle(ix["request"])
```

`set_state` returning `False` is a first-class failure rather than a skip. A verifier that silently skips unknown states reports green for a contract it never checked, which is worse than reporting nothing.

The compatibility checker in section 4 refuses to hard-code any verdict. `round_trip()` is the entire definition of compatibility:

```python
def round_trip(reader: Schema, writer: Schema, k: int, rng: random.Random) -> tuple[int, str]:
    """Compatibility is not a lookup: it is whether this loop completes."""
    ok, first = 0, ""
    sf = writer.get("status")
    statuses = tuple(sf.enum) if sf and sf.enum else ("confirmed",)
    for canon in canon_stream(k, rng, statuses):
        try:
            read_record(reader, write_record(writer, canon, rng))
            ok += 1
        except ReadError as exc:
            first = first or str(exc)
    return ok, first
```

`classify()` predicts the same two booleans statically, from the schemas alone, and section 4 prints whether they agree. They do, on 12/12 rows — which is the check that neither the rule table nor the reader is quietly wrong.

Section 5's rolling deploy is the third, independent route. Two lines set up the hazard the whole lesson is about:

```python
        pc, pp = (lead, follow) if order == "consumer_first" else (follow, lead)
        c_new, p_new = rng.random() < pc, rng.random() < pp
```

At any instant during a rollout there is a probability the request is served by a new provider and a probability it was issued by a new consumer, independently. All four pairings occur. That is why "we deployed them together" is not a deploy order — it is all four pairings at once, which is why row 4 fails in every ordering.

Run it:

```bash
python3 phases/12-testing-and-quality/10-contract-testing/code/contract_testing.py
```

```console
CONTRACT TESTING: THE SEAM BETWEEN SERVICES
deterministic, standard library only, seed = 20260718

== 1 · THE INTEGRATION MATRIX: WHY A SHARED ENVIRONMENT STOPS SCALING ==
  M = 3 live versions per service (production, staging, the branch in review)
  dependency graph: service i calls i+1 and i+2, so E edges = one contract each

    services   edges   version combinations   pairwise pairs   contract verifications   matrix/contract
           3       3                     27               27                        3                 9
           5       7                    243               63                        7                35
          11      19                177,147              171                       19             9,324
          30      57               2.06e+14              513                       57          3.61e+12
  M^N grows with the SYSTEM; E grows with the WIRING. At 11 services that is
  177,147 combinations against 19 contracts, and a shared environment
  holds exactly ONE of those combinations at a time.
  lockstep: 11 services x 5 deploys/week = 55/week independently, or 5/week as one
  release train — an 11x difference in how often anything reaches a user.

  the environment's own availability — each service breaks it with p=0.02/day,
  repaired with p=0.25/day (mean repair 4 days); 20,000 simulated days:
    services   simulated green   closed form   longest unbroken red streak
           3            78.5%         79.4%                       29 days
           5            68.9%         68.1%                       39 days
          11            42.4%         42.9%                       52 days
          30            10.0%          9.9%                      161 days
  simulation and closed form agree: availability is a PRODUCT over members, so it
  decays exponentially while every member stays healthy. At 11 services the gate
  answers on 42.4% of days; its longest red stretch was 52 days.

== 2 · A CONTRACT, RECORDED BY THE CONSUMER AND VERIFIED BY THE PROVIDER ==
  the consumer test drove 3 interactions through its own code and wrote a
  1916-byte contract. Interactions the consumer actually exercised: 3/3.
  the provider's 200 response carries 11 top-level fields; the contract constrains
  4 of them, with 6 matching rules on type and pattern — never on the value.

    provider build                            fields   verified   failed
    v1  the recorded baseline                    11      3/3      0
    v2  renames total_cents -> amount_cents      11      1/3      2
          FAIL [a request for a confirmed order]  $.total_cents: MISSING from the provider response
          FAIL [a request for a cancelled order]  $.total_cents: MISSING from the provider response
    v3  adds 3 fields, changes nothing           14      3/3      0
    v4  emits total_cents as a string            11      1/3      2
          FAIL [a request for a confirmed order]  $.total_cents: expected integer, got string ('129900')
          FAIL [a request for a cancelled order]  $.total_cents: expected integer, got string ('129900')
  v3 added three fields and stayed green: a contract is a floor, not a schema.

  the consumer's own unit suite, over a hand-written mock: 4/4 GREEN — including
  both broken builds. A double is a second implementation of someone else's
  contract, written from the same reading as the code, verified by nobody.

== 3 · THREE GATES, SIX DEFECTS: WHAT EACH ONE ACTUALLY PROVES ==
  (S) spec diff on the published API description, (C) consumer-driven contract
  verification, (E) end-to-end against the shared environment.

    id   defect                                             S       C       E
    d1   rename total_cents -> amount_cents              caught  caught  caught
    d2   remove currency from the response               caught  caught  caught
    d3   404 becomes 200 with a null body                caught  caught    .   
    d4   total_cents redenominated in DOLLARS              .       .     caught
    d5   lines[] returned in a different order             .       .     caught
    d6   shipping_cents removed (no consumer reads it)   caught    .       .   

    caught: spec diff 4/6   contract 3/6   end-to-end 4/6
    only end-to-end caught ['d4', 'd5']: a redenomination and a reordering are
    changes to MEANING, and meaning is not a statement a schema can carry.
    only the spec diff caught ['d6']: a field no consumer reads. A breaking-change
    alarm that breaks nobody is how a spec-diff gate becomes a muted channel.
    d3 shows the reverse: the contract carries the 404 the happy path never walks.
    and the end-to-end gate only answers on the 42.4% of days the environment is
    green, so its effective rate is 4/6 x 0.424 = 1.69/6 against the contract
    gate's 3/6, which runs in the provider's own CI with nothing shared.

== 4 · TWELVE SCHEMA CHANGES, DECIDED BY ROUND-TRIPPING REAL DATA ==
  each verdict is 400 records written under one schema and read under the other.
  BACKWARD = new reader reads old data.  FORWARD = old reader reads new data.

     #  change                                            dir   backward   forward    verdict    static
     1  add an optional response field with a default     resp    400/400   400/400   FULL       agree
     2  remove an optional response field                 resp    400/400   400/400   FULL       agree
     3  remove a required response field                  resp    400/400     0/400   BACKWARD   agree
     4  rename a response field                           resp      0/400     0/400   NEITHER    agree
     5  widen a response type  integer -> number          resp    400/400     0/400   BACKWARD   agree
     6  narrow a response type  number -> integer         resp    104/400   400/400   FORWARD    agree
     7  add a value to a response enum                    resp    400/400   318/400   BACKWARD   agree
     8  remove a value from a response enum               resp    296/400   400/400   FORWARD    agree
     9  make a required response field optional           resp    400/400   296/400   BACKWARD   agree
    10  add a required request field                      requ      0/400   400/400   FORWARD    agree
    11  make a required request field optional            requ    400/400   282/400   BACKWARD   agree
    12  redenominate total_cents in DOLLARS (same type)   resp    400/400   400/400   FULL       agree

    an independent static classifier agreed with the measured round-trip on 12/12 rows.
    row  3 forward:  required field 'currency' is absent
    row  4 backward: required field 'amount_cents' is absent
    row  4 forward:  required field 'total_cents' is absent
    row  5 forward:  field 'total_cents': expected integer, got number
    row  6 backward: field 'fx_rate': expected integer, got number
    row  7 forward:  field 'status': unknown enum symbol 'partially_shipped'
    row  8 backward: field 'status': unknown enum symbol 'pending'
    row  9 forward:  required field 'currency' is absent
    row 10 backward: required field 'idempotency_key' is absent
    row 11 forward:  required field 'channel' is absent

  (the three-row commentary printed here is reproduced in The Concept, above)

  row 12 is the one no checker on earth catches:
    the provider means 185,747,545 minor units; the consumer computes 1,857,277 —
    a factor of 100, with every structural check green in both directions.

== 5 · DEPLOY ORDER, DERIVED: WHOEVER READS THE DATA SHIPS FIRST ==
  a rolling deploy of 3000 requests: one side flips instance by instance, then
  the other. Both versions of both sides are live at once — that is the hazard.

     #  change                                           consumer-first     provider-first    ship first
     1  add an optional response field with a default        0e     0w       0e     0w    either
     2  remove an optional response field                    0e     0w       0e     0w    either
     3  remove a required response field                     0e     0w    1489e     0w    consumer
     4  rename a response field                           1521e     0w    1546e     0w    NEITHER
     5  widen a response type  integer -> number             0e     0w    1523e     0w    consumer
     6  narrow a response type  number -> integer         1059e     0w       0e     0w    provider
     7  add a value to a response enum                       0e     0w     323e     0w    consumer
     8  remove a value from a response enum                384e     0w       0e     0w    provider
     9  make a required response field optional              0e     0w     447e     0w    consumer
    10  add a required request field                         0e     0w    1505e     0w    consumer
    11  make a required request field optional             451e     0w       0e     0w    provider
    12  redenominate total_cents in DOLLARS (same type)      0e   811w       0e  2337w    SILENT

    section 4's verdicts predicted 12/12 of these outcomes with no simulation.
    the rule that falls out, and it is the only one worth memorising:
      the side that READS the changed data must understand both shapes. BACKWARD
      compatibility lets the READER ship first; FORWARD lets the WRITER ship first.
      For a RESPONSE the reader is the consumer. For a REQUEST it is the provider.
      That single flip is the part everybody gets wrong.
    rows that never error in either order and answer wrongly in both: [12]
    no deploy-order policy reaches those. Only a value assertion does.

== 6 · THE TOLERANT READER: BREAKAGE DEFERRED, NOT AVOIDED ==
  two frozen consumers, 200 orders per release, 12 releases, each measured in
  ISOLATION. STRICT validates its slice and raises. TOLERANT ignores unknown
  fields, coerces types, lower-cases enums and defaults what is missing.

    rel  what the provider shipped                   strict rejects  tolerant wrong  tolerant raised  outcome
    r01  add promised_at                                      0/200         0/200          0       free
    r02  add discount_cents                                   0/200         0/200          0       free
    r03  total_cents sent as a string                       200/200         0/200          0       absorbed
    r04  status gains 'partially_shipped'                    29/200        29/200          0       DEFERRED
    r05  currency null for domestic orders                   86/200         0/200          0       absorbed
    r06  rename tax_cents -> tax_amount_cents                 0/200         0/200          0       free
    r07  drop shipping_cents                                  0/200         0/200          0       free
    r08  total_cents redenominated in DOLLARS                 0/200        99/200          0       INVISIBLE
    r09  created_at gains a +05:30 offset                     0/200         0/200          0       free
    r10  status upper-cased                                  94/200         0/200          0       absorbed
    r11  lines becomes {items:[...]}                        200/200         0/200          0       absorbed
    r12  rename total_cents -> amount_cents                 200/200        98/200          0       DEFERRED

    free for both consumers:                       [1, 2, 6, 7, 9]
    the tolerant reader absorbed CORRECTLY:        [3, 5, 10, 11]
    it turned an exception into a wrong number:    [4, 12]
    NEITHER consumer noticed — pure semantics:     [8]

    the strict consumer rejected data in 6 of 12 releases: loud, immediate, and
    an outage until somebody ships a fix. That is the honest cost of strictness.
    the tolerant consumer raised 0 exceptions in 12 of 12 releases and issued
    226 wrong receipts, understating what it billed by 101,132,788 minor units.
    of the 6 changes a strict reader would have rejected, tolerance handled
    4 correctly and turned 2 into silent corruption — and the 4 it handled
    are exactly the evidence that persuaded the provider the other 2 were safe.

== 7 · PROVIDER STATES, AND THE GATE THAT MAKES VERIFICATION MEAN SOMETHING ==
  a provider with no state-setup hook: 1/3 interactions verified.
      FAIL [a request for a confirmed order]  $.status: expected HTTP 200, got 404
      FAIL [a request for a cancelled order]  $.status: expected HTTP 200, got 404
  the same contract with the hook implemented: 3/3 verified, over 3 states:
      - an order ord_3Xb10p exists and is cancelled
      ...  (3 provider states in total)

  state explosion across the provider's consumer set:
    consumer      interactions   distinct states   contradiction
    receipts                 3                 3   -
    shipping                 4                 4   ord_7hQ2df: confirmed vs shipped
    analytics                2                 2   ord_7hQ2df: confirmed vs cancelled
    fraud                    3                 3   -
    4 consumers, 12 interactions, 7 distinct states, 2 contradictory pair(s).
    no single seeded fixture satisfies both 'ord_7hQ2df is confirmed' and
    'ord_7hQ2df is cancelled'. Per-state setup, not a shared database, is the fix.

  can-i-deploy: every consumer contract replayed against every provider build
    provider build                receipts@v3    shipping@v2   analytics@v1     deployable
    orders v1                        pass           pass           pass     yes
    orders v2 (rename)               FAIL           pass           pass     BLOCKED
    orders v3 (additive)             pass           pass           pass     yes
    orders v4 (stringly)             FAIL           pass           pass     BLOCKED
    the gate is not 'did my tests pass'. It is 'does every consumer version now in
    production still verify against the artifact I am about to ship' — a question
    the provider's own CI answers alone, with no shared environment anywhere.

(every number above was produced by this program on this run)
```

Four things in that output are arguments rather than demonstrations.

**Section 2's last three lines are the reason this lesson exists.** The hand-written mock suite is `4/4 GREEN` across all four provider builds, *including the two that are broken*, because a double never talks to the provider. [Test Doubles](../04-test-doubles/) measures that drift in detail; a contract is the fix, and the fix works because the artifact leaves the consumer's repository.

**Section 3's `d6` row is the argument against schema-only gating.** The one defect that only the spec diff caught was the removal of a field nobody reads. Its unique contribution was a false alarm.

**Section 4's rows 7, 8 and 9 are the review checklist.** Three changes that every engineer's intuition marks as safe, three measured breakages, and in each case the provider had only added, only removed something it no longer sent, or only relaxed a rule.

**Section 6's `tolerant raised` column is entirely zeroes.** Twelve releases, six of them structurally incompatible with a frozen consumer, and not one exception. That column is what "deferred, not avoided" looks like in a log file: nothing.

## Use It

**Pact** is the reference implementation of everything in section 2, across nine languages with a shared specification. The consumer half looks like the program's DSL because the program's DSL was written from the specification:

```python
# pip install pact-python
from pact import Consumer, Provider, Like, Term

pact = Consumer("receipts").has_pact_with(Provider("orders"), pact_dir="./pacts")

def test_confirmed_order_is_billable():
    (pact
     .given("an order ord_7hQ2df exists and is confirmed")   # the provider state
     .upon_receiving("a request for a confirmed order")
     .with_request("get", "/orders/ord_7hQ2df")
     .will_respond_with(200, body={
         "id": Like("ord_7hQ2df"),
         "status": "confirmed",                 # exact: the consumer branches on it
         "total_cents": Like(129900),           # type only
         "currency": Term(r"[A-Z]{3}", "INR"),  # pattern
     }))
    with pact:
        receipt = build_receipt(OrdersClient(pact.uri), "ord_7hQ2df")   # REAL code
        assert receipt.amount_due_cents == 129900
```

Two flags decide whether this is real. `pact_dir` must be published, not committed as a local artifact nobody reads. And the `with pact:` block **verifies that every declared interaction was exercised** — the same `3/3` check the program prints. Without it you accumulate constraints on the provider that no consumer needs.

The provider side is a verifier plus state handlers. In `pact-python`:

```bash
pact-verifier \
  --provider-base-url=http://localhost:8080 \
  --provider-states-setup-url=http://localhost:8080/_pact/provider_states \
  --pact-broker-base-url=https://broker.internal \
  --provider=orders \
  --consumer-version-selectors='{"mainBranch": true}' \
  --consumer-version-selectors='{"deployedOrReleased": true}' \
  --publish-verification-results \
  --provider-app-version=$GIT_SHA
```

`--provider-states-setup-url` is the hook from section 7 — an endpoint, enabled only in test builds, that takes a state name and builds that world. `deployedOrReleased` is the selector that matters: verify against the consumer versions actually running in production, not against every pact ever recorded.

**The Pact Broker (or PactFlow) plus `can-i-deploy` is the part that makes it real.** Everything up to here is a test; this is a gate:

```bash
pact-broker can-i-deploy \
  --pacticipant orders --version $GIT_SHA \
  --to-environment production \
  --retry-while-unknown 30 --retry-interval 10
```

It answers exactly the question section 7 measures: *given the consumer versions currently in production, is this provider build safe to deploy?* Exit non-zero blocks the deploy. `--retry-while-unknown` exists because verification is asynchronous — the consumer may not have published yet — and a gate that fails open on "unknown" is not a gate. Put it in the deploy job, after the build, before the rollout ([Deployment Strategies](../../10-infrastructure-and-deployment/11-deployment-strategies/)), and record the deploy with `pact-broker record-deployment` so the broker knows what is actually running.

**`oasdiff` / `openapi-diff`** for breaking-change detection on the spec itself. Cheap, fast, and — per section 3 — prone to alarms that break nobody:

```bash
oasdiff breaking https://api.internal/openapi.json openapi.json --fail-on ERR
oasdiff changelog old.json new.json --format markdown >> "$GITHUB_STEP_SUMMARY"
```

`--fail-on ERR` restricts the gate to genuine breaking changes; without it you fail on additions. Compare against the **published** spec, not the previous commit's file, or a PR that changes code and spec together passes trivially.

**`schemathesis`** generates requests straight from an OpenAPI document and checks the responses conform — property-based testing of an API, and the natural complement to a contract, since it explores inputs no consumer recorded (forward-referencing [Property-Based Testing & Fuzzing](../12-property-based-testing-and-fuzzing/)):

```bash
schemathesis run openapi.json --url http://localhost:8080 \
  --checks all --hypothesis-max-examples=200 --stateful=links
```

`--checks all` includes `response_schema_conformance`, which is where the bugs are. `--stateful=links` follows OpenAPI links to build sequences. Note what this does *not* do: it validates the provider against its own spec, so it cannot tell you whether the spec matches what a consumer needs.

**For events**, the Confluent Schema Registry enforces compatibility at registration. The four modes have transitive variants, and the difference is the whole game:

```bash
# check a candidate BEFORE it can be registered — this is the CI gate
curl -sf -X POST -H "Content-Type: application/vnd.schemaregistry.v1+json" \
  --data @candidate.json \
  https://registry.internal/compatibility/subjects/orders.placed-value/versions/latest \
  | jq -e '.is_compatible'

curl -X PUT --data '{"compatibility": "FULL_TRANSITIVE"}' \
  https://registry.internal/config/orders.placed-value
```

`BACKWARD` (the default) checks only against the immediately previous version. `BACKWARD_TRANSITIVE` checks against **every** version ever registered — which is what a retained log actually needs, because compatibility is not transitive and a replay reads the oldest record, not the newest. Protobuf's `reserved` keyword and Avro's mandatory `default` exist for the same reason; [Schema Evolution & Event Contracts](../../06-messaging-and-pub-sub/12-schema-evolution-and-event-contracts/) works through all six modes.

**What to actually adopt.**

**At 3 services**, do not deploy Pact. The full apparatus costs more than it saves at this size. Do three things: run `oasdiff breaking` against the published spec in CI; put the error paths into a small end-to-end suite along with one golden **value** assertion per money field (that is the `d4` control, and it is the only one); and write down which fields each consumer reads, even in a Markdown table. You are buying the *discipline* without the infrastructure.

**At 10+ services, or as soon as two teams cannot deploy independently**, adopt Pact with a broker and put `can-i-deploy` in the deploy job. The infrastructure is now cheaper than the coordination it replaces — 19 contracts against 177,147 combinations. Adopt it consumer by consumer along the edges that actually break, never as a mandate; a contract nobody wrote is worse than no contract, because the provider now believes it has coverage.

**In both cases**: keep a schema registry with `FULL_TRANSITIVE` on any retained topic from day one. Changing a topic's compatibility mode after the fact does not retroactively validate the versions already registered.

## Think about it

1. Section 3 measured the end-to-end gate catching 4 of 6 defects and the contract gate catching 3 of 6 — but the effective rates were 1.69/6 and 3/6 once the environment's 42.4% availability was applied. At what environment availability do the two become equal, and what would you have to change about your organisation (not your tooling) to get there? Is that a better investment than adopting contracts?
2. Row 12 passed every structural check in both directions and produced an answer 100× too small. You cannot write a contract assertion that catches it. Design the cheapest control that *would* have caught it within one hour of the deploy, and state precisely what it costs you when the provider makes a legitimate change to the same field.
3. The tolerant consumer absorbed 4 of 6 breaking changes correctly and corrupted 2. Suppose you keep the tolerance but add a metric that counts every coercion it performs. Which of the six would that metric have caught, which would it have missed, and what does the answer tell you about where to put observability at a service seam?
4. Rows 7 and 8 measured enum widening and enum narrowing as breaking in opposite directions. Your provider needs to both add `partially_shipped` and retire `pending`. Work out a deploy sequence that is safe at every intermediate step, and say how many separate deploys it takes.
5. Section 7 found 2 contradictory provider states across only 4 consumers. Extrapolate that to 30 consumers and describe what breaks first — the provider's test runtime, the state implementations, or something organisational. What would you change about how states are named to delay it?

## Key takeaways

- **A shared integration environment fails on combinatorics and on availability, not on effort.** At 11 services with 3 live versions each there are **177,147** whole-system combinations against **19** contracts (**9,324×**); at 30 services it is **2.06 × 10¹⁴** against **57**. And with each service breaking the environment 2% of days and taking 4 days to repair, the environment answered on **42.4% of days** with a **52-day** longest red stretch — matching the closed form `0.926¹¹ = 42.9%` exactly.
- **A contract records usage, not schema — that is why it does not obstruct the provider.** The consumer's contract constrained **4 of the provider's 11 top-level fields** with **6 matching rules** on type and pattern. A build adding **3 new fields** (11 → 14) verified **3/3** unchanged; a build renaming one *used* field failed **2 of 3** with `$.total_cents: MISSING from the provider response`.
- **The consumer's own doubles cannot detect any of this.** The same hand-written mock suite was **4/4 green** across all four provider builds, including both broken ones. A double is a second implementation of someone else's contract, written from the same reading as the code and verified by nobody.
- **Three gates, three guarantees, and none is a superset.** Over six real defects: spec diff **4/6**, contract **3/6**, end-to-end **4/6**. Only end-to-end caught the redenomination and the reordering (it asserts on values); only the contract caught the `404 → 200` error-contract change (the happy path never asks); the spec diff's only unique catch was a **false alarm** on a field no consumer reads. Weighted by environment availability, end-to-end is **1.69/6 per attempt** against the contract's **3/6, every time**.
- **Whoever reads the changed data ships first — and who that is flips with the direction.** Backward compatibility lets the reader ship first, forward lets the writer. For a response the reader is the consumer; for a request it is the provider. **9,600 round-tripped records** (12 rows × 400 × 2 directions), an independent static classifier and a 3,000-request rolling-deploy simulation agreed on **12/12 rows** and **12/12 deploys**.
- **The three changes intuition gets wrong all look permissive.** Adding an enum value is backward-compatible and broke the consumer (**318/400** forward). Removing a value you no longer emit broke the *new* reader (**296/400** backward). Relaxing a required response field to optional broke the old reader (**296/400** forward). A change is breaking when it invalidates an assumption the *other* side was entitled to make.
- **Tolerance defers breakage; it does not remove it.** Across 12 releases the tolerant consumer raised **0 exceptions in 12 of 12**, absorbed **4** changes correctly, and turned **2** into **226 wrong receipts** understating **101,132,788 minor units** — silently. The 4 it absorbed are exactly the evidence that persuaded the provider the other 2 were safe (RFC 761 §2.10, 1980; RFC 9413, 2023). Be strict about the fields you read, tolerant about everything else, and never `.get(field, default)` on a field your contract requires.
- **Provider states are where contract testing gets hard.** Without a state-setup hook the same contract verified **1 of 3** interactions and the failures said `expected HTTP 200, got 404` — a message about an empty database, not about compatibility. Four consumers already produced **7 distinct states** and **2 contradictory pairs** on the same order id, so states must be per-interaction setup functions rather than a shared fixture.
- **Contract testing is structural and stops at meaning.** `total_cents` redenominated into dollars round-tripped **400/400 in both directions**, verdict **FULL**, **0 errors in either deploy order** — and the consumer computed **1,857,277** where the provider meant **185,747,545**. Never redefine a field; put the unit in the name; and keep one value assertion somewhere, because it is the only thing that ever sees this.

Next: [Testing Async & Event-Driven Systems](../11-testing-async-and-event-driven/) — the seam where there is no response to match against, no synchronous moment at which "done" is observable, and `sleep()` is a guess about somebody else's scheduler.
