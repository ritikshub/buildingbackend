# Reading the Machine

> `top`, `vmstat`, `free` and `iostat` are the same program: read a counter from `/proc`, wait one second, read it again, divide. This lesson rebuilds all four that way, then generates each kind of load on purpose so every number moves: ten CPU burners push `us` to **89.8%** and the run queue to **11**, an `fsync` loop pushes the disk to **71% util** at **3,536 writes/s**, a 300 MiB hog drops `MemAvailable` by **303 MiB**, an open-file loop dies at exactly the soft limit with `EMFILE`, and a 200 MiB process inside a 64 MiB cgroup is killed by the kernel with `Memory cgroup out of memory: Killed process` in the log and `Result: oom-kill` in `systemctl status`.

## The Problem

"The server is slow." That sentence has at most five causes: the CPU is saturated, memory is exhausted, the disk cannot keep up, the network is dropping or queueing, or the process has run out of a limit like file descriptors. Everything else ("the database is slow", "the API is slow") is one of those five on some machine. And the tools that tell you which are on every box already, because they only read `/proc`.

The problem is that the tools print thirty numbers and people read two of them wrong. `free` says the RAM is gone when it is not. Load average is compared to nothing. `%CPU` in `ps` is an average since the process started. `iowait` is counted as idle. `EMFILE` shows up as "the server stopped accepting connections" with the CPU pegged. And when the kernel kills a process for memory, the only record is one line in a log most people never open. This lesson is the five resources, the three questions to ask of each, the number that answers each question, and where it comes from.

## The Concept

### Every monitoring tool is two reads and a subtraction

