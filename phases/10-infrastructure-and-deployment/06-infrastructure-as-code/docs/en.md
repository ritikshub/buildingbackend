# Infrastructure as Code: Desired State, Plan, Apply & Drift

> Change one attribute — the network's address range, at the root of the dependency graph — and the plan proposes to replace **6 of 7 resources**, including a 100 GB production database that nobody edited and nobody mentioned. Measured here: `Plan: 6 to add, 1 to change, 6 to destroy`, and the one lifecycle line that refused the whole thing before it ran. Then the other half of the story: four console clicks at 02:40, **3 of 7 resources drifting**, one perfectly healthy server destroyed as collateral, and one object that exists in the cloud, in no state file, and is therefore invisible to every command you can run.

**Type:** Build
**Languages:** Python
**Prerequisites:** [Config, Environments & the Twelve-Factor App](../05-config-and-twelve-factor/)
**Time:** ~85 minutes

## The Problem

**Scene one.** You have inherited a production environment. It works. Nobody knows how it got there.

It was built in a web console over eighteen months by an engineer who left in March. There is a wiki page, last edited two years ago, describing a setup that no longer matches anything. There is a shell script called `setup-prod-FINAL.sh` in someone's home directory that has not run successfully since a provider API changed. The security group rules were adjusted during an incident and never written down. Somebody enabled a flag on the database to fix a replication problem and nobody remembers which flag.

Now you are asked a reasonable question: *how is staging different from production?* You cannot answer it. Not "it takes a while to answer" — you **cannot** answer it, because answering requires comparing two things and only one of them has ever been written down, in a form nobody trusts. You can open two browser tabs and compare what you can see, but the console shows you what it chooses to show you, defaults are invisible, and there are forty-odd resource types. You will find some differences. You will not find all of them. The one that matters is always in the group you did not check.

That is **click-ops**, and its defining property is not that it is manual. It is that **the system has no model of itself.** There is nothing to review, nothing to diff, nothing to recreate from, and no way to know that the thing you are about to change is load-bearing.

**Scene two**, and this is the one that makes people back away from the fix. A team adopts infrastructure as code. Six months in, someone renames a resource in the configuration file — a tidy-up, part of a larger refactor, reviewed and approved. They run the tool. It prints sixty lines of output. Buried on line 34, in the same typeface as everything else:

```text
  # aws_db_instance.main must be replaced
-/+ resource "aws_db_instance" "main" {
      ~ identifier = "prod-main" -> "prod-primary" # forces replacement
```

They type `yes`, because they have typed `yes` two hundred times before and it has always been fine. **The production database is destroyed and a new empty one is created in its place.** The change was a rename.

These are not opposite failures. They are the same missing thing seen from two sides. In scene one there is no truthful model of what exists, so nothing can be reviewed. In scene two there *is* a model, it is truthful, it told you exactly what it was about to do — and it was reviewed by a human who did not know which of the four verbs in that output means *delete your data*. This lesson builds the model, and then teaches you to read it.

## The Concept

### Declarative beats imperative because it can be re-evaluated

An **imperative** description says *how*: create the network, then the subnets, then wait, then the servers. A shell script is imperative, and its defining weakness is that **it is correct exactly once** — the first time, against an empty account. Run it again and it either fails ("that name is taken") or duplicates everything. So the script grows conditionals: *if the network doesn't exist, create it; if it does, check whether the CIDR matches; if not, ...*. Every one of those branches is a hand-written diff, and you will get them wrong, and you will only find out during an incident.

A **declarative** description says *what*: there is a network with this address range, two subnets in it, two servers in those subnets. It contains no ordering and no conditionals. The tool derives both. That is not a stylistic preference — it is what makes the description **idempotent**: applying it once and applying it five times produce the same result. Idempotence sounds like a small mathematical nicety and is in fact the entire operational argument, because it is the property that makes the tool safe to run *unattended*, on every merge, in a pipeline nobody is watching. A thing you can only run once is a thing a human must supervise. A thing you can run any number of times is automation.

This is the same distinction as [Migrations & Schema Evolution](../../03-relational-databases/15-migrations-and-schema-evolution/): a migrations table is a state file, and "which migrations have run?" is exactly the question this lesson's state file answers for infrastructure.

### The central triangle: desired, actual, and the thing in between

Almost everyone starts with a two-box mental model: my code, and the cloud. That model is wrong, and every painful story in this field comes from the box it leaves out.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 476" width="100%" style="max-width:840px" role="img" aria-label="The three corners of infrastructure as code: your declaration is the desired state, the state file is the recorded mapping from each declared address to a real cloud identifier, and the cloud is the actual state. The plan diffs the declaration against the refreshed actual state, apply makes the cloud match the declaration and writes the new mapping into state, and refresh compares the recorded state to the cloud. Drift is the divergence between the recorded state and the actual cloud, measured in this lesson as three of seven managed resources drifted, two attributes changed, one resource vanished, and one extra object created out of band that no state file knows about and that is therefore invisible to the tool.">
  <defs>
    <marker id="l06-a1" markerWidth="10" markerHeight="10" refX="6.5" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker>
    <marker id="l06-a1r" markerWidth="10" markerHeight="10" refX="6.5" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#d64545"/></marker>
    <marker id="l06-a1rs" markerWidth="10" markerHeight="10" refX="0.5" refY="3" orient="auto"><path d="M7,0 L0,3 L7,6 Z" fill="#d64545"/></marker>
  </defs>
  <text x="440" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">Three states, not two — and the tool only ever compares a pair at a time</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <g fill="none" stroke-width="2.2" stroke-linejoin="round">
      <rect x="278" y="50" width="324" height="92" rx="12" fill="#3553ff" fill-opacity="0.12" stroke="#3553ff"/>
      <rect x="24" y="252" width="252" height="110" rx="12" fill="#7c5cff" fill-opacity="0.13" stroke="#7c5cff"/>
      <rect x="604" y="252" width="252" height="110" rx="12" fill="#0fa07f" fill-opacity="0.12" stroke="#0fa07f"/>
    </g>

    <g fill="currentColor">
      <text x="440" y="74" font-size="12.5" font-weight="700" text-anchor="middle" fill="#3553ff">DESIRED — your declaration</text>
      <text x="440" y="94" font-size="10" text-anchor="middle" opacity="0.9">main.tf, in git, reviewed in a pull request</text>
      <text x="440" y="112" font-size="9.5" text-anchor="middle" opacity="0.85">resource "database" "main" { engine = "postgres-16" }</text>
      <text x="440" y="130" font-size="9.5" text-anchor="middle" opacity="0.85">it names WHAT, never HOW or IN WHAT ORDER</text>

      <text x="150" y="276" font-size="12" font-weight="700" text-anchor="middle" fill="#7c5cff">RECORDED — the state file</text>
      <text x="150" y="298" font-size="9.5" text-anchor="middle" opacity="0.9">"database.main" -&gt; "db-18b8ff"</text>
      <text x="150" y="314" font-size="9.5" text-anchor="middle" opacity="0.9">"subnet.app_a"  -&gt; "sub-4d3c1a"</text>
      <text x="150" y="336" font-size="9.5" text-anchor="middle" opacity="0.85">plus every attribute as applied,</text>
      <text x="150" y="351" font-size="9.5" text-anchor="middle" opacity="0.85">passwords included, in plaintext</text>

      <text x="730" y="276" font-size="12" font-weight="700" text-anchor="middle" fill="#0fa07f">ACTUAL — the cloud</text>
      <text x="730" y="298" font-size="9.5" text-anchor="middle" opacity="0.9">db-18b8ff  sub-4d3c1a  srv-25165e</text>
      <text x="730" y="320" font-size="9.5" text-anchor="middle" opacity="0.85">it knows opaque ids, and nothing</text>
      <text x="730" y="335" font-size="9.5" text-anchor="middle" opacity="0.85">about your names — or which of two</text>
      <text x="730" y="350" font-size="9.5" text-anchor="middle" opacity="0.85">identical subnets is yours</text>
    </g>

    <g fill="none" stroke="currentColor" stroke-width="1.8">
      <path d="M300 148 L 196 246" marker-end="url(#l06-a1)"/>
      <path d="M580 148 L 684 246" marker-end="url(#l06-a1)"/>
    </g>
    <path d="M284 286 L 596 286" fill="none" stroke="#d64545" stroke-width="2" stroke-dasharray="7 4" marker-end="url(#l06-a1r)" marker-start="url(#l06-a1rs)"/>

    <g fill="currentColor">
      <text x="40" y="180" font-size="10.5" font-weight="700" fill="#3553ff">PLAN</text>
      <text x="40" y="196" font-size="9.5" opacity="0.9">diff desired vs actual,</text>
      <text x="40" y="211" font-size="9.5" opacity="0.9">taking identity from state</text>
      <text x="840" y="180" font-size="10.5" font-weight="700" fill="#3553ff" text-anchor="end">APPLY</text>
      <text x="840" y="196" font-size="9.5" opacity="0.9" text-anchor="end">create / update / replace /</text>
      <text x="840" y="211" font-size="9.5" opacity="0.9" text-anchor="end">destroy — then rewrite state</text>
      <text x="440" y="272" font-size="10.5" font-weight="700" text-anchor="middle" fill="#d64545">REFRESH</text>
      <text x="440" y="306" font-size="9.5" text-anchor="middle" opacity="0.9">state is a CACHE of reality.</text>
      <text x="440" y="322" font-size="9.5" text-anchor="middle" opacity="0.9">A console click invalidates it,</text>
      <text x="440" y="338" font-size="9.5" text-anchor="middle" opacity="0.9">and nothing tells you.</text>
      <text x="440" y="358" font-size="10" font-weight="700" text-anchor="middle" fill="#d64545">DRIFT LIVES HERE</text>
    </g>

    <g fill="none" stroke-width="1.8" stroke-linejoin="round">
      <rect x="24" y="386" width="832" height="52" rx="10" fill="#d64545" fill-opacity="0.09" stroke="#d64545"/>
    </g>
    <g fill="currentColor">
      <text x="38" y="406" font-size="10" font-weight="700" fill="#d64545">MEASURED after four console edits:</text>
      <text x="298" y="406" font-size="10">3 of 7 managed resources drifted — 2 attributes changed, 1 vanished.</text>
      <text x="38" y="426" font-size="10">One further object was created by hand: it is in the cloud, in no state file, and so invisible to plan, apply and destroy alike.</text>
    </g>
    <text x="440" y="462" font-size="11" text-anchor="middle" fill="currentColor" opacity="0.9">Lose the state file and the cloud is still running — but nothing you own is managed any more.</text>
  </g>
