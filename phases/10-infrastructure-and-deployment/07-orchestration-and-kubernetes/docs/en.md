# Orchestration: Control Loops, Schedulers & Kubernetes

> A machine dies at 02:00 and forty containers go with it. The transferable idea is not Kubernetes — it is a loop that observes what is running, subtracts it from what should be running, and closes the gap without being asked. Measured here: that loop restored full capacity in 2 ticks with nobody awake. Measured also: the same machine death cost **66.7% of serving capacity when the replicas were bin-packed and 16.7% when they were spread** — a 4× difference decided by a scheduler flag, months before the failure. And the property that makes the loop survivable at all: with 20% of failure events dropped, an event-driven reconciler converged in **5 of 10 runs**; the one that re-observes state converged in **10 of 10**.

**Type:** Build
**Languages:** Python
**Prerequisites:** [Infrastructure as Code: Desired State, Plan, Apply & Drift](../06-infrastructure-as-code/), [What a Container Actually Is](../02-what-a-container-actually-is/)
**Time:** ~95 minutes

## The Problem

You run forty containers across six machines. It works. You built it with the tools from the last six lessons: images pinned by digest, config in the environment, machines declared in code. Deploys are a script that SSHes to each host in turn and restarts things. It is not elegant but it is honest, and you understand every line of it.

It is 02:14 on a Saturday. `node-a` — one of the six — loses a power supply. Here is what happens, in order.

**02:14 — the containers stop existing.** Not "become unhealthy". The machine is gone; the eight containers it was running are gone with it. Nothing wrote a log line, because the thing that would have written it is the thing that died.

**02:14 — nobody notices.** Your monitoring pages on *error rate*, and your error rate did not move: the load balancer is still sending traffic to the other five machines, which are now doing 100% of the work with 83% of the fleet. Latency creeps up. It is 02:14 on a Saturday; there is no traffic to speak of. The dashboard is green.

**02:31 — the load balancer notices.** Its health checks against `node-a` have been failing for seventeen minutes. Whether it removed the target depends entirely on whether someone configured `unhealthyThresholdCount` on the target group, which someone did, eighteen months ago, for a different service. Half your requests to `node-a` have been timing out this whole time.

**07:40 — a human notices.** The morning shift sees the graph. Now the interesting part begins, because every question that follows has to be answered *by a person*, at a keyboard, with incomplete information:

- Which eight containers were on `node-a`? (Your deploy script wrote that down. On `node-a`.)
- Which machines have room for them? Not "which have free RAM right now" — which have room *after* accounting for what the remaining containers are about to grow into.
- If you put all eight on `node-b`, will `node-b` fall over? It is already running seven.
- Two of those eight were the only two replicas of the payments consumer. Were they? Was there a third?
- Once you place them, who tells the load balancer the new addresses?
- What if `node-b` dies while you are doing this?

At three machines this is a Tuesday. You know the machines by name; you can hold the whole layout in your head. At thirty machines it is not a harder version of the same job — **it is a different job, and it is one no human should be doing.** The work is not creative. It is arithmetic under constraints, performed continuously, at 02:14, correctly.

Name what you actually need. Not "a deployment tool". You need something that **continuously compares what should be running with what is running, and closes the gap without being asked** — and that keeps doing it, forever, including at 02:14, including when its own machinery has just been partly destroyed, including when the message telling it something broke never arrives.

That thing is a **control loop**. Everything in this lesson is a consequence of it.

## The Concept

### The control loop is the whole idea

Lesson 6 built a plan/apply engine: read declared state, read actual state, compute a diff, execute the diff. Look at that sequence again with fresh eyes.

```text
observe actual state  ->  diff against declared state  ->  act to close the gap
```

**Lesson 6 ran that loop once, by a human, when the human remembered to.** Orchestration is the identical loop run **continuously, by a machine, forever.** That is the entire conceptual step, and it is the spine of this phase. `terraform apply` is a control loop with a human as the scheduler; an orchestrator is `terraform apply` with the human removed and the interval set to "always".

Three properties fall out of "forever", and each one is worth naming:

- **Idempotence stops being a nicety.** A loop that runs a thousand times a day must produce the same result on pass 1,000 as on pass 1. If your action is "create a replica" rather than "ensure 12 replicas exist", you will have 12,000 replicas by lunchtime.
- **Convergence replaces correctness-at-a-moment.** You never ask "is the system right?" — you ask "is the system *getting* right, and how fast?" The measured answer in the Build It is **12 replicas Running by tick 5** from a cold start, and **2 ticks to recover** from a machine dying.
- **Failure becomes an input, not an exception.** A dead machine is not an error condition requiring special handling. It is simply a smaller observed number on the next pass. There is no `except NodeDied:` anywhere in the Build It, and that is not an oversight.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 546" width="100%" style="max-width:840px" role="img" aria-label="The control loop drawn as observe, diff, act, repeat: declared state feeds the diff step, the cluster feeds the observe step, and the act step changes the cluster, with no exit condition. Below, an edge-triggered reconciler and a level-triggered one are compared over three node failures with twenty percent event loss: the edge-triggered one misses a delivered event and stays permanently short, converging in five of ten runs, while the level-triggered one re-observes every tick and converges in ten of ten.">
  <defs>
    <marker id="l07-a1" markerWidth="10" markerHeight="10" refX="6.5" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker>
  </defs>
  <text x="440" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">Observe, diff, act, repeat — and why it must be level-triggered</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">

    <g fill="none" stroke-width="2" stroke-linejoin="round">
      <rect x="248" y="46" width="384" height="52" rx="10" fill="#3553ff" fill-opacity="0.12" stroke="#3553ff"/>
      <rect x="120" y="132" width="146" height="60" rx="10" fill="#7f7f7f" fill-opacity="0.10" stroke="currentColor" stroke-opacity="0.6"/>
      <rect x="367" y="132" width="146" height="60" rx="10" fill="#e0930f" fill-opacity="0.14" stroke="#e0930f"/>
      <rect x="614" y="132" width="146" height="60" rx="10" fill="#0fa07f" fill-opacity="0.13" stroke="#0fa07f"/>
      <rect x="120" y="228" width="640" height="52" rx="10" fill="#7c5cff" fill-opacity="0.12" stroke="#7c5cff"/>
    </g>

    <g fill="currentColor" text-anchor="middle">
      <text x="440" y="66" font-size="11.5" font-weight="700" fill="#3553ff">DECLARED STATE — the only thing a human writes</text>
      <text x="440" y="86" font-size="10" opacity="0.9">web: 12 replicas &#8195; 500m cpu / 512Mi each &#8195; spread maxSkew=1</text>
      <text x="193" y="156" font-size="12" font-weight="700">1 &#183; OBSERVE</text>
      <text x="193" y="173" font-size="9" opacity="0.85">count what is really</text>
      <text x="193" y="185" font-size="9" opacity="0.85">Running, right now</text>
      <text x="440" y="156" font-size="12" font-weight="700" fill="#e0930f">2 &#183; DIFF</text>
      <text x="440" y="173" font-size="9" opacity="0.85">declared 12 &#8722; observed 10</text>
      <text x="440" y="185" font-size="9" opacity="0.85">= +2</text>
      <text x="687" y="156" font-size="12" font-weight="700" fill="#0fa07f">3 &#183; ACT</text>
      <text x="687" y="173" font-size="9" opacity="0.85">schedule 2 replicas</text>
      <text x="687" y="185" font-size="9" opacity="0.85">onto nodes with room</text>
      <text x="440" y="248" font-size="11.5" font-weight="700" fill="#7c5cff">THE CLUSTER — actual state, which changes without asking you</text>
      <text x="440" y="266" font-size="9.5" opacity="0.9">node-a died at 02:00 &#8195; 2 Running replicas vanished &#8195; nobody was told</text>
    </g>

    <g fill="none" stroke="currentColor" stroke-width="1.7">
      <path d="M266 162 L 361 162" marker-end="url(#l07-a1)"/>
      <path d="M513 162 L 608 162" marker-end="url(#l07-a1)"/>
      <path d="M440 98 L 440 126" marker-end="url(#l07-a1)"/>
      <path d="M150 224 L 150 198" marker-end="url(#l07-a1)"/>
      <path d="M730 198 L 730 222" marker-end="url(#l07-a1)"/>
    </g>
    <g fill="currentColor" font-size="9" opacity="0.85">
      <text x="98" y="216" text-anchor="end">read</text>
      <text x="782" y="216">write</text>
      <text x="452" y="118">declared</text>
    </g>
    <text x="440" y="300" font-size="10.5" text-anchor="middle" fill="currentColor" font-weight="700">the loop has no exit condition — measured: 12 Running by tick 5, and 2 ticks to recover from node-a</text>

    <g fill="none" stroke-width="2" stroke-linejoin="round">
      <rect x="16" y="318" width="416" height="180" rx="12" fill="#d64545" fill-opacity="0.08" stroke="#d64545"/>
      <rect x="448" y="318" width="416" height="180" rx="12" fill="#0fa07f" fill-opacity="0.09" stroke="#0fa07f"/>
    </g>
    <g fill="currentColor" text-anchor="middle">
      <text x="224" y="342" font-size="12.5" font-weight="700" fill="#d64545">EDGE-TRIGGERED — acts on events</text>
      <text x="656" y="342" font-size="12.5" font-weight="700" fill="#0fa07f">LEVEL-TRIGGERED — acts on state</text>
      <text x="224" y="359" font-size="9" opacity="0.85">&quot;a node failed&quot; arrives; it adjusts its own count</text>
      <text x="656" y="359" font-size="9" opacity="0.85">ignores events; re-counts the cluster every tick</text>
    </g>

    <g fill="none" stroke="currentColor" stroke-width="1.4">
      <path d="M40 400 L 412 400"/>
      <path d="M472 400 L 844 400"/>
    </g>
    <g fill="none" stroke-width="1.8">
      <path d="M110 372 L 110 394" stroke="#e0930f" marker-end="url(#l07-a1)"/>
      <path d="M542 372 L 542 394" stroke="#e0930f" marker-end="url(#l07-a1)"/>
      <path d="M340 372 L 340 394" stroke="#e0930f" marker-end="url(#l07-a1)"/>
      <path d="M772 372 L 772 394" stroke="#e0930f" marker-end="url(#l07-a1)"/>
    </g>
    <g stroke="#d64545" stroke-width="2.4" fill="none">
      <path d="M218 374 L 234 390"/><path d="M234 374 L 218 390"/>
    </g>
    <path d="M650 372 L 650 394" fill="none" stroke="#e0930f" stroke-width="1.8" marker-end="url(#l07-a1)"/>

    <g fill="currentColor" font-size="9" text-anchor="middle">
      <text x="110" y="368" opacity="0.85">fail 1</text>
      <text x="226" y="368" fill="#d64545" font-weight="700">fail 2 DROPPED</text>
      <text x="340" y="368" opacity="0.85">fail 3</text>
      <text x="542" y="368" opacity="0.85">fail 1</text>
      <text x="650" y="368" opacity="0.85">fail 2</text>
      <text x="772" y="368" opacity="0.85">fail 3</text>
    </g>
    <path d="M40 414 L 226 414" fill="none" stroke="#0fa07f" stroke-width="3"/>
    <path d="M226 414 L 412 414" fill="none" stroke="#d64545" stroke-width="3"/>
    <path d="M472 414 L 844 414" fill="none" stroke="#0fa07f" stroke-width="3"/>
    <g fill="currentColor" font-size="9">
      <text x="46" y="429" opacity="0.85">12 Running</text>
      <text x="406" y="429" text-anchor="end" fill="#d64545" font-weight="700">10 Running — forever</text>
      <text x="478" y="429" opacity="0.85">12 Running</text>
      <text x="838" y="429" text-anchor="end" fill="#0fa07f" font-weight="700">12 Running</text>
    </g>

    <g fill="currentColor">
      <text x="40" y="454" font-size="10" font-weight="700">measured, 10 runs x 3 node failures, 20% event loss</text>
      <text x="40" y="470" font-size="10">converged: 5 of 10 &#8195; avg Running 10.5 / 12</text>
      <text x="40" y="486" font-size="9.5" opacity="0.9">at 50% loss: 2 of 10. One miss is permanent.</text>
      <text x="472" y="454" font-size="10" font-weight="700">same runs, same dropped events</text>
      <text x="472" y="470" font-size="10">converged: 10 of 10 &#8195; avg Running 12.0 / 12</text>
      <text x="472" y="486" font-size="9.5" opacity="0.9">at 50% loss: still 10 of 10. A miss costs one tick.</text>
    </g>
    <text x="440" y="524" font-size="11" text-anchor="middle" fill="currentColor" opacity="0.9">An edge-triggered system is only as correct as its least reliable message. A level-triggered one re-derives the truth every pass.</text>
  </g>
