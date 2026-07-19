# The Tail at Scale: Fan-Out, Hedged Requests & Correlated Failure

> Every backend you call has a p99 of 105 ms and a green dashboard. Your user request calls a hundred of them and waits for all of them, and its **median** is 129 ms — worse than the p99 of every single service it touched, because the chance that at least one of 100 calls lands in its own slow 1% is 63.7%. Nobody's dashboard shows this, because the problem is not in any one service; it is in the multiplication. This lesson measures that arithmetic, then buys the tail back: hedging at the p95 took the same 100-way request from a 128.7 ms median to 35.7 ms for **5% more backend load** — and then shows you the two ways that same trick kills you.

**Type:** Build
**Languages:** Python
**Prerequisites:** [Load Balancing Algorithms](../03-load-balancing-algorithms/), [Backpressure, Queueing & Load Shedding](../../08-concurrency-and-performance/11-backpressure-and-load-shedding/), [Sharding the Data Tier](../08-sharding-the-data-tier/)
**Time:** ~80 minutes

## The Problem

It is 09:40 on a Tuesday and you are in a meeting that has happened four times already this quarter.

The product is a search page. A user types a query, and your search-aggregator service fans that query out to **100 index shards** — the corpus does not fit on one machine, so each shard holds 1% of the documents, every shard scores the query against its own slice, and the aggregator merges 100 partial result sets into one ranked page. This is not an exotic design. It is how every search engine, every timeline, every "recommended for you" row, and every dashboard-with-widgets is built. **The request cannot finish until the slowest shard answers**, because a search result missing 1% of the corpus is a wrong search result.

The complaint on the table is that the search page feels slow. Not broken — slow. Users say "sometimes it takes a second." Support has forty tickets.

So you do the responsible thing and you look at the shards. There are a hundred teams' worth of dashboards, and they are all the same, and they are all **green**:

- p50 (the median): **9.2 ms**
- p90: **17.3 ms**
- p99: **105.0 ms**
- p99.9: **384.6 ms**

Every shard is meeting its Service Level Objective (SLO — the latency target a team commits to). The SLO says "99% of shard queries complete in under 150 ms," and every shard is comfortably inside it. There is no error rate to speak of. There is no saturated CPU. There is no shard that is obviously the problem, because there **is** no shard that is the problem.

Now measure the thing the user actually experiences. Not the shard. The request.

```text
  one shard call        p50    9.2 ms      p99  105.0 ms
  the 100-way request   p50  129.0 ms      p99 1583.9 ms
```

Read that twice. **The median user request is slower than the p99 of every backend it called.** Not the p99 of the request — the *median*. Half of all searches are having an experience worse than the worst 1% of any individual shard. And the request's p99 is 1.58 seconds, which is where the forty support tickets came from.

Here is the arithmetic that produced it, and it is arithmetic, not a bug. Each shard call has a 1% chance of exceeding 105 ms — that is what "p99 = 105 ms" *means*. The request must wait for all 100. The chance that **at least one** of the 100 lands in its own slow 1% is:

```text
1 - (1 - 0.01)^100  =  1 - 0.99^100  =  1 - 0.366  =  63.4%
```

Sixty-three percent of user requests contain at least one call that its own owner would classify as a tail event. The measured figure over 20,000 simulated requests is **63.7%**. So the "rare" 1% case is not rare from where the user is standing. It is the common case. It is the *majority* case.

And now the part that makes this a meeting rather than a ticket. **There is no owner.** You cannot file a bug against shard 47, because shard 47 is fine; it was slow on this request and fast on the next thousand. You cannot file a bug against the aggregator, because the aggregator did nothing but wait. Every team's dashboard is green, every team's SLO is met, every team is correct, and the product is slow. The failure lives in the *composition*, and no team owns the composition.

You will hear the obvious proposal in this meeting, and it is wrong: "let's get the shard p99 down." Hold that thought — the whole first half of this lesson is about why that is the expensive road, and what the cheap one looks like.

## The Concept

The canonical treatment is Dean, J. and Barroso, L. A., **"The Tail at Scale"**, *Communications of the ACM* 56(2), pp. 74–80, 2013 — written out of Google's experience running exactly the fan-out services above. Nearly everything in this lesson is either in that paper or a direct consequence of it, and it is eight pages long and worth reading in full.

### The fan-out arithmetic

Start from first principles, because the whole lesson is a consequence of one line.

Take a single backend call. Let **p** be the probability that it exceeds some latency **L**. If your backend's p99 is 105 ms, then by definition p = 0.01 at L = 105 ms. Now issue **N** such calls, independently, and wait for all of them.

The probability that a *particular* call comes in under L is `(1 − p)`. The probability that **all N** come in under L — which is what "the request was fast" requires — is `(1 − p)^N`, because they are independent. So the probability that **at least one** exceeds L is the complement:

```text
P(at least one call exceeds L)  =  1 - (1 - p)^N
```

That is the entire result. Everything else is reading the table it produces. For p = 0.01:

| N (fan-out width) | 1 − (1−p)^N | in words |
|---:|---:|---|
| 1 | **1.0%** | the SLO you signed |
| 10 | **9.6%** | one request in ten |
| 100 | **63.4%** | the majority of requests |
| 1000 | **99.996%** | effectively all of them |

The measured run agrees to within noise: 0.9%, 5.0% (N = 5), 18.0% (N = 20), **63.7%** (N = 100), 99.3% (N = 500) against theoretical 1.0%, 4.9%, 18.2%, 63.4%, 99.3%.

Now the sharper framing, which is the one to carry around. A fan-out request's latency is not the *average* of its calls. It is the **maximum**:

```text
request_latency  =  max(call_1, call_2, ..., call_N)
```

And the expected maximum of N samples drawn from a distribution sits far into that distribution's tail — that is what a maximum *is*. Concretely: the median of the max of 100 samples is the point where `F(x)^100 = 0.5`, i.e. `F(x) = 0.5^(1/100) = 0.9931`. **The median of a 100-way fan-out is the 99.31st percentile of one backend call.** Your p99 has become everyone's median, exactly as advertised.