</svg>
```

The **state file** is the mapping from the names in your code to the identifiers in the cloud: `"database.main" -> "db-18b8ff"`. It also records every attribute as it was at the last apply. And the sentence to keep is this one: **the state file is a cache of reality, and like every cache it can be wrong.**

Once you see it as a cache, the entire folklore of this field decodes. *Someone changed something in the console* — the cache is stale. *We lost the state file* — the cache was the only index and the cloud has no other one. *Two people applied at once* — two writers, one cache, last write wins and the loser's resources are now orphaned. *The state file says the server exists but it doesn't* — the cache has an entry for something that was evicted behind its back.

### Why the tool cannot simply ask the cloud every time

The obvious objection: throw the state file away and query the cloud on every run. It does not work, for three reasons, and the third is fatal.

**Identity.** Your code calls it `subnet.app_a`. The cloud calls it `sub-4d3c1a` and has never heard the string "app_a". Something has to hold that correspondence, and the only two places it can live are a file you keep or a tag you set on the resource — and tags are themselves mutable, deletable, and not supported on every resource type.

**Completeness.** "Everything in the account" is not the same as "everything this configuration manages". Real accounts contain resources owned by other teams, other configurations, and the console. Without a recorded set, the tool cannot tell *your* resources from *theirs*, and a tool that guesses is a tool that offers to delete someone else's network.

**Ambiguity — the fatal one.** Section 5 of the Build It creates the exact case: after a hand-made subnet is added out of band, the cloud contains **two subnets identical in every attribute** — same network, same address range, same availability zone. Only the ids differ. The question "which of these is `subnet.app_a`?" **has no answer in the cloud's own data.** It was answered once, at creation time, and written down in exactly one place. Delete that place and the answer is gone for good.

### The plan: four verbs, and one of them is not like the others

A **plan** is a diff between desired and actual, expressed as operations. There are four.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 510" width="100%" style="max-width:840px" role="img" aria-label="The four verbs a plan can produce. Create makes a new object with a new identifier. Update in place edits a mutable attribute and keeps the same identifier and the data. Replace is triggered by changing an immutable attribute and expands to destroy followed by create, so the identifier changes and the data does not survive. Destroy removes a resource that is in state but no longer in the declaration, and runs in reverse dependency order. Below, the measured replacement cascade: editing one immutable attribute on the graph root replaced six of seven resources including the database, while only the load balancer could absorb the change as an in-place update, and a prevent destroy lifecycle rule refused the whole plan.">
  <defs>
    <marker id="l06-a2" markerWidth="10" markerHeight="10" refX="6.5" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#3553ff"/></marker>
    <marker id="l06-a2r" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L6.5,3 L0,6 Z" fill="#d64545"/></marker>
  </defs>
  <text x="440" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">Four verbs. One of them is how people delete databases.</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <g fill="none" stroke-width="2" stroke-linejoin="round">
      <rect x="24" y="46" width="200" height="164" rx="11" fill="#0fa07f" fill-opacity="0.12" stroke="#0fa07f"/>
      <rect x="232" y="46" width="200" height="164" rx="11" fill="#3553ff" fill-opacity="0.12" stroke="#3553ff"/>
      <rect x="440" y="46" width="200" height="164" rx="11" fill="#d64545" fill-opacity="0.13" stroke="#d64545"/>
      <rect x="648" y="46" width="200" height="164" rx="11" fill="#7f7f7f" fill-opacity="0.10" stroke="currentColor" stroke-opacity="0.55"/>
    </g>

    <g fill="currentColor">
      <text x="40" y="70" font-size="14" font-weight="700" fill="#0fa07f">+ create</text>
      <text x="40" y="92" font-size="9" opacity="0.6">WHEN</text>
      <text x="40" y="107" font-size="9.5">declared, not in state</text>
      <text x="40" y="129" font-size="9" opacity="0.6">IDENTITY</text>
      <text x="40" y="144" font-size="9.5">a new id, unknown</text>
      <text x="40" y="158" font-size="9.5">until the apply ends</text>
      <text x="40" y="194" font-size="9.5" font-weight="700" fill="#0fa07f">data: none to lose</text>

      <text x="248" y="70" font-size="14" font-weight="700" fill="#3553ff">~ update</text>
      <text x="248" y="92" font-size="9" opacity="0.6">WHEN</text>
      <text x="248" y="107" font-size="9.5">a MUTABLE attribute</text>
      <text x="248" y="121" font-size="9.5">changed (tag, size)</text>
      <text x="248" y="143" font-size="9" opacity="0.6">IDENTITY</text>
      <text x="248" y="158" font-size="9.5">same id: srv-25165e</text>
      <text x="248" y="194" font-size="9.5" font-weight="700" fill="#3553ff">data: survives</text>

      <text x="456" y="70" font-size="14" font-weight="700" fill="#d64545">-/+ replace</text>
      <text x="456" y="92" font-size="9" opacity="0.6">WHEN</text>
      <text x="456" y="107" font-size="9.5">an IMMUTABLE attribute</text>
      <text x="456" y="121" font-size="9.5">changed (zone, cidr)</text>
      <text x="456" y="143" font-size="9" opacity="0.6">EXPANDS TO</text>
      <text x="456" y="158" font-size="9.5">1. destroy the old id</text>
      <text x="456" y="172" font-size="9.5">2. create a new one</text>
      <text x="456" y="194" font-size="9.5" font-weight="700" fill="#d64545">data: GONE</text>

      <text x="664" y="70" font-size="14" font-weight="700">- destroy</text>
      <text x="664" y="92" font-size="9" opacity="0.6">WHEN</text>
      <text x="664" y="107" font-size="9.5">in state, no longer</text>
      <text x="664" y="121" font-size="9.5">in the declaration</text>
      <text x="664" y="143" font-size="9" opacity="0.6">ORDER</text>
      <text x="664" y="158" font-size="9.5">reverse dependency</text>
      <text x="664" y="194" font-size="9.5" font-weight="700">data: GONE</text>
    </g>

    <path d="M540 212 L 540 230" fill="none" stroke="#d64545" stroke-width="1.8" marker-end="url(#l06-a2r)"/>
    <g fill="none" stroke-width="1.8" stroke-linejoin="round">
      <rect x="24" y="236" width="824" height="224" rx="11" fill="#d64545" fill-opacity="0.06" stroke="#d64545" stroke-opacity="0.7"/>
    </g>
    <text x="440" y="258" font-size="12" font-weight="700" text-anchor="middle" fill="#d64545">…and a replace propagates through every reference to it</text>
    <text x="440" y="276" font-size="9.5" text-anchor="middle" fill="currentColor" opacity="0.9">MEASURED: one edit to network.core.cidr, the root of the graph. Plan: 6 to add, 1 to change, 6 to destroy.</text>

    <g fill="none" stroke-width="1.8" stroke-linejoin="round">
      <rect x="38" y="340" width="132" height="34" rx="8" fill="#d64545" fill-opacity="0.20" stroke="#d64545"/>
      <rect x="226" y="318" width="132" height="30" rx="8" fill="#d64545" fill-opacity="0.14" stroke="#d64545"/>
      <rect x="226" y="362" width="132" height="30" rx="8" fill="#d64545" fill-opacity="0.14" stroke="#d64545"/>
      <rect x="414" y="298" width="146" height="30" rx="8" fill="#d64545" fill-opacity="0.14" stroke="#d64545"/>
      <rect x="414" y="342" width="146" height="30" rx="8" fill="#d64545" fill-opacity="0.14" stroke="#d64545"/>
      <rect x="414" y="386" width="146" height="30" rx="8" fill="#d64545" fill-opacity="0.30" stroke="#d64545" stroke-width="2.4"/>
      <rect x="620" y="342" width="132" height="30" rx="8" fill="#3553ff" fill-opacity="0.16" stroke="#3553ff"/>
    </g>
    <g fill="none" stroke="#d64545" stroke-width="1.5">
      <path d="M172 351 L 220 337" marker-end="url(#l06-a2r)"/>
      <path d="M172 363 L 220 377" marker-end="url(#l06-a2r)"/>
      <path d="M360 328 L 408 314" marker-end="url(#l06-a2r)"/>
      <path d="M360 336 L 408 356" marker-end="url(#l06-a2r)"/>
      <path d="M360 382 L 408 398" marker-end="url(#l06-a2r)"/>
    </g>
    <g fill="none" stroke="#3553ff" stroke-width="1.5">
      <path d="M562 315 L 614 350" marker-end="url(#l06-a2)"/>
      <path d="M562 357 L 614 357" marker-end="url(#l06-a2)"/>
    </g>

    <g fill="currentColor" text-anchor="middle">
      <text x="104" y="354" font-size="10" font-weight="700">network.core</text>
      <text x="104" y="367" font-size="8.5" opacity="0.9">cidr edited by you</text>
      <text x="292" y="332" font-size="9.5" font-weight="700">subnet.app_a</text>
      <text x="292" y="343" font-size="8" opacity="0.85">network_id immutable</text>
      <text x="292" y="376" font-size="9.5" font-weight="700">subnet.app_b</text>
      <text x="292" y="387" font-size="8" opacity="0.85">network_id immutable</text>
      <text x="487" y="312" font-size="9.5" font-weight="700">server.api_1</text>
      <text x="487" y="323" font-size="8" opacity="0.85">subnet_id immutable</text>
      <text x="487" y="356" font-size="9.5" font-weight="700">server.api_2</text>
      <text x="487" y="367" font-size="8" opacity="0.85">subnet_id immutable</text>
      <text x="487" y="400" font-size="9.5" font-weight="700" fill="#d64545">database.main</text>
      <text x="487" y="411" font-size="8" font-weight="700" fill="#d64545">100 GB, replaced</text>
      <text x="686" y="356" font-size="9.5" font-weight="700" fill="#3553ff">lb.public</text>
      <text x="686" y="367" font-size="8" opacity="0.85">targets are MUTABLE</text>
    </g>

    <g fill="currentColor">
      <text x="38" y="294" font-size="9" font-weight="700" opacity="0.65">EDITED BY A HUMAN</text>
      <text x="226" y="294" font-size="9" font-weight="700" fill="#d64545" opacity="0.9">DRAGGED IN — nobody asked</text>
      <text x="620" y="294" font-size="9" font-weight="700" fill="#3553ff" opacity="0.9">CASCADE STOPS HERE</text>
      <text x="620" y="392" font-size="8.5" opacity="0.9">a mutable attribute can</text>
      <text x="620" y="404" font-size="8.5" opacity="0.9">absorb the new ids:</text>
      <text x="620" y="416" font-size="8.5" opacity="0.9">1 update, not a replace</text>
      <text x="38" y="392" font-size="8.5" opacity="0.9">1 attribute →</text>
      <text x="38" y="405" font-size="9" font-weight="700" fill="#d64545">6 of 7 replaced</text>
      <text x="38" y="418" font-size="8.5" opacity="0.9">5 of them by nobody</text>
      <text x="38" y="446" font-size="9" font-weight="700" fill="#0fa07f">lifecycle { prevent_destroy = true } on database.main refused the WHOLE plan. Nothing was applied.</text>
    </g>
    <text x="440" y="492" font-size="11" text-anchor="middle" fill="currentColor" opacity="0.9">A replace counts once in "to add" and once in "to destroy". 6/1/6 on a 7-resource stack is a full rebuild.</text>
  </g>
</svg>
```