</svg>
```

### Level-triggered vs edge-triggered

This is the single most important robustness property in the lesson, it has a precise definition, and it is almost always explained badly. The names come from digital electronics, where an input can be sampled either on a **transition** (a rising edge) or on a **held value** (a level).

- **Edge-triggered** means *react to changes*. Something publishes "node-a failed"; you receive it; you act on it. Your correctness depends on receiving every message exactly once, in order.
- **Level-triggered** means *react to state*. You look at the world, see 10 replicas where you declared 12, and act on the discrepancy. You do not care what happened, when, or how many times.

Stated that way it sounds like an efficiency trade-off — events are cheap, polling is wasteful. It is not an efficiency trade-off. It is a **correctness** trade-off, and the asymmetry is total:

> **A missed event breaks an edge-triggered system permanently. A missed observation costs a level-triggered system one tick.**

There is no path by which an edge-triggered reconciler recovers from a lost message, because nothing later in its life ever re-derives the truth — its belief about the world is a running total, and a running total with a dropped term is wrong forever. The level-triggered one throws its beliefs away and recounts on every pass, so a dropped message is not even an event: it is a pass that happened to find nothing to do.

The Build It runs both against identical scenarios with a configurable event-drop rate. With **20% of failure events dropped, the edge-triggered reconciler converged in 5 of 10 runs and averaged 10.5 of 12 replicas; the level-triggered one converged in 10 of 10 and averaged 12.0.** At 50% loss the edge version managed **2 of 10**; the level version was still **10 of 10**. And note the honest part of that table: **at 0% loss both converge in 10 of 10.** Edge-triggering is not wrong. It is *fragile*, and it fails in exactly the conditions — a network partition, an overloaded queue, a restarted process — under which failures actually happen.

Real orchestrators are level-triggered *and* use events, which sounds like a contradiction until you see the shape. Kubernetes controllers subscribe to a watch stream, but the event does not carry the instruction — it only carries a *key*, which is put on a work queue, and the handler then **re-reads the full current object** and reconciles it from scratch. The event is a hint about *when* to look, never a description of *what to do*. Add a periodic full resync on top, and a dropped event costs you latency, not correctness. That is the pattern to copy in your own systems, and the phrase to keep is: **events are an optimisation of polling, not a replacement for it.**

### The scheduler: arithmetic under constraints

The loop decides *how many*. The scheduler decides *where*, and it is a genuinely hard problem being solved thousands of times a second. Every real scheduler has the same two-phase shape:

1. **Filter** (Kubernetes calls these *predicates*): eliminate every node that *cannot* host this work. Not enough free CPU. Not enough free memory. Wrong architecture. Tainted. Would violate an anti-affinity rule.
2. **Score** (*priorities*): rank the survivors and take the best. This is where policy lives.

**Requests and limits are two different numbers and confusing them causes outages.** This is the tie-back to Lesson 2's cgroups, and the distinction is sharp:

- A **request** is what the *scheduler* reserves. It is a promise about how much room to set aside, and it is the only number the scheduler looks at. It is not enforced at runtime at all — a container requesting 500m of CPU can use 3 cores if 3 cores are idle.
- A **limit** is what the *kernel* enforces, and it becomes a literal cgroup v2 value on the node: `cpu.max` and `memory.max`, the files you read in Lesson 2. Exceeding them does not fail the same way. **CPU is throttled** — your process is simply given fewer microseconds per period and gets slower, which shows up as mysterious p99 latency and no error at all. **Memory is killed** — the kernel OOM (out of memory) killer terminates the process, and the container exits with code 137.

Two consequences follow immediately. **A workload with no request is scheduled as if it were free**, so the node accepts it, and every other pod on that node now competes with a ghost. **A memory limit equal to your steady-state usage is a timer**, because the one request with a large response body will cross it, and 137 is the least informative error message in production.

The scoring function is where you choose your blast radius, months before anything breaks:

- **Bin-packing** (Kubernetes: `MostAllocated`) fills each node before opening the next. It minimises the number of machines you pay for. In the Build It, 12 replicas at 500m on 4000m nodes bin-pack onto **2 of 6 machines, with 8 replicas — 67% of the fleet — on one box**.
- **Spreading** (Kubernetes: `LeastAllocated`, and it is the **default**) picks the emptiest node. The same 12 replicas land **2 per machine across all 6**.

Then there are the constraints that make placement a hard guarantee rather than a lucky outcome of scoring:

- **Node affinity** — "run me on nodes with SSDs / this instance type / this architecture." A property of the node.
- **Pod affinity / anti-affinity** — "run me near / away from *other work*." Anti-affinity is how you say "never put two replicas of the same thing on one machine". As a *hard* rule (`requiredDuringScheduling…`) it will leave replicas unschedulable rather than break it; as a *soft* rule (`preferredDuringScheduling…`) it is a scoring bonus that can be ignored.
- **Topology spread constraints** — the modern, more precise form: "keep the count of my replicas in any *topology domain* within `maxSkew` of the minimum." Set the domain to the hostname and you spread across machines; set it to the zone label and you spread across **availability zones** (an AZ is a physically separate datacentre within a cloud region, with independent power and network, precisely so that it can fail alone).
- **Taints and tolerations** — the inverted mechanism, and the only one where the *node* pushes back. A taint on a node says "nothing may schedule here unless it explicitly says it can handle me." Tolerations on the workload are that explicit statement. This is how GPU nodes, dedicated hardware and drained machines keep general traffic off themselves. Note the direction: affinity is the workload choosing a node; a taint is a node refusing workloads.

**Why spreading is not merely tidier.** The Build It kills one machine under each strategy and measures the result. Bin-packed, `node-a` held 8 of 12 replicas, so its death cost **66.7% of serving capacity**, took **3 ticks** to recover, and lost **20 replica-ticks** of work. Spread, the same failure cost **16.7%**, recovered in **2 ticks**, and lost **4 replica-ticks** — a **4.0× smaller blast radius and 5.0× less lost capacity**. Both configurations had exactly the same total capacity available. The only difference was a scoring preference set long before.

Then it kills an entire availability zone, and the numbers separate again: bin-packed loses **100%** and spends **2 ticks at literally zero capacity**; spread-across-nodes loses **50%**; spread-across-*zones* loses **33.3%**. Spreading over nodes did not protect the zone, because zone-1 happened to contain 3 of the 6 machines, so an even spread over nodes was an uneven spread over zones. **A failure domain is whatever fails together; spreading over the wrong one buys nothing.**

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 560" width="100%" style="max-width:840px" role="img" aria-label="Two placements of the same twelve replicas across six nodes in three availability zones, compared under failure. Bin-packing fills node-a with eight replicas and node-b with four; when node-a dies, eight of twelve replicas vanish, sixty-six point seven percent of serving capacity, and recovery takes three ticks with a deficit of twenty replica-ticks. A topology spread constraint puts two replicas on each of the six nodes; the same node failure costs two of twelve, sixteen point seven percent, recovering in two ticks with a deficit of four replica-ticks. A table underneath shows the same comparison for the loss of a whole availability zone, where bin-packing loses one hundred percent and spends two ticks at zero capacity, node-spread loses fifty percent and zone-spread loses thirty-three point three percent.">
  <text x="440" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">The scheduler decides your blast radius before anything breaks</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">

    <g fill="none" stroke-width="2" stroke-linejoin="round">
      <rect x="16" y="44" width="416" height="292" rx="12" fill="#d64545" fill-opacity="0.07" stroke="#d64545"/>
      <rect x="448" y="44" width="416" height="292" rx="12" fill="#0fa07f" fill-opacity="0.08" stroke="#0fa07f"/>
    </g>
    <g fill="currentColor" text-anchor="middle">
      <text x="224" y="68" font-size="12.5" font-weight="700" fill="#d64545">BIN-PACK &#183; MostAllocated</text>
      <text x="224" y="85" font-size="9" opacity="0.85">cheapest: 12 replicas fit on 2 machines</text>
      <text x="656" y="68" font-size="12.5" font-weight="700" fill="#0fa07f">SPREAD &#183; topologySpread maxSkew=1</text>
      <text x="656" y="85" font-size="9" opacity="0.85">6 machines, idle cores you still pay for</text>
    </g>

    <g fill="currentColor" font-size="8.5" opacity="0.7">
      <text x="24" y="106">node &#8195; zone &#8195; capacity 4000m cpu &#8195; request 500m</text>
      <text x="456" y="106">node &#8195; zone &#8195; capacity 4000m cpu &#8195; request 500m</text>
    </g>

    <g fill="none" stroke-width="1.4" stroke="currentColor" stroke-opacity="0.45">
      <rect x="86" y="114" width="314" height="18" rx="4"/>
      <rect x="86" y="140" width="314" height="18" rx="4"/>
      <rect x="86" y="166" width="314" height="18" rx="4"/>
      <rect x="86" y="192" width="314" height="18" rx="4"/>
      <rect x="86" y="218" width="314" height="18" rx="4"/>
      <rect x="86" y="244" width="314" height="18" rx="4"/>
      <rect x="518" y="114" width="314" height="18" rx="4"/>
      <rect x="518" y="140" width="314" height="18" rx="4"/>
      <rect x="518" y="166" width="314" height="18" rx="4"/>
      <rect x="518" y="192" width="314" height="18" rx="4"/>
      <rect x="518" y="218" width="314" height="18" rx="4"/>
      <rect x="518" y="244" width="314" height="18" rx="4"/>
    </g>

    <g fill="#d64545" fill-opacity="0.55" stroke="#d64545" stroke-width="1">
      <rect x="88" y="116" width="35" height="14" rx="2"/><rect x="127" y="116" width="35" height="14" rx="2"/>
      <rect x="166" y="116" width="35" height="14" rx="2"/><rect x="205" y="116" width="35" height="14" rx="2"/>
      <rect x="244" y="116" width="35" height="14" rx="2"/><rect x="283" y="116" width="35" height="14" rx="2"/>
      <rect x="322" y="116" width="35" height="14" rx="2"/><rect x="361" y="116" width="35" height="14" rx="2"/>
      <rect x="520" y="116" width="35" height="14" rx="2"/><rect x="559" y="116" width="35" height="14" rx="2"/>
    </g>
    <g fill="#0fa07f" fill-opacity="0.45" stroke="#0fa07f" stroke-width="1">
      <rect x="88" y="142" width="35" height="14" rx="2"/><rect x="127" y="142" width="35" height="14" rx="2"/>
      <rect x="166" y="142" width="35" height="14" rx="2"/><rect x="205" y="142" width="35" height="14" rx="2"/>
      <rect x="520" y="142" width="35" height="14" rx="2"/><rect x="559" y="142" width="35" height="14" rx="2"/>
      <rect x="520" y="168" width="35" height="14" rx="2"/><rect x="559" y="168" width="35" height="14" rx="2"/>
      <rect x="520" y="194" width="35" height="14" rx="2"/><rect x="559" y="194" width="35" height="14" rx="2"/>
      <rect x="520" y="220" width="35" height="14" rx="2"/><rect x="559" y="220" width="35" height="14" rx="2"/>
      <rect x="520" y="246" width="35" height="14" rx="2"/><rect x="559" y="246" width="35" height="14" rx="2"/>
    </g>

    <g fill="currentColor" font-size="9.5">
      <text x="24" y="127">node-a</text><text x="24" y="153">node-b</text><text x="24" y="179">node-c</text>
      <text x="24" y="205">node-d</text><text x="24" y="231">node-e</text><text x="24" y="257">node-f</text>
      <text x="456" y="127">node-a</text><text x="456" y="153">node-b</text><text x="456" y="179">node-c</text>
      <text x="456" y="205">node-d</text><text x="456" y="231">node-e</text><text x="456" y="257">node-f</text>
    </g>
    <g fill="currentColor" font-size="8" opacity="0.65" text-anchor="end">
      <text x="80" y="127">z1</text><text x="80" y="153">z1</text><text x="80" y="179">z1</text>
      <text x="80" y="205">z2</text><text x="80" y="231">z2</text><text x="80" y="257">z3</text>
      <text x="512" y="127">z1</text><text x="512" y="153">z1</text><text x="512" y="179">z1</text>
      <text x="512" y="205">z2</text><text x="512" y="231">z2</text><text x="512" y="257">z3</text>
    </g>

    <g stroke="#d64545" stroke-width="2.6" fill="none">
      <path d="M406 116 L 418 130"/><path d="M418 116 L 406 130"/>
      <path d="M838 116 L 850 130"/><path d="M850 116 L 838 130"/>
    </g>
    <g fill="#d64545" font-size="8" font-weight="700" text-anchor="end">
      <text x="400" y="274">red = lost with node-a</text>
      <text x="832" y="274">red = lost with node-a</text>
    </g>

    <g fill="currentColor">
      <text x="24" y="296" font-size="10.5" font-weight="700" fill="#d64545">node-a dies: 8 of 12 gone &#8212; 66.7% of capacity</text>
      <text x="24" y="313" font-size="9.5" opacity="0.95">recovery 3 ticks &#8195; deficit 20 replica-ticks</text>
      <text x="24" y="328" font-size="9.5" opacity="0.95">4 nodes sat idle; the one that died held two thirds</text>
      <text x="456" y="296" font-size="10.5" font-weight="700" fill="#0fa07f">node-a dies: 2 of 12 gone &#8212; 16.7% of capacity</text>
      <text x="456" y="313" font-size="9.5" opacity="0.95">recovery 2 ticks &#8195; deficit 4 replica-ticks</text>
      <text x="456" y="328" font-size="9.5" opacity="0.95">4.0x smaller blast radius, 5.0x less lost work</text>
    </g>

    <text x="440" y="366" font-size="12.5" text-anchor="middle" font-weight="700" fill="currentColor">now lose a whole availability zone &#8212; zone-1 is 3 of the 6 nodes</text>
    <rect x="60" y="382" width="760" height="112" rx="10" fill="#7f7f7f" fill-opacity="0.07" stroke="currentColor" stroke-opacity="0.4" stroke-width="1.6"/>
    <g fill="currentColor" font-size="9" font-weight="700" opacity="0.7">
      <text x="80" y="402">PLACEMENT</text><text x="300" y="402">REPLICAS LOST</text><text x="470" y="402">CAPACITY LOST</text>
      <text x="616" y="402">RECOVERY</text><text x="722" y="402">AT ZERO CAPACITY</text>
    </g>
    <path d="M72 410 L 808 410" fill="none" stroke="currentColor" stroke-width="1" opacity="0.35"/>
    <g fill="currentColor" font-size="10.5">
      <text x="80" y="430" font-weight="700" fill="#d64545">bin-packed</text><text x="300" y="430">12 of 12</text>
      <text x="470" y="430" font-weight="700" fill="#d64545">100.0%</text><text x="616" y="430">4 ticks</text>
      <text x="722" y="430" font-weight="700" fill="#d64545">2 ticks</text>
      <text x="80" y="454" font-weight="700" fill="#e0930f">spread over nodes</text><text x="300" y="454">6 of 12</text>
      <text x="470" y="454" font-weight="700" fill="#e0930f">50.0%</text><text x="616" y="454">3 ticks</text>
      <text x="722" y="454">0 ticks</text>
      <text x="80" y="478" font-weight="700" fill="#0fa07f">spread over zones</text><text x="300" y="478">4 of 12</text>
      <text x="470" y="478" font-weight="700" fill="#0fa07f">33.3%</text><text x="616" y="478">2 ticks</text>
      <text x="722" y="478">0 ticks</text>
    </g>
    <text x="440" y="518" font-size="11" text-anchor="middle" fill="currentColor" opacity="0.95">Spreading over NODES does not protect a ZONE: zone-1 held 3 of 6 nodes, so node-spread put half the fleet in it.</text>
    <text x="440" y="538" font-size="11" text-anchor="middle" fill="currentColor" opacity="0.9">A failure domain is whatever fails together. Bin-packing is a bill you pay in an outage instead of on an invoice.</text>
  </g>
</svg>
```

