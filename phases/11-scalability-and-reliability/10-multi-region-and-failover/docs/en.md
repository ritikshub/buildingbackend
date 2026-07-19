# Multi-Region: Global Traffic, Failover & Data Gravity

> The business asks for a second region and nobody asks which region owns a write. Measured here: moving the app tier one region away from its database — same code, same queries — took p50 from **9.3 ms to 456.2 ms**, a 49x regression that no profiler will ever blame on you. Then the part that decides whether the second region was worth its bill: two identical evacuations of a dead region, differing only in whether the survivor had headroom, cost **455,000 failed requests versus 2,941,245**. A second region you have never failed over to is a second bill, not a second region.

**Type:** Build
**Languages:** Python
**Prerequisites:** [Failure Domains, Blast Radius & Shuffle Sharding](../09-failure-domains-and-shuffle-sharding/), [Read Replicas & Replication Lag](../07-read-replicas-and-replication-lag/), [Names on the Network: DNS](../../01-networking-and-protocols/06-dns-names-on-the-network/)
**Time:** ~85 minutes

## The Problem

The decision arrives in a sentence: *"we need to be multi-region for reliability."* Nobody in the
room disagrees, because nobody in the room can. It is a quarter of work. Here is how it goes.

**Week 1 — the deploy.** The team stands up the whole stack in `eu-west-1` alongside the existing
`us-east-1`. Terraform runs clean. Both regions serve traffic. There is a screenshot in the channel
and it is genuinely an achievement.

**Week 2 — p99 gets worse for everyone.** Not for the European users, for *everyone*. The app tier
moved; the database did not. Every request served from Europe now makes its six queries across the
Atlantic at **75 ms** a round trip instead of the **0.55 ms** it cost inside the region. The p50
goes from **9.3 ms to 456.2 ms** — measured below, and it is exactly `6 x 75 ms` of glass plus the
work that was always there. No code changed, no query got slower, and the flame graph shows
nothing, because the time is not being spent in your process.

**Week 5 — the write question.** Someone finally asks it: which region owns the write for a given
user? There is no answer, because the design never had one. The interim decision is "both, we'll
reconcile" — which is a decision to have conflicts and a plan to be surprised by them later.

**Week 9 — the partition.** A transit provider has a bad afternoon and the two regions cannot see
each other for two minutes. Both keep taking writes, because both are healthy and both have users.
When the link comes back, **209 entities** have been written on both sides. The database resolves
it the way most of them do — last write wins, by wall-clock timestamp — and **694 acknowledged
writes disappear**. Every one of them returned `200 OK` to somebody. There is no error, no log
line, no alert. There is a support ticket in three weeks that says "my settings reverted" and
nobody will ever connect the two.

**Month 7 — the outage.** `us-east-1` goes away. Now every unanswered question arrives in the same
minute: who promotes the database, and is it current as of *when*? Does the surviving region have
capacity for 100% of traffic when it was sized for 50%? How long until traffic actually moves?
Nobody knows, because **the failover has never been run.** The first real test is happening now, in
front of customers, at 03:00.

This is the shape of almost every multi-region project that fails. Not because multi-region is hard
in theory — because three separate goals (latency, disaster recovery, data residency) got merged
into one word, and because **the speed of light is a hard constraint on your architecture** and
nobody did the arithmetic first. Do the arithmetic first.

Do the arithmetic first. That is this lesson.

## The Concept

### The speed of light is a design constraint, not a detail

Light in a vacuum moves at 299,792 km/s. In single-mode fibre it moves slower, because glass has a
refractive index: for the fibre the internet is actually built from (ITU-T G.652, group index
~1.468 at 1550 nm), the signal travels at **204,190 km/s** — about two-thirds of *c*.

That gives you a floor nobody can sell you a way around:

```text
minimum RTT = 2 x great-circle distance / 204,190 km/s
```

New York to London is 5,570 km, so one way is **27.3 ms** and a round trip **54.6 ms**, at best,
forever, assuming a perfectly straight piece of glass that does not exist. The fastest commercial
transatlantic route sells **58.95 ms** — **1.08x** the physical floor. That number is the entire
competitive advantage of a cable that cost hundreds of millions to lay, and it exists because the
only way to go faster is to make the cable *shorter*.

