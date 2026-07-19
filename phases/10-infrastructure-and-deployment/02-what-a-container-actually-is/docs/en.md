# What a Container Actually Is: Namespaces, cgroups & Layers

> There is no "container" object in Linux. There is a process, and the kernel tells it three lies — about what it can see, what it may use, and what its disk is. Measured here from inside one: **41,943,040 bytes copied to change a single byte** of a file that lives in an image layer; **14 of 41 capabilities held**, so every one of six `unshare()` calls fails with EPERM even as root; **65.9 MB of page cache billed to a cgroup** whose heap never grew; and a process that ignores `SIGTERM` burning the entire grace period before dying to `SIGKILL` with **8 in-flight requests severed** and nothing in the error rate to show for it.

**Type:** Build
**Languages:** Python
**Prerequisites:** [Where Code Actually Runs](../01-where-code-actually-runs/), [How a Computer Runs a Program](../../00-foundations/09-how-a-computer-runs-a-program/)
**Time:** ~90 minutes

## The Problem

It is 09:40 on a Tuesday and you are watching a routine rolling update replace 40 pods of a checkout service. The deploy is green. Every new pod passes its readiness probe. The dashboard shows no elevated error rate — 0.02%, same as yesterday.

Support opens a ticket forty minutes later. Fourteen customers report that the payment page "hung and then said the connection was lost." Nobody can reproduce it. Your logs contain no errors for those users, no 500s, no timeouts. The last line for each of them is the request being *accepted*.

Here is what actually happened, once per pod, forty times.

**T+0.** The orchestrator sends `SIGTERM` to your container. This is the polite request: *finish up, you are being replaced.* Your application is a Python process started as the container's entrypoint, so it is **PID 1** inside its own process-id namespace.

**T+0, still.** Nothing happens. Not "the process ignored it and carried on for a while" — nothing at all, in the kernel. **PID 1 does not get default signal handlers.** For every other process on the system, a signal with no handler installed triggers a default action defined by POSIX, and `SIGTERM`'s default action is *terminate*. For PID 1 of a namespace the kernel skips that step entirely: a signal with no registered handler is **discarded** (`pid_namespaces(7)`). Your process was never told anything.

**T+0 to T+30.** The pod's endpoint has already been removed from the service, but your process does not know it is dying, so it keeps doing what it does: accepting new connections and serving them. It is now a pod that the control plane has deleted, is not in any load balancer, and is still admitting work. Every request it accepts in this window is a request it will never finish.

**T+30.** The grace period expires. `SIGKILL` — the one signal that cannot be caught, blocked, or ignored. The process is removed from the run queue mid-syscall. Every socket it held is closed by the kernel with a TCP RST.

**And this is why your dashboards are clean.** A severed connection is not a 500. Your process never generated a response, so your HTTP middleware never recorded one. Your error rate is computed from responses you sent, and you sent nothing. The failure exists only in the client's telemetry — and the client is a browser on somebody's phone. In this lesson's Build It, that pattern severs **8 in-flight requests per pod**; at 40 pods and 12 deploys a day it is **3,840 dropped connections a day** that no server-side metric will ever show you.

Now the second bug, which has the same root cause: not knowing what the box actually is.

The same service gets OOM-killed twice a week. Exit code **137** — that is 128 + 9, the shell's convention for "killed by signal 9". You set `--memory 512m`. You attach a Python memory profiler and it insists the heap peaks at 180 MB. You raise the limit to 768 MB. It still happens, just less often, and always during the nightly job that streams a few gigabytes of CSV through the service.

The profiler is not lying and neither is the kernel. They are measuring different things, and the thing that kills you is the one the profiler cannot see. This lesson measures it directly: writing and reading back a 64 MB file grew `memory.current` by **65.9 MB — 103% of the file** — while the Python heap did not move at all. **Page cache is charged to your cgroup.** Your memory limit is not a limit on your heap. It is a limit on everything the kernel has billed to you, including file pages it decided to cache on your behalf.

Both bugs come from the same mental model: *a container is a small, lightweight virtual machine.* It is not. It is not a machine at all. By the end of this lesson you will have read your own container's namespaces, watched root fail to create one, built an overlay filesystem by hand and measured what it costs, parsed your own resource limits out of `/sys/fs/cgroup`, and made zombies appear and disappear on demand.

## The Concept

### There is no "container" object in Linux

Search the Linux kernel source for a `struct container`. There isn't one. There is no container system call, no container object, no container subsystem.

What exists is an ordinary process, plus a handful of unrelated kernel features that a **container runtime** (the program that starts containers — `containerd`, `runc`, `crun`) configures on that process at the moment it starts. Take those features away one at a time and at no point does the thing "stop being a container" — it just gradually becomes an ordinary process again, which is all it ever was.

That is the whole idea, and everything else in this lesson is detail:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 470" width="100%" style="max-width:840px" role="img" aria-label="A container drawn as one ordinary process surrounded by three kernel lies: namespaces control what it can see, cgroups control what it may use, and a stack of read-only image layers plus one writable upper layer control what it thinks its disk is. Underneath, a single shared host kernel is drawn in red because every container on the machine calls into that same kernel, which is the blast radius a container does not isolate.">
  <defs>
    <marker id="l02-a1" markerWidth="10" markerHeight="10" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker>
  </defs>
  <text x="440" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">A container is a process the kernel tells three lies to</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">

    <rect x="330" y="176" width="220" height="96" rx="12" fill="#3553ff" fill-opacity="0.14" stroke="#3553ff" stroke-width="2.2"/>
    <text x="440" y="206" font-size="13" font-weight="700" text-anchor="middle" fill="#3553ff">ONE ORDINARY</text>
    <text x="440" y="224" font-size="13" font-weight="700" text-anchor="middle" fill="#3553ff">LINUX PROCESS</text>
    <text x="440" y="245" font-size="9.5" text-anchor="middle" fill="currentColor" opacity="0.9">pid 1 in its namespace</text>
    <text x="440" y="259" font-size="9.5" text-anchor="middle" fill="currentColor" opacity="0.9">uid 0, 14 of 41 capabilities</text>

    <rect x="24" y="56" width="266" height="150" rx="11" fill="#7c5cff" fill-opacity="0.12" stroke="#7c5cff" stroke-width="2"/>
    <text x="40" y="80" font-size="11.5" font-weight="700" fill="#7c5cff">LIE 1 · NAMESPACES</text>
    <text x="40" y="96" font-size="9.5" fill="currentColor" opacity="0.85">what it can SEE</text>
    <g fill="currentColor" font-size="9.5">
      <text x="40" y="116">mnt</text><text x="96" y="116" opacity="0.8">the mount table</text>
      <text x="40" y="131">pid</text><text x="96" y="131" opacity="0.8">who else exists</text>
      <text x="40" y="146">net</text><text x="96" y="146" opacity="0.8">interfaces, ports</text>
      <text x="40" y="161">ipc uts</text><text x="96" y="161" opacity="0.8">queues, hostname</text>
      <text x="40" y="176">user</text><text x="96" y="176" opacity="0.8">what root means</text>
      <text x="40" y="191">cgroup time</text><text x="150" y="191" opacity="0.8">tree root, clocks</text>
    </g>

    <rect x="590" y="56" width="266" height="150" rx="11" fill="#0fa07f" fill-opacity="0.12" stroke="#0fa07f" stroke-width="2"/>
    <text x="606" y="80" font-size="11.5" font-weight="700" fill="#0fa07f">LIE 2 · CGROUPS v2</text>
    <text x="606" y="96" font-size="9.5" fill="currentColor" opacity="0.85">what it may USE</text>
    <g fill="currentColor" font-size="9.5">
      <text x="606" y="116">cpu.max</text><text x="700" y="116" opacity="0.8">quota per 100 ms</text>
      <text x="606" y="131">memory.max</text><text x="700" y="131" opacity="0.8">a hard ceiling</text>
      <text x="606" y="146">pids.max</text><text x="700" y="146" opacity="0.8">the fork-bomb fuse</text>
      <text x="606" y="161">io.max</text><text x="700" y="161" opacity="0.8">bytes/s and IOPS</text>
    </g>
    <text x="606" y="182" font-size="9.5" font-weight="700" fill="#e0930f">over cpu.max  -&gt; THROTTLED</text>
    <text x="606" y="196" font-size="9.5" font-weight="700" fill="#d64545">over memory.max -&gt; KILLED</text>

    <rect x="24" y="238" width="266" height="150" rx="11" fill="#7c5cff" fill-opacity="0.12" stroke="#7c5cff" stroke-width="2"/>
    <text x="40" y="262" font-size="11.5" font-weight="700" fill="#7c5cff">LIE 3 · LAYERED ROOTFS</text>
    <text x="40" y="278" font-size="9.5" fill="currentColor" opacity="0.85">what it thinks its DISK is</text>
    <g stroke-width="1.6">
      <rect x="40" y="290" width="234" height="20" rx="5" fill="#0fa07f" fill-opacity="0.20" stroke="#0fa07f"/>
      <rect x="40" y="314" width="234" height="17" rx="5" fill="#7c5cff" fill-opacity="0.20" stroke="#7c5cff"/>
      <rect x="40" y="335" width="234" height="17" rx="5" fill="#7c5cff" fill-opacity="0.20" stroke="#7c5cff"/>
      <rect x="40" y="356" width="234" height="17" rx="5" fill="#7c5cff" fill-opacity="0.20" stroke="#7c5cff"/>
    </g>
    <text x="52" y="304" font-size="9.5" font-weight="700" fill="currentColor">upper — writable, PRIVATE</text>
    <text x="52" y="326" font-size="9" fill="currentColor" opacity="0.9">lower[0] app code</text>
    <text x="52" y="347" font-size="9" fill="currentColor" opacity="0.9">lower[1] dependencies</text>
    <text x="52" y="368" font-size="9" fill="currentColor" opacity="0.9">lower[2] base OS — read-only, SHARED</text>

    <rect x="590" y="238" width="266" height="150" rx="11" fill="#e0930f" fill-opacity="0.12" stroke="#e0930f" stroke-width="2"/>
    <text x="606" y="262" font-size="11.5" font-weight="700" fill="#e0930f">THE FOURTH THING</text>
    <text x="606" y="278" font-size="9.5" fill="currentColor" opacity="0.85">CAPABILITIES — what root means</text>
    <g fill="currentColor" font-size="9.5">
      <text x="606" y="300">root inside != root outside.</text>
      <text x="606" y="315">uid 0 with a REDUCED set:</text>
      <text x="606" y="333" font-weight="700" fill="#0fa07f">measured: 14 of 41 held</text>
      <text x="606" y="348" font-weight="700" fill="#d64545">CAP_SYS_ADMIN: DROPPED</text>
      <text x="606" y="366" opacity="0.85">so unshare() = EPERM,</text>
      <text x="606" y="380" opacity="0.85">and --privileged undoes it all</text>
    </g>

    <g fill="none" stroke="currentColor" stroke-width="1.6" opacity="0.7">
      <path d="M290 130 L 324 190" marker-end="url(#l02-a1)"/>
      <path d="M590 130 L 556 190" marker-end="url(#l02-a1)"/>
      <path d="M290 300 L 324 256" marker-end="url(#l02-a1)"/>
      <path d="M590 300 L 556 256" marker-end="url(#l02-a1)"/>
    </g>

    <rect x="24" y="404" width="832" height="40" rx="9" fill="#d64545" fill-opacity="0.13" stroke="#d64545" stroke-width="2"/>
    <text x="440" y="421" font-size="11.5" font-weight="700" text-anchor="middle" fill="#d64545">ONE SHARED HOST KERNEL — every container on the machine calls into this exact code</text>
    <text x="440" y="436" font-size="9.5" text-anchor="middle" fill="currentColor" opacity="0.9">not virtualised, not duplicated, not isolated. a kernel bug here is every container's bug.</text>

    <text x="440" y="462" font-size="11" text-anchor="middle" fill="currentColor" opacity="0.9">There is no "container" object in Linux. Remove all four and you are left with a process — which is all it ever was.</text>
  </g>
