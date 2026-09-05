# Processes & Signals

> `kill` does not kill. It delivers one small integer, and what happens next is the receiving process's decision, except for signal 9, which the kernel handles without asking. This lesson builds `ps` and `pstree` from `/proc`, then forks children and sends them everything: a `SIGTERM` handler that finishes its request and exits **0**, a process that ignores `SIGTERM` and dies only to `SIGKILL` with status **137**, `SIGSTOP` and `SIGCONT`, a zombie you can watch in `/proc`, an orphan adopted by PID 1, and a child that outlives its parent with `setsid`. Then the tools: `ps`, `top`, `pgrep`, `kill`, `jobs`, `nohup`, `nice`, `timeout`.

## The Problem

Lesson 09's deploy script "restarted the service" with an `echo`. On a real box that line is `systemctl restart app`, and underneath it is a signal sent to a PID. Whether the restart drops in-flight requests, corrupts a file, or leaves a port busy for the new copy depends on what that signal is, what the process does when it arrives, and what happens to its children. None of that is visible from the script.

It is also the daily vocabulary of operating anything. "The process is a zombie." "It is in D state, you cannot kill it." "It got OOM-killed, exit 137." "It died when I closed my terminal." "The port is still in use after I killed it." Each of those is a sentence about the process table and the signal table, two structures the kernel keeps and exposes in `/proc`. Lesson 02 drew the scheduler; lesson 03 built `fork`, `exec` and `wait`. This lesson is the rest of a process's life, and the one thing you will do to processes more than anything else: stop them.

## The Concept

### A process is a record