### Pending is an answer, not an error

The most common beginner confusion, and it is worth being blunt: **`Pending` is not a failure state.** It means the scheduler ran, evaluated every node, found none feasible, and put the work back in the queue. Nothing crashed. Nothing is in a back-off loop. The replica will be scheduled the instant a node becomes feasible — because the loop never stops trying, which is the entire point of a loop.

The reason string tells you exactly which filter rejected which node, and it is generated by the scheduler itself:

```text
0/3 nodes are available: 2 Insufficient cpu, 1 node(s) had untolerated taint {gpu=true}.
```

Read it as three facts: three nodes were considered; two had less free CPU than the request; one refused you because of a taint. Not "the cluster is out of resources" — a specific count of specific rejections. And the second cause, which produces the identical symptom for a completely different reason:

```text
0/3 nodes are available: 3 node(s) didn't match pod anti-affinity rules.
```

In the Build It, that one fires on a cluster with **10,250m of free CPU when the replica requested 250m**. Capacity was never the issue; a constraint was. **A Pending pod on a cluster with free capacity means a constraint, not a shortage** — and the string in the Events section is the difference between a five-minute fix and an afternoon.

### Controllers are many small loops, not one big one

The last structural idea. You do not build *an* orchestrator; you build a population of independent loops, each owning exactly one invariant, all level-triggered, none aware of the others:

- one loop keeps N replicas of a workload existing;
- one loop marks a node unhealthy when its agent stops reporting;
- one loop keeps the list of healthy endpoints behind a service name current;
- one loop binds a storage claim to a real volume;
- one loop runs a job to completion and no further;
- one loop adjusts N based on a metric.

They coordinate only through **shared state**, never by calling each other. The replica loop does not know the endpoint loop exists; it writes a replica, and the endpoint loop notices a replica and writes an endpoint. This is why the architecture survives its own components failing — a crashed loop stops maintaining *its* invariant while every other invariant continues to hold, and when it restarts it re-observes and catches up, because it kept no state of its own worth losing. Rolling updates are simply one more loop with a slightly cleverer diff (raise the new version's count, lower the old one's, wait for health between steps). Lesson 11 owns the strategies in full; the thing to notice here is that a rollout needed **no new mechanism**, only a different diff.

### Kubernetes, as the worked example

Everything above is vendor-neutral, and now it earns its vocabulary. **Kubernetes** (from κυβερνήτης, "helmsman"; abbreviated **k8s**) is an open-source orchestrator, originally from Google, now under the Cloud Native Computing Foundation. Its architecture is exactly the population-of-loops design, with one addition that does most of the work.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 596" width="100%" style="max-width:840px" role="img" aria-label="Kubernetes drawn as one shared state store surrounded by independent control loops. The API server sits in the centre and is the only process that writes to etcd, which holds declared and observed state. The scheduler, the controller manager and the kubelet on every node are all clients of the API server, each running its own observe, diff, act loop and writing results back through the API. A panel underneath maps the object vocabulary to the primitives built by hand in this lesson: Pod to a replica, ReplicaSet to the replica count loop, Deployment to a versioned replica set, StatefulSet, DaemonSet, Job and CronJob, Service, Ingress, ConfigMap, Secret, Namespace, PersistentVolumeClaim and PodDisruptionBudget.">
  <defs>
    <marker id="l07-a3" markerWidth="10" markerHeight="10" refX="6.5" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker>
  </defs>
  <text x="440" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">Kubernetes is one store, one door, and many small loops</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">

    <g fill="none" stroke-width="2.2" stroke-linejoin="round">
      <rect x="330" y="140" width="220" height="76" rx="12" fill="#3553ff" fill-opacity="0.13" stroke="#3553ff"/>
      <rect x="320" y="248" width="240" height="60" rx="12" fill="#7c5cff" fill-opacity="0.13" stroke="#7c5cff"/>
    </g>
    <g fill="currentColor" text-anchor="middle">
      <text x="440" y="166" font-size="13" font-weight="700" fill="#3553ff">kube-apiserver</text>
      <text x="440" y="184" font-size="9.5" opacity="0.9">validates, authorises, versions</text>
      <text x="440" y="199" font-size="9.5" opacity="0.9">the ONLY writer to etcd</text>
      <text x="440" y="272" font-size="12.5" font-weight="700" fill="#7c5cff">etcd</text>
      <text x="440" y="292" font-size="9.5" opacity="0.9">declared + observed state, replicated</text>
    </g>
    <path d="M440 216 L 440 244" fill="none" stroke="currentColor" stroke-width="1.8" marker-end="url(#l07-a3)"/>
    <path d="M462 244 L 462 220" fill="none" stroke="currentColor" stroke-width="1.8" marker-end="url(#l07-a3)"/>

    <g fill="none" stroke-width="2" stroke-linejoin="round">
      <rect x="36" y="70" width="212" height="70" rx="10" fill="#0fa07f" fill-opacity="0.12" stroke="#0fa07f"/>
      <rect x="632" y="70" width="212" height="70" rx="10" fill="#0fa07f" fill-opacity="0.12" stroke="#0fa07f"/>
      <rect x="36" y="234" width="212" height="86" rx="10" fill="#e0930f" fill-opacity="0.12" stroke="#e0930f"/>
      <rect x="632" y="234" width="212" height="86" rx="10" fill="#e0930f" fill-opacity="0.12" stroke="#e0930f"/>
    </g>
    <g fill="currentColor" text-anchor="middle">
      <text x="142" y="92" font-size="11.5" font-weight="700" fill="#0fa07f">kube-scheduler</text>
      <text x="142" y="110" font-size="9" opacity="0.9">watches Pods with no node</text>
      <text x="142" y="124" font-size="9" opacity="0.9">filter -&gt; score -&gt; write binding</text>
      <text x="738" y="92" font-size="11.5" font-weight="700" fill="#0fa07f">kube-controller-manager</text>
      <text x="738" y="110" font-size="9" opacity="0.9">~30 loops in one process:</text>
      <text x="738" y="124" font-size="9" opacity="0.9">ReplicaSet, Node, Job, Endpoints</text>
      <text x="142" y="256" font-size="11.5" font-weight="700" fill="#e0930f">kubelet &#183; node-a</text>
      <text x="142" y="274" font-size="9" opacity="0.9">watches Pods bound to me</text>
      <text x="142" y="288" font-size="9" opacity="0.9">starts containers, runs probes</text>
      <text x="142" y="304" font-size="9" opacity="0.9">reports status back up</text>
      <text x="738" y="256" font-size="11.5" font-weight="700" fill="#e0930f">kubelet &#183; node-b &#8230; node-f</text>
      <text x="738" y="274" font-size="9" opacity="0.9">same loop, one per machine</text>
      <text x="738" y="288" font-size="9" opacity="0.9">stops heartbeating when the</text>
      <text x="738" y="304" font-size="9" opacity="0.9">machine dies &#8212; that is the signal</text>
    </g>

    <g fill="none" stroke="currentColor" stroke-width="1.6">
      <path d="M248 108 C 296 108, 300 152, 324 162" marker-end="url(#l07-a3)"/>
      <path d="M324 178 C 300 190, 296 132, 250 126" marker-end="url(#l07-a3)"/>
      <path d="M632 108 C 584 108, 580 152, 556 162" marker-end="url(#l07-a3)"/>
      <path d="M556 178 C 580 190, 584 132, 630 126" marker-end="url(#l07-a3)"/>
      <path d="M248 262 C 300 258, 302 210, 326 200" marker-end="url(#l07-a3)"/>
      <path d="M326 210 C 302 226, 300 282, 250 280" marker-end="url(#l07-a3)"/>
      <path d="M632 262 C 580 258, 578 210, 554 200" marker-end="url(#l07-a3)"/>
      <path d="M554 210 C 578 226, 580 282, 630 280" marker-end="url(#l07-a3)"/>
    </g>
    <text x="440" y="334" font-size="9" text-anchor="middle" fill="currentColor" opacity="0.85">each arrow pair: watch the API for changes &#8594; write the result back. Nothing but the API server touches etcd.</text>
    <text x="440" y="354" font-size="10.5" text-anchor="middle" fill="currentColor" font-weight="700">Every component is a CLIENT running its own observe -&gt; diff -&gt; act loop. None of them talks to any other.</text>
    <text x="440" y="369" font-size="9.5" text-anchor="middle" fill="currentColor" opacity="0.9">Delete the scheduler and the cluster keeps serving; new Pods just stay Pending. That is what decoupling buys.</text>

    <rect x="16" y="382" width="848" height="176" rx="12" fill="#7f7f7f" fill-opacity="0.07" stroke="currentColor" stroke-opacity="0.4" stroke-width="1.6"/>
    <text x="440" y="404" font-size="11.5" text-anchor="middle" font-weight="700" fill="currentColor">the object vocabulary, mapped to what you built</text>
    <g fill="currentColor" font-size="9.5">
      <text x="34" y="426" font-weight="700" fill="#3553ff">Pod</text>
      <text x="34" y="440" opacity="0.9">one Replica: co-scheduled</text>
      <text x="34" y="452" opacity="0.9">containers, one IP, one fate</text>
      <text x="34" y="472" font-weight="700" fill="#3553ff">ReplicaSet</text>
      <text x="34" y="486" opacity="0.9">the loop in section 2:</text>
      <text x="34" y="498" opacity="0.9">keep N Pods existing</text>
      <text x="34" y="518" font-weight="700" fill="#3553ff">Deployment</text>
      <text x="34" y="532" opacity="0.9">a loop over ReplicaSets;</text>
      <text x="34" y="544" opacity="0.9">rolling updates live here</text>

      <text x="242" y="426" font-weight="700" fill="#3553ff">StatefulSet</text>
      <text x="242" y="440" opacity="0.9">stable identity + its own</text>
      <text x="242" y="452" opacity="0.9">volume, ordered rollout</text>
      <text x="242" y="472" font-weight="700" fill="#3553ff">DaemonSet</text>
      <text x="242" y="486" opacity="0.9">one Pod per node, not N</text>
      <text x="242" y="498" opacity="0.9">total: agents and log shippers</text>
      <text x="242" y="518" font-weight="700" fill="#3553ff">Job / CronJob</text>
      <text x="242" y="532" opacity="0.9">run to COMPLETION, then</text>
      <text x="242" y="544" opacity="0.9">stop. On a schedule.</text>

      <text x="450" y="426" font-weight="700" fill="#0fa07f">Service</text>
      <text x="450" y="440" opacity="0.9">a stable name + virtual IP</text>
      <text x="450" y="452" opacity="0.9">over a changing Pod set</text>
      <text x="450" y="472" font-weight="700" fill="#0fa07f">Ingress / Gateway</text>
      <text x="450" y="486" opacity="0.9">HTTP routing and TLS from</text>
      <text x="450" y="498" opacity="0.9">outside the cluster</text>
      <text x="450" y="518" font-weight="700" fill="#0fa07f">ConfigMap / Secret</text>
      <text x="450" y="532" opacity="0.9">config as environment;</text>
      <text x="450" y="544" opacity="0.9">Secret is base64, NOT encrypted</text>

      <text x="672" y="426" font-weight="700" fill="#e0930f">Namespace</text>
      <text x="672" y="440" opacity="0.9">a name scope + a quota</text>
      <text x="672" y="452" opacity="0.9">boundary. Not a sandbox.</text>
      <text x="672" y="472" font-weight="700" fill="#e0930f">PersistentVolumeClaim</text>
      <text x="672" y="486" opacity="0.9">&quot;I need 20Gi&quot; &#8212; declared</text>
      <text x="672" y="498" opacity="0.9">storage, bound by a loop</text>
      <text x="672" y="518" font-weight="700" fill="#e0930f">PodDisruptionBudget</text>
      <text x="672" y="532" opacity="0.9">a floor the VOLUNTARY</text>
      <text x="672" y="544" opacity="0.9">evictions must respect</text>
    </g>
    <text x="440" y="578" font-size="10.5" text-anchor="middle" fill="currentColor" opacity="0.95">HorizontalPodAutoscaler is another loop &#8212; it writes replicas. A CustomResourceDefinition plus your own loop is an operator.</text>
  </g>