**Create** and **destroy** are self-explanatory. The pair that matters is update versus replace, and the distinction has nothing to do with how big your edit looks and everything to do with **whether the underlying API can change that field on a live object.**

Some attributes are mutable: a tag, an instance size, a load balancer's target list. The provider issues a modify call and the object keeps its identity — and therefore its disk, its data, its IP address, its DNS records, its warm caches. Other attributes are **immutable**: an availability zone, an address range, a machine image on some platforms, the name that forms part of the resource's own identity. The cloud provides no API to change them. So the tool does the only thing left: **destroy the object and create a new one.** That is `-/+`, and it is a data-loss operation dressed up as an edit.

Two more precisions worth having. First, **the plan summary counts a replace twice**: once in "to add" and once in "to destroy". A line reading `Plan: 6 to add, 1 to change, 6 to destroy` against a seven-resource stack is not six new things — it is a full rebuild. Second, `(known after apply)` is not decoration. It means *this value does not exist yet*, and any attribute of yours that consumes it is, by definition, changing. If that attribute happens to be immutable, you have just been recruited into the cascade.

### Replace is the verb to fear, and the cascade is why

A single replace is survivable. What people do not anticipate is that **replacement propagates**. When `network.core` is replaced its id is unknown until apply time; the subnets' `network_id` is therefore changing; `network_id` is immutable for a subnet, so the subnets are replaced too; the servers' and database's `subnet_id` is now changing; that is immutable as well. The measured result in the Build It: **one edited attribute, 6 of 7 resources replaced, and 5 of those 6 were touched by nobody at all.**

The cascade stops only where it meets a **mutable** attribute. The load balancer's target list can absorb two brand-new server ids, so the load balancer is *updated*, not replaced. That is the whole mechanism, in both directions: mutable attributes are firebreaks; immutable ones are fuses.

Four guards, in the order you should reach for them:

- **`prevent_destroy`.** A lifecycle rule on the resource: if any plan proposes to destroy or replace it, the tool errors out and refuses the plan **as a whole** — not partially, not the rest of it. Put it on every database, every object store holding data, every disk. It is one line and it is the difference between an argument and an incident.
- **Read the plan.** The plan output *is* the review artifact. The number to look at is not "how many lines" but the destroy count. Any plan with a non-zero destroy count on a stateful resource requires a second person.
- **`create_before_destroy`.** Flips the order of a replacement: build the new object, repoint references, then remove the old one. The Build It shows the sequence and the modelled cost: **a ~25 s window with zero capacity becomes 0 s**. The price is that both objects exist simultaneously — double capacity for the duration, and an outright failure if any immutable attribute must be globally unique.
- **Policy as code.** A machine reading the plan before a human does, so that "no plan may destroy an `aws_db_instance` without an approved exception" is enforced rather than remembered.

### The dependency graph