To the kernel, a process is an entry in a table: a **PID**, its parent's PID (**PPID**), the user it runs as, its **state**, its process group and session, its open descriptors, its working directory, its CPU time so far, and eventually its **exit status**. Lesson 02 showed the window: `/proc/<pid>/status` has the identity and state, `/proc/<pid>/stat` has the CPU counters, `/proc/<pid>/cmdline` has the command. `ps` is that directory, read once and formatted; `top` is `ps` in a loop with two samples subtracted to get a rate. The **Build It** script does both in eighty lines.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 440" width="100%" style="max-width:880px" font-family="'JetBrains Mono', ui-monospace, monospace" role="img" aria-label="The life of a process as a state diagram. fork creates it in state R, runnable. From R it moves to S, sleeping, when it waits for input, a timer or a lock, and back to R when woken. It moves to D, uninterruptible sleep, while waiting on a disk or a network filesystem, and signals cannot reach it there. SIGSTOP or Ctrl+Z moves it to T, stopped, and SIGCONT brings it back. exit or a fatal signal moves it to Z, zombie: the memory and descriptors are freed but the PID and exit status remain until the parent calls wait. After wait the entry is gone. A side note shows that if the parent exits first, the child is re-parented to PID 1, which waits for it, so orphans do not become permanent zombies. Each state is labelled with what ps prints in the STAT column.">
  <defs>
    <marker id="p1l10a-ar" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker>
    <marker id="p1l10a-ard" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#d64545"/></marker>
  </defs>
  <text x="450" y="26" text-anchor="middle" font-size="14.5" font-weight="700" fill="currentColor">The life of a process: the states ps prints, and how it moves between them</text>
  <!-- fork -->
  <rect x="40" y="170" width="110" height="44" rx="9" fill="#7c5cff" fill-opacity="0.12" stroke="#7c5cff" stroke-width="1.7" stroke-linejoin="round"/>
  <text x="95" y="189" text-anchor="middle" font-size="10" font-weight="700" fill="#7c5cff">fork()</text>
  <text x="95" y="204" text-anchor="middle" font-size="8" fill="currentColor" opacity="0.8">a new PID</text>
  <!-- R -->
  <rect x="200" y="160" width="140" height="64" rx="9" fill="#0fa07f" fill-opacity="0.14" stroke="#0fa07f" stroke-width="2" stroke-linejoin="round"/>
  <text x="270" y="182" text-anchor="middle" font-size="11" font-weight="700" fill="#0fa07f">R · runnable</text>
  <text x="270" y="198" text-anchor="middle" font-size="8.5" fill="currentColor">on a CPU, or queued for one</text>
  <text x="270" y="212" text-anchor="middle" font-size="8" fill="currentColor" opacity="0.75">counts toward load average</text>
  <!-- S -->
  <rect x="200" y="50" width="140" height="64" rx="9" fill="#7f7f7f" fill-opacity="0.14" stroke="#7f7f7f" stroke-width="1.7" stroke-linejoin="round"/>
  <text x="270" y="72" text-anchor="middle" font-size="11" font-weight="700" fill="currentColor">S · sleeping</text>
  <text x="270" y="88" text-anchor="middle" font-size="8.5" fill="currentColor">waits on a socket or timer</text>
  <text x="270" y="102" text-anchor="middle" font-size="8" fill="currentColor" opacity="0.75">a signal wakes it</text>
  <!-- D -->
  <rect x="200" y="270" width="140" height="64" rx="9" fill="#e0930f" fill-opacity="0.14" stroke="#e0930f" stroke-width="1.7" stroke-linejoin="round"/>
  <text x="270" y="292" text-anchor="middle" font-size="11" font-weight="700" fill="#e0930f">D · uninterruptible</text>
  <text x="270" y="308" text-anchor="middle" font-size="8.5" fill="currentColor">waiting on a disk or NFS</text>
  <text x="270" y="322" text-anchor="middle" font-size="8" fill="currentColor" opacity="0.75">even kill -9 waits</text>
  <!-- T -->
  <rect x="400" y="50" width="140" height="64" rx="9" fill="#7f7f7f" fill-opacity="0.14" stroke="#7f7f7f" stroke-width="1.7" stroke-linejoin="round"/>
  <text x="470" y="72" text-anchor="middle" font-size="11" font-weight="700" fill="currentColor">T · stopped</text>
  <text x="470" y="88" text-anchor="middle" font-size="8.5" fill="currentColor">SIGSTOP, Ctrl+Z, a debugger</text>
  <text x="470" y="102" text-anchor="middle" font-size="8" fill="currentColor" opacity="0.75">gets no CPU until SIGCONT</text>
  <!-- Z -->
  <rect x="600" y="160" width="140" height="64" rx="9" fill="#d64545" fill-opacity="0.10" stroke="#d64545" stroke-width="1.7" stroke-linejoin="round"/>
  <text x="670" y="182" text-anchor="middle" font-size="11" font-weight="700" fill="#d64545">Z · zombie</text>
  <text x="670" y="198" text-anchor="middle" font-size="8.5" fill="currentColor">exited; memory and fds freed</text>
  <text x="670" y="212" text-anchor="middle" font-size="8" fill="currentColor" opacity="0.75">only a PID and an exit status</text>
  <!-- gone -->
  <rect x="780" y="170" width="90" height="44" rx="9" fill="#7c5cff" fill-opacity="0.12" stroke="#7c5cff" stroke-width="1.7" stroke-linejoin="round"/>
  <text x="825" y="189" text-anchor="middle" font-size="10" font-weight="700" fill="#7c5cff">gone</text>
  <text x="825" y="204" text-anchor="middle" font-size="8" fill="currentColor" opacity="0.8">PID reusable</text>
  <!-- arrows -->
  <g fill="none" stroke="currentColor" stroke-width="1.6">
    <path d="M152 192 L196 192" marker-end="url(#p1l10a-ar)"/>
    <path d="M250 158 L250 118" marker-end="url(#p1l10a-ar)"/>
    <path d="M290 116 L290 156" marker-end="url(#p1l10a-ar)"/>
    <path d="M250 226 L250 266" marker-end="url(#p1l10a-ar)"/>
    <path d="M290 268 L290 228" marker-end="url(#p1l10a-ar)"/>
    <path d="M342 176 L396 108" marker-end="url(#p1l10a-ar)"/>
    <path d="M440 116 L330 176" marker-end="url(#p1l10a-ar)"/>
    <path d="M742 192 L776 192" marker-end="url(#p1l10a-ar)"/>
  </g>
  <path d="M342 192 L596 192" fill="none" stroke="#d64545" stroke-width="1.8" marker-end="url(#p1l10a-ard)"/>
  <g font-size="7.8" fill="currentColor" opacity="0.85">
    <text x="215" y="140">wait for I/O</text>
    <text x="296" y="140">woken</text>
    <text x="214" y="250">disk I/O</text>
    <text x="296" y="250">I/O done</text>
    <text x="352" y="134">SIGSTOP</text>
    <text x="392" y="156">SIGCONT</text>
    <text x="469" y="184" text-anchor="middle" fill="#d64545">exit(), or a fatal signal</text>
    <text x="759" y="184">wait()</text>
  </g>
  <rect x="380" y="270" width="490" height="90" rx="10" fill="#7f7f7f" fill-opacity="0.10" stroke="#7f7f7f" stroke-width="1.5" stroke-linejoin="round"/>
  <text x="625" y="290" text-anchor="middle" font-size="10" font-weight="700" fill="currentColor">WHO CALLS wait()</text>
  <g text-anchor="middle" font-size="8.5" fill="currentColor">
    <text x="625" y="310">the parent, normally: that is lesson 03's wait4, and it turns the zombie into $?</text>
    <text x="625" y="326">if the parent exits first, the child is re-parented to PID 1 (or a subreaper), which waits</text>
    <text x="625" y="342" opacity="0.8">a parent that is alive and never waits leaves zombies: one PID each, until fork fails</text>
  </g>
  <text x="450" y="400" text-anchor="middle" font-size="10.5" fill="currentColor" opacity="0.9">ps STAT: R S D T Z, plus s (session leader), l (multi-threaded), + (foreground), N (niced), &lt; (high priority)</text>
  <text x="450" y="420" text-anchor="middle" font-size="9.5" fill="currentColor" opacity="0.72">A process is created by fork, stopped by a signal or its own exit, and removed by its parent's wait. Nothing else creates or removes one.</text>
</svg>
```

The **state** letter in `ps`'s `STAT` column is the one you will read most. `R` is runnable, `S` is sleeping (interruptible: a signal wakes it), `D` is uninterruptible sleep on I/O (signals wait, including `SIGKILL`, until the I/O returns), `T` is stopped, `Z` is a zombie. The suffixes say more: `s` a session leader, `l` multi-threaded, `+` in the foreground, `N` niced down. Read `Ss` as "a shell," `Sl` as "a server with threads," `R+` as "the thing you just started."

### Reading ps and top

`ps aux` is the historical form and prints everything; `ps -eo pid,ppid,user,stat,%cpu,%mem,etime,cmd` lets you pick columns; `--forest` draws the tree; `pstree -p` draws it better. In the sandbox:

```console
$ ps -eo pid,ppid,user,stat,%cpu,%mem,etime,cmd | head -4
    PID    PPID USER     STAT %CPU %MEM     ELAPSED CMD
      1       0 root     Ss    1.5  0.0       00:03 bash -c ...
     14       1 root     S     0.0  0.0       00:00 sleep 300
     15       1 root     S     0.0  0.0       00:00 sleep 300
$ pstree -p | head -4
bash(1)-+-head(23)
        |-pstree(22)
        |-sleep(14)
        `-sleep(15)
```

