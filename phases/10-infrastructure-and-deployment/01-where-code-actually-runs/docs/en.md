# Where Code Actually Runs: Bare Metal, VMs, Containers & Serverless

> "It works on my laptop" is not a joke about carelessness. It is a statement about ambient state — a library, a locale, a working directory, a port, a CPU count — that your laptop handed your process for free and production does not. Measured here, inside a real container: `os.cpu_count()` reported **10** while the process was allowed to run on **2** CPUs, and a worker pool sized from that first number took **6.3× longer to return its first answer**, held **5.0× the memory**, and bought **no extra throughput at all**. Nothing errored. This lesson is the ladder of places code can run — bare metal, virtual machine, container, serverless, managed service — and what each rung stops giving you for free.

**Type:** Learn
**Languages:** Python
**Prerequisites:** [How a Computer Runs a Program](../../00-foundations/09-how-a-computer-runs-a-program/), [Files & the Filesystem](../../00-foundations/10-files-and-the-filesystem/)
**Time:** ~60 minutes

## The Problem

It is 09:40 on a Tuesday. The service has passed review, passed CI (Continuous Integration — the automated build-and-test pipeline), and run on your laptop every day for three weeks. You deploy it. Here is the morning, in order.

**09:41 — a missing system library.** The process exits before it prints anything: `ImportError: libxml2.so.2: cannot open shared object file`. Your laptop has `libxml2` because something else installed it eighteen months ago and you never knew. The production image is a slim base with 94 packages in it, and that is not one of them. Your code never mentioned `libxml2`; a dependency of a dependency links against it.

**09:52 — a locale.** You add the package, redeploy, and the service starts. An hour later the nightly dedupe job produces duplicates. Your laptop's default locale is `en_US.UTF-8`; the slim image ships the `C` locale (also called `POSIX`), where `str.upper()` and string comparison follow ASCII rules only. `"straße".upper()` and the sort order of a list of German customer names are both different, so two records that matched locally no longer match.

**10:15 — a working directory.** A code path that only runs on the reporting endpoint opens `./config/limits.yaml`. On your laptop you always `cd` into the repo before running anything, so the relative path resolves. The container's working directory is `/`, so the same string resolves to `/config/limits.yaml`, which does not exist. [Files & the Filesystem](../../00-foundations/10-files-and-the-filesystem/) is why: a relative path is meaningless without a current working directory, and the current working directory is ambient state.

**10:30 — a version.** The TLS (Transport Layer Security) handshake to a partner's legacy API fails. Your laptop has OpenSSL 1.1; the image has OpenSSL 3, which refuses the partner's renegotiation by default. Nothing in your code changed. A number in a library you never imported changed.

**10:44 — a port.** You add a debug endpoint on 8080. It never receives a request. In the pod, a logging sidecar already holds 8080, and your bind failed with `EADDRINUSE` at startup, on a thread whose exception handler logged at DEBUG.

Every one of those is fixable, and every one of them is *loud*. A stack trace, a bind error, a failed handshake. Which brings us to the sixth.

**11:20 — a CPU count.** Your service sizes its worker pool the way every framework's default does: from the number of CPUs (Central Processing Units — the cores that execute instructions). `os.cpu_count()` returns 10 on your laptop, so you get 10 workers locally, which is right. In production, the container runs on a shared 64-core node, and **`os.cpu_count()` returns 64** — because it reports the machine, and the machine has 64 cores. Meanwhile the deployment gives the container a limit of 2 CPUs. So you get 64 workers competing for 2 CPUs' worth of time.

Nothing errors. There is no missing file, no failed bind, no exception. The program asked the kernel a question, the kernel answered truthfully, and the answer was about a *machine* rather than about *you*. The p99 latency (the value 99% of requests come in under) goes from 40 ms to something with a comma in it, memory use goes up fivefold, and the graph everyone looks at — CPU utilisation — reads 100%, which is exactly what you would expect from a busy service.

**The first five problems are solved by shipping the environment with the code.** That is a container image, and the next three lessons build one. **The sixth is not, because the sixth is not about the environment — it is about the boundary.** Your code is running somewhere, that somewhere gives it a specific slice of a specific machine, and almost nothing in your runtime tells you what the slice is unless you ask precisely the right question.

So: what are the places code can run, what does each one actually give you, and what does each one silently take away?

## The Concept

### The compute ladder

There are five common answers to "where does this run", and they form a ladder. Each rung slices the same physical machine at a different layer, and everything else — how fast it starts, how many fit on a host, what a break-in reaches, who applies the security patch, and who pays when it sits idle — falls out of *where the slice is taken*.