Run the same logic the other way and you get the most useful sentence in this section. One backend's **p99.9** — the 385 ms figure that lives in a footnote of a quarterly review, if it is measured at all — is the point where `0.999^100 = 0.905`, i.e. the **p90.5** of a 100-way fan-out. Measured: **p90.5**. A number you treat as a curiosity for one service is a number that one user in ten meets for the composed request.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 468" width="100%" style="max-width:840px" role="img" aria-label="One user request fanning out to one hundred backend shards, drawn as one hundred vertical bars whose height is that call's measured latency on a logarithmic scale. Ninety-nine bars sit near the nine millisecond median; a single red bar reaches 599 milliseconds and determines the whole request, because the request must wait for all one hundred. A panel on the right tabulates the measured fan-out percentiles for N of one, five, twenty, one hundred and five hundred, showing the median hundred-way request at 129 milliseconds against a backend p99 of 105 milliseconds, and the arithmetic one minus zero point nine nine to the hundredth power equals 63.4 percent.">
  <defs>
    <marker id="p11-11-a1" markerWidth="10" markerHeight="10" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker>
  </defs>
  <text x="440" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">Your p99 is everyone&#8217;s median: the slowest of 100 calls IS the request</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <text x="62" y="52" font-size="10.5" fill="currentColor" opacity="0.85">one user request &#8594; 100 shards, measured latency per call (log scale)</text>

    <g fill="none" stroke="currentColor" stroke-width="1.4"><path d="M62 300 L 528 300"/></g>
    <rect x="62.0" y="241.4" width="3.47" height="58.6" fill="#0fa07f" fill-opacity="0.5"/><rect x="66.6" y="282.6" width="3.47" height="17.4" fill="#0fa07f" fill-opacity="0.5"/><rect x="71.2" y="273.5" width="3.47" height="26.5" fill="#0fa07f" fill-opacity="0.5"/><rect x="75.9" y="235.1" width="3.47" height="64.9" fill="#0fa07f" fill-opacity="0.5"/><rect x="80.5" y="246.5" width="3.47" height="53.5" fill="#0fa07f" fill-opacity="0.5"/><rect x="85.1" y="259.5" width="3.47" height="40.5" fill="#0fa07f" fill-opacity="0.5"/><rect x="89.7" y="296.2" width="3.47" height="3.8" fill="#0fa07f" fill-opacity="0.5"/><rect x="94.3" y="248.8" width="3.47" height="51.2" fill="#0fa07f" fill-opacity="0.5"/><rect x="99.0" y="265.9" width="3.47" height="34.1" fill="#0fa07f" fill-opacity="0.5"/><rect x="103.6" y="296.2" width="3.47" height="3.8" fill="#0fa07f" fill-opacity="0.5"/><rect x="108.2" y="262.7" width="3.47" height="37.3" fill="#0fa07f" fill-opacity="0.5"/><rect x="112.8" y="251.8" width="3.47" height="48.2" fill="#0fa07f" fill-opacity="0.5"/><rect x="117.4" y="263.1" width="3.47" height="36.9" fill="#0fa07f" fill-opacity="0.5"/><rect x="122.1" y="267.4" width="3.47" height="32.6" fill="#0fa07f" fill-opacity="0.5"/><rect x="126.7" y="252.7" width="3.47" height="47.3" fill="#0fa07f" fill-opacity="0.5"/><rect x="131.3" y="261.8" width="3.47" height="38.2" fill="#0fa07f" fill-opacity="0.5"/><rect x="135.9" y="112.2" width="3.47" height="187.8" fill="#d64545" fill-opacity="0.95"/><rect x="140.5" y="276.3" width="3.47" height="23.7" fill="#0fa07f" fill-opacity="0.5"/><rect x="145.2" y="253.9" width="3.47" height="46.1" fill="#0fa07f" fill-opacity="0.5"/><rect x="149.8" y="296.2" width="3.47" height="3.8" fill="#0fa07f" fill-opacity="0.5"/><rect x="154.4" y="270.7" width="3.47" height="29.3" fill="#0fa07f" fill-opacity="0.5"/><rect x="159.0" y="245.1" width="3.47" height="54.9" fill="#0fa07f" fill-opacity="0.5"/><rect x="163.6" y="240.4" width="3.47" height="59.6" fill="#0fa07f" fill-opacity="0.5"/><rect x="168.3" y="280.7" width="3.47" height="19.3" fill="#0fa07f" fill-opacity="0.5"/><rect x="172.9" y="296.2" width="3.47" height="3.8" fill="#0fa07f" fill-opacity="0.5"/><rect x="177.5" y="272.8" width="3.47" height="27.2" fill="#0fa07f" fill-opacity="0.5"/><rect x="182.1" y="247.3" width="3.47" height="52.7" fill="#0fa07f" fill-opacity="0.5"/><rect x="186.7" y="273.0" width="3.47" height="27.0" fill="#0fa07f" fill-opacity="0.5"/><rect x="191.4" y="281.7" width="3.47" height="18.3" fill="#0fa07f" fill-opacity="0.5"/><rect x="196.0" y="285.5" width="3.47" height="14.5" fill="#0fa07f" fill-opacity="0.5"/><rect x="200.6" y="246.5" width="3.47" height="53.5" fill="#0fa07f" fill-opacity="0.5"/><rect x="205.2" y="263.3" width="3.47" height="36.7" fill="#0fa07f" fill-opacity="0.5"/><rect x="209.8" y="257.6" width="3.47" height="42.4" fill="#0fa07f" fill-opacity="0.5"/><rect x="214.5" y="268.6" width="3.47" height="31.4" fill="#0fa07f" fill-opacity="0.5"/><rect x="219.1" y="256.8" width="3.47" height="43.2" fill="#0fa07f" fill-opacity="0.5"/><rect x="223.7" y="264.8" width="3.47" height="35.2" fill="#0fa07f" fill-opacity="0.5"/><rect x="228.3" y="274.4" width="3.47" height="25.6" fill="#0fa07f" fill-opacity="0.5"/><rect x="232.9" y="271.9" width="3.47" height="28.1" fill="#0fa07f" fill-opacity="0.5"/><rect x="237.6" y="296.2" width="3.47" height="3.8" fill="#0fa07f" fill-opacity="0.5"/><rect x="242.2" y="296.2" width="3.47" height="3.8" fill="#0fa07f" fill-opacity="0.5"/><rect x="246.8" y="292.4" width="3.47" height="7.6" fill="#0fa07f" fill-opacity="0.5"/><rect x="251.4" y="272.7" width="3.47" height="27.3" fill="#0fa07f" fill-opacity="0.5"/><rect x="256.0" y="237.6" width="3.47" height="62.4" fill="#0fa07f" fill-opacity="0.5"/><rect x="260.7" y="262.7" width="3.47" height="37.3" fill="#0fa07f" fill-opacity="0.5"/><rect x="265.3" y="261.5" width="3.47" height="38.5" fill="#0fa07f" fill-opacity="0.5"/><rect x="269.9" y="273.5" width="3.47" height="26.5" fill="#0fa07f" fill-opacity="0.5"/><rect x="274.5" y="278.2" width="3.47" height="21.8" fill="#0fa07f" fill-opacity="0.5"/><rect x="279.1" y="276.7" width="3.47" height="23.3" fill="#0fa07f" fill-opacity="0.5"/><rect x="283.8" y="264.7" width="3.47" height="35.3" fill="#0fa07f" fill-opacity="0.5"/><rect x="288.4" y="268.0" width="3.47" height="32.0" fill="#0fa07f" fill-opacity="0.5"/><rect x="293.0" y="286.3" width="3.47" height="13.7" fill="#0fa07f" fill-opacity="0.5"/><rect x="297.6" y="251.6" width="3.47" height="48.4" fill="#0fa07f" fill-opacity="0.5"/><rect x="302.2" y="254.5" width="3.47" height="45.5" fill="#0fa07f" fill-opacity="0.5"/><rect x="306.9" y="267.2" width="3.47" height="32.8" fill="#0fa07f" fill-opacity="0.5"/><rect x="311.5" y="265.2" width="3.47" height="34.8" fill="#0fa07f" fill-opacity="0.5"/><rect x="316.1" y="265.6" width="3.47" height="34.4" fill="#0fa07f" fill-opacity="0.5"/><rect x="320.7" y="252.1" width="3.47" height="47.9" fill="#0fa07f" fill-opacity="0.5"/><rect x="325.3" y="233.7" width="3.47" height="66.3" fill="#0fa07f" fill-opacity="0.5"/><rect x="330.0" y="272.3" width="3.47" height="27.7" fill="#0fa07f" fill-opacity="0.5"/><rect x="334.6" y="296.2" width="3.47" height="3.8" fill="#0fa07f" fill-opacity="0.5"/><rect x="339.2" y="275.8" width="3.47" height="24.2" fill="#0fa07f" fill-opacity="0.5"/><rect x="343.8" y="274.8" width="3.47" height="25.2" fill="#0fa07f" fill-opacity="0.5"/><rect x="348.4" y="246.5" width="3.47" height="53.5" fill="#0fa07f" fill-opacity="0.5"/><rect x="353.1" y="269.6" width="3.47" height="30.4" fill="#0fa07f" fill-opacity="0.5"/><rect x="357.7" y="283.9" width="3.47" height="16.1" fill="#0fa07f" fill-opacity="0.5"/><rect x="362.3" y="266.5" width="3.47" height="33.5" fill="#0fa07f" fill-opacity="0.5"/><rect x="366.9" y="279.8" width="3.47" height="20.2" fill="#0fa07f" fill-opacity="0.5"/><rect x="371.5" y="291.6" width="3.47" height="8.4" fill="#0fa07f" fill-opacity="0.5"/><rect x="376.2" y="287.1" width="3.47" height="12.9" fill="#0fa07f" fill-opacity="0.5"/><rect x="380.8" y="260.2" width="3.47" height="39.8" fill="#0fa07f" fill-opacity="0.5"/><rect x="385.4" y="280.8" width="3.47" height="19.2" fill="#0fa07f" fill-opacity="0.5"/><rect x="390.0" y="247.8" width="3.47" height="52.2" fill="#0fa07f" fill-opacity="0.5"/><rect x="394.6" y="259.5" width="3.47" height="40.5" fill="#0fa07f" fill-opacity="0.5"/><rect x="399.3" y="294.0" width="3.47" height="6.0" fill="#0fa07f" fill-opacity="0.5"/><rect x="403.9" y="283.1" width="3.47" height="16.9" fill="#0fa07f" fill-opacity="0.5"/><rect x="408.5" y="250.6" width="3.47" height="49.4" fill="#0fa07f" fill-opacity="0.5"/><rect x="413.1" y="287.8" width="3.47" height="12.2" fill="#0fa07f" fill-opacity="0.5"/><rect x="417.7" y="278.3" width="3.47" height="21.7" fill="#0fa07f" fill-opacity="0.5"/><rect x="422.4" y="274.4" width="3.47" height="25.6" fill="#0fa07f" fill-opacity="0.5"/><rect x="427.0" y="262.3" width="3.47" height="37.7" fill="#0fa07f" fill-opacity="0.5"/><rect x="431.6" y="234.5" width="3.47" height="65.5" fill="#0fa07f" fill-opacity="0.5"/><rect x="436.2" y="295.5" width="3.47" height="4.5" fill="#0fa07f" fill-opacity="0.5"/><rect x="440.8" y="284.6" width="3.47" height="15.4" fill="#0fa07f" fill-opacity="0.5"/><rect x="445.5" y="268.2" width="3.47" height="31.8" fill="#0fa07f" fill-opacity="0.5"/><rect x="450.1" y="253.2" width="3.47" height="46.8" fill="#0fa07f" fill-opacity="0.5"/><rect x="454.7" y="258.2" width="3.47" height="41.8" fill="#0fa07f" fill-opacity="0.5"/><rect x="459.3" y="258.4" width="3.47" height="41.6" fill="#0fa07f" fill-opacity="0.5"/><rect x="463.9" y="296.2" width="3.47" height="3.8" fill="#0fa07f" fill-opacity="0.5"/><rect x="468.6" y="271.9" width="3.47" height="28.1" fill="#0fa07f" fill-opacity="0.5"/><rect x="473.2" y="259.5" width="3.47" height="40.5" fill="#0fa07f" fill-opacity="0.5"/><rect x="477.8" y="274.4" width="3.47" height="25.6" fill="#0fa07f" fill-opacity="0.5"/><rect x="482.4" y="243.8" width="3.47" height="56.2" fill="#0fa07f" fill-opacity="0.5"/><rect x="487.0" y="274.3" width="3.47" height="25.7" fill="#0fa07f" fill-opacity="0.5"/><rect x="491.7" y="258.4" width="3.47" height="41.6" fill="#0fa07f" fill-opacity="0.5"/><rect x="496.3" y="284.2" width="3.47" height="15.8" fill="#0fa07f" fill-opacity="0.5"/><rect x="500.9" y="270.1" width="3.47" height="29.9" fill="#0fa07f" fill-opacity="0.5"/><rect x="505.5" y="256.6" width="3.47" height="43.4" fill="#0fa07f" fill-opacity="0.5"/><rect x="510.1" y="254.0" width="3.47" height="46.0" fill="#0fa07f" fill-opacity="0.5"/><rect x="514.8" y="271.5" width="3.47" height="28.5" fill="#0fa07f" fill-opacity="0.5"/><rect x="519.4" y="253.5" width="3.47" height="46.5" fill="#0fa07f" fill-opacity="0.5"/>

    <path d="M62 268.9 L 524 268.9" fill="none" stroke="#0fa07f" stroke-width="1.2" stroke-dasharray="4 5" opacity="0.8"/> <path d="M62 177.5 L 524 177.5" fill="none" stroke="#e0930f" stroke-width="1.2" stroke-dasharray="4 5" opacity="0.9"/> <path d="M62 112.2 L 524 112.2" fill="none" stroke="#d64545" stroke-width="1.6" stroke-dasharray="6 4"/>

    <g font-size="9.5">
      <text x="530" y="272" fill="#0fa07f" font-weight="700">p50 9.2</text> <text x="530" y="181" fill="#e0930f" font-weight="700">p99 105</text> <text x="530" y="109" fill="#d64545" font-weight="700">599 ms</text> <text x="530" y="121" fill="#d64545" font-size="8.5">this call</text>
    </g>

    <path d="M196 96 L 152 108" fill="none" stroke="#d64545" stroke-width="1.5" marker-end="url(#p11-11-a1)"/> <text x="200" y="86" font-size="10" font-weight="700" fill="#d64545">1 call of 100 landed in its own slow 1%</text> <text x="200" y="99" font-size="9.5" fill="currentColor" opacity="0.9">every other call answered in under 24 ms</text>
    <text x="62" y="318" font-size="9.5" fill="currentColor" opacity="0.7">shard 1</text> <text x="524" y="318" font-size="9.5" text-anchor="end" fill="currentColor" opacity="0.7">shard 100</text>

    <g fill="none" stroke-width="1.8" stroke-linejoin="round">
      <rect x="612" y="44" width="254" height="276" rx="10" fill="#3553ff" fill-opacity="0.09" stroke="#3553ff"/>
    </g>
    <g fill="currentColor">
      <text x="628" y="64" font-size="10.5" font-weight="700" fill="#3553ff">MEASURED, 200k samples</text> <text x="628" y="84" font-size="9" font-weight="700" opacity="0.7">N</text> <text x="704" y="84" font-size="9" font-weight="700" opacity="0.7" text-anchor="end">user p50</text> <text x="856" y="84" font-size="9" font-weight="700" opacity="0.7" text-anchor="end">P(&#8805;1 over p99)</text>
      <text x="628" y="102" font-size="10">1</text><text x="704" y="102" font-size="10" text-anchor="end">9.1 ms</text><text x="856" y="102" font-size="10" text-anchor="end">0.9%</text> <text x="628" y="120" font-size="10">5</text><text x="704" y="120" font-size="10" text-anchor="end">15.9 ms</text><text x="856" y="120" font-size="10" text-anchor="end">5.0%</text> <text x="628" y="138" font-size="10">20</text><text x="704" y="138" font-size="10" text-anchor="end">29.5 ms</text><text x="856" y="138" font-size="10" text-anchor="end">18.0%</text>
      <text x="628" y="156" font-size="10" font-weight="700" fill="#d64545">100</text><text x="704" y="156" font-size="10" text-anchor="end" font-weight="700" fill="#d64545">129.0 ms</text><text x="856" y="156" font-size="10" text-anchor="end" font-weight="700" fill="#d64545">63.7%</text> <text x="628" y="174" font-size="10">500</text><text x="704" y="174" font-size="10" text-anchor="end">323.0 ms</text><text x="856" y="174" font-size="10" text-anchor="end">99.3%</text>
    </g>
    <path d="M624 188 L 856 188" fill="none" stroke="currentColor" stroke-width="1" opacity="0.35"/>
    <g fill="currentColor">
      <text x="628" y="208" font-size="10" font-weight="700">the arithmetic, exactly:</text> <text x="628" y="226" font-size="10.5" fill="#3553ff" font-weight="700">1 &#8722; (1&#8722;p)&#8319;</text> <text x="628" y="244" font-size="10">1 &#8722; 0.99&#185;&#8304;&#8304; = 63.4%</text> <text x="628" y="258" font-size="9" opacity="0.8">measured: 63.7%</text>
      <text x="628" y="278" font-size="10" opacity="0.95">backend p99 = 105.0 ms</text> <text x="628" y="294" font-size="10" font-weight="700" fill="#d64545">user p50&#8195;&#8195;&#8195;= 129.0 ms</text> <text x="628" y="310" font-size="10" font-weight="700" fill="#d64545">= 1.23&#215; the backend p99</text>
    </g>

    <g fill="none" stroke-width="1.8" stroke-linejoin="round">
      <rect x="62" y="340" width="804" height="76" rx="10" fill="#e0930f" fill-opacity="0.10" stroke="#e0930f"/>
    </g>
    <g fill="currentColor">
      <text x="78" y="360" font-size="11" font-weight="700" fill="#e0930f">Why no dashboard shows this</text> <text x="78" y="378" font-size="10" opacity="0.95">Every backend meets its SLO. Every backend&#8217;s p99 is 105 ms and its dashboard is green.</text> <text x="78" y="394" font-size="10" opacity="0.95">The request&#8217;s latency is the MAXIMUM of 100 samples, and the expected maximum of 100 samples</text> <text x="78" y="410" font-size="10" opacity="0.95">sits far into the tail: one backend&#8217;s p99.9 (385 ms) is the p90.5 of a 100-way fan-out.</text>
    </g>
    <text x="440" y="440" font-size="11" text-anchor="middle" fill="currentColor" opacity="0.9">The problem is not in any one service. It is in the multiplication &#8212; and nobody owns the multiplication.</text>
  </g>
</svg>
```

This reframes what an SLO on a backend service even means. "99% under 105 ms" sounds like a promise about how often users wait 105 ms. At a fan-out of 100 it is nothing of the kind — it is a promise that **63% of composed requests will contain a 105 ms call**. If you own a service that is called in a fan-out, your p99 is not your tail. It is your caller's body. The percentile that matters to your caller is roughly your `p(100 − 100/N)`: at N = 100, your p99.9; at N = 1000, your p99.99. Almost nobody measures that far out, which is why almost nobody sees this coming.

### Where the variability comes from

You cannot fix what you cannot name, so here is the honest catalogue of what actually produces those slow calls. Almost none of it is your code being wrong.

- **Queueing.** The dominant cause at any real utilization. Phase 8 Lesson 11 derived `W = S/(1−ρ)` and showed the knee; a shared machine at ρ = 0.85 has a waiting-time distribution with a long right tail whatever your code does.
- **Garbage collection pauses.** A generational collector will eventually do a collection that is 100× the usual one. In a managed runtime this is not avoidable, only deferrable.
- **Background daemons and cron.** Log rotation, metrics agents, security scanners, config reloaders, the backup job at :00.
- **Contention from co-tenants.** On shared hardware your neighbour's workload consumes L3 cache, memory bandwidth and disk queue depth. Your process is not slower; your *machine* is. This is invisible from inside your container.
- **Power and thermal throttling.** A CPU that hits its thermal envelope drops clock. Nothing in your stack reports this as latency.
- **Disk and SSD garbage collection.** An SSD erase block cycle stalls writes for milliseconds at unpredictable times. Compaction in an LSM-tree store does the same at a larger scale.
- **Network congestion and retransmits.** One dropped packet costs you a retransmission timeout — often orders of magnitude more than the request itself.
- **JIT warmup and cold starts.** A freshly deployed or freshly scaled instance is slow for its first thousand requests, and autoscaling means you always have some.
- **Periodic maintenance.** Index rebuilds, compactions, vacuum, cache warming, certificate rotation.

Two things to notice. First, most of these are **shared-resource interference** — the resource being contended is shared between processes, tenants, or machines. Second, and this is the thread that runs to the end of the lesson: shared causes are **correlated**. A rack-level thermal event, a synchronised cron, a bad config push, a compaction triggered by the same write volume on every replica — these do not hit one machine at a time. They hit many at once. Hold that thought; Section 5 of the code is built to measure exactly what correlation does to everything you are about to learn.

### Why "just make p99 better" fails

Back to the meeting, and the obvious proposal: drive the shard p99 down.

You can do some of this. You should do some of this. But look at what the list above demands. To meaningfully reduce the *tail* you would have to eliminate GC pauses, evict your co-tenants, control the thermal behaviour of the rack, stop the SSD from doing its own housekeeping, and prevent the network from ever dropping a packet — everywhere, on every machine, permanently. Each of those is a project. Several are impossible. And you would have to keep them all fixed forever, because the arithmetic is unforgiving: at N = 100, halving p from 1% to 0.5% takes the "at least one slow call" probability from 63.4% only to **39.4%**. You did enormous work and the majority case merely became a large minority case.

This is where Dean & Barroso make the move that defines the field, and it is the thesis of this lesson:

> **Stop trying to eliminate variability. Build a system that produces a predictable whole out of unpredictable parts.**

They draw the analogy explicitly, and it is the right one: this is the same move as building **reliable storage out of unreliable disks**. Nobody makes disks that never fail. We accept that disks fail at some rate and build RAID, replication and checksums on top, so that the *storage system* has a failure rate many orders of magnitude better than any disk in it. A **tail-tolerant** system does that for latency: it accepts that any individual call may be slow at some rate, and composes calls so that the *request* is fast anyway.

That reframing has a practical consequence you can act on this afternoon. Tail tolerance is mostly implemented **in the caller**, not the callee — it is about how requests are *issued*, not how they are served. Which means you can have it without a hundred teams agreeing to anything.

### Hedged requests

Here is the technique, and it is almost embarrassingly simple.

Send the request to one replica. If it has not answered by some delay **D**, send a *second copy* of the same request to a **different** replica. Take whichever answers first, and cancel the other.

The insight that makes it work is about who pays. Set D at a **high percentile of the normal latency distribution** — the p95, say. Then by construction only about 5% of requests are still outstanding when the timer fires, so only about 5% get a second copy. **The extra load is ~5%. The tail improvement is enormous**, because the 5% you duplicated is precisely the 5% that was going badly, and a fresh replica is overwhelmingly likely to be having a better minute than the one that is currently stalled.

Measured over 200,000 single calls with the delay set at the measured p95 (22.5 ms):

```text
                    p50      p99    p99.9   hedged   extra load
no hedge            9.1    103.3    386.9     0.0%         0.0%
hedge @ p95         9.2     33.9     52.7     5.0%         5.0%
```

The p99 improves **3.05×** and the p99.9 improves **7.35×**, for 5.0% more backend calls. The median is untouched (9.1 → 9.2 ms) — which is exactly right, because the median request was never slow and never got hedged.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 486" width="100%" style="max-width:840px" role="img" aria-label="A timeline of a hedged request. Without hedging, replica A hiccups and the user waits 240 milliseconds. With hedging, the client sends the request to replica A at time zero, waits until the 22.5 millisecond p95 delay, then sends a second copy to replica B; replica B answers at 35.5 milliseconds and replica A's copy is cancelled. A measured table below shows the single-call p99 falling from 103.3 to 33.9 milliseconds and p99.9 from 386.9 to 52.7 milliseconds for 5 percent extra load, and the hundred-way fan-out p50 falling from 128.7 to 35.7 milliseconds.">
  <defs>
    <marker id="p11-11-a2" markerWidth="10" markerHeight="10" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker>
    <marker id="p11-11-a2g" markerWidth="10" markerHeight="10" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#0fa07f"/></marker>
  </defs>
  <text x="440" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">Hedged requests: a second copy, only for the slow 5%</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">

    <text x="96" y="54" font-size="10.5" fill="currentColor" opacity="0.85">one request, one slow replica &#8212; the same 240 ms hiccup, handled two ways</text>

    <text x="96" y="82" font-size="10" font-weight="700" fill="#d64545">WITHOUT HEDGING</text> <rect x="96" y="90" width="558" height="24" rx="5" fill="#d64545" fill-opacity="0.14" stroke="#d64545" stroke-width="1.6"/> <text x="106" y="106" font-size="9.5" fill="currentColor">replica A &#8212; hiccup (GC pause / compaction / co-tenant)</text> <text x="662" y="106" font-size="10" font-weight="700" fill="#d64545">user waits 240 ms</text>

    <text x="96" y="146" font-size="10" font-weight="700" fill="#0fa07f">WITH HEDGING</text> <text x="196" y="146" font-size="9.5" font-weight="700" fill="#0fa07f">35.5 ms &#8212; first response wins, twin cancelled</text> <rect x="96" y="154" width="83" height="24" rx="5" fill="#3553ff" fill-opacity="0.14" stroke="#3553ff" stroke-width="1.6"/>
    <path d="M179 154 L 654 154 L 654 178 L 179 178 Z" fill="#7f7f7f" fill-opacity="0.07" stroke="currentColor" stroke-width="1.2" stroke-dasharray="5 4" stroke-opacity="0.5"/> <text x="106" y="170" font-size="9.5" fill="currentColor">replica A</text> <text x="360" y="170" font-size="9" fill="currentColor" opacity="0.7">cancelled at 35.5 ms &#8212; would have run to 240 ms</text>

    <rect x="148" y="190" width="31" height="24" rx="5" fill="#0fa07f" fill-opacity="0.18" stroke="#0fa07f" stroke-width="1.6"/> <text x="188" y="206" font-size="9.5" fill="currentColor">replica B &#8212; the hedge, answers in 13 ms</text>

    <path d="M148 184 L 148 226" fill="none" stroke="#e0930f" stroke-width="1.6" stroke-dasharray="5 4"/> <path d="M179 148 L 179 226" fill="none" stroke="#0fa07f" stroke-width="1.8"/>

    <text x="148" y="242" font-size="9.5" text-anchor="middle" font-weight="700" fill="#e0930f">22.5 ms</text> <text x="148" y="254" font-size="8.5" text-anchor="middle" fill="#e0930f">hedge fires</text> <text x="148" y="265" font-size="8.5" text-anchor="middle" fill="#e0930f">(the p95)</text>

    <g fill="none" stroke="currentColor" stroke-width="1.3"><path d="M96 226 L 700 226"/></g>
    <g fill="none" stroke="currentColor" stroke-width="1" opacity="0.45">
      <path d="M96 226 L 96 231"/><path d="M212 226 L 212 231"/><path d="M328 226 L 328 231"/><path d="M444 226 L 444 231"/><path d="M560 226 L 560 231"/><path d="M676 226 L 676 231"/>
    </g>
    <g fill="currentColor" font-size="9" opacity="0.7" text-anchor="middle">
      <text x="96" y="243">0</text><text x="212" y="243">50</text><text x="328" y="243">100</text><text x="444" y="243">150</text><text x="560" y="243">200</text><text x="676" y="243">250 ms</text>
    </g>

    <g fill="none" stroke-width="1.8" stroke-linejoin="round">
      <rect x="62" y="276" width="804" height="142" rx="10" fill="#3553ff" fill-opacity="0.07" stroke="#3553ff"/>
    </g>
    <text x="78" y="296" font-size="10.5" font-weight="700" fill="#3553ff">MEASURED &#8212; 200,000 single calls and 20,000 hundred-way fan-outs</text>
    <g fill="currentColor" font-size="9" font-weight="700" opacity="0.7">
      <text x="78" y="316">configuration</text> <text x="470" y="316" text-anchor="end">p50</text> <text x="574" y="316" text-anchor="end">p99</text> <text x="678" y="316" text-anchor="end">p99.9</text> <text x="850" y="316" text-anchor="end">extra backend load</text>
    </g>
    <path d="M74 324 L 854 324" fill="none" stroke="currentColor" stroke-width="1" opacity="0.3"/>
    <g fill="currentColor" font-size="10">
      <text x="78" y="342">one call, no hedge</text> <text x="470" y="342" text-anchor="end">9.1 ms</text><text x="574" y="342" text-anchor="end">103.3 ms</text><text x="678" y="342" text-anchor="end">386.9 ms</text><text x="850" y="342" text-anchor="end">&#8212;</text> <text x="78" y="362" font-weight="700" fill="#0fa07f">one call, hedge @ p95</text>
      <text x="470" y="362" text-anchor="end" font-weight="700" fill="#0fa07f">9.2 ms</text><text x="574" y="362" text-anchor="end" font-weight="700" fill="#0fa07f">33.9 ms</text><text x="678" y="362" text-anchor="end" font-weight="700" fill="#0fa07f">52.7 ms</text><text x="850" y="362" text-anchor="end" font-weight="700" fill="#0fa07f">+5.0%</text> <text x="78" y="384">100-way fan-out, no hedge</text>
      <text x="470" y="384" text-anchor="end">128.7 ms</text><text x="574" y="384" text-anchor="end">1583.9 ms</text><text x="678" y="384" text-anchor="end">3000.0 ms</text><text x="850" y="384" text-anchor="end">&#8212;</text> <text x="78" y="404" font-weight="700" fill="#0fa07f">100-way fan-out, hedge @ p95</text>
      <text x="470" y="404" text-anchor="end" font-weight="700" fill="#0fa07f">35.7 ms</text><text x="574" y="404" text-anchor="end" font-weight="700" fill="#0fa07f">116.5 ms</text><text x="678" y="404" text-anchor="end" font-weight="700" fill="#0fa07f">199.0 ms</text><text x="850" y="404" text-anchor="end" font-weight="700" fill="#0fa07f">+5.0%</text>
    </g>
    <text x="440" y="444" font-size="11" text-anchor="middle" fill="currentColor" opacity="0.9">Only the slow 5% get a second copy, so the load cost is ~5% &#8212; and the 100-way median falls 3.6&#215;.</text> <text x="440" y="464" font-size="10.5" text-anchor="middle" fill="#d64545" font-weight="700">Hedge only idempotent reads, and always give it a budget.</text>
  </g>
</svg>
```

Now apply it where it matters, to every shard of the 100-way fan-out. This is the headline result of the lesson:

```text
100-way fan-out    p50      p99      p99.9    backend calls per shard
no hedge         128.7   1583.9     3000.0    1.000
hedge @ p95       35.7    116.5      199.0    1.050
```

The median composed request goes from **128.7 ms to 35.7 ms** — a 3.6× improvement in the typical user's experience — and the p99 from **1583.9 ms to 116.5 ms**, a 13.6× improvement, for **5% more load**. That trade is not close. There is no capacity purchase, no rewrite, and no hundred-team coordination that buys a 13× tail improvement for 5%.

**Choosing D is the whole engineering decision**, so measure the trade rather than guessing. Sweeping the delay across percentiles of the call distribution:

| delay set at | delay | p99 | p99.9 | extra load |
|---|---:|---:|---:|---:|
| (no hedging) | — | 103.3 ms | 386.9 ms | 0% |
| p99 | 105.0 ms | 105.3 ms | 121.0 ms | **1.0%** |
| **p95** | **22.5 ms** | **34.2 ms** | **54.3 ms** | **5.0%** |
| p90 | 17.3 ms | 29.1 ms | 43.4 ms | 10.0% |
| p75 | 12.6 ms | 25.2 ms | 40.6 ms | 25.0% |
| p50 | 9.2 ms | 22.9 ms | 37.8 ms | 49.9% |

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 424" width="100%" style="max-width:840px" role="img" aria-label="A measured curve of tail latency against extra backend load as the hedge delay is swept from the p99 down to the p50 of the call distribution. With no hedging the p99.9 is 386.9 milliseconds. One percent of extra load drops it to 121 milliseconds, five percent drops it to 54.3 milliseconds, and everything beyond five percent is nearly flat, reaching only 37.8 milliseconds at fifty percent extra load. The recommended operating point, a hedge delay set at the p95, is ringed at five percent extra load.">
  <defs>
    <marker id="p11-11-a3" markerWidth="10" markerHeight="10" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker>
  </defs>
  <text x="440" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">The knee is at 5%: almost all the tail, for almost none of the load</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">

    <g fill="none" stroke="currentColor" stroke-width="1.5">
      <path d="M112 306 L 520 306"/><path d="M112 306 L 112 82"/>
    </g>
    <g fill="none" stroke="currentColor" stroke-width="1" opacity="0.35">
      <path d="M190.5 306 L 190.5 311"/><path d="M268.9 306 L 268.9 311"/><path d="M347.4 306 L 347.4 311"/><path d="M425.8 306 L 425.8 311"/><path d="M504.2 306 L 504.2 311"/> <path d="M107 251 L 112 251"/><path d="M107 196 L 112 196"/><path d="M107 141 L 112 141"/><path d="M107 86 L 112 86"/>
    </g>
    <g fill="none" stroke="currentColor" stroke-width="1" opacity="0.16">
      <path d="M112 251 L 520 251"/><path d="M112 196 L 520 196"/><path d="M112 141 L 520 141"/><path d="M112 86 L 520 86"/>
    </g>

    <polyline points="112.0,93.2 119.8,239.5 151.2,276.1 190.5,282.1 308.2,283.7 503.5,285.2" fill="none" stroke="#e0930f" stroke-width="2.6" stroke-linejoin="round"/> <polyline points="112.0,249.2 119.8,248.1 151.2,287.2 190.5,290.0 308.2,292.1 503.5,293.4" fill="none" stroke="#3553ff" stroke-width="2.2" stroke-linejoin="round" stroke-dasharray="7 4"/>

    <g fill="#e0930f"><circle cx="112.0" cy="93.2" r="3.4"/><circle cx="119.8" cy="239.5" r="3.4"/><circle cx="151.2" cy="276.1" r="3.4"/><circle cx="190.5" cy="282.1" r="3.4"/><circle cx="308.2" cy="283.7" r="3.4"/><circle cx="503.5" cy="285.2" r="3.4"/></g>
    <g fill="#3553ff"><circle cx="112.0" cy="249.2" r="3"/><circle cx="119.8" cy="248.1" r="3"/><circle cx="151.2" cy="287.2" r="3"/><circle cx="190.5" cy="290.0" r="3"/><circle cx="308.2" cy="292.1" r="3"/><circle cx="503.5" cy="293.4" r="3"/></g>

    <circle cx="151.2" cy="276.1" r="9.5" fill="none" stroke="#0fa07f" stroke-width="2.2"/> <path d="M232 240 L 163 270" fill="none" stroke="#0fa07f" stroke-width="1.5" marker-end="url(#p11-11-a3)"/> <text x="236" y="232" font-size="10.5" font-weight="700" fill="#0fa07f">hedge delay = p95</text> <text x="236" y="245" font-size="9.5" fill="currentColor" opacity="0.9">5.0% load &#8594; p99.9 = 54.3 ms</text>
    <text x="236" y="257" font-size="9.5" font-weight="700" fill="#0fa07f">the operating point</text>

    <path d="M150 100 L 118 100" fill="none" stroke="#d64545" stroke-width="1.5" marker-end="url(#p11-11-a3)"/> <text x="156" y="97" font-size="10" font-weight="700" fill="#d64545">no hedging: p99.9 = 386.9 ms</text> <text x="156" y="110" font-size="9" fill="currentColor" opacity="0.85">the first 1% of extra load removes 69% of it</text>

    <path d="M392 204 L 418 276" fill="none" stroke="currentColor" stroke-width="1.3" stroke-dasharray="4 4" opacity="0.6" marker-end="url(#p11-11-a3)"/> <text x="312" y="176" font-size="9.5" fill="currentColor" opacity="0.9">flat beyond 5%: another 45% of</text> <text x="312" y="189" font-size="9.5" fill="currentColor" opacity="0.9">load buys only 16 more ms</text>

    <g fill="currentColor" font-size="9" opacity="0.75" text-anchor="middle">
      <text x="112" y="322">0</text><text x="190.5" y="322">10</text><text x="268.9" y="322">20</text><text x="347.4" y="322">30</text><text x="425.8" y="322">40</text><text x="504.2" y="322">50</text>
    </g>
    <text x="316" y="340" font-size="10" text-anchor="middle" fill="currentColor" opacity="0.9">extra backend load (% more calls issued)</text>
    <g fill="currentColor" font-size="9" opacity="0.75" text-anchor="end">
      <text x="103" y="309">0</text><text x="103" y="254">100</text><text x="103" y="199">200</text><text x="103" y="144">300</text><text x="103" y="89">400</text>
    </g>
    <text x="34" y="194" font-size="10" text-anchor="middle" fill="currentColor" opacity="0.9" transform="rotate(-90 34 194)">tail latency (ms)</text>

    <g font-size="10" font-weight="700">
      <text x="140" y="140" fill="#e0930f">&#8212; p99.9</text> <text x="140" y="156" fill="#3553ff">- - p99</text>
    </g>

    <g fill="none" stroke-width="1.8" stroke-linejoin="round">
      <rect x="548" y="62" width="318" height="248" rx="10" fill="#3553ff" fill-opacity="0.07" stroke="#3553ff"/>
    </g>
    <text x="562" y="82" font-size="10" font-weight="700" fill="#3553ff">THE MEASURED SWEEP</text>
    <g fill="currentColor" font-size="9" font-weight="700" opacity="0.7">
      <text x="562" y="104">delay set at</text> <text x="726" y="104" text-anchor="end">load</text> <text x="794" y="104" text-anchor="end">p99</text> <text x="856" y="104" text-anchor="end">p99.9</text>
    </g>
    <path d="M560 112 L 856 112" fill="none" stroke="currentColor" stroke-width="1" opacity="0.3"/>
    <g fill="currentColor" font-size="9.5">
      <text x="562" y="130">no hedging</text><text x="726" y="130" text-anchor="end">0%</text><text x="794" y="130" text-anchor="end">103.3</text><text x="856" y="130" text-anchor="end">386.9</text> <text x="562" y="150">p99&#8195;&#8195;105.0 ms</text><text x="726" y="150" text-anchor="end">1.0%</text><text x="794" y="150" text-anchor="end">105.3</text><text x="856" y="150" text-anchor="end">121.0</text>
      <text x="562" y="170" font-weight="700" fill="#0fa07f">p95&#8195;&#8195;&#8195;22.5 ms</text><text x="726" y="170" text-anchor="end" font-weight="700" fill="#0fa07f">5.0%</text><text x="794" y="170" text-anchor="end" font-weight="700" fill="#0fa07f">34.2</text><text x="856" y="170" text-anchor="end" font-weight="700" fill="#0fa07f">54.3</text> <text x="562" y="190">p90&#8195;&#8195;&#8195;17.3 ms</text><text x="726" y="190" text-anchor="end">10.0%</text><text x="794" y="190" text-anchor="end">29.1</text><text x="856" y="190" text-anchor="end">43.4</text>
      <text x="562" y="210">p75&#8195;&#8195;&#8195;12.6 ms</text><text x="726" y="210" text-anchor="end">25.0%</text><text x="794" y="210" text-anchor="end">25.2</text><text x="856" y="210" text-anchor="end">40.6</text> <text x="562" y="230">p50&#8195;&#8195;&#8195;&#8195;9.2 ms</text><text x="726" y="230" text-anchor="end">49.9%</text><text x="794" y="230" text-anchor="end">22.9</text><text x="856" y="230" text-anchor="end">37.8</text>
    </g>
    <path d="M560 244 L 856 244" fill="none" stroke="currentColor" stroke-width="1" opacity="0.3"/>
    <g fill="currentColor" font-size="9">
      <text x="562" y="262" font-weight="700" fill="#d64545">Set it too low and you are</text> <text x="562" y="276" font-weight="700" fill="#d64545">not hedging, you are retrying.</text> <text x="562" y="294" opacity="0.9">A p50 delay duplicates half your</text> <text x="562" y="306" opacity="0.9">traffic for 16 ms of tail.</text>
    </g>

    <text x="440" y="368" font-size="11" text-anchor="middle" fill="currentColor" opacity="0.9">Measured over 200,000 calls: the curve is a hockey stick, and the whole prize is in the first 5%.</text> <text x="440" y="390" font-size="10.5" text-anchor="middle" fill="#e0930f" font-weight="700">Set the delay from a percentile you actually measure &#8212; and re-measure it, because the p95 moves with load.</text>
  </g>
</svg>
```

The curve is a hockey stick and the knee is at about 5%. The first 1% of extra load removes **69%** of the p99.9. By 5% you have taken it from 386.9 ms to 54.3 ms. Everything after that is a bad deal: going from 5% to 49.9% extra load — **ten times the cost** — buys you 54.3 ms → 37.8 ms, sixteen milliseconds. **Somewhere around the p95 you stop buying latency and start buying load.**

Now say the uncomfortable part, because this is where hedging turns on you.

Set D too low and you are not hedging any more, **you are retrying** — indiscriminately, on every request, at full volume. A p50 delay duplicates half your traffic. And the real danger is not that you configured it badly on day one; it is that **the delay is a constant and the distribution is not**. You measure a p95 of 22.5 ms on a healthy Tuesday and hard-code it. Then load rises, queueing inflates every latency, and that 22.5 ms threshold — which used to catch the slowest 5% — now catches 40%, or 95%. Each of those hedges is extra load, which causes more queueing, which pushes more requests over the threshold. **Slow → hedge → more load → slower → hedge more.** That is a positive feedback loop, and Phase 8 Lesson 11 has a name for what it produces: a **metastable failure**, a system that stays down after the trigger is gone because it now sustains itself.

Section 3 of the code measures precisely this, and the numbers are brutal. A fleet calibrated at ρ = 0.50 (where the p95 was 40.6 ms) then run at ρ = 0.85 with that delay unchanged:

```text
config                          p50       p99     p99.9   hedged    busy
rho=0.85, no hedging            16.9     466.3     640.1    0.0%   82.8%
rho=0.85, hedge, no budget    4164.8    9401.0    9776.5   95.2%  161.4%
rho=0.85, hedge, 5% budget      22.3     342.9     499.8    5.0%   86.7%
```

**95.2% of requests got hedged, not 5%.** Offered load became 1.95× demand, which turns ρ = 0.85 into ρ = 1.66 — past capacity, so the queue grows without bound. The p99 went from 466 ms to **9401 ms, twenty times worse.** Hedging did not respond to the overload; hedging *created* it.

The fix is the same one retries need, for exactly the same reason. **A hedge must have a budget**: a hard cap on hedges as a *fraction of traffic*, enforced globally, not a per-request decision. "At most 5% of requests may be hedged" is an invariant that holds no matter what the latency distribution does. In the run above it denied **18,365** hedges and held the p99 at **343 ms** — 27× better than the unbudgeted hedge, and still 1.36× better than not hedging at all. The budget is not a safety feature bolted on the side. **It is the feature.** An unbudgeted hedge is a retry storm with better branding.

Two more rules that are not negotiable. **Hedge only idempotent operations** — a second copy of a request is a duplicate execution, and the first copy may complete even after you stopped waiting for it. `GET` and other safe reads are fine; anything that charges a card is not (see [Idempotency & Safe Retries](../../02-api-design/07-idempotency-safe-retries/)). And **send the hedge to a different replica** — a hedge to the same instance inherits the same queue and the same GC pause and buys you nothing.

### Tied requests

Hedging has one obvious inefficiency: you spend D milliseconds *waiting to find out* that the first copy is slow. On a request whose median is 9 ms, burning 22.5 ms before you even start the backup is most of your budget.

**Tied requests** remove the delay entirely. Send the request to **two replicas immediately** — but each copy carries **the identity of the other**. When a server *begins executing* its copy, it sends a cancellation directly to its twin. Whichever replica gets to the work first kills the redundant copy on the other.

The subtlety is what "begins executing" means, and it is the whole mechanism. The cancel is useful only if it arrives while the twin is still **enqueued and not yet started** — then dropping it costs nothing at all. That means tied requests only pay off where there is a real queue in front of the server: a storage shard with one I/O worker, which is exactly the setting Dean & Barroso designed them for. Measured on 64 such replicas at ρ = 0.75:

```text
config                   p50      p99     p99.9   2nd copies   of those,   duplicate
                                                      issued    ran anyway  work
no hedge                25.8   1451.7    1990.9        0.0%        0.0%        0.0%
hedged @ p95            27.0    308.6     467.5        9.1%       17.4%       12.6%
tied                    14.0    157.3     610.0      100.0%        8.6%       11.2%
tied, NO cancel path  2002.2   5514.2    6876.6      100.0%      100.0%       53.0%
```

Tied requests issue a second copy for **100%** of requests, which sounds like doubling your load — and the measured duplicate work is **11.2%**, slightly *less* than hedging's 12.6%, because only **8.6%** of those second copies ever executed. The rest were cancelled while still sitting in a queue. The p99 lands at **157.3 ms** against hedging's 308.6 ms and 1451.7 ms unprotected.

What remains is the **race window**. If both replicas start the work inside the time the cancel message spends on the wire (1.0 ms here), both copies run to completion and one is wasted. That residue is the 11.2%. The window is proportional to the message flight time, which is why tied requests are a same-datacenter technique — across regions the cancel arrives long after both copies have finished.

And the last row is the uncomfortable part, stated as a measurement rather than a warning. **Strip the cancellation path and the identical policy becomes a 2× load multiplier**: 100% of second copies execute, 53.0% of all service time goes to answers nobody reads, and the p99 goes from 157 ms to **5514 ms**. Tied requests are a **server capability the client gets to use**, not a client-side trick. If your backend cannot drop enqueued-but-unstarted work — and a plain HTTP server cannot, because a client hanging up does not stop a request already in the accept queue — you do not have tied requests. You have double the load.

### Micro-partitioning and selective replication

Two structural techniques that make everything above work better, both of which you have already met under a different motivation.

**Micro-partitioning** means making your partitions **much smaller than your machine count** — say 20 partitions per machine rather than one. Lesson 8 introduced this as *virtual buckets* so that resharding does not require moving half the data. Here the motivation is different: fine-grained partitions let you move load in small increments. If one machine is running hot, you migrate three of its twenty partitions elsewhere, instead of facing a choice between "do nothing" and "move 100% of a machine's load." Recovery from a failed machine is also faster and smoother, because its partitions are spread across many recipients rather than dumped on one.

**Selective replication** is the natural companion: detect the partitions that are **hot** — the celebrity user, the trending query, the popular product — and give *those* extra replicas. Uniform replication forces you to pay for your peak partition across every partition. Selective replication puts the copies where the load is. Both techniques exist to give the load balancer somewhere to put work at a granularity finer than "a whole machine," which is what makes latency-aware routing possible at all.

### Latency-induced probation and good-enough responses

**Latency-induced probation** handles the replica that is not down but is having a bad hour. When a replica's observed latency drifts persistently above its peers, take it out of rotation — but **keep sending it shadow traffic** so you can tell when it recovers. This is the important detail, and the one that gets skipped: a replica you have fully removed is a replica you have no signal about, so you are guessing when to bring it back. Shadow requests you do not wait on cost you a little load and buy you a reliable readmission signal. Note that this is a *fleet* refinement of the outlier ejection from Lesson 4 — there the trigger was health-check failure, here it is a latency distribution that is merely worse than its neighbours'.

**Good-enough responses** are the other half, and they are a design decision rather than a runtime one. When the deadline arrives and 98 of 100 shards have answered, **return the answer you have** and mark it partial. For a search page, results missing 2% of the corpus are overwhelmingly better than an error, and no user will notice. For a bank balance, they are a catastrophe.

That is the point: **the caller must be able to tolerate a partial result, and only the caller knows.** You cannot bolt this on during an incident. It has to be in the response contract from the beginning — a `partial: true` flag, a `shards_answered: 98/100` field, a documented meaning — so that clients are written to handle it. Every fan-out response should carry the count of contributing shards whether it is partial or not, because that number is also your best diagnostic when the tail goes bad.

### Correlated failure at fleet scale

Everything so far assumed slowness is **independent**. It often is not, and this is the honest limit of the entire technique.

Hedging is a bet that the *second* replica is having a better minute than the first. When the causes are independent that bet is excellent. When a **shared cause** — the same rack, the same co-tenant, the same bad deploy, the same compaction schedule — has hit both replicas of a shard, the hedge lands on a machine with exactly the same problem. Measured on a 100-way fan-out where 5% of replicas are stalled by 150–450 ms:

```text
regime                     p50      p99    p99.9   hedged   p50 gain  p99 gain
independent, no hedge     426.9   1583.9   3000.0    0.0%          -         -
independent, hedged        48.2    421.5    455.2    8.9%      8.86x     3.76x
correlated, no hedge      426.1   1416.6   3000.0    0.0%          -         -
correlated, hedged        419.5    470.8    484.9    8.9%      1.02x     3.01x
```

Same technique, same 8.9% extra load, both times. In the independent case the median composed request improves **8.86×**. In the correlated case it improves **1.02×** — you paid the load in full and bought **nothing**.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 474" width="100%" style="max-width:840px" role="img" aria-label="Two panels comparing independent and correlated slowness for a hedged request. On the left, replica one of a shard is stalled but replica two draws its own luck and is healthy, so the hedge escapes and the measured hundred-way median falls from 426.9 to 48.2 milliseconds, an 8.86 times gain. On the right, both replicas sit behind one shared cause such as the same rack, co-tenant or bad deploy, so the hedge inherits the same stall and the median only moves from 426.1 to 419.5 milliseconds, a gain of 1.02 times, while the extra load was paid in full.">
  <defs>
    <marker id="p11-11-a5" markerWidth="10" markerHeight="10" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker>
    <marker id="p11-11-a5g" markerWidth="10" markerHeight="10" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#0fa07f"/></marker>
    <marker id="p11-11-a5r" markerWidth="10" markerHeight="10" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#d64545"/></marker>
  </defs>
  <text x="440" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">Hedging bets the other replica is having a better minute</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">

    <g fill="none" stroke-width="2" stroke-linejoin="round">
      <rect x="34" y="46" width="396" height="216" rx="12" fill="#0fa07f" fill-opacity="0.07" stroke="#0fa07f"/> <rect x="450" y="46" width="396" height="216" rx="12" fill="#d64545" fill-opacity="0.07" stroke="#d64545"/>
    </g>
    <text x="232" y="70" font-size="12" text-anchor="middle" font-weight="700" fill="#0fa07f">INDEPENDENT SLOWNESS</text> <text x="648" y="70" font-size="12" text-anchor="middle" font-weight="700" fill="#d64545">CORRELATED SLOWNESS</text> <text x="232" y="86" font-size="9" text-anchor="middle" fill="currentColor" opacity="0.85">each replica draws its own luck</text> <text x="648" y="86" font-size="9" text-anchor="middle" fill="currentColor" opacity="0.85">one cause, both replicas</text>

    <circle cx="70" cy="150" r="15" fill="#3553ff" fill-opacity="0.16" stroke="#3553ff" stroke-width="1.8"/> <text x="70" y="154" font-size="9" text-anchor="middle" fill="currentColor" font-weight="700">you</text> <circle cx="486" cy="150" r="15" fill="#3553ff" fill-opacity="0.16" stroke="#3553ff" stroke-width="1.8"/> <text x="486" y="154" font-size="9" text-anchor="middle" fill="currentColor" font-weight="700">you</text>

    <g stroke-width="1.8">
      <rect x="182" y="104" width="180" height="42" rx="8" fill="#e0930f" fill-opacity="0.16" stroke="#e0930f"/> <rect x="182" y="170" width="180" height="42" rx="8" fill="#0fa07f" fill-opacity="0.16" stroke="#0fa07f"/>
    </g>
    <text x="272" y="122" font-size="10" text-anchor="middle" font-weight="700" fill="#e0930f">replica 1 &#8212; STALLED</text> <text x="272" y="137" font-size="8.5" text-anchor="middle" fill="currentColor" opacity="0.85">compaction, +150-450 ms</text> <text x="272" y="188" font-size="10" text-anchor="middle" font-weight="700" fill="#0fa07f">replica 2 &#8212; healthy</text> <text x="272" y="203" font-size="8.5" text-anchor="middle" fill="currentColor" opacity="0.85">answers in 9 ms</text>

    <path d="M88 142 L 176 124" fill="none" stroke="#e0930f" stroke-width="1.8" marker-end="url(#p11-11-a5)"/> <path d="M88 160 L 176 188" fill="none" stroke="#0fa07f" stroke-width="1.8" stroke-dasharray="5 3" marker-end="url(#p11-11-a5g)"/> <text x="94" y="122" font-size="8.5" fill="#e0930f" font-weight="700">1st copy</text> <text x="94" y="182" font-size="8.5" fill="#0fa07f" font-weight="700">hedge</text>
    <text x="232" y="236" font-size="11" text-anchor="middle" font-weight="700" fill="#0fa07f">the hedge escapes &#8594; p50 426.9 &#8594; 48.2 ms</text> <text x="232" y="252" font-size="10" text-anchor="middle" fill="#0fa07f" font-weight="700">8.86&#215; better</text>

    <rect x="590" y="98" width="188" height="120" rx="9" fill="#7f7f7f" fill-opacity="0.10" stroke="currentColor" stroke-width="1.5" stroke-dasharray="6 4" stroke-opacity="0.6"/> <text x="684" y="114" font-size="9" text-anchor="middle" fill="currentColor" font-weight="700" opacity="0.85">ONE SHARED CAUSE</text>
    <text x="684" y="126" font-size="8" text-anchor="middle" fill="currentColor" opacity="0.75">same rack / co-tenant / deploy</text>
    <g stroke-width="1.8">
      <rect x="602" y="134" width="164" height="36" rx="8" fill="#e0930f" fill-opacity="0.16" stroke="#e0930f"/> <rect x="602" y="176" width="164" height="36" rx="8" fill="#e0930f" fill-opacity="0.16" stroke="#e0930f"/>
    </g>
    <text x="684" y="150" font-size="10" text-anchor="middle" font-weight="700" fill="#e0930f">replica 1 &#8212; STALLED</text> <text x="684" y="163" font-size="8.5" text-anchor="middle" fill="currentColor" opacity="0.85">+150-450 ms</text> <text x="684" y="192" font-size="10" text-anchor="middle" font-weight="700" fill="#e0930f">replica 2 &#8212; STALLED</text> <text x="684" y="205" font-size="8.5" text-anchor="middle" fill="currentColor" opacity="0.85">same stall, same minute</text>

    <path d="M504 142 L 596 148" fill="none" stroke="#e0930f" stroke-width="1.8" marker-end="url(#p11-11-a5)"/> <path d="M504 160 L 596 190" fill="none" stroke="#d64545" stroke-width="1.8" stroke-dasharray="5 3" marker-end="url(#p11-11-a5r)"/> <text x="510" y="132" font-size="8.5" fill="#e0930f" font-weight="700">1st copy</text> <text x="510" y="184" font-size="8.5" fill="#d64545" font-weight="700">hedge</text>
    <text x="648" y="236" font-size="11" text-anchor="middle" font-weight="700" fill="#d64545">the hedge inherits it &#8594; p50 426.1 &#8594; 419.5 ms</text> <text x="648" y="252" font-size="10" text-anchor="middle" fill="#d64545" font-weight="700">1.02&#215; &#8212; you paid the load and bought nothing</text>

    <g fill="none" stroke-width="1.8" stroke-linejoin="round">
      <rect x="34" y="284" width="812" height="136" rx="10" fill="#3553ff" fill-opacity="0.07" stroke="#3553ff"/>
    </g>
    <text x="50" y="304" font-size="10" font-weight="700" fill="#3553ff">MEASURED &#8212; 8,000 hundred-way fan-outs, 5% of replicas stalled, hedge delay 22.5 ms</text>
    <g fill="currentColor" font-size="9" font-weight="700" opacity="0.7">
      <text x="50" y="324">regime</text> <text x="400" y="324" text-anchor="end">p50</text> <text x="510" y="324" text-anchor="end">p99</text> <text x="620" y="324" text-anchor="end">p99.9</text> <text x="722" y="324" text-anchor="end">extra load</text> <text x="834" y="324" text-anchor="end">p50 gain</text>
    </g>
    <path d="M46 332 L 834 332" fill="none" stroke="currentColor" stroke-width="1" opacity="0.3"/>
    <g fill="currentColor" font-size="10">
      <text x="50" y="352">independent, no hedge</text> <text x="400" y="352" text-anchor="end">426.9</text><text x="510" y="352" text-anchor="end">1583.9</text><text x="620" y="352" text-anchor="end">3000.0</text><text x="722" y="352" text-anchor="end">&#8212;</text><text x="834" y="352" text-anchor="end">&#8212;</text> <text x="50" y="370" font-weight="700" fill="#0fa07f">independent, hedged</text>
      <text x="400" y="370" text-anchor="end" font-weight="700" fill="#0fa07f">48.2</text><text x="510" y="370" text-anchor="end" font-weight="700" fill="#0fa07f">421.5</text><text x="620" y="370" text-anchor="end" font-weight="700" fill="#0fa07f">455.2</text><text x="722" y="370" text-anchor="end">8.9%</text><text x="834" y="370" text-anchor="end" font-weight="700" fill="#0fa07f">8.86&#215;</text>
      <text x="50" y="388">correlated, no hedge</text> <text x="400" y="388" text-anchor="end">426.1</text><text x="510" y="388" text-anchor="end">1416.6</text><text x="620" y="388" text-anchor="end">3000.0</text><text x="722" y="388" text-anchor="end">&#8212;</text><text x="834" y="388" text-anchor="end">&#8212;</text> <text x="50" y="406" font-weight="700" fill="#d64545">correlated, hedged</text>
      <text x="400" y="406" text-anchor="end" font-weight="700" fill="#d64545">419.5</text><text x="510" y="406" text-anchor="end" font-weight="700" fill="#d64545">470.8</text><text x="620" y="406" text-anchor="end" font-weight="700" fill="#d64545">484.9</text><text x="722" y="406" text-anchor="end">8.9%</text><text x="834" y="406" text-anchor="end" font-weight="700" fill="#d64545">1.02&#215;</text>
    </g>
    <text x="440" y="450" font-size="11" text-anchor="middle" fill="currentColor" opacity="0.9">Same 8.9% extra load, both times. Correlated slowness is a blast-radius problem, not a tail problem.</text>
  </g>
</svg>
```

State this plainly: **correlated slowness is a capacity or blast-radius problem, not a tail problem.** No way of *issuing* requests can fix a problem that lives in the resource both copies are sharing. The fix is structural and it is Lesson 9's material — spread replicas across failure domains so that "the other replica" is genuinely independent: different rack, different power, different availability zone, different deploy wave. **Hedging only works as well as your replica placement is uncorrelated**, which makes replica placement a latency decision, not just an availability one.

Now the fleet-scale version of the same idea, which is where Phase 8's single-process patterns start interacting badly. Lesson 11 of Phase 8 built the circuit breaker; what follows is what happens when **300 of them trip in the same second.**

**Synchronised breakers.** A dependency has a bad thirty seconds. All 300 instances of your service observe it, and all 300 breakers open at roughly the same moment — correctly, individually. Two things follow. First, the load on the *fallback* path is a step function: it goes from zero to 100% of traffic instantly, and the fallback path has never been load-tested at that volume. Second, and worse, every breaker uses the same cool-down, so all 300 send their half-open probe at the same instant. The recovering dependency, which could have absorbed a trickle, gets a 300-request wall and falls over again. Every breaker sees the probe fail, re-opens, waits the same cool-down, and does it again. Measured over 300 instances against a dependency that can absorb 25 probes per 100 ms window:

```text
cool-down            peak probes    windows      failed    all breakers
                     per 100 ms   overwhelmed    probes    closed at
fixed 5.000 s            158          22         3300      NEVER (>60s)
5 s * U(0.5, 1.5)        14            0          0        7.61 s
```

The unjittered fleet **never recovers** inside the 60-second horizon. It re-kills its own dependency once per cool-down, forever, with 3,300 failed probes and nothing to show for them. Jittering the same cool-down over a 5-second spread drops the peak from 158 probes to 14, overwhelms zero windows, and has every breaker closed **7.61 seconds** in. The dependency was equally healthy in both runs. The only difference was **correlation**.

**Retry amplification.** The other fleet-scale multiplier, and the one people consistently get wrong by one operation. Retries across layers **multiply**; they do not add. If your gateway retries 3×, your service mesh retries 3×, and your client SDK retries 3×, one user request becomes:

```text
 layers   2 attempts each   3 attempts each   3 attempts, 10% budget each
   1             2                 3                     1.10
   2             4                 9                     1.21
   3             8                27                     1.33
   4            16                81                     1.46
```

**Three layers of three attempts is 27 requests at the bottom of the stack**, and each layer was configured by someone who believed they were the only one retrying. Four layers is 81. The right-hand column is the same thing with a 10% retry *budget* at each layer: three layers amplify to **1.33×** instead of 27×. Budgets compose safely because they are fractions of traffic; attempt counts compose catastrophically because they are multipliers.

The general rule that covers breakers, cron, TTLs, backoff, health checks, token refreshes and cache expiry alike:

> **Jitter every periodic action.** Correlation, not volume, is what turns 300 instances into an incident.

The reason is worth stating precisely. A fleet of 300 instances each doing something once every 5 seconds is 60 events per second — trivial. The *same* fleet doing it in lockstep is 300 events in one instant and nothing for 5 seconds, and your dependency is sized for the average while it dies of the peak. Randomising the phase costs nothing and converts a spike into a rate. Anything on a timer — anything with a fixed TTL, a round-number schedule, or a `sleep(BACKOFF)` — is synchronised by default, and things that start together stay together.

### Deadline propagation

The last technique is the one most systems get wrong, and it is the fleet-level version of a timeout.

A **timeout** is a duration: "wait 1 second for this call." A **deadline** is an absolute point in time: "this request must be done by 09:41:03.250." The difference sounds pedantic and is not, because durations restart at every hop and absolute times do not.

Consider a three-hop chain — service A calls B calls C — where each hop has its own perfectly reasonable 1-second timeout. What is the worst-case total? **Three seconds.** Each hop starts a fresh clock, so the timeouts stack. Meanwhile the user, who gave up at 1 second, left two seconds ago. Everything after that point is work executed for a caller who is gone — Phase 8's *goodput* problem, moved one network hop further out.

The fix is to pass a **deadline** rather than a timeout, and to pass the **remaining** budget at every hop:

```text
at each hop:  remaining = deadline - now()
              if remaining <= 0:                    refuse immediately
              if remaining < expected_service_time: refuse immediately
              else: do the work with a timeout of `remaining`
```

That second check is the one that earns its keep. If only 80 ms remain and this hop's work takes 183 ms at the median, **starting is pure waste** — you will burn a service time you cannot deliver. Refusing costs zero and frees the capacity for a request that can still make it. Measured over 80,000 three-hop requests against a 1000 ms deadline:

```text
mode          p50 total   p99 total   worst    late    wasted ms/req   refused early
independent        594        1587     2664   10.4%           38.3           0.0%
propagated         594        1000     1000    0.0%            0.0           6.7%
```

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 452" width="100%" style="max-width:840px" role="img" aria-label="A three-hop call chain drawn twice against the same time axis. With independent one-second timeouts each hop restarts its own clock, so the chain runs to 1520 milliseconds and the shaded red region from the user's 1000 millisecond deadline onward is work executed for a caller who has already gone; the worst case is bounded only by three times one second. With a propagated absolute deadline, hop C computes that only 80 milliseconds remain, refuses immediately, and the chain is bounded at 1000 milliseconds with no wasted work. A measured table reports 38.3 wasted milliseconds per request and a 2664 millisecond worst case for independent timeouts against zero wasted milliseconds and a 1000 millisecond worst case for propagated deadlines.">
  <defs>
    <marker id="p11-11-a4" markerWidth="10" markerHeight="10" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker>
    <marker id="p11-11-a4r" markerWidth="10" markerHeight="10" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#d64545"/></marker>
  </defs>
  <text x="440" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">A deadline is an absolute time. A timeout is three of them in a row.</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">

    <path d="M555 62 L 555 268" fill="none" stroke="#d64545" stroke-width="2" stroke-dasharray="6 4"/> <text x="561" y="72" font-size="10" font-weight="700" fill="#d64545">the user&#8217;s deadline: 1000 ms</text> <text x="561" y="84" font-size="9" fill="#d64545" opacity="0.9">after this line, nobody is listening</text>

    <text x="130" y="108" font-size="10.5" font-weight="700" fill="#d64545">INDEPENDENT TIMEOUTS &#8212; each hop starts its own 1000 ms clock</text>
    <g stroke-width="1.7">
      <rect x="130" y="118" width="170" height="30" rx="5" fill="#3553ff" fill-opacity="0.13" stroke="#3553ff"/> <rect x="300" y="118" width="221" height="30" rx="5" fill="#3553ff" fill-opacity="0.13" stroke="#3553ff"/> <rect x="521" y="118" width="255" height="30" rx="5" fill="#3553ff" fill-opacity="0.13" stroke="#3553ff"/>
    </g>
    <rect x="555" y="118" width="221" height="30" fill="#d64545" fill-opacity="0.28" stroke="none"/>
    <g fill="currentColor" font-size="9.5" text-anchor="middle">
      <text x="215" y="137">hop A &#183; 400 ms</text><text x="410" y="137">hop B &#183; 520 ms</text><text x="640" y="137">hop C &#183; 600 ms</text>
    </g>
    <text x="666" y="166" font-size="9.5" text-anchor="middle" font-weight="700" fill="#d64545">520 ms of work for nobody</text> <text x="790" y="137" font-size="10" font-weight="700" fill="#d64545">1520 ms</text>

    <text x="130" y="200" font-size="10.5" font-weight="700" fill="#0fa07f">PROPAGATED DEADLINE &#8212; each hop inherits what is LEFT</text>
    <g stroke-width="1.7">
      <rect x="130" y="210" width="170" height="30" rx="5" fill="#0fa07f" fill-opacity="0.13" stroke="#0fa07f"/> <rect x="300" y="210" width="221" height="30" rx="5" fill="#0fa07f" fill-opacity="0.13" stroke="#0fa07f"/> <rect x="521" y="210" width="34" height="30" rx="5" fill="#d64545" fill-opacity="0.18" stroke="#d64545"/>
    </g>
    <g fill="currentColor" font-size="9.5" text-anchor="middle">
      <text x="215" y="229">hop A &#183; 400 ms</text><text x="410" y="229">hop B &#183; 520 ms</text>
    </g>
    <g font-size="9" text-anchor="middle">
      <text x="215" y="256" fill="currentColor" opacity="0.85">budget left: 1000 ms</text> <text x="410" y="256" fill="currentColor" opacity="0.85">budget left: 600 ms</text> <text x="694" y="256" fill="#d64545" font-weight="700">budget left: 80 ms &#8212; less than one hop needs</text>
    </g>
    <path d="M600 218 L 562 224" fill="none" stroke="#d64545" stroke-width="1.5" marker-end="url(#p11-11-a4r)"/> <text x="606" y="222" font-size="10" font-weight="700" fill="#d64545">hop C refuses in 0 ms &#8212; total 920 ms</text>

    <g fill="none" stroke="currentColor" stroke-width="1.3"><path d="M130 268 L 830 268"/></g>
    <g fill="none" stroke="currentColor" stroke-width="1" opacity="0.4">
      <path d="M130 268 L 130 273"/><path d="M342 268 L 342 273"/><path d="M555 268 L 555 273"/><path d="M767 268 L 767 273"/>
    </g>
    <g fill="currentColor" font-size="9" opacity="0.7" text-anchor="middle">
      <text x="130" y="285">0</text><text x="342" y="285">500</text><text x="555" y="285">1000</text><text x="767" y="285">1500 ms</text>
    </g>

    <g fill="none" stroke-width="1.8" stroke-linejoin="round">
      <rect x="40" y="300" width="800" height="106" rx="10" fill="#3553ff" fill-opacity="0.07" stroke="#3553ff"/>
    </g>
    <text x="56" y="320" font-size="10" font-weight="700" fill="#3553ff">MEASURED &#8212; 80,000 three-hop requests</text>
    <g fill="currentColor" font-size="9" font-weight="700" opacity="0.7">
      <text x="56" y="340">mode</text> <text x="330" y="340" text-anchor="end">p50</text> <text x="430" y="340" text-anchor="end">p99</text> <text x="530" y="340" text-anchor="end">worst seen</text> <text x="640" y="340" text-anchor="end">past deadline</text> <text x="750" y="340" text-anchor="end">wasted ms/req</text> <text x="828" y="340" text-anchor="end">refused</text>
    </g>
    <path d="M52 348 L 828 348" fill="none" stroke="currentColor" stroke-width="1" opacity="0.3"/>
    <g fill="currentColor" font-size="10">
      <text x="56" y="368" font-weight="700" fill="#d64545">independent timeouts</text> <text x="330" y="368" text-anchor="end">594</text><text x="430" y="368" text-anchor="end">1587</text><text x="530" y="368" text-anchor="end">2664</text><text x="640" y="368" text-anchor="end" font-weight="700" fill="#d64545">10.4%</text><text x="750" y="368" text-anchor="end" font-weight="700" fill="#d64545">38.3</text><text x="828" y="368" text-anchor="end">0.0%</text> <text x="56" y="390" font-weight="700" fill="#0fa07f">propagated deadline</text>
      <text x="330" y="390" text-anchor="end">594</text><text x="430" y="390" text-anchor="end">1000</text><text x="530" y="390" text-anchor="end">1000</text><text x="640" y="390" text-anchor="end" font-weight="700" fill="#0fa07f">0.0%</text><text x="750" y="390" text-anchor="end" font-weight="700" fill="#0fa07f">0.0</text><text x="828" y="390" text-anchor="end">6.7%</text>
    </g>
    <text x="440" y="428" font-size="11" text-anchor="middle" fill="currentColor" opacity="0.9">Identical p50. The difference is the worst case (3&#215; the budget vs bounded) and who pays for it.</text>
  </g>
</svg>
```

The medians are **identical** — 594 ms both times — which is why this never shows up in a dashboard review. Everything else differs. Independent timeouts produce a p99 of 1587 ms, a worst case of **2664 ms** (bounded only by 3 × 1000 ms), **10.4%** of requests finishing after the caller stopped waiting, and **38.3 ms per request** of service time spent on answers nobody read. Propagated deadlines are bounded at 1000 ms **by construction**, waste zero, and refuse 6.7% of requests instantly — those are the ones that could not have finished anyway, converted from a slow failure into a fast one.

Two mechanics make this work in practice. The deadline must ride along with the request — a header, a gRPC deadline, a `context.Context`. [Structured Concurrency: Tasks, Cancellation & Timeouts](../../08-concurrency-and-performance/06-structured-concurrency-and-cancellation/) covers how a cancellation signal propagates *inside* one process, and [Correlation: Request IDs, Trace Context & Propagation](../../09-logging-monitoring-and-observability/03-correlation-and-request-context/) covers the context-propagation plumbing that carries values across service boundaries — the same mechanism carries the deadline. And clocks: an absolute deadline crossing machines depends on clock sync, so in practice most systems send the *remaining duration* on the wire and each hop immediately converts it back to a local absolute time. That is skew-tolerant, since it only relies on each machine measuring elapsed time correctly, not on machines agreeing about what time it is.

## Build It

[`code/tail_at_scale.py`](code/tail_at_scale.py) is seven numbered arguments. Standard library only, seeded with `SEED = 7`, ~11 seconds, no network and no servers.

The backend latency distribution is the foundation everything else rests on, so it is stated explicitly rather than hidden: a lognormal body (the normal path) plus a rare heavy-tailed **hiccup** (GC, compaction, a co-tenant), truncated by the server's own execution limit.

```python
def draw_latency(rng: random.Random) -> float:
    """One backend call's response time in milliseconds."""
    v = BODY_MEDIAN * math.exp(BODY_SIGMA * rng.gauss(0.0, 1.0))
    if rng.random() < HICCUP_P:
        v += HICCUP_XM / (1.0 - rng.random()) ** (1.0 / HICCUP_ALPHA)
    return v if v < EXEC_LIMIT else EXEC_LIMIT
```

`HICCUP_ALPHA = 1.6` gives a Pareto tail with a finite mean and *infinite variance* — which is the honest shape for real backend latency and the reason averages mislead so badly here. The `EXEC_LIMIT` truncation matters more than it looks: it is why the N = 100 row's p99.9 reads exactly 3000.0 ms. At a 100-way fan-out, **0.33% of user requests hit a backend's server-side execution limit**, and at 500-way, 1.57% do.

**Hedging is four lines**, and writing it out makes the load arithmetic obvious — the second call happens only inside the `if`:

```python
def hedged(pool, K, randrange, delay):
    """Return (latency, hedged?) for one call with a hedge fired at `delay`."""
    a = pool[randrange(K)]
    if a <= delay:
        return a, False
    b = pool[randrange(K)]          # a second copy, to a different replica
    return (a if a < delay + b else delay + b), True
```

Sections 3 and 4 need real queues, so they run a discrete-event simulation of a fleet of replicas. The single most important parameter is the one most simulations quietly get wrong, and it is the difference between hedging being safe and hedging being a retry storm:

```python
cancel_enqueued: whether the SERVER can drop queued work whose answer is no
longer wanted. False is the HTTP default - a client that gives up does not
stop the server, so every copy issued is a copy executed. True requires real
cancellation propagation (gRPC, or Dean & Barroso's tied requests).
```

In the dispatch loop, that flag decides whether a doomed copy is free or fully paid for:

```python
while inflight[s] < slots and q:
    task = q.popleft()
    dead = task.cancelled or task.req.done_at is not None
    if dead and cancel_enqueued:
        st["dropped"] += 1          # dropped before it cost anything
        continue
    inflight[s] += 1
    ...
    if dead:
        st["wasted_ms"] += svc      # nobody is waiting for this answer
```

The hedge budget is the other load-bearing line — a global cap on hedges as a fraction of requests seen, not a per-request decision:

```python
if hedge_budget is not None and st["extra"] >= hedge_budget * st["requests"]:
    st["denied"] += 1           # the hedge budget said no
    continue
```

Run it:

```bash
docker compose exec -T app python \
  phases/11-scalability-and-reliability/11-the-tail-at-scale/code/tail_at_scale.py
```

```console
== 1 . FAN-OUT AMPLIFICATION: YOUR p99 IS EVERYONE'S MEDIAN ==
  one backend call, 200,000 samples (lognormal body + 3% heavy-tailed hiccup):
    p50     9.2 ms   p90    17.3 ms   p99   105.0 ms   p99.9   384.6 ms

  a user request fans out to N shards and must wait for ALL of them,
  so its latency is the MAXIMUM of N independent calls:

     N      p50      p90      p99    p99.9   P(>=1 call over backend p99)     hit the
                                              measured    1-(1-p)^N       3 s limit
     1      9.1     17.3    100.6    375.2         0.9%        1.0%        0.00%
     5     15.9     71.6    273.1    941.5         5.0%        4.9%        0.02%
    20     29.5    149.5    588.4   2840.6        18.0%       18.2%        0.07%
   100    129.0    370.1   1583.9   3000.0        63.7%       63.4%        0.33%
   500    323.0   1075.5   3000.0   3000.0        99.3%       99.3%        1.57%

  the arithmetic is exact, and it is the whole lesson:
    backend p99      =  105.0 ms   (1% of calls are slower)
    user p50 at N=100 =  129.0 ms   <-- the MEDIAN 100-way request is 1.23x the p99 of every backend it called
    user p50 at N=500 =  323.0 ms   = 3.08x that same backend p99
  and one backend's p99.9 (385 ms) is the p90.5 of a 100-way fan-out
  (theory: 0.999^100 = 0.905). Nobody's dashboard shows this,
  because the problem is not in any one service - it is in the multiplication.

== 2 . HEDGED REQUESTS: BUY THE TAIL BACK FOR 5% MORE LOAD ==
  hedge delay = the measured p95 of one call = 22.5 ms
  200,000 single calls, each replicated to a second replica only if slow:

                      p50      p99    p99.9   hedged   extra load
  no hedge            9.1    103.3    386.9     0.0%         0.0%
  hedge @ p95         9.2     33.9     52.7    5.0%         5.0%
  -> p99 103.3 -> 33.9 ms (3.05x better), p99.9 387 -> 53 ms (7.35x)

  the same hedging, applied to every shard of a 100-way fan-out:
  no hedge        p50   128.7   p99  1583.9   p99.9  3000.0   backend calls 1.000 per shard
  hedge @ p95     p50    35.7   p99   116.5   p99.9   199.0   backend calls 1.050 per shard

  sweeping the hedge delay - the trade, made visible:
   delay set at    delay     p50      p99    p99.9   hedged   extra load
   p50              9.2     9.1     22.9     37.8   49.9%        49.9%
   p75             12.6     9.2     25.2     40.6   25.0%        25.0%
   p90             17.3     9.2     29.1     43.4   10.0%        10.0%
   p95             22.5     9.2     34.2     54.3    5.0%         5.0%
   p99            105.0     9.2    105.3    121.0    1.0%         1.0%

== 3 . HEDGING UNDER OVERLOAD IS A RETRY STORM WITH A NICER NAME ==
  16 replicas x 4 concurrent slots, mean service 13.8 ms => capacity 4638 req/s
  calibration run at rho = 0.50: p50 9.9 ms, p95 40.6 ms, p99 143.3 ms
  you set the hedge delay to the p95 you measured while healthy: 40.6 ms

  config                          p50       p99     p99.9   hedged    busy
  rho=0.85, no hedging            16.9     466.3     640.1    0.0%   82.8%
  rho=0.85, hedge, no budget    4164.8    9401.0    9776.5   95.2%  161.4%
  rho=0.85, hedge, 5% budget      22.3     342.9     499.8    5.0%   86.7%

  at rho = 0.85 a delay of 40.6 ms is no longer the p95 of anything. Queueing moved
  the whole distribution right, so 95% of requests crossed it instead of 5%, and
  offered load became 1.95x demand - which turns rho = 0.85 into rho = 1.66.
  Replicas went 83% -> 161% busy and p99 went 466 -> 9401 ms, 20x WORSE.
  The 5% budget denied 18,365 hedges, held extra load at 5.0%, and kept p99 at
  343 ms - 27x better than the unbudgeted hedge and 1.36x better than no hedge at all.

== 4 . TIED REQUESTS: PAY A CROSS-SERVER MESSAGE, DELETE THE DELAY ==
  64 storage replicas, ONE I/O worker each, so a real queue forms in
  front of every one - the regime Dean & Barroso designed tied requests for.
  rho = 0.75, hedge delay = the calm p95 = 209.3 ms, cancel message 1.0 ms.

  config                   p50      p99     p99.9   2nd copies   of those,   duplicate
                                                       issued    ran anyway  work
  no hedge                25.8   1451.7    1990.9        0.0%        0.0%        0.0%
  hedged @ p95            27.0    308.6     467.5        9.1%       17.4%       12.6%
  tied                    14.0    157.3     610.0      100.0%        8.6%       11.2%
  tied, NO cancel path  2002.2   5514.2    6876.6      100.0%      100.0%       53.0%

  the last row is why this is not free. Strip the cancel path and the same
  tied policy executes both copies of 100% of requests, burns 53% of all service time on
  answers nobody reads, and takes p99 from 157 to 5514 ms. Tied requests are a
  server capability the client gets to use, not a client-side trick.

== 5 . THE HONEST LIMIT: HEDGING DIES ON CORRELATED SLOWNESS ==
  100-way fan-out, hedge delay 22.5 ms. At any moment 5% of replicas are
  stalled - a compaction, a GC pause, a co-tenant - adding 150-450 ms to every call.
  INDEPENDENT: the replica you hedge to draws its own luck.
  CORRELATED : both replicas of a shard share the cause (same rack, same
               co-tenant, same bad deploy), so the hedge inherits the stall.

  regime                     p50      p99    p99.9   hedged   p50 gain  p99 gain
  independent, no hedge     426.9   1583.9   3000.0    0.0%          -         -
  independent, hedged        48.2    421.5    455.2    8.9%      8.86x     3.76x
  correlated, no hedge      426.1   1416.6   3000.0    0.0%          -         -
  correlated, hedged        419.5    470.8    484.9    8.9%      1.02x     3.01x

== 6 . WHAT BREAKS WHEN 300 INSTANCES RUN THE SAME GOOD PATTERN ==
  (a) retry amplification MULTIPLIES across layers - it does not add:

   layers   2 attempts each   3 attempts each   3 attempts, 10% budget each
     1             2                 3                     1.10
     2             4                 9                     1.21
     3             8                27                     1.33
     4            16                81                     1.46

  (b) 300 circuit breakers trip in the same second. The recovering
      dependency can absorb 25 probes per 100 ms window;
      more than that and it falls over again and every probe fails.

  cool-down            peak probes    windows      failed    all breakers
                       per 100 ms   overwhelmed    probes    closed at
  fixed 5.000 s            158          22         3300      NEVER (>60s)
  5 s * U(0.5, 1.5)        14            0          0        7.61 s

== 7 . DEADLINE PROPAGATION: THE FLEET-LEVEL VERSION OF A TIMEOUT ==
  A -> B -> C. Each hop's own work ~ the same distribution x20 (p50 183 ms).
  The user's deadline is 1000 ms, absolute, set when the request is accepted.

  mode          p50 total   p99 total   worst    late    wasted ms/req   refused early
  independent        594        1587     2664   10.4%           38.3           0.0%
  propagated         594        1000     1000    0.0%            0.0           6.7%

  independent timeouts are bounded only by 3 x 1000 ms = 3000 ms - three times the
  budget the user actually had; 80,000 requests reached 2664 ms. Propagated deadlines
  cannot exceed 1000 ms by construction, and the worst observed was 1000 ms.
```

Five of these sections are arguments rather than demos, so read them as such.

**Section 1 is the lesson.** The measured "at least one slow call" column tracks `1 − (1−p)^N` to within 0.3 percentage points at every width, so this is arithmetic and not a simulation artefact. The row to stare at is N = 100: a **p50 of 129.0 ms against a backend p99 of 105.0 ms.** The typical user is having a worse time than the worst 1% of any component. Note also the last column — the fraction of user requests that hit a backend's 3-second execution limit climbs from 0.00% at N = 1 to **1.57% at N = 500.** Those are not slow requests; those are requests where a shard gave up entirely, and they exist only because you fanned out.

**Section 2 is the payoff and it is lopsided.** For **5.0% more backend calls**, the 100-way fan-out's median goes 128.7 → 35.7 ms and its p99 goes 1583.9 → 116.5 ms. The sweep shows why the p95 is the right delay and not a superstition: the first 1% of extra load removes 69% of the p99.9, five percent removes 86% of it, and the remaining 45% of load you could spend buys sixteen milliseconds.

**Section 3 is the safety lesson and the reason hedging has a bad reputation among people who have been burned by it.** Nothing about the hedge configuration changed between the calm calibration and the overloaded run — only the traffic did. A delay set at the healthy p95 caught **95.2%** of requests once queueing shifted the distribution, offered load hit 1.95×, effective ρ hit 1.66, and the p99 went **twenty times worse than not hedging at all**. The budget is what converts hedging from a gamble into a technique: 18,365 hedges denied, extra load pinned at 5.0%, p99 held at 343 ms.

**Section 4 quantifies what tied requests actually cost**, which is the thing the paper's description makes hard to intuit. Issuing 100% second copies produces **11.2%** duplicate work — *less* than hedging's 12.6% — because 91.4% of those copies get cancelled while still queued. But that number is entirely a function of the cancel path: remove it and the same policy runs both copies of every request, wastes **53.0%** of all service time, and takes the p99 from 157 ms to 5514 ms. Same client logic, opposite outcome, and the deciding factor lives in the server.

**Section 5 is the honest limit** and belongs in the same breath as the technique. Identical hedging, identical 8.9% extra load: the median improves **8.86×** when slowness is independent and **1.02×** when it is correlated. If your replicas share a rack, a hypervisor, a power domain or a deploy wave, you have quietly converted your latency insurance into pure cost.

**Sections 6 and 7 are the fleet arithmetic.** Three layers of three retries is 27× amplification and each layer's owner thinks they are alone; the same three layers with a 10% budget each is 1.33×. An unjittered fleet of 300 breakers **never recovers** within 60 seconds because its own synchronised probes keep re-killing the dependency, while jittering the identical cool-down has everything closed in 7.61 seconds. And independent timeouts and propagated deadlines have **exactly the same p50 of 594 ms** — the entire difference is a worst case of 2664 ms versus 1000 ms, and 38.3 ms per request of work performed for callers who had already gone.

## Use It

Nothing above needs a framework, but the production tools have opinions worth knowing.

**gRPC builds deadlines into the protocol**, which is the single strongest argument for it in a fan-out architecture. A gRPC client sets a deadline, not a timeout, and it travels on the wire as the `grpc-timeout` header; each hop converts it back to a local absolute time and passes the *remaining* budget onward. The server can read it and refuse work it cannot finish:

```python
# The caller sets an absolute budget once, at the edge.
response = stub.Search(request, timeout=0.25)     # 250 ms for the WHOLE chain

# Every downstream hop inherits what is left, and can check it:
def Search(self, request, context):
    remaining = context.time_remaining()          # seconds, absolute-derived
    if remaining < EXPECTED_SERVICE_TIME:
        context.abort(grpc.StatusCode.DEADLINE_EXCEEDED, "insufficient budget")
    ...
```

`context.time_remaining()` is the line that matters. Cancellation propagates too: when the caller gives up, the server's context is cancelled and a well-written handler stops working — which is precisely the `cancel_enqueued=True` capability that Section 4 showed to be worth a 35× difference in p99. In HTTP-land you get none of this for free; you must pass a deadline header yourself, convert it at every hop, and check it before starting expensive work.

**Envoy implements hedging directly.** The knob is per-try timeout plus hedging on it:

```yaml
route:
  timeout: 1s                          # the whole-request deadline
  retry_policy:
    retry_on: "5xx,reset,connect-failure"
    num_retries: 2
    per_try_timeout: 0.05s             # ~ your p95, measured
    retry_budget:                      # THE line that stops a retry storm
      budget_percent: { value: 20 }
      min_retry_concurrency: 3
  hedge_policy:
    hedge_on_per_try_timeout: true     # send copy #2 when per_try_timeout fires
```

`hedge_on_per_try_timeout: true` is hedging exactly as measured above: `per_try_timeout` is the hedge delay D, so set it from a percentile you actually measured, and **re-measure it**, because Section 3 is what happens when it drifts. `retry_budget` is the budget — Envoy's default is 20% of active requests, and it applies to hedges too. Finagle pioneered the same pair (its client-side "backup requests" with a configurable budget), and Envoy's `budget_percent` is the direct descendant.

**What to instrument**, because none of this is visible by default:

- **Percentiles of the fan-out request, not of the backends.** This is the whole lesson. Per-backend dashboards are structurally incapable of showing the problem — every one of them was green in the opening scene. Emit a histogram keyed on the *composed* request.
- **The number of shards that contributed to each response.** Emit it on every response, not just partial ones. When the tail degrades, "we served 96/100 shards" localises the problem instantly, and it is the only way to know whether your good-enough responses are firing.
- **Hedge rate and hedge win rate, as counters.** Hedge rate tells you whether your delay is still calibrated — if it drifts from 5% toward 40%, you are heading into Section 3. Win rate (how often the hedge answered first) tells you whether hedging is buying anything at all; a collapsing win rate with a steady hedge rate is the signature of correlated slowness.
- **Budget exhaustion events.** A counter that increments when a hedge or retry is denied. Non-zero means you are being protected; sharply rising means something upstream is on fire.
- **Beware coordinated omission.** If your load generator waits for a response before sending the next request, it stops issuing requests exactly when the system is slowest, and your measured percentiles are fiction — the slow period is under-sampled precisely because it is slow. [Benchmarking & Load Testing](../../08-concurrency-and-performance/14-benchmarking-and-load-testing/) covers the correction. Percentile aggregation is the other trap: **you cannot average percentiles across instances**, so collect histograms and merge those instead ([Metrics from Scratch](../../09-logging-monitoring-and-observability/05-metrics-from-scratch/), and [Prometheus: Pull, Exposition & PromQL](../../09-logging-monitoring-and-observability/06-prometheus-and-promql/) for `histogram_quantile` over a fleet).

The rule set, short enough to put in a code review checklist:

- **Hedge only idempotent reads.** A hedge is a duplicate execution and the loser may still complete. `GET`s, yes; anything that mutates, only behind an idempotency key ([Idempotency & Safe Retries](../../02-api-design/07-idempotency-safe-retries/)).
- **Always budget hedges**, as a percentage of traffic, enforced globally. 5–10% is a sane default. Unbudgeted hedging is a retry storm you built on purpose.
- **Set the hedge delay from a measured percentile, and re-measure it.** A hard-coded delay is correct for exactly one load level.
- **Always propagate deadlines**, as absolute times converted per hop, and refuse work that cannot finish inside the remaining budget.
- **Jitter every periodic action.** Cool-downs, cron, TTLs, backoff, health checks, token refresh. Anything on a fixed timer is synchronised by default.
- **Retry at exactly one layer**, and budget it there. Three layers of three attempts is 27×.
- **Place replicas in different failure domains**, or hedging buys you nothing when it matters most.

## Think about it

1. Your fan-out is N = 40 and each backend has a p99 of 80 ms. Without running anything, estimate the fraction of user requests containing at least one call over 80 ms, and the percentile of a single backend that corresponds to your composed median. What single backend percentile should that team's SLO actually be written against?
2. Section 3 broke because a constant delay met a moving distribution. Design a hedge delay that adapts — what would you measure, over what window, and what stops your adaptive delay from itself becoming a feedback loop during overload?
3. You have hedging with a 5% budget, and during an incident the hedge rate pins at 5% (budget exhausted) while the hedge *win* rate collapses toward zero. What is happening, and which of the techniques in this lesson is the right response? Which would be actively harmful?
4. Your service is a fan-out aggregator whose callers cannot tolerate partial results today. Write the response-contract change that would let them, and list what breaks in existing clients when you ship it. Whose decision is it?
5. Tied requests need the server to cancel enqueued-but-unstarted work. Take an HTTP service you know and trace what actually happens end to end when a client disconnects mid-request. At which layer, if any, does the work stop — and what would you have to change to make the cancel effective?

## Key takeaways

- **At fan-out, your p99 becomes everyone's median.** With backends at a p50 of 9.2 ms and a p99 of 105.0 ms, the measured 100-way request had a **p50 of 129.0 ms** — 1.23× the p99 of every service it called — because `1 − 0.99^100 = 63.4%` of requests contain at least one tail call (measured: **63.7%**). A request's latency is the **maximum** of N samples, so a backend's p99.9 is the **p90.5** of a 100-way fan-out.
- **The fix is not a faster backend, it is a different way of issuing requests.** Tail variability comes from shared, intermittent, largely unfixable sources — GC, co-tenants, compaction, thermal throttling. Halving p from 1% to 0.5% only moves the 100-way "at least one slow" figure from 63.4% to 39.4%. Build a **tail-tolerant** system instead, the same move as reliable storage from unreliable disks (Dean & Barroso, CACM 56(2), 2013).
- **Hedging at the p95 is the best trade in this lesson.** Measured: the 100-way median fell **128.7 → 35.7 ms** and the p99 **1583.9 → 116.5 ms** for **5.0% more backend load**. The sweep shows the knee — the first 1% of load removes 69% of the p99.9, and going from 5% to 49.9% extra load buys only another 16 ms.
- **An unbudgeted hedge is a retry storm.** A delay calibrated at ρ = 0.50 and left alone hedged **95.2%** of requests at ρ = 0.85, drove offered load to 1.95× (effective ρ = 1.66), and made the p99 **20× worse — 466 → 9401 ms**. A 5% budget denied 18,365 hedges and held p99 at 343 ms. Budget hedges for the same reason you budget retries (Phase 8 Lesson 11).
- **Tied requests trade a cross-server message for the hedge delay, and only work if the server can cancel.** Issuing 100% second copies cost **11.2%** duplicate work (vs hedging's 12.6%) and gave a p99 of **157.3 ms vs 308.6 ms** — because 91.4% of copies were cancelled while still queued. Remove the cancel path and the identical policy wastes **53.0%** of service time and yields a p99 of 5514 ms.
- **Hedging dies on correlated slowness, and this is not a footnote.** Same technique, same 8.9% extra load: the median improved **8.86×** under independent slowness and **1.02×** when both replicas sat behind one shared cause. Correlated slowness is a blast-radius problem (Lesson 9); replica placement is therefore a latency decision, not only an availability one.
- **Correlation is what turns 300 good instances into an incident.** 300 unjittered circuit breakers peaked at 158 simultaneous probes, overwhelmed 22 windows, burned 3,300 failed probes and **never recovered** in 60 s; jittering the same cool-down peaked at 14 and closed everything in **7.61 s**. Retries multiply rather than add — three layers of three attempts is **27×**, or **1.33×** with a 10% budget per layer. **Jitter every periodic action.**
- **A deadline is an absolute time; a timeout is three of them in a row.** Three hops with independent 1 s timeouts and propagated deadlines had an **identical p50 of 594 ms** — and worst cases of **2664 ms vs 1000 ms**, with **10.4% of requests finishing after the caller left** and **38.3 ms per request** of work done for nobody, against 0.0 for propagated. Pass the remaining budget, and refuse work that cannot finish inside it.

Next: [Capacity Planning: Headroom, Peak & What to Actually Buy](../12-capacity-planning/) — how much headroom the techniques in this lesson actually require, why the answer is never "run at 95%", and what to buy when the peak is not the average.