`%CPU` in `ps` is CPU time divided by elapsed time since the process started, which is why a process that was busy an hour ago and idle since still shows a number; `top`'s `%CPU` is the rate over its last refresh, which is the one you want during an incident. `RSS` is resident memory (lesson 02: the number that matters), `VSZ` is address space (the number that does not). `etime` is how long it has been running, which answers "did it restart" faster than any log.

`top` adds the whole-machine header, and its five lines are worth reading once slowly:

```console
$ top -bn1 | head -5
top - 04:29:41 up 3 days,  5:34,  0 users,  load average: 0.57, 0.38, 0.39
Tasks:   5 total,   1 running,   4 sleeping,   0 stopped,   0 zombie
%Cpu(s):  0.0 us,  0.9 sy,  0.0 ni, 99.1 id,  0.0 wa,  0.0 hi,  0.0 si,  0.0 st
MiB Mem :   8004.5 total,   3731.8 free,   3617.4 used,   1206.8 buff/cache
MiB Swap:   9028.5 total,   8329.5 free,    699.0 used.   4387.0 avail Mem
```

Line 1 is `uptime` (lesson 02's load average). Line 2 counts processes by state, and a non-zero `zombie` is a parent with a bug. Line 3 splits CPU time: `us` user code, `sy` kernel (lesson 01's syscalls), `id` idle, `wa` waiting for I/O (a high `wa` with a low `us` is a disk problem, lesson 12), `st` stolen by the hypervisor (you are on an oversold VM). Lines 4 and 5 are `free`. Inside `top`, `M` sorts by memory, `P` by CPU, `1` shows each core, `c` shows full commands, `k` kills, `q` quits. `htop` is the same with colour and a mouse. `-bn1` prints once and exits, for scripts.

`pgrep -f pattern` finds PIDs by command line, `pgrep -x name` by exact name, and `pkill` is the same search with a signal on the end. Both will happily match more than you meant; run the `pgrep` first and read it.

### Signals: one integer, delivered asynchronously