Real routes are not straight, so measured RTT runs **1.23x to 1.81x** the floor once you add
routing, switching, regeneration and fibre that follows the seabed. Here is the table the Build It
computes, and the budget it has to fit inside:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 436" width="100%" style="max-width:840px" role="img" aria-label="A schematic region map with arcs annotated by the minimum round-trip time physics allows in fibre and the typical measured round-trip time: Oregon to Virginia 34 versus 62 milliseconds, Virginia to Dublin 53 versus 75, Dublin to Singapore 110 versus 175, and Virginia to Sydney 154 versus 200. Below, a two hundred millisecond user budget bar is divided into forty milliseconds of server work and two seventy-five millisecond cross-region round trips, leaving ten milliseconds spare, so a third round trip overflows the budget."> <g font-family="'JetBrains Mono', ui-monospace, monospace"> <text x="440" y="26" text-anchor="middle" font-size="14.5" font-weight="700" fill="currentColor">Physics sets the floor. Every cross-region hop spends 37% of a 200 ms budget.</text> <g fill="none" stroke="#7f7f7f" stroke-width="1.8" opacity="0.85"> <path d="M187 114 Q 231 74 276 122"/> <path d="M276 122 Q 351 58 427 105"/> <path d="M427 105 Q 543 76 659 168"/> <path d="M276 122 Q 520 300 759 211"/> </g> <g fill="#7c5cff" fill-opacity="0.22" stroke="#7c5cff" stroke-width="2"> <circle cx="187" cy="114" r="7"/><circle cx="276" cy="122" r="7"/><circle cx="342" cy="199" r="7"/> <circle cx="427" cy="105" r="7"/><circle cx="735" cy="126" r="7"/><circle cx="659" cy="168" r="7"/> <circle cx="759" cy="211" r="7"/> </g> <g fill="currentColor" font-size="9" text-anchor="middle" opacity="0.92">
<text x="187" y="136">us-west-2</text> <text x="264" y="146">us-east-1</text> <text x="342" y="221">sa-east-1</text> <text x="427" y="92">eu-west-1</text> <text x="735" y="112">ap-northeast-1</text> <text x="659" y="190">ap-southeast-1</text> <text x="759" y="233">ap-southeast-2</text> </g> <g fill="currentColor" font-size="7.5" text-anchor="middle" opacity="0.6"> <text x="187" y="147">Oregon</text> <text x="264" y="157">Virginia</text> <text x="342" y="232">Sao Paulo</text> <text x="427" y="82">Dublin</text> <text x="735" y="102">Tokyo</text> <text x="659" y="201">Singapore</text> <text x="759" y="244">Sydney</text> </g> <g text-anchor="middle" font-size="9.5" font-weight="700"> <text x="231" y="66"><tspan fill="#0fa07f">34</tspan><tspan fill="currentColor" opacity="0.55"> min / </tspan><tspan fill="#e0930f">62 real</tspan></text> <text x="351" y="52"><tspan fill="#0fa07f">53</tspan><tspan fill="currentColor" opacity="0.55"> min / </tspan><tspan fill="#e0930f">75 real</tspan></text> <text x="551" y="86"><tspan fill="#0fa07f">110</tspan><tspan fill="currentColor" opacity="0.55"> min / </tspan><tspan fill="#e0930f">175 real</tspan></text> <text x="520" y="266"><tspan fill="#0fa07f">154 </tspan><tspan fill="currentColor" opacity="0.55"> min / </tspan><tspan fill="#e0930f">200 real</tspan></text> </g> <g font-size="9"> <rect x="60" y="176" width="196" height="46" rx="7" fill="#7f7f7f" fill-opacity="0.07" stroke="currentColor" stroke-opacity="0.3" stroke-width="1.2"/> <text x="72" y="192" fill="#0fa07f" font-weight="700">green = minimum in fibre
</text> <text x="72" y="205" fill="currentColor" opacity="0.75">2 x great-circle / 204,190 km/s</text> <text x="72" y="217" fill="#e0930f" font-weight="700">amber = typical measured RTT</text> </g> <text x="440" y="292" text-anchor="middle" font-size="12" font-weight="700" fill="currentColor">how a 200 ms user-facing budget is actually spent</text> <g stroke-width="2"> <rect x="90" y="304" width="144" height="34" rx="4" fill="#0fa07f" fill-opacity="0.16" stroke="#0fa07f"/> <rect x="234" y="304" width="270" height="34" rx="4" fill="#e0930f" fill-opacity="0.16" stroke="#e0930f"/> <rect x="504" y="304" width="270" height="34" rx="4" fill="#e0930f" fill-opacity="0.16" stroke="#e0930f"/> <rect x="774" y="304" width="36" height="34" rx="4" fill="#7f7f7f" fill-opacity="0.12" stroke="currentColor" stroke-opacity="0.4"/> </g> <rect x="810" y="304" width="60" height="34" rx="4" fill="#d64545" fill-opacity="0.14" stroke="#d64545" stroke-width="2" stroke-dasharray="5 4"/> <path d="M810 296 L 810 348" fill="none" stroke="#d64545" stroke-width="2.2"/> <g fill="currentColor" text-anchor="middle" font-size="9.5"> <text x="162" y="320" font-weight="700" fill="#0fa07f">server</text> <text x="162" y="332" opacity="0.85">40 ms</text> <text x="369" y="320" font-weight="700" fill="#e0930f">cross-region RTT 1</text> <text x="369" y="332" opacity="0.85">75 ms</text> <text x="639" y="320" font-weight="700" fill="#e0930f">cross-region RTT 2</text> <text x="639" y="332" opacity="0.85">75 ms</text> <text x="792" y="326" font-size="8" opacity="0.8">10 ms
</text> <text x="840" y="320" font-size="8.5" font-weight="700" fill="#d64545">RTT 3 </text> <text x="840" y="332" font-size="8" fill="#d64545">blown</text> </g> <g fill="currentColor" font-size="8.5" opacity="0.7" text-anchor="middle"> <text x="90" y="352">0</text><text x="234" y="352">40</text><text x="504" y="352">115</text> <text x="774" y="352">190</text><text x="812" y="366" font-weight="700" fill="#d64545">200 ms budget</text> </g> <text x="440" y="386" text-anchor="middle" font-size="10.5" fill="currentColor" opacity="0.95">You can afford 2 sequential cross-region round trips per request. Design for 1.</text> <text x="440" y="416" text-anchor="middle" font-size="11" fill="currentColor" opacity="0.9">The fastest transatlantic cable sells 58.95 ms RTT against a 54.6 ms physical floor. Nobody sells less.</text> </g> </svg>
```

Now put that against a user-facing budget. Two hundred milliseconds is a reasonable target for an
interactive request. Subtract 40 ms of server work and 160 ms remain, which buys **two**
transatlantic round trips with 10 ms to spare; a third blows the budget by 65 ms:

> **You get very few cross-region round trips per request — often zero. Two is the ceiling.
> Design for one.**

Notice how brutally the scale changes. A same-rack round trip is **0.10 ms** — 0.1% of your budget,
free. Cross-AZ (AZ = Availability Zone, an isolated datacenter within a region) is **0.55 ms**,
0.3%, still effectively free, which is why multi-AZ designs never think about this. Cross-region
transatlantic is **75 ms — 37.5% of the entire budget in one hop.** There is no gradual
degradation: you step off a cliff between "same region" and "different region", and every decision
that follows is downstream of that step.

### Three reasons to go multi-region, three different architectures

This is where most projects go wrong, in the first meeting. "Multi-region" names three unrelated
goals needing three different designs, and conflating them produces a system that achieves none.

**1. Latency — serve users from somewhere near them.** *Reads* must happen close to the user.
Writes can still be remote — users expect a "Save" to take a moment, not a page. This needs
replicas near users and does *not* need every region to be writable.

**2. Availability and disaster recovery — survive losing a region.** The data must *already* be
replicated elsewhere and the capacity *already* provisioned there. Note what this does not require:
the second region need not be near anybody. It requires that failover has been tested, which is
where these projects actually die.

**3. Data residency and compliance — certain data must physically stay in a jurisdiction.** EU
users' personal data stays in the EU; Indian payment data stays in India. This is not replication
at all — it is **partitioning by region**, a fundamentally different shape. The data must *not* be
everywhere.

And here is the uncomfortable interaction: **goal 3 actively conflicts with goals 1 and 2.** If EU
data may not leave the EU, you cannot replicate it to `us-east-1` for disaster recovery, so your EU
DR story must live inside the EU and your global cache cannot hold it. Teams discover this after
building the replication topology. Write down which of the three you are buying, in one sentence,
before anyone opens Terraform. If the answer is "all three", you have three projects.

Write down which of the three you are actually buying, in one sentence, before anyone opens
Terraform. If the answer is "all three", you have three projects.

### The topologies

Four arrangements, in increasing order of what they let you do and how much they can hurt you. The
Build It simulates all four for a year:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 544" width="100%" style="max-width:840px" role="img" aria-label="Four multi-region topologies drawn side by side with their read path, write path and failure behaviour: active-passive with an idle standby and a 34 minute recovery time objective, active-active with a single write region where every write crosses the ocean, regional data ownership where each region owns its own users entities and both reads and writes stay local, and full multi-master which is the only one that produces write conflicts. Measured p99 read and write latencies and yearly availability are printed on each panel."> <defs><marker id="p11-10-a1" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L6.5,3 L0,6 Z" fill="currentColor"/></marker><marker id="p11-10-a2" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L6.5,3 L0,6 Z" fill="#e0930f"/></marker><marker id="p11-10-a3" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L6.5,3 L0,6 Z" fill="#0fa07f"/></marker> </defs> <text x="440" y="26" text-anchor="middle" font-size="14.5" font-weight="700" fill="currentColor">Four topologies, one simulated year. Only the third is boring on every axis.</text> <g font-family="'JetBrains Mono', ui-monospace, monospace"> <rect x="14" y="46" width="424" height="216" rx="12" fill="#7f7f7f" fill-opacity="0.05" stroke="currentColor" stroke-opacity="0.32" stroke-width="1.3"/><text x="28" y="69" font-size="12" font-weight="700" fill="currentColor">1 . ACTIVE-PASSIVE (warm standby)
</text><text x="28" y="84" font-size="8.5" fill="currentColor" opacity="0.85">p99 read 93.6 ms . p99 write 101.2 ms . RTO 34 min</text><text x="28" y="96" font-size="8.5" fill="currentColor" opacity="0.85">avail 99.971% . cost 2.0x . 50% of the spend serves nobody </text><rect x="46" y="112" width="116" height="46" rx="8" fill="#0fa07f" fill-opacity="0.12" stroke="#0fa07f" stroke-width="2"/><rect x="290" y="112" width="116" height="46" rx="8" fill="#7f7f7f" fill-opacity="0.10" stroke="currentColor" stroke-width="2" stroke-dasharray="6 4"/><text x="104" y="132" font-size="10" font-weight="700" text-anchor="middle" fill="#0fa07f">REGION A</text><text x="104" y="147" font-size="8" text-anchor="middle" fill="currentColor" opacity="0.85">primary: all reads + writes</text><text x="348" y="132" font-size="10" font-weight="700" text-anchor="middle" fill="currentColor">REGION B </text><text x="348" y="147" font-size="8" text-anchor="middle" fill="currentColor" opacity="0.85">standby: idle until the day</text><rect x="56" y="202" width="96" height="26" rx="7" fill="#3553ff" fill-opacity="0.10" stroke="#3553ff" stroke-width="1.6"/><text x="104" y="219" font-size="8.5" text-anchor="middle" fill="#3553ff" font-weight="700">users near A</text><rect x="300" y="202" width="96" height="26" rx="7" fill="#3553ff" fill-opacity="0.10" stroke="#3553ff" stroke-width="1.6"/><text x="348" y="219" font-size="8.5" text-anchor="middle" fill="#3553ff" font-weight="700">users near B </text><path d="M166 126 L 286 126" fill="none" stroke="#0fa07f" stroke-width="1.7" marker-end="url(#p11-10-a3)"/>
<text x="226.0" y="120" font-size="7.5" text-anchor="middle" fill="#0fa07f" font-weight="700">async replication</text><path d="M104 202 L 104 164" fill="none" stroke="#0fa07f" stroke-width="2" marker-end="url(#p11-10-a1)"/><text x="112" y="188" font-size="8.5" fill="#0fa07f" font-weight="700">R W</text><path d="M300 215 L 232 215 L 232 176 L 136 176 L 136 164" fill="none" stroke="#e0930f" stroke-width="2" marker-end="url(#p11-10-a2)"/><text x="238" y="198" font-size="8" fill="#e0930f" font-weight="700">+75 ms on EVERY request </text><text x="28" y="249" font-size="8.5" font-weight="700" fill="#d64545">A dies -&gt; everything stops until a human promotes B. 34 min RTO.</text> <rect x="446" y="46" width="424" height="216" rx="12" fill="#7f7f7f" fill-opacity="0.05" stroke="currentColor" stroke-opacity="0.32" stroke-width="1.3"/><text x="460" y="69" font-size="12" font-weight="700" fill="currentColor">2 . ACTIVE-ACTIVE, ONE WRITE REGION</text><text x="460" y="84" font-size="8.5" fill="currentColor" opacity="0.85">p99 read 19.6 ms . p99 write 100.6 ms . RTO 12 min</text><text x="460" y="96" font-size="8.5" fill="currentColor" opacity="0.85">avail 99.989% . cost 2.0x . reads local, writes global </text><rect x="478" y="112" width="116" height="46" rx="8" fill="#0fa07f" fill-opacity="0.12" stroke="#0fa07f" stroke-width="2"/><rect x="722" y="112" width="116" height="46" rx="8" fill="#0fa07f" fill-opacity="0.10" stroke="#0fa07f" stroke-width="2"/><text x="536" y="132" font-size="10" font-weight="700" text-anchor="middle" fill="#0fa07f">REGION A
</text><text x="536" y="147" font-size="8" text-anchor="middle" fill="currentColor" opacity="0.85">the only writer</text><text x="780" y="132" font-size="10" font-weight="700" text-anchor="middle" fill="#0fa07f">REGION B </text><text x="780" y="147" font-size="8" text-anchor="middle" fill="currentColor" opacity="0.85">read replica</text><rect x="488" y="202" width="96" height="26" rx="7" fill="#3553ff" fill-opacity="0.10" stroke="#3553ff" stroke-width="1.6"/><text x="536" y="219" font-size="8.5" text-anchor="middle" fill="#3553ff" font-weight="700">users near A</text><rect x="732" y="202" width="96" height="26" rx="7" fill="#3553ff" fill-opacity="0.10" stroke="#3553ff" stroke-width="1.6"/><text x="780" y="219" font-size="8.5" text-anchor="middle" fill="#3553ff" font-weight="700">users near B </text><path d="M598 126 L 718 126" fill="none" stroke="#0fa07f" stroke-width="1.7" marker-end="url(#p11-10-a3)"/><text x="658.0" y="120" font-size="7.5" text-anchor="middle" fill="#0fa07f" font-weight="700">async replication</text><path d="M536 202 L 536 164" fill="none" stroke="#0fa07f" stroke-width="2" marker-end="url(#p11-10-a1)"/><text x="544" y="188" font-size="8.5" fill="#0fa07f" font-weight="700">R W</text><path d="M780 202 L 780 164" fill="none" stroke="#0fa07f" stroke-width="2" marker-end="url(#p11-10-a1)"/><text x="788" y="188" font-size="8.5" fill="#0fa07f" font-weight="700">R </text><path d="M732 215 L 664 215 L 664 176 L 568 176 L 568 164" fill="none" stroke="#e0930f" stroke-width="2" marker-end="url(#p11-10-a2)"/>
<text x="670" y="198" font-size="8" fill="#e0930f" font-weight="700">W +75 ms</text><text x="460" y="249" font-size="8.5" font-weight="700" fill="#d64545">A dies -&gt; reads survive; EVERY write fails until B is promoted.</text> <rect x="14" y="274" width="424" height="216" rx="12" fill="#7f7f7f" fill-opacity="0.05" stroke="currentColor" stroke-opacity="0.32" stroke-width="1.3"/><text x="28" y="297" font-size="12" font-weight="700" fill="currentColor">3 . REGIONAL DATA OWNERSHIP (home-region pinning) </text><text x="28" y="312" font-size="8.5" fill="currentColor" opacity="0.85">p99 read 19.6 ms . p99 write 95.6 ms . RTO 9 min</text><text x="28" y="324" font-size="8.5" fill="currentColor" opacity="0.85">avail 99.993% . cost 2.0x . 91.6% of writes never leave home</text><rect x="46" y="340" width="116" height="46" rx="8" fill="#0fa07f" fill-opacity="0.12" stroke="#0fa07f" stroke-width="2"/><rect x="290" y="340" width="116" height="46" rx="8" fill="#0fa07f" fill-opacity="0.10" stroke="#0fa07f" stroke-width="2"/><text x="104" y="360" font-size="10" font-weight="700" text-anchor="middle" fill="#0fa07f">REGION A </text><text x="104" y="375" font-size="8" text-anchor="middle" fill="currentColor" opacity="0.85">owns A-homed entities</text><text x="348" y="360" font-size="10" font-weight="700" text-anchor="middle" fill="#0fa07f">REGION B</text><text x="348" y="375" font-size="8" text-anchor="middle" fill="currentColor" opacity="0.85">owns B-homed entities</text><rect x="56" y="430" width="96" height="26" rx="7" fill="#3553ff" fill-opacity="0.10" stroke="#3553ff" stroke-width="1.6"/>
<text x="104" y="447" font-size="8.5" text-anchor="middle" fill="#3553ff" font-weight="700">users near A </text><rect x="300" y="430" width="96" height="26" rx="7" fill="#3553ff" fill-opacity="0.10" stroke="#3553ff" stroke-width="1.6"/><text x="348" y="447" font-size="8.5" text-anchor="middle" fill="#3553ff" font-weight="700">users near B</text><path d="M166 350 L 286 350" fill="none" stroke="#0fa07f" stroke-width="1.7" marker-end="url(#p11-10-a3)"/><text x="226.0" y="344" font-size="7.5" text-anchor="middle" fill="#0fa07f" font-weight="700">read-only copies</text><path d="M286 376 L 166 376" fill="none" stroke="#e0930f" stroke-width="1.7" stroke-dasharray="5 4" marker-end="url(#p11-10-a2)"/> <text x="226.0" y="389" font-size="7.5" text-anchor="middle" fill="#e0930f" font-weight="700">8.4% strays +75 ms</text><path d="M104 430 L 104 392" fill="none" stroke="#0fa07f" stroke-width="2" marker-end="url(#p11-10-a1)"/><text x="112" y="416" font-size="8.5" fill="#0fa07f" font-weight="700">R W</text><path d="M348 430 L 348 392" fill="none" stroke="#0fa07f" stroke-width="2" marker-end="url(#p11-10-a1)"/><text x="356" y="416" font-size="8.5" fill="#0fa07f" font-weight="700">R W</text><text x="28" y="477" font-size="8.5" font-weight="700" fill="#d64545">A dies -&gt; only A-homed entities stall. B keeps reading AND writing. </text> <rect x="446" y="274" width="424" height="216" rx="12" fill="#7f7f7f" fill-opacity="0.05" stroke="currentColor" stroke-opacity="0.32" stroke-width="1.3"/><text x="460" y="297" font-size="12" font-weight="700" fill="currentColor">4 . FULL MULTI-MASTER
</text><text x="460" y="312" font-size="8.5" fill="currentColor" opacity="0.85">p99 read 19.5 ms . p99 write 28.7 ms . RTO 6 min</text><text x="460" y="324" font-size="8.5" fill="currentColor" opacity="0.85">avail 99.995% . cost 2.0x . and then there are the conflicts</text><rect x="478" y="340" width="116" height="46" rx="8" fill="#0fa07f" fill-opacity="0.12" stroke="#0fa07f" stroke-width="2"/> <rect x="722" y="340" width="116" height="46" rx="8" fill="#0fa07f" fill-opacity="0.10" stroke="#0fa07f" stroke-width="2"/><text x="536" y="360" font-size="10" font-weight="700" text-anchor="middle" fill="#0fa07f">REGION A</text><text x="536" y="375" font-size="8" text-anchor="middle" fill="currentColor" opacity="0.85">accepts ALL writes</text><text x="780" y="360" font-size="10" font-weight="700" text-anchor="middle" fill="#0fa07f">REGION B</text><text x="780" y="375" font-size="8" text-anchor="middle" fill="currentColor" opacity="0.85">accepts ALL writes </text><rect x="488" y="430" width="96" height="26" rx="7" fill="#3553ff" fill-opacity="0.10" stroke="#3553ff" stroke-width="1.6"/><text x="536" y="447" font-size="8.5" text-anchor="middle" fill="#3553ff" font-weight="700">users near A</text><rect x="732" y="430" width="96" height="26" rx="7" fill="#3553ff" fill-opacity="0.10" stroke="#3553ff" stroke-width="1.6"/><text x="780" y="447" font-size="8.5" text-anchor="middle" fill="#3553ff" font-weight="700">users near B</text><path d="M598 352 L 718 352" fill="none" stroke="#0fa07f" stroke-width="1.7" marker-end="url(#p11-10-a3)"/>
<text x="620.0" y="345" font-size="7.5" text-anchor="middle" fill="#0fa07f" font-weight="700">replicate</text><path d="M718 376 L 598 376" fill="none" stroke="#0fa07f" stroke-width="1.7" marker-end="url(#p11-10-a3)"/><text x="696.0" y="389" font-size="7.5" text-anchor="middle" fill="#0fa07f" font-weight="700">replicate</text><path d="M536 430 L 536 392" fill="none" stroke="#0fa07f" stroke-width="2" marker-end="url(#p11-10-a1)"/><text x="544" y="416" font-size="8.5" fill="#0fa07f" font-weight="700">R W</text><path d="M780 430 L 780 392" fill="none" stroke="#0fa07f" stroke-width="2" marker-end="url(#p11-10-a1)"/> <text x="788" y="416" font-size="8.5" fill="#0fa07f" font-weight="700">R W</text><text x="460" y="477" font-size="8.5" font-weight="700" fill="#d64545">partition -&gt; 209 entities diverge; LWW discards 694 acked writes.</text><path d="M658 336 L 658 392" fill="none" stroke="#d64545" stroke-width="3" stroke-dasharray="7 5"/><text x="658" y="406" font-size="8.5" text-anchor="middle" fill="#d64545" font-weight="700">PARTITION</text> <g stroke="#d64545" stroke-width="2.2" opacity="0.6"><path d="M52 118 L 156 152"/><path d="M156 118 L 52 152"/> </g> <g stroke="#d64545" stroke-width="2.2" opacity="0.6"><path d="M484 118 L 588 152"/><path d="M588 118 L 484 152"/> </g> <g stroke="#d64545" stroke-width="2.2" opacity="0.6"><path d="M52 346 L 156 380"/><path d="M156 346 L 52 380"/> </g> <text x="440" y="522" text-anchor="middle" font-size="11" fill="currentColor" opacity="0.9">All four cost the same 2.0x compute. What differs is who pays the 75 ms, and what breaks when a region does.
</text> </g> </svg>
```