- **Bare metal.** Your code runs on a physical machine with no virtualization at all. You own the kernel, the distribution, the disks.
- **VM (virtual machine).** Software presents *fake hardware* — a CPU, RAM (Random Access Memory), a disk, a network card — and a complete operating system boots on top of it, believing it is alone on a computer.
- **Container.** A group of ordinary processes on a *shared* kernel, given a private view of the filesystem, the process table, and the network, plus a hard accounting limit on CPU and memory.
- **Serverless / FaaS (Function as a Service).** You upload a function. The provider runs it on demand, from zero instances to thousands and back to zero, and bills per invocation.
- **Managed service.** The rung someone else operates entirely: a hosted database, a hosted queue, a hosted cache. You get an endpoint and a bill.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 430" width="100%" style="max-width:840px" role="img" aria-label="The compute ladder drawn as five columns sharing one row grid: bare metal, virtual machine, container, serverless function and managed platform. Each row is a layer of the stack from hardware at the bottom to your code at the top, coloured green where you write it, purple where it is your own isolated substrate, and grey where it is shared with other tenants or operated by someone else. Moving right, the green and purple shrink and the grey grows. The container column's kernel cell is outlined in red because it is the host kernel shared with every other container. Underneath, four measured rows compare cold start, density per host, blast radius and who patches the kernel.">
  <text x="440" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">The compute ladder: the same stack, sliced at a different layer</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">

    <g fill="currentColor" font-size="10.5" font-weight="700" text-anchor="middle">
      <text x="192" y="60">BARE METAL</text>
      <text x="341" y="60">VIRTUAL MACHINE</text>
      <text x="490" y="60">CONTAINER</text>
      <text x="639" y="60">SERVERLESS</text>
      <text x="788" y="60">MANAGED SERVICE</text>
    </g>
    <g fill="currentColor" font-size="8.5" opacity="0.7" text-anchor="middle">
      <text x="192" y="74">a machine you own</text>
      <text x="341" y="74">virtualized hardware</text>
      <text x="490" y="74">virtualized view</text>
      <text x="639" y="74">a function, on demand</text>
      <text x="788" y="74">someone else's rung</text>
    </g>

    <g fill="currentColor" font-size="9" text-anchor="end" opacity="0.75">
      <text x="114" y="106">your code</text>
      <text x="114" y="138">runtime / libs</text>
      <text x="114" y="170">OS userland</text>
      <text x="114" y="202">kernel</text>
      <text x="114" y="234">virtualization</text>
      <text x="114" y="266">hardware</text>
    </g>

    <g fill="none" stroke-width="1.6">
      <rect x="124" y="88" width="137" height="28" rx="6" fill="#0fa07f" fill-opacity="0.16" stroke="#0fa07f"/>
      <rect x="124" y="120" width="137" height="28" rx="6" fill="#7c5cff" fill-opacity="0.13" stroke="#7c5cff"/>
      <rect x="124" y="152" width="137" height="28" rx="6" fill="#7c5cff" fill-opacity="0.13" stroke="#7c5cff"/>
      <rect x="124" y="184" width="137" height="28" rx="6" fill="#7c5cff" fill-opacity="0.13" stroke="#7c5cff"/>
      <rect x="124" y="216" width="137" height="28" rx="6" fill="#7f7f7f" fill-opacity="0.07" stroke="#7f7f7f" stroke-dasharray="4 4"/>
      <rect x="124" y="248" width="137" height="28" rx="6" fill="#7c5cff" fill-opacity="0.13" stroke="#7c5cff"/>

      <rect x="273" y="88" width="137" height="28" rx="6" fill="#0fa07f" fill-opacity="0.16" stroke="#0fa07f"/>
      <rect x="273" y="120" width="137" height="28" rx="6" fill="#7c5cff" fill-opacity="0.13" stroke="#7c5cff"/>
      <rect x="273" y="152" width="137" height="28" rx="6" fill="#7c5cff" fill-opacity="0.13" stroke="#7c5cff"/>
      <rect x="273" y="184" width="137" height="28" rx="6" fill="#7c5cff" fill-opacity="0.13" stroke="#7c5cff"/>
      <rect x="273" y="216" width="137" height="28" rx="6" fill="#7f7f7f" fill-opacity="0.12" stroke="#7f7f7f"/>
      <rect x="273" y="248" width="137" height="28" rx="6" fill="#7f7f7f" fill-opacity="0.12" stroke="#7f7f7f"/>

      <rect x="422" y="88" width="137" height="28" rx="6" fill="#0fa07f" fill-opacity="0.16" stroke="#0fa07f"/>
      <rect x="422" y="120" width="137" height="28" rx="6" fill="#7c5cff" fill-opacity="0.13" stroke="#7c5cff"/>
      <rect x="422" y="152" width="137" height="28" rx="6" fill="#7c5cff" fill-opacity="0.13" stroke="#7c5cff"/>
      <rect x="422" y="184" width="137" height="28" rx="6" fill="#d64545" fill-opacity="0.14" stroke="#d64545" stroke-width="2.2"/>
      <rect x="422" y="216" width="137" height="28" rx="6" fill="#7f7f7f" fill-opacity="0.12" stroke="#7f7f7f"/>
      <rect x="422" y="248" width="137" height="28" rx="6" fill="#7f7f7f" fill-opacity="0.12" stroke="#7f7f7f"/>

      <rect x="571" y="88" width="137" height="28" rx="6" fill="#0fa07f" fill-opacity="0.16" stroke="#0fa07f"/>
      <rect x="571" y="120" width="137" height="28" rx="6" fill="#7f7f7f" fill-opacity="0.12" stroke="#7f7f7f"/>
      <rect x="571" y="152" width="137" height="28" rx="6" fill="#7f7f7f" fill-opacity="0.12" stroke="#7f7f7f"/>
      <rect x="571" y="184" width="137" height="28" rx="6" fill="#7f7f7f" fill-opacity="0.12" stroke="#7f7f7f"/>
      <rect x="571" y="216" width="137" height="28" rx="6" fill="#7f7f7f" fill-opacity="0.12" stroke="#7f7f7f"/>
      <rect x="571" y="248" width="137" height="28" rx="6" fill="#7f7f7f" fill-opacity="0.12" stroke="#7f7f7f"/>

      <rect x="720" y="88" width="137" height="28" rx="6" fill="#0fa07f" fill-opacity="0.16" stroke="#0fa07f"/>
      <rect x="720" y="120" width="137" height="156" rx="6" fill="#7f7f7f" fill-opacity="0.12" stroke="#7f7f7f"/>
    </g>

    <g fill="currentColor" font-size="9" text-anchor="middle">
      <text x="192" y="106" font-weight="700" fill="#0fa07f">your process</text>
      <text x="192" y="138">your runtime</text>
      <text x="192" y="170">your distro</text>
      <text x="192" y="202" font-weight="700">your kernel</text>
      <text x="192" y="234" opacity="0.55">none</text>
      <text x="192" y="266" font-weight="700">dedicated CPUs</text>

      <text x="341" y="106" font-weight="700" fill="#0fa07f">your process</text>
      <text x="341" y="138">your runtime</text>
      <text x="341" y="170">your distro</text>
      <text x="341" y="202" font-weight="700">GUEST kernel</text>
      <text x="341" y="234">hypervisor</text>
      <text x="341" y="266">shared CPUs</text>

      <text x="490" y="106" font-weight="700" fill="#0fa07f">your process</text>
      <text x="490" y="138">image runtime</text>
      <text x="490" y="170">image userland</text>
      <text x="490" y="202" font-weight="700" fill="#d64545">HOST kernel</text>
      <text x="490" y="234">runtime + cgroups</text>
      <text x="490" y="266">shared CPUs</text>

      <text x="639" y="106" font-weight="700" fill="#0fa07f">your handler</text>
      <text x="639" y="138">managed runtime</text>
      <text x="639" y="170">provider userland</text>
      <text x="639" y="202">provider kernel</text>
      <text x="639" y="234">microVM sandbox</text>
      <text x="639" y="266">shared CPUs</text>

      <text x="788" y="106" font-weight="700" fill="#0fa07f">your queries</text>
      <text x="788" y="170">everything below</text>
      <text x="788" y="186">this line is</text>
      <text x="788" y="202">operated, patched</text>
      <text x="788" y="218">and paged for</text>
      <text x="788" y="234">by the provider</text>
    </g>

    <path d="M124 288 L 857 288" fill="none" stroke="currentColor" stroke-width="1.1" opacity="0.35"/>

    <g fill="currentColor" font-size="8.5" text-anchor="end" opacity="0.7">
      <text x="114" y="306">cold start</text>
      <text x="114" y="328">per host</text>
      <text x="114" y="350">blast radius</text>
      <text x="114" y="372">kernel patched by</text>
    </g>

    <g font-size="8.5" text-anchor="middle" fill="currentColor">
      <text x="192" y="306">minutes (POST+boot)</text>
      <text x="341" y="306">seconds</text>
      <text x="490" y="306">10-100 ms</text>
      <text x="639" y="306">0 ms warm</text>
      <text x="788" y="306">not yours</text>

      <text x="192" y="328">1</text>
      <text x="341" y="328">tens</text>
      <text x="490" y="328">hundreds</text>
      <text x="639" y="328">thousands</text>
      <text x="788" y="328">not yours</text>

      <text x="192" y="372">you</text>
      <text x="341" y="372">you (guest)</text>
      <text x="490" y="372">the host owner</text>
      <text x="639" y="372">the provider</text>
      <text x="788" y="372">the provider</text>
    </g>

    <g font-size="8.5" text-anchor="middle" fill="currentColor" opacity="0.75">
      <text x="341" y="317">(125 ms microVM)</text>
      <text x="639" y="317">0.1-1 s cold</text>
    </g>

    <g font-size="8.5" text-anchor="middle" font-weight="700" fill="#d64545">
      <text x="192" y="350">the machine</text>
      <text x="341" y="350">hypervisor escape</text>
      <text x="490" y="350">KERNEL escape</text>
      <text x="639" y="350">sandbox escape</text>
      <text x="788" y="350">the provider</text>
    </g>

    <text x="440" y="402" font-size="11" text-anchor="middle" fill="currentColor" opacity="0.9">A VM brings its own kernel; a container shares the host's and virtualizes only the view.</text>
    <text x="440" y="420" font-size="11" text-anchor="middle" fill="currentColor" opacity="0.9">That one sentence explains the cold start, the density, and where the red cell is.</text>
  </g>