A **signal** is a number the kernel delivers to a process outside its normal flow of execution. There are about thirty; a dozen matter. Each has a **default action**: terminate, terminate with a core dump, ignore, stop, or continue. A process may change what happens for most of them by installing a **handler** (a function the kernel calls when the signal arrives) or by setting the signal to be **ignored**. Two cannot be changed at all: `SIGKILL` (9) ends the process and `SIGSTOP` (19) pauses it, both without the process's participation.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 470" width="100%" style="max-width:880px" font-family="'JetBrains Mono', ui-monospace, monospace" role="img" aria-label="Signal delivery as a flow. A sender, such as the kill command, a terminal's Ctrl+C, the kernel's OOM killer, a timer, or the process itself, calls kill with a PID and a number. The kernel checks permission, the sender must be the same user or root, then marks the signal pending on the target. When the target next returns to user space it looks up its disposition for that number. Three branches: default action, which for most signals is terminate and for a few is ignore, stop or continue; ignore, set by the program with SIG_IGN, in which case nothing happens; or a handler, in which case the program's function runs and the process continues, and a blocking sleep or read that was interrupted returns early. A separate branch: SIGKILL and SIGSTOP never consult the disposition; the kernel acts immediately, no handler, no cleanup, no flush. A footnote lists the common signals: 1 HUP reload or terminal gone, 2 INT Ctrl+C, 9 KILL, 10 and 12 USR1 and USR2 program-defined, 13 PIPE, 14 ALRM, 15 TERM please stop, 17 CHLD a child changed state, 18 CONT, 19 STOP, 20 TSTP Ctrl+Z, and that a shell reports death by signal N as 128 plus N.">
  <defs>
    <marker id="p1l10b-ar" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker>
    <marker id="p1l10b-ard" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#d64545"/></marker>
  </defs>
  <text x="450" y="26" text-anchor="middle" font-size="14.5" font-weight="700" fill="currentColor">A signal is a number; what it does depends on the receiver, except for 9 and 19</text>
  <rect x="40" y="50" width="240" height="90" rx="9" fill="#7c5cff" fill-opacity="0.10" stroke="#7c5cff" stroke-width="1.7" stroke-linejoin="round"/>
  <text x="160" y="72" text-anchor="middle" font-size="10" font-weight="700" fill="#7c5cff">THE SENDER</text>
  <g text-anchor="middle" font-size="8.5" fill="currentColor">
    <text x="160" y="90">kill -TERM 1234 · Ctrl+C at the terminal</text>
    <text x="160" y="104">the OOM killer · a timer (alarm) · a crash</text>
    <text x="160" y="118">systemctl stop · docker stop · itself</text>
    <text x="160" y="132" opacity="0.75">all end in kill(pid, signum)</text>
  </g>
  <rect x="330" y="50" width="240" height="90" rx="9" fill="#0fa07f" fill-opacity="0.10" stroke="#0fa07f" stroke-width="1.7" stroke-linejoin="round"/>
  <text x="450" y="72" text-anchor="middle" font-size="10" font-weight="700" fill="#0fa07f">THE KERNEL</text>
  <g text-anchor="middle" font-size="8.5" fill="currentColor">
    <text x="450" y="90">permission: same uid, or root</text>
    <text x="450" y="104">mark the signal pending on the target</text>
    <text x="450" y="118">deliver when it next returns to user space</text>
    <text x="450" y="132" opacity="0.75">(a sleeping process is woken to receive it)</text>
  </g>
  <rect x="620" y="50" width="240" height="90" rx="9" fill="#e0930f" fill-opacity="0.10" stroke="#e0930f" stroke-width="1.7" stroke-linejoin="round"/>
  <text x="740" y="72" text-anchor="middle" font-size="10" font-weight="700" fill="#e0930f">THE TARGET'S DISPOSITION</text>
  <g text-anchor="middle" font-size="8.5" fill="currentColor">
    <text x="740" y="90">one entry per signal number:</text>
    <text x="740" y="104">default · ignore · a handler function</text>
    <text x="740" y="118">set with signal() / sigaction()</text>
    <text x="740" y="132" opacity="0.75">inherited across fork AND exec</text>
  </g>
  <g fill="none" stroke="currentColor" stroke-width="1.6">
    <path d="M282 95 L326 95" marker-end="url(#p1l10b-ar)"/>
    <path d="M572 95 L616 95" marker-end="url(#p1l10b-ar)"/>
  </g>
  <!-- three outcomes -->
  <g stroke-linejoin="round" stroke-width="1.6">
    <rect x="40"  y="190" width="250" height="100" rx="9" fill="#7f7f7f" fill-opacity="0.12" stroke="#7f7f7f"/>
    <rect x="325" y="190" width="250" height="100" rx="9" fill="#7f7f7f" fill-opacity="0.12" stroke="#7f7f7f"/>
    <rect x="610" y="190" width="250" height="100" rx="9" fill="#0fa07f" fill-opacity="0.12" stroke="#0fa07f"/>
  </g>
  <g text-anchor="middle" font-size="8.5" fill="currentColor">
    <text x="165" y="210" font-size="10" font-weight="700">DEFAULT</text>
    <text x="165" y="228">TERM, INT, HUP, USR1, ALRM, PIPE: terminate</text>
    <text x="165" y="242">SEGV, ABRT, QUIT: terminate + core dump</text>
    <text x="165" y="256">CHLD, WINCH: ignore · STOP, TSTP: stop</text>
    <text x="165" y="276" opacity="0.75">the shell reports 128 + N</text>
    <text x="450" y="210" font-size="10" font-weight="700">IGNORED (SIG_IGN)</text>
    <text x="450" y="228">nothing happens; the signal is dropped</text>
    <text x="450" y="242">the stubborn child in Build It</text>
    <text x="450" y="256">Python ignores PIPE by default (lesson 07)</text>
    <text x="450" y="276" opacity="0.75">visible in /proc/PID/status SigIgn</text>
    <text x="740" y="210" font-size="10" font-weight="700" fill="#0fa07f">A HANDLER</text>
    <text x="740" y="228">the function runs; the process continues</text>
    <text x="740" y="242">a sleep() or read() in progress returns early</text>
    <text x="740" y="256">graceful shutdown lives here</text>
    <text x="740" y="276" opacity="0.75">visible in SigCgt</text>
  </g>
  <g fill="none" stroke="currentColor" stroke-width="1.5">
    <path d="M700 142 L200 186" marker-end="url(#p1l10b-ar)"/>
    <path d="M730 142 L470 186" marker-end="url(#p1l10b-ar)"/>
    <path d="M745 142 L745 186" marker-end="url(#p1l10b-ar)"/>
  </g>
  <rect x="40" y="310" width="820" height="50" rx="9" fill="#d64545" fill-opacity="0.08" stroke="#d64545" stroke-width="1.8" stroke-linejoin="round"/>
  <text x="450" y="330" text-anchor="middle" font-size="10" font-weight="700" fill="#d64545">SIGKILL (9) and SIGSTOP (19) never consult the disposition</text>
  <text x="450" y="348" text-anchor="middle" font-size="8.5" fill="currentColor">the kernel ends or pauses the process itself: no handler, no cleanup, no flushed buffer. Even root cannot make a program catch them.</text>
  <path d="M450 142 L450 306" fill="none" stroke="#d64545" stroke-width="1.6" stroke-dasharray="5 4" marker-end="url(#p1l10b-ard)"/>
  <rect x="40" y="376" width="820" height="60" rx="9" fill="#7f7f7f" fill-opacity="0.08" stroke="#7f7f7f" stroke-width="1.4" stroke-linejoin="round"/>
  <g font-size="8.5" fill="currentColor">
    <text x="56" y="396">1 HUP  reload config, or "your terminal went away"   2 INT  Ctrl+C   9 KILL   10/12 USR1/USR2  program-defined   13 PIPE  reader gone</text>
    <text x="56" y="412">14 ALRM  a timer   15 TERM  "please stop": the default of kill   17 CHLD  a child changed state   18 CONT   19 STOP   20 TSTP  Ctrl+Z</text>
    <text x="56" y="428" opacity="0.8">exit status when killed by signal N: 128 + N. So 143 is TERM, 137 is KILL, 130 is Ctrl+C, 139 is a segfault, 141 is a broken pipe.</text>
  </g>
  <text x="450" y="458" text-anchor="middle" font-size="10.5" fill="currentColor" opacity="0.9">Send TERM and let the program decide. Send KILL and the kernel decides. Everything in between is the program's contract with you.</text>