The kernel keeps **counters**: CPU ticks spent in user code, in the kernel, idle, waiting for I/O; bytes written to each disk; pages swapped; context switches. It never computes a rate. `vmstat 1` reads `/proc/stat`, sleeps a second, reads it again, and prints the difference. `iostat` does it with `/proc/diskstats`, `top` with `/proc/stat` and every `/proc/<pid>/stat`, `sar` with all of them. That is why the first line of `vmstat` and `iostat` is meaningless (an average since boot) and why `ps`'s `%CPU` lies about a process that was busy an hour ago.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 400" width="100%" style="max-width:880px" font-family="'JetBrains Mono', ui-monospace, monospace" role="img" aria-label="The mechanism behind every rate a monitoring tool prints. The kernel keeps monotonically increasing counters in /proc: /proc/stat has CPU ticks by category, context switches and procs running; /proc/diskstats has reads, writes, sectors and milliseconds in I/O per device; /proc/vmstat has pages swapped in and out; /proc/net/dev has bytes per interface. A tool reads a counter, sleeps an interval, reads it again, and divides the difference by the interval. Examples: CPU user percent is the change in user ticks over the change in all ticks; disk utilisation is milliseconds in I/O over the interval; writes per second is the change in writes completed over the interval; swap out per second is the change in pswpout over the interval. Notes: the first line of vmstat and iostat is an average since boot and is meaningless; ps percent CPU is CPU time over the process lifetime, top's is over the last refresh; load average is different, an exponentially damped average the kernel computes itself of tasks runnable or in D state.">
  <defs>
    <marker id="p1l12a-ar" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker>
  </defs>
  <text x="450" y="26" text-anchor="middle" font-size="14.5" font-weight="700" fill="currentColor">Two reads and a subtraction: how a counter in /proc becomes a number on a dashboard</text>
  <rect x="40" y="52" width="300" height="150" rx="10" fill="#0fa07f" fill-opacity="0.10" stroke="#0fa07f" stroke-width="1.8" stroke-linejoin="round"/>
  <text x="190" y="74" text-anchor="middle" font-size="10.5" font-weight="700" fill="#0fa07f">THE KERNEL'S COUNTERS (only ever go up)</text>
  <g font-size="8.5" fill="currentColor">
    <text x="56" y="96">/proc/stat        cpu: user nice system idle iowait irq softirq steal</text>
    <text x="56" y="110">                  ctxt (context switches) · procs_running · procs_blocked</text>
    <text x="56" y="124">/proc/diskstats   per device: reads, writes, sectors, ms spent in I/O</text>
    <text x="56" y="138">/proc/vmstat      pswpin pswpout pgpgin pgpgout (pages)</text>
    <text x="56" y="152">/proc/net/dev     bytes and packets per interface, errors, drops</text>
    <text x="56" y="166">/proc/PID/stat    utime stime per process</text>
    <text x="56" y="188" opacity="0.75">a snapshot says nothing about "now"; only a difference does</text>
  </g>
  <rect x="380" y="52" width="180" height="150" rx="10" fill="#c94a12" fill-opacity="0.10" stroke="#c94a12" stroke-width="1.8" stroke-linejoin="round"/>
  <text x="470" y="74" text-anchor="middle" font-size="10.5" font-weight="700" fill="#c94a12">THE TOOL</text>
  <g text-anchor="middle" font-size="8.5" fill="currentColor">
    <text x="470" y="98">a = read()</text>
    <text x="470" y="114">sleep(interval)</text>
    <text x="470" y="130">b = read()</text>
    <text x="470" y="150" font-weight="700">rate = (b - a) / interval</text>
    <text x="470" y="172" opacity="0.75">vmstat, iostat, top, sar,</text>
    <text x="470" y="186" opacity="0.75">and every agent in Phase 10</text>
  </g>
  <rect x="600" y="52" width="270" height="150" rx="10" fill="#7c5cff" fill-opacity="0.10" stroke="#7c5cff" stroke-width="1.8" stroke-linejoin="round"/>
  <text x="735" y="74" text-anchor="middle" font-size="10.5" font-weight="700" fill="#7c5cff">WHAT COMES OUT</text>
  <g font-size="8.5" fill="currentColor">
    <text x="616" y="98">%us  = Δuser / Δ(all ticks) × 100</text>
    <text x="616" y="114">%wa  = Δiowait / Δ(all ticks) × 100</text>
    <text x="616" y="130">util = Δ(ms in I/O) / interval_ms × 100</text>
    <text x="616" y="146">w/s  = Δwrites / interval</text>
    <text x="616" y="162">so   = Δpswpout / interval</text>
    <text x="616" y="178">cs   = Δctxt / interval</text>
    <text x="616" y="194" opacity="0.75">the Build It script prints all of these</text>
  </g>
  <g fill="none" stroke="currentColor" stroke-width="1.6">
    <path d="M342 127 L376 127" marker-end="url(#p1l12a-ar)"/>
    <path d="M562 127 L596 127" marker-end="url(#p1l12a-ar)"/>
  </g>
  <rect x="40" y="226" width="830" height="110" rx="10" fill="#e0930f" fill-opacity="0.08" stroke="#e0930f" stroke-width="1.6" stroke-linejoin="round"/>
  <text x="455" y="248" text-anchor="middle" font-size="10" font-weight="700" fill="#e0930f">THREE THINGS THAT FOLLOW</text>
  <g font-size="8.5" fill="currentColor">
    <text x="56" y="270">1 · the first line of vmstat and iostat is the average since boot: ignore it, read the second and later (vmstat 1 5)</text>
    <text x="56" y="288">2 · ps %CPU is CPU time divided by the process's whole lifetime; top's %CPU is over its last refresh. During an incident, top is right</text>
    <text x="56" y="306">3 · load average is the exception: the kernel computes it, as a damped average of tasks that are runnable OR in D state</text>
    <text x="56" y="324" opacity="0.8">    so it counts CPU demand and disk stalls together, and it lags: a 1-minute average needs a minute to reflect a change</text>
  </g>
  <text x="450" y="368" text-anchor="middle" font-size="10.5" fill="currentColor" opacity="0.9">Once you know which counter a number came from, you know what it can and cannot tell you.</text>
  <text x="450" y="388" text-anchor="middle" font-size="9.5" fill="currentColor" opacity="0.72">Phase 10's metrics are these counters shipped somewhere and graphed; the subtraction happens in the query.</text>
