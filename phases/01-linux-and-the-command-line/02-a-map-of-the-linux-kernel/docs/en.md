# A Map of the Kernel

> The kernel is not a black box. It is five subsystems and a window. This lesson draws the map, traces one `read()` and one packet through it, and then opens the window: `/proc`, where every file is the kernel answering a question about itself. In the sandbox, writing a 64 MiB file made `Cached` rise by exactly **64 MiB**, reading it back ran at **3,488 MiB/s** without touching the disk, and 300 ms of pure CPU got the process pulled off the core **10 times** by a scheduler you never called.

## The Problem

Lesson 01 showed you the door. Every `print`, every `open`, every `connect` is a request that crosses into the kernel, and something on the other side does the work. But "the kernel" is still one word for a program with tens of millions of lines. When a server is slow, "the kernel is doing something" is not a diagnosis. Is it the scheduler, refusing your process a turn? The memory manager, quietly swapping? The filesystem, waiting for a disk? The network stack, dropping connections because a queue is full?

You cannot fix what you cannot locate, and you cannot locate anything without a map. This lesson is that map: the five subsystems every request passes through, drawn so that you can point at the one that owns your problem. Then it hands you the window the kernel leaves open for exactly this purpose. Linux describes itself, live, through a directory of files that are not on any disk. Learn to read them and `top`, `free`, `ss` and `ps` stop being oracles: they are `cat` with formatting.

## The Concept

### The map: five subsystems under one interface