</svg>
```

Three properties shape how you use them. **Delivery is asynchronous**: the signal arrives whenever the process next returns to user space, and a `sleep()` or `read()` it was blocked in returns early. **Dispositions are inherited across `fork` and `exec`**, which is how lesson 07's Python child ended up ignoring `SIGPIPE`, and why a service started by a script that ignored `SIGHUP` ignores it too. And **permission is by user**: you may signal your own processes, root may signal anything, which is the `Operation not permitted` from `kill`.

The signals a backend engineer sends and handles:

| signal | number | who sends it | what a well-behaved service does |
|---|---|---|---|
| `SIGTERM` | 15 | `kill`, `systemctl stop`, `docker stop`, Kubernetes | stop accepting, finish in-flight work, close files, exit 0 |
| `SIGINT` | 2 | `Ctrl+C` | the same as TERM, so development matches production |
| `SIGHUP` | 1 | the pty when a terminal closes; `kill -HUP` by convention | reload config and reopen logs, or exit if it does not reload |
| `SIGKILL` | 9 | `kill -9`, the OOM killer, `docker stop` after its timeout | nothing: it never sees it |
| `SIGUSR1`, `SIGUSR2` | 10, 12 | you | whatever the program documents: dump stats, rotate, toggle debug |
| `SIGCHLD` | 17 | the kernel, when a child exits or stops | call `wait()` so the child does not stay a zombie |
| `SIGPIPE` | 13 | the kernel, on a write with no reader | die quietly, or handle `EPIPE` (lesson 07) |
| `SIGALRM` | 14 | a timer the process set | a timeout fired |
| `SIGSTOP`, `SIGCONT` | 19, 18 | `Ctrl+Z` (as `SIGTSTP`, 20), `fg`, `bg`, a debugger | nothing: the kernel pauses and resumes it |

### The shutdown contract, and the exit codes that record it

Every service manager stops a process the same way: send `SIGTERM`, wait a grace period, send `SIGKILL`. `systemd` waits `TimeoutStopSec` (90 s by default), Docker waits 10 s, Kubernetes waits `terminationGracePeriodSeconds` (30 s). The contract for a service is therefore: **on `SIGTERM`, stop taking new work, finish what is in flight within the grace period, and exit 0.** A service that ignores `SIGTERM` or handles it by only logging is killed at the deadline with whatever it was doing severed, and the last lines of its log lost in a buffer.

The exit status records which way it went, and you will read these numbers in `systemctl status`, `docker inspect`, and every CI log: **143** means TERM and cooperation (128 + 15), **137** means KILL (128 + 9), which is either the deadline or the OOM killer, **130** is `Ctrl+C`, **139** is a segfault. The `timeout` command wraps the whole ladder for one-off commands: `timeout 30 cmd` sends TERM at 30 s and exits **124** if it had to; `timeout -k 5 30 cmd` follows with KILL five seconds later.

### Zombies and orphans

When a process exits, the kernel frees its memory and descriptors immediately but keeps the table entry, with the exit status in it, until the parent calls `wait()`. That interval is the **zombie** state: `Z` in `ps`, `<defunct>` after the name. A zombie uses no memory and cannot be killed, because there is nothing left to kill; the only fix is for the parent to wait, or to die so that PID 1 inherits and reaps the child. A single zombie is normal for a few milliseconds. Hundreds of them under one parent is a program that forks and never waits, and it is leaking PIDs against `pid_max` (4,194,304 on the sandbox, 32,768 on older kernels).

An **orphan** is the reverse: the parent exits first. The kernel re-parents the child to PID 1 (`init`, `systemd`, or in a container whatever ran first), whose whole job includes waiting for adopted children. This is why a container's PID 1 matters (Phase 11): if it is a shell script that never waits, every orphan in the container becomes a permanent zombie. It is also how daemons have always detached: fork, let the parent exit, and be adopted.

### Jobs, the terminal, and why a process dies when you log out

The shell gives you job control over the processes it starts. `cmd &` runs it in the background and `$!` is its PID; `jobs` lists them; `Ctrl+Z` sends `SIGTSTP` to the foreground job (state `T`); `fg` and `bg` send `SIGCONT` and choose which job owns the terminal; `wait` blocks until background jobs finish. The machinery underneath is two more numbers in the process record, and they explain the most common way a service dies by accident:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 400" width="100%" style="max-width:880px" font-family="'JetBrains Mono', ui-monospace, monospace" role="img" aria-label="A session drawn as a large box tied to one controlling terminal, /dev/pts/0, with the login shell as session leader. Inside it are process groups: the foreground group, here a pipeline of grep and sort, which receives Ctrl+C as SIGINT and Ctrl+Z as SIGTSTP from the terminal; and background groups, a sleep started with an ampersand, which do not receive keyboard signals and are stopped if they try to read the terminal. When the terminal closes, the kernel sends SIGHUP to the session leader, and the shell forwards it to every job it knows about, so everything in the session dies by default. Outside the box, a process started with setsid or nohup: setsid puts it in a new session with no controlling terminal so no SIGHUP ever reaches it; nohup keeps it in the session but makes it ignore SIGHUP and redirects its output to nohup.out; disown makes the shell forget the job so it does not forward the signal; tmux or screen keep a session alive on a server after you disconnect; and a systemd unit avoids the terminal entirely. A note explains that kill with a negative PID signals a whole process group, which is how a pipeline or a parent with workers is stopped at once.">
  <defs>
    <marker id="p1l10c-ar" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker>
    <marker id="p1l10c-ard" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#d64545"/></marker>
  </defs>
  <text x="450" y="26" text-anchor="middle" font-size="14.5" font-weight="700" fill="currentColor">Sessions and process groups: why Ctrl+C hits the pipeline and logging out kills the job</text>
  <rect x="40" y="50" width="560" height="270" rx="12" fill="#7c5cff" fill-opacity="0.06" stroke="#7c5cff" stroke-width="2" stroke-linejoin="round"/>
  <text x="56" y="72" font-size="10.5" font-weight="700" fill="#7c5cff">THE SESSION · controlling terminal /dev/pts/0 · leader: bash (pid 1)</text>
  <rect x="60" y="90" width="250" height="90" rx="9" fill="#0fa07f" fill-opacity="0.12" stroke="#0fa07f" stroke-width="1.7" stroke-linejoin="round"/>
  <text x="185" y="110" text-anchor="middle" font-size="10" font-weight="700" fill="#0fa07f">FOREGROUND GROUP · pgid 7</text>
  <text x="185" y="128" text-anchor="middle" font-size="8.5" fill="currentColor">grep ERROR app.log | sort</text>
  <text x="185" y="144" text-anchor="middle" font-size="8.5" fill="currentColor">Ctrl+C → SIGINT to the whole group</text>
  <text x="185" y="158" text-anchor="middle" font-size="8.5" fill="currentColor">Ctrl+Z → SIGTSTP to the whole group</text>
  <text x="185" y="172" text-anchor="middle" font-size="8" fill="currentColor" opacity="0.75">owns the keyboard</text>
  <rect x="330" y="90" width="250" height="90" rx="9" fill="#7f7f7f" fill-opacity="0.12" stroke="#7f7f7f" stroke-width="1.7" stroke-linejoin="round"/>
  <text x="455" y="110" text-anchor="middle" font-size="10" font-weight="700" fill="currentColor">BACKGROUND GROUPS · pgid 14 ...</text>
  <text x="455" y="128" text-anchor="middle" font-size="8.5" fill="currentColor">sleep 300 &amp;   ·   ./server &amp;</text>
  <text x="455" y="144" text-anchor="middle" font-size="8.5" fill="currentColor">no keyboard signals reach them</text>
  <text x="455" y="158" text-anchor="middle" font-size="8.5" fill="currentColor">reading the terminal stops them (SIGTTIN)</text>
  <text x="455" y="172" text-anchor="middle" font-size="8" fill="currentColor" opacity="0.75">jobs lists them; fg brings one forward</text>
  <rect x="60" y="200" width="520" height="104" rx="9" fill="#d64545" fill-opacity="0.08" stroke="#d64545" stroke-width="1.7" stroke-linejoin="round"/>
  <text x="320" y="220" text-anchor="middle" font-size="10" font-weight="700" fill="#d64545">WHEN THE TERMINAL CLOSES (ssh drops, the window is shut)</text>
  <g text-anchor="middle" font-size="8.5" fill="currentColor">
    <text x="320" y="240">the kernel sends SIGHUP to the session leader, the shell</text>
    <text x="320" y="255">the shell forwards SIGHUP to every job it knows about, then exits</text>
    <text x="320" y="270">SIGHUP's default action is terminate: your ./server &amp; is gone</text>
    <text x="320" y="290" opacity="0.8">this is how "it died when I logged out" happens, every time</text>
  </g>
  <rect x="620" y="50" width="250" height="270" rx="12" fill="#0fa07f" fill-opacity="0.06" stroke="#0fa07f" stroke-width="2" stroke-linejoin="round"/>
  <text x="745" y="72" text-anchor="middle" font-size="10.5" font-weight="700" fill="#0fa07f">OUTSIDE THE SESSION</text>
  <g font-size="8.5" fill="currentColor">
    <text x="636" y="98" font-weight="700">setsid cmd</text>
    <text x="636" y="112">a new session, no terminal:</text>
    <text x="636" y="126">no SIGHUP can arrive</text>
    <text x="636" y="150" font-weight="700">nohup cmd &amp;</text>
    <text x="636" y="164">same session, but SIGHUP is</text>
    <text x="636" y="178">ignored; output → nohup.out</text>
    <text x="636" y="202" font-weight="700">disown</text>
    <text x="636" y="216">the shell forgets the job and</text>
    <text x="636" y="230">does not forward SIGHUP</text>
    <text x="636" y="254" font-weight="700">tmux / screen</text>
    <text x="636" y="268">a session that survives you</text>
    <text x="636" y="292" font-weight="700">a systemd unit (lesson 11)</text>
    <text x="636" y="306">never had a terminal at all</text>
  </g>
  <text x="450" y="352" text-anchor="middle" font-size="10" fill="currentColor" opacity="0.9">kill -TERM -- -PGID signals a whole process group: a pipeline, or a parent and its workers, in one call.</text>
  <text x="450" y="372" text-anchor="middle" font-size="9.5" fill="currentColor" opacity="0.72">A process you want to outlive your login belongs in a unit file. Everything else on this page is a workaround for not having one yet.</text>
</svg>
```