**Active-passive (warm standby).** One region serves everything; the other holds a replica and
waits. The failure mode is at least honest: if the primary dies, everything stops until someone
promotes the standby. Measured: **p99 read 93.6 ms** (45% of users cross an ocean for every
request), **RTO 34 minutes**, **availability 99.971%**, cost **2.0x** — and **half that spend
serves nobody.** You pay for two regions and get the serving capacity of one, and the day you find
out whether it works is the day you need it.

**Active-active with a single write region.** Both regions serve reads locally; all writes go to
one designated writer. Reads get dramatically better — **p99 19.6 ms**, a **4.8x** improvement.
Writes do not: **p99 100.6 ms**, because 45% of writes still cross the Atlantic. Availability
**99.989%**. A good, common, defensible design whose honest weakness is that a write-region failure
takes down 100% of writes globally, not 45%.

**Active-active with regional data ownership.** Every entity has a **home region** — the region its
owner lives in — and only that region may write it. Reads are local (**19.6 ms**); writes are local
for the 91.6% that arrive at their home region (**p99 95.6 ms**, **p50 17.6 ms**) and the remainder
is forwarded. Availability **99.993%**, RTO **9 minutes**, because a failure only requires
promoting *that region's* shards. **This is the sweet spot**, and the rest of the lesson is largely
an argument for it.

**Full multi-master.** Every region accepts every write. The latency numbers are the best of the
four — **p99 write 28.7 ms**, availability **99.995%** — which is exactly why it is tempting. It is
also the only one that can produce **write conflicts**, and that cost appears in no latency table.
Choose it when your data types genuinely converge (counters, sets, presence, collaborative text),
not because the availability column looked good.

One measured result deserves its own line, because it is not the one people expect:

> **All four cost the same 2.0x compute.** To survive losing 1 of 2 regions, each region must
> be able to hold 100% of demand. That is not a property of the topology; it is arithmetic.
> What differs is whether the second region's capacity *does anything* on the other 364 days.

### RTO and RPO are numbers you design to

Two acronyms, and they are the entire vocabulary of a failover conversation:

- **RTO — Recovery Time Objective.** How long until service is restored. Measured in minutes.
- **RPO — Recovery Point Objective.** How much data you accept losing. Measured in *seconds of
  writes*, not in minutes of downtime.

RPO is the one people get wrong, because they pick it instead of measuring it. **Your RPO is your
replication lag** (Lesson 7 built this) — specifically its *tail*, because a region does not
politely fail at the median. The Build It measures async cross-region replication over 30,000
samples, including a window where a bulk job saturates the replication stream:

```text
     p50       p95       p99       max
    84ms     0.37s     7.30s     9.10s
```

Quote the **p99: 7.30 s**. At any instant, 7.30 seconds of acknowledged writes exist only in the
primary; lose the region now and they are gone. The median of 84 ms is the number that goes in the
slide and the number that is wrong.

Now the cost curve. An RPO of seconds is nearly free — it is what async replication already gives
you. An RPO of **zero** requires the write to be durable in both regions *before* you acknowledge
it: a synchronous cross-region commit, which puts a full cross-region round trip inside your commit
path:

```text
RPO target  mechanism                           p50 write  p99 write
seconds     async streaming replication            17.6ms     95.6ms
zero        synchronous cross-region commit        92.4ms    103.7ms
```

**RPO = 0 costs 75 ms on every write, forever** — including the 364 days a year when nothing fails.
That is one cross-region round trip, exactly as the light-speed arithmetic predicted, and it is the
price of the guarantee. Sometimes worth it (a payment ledger); usually not (a user profile), and
the right answer is an RPO of a few seconds plus the honesty to say so out loud.

One more measured result worth internalising, from the topology table:

> **RPO was identical — 7.30 s — for all four topologies.** RPO is a property of the
> *replication mechanism*, not of the topology. Changing your topology does not change how
> much data you lose. Only changing your replication does.

### Global traffic management: how a user reaches a region at all

You have two regions. A user types your hostname. Something must decide which region they land on
and — much harder — must *change its mind* when one dies. Three mechanisms, three failure modes.

**GeoDNS / latency-based DNS routing.** The authoritative nameserver returns a different address
depending on where the query came from. It is cheap, protocol-agnostic, and has one enormous flaw:
**DNS is a caching system and you do not control the caches.** Lesson 5 met this when DNS-based
discovery could not drain an instance promptly; at global scale it is worse, because the caches
belong to other people's resolvers and other people's runtimes.