The kernel is organised around what it manages. Above everything sits the **system call interface** from lesson 01: a few hundred entry points. Below it, five subsystems do the work, and below them is hardware. Every arrow in the diagram is a path a request can take.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 520" width="100%" style="max-width:880px" role="img" aria-label="The Linux kernel drawn as layers. At the top, a band labelled the system call interface, a few hundred entry points such as open, read, write, fork, execve, socket, connect and mmap. Below it, five columns, one per subsystem. Process management: the scheduler, fork, exec and exit, signals, process states R, S, D and Z, with its window at /proc/PID. Memory management: virtual memory and page tables, the page cache, swap, the out-of-memory killer, window /proc/meminfo. The virtual filesystem and filesystems: one API over ext4, xfs, btrfs, tmpfs, overlay, proc, sysfs and nfs, the dentry and inode caches, the block layer, window /proc/mounts. The network stack: sockets, TCP and UDP, IP and routing, netfilter, queueing, window /proc/net. Device drivers: nvme, virtio, network cards, terminals, built in or loaded as modules, driven by interrupts, windows /dev and /sys. Arrows lead from every column down to a hardware band: CPU, RAM, disk, network card. A caption says that a request can cross several columns, and that each column has a file you can read.">
  <defs>
    <marker id="p1l02a-ar" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker>
  </defs>
  <text x="450" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">The kernel, mapped: one interface, five subsystems, one window each</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">

    <!-- syscall interface -->
    <rect x="40" y="46" width="820" height="44" rx="10" fill="#c94a12" fill-opacity="0.10" stroke="#c94a12" stroke-width="2" stroke-linejoin="round"/>
    <text x="450" y="65" text-anchor="middle" font-size="11.5" font-weight="700" fill="#c94a12">THE SYSTEM CALL INTERFACE · lesson 01's door</text>
    <text x="450" y="81" text-anchor="middle" font-size="9" fill="currentColor">open · read · write · close · fork · execve · exit · kill · mmap · socket · connect · accept · epoll_wait · ...</text>

    <!-- five arrows from the interface into the subsystems -->
    <g fill="none" stroke="currentColor" stroke-width="1.5" stroke-opacity="0.6">
      <path d="M115 92 L115 106" marker-end="url(#p1l02a-ar)"/>
      <path d="M287 92 L287 106" marker-end="url(#p1l02a-ar)"/>
      <path d="M459 92 L459 106" marker-end="url(#p1l02a-ar)"/>
      <path d="M631 92 L631 106" marker-end="url(#p1l02a-ar)"/>
      <path d="M803 92 L803 106" marker-end="url(#p1l02a-ar)"/>
    </g>

    <!-- five subsystem columns -->
    <g fill="none" stroke-linejoin="round" stroke-width="1.8">
      <rect x="40"  y="110" width="150" height="250" rx="10" fill="#7c5cff" fill-opacity="0.08" stroke="#7c5cff"/>
      <rect x="212" y="110" width="150" height="250" rx="10" fill="#0fa07f" fill-opacity="0.08" stroke="#0fa07f"/>
      <rect x="384" y="110" width="150" height="250" rx="10" fill="#e0930f" fill-opacity="0.08" stroke="#e0930f"/>
      <rect x="556" y="110" width="150" height="250" rx="10" fill="#c94a12" fill-opacity="0.08" stroke="#c94a12"/>
      <rect x="728" y="110" width="132" height="250" rx="10" fill="#7f7f7f" fill-opacity="0.10" stroke="#7f7f7f"/>
    </g>

    <!-- 1 process management -->
    <text x="115" y="132" text-anchor="middle" font-size="10" font-weight="700" fill="#7c5cff">PROCESS MGMT</text>
    <g text-anchor="middle" font-size="8.5" fill="currentColor">
      <text x="115" y="152">the scheduler</text>
      <text x="115" y="166">fork · execve · exit</text>
      <text x="115" y="180">signals (kill, SIGTERM)</text>
      <text x="115" y="194">states: R S D Z T</text>
      <text x="115" y="208">threads, PIDs, parents</text>
      <text x="115" y="222">context switches</text>
      <text x="115" y="236">nice, cgroup CPU limits</text>
    </g>
    <text x="115" y="272" text-anchor="middle" font-size="8" fill="currentColor" opacity="0.75">owns: who runs, when,</text>
    <text x="115" y="284" text-anchor="middle" font-size="8" fill="currentColor" opacity="0.75">and for how long</text>
    <rect x="52" y="316" width="126" height="32" rx="6" fill="#7c5cff" fill-opacity="0.14" stroke="#7c5cff" stroke-width="1.2"/>
    <text x="115" y="330" text-anchor="middle" font-size="8" font-weight="700" fill="#7c5cff">window</text>
    <text x="115" y="342" text-anchor="middle" font-size="8.5" fill="currentColor">/proc/&lt;pid&gt;/ · loadavg</text>

    <!-- 2 memory -->
    <text x="287" y="132" text-anchor="middle" font-size="10" font-weight="700" fill="#0fa07f">MEMORY MGMT</text>
    <g text-anchor="middle" font-size="8.5" fill="currentColor">
      <text x="287" y="152">virtual memory, page tables</text>
      <text x="287" y="166">one address space per process</text>
      <text x="287" y="180">the page cache</text>
      <text x="287" y="194">demand paging, mmap</text>
      <text x="287" y="208">swap</text>
      <text x="287" y="222">the OOM killer</text>
      <text x="287" y="236">cgroup memory limits</text>
    </g>
    <text x="287" y="272" text-anchor="middle" font-size="8" fill="currentColor" opacity="0.75">owns: every byte of RAM,</text>
    <text x="287" y="284" text-anchor="middle" font-size="8" fill="currentColor" opacity="0.75">and what "free" means</text>
    <rect x="224" y="316" width="126" height="32" rx="6" fill="#0fa07f" fill-opacity="0.14" stroke="#0fa07f" stroke-width="1.2"/>
    <text x="287" y="330" text-anchor="middle" font-size="8" font-weight="700" fill="#0fa07f">window</text>
    <text x="287" y="342" text-anchor="middle" font-size="8.5" fill="currentColor">meminfo · &lt;pid&gt;/maps</text>

    <!-- 3 vfs -->
    <text x="459" y="132" text-anchor="middle" font-size="10" font-weight="700" fill="#e0930f">VFS + FILESYSTEMS</text>
    <g text-anchor="middle" font-size="8.5" fill="currentColor">
      <text x="459" y="152">one API: open read write</text>
      <text x="459" y="166">ext4 · xfs · btrfs</text>
      <text x="459" y="180">tmpfs · overlay · nfs</text>
      <text x="459" y="194">proc · sysfs · cgroup2</text>
      <text x="459" y="208">dentry + inode caches</text>
      <text x="459" y="222">the block layer, I/O queues</text>
      <text x="459" y="236">mounts, permissions</text>
    </g>
    <text x="459" y="272" text-anchor="middle" font-size="8" fill="currentColor" opacity="0.75">owns: every path, and the</text>
    <text x="459" y="284" text-anchor="middle" font-size="8" fill="currentColor" opacity="0.75">idea that everything is a file</text>
    <rect x="396" y="316" width="126" height="32" rx="6" fill="#e0930f" fill-opacity="0.14" stroke="#e0930f" stroke-width="1.2"/>
    <text x="459" y="330" text-anchor="middle" font-size="8" font-weight="700" fill="#e0930f">window</text>
    <text x="459" y="342" text-anchor="middle" font-size="8.5" fill="currentColor">/proc/mounts · &lt;pid&gt;/fd</text>

    <!-- 4 network -->
    <text x="631" y="132" text-anchor="middle" font-size="10" font-weight="700" fill="#c94a12">NETWORK STACK</text>
    <g text-anchor="middle" font-size="8.5" fill="currentColor">
      <text x="631" y="152">sockets, the accept queue</text>
      <text x="631" y="166">TCP · UDP</text>
      <text x="631" y="180">IP, routing tables</text>
      <text x="631" y="194">netfilter (the firewall)</text>
      <text x="631" y="208">queueing (qdisc)</text>
      <text x="631" y="222">interfaces, ARP, MTU</text>
      <text x="631" y="236">network namespaces</text>
    </g>
    <text x="631" y="272" text-anchor="middle" font-size="8" fill="currentColor" opacity="0.75">owns: every packet in</text>
    <text x="631" y="284" text-anchor="middle" font-size="8" fill="currentColor" opacity="0.75">and out (Phase 2 in code)</text>
    <rect x="568" y="316" width="126" height="32" rx="6" fill="#c94a12" fill-opacity="0.14" stroke="#c94a12" stroke-width="1.2"/>
    <text x="631" y="330" text-anchor="middle" font-size="8" font-weight="700" fill="#c94a12">window</text>
    <text x="631" y="342" text-anchor="middle" font-size="8.5" fill="currentColor">/proc/net · /sys/class</text>

    <!-- 5 drivers -->
    <text x="794" y="132" text-anchor="middle" font-size="10" font-weight="700" fill="currentColor">DEVICE DRIVERS</text>
    <g text-anchor="middle" font-size="8.5" fill="currentColor">
      <text x="794" y="152">nvme · virtio · sata</text>
      <text x="794" y="166">network cards</text>
      <text x="794" y="180">terminals (tty)</text>
      <text x="794" y="194">gpu, usb, sensors</text>
      <text x="794" y="208">built in, or modules</text>
      <text x="794" y="222">woken by interrupts</text>
      <text x="794" y="236">expose /dev nodes</text>
    </g>
    <text x="794" y="272" text-anchor="middle" font-size="8" fill="currentColor" opacity="0.75">owns: the only code</text>
    <text x="794" y="284" text-anchor="middle" font-size="8" fill="currentColor" opacity="0.75">that touches hardware</text>
    <rect x="740" y="316" width="108" height="32" rx="6" fill="#7f7f7f" fill-opacity="0.16" stroke="#7f7f7f" stroke-width="1.2"/>
    <text x="794" y="330" text-anchor="middle" font-size="8" font-weight="700" fill="currentColor">window</text>
    <text x="794" y="342" text-anchor="middle" font-size="8.5" fill="currentColor">/dev · /sys</text>

    <!-- arrows to hardware -->
    <g fill="none" stroke="currentColor" stroke-width="1.5" stroke-opacity="0.6">
      <path d="M115 362 L115 384" marker-end="url(#p1l02a-ar)"/>
      <path d="M287 362 L287 384" marker-end="url(#p1l02a-ar)"/>
      <path d="M459 362 L459 384" marker-end="url(#p1l02a-ar)"/>
      <path d="M631 362 L631 384" marker-end="url(#p1l02a-ar)"/>
      <path d="M794 362 L794 384" marker-end="url(#p1l02a-ar)"/>
    </g>

    <!-- hardware -->
    <rect x="40" y="388" width="820" height="44" rx="10" fill="#7f7f7f" fill-opacity="0.10" stroke="#7f7f7f" stroke-width="2" stroke-linejoin="round"/>
    <text x="450" y="407" text-anchor="middle" font-size="11.5" font-weight="700" fill="currentColor">HARDWARE</text>
    <text x="450" y="423" text-anchor="middle" font-size="9" fill="currentColor">CPU cores and their timer · RAM · disks · network cards · everything with an interrupt line</text>
  </g>
  <text x="450" y="466" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="10.5" fill="currentColor" opacity="0.9">One request often crosses several columns: a read() is VFS, then memory (the page cache), then a driver.</text>
  <text x="450" y="484" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="10.5" fill="currentColor" opacity="0.9">Every column has a window under /proc or /sys, and every tool you will meet in this phase reads from one of them.</text>
  <text x="450" y="504" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="9.5" fill="currentColor" opacity="0.72">When a server misbehaves, the first question is which column. The second is which file.</text>