</svg>
```

The addition is the **API server**. Rather than letting every loop read and write the state store, Kubernetes puts one process in front of it:

- **etcd** — a replicated key-value store using the Raft consensus algorithm. It holds both declared state (`spec`) and observed state (`status`) for every object. It is the only stateful component; everything else can be deleted and restarted.
- **kube-apiserver** — the only process that talks to etcd. It authenticates, authorises, validates against a schema, applies defaults, and versions every object with a `resourceVersion` so that clients can watch for changes and detect conflicting writes. **This is the single most valuable design decision in the system.** One place enforces the rules; every other component is an ordinary client with no special privileges.
- **kube-scheduler** — a loop watching for Pods with no node assigned. Filter, score, write the binding back through the API. It touches nothing else.
- **kube-controller-manager** — one process containing roughly thirty independent loops (ReplicaSet, Deployment, Node, Job, Endpoints, and so on), each maintaining one invariant.
- **kubelet** — an agent on every machine. It watches for Pods bound to *its* node, tells the container runtime to start them, runs the liveness and readiness probes from [Health Checks & Probes](../../09-logging-monitoring-and-observability/08-health-checks-and-probes/), and reports status back. When a machine dies, its kubelet stops sending heartbeats — **and that silence is the observation the node controller acts on**, which is the level-triggered principle at the level of hardware.

The vocabulary, one line each, each mapped back to something you have built:

| Object | What it is |
|---|---|
| **Pod** | The unit of scheduling: one or more containers that share a network namespace, an IP and a fate. Your `Replica`. Rarely created directly. |
| **ReplicaSet** | The "keep N Pods existing" loop from the Build It. You almost never write one by hand. |
| **Deployment** | A loop over ReplicaSets. Changing the image creates a new ReplicaSet and shifts counts between them — that is a rolling update (Lesson 11). |
| **StatefulSet** | Like a Deployment, but each Pod gets a stable ordinal name, stable DNS, and its own volume, and rollouts are ordered. For databases and anything with identity. |
| **DaemonSet** | "One Pod on *every* node", not "N Pods total". Log shippers ([The Log Pipeline](../../09-logging-monitoring-and-observability/04-the-log-pipeline/)), metrics agents, CNI plugins. |
| **Job / CronJob** | Run to *completion*, not forever. A CronJob is a Job on a schedule — and it can overlap with itself, which is the classic surprise. |
| **Service** | A stable name and virtual IP in front of a changing set of Pods, backed by an `EndpointSlice` that a loop keeps current. This is Lesson 8's whole subject. |
| **Ingress / Gateway API** | HTTP routing, host and path rules, and TLS termination for traffic from outside the cluster. Lesson 9. |
| **ConfigMap** | Non-secret config, injected as environment variables or files. Lesson 5's twelve-factor config, as an API object. |
| **Secret** | The same, for credentials — but **base64 is encoding, not encryption**. Enable encryption at rest and restrict access with RBAC, or your secrets are plaintext in etcd. |
| **Namespace** | A name scope plus a boundary for quotas and policy. It is **not** a security sandbox on its own. |
| **PersistentVolumeClaim** | "I need 20Gi of fast storage" — declared state for storage, matched to a real volume by (of course) a loop. |
| **PodDisruptionBudget** | "At least 4 of my 6 replicas must stay up." It constrains **voluntary** disruptions — node drains, cluster upgrades — and cannot stop a machine catching fire. |
| **HorizontalPodAutoscaler** | A loop whose action is to *write the replica count* on a Deployment, based on a metric. Its output is another loop's input. |

And the thing to take away from that table: **CustomResourceDefinitions and operators are not an advanced topic; they are this table, opened up to you.** A CRD registers a new object kind with the API server. An operator is a control loop you wrote that watches it. `PostgresCluster: 3 replicas, failover enabled` is exactly `web: 12 replicas` with a different diff function. There is no privileged internal API — the built-in controllers use the same endpoints your code would.

### When you do not need Kubernetes

An honest section, because the operational cost of a cluster is real and rarely counted. A Kubernetes cluster is a distributed system you now also operate: etcd needs backups and its own disaster recovery; the control plane needs upgrading roughly quarterly; CNI (Container Network Interface) plugins, CSI (Container Storage Interface) drivers, ingress controllers and RBAC (Role-Based Access Control) policies each have their own failure modes; and your team acquires a vocabulary of about forty new nouns before shipping anything. That is worth paying when you have many services, many teams, and real churn. It is a bad trade when you do not.

- **One VM and systemd.** Genuinely fine for a service that fits on one machine. `systemd` restarts crashed processes — that is a control loop too, with a node pool of one. You lose rescheduling on machine failure, which for many businesses is a "restore from backup within the hour" event, not an outage worth a cluster to prevent.
- **AWS ECS / Fargate, Google Cloud Run, Azure Container Apps.** Managed orchestration: you declare a task or service and the provider runs the loop. You lose extensibility and gain not operating a control plane. For a handful of stateless HTTP services this is almost always the right answer.
- **Nomad.** A single-binary scheduler with the same control-loop model and dramatically less surface. Worth knowing precisely because it makes the point that *the loop is the idea and Kubernetes is one implementation of it.*
- **A managed cluster** (EKS, GKE, AKS) when you do want Kubernetes. Someone else runs etcd and the control plane; you still own the nodes, upgrades and everything above them. This is the default for most teams and should be, but note it removes maybe half the operational burden, not all of it.

The test is not "are we serious engineers". It is: **do you have enough services, enough machines and enough change that a human is doing arithmetic under constraints at 02:14?**

## Build It

[`code/orchestrator.py`](code/orchestrator.py) is a real scheduler and a real control loop over a simulated node pool — standard library only, seeded with `random.Random(7)`, five numbered arguments, total runtime **0.1 s**. The cluster is modelled rather than real (creating six machines inside this sandbox is not on offer), but nothing about the *logic* is simplified: the scheduler filters and scores exactly as described, and the loop has no special cases.

The whole reconciler is twenty lines, and the shape is the lesson:

```python
def reconcile(cluster, spec, tick, strategy, max_ops=MAX_OPS):
    """One pass of the loop. Returns a human-readable action string."""
    owned = cluster.owned(spec.name)                       # 1. OBSERVE
    diff = spec.replicas - len(owned)                      # 2. DIFF
    acts = []

    if diff > 0:                                           # 3. ACT: create
        for _ in range(min(diff, max_ops)):
            ...
    elif diff < 0:                                         # 3. ACT: delete surplus
        ...

    for r in cluster.owned(spec.name):                     # retry every Pending, always
        if r.state == "Pending":
            ...