RFC 2181 §8 is precise: the TTL (Time To Live) is an **upper bound** on how long a record may be
cached, and nothing obliges anyone to be honest about the lower bound. In practice many public and
ISP resolvers enforce a minimum TTL floor; HTTP clients and connection pools cache a resolved
address for the life of a pool; and the JVM's default `networkaddress.cache.ttl` of `-1` caches a
successful lookup **forever**. The Build It models 200,000 clients across those populations and
measures what happens after a health-check-driven failover on a 60-second record:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 448" width="100%" style="max-width:840px" role="img" aria-label="Measured fraction of client traffic still resolving to a dead region over a logarithmic time axis after a DNS failover on a sixty second record. Both curves sit at one hundred percent through the thirty five second detection window. The DNS curve then falls to 72.17 percent at one minute, 17.01 percent at five minutes, 11.01 percent at fifteen minutes and is still 5.24 percent at one hour, never reaching one percent within twenty four hours. The anycast curve drops to zero within two seconds because the BGP session dies with the region."> <defs><marker id="p11-10-a5" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L6.5,3 L0,6 Z" fill="currentColor"/></marker> </defs> <g font-family="'JetBrains Mono', ui-monospace, monospace"> <text x="440" y="26" text-anchor="middle" font-size="14.5" font-weight="700" fill="currentColor">A 60-second TTL is a request. One hour later, 5.24% of clients are still calling the dead region.</text> <path d="M116 306.0 L 836 306.0" fill="none" stroke="currentColor" stroke-width="1" opacity="0.5"/> <text x="108" y="309.5" font-size="8.5" text-anchor="end" fill="currentColor" opacity="0.7">0%</text> <path d="M116 283.6 L 836 283.6" fill="none" stroke="currentColor" stroke-width="1" opacity="0.16"/> <text x="108" y="287.1" font-size="8.5" text-anchor="end" fill="currentColor" opacity="0.7">10%</text> <path d="M116 250.0 L 836 250.0" fill="none" stroke="currentColor" stroke-width="1" opacity="0.16"/>
<text x="108" y="253.5" font-size="8.5" text-anchor="end" fill="currentColor" opacity="0.7">25%</text> <path d="M116 194.0 L 836 194.0" fill="none" stroke="currentColor" stroke-width="1" opacity="0.16"/> <text x="108" y="197.5" font-size="8.5" text-anchor="end" fill="currentColor" opacity="0.7">50%</text> <path d="M116 138.0 L 836 138.0" fill="none" stroke="currentColor" stroke-width="1" opacity="0.16"/> <text x="108" y="141.5" font-size="8.5" text-anchor="end" fill="currentColor" opacity="0.7">75%</text> <path d="M116 82.0 L 836 82.0" fill="none" stroke="currentColor" stroke-width="1" opacity="0.16"/> <text x="108" y="85.5" font-size="8.5" text-anchor="end" fill="currentColor" opacity="0.7">100%</text> <path d="M116.0 306 L 116.0 312" fill="none" stroke="currentColor" stroke-width="1.1" opacity="0.5"/> <text x="116.0" y="325" font-size="8.5" text-anchor="middle" fill="currentColor" opacity="0.7">10s</text> <path d="M269.2 306 L 269.2 312" fill="none" stroke="currentColor" stroke-width="1.1" opacity="0.5"/> <text x="269.2" y="325" font-size="8.5" text-anchor="middle" fill="currentColor" opacity="0.7">35s</text> <path d="M335.2 306 L 335.2 312" fill="none" stroke="currentColor" stroke-width="1.1" opacity="0.5"/> <text x="335.2" y="325" font-size="8.5" text-anchor="middle" fill="currentColor" opacity="0.7">1min</text> <path d="M532.0 306 L 532.0 312" fill="none" stroke="currentColor" stroke-width="1.1" opacity="0.5"/> <text x="532.0" y="325" font-size="8.5" text-anchor="middle" fill="currentColor" opacity="0.7">5min
</text> <path d="M666.4 306 L 666.4 312" fill="none" stroke="currentColor" stroke-width="1.1" opacity="0.5"/> <text x="666.4" y="325" font-size="8.5" text-anchor="middle" fill="currentColor" opacity="0.7">15min</text> <path d="M751.2 306 L 751.2 312" fill="none" stroke="currentColor" stroke-width="1.1" opacity="0.5"/> <text x="751.2" y="325" font-size="8.5" text-anchor="middle" fill="currentColor" opacity="0.7">30min</text> <path d="M836.0 306 L 836.0 312" fill="none" stroke="currentColor" stroke-width="1.1" opacity="0.5"/> <text x="836.0" y="325" font-size="8.5" text-anchor="middle" fill="currentColor" opacity="0.7">1h</text> <path d="M116 76 L 116 306" fill="none" stroke="currentColor" stroke-width="1.3" opacity="0.5"/> <text x="476" y="342" font-size="9.5" text-anchor="middle" fill="currentColor" opacity="0.8">time since the region died (log scale)</text> <text x="30" y="194" font-size="9.5" text-anchor="middle" fill="currentColor" opacity="0.8" transform="rotate(-90 30 194)">traffic aimed at the DEAD region</text> <rect x="116" y="82" width="153.2" height="224" fill="#e0930f" fill-opacity="0.10"/> <text x="192.6" y="74" font-size="8.5" text-anchor="middle" fill="#e0930f" font-weight="700">35 s detection</text> <path d="M116.0 82.0 L 200.8 82.0 L 269.2 82.0 L 285.6 94.5 L 300.0 106.9 L 312.9 119.4 L 324.5 131.8 L 335.2 144.3 L 354.0 169.2 L 370.4 194.1 L 391.4 231.5 L 409.3 234.2 L 429.7 237.7 L 455.1 243.0 L 482.4 250.1 L 504.7 257.2 L 532.0 267.8 L 561.0 274.6 L 589.5 275.9 L 616.8 277.5 L 645.7 279.6 L 666.4 281.4 L 691.0 284.0 L 720.5 287.8 L 744.2 291.7 L 753.6 293.5 L 770.1 293.6 L 796.2 293.8 L 817.7 294.0 L 836.0 294.3" fill="none" stroke="#d64545" stroke-width="2.8" stroke-linejoin="round"/>
<path d="M116 82.0 L 269.2 82.0 L 269.2 305.1 L 836 305.1" fill="none" stroke="#0fa07f" stroke-width="2.8" stroke-linejoin="round"/> <circle cx="335.2" cy="144.3" r="4.6" fill="#d64545" fill-opacity="0.4" stroke="#d64545" stroke-width="1.8"/> <text x="326.2" y="132.3" font-size="9.5" text-anchor="end" fill="#d64545" font-weight="700">72.17%</text> <circle cx="532.0" cy="267.9" r="4.6" fill="#d64545" fill-opacity="0.4" stroke="#d64545" stroke-width="1.8"/> <text x="532.0" y="255.9" font-size="9.5" text-anchor="middle" fill="#d64545" font-weight="700">17.01% </text> <circle cx="666.4" cy="281.3" r="4.6" fill="#d64545" fill-opacity="0.4" stroke="#d64545" stroke-width="1.8"/> <text x="666.4" y="269.3" font-size="9.5" text-anchor="middle" fill="#d64545" font-weight="700">11.01%</text> <circle cx="836.0" cy="294.3" r="4.6" fill="#d64545" fill-opacity="0.4" stroke="#d64545" stroke-width="1.8"/> <text x="827.0" y="280.3" font-size="9.5" text-anchor="end" fill="#d64545" font-weight="700">5.24%</text> <circle cx="269.2" cy="305.1" r="4.6" fill="#0fa07f" fill-opacity="0.4" stroke="#0fa07f" stroke-width="1.8"/> <text x="307.9" y="296.1" font-size="9.5" fill="#0fa07f" font-weight="700">anycast: ~0% within 2 s of the BGP session dropping </text> <rect x="546" y="108" width="300" height="72" rx="8" fill="#7f7f7f" fill-opacity="0.07" stroke="currentColor" stroke-opacity="0.3" stroke-width="1.2"/> <text x="560" y="127" font-size="9" font-weight="700" fill="currentColor">who is still holding the old answer
</text> <text x="560" y="142" font-size="8" fill="currentColor" opacity="0.75">62% resolver honours the 60 s TTL</text> <text x="560" y="153" font-size="8" fill="currentColor" opacity="0.75">22% resolver enforces a 300 s floor</text> <text x="560" y="164" font-size="8" fill="currentColor" opacity="0.75">10% HTTP client caches 30 min · 5% JVM forever </text> <text x="560" y="175" font-size="8" fill="#d64545" opacity="0.95">1% IP hard-coded — never re-resolves</text> <rect x="18" y="356" width="844" height="48" rx="9" fill="#d64545" fill-opacity="0.07" stroke="#d64545" stroke-opacity="0.5" stroke-width="1.2"/> <text x="34" y="374" font-size="9.5" font-weight="700" fill="#d64545">measured: 1.4 min to fall below 50% · 18.0 min below 10% · 81.3 min below 5% · below 1%: never, within 24 hours</text> <text x="34" y="392" font-size="9.5" fill="currentColor" opacity="0.9">RFC 2181 s8: the TTL is an upper bound on caching. Nothing obliges a resolver, a runtime or a config file to be honest about the lower one. </text> <text x="440" y="428" text-anchor="middle" font-size="11" fill="currentColor" opacity="0.9">Plan the evacuation around the tail you measured, not the TTL you configured.</text> </g> </svg>
```

Read the curve, because "60 second TTL" and this curve are not related the way the configuration
implies. It takes **1.4 minutes** to shed half the traffic, **18.0 minutes** to get below 10%,
**81.3 minutes** to get below 5%, and it **never reaches 1% within 24 hours** — because 1% of
clients have the address in a config file and will never re-resolve. One hour after failover,
**5.24%** of clients are still aiming at a dead region. Note also where the curve *starts*: both
curves sit at 100% for 35 seconds, and none of that is DNS's fault — it is **3 failed health checks
at a 10 s interval = 30 s of detection**, plus 5 s to publish. Detection lag is a floor under every
failover mechanism you will ever build.

Note also where the curve *starts*. Both curves sit at 100% through the first 35 seconds, and none
of that is DNS's fault: it is **3 failed health checks at a 10 s interval = 30 s of detection**,
plus 5 s to publish. Detection lag is a floor under every failover mechanism you will ever build.

**Anycast + BGP.** The same IP address is announced from many locations; the internet's routing
protocol (BGP — Border Gateway Protocol) delivers each packet to the topologically nearest
announcement. Failover is a *route withdrawal*, the client holds no state, and so there is no tail:
**0.00% at every checkpoint**. Note why it starts at zero rather than after a detection delay — on
a **hard** region loss the BGP session dies with the region, so the withdrawal is automatic and
needs no health check. A **partial** failure (region up, application broken) still costs the same
30 s of detection, then reconverges in seconds instead of hours.

The price of anycast is real and specific: a route change can re-anchor an **in-flight TCP
connection** at a different PoP (point of presence), which has no state for it, and the connection
resets. Terminate TLS at the edge and proxy onward and that is a retry the client barely notices;
run long-lived stateful protocols directly over raw anycast and it is a bug report.

**The practical architecture** is the combination: anycast to the edge, TLS terminated at the edge,
and the edge chooses the origin region over connections it manages itself. That gives you anycast's
instant failover *and* full control of origin selection, because the decision lives in software you
operate rather than in ten thousand resolvers you do not. Keep DNS as the slow, coarse layer — and
size your expectations by the curve above, not by the TTL field.

### Conflicts and split brain

Two regions accepting writes, plus a partition between them, produces conflicting writes. Not
"might" — the Build It runs a 120-second partition with 5,400 writes over 800 entities, where only
**8%** of an entity's writes arrive at a region other than its owner's home, and even that is
enough: **209 entities (30.3% of those touched) were written on both sides**, because a hot entity
gets written dozens of times and it only takes one stray.

So you have a choice about *when* you deal with it. Four strategies, and what each actually costs:

**Last-write-wins (LWW).** Keep the write with the largest timestamp, discard the rest. It is the
default in more systems than you would like. Measured cost: **694 acknowledged writes silently
discarded**, with **zero errors returned to anyone**. The deeper problem is in the name — it is not
"the last write wins", it is *the write carrying the largest number wins*, and that number comes
from a clock. Vary only the clock and the correctness of the whole scheme moves:

```text
clock offset on region B                writes lost   earlier write won
0 ms (perfect clocks)                           721            0 ( 0.0%)
50 ms (good NTP)                                721            0 ( 0.0%)
250 ms (ordinary NTP)                           694            1 ( 0.5%)
2 s (NTP daemon died)                           726            7 ( 3.3%)
10 s (host drifted, nobody looked)             1081           27 (12.9%)
```

With perfectly synchronised clocks LWW at least picks the genuinely later write. With an *ordinary,
healthy* 250 ms NTP offset it already inverts one resolution. With a host whose NTP daemon died — a
thing that happens silently and is not on your dashboard — **27 of 209 resolutions (12.9%) keep the
write that happened *earlier***. LWW's correctness is outsourced to clock hygiene you cannot audit
after the fact.

**Version vectors.** Track which replica has seen which versions, detect that two writes are
concurrent, and keep both as siblings (Parker et al., *Detection of Mutual Inconsistency in
Distributed Systems*, IEEE TSE SE-9(3), 1983; deployed at scale in DeCandia et al., *Dynamo*, SOSP
2007). Measured: **0 writes lost**, and **209 merge decisions** handed back to you. Strictly more
honest than LWW, and not free — someone must write a merge function for every type you store, and
the application must be able to render "this value is currently two values".

**CRDTs — Conflict-free Replicated Data Types** (Shapiro et al., *Conflict-Free Replicated Data
Types*, SSS 2011). Types whose merge is mathematically guaranteed to converge: counters, grow-only
sets, observed-remove sets, sequences for collaborative text. When your data fits one, this is the
best answer available and needs no merge function. Two caveats: most business data does *not* fit
one ("the current shipping address" is a register, and registers do not converge, they just pick),
and CRDTs carry per-replica metadata that grows with the replicas that ever wrote.

**Or avoid the conflict entirely.** Give every entity a **home region** and let only that region
write it:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 470" width="100%" style="max-width:840px" role="img" aria-label="The same network partition drawn twice. On the left, full multi-master: both regions accept a write to the same entity, 209 entities diverge and last-write-wins silently discards 694 acknowledged writes, with the winner decided by a clock. On the right, home-region pinning: only an entity home region may write it, so the stray write is rejected with a 503 the client can retry, producing zero conflicts and zero lost writes at the cost of 453 rejected writes."> <defs><marker id="p11-10-a6" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L6.5,3 L0,6 Z" fill="#0fa07f"/></marker><marker id="p11-10-a7" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L6.5,3 L0,6 Z" fill="#d64545"/></marker><marker id="p11-10-a8" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L6.5,3 L0,6 Z" fill="#e0930f"/></marker> </defs> <g font-family="'JetBrains Mono', ui-monospace, monospace"> <text x="440" y="26" text-anchor="middle" font-size="14.5" font-weight="700" fill="currentColor">Same partition, same 5,400 writes. One design resolves conflicts; the other never has one.</text> <rect x="14" y="46" width="418" height="336" rx="12" fill="#d64545" fill-opacity="0.05" stroke="#d64545" stroke-opacity="0.55" stroke-width="1.5"/> <text x="30" y="70" font-size="12" font-weight="700" fill="#d64545">FULL MULTI-MASTER
</text> <text x="30" y="85" font-size="8.5" fill="currentColor" opacity="0.85">both regions accept every write, then reconcile </text> <rect x="36" y="102" width="174" height="98" rx="9" fill="#0fa07f" fill-opacity="0.10" stroke="#0fa07f" stroke-width="1.9"/> <text x="123" y="120" font-size="9.5" font-weight="700" text-anchor="middle" fill="#0fa07f">REGION A</text> <text x="46" y="138" font-size="8.5" fill="#0fa07f" font-weight="700">u17 (home A) &lt;- write</text> <text x="46" y="154" font-size="8.5" fill="#0fa07f" font-weight="700">u42 (home A) &lt;- write</text> <text x="46" y="170" font-size="8.5" fill="#e0930f" font-weight="700">e.g. A writes u17 at t=61.40s</text> <rect x="236" y="102" width="174" height="98" rx="9" fill="#0fa07f" fill-opacity="0.10" stroke="#0fa07f" stroke-width="1.9"/> <text x="323" y="120" font-size="9.5" font-weight="700" text-anchor="middle" fill="#0fa07f">REGION B</text> <text x="246" y="138" font-size="8.5" fill="#d64545" font-weight="700">u17 (home A) &lt;- write</text> <text x="246" y="154" font-size="8.5" fill="#0fa07f" font-weight="700">u91 (home B) &lt;- write</text> <text x="246" y="170" font-size="8.5" fill="#d64545" font-weight="700">e.g. B writes 61.28 -&gt; 61.53</text> <path d="M223 96 L 223 206" fill="none" stroke="#d64545" stroke-width="3.2" stroke-dasharray="8 5"/> <text x="223" y="220" font-size="8.5" text-anchor="middle" fill="#d64545" font-weight="700">PARTITION — 120 s </text> <rect x="36" y="236" width="374" height="130" rx="9" fill="#d64545" fill-opacity="0.10" stroke="#d64545" stroke-width="1.7"/>
<text x="50" y="256" font-size="10" font-weight="700" fill="#d64545">on heal — someone has to pick a winner</text> <text x="50" y="274" font-size="8.5" fill="currentColor" font-weight="400" opacity="0.9">209 entities written on both sides (30.3% of those touched)</text> <text x="50" y="289" font-size="8.5" fill="currentColor" font-weight="400" opacity="0.9">LWW keeps the larger stamp, so B's EARLIER write wins</text> <text x="50" y="304" font-size="8.5" fill="#d64545" font-weight="700" opacity="1">694 acknowledged writes silently discarded — 0 errors returned </text> <text x="50" y="319" font-size="8.5" fill="currentColor" font-weight="400" opacity="0.9">the winner is chosen by a clock you do not control:</text> <text x="50" y="334" font-size="8.5" fill="#d64545" font-weight="700" opacity="1"> 0ms skew: 0 inversions · 2s: 7 · 10s: 27 (of 209)</text> <text x="50" y="349" font-size="8.5" fill="currentColor" font-weight="400" opacity="0.9">version vectors lose nothing and hand you 209 merges instead</text> <rect x="448" y="46" width="418" height="336" rx="12" fill="#0fa07f" fill-opacity="0.05" stroke="#0fa07f" stroke-opacity="0.55" stroke-width="1.5"/> <text x="464" y="70" font-size="12" font-weight="700" fill="#0fa07f">HOME-REGION PINNING</text> <text x="464" y="85" font-size="8.5" fill="currentColor" opacity="0.85">only an entity's home region may write it</text> <rect x="470" y="102" width="174" height="98" rx="9" fill="#0fa07f" fill-opacity="0.10" stroke="#0fa07f" stroke-width="1.9"/>
<text x="557" y="120" font-size="9.5" font-weight="700" text-anchor="middle" fill="#0fa07f">REGION A</text> <text x="480" y="138" font-size="8.5" fill="#0fa07f" font-weight="700">u17 (home A) &lt;- write</text> <text x="480" y="154" font-size="8.5" fill="#0fa07f" font-weight="700">u42 (home A) &lt;- write </text> <text x="480" y="170" font-size="8.5" fill="#0fa07f" font-weight="700">authoritative for A-homed</text> <rect x="670" y="102" width="174" height="98" rx="9" fill="#0fa07f" fill-opacity="0.10" stroke="#0fa07f" stroke-width="1.9"/> <text x="757" y="120" font-size="9.5" font-weight="700" text-anchor="middle" fill="#0fa07f">REGION B</text> <text x="680" y="138" font-size="8.5" fill="#e0930f" font-weight="700">u17 (home A) -&gt; 503</text> <text x="680" y="154" font-size="8.5" fill="#0fa07f" font-weight="700">u91 (home B) &lt;- write</text> <text x="680" y="170" font-size="8.5" fill="#0fa07f" font-weight="700">authoritative for B-homed </text> <path d="M657 96 L 657 206" fill="none" stroke="#d64545" stroke-width="3.2" stroke-dasharray="8 5"/> <text x="657" y="220" font-size="8.5" text-anchor="middle" fill="#d64545" font-weight="700">PARTITION — 120 s</text> <rect x="470" y="236" width="374" height="130" rx="9" fill="#0fa07f" fill-opacity="0.10" stroke="#0fa07f" stroke-width="1.7"/> <text x="484" y="256" font-size="10" font-weight="700" fill="#0fa07f">on heal — there is nothing to reconcile</text> <text x="484" y="274" font-size="8.5" fill="currentColor" font-weight="400" opacity="0.9">0 entities written on both sides. By construction, not by luck.
</text> <text x="484" y="289" font-size="8.5" fill="#0fa07f" font-weight="700" opacity="1">0 writes lost, 0 merge functions, 0 dependence on any clock</text> <text x="484" y="304" font-size="8.5" fill="#e0930f" font-weight="700" opacity="1">453 writes (8.4%) rejected with a 503 during the partition</text> <text x="484" y="319" font-size="8.5" fill="currentColor" font-weight="400" opacity="0.9">the client is TOLD, and can retry — Gilbert &amp; Lynch (2002)</text> <text x="484" y="334" font-size="8.5" fill="currentColor" font-weight="400" opacity="0.9">charging for consistency in availability, visibly </text> <text x="484" y="349" font-size="8.5" fill="#0fa07f" font-weight="700" opacity="1">normal operation: 91.6% of writes never leave their region</text> <text x="440" y="404" text-anchor="middle" font-size="11.5" font-weight="700" fill="currentColor">Avoid the conflict rather than resolve it.</text> <text x="440" y="426" text-anchor="middle" font-size="10.5" fill="currentColor" opacity="0.9">One rule — "only the home region may write this entity" — removed 209 conflicts, 694 silent losses and every merge function.</text> <text x="440" y="446" text-anchor="middle" font-size="10" fill="currentColor" opacity="0.75">It buys that with an error the client can see, which is the only kind of data loss you ever get to fix. </text> </g> </svg>
```