</svg>
```

Read the diagram as a colour gradient: **green is what you write, purple is substrate that is yours alone, grey is shared with strangers or operated by someone else.** Going right, the green and purple shrink and the grey grows. That is the actual trade in this lesson. You are not choosing a technology; you are choosing how much of the stack you are responsible for, and how much of it you are trusting.

### A VM brings its own kernel; a container shares the host's and virtualizes only the view

This is the sentence to keep. Everything else in the ladder is a consequence of it.

The **kernel** is the program that owns the hardware. It is the only code allowed to talk to the CPU's privileged instructions, the disk controller, the network card. Your program never touches any of them directly; it makes a **system call** (a syscall — a controlled jump into the kernel: `read`, `write`, `open`, `mmap`, `clone`), and the kernel does the work on its behalf. [How a Computer Runs a Program](../../00-foundations/09-how-a-computer-runs-a-program/) walks that path.

**A VM virtualizes the hardware.** The hypervisor shows the guest a CPU, some RAM, a disk and a NIC (Network Interface Card) that are all fabrications. The guest therefore has to do what any computer does with hardware: run firmware, load a bootloader, start *its own kernel*, initialise *its own* device drivers, and boot *its own* userland. That is why a VM takes seconds to tens of seconds to start, why you can only fit tens on a host — each one is carrying a whole operating system's worth of memory — and why the guest kernel is the guest's problem to patch.

**A container virtualizes only the view.** There is no second kernel. Your processes make syscalls directly into the *host's* kernel, exactly like every other process on that machine. What changes is what those syscalls *see*: a private filesystem tree, a private process table, a private network stack, a private hostname. Nothing has to boot, because nothing new is being started except your processes. That is why a container starts in tens to hundreds of milliseconds, why hundreds fit on a host, and why the host owner patches the kernel — because there is only one, and it is theirs.

And it is why the blast radius differs so sharply. A bug in your code reaches your process on either rung. **A kernel vulnerability crosses container boundaries and does not cross VM boundaries**, because on the container rung there is exactly one kernel and every tenant is calling into it. The VM's equivalent failure is a hypervisor escape, which is a much smaller and much more heavily scrutinised piece of software. This is not a claim that containers are insecure; it is a claim about *what a boundary is made of*, and it is why providers running untrusted code from strangers — the serverless rung — put a VM back underneath the container rather than trusting the shared kernel.

### Hypervisors, type 1 and type 2

The formal requirements for a hypervisor were set out by Popek and Goldberg in 1974 (*Formal Requirements for Virtualizable Third Generation Architectures*, CACM 17(7)): a virtual machine monitor must provide an environment essentially identical to the real machine, with only a minor speed penalty, and must retain complete control of system resources.

- **Type 1 (bare metal).** The hypervisor *is* the thing running on the hardware; there is no host operating system beneath it. Xen, VMware ESXi, Microsoft Hyper-V. Linux's KVM is a type 1 in the ways that matter — the hypervisor lives inside the Linux kernel itself, turning the kernel into the hypervisor rather than running above one. This is what every major cloud runs your instances on.
- **Type 2 (hosted).** The hypervisor is an application on a normal desktop operating system, which handles the hardware. VirtualBox, VMware Workstation, and — relevant to you right now — the Linux VM that Docker Desktop runs on macOS and Windows.

That last one is worth pausing on, because it is the machine you are about to measure. On a Mac, `docker compose exec app` reaches a *container* inside a *type 2 hypervisor's Linux VM* on macOS. Three rungs of this ladder, stacked, on a laptop. The measurements below are taken from the top of that stack looking down, which is exactly the position your production code is in.

### The two mechanisms a container is made of

Lesson 2 builds these properly; you need the one-line version now, because the Build It reads both directly.

- **Namespaces** control **what you can see.** A namespace is a private copy of one global kernel resource. There are eight of them, and each is identified by nothing more than an inode number — a file identity in the kernel's `nsfs` filesystem, visible at `/proc/self/ns/`. Two processes showing the same inode share that namespace; different numbers mean private views. (`man 7 namespaces`.)
- **cgroups** (control groups) control **how much you can use.** A cgroup is an accounting bucket: CPU time, memory bytes, I/O bandwidth, process count. Version 2 exposes them as a single tree of plain files under `/sys/fs/cgroup`, where `cpu.max` holds your CPU bandwidth and `memory.max` your hard memory ceiling. (Linux kernel `Documentation/admin-guide/cgroup-v2.rst`.)

Seeing and using are separate, and **that separation is the source of the bug in the problem section.** Your CPU *limit* lives in a cgroup file. Your *view* of how many CPUs exist comes from `/proc` and `/sys`, which are not namespaced for CPU topology at all. So the kernel will cheerfully tell you the host has 64 cores while holding you to two of them, and it is not lying in either answer — you asked two different questions.

### Serverless: scale-to-zero, and the four limits you accept for it

Serverless (more precisely **FaaS**, Function as a Service) inverts the deployment model. You do not run a process; you register a function, and the provider creates an execution environment when a request arrives, reuses it for subsequent requests, and destroys it after an idle period.

**Scale-to-zero is the entire product.** At 03:00 with no traffic there are no instances and the bill is zero. That single property is what you are buying, and everything else is the price:

- **Cold start.** The first request to a new instance pays for creating the sandbox, loading your code, and running your initialisation before your handler ever executes. A warm instance answers in microseconds of overhead; a cold one adds anywhere from ~100 ms to seconds depending on runtime and package size. Cold starts are not rare in a well-designed system; they happen on every scale-up, every deploy, and after every idle period. **Your p99 is a cold-start distribution whether you measured it or not.**
- **Execution-time limits.** There is a hard ceiling on how long one invocation may run, typically measured in minutes. Work that takes longer must be decomposed or moved to a different rung.
- **No state between invocations, and none you can rely on.** An instance may be reused, so the process-local cache you filled may still be there — or may not, because the next request goes to a different instance or a fresh one. Caching is therefore an optimisation you may never depend on for correctness.
- **No background work after the response.** The environment is frozen or destroyed once the handler returns. A fire-and-forget task started just before returning may simply never run, and it will fail this way *intermittently*, which is worse than failing always.

Under the hood, the serious implementations put a VM back under each function precisely because of the shared-kernel argument above: AWS's Firecracker (*Firecracker: Lightweight Virtualization for Serverless Applications*, NSDI 2020) is a minimal virtual machine monitor built to give each tenant a real hardware boundary while booting to userland in about 125 ms. **That number is the answer to "VMs are slow": a general-purpose VM is slow because of everything a general-purpose VM carries, not because virtualization is inherently expensive.**

### Regions, availability zones, and the unit of correlated failure

Cloud capacity is organised in two levels, and the distinction is operational, not marketing.

- A **region** is a geographic area — a metro, roughly. Regions are far apart, and traffic between them crosses the public backbone with latency proportional to distance and a bill attached to every byte.
- An **availability zone (AZ)** is one or more data centres inside a region with **independent power, independent cooling, and independent physical network**, deliberately far enough apart that one flood, fire, or substation failure cannot take two of them, and close enough that the network between them is fast enough to run a synchronous replica across.

**The AZ is the unit of correlated failure.** That is the whole reason the concept exists. Two instances in the same AZ can fail together for reasons that have nothing to do with your code: a power event, a cooling failure, a network partition, a rack. Two instances in different AZs, in general, cannot. So the design rules are simple and unromantic:

- Anything that must survive a single infrastructure failure must exist in **at least two AZs**, and its failover must be tested — an untested failover is an assumption.
- The AZ boundary is the only unit your provider will make availability commitments about. "Three instances" is not redundancy if the scheduler placed all three in one AZ; check, do not assume.
- Cross-AZ traffic is usually billed and cross-region traffic definitely is, so a naive "spread everything everywhere" design can turn your data-transfer line item into your largest one.
- **A region is not a failure domain you can ignore.** Whole-region events are rare and they happen. Whether you carry the cost of multi-region is a business decision about your recovery objectives — but it should be a *decision*, written down, not a discovery made during an outage.

### Managed services are rungs someone else operates

A hosted database, cache, or queue is not a different kind of thing from the ladder — it is a rung whose entire stack, up to and including the application, is operated by the provider. You supply queries and configuration; they supply capacity, patching, backups, failover and an on-call rota.

The honest accounting: you are trading **control and cost per unit** for **engineer-hours and expertise you would otherwise have to hire.** A self-run database is cheaper per gigabyte and more tunable, and it also means someone on your team owns replication lag, version upgrades, and 03:00 failovers forever. Neither answer is universally right. What is universally wrong is choosing without pricing the second column.

### What actually decides the rung

Not fashion, and not what the last conference talk said. Six things:

1. **Who is on call, and how many of them are there?** This dominates everything else. A three-person team running Kubernetes is a three-person team with a part-time Kubernetes job. The right rung is the highest one whose failure modes you can actually staff.
2. **The shape of your traffic, not its size.** The ratio of peak to trough decides who should pay for idle. The model below uses a real diurnal curve with a **31× peak-to-trough ratio** and still finds always-on cheaper — because the *average* utilisation, not the ratio, is what the bill responds to.
3. **Your latency floor.** If a cold start of a few hundred milliseconds is unacceptable on your p99, scale-to-zero is not available to you at any price. Provisioned concurrency buys it back and, in doing so, buys back idle cost too — which is the thing you went to serverless to avoid.
4. **State.** Long-lived connections, local disk, in-memory caches that must survive, background loops, WebSockets: each of these is a reason the serverless rung will fight you. Stateless request/response is the shape that fits.
5. **Compliance and tenancy.** Data residency, dedicated hardware requirements, and regulatory audits routinely rule out entire rungs before any technical argument starts.
6. **The cost of idle.** Which is not a vibe. It is a crossover point you can compute, and the model below computes it: for that workload's prices, **always-on wins above 5.6% utilisation.**

## Build It

[`code/compute_ladder.py`](code/compute_ladder.py) measures the rung it is running on, from the inside. Standard library only, about 19 seconds. The timing rows are best-of-N batches, because creation cost is a minimum problem — contention from other tenants on the host can only ever add time — so the *ratios* hold across runs even though the absolute milliseconds move with host load.

Run it:

```bash
docker compose exec -T app python \
  phases/10-infrastructure-and-deployment/01-where-code-actually-runs/code/compute_ladder.py