```

Three details carry the weight. **It counts what exists, not what is healthy** — a Pod that is still booting is counted, or the loop would create replacements for replicas that are merely slow. **`max_ops` rate-limits the action**, so a transient observation error cannot produce a hundred replicas in one pass (Kubernetes does the same with a slow-start batch that doubles: 1, 2, 4, 8…). And **every Pending replica is retried on every pass, unconditionally**, which is why adding a node in section 5 is enough to make things schedule with no other trigger.

The scheduler is the same filter-then-score structure the real one uses, and the loop that builds the rejection reason is the loop that produces the string you read in `kubectl describe`:

```python
    for n in sorted(cluster.nodes.values(), key=lambda x: x.name):
        if not n.ready:
            note("node(s) were not Ready"); continue
        bad = [t for t in n.taints if t not in spec.tolerations]
        if bad:
            note("node(s) had untolerated taint {%s}" % bad[0]); continue
        fc, fm = cluster.free(n.name)
        if fc < spec.cpu:
            note("Insufficient cpu"); continue
        ...
    if not feasible:
        detail = ", ".join("%d %s" % (c, m) for m, c in fails.items())
        return None, "0/%d nodes are available: %s." % (len(cluster.nodes), detail)

    if strategy == "binpack":                      # MostAllocated: fill a node up
        pick = min(feasible, key=lambda n: (cluster.free(n.name)[0] - spec.cpu, n.name))
    else:                                          # LeastAllocated: k8s default
        pick = max(feasible, key=lambda n: (cluster.free(n.name)[0], -ord(n.name[-1])))
```

**The entire bin-pack-versus-spread result is `min` versus `max` on that last expression.** Everything else — the node pool, the workload, the failure, the seed — is identical across the three runs in section 3.

The edge-triggered reconciler in section 4 is deliberately not a straw man. It is competent code that maintains an accurate running count and acts on it:

```python
        if mode == "level":
            reconcile(c, spec, tick, "spread")
        else:
            # Edge-triggered: acts only on its own bookkeeping, never re-observes.
            want = spec.replicas - believed
            for _ in range(min(max(0, want), MAX_OPS)):
                ...
                believed += 1
```

`believed` is updated correctly on every delivered event and on every replica it creates. It has exactly one flaw: when an event is dropped, `believed` is silently wrong, and **nothing in the rest of its life re-derives the truth.** Run it:

```bash
docker compose exec -T app python \
  phases/10-infrastructure-and-deployment/07-orchestration-and-kubernetes/code/orchestrator.py