Measured: **zero conflicts. Zero writes lost. Zero merge functions. Zero dependence on any clock.**
By construction, not by luck — two regions cannot both write an entity when only one is permitted
to.

It is not free, and the cost is the interesting part. During the partition, **453 writes (8.4%)**
arrived at the wrong region, could not be forwarded home, and were **rejected with a 503**. That is
Gilbert & Lynch (*Brewer's Conjecture and the Feasibility of Consistent, Available,
Partition-Tolerant Web Services*, SIGACT News 33(2), 2002) charging you for consistency in
availability, exactly as the theorem says. But compare the bills: multi-master lost 694 writes and
told nobody; pinning refused 453 and told everybody. **An error the client can see is the only kind
of data loss you ever get to fix.** Silent loss surfaces as a support ticket months later that no
one can explain. And in normal operation the rule costs almost nothing: **91.6% of writes never
leave their region.**

And in normal operation the rule costs almost nothing: **91.6% of writes never leave their
region**, and the 8.4% that arrive in the wrong place are forwarded for one cross-region round
trip. Pin users to the region they live in and even that shrinks.

> **The strongest practical advice in this lesson: avoid the conflict rather than resolve it.
> One rule — "only the home region may write this entity" — removed 209 conflicts, 694 silent
> losses and every merge function you were about to write.**