You never write down an order. The tool derives one from the references in your configuration, builds a **DAG** (directed acyclic graph — nodes with one-way edges and no loops), and walks it.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 500" width="100%" style="max-width:840px" role="img" aria-label="The dependency graph the tool derives from references in the declaration. Four waves: the network first, then the two subnets, then the two servers and the database, then the load balancer. Everything inside a wave may run concurrently. The critical path runs network to subnet app a to database and takes two hundred and forty five modelled seconds, against three hundred and forty two if the same work ran one resource at a time. Destroy runs the identical graph in reverse, load balancer first and network last. A declaration whose resources reference each other in a circle produces a cycle error and no plan at all.">
  <defs>
    <marker id="l06-a3" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L6.5,3 L0,6 Z" fill="currentColor"/></marker>
    <marker id="l06-a3c" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L6.5,3 L0,6 Z" fill="#e0930f"/></marker>
  </defs>
  <text x="440" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">Nobody wrote this order down — the references imply it</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <g fill="none" stroke="currentColor" stroke-width="1.3" stroke-dasharray="5 4" stroke-opacity="0.4">
      <rect x="30" y="76" width="138" height="212" rx="10"/>
      <rect x="176" y="76" width="138" height="212" rx="10"/>
      <rect x="322" y="76" width="138" height="212" rx="10"/>
      <rect x="482" y="76" width="138" height="212" rx="10"/>
    </g>
    <g fill="currentColor" font-size="9.5" font-weight="700" opacity="0.65" text-anchor="middle">
      <text x="99" y="68">wave 1</text><text x="245" y="68">wave 2</text><text x="391" y="68">wave 3</text><text x="551" y="68">wave 4</text>
    </g>

    <g fill="none" stroke="currentColor" stroke-width="1.5" stroke-opacity="0.75">
      <path d="M160 180 L 182 152" marker-end="url(#l06-a3)"/>
      <path d="M160 194 L 182 222" marker-end="url(#l06-a3)"/>
      <path d="M306 138 L 328 119" marker-end="url(#l06-a3)"/>
      <path d="M306 222 L 328 184" marker-end="url(#l06-a3)"/>
      <path d="M452 118 L 488 138" marker-end="url(#l06-a3)"/>
      <path d="M452 172 L 488 152" marker-end="url(#l06-a3)"/>
    </g>
    <path d="M306 156 L 328 230" fill="none" stroke="#e0930f" stroke-width="2" marker-end="url(#l06-a3c)"/>
    <path d="M160 180 L 182 152" fill="none" stroke="#e0930f" stroke-width="2" marker-end="url(#l06-a3c)"/>

    <g fill="none" stroke-width="2" stroke-linejoin="round">
      <rect x="40" y="170" width="118" height="34" rx="8" fill="#7c5cff" fill-opacity="0.14" stroke="#e0930f" stroke-width="2.6"/>
      <rect x="186" y="128" width="118" height="34" rx="8" fill="#7c5cff" fill-opacity="0.14" stroke="#e0930f" stroke-width="2.6"/>
      <rect x="186" y="212" width="118" height="34" rx="8" fill="#7c5cff" fill-opacity="0.14" stroke="#7c5cff"/>
      <rect x="332" y="96" width="118" height="34" rx="8" fill="#7c5cff" fill-opacity="0.14" stroke="#7c5cff"/>
      <rect x="332" y="160" width="118" height="34" rx="8" fill="#7c5cff" fill-opacity="0.14" stroke="#7c5cff"/>
      <rect x="332" y="224" width="118" height="34" rx="8" fill="#7c5cff" fill-opacity="0.14" stroke="#e0930f" stroke-width="2.6"/>
      <rect x="492" y="128" width="118" height="34" rx="8" fill="#7c5cff" fill-opacity="0.14" stroke="#7c5cff"/>
    </g>
    <g fill="currentColor" text-anchor="middle">
      <text x="99" y="186" font-size="9.5" font-weight="700">network.core</text>
      <text x="99" y="198" font-size="8" opacity="0.85">3 s · t=0 → 3</text>
      <text x="245" y="144" font-size="9.5" font-weight="700">subnet.app_a</text>
      <text x="245" y="156" font-size="8" opacity="0.85">2 s · t=3 → 5</text>
      <text x="245" y="228" font-size="9.5" font-weight="700">subnet.app_b</text>
      <text x="245" y="240" font-size="8" opacity="0.85">2 s · t=3 → 5</text>
      <text x="391" y="112" font-size="9.5" font-weight="700">server.api_1</text>
      <text x="391" y="124" font-size="8" opacity="0.85">25 s · t=5 → 30</text>
      <text x="391" y="176" font-size="9.5" font-weight="700">server.api_2</text>
      <text x="391" y="188" font-size="8" opacity="0.85">25 s · t=5 → 30</text>
      <text x="391" y="240" font-size="9.5" font-weight="700">database.main</text>
      <text x="391" y="252" font-size="8" opacity="0.85">240 s · t=5 → 245</text>
      <text x="551" y="144" font-size="9.5" font-weight="700">lb.public</text>
      <text x="551" y="156" font-size="8" opacity="0.85">45 s · t=30 → 75</text>
    </g>

    <g fill="none" stroke-width="1.8" stroke-linejoin="round">
      <rect x="640" y="76" width="216" height="212" rx="10" fill="#7f7f7f" fill-opacity="0.09" stroke="currentColor" stroke-opacity="0.5"/>
    </g>
    <g fill="currentColor">
      <text x="748" y="98" font-size="11" font-weight="700" text-anchor="middle">DESTROY — same graph,</text>
      <text x="748" y="112" font-size="11" font-weight="700" text-anchor="middle">walked backwards</text>
      <text x="656" y="136" font-size="9.5">1 · lb.public</text>
      <text x="656" y="154" font-size="9.5">2 · database.main</text>
      <text x="678" y="168" font-size="9.5">server.api_1</text>
      <text x="678" y="182" font-size="9.5">server.api_2</text>
      <text x="656" y="200" font-size="9.5">3 · subnet.app_a</text>
      <text x="678" y="214" font-size="9.5">subnet.app_b</text>
      <text x="656" y="232" font-size="9.5">4 · network.core</text>
      <text x="656" y="256" font-size="8.5" opacity="0.9">you cannot delete a subnet</text>
      <text x="656" y="268" font-size="8.5" opacity="0.9">that still holds a server —</text>
      <text x="656" y="280" font-size="8.5" opacity="0.9">the graph already knew that</text>
    </g>

    <g fill="none" stroke-width="1.8" stroke-linejoin="round">
      <rect x="446" y="308" width="410" height="140" rx="10" fill="#0fa07f" fill-opacity="0.10" stroke="#0fa07f"/>
      <rect x="24" y="308" width="404" height="140" rx="10" fill="#d64545" fill-opacity="0.09" stroke="#d64545"/>
    </g>
    <g fill="currentColor">
      <text x="462" y="330" font-size="11" font-weight="700" fill="#0fa07f">WHAT THE GRAPH BUYS (durations MODELLED)</text>
      <text x="462" y="352" font-size="9.5">one resource at a time</text>
      <text x="700" y="352" font-size="10" font-weight="700">342 s</text>
      <text x="462" y="370" font-size="9.5">following the DAG</text>
      <text x="700" y="370" font-size="10" font-weight="700" fill="#0fa07f">245 s</text>
      <text x="762" y="370" font-size="9.5" fill="#0fa07f" font-weight="700">1.40x</text>
      <text x="462" y="394" font-size="9.5" font-weight="700" fill="#e0930f">critical path (amber):</text>
      <text x="462" y="408" font-size="9.5">network.core → subnet.app_a → database.main</text>
      <text x="462" y="428" font-size="9" opacity="0.9">Nothing else is on it: lb.public is finished at t=75 s and</text>
      <text x="462" y="440" font-size="9" opacity="0.9">the run still takes 245 s. Only the database shortens it.</text>

      <text x="40" y="330" font-size="11" font-weight="700" fill="#d64545">A CYCLE IS AN ERROR, NOT A WARNING</text>
      <text x="40" y="352" font-size="9">resource "server" "a" { subnet_id = server.b.id }</text>
      <text x="40" y="366" font-size="9">resource "server" "b" { subnet_id = server.a.id }</text>
      <text x="40" y="390" font-size="9.5" font-weight="700" fill="#d64545">Error: Cycle: server.a -&gt; server.b -&gt; server.a</text>
      <text x="40" y="412" font-size="9" opacity="0.9">There is no first node, so there is no correct order.</text>
      <text x="40" y="426" font-size="9" opacity="0.9">The tool produces no plan at all rather than guess —</text>
      <text x="40" y="440" font-size="9" opacity="0.9">and refusing to start is the safe failure here.</text>
    </g>
    <text x="440" y="480" font-size="11" text-anchor="middle" fill="currentColor" opacity="0.9">Every edge came from one resource referencing another. Delete the reference and you delete the ordering guarantee.</text>
  </g>