</svg>
```

### The three questions, per resource

Ask the same three things of each resource, in order. **Utilisation**: how busy is it? **Saturation**: how much work is queued because it is busy? **Errors**: is it failing outright? Utilisation at 100% is not by itself a problem (a CPU doing useful work is what you paid for); saturation is, because queued work is latency. The runbook is this table applied; the rest of the concept section is the number behind each cell.

| resource | utilisation | saturation | errors |
|---|---|---|---|
| CPU | `%us + %sy` (`vmstat`, `top`) | run queue `r` vs CPUs; load / CPUs; `/proc/pressure/cpu` | `dmesg` hard-lockups, `st` stolen time |
| memory | `MemAvailable` (`free`) | swap `si`/`so`; `/proc/pressure/memory` | the OOM killer in `dmesg` / `journalctl -k` |
| disk | `%util`, `r/s`, `w/s`, MB/s (`iostat -x`) | `aqu-sz`, `await`; `%wa`; `/proc/pressure/io` | I/O errors in `dmesg`, SMART |
| network | bytes/s vs link (`ip -s link`) | accept-queue overflows, retransmits (`ss`, `nstat`) | drops, errors (`ip -s link`) |
| descriptors | open vs limit (`/proc/PID/fd`, `ulimit -n`) | `EMFILE` in the log | `Too many open files` |

### CPU: what the split means

`vmstat` and `top` divide CPU time into columns. `us` is your code. `sy` is the kernel working on your behalf: syscalls (lesson 01), the network stack, page faults; a high `sy` with a low `us` is a program that makes too many small requests. `id` is idle. `wa` is the one people misread: **idle, but with a task waiting for disk I/O**, so a high `wa` means the disk is the bottleneck and the CPU is a bystander. `st` is time the hypervisor gave to someone else's VM; on a cloud instance it means noisy neighbours or an oversold host, and nothing on your box can fix it.

Saturation is the **run queue**, `r` in `vmstat`, the number of tasks that are runnable right now, and it is meaningful only next to the CPU count. So is **load average**, which the kernel computes as a damped one-, five- and fifteen-minute average of tasks that are runnable or in state `D`. Divide it by `nproc`: under 1 is headroom, over 1 sustained is queueing, and because `D` counts, a disk stall raises it too. The **Build It** script forks ten busy loops on a ten-CPU sandbox:

```console
   10 CPU burners: r 11  us 89.8%  id 10.1%   load now 0.90 (it lags: a 1-minute average needs a minute)