### Data gravity and the partial-migration trap

Data has gravity: it is expensive to move, so everything else ends up orbiting it. The most common
real-world multi-region failure is moving the app tier and leaving the data tier behind — because
the app tier is stateless and easy to move (Lesson 6), and the database is neither. Do the
arithmetic before the migration. A request making 6 sequential queries pays 6 round trips: inside a
region that is `6 x 0.55 ms` and invisible; across the Atlantic it is `6 x 75 ms = 450 ms` of pure
propagation that no CPU, index or cache removes:

Do the arithmetic before you do the migration. A request that makes 6 sequential queries pays 6
round trips. Inside a region that is `6 x 0.55 ms` and invisible. Across the Atlantic it is
`6 x 75 ms = 450 ms` of pure propagation, and no amount of CPU, indexing, or caching removes
it:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 424" width="100%" style="max-width:840px" role="img" aria-label="Four timelines of the same request, all drawn to the same millisecond scale. With the database in the same region the request takes 9.3 milliseconds and is barely visible. With the database a region away the six sequential queries become six visible 75 millisecond round trips totalling 456.2 milliseconds, far past the 200 millisecond budget line. Batching the six queries into one round trip gives 81.1 milliseconds and parallelising them gives 77.2 milliseconds, both still about nine times the local cost."> <defs><marker id="p11-10-a4" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L6.5,3 L0,6 Z" fill="currentColor"/></marker> </defs> <g font-family="'JetBrains Mono', ui-monospace, monospace"> <text x="440" y="26" text-anchor="middle" font-size="14.5" font-weight="700" fill="currentColor">Six sequential queries. The only thing that changed is where the database is.</text> <path d="M252 62 L 844.0 62" fill="none" stroke="currentColor" stroke-width="1.3" opacity="0.5"/> <path d="M252.0 56 L 252.0 62" fill="none" stroke="currentColor" stroke-width="1.2" opacity="0.5"/> <text x="252.0" y="50" font-size="8.5" text-anchor="middle" fill="currentColor" opacity="0.7">0</text> <path d="M375.3 56 L 375.3 62" fill="none" stroke="currentColor" stroke-width="1.2" opacity="0.5"/> <text x="375.3" y="50" font-size="8.5" text-anchor="middle" fill="currentColor" opacity="0.7">100
</text> <path d="M498.7 56 L 498.7 62" fill="none" stroke="currentColor" stroke-width="1.2" opacity="0.5"/> <text x="498.7" y="50" font-size="8.5" text-anchor="middle" fill="currentColor" opacity="0.7">200</text> <path d="M622.0 56 L 622.0 62" fill="none" stroke="currentColor" stroke-width="1.2" opacity="0.5"/> <text x="622.0" y="50" font-size="8.5" text-anchor="middle" fill="currentColor" opacity="0.7">300</text> <path d="M745.3 56 L 745.3 62" fill="none" stroke="currentColor" stroke-width="1.2" opacity="0.5"/> <text x="745.3" y="50" font-size="8.5" text-anchor="middle" fill="currentColor" opacity="0.7">400</text> <path d="M844.0 56 L 844.0 62" fill="none" stroke="currentColor" stroke-width="1.2" opacity="0.5"/> <text x="844.0" y="50" font-size="8.5" text-anchor="middle" fill="currentColor" opacity="0.7">480</text> <text x="850.0" y="50" font-size="8.5" fill="currentColor" opacity="0.7">ms</text> <path d="M498.7 62 L 498.7 296" fill="none" stroke="#d64545" stroke-width="1.8" stroke-dasharray="6 5" opacity="0.6"/> <text x="504.7" y="78" font-size="9.5" font-weight="700" fill="#d64545">200 ms budget </text> <text x="18" y="90" font-size="9.5" font-weight="700" fill="currentColor">app + db, same region</text> <text x="18" y="103" font-size="8" fill="currentColor" opacity="0.8">p50 9.3 ms · p99 16.9 ms · 6 x 0.55 ms</text> <rect x="252" y="80" width="11.5" height="24" rx="3" fill="#0fa07f" fill-opacity="0.45" stroke="#0fa07f" stroke-width="1.6"/> <path d="M269.5 92 L 294 92" fill="none" stroke="#0fa07f" stroke-width="1.3"/>
<text x="300" y="96" font-size="9" fill="#0fa07f" font-weight="700">9.3 ms, drawn to scale</text> <text x="18" y="148" font-size="9.5" font-weight="700" fill="currentColor">app in region B, db in region A </text> <text x="18" y="161" font-size="8" fill="currentColor" opacity="0.8">p50 456.2 ms · p99 467.0 ms · 49.3x</text> <rect x="252.0" y="138" width="91.8" height="24" rx="3" fill="#e0930f" fill-opacity="0.16" stroke="#e0930f" stroke-width="1.7"/> <text x="298.9" y="154" font-size="8" text-anchor="middle" fill="#e0930f" font-weight="700">RTT 1</text> <rect x="345.8" y="138" width="91.8" height="24" rx="3" fill="#e0930f" fill-opacity="0.16" stroke="#e0930f" stroke-width="1.7"/> <text x="392.7" y="154" font-size="8" text-anchor="middle" fill="#e0930f" font-weight="700">RTT 2 </text> <rect x="439.5" y="138" width="91.8" height="24" rx="3" fill="#e0930f" fill-opacity="0.16" stroke="#e0930f" stroke-width="1.7"/> <text x="486.4" y="154" font-size="8" text-anchor="middle" fill="#e0930f" font-weight="700">RTT 3</text> <rect x="533.3" y="138" width="91.8" height="24" rx="3" fill="#e0930f" fill-opacity="0.16" stroke="#e0930f" stroke-width="1.7"/> <text x="580.2" y="154" font-size="8" text-anchor="middle" fill="#e0930f" font-weight="700">RTT 4</text> <rect x="627.1" y="138" width="91.8" height="24" rx="3" fill="#e0930f" fill-opacity="0.16" stroke="#e0930f" stroke-width="1.7"/> <text x="674.0" y="154" font-size="8" text-anchor="middle" fill="#e0930f" font-weight="700">RTT 5</text> <rect x="720.9" y="138" width="91.8" height="24" rx="3" fill="#e0930f" fill-opacity="0.16" stroke="#e0930f" stroke-width="1.7"/>
<text x="767.8" y="154" font-size="8" text-anchor="middle" fill="#e0930f" font-weight="700">RTT 6</text> <text x="820.6" y="154" font-size="9" fill="#d64545" font-weight="700">456 ms</text> <text x="18" y="206" font-size="9.5" font-weight="700" fill="currentColor">... the 6 queries batched</text> <text x="18" y="219" font-size="8" fill="currentColor" opacity="0.8">p50 81.1 ms · p99 89.1 ms · 8.8x </text> <rect x="252" y="196" width="100.0" height="24" rx="3" fill="#e0930f" fill-opacity="0.16" stroke="#e0930f" stroke-width="1.7"/> <text x="302.0" y="212" font-size="8" text-anchor="middle" fill="#e0930f" font-weight="700">1 RTT</text> <text x="360.0" y="212" font-size="9" fill="currentColor" opacity="0.85">1 request carrying 6 queries</text> <text x="18" y="254" font-size="9.5" font-weight="700" fill="currentColor">... the 6 queries parallelised</text> <text x="18" y="267" font-size="8" fill="currentColor" opacity="0.8">p50 77.2 ms · p99 82.9 ms · 8.3x </text> <rect x="252" y="244" width="95.2" height="24" rx="3" fill="#e0930f" fill-opacity="0.16" stroke="#e0930f" stroke-width="1.7"/> <text x="299.6" y="260" font-size="8" text-anchor="middle" fill="#e0930f" font-weight="700">1 RTT</text> <text x="355.2" y="260" font-size="9" fill="currentColor" opacity="0.85">6 in flight — pay the slowest, not the sum</text> <path d="M244 80 L 244 272" fill="none" stroke="currentColor" stroke-width="1.1" opacity="0.25"/> <rect x="18" y="308" width="844" height="52" rx="9" fill="#7f7f7f" fill-opacity="0.06" stroke="currentColor" stroke-opacity="0.3" stroke-width="1.2"/>
<text x="34" y="328" font-size="10" font-weight="700" fill="currentColor">the arithmetic, before you run anything:</text> <text x="34" y="346" font-size="10" fill="currentColor" opacity="0.9">6 queries x 75 ms of glass = 450 ms of pure propagation. The queries themselves still cost the ~6 ms they always did.</text> <text x="440" y="392" text-anchor="middle" font-size="11" fill="currentColor" opacity="0.9">Moving the app tier without the data tier is a 49x latency regression that no profiler will ever attribute to you.</text> <text x="440" y="410" text-anchor="middle" font-size="10" fill="currentColor" opacity="0.75">Batching recovers 5.6x of it and is still 9x local. There is no code change that removes an ocean. </text> </g> </svg>
```

Measured: p50 goes from **9.3 ms to 456.2 ms — a 49.3x regression** — and p99 from **16.9 ms to
467.0 ms**. Notice that the remote p50 and p99 are almost the same number. That is the signature of
a latency problem that is *propagation*, not *load*: the distribution collapses onto a constant,
because 450 of the 456 ms is a fixed cost no percentile escapes.

The mitigations are real, and it matters how far they get you:

- **Batch the 6 queries into 1 round trip** — one request carrying six queries. **456.2 ms → 81.1
  ms, a 5.6x improvement.** Still **8.8x** the local cost.
- **Parallelise them** — issue all 6 at once and pay the slowest rather than the sum. **77.2 ms,
  8.3x** local.

Both are worth doing and neither is a fix. **There is no code change that removes an ocean.** The
floor for a request that must touch a remote data tier is one round trip, and one transatlantic
round trip is 37.5% of a 200 ms budget.

Then the line item nobody forecasts: **egress**. Cross-region transfer is billed. At 2,000 req/s
with 6 queries returning 25 rows of 400 bytes — 59 KB per request — that is **311,040 GB/month**
crossing a region boundary, about **$6,221/month at $0.02/GB**, to run a query that used to be
free. The rule that follows: **move the data and the compute together, or move neither.** A
migration that relocates the app tier this quarter and the data tier next has a quarter of 49x
latency in the middle, and that quarter is when everyone concludes multi-region was a mistake.

The rule that follows: **move the data and the compute together, or move neither.** A migration
that relocates the app tier this quarter and the data tier next quarter has a quarter of 49x
latency in the middle of it, and that quarter is when everyone concludes multi-region was a
mistake.

### Failover is an operation you practise, not a feature you have

Everything above is design. This is the part that decides whether any of it works.

A failover is not an event, it is a **sequence**, and every step has a duration you can measure and
shorten:

1. **Detect.** Health checks decide the region is gone. Measured floor above: **30 s** for 3 failed
   checks at a 10 s interval. Faster checks detect faster and false-positive more.
2. **Decide.** Automatic or human? This is the genuinely hard question, and the answer is usually
   *human for a whole region*. A false positive in an automatic region failover **causes** an
   outage rather than preventing one: it promotes a standby while the primary is still taking
   writes, and now you have split brain in the one system you were most careful about. Automate
   ruthlessly *within* a region; put a human in the loop *across* regions, and make their job a
   checklist rather than a design exercise.
3. **Drain traffic.** Move users off the dead region — the curve above says this is minutes with
   anycast and tens of minutes with DNS.
4. **Promote the database.** The slowest step, and the one most likely to be wrong: the replica
   must be caught up, and you must accept whatever the RPO tail says you lost.
5. **Redirect and verify.** Not "did the promotion command exit 0" — did a real request from a real
   client succeed end to end.
6. **Fail back.** Almost always harder than failing over, because the old primary now has
   *divergent* data: writes it accepted before it died that the new primary never saw. Fail back is
   a data reconciliation problem wearing a traffic-management costume, and it is where the second
   outage happens.

And then the rule, stated as bluntly as it deserves:

> **An untested failover does not work.** Not "might not" — does not. Every failover path that
> has never been exercised contains at least one of: an expired credential, a security group
> that only allows the primary, a DNS record with a 3600-second TTL nobody noticed, a replica
> that has been broken for six weeks, a runbook referencing a hostname that was renamed, or a
> capacity assumption that was true when it was written.

The only way to know is to **evacuate a region on a schedule** and watch what breaks while everyone
is awake and nothing is actually wrong. Which creates the requirement this lesson ends on, and
Lesson 12 picks up: to absorb a failed region's traffic, the survivors need somewhere to put it. To
survive losing 1 of N regions you must run at most **(N−1)/N** utilization:

To survive losing 1 of N regions you must run at most **(N−1)/N** utilization:

```text
  regions   max utilisation   cost multiplier
        2             50.0%             2.00x
        3             66.7%             1.50x
        4             75.0%             1.33x
        6             83.3%             1.20x