</svg>
```

Three consequences follow from having a graph rather than a script.

**Parallelism is free.** Anything with no path between it and another node can run at the same time. With modelled provisioning times — 3 s for a network, 25 s for a server, 240 s for a database — running the seven resources one at a time takes **342 s**; following the graph takes **245 s**, a **1.40× speed-up** that required no configuration. The limit is the **critical path**: `network.core → subnet.app_a → database.main`. Nothing else is on it. Making the servers faster changes the total by zero.

**Destruction runs the graph backwards.** You cannot delete a subnet that still contains a server, and the tool does not need to be told: reverse topological order handles it.

**Cycles are an error, not a warning.** If A references B and B references A, there is no first node and therefore no correct order. The tool prints `Error: Cycle: server.a -> server.b -> server.a` and produces **no plan at all**. That is the right failure: a half-order applied to real infrastructure is worse than no order.

There is a subtlety here that bites people. The graph only knows about dependencies you **expressed as references**. If you hard-code `subnet_id = "sub-4d3c1a"` instead of referencing the resource, the edge disappears, the ordering guarantee disappears with it, and the tool will cheerfully try to create the server before the subnet exists. Reference resources; never paste ids.

### Drift, and the honest choice it forces

**Drift** is divergence between the actual infrastructure and your declaration. It arrives four ways, and only the first is anyone's fault:

1. **A human in the console.** Almost always during an incident, almost always for a good reason, almost never written down.
2. **Another tool.** An autoscaler changing a capacity, a cluster controller adding a tag, a backup system creating a snapshot resource.
3. **The provider itself.** A default changed on the vendor's side; a new required field appeared; a value you never set is now populated.
4. **A failed apply.** The run died halfway. Some resources moved, some did not, and the state file may or may not have caught up.

Detection is a refresh: read every recorded id and compare with what was written down. What to do next is a genuine judgement, and pretending otherwise is how tools get distrusted:

- **Re-assert the declaration.** The next apply corrects the drift and the code stays the single source of truth. This is the default and usually right — but understand that re-asserting can mean *replacing*, and in the Build It it drags a healthy server down with it.
- **Adopt reality.** Someone changed a production setting at 02:40 and they were right. Update the declaration to match, in a pull request, with the reason in the commit message. The change is now reviewed after the fact instead of never.

What you must not do is leave it. Undetected drift compounds silently until the day someone runs an apply for an unrelated reason and inherits every accumulated correction at once — which is precisely when a routine tag change turns into a plan with six replacements in it.

### Mutable versus immutable infrastructure

Two philosophies, and the distinction runs through the rest of this phase.

**Mutable** (or "pets"): a server is created once and changed in place forever — patches, config edits, package upgrades. It accumulates history. Two servers built from the same recipe six months apart end up different in ways nobody can enumerate, which is **configuration drift** at the machine level, and it is the reason "works on that box, not this one" survives into production.

**Immutable** ("cattle"): a server is never modified. To change anything you build a new image, launch new instances from it, shift traffic, and delete the old ones. The running fleet is always exactly the artifact you tested, because nothing has happened to it since. This is the direction of travel and it is what containers made cheap — Lessons 2 and 3 built exactly this artifact.

It is not free. Immutability means every change is a replacement, so every change needs a way to move traffic without dropping it (Lessons 9, 11 and 12), stateful things need somewhere durable to live because the compute is disposable, and your build-and-ship path must be fast enough that a one-line fix does not take forty minutes. The trade you are making is **more machinery, less mystery** — and the mystery is what actually costs you at 03:00.

### Working as a team: the parts that fail with more than one person

Everything so far assumes a single operator. Adding people breaks four things:

- **The state file must be shared and remote.** On a laptop it is invisible to everyone else and one disk failure from gone. It belongs in a remote backend — object storage, a database, a managed service — with versioning on so you can roll back a corrupted write.
- **State locking is mandatory.** Two applies at once means two processes reading the same state, each writing back what it thinks the world looks like. The second write erases the first's records and those resources are now orphaned: alive, costing money, referenced by nothing. A lock makes the second apply wait. **A remote backend without locking is more dangerous than a local state file**, because it invites the concurrency it cannot survive.
- **Modules are how you stop copy-pasting.** A module is a parameterised group of resources — the composition unit. Without them, three environments means three copies of the same 400 lines drifting apart at three different rates.
- **Environments must be separated at the state boundary.** One state file per environment, at minimum. If staging and production share a state file, a plan for one can propose changes to the other, and the blast radius of every mistake is both.

And a fifth, which is the most commonly missed thing in this entire subject: **secrets end up in the state file.** The tool records every attribute of every resource as applied, and that includes the database password you passed in, the generated private key, the token the provider returned. Marking a variable `sensitive` hides it from *console output* — it does not remove it from state. The Build It prints its own state file to make this concrete. Treat the state file as a credential store: encrypt it at rest, restrict who can read it, never commit it, and see [Secrets Management & Rotation](../../07-auth-and-security/13-secrets-management-and-rotation/) for what to do instead.

### Provisioning is not configuration management

Beginners conflate two tool families that solve adjacent problems.

**Provisioning** tools — Terraform, OpenTofu, Pulumi, CloudFormation, CDK — create, change and destroy *resources*: networks, machines, databases, DNS records, permissions. They talk to cloud APIs from outside. Their model is desired state plus a plan, which is everything this lesson describes.

**Configuration management** tools — Ansible, Chef, Puppet, Salt — converge the *inside* of a machine: install packages, write config files, start services, apply patches. They log in (or run an agent) and make the operating system match a description. They are also declarative, and they are also idempotent, but the thing they own is one machine's contents, not the fleet's shape.

The usual pairing is provisioning to create the machines and configuration management to fill them. The immutable model shortens that chain: bake the contents into an image at build time, and the running machine needs no convergence at all because nothing is ever changed on it. That is why configuration management matters less in a container-native stack than it did a decade ago — but it never disappears, because something still has to build the image, and images are how you get [reproducible builds](../03-images-layers-and-builds/) in the first place.

## Build It

[`code/iac_engine.py`](code/iac_engine.py) is a miniature IaC engine: a declaration, a state file, a planner with a fixpoint loop for replacement propagation, a DAG walker, lifecycle guards and a drift detector — against a fake cloud that is a Python dictionary. Standard library only, seeded, and it finishes in well under a second. **No network calls and no credentials**: creating real infrastructure is exactly the kind of thing the sandbox cannot do, so the provider is modelled, and every provisioning duration in section 3 is a plausible number rather than a measured one. Everything else is real computation on real data structures.

**The schema is where update-versus-replace lives.** The entire distinction is one table:

```python
IMMUTABLE: dict[str, set[str]] = {
    "network": {"cidr", "region"},
    "subnet": {"network_id", "cidr", "zone"},
    "server": {"subnet_id", "zone", "image"},
    "database": {"subnet_id", "engine"},
    "lb": set(),  # everything on a load balancer can be changed in place
}
```

A real provider carries this knowledge for several hundred resource types, learned from the cloud's API documentation, and it is the reason a provider is not a thin HTTP wrapper.

**The planner is a fixpoint loop**, and that loop is the cascade. You cannot decide whether a resource is replaced until you know whether its dependencies are, so you iterate until the answer stops changing:

```python
    for _ in range(12):
        changes = {}
        for res in decl:
            cur = actual.get(res.addr)
            if cur is None:
                ...                                     # create: gone, or never existed
            want = resolve(res, ids, unknown)           # unknown deps -> (known after apply)
            diffs = {k: (cur.get(k), want[k]) for k in want if cur.get(k) != want[k]}
            forces = sorted(k for k in diffs if k in IMMUTABLE[res.type])
            action = REPLACE if forces else (UPDATE if diffs else NOOP)
            changes[res.addr] = Change(res.addr, action, diffs, forces)
        fresh = {a for a, c in changes.items() if c.action in (CREATE, REPLACE)}
        if fresh == unknown:
            break                                        # the answer stopped changing
        unknown = fresh
```

Read `resolve` alongside it: a reference to a resource in the `unknown` set resolves to the string `(known after apply)`. That is not cosmetic — it is a *different value* from the id currently recorded, so it registers as a diff, and if the attribute is immutable it registers as a forcing one. The cascade is not special-cased anywhere. It falls out of "an unknown value is a changed value."

**Apply respects the graph in both directions**, and the reversal for deletes is one line:

```python
    for c in reversed(changes):
        if c.action == DELETE:
            cloud.delete(state.resources[c.addr]["id"])   # destroy in REVERSE order
            del state.resources[c.addr]
    for c in changes:
        ...
        if c.action == REPLACE:
            cloud.delete(state.resources[c.addr]["id"])   # destroy, THEN create
            state.resources.pop(c.addr)
```

**The guard runs at plan time, not apply time**, and it rejects the whole plan:

```python
def check_guards(changes: list[Change], decl: list[Res]) -> None:
    guarded = {r.addr for r in decl if r.prevent_destroy}
    for c in changes:
        if c.action in (REPLACE, DELETE) and c.addr in guarded:
            raise GuardError(...)
```

All-or-nothing is deliberate and matches the real tools. A guard that let the other five replacements through and skipped only the database would leave you with servers in a network that no longer exists.

Run it:

```bash
docker compose exec -T app python \
  phases/10-infrastructure-and-deployment/06-infrastructure-as-code/code/iac_engine.py
```

```console
== 1 · DECLARE, PLAN, APPLY ==
  the declaration: 7 resources, one network, two subnets, two servers,
  one database, one load balancer. Nothing exists yet.

    + create  network.core
    + create  subnet.app_a
    + create  subnet.app_b
    + create  database.main
    + create  server.api_1
    + create  server.api_2
    + create  lb.public
  Plan: 7 to add, 0 to change, 0 to destroy.

  applied. cloud API calls: create=7 update=0 delete=0
  the state file - the mapping the tool cannot rebuild without:
    {
      "version": 4,  "serial": 1,  "lineage": "7f0c1e2a-3b4d-4e5f-8a91-0d2c4b6e8f00",
      "resources": {
        "database.main"    -> "db-18b8ff"
        "lb.public"        -> "lb-bb3b93"
        "network.core"     -> "net-a5cd68"
        "server.api_1"     -> "srv-25165e"
        "server.api_2"     -> "srv-3031d0"
        "subnet.app_a"     -> "sub-4d3c1a"
        "subnet.app_b"     -> "sub-ca264e"
      }
    }

  each entry also records every attribute as applied. One entry in full:
    {
      "database.main": {
        "id": "db-18b8ff",
        "attributes": {
          "subnet_id": "sub-4d3c1a",
          "engine": "postgres-16",
          "storage_gb": 100,
          "password": "***",
          "backup_window": "03:00-04:00"
        }
      }
    }
  the password is masked above for the page. On disk that field is the
  literal string 'hunter2-prod'. State files hold every attribute of every
  resource, in plaintext, including the ones marked sensitive in the config.

