---
name: checklist-container-runtime-spec
description: Review a container spec against what a container actually is — isolation boundaries you did not mean to remove, cgroup limits that throttle versus kill, copy-up and layer traps in the filesystem, capabilities and seccomp, and the PID 1 rules that decide whether a deploy severs connections.
phase: 10
lesson: 02
---

# The container spec — pre-ship review

Run this before a container takes production traffic, and again whenever you change the
base image, add a flag to make an error go away, or start writing to a new path.
Every item exists because skipping it has caused a real outage or a real leak.

The four things a container actually is: **namespaces** (what it can see), **cgroups**
(what it may use), a **layered root filesystem** (what it thinks its disk is), and a
**reduced capability set** (what root means). Everything below is one of those four.

## 1 · The boundary you have, and the one you do not

- [ ] Everyone on the team can state the boundary correctly: **the host kernel is shared.**
      Every syscall from every container is executed by the same kernel binary. A kernel
      CVE is your CVE, patched hardening or not.
- [ ] Anything running genuinely untrusted code (customer-supplied builds, multi-tenant
      execution, sandboxed plugins) is on a **hypervisor or userspace-kernel boundary** —
      Firecracker, Kata, gVisor — not on namespaces alone.
- [ ] No `--pid host`, `--ipc host`, `--uts host`, `--userns host` (K8s: `hostPID`,
      `hostIPC`, `hostNetwork`, `hostUsers`) unless there is a named reason in the manifest.
      Each one **removes** a boundary; none of them add anything.
- [ ] `--network host` in particular is reviewed by a human. You gain a few microseconds
      and lose port isolation, the container's own firewall rules, and the ability to run
      two copies on one node.
- [ ] `shareProcessNamespace` is understood as deliberate: useful for debug sidecars,
      because the sidecar can then see and `exec` against the main container's processes.
- [ ] Nobody believes `fork()` creates isolation. A forked child inherits **8 of 8**
      namespaces. Isolation comes from `clone()` with `CLONE_NEW*` flags at start-up,
      and from nothing else.

## 2 · cgroup limits — one throttles, one kills

```text
exceed cpu.max     -> THROTTLED. no error, no exception, no log line. pure latency.
exceed memory.max  -> KILLED.    uncatchable SIGKILL, exit 137 (128+9), no log line.
```

- [ ] **Every container has a memory limit.** An unlimited container that leaks evicts its
      neighbours and can take the node down with it.
- [ ] `requests.memory == limits.memory` for anything latency-sensitive. In Kubernetes that
      is the `Guaranteed` QoS class — last in line for eviction rather than first.
- [ ] The team knows **requests are for the scheduler and limits are for the kernel**.
      Requests decide which node you land on and reserve nothing at runtime; limits are
      written verbatim into the cgroup files (`--cpus 1.5` becomes `cpu.max = 150000 100000`,
      i.e. 150 ms of CPU per 100 ms window summed across all your threads).
- [ ] **CPU limits are set sparingly and reviewed.** A limit that clips a bursty service
      produces latency indistinguishable from a slow dependency, visible in none of your
      application's own instrumentation. Many mature teams set CPU requests and no CPU limit.
- [ ] `container_cpu_cfs_throttled_periods_total` (`nr_throttled` in `cpu.stat`) is graphed
      **next to p99**. Rising throttling plus a latency complaint plus idle-looking CPU
      graphs is one of the highest-value signals in container operations, and almost nobody
      graphs it.
- [ ] The memory limit is sized from **`memory.peak` under real load**, never from a heap
      profiler. Page cache is charged to your cgroup: this lesson measured writing and
      reading back a 64 MB file growing `memory.current` by **65.9 MB — 103% of the file** —
      while the Python heap did not move, and dropping straight back when the file was
      deleted.
- [ ] Any service that streams large files (CSV imports, media, backups, log shipping) has
      had that page-cache headroom explicitly added to its limit.
- [ ] `pids.max` is set. It is the fork-bomb fuse, and it is also what turns a slow zombie
      leak into a bounded failure instead of a node-wide one.