```

### 1 · Proving you are already inside a container

The script opens by reading its own namespace inodes out of `/proc/self/ns/`. There is a trick that makes the answer unambiguous: the kernel assigns the *initial* namespace of each type a fixed inode number at compile time (`include/linux/proc_ns.h`), so comparing against those constants tells you, per namespace, whether you have a private one:

```python
INIT_INO = {
    "time": 0xEFFFFFFA,   # 4026531834
    "cgroup": 0xEFFFFFFB,  # 4026531835
    "pid": 0xEFFFFFFC,    # 4026531836
    "user": 0xEFFFFFFD,   # 4026531837
    ...
}

target = os.readlink("/proc/self/ns/%s" % name)   # e.g. "pid:[4026533911]"
ino = int(target.split("[")[1].rstrip("]"))
isolated = ino != INIT_INO[name]
```

The result is **7 namespaces private to this process and 1 shared with the host** — and the shared one is `user`, at inode `4026531837`, exactly the compile-time initial value. That single fact is the security story of the container rung in one line: **there is no user-ID remapping here, so uid 0 inside this container is uid 0 on the host kernel.** A container escape is therefore a root escape. Rootless runtimes exist to close precisely that gap by giving the container a user namespace where its "root" maps to an unprivileged host uid.

The cgroup half is just files. `/proc/self/cgroup` reads `0::/` — the `0` means cgroup v2's single unified hierarchy, and the path is `/` rather than a long `/docker/<id>` because the cgroup *namespace* re-roots the view. `/sys/fs/cgroup` is mounted `ro` (read-only): **you can read your limits and you cannot raise them.** Whoever started the container decided; you live inside the decision.

The last line of the section is the one to internalise:

```text
  /proc/meminfo MemTotal   7.75 GiB   <- the HOST's RAM, not yours
  cgroup memory.max        max
```

`/proc/meminfo` is **not namespaced.** A runtime that sizes a heap, a buffer pool, or a cache as "a fraction of system memory" reads the host's RAM, allocates for a machine it does not have, and gets SIGKILLed by the kernel's OOM (Out Of Memory) killer with no stack trace and no log line. Same bug as the CPU count, different resource.

### 2 · The CPU-count trap — the centrepiece

Three APIs answer "how many CPUs do I have?", and they answer different questions:

```text
  os.cpu_count()          10          the machine's CPUs. Never your limit.
  os.sched_getaffinity(0) 10          CPUs you may be SCHEDULED on (cpuset)
  /sys/fs/cgroup/cpu.max  max 100000  the CFS bandwidth quota you are held to
```

- **`os.cpu_count()`** counts the CPUs the *kernel* knows about. It is a property of the machine. It is what almost every default pool size in almost every runtime reads, and it is **never** your limit.
- **`os.sched_getaffinity(0)`** returns the set of CPUs this process may be scheduled on — the **cpuset**, set by `docker run --cpuset-cpus`. This is a hard restriction on *which* cores, inherited by every child process.
- **`/sys/fs/cgroup/cpu.max`** is the **CFS bandwidth quota** (CFS = Completely Fair Scheduler; see `Documentation/scheduler/sched-bwc.rst`). It reads as two numbers, `quota_us period_us`: how many microseconds of CPU time your whole cgroup may consume per period. This is what `docker run --cpus=2` and a Kubernetes CPU *limit* set.

The sandbox has no bandwidth quota set (`cpu.max` reads `max`), so the script imposes the one limit it is permitted to impose — `sched_setaffinity` to 2 CPUs, which is precisely what `--cpuset-cpus=0,1` does — and then shows the disagreement:

```text
  after the call: os.cpu_count()=10  sched_getaffinity=2  <- they now DISAGREE
```

Then it runs identical work twice: 24 tasks, each a fixed 900,000-iteration LCG walk (a linear congruential generator — pure arithmetic, no I/O, no allocation, so the only thing being measured is CPU time), through a process pool sized two different ways.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 470" width="100%" style="max-width:840px" role="img" aria-label="The cpu_count versus cgroup quota trap, with measured numbers. Three APIs are consulted: os.cpu_count reports ten, which is the machine; sched_getaffinity reports two, which is the cpuset; and the cgroup file cpu.max holds the bandwidth quota. Two panels then run the identical twenty-four task workload through a process pool. The left panel sizes the pool from os.cpu_count, giving ten workers on two CPUs, a five times oversubscription, 13.87 tasks per second, 748 milliseconds to the first answer and 117 megabytes of worker memory. The right panel sizes it from the quota, giving two workers, 19.15 tasks per second, 119 milliseconds to the first answer and 23.3 megabytes. Same CPUs, same work.">
  <defs>
    <marker id="l01-a1" markerWidth="10" markerHeight="10" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker>
  </defs>
  <text x="440" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">Three APIs answer &quot;how many CPUs do I have?&quot; — two of them lie to you</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">

    <g fill="none" stroke-width="1.8">
      <rect x="20" y="44" width="272" height="56" rx="9" fill="#d64545" fill-opacity="0.11" stroke="#d64545"/>
      <rect x="304" y="44" width="272" height="56" rx="9" fill="#0fa07f" fill-opacity="0.12" stroke="#0fa07f"/>
      <rect x="588" y="44" width="272" height="56" rx="9" fill="#0fa07f" fill-opacity="0.12" stroke="#0fa07f"/>
    </g>
    <g fill="currentColor" font-size="10">
      <text x="34" y="64" font-weight="700">os.cpu_count()</text>
      <text x="34" y="80" opacity="0.85">the MACHINE's CPUs</text>
      <text x="34" y="94" font-size="9" opacity="0.7">what every default pool reads</text>
      <text x="278" y="72" font-size="19" font-weight="700" text-anchor="end" fill="#d64545">10</text>
      <text x="318" y="64" font-weight="700">sched_getaffinity(0)</text>
      <text x="318" y="80" opacity="0.85">CPUs you may run ON</text>
      <text x="318" y="94" font-size="9" opacity="0.7">set by --cpuset-cpus</text>
      <text x="562" y="72" font-size="19" font-weight="700" text-anchor="end" fill="#0fa07f">2</text>
      <text x="602" y="64" font-weight="700">cgroup cpu.max</text>
      <text x="602" y="80" opacity="0.85">quota us per period us</text>
      <text x="602" y="94" font-size="9" opacity="0.7">set by --cpus / K8s limits</text>
      <text x="846" y="72" font-size="13" font-weight="700" text-anchor="end" fill="#0fa07f">200000/100000</text>
      <text x="846" y="88" font-size="9" text-anchor="end" opacity="0.8">= 2.0 CPUs</text>
    </g>

    <g fill="none" stroke-width="2" stroke-linejoin="round">
      <rect x="20" y="120" width="414" height="284" rx="12" fill="#d64545" fill-opacity="0.07" stroke="#d64545"/>
      <rect x="446" y="120" width="414" height="284" rx="12" fill="#0fa07f" fill-opacity="0.08" stroke="#0fa07f"/>
    </g>

    <g font-size="12" font-weight="700" text-anchor="middle">
      <text x="227" y="146" fill="#d64545">pool = os.cpu_count() = 10 workers</text>
      <text x="653" y="146" fill="#0fa07f">pool = the quota = 2 workers</text>
    </g>
    <g font-size="9" text-anchor="middle" fill="currentColor" opacity="0.8">
      <text x="227" y="162">the framework default</text>
      <text x="653" y="162">what the kernel will actually give you</text>
    </g>

    <g fill="#d64545" fill-opacity="0.3" stroke="#d64545" stroke-width="1.4">
      <rect x="40" y="176" width="30" height="26" rx="4"/>
      <rect x="78" y="176" width="30" height="26" rx="4"/>
      <rect x="116" y="176" width="30" height="26" rx="4"/>
      <rect x="154" y="176" width="30" height="26" rx="4"/>
      <rect x="192" y="176" width="30" height="26" rx="4"/>
      <rect x="230" y="176" width="30" height="26" rx="4"/>
      <rect x="268" y="176" width="30" height="26" rx="4"/>
      <rect x="306" y="176" width="30" height="26" rx="4"/>
      <rect x="344" y="176" width="30" height="26" rx="4"/>
      <rect x="382" y="176" width="30" height="26" rx="4"/>
    </g>
    <g fill="#0fa07f" fill-opacity="0.3" stroke="#0fa07f" stroke-width="1.4">
      <rect x="548" y="176" width="30" height="26" rx="4"/>
      <rect x="686" y="176" width="30" height="26" rx="4"/>
    </g>

    <g fill="none" stroke="currentColor" stroke-width="1.4" opacity="0.55">
      <path d="M55 204 L 160 230" marker-end="url(#l01-a1)"/>
      <path d="M93 204 L 168 230" marker-end="url(#l01-a1)"/>
      <path d="M131 204 L 176 230" marker-end="url(#l01-a1)"/>
      <path d="M169 204 L 184 230" marker-end="url(#l01-a1)"/>
      <path d="M207 204 L 196 230" marker-end="url(#l01-a1)"/>
      <path d="M245 204 L 262 230" marker-end="url(#l01-a1)"/>
      <path d="M283 204 L 274 230" marker-end="url(#l01-a1)"/>
      <path d="M321 204 L 286 230" marker-end="url(#l01-a1)"/>
      <path d="M359 204 L 294 230" marker-end="url(#l01-a1)"/>
      <path d="M397 204 L 302 230" marker-end="url(#l01-a1)"/>
      <path d="M563 204 L 563 230" marker-end="url(#l01-a1)"/>
      <path d="M701 204 L 701 230" marker-end="url(#l01-a1)"/>
    </g>

    <g fill="#7c5cff" fill-opacity="0.16" stroke="#7c5cff" stroke-width="1.8">
      <rect x="96" y="234" width="126" height="30" rx="6"/>
      <rect x="234" y="234" width="126" height="30" rx="6"/>
      <rect x="500" y="234" width="126" height="30" rx="6"/>
      <rect x="638" y="234" width="126" height="30" rx="6"/>
    </g>
    <g font-size="10" font-weight="700" text-anchor="middle" fill="currentColor">
      <text x="159" y="254">CPU 0</text>
      <text x="297" y="254">CPU 1</text>
      <text x="563" y="254">CPU 0</text>
      <text x="701" y="254">CPU 1</text>
    </g>

    <g font-size="10" font-weight="700" text-anchor="middle">
      <text x="227" y="286" fill="#d64545">5.0x oversubscribed</text>
      <text x="653" y="286" fill="#0fa07f">1.0x — one worker per CPU</text>
    </g>

    <g fill="currentColor" font-size="9.5">
      <text x="46" y="312" opacity="0.75">throughput</text>
      <text x="46" y="332" opacity="0.75">time to 1st answer</text>
      <text x="46" y="352" opacity="0.75">worker memory (RSS)</text>
      <text x="46" y="372" opacity="0.75">capacity bought</text>
      <text x="472" y="312" opacity="0.75">throughput</text>
      <text x="472" y="332" opacity="0.75">time to 1st answer</text>
      <text x="472" y="352" opacity="0.75">worker memory (RSS)</text>
      <text x="472" y="372" opacity="0.75">capacity bought</text>
    </g>
    <g font-size="11" font-weight="700" text-anchor="end">
      <text x="414" y="312" fill="#d64545">13.87 tasks/s</text>
      <text x="414" y="332" fill="#d64545">748 ms</text>
      <text x="414" y="352" fill="#d64545">117.0 MB</text>
      <text x="414" y="372" fill="#d64545">none</text>
      <text x="840" y="312" fill="#0fa07f">19.15 tasks/s</text>
      <text x="840" y="332" fill="#0fa07f">119 ms</text>
      <text x="840" y="352" fill="#0fa07f">23.3 MB</text>
      <text x="840" y="372" fill="#0fa07f">all of it</text>
    </g>

    <text x="440" y="428" font-size="11" text-anchor="middle" fill="currentColor" opacity="0.9">Identical 24 tasks, identical 2 CPUs. Sizing from os.cpu_count() bought 5.0x the memory,</text>
    <text x="440" y="446" font-size="11" text-anchor="middle" fill="currentColor" opacity="0.9">6.3x the time to first answer, and not one extra unit of throughput. The CPUs are the CPUs.</text>
    <text x="440" y="464" font-size="9.5" text-anchor="middle" fill="currentColor" opacity="0.7">Under cpu.max rather than a cpuset, the same mistake adds hard CFS throttling on top.</text>
  </g>
</svg>
```