== 2 · IDEMPOTENCE, PROVED: THE SECOND PLAN IS EMPTY ==
  No changes. Your infrastructure matches the configuration.
  Plan: 0 to add, 0 to change, 0 to destroy.
  the re-plan made 7 read calls and 0 create/update/delete calls.
  a script would have run 7 create calls again. A declaration re-evaluates
  to the same 0/0/0 for as long as reality matches it - which is what makes
  it safe to run on every merge, in CI, unattended.

== 3 · THE DEPENDENCY GRAPH (modelled durations) ==
  edges - each one is a reference in the declaration, nothing declared by hand:
    database.main    depends on  subnet.app_a
    lb.public        depends on  server.api_1, server.api_2
    network.core     (root)
    server.api_1     depends on  subnet.app_a
    server.api_2     depends on  subnet.app_b
    subnet.app_a     depends on  network.core
    subnet.app_b     depends on  network.core

  topological order, grouped into waves that may run concurrently:
    wave 1: network.core
    wave 2: subnet.app_a, subnet.app_b
    wave 3: database.main, server.api_1, server.api_2
    wave 4: lb.public

  earliest-start schedule (provisioning times are MODELLED, not measured):
    t=   0.0s ->    3.0s  network.core     runs alongside: -
    t=   3.0s ->    5.0s  subnet.app_a     runs alongside: subnet.app_b
    t=   3.0s ->    5.0s  subnet.app_b     runs alongside: subnet.app_a
    t=   5.0s ->  245.0s  database.main    runs alongside: lb.public, server.api_1, ...
    t=   5.0s ->   30.0s  server.api_1     runs alongside: database.main, server.api_2
    t=   5.0s ->   30.0s  server.api_2     runs alongside: database.main, server.api_1
    t=  30.0s ->   75.0s  lb.public        runs alongside: database.main

  one at a time: 342s.  Following the DAG: 245s (1.40x faster).
  the critical path is network.core -> subnet.app_a -> database.main
  (245s); every other resource finishes with time to spare.
  destroy runs the same order REVERSED, wave by wave:
    step 1: lb.public
    step 2: database.main, server.api_1, server.api_2
    step 3: subnet.app_a, subnet.app_b
    step 4: network.core

  cycle detection - a declaration where two servers reference each other:
    Error: Cycle: server.a -> server.b -> server.a
    a DAG has no answer to 'which of these do I create first?', so the
    tool refuses to plan at all rather than guess.

== 4 · UPDATE vs REPLACE - THE VERB THAT DELETES DATABASES ==
  4a · change a MUTABLE attribute (a tag, an instance size):
        ~ update  server.api_1
              size: "c6i.large" -> "c6i.xlarge"
              tags: "prod" -> "prod,team-checkout"
      Plan: 0 to add, 1 to change, 0 to destroy.
      id before srv-25165e -> after srv-25165e (unchanged: the machine was edited, not rebuilt)

  4b · change an IMMUTABLE attribute on ONE leaf server (its zone):
      -/+ replace server.api_2
              zone: "eu-west-1b" -> "eu-west-1c"  # forces replacement
        ~ update  lb.public
              targets: ["srv-25165e", "srv-3031d0"] -> ["srv-25165e", (known after apply)]
      Plan: 1 to add, 1 to change, 1 to destroy.
      1 attribute changed -> 1 resource replaced and 1 dependent dragged in: lb.public
      the load balancer is UPDATED, not replaced, because its target list
      is a mutable attribute. That is the cascade stopping.

      the apply ORDER for a replace, default (destroy first):
        1. destroy server.api_2 (srv-3031d0)      <- the old object is gone NOW
        2. create  server.api_2                   <- ~25s of zero capacity here (modelled)
        3. update  lb.public                      <- references repointed at the new id
      with lifecycle { create_before_destroy = true }:
        1. create  server.api_2                   <- new object, new id
        2. update  lb.public                      <- references repointed at the new id
        3. destroy server.api_2 (srv-3031d0)      <- only after the replacement is serving
      the gap where the zone has no server: 25s -> 0s. The cost is that
      two objects exist at once - double capacity, and a name collision if any
      immutable attribute has to be globally unique.
      Now watch the cascade not stop.

  4c · change ONE immutable attribute on the ROOT of the graph (the CIDR):
      -/+ replace network.core
              cidr: "10.0.0.0/16" -> "10.1.0.0/16"  # forces replacement
      -/+ replace subnet.app_a
              network_id: "net-a5cd68" -> (known after apply)  # forces replacement
      -/+ replace subnet.app_b
              network_id: "net-a5cd68" -> (known after apply)  # forces replacement
      -/+ replace database.main
              subnet_id: "sub-4d3c1a" -> (known after apply)  # forces replacement
      -/+ replace server.api_1
              subnet_id: "sub-4d3c1a" -> (known after apply)  # forces replacement
      -/+ replace server.api_2
              subnet_id: "sub-ca264e" -> (known after apply)  # forces replacement
        ~ update  lb.public
              targets: ["srv-25165e", "srv-3031d0"] -> [(known after apply), (known after apply)]
      Plan: 6 to add, 1 to change, 6 to destroy.

      ONE edited attribute. 6 of 7 resources are REPLACED, 1 updated.
      replaced: network.core, subnet.app_a, subnet.app_b, database.main, server.api_1, server.api_2
      only network.core was edited. The other 5 were dragged in transitively:
      an immutable attribute of each one is a reference to something being
      replaced, so its value is (known after apply) - a change, and a forcing one.
      database.main is in that list. Its data is in that list.

      the guard: database.main declares lifecycle { prevent_destroy = true }
      Error: Instance cannot be destroyed: resource database.main has
      lifecycle.prevent_destroy set, but the plan calls for it to be replaced.
      NOTHING was applied. The plan is refused as a whole, not partially.
      Without that one line, `apply` would have deleted 100 GB of data and
      created an empty database with a new id, and the plan output would
      have said so - on line 4 of 60, under a heading nobody read.
      cloud state untouched: 7 objects, database id still db-18b8ff

== 5 · DRIFT: THE STATE FILE IS A CACHE OF REALITY, AND CACHES GO STALE ==
  four things happen in the console at 02:40 during an incident:
    1. someone re-tags server.api_1 to find it in the billing view
    2. someone widens the database backup window to run a manual dump
    3. someone deletes subnet.app_b, believing it is unused
    4. someone creates a subnet by hand to test a fix, and leaves it

  drift report (what the cloud says, versus what the state file recorded):
    ~ database.main    backup_window: recorded "03:00-04:00" -> actual "12:00-13:00"
    ~ server.api_1     tags: recorded "prod" -> actual "DEBUG-do-not-delete"
    - subnet.app_b     recorded id sub-ca264e no longer exists in the cloud
    3 of 7 managed resources have drifted (2 attributes changed, 1 vanished).

  the next plan, after a refresh:
      + create  subnet.app_b   # in state, but gone from the cloud
      ~ update  database.main
            backup_window: "12:00-13:00" -> "03:00-04:00"
      ~ update  server.api_1
            tags: "DEBUG-do-not-delete" -> "prod"
    -/+ replace server.api_2
            subnet_id: "sub-ca264e" -> (known after apply)  # forces replacement
      ~ update  lb.public
            targets: ["srv-25165e", "srv-3031d0"] -> ["srv-25165e", (known after apply)]
    Plan: 2 to add, 3 to change, 1 to destroy.
    corrected in place: database.main, server.api_1, lb.public
    recreated after the out-of-band delete: subnet.app_b
    collateral - not touched by anyone, replaced anyway: server.api_2
    server.api_2 was healthy and unedited. It is being destroyed because the
    subnet it sits in will come back with a NEW id, and subnet_id is immutable.

  the second failure mode - a resource the state file has never heard of:
    the cloud holds 7 objects. State holds 7 mappings, one of which (subnet.app_b)
    points at an id that no longer exists.
    1 object is in the cloud and in NO state file: sub-1db208
    cloud.list('subnet') returns 2: sub-1db208, sub-4d3c1a
    sub-1db208 and sub-4d3c1a are identical in every attribute: True
    (network_id, cidr and zone all match; only the id differs)
    THIS is why the tool cannot just ask the cloud every time. 'Which of these
    subnets is subnet.app_a?' has no answer in the cloud's own data. The state
    file is the only place the answer was ever written down.
    the plan above is silent about sub-1db208: unmanaged means invisible, not
    deleted. `terraform import` writes the mapping in, and only then can the
    tool see it, plan against it, or destroy it.