```

**Two regions is the most expensive way to be multi-region.** Each must idle at 50% to cover the
other, so you pay 2.00x. Three regions need only 66.7% utilization and cost 1.50x per unit of
survivable traffic. Nobody budgets for the third region, and the third region is the one that makes
the arithmetic stop hurting.

## Build It

[`code/multi_region.py`](code/multi_region.py) is six numbered arguments. Standard library only,
seeded with `random.Random(7)`, runs in 2.0 seconds. The interesting parts:

**Section 1 derives the floor rather than asserting it.** Every "minimum RTT" in the output comes
out of haversine distance and one physical constant (`V_FIBRE_KM_S = 299_792.458 / 1.4682`), so
`min_rtt = 2 * km / V_FIBRE_KM_S`. The `typical` column *is* a table of constants — documented
public figures used as model inputs. The program never pretends to have measured them; what it
derives is the distance, the floor, and the overhead ratio between them.

**Section 2 changes exactly one number.** The local and remote runs share the same query-time
distribution and the same seed; the only difference is which constant is added per query:

```python
for _ in range(n_queries):
    t += CROSS_AZ_RTT_MS + query_ms()                             # 0.55 ms
    ...
    t += CROSS_REGION_RTT_MS + RNG.gauss(0, 1.5) + query_ms()     # 75 ms
```

That is the whole 49.3x. The batched variant moves the round trip *outside* the loop and the
parallel variant replaces `sum` with `max` — three lines separating 456 ms from 81 ms.

**Section 3 simulates a year at one-minute resolution.** Each region gets an independent failure
process; each topology reacts to the same failures with its own RTO and blast radius. The clause
worth reading says who is hurt by losing the write region:

```python
elif topo == "single-write-region":
    if recovered:
        lost = 0.0
    elif failed == "A":
        # A's users are stranded AND every remaining user's writes fail.
        lost = share + (1 - share) * WRITE_FRACTION
    else:
        lost = share
```

Losing the *read* region costs you that region's users. Losing the *write* region costs you that
region's users **plus every write in the world**, which is why its availability lands below
regional ownership's despite an identical replication setup.

**Section 4 models resolvers, not nameservers.** The failover is instant; the tail is entirely
other people's caches, so the client population *is* the model — 62% honour the 60 s TTL, 22% hit a
300 s resolver floor, 10% are pooled HTTP clients at 30 min, 5% are JVMs caching forever, 1% never
re-resolve. A client that respects the TTL still has a *uniformly distributed remaining* TTL when
the record changes; that factor of one-half is why the curve does not fall off a cliff at exactly
60 seconds.

**Section 5's whole argument is one predicate.** Conflict detection and conflict avoidance are the
same line read in two directions:

```python
stray = sum(1 for _, region, key, _ in writes if region != home[key])
```

Under multi-master a stray write is *accepted locally* and becomes a conflict. Under pinning it is
*forwarded* (+75 ms) in normal operation and *rejected* during a partition. Same predicate, three
completely different systems. The LWW resolver takes clock skew as a parameter (`stamp_b =
best_b[0] + skew_s`) precisely so the sweep can hold everything else fixed and vary only the clock.

**Section 6 isolates headroom.** Both runs get the same failure, the same detection lag and the
same redirection curve; `cap_b` is the only variable, and autoscaling is given to both —
`run(demand * 0.5 / 0.90, ...)` against `run(demand * 1.00, ...)`.

Run it:

```bash
docker compose exec -T app python \
  phases/11-scalability-and-reliability/10-multi-region-and-failover/code/multi_region.py
```

```console
MULTI-REGION: GLOBAL TRAFFIC, FAILOVER & DATA GRAVITY
Phase 11 . Lesson 10 . seeded random.Random(7), stdlib only

== 1 . THE SPEED OF LIGHT IS THE FIRST LINE OF YOUR ARCHITECTURE ==
  light in vacuum 299,792 km/s;  in single-mode fibre (n=1.4682) 204,190 km/s

  region pair                        distance   min RTT   typical  overhead
  us-east-1 <-> us-west-2             3,503km     34.3ms     62.0ms     1.81x
  us-east-1 <-> sa-east-1             7,664km     75.1ms    116.0ms     1.55x
  eu-west-1 <-> ap-southeast-1       11,199km    109.7ms    175.0ms     1.60x
  us-east-1 <-> ap-southeast-2       15,674km    153.5ms    200.0ms     1.30x

== 2 . DATA GRAVITY: THE APP TIER MOVED, THE DATA TIER DID NOT ==
  one request = 6 sequential queries. Same code, same database, same query plan.

  configuration                            p50       p99   vs local
  app + db in the same region            9.3ms    16.9ms       1.0x
  app in region B, db in region A      456.2ms   467.0ms      49.3x
    ... batched into 1 round trip       81.1ms    89.1ms       8.8x
    ... parallelised, 1 round trip      77.2ms    82.9ms       8.3x

  egress: 2,000 req/s x 6 queries x 25 rows x 400 B = 59 KB/request
  = 311,040 GB/month crossing a region boundary. At $0.02/GB that is $6,221/month

== 3 . FOUR TOPOLOGIES, ONE SIMULATED YEAR ==
  cross-region RTT 75 ms, last mile 15 ms, 8 region-impacting failures simulated over 365 days.

  topology                p99 read  p99 write    RTO      RPO     avail   cost  idle $  conflicts
  active-passive            93.6ms    101.2ms   34min   7.30s   99.971%   2.0x     50%       none
  single-write-region       19.6ms    100.6ms   12min   7.30s   99.989%   2.0x      0%       none
  regional-ownership        19.6ms     95.6ms    9min   7.30s   99.993%   2.0x      0%       none
  multi-master              19.5ms     28.7ms    6min   7.30s   99.995%   2.0x      0%        YES

       p50       p95       p99       max
      84ms     0.37s     7.30s     9.10s

  RPO target  mechanism                           p50 write  p99 write
  seconds     async streaming replication            17.6ms     95.6ms
  zero        synchronous cross-region commit        92.4ms    103.7ms

== 4 . DNS FAILOVER HAS A LONG TAIL. ANYCAST DOES NOT. ==

  traffic still resolving to the DEAD region, 200,000 clients:
         t    DNS failover    anycast withdrawal
      60s         72.17%                0.00%
     300s         17.01%                0.00%
     900s         11.01%                0.00%
    3600s          5.24%                0.00%
  time for the dead region's share to fall below 50%:      85s (   1.4 min)
  time for the dead region's share to fall below 10%:   1,080s (  18.0 min)
  time for the dead region's share to fall below  5%:   4,880s (  81.3 min)
  time for the dead region's share to fall below  1%: NEVER within 24 h

== 5 . CONFLICTS: RESOLVE THEM, OR ARRANGE FOR THEM NOT TO EXIST ==

  5,400 writes landed on 690 distinct entities during the partition.
  entities written on BOTH sides = 209 (30.3% of entities touched)
  -- an 8% stray-write rate is enough, because a hot entity is written dozens of times.
  strategy                    conflicts  writes lost  silent?  rejected  merges owed
  last-write-wins (clock)           209          694      YES         0            0
  version vectors                   209            0       no         0          209
  CRDT (if types fit)               209            0       no         0            0
  home-region pinning                 0            0        -       453            0

  clock offset on region B                writes lost   earlier write won
  0 ms (perfect clocks)                           721            0 ( 0.0%)
  50 ms (good NTP)                                721            0 ( 0.0%)
  250 ms (ordinary NTP)                           694            1 ( 0.5%)
  2 s (NTP daemon died)                           726            7 ( 3.3%)
  10 s (host drifted, nobody looked)             1081           27 (12.9%)

== 6 . THE EVACUATION: WHAT HEADROOM ACTUALLY BUYS ==
  20,000 req/s split 50/50 across two regions. Region A dies at t=0.

  configuration                                    cap  peak err  peak after   failed reqs   recovery
  no headroom  (each region 90% utilised)     11,111/s     50.0%       44.4%     2,941,245       407s
  headroom     (each region 50% utilised)     20,000/s     50.0%        0.0%       455,000        55s

       t   no headroom err%   headroom err%   what is failing
      0s             50.0%           50.0%   region A is dead, nobody knows yet
     35s             50.0%           50.0%   detected; redirection begins
     55s             44.4%            0.0%   redirection complete
    120s             44.4%            0.0%   survivor is the only bottleneck now
    245s             44.4%            0.0%   new capacity starts landing
    500s              0.0%            0.0%

                                                        peak err  peak after   failed reqs   recovery
  headroom, but DNS redirection               20,000/s     50.0%       38.9%     2,038,064      >900s
  to survive losing 1 of N regions you must run at most (N-1)/N utilisation:
    regions   max utilisation   cost multiplier
          2             50.0%             2.00x
          3             66.7%             1.50x
          4             75.0%             1.33x
          6             83.3%             1.20x
  (total wall time 2.0 s)