The three results, in order of how much they matter:

**Throughput did not improve.** The right-sized pool did 19.15 tasks/s; the oversized one did 13.87 — **28% worse**, and that exact figure moves with host load between roughly "unchanged" and "a third worse". It is never better. This is the part people find genuinely surprising, and it should not be: **the CPUs are the CPUs.** Ten runnable workers on two cores do not execute more instructions per second than two runnable workers on two cores. They execute the same instructions, plus the context switches between them.

**Time to first answer got 6.3× worse: 119 ms → 748 ms.** This is the result that matters, and it is invisible in a throughput graph. With two workers, two tasks run at full speed and finish quickly; results start arriving at 119 ms and keep arriving. With ten workers, all ten tasks make progress at one-fifth speed, so **nothing at all completes for 748 ms** and then everything completes at once. Oversubscription does not slow the *system* down much — it slows *every individual request* down by the oversubscription factor, so they can all be late together. That is a latency profile shaped exactly like an incident.

**Memory went up 5.0×: 23.3 MB → 117.0 MB.** Exactly the oversubscription factor, because each worker is a process with its own interpreter. This is the one that kills you rather than merely embarrassing you: under a `memory.max` limit, that difference is the difference between running and being SIGKILLed by the OOM killer, with no stack trace, no traceback, and no application log line.