```

Read what each section establishes.

**Section 1** is the whole loop in twenty lines of output, and the part worth staring at is the state file. Seven mappings, `"subnet.app_a" -> "sub-4d3c1a"`. That is the artifact section 5 will prove is irreplaceable. Note also `"serial": 1` — a monotonically increasing write counter, and the mechanism by which a backend detects that someone else has written since you read. Then the entry printed in full: `storage_gb`, `backup_window`, and **`password`**, which on disk is the literal string `hunter2-prod`. Nothing was misconfigured to produce that. Recording every attribute is how the tool knows what changed, so a password passed to a resource is a password in the state file, permanently, in every historical version the backend has kept.

**Section 2 is the argument for the entire paradigm, and it is one line long: `Plan: 0 to add, 0 to change, 0 to destroy.`** The second run made **7 read calls and 0 write calls**. A shell script asked to do the same thing would have made seven create calls and produced seven duplicate resources or seven errors. This is why a declarative tool can run on every merge, unattended, and why "did anyone apply this?" stops being a question worth asking — the answer is visible in an empty plan.

**Section 3** shows an ordering nobody wrote. Seven resources, seven edges, all of them derived from references, arranged into four waves. With modelled provisioning times the serial run is **342 s** and the graph-ordered run is **245 s — 1.40× faster**, and the entire remaining cost is the critical path `network.core → subnet.app_a → database.main`. `lb.public` finishes at t=75 s and then the run just waits 170 more seconds for the database. That is the useful lesson about optimising an apply: only the critical path counts. Then the destroy order, reversed wave by wave, and the cycle: `Error: Cycle: server.a -> server.b -> server.a`, with **no plan produced at all**.

**Section 4 is the centrepiece.** Three edits, escalating.

In **4a** a tag and an instance size change. The plan is `0 to add, 1 to change, 0 to destroy` and the id is `srv-25165e` before and `srv-25165e` after. The machine was edited. This is the safe case, and it is what most people assume every change looks like.

In **4b** one immutable attribute changes on one leaf resource — a server's availability zone. The plan becomes `1 to add, 1 to change, 1 to destroy`, and **one dependent is dragged in**: the load balancer, whose target list contains an id that is about to become `(known after apply)`. Crucially the load balancer is only *updated*, because `targets` is mutable. The apply order is then shown twice: destroy-then-create leaves a **~25 s window (modelled) with zero servers in that zone**, and `create_before_destroy` reduces that gap to **0 s** at the cost of running two objects at once.

In **4c** the same class of edit is applied to the *root* of the graph — the network's address range — and the result is the number to remember. **`Plan: 6 to add, 1 to change, 6 to destroy`: 6 of 7 resources replaced, and 5 of those 6 were edited by nobody.** The mechanism is spelled out in the diff lines: each dragged-in resource shows an immutable attribute going from a real id to `(known after apply)`. `database.main` is in that list, and so is its data. Then the guard fires — `Error: Instance cannot be destroyed` — and **nothing is applied at all**: the cloud still holds 7 objects and the database is still `db-18b8ff`. One line of configuration is the difference between an argument in a pull request and a restore from backup.

**Section 5** does the two failure modes people meet in year two. Four console edits produce a drift report: **3 of 7 managed resources drifted — 2 attributes changed, 1 vanished.** The next plan corrects the two changed attributes in place and proposes to recreate the deleted subnet, which is exactly what you want. And then the sting: **`server.api_2` — untouched, healthy, serving traffic — is proposed for replacement**, because the subnet it lives in is coming back with a new id and `subnet_id` is immutable. Somebody else's console click at 02:40 has queued up the destruction of a server they never looked at. That is drift's real cost: not the drifted attribute, but what re-asserting it drags along.

The last block is the identity argument made concrete. The cloud now holds **two subnets identical in every attribute** — `sub-1db208` and `sub-4d3c1a`, same network, same range, same zone, different ids. The hand-made one is in no state file, and so **the plan is silent about it**. It is not going to be deleted, not going to be corrected, not going to be reported. It will simply exist, and be billed, and confuse the next person. `import` is the only way to fold it in — and it works by writing the one thing that was never written down: the mapping.

## Use It

The tool most teams meet first is **Terraform**, or its fork **OpenTofu** (created under the Linux Foundation after HashiCorp moved Terraform to the Business Source Licence in 2023; the configuration language and workflow are compatible). What follows is an overview — enough to read a real plan and know what it is doing on your behalf, deliberately not a full course.

### A configuration, a variable and an output

```hcl
terraform {
  required_version = ">= 1.6"
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 5.0" }
  }
}

variable "instance_count" {
  type        = number
  default     = 2
  description = "How many API servers to run."

  validation {
    condition     = var.instance_count >= 2
    error_message = "Production must run at least two instances."
  }
}

resource "aws_instance" "api" {
  count                  = var.instance_count
  ami                    = data.aws_ami.api.id
  instance_type          = "c6i.large"
  subnet_id              = aws_subnet.app_a.id     # <- this reference IS the graph edge
  vpc_security_group_ids = [aws_security_group.api.id]

  tags = { Name = "api-${count.index}", Environment = var.environment }

  lifecycle {
    create_before_destroy = true
    ignore_changes        = [ami]   # the deploy pipeline rolls images, not terraform
  }
}

output "api_private_ips" {
  value = aws_instance.api[*].private_ip
}
```

`subnet_id = aws_subnet.app_a.id` is the line that matters. It is simultaneously the value, the dependency edge, and the reason a replacement of the subnet will propagate here. Write ids as references, never as literals — a pasted `"subnet-0a1b2c"` deletes the edge and the ordering guarantee with it.

`ignore_changes` deserves a note because it is both a useful escape hatch and a way to lie to yourself. It tells the tool to stop caring about an attribute, which is correct when another system legitimately owns it (an autoscaler owning `desired_capacity`, a deploy pipeline owning the image). Used to silence a drift you simply do not want to think about, it converts drift from something you can detect into something you have chosen not to see.

### The workflow, and what a real plan looks like

```bash
terraform init                     # download providers, configure the backend
terraform fmt -check && terraform validate
terraform plan -out=tfplan         # ALWAYS write the plan to a file
terraform apply tfplan             # apply exactly that plan, not a fresh one
terraform destroy                  # reverse topological order, for real
```

Planning to a file and applying *that file* is not a stylistic nicety. `terraform apply` without an argument computes a **new** plan at apply time, which may differ from the one your colleague reviewed ten minutes ago. The reviewed artifact and the executed artifact should be the same bytes.

```console
$ terraform plan -out=tfplan
aws_vpc.core: Refreshing state... [id=vpc-0f3a1c9d2b4e5f678]
aws_subnet.app_a: Refreshing state... [id=subnet-0a1b2c3d4e5f67890]
aws_db_instance.main: Refreshing state... [id=prod-main]

Terraform used the selected providers to generate the following execution plan.
Resource actions are indicated with the following symbols:
  + create
  ~ update in-place
-/+ destroy and then create replacement

Terraform will perform the following actions:

  # aws_db_instance.main must be replaced
-/+ resource "aws_db_instance" "main" {
      ~ availability_zone    = "eu-west-1a" -> "eu-west-1b" # forces replacement
      ~ id                   = "prod-main" -> (known after apply)
      ~ endpoint             = "prod-main.abc123.eu-west-1.rds.amazonaws.com" -> (known after apply)
        allocated_storage    = 100
        # (23 unchanged attributes hidden)
    }