</svg>
```

The red bar is the part that separates a container from a virtual machine, and it is worth being blunt about. A VM (virtual machine) runs its own kernel on virtualised hardware; a hypervisor bug is the only way out. A container calls into the **same kernel as everything else on the host** — the same 30-million-line C program, on the same hardware, with the same bugs. Lesson 1 compared the isolation boundaries; this is the mechanical reason the container's is thinner. Every syscall your container makes is a syscall the host kernel executes.

### Namespaces — what the process can see

A **namespace** wraps a global system resource so that processes inside it see their own private instance of it. Linux has eight kinds, and each hides exactly one thing:

- **mnt** — the mount table. Inside, `/` is your image, not the host's root filesystem. The host's disks are simply not in the table.
- **pid** — the process-id number space. Your process is PID 1 and cannot see, signal, or `/proc`-inspect anything outside. This is why `ps aux` in a container shows three processes on a machine running four hundred.
- **net** — network interfaces, addresses, routing tables, port numbers, firewall rules. Two containers can both bind port 8080 because those are two different port 8080s.
- **ipc** — System V IPC objects and POSIX message queues.
- **uts** — the hostname and NIS domain name. (UTS = UNIX Time-sharing System, a historical name for the kernel struct.) This is why your container's hostname is a short hex string.
- **user** — the uid/gid mapping. This is the deep one: it lets uid 0 *inside* map to unprivileged uid 165536 *outside*, which is the foundation of rootless containers.
- **cgroup** — where the cgroup tree appears to be rooted, so a container cannot see the host's resource hierarchy.
- **time** — the offsets for `CLOCK_MONOTONIC` and `CLOCK_BOOTTIME`, so a checkpointed and restored container can keep a consistent uptime.

A namespace has no name. Its identity is an **inode number** on a special filesystem, exposed as a symlink at `/proc/<pid>/ns/<kind>`. Two processes are in the same namespace if and only if those numbers are equal — which makes "are these two things isolated from each other?" a question you can answer with `readlink` and string equality. The Build It prints all eight for the running process.

The critical thing to internalise: **`fork()` does not create namespaces.** A child inherits every one of its parent's. The Build It forks a child and confirms it shares **8 of 8**. Creating a container means calling `clone()` with `CLONE_NEW*` flags (or `unshare()` afterwards), which produces *fresh* ids for the kinds you asked for and keeps the parent's for the rest. That selectivity is the point, and it is used constantly: a Kubernetes Pod is a group of containers that share a **net** and **ipc** namespace while keeping separate **mnt** namespaces, which is exactly why two containers in one Pod reach each other on `localhost` but cannot see each other's files.

### cgroups v2 — what the process may use

Namespaces control visibility. They control *nothing* about resource consumption: a process alone in its own eight namespaces can still consume every core and every byte of RAM on the host. Limits come from an entirely separate subsystem, **cgroups** (control groups), now in its second major version. The two are independent kernel features that a runtime happens to configure together.

cgroup v2 is a filesystem. Your container's limits are text files under `/sys/fs/cgroup`, and you can read them right now:

| file | what it governs |
|---|---|
| `cgroup.controllers` | which controllers are available here (measured: `cpuset cpu io memory hugetlb pids rdma`) |
| `memory.max` | hard memory ceiling. Exceed it and the OOM killer fires |
| `memory.high` | soft ceiling — the kernel throttles and reclaims instead of killing |
| `memory.current` | bytes charged to this cgroup right now |
| `memory.peak` | high-water mark, the number to size a limit from |
| `cpu.max` | `QUOTA PERIOD` in microseconds — you get QUOTA of CPU time per PERIOD |
| `cpu.stat` | usage, and the throttling counters that matter |
| `pids.max` | process and thread ceiling — the fork-bomb fuse |
| `io.max` | per-device bytes/second and IOPS ceilings |

`cpu.max` deserves decoding because its format confuses people. `--cpus 1.5` writes `150000 100000`: **150,000 microseconds of CPU time in every 100,000-microsecond window**, summed across all your threads. Four threads on a 4-core box will exhaust that in 37.5 ms of wall time and then get nothing for the remaining 62.5 ms.

And now the distinction that this whole section exists for, because **the two limits fail in completely different ways**:

> **Exceed `cpu.max` and you are throttled. Exceed `memory.max` and you are killed.**

CPU is a **rate**, and a rate can be slowed. When you exhaust your quota the scheduler simply stops running your threads until the next period opens. From inside the container this produces **no error, no exception, no log line** — just latency. Your p99 grows a step and nothing anywhere says why. The evidence lives in `cpu.stat`: `nr_throttled` counts the periods in which you were stopped and `throttled_usec` totals the microseconds lost. (This sandbox runs unlimited, so it honestly reads `nr_throttled=0`.) **A rising `nr_throttled` on a service with a latency complaint and idle-looking CPU graphs is one of the highest-value signals in container operations,** and almost nobody graphs it.

Memory is a **level**, and a level cannot be slowed — the bytes are either there or they are not. When you cross `memory.max` the kernel first tries to reclaim, and when it cannot reclaim fast enough the OOM (out-of-memory) killer picks a process in your cgroup and sends `SIGKILL`. Uncatchable. No handler, no drain, no flush, no stack trace, no log line from your process — because your process was not consulted. You get exit code **137** and nothing else.

The asymmetry gives you two rules. **Always set a memory limit** — an unlimited container that leaks takes the whole node down with it, including its neighbours. And **be much more careful with CPU limits than you expect**, because a too-tight CPU limit produces latency that looks exactly like a slow dependency and shows up in none of your application's own instrumentation.

There is a third trap here and it is the one from The Problem. **Page cache is charged to your cgroup.** When your process reads or writes a file, the kernel caches those pages and bills them to you. The Build It writes and reads back a 64 MB file and watches `memory.current` climb by **65.9 MB — 103% of the file size** — while the Python heap does not move. That cache is reclaimable, so the kernel drops it under pressure rather than killing you, which is why this is a *usually* invisible problem. But under a burst it cannot always reclaim fast enough, and then a service whose heap peaks at 180 MB dies at a 512 MB limit while streaming CSVs, and the profiler shows nothing. If your service touches large files, **size the limit from `memory.peak` under real load, not from your heap profiler.**

### The layered root filesystem — what the process thinks its disk is

The third lie is the one with the most operational consequence, and the direct set-up for the next lesson.

A container's root filesystem is not a copy of an image. It is a **union mount**: an ordered stack of read-only directories (the image's **layers**) with exactly one writable directory on top. Linux's implementation is **overlayfs** (kernel `Documentation/filesystems/overlayfs.rst`), and its vocabulary is worth learning precisely:

- **lowerdir** — an ordered list of read-only layers. Searched top-down; the first match wins.
- **upperdir** — the single writable layer. Private to this container, created empty when it starts.
- **workdir** — an empty staging directory overlayfs needs on the same filesystem as `upperdir` to make copy-ups atomic.
- **merged** — the unified view, which is what the process actually sees at `/`.

This is not an analogy for how containers work; it is literally how the container running this lesson's code works. Reading `/proc/self/mountinfo` shows its own root as an overlay with **8 lower layers** stacked under one writable upper layer. Every one of those 8 is shared, read-only, with every other container started from the same image — which is the entire reason a container starts in milliseconds and 50 containers from one image do not cost 50 copies of it.

Three operations define the behaviour, and each has a consequence people meet in production without recognising it:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 512" width="100%" style="max-width:840px" role="img" aria-label="The three overlay filesystem operations drawn over a five layer stack. A read walks down from the writable upper layer through the lower layers and stops at the first match. A write to a file that lives in a lower layer must first copy the entire file up into the writable layer, measured here at forty one million nine hundred forty three thousand and forty bytes moved to change one byte. A delete cannot touch a read-only lower layer, so it writes a whiteout marker in the upper layer that hides the file from the merged view while it remains on disk below.">
  <defs>
    <marker id="l02-a2" markerWidth="9" markerHeight="9" refX="5.5" refY="3" orient="auto"><path d="M0,0 L6.5,3 L0,6 Z" fill="currentColor"/></marker>
    <marker id="l02-a2r" markerWidth="9" markerHeight="9" refX="5.5" refY="3" orient="auto"><path d="M0,0 L6.5,3 L0,6 Z" fill="#d64545"/></marker>
    <marker id="l02-a2o" markerWidth="9" markerHeight="9" refX="5.5" refY="3" orient="auto"><path d="M0,0 L6.5,3 L0,6 Z" fill="#e0930f"/></marker>
  </defs>
  <text x="440" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">Overlay: read walks down, write copies up, delete masks</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">

    <text x="40" y="58" font-size="9" font-weight="700" fill="currentColor" opacity="0.65">THE LAYER STACK</text>
    <g stroke-width="2">
      <rect x="34" y="68" width="270" height="46" rx="8" fill="#0fa07f" fill-opacity="0.14" stroke="#0fa07f"/>
      <rect x="34" y="128" width="270" height="40" rx="8" fill="#7c5cff" fill-opacity="0.13" stroke="#7c5cff"/>
      <rect x="34" y="178" width="270" height="40" rx="8" fill="#7c5cff" fill-opacity="0.13" stroke="#7c5cff"/>
      <rect x="34" y="228" width="270" height="40" rx="8" fill="#7c5cff" fill-opacity="0.13" stroke="#7c5cff"/>
      <rect x="34" y="278" width="270" height="40" rx="8" fill="#7c5cff" fill-opacity="0.13" stroke="#7c5cff"/>
    </g>
    <g fill="currentColor">
      <text x="46" y="87" font-size="10.5" font-weight="700" fill="#0fa07f">upper — WRITABLE</text>
      <text x="46" y="103" font-size="9" opacity="0.9">private, empty at start</text>
      <text x="46" y="145" font-size="10" font-weight="700">lower[0]  app</text>
      <text x="46" y="159" font-size="9" opacity="0.85">app.py  config.yaml</text>
      <text x="46" y="195" font-size="10" font-weight="700">lower[1]  vendor-deps</text>
      <text x="46" y="209" font-size="9" opacity="0.85">vendor-bundle.bin  40 MB</text>
      <text x="46" y="245" font-size="10" font-weight="700">lower[2]  runtime</text>
      <text x="46" y="259" font-size="9" opacity="0.85">python3.12  os-release</text>
      <text x="46" y="295" font-size="10" font-weight="700">lower[3]  base OS</text>
      <text x="46" y="309" font-size="9" opacity="0.85">libc.so  os-release</text>
    </g>
    <text x="34" y="336" font-size="8.5" fill="currentColor" opacity="0.75">upper: 1 per container.  lower: shared,</text>
    <text x="34" y="348" font-size="8.5" fill="currentColor" opacity="0.75">read-only, immutable, deduplicated.</text>

    <rect x="384" y="56" width="472" height="118" rx="10" fill="#3553ff" fill-opacity="0.08" stroke="#3553ff" stroke-width="1.8"/>
    <text x="400" y="76" font-size="11" font-weight="700" fill="#3553ff">1 · READ   open("os-release")</text>
    <path d="M404 86 L 404 130" fill="none" stroke="currentColor" stroke-width="1.7" marker-end="url(#l02-a2)" opacity="0.8"/>
    <g fill="currentColor" font-size="9.5">
      <text x="422" y="96">upper?     miss</text>
      <text x="422" y="112">lower[0]?  miss</text>
      <text x="422" y="128">lower[1]?  miss</text>
      <text x="422" y="144" font-weight="700" fill="#0fa07f">lower[2]?  HIT — stop here</text>
      <text x="400" y="164" font-size="9" opacity="0.85">lower[3] has os-release too: shadowed, still on disk, still paid for.</text>
    </g>

    <rect x="384" y="186" width="472" height="160" rx="10" fill="#e0930f" fill-opacity="0.10" stroke="#e0930f" stroke-width="1.8"/>
    <text x="400" y="206" font-size="11" font-weight="700" fill="#e0930f">2 · WRITE  one byte into vendor-bundle.bin</text>
    <text x="400" y="223" font-size="9.5" fill="currentColor">lower layers are READ-ONLY, so the file has to move first:</text>
    <g fill="currentColor" font-size="9.5">
      <text x="418" y="241" font-weight="700" fill="#e0930f">COPY-UP</text>
      <text x="490" y="241">copy all 40 MB, lower[1] -&gt; upper</text>
      <text x="418" y="257">then</text>
      <text x="490" y="257">apply the 1-byte change in upper</text>
    </g>
    <rect x="400" y="268" width="440" height="40" rx="7" fill="#d64545" fill-opacity="0.12" stroke="#d64545" stroke-width="1.6"/>
    <text x="412" y="284" font-size="10" font-weight="700" fill="#d64545">MEASURED   41,943,040 bytes moved to change 1 byte</text>
    <text x="412" y="299" font-size="9.5" fill="currentColor">write amplification 41,943,040x — exactly the file size</text>
    <text x="400" y="324" font-size="9" fill="currentColor" opacity="0.9">Paid ONCE per file per container; the next write takes ~0.01 ms.</text>
    <text x="400" y="337" font-size="9" fill="currentColor" opacity="0.9">Scales with FILE size, not write size: 1 byte into 5 GB copies 5 GB.</text>

    <rect x="384" y="358" width="472" height="106" rx="10" fill="#7f7f7f" fill-opacity="0.08" stroke="currentColor" stroke-opacity="0.5" stroke-width="1.8"/>
    <text x="400" y="378" font-size="11" font-weight="700" fill="currentColor">3 · DELETE  rm libc.so</text>
    <text x="400" y="395" font-size="9.5" fill="currentColor">you cannot remove a file from a layer you do not own.</text>
    <g font-size="9.5">
      <text x="418" y="413" font-weight="700" fill="#d64545">WHITEOUT</text>
      <text x="512" y="413" fill="currentColor">write .wh.libc.so into upper</text>
      <text x="418" y="429" fill="currentColor">merged view</text>
      <text x="512" y="429" font-weight="700" fill="#0fa07f">13 entries -&gt; 12: gone</text>
      <text x="418" y="445" fill="currentColor">on disk below</text>
      <text x="512" y="445" font-weight="700" fill="#d64545">still there, all 1.4 MB</text>
    </g>

    <g fill="none" stroke-width="1.8">
      <path d="M304 90 C 340 90, 350 100, 378 106" stroke="#3553ff" marker-end="url(#l02-a2)" stroke-opacity="0.8"/>
      <path d="M304 198 C 336 210, 350 226, 378 240" stroke="#e0930f" marker-end="url(#l02-a2o)"/>
      <path d="M304 298 C 336 330, 350 380, 378 404" stroke="#d64545" marker-end="url(#l02-a2r)"/>
    </g>

    <text x="440" y="494" font-size="11" text-anchor="middle" fill="currentColor" opacity="0.9">Every write to an image file pays for the whole file once. This is why write-heavy paths belong in a volume, not the container.</text>
  </g>
</svg>
```