```

**Section 1** is the constraint everything else obeys. The overhead ratio never falls below
**1.23x** and reaches **1.81x** on a route that is nominally domestic, so budgeting with the
theoretical floor is optimistic by up to 80%. Against a 200 ms budget with 40 ms of server work,
**two** cross-region round trips fit with 10 ms to spare and a third overshoots by 65 ms.

**Section 2 is the most common real multi-region failure, and it is arithmetic.** The same six
queries cost **9.3 ms** locally and **456.2 ms** across the Atlantic — **49.3x** — because
`6 x 75 ms = 450 ms` of the total is propagation that no index, cache or CPU touches. Remote p50
and p99 are **456.2 ms and 467.0 ms**: percentiles that collapse together mean a distance problem,
not a load problem, and it will not respond to anything you would normally do about latency.

**Section 3 prices the topologies against each other.** Active-passive has the worst read latency
(**93.6 ms p99**, 4.8x regional ownership) *and* the worst RTO (**34 minutes**) *and* wastes half
its spend. Regional ownership reaches **19.6 ms / 95.6 ms / 9 min / 99.993%** with no conflict
exposure. Multi-master wins every latency column (**28.7 ms p99 writes**) and pays for it in
section 5. The cost column is flat at **2.0x for all four**, because surviving the loss of 1 of 2
regions is what costs money — not the topology you spend it in.

**Section 4 is the one that surprises operators.** The authoritative record changed at 35 seconds.
One minute in, **72.17%** of clients are still resolving to the dead region; five minutes in,
**17.01%**; an hour in, **5.24%**; and it **never reaches 1% within 24 hours**. An anycast
withdrawal measures **0.00%** at every checkpoint. If your evacuation plan is "change DNS and wait
for the TTL", your plan is 18 minutes to 10% and 81 minutes to 5%.

**Section 5 is the argument for pinning, in one table.** Same partition, same 5,400 writes.
Last-write-wins loses **694 acknowledged writes** and reports nothing; version vectors lose none
and hand you **209 merges**; home-region pinning has **zero conflicts** and rejects **453 writes**
with an error the client can see. Then the clock sweep: at 0 ms of skew LWW never picks the wrong
write, at an ordinary **250 ms** it inverts one resolution, and at **10 s** — a dead NTP daemon
nobody noticed — it keeps the *earlier* write **27 times out of 209 (12.9%)**. Your data model's
correctness should not be downstream of a clock you cannot audit.

**Section 6 is the number that justifies the capacity bill.** Both evacuations peak at **50.0%
errors** — the 35-second detection window, which headroom does nothing about. After redirection
they diverge: the provisioned survivor is at **0.0% errors, fully recovered at 55 s**, while the
tight one sits at **44.4% errors for another six minutes** and does not recover until **407 s**.
Total: **455,000 failed requests versus 2,941,245 — 6.5x**. The third row prices section 4 in the
same currency: the same capacity redirected by 60-second DNS fails **2,038,064** requests and never
fully recovers inside the window.

## Use It

**Route 53 (or any managed DNS) gives you the routing policies and the health checks.**
Latency-based routing sends a user to the region with the lowest RTT to their resolver; geolocation
routing sends them by geography — that is the one you want for data residency, because it is
deterministic; failover routing swaps primary for secondary when a health check fails. The knobs
that decide your section-4 curve:

```bash
# health check: interval 10s or 30s (10 costs more), 3 failures to declare unhealthy
aws route53 create-health-check --health-check-config \
  'Type=HTTPS,ResourcePath=/healthz,FullyQualifiedDomainName=origin-use1.example.com,
   RequestInterval=10,FailureThreshold=3'

# the record TTL — the number section 4 says you cannot trust
aws route53 change-resource-record-sets --change-batch \
  '{"Changes":[{"Action":"UPSERT","ResourceRecordSet":{
     "Name":"api.example.com","Type":"A","TTL":60,
     "SetIdentifier":"use1","Failover":"PRIMARY",
     "HealthCheckId":"...","AliasTarget":{"...":"..."}}}]}'
```

`RequestInterval=10` with `FailureThreshold=3` is the 30 seconds of detection in the output.
Lowering the TTL below 60 buys very little, because the tail is not made of TTL-respecting clients
— it is made of the 38% who are not.

**Cloudflare, Fastly and other anycast edges** give you the fast path: one anycast address, TLS
terminated at the edge, origin selection made in the edge's own configuration over connections it
manages. Failover becomes an edge config change measured in seconds and the client never
re-resolves anything. Hence the recommendation: *anycast edge in front, DNS as the coarse layer
behind.*

**Global databases** are where the topology decision becomes a product choice:

- **Aurora Global Database** — one writable region, read replicas elsewhere, typical cross-region
  lag under a second — section 3's *single-write-region* row. Managed failover promotes a secondary
  in about a minute; the RPO is whatever the lag was, which is why you graph the lag rather than
  trusting the brochure.
- **DynamoDB Global Tables** — genuine multi-master across regions, with conflict resolution by
  **last-writer-wins**. That is section 5's first row, in production, by default. Fine for data
  whose writes are naturally partitioned by user; it silently drops updates for anything two
  regions might touch at once. Name that caveat out loud before choosing it.
- **Spanner** — synchronous global consistency via TrueTime, which turns clock uncertainty into an
  explicit bounded interval and *waits it out* before committing (Corbett et al., *Spanner:
  Google's Globally-Distributed Database*, OSDI 2012). The honest version of what LWW pretends to
  do, costing a commit-wait plus cross-region consensus on every write — section 3's `RPO = 0` row,
  productised.
- **CockroachDB regional-by-row tables** — a `crdb_region` column pins each row to a home region,
  so writes to that row are served locally and cannot conflict. This is home-region pinning as a
  schema feature, and the most direct implementation of section 5's conclusion available off the
  shelf.

**Kubernetes multi-cluster** means one cluster per region, not one spanning regions — etcd's
consensus does not tolerate 75 ms between members. Federate per-region clusters behind a global
load balancer; [Phase 10](../../10-infrastructure-and-deployment/) covers the mechanics.

**The regional evacuation runbook** is what makes any of this real. At minimum: the decision
criteria and who may make the call; the drain sequence in order; the promotion command with its
verification query; the capacity check for the surviving region *before* you send it double
traffic; the fail-back procedure and its reconciliation step; and an explicit statement of what an
RPO of 7.30 s means you have lost. Netflix has described publicly how it evacuates an entire AWS
region in minutes, and the point of that exercise is not the tooling — it is that they run it on a
schedule, so the runbook is exercised while everyone is awake and nothing is actually wrong.

**And the honest closing advice: most teams do not need a second region.** Multi-AZ within one
region survives the overwhelming majority of real failures — a rack, a power domain, a switch, an
entire datacenter — at a cross-AZ RTT of **0.55 ms**, 0.3% of a 200 ms budget, with no conflicts,
no data gravity problem, no egress bill, and no failover you have to practise. A second region
defends against exactly one class of event, the total regional loss, and costs **2.0x** compute, a
redesign of every write path, and an operational practice you must keep alive forever. Buy multi-AZ
first, be excellent at it, and go multi-region when you can name the requirement — latency, DR, or
residency — in one sentence with a number attached.

## Think about it

1. Your 200 ms budget currently holds one cross-region round trip and 40 ms of server work. Product
   wants to add a call to a service that exists only in the other region. Show the arithmetic for
   both options — move the service, or batch the call into the existing round trip — and say what
   you would measure before choosing.
2. Section 3 measured an identical RPO of 7.30 s across all four topologies. Explain why, then
   describe the change you *would* make if the business said "we can lose at most 1 second of
   writes", including what that change does to your p50 write latency.
3. Your DNS failover reaches 5.24% residual traffic after an hour and the 1% floor never clears.
   For each of the five client populations in section 4, say what you would actually do about it —
   and which ones you cannot fix from your side at all.
4. Home-region pinning rejected 453 writes during the partition rather than accepting and
   reconciling them. Argue the opposite case: what kind of data *should* accept the write and
   reconcile later, and what property must it have for that reconciliation to be automatic rather
   than a support ticket?
5. Your two regions each run at 50% utilization to cover each other, at 2.0x cost. Someone proposes
   three regions at 66.7%. Work out what actually changes — cost per unit of survivable traffic,
   blast radius, write-path complexity, and the evacuation runbook — and say whether you would take
   the deal.

## Key takeaways

- **The speed of light is the first constraint on the design, not a footnote.** Light in fibre
  travels **204,190 km/s**, so New York to London is **54.6 ms** round trip at the physical floor
  and the fastest commercial route sells **58.95 ms (1.08x)**; real inter-region RTT runs
  **1.23x-1.81x** the floor. Against a 200 ms budget with 40 ms of server work you can afford
  **two** cross-region round trips — design for one. And be strict about *why* you want a second
  region: latency needs local reads, DR needs replicated data **and** pre-provisioned capacity, and
  data residency needs **partitioning by region**, which conflicts with both.
- **Data gravity is measurable and brutal.** Moving the app tier one region from its database took
  the same 6-query request from **9.3 ms to 456.2 ms p50 — 49.3x** — because `6 x 75 ms` is
  propagation nothing removes. Batching recovers **5.6x** and is still **8.8x** local, and the
  egress bill for that pattern was **$6,221/month**. Move data and compute together, or move
  neither.
- **Regional data ownership is the sweet spot, and all four topologies cost the same 2.0x.** Over a
  simulated year: active-passive **93.6 ms p99 read / 34 min RTO / 99.971%** with **half its spend
  idle**; regional ownership **19.6 ms / 95.6 ms / 9 min / 99.993%** with no conflict exposure.
  Full multi-master wins every latency column and pays for it in conflicts.
- **RPO is measured, not chosen — and it belongs to your replication, not your topology.** Async
  lag was **p50 84 ms but p99 7.30 s**; quote the tail. RPO = 0 requires a synchronous cross-region
  commit costing **+75 ms on every write, forever**, including the 364 days nothing fails. Changing
  topology does not change RPO — it was identical across all four.
- **DNS failover has a long tail; anycast does not.** One hour after a 60-second-TTL failover,
  **5.24%** of clients were still hitting the dead region, and the residual **never fell below 1%
  within 24 hours** — RFC 2181 §8 makes the TTL an upper bound and nothing enforces a lower one.
  Anycast withdrawal measured **0.00%** at every checkpoint; its price is that a route change can
  reset an in-flight TCP connection.
- **Avoid conflicts rather than resolve them.** With writes on both sides of a 120-second
  partition, **209 entities (30.3%)** diverged. Last-write-wins discarded **694 acknowledged writes
  silently**, and its correctness depends on clocks: at **10 s** of skew it kept the *earlier*
  write **12.9%** of the time. Home-region pinning produced **zero** conflicts and **zero** losses,
  charging **453 visible 503s** instead — and **91.6% of writes never left their region.**
- **An untested failover does not work, and headroom is what makes the tested one survivable.** Two
  identical evacuations peaked at the same **50.0%** error rate — detection lag is unavoidable —
  but the provisioned survivor recovered in **55 s** with **455,000** failed requests while the
  tight one took **407 s** and **2,941,245 (6.5x)**. To survive losing 1 of N regions you must run
  at most **(N−1)/N** utilization: **2 regions = 50%, 2.00x**; three = 66.7%, 1.50x. Two regions is
  the most expensive way to be multi-region.

Next: [The Tail at Scale: Fan-Out, Hedged Requests & Correlated
Failure](../11-the-tail-at-scale/) — what happens to that 200 ms budget when one request becomes a
hundred parallel ones, and why the slowest of them decides what the user experiences.