</svg>
```

Hold this picture. The rest of the lesson walks the five columns left to right, then traces two requests across them, then opens the windows.

### Process management: the scheduler

The kernel keeps one record per process (and per thread; to the scheduler they are the same kind of thing, a **task**). That record holds the PID, the parent, the user, the open files, the memory map, and the **state**:

- **R** (running or runnable): on a CPU, or in the queue waiting for one.
- **S** (sleeping): waiting for something that will wake it, a socket, a timer, a lock. Interruptible: a signal can wake it.
- **D** (uninterruptible sleep): waiting for hardware, usually a disk. Cannot be killed until the I/O returns. A process stuck in D is the classic sign of a dying disk or a hung network filesystem.
- **Z** (zombie): finished, but its parent has not yet collected its exit status. Costs nothing but a PID (lesson 10).
- **T** (stopped): paused by `Ctrl+Z` or a debugger.

The **scheduler** decides which runnable task gets each CPU next. Since Linux 6.6 that is EEVDF (Earliest Eligible Virtual Deadline First), the successor to the long-lived CFS (Completely Fair Scheduler); both share one goal: every runnable task gets a fair share of CPU time, weighted by its **nice** value, and no task waits unreasonably long. Each CPU keeps its own run queue. The timer tick from lesson 01 is when the scheduler checks whether the running task has used its turn and, if so, **preempts** it: saves its registers, loads another task's, and jumps. That is a **context switch**, and it comes in two flavours the kernel counts separately:

- **Voluntary**: the task gave the CPU up itself by blocking, `sleep()`, `read()` on an empty socket, waiting on a lock.
- **Involuntary**: the task was still runnable and the scheduler took the CPU away at a tick.

The **Try It** script measures both. Twenty sleeps of 5 ms produced **exactly 20 voluntary switches** and 0 involuntary; 300 ms of a busy loop produced **0 voluntary and 10 involuntary**. A process that sleeps is polite; a process that computes is interrupted a few dozen times a second whether it likes it or not. The **load average** you see in `uptime` is the count of tasks in R or D, averaged over 1, 5 and 15 minutes. Compare it with the CPU count: a load of 8 on 2 cores is a queue, on 16 cores it is quiet.

### Memory management: virtual memory and the page cache

Foundations drew one process's memory as code, data, heap and stack. The memory manager's job is to make that private picture true for every process at once, on one shared pool of physical RAM. It does this with **virtual memory**: every address your program uses is translated, by the CPU with tables the kernel maintains, into a physical address, in units of **pages** (4 KiB on most machines). Two processes can both use address `0x1000` and land on different physical pages. A process cannot form an address that reaches another process's page; the tables do not contain it. That is the isolation Foundations promised, and it is enforced by hardware.

Three consequences matter for a backend engineer:

**Memory is lazy.** `malloc` and Python's object allocator reserve address space; physical pages are attached only when a page is first touched (**demand paging**). So a process's **VmSize** (address space reserved) is nearly meaningless, and **VmRSS** (resident set size, pages actually in RAM) is the number to watch. In the sandbox the script reserved 18,200 kB and was resident in 13,368 kB.

**The page cache eats all free RAM, on purpose.** Every file the kernel reads or writes is kept in RAM afterwards, in the **page cache**, until that RAM is needed for something else. This is why a Linux box shows almost no "free" memory after an hour of uptime and why that is fine. The script wrote a 64 MiB file and `Cached` in `/proc/meminfo` rose by **exactly 64 MiB**; reading it back ran at **3,488 MiB/s**, which is RAM speed, not disk speed. The number that says how much memory a new process could actually get is **MemAvailable**, which counts reclaimable cache as available. `MemFree` is the number that frightens people; `MemAvailable` is the one that matters. Lesson 12 turns this into a diagnostic.

**When RAM runs out, something dies.** If MemAvailable reaches zero and there is no swap left to spill to, the kernel invokes the **OOM (out-of-memory) killer**, which picks the process with the highest `oom_score` (roughly: the biggest) and sends it `SIGKILL`. Your database going away at 3 a.m. with nothing in its own logs is this. The kernel log (`dmesg`) has the only record.

### The virtual filesystem: everything is a file

Lesson 01 showed `cat` as `open`, `read`, `write`, `close`, and said the same four calls work on a file, a pipe and a socket. The **VFS** (virtual filesystem) is the layer that makes that true. It defines what a file, a directory and an open file *are* in terms of operations (open, read, write, seek, list), and each concrete **filesystem** implements them:

- **ext4** (the default on Debian and Ubuntu) and **xfs** (the default on Red Hat): data on a real disk, with journals for crash safety.
- **btrfs**: snapshots and checksums; the sandbox's host uses it for `/etc/hosts` and `/etc/resolv.conf`.
- **tmpfs**: a filesystem in RAM. `/dev/shm` and often `/tmp`. Fast, gone on reboot.
- **overlay**: several directories stacked so that one appears on top of another. The root of every container (Phase 11, lesson 02).
- **nfs**, **cifs**: files on another machine over the network. A hung server puts your processes into state D.
- **proc**, **sysfs**, **cgroup2**: not storage at all. Files that the kernel generates when read. The windows.

`/proc/mounts` lists what is mounted where and of which type; the sandbox showed 22 mounts of 9 types. Beneath the VFS, for disk-backed filesystems, sits the **block layer**: it turns "block 4,912 of this filesystem" into requests, merges and sorts them (the I/O scheduler), and hands them to a **driver**. Between the VFS and the block layer sits the page cache, which is why most reads never reach the block layer at all:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 520" width="100%" style="max-width:880px" role="img" aria-label="One read system call traced through the kernel, with a fast path and a slow path. The process calls read on a file descriptor asking for 4096 bytes. The syscall entry checks the descriptor. The virtual filesystem maps the descriptor to an open file and its inode, and asks the page cache whether that page of the file is already in RAM. On a hit, the fast path: the kernel copies the bytes into the process's buffer and returns; measured in the sandbox at 3,488 megabytes per second, about a microsecond per page. On a miss, the slow path: the filesystem, for example ext4, works out which disk blocks hold that page; the block layer queues, merges and orders the request; the driver, nvme or virtio, submits it to the disk; the disk answers with an interrupt some hundreds of microseconds to milliseconds later; the page is placed in the page cache; and only then does the copy happen and the call return. During the slow path the process is in state D, uninterruptible sleep, and the CPU runs someone else. A caption says the difference between the two paths is a thousand times, and that the page cache is why a second read of the same file is always fast.">
  <defs>
    <marker id="p1l02b-ar" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker>
    <marker id="p1l02b-arg" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#0fa07f"/></marker>
    <marker id="p1l02b-ard" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#d64545"/></marker>
  </defs>
  <text x="450" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">One read(): the fast path through the page cache, the slow path to the disk</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">

    <!-- left column: the main path -->
    <g fill="none" stroke-linejoin="round" stroke-width="1.8">
      <rect x="60"  y="52"  width="340" height="46" rx="9" fill="#7c5cff" fill-opacity="0.10" stroke="#7c5cff"/>
      <rect x="60"  y="122" width="340" height="46" rx="9" fill="#c94a12" fill-opacity="0.10" stroke="#c94a12"/>
      <rect x="60"  y="192" width="340" height="46" rx="9" fill="#e0930f" fill-opacity="0.10" stroke="#e0930f"/>
      <rect x="60"  y="262" width="340" height="56" rx="9" fill="#0fa07f" fill-opacity="0.12" stroke="#0fa07f" stroke-width="2.2"/>
      <rect x="60"  y="356" width="340" height="46" rx="9" fill="#0fa07f" fill-opacity="0.10" stroke="#0fa07f"/>
      <rect x="60"  y="426" width="340" height="46" rx="9" fill="#7c5cff" fill-opacity="0.10" stroke="#7c5cff"/>
    </g>
    <g text-anchor="middle" fill="currentColor">
      <text x="230" y="71" font-size="10.5" font-weight="700" fill="#7c5cff">your process: read(fd, buf, 4096)</text>
      <text x="230" y="87" font-size="8.5">user space, a Python f.read() underneath</text>
      <text x="230" y="141" font-size="10.5" font-weight="700" fill="#c94a12">syscall entry</text>
      <text x="230" y="157" font-size="8.5">is fd open in this process? is buf yours?</text>
      <text x="230" y="211" font-size="10.5" font-weight="700" fill="#e0930f">VFS: fd → open file → inode</text>
      <text x="230" y="227" font-size="8.5">which file, which offset, which filesystem</text>
      <text x="230" y="283" font-size="10.5" font-weight="700" fill="#0fa07f">page cache: is this page in RAM?</text>
      <text x="230" y="299" font-size="8.5">a lookup keyed by (inode, page number)</text>
      <text x="230" y="311" font-size="8" opacity="0.75">HIT → straight down · MISS → detour right</text>
      <text x="230" y="375" font-size="10.5" font-weight="700" fill="#0fa07f">copy the page into buf</text>
      <text x="230" y="391" font-size="8.5">RAM to RAM, the only copy that ever happens</text>
      <text x="230" y="445" font-size="10.5" font-weight="700" fill="#7c5cff">return 4096 to the process</text>
      <text x="230" y="461" font-size="8.5">the process becomes runnable again</text>
    </g>
    <g fill="none" stroke="currentColor" stroke-width="1.6">
      <path d="M230 100 L230 118" marker-end="url(#p1l02b-ar)"/>
      <path d="M230 170 L230 188" marker-end="url(#p1l02b-ar)"/>
      <path d="M230 240 L230 258" marker-end="url(#p1l02b-ar)"/>
      <path d="M230 404 L230 422" marker-end="url(#p1l02b-ar)"/>
    </g>
    <path d="M230 320 L230 352" fill="none" stroke="#0fa07f" stroke-width="2.4" marker-end="url(#p1l02b-arg)"/>
    <text x="244" y="340" font-size="8.5" font-weight="700" fill="#0fa07f">HIT: the fast path</text>
    <text x="244" y="351" font-size="8" fill="currentColor" opacity="0.8">~1 µs per page · 3,488 MiB/s measured</text>

    <!-- right column: the miss detour -->
    <path d="M402 290 L470 290" fill="none" stroke="#d64545" stroke-width="2.2" marker-end="url(#p1l02b-ard)"/>
    <text x="436" y="282" text-anchor="middle" font-size="8.5" font-weight="700" fill="#d64545">MISS</text>

    <g fill="none" stroke-linejoin="round" stroke-width="1.7">
      <rect x="474" y="122" width="380" height="46" rx="9" fill="#e0930f" fill-opacity="0.08" stroke="#e0930f"/>
      <rect x="474" y="192" width="380" height="46" rx="9" fill="#7f7f7f" fill-opacity="0.10" stroke="#7f7f7f"/>
      <rect x="474" y="268" width="380" height="46" rx="9" fill="#7f7f7f" fill-opacity="0.10" stroke="#7f7f7f"/>
      <rect x="474" y="342" width="380" height="46" rx="9" fill="#7f7f7f" fill-opacity="0.14" stroke="#7f7f7f" stroke-width="2"/>
      <rect x="474" y="416" width="380" height="46" rx="9" fill="#0fa07f" fill-opacity="0.08" stroke="#0fa07f"/>
    </g>
    <g text-anchor="middle" fill="currentColor">
      <text x="664" y="141" font-size="10.5" font-weight="700" fill="#e0930f">the filesystem (ext4, xfs ...)</text>
      <text x="664" y="157" font-size="8.5">which disk blocks hold page 3 of inode 8815?</text>
      <text x="664" y="211" font-size="10.5" font-weight="700">the block layer</text>
      <text x="664" y="227" font-size="8.5">queue the request, merge neighbours, order them (I/O scheduler)</text>
      <text x="664" y="287" font-size="10.5" font-weight="700">the driver (nvme, virtio_blk, sata)</text>
      <text x="664" y="303" font-size="8.5">write the command into the device's queue; process goes to state D</text>
      <text x="664" y="361" font-size="10.5" font-weight="700">the disk</text>
      <text x="664" y="377" font-size="8.5">100s of µs (NVMe) to ms (spinning): the CPU runs someone else meanwhile</text>
      <text x="664" y="435" font-size="10.5" font-weight="700" fill="#0fa07f">interrupt: data landed in RAM</text>
      <text x="664" y="451" font-size="8.5">the page is now in the page cache; rejoin the fast path</text>
    </g>
    <g fill="none" stroke="currentColor" stroke-width="1.6">
      <path d="M664 170 L664 188" marker-end="url(#p1l02b-ar)"/>
      <path d="M664 240 L664 264" marker-end="url(#p1l02b-ar)"/>
      <path d="M664 316 L664 338" marker-end="url(#p1l02b-ar)"/>
      <path d="M664 390 L664 412" marker-end="url(#p1l02b-ar)"/>
    </g>
    <!-- miss goes up into the filesystem box first -->
    <path d="M474 290 L460 290 L460 145 L470 145" fill="none" stroke="#d64545" stroke-width="2.2" marker-end="url(#p1l02b-ard)"/>
    <!-- rejoin: from the interrupt box back to "copy the page" -->
    <path d="M474 439 L440 439 L440 379 L404 379" fill="none" stroke="#0fa07f" stroke-width="2.2" marker-end="url(#p1l02b-arg)"/>
    <text x="444" y="470" text-anchor="middle" font-size="8" fill="currentColor" opacity="0.8">rejoin</text>
  </g>
  <text x="450" y="496" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="10.5" fill="currentColor" opacity="0.9">Hit and miss differ by a thousand times. The page cache is why the second read of any file is always fast,</text>
  <text x="450" y="512" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="10.5" fill="currentColor" opacity="0.9">and why "free" memory on a healthy Linux box is nearly zero.</text>
</svg>
```