A **session** is a set of processes tied to one controlling terminal, led by your login shell. Within it, each pipeline is a **process group** (`PGID`), and the terminal delivers `Ctrl+C` and `Ctrl+Z` to the whole foreground group at once, which is how one keystroke stops `grep | sort | uniq`. When the terminal goes away, the kernel sends `SIGHUP` to the session leader, the shell forwards it to its jobs, and the default action of `SIGHUP` is to terminate. That is the whole story of "my server died when I closed my laptop."

The escapes are all on the diagram. `setsid cmd` starts it in a new session with no terminal, which is what daemons do and what the script demonstrates with `os.setsid()`. `nohup cmd &` keeps it in your session but makes it ignore `SIGHUP`. `disown` after `&` makes the shell forget it. `tmux` keeps a whole session alive on the server between connections. And a `systemd` unit never had a terminal in the first place, which is the answer for anything that should outlive you (lesson 11). `kill -- -PGID` (note the minus) signals an entire group, which is how you stop a parent and all its workers in one call, and what `systemd` does on your behalf with `KillMode=control-group`.

### Priority and threads

`nice -n 10 cmd` starts a process with lower scheduling priority (higher niceness: 0 is default, 19 is lowest, negative needs root); `renice -n 15 -p PID` changes a running one; `ps` shows it in the `NI` column and `N` in `STAT`. It is a hint to lesson 02's scheduler, useful for a backup or a batch job that should never compete with the service; cgroups (Phase 11) are the hard version.

A process may contain several **threads**, each a schedulable task with its own TID sharing one PID, one address space and one set of descriptors. `ps -L` lists them, `NLWP` counts them, `/proc/<pid>/task/` has a directory per thread, and `Threads:` in `status` is the count. Signals are delivered to the process and handled by whichever thread has not blocked them; `kill` of the PID affects all of them. Phase 9 is where threads earn their keep.

## Build It