**Read** walks the stack top-down and stops at the first hit. Cheap, and it explains *shadowing*: when two layers contain the same path, the higher one wins and the lower one is invisible — **but still present, and still counted in your image size.** You are downloading and storing a file that nothing can ever open.

**Write** is where the cost is. Lower layers are read-only, so before a single byte of a lower-layer file can change, overlayfs **copies the entire file into the upper layer** — a *copy-up*. The Build It measures this directly: appending one byte to a 40 MB file that lives in a lower layer moved **41,943,040 bytes**. That is a write amplification of **41,943,040×**, and the figure is exact because it is simply the file size. The second write to the same file takes about **0.01 ms**, because by then the file lives in the upper layer.

Two things follow, and they are the practical payload of this section. **The cost scales with file size, not write size** — one byte into a 5 GB file copies 5 GB. And **it is paid once per file, per container**, which is why "the first request after a deploy is slow and the rest are fine" is such a common and such a confusing performance report. If your service writes to files that came from the image — a SQLite database, a log file, an unpacked cache — that path belongs in a **volume**, which bypasses the overlay entirely.

**Delete** cannot touch a read-only layer either, so overlayfs writes a **whiteout**: a marker in the upper layer that makes the name disappear from the merged view. The Build It deletes `libc.so` and confirms both halves — the merged listing drops from **13 entries to 12**, and the file is **still on disk in the lower layer, all 1.4 MB of it.**