```

Eleven runnable tasks on ten CPUs, 90% user time, and a load average that has not caught up yet: the run queue is the instant picture, the load average is the trend. Inside a container add one check: `cat /sys/fs/cgroup/cpu.max` may say the process gets two CPUs while `nproc` says ten (Phase 11, lesson 01), and `cpu.stat` counts how often it was throttled.

### Memory: available, not free, and who dies

Lesson 02 gave you the rule and this lesson depends on it: **`MemAvailable`** (the `available` column of `free`) is what a new process could get, because the page cache is reclaimable and counted; `MemFree` is only what nobody has touched and is nearly zero on any healthy box after an hour. Saturation is **swapping in progress**: `si` and `so` in `vmstat` non-zero for several consecutive seconds means the kernel is moving pages to disk and back to keep everyone running, and everything gets slow together. A little swap *used* and stable is fine (old pages evicted once); swap *traffic* is not.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 430" width="100%" style="max-width:880px" font-family="'JetBrains Mono', ui-monospace, monospace" role="img" aria-label="Two panels. Left: the memory of the sandbox as a bar of 8,004 MiB split into used by processes, 3,617; page cache and buffers, 1,142; and free, 3,747; with a bracket showing that available, 4,338, spans free plus most of the cache, because cache can be dropped on demand. A note: read available, not free. Right: what happens when available reaches zero. First the kernel reclaims cache, then swaps if there is swap, then, if still short, the OOM killer runs: it ranks every process by oom_score, roughly its share of RAM adjusted by oom_score_adj, and sends SIGKILL to the highest. The record is one line in the kernel log: Out of memory: Killed process PID name total-vm anon-rss. Inside a cgroup with memory.max, the same thing happens to that cgroup alone when it exceeds its limit, unless swap absorbs it; systemd reports Result oom-kill and journalctl says a process of this unit has been killed by the OOM killer. OOMScoreAdjust in a unit moves a service up or down the list.">
  <defs>
    <marker id="p1l12b-ar" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker>
  </defs>
  <text x="450" y="26" text-anchor="middle" font-size="14.5" font-weight="700" fill="currentColor">Memory: what "available" spans, and what the kernel does when it runs out</text>
  <rect x="40" y="52" width="400" height="200" rx="10" fill="#0fa07f" fill-opacity="0.08" stroke="#0fa07f" stroke-width="1.7" stroke-linejoin="round"/>
  <text x="240" y="74" text-anchor="middle" font-size="10" font-weight="700" fill="#0fa07f">free -m ON THE SANDBOX · 8,004 MiB total</text>
  <rect x="60" y="96" width="171" height="34" fill="#c94a12" fill-opacity="0.35" stroke="#c94a12" stroke-width="1.2"/>
  <rect x="231" y="96" width="54" height="34" fill="#e0930f" fill-opacity="0.35" stroke="#e0930f" stroke-width="1.2"/>
  <rect x="285" y="96" width="135" height="34" fill="#7f7f7f" fill-opacity="0.18" stroke="#7f7f7f" stroke-width="1.2"/>
  <g text-anchor="middle" font-size="8" fill="currentColor">
    <text x="145" y="117">used 3,617</text>
    <text x="258" y="117">cache 1,142</text>
    <text x="352" y="117">free 3,747</text>
  </g>
  <path d="M238 148 L420 148" fill="none" stroke="#0fa07f" stroke-width="2.2"/>
  <path d="M238 142 L238 154 M420 142 L420 154" fill="none" stroke="#0fa07f" stroke-width="2.2"/>
  <text x="329" y="168" text-anchor="middle" font-size="9" font-weight="700" fill="#0fa07f">available 4,338 = free + reclaimable cache</text>
  <g font-size="8.5" fill="currentColor">
    <text x="56" y="196">read available. free is nearly zero on any healthy box after an hour</text>
    <text x="56" y="212">a process needing RAM makes the kernel drop cache first; that costs a</text>
    <text x="56" y="226">re-read later, not a failure. swap traffic (si/so in vmstat) is the</text>
    <text x="56" y="240">next stage, and it is the one that makes everything slow at once</text>
  </g>
  <rect x="470" y="52" width="400" height="330" rx="10" fill="#d64545" fill-opacity="0.06" stroke="#d64545" stroke-width="1.7" stroke-linejoin="round"/>
  <text x="670" y="74" text-anchor="middle" font-size="10" font-weight="700" fill="#d64545">WHEN AVAILABLE REACHES ZERO</text>
  <g stroke-linejoin="round" stroke-width="1.4">
    <rect x="490" y="90" width="360" height="34" rx="7" fill="#7f7f7f" fill-opacity="0.12" stroke="#7f7f7f"/>
    <rect x="490" y="136" width="360" height="34" rx="7" fill="#e0930f" fill-opacity="0.12" stroke="#e0930f"/>
    <rect x="490" y="182" width="360" height="70" rx="7" fill="#d64545" fill-opacity="0.12" stroke="#d64545" stroke-width="1.8"/>
  </g>
  <g font-size="8.5" fill="currentColor">
    <text x="500" y="104" font-weight="700">1 · reclaim</text><text x="580" y="104">drop clean page cache; write out dirty pages first</text>
    <text x="500" y="118" opacity="0.75">    free of charge except the re-reads</text>
    <text x="500" y="150" font-weight="700">2 · swap</text><text x="580" y="150">move idle anonymous pages to disk (if there is swap)</text>
    <text x="500" y="164" opacity="0.75">    si/so climb; latency everywhere; vm.swappiness tunes eagerness</text>
    <text x="500" y="198" font-weight="700" fill="#d64545">3 · the OOM killer</text><text x="640" y="198">rank every process by oom_score</text>
    <text x="500" y="212">    ≈ share of RAM, shifted by oom_score_adj (-1000 .. +1000)</text>
    <text x="500" y="226">    SIGKILL the highest. It never sees it coming (lesson 10)</text>
    <text x="500" y="242" opacity="0.8">    one line in the kernel log is the only record of what happened</text>
  </g>
  <text x="500" y="272" font-size="8.5" fill="currentColor" font-weight="700">the record:</text>
  <text x="500" y="288" font-size="7.8" fill="currentColor">kernel: Memory cgroup out of memory: Killed process 2358886 (python3)</text>
  <text x="500" y="300" font-size="7.8" fill="currentColor">        total-vm:218724kB, anon-rss:65528kB, ... oom_score_adj:0</text>
  <g font-size="8.5" fill="currentColor">
    <text x="500" y="324" font-weight="700">inside a cgroup (a unit with MemoryMax=, a container):</text>
    <text x="500" y="340">the same three steps, for that group alone, at its own limit;</text>
    <text x="500" y="354">swap can absorb it unless MemorySwapMax=0. systemd shows</text>
    <text x="500" y="368">Result: oom-kill; OOMScoreAdjust= moves a unit up or down the list</text>
  </g>
  <text x="450" y="408" text-anchor="middle" font-size="10.5" fill="currentColor" opacity="0.9">Exit 137 with nobody's kill -9 in the history is this. The kernel log has the victim's name and size; nothing else does.</text>
</svg>
```