- [ ] Exit **137** is recognised on sight as OOM-kill and **143** as a plain SIGTERM
      death (128+9 and 128+15). Both are in the runbook by number.

## 3 · The filesystem — copy-up, whiteouts, and where you write

- [ ] You can name **every path the service writes to**, from memory. If you cannot, you do
      not know where your copy-ups are.
- [ ] `--read-only` / `readOnlyRootFilesystem: true`, with explicit writable mounts. This is
      the highest-value-per-character hardening flag there is: it stops an attacker writing
      a binary or editing your code, and it forces the knowledge in the item above.
- [ ] Explicit scratch: `--tmpfs /tmp:rw,noexec,nosuid,size=64m`.
- [ ] **Every write-heavy path is a volume, not the overlay.** Databases, caches, uploads,
      unpacked archives, log files. A volume is a bind mount over the merged view — writes
      go straight to the host filesystem with no copy-up and no layer growth.
- [ ] No file that ships in the image is written in place. The first write copies the
      **entire file**: measured here at **41,943,040 bytes moved to change 1 byte** of a
      40 MB file, ~10.5 ms warm, versus **0.01 ms** for the next write once it lives in
      upper. It scales with file size, not write size — one byte into a 5 GB file copies
      5 GB — and is paid once per file per container.
- [ ] "The first request after a deploy is slow and the rest are fine" is investigated as a
      copy-up before it is investigated as a JIT or cache warm-up.
- [ ] **No secret has ever existed in any layer.** `RUN rm -rf /secrets` writes a whiteout
      in a *new* layer; the earlier layer still contains the file, is still pushed, and is
      readable by anyone who pulls the image. Measured: `rm libc.so` took the merged view
      from **13 entries to 12** while all **1.4 MB** stayed on disk below.
- [ ] Therefore: build-time secret mounts (`RUN --mount=type=secret`) or a multi-stage build
      that leaves the secret behind. A later `rm` is not a fix and never was.
- [ ] Duplicate paths across layers are known about. A shadowed file is invisible to every
      process and still downloaded, stored, and paid for on every pull.

## 4 · Capabilities, seccomp, and the user

- [ ] `--cap-drop ALL` / `capabilities: drop: ["ALL"]` is the starting point, always, and
      capabilities are added back **only after you proved you need them**.
- [ ] Most services need **zero** capabilities. Bind above 1024 and let the load balancer
      map 443, rather than granting `CAP_NET_BIND_SERVICE`.
- [ ] `runAsNonRoot: true` plus an explicit `runAsUser`, so a regression to root is caught
      at admission rather than in production. The uid must exist in the image.
- [ ] `allowPrivilegeEscalation: false` / `--security-opt no-new-privileges`.
- [ ] `seccompProfile: type: RuntimeDefault` is set **explicitly** — it is not the default
      in older clusters, and it is a second, independent gate from capabilities. Proof they
      are independent: `CLONE_NEWUSER` needs no capability on a modern kernel and still
      failed with EPERM here, with `user.max_user_namespaces = 31735` showing the kernel was
      willing and `Seccomp: filter (BPF), 1 filter installed` showing what was not.
- [ ] **No `--privileged`. Anywhere.** It is not a convenience flag; it grants all
      capabilities, disables seccomp, relaxes AppArmor/SELinux and exposes host devices in
      one switch. When you reach for it, the question is always "which *one* capability?"
      (`CAP_NET_ADMIN` for a VPN sidecar, `CAP_SYS_PTRACE` for a profiler — both one
      `--cap-add`.)
- [ ] Image builds in CI do **not** solve EPERM by mounting the node's container socket or
      running privileged — both hand the host away. Use a userspace builder (Kaniko,
      rootless Buildah, rootless BuildKit) that never calls `mount()`.
- [ ] Where the platform supports it, the runtime itself is rootless, so an escape lands on
      an unprivileged account rather than host root. Known costs: no ports below 1024
      without extra setup, slower userspace networking, some storage drivers unavailable.

## 5 · PID 1 — the process that is not like the others