That mechanism has a security consequence that has leaked real credentials at real companies. Writing `RUN rm -rf /secrets` in a Dockerfile **does not remove the secret and does not shrink the image.** Each instruction creates a new layer, so the delete becomes a whiteout in a *new* layer sitting on top of the layer that still contains the file. Anyone who pulls the image can extract the lower layer and read it. The only fix is to never let the secret into a layer at all — build-time secret mounts, or a multi-stage build that leaves it behind. ([Secrets Management & Rotation](../../07-auth-and-security/13-secrets-management-and-rotation/) covers the handling side.) The next lesson builds images layer by layer and returns to this.

### Capabilities — what root actually means

Here is the fourth thing, the one that is missing from most explanations of containers, and it is the reason the Build It's most instructive section is a section where everything fails.

Traditional UNIX has a binary privilege model: you are uid 0 and may do anything, or you are not and may not. Linux replaced that in 2.2 with **capabilities** (`capabilities(7)`) — root's power split into **41 independent privileges** that can be granted and removed one at a time. `CAP_NET_BIND_SERVICE` lets you bind port 80. `CAP_KILL` lets you signal any process. `CAP_SYS_MODULE` lets you load a kernel module, which is total ownership of the host.

**Root inside a container is uid 0 with most of those removed.** Measured in this sandbox: `CapEff = 0x00000000a80425fb`, which decodes to **14 of 41 capabilities held and 27 dropped**. Absent from the list: `CAP_SYS_ADMIN`, `CAP_SYS_MODULE`, `CAP_SYS_PTRACE`, `CAP_NET_ADMIN`, `CAP_SYS_BOOT`, `CAP_SYS_TIME`, `CAP_BPF`.

You can watch this bite. The Build It calls `unshare()` six times through `ctypes`, once per namespace type, and **all six fail with EPERM (errno 1, "Operation not permitted")** — as root. `CLONE_NEWNS`, `CLONE_NEWUTS`, `CLONE_NEWIPC`, `CLONE_NEWPID`, `CLONE_NEWNET` all require `CAP_SYS_ADMIN`, and this process does not have it. The same capability gates `mount()`, `setns()` and `pivot_root()` — which is to say, it gates *every syscall a container runtime needs to start a container*.

**That is the mechanical reason you cannot build container images inside an ordinary CI container.** It is not a Docker quirk or a licensing choice; the kernel is refusing the syscalls. The workarounds all follow from it: mount the host's Docker socket (and hand the host away), run the build container `--privileged` (and hand the host away), or use a **userspace builder** — Kaniko, Buildah in rootless mode, BuildKit's rootless mode — that constructs layers as ordinary file operations without ever calling `mount()`.

Now the sharpest observation in the whole lesson, and it is one the sandbox handed over for free. `CLONE_NEWUSER` **also** failed with EPERM — but creating a *user* namespace requires no capability at all on a modern kernel. That is precisely what makes rootless containers possible: an unprivileged user creates a user namespace, becomes uid 0 *inside* it, and thereby gains `CAP_SYS_ADMIN` *within that namespace*, which is enough to create the others. So why did it fail? The Build It prints the evidence: `user.max_user_namespaces = 31735`, so the kernel is not the one refusing; and `Seccomp: filter (BPF), 1 filter installed`.

**There are two independent gates, and you have to know about both.** Capabilities are one. **seccomp** (secure computing mode) is the other: a BPF program attached to the process that filters syscalls by number and argument, and the container runtime's default profile blocks `unshare` with `CLONE_NEWUSER` regardless of your capabilities. This is why `--privileged` is so dangerous and so misunderstood: **it does not grant one thing, it switches off several defence layers at once** — it grants all capabilities, disables the seccomp filter, relaxes AppArmor/SELinux, and exposes host devices. It is not a convenience flag that makes an annoying error go away. It is a decision to remove the boundary.

### PID 1 — the process that is not like the others

The last piece, and the one that causes the most production bugs per line of explanation.

Being PID 1 changes your process's contract with the kernel in two ways that nothing warns you about.

**First: no default signal dispositions.** Every ordinary process has a default action for each signal, defined by POSIX (IEEE Std 1003.1) and applied by the kernel when no handler is installed — `SIGTERM` terminates, `SIGINT` terminates, `SIGQUIT` cores. For **PID 1 of a namespace, the kernel does not apply default actions at all.** A signal with no registered handler is silently discarded (`pid_namespaces(7)`). The rationale is sound — it stops a stray signal from killing the init process and taking the whole namespace down — but the consequence for a web app shipped as a container entrypoint is that **`SIGTERM` does nothing whatsoever**, and the first thing that actually stops it is the `SIGKILL` at the end of the grace period.