When reclaim and swap are not enough, the **OOM killer** runs: it ranks every process by `oom_score` (roughly its share of RAM, shifted by `oom_score_adj`, which a unit sets with `OOMScoreAdjust=`) and sends `SIGKILL` to the highest. The victim never sees it (lesson 10), its log ends mid-sentence with whatever was still in a buffer (lesson 07), and the only record is one line in the kernel log. **Inside a cgroup**, a unit with `MemoryMax=` or a container with a memory limit, the same thing happens to that group alone when it exceeds *its* limit. The **Use It** section does this on purpose. And one subtlety that surprised the first attempt: with swap available, the cgroup swapped its excess out instead of killing; `MemorySwapMax=0` makes the limit hard.

### Disk: utilisation, queue, and the wait column

`iostat -x 1` prints, per device, requests per second, bytes per second, the average request latency (`r_await`, `w_await`, in milliseconds), the average queue length (`aqu-sz`), and `%util`, the share of the interval in which the device had at least one request in flight. A single spindle or a cloud disk with an IOPS cap is saturated when `%util` approaches 100 and `await` climbs above its normal (well under a millisecond for NVMe, a few for a cloud volume, ten or more for spinning disks). The **Build It** `fsync` loop, which waits for the disk on every write, shows what a write-heavy database does to the numbers:

```console
   an fsync loop: wa  6.9%  bo 159828 KiB/s  b 0   vdb util 71%  w/s 3536
```

The CPU is 7% "waiting", the disk is 71% busy at 3,536 writes a second, 156 MiB/s leaving through `bo`. That is a healthy disk under a heavy writer; the same loop on a slow volume would show `util` at 100, `await` in the tens of milliseconds, and `b` (tasks blocked) above zero, which is the pattern behind "the database got slow and the CPU is idle." `dmesg` holds the errors: `I/O error`, `ata` resets, `nvme` timeouts, which no amount of tuning fixes.

### Descriptors: the limit every server hits once

A process may hold at most `RLIMIT_NOFILE` open descriptors: the **soft limit** is what applies, the **hard limit** is the ceiling it may raise the soft one to, and `ulimit -n` shows the soft one. Sockets count, so a server that accepts one connection per client stops accepting at the limit minus a handful, with `EMFILE`, `Too many open files`, and some servers then spin on `accept()` at 100% CPU, which is how a descriptor limit looks like a CPU problem. The default of 1,024 on most systems is too low for any server that holds connections; a unit raises it with `LimitNOFILE=65536`, and the **Use It** section shows the sandbox's shell has 20,480 while the systemd service got 1,024 because its unit did not say. The script lowers its own soft limit to 256 and opens files until the kernel refuses:

```console
   opened 253 more, then: errno 24 Too many open files  <- EMFILE at the soft limit (256)
```

A leak is diagnosed by counting and categorising: `ls /proc/PID/fd | wc -l` against `/proc/PID/limits`, and `ls -l /proc/PID/fd` grouped by type, where fifty `socket:` entries that never close, or hundreds of `pipe:` from subprocesses never reaped (lesson 10), name the bug.

### Pressure stall information

Kernels since 4.20 can offer a cleaner saturation signal than any of the above: `/proc/pressure/cpu`, `memory` and `io` each report the share of the last 10, 60 and 300 seconds during which **some** task was stalled waiting for that resource (and, for memory and I/O, during which **all** tasks were). One number per resource, comparable across machines, and the input Kubernetes and systemd use for eviction and oom decisions. The sandbox's kernel does not expose it, so the script says so; on a stock server kernel, it is the first thing to read.

## Build It

The script for this lesson is [`code/machine.py`](../code/machine.py). It reads the counters, computes the rates, prints what each means, and then makes them move. It runs on macOS, where it explains each section and skips the `/proc` parts; the interesting run is in the sandbox:

```bash
make shell
python3 phases/01-linux-and-the-command-line/12-reading-the-machine/code/machine.py
```

**`vmstat`** is the CPU line of `/proc/stat` twice, the context-switch counter twice, and the swap and paging counters from `/proc/vmstat` twice:

```python
def cpu_snapshot():
    for line in read("/proc/stat").splitlines():
        if line.startswith("cpu "):
            return [int(x) for x in line.split()[1:9]]       # user nice system idle iowait irq softirq steal

def cpu_percentages(a, b):
    d = [y - x for x, y in zip(a, b)]
    total = sum(d) or 1
    return {n: 100.0 * v / total for n, v in zip(["us", "ni", "sy", "id", "wa", "hi", "si", "st"], d)}
```

**`iostat`** is `/proc/diskstats` twice, with `%util` as milliseconds-in-I/O over the interval, and **`free`** is one read of `/proc/meminfo`. Idle, the sandbox reads:

```console
   r   1  b   0   si      0 so      0   bi     4814 bo       95 KiB/s   cs     2224/s   us  0.6 sy  1.3 id 97.8 wa  0.1 st  0.0
   MemTotal     8004 MiB   MemFree     3729   Cached      718   MemAvailable     4364   SwapUsed    697
   device         r/s     w/s   rMiB/s   wMiB/s  util%
   vdb              0       0      0.0      0.0    0.0
```

**The limit** is `resource.getrlimit`, then a loop that opens `/dev/null` until it cannot; **the load** is ten forked busy loops, a child that writes and `fsync`s in a loop while the parent samples, and a `bytearray` of 300 MiB touched page by page so the kernel really allocates it:

```console
   10 CPU burners: r 11  us 89.8%  id 10.1%   load now 0.90 (it lags: a 1-minute average needs a minute)
   an fsync loop: wa  6.9%  bo 159828 KiB/s  b 0   vdb util 71%  w/s 3536
   a 300 MiB hog: MemAvailable 4314 -> 4012 MiB (-303); this process RSS 311 MiB
   /proc/self/oom_score = 678: the kernel's ranking of who dies first if RAM runs out (bigger = sooner)
```

Three hundred megabytes allocated, three hundred and three fewer available, and an `oom_score` that went up accordingly. Every line was two reads and a subtraction.

## Use It

The standard tools on the same sandbox, idle and then under load. `top`'s header, `vmstat`, `free` and `iostat` at rest:

```console
$ uptime;  nproc
 04:45:25 up 3 days,  5:50,  0 users,  load average: 1.50, 0.84, 0.74
10
$ vmstat 1 3
procs -----------memory---------- ---swap-- -----io---- -system-- -------cpu-------
 r  b   swpd   free   buff  cache   si   so    bi    bo   in   cs us sy id wa st gu
 1  0 713952 3835036    156 1169604  440 1075  2979  2253 1252    1  4  1 94  0  0  0     <- since boot: ignore
 0  0 713952 3831256    156 1173316    0    0  3580    76  678  907  0  0 99  0  0  0
 1  0 713952 3829660    156 1173320    0    0     0     0  448  451  0  0 99  0  0  0
$ free -h
               total        used        free      shared  buff/cache   available
Mem:           7.8Gi       3.6Gi       3.7Gi       351Mi       1.1Gi       4.2Gi
Swap:          8.8Gi       697Mi       8.1Gi
```

Four busy loops for eight seconds, and the three views of the same fact: `vmstat`'s run queue and `us`, the load average starting to climb, and `top` naming the four:

```console
$ for i in 1 2 3 4; do python3 -c 'import time; t=time.time()+8
while time.time()<t: pass' & done;  sleep 3
$ vmstat 1 2 | tail -1;  cat /proc/loadavg
 4  0 713952 3821132    156 1184300    0    0     0     0 4697  662 40  0 60  0  0  0
2.40 1.06 0.81 5/731 25
$ top -bn1 -o %CPU | head -12 | tail -5
    PID USER      PR  NI    VIRT    RES    SHR S  %CPU  %MEM     TIME+ COMMAND
     18 root      20   0   12768   8388   5104 R 100.0   0.1   0:04.20 python3
     19 root      20   0   12768   8408   5144 R 100.0   0.1   0:04.21 python3
     20 root      20   0   12768   8324   5056 R 100.0   0.1   0:04.20 python3
     21 root      20   0   12768   8420   5140 R 100.0   0.1   0:04.19 python3
```

`r` is 4, `us` is 40% of ten CPUs, four processes at 100% each. A 600 MiB hog and the columns that notice it:

```console
$ free -m | head -2                                   # before, then during
Mem:            8004        3661        3721         351        1172        4342
Mem:            8004        4264        3118         351        1172        3739
$ ps -o pid,rss,vsz,cmd --sort=-rss | head -2
    PID   RSS    VSZ CMD
     43 622972 627172 python3 -c  import time b = bytearray(600 * 2**20) ...
$ echo "oom_score: $(cat /proc/43/oom_score)  oom_score_adj: $(cat /proc/43/oom_score_adj)"
oom_score: 666  oom_score_adj: 0
```

Descriptors, the limits, and what a leaky process holds, categorised:

```console
$ ulimit -n;  ulimit -Hn;  cat /proc/sys/fs/file-nr
20480
1048576
2941    0       9223372036854775807
$ (ulimit -n 64;  python3 -c 'import os
fds = []
try:
    while True: fds.append(os.open("/dev/null", os.O_RDONLY))
except OSError as e: print("opened", len(fds), "then", e)')
opened 61 then [Errno 24] Too many open files: '/dev/null'
$ ls -l /proc/$P/fd | awk '{print $NF}' | sed 's/:.*//' | sort | uniq -c | sort -rn | head -3     # a process holding 50 sockets
     50 socket
      2 pipe
      1 /dev/null
$ ulimit -a | grep -E 'open files|processes'
open files                          (-n) 20480
```

And the one that has no substitute: a real OOM kill, on the booted `systemd` box from lesson 11, with a unit limited to 64 MiB running a process that wants 200:

```console
$ cat /etc/systemd/system/hog.service
[Service]
ExecStart=/usr/bin/python3 -c "import time; b = bytearray(200 * 2**20); ..."
MemoryMax=64M
MemorySwapMax=0
$ systemctl start hog;  sleep 2;  systemctl status hog | grep -E 'Active|Main PID|OOM'
     Active: failed (Result: oom-kill) since Sat 2026-09-05 04:46:22 UTC; 1s ago
   Main PID: 1175 (code=killed, signal=KILL)
Sep 05 04:46:22 0970caef98b3 systemd[1]: hog.service: A process of this unit has been killed by the OOM killer.
$ systemctl show hog -p Result,ExecMainStatus
Result=oom-kill
ExecMainStatus=9
$ journalctl -k | grep -i 'killed process' | tail -1
Sep 05 04:46:22 0970caef98b3 kernel: Memory cgroup out of memory: Killed process 2358886 (python3) total-vm:218724kB, anon-rss:65528kB, file-rss:2720kB, shmem-rss:0kB, UID:0 pgtables:188kB oom_score_adj:0
```