The script for this lesson is [`code/procs.py`](../code/procs.py). It reads `/proc` to build `ps` and `pstree`, then forks children and sends them signals, reporting each child's fate from `waitpid` exactly as a shell would. It runs on macOS too, using `ps` where `/proc` is missing:

```bash
python3 phases/01-linux-and-the-command-line/10-processes-and-signals/code/procs.py
```

**`ps` from `/proc`** is a loop over the numeric directories, a `status` parse per PID, and two samples of `stat` 0.2 s apart for `%CPU`:

```python
pids = sorted(int(p) for p in os.listdir("/proc") if p.isdigit())
before = {pid: cpu_ticks(pid) for pid in pids}                  # utime + stime, in clock ticks
time.sleep(0.2)
for pid in pids:
    st = read_status(pid)                                        # Name, State, PPid, Uid, VmRSS ...
    cpu = (cpu_ticks(pid) - before[pid]) / os.sysconf("SC_CLK_TCK") / 0.2 * 100
```

**The graceful handler** is what every server should install, and what the runbook calls the contract:

```python
def on_term(signum, frame):
    print("got SIGTERM, finishing the request in flight")
    stop = True                                                  # the loop notices and exits 0
signal.signal(signal.SIGTERM, on_term)
signal.signal(signal.SIGHUP, on_hup)                             # reload, do not exit
signal.signal(signal.SIGUSR1, on_usr1)                           # dump stats
while not stop:
    time.sleep(0.05)                                             # a sleep interrupted by a signal returns early
```

Run in the sandbox, the four signal experiments read like the diagram:

```console
2 · SIGTERM to a process with a handler: graceful shutdown
   parent: child 7 is state S (S = sleeping, waiting in sleep())
      child 7: got SIGHUP, reloading config (not exiting)
      child 7: got SIGUSR1, dumping stats: 3 requests served
      child 7: got SIGTERM, finishing the request in flight
      child 7: cleanup done, exiting 0
   graceful child: exited with status 0

3 · SIGTERM to a process that ignores it, then SIGKILL
   after SIGTERM: child 8 is still state S: it installed SIG_IGN, so the kernel dropped the signal
   stubborn child: killed by signal 9 (SIGKILL); a shell would report $? = 137

4 · SIGSTOP and SIGCONT: pausing a process (Ctrl+Z, fg, bg)
   after SIGSTOP: state T (T = stopped; it gets no CPU at all, like Ctrl+Z)
   after SIGCONT: state S (running again, like fg or bg)
```

The **zombie** is caught in `/proc` between the child's exit and the parent's `wait`, and then gone:

```console
5 · A zombie: exited, but the parent has not called wait() yet
   child 10 exited with 7; before the parent waits it is state Z (Z = zombie: a PID and an exit status, nothing else)
   /proc/10/status says: State=Z (zombie)  VmRSS=gone  <- no memory, no files, just the record
   parent called wait(): status 7 collected; now /proc/10 exists? False
```

The **orphan** is found by scanning `/proc` for a process whose `PPid` became 1, and the **setsid** child reports its own session id and keeps running after its parent has moved on:

```console
6 · An orphan: the parent dies first, and init (or a subreaper) adopts the child
      middle 11: forked grandchild 12, now exiting without waiting
   grandchild 12 now has PPid 1: adopted by PID 1, which will wait() for it so it never becomes a zombie

7 · setsid: how nohup and daemons survive the terminal closing
      daemon-style child 13: session id 13, parent will exit; I keep running
   parent: child 13 has its own session (13 vs mine 1); `nohup cmd &` and systemd do this
      daemon-style child 13: still alive after the parent 'left'; exiting
```

One detail differs between platforms, and it is worth noticing: the signal numbers. `SIGUSR1` is 10 on Linux and 30 on macOS, `SIGSTOP` is 19 and 17. The names are portable; the numbers are not, which is why `kill -TERM` beats `kill -15` in a script.

## Use It

Inside `make shell`, the same facts through the standard tools. A `sleep` as the victim, its record in `/proc`, and the ladder from TERM to KILL with the exit codes each produces:

```console
$ sleep 300 &  P=$!
$ grep -E '^(Name|State|PPid|VmRSS|Threads|SigIgn|SigCgt)' /proc/$P/status
Name:   sleep
State:  S (sleeping)
PPid:   1
VmRSS:      1656 kB
Threads:        1
SigIgn: 0000000200000006          <- a bitmask: which signals it ignores
SigCgt: 0000000000000000          <- which it catches: none; sleep has no handlers
$ kill -TERM $P;  wait $P;  echo "TERM -> $?"
TERM -> 143
$ sleep 300 &  P=$!;  kill -KILL $P;  wait $P;  echo "KILL -> $?"
KILL -> 137
```

A process that ignores TERM, from the shell, and what it takes:

```console
$ bash -c 'trap "" TERM; sleep 300' &  P=$!
$ kill -TERM $P;  sleep 0.3;  ps -o pid,stat,cmd -p $P | tail -1
     38 S    sleep 300                          <- still there: TERM ignored
$ kill -KILL $P;  wait $P;  echo "exit status after KILL: $?"
exit status after KILL: 137
$ timeout 1 sleep 10;  echo "timeout exit: $?";  timeout -s KILL 1 sleep 10;  echo "with -s KILL: $?"
timeout exit: 124
with -s KILL: 137
```

Stopping and continuing, jobs, and a zombie made in one line and seen in `ps`:

```console
$ sleep 300 &  P=$!;  kill -STOP $P;  ps -o pid,stat= -p $P | tail -1;  kill -CONT $P;  ps -o pid,stat= -p $P | tail -1
     49 T
     49 S
$ bash -c 'sleep 2 & sleep 3 & jobs; echo last pid $!; wait; echo all done'
[1]-  Running                 sleep 2 &
[2]+  Running                 sleep 3 &
last pid 58
all done
$ python3 -c 'import os,time; os.fork() or os._exit(0); time.sleep(1.5)' &  sleep 0.5;  ps -eo pid,ppid,stat,cmd | grep defunct
     61      59 Z    [python3] <defunct>
```