**Second: the zombie-reaping duty.** When a process exits, the kernel keeps its exit status until the parent collects it with `wait()`. Until then it is a **zombie**: no memory, no code, just a process-table slot and a held pid. Normally the parent reaps promptly. But when a parent dies before its children, the orphans are **re-parented to PID 1**, and reaping them becomes PID 1's job. A real init program has a loop for exactly this. **Your web framework does not — it has no such loop, because it was never written to be init.** So a service that shells out to a subprocess which itself spawns a helper accumulates one zombie per occurrence, forever, until `pids.max` is reached and `fork()` starts returning EAGAIN — surfacing as "Resource temporarily unavailable" from some completely unrelated part of the system.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 520" width="100%" style="max-width:840px" role="img" aria-label="Two views of PID 1. On the left, the zombie lifecycle: a child exits and becomes a zombie holding a process table slot until its parent calls wait, and orphans are re-parented to PID 1 which must reap them or the pids limit is eventually reached. On the right, a deploy timeline comparing three processes receiving SIGTERM: an ordinary process with no handler dies in two milliseconds severing eight in-flight requests, a PID 1 with no handler ignores SIGTERM entirely and keeps admitting new work for the full one second grace period before being SIGKILLed with eight requests still severed, and a process with a handler stops admitting work, drains all eight requests and exits cleanly in about two hundred milliseconds with nothing severed.">
  <defs>
    <marker id="l02-a3" markerWidth="10" markerHeight="10" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker>
    <marker id="l02-a3r" markerWidth="10" markerHeight="10" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#d64545"/></marker>
  </defs>
  <text x="440" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">PID 1 has no default signal handlers, and inherits every orphan</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">

    <text x="24" y="56" font-size="10.5" font-weight="700" fill="currentColor">A · THE ZOMBIE CYCLE</text>
    <g stroke-width="2">
      <rect x="24" y="68" width="118" height="42" rx="9" fill="#0fa07f" fill-opacity="0.14" stroke="#0fa07f"/>
      <rect x="24" y="140" width="118" height="42" rx="9" fill="#e0930f" fill-opacity="0.15" stroke="#e0930f"/>
      <rect x="24" y="212" width="118" height="42" rx="9" fill="#7f7f7f" fill-opacity="0.10" stroke="currentColor" stroke-opacity="0.55"/>
      <rect x="212" y="140" width="146" height="42" rx="9" fill="#d64545" fill-opacity="0.13" stroke="#d64545"/>
    </g>
    <g fill="currentColor" text-anchor="middle">
      <text x="83" y="86" font-size="10.5" font-weight="700" fill="#0fa07f">RUNNING</text>
      <text x="83" y="101" font-size="8.5" opacity="0.9">state R / S</text>
      <text x="83" y="158" font-size="10.5" font-weight="700" fill="#e0930f">ZOMBIE</text>
      <text x="83" y="173" font-size="8.5" opacity="0.9">state Z — pid held</text>
      <text x="83" y="230" font-size="10.5" font-weight="700">REAPED</text>
      <text x="83" y="245" font-size="8.5" opacity="0.9">slot released</text>
      <text x="285" y="158" font-size="10" font-weight="700" fill="#d64545">NOBODY CALLS wait()</text>
      <text x="285" y="173" font-size="8.5" opacity="0.9">zombies accumulate forever</text>
    </g>
    <g fill="none" stroke="currentColor" stroke-width="1.7">
      <path d="M83 110 L 83 134" marker-end="url(#l02-a3)"/>
      <path d="M83 182 L 83 206" marker-end="url(#l02-a3)"/>
    </g>
    <path d="M142 161 L 206 161" fill="none" stroke="#d64545" stroke-width="1.7" marker-end="url(#l02-a3r)"/>
    <text x="152" y="128" font-size="8.5" fill="currentColor" opacity="0.85">_exit()</text>
    <text x="96" y="200" font-size="8.5" fill="currentColor" opacity="0.85">parent wait()s</text>

    <rect x="212" y="200" width="146" height="66" rx="9" fill="#d64545" fill-opacity="0.10" stroke="#d64545" stroke-width="1.6"/>
    <text x="224" y="218" font-size="9" font-weight="700" fill="#d64545">then pids.max</text>
    <text x="224" y="232" font-size="8.5" fill="currentColor" opacity="0.9">fork() -&gt; EAGAIN</text>
    <text x="224" y="245" font-size="8.5" fill="currentColor" opacity="0.9">"Resource temporarily</text>
    <text x="224" y="258" font-size="8.5" fill="currentColor" opacity="0.9">unavailable", elsewhere</text>

    <rect x="24" y="282" width="334" height="76" rx="9" fill="#7c5cff" fill-opacity="0.11" stroke="#7c5cff" stroke-width="1.8"/>
    <text x="36" y="301" font-size="9.5" font-weight="700" fill="#7c5cff">WHY IT LANDS ON PID 1</text>
    <text x="36" y="317" font-size="9" fill="currentColor" opacity="0.92">when a parent dies first, its children are</text>
    <text x="36" y="330" font-size="9" fill="currentColor" opacity="0.92">re-parented to PID 1. reaping them is then</text>
    <text x="36" y="343" font-size="9" fill="currentColor" opacity="0.92">PID 1's duty. an init has a loop for it.</text>
    <text x="36" y="356" font-size="9" font-weight="700" fill="#d64545">your web framework does not.</text>

    <text x="36" y="382" font-size="9.5" font-weight="700" fill="currentColor">MEASURED</text>
    <text x="36" y="398" font-size="9" fill="currentColor" opacity="0.92">6 children forked, none reaped -&gt; 6 of 6 in</text>
    <text x="36" y="411" font-size="9" fill="currentColor" opacity="0.92">state Z, pids.current 16 -&gt; 22. after one</text>
    <text x="36" y="424" font-size="9" fill="currentColor" opacity="0.92">waitpid() each: 0 zombies, back to 16.</text>

    <text x="398" y="56" font-size="10.5" font-weight="700" fill="currentColor">B · ONE DEPLOY, THREE PROCESSES</text>

    <g fill="none" stroke="currentColor" stroke-width="1.3" stroke-dasharray="4 4" opacity="0.5">
      <path d="M470 66 L 470 300"/>
      <path d="M836 66 L 836 300"/>
    </g>
    <text x="470" y="78" font-size="9" font-weight="700" text-anchor="middle" fill="#3553ff">SIGTERM</text>
    <text x="828" y="78" font-size="9" font-weight="700" text-anchor="end" fill="#d64545">SIGKILL — grace ends, 1.0 s</text>

    <g stroke-width="2">
      <rect x="470" y="90" width="10" height="34" rx="4" fill="#d64545" fill-opacity="0.30" stroke="#d64545"/>
      <rect x="470" y="152" width="366" height="34" rx="6" fill="#e0930f" fill-opacity="0.16" stroke="#e0930f"/>
      <rect x="470" y="214" width="76" height="34" rx="6" fill="#0fa07f" fill-opacity="0.17" stroke="#0fa07f"/>
    </g>

    <g fill="currentColor">
      <text x="398" y="104" font-size="9" font-weight="700">no handler</text>
      <text x="398" y="116" font-size="8" opacity="0.8">ordinary proc</text>
      <text x="492" y="105" font-size="9" font-weight="700" fill="#d64545">dead in 2 ms</text>
      <text x="492" y="118" font-size="8.5" opacity="0.9">default disposition = terminate. exit 143.</text>
      <text x="700" y="111" font-size="9" font-weight="700" fill="#d64545">8 SEVERED</text>

      <text x="398" y="166" font-size="9" font-weight="700">no handler</text>
      <text x="398" y="178" font-size="8" opacity="0.8">but is PID 1</text>
      <text x="484" y="167" font-size="9" font-weight="700" fill="#e0930f">SIGTERM DISCARDED — keeps admitting new work</text>
      <text x="484" y="180" font-size="8.5" opacity="0.9">burns the entire grace period, then exit 137.</text>
      <text x="828" y="203" font-size="9" font-weight="700" fill="#d64545" text-anchor="end">8 SEVERED</text>

      <text x="398" y="228" font-size="9" font-weight="700">handler</text>
      <text x="398" y="240" font-size="8" opacity="0.8">drain flag</text>
      <text x="560" y="228" font-size="9" font-weight="700" fill="#0fa07f">drains all 8 and exits 0 in ~200 ms</text>
      <text x="560" y="243" font-size="8.5" opacity="0.9">stops admitting, finishes in-flight —</text>
      <text x="770" y="243" font-size="9" font-weight="700" fill="#0fa07f">0 SEVERED</text>
    </g>

    <rect x="398" y="282" width="458" height="76" rx="9" fill="#d64545" fill-opacity="0.10" stroke="#d64545" stroke-width="1.8"/>
    <text x="412" y="301" font-size="9.5" font-weight="700" fill="#d64545">WHY NOBODY NOTICES</text>
    <text x="412" y="317" font-size="9" fill="currentColor" opacity="0.92">a severed request is a TCP reset, not a 5xx. it never reaches</text>
    <text x="412" y="330" font-size="9" fill="currentColor" opacity="0.92">your error rate, your logs, or your SLO burn — the client</text>
    <text x="412" y="343" font-size="9" fill="currentColor" opacity="0.92">records the failure and you record nothing at all.</text>

    <text x="412" y="382" font-size="9.5" font-weight="700" fill="currentColor">SCALED TO A FLEET</text>
    <text x="412" y="398" font-size="9" fill="currentColor" opacity="0.92">8 severed x 40 pods x 12 deploys/day = 3,840 dropped</text>
    <text x="412" y="411" font-size="9" fill="currentColor" opacity="0.92">connections a day. deploy time per pod also goes from</text>
    <text x="412" y="424" font-size="9" fill="currentColor" opacity="0.92">~200 ms to 1001 ms — a 4.3x slower rollout, every time.</text>

    <rect x="24" y="444" width="832" height="40" rx="9" fill="#0fa07f" fill-opacity="0.12" stroke="#0fa07f" stroke-width="1.8"/>
    <text x="440" y="461" font-size="10.5" font-weight="700" text-anchor="middle" fill="#0fa07f">THE FIX: handle SIGTERM yourself, or run a real init at PID 1 (tini, dumb-init, docker run --init)</text>
    <text x="440" y="476" font-size="9" text-anchor="middle" fill="currentColor" opacity="0.9">an init forwards signals to your app — which is not PID 1 any more, so the ordinary defaults apply again — and reaps orphans</text>
  </g>
</svg>
```

The graceful-shutdown *sequence* — fail readiness first, then wait for the load balancer to notice, then stop accepting, then drain — is built in detail in [Health Checks, Readiness & Graceful Shutdown](../../09-logging-monitoring-and-observability/08-health-checks-and-probes/). This lesson supplies the piece underneath it: **none of that sequence runs at all unless a handler is installed, because PID 1 never receives the default action that would have started it.**

## Build It

[`code/container_internals.py`](code/container_internals.py) is five numbered sections, standard library only, about 2.4 seconds end to end. Nothing in it requires privilege — section 2 exists precisely because the privileged operations fail.

**Section 2 is the one to read first**, because it turns a permission error into the lesson. `unshare()` is not exposed by Python's `os` module, so it is called through `ctypes` with `use_errno=True`:

```python
libc = ctypes.CDLL(ctypes.util.find_library("c") or "libc.so.6", use_errno=True)
for name, flag, _kind, gate in CLONE_FLAGS:
    ctypes.set_errno(0)
    rc = libc.unshare(flag)
    err = ctypes.get_errno()
    if rc != 0:
        print("  %-14s %-8s %-7s %-24s %s"
              % (name, "FAILED", "%d" % err, os.strerror(err), gate))