A write takes the mirror path: the bytes go into the page cache and the call returns immediately; the kernel writes the **dirty** pages to disk later, in the background. That is why `write()` is fast and why a power cut can lose the last few seconds of data unless the program calls `fsync()`, which is the subject of Phase 4's durability lesson.

### The network stack: a packet in, a packet out

The network stack is the largest subsystem and the one Phase 2 builds in code layer by layer. Here you only need its shape, because every socket call your backend makes walks through it. A **socket** is a file descriptor (the VFS again) whose read and write operations are implemented by the protocol layers instead of a disk:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 520" width="100%" style="max-width:880px" role="img" aria-label="Six horizontal bands, top to bottom: your process, the socket layer, TCP or UDP, IP with routing and netfilter, the driver with its queueing discipline, and the network card. A left column labelled OUT traces a send call downward: the process calls send; the socket layer copies the bytes into the socket's send buffer and returns; TCP segments the data, numbers it, and retransmits if unacknowledged; IP picks a route and a source address and runs netfilter's output rules, which is the firewall; the driver queues the frame in the qdisc and writes it to the card's transmit ring; the network card puts it on the wire. A right column labelled IN traces a packet upward: the card DMAs the frame into RAM and raises an interrupt; the kernel polls the receive ring, called NAPI, and the driver builds a packet buffer; IP checks the checksum, runs netfilter's input rules, and decides the packet is for this host; TCP matches it to a connection, acknowledges it, and appends the data to that socket's receive queue; the socket layer wakes whatever is blocked in read or epoll_wait on that descriptor; the process's read call returns the bytes. A caption notes that /proc/net/tcp is the table of those connections, that ss decodes it, and that the accept queue and the socket buffers are the two places a busy server drops connections.">
  <defs>
    <marker id="p1l02c-ard" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#c94a12"/></marker>
    <marker id="p1l02c-arg" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#0fa07f"/></marker>
  </defs>
  <text x="450" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">The network stack: send() walks down the left, a packet walks up the right</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">

    <!-- bands -->
    <g fill="none" stroke-linejoin="round" stroke-width="1.7">
      <rect x="40" y="56"  width="820" height="50" rx="9" fill="#7c5cff" fill-opacity="0.08" stroke="#7c5cff"/>
      <rect x="40" y="124" width="820" height="56" rx="9" fill="#e0930f" fill-opacity="0.08" stroke="#e0930f"/>
      <rect x="40" y="198" width="820" height="56" rx="9" fill="#0fa07f" fill-opacity="0.08" stroke="#0fa07f"/>
      <rect x="40" y="272" width="820" height="56" rx="9" fill="#0fa07f" fill-opacity="0.08" stroke="#0fa07f"/>
      <rect x="40" y="346" width="820" height="56" rx="9" fill="#7f7f7f" fill-opacity="0.10" stroke="#7f7f7f"/>
      <rect x="40" y="420" width="820" height="44" rx="9" fill="#7f7f7f" fill-opacity="0.14" stroke="#7f7f7f" stroke-width="2"/>
    </g>
    <!-- band labels (centre) -->
    <g text-anchor="middle" font-size="10" font-weight="700">
      <text x="450" y="76" fill="#7c5cff">YOUR PROCESS</text>
      <text x="450" y="146" fill="#e0930f">SOCKET LAYER</text>
      <text x="450" y="220" fill="#0fa07f">TCP / UDP</text>
      <text x="450" y="294" fill="#0fa07f">IP · ROUTING · NETFILTER</text>
      <text x="450" y="368" fill="currentColor">DRIVER · QUEUEING (qdisc)</text>
      <text x="450" y="440" fill="currentColor">THE NETWORK CARD</text>
    </g>
    <g text-anchor="middle" font-size="8" fill="currentColor" opacity="0.7">
      <text x="450" y="90">user space</text>
      <text x="450" y="160">a socket is a file descriptor</text>
      <text x="450" y="234">the transport layer (Phase 2, lesson 05)</text>
      <text x="450" y="308">the network layer + the firewall</text>
      <text x="450" y="382">rings of buffers shared with the card</text>
      <text x="450" y="454">hardware: the wire</text>
    </g>

    <!-- OUT column -->
    <text x="200" y="48" text-anchor="middle" font-size="9.5" font-weight="700" fill="#c94a12">OUT · send(fd, data)</text>
    <g font-size="8.5" fill="currentColor">
      <text x="56" y="76">send(fd, b"GET / HTTP/1.1...")</text>
      <text x="56" y="90">one syscall; returns when copied, not when delivered</text>
      <text x="56" y="144">copy into the socket's send buffer</text>
      <text x="56" y="158">full buffer? send() blocks: backpressure</text>
      <text x="56" y="172">/proc/sys/net/core/wmem_max caps it</text>
      <text x="56" y="218">cut into segments, number them</text>
      <text x="56" y="232">keep a copy until the peer ACKs</text>
      <text x="56" y="246">retransmit on timeout; window, congestion</text>
      <text x="56" y="292">pick a route and a source address (ip route)</text>
      <text x="56" y="306">OUTPUT chain: may the packet leave? (iptables)</text>
      <text x="56" y="320">wrap in an IP header, resolve the next hop's MAC</text>
      <text x="56" y="366">enqueue in the qdisc (fair queueing, shaping)</text>
      <text x="56" y="380">write a descriptor into the card's TX ring</text>
      <text x="56" y="394">the card DMAs the frame out of RAM</text>
      <text x="56" y="440">bits on the wire (Phase 2, lesson 02)</text>
    </g>
    <path d="M330 100 L330 118" fill="none" stroke="#c94a12" stroke-width="2" marker-end="url(#p1l02c-ard)"/>
    <path d="M330 182 L330 192" fill="none" stroke="#c94a12" stroke-width="2" marker-end="url(#p1l02c-ard)"/>
    <path d="M330 256 L330 266" fill="none" stroke="#c94a12" stroke-width="2" marker-end="url(#p1l02c-ard)"/>
    <path d="M330 330 L330 340" fill="none" stroke="#c94a12" stroke-width="2" marker-end="url(#p1l02c-ard)"/>
    <path d="M330 404 L330 414" fill="none" stroke="#c94a12" stroke-width="2" marker-end="url(#p1l02c-ard)"/>

    <!-- IN column -->
    <text x="700" y="48" text-anchor="middle" font-size="9.5" font-weight="700" fill="#0fa07f">IN · a packet arrives</text>
    <g font-size="8.5" fill="currentColor" text-anchor="end">
      <text x="844" y="76">read() returns the bytes; epoll_wait reports readable</text>
      <text x="844" y="90">the process was asleep in S until this moment</text>
      <text x="844" y="144">append to that socket's receive queue</text>
      <text x="844" y="158">wake whoever is blocked on this descriptor</text>
      <text x="844" y="172">full queue? TCP shrinks the window: backpressure</text>
      <text x="844" y="218">match (src, dst, ports) to a connection</text>
      <text x="844" y="232">a SYN to a LISTEN socket → the accept queue</text>
      <text x="844" y="246">accept queue full? drop it (net.core.somaxconn)</text>
      <text x="844" y="292">checksum; is this host the destination?</text>
      <text x="844" y="306">INPUT chain: is it allowed in? (the firewall)</text>
      <text x="844" y="320">else forward it, or drop it</text>
      <text x="844" y="366">interrupt → poll the RX ring (NAPI) → build a buffer</text>
      <text x="844" y="380">too many packets? the ring overflows: drops</text>
      <text x="844" y="394">/proc/net/dev counts every one, and every drop</text>
      <text x="844" y="440">the card DMAs the frame into RAM, raises an interrupt</text>
    </g>
    <path d="M570 414 L570 404" fill="none" stroke="#0fa07f" stroke-width="2" marker-end="url(#p1l02c-arg)"/>
    <path d="M570 340 L570 330" fill="none" stroke="#0fa07f" stroke-width="2" marker-end="url(#p1l02c-arg)"/>
    <path d="M570 266 L570 256" fill="none" stroke="#0fa07f" stroke-width="2" marker-end="url(#p1l02c-arg)"/>
    <path d="M570 192 L570 182" fill="none" stroke="#0fa07f" stroke-width="2" marker-end="url(#p1l02c-arg)"/>
    <path d="M570 118 L570 100" fill="none" stroke="#0fa07f" stroke-width="2" marker-end="url(#p1l02c-arg)"/>
  </g>
  <text x="450" y="486" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="10.5" fill="currentColor" opacity="0.9">/proc/net/tcp is the table of these connections; ss decodes it. The accept queue and the socket buffers</text>
  <text x="450" y="502" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="10.5" fill="currentColor" opacity="0.9">are the two places a busy server silently drops work, and both have a sysctl and a counter.</text>