Two kernel behaviours nothing warns you about: **PID 1 gets no default signal
dispositions** (an unhandled signal is silently *discarded*, `pid_namespaces(7)`), and
**PID 1 inherits every orphan** and must reap them.

- [ ] `ENTRYPOINT` is in **exec form**: `ENTRYPOINT ["python", "app.py"]`. Shell form runs
      `/bin/sh -c "..."`, so `sh` is PID 1, `sh` does not forward signals, and your handler
      is never called no matter how correct it is. This single line has caused more
      "my SIGTERM handler doesn't work" incidents than every other cause combined.
- [ ] You have **verified** which process is PID 1 in the running container, rather than
      assuming. `ps` inside it, or read `/proc/1/cmdline`.
- [ ] A `SIGTERM` handler is installed, and it **only flips a flag**. Never do work in a
      signal handler — it runs on an arbitrary thread at an arbitrary point and anything
      non-reentrant can deadlock there.
- [ ] The flag actually causes the service to **stop admitting new work**. A handler that
      does not is worse than none: the measured "ignore SIGTERM" case kept accepting
      requests for the full grace period, was SIGKILLed at **1001 ms with exit 137**, and
      still severed **8** in-flight requests — buying nothing but a slower rollout
      (**235 ms → 1001 ms per pod, 4.3x**). The handler version severed **0** and exited
      **0** in ~235 ms under identical load.
- [ ] The full drain sequence is implemented, not just the handler — fail readiness, wait
      for the load balancer to notice, then stop accepting, then drain. None of it runs at
      all unless the handler exists.
- [ ] **An init runs at PID 1 if your service ever spawns a child process** — `docker run
      --init`, or tini/dumb-init as `ENTRYPOINT`. There is no `--init` in Kubernetes; bake
      it in. An init forwards signals (making your app an ordinary child whose POSIX
      defaults apply again) and reaps orphans in its main loop.
- [ ] Zombie accumulation is monitored: state `Z` in `ps`, or `pids.current` against
      `pids.max`. Measured: six children that exit with no `wait()` sit in state `Z` and
      push `pids.current` from 16 to 22; one `waitpid()` each returns it to 0 and 16.
      Nothing is running — which is why memory and CPU graphs stay flat while it leaks.
- [ ] The team knows that **severed connections do not appear in your error rate.** The
      client gets a TCP reset; you generated no response, so your middleware recorded
      nothing. At 8 severed per pod, 40 pods, 12 deploys a day, that is **3,840 dropped
      connections daily** and a completely clean dashboard.

## 6 · Anti-patterns to grep for

- [ ] `--privileged`, or `privileged: true`, in any manifest.
- [ ] Shell-form `ENTRYPOINT` or `CMD` on the process that must handle signals.
- [ ] A `RUN rm` of anything sensitive, at any point in a Dockerfile.
- [ ] A SQLite file, cache, index or log path that lives inside the image rather than a volume.
- [ ] A container with a CPU limit and no throttling metric on any dashboard.
- [ ] A container with no memory limit at all.
- [ ] `hostNetwork`, `hostPID` or `hostIPC` with no comment explaining why.
- [ ] A memory limit derived from a heap profile.
- [ ] `subprocess`/`exec` calls in a service whose PID 1 is the application itself.
- [ ] `no-new-privileges` and `seccompProfile` absent from a security context that otherwise
      looks well-hardened — the two most commonly forgotten lines.

> ## Decision shortcuts
>
> **"Does this flag add isolation or remove it?"**
> `--pid host`, `--network host`, `--privileged`, `--userns host` all remove. There is no
> flag that adds a boundary; there is only choosing a different runtime.
>
> **"What happens when we exceed this limit?"**
> CPU → throttled, silently, as latency. Memory → killed, uncatchably, exit 137.
> Set the memory one always; set the CPU one carefully and graph it.
>
> **"Will this write copy a file?"**
> If the path came from the image, yes — the whole file, once. Put it in a volume.
>
> **"Who is PID 1, and does it forward signals and reap children?"**
> If the answer is `sh`, nothing downstream of it works. If the answer is your app and it
> spawns children, you have a zombie leak with a nine-day fuse.