```

The capability set is then decoded from `/proc/self/status` by treating `CapEff` as a bitmask over the ordered list from `linux/capability.h`:

```python
eff = int(cap_eff, 16)
held    = [n for i, n in enumerate(CAP_NAMES) if eff >> i & 1]
dropped = [n for i, n in enumerate(CAP_NAMES) if not (eff >> i & 1)]
```

**Section 3 builds the overlay.** The whole model is an ordered list of lower directories plus one upper, with three methods. Reads resolve top-down:

```python
def resolve(self, name: str) -> tuple[str | None, str]:
    """Return (path, which_layer). Top-down, first match wins."""
    if os.path.exists(self._whiteout_path(name)):
        return None, "whiteout (deleted in upper)"
    candidate = os.path.join(self.upper, name)
    if os.path.exists(candidate):
        return candidate, "upper (writable)"
    for depth, lower in enumerate(self.lowers):
        candidate = os.path.join(lower, name)
        if os.path.exists(candidate):
            return candidate, "lower[%d] %s" % (depth, os.path.basename(lower))
    return None, "not found"
```

Copy-up is the heart of it, and it is four lines. Note that the lower layer is only ever *read* — that immutability is what lets containers share it:

```python
def copy_up(self, name: str) -> tuple[bool, float, int]:
    """Ensure `name` exists in the upper layer. Returns (did_copy, secs, bytes)."""
    target = os.path.join(self.upper, name)
    if os.path.exists(target):
        return False, 0.0, 0              # already up: writes are cheap now
    source = next((os.path.join(lo, name) for lo in self.lowers
                   if os.path.exists(os.path.join(lo, name))), None)
    if source is None:
        return False, 0.0, 0
    size = os.path.getsize(source)
    start = time.perf_counter()
    shutil.copyfile(source, target)       # the ENTIRE file, to change one byte
    return True, time.perf_counter() - start, size
```

And delete, which cannot delete:

```python
def unlink(self, name: str) -> str:
    """Delete from the merged view. Lower layers are immutable, so we mask."""
    upper_path = os.path.join(self.upper, name)
    in_lower = any(os.path.exists(os.path.join(lo, name)) for lo in self.lowers)
    if os.path.exists(upper_path):
        os.unlink(upper_path)
    if in_lower:
        with open(self._whiteout_path(name), "wb"):   # .wh.<name>
            pass
        return "whiteout written (file still present in a lower layer)"
    return "removed from upper (no lower copy existed)"
```

**Section 5b models the deploy.** Three child processes run identical load — 8 requests in flight, a new one admitted whenever one completes — and differ only in how they treat `SIGTERM`. The middle one uses `SIG_IGN` as a faithful stand-in for PID 1's implicit discard, since creating a pid namespace needs the `CAP_SYS_ADMIN` that section 2 proved is absent:

```python
if mode == "ignore":
    signal.signal(signal.SIGTERM, signal.SIG_IGN)    # what PID 1 does implicitly
elif mode == "handle":
    def on_term(_signum, _frame):
        drain["asked"] = True                        # a flag, never work
    signal.signal(signal.SIGTERM, on_term)
...
    inflight -= 1
    served += 1
    if not drain["asked"]:
        inflight += 1                                # still admitting: full load
```

The parent then plays the orchestrator exactly as a real one does — `SIGTERM`, wait out the grace period, `SIGKILL`:

```python
if time.perf_counter() >= deadline:
    os.kill(pid, signal.SIGKILL)     # the uncatchable one
    sigkilled = True
```

Run it:

```bash
docker compose exec -T app python \
  phases/10-infrastructure-and-deployment/02-what-a-container-actually-is/code/container_internals.py
```

```console
== 1 · THE NAMESPACES YOU ARE ALREADY IN ==
  KIND     ID                     WHAT IT VIRTUALISES
  mnt      mnt:[4026533908]       the mount table -- which filesystems exist and where
  pid      pid:[4026533911]       the process id number space -- who else exists
  net      net:[4026534032]       interfaces, addresses, routes, ports, firewall rules
  ipc      ipc:[4026533910]       System V IPC objects and POSIX message queues
  uts      uts:[4026533909]       the hostname and NIS domain name
  user     user:[4026531837]      the uid/gid mapping -- and therefore what root means
  cgroup   cgroup:[4026533912]    where the cgroup tree appears to be rooted
  time     time:[4026534160]      the offsets for CLOCK_MONOTONIC and CLOCK_BOOTTIME

  forked a child (pid 56848). it shares 8/8 namespaces with us.

== 2 · WHY YOU CANNOT BUILD ONE HERE — CAPABILITIES, DEMONSTRATED ==
  we are uid 0 (root) in this container. watch root fail anyway.

  unshare(flag)  result   errno   meaning                  gate
  CLONE_NEWNS    FAILED   1       Operation not permitted  CAP_SYS_ADMIN
  CLONE_NEWUTS   FAILED   1       Operation not permitted  CAP_SYS_ADMIN
  CLONE_NEWIPC   FAILED   1       Operation not permitted  CAP_SYS_ADMIN
  CLONE_NEWPID   FAILED   1       Operation not permitted  CAP_SYS_ADMIN
  CLONE_NEWNET   FAILED   1       Operation not permitted  CAP_SYS_ADMIN
  CLONE_NEWUSER  FAILED   1       Operation not permitted  none on a modern kernel

  CapEff = 0x00000000a80425fb   -> 14 of 41 capabilities held
  CapBnd = 0x00000000a80425fb   -> the bounding set: a ceiling you can never rise above

  DROPPED — 27 in total. the ones worth knowing by name:
    - CAP_DAC_READ_SEARCH      read any file, traverse any directory
    - CAP_NET_ADMIN            reconfigure interfaces, routes, firewall rules
    - CAP_SYS_MODULE           load a kernel module: total host compromise
    - CAP_SYS_PTRACE           attach to any process and read its memory
    - CAP_SYS_ADMIN            mount, unshare, setns, pivot_root -- 'the new root'
    - CAP_SYS_BOOT             reboot the host
    - CAP_BPF                  load BPF programs into the kernel

  the sharp one is CLONE_NEWUSER. creating a USER namespace needs no
  capability on a modern kernel -- that is the whole point of rootless
  containers. and it still failed here. two gates, not one:
    gate 1  capabilities   -> CAP_SYS_ADMIN: absent (see above)
    gate 2  seccomp        -> Seccomp mode filter (BPF), 1 filter(s) installed
    kernel would allow it: user.max_user_namespaces = 31735 (non-zero)