</svg>
```

Two facts from this diagram will come back again and again. First, `send()` returns when the bytes are **copied into a kernel buffer**, not when they reach the other machine; delivery is TCP's problem, handled inside the kernel after your call returned. Second, there are **queues at every level**, and each has a size: the socket buffers, the accept queue, the card's rings. A server under load fails at whichever queue fills first, and each queue has a counter in `/proc/net` and a knob in `/proc/sys/net`. Lesson 14 reads those counters with `ss` and `ip`; Phase 2 builds the layers.

### Device drivers and the hardware boundary

A **driver** is the piece of kernel code that knows how to talk to one kind of hardware: an NVMe disk, a virtio network card in a VM, a USB keyboard, a serial console. Drivers are the only code in the system that reads and writes device registers, and they are woken by **interrupts** when the device has something to say. Everything above them is hardware-independent; that is the whole point of the layering. Your `read()` does not know whether the file lives on NVMe, SATA or a network share.

Drivers are either **built into** the kernel image or loaded on demand as **modules** from `/lib/modules/<version>/`; `lsmod` lists the loaded ones. Two things you will notice in the sandbox: there is no `/lib/modules` and no `lsmod`. A container has no kernel of its own. It runs on the host's kernel, with the host's drivers, and sees only the small, virtual set of devices the host lets it see. That is the first concrete evidence that a container is a process and not a machine, a thread Phase 11 pulls on hard.

Drivers expose themselves in two places. Under `/dev` each device gets a **device file**: `/dev/null` and `/dev/tty` are **character devices** (`c` in `ls -l`, a stream of bytes), `/dev/sda` and `/dev/nvme0n1` are **block devices** (`b`, addressable in fixed blocks, what a filesystem sits on). Reading `/dev/random` is a `read()` that the VFS routes to the random-number driver instead of a disk. Under `/sys` (**sysfs**) the kernel exposes the tree of devices and their attributes as files: `/sys/class/net/eth0/address` is your MAC address, `/sys/class/net/eth0/mtu` is `1500`, `/sys/block/*/stat` is disk activity.

### The window: /proc and /sys

You have now seen `/proc` mentioned in every column, so here is what it is. **procfs** is a filesystem, mounted at `/proc`, whose files do not exist on any disk. When you `open()` and `read()` one, the VFS routes the call to a kernel function that generates the content at that moment. `cat /proc/meminfo` is the memory manager describing itself; `cat /proc/self/status` is the scheduler describing the process doing the reading. The format is documented in `proc(5)`.

The layout is simple:

- `/proc/<pid>/` is one directory per process: `status`, `cmdline`, `environ`, `cwd`, `exe`, `fd/`, `maps`, `limits`, `stat`. `/proc/self` is a symlink to your own.
- `/proc/meminfo`, `/proc/cpuinfo`, `/proc/loadavg`, `/proc/uptime`, `/proc/version`, `/proc/mounts`: the whole machine.
- `/proc/net/`: `dev`, `tcp`, `udp`, `route`: the network stack's tables, in hex.
- `/proc/sys/`: the **tunables**. Writing to `/proc/sys/net/core/somaxconn` changes the kernel's behaviour immediately; `sysctl` is a thin wrapper that turns dots into slashes. The sandbox exposes 894 of them.

`/sys` (sysfs) is the same idea for devices and drivers, and `/sys/fs/cgroup` is how Phase 11's resource limits are set and read. Together they are the reason Linux needs no dashboard program: every monitoring tool you will ever run is reading these files and subtracting two readings to make a rate.

## Try It

The script for this lesson is [`code/kernel_map.py`](../code/kernel_map.py). It visits each column's window in turn and prints what it finds. Run it inside the sandbox, where `/proc` exists; on a Mac it runs too but says what it cannot show:

```bash
make shell
python3 phases/01-linux-and-the-command-line/02-a-map-of-the-linux-kernel/code/kernel_map.py
```

**The scheduler**, seen through `/proc/self/status` before and after two experiments:

```console
/proc/self/status: State=R (running)  Pid=1  PPid=0  Threads=1
after 20 x sleep(5 ms) : +20 voluntary, +0 involuntary switches
after 300 ms of pure CPU: +0 voluntary, +10 involuntary switches
   sleep() hands the CPU back on purpose; a busy loop is taken off it at the timer tick
/proc/self/stat  : state=R  user=0.34s  kernel=0.04s  (CPU time so far, 100 ticks/s)
```

Every `sleep()` was one voluntary switch, exactly. The busy loop never asked for anything and was still pulled off the CPU ten times in 300 ms, by the tick. Notice `Pid=1 PPid=0`: `docker compose run` made the script the first process in a fresh PID namespace, so it sees itself as PID 1 with no parent. On your laptop the same script prints a five-digit PID. Same kernel, different view; that trick is Phase 11.

**Memory**, and why `free` looks the way it does:

```console
MemTotal          8004 MiB   all the RAM the kernel manages
MemFree           3871 MiB   touched by nobody: this is the number that looks scary
Cached             674 MiB   the page cache: file data kept in RAM, dropped the instant someone needs it
MemAvailable      4429 MiB   what a new process could actually get: the number that matters

wrote a 64 MiB file: Cached went 674 MiB -> 737 MiB (+64 MiB)
read it back: 3,488 MiB/s: it never went near the disk, it came from the page cache

this process : VmSize=18200 kB (address space reserved)  VmRSS=13368 kB (RAM actually resident)
/proc/self/maps: 90 mapped regions (the code/data/heap/stack map from Foundations, plus every shared library)
```

The file went into the page cache byte for byte, and came back at RAM speed. The 90 mapped regions are Foundations' four-region picture in real life: heap, stack, the Python binary, and every shared library it loaded, each mapped at an address you can read.

**The VFS**, as the mount table and this process's descriptor table:

```console
/proc/mounts: 22 mounts, 9 filesystem types
   tmpfs        7   /dev, /dev/shm, /proc/asound ...
   proc         6   /proc, /proc/bus, /proc/fs ...
   overlay      1   /
   sysfs        1   /sys
   cgroup2      1   /sys/fs/cgroup

/proc/self/fd: descriptors this process holds right now
   fd  0 -> pipe:[7425557]
   fd  1 -> pipe:[7425558]
   fd  2 -> pipe:[7425559]
cwd -> /workspace     exe -> /usr/local/bin/python3.12
```

Of the 22 mounts, only the `overlay` root and the three `btrfs` bind-mounts are backed by storage. Everything else is the kernel. And descriptors 0, 1 and 2 are pipes here rather than a terminal, because Docker connected them to pipes; lesson 07 is entirely about what that means.

**The network stack**, decoded from hex the way `ss` does it. The script opens a listening socket and then finds it in `/proc/net/tcp`:

```console
this script is now listening on 127.0.0.1:36605; let's find it the way ss does
/proc/net/tcp, the table ss -tln reads (hex, little-endian, one row per socket):
   raw  0100007F:8EFD state 0A  ->  127.0.0.1:36605        LISTEN  <- ours
   raw  0B00007F:A119 state 0A  ->  127.0.0.11:41241       LISTEN
```

`0100007F` is `127.0.0.1` with its bytes reversed, `8EFD` is 36605 in hexadecimal, and state `0A` is LISTEN. That is all `ss -tln` does: read this file and print it the right way round. The second socket is Docker's embedded DNS resolver, which every container talks to.

**The tunables**, read straight from `/proc/sys`:

```console
   net.core.somaxconn             = 4096            max length of a listen() backlog: full = new connections refused
   net.ipv4.ip_local_port_range   = 32768 60999     ports a client may use: exhaust them and connect() fails
   fs.nr_open                     = 1073741816      per-process ceiling for ulimit -n
   vm.swappiness                  = 20              how eagerly the kernel swaps (0-100)
   vm.overcommit_memory           = 1               whether malloc may promise RAM that does not exist
```

Each of these will be the answer to a real question later in the curriculum: the backlog in Phase 2's rate-limiting lesson, the port range when a proxy runs out of client ports, `overcommit_memory` when Redis refuses to start.

## Use It

The commands below are the same windows, read by the standard tools. Every one of them is a program that opens a file under `/proc` or `/sys` and formats it; where that is not obvious, the file is named beside it.

```bash
uname -r                       # /proc/sys/kernel/osrelease
nproc                          # /proc/cpuinfo, counted (in a container: the host's count)
cat /proc/loadavg; uptime      # the same three numbers, twice
free -h                        # /proc/meminfo, in human units
findmnt -t proc,sysfs,tmpfs,overlay -o TARGET,FSTYPE    # /proc/self/mountinfo, as a tree
ls -l /dev/null /dev/tty       # c = character device; the "1, 3" is the driver's major, minor number
ls /sys/class/net; cat /sys/class/net/eth0/address      # your interfaces and their MAC
sysctl net.core.somaxconn vm.swappiness                 # /proc/sys, dots to slashes
sysctl -a | wc -l              # every knob: 894 in the sandbox
ss -tln                        # /proc/net/tcp, decoded
cat /proc/1/status | head -8   # PID 1: whatever started the container
ls -l /proc/1/fd               # its descriptors
```

What came back in the sandbox, with the lines worth reading:

```console
$ free -h
               total        used        free      shared  buff/cache   available
Mem:           7.8Gi       3.5Gi       3.8Gi       351Mi       1.0Gi       4.3Gi
Swap:          8.8Gi       699Mi       8.1Gi
```

The `buff/cache` column is the page cache and the `available` column is `MemAvailable`. Read `available`, ignore `free`. That is the whole of the "Linux ate my RAM" confusion, resolved in one row.

```console
$ ls -l /dev/null /dev/tty
crw-rw-rw- 1 root root 1, 3 Sep  5 03:30 /dev/null
crw-rw-rw- 1 root root 5, 0 Sep  5 03:30 /dev/tty
```

The leading `c` says character device, and `1, 3` is the pair of numbers the VFS uses to find the driver: major 1 is the memory-devices driver, minor 3 is its "null" device. Writing to `/dev/null` is a `write()` that the VFS routes to a function that discards the bytes and returns the count.

```console
$ ss -tln
State  Recv-Q Send-Q Local Address:Port  Peer Address:Port
LISTEN 0      4096      127.0.0.11:44041      0.0.0.0:*
```

`Send-Q` on a LISTEN socket is the accept queue's capacity, 4096, which is the `somaxconn` you read a moment ago, and `Recv-Q` is how many connections are waiting to be accepted right now. Lesson 14 lives in this command.

Three of the commands refuse inside a container, and the refusals are the lesson:

```console
$ lsmod
bash: lsmod: command not found
$ ls /lib/modules
ls: cannot access '/lib/modules': No such file or directory
$ dmesg | tail
dmesg: read kernel buffer failed: Operation not permitted
```

No modules, because the kernel is the host's and the container never loaded one. No `dmesg`, because reading the kernel's log is a privilege the container was not given (it needs `CAP_SYSLOG`; Phase 11 explains capabilities). On a real server all three work, and `dmesg -T` is where the OOM killer, disk errors and network card resets leave their only trace.

## Ship It

The artifact for this lesson is a runbook: [`outputs/runbook-proc-and-sys-windows.md`](../outputs/runbook-proc-and-sys-windows.md). It is a question-to-file map. "Is the box out of memory?" is a line in `/proc/meminfo`. "What is this PID doing, and where is it running from?" is `/proc/<pid>/status` and `/proc/<pid>/cwd`. "Who holds port 8080?" is `/proc/net/tcp`. "Which knob controls that?" is a table of the two dozen `sysctl` settings a backend engineer actually changes, with the default and the reason. When the monitoring agent is down and `top` is not installed, it is the whole diagnosis kit, with `cat`.

## Think about it

1. `free` shows 200 MiB free on a 64 GiB database server and the on-call engineer wants to add RAM. Which line of `/proc/meminfo` would you read first, and what would convince you they are right?
2. A process shows `State: D` for thirty seconds and `kill -9` does nothing. Which column of the map owns the problem, and what is it probably waiting for?
3. Your web server's `ss -tln` shows `Recv-Q 4096 Send-Q 4096` on its listening socket. What is happening to new connections, and which sysctl and which line of your own code are involved?
4. Inside a container, `nproc` says 10 but `cat /sys/fs/cgroup/cpu.max` says `200000 100000`. How many CPUs does the process actually get, and which subsystem enforces it?

## Key takeaways

- The kernel is **five subsystems** under one syscall interface: process management (the scheduler), memory management, the VFS and filesystems, the network stack, and device drivers. Locate the column before you debug.
- The **scheduler** preempts at the timer tick. Sleeping is a voluntary switch; computing gets you taken off the CPU involuntarily, ten times in 300 ms in the sandbox. Load average counts tasks in R and D.
- **Virtual memory** gives each process its own address space on shared RAM, lazily. Watch **VmRSS**, not VmSize; watch **MemAvailable**, not MemFree. The **page cache** uses all free RAM on purpose and gives it back on demand; a cached read runs at RAM speed.
- The **VFS** makes files, pipes, sockets and devices answer the same four calls. Disk filesystems sit above a block layer and a driver; `proc`, `sysfs` and `tmpfs` are not on any disk at all.
- The **network stack** is queues at every layer: socket buffers, the accept queue, the card's rings. `send()` returns on copy, not delivery. Each queue has a counter in `/proc/net` and a knob in `/proc/sys/net`.
- **Drivers** are the only code that touches hardware, woken by interrupts, exposed as `/dev` files and `/sys` attributes. A container has no drivers of its own because it has no kernel of its own.
- **`/proc` and `/sys` are the window.** Every monitoring tool is `cat` plus formatting plus subtraction. `/proc/<pid>/` for a process, `/proc/meminfo` for RAM, `/proc/net/` for sockets, `/proc/sys/` for the knobs.

Next: [The Shell](../03-the-shell/). You have the map of the kernel. Now the program you will use to drive it, and a mini shell of your own so it is never magic.