Signal 9, nobody sent it, `Result: oom-kill`, and the kernel's one line naming the victim, its resident size at death (65,528 kB, right at the limit), and its `oom_score_adj`. That line is what you grep for when a service exited 137 at 3 a.m. and its own log just stops. Without `MemorySwapMax=0` the first attempt did not die at all: `systemctl status` showed `Memory: 63.9M (max: 64M, ... swap: 140M)` and `memory.events` counted `max 1798`, the limit hit 1,798 times and absorbed by swap each time. Slow, but alive, which is its own kind of incident.

## Ship It

The artifact for this lesson is a runbook: [`outputs/runbook-the-box-is-slow.md`](../outputs/runbook-the-box-is-slow.md). It is the three questions applied to the five resources: for each, the command, the number to read, the threshold that means trouble, and the next question, with the traps beside them (`free` versus `available`, `wa` counted as idle, the cgroup ceiling under `nproc`, `EMFILE` looking like CPU, swap traffic versus swap used, a cloud disk's IOPS cap). It ends with what to do when nothing on the box is saturated, which is the case where the slow thing is somewhere else, and with the six commands whose output belongs in the incident note.

## Think about it

1. A ten-CPU database server shows load average 12, `us` 15%, `id` 80%, `wa` 5%. Which resource is saturated, why does the load average say 12, and which two `iostat` columns confirm it?
2. `free -h` shows 300 MB `free` on a 64 GB server. The team wants to add RAM. Which column do you read instead, and what `vmstat` columns would change your mind?
3. A service exits 137 every few hours. `journalctl -u app` ends with a normal request log line. Where is the only record of why, what will it contain, and which unit directive changes who gets chosen next time?
4. Your API stops accepting new connections at exactly 1,019 concurrent clients while CPU is idle and memory is fine. Name the limit, the two commands that prove it, the unit directive that raises it, and the reason raising it alone is not the fix.

## Key takeaways

- Every rate a tool prints is **two reads of a `/proc` counter and a subtraction**. Ignore the first line of `vmstat` and `iostat`; trust `top`'s `%CPU` over `ps`'s during an incident; load average is the kernel's own damped average of runnable plus `D` tasks.
- Ask **utilisation, saturation, errors** of each of five resources: CPU, memory, disk, network, descriptors. Saturation is what costs latency.
- CPU: `us` is your code, `sy` the kernel, **`wa` is the disk**, `st` the hypervisor. Saturation is `r` and load against `nproc`, and the cgroup's `cpu.max` inside a container.
- Memory: read **`MemAvailable`**. Saturation is **swap traffic** (`si`/`so`), not swap used. When reclaim and swap fail, the **OOM killer** `SIGKILL`s the highest `oom_score`; the only record is the kernel log; inside a cgroup the same happens at the cgroup's limit, and swap can hide it unless `MemorySwapMax=0`.
- Disk: `iostat -x` for `%util`, `await` and `aqu-sz`; `wa` is the CPU-side symptom; `dmesg` for errors. A slow database with an idle CPU is usually here.
- Descriptors: soft limit via `ulimit -n`, raised in a unit with `LimitNOFILE=`; `EMFILE` shows as "stopped accepting" and sometimes as 100% CPU; count and categorise `/proc/PID/fd` to find the leak.
- `/proc/pressure/*` is the one-number saturation signal when the kernel has it.

Next: [Installing Software](../13-installing-software/). The box can be read. Now how the software on it got there, what `apt install` actually does, why `/usr/local` and `pip` do not fight, and how the same job looks on Alpine and Red Hat.