Sessions and groups: `nohup` keeps the session and ignores the signal, `setsid` gets a session of its own (`SID` becomes the process's own PID), and a whole pipeline dies to one negative-PID `kill`:

```console
$ nohup sleep 300 >/dev/null 2>&1 &  P=$!;  ps -o pid,pgid,sid,stat,cmd -p $P | tail -1
     65       1       1 S    sleep 300
$ setsid sleep 300 &  P2=$(pgrep -x sleep | tail -1);  ps -o pid,pgid,sid,stat,cmd -p $P2 | tail -1
     69      69      69 Ss   sleep 300
$ bash -c 'set -m; sleep 300 | sleep 300 &  PG=$(ps -o pgid= -p $!);  echo "pipeline pgid $PG";  kill -TERM -- -$PG;  sleep 0.2;  echo "$(ps -o pid= -g $PG | wc -l) left in the group"'
pipeline pgid 7
0 left in the group
```

Priority, threads, and the kernel's side of a signal caught by `strace`:

```console
$ nice -n 10 sleep 300 &  P=$!;  ps -o pid,ni,stat,cmd -p $P | tail -1;  renice -n 15 -p $P >/dev/null;  ps -o pid,ni,stat,cmd -p $P | tail -1
     76  10 SN   sleep 300
     76  15 SN   sleep 300
$ ps -o pid,tid,nlwp,stat,comm -L -p 20          # a Python process with three extra threads
    PID     TID NLWP STAT COMMAND
     20      20    4 Sl   python3
     20      22    4 Sl   python3
     20      23    4 Sl   python3
     20      24    4 Sl   python3
$ strace -e trace=kill -o /tmp/k.txt bash -c 'trap "echo caught" TERM; kill -TERM $$; echo after';  grep -E 'kill|SIGTERM' /tmp/k.txt
caught
after
kill(110, SIGTERM)                      = 0
--- SIGTERM {si_signo=SIGTERM, si_code=SI_USER, si_pid=110, si_uid=0} ---
```

The last trace is the whole mechanism in two lines: a `kill` syscall carrying the number, and the kernel's delivery record naming who sent it (`si_pid`) and as whom (`si_uid`), followed by the handler's `caught` and the program carrying on. Finally the limits that bound all of this: `ulimit -u` is the per-user process cap (32,137 here), `/proc/sys/kernel/pid_max` is the largest PID (4,194,304), and `threads-max` the system-wide thread cap.

## Ship It

The artifact for this lesson is a runbook: [`outputs/runbook-stopping-a-process.md`](../outputs/runbook-stopping-a-process.md). It is the escalation ladder: identify the PID from the source of truth and look at its tree and state first; stop it through its service manager if it has one; `TERM`, wait the grace period, the whole process group if it has workers, then `KILL`; what each rung leaves behind. Then the four reasons a process will not die (TERM ignored, state `D`, a zombie, a supervisor that restarts it) with the diagnosis for each, the reverse question of why a process disappeared on its own (137 and the OOM killer, 143 and a deploy, a crash, `SIGHUP` from a closed terminal), and the five rules for writing a service that stops well.

## Think about it

1. `docker stop` on a container whose PID 1 is a shell script that runs your server takes exactly ten seconds and the server's shutdown log line never appears. Explain with the shutdown contract and with what a shell does with `SIGTERM` by default.
2. `ps` shows 3,000 `<defunct>` entries under a PID that is alive and idle. Nothing else is wrong yet. What will go wrong, when, and what are the two fixes, one immediate and one permanent?
3. A colleague starts a migration with `./migrate.sh &` over SSH, the connection drops, and the migration is half done. Which signal, from where, and give three ways they should have started it, from most to least appropriate.
4. A process in state `D` has been unkillable for ten minutes. `cat /proc/<pid>/wchan` says `nfs_wait_bit_killable`. What is it waiting for, why does `kill -9` not help, and what would?

## Key takeaways

- A process is a **record**: PID, PPID, user, state, group, session, descriptors, exit status, all visible in `/proc/<pid>/`. `ps` reads it; `top` subtracts two readings. `STAT` letters: `R S D T Z`, with `s l + N` suffixes.
- **A signal is a number** with a per-process disposition: default, ignore, or a handler. `SIGKILL` and `SIGSTOP` bypass the disposition. Dispositions are inherited across `fork` and `exec`. You may signal your own processes; root may signal any.
- **The shutdown contract**: `TERM`, a grace period, then `KILL`. A service handles `TERM` by draining and exiting 0. `143` is TERM, `137` is KILL or the OOM killer, `124` is `timeout`.
- A **zombie** is an exited child whose parent has not called `wait()`: a PID and a status, unkillable, harmless alone and a leak in thousands. An **orphan** is adopted by PID 1, which reaps it. A container's PID 1 must do the same.
- **Sessions and process groups** explain the terminal: `Ctrl+C` goes to the foreground group, a closed terminal sends `SIGHUP` to the session, and `setsid`, `nohup`, `disown`, `tmux` or a unit file are how a process survives you. `kill -- -PGID` stops a group at once.
- `nice`/`renice` hint the scheduler; threads share a PID and are listed with `ps -L`; `pgrep` before `pkill`; `systemctl stop` before `kill` for anything a manager owns.

Next: [Boot, init & systemd](../11-boot-init-and-systemd/). You can stop a process. Now the program that starts them all at boot and restarts yours when it dies: a supervisor built in Python, then `systemd` units, `journalctl`, timers and log rotation.