```

```console
== 1 · DESIRED STATE AND A SCHEDULER ==
  declared: workload 'web', 12 replicas, each requesting 500m cpu / 512Mi mem
  pool: 6 nodes x 4000m cpu / 8192Mi mem  (zone-1: a,b,c  zone-2: d,e  zone-3: f)
  a node fits floor(4000/500) = 8 replicas on cpu, floor(8192/512) = 16 on mem
  -> cpu is the binding constraint. That is the whole of capacity planning.

  BIN-PACK   (MostAllocated: fill a node before opening another)
  node     zone   replicas  cpu used/total       mem used/total
  node-a   zone-1       8    [############] 4000/4000m  [######......]  4096/ 8192Mi
  node-b   zone-1       4    [######......] 2000/4000m  [###.........]  2048/ 8192Mi
  node-c   zone-1       0    [............]    0/4000m  [............]     0/ 8192Mi
  node-d   zone-2       0    [............]    0/4000m  [............]     0/ 8192Mi
  node-e   zone-2       0    [............]    0/4000m  [............]     0/ 8192Mi
  node-f   zone-3       0    [............]    0/4000m  [............]     0/ 8192Mi
  -> 12 replicas on 2 of 6 nodes; largest single node holds 8 (67% of the fleet)

  SPREAD     (LeastAllocated + topology spread, maxSkew=1)
  node     zone   replicas  cpu used/total       mem used/total
  node-a   zone-1       2    [###.........] 1000/4000m  [##..........]  1024/ 8192Mi
  node-b   zone-1       2    [###.........] 1000/4000m  [##..........]  1024/ 8192Mi
  node-c   zone-1       2    [###.........] 1000/4000m  [##..........]  1024/ 8192Mi
  node-d   zone-2       2    [###.........] 1000/4000m  [##..........]  1024/ 8192Mi
  node-e   zone-2       2    [###.........] 1000/4000m  [##..........]  1024/ 8192Mi
  node-f   zone-3       2    [###.........] 1000/4000m  [##..........]  1024/ 8192Mi
  -> 12 replicas on 6 of 6 nodes; largest single node holds 2 (17% of the fleet)

  ZONE-SPREAD(LeastAllocated + spread over zones, maxSkew=1)
  ...
  node-f   zone-3       4    [######......] 2000/4000m  [###.........]  2048/ 8192Mi
  -> 12 replicas on 6 of 6 nodes; largest single node holds 4 (33% of the fleet)

== 2 · THE CONTROL LOOP CONVERGES: OBSERVE -> DIFF -> ACT -> REPEAT ==
  nobody calls 'create'. The loop reads declared state and closes the gap.
  controller starts at most 4 replicas per tick; a replica needs 2 ticks to boot.

  tick  observed(run/start/pend)  declared  diff  action
     1            0/0/0          12    +12  +web-01->node-a +web-02->node-b +web-03->node-c +web-04->node-d
     2            0/4/0          12     +8  +web-05->node-e +web-06->node-f +web-07->node-a +web-08->node-b
     3            4/4/0          12     +4  +web-09->node-c +web-10->node-d +web-11->node-e +web-12->node-f
     4            8/4/0          12     +0  -
     5           12/0/0          12     +0  -
       ---- a human edits the declared replica count: 12 -> 8 ----
     8           12/0/0           8     -4  -web-09 -web-10 -web-11 -web-12
     9            8/0/0           8     +0  -
  converged to 12 Running at tick 5; after the edit, converged to 8 at tick 8.
  the loop scaled UP and DOWN with no scale-up or scale-down code path:
  both directions are the same subtraction, run again every tick.

== 3 · A NODE DIES AT 02:00. THE LOOP DOES NOT NEED TO BE TOLD ==
  12 spread replicas; node-a is destroyed at tick 6. Nobody is paged.

  tick  running  starting  pending  event / action
     4        8         4        0  -
     5       12         0        0  -
     6       10         2        0  !! node-a LOST -- 2 running replicas vanished  +web-13->node-b +web-14->node-c
     7       10         2        0  -
     8       12         0        0  -
  time-to-recovery: 2 ticks (lost at tick 6, back to 12 Running at tick 8).
  no human, no alert, no runbook. The next observation simply disagreed
  with the declared state, and the loop closed the gap.

  ---- the SAME node failure under three placement strategies ----
  strategy      worst node   node-a died: lost   capacity lost   recovery   deficit
                (replicas)                                        (ticks)   (rep-ticks)
  bin-packed         8 (67%)                  8           66.7%          3         20
  node-spread        2 (17%)                  2           16.7%          2          4
  zone-spread        4 (33%)                  2           16.7%          2          4
  bin-packing lost 66.7% of serving capacity to one machine dying;
  spreading lost 16.7%. Same failure, same cluster, 4.0x the blast radius.
  'deficit' integrates the shortfall over time: 20 vs 4 replica-ticks (5.0x).

  ---- now a correlated failure: all of zone-1 (node-a + node-b + node-c) ----
  strategy      lost   capacity lost   recovery   time at ZERO capacity
  bin-packed      12          100.0%          4            2 ticks
  node-spread      6           50.0%          3            0 ticks
  zone-spread      4           33.3%          2            0 ticks
  spreading across NODES does not protect you from losing a ZONE.
  zone-1 holds 3 of 6 nodes, so node-spread put half the fleet in it.
  a failure domain is whatever fails together — pick the right one.

== 4 · LEVEL-TRIGGERED VS EDGE-TRIGGERED, WITH LOSSY EVENTS ==
  identical scenario: 12 replicas, 3 node failures (ticks 5, 11, 17), 30 ticks.
  the edge-triggered reconciler acts on delivered EVENTS and never re-reads
  the world. The level-triggered one ignores events and re-observes each tick.

  event loss   edge: converged   avg running   |   level: converged   avg running
         0%         10 of 10          12.0   |           10 of 10          12.0
        10%          8 of 10          11.3   |           10 of 10          12.0
        20%          5 of 10          10.5   |           10 of 10          12.0
        50%          2 of 10           8.6   |           10 of 10          12.0
  with 20% event loss the edge-triggered reconciler converged in 5 of 10 runs;
  the level-triggered one converged in 10 of 10 at every loss rate, including 50%.
  a missed event breaks an edge-triggered system PERMANENTLY: nothing later
  in the run ever re-derives the truth. A missed OBSERVATION costs one tick.

== 5 · WHY A REPLICA IS 'PENDING' (AND WHY THAT IS NOT AN ERROR) ==
  a 3-node cluster already running 6 'web' replicas at 1000m each:
  node     zone   replicas  cpu used/total       mem used/total
  node-a   zone-1       3    [#########...] 3000/4000m  [####........]  3072/ 8192Mi
  node-b   zone-1       3    [#########...] 3000/4000m  [####........]  3072/ 8192Mi
  node-c   zone-2       0    [............]    0/4000m  [............]     0/ 8192Mi  taint=gpu=true:NoSchedule

  now declare 'batch': 3 replicas, 2000m cpu / 2048Mi each, no toleration.
  batch-07  Pending  0/3 nodes are available: 2 Insufficient cpu, 1 node(s) had untolerated taint {gpu=true}.
  batch-08  Pending  0/3 nodes are available: 2 Insufficient cpu, 1 node(s) had untolerated taint {gpu=true}.
  batch-09  Pending  0/3 nodes are available: 2 Insufficient cpu, 1 node(s) had untolerated taint {gpu=true}.
  that string is what `kubectl describe pod` prints in its Events section.
  Pending means the scheduler ran, found no feasible node, and will retry.
  Nothing crashed. Nothing is retried in a back-off loop. It is a QUEUE.

  add node-d (4000m / 8192Mi) and run one more tick:
  batch-07  Starting -> node-d
  batch-08  Starting -> node-d
  batch-09  Pending  0/4 nodes are available: 3 Insufficient cpu, 1 node(s) had untolerated taint {gpu=true}.
  two fit (2 x 2000m = 4000m, exactly full). The third still cannot.
  add node-e and it schedules — the loop never stopped trying:
  batch-09  Starting -> node-e

  a second cause, same symptom: hard anti-affinity with too few nodes.
  cache-01  Starting -> node-a
  cache-02  Starting -> node-b
  cache-03  Starting -> node-c
  cache-04  Pending  0/3 nodes are available: 3 node(s) didn't match pod anti-affinity rules.
  the cluster has 10250m of free cpu and the replica wants 250m.
  Capacity was never the problem. A CONSTRAINT was. Read the reason string.

  (total wall time 0.1 s, seed=7, fully deterministic)
```

Read what each section proves.

**Section 1** establishes the arithmetic before any drama. A 4000m node fits 8 replicas by CPU and 16 by memory, so **CPU is the binding constraint** — and knowing which of your two resources binds is most of capacity planning. Then the same 12 replicas are placed three ways from identical inputs. Bin-packing puts **8 on `node-a` and 4 on `node-b`, leaving four machines completely empty**; spreading puts **2 on each of the six**. Neither is wrong. The bin-packed cluster could be four machines smaller and the invoice would show it. What the table shows is that **the cost of that saving is denominated in blast radius, and it is invisible until something breaks.**

**Section 2 is the loop with the mask off.** Nobody calls "create". The controller observes 0, subtracts from 12, and starts 4 (its per-tick budget). Next tick it observes 4 *existing* — note that it counts the still-booting ones, or it would create replacements for replicas that were merely slow — and starts 4 more. **All 12 are Running at tick 5.** Then a human edits one number from 12 to 8, and at tick 8 the loop deletes four replicas. **There is no scale-down code path.** Scaling up and scaling down are the same subtraction with a different sign, evaluated again on the next pass. That is what "declarative" buys you, and it is why the same mechanism handles a rollout, an autoscaler and a human typing a number.

**Section 3 is the argument of the lesson.** At tick 6, `node-a` is destroyed. The next observation returns 10 instead of 12, the diff is +2, and two replacements are scheduled onto nodes that still have room. **Full capacity is restored 2 ticks later, and no human was involved at any point.** No alert fired, no runbook was opened, and — this is the part worth sitting with — **there is no error-handling code for this case anywhere in the file.** A dead machine is not an exception; it is a smaller number.

Then the same failure runs under three placements and the numbers separate hard. Bin-packed, `node-a` was holding **8 of 12 replicas: 66.7% of serving capacity vanished in one instant**, recovery took **3 ticks**, and the shortfall integrated to **20 replica-ticks**. Spread, the identical failure cost **16.7%**, recovered in **2 ticks**, and cost **4 replica-ticks** — **a 4.0× smaller blast radius and 5.0× less lost work**, from a scheduler preference chosen weeks earlier. The zone table then removes the last comfort: killing zone-1 costs the bin-packed cluster **100% of capacity with 2 full ticks at zero**, node-spread **50%**, and zone-spread **33.3%**. Spreading across nodes bought nothing against a zone failure because zone-1 held 3 of the 6 machines. **You must spread across the domain that actually fails together, and you have to know which one that is.**

**Section 4 is the cleanest experiment here.** Both reconcilers get the same cluster, the same three node failures, the same random draws, and the same scheduler. At **0% event loss both converge in 10 of 10** — edge-triggering is not broken. At **10% loss the edge version drops to 8 of 10**. At **20%, 5 of 10, averaging 10.5 of 12 replicas** — meaning half the runs finished permanently under-provisioned with no error anywhere, no alert, and a system that believes it is correct. At **50%, 2 of 10 and an average of 8.6**. The level-triggered column does not move: **10 of 10 and 12.0 at every loss rate.** The failure is not proportional to the loss rate in the way you might expect it to be — it is *absorbing*: once an event is missed, that run is broken for its entire remaining lifetime. This is why "we'll just publish an event when something changes" is a decision that looks correct in code review and fails in production, and why the fix is never a more reliable message bus.

**Section 5** removes the last mystery. Three `batch` replicas requesting 2000m go **Pending**, with a reason naming every rejection: `2 Insufficient cpu, 1 node(s) had untolerated taint {gpu=true}`. Add a node and **two of the three schedule immediately** — 2 × 2000m fills 4000m exactly — while the third stays Pending with an updated count (`3 Insufficient cpu`). Add another node and it schedules, with nothing else changing: the loop had been retrying it on every tick the whole time. Then the second cause, which produces the same word for an entirely different reason: `cache-04` is Pending on a cluster holding **10,250m of free CPU while requesting 250m**, because a hard anti-affinity rule allows one replica per node and there are only three nodes. **When something is Pending, the reason string is the answer, and it is already printed.**

## Use It

### Reading a real cluster

`kubectl` is the API server's command-line client. Ninety percent of the value is in reading, and these five commands answer almost every question:

```bash
# What is running, where, and with what IP? -o wide is the flag people forget.
kubectl get pods -o wide

# THE command. Everything the scheduler and kubelet decided about this Pod,
# and at the bottom, the Events section — the reason for Pending, for a
# restart, for an image pull failure. Read this before searching the web.
kubectl describe pod web-7d9f8c6b4-x2klm

# Cluster-wide events, newest last. When several things broke at once,
# this is the timeline. Note events expire (default TTL 1 hour).
kubectl get events --sort-by=.lastTimestamp

# Logs: -p for the PREVIOUS container, which is how you see why it crashed.
kubectl logs web-7d9f8c6b4-x2klm --tail=100
kubectl logs web-7d9f8c6b4-x2klm -p

# Actual usage vs requests. If usage is far below requests, you are paying
# for reserved room nobody uses; if it is above, you sized requests wrong.
kubectl top pods
kubectl top nodes

# Why is the cluster full? Requests, limits and allocatable capacity per node.
kubectl describe node node-a
```

The `Events` section of `kubectl describe pod` is where the scheduler tells you, in plain English, exactly what section 5 printed:

```text
Events:
  Type     Reason            Age   From               Message
  ----     ------            ----  ----               -------
  Warning  FailedScheduling  2m    default-scheduler  0/6 nodes are available:
           2 Insufficient cpu, 3 node(s) didn't match pod topology spread
           constraints, 1 node(s) had untolerated taint {gpu=true}.
```

Two operational traps live in that output. **Events are garbage-collected** (one hour by default), so a Pod that has been Pending since yesterday may show no events at all — check `kubectl get pod -o yaml` and the object's conditions. And **`kubectl top` requires the metrics-server** to be installed; on a bare cluster it simply errors, which is not a sign anything is wrong.

### A Deployment, with every field mapped to this phase

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: web
spec:
  replicas: 12                      # DECLARED STATE. The only number in section 2.
  selector:
    matchLabels: { app: web }       # which Pods this loop OWNS. Change it and the
                                    # loop orphans the old ones and creates 12 more.
  template:
    metadata:
      labels: { app: web }
    spec:
      topologySpreadConstraints:
        - maxSkew: 1                      # section 3: 16.7% blast radius, not 66.7%
          topologyKey: topology.kubernetes.io/zone
          whenUnsatisfiable: DoNotSchedule  # HARD. ScheduleAnyway = a hint only.
          labelSelector:
            matchLabels: { app: web }
      containers:
        - name: web
          image: registry.example.com/web@sha256:9f2c...   # digest, Lesson 4
          resources:
            requests:                   # what the SCHEDULER reserves. Always set it.
              cpu: "500m"               # 500 millicores = half a core
              memory: "512Mi"
            limits:                     # what the KERNEL enforces, via cgroup v2
              memory: "1Gi"             # -> memory.max. Exceed it: OOMKill, exit 137
                                        # NOTE: no cpu limit. See the note below.
          readinessProbe:               # "send me traffic?" — removes from the Service
            httpGet: { path: /readyz, port: 8080 }
            periodSeconds: 3
            failureThreshold: 2
          livenessProbe:                # "am I broken?" — KILLS and restarts. Slow
            httpGet: { path: /healthz, port: 8080 }   # and forgiving, never a dependency
            periodSeconds: 10
            failureThreshold: 3
          lifecycle:
            preStop:
              exec: { command: ["sh", "-c", "sleep 5"] }   # let endpoints propagate
      terminationGracePeriodSeconds: 45  # preStop + longest request, with headroom
---
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: web
spec:
  minAvailable: 10                  # a node drain may take at most 2 of my 12
  selector:
    matchLabels: { app: web }
```

Every field maps to something built or measured. `replicas` is the declared state from section 2. `topologySpreadConstraints` is the difference between 16.7% and 66.7%. `requests` is what the scheduler subtracts in the filter phase; `limits` becomes `memory.max` in the cgroup you read in Lesson 2. The probes are the machine-readable contract from [Health Checks & Probes](../../09-logging-monitoring-and-observability/08-health-checks-and-probes/), and the `preStop` sleep plus `terminationGracePeriodSeconds` are that lesson's drain sequence, expressed as YAML.

Two field-level traps worth stating outright. **`whenUnsatisfiable: ScheduleAnyway` turns your spread constraint into a suggestion** — the scheduler will happily pile replicas onto one node when the cluster is tight, which is exactly when you needed the guarantee. And **a CPU limit is usually a mistake**: exceeding it does not kill your process, it *throttles* it, and CFS-quota throttling produces latency spikes that are extremely hard to diagnose. Set CPU requests always, CPU limits rarely, memory requests and limits both (memory is incompressible — there is no "throttling" a process that needs bytes).

### PodDisruptionBudgets, and the word "voluntary"

A **PDB** constrains **voluntary** disruptions only: node drains, cluster upgrades, autoscaler scale-downs, anything that calls the Eviction API. It does not, and cannot, constrain a power supply failing. Its purpose is to stop your own automation doing what a hurricane would: an upgrade that drains six nodes in sequence will happily take your service to zero if nothing tells it not to.

The trap is on the other side. **A PDB that can never be satisfied blocks node drains forever.** `minAvailable: 3` on a Deployment with `replicas: 3` means no Pod may ever be evicted voluntarily, so cluster upgrades hang and someone eventually deletes the PDB during an incident. Write it as `maxUnavailable: 1`, or as a `minAvailable` strictly below your replica count, and check that the arithmetic still works after an autoscaler scales you down at 03:00.

### Managed options

- **EKS / GKE / AKS** — managed control plane; you own nodes and everything above. GKE Autopilot and EKS Auto Mode also manage the nodes, moving you toward the "declare a workload" model without leaving the Kubernetes API.
- **ECS / Fargate, Cloud Run, Container Apps** — managed orchestration without Kubernetes at all. Cloud Run in particular scales to zero, which Kubernetes does not do natively.
- **Nomad** — the same control-loop model in one binary, if the cost of a cluster is what you are trying to avoid but you still need scheduling.

### Production rules

- **Always set resource requests.** A Pod with no request is scheduled as if it costs nothing, and it will be placed on a node that has no room for it. Every other workload on that node now pays. If you set exactly one thing today, set requests.
- **Spread across the domain that actually fails together.** Node-level spread does not save you from a zone failure — measured at 50% loss versus 33.3% in section 3. Use `topology.kubernetes.io/zone` with `whenUnsatisfiable: DoNotSchedule`.
- **Budget for disruption, and make the budget satisfiable.** Every workload with more than one replica gets a PDB with `maxUnavailable`, never a `minAvailable` equal to the replica count.
- **Read the Events section before searching the web.** The scheduler already told you which filter rejected which node. `0/6 nodes are available: …` is a complete answer, not an error message.
- **Treat the API server as the source of truth, never a node.** SSHing to a machine and running `docker ps` tells you what *is*, not what *should be* — and the difference between those is the only interesting quantity in the system. If they disagree, the loop is mid-convergence, or something outside the loop changed the world, which is the drift from Lesson 6 wearing a different hat.
- **Know your real detection latency.** The Build It recovers in 2 ticks; a stock cluster is much slower on purpose. The node controller waits roughly 40 seconds of missed heartbeats before marking a node `NotReady`, and Pods then carry a default 300-second toleration for `node.kubernetes.io/unreachable` before eviction — call it five and a half minutes from power loss to rescheduling, tuned that way so a network blip does not evacuate a healthy machine. If your business needs less, that is a number you change deliberately and test, not a bug.
- **Never mutate a Deployment's `selector`.** It is immutable in the API for good reason; changing it makes the loop disown its existing Pods and create a full new set beside them.

## Think about it

1. Section 3 measured a 4.0× difference in blast radius between bin-packing and spreading, and the spread cluster used 6 machines where the bin-packed one used 2. Put a price on both sides: at what point does the idle capacity cost more than the outage risk, and which numbers from your own service would you need to answer that honestly rather than by preference?
2. The edge-triggered reconciler in section 4 converged in 10 of 10 runs at 0% event loss and 5 of 10 at 20%. Suppose you cannot switch to level-triggering — you consume a change stream from a system that offers nothing else. What would you add to make it converge anyway, and what does your answer have to assume about the events you receive?
3. A Pod is Pending with `0/6 nodes are available: 6 Insufficient memory`, and `kubectl top nodes` shows every node at 40% memory usage. Both facts are true. Explain how, and say which number you would change.
4. Your liveness probe checks the database. The database has a 30-second failover. Trace what the node agent, the ReplicaSet loop and the scheduler each do over the following two minutes, and identify which loop turns a 30-second blip into a much longer outage. Then say what the same failure does with the check moved to readiness.
5. You have a stateful workload with 3 replicas, a PDB of `minAvailable: 2`, and 3 nodes. The cluster needs a rolling upgrade that drains one node at a time. Walk through what happens, then repeat it with `minAvailable: 3`, and say which of the two failures is worse to discover during a maintenance window.

## Key takeaways

- **Orchestration is Lesson 6's plan/apply loop with the human removed and the interval set to "forever."** Observe actual state, diff against declared state, act to close the gap, repeat. The Build It converges from nothing to **12 Running replicas by tick 5**, scales **12 → 8 at tick 8 with no scale-down code path**, and contains no error handling for a dead machine — a failure is simply a smaller observed number on the next pass.
- **Level-triggered beats edge-triggered on correctness, not efficiency.** With 20% of failure events dropped, the edge-triggered reconciler converged in **5 of 10 runs (avg 10.5 of 12 replicas)** and at 50% loss in **2 of 10 (avg 8.6)**; the level-triggered one converged **10 of 10 at every loss rate**. A missed event breaks an edge-triggered system permanently; a missed observation costs one tick. Events are an optimisation of polling, never a replacement.
- **The scheduler sets your blast radius weeks before the outage.** The same machine failure cost **66.7% of serving capacity bin-packed and 16.7% spread — 4.0× the blast radius and 5.0× the lost work (20 vs 4 replica-ticks)**. Losing a whole zone cost **100% (2 ticks at literally zero capacity), 50% and 33.3%** for bin-packed, node-spread and zone-spread. Spread across the domain that actually fails together.
- **Requests and limits are different numbers with different enforcers.** A **request** is what the scheduler reserves and is never enforced at runtime; a **limit** becomes a cgroup v2 value on the node. Exceeding CPU throttles you into unexplained p99 latency; exceeding memory gets you OOM-killed with **exit code 137**. A workload with no request is scheduled as if it were free.
- **`Pending` is a scheduling outcome, not an error, and the reason string is the answer.** `0/3 nodes are available: 2 Insufficient cpu, 1 node(s) had untolerated taint {gpu=true}` names every rejection. The Build It also produced a Pending replica on a cluster with **10,250m of free CPU for a 250m request** — a hard anti-affinity rule, not a shortage. Add a node and it schedules with no other trigger, because the loop never stopped retrying.
- **Kubernetes is this design with a vocabulary.** One store (etcd), one door (the API server, the only writer), and many small independent loops — scheduler, ~30 controllers, one kubelet per machine — that coordinate only through shared state and never call each other. Pod, ReplicaSet, Deployment, StatefulSet, DaemonSet, Job, Service, PDB and HorizontalPodAutoscaler are all the same loop with different diffs, and a CRD plus your own loop is an operator. **You do not always need it:** a single VM, ECS/Fargate, Cloud Run or Nomad are honest answers when nobody is doing arithmetic under constraints at 02:14.

Next: [Service Discovery & Health-Aware Routing](../08-service-discovery-and-routing/) — the loop moved your replicas to new machines with new addresses in 2 ticks; now something has to notice, and tell every caller, before the next request goes to an IP that no longer exists.