Plan: 1 to add, 0 to change, 1 to destroy.
```

Everything in that output is something you have now built by hand: the refresh, the symbols, `forces replacement`, `(known after apply)`, and the summary line where a replace is counted in both columns. And the guard, in its real wording:

```console
$ terraform apply tfplan
Error: Instance cannot be destroyed

  on rds.tf line 12, in resource "aws_db_instance" "main":
  12: resource "aws_db_instance" "main" {

Resource aws_db_instance.main has lifecycle.prevent_destroy set, but the plan
calls for this resource to be destroyed.
```

### Remote state and locking

```hcl
terraform {
  backend "s3" {
    bucket       = "acme-tfstate-prod"
    key          = "platform/network/terraform.tfstate"
    region       = "eu-west-1"
    encrypt      = true                    # at rest — state is a credential store
    use_lockfile = true                    # S3-native locking (older setups used DynamoDB)
  }
}
```

Turn on **object versioning** on that bucket. A corrupted or truncated state write is recoverable if you can fetch the previous version and unrecoverable if you cannot. Restrict read access the same way you would restrict access to a password vault, because that is what it is.

Locking is the part people skip because it is invisible until the day it isn't. Without it, two applies that start within a few seconds of each other both read serial 41, both do their work, and both write serial 42. The second write wins. **The resources created by the first apply are now real, running, billed, and referenced by no state file anywhere** — orphans that no plan will ever mention and no destroy will ever clean up. The lock turns that into a `Error: Error acquiring the state lock` and a thirty-second wait.

### Modules and environment separation

```hcl
module "api_service" {
  source = "../../modules/service"

  name           = "api"
  environment    = "prod"
  instance_count = 6
  instance_type  = "c6i.2xlarge"
  subnet_ids     = module.network.private_subnet_ids
}
```

For environments there are two options and one recommendation.

**Workspaces** keep one configuration and one backend with multiple named states. They are convenient and they have a specific failure mode: everything diverges through `terraform.workspace` conditionals scattered through the configuration, so the difference between staging and production is no longer readable in one place, and a mis-set workspace points production credentials at a plan you meant for staging.

**Separate directories** — `envs/prod/`, `envs/staging/`, each a small root module calling shared modules with different variables — give you a separate backend, separate credentials, separate state, and a diff between two files that tells you exactly how the environments differ. **Prefer directories.** Use workspaces for short-lived identical copies (a per-branch review environment), which is what they are good at.

### Refactoring without destroying: `moved` and `import`

Scene two of The Problem is preventable, and this is how. Renaming a resource *block* changes its address, and the tool reads that as "the old one is gone, a new one is wanted" — destroy plus create. A `moved` block tells it the truth:

```hcl
moved {
  from = aws_instance.api
  to   = aws_instance.api_server
}
```

That rewrites the mapping in state and produces a plan with **no changes at all**. The inverse operation, adopting something that already exists — like the hand-made subnet in section 5:

```hcl
import {
  to = aws_subnet.app_a
  id = "subnet-0a1b2c3d4e5f67890"
}
```

`terraform plan` then shows what it *would* import and what it would immediately change to match your configuration, which is the step to read carefully: if your declaration does not exactly match the imported reality, the first apply after an import is a modification, and it is occasionally a replacement.

### Policy as code, and drift detection on a schedule

A plan is machine-readable, which means a machine can review it before a human does:

```bash
terraform plan -out=tfplan
terraform show -json tfplan > plan.json
conftest test --policy policy/ plan.json      # Open Policy Agent / Rego
```

```rego
package terraform.guardrails

deny contains msg if {
    some change in input.resource_changes
    "delete" in change.change.actions
    change.type in {"aws_db_instance", "aws_s3_bucket", "aws_dynamodb_table"}
    msg := sprintf("%s would be destroyed — stateful resources need an approved exception",
                   [change.address])
}
```

That policy is section 4c expressed as a gate: no plan that destroys a stateful resource merges without an exception. Sentinel (HashiCorp's own) and Checkov do the same job with different syntax. And drift detection is a scheduled job, not a vibe:

```bash
# nightly. -detailed-exitcode: 0 = no changes, 1 = error, 2 = drift found
terraform plan -refresh-only -detailed-exitcode || \
  [ $? -eq 2 ] && notify "drift detected in $ENVIRONMENT"
```

Run it nightly per environment and route the output to the owning team. Drift found within a day is a conversation; drift found after six months is an archaeology project, and it will be found by an unrelated apply at the worst possible moment.

### Secrets, honestly

`sensitive = true` hides a value from CLI output. **It does not remove it from state.** Neither does anything else. The mitigations, in order of effectiveness:

1. **Do not put the secret in state at all.** Store it in a secrets manager, put only the *reference* (an ARN, a path) in your configuration, and have the application fetch the value at runtime. The infrastructure tool then never sees the plaintext.
2. **Encrypt the backend and treat it as a credential store** — encryption at rest, tight access control, audit logging on reads.
3. **Never commit state.** It belongs in the backend and nowhere else; add it to `.gitignore` on the day you create the repository.
4. **Rotate anything that has passed through state** if the file has ever been on a laptop, in a CI log, or in a bucket with loose permissions. See [Secrets Management & Rotation](../../07-auth-and-security/13-secrets-management-and-rotation/).

### Pulumi and CDK: the real-programming-language alternative

Pulumi and the AWS CDK let you declare infrastructure in TypeScript, Python, Go or C#: loops, types, functions, unit tests, an IDE that autocompletes. For a large stack with genuine repetition this is a real ergonomic gain, and the underlying model does not change — CDK synthesises CloudFormation, Pulumi keeps its own state and plan.

The honest trade-off is that **the diff is no longer a property of a static file.** With HCL, what the configuration says is what it says; review is reading. With a general-purpose language, understanding what will be created can require executing the program in your head, and the ways to be accidentally non-deterministic — a timestamp, a network call at synth time, a dictionary iteration order — are as many as the language provides. CloudFormation's variant of the trade is that AWS holds the state for you, so there is no state file to lose or leak; in exchange you get less control over drift handling and the special misery of a stack stuck in `UPDATE_ROLLBACK_FAILED`.

### Production rules

- **Nobody clicks in the console.** Read-only access for everyone, break-glass credentials that page when used, and every use followed by importing or reverting what was done. This is a social rule enforced with permissions, not a preference.
- **Every change is a reviewed plan, and the plan output is the review artifact.** Post it on the pull request. The reviewer's job is not "does this code look right" but "is this list of operations the list we intended."
- **Read the destroy count first.** Then read every `forces replacement` line. Then approve.
- **Guard every stateful resource** with `prevent_destroy`, and back it with a policy check so that removing the guard is itself a reviewed change.
- **Remote backend, locking on, versioning on, encrypted, access-controlled.** Non-negotiable above one person.
- **One state file per environment**, blast radius sized deliberately. Also split by rate of change: the network that changes twice a year does not belong in the same state as the service that ships daily.
- **Run drift detection on a schedule** and route it to the team that owns the resources.
- **Never hand-edit state.** Use `terraform state mv`, `moved`, `import` and `terraform state rm`. Hand-editing is how the mapping gets corrupted, and the corruption surfaces one apply later, as an offer to recreate something that already exists.

## Think about it

1. Your team runs `terraform apply` from a laptop with local state. Today the laptop's disk fails. The infrastructure is untouched and still serving traffic. Describe precisely what you have lost, what you still have, and the recovery path — and estimate the effort for 40 resources versus 400. What is different about the 400-resource case beyond arithmetic?
2. A plan says `Plan: 6 to add, 1 to change, 6 to destroy` and the configuration diff is a single line. Before running anything, what four questions do you ask of the plan output, in what order, and which single line of the diff tells you whether this is a rename, a resize, or a rebuild?
3. Someone widened a database's backup window in the console during an incident and it fixed the problem. The nightly drift check flags it. Argue both options — re-assert the declaration, or adopt reality — and say what the deciding evidence is. Now the same drift appears on a security group rule that opens a port. Does your answer change, and why is that asymmetry not hypocrisy?
4. The measured cascade replaced 6 of 7 resources because immutable attributes referenced things being replaced. Redesign the declaration so that the same CIDR change touches as few resources as possible. What did you have to give up, and which of your changes weakened the dependency graph in a way you would have to document?
5. Your CI pipeline runs `terraform apply -auto-approve` on merge to `main`. Someone opens a pull request that deletes a resource block for something they believe is unused. Trace what happens from merge to outage, name every point where a control could have stopped it, and pick the two you would actually implement first.

## Key takeaways

- **Declarative beats imperative because it can be re-evaluated.** A script is correct once; a declaration is correct forever. The measured proof is one line: after applying 7 resources, the immediate re-plan was **`0 to add, 0 to change, 0 to destroy` with 7 read calls and 0 write calls**. That idempotence is what makes the tool safe to run unattended in CI on every merge.
- **There are three states, not two, and the state file is a cache of reality.** It maps `"subnet.app_a" -> "sub-4d3c1a"` — a mapping the cloud cannot reconstruct. Proved by building two subnets **identical in every attribute except their id**: "which one is mine?" has no answer in the cloud's own data. Drift is that cache going stale, and lose the file and nothing you own is managed any more.
- **Replace is the verb that deletes databases, and it propagates.** Changing a *mutable* attribute updates in place and keeps the id (`srv-25165e` before and after). Changing one *immutable* attribute at the root of the graph produced **`Plan: 6 to add, 1 to change, 6 to destroy` — 6 of 7 resources replaced, 5 of them edited by nobody** — because each dragged-in resource had an immutable attribute pointing at a value that became `(known after apply)`. The cascade stops only at a **mutable** attribute; the load balancer absorbed it as a single update.
- **One line of lifecycle configuration is the whole guard.** `prevent_destroy` on the database refused that plan **as a whole** — 7 cloud objects untouched, `db-18b8ff` intact — rather than applying the other five replacements. `create_before_destroy` is the other half: it cut a replacement's modelled zero-capacity window from **~25 s to 0 s**, at the cost of running two objects at once.
- **The dependency graph is derived, not written, and it pays for itself twice.** Seven resources, seven reference-derived edges, four waves: **342 s serial versus 245 s following the DAG (1.40×)**, with all the remaining cost on the critical path `network.core → subnet.app_a → database.main`. It also reverses for destroy, and it refuses cycles outright — `Error: Cycle: server.a -> server.b -> server.a`, with no plan produced at all.
- **Drift's real cost is the collateral, and unmanaged resources are invisible.** Four console clicks left **3 of 7 resources drifted (2 attributes changed, 1 vanished)**, and the correcting plan proposed to **replace a healthy, untouched server** because its subnet was coming back with a new id. Meanwhile a hand-made resource appeared in **no plan at all** — unmanaged means invisible, not safe. And the state file recorded the database password in plaintext, which is why the backend is encrypted, access-controlled, versioned, locked, and never committed.

Next: [Orchestration: Control Loops, Schedulers & Kubernetes](../07-orchestration-and-kubernetes/) — the same desired-state model, except that instead of running when a human types `apply`, a controller runs the compare-and-correct loop continuously, forever, and drift is corrected in seconds rather than reported the next morning.