== 3 · THE LAYERED FILESYSTEM, BUILT FOR REAL ==
  our own root filesystem, from /proc/self/mountinfo:
    fstype   overlay
    lowerdir 8 read-only layers stacked
    upperdir 1 writable layer (this container's private scratch)
    workdir  1 (overlayfs' staging area for atomic renames)

  READ PATH — first match top-down wins:
    read config.yaml          -> lower[0] 03-app
    read os-release           -> lower[2] 01-runtime
    read libc.so              -> lower[3] 00-base-os
    read vendor-bundle-0.bin  -> lower[1] 02-vendor-deps
    read nope.txt             -> not found

  COPY-UP — the cost of the first write to a lower-layer file:
    file under test          vendor-bundle-N.bin, 40 MB, in lower[1]
    bytes actually changed   1

    write 1 byte, file already in upper             0.01 ms
    write 1 byte, file in a LOWER layer            10.53 ms  <-- copy-up
       ...of which: copying the file               10.51 ms
    write 1 byte again, same file                   0.01 ms
       (individual copy-ups: 11, 11, 11, 10, 9 ms)

    WRITE AMPLIFICATION  41,943,040 bytes moved to change 1 byte = 41,943,040x
    that figure is exact and it does not vary: it is the file size.

  WHITEOUT — deleting something you do not own:
    rm libc.so           -> whiteout written (file still present in a lower layer)
    merged view          -> gone
    lower[3] on disk     -> still present (1.4 MB)
    upper layer now has  -> 7 entries, of which 1 whiteout marker(s): .wh.libc.so
    merged entries: 13 before, 12 after

== 4 · CGROUPS v2 — WHAT THE PROCESS MAY *USE* ==
  cgroup.controllers   which resource controllers are available here
                       cpuset cpu io memory hugetlb pids rdma
  memory.max           max                          HARD memory ceiling. exceed it and the OOM killer fires
  memory.current       45301760                     bytes charged to this cgroup right now
  memory.peak          779636736                    high-water mark since boot -- size your limit from this
  cpu.max              max 100000                   'QUOTA PERIOD' in microseconds. you get QUOTA per PERIOD
  cpu.stat             (parsed below)               usage and, crucially, throttling counters
      usage_usec       1,736,539,013
      nr_throttled     0
      throttled_usec   0
  pids.max             max                          process/thread count ceiling -- the fork-bomb fuse

  THE DISTINCTION THAT MATTERS, and it is not symmetric:
    exceed cpu.max     -> you are THROTTLED. the kernel stops scheduling
                          your threads until the next 100 ms period opens.
                          from inside this looks like LATENCY, not an error.
    exceed memory.max  -> you are KILLED. the kernel OOM killer sends an
                          uncatchable SIGKILL. exit code 137 (128+9).

  HONESTY NOTE: memory.max, memory.high, memory.swap.max, pids.max read 'max'
  (unlimited) in this sandbox. `docker run --memory 512m --cpus 1.5
  --pids-limit 200` writes 536870912, '150000 100000' and 200 into these files.

  THE PART THAT SURPRISES PEOPLE: page cache is charged to the cgroup.
    memory.current before writing a 64 MB file   43.2 MB
    memory.current after writing and reading it  109.1 MB
    delta                                        65.9 MB (103% of the file)
    after deleting the file                      43.2 MB

== 5a · PID 1 — THE ZOMBIE REAPING DUTY ==
  forked 6 children; every one called _exit(0) immediately.
  we did NOT call wait(). their /proc/<pid>/stat state:
    56850=Z  56851=Z  56852=Z  56853=Z  56854=Z  56855=Z
  zombies: 6 of 6   ('Z' is the state letter in stat field 3)
  pids.current for this cgroup: 22

  ...then one os.waitpid() per child.
  zombies now: 0 of 6
  pids.current for this cgroup: 16

== 5b · PID 1 — SIGNALS, AND THE REQUESTS A DEPLOY DROPS ==
  three servers, identical load: 8 requests in flight at all times,
  25 ms each, a new one admitted whenever one completes.
  SIGTERM arrives after ~100 ms; grace period 1.0 s.

  process                                    outcome             exit   served   SEVERED     took
  no handler (an ordinary process)           killed by SIGTERM    143        3         8       2ms
  SIGTERM ignored (== PID 1, no handler)     killed by SIGKILL    137       34         8    1001ms
  handler installed: stop admitting, drain   exited cleanly         0       11         0     235ms

  scale row 2: 8 severed per pod x 40 pods x 12 deploys/day
  = 3,840 severed connections a day, and NONE appear in your error rate:
  the client gets a TCP reset, not a 5xx, so your own counters stay flat.
  deploy time also goes from 235 ms to 1001 ms per pod (4.3x), which
  is why a 40-pod rolling update that 'should take a minute' takes ten.

(total wall time 2.4 s)
```

Read what each section actually proves.

**Section 1** establishes that you are already inside all eight namespaces and that a `fork()` child shares **8 of 8** of them. Nothing was created; you inherited membership. The only difference between this process and a "container" is which of those ids were made fresh at start-up.

**Section 2 is the argument.** Six privileged operations, six EPERMs, as root. The capability mask decodes to **14 of 41 held**, and the missing `CAP_SYS_ADMIN` is the exact reason. Then the detail that separates a working mental model from a superficial one: **`CLONE_NEWUSER` needs no capability and still failed**, with `user.max_user_namespaces = 31735` proving the kernel was willing. The seccomp filter is a second, independent gate. If you only knew about capabilities you would have mis-diagnosed this, and `--privileged` "fixing" it would have taught you the wrong lesson about why.

**Section 3** is the lesson's headline measurement. Reads resolve top-down (`os-release` comes from the runtime layer, shadowing the base layer's copy, which is still on disk and still in your image). A one-byte append to a 40 MB lower-layer file moved **41,943,040 bytes** — write amplification of **41,943,040×**, exact because it is the file size. The copy took about **10.5 ms** here on a warm page cache; the *next* write to the same file took **0.01 ms**. Do not anchor on the milliseconds — anchor on the bytes, because the ratio moves with cache state and storage backend while the byte count never does. Then the whiteout: the merged view drops from **13 entries to 12**, and `libc.so` is **still on disk, all 1.4 MB**. Deleting in a layer does not delete.

**Section 4** reads real limits, and reports honestly that this sandbox sets none — `memory.max`, `pids.max` and the `cpu.max` quota all read `max`. The teaching still lands because the *files* are real and the interpretations are what you need at 3 a.m. The measured part is the page-cache experiment: writing and reading a 64 MB file grew `memory.current` from 43.2 MB to 109.1 MB, a delta of **65.9 MB — 103% of the file** — which came straight back down to 43.2 MB when the file was deleted. Your heap never moved. That is the whole explanation for OOM kills at numbers your profiler cannot account for.

**Section 5a** makes zombies visible: 6 forked children that exit immediately show **state `Z` in all 6** of their `/proc/<pid>/stat` entries, and `pids.current` for the cgroup goes 16 → 22. One `waitpid()` each and it is 0 zombies, back to 16. Nothing was running; six process-table slots were simply held hostage by a missing function call.

**Section 5b is the deploy.** Three servers, identical load, differing only in signal handling. The ordinary process with no handler dies in **2 ms** with exit **143** (128+15) and severs **8** in-flight requests. The PID-1-equivalent **ignores `SIGTERM` completely**, keeps admitting new work for the entire grace period, and is `SIGKILL`ed at **1001 ms** with exit **137** — and still severs **8**. It bought nothing with that second: it served requests it could not finish and delayed the rollout. The handler version stops admitting, drains all 8, and exits **0** in about **200 ms** with **0 severed**. Same code, same load; one signal handler is the whole difference between 3,840 dropped connections a day and none.

## Use It

Every primitive you just built by hand is one flag on a container runtime. This is the mapping worth memorising.

### Namespaces

```bash
docker run --pid host        myimg   # share the HOST pid namespace — see every process
docker run --network host    myimg   # no net namespace: bind directly on host ports
docker run --ipc host        myimg   # share System V IPC (needed by some ML libs)
docker run --uts host        myimg   # share the hostname
docker run --userns host     myimg   # opt OUT of user-namespace remapping
docker run --pid container:other-ctr myimg   # join another container's pid namespace
```

Each of these *removes* an isolation boundary. `--network host` is the most commonly used and the most commonly regretted: you gain a few microseconds of latency and lose port isolation, the container's own firewall rules, and the ability to run two copies. In Kubernetes the same switches are `hostPID`, `hostNetwork`, `hostIPC` and `shareProcessNamespace` on the Pod spec — the last of which is genuinely useful for debug sidecars, since it lets a sidecar see and `exec` against the main container's processes.

### cgroups

```bash
docker run --memory 512m --memory-swap 512m \   # equal values disable swap entirely
           --cpus 1.5 \                          # -> cpu.max "150000 100000"
           --pids-limit 200 \                    # -> pids.max
           --device-write-bps /dev/sda:10mb \    # -> io.max
           myimg
```

```yaml
resources:
  requests:            # what the SCHEDULER reserves for you
    memory: "256Mi"
    cpu: "500m"
  limits:              # what the KERNEL enforces on you
    memory: "512Mi"    # -> memory.max. Exceed it -> OOMKilled, exit 137
    cpu: "1500m"       # -> cpu.max. Exceed it -> throttled, no error
```

Requests and limits are different mechanisms and confusing them is a top-three cause of mystery latency. **Requests are for the scheduler** — they decide which node you land on and reserve nothing at runtime. **Limits are for the kernel** — they are written into the cgroup files you just read. Three rules:

- **Always set a memory limit.** An unlimited container that leaks evicts its neighbours and can take the node down.
- **Set `requests.memory == limits.memory`** for anything latency-sensitive. In Kubernetes that earns the `Guaranteed` QoS class, which makes you last in line for eviction rather than first.
- **Be sceptical of tight CPU limits.** A limit that clips a bursty service produces `nr_throttled` and a latency graph nobody can explain. Graph `container_cpu_cfs_throttled_periods_total` next to your p99 — if they move together, the limit is the bug. Many mature teams set CPU *requests* and no CPU *limit* for exactly this reason.

### The layered filesystem

```bash
docker run --read-only \                              # rootfs mounted read-only
           --tmpfs /tmp:rw,noexec,nosuid,size=64m \    # explicit writable scratch
           -v app-data:/var/lib/app \                  # a volume: bypasses the overlay
           myimg
```

A **read-only root filesystem with explicit writable mounts** is the single highest-value hardening flag available, and it is nearly free. It stops an attacker writing a binary or modifying your code, and it forces you to *know* where your service writes — which is exactly the knowledge that prevents copy-up surprises. Anything write-heavy belongs in a volume: databases, caches, uploads, logs. A volume is a bind mount over the merged view, so writes go straight to the host filesystem with no copy-up and no layer growth. ([Files & the Filesystem](../../00-foundations/10-files-and-the-filesystem/) covers the underlying mount semantics.)

### Capabilities and the security posture

```bash
docker run --cap-drop ALL \                    # start from zero, always
           --cap-add NET_BIND_SERVICE \        # add back only what you proved you need
           --security-opt no-new-privileges \  # setuid binaries cannot escalate
           --user 10001:10001 \                # non-root uid; must exist in the image
           --read-only \
           myimg
```

```yaml
securityContext:
  runAsNonRoot: true          # the kubelet REFUSES to start a root container
  runAsUser: 10001
  allowPrivilegeEscalation: false
  readOnlyRootFilesystem: true
  capabilities:
    drop: ["ALL"]
    add: ["NET_BIND_SERVICE"]
  seccompProfile:
    type: RuntimeDefault      # not the default in older clusters — set it explicitly
```

`--cap-drop ALL` then adding back is the whole discipline, and it is the same least-privilege principle as [Authorization: RBAC, ABAC & ReBAC](../../07-auth-and-security/09-authorization-rbac-abac-rebac/) applied to the kernel's syscall surface. In practice most services need **zero** capabilities — bind a port above 1024 and you need none at all, which is why listening on 8080 and letting the load balancer map 443 is both simpler and safer than granting `CAP_NET_BIND_SERVICE`.

And the flag to treat with real suspicion:

```bash
docker run --privileged myimg      # grants ALL capabilities, disables seccomp,
                                   # relaxes AppArmor/SELinux, exposes host devices
```

**`--privileged` is not a convenience flag; it is a decision to remove the boundary.** A privileged container with `CAP_SYS_ADMIN` can mount the host filesystem, load kernel modules, and write to the host's cgroup tree — it is host root with extra steps. When you find yourself reaching for it, the question is always "which *one* capability do I actually need?" The common legitimate answers are `CAP_NET_ADMIN` for a VPN sidecar and `CAP_SYS_PTRACE` for a profiler, and both are `--cap-add` of one thing, not `--privileged`.

**Rootless containers** solve the same problem from the other end. Podman rootless and Docker's rootless mode run the whole runtime as an unprivileged user, using a user namespace so that uid 0 inside maps to your ordinary uid outside. A container escape lands the attacker on your unprivileged account rather than on host root. The cost is a set of sharp edges — no binding below port 1024 without extra setup, slower userspace networking, and some storage drivers unavailable.

### PID 1

```bash
docker run --init myimg          # runs tini as PID 1; your app becomes its child
```

```dockerfile
ENTRYPOINT ["/usr/bin/tini", "--"]   # or dumb-init
CMD ["python", "-m", "myapp"]
```

An init process at PID 1 fixes both problems at once. It forwards signals to your application — which is now an ordinary child, so **the normal default dispositions apply again** — and it reaps orphaned zombies in its main loop. In Kubernetes there is no `--init` flag; either bake tini into the image or handle signals yourself.

Handling it yourself is a few lines, and it is what a well-behaved service does regardless:

```python
import signal, threading

_draining = threading.Event()

def _on_term(signum, frame):
    _draining.set()          # flip a flag. NEVER do work in a signal handler.

signal.signal(signal.SIGTERM, _on_term)
signal.signal(signal.SIGINT, _on_term)
```

Two rules that catch people. **Do the minimum in the handler** — set a flag and return; the handler runs on an arbitrary thread at an arbitrary point and anything non-reentrant can deadlock there. And **make sure the signal reaches your process at all**: `ENTRYPOINT python app.py` in *shell form* runs `/bin/sh -c "python app.py"`, so **`sh` is PID 1**, `sh` does not forward signals to its child, and your handler is never called no matter how correct it is. Always use exec form — `ENTRYPOINT ["python", "app.py"]`. This one line has caused more "my SIGTERM handler doesn't work" incidents than every other cause combined.

### Production rules

- **Drop all capabilities, add back what you proved you need.** Most services need none.
- **Run as a non-root uid**, and set `runAsNonRoot: true` so a regression is caught at admission rather than in production.
- **Read-only root filesystem, with explicit writable volumes.** It hardens you and it documents where you write.
- **Always set a memory limit; set requests equal to limits for latency-sensitive services.** Be sparing with CPU limits and graph throttling when you use them.
- **Handle `SIGTERM`, and use an init if your app spawns child processes.** Verify the signal actually arrives — check that PID 1 is your process, not `sh`.
- **Never `--privileged`.** Name the one capability instead.
- **Keep write-heavy paths off the overlay.** Every first write to an image file copies the whole file.

## Think about it

1. A colleague argues that because their container runs as `--user 10001` and drops all capabilities, a kernel privilege-escalation vulnerability is not a concern for them. Using the shared-kernel argument from the first diagram, say precisely what their mitigations do and do not buy, and name the class of deployment that would actually change the answer.
2. Your image is 1.2 GB. A `RUN` step deletes a 400 MB dataset that an earlier `RUN` downloaded, and the image is still 1.2 GB. Explain the mechanism in terms of whiteouts, then give two different build-time fixes and say what each costs you.
3. A service has a p99 of 40 ms most of the time and 900 ms in bursts, with CPU utilisation graphs that never exceed 55%. `nr_throttled` is climbing. Explain how both facts can be true simultaneously, and work out what `cpu.max` would need to say for a 4-thread service to be throttled while averaging 55%.
4. You add an init process (`--init`) to fix zombie accumulation. A colleague says this also makes your graceful shutdown correct, since tini forwards `SIGTERM`. Under what circumstances are they right, and under what circumstances does the deploy still sever in-flight requests? What would you have to check in the application to know which case you are in?
5. Your CI runs `docker build` inside a Kubernetes pod and fails with EPERM. You have three options: mount the node's container socket, run the build pod privileged, or switch to a userspace builder. Rank them by blast radius if the build job is compromised, and explain what each one does to the `CAP_SYS_ADMIN` requirement that caused the error.

## Key takeaways

- **There is no container object in Linux.** There is a process plus namespaces (what it sees), cgroups (what it may use), a layered root filesystem (what it thinks its disk is) and a reduced capability set (what root means). Measured from inside: 8 namespace kinds, all inherited by a `fork()` child **8 of 8**, because `fork()` copies a process and not its namespace membership. **The kernel is shared** — that, not any flag, is the difference between a container and a VM.
- **Root in a container is not root.** `CapEff = 0x00000000a80425fb` decodes to **14 of 41 capabilities held, 27 dropped**, and all six `unshare()` calls fail with **EPERM (errno 1)** as uid 0 — which is exactly why image builds fail inside unprivileged CI containers. `CLONE_NEWUSER` failed too, despite needing no capability, with `user.max_user_namespaces = 31735`: **seccomp is a second, independent gate**, and `--privileged` disables both plus AppArmor plus device isolation.
- **Copy-up costs the whole file, not the write.** Appending one byte to a 40 MB file in a lower layer moved **41,943,040 bytes — a write amplification of 41,943,040×**, exact because it is the file size. The copy took ~10.5 ms warm; the next write to that file took **0.01 ms**. It is paid **once per file, per container**, and it scales with file size, so one byte into a 5 GB file copies 5 GB. Write-heavy paths belong in a volume.
- **Deleting in a layer does not delete.** `rm libc.so` wrote a `.wh.libc.so` whiteout: the merged view went from **13 entries to 12** while the file stayed on disk below, all **1.4 MB**. This is why `RUN rm -rf /secrets` neither shrinks the image nor removes the secret — anyone who pulls it can read the lower layer.
- **CPU throttles, memory kills, and page cache counts.** Over `cpu.max` the scheduler stops you until the next 100 ms window: pure latency, no error, no log — visible only as `nr_throttled` in `cpu.stat`. Over `memory.max` the OOM killer sends an uncatchable `SIGKILL` and you get **exit 137** with nothing in your logs. And **page cache is charged to your cgroup**: writing and reading a 64 MB file grew `memory.current` by **65.9 MB, 103% of the file**, while the heap never moved — which is how a service whose profiler says 180 MB dies at a 512 MB limit.
- **PID 1 has no default signal handlers and inherits every orphan.** With no handler installed, `SIGTERM` is *discarded* for PID 1 (`pid_namespaces(7)`) — measured: the ignoring server kept admitting work for the full grace period, died to `SIGKILL` at **1001 ms with exit 137**, and still severed **8** in-flight requests; a handler that flips a drain flag severed **0** and exited **0** in ~200 ms. At 40 pods and 12 deploys a day that is **3,840 severed connections** that never appear in your error rate, because a TCP reset is not a 5xx. Six unreaped children also sat in state **`Z`**, holding pids until one `waitpid()` each released them.

Next: [Images, Layers & the Reproducible Build](../03-images-layers-and-builds/) — you have now built the layer stack a container runs on; the next question is where those layers come from, why build order decides your cache hit rate, and how to make the same source produce the same bytes twice.