The section then **models** — and says so — the thing this sandbox cannot demonstrate, because the sandbox has no bandwidth quota set. A cpuset restricts *which* CPUs; `cpu.max` restricts *how much CPU time per period*, and the two fail differently. With a quota of `200000 100000` (2 CPUs' worth per 100 ms period) and W runnable threads, the cgroup burns its entire quota in `quota/W` of wall time and then **the kernel freezes every thread in it until the period rolls over**:

```text
  threads W  quota spent in   then stalled      added p99
  2                 100.0 ms          0.0 ms          0.0 ms
  4                  50.0 ms         50.0 ms         50.0 ms
  8                  25.0 ms         75.0 ms         75.0 ms
  10                 20.0 ms         80.0 ms         80.0 ms
  16                 12.5 ms         87.5 ms         87.5 ms
  32                  6.2 ms         93.8 ms         93.8 ms
```

At W equal to the quota there is no stall at all. At W = 32 the cgroup is **frozen for 94 ms out of every 100 ms period**, and that 94 ms lands on whichever request happened to be halfway through being served. **This is the mechanism behind "our p99 is 100 ms and we cannot find the slow query."** There is no slow query. There is a scheduler enforcing a limit you set, on a pool you sized from the wrong number.

It is also close to invisible. CPU utilisation looks *fine* — you are using exactly your quota, which is what a quota is for. The only place it shows up is `cpu.stat`:

```text
  cpu.stat nr_throttled=0 throttled_usec=0
```

**`nr_throttled` is the container metric nobody graphs.** Non-zero means the kernel stopped your runnable threads to enforce `cpu.max`. Put it on a dashboard next to your latency percentiles ([Metrics: Counters, Gauges & Histograms from Scratch](../../09-logging-monitoring-and-observability/05-metrics-from-scratch/) covers making it a counter you can alert on) and a whole class of unexplained tail latency becomes a five-second diagnosis.

### 3 · What an isolate costs, and how many fit

The ladder's rungs differ by roughly an order of magnitude each in the cost of creating one more isolated unit. The script measures the three rungs it *can* create — a thread, a `fork()` child, and a fresh interpreter process — using Pss (Proportional Set Size, which divides each shared page by its number of sharers, so it is the honest *marginal* cost of one more isolate rather than a double-count of copy-on-write pages):

```text
  isolate                    create       memory  what it still SHARES
  thread                    0.086 ms        16 KB  address space, fds, kernel, interpreter
  fork() child              1.560 ms      7885 KB  fds and kernel; pages are copy-on-write
  fresh interpreter         7.655 ms      5276 KB  the kernel, and the binary's file pages
```

**Roughly one order of magnitude per rung: 18.1× from a thread to a `fork()`, 4.9× from a `fork()` to a fresh interpreter, 88.8× end to end.** The "what it still shares" column is the point — each step up buys isolation by giving up sharing, and creation cost is what that purchase costs. ([Processes, Threads & the GIL](../../08-concurrency-and-performance/02-processes-threads-and-the-gil/) is the deep treatment of the first two rungs.)

The memory column has a wrinkle worth understanding: the `fork()` child measures **7885 KB, more than the fresh interpreter's 5276 KB.** That looks backwards until you remember what Pss counts. The forked child is charged a share of its parent's already-grown heap; a fresh process inherits nothing but its binary's file pages. **The cost of a fork is a function of how fat the parent is at the moment you fork** — which is exactly why a pre-fork server that loads everything before forking behaves so differently from one that forks early.

On memory alone that is **~65,634 threads or ~198 fresh interpreters per GiB** — which is the density argument for the whole ladder, in two numbers. The rungs above cannot be measured here, and the script says so plainly rather than faking it: a container start adds image setup, namespace and cgroup creation and a whole process tree (tens to hundreds of ms), and a VM boot adds firmware, a kernel and an init sequence (seconds, or ~125 ms for a stripped microVM).

The reason it cannot measure them is itself a lesson, and the script demonstrates it rather than asserting it:

```text
  proof: unshare(CLONE_NEWNS) -> errno 1 (Operation not permitted).
```

We are **uid 0 — root — inside this container, and still cannot create a namespace**, because the runtime dropped `CAP_SYS_ADMIN` from the capability set (`man 7 capabilities`). Root is not the same as capable. A modern container runtime keeps a root process inside the container from doing most of the things root can do, and that gap is exactly why "just run as root inside the container, it's isolated" is a sentence with a lot of load-bearing trust in it.

### 4 · Who pays for idle

The last section is **a model, not a measurement** — no cloud API is called and no VM is billed. It prints every price it uses so you can substitute your own, and it takes one realistic weekday traffic curve with a **31× peak-to-trough ratio** (1180 req/s at the busiest hour, 38 at the quietest, 52.3M requests over the day) and prices it two ways.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 470" width="100%" style="max-width:840px" role="img" aria-label="Cost per day plotted against utilisation for two billing models. The always-on line is flat at 7.99 dollars a day because eight instances are provisioned for peak whether or not they are used. The per-invocation line rises straight from the origin, reaching 57 dollars a day at forty percent utilisation. The two cross at 5.6 percent utilisation: left of it scale-to-zero is cheaper because idle is free, right of it always-on is cheaper. The modelled weekday workload sits at 37.8 percent utilisation, where always-on costs 7.99 dollars a day against per-invocation's 54.01, a gap of 46.02 dollars a day, even though 62.2 percent of the provisioned capacity is idle.">
  <text x="440" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">Who pays for idle — and the utilisation where the answer flips</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">

    <rect x="90" y="70" width="102" height="310" fill="#e0930f" fill-opacity="0.08"/>
    <rect x="192" y="70" width="628" height="310" fill="#7c5cff" fill-opacity="0.06"/>

    <g fill="none" stroke="currentColor" stroke-width="1.5">
      <path d="M90 380 L 830 380"/><path d="M90 380 L 90 62"/>
    </g>
    <g fill="none" stroke="currentColor" stroke-width="1.1" opacity="0.4">
      <path d="M272 380 L 272 385"/><path d="M455 380 L 455 385"/><path d="M637 380 L 637 385"/><path d="M820 380 L 820 385"/>
      <path d="M85 302 L 90 302"/><path d="M85 225 L 90 225"/><path d="M85 147 L 90 147"/><path d="M85 70 L 90 70"/>
    </g>

    <path d="M90 339 L 820 339" fill="none" stroke="#7c5cff" stroke-width="2.8"/>
    <path d="M90 380 L 820 85" fill="none" stroke="#e0930f" stroke-width="2.8"/>

    <path d="M192 380 L 192 176" fill="none" stroke="#d64545" stroke-width="1.6" stroke-dasharray="5 5" opacity="0.9"/>
    <circle cx="192" cy="339" r="6.5" fill="none" stroke="#d64545" stroke-width="2.4"/>

    <path d="M780 334 L 780 106" fill="none" stroke="currentColor" stroke-width="1.2" stroke-dasharray="4 4" opacity="0.45"/>
    <circle cx="780" cy="339" r="4.5" fill="#7c5cff" stroke="#7c5cff" stroke-width="1.6" fill-opacity="0.4"/>
    <circle cx="780" cy="101" r="4.5" fill="#e0930f" stroke="#e0930f" stroke-width="1.6" fill-opacity="0.4"/>

    <g fill="currentColor" font-size="9.5" opacity="0.75">
      <text x="90" y="398" text-anchor="middle">0%</text>
      <text x="272" y="398" text-anchor="middle">10%</text>
      <text x="455" y="398" text-anchor="middle">20%</text>
      <text x="637" y="398" text-anchor="middle">30%</text>
      <text x="820" y="398" text-anchor="middle">40%</text>
      <text x="80" y="384" text-anchor="end">$0</text>
      <text x="80" y="306" text-anchor="end">$15</text>
      <text x="80" y="229" text-anchor="end">$30</text>
      <text x="80" y="151" text-anchor="end">$45</text>
      <text x="80" y="74" text-anchor="end">$60</text>
    </g>
    <text x="455" y="418" font-size="10.5" text-anchor="middle" fill="currentColor" opacity="0.85">utilisation = requests actually served / capacity provisioned</text>
    <text x="26" y="225" font-size="10.5" fill="currentColor" opacity="0.85" transform="rotate(-90 26 225)" text-anchor="middle">USD per day</text>

    <g fill="currentColor">
      <text x="202" y="140" font-size="11" font-weight="700" fill="#d64545">crossover: 5.6% utilisation</text>
      <text x="202" y="155" font-size="9" opacity="0.85">below this, scale-to-zero wins</text>
      <text x="202" y="168" font-size="9" opacity="0.85">above it, always-on wins</text>
    </g>

    <g fill="currentColor">
      <text x="202" y="192" font-size="10.5" font-weight="700">this workload: 37.8% utilisation</text>
      <text x="202" y="208" font-size="9" opacity="0.85">peak 1180 rps, trough 38 rps (31x)</text>
      <text x="202" y="222" font-size="9" opacity="0.85">52.3M requests/day</text>
      <text x="202" y="236" font-size="9" opacity="0.85">62.2% of provisioned capacity idle</text>
      <text x="202" y="252" font-size="9.5" font-weight="700" fill="#7c5cff">always-on wins by $46.02/day</text>
    </g>

    <g fill="#e0930f" font-size="9.5" font-weight="700">
      <text x="126" y="300">idle</text>
      <text x="126" y="313">is free</text>
      <text x="126" y="326">here</text>
    </g>

    <g fill="currentColor">
      <text x="440" y="292" font-size="11" font-weight="700" fill="#e0930f">per-invocation: $0.000001033 per request</text>
      <text x="440" y="307" font-size="9" opacity="0.85">zero at zero traffic; linear in what you serve</text>
      <text x="300" y="358" font-size="11" font-weight="700" fill="#7c5cff">always-on: 8 instances x 24 h = $7.99/day, flat</text>
      <text x="300" y="372" font-size="9" opacity="0.85">you pay for peak capacity every hour of the night</text>
    </g>

    <text x="770" y="88" font-size="10.5" font-weight="700" text-anchor="end" fill="#e0930f">$54.01/day</text>
    <text x="780" y="357" font-size="9.5" font-weight="700" text-anchor="middle" fill="#7c5cff">37.8%</text>

    <text x="440" y="442" font-size="11" text-anchor="middle" fill="currentColor" opacity="0.9">A model, not a measurement — substitute your own prices. It does not price cold starts,</text>
    <text x="440" y="460" font-size="11" text-anchor="middle" fill="currentColor" opacity="0.9">engineer-hours, egress, or committed-use discounts that move the flat line down 30-60%.</text>
  </g>
</svg>
```

Provisioning for peak with 25% headroom needs **8 instances**, always on. They can serve 138,240,000 requests a day and actually serve 52,264,800 — **37.8% utilisation, meaning you paid for 62.2% of nothing** — at **$7.99/day, $2,915/year**. Per-invocation billing costs $0.000001033 per request, so the same traffic costs **$54.01/day, $19,713/year.**

**Always-on is cheaper here by $46.02/day — about 6.8× — for a workload with a 31× peak-to-trough ratio and nearly two-thirds of its capacity sitting idle.** That is the counterintuitive result, and it is worth sitting with, because "we have very spiky traffic" is the most common argument offered for serverless and it is the wrong test. Setting the two expressions equal gives the crossover:

```text
  crossover: always-on wins once utilisation exceeds 5.6%
  utilisation     always-on/day per-invoke/day     winner
  1.0%                    7.99           1.43 per-invoke
  5.0%                    7.99           7.14 per-invoke
  5.6% <-                 7.99           7.99  crossover
  10.0%                   7.99          14.28  always-on
  100.0%                  7.99         142.85  always-on
```

**5.6% is a very low bar.** Above it, per-invocation billing is a premium you pay for elasticity; below it, the premium is worth it because you would otherwise be paying for a machine that does almost nothing. So the real serverless argument is *not* "our traffic is spiky" — it is "our traffic is **low, or genuinely intermittent**", which is a different claim: an internal tool, a webhook receiver, a nightly job, a new product with no users yet. Those are excellent serverless workloads and they are excellent for the same reason.

The model deliberately does not price four things, and each can move the answer: cold starts (a latency cost that can become a revenue cost), the engineer-hours of operating each rung (which usually favours the higher rung and is the single biggest omission), egress, and reserved or committed-use discounts, which move the flat line **down by 30-60%** and therefore push the crossover lower still.

### The full output

```console
== 1 · YOU ARE ALREADY IN A CONTAINER — HERE IS THE PROOF ==
  a namespace is just an inode. Two processes that see the same inode
  number share that namespace; a different number means a private view.
  NS       INODE          ISOLATED  WHAT IT CONTROLS
  mnt      4026533908     private*  the filesystem tree: what / looks like
  pid      4026533911     private   the process table: who exists, and who is PID 1
  net      4026534032     private*  interfaces, routes, ports: your own 0.0.0.0:8080
  ipc      4026533910     private   System V IPC and POSIX message queues
  uts      4026533909     private   hostname and domain name
  user     4026531837     SHARED    uid/gid mapping: whether root here is root out there
  cgroup   4026533912     private   where the cgroup tree appears to be rooted
  time     4026534160     private   CLOCK_MONOTONIC and CLOCK_BOOTTIME offsets
  -> 7 namespaces private to this process, 1 shared with the host.
  the SHARED one is 'user': there is no uid remapping here, so uid 0
  inside this container is uid 0 on the host kernel. That is why a
  container escape is a root escape, and why rootless runtimes exist.

  -- what the kernel says about your cgroup --
  /proc/self/cgroup       0::/
  /sys/fs/cgroup mounted ro,nosuid,nodev,noexec,relatime
    read-only: this process can READ its limits and cannot RAISE them.

  -- cgroup v2 interface files (/sys/fs/cgroup) --
  cgroup.controllers       cpuset cpu io memory hugetlb pids rdma
  cpu.max                  max 100000
  cpuset.cpus.effective    0-9
  memory.max               max
  memory.current           18440192 (17.6 MiB)
  pids.max                 max
  cpu.stat nr_throttled=0 throttled_usec=0
    nr_throttled is THE container metric nobody graphs.

  /proc/meminfo MemTotal   7.75 GiB   <- the HOST's RAM, not yours
  cgroup memory.max        max
    ... /proc/meminfo is not namespaced, so a runtime that sizes a
    heap or a cache from it reads the host's RAM and gets OOM-killed.

== 2 · THE CPU-COUNT TRAP: WHAT THREE APIs REPORT, AND WHICH ONE IS TRUE ==
  os.cpu_count()          10          the machine's CPUs. Never your limit.
  os.sched_getaffinity(0) 10          CPUs you may be SCHEDULED on (cpuset)
  /sys/fs/cgroup/cpu.max  max 100000  the CFS bandwidth quota you are held to
  every runtime's default pool size reads the FIRST line and ignores the rest.

  -- imposing a real limit: sched_setaffinity to 2 CPUs --
  (identical to `docker run --cpuset-cpus=0,1`; inherited by every child)
  after the call: os.cpu_count()=10  sched_getaffinity=2  <- they now DISAGREE

  identical work both times: 24 tasks x 900k-iteration LCG walk, through a
  process pool. The ONLY difference is how the pool was sized. Each row is
  the BEST of 5 trials.
  pool sized from           workers       wall  throughput   1st result  worker RSS
  cgroup/cpuset budget            2     1254ms    19.15/s        119ms      23.3MB
  os.cpu_count()                 10     1730ms    13.87/s        748ms     117.0MB

  oversubscription        5.0x        10 workers sharing 2 CPUs
  throughput              19.15/s -> 13.87/s   (-28%)
     Never better, usually slightly worse, and the exact figure moves with
     host load. That is the whole point: the CPUs are the CPUs.
  time to FIRST answer    119 ms -> 748 ms   (6.3x worse)
  worker memory           23.3 MB -> 117.0 MB  (5.0x)
     under a memory.max this pool is the difference between running
     and being SIGKILLed by the kernel with no stack trace.

  -- MODEL (not a measurement): what cpu.max does that cpuset does not --
  threads W  quota spent in   then stalled      added p99
  2                 100.0 ms          0.0 ms          0.0 ms
  4                  50.0 ms         50.0 ms         50.0 ms
  8                  25.0 ms         75.0 ms         75.0 ms
  10                 20.0 ms         80.0 ms         80.0 ms
  16                 12.5 ms         87.5 ms         87.5 ms
  32                  6.2 ms         93.8 ms         93.8 ms
  at W = 2 (= the quota) there is no stall at all. At W = 32 the cgroup is
  frozen for 94 ms out of every 100 ms period. This is the mechanism behind
  'our p99 is 100 ms and we cannot find the slow query'.

== 3 · THE COST OF A FRESH ISOLATE RISES BY AN ORDER OF MAGNITUDE PER RUNG ==
  isolate                    create       memory  what it still SHARES
  thread                    0.086 ms        16 KB  address space, fds, kernel, interpreter
  fork() child              1.560 ms      7885 KB  fds and kernel; pages are copy-on-write
  fresh interpreter         7.655 ms      5276 KB  the kernel, and the binary's file pages

  measured step-ups in creation cost on this machine:
    thread -> fork()              18.1x slower
    fork() -> new interpreter      4.9x slower
    thread -> new interpreter     88.8x slower
  memory: 16 KB -> 5276 KB is 330x from a thread to a private address space.
  On memory alone that is ~65,634 threads or ~198 fresh interpreters per GiB.

  -- the rungs above this, quoted not measured --
  A container start adds an image pull (if cold), namespace and cgroup
  setup, and a full process tree: tens to hundreds of ms.
  A VM boot adds firmware, a kernel, and a userland init sequence:
  seconds to tens of seconds for a general-purpose hypervisor.
  proof: unshare(CLONE_NEWNS) -> errno 1 (Operation not permitted).
  We are uid 0 inside this container and still cannot create a
  namespace, because the runtime dropped CAP_SYS_ADMIN.

== 4 · THE ECONOMICS OF IDLE (a model, with the prices printed) ==
  one weekday of real traffic: peak 1180 req/s, trough 38 req/s (31x), 52,264,800 requests

  provisioned for peak: 8 instances, always on
    capacity            138,240,000 requests/day
    delivered           52,264,800 requests/day
    utilisation         37.8%  -> you paid for 62.2% of nothing
    cost                $7.99/day   $2915/year
  scale-to-zero, billed per invocation
    unit cost           $0.000001033 per request
    cost                $54.01/day   $19713/year
    -> always-on is cheaper today, by $46.02/day ($16797/year)

  crossover: always-on wins once utilisation exceeds 5.6%
  utilisation     always-on/day per-invoke/day     winner
  5.0%                    7.99           7.14 per-invoke
  5.6% <-                 7.99           7.99  crossover
  10.0%                   7.99          14.28  always-on
  100.0%                  7.99         142.85  always-on

  (total wall time 18.8 s)
```

## Use It

### The rungs, as products

| Rung | AWS | Google Cloud | Azure | You operate |
|---|---|---|---|---|
| **Bare metal** | EC2 Bare Metal (`*.metal`) | Bare Metal Solution | Azure Dedicated Host | the kernel and everything above it |
| **VM** | EC2 (Elastic Compute Cloud) | Compute Engine | Virtual Machines | the guest OS, the runtime, the app |
| **Container, no cluster to run** | ECS on Fargate, App Runner | Cloud Run | Container Apps | the image and its config |
| **Container, your own cluster** | EKS | GKE | AKS | the cluster, node pools, upgrades, the app |
| **Serverless / FaaS** | Lambda | Cloud Functions | Azure Functions | the handler and its config |
| **Managed data services** | RDS, ElastiCache, MSK | Cloud SQL, Memorystore | Azure Database, Cache | schemas, queries, capacity choices |

The row that most teams should read twice is the fourth. Kubernetes (lesson 7 of this phase) is a superb answer to "we have many services, many teams, and enough people to run a platform." It is an expensive answer to "we have one service." **The managed container rungs — Fargate, Cloud Run, Container Apps — take the same image and ask for a fraction of the operational surface**, and they are where a small team should start unless something specific pushes them off.

### The knobs that set the numbers the script read

Everything measured above traces back to two flags:

```bash
# Docker: --cpus writes cpu.max; --cpuset-cpus writes cpuset.cpus; -m writes memory.max
docker run --cpus=2 --memory=1g --memory-swap=1g myimage
docker run --cpuset-cpus=0,1 --memory=1g myimage       # pin to specific cores instead

# Read back exactly what the script read, from inside the container:
docker run --cpus=2 --memory=1g --rm myimage \
  sh -c 'cat /sys/fs/cgroup/cpu.max /sys/fs/cgroup/memory.max'
# 200000 100000
# 1073741824
```

And in Kubernetes, the same two cgroup values come from `resources` (Kubernetes API reference, `ResourceRequirements`):

```yaml
resources:
  requests:                 # what the SCHEDULER reserves for you on a node
    cpu: "500m"             # 0.5 CPU. Sum of requests <= node capacity.
    memory: "512Mi"
  limits:                   # what the KERNEL enforces via cgroups
    cpu: "2"                # -> cpu.max = "200000 100000"  (CFS throttling)
    memory: "1Gi"           # -> memory.max = 1073741824    (OOM kill)
```

The two halves do genuinely different jobs and this is the most common misconfiguration in the ecosystem:

- **`requests` is a scheduling promise.** It decides which node you land on and how much capacity is reserved. Set it too low and the scheduler packs your pod onto a node with nothing left, and you are throttled from the first second. Omit it and you may inherit a namespace default, or nothing.
- **`limits` is a kernel ceiling.** Exceeding a CPU limit gets you **throttled** — the frozen-for-94-ms behaviour modelled above. Exceeding a memory limit gets you **killed**, immediately, because there is no way to "throttle" memory. Same mechanism as the `memory.max` in the script's output.
- **`requests` without `limits`** means you can burst into other tenants' capacity — pleasant until a neighbour needs it and your latency collapses without any change on your side.
- **`limits` without `requests`**: on Kubernetes, setting only limits causes requests to default to the limits, which quietly reserves your ceiling and wastes capacity across the fleet.

### Reading your own limits at startup

Rather than trusting a default, read the quota and size from it. This is the whole fix, in a dozen lines:

```python
import os

def effective_cpus() -> float:
    """The CPU budget this process actually has. Checks all three sources."""
    quota = None
    try:                                      # cgroup v2 bandwidth quota
        raw = open("/sys/fs/cgroup/cpu.max").read().split()
        if raw[0] != "max":
            quota = int(raw[0]) / int(raw[1])
    except OSError:
        pass
    try:                                      # cgroup v1, still common
        q = int(open("/sys/fs/cgroup/cpu/cpu.cfs_quota_us").read())
        p = int(open("/sys/fs/cgroup/cpu/cpu.cfs_period_us").read())
        if q > 0:
            quota = min(quota or 1e9, q / p)
    except OSError:
        pass
    cpuset = len(os.sched_getaffinity(0))     # which cores, not how much time
    return max(1.0, min(quota or 1e9, cpuset))

WORKERS = max(1, int(effective_cpus()))       # never os.cpu_count()
```

Log the result at startup, on one line, next to the value `os.cpu_count()` returned. When the two disagree, you want that in the logs of the deploy that introduced the disagreement — not discovered six weeks later from a latency graph. Newer runtimes have started doing this for you: modern JVMs read cgroup limits by default (`UseContainerSupport`), .NET reads them, and Go's `GOMAXPROCS` still defaults to the machine's core count unless you set it. **Check yours; do not assume.** Then size the pool from a *measurement of your workload*, not from the CPU count at all — [Thread Pools, Work Queues & Executors](../../08-concurrency-and-performance/07-thread-pools-and-work-queues/) is the treatment of why an I/O-bound pool and a CPU-bound pool want completely different numbers.

### Rules that survive contact with production

- **Set requests AND limits, on every container, always.** Requests decide where you land; limits decide how you die. Missing either one is a decision you did not make.
- **Size every pool from the quota, never from `os.cpu_count()`.** And log both at startup so the disagreement is visible on the day it appears.
- **Graph `container_cpu_cfs_throttled_periods_total` / `nr_throttled` next to your p99.** Unexplained tail latency in a CPU-limited container is throttling until proven otherwise. See [Health Checks & Probes](../../09-logging-monitoring-and-observability/08-health-checks-and-probes/) for the related failure where a throttled process fails its own liveness probe and gets restarted for being throttled.
- **Memory limits kill; CPU limits throttle.** Set memory limits with real headroom over your measured peak RSS, and remember the kill leaves no application-level trace — check exit code 137 and the kernel log, not your logs.
- **Know your AZ topology.** Confirm that "three replicas" is actually three availability zones, and that your data layer's failover across them has been *tested*, not assumed.
- **Know who patches your kernel.** On a VM it is you. On managed containers and serverless it is the provider. On your own Kubernetes nodes it is you, on a schedule you must actually keep, and "we run containers so the kernel is someone else's problem" is precisely backwards.
- **Do not size the rung by fashion.** Write down the six factors, put your numbers in them, and let the crossover arithmetic tell you what you can afford. Then rerun it when your traffic changes by an order of magnitude.

## Think about it

1. `os.cpu_count()` returns 64 and your CPU limit is 2. You fix the pool size and the p99 improves, but `nr_throttled` is still climbing. What else in a typical Python or JVM service creates threads without asking you, and how would you find them from inside a running container?
2. A `memory.max` breach kills your process instantly with SIGKILL; a CPU limit only throttles. Why can the kernel not "throttle" memory the way it throttles CPU — and what does that asymmetry imply about how you should choose the two limits relative to your measured peaks?
3. The idle model found always-on cheaper by 6.8× for a workload with a 31× peak-to-trough ratio. Construct a realistic workload where the answer flips, and state which single input you changed. Then say what would have to be true about your *team* for the cheaper option to still be the wrong choice.
4. A kernel vulnerability crosses container boundaries and not VM boundaries. Given that, argue both sides of running two customers' untrusted code as two containers on one host — and then explain what serverless providers do instead, and what it costs them.
5. The script proved it is inside 7 private namespaces and could still not create an eighth, because `CAP_SYS_ADMIN` was dropped. If you were designing the runtime, which capabilities would you keep for a normal web service, and what breaks first when you drop too many?

## Key takeaways

- **A VM virtualizes hardware and brings its own kernel; a container shares the host kernel and virtualizes only the view.** That one sentence explains the whole ladder: seconds versus **10-100 ms** to start, tens versus hundreds of isolates per host, and why a kernel vulnerability crosses container boundaries but not VM boundaries. The measured proof of the boundary from inside: **7 namespaces private, 1 (`user`) shared with the host**, so uid 0 in the container is uid 0 on the host kernel.
- **`os.cpu_count()` reports the machine and is never your limit.** Measured here, `os.cpu_count()` said **10** while the process was held to **2** CPUs. A pool sized from the first number ran **5.0× oversubscribed**, took **6.3× longer to return its first answer (119 ms → 748 ms)**, held **5.0× the memory (23.3 MB → 117.0 MB)** and delivered **no extra throughput** — it measured 28% *less*. Read `cpu.max` and `sched_getaffinity`, size from those, log both at startup.
- **A CPU limit throttles and a memory limit kills.** With a 2-CPU quota and 32 runnable threads the cgroup burns its quota in 6.2 ms and is then **frozen for 93.8 ms of every 100 ms period** — invisible in CPU utilisation, visible only in `cpu.stat`'s **`nr_throttled`**, the container metric nobody graphs. A `memory.max` breach is a SIGKILL with no stack trace.
- **Isolation costs about an order of magnitude per rung.** Measured: a thread costs **0.086 ms and 16 KB**, a `fork()` **1.560 ms** (18.1× slower), a fresh interpreter **7.655 ms** (88.8× slower than a thread) — **~65,634 threads or ~198 interpreters per GiB.** A container adds tens to hundreds of ms on top; a VM adds seconds, or ~**125 ms** for a stripped microVM, which is the answer to "VMs are slow".
- **The availability zone is the unit of correlated failure**, and it is the only unit your provider makes availability commitments about. Anything that must survive one infrastructure failure lives in at least two AZs, with a failover that has been tested rather than assumed.
- **Idle cost is arithmetic, not taste.** For the modelled prices, a real weekday curve with a **31× peak-to-trough ratio** and **62.2% of its capacity idle** still made always-on cheaper — **$7.99/day against $54.01/day, a gap of $46.02** — because the crossover sits at just **5.6% utilisation**. The case for scale-to-zero is *low or intermittent* traffic, not spiky traffic; and the biggest cost the model omits is the engineer-hours of operating whichever rung you pick.

Next: [What a Container Actually Is: Namespaces, cgroups & Layers](../02-what-a-container-actually-is/) — you have now read your own namespace inodes and cgroup files from the outside of the abstraction; the next lesson opens it up and builds each of those primitives by hand.
