---
name: runbook-proc-and-sys-windows
description: The question-to-file map for /proc and /sys — which kernel window answers "is the box out of memory", "what is this PID doing", "who holds that port", "what is the disk doing", and the command that reads each one, so you can diagnose a Linux server with nothing but cat
phase: 01
lesson: 02
---

# /proc and /sys: which file answers which question

Everything a monitoring agent, `top`, `free`, `ss`, `lsof` or `ps` tells you
is read from a file under `/proc` or `/sys`. Those files are not on disk; they
are the kernel answering the question at the moment you read. When the fancy
tool is missing, broken, or lying, go to the file. This is the map.

All paths are Linux. `<pid>` is a process id; `self` always means "the process
doing the reading," so `cat /proc/self/status` describes `cat`.

## 1 · "Is the machine in trouble?" (the whole box)

| question | file | read it with | what to look at |
|---|---|---|---|
| Is the CPU overloaded? | `/proc/loadavg` | `cat /proc/loadavg`, `uptime` | first three numbers = runnable + uninterruptible tasks averaged over 1, 5, 15 min. Compare with `nproc`: load 8 on 2 CPUs is a queue; load 8 on 16 is idle |
| How many CPUs do I have? | `/proc/cpuinfo` | `nproc`, `grep -c processor /proc/cpuinfo` | inside a container this is the **host's** count; the cgroup limit is what you actually get (Phase 11, lesson 01) |
| Is it out of memory? | `/proc/meminfo` | `free -h`, `grep -E 'MemTotal\|MemAvailable\|Cached\|Swap' /proc/meminfo` | **MemAvailable**, not MemFree. Low MemFree with high Cached is healthy; low MemAvailable with growing SwapUsed is not |
| Is it swapping right now? | `/proc/vmstat` | `vmstat 1 5` | `si`/`so` columns (swap in/out) non-zero for consecutive seconds = thrashing |
| Did the OOM killer fire? | kernel log | `dmesg -T \| grep -i 'out of memory'`, `journalctl -k` | the line names the killed PID and its RSS (lesson 12) |
| How long since boot? | `/proc/uptime` | `uptime -p` | first number = seconds up. A surprisingly small number means it rebooted |
| What kernel exactly? | `/proc/version`, `/proc/sys/kernel/osrelease` | `uname -r` | version, who built it, compiler |
| Which distribution? | `/etc/os-release` | `cat /etc/os-release` | `PRETTY_NAME`, `VERSION_ID`. Not a kernel file: the distribution wrote it |
| What is the disk doing? | `/proc/diskstats`, `/sys/block/*/stat` | `iostat -x 1`, `cat /proc/diskstats` | reads/writes completed, sectors, and the time-in-queue column that shows saturation |
| What is mounted where? | `/proc/mounts`, `/proc/self/mountinfo` | `findmnt`, `mount`, `df -h` | the filesystem type per mount: `overlay` = container root, `nfs` = network, `tmpfs` = RAM |
| Is the disk full, or out of inodes? | (stat on the filesystem) | `df -h`, `df -i` | `df -i` at 100% with `df -h` at 40% is the "no space left" that is actually inodes (lesson 04) |

## 2 · "What is this process doing?" (one PID)

| question | file | read it with | what to look at |
|---|---|---|---|
| Is it alive, and in what state? | `/proc/<pid>/status` | `cat /proc/<pid>/status \| head -12` | `State:` R running, S sleeping, D uninterruptible (stuck in I/O), Z zombie, T stopped |
| What command started it? | `/proc/<pid>/cmdline` | `tr '\0' ' ' < /proc/<pid>/cmdline` | NUL-separated argv; `ps` shows the same thing |
| Which binary is it, really? | `/proc/<pid>/exe` | `ls -l /proc/<pid>/exe` | a symlink to the executable; `(deleted)` after it means the binary was replaced under a running process: restart it |
| Where is it running from? | `/proc/<pid>/cwd` | `ls -l /proc/<pid>/cwd` | the working directory, the usual cause of relative-path "file not found" |
| What environment does it have? | `/proc/<pid>/environ` | `tr '\0' '\n' < /proc/<pid>/environ` | `DATABASE_URL` and friends as the process actually sees them, not as you think you set them |
| What files and sockets is it holding? | `/proc/<pid>/fd/` | `ls -l /proc/<pid>/fd`, `ls /proc/<pid>/fd \| wc -l` | each entry is a symlink: a path, `socket:[inode]`, `pipe:[inode]`, `anon_inode:[eventpoll]`. A count that keeps rising is a leak |
| What is its descriptor limit? | `/proc/<pid>/limits` | `grep 'open files' /proc/<pid>/limits` | soft and hard `Max open files`; compare with the fd count above |
| How much memory is it using? | `/proc/<pid>/status` | `grep -E 'VmRSS\|VmSize\|VmSwap' /proc/<pid>/status` | **VmRSS** is RAM actually resident; VmSize is address space reserved and is usually meaningless |
| Where does that memory go? | `/proc/<pid>/smaps_rollup`, `/proc/<pid>/maps` | `cat /proc/<pid>/smaps_rollup` | `Rss`, `Pss` (proportional share of shared pages), `Anonymous` (heap) vs file-backed |
| How much CPU has it used? | `/proc/<pid>/stat` | `ps -o pid,etime,time,pcpu -p <pid>` | user and system ticks; a high system share means it lives in syscalls |
| Is it being switched out a lot? | `/proc/<pid>/status` | `grep ctxt /proc/<pid>/status` | `voluntary` = it sleeps (waits on I/O or locks); `nonvoluntary` = preempted (CPU contention) |
| What is it waiting on, right now? | `/proc/<pid>/wchan`, `/proc/<pid>/stack` (root) | `cat /proc/<pid>/wchan` | the kernel function it sleeps in; `strace -p` shows the syscall (lesson 01 runbook) |
| Which threads does it have? | `/proc/<pid>/task/` | `ls /proc/<pid>/task`, `top -H -p <pid>` | one directory per thread, each with its own `status` and `stat` |
| What cgroup is it in? | `/proc/<pid>/cgroup` | `cat /proc/<pid>/cgroup` | the path under `/sys/fs/cgroup/` where its CPU and memory limits live (Phase 11) |
| What is its OOM risk? | `/proc/<pid>/oom_score` | `cat /proc/<pid>/oom_score` | higher = killed first when memory runs out; `oom_score_adj` tunes it |
| Who is its parent? | `/proc/<pid>/status` | `grep PPid /proc/<pid>/status`, `pstree -p <pid>` | PPid 1 means it was orphaned and adopted by init |

## 3 · "Who is on the network?"

| question | file | read it with | what to look at |
|---|---|---|---|
| Which interfaces exist, and their traffic? | `/proc/net/dev`, `/sys/class/net/` | `ip -s link`, `cat /proc/net/dev` | bytes and packets in and out per interface; error and drop counters |
| What is my MAC, MTU, link state? | `/sys/class/net/<if>/{address,mtu,operstate}` | `cat /sys/class/net/eth0/operstate` | `up`/`down`; an MTU mismatch shows up as large transfers hanging |
| Who is listening on which port? | `/proc/net/tcp`, `/proc/net/tcp6`, `/proc/net/udp` | `ss -tlnp` | state `0A` = LISTEN in the raw file; `ss` decodes it. `-p` names the PID (needs root for others' sockets) |
| Which connections are open? | `/proc/net/tcp` | `ss -tan`, `ss -tan state established` | state `01` = ESTABLISHED, `06` = TIME_WAIT. Thousands of TIME_WAIT is normal after a burst; thousands of SYN_RECV is not |
| Is the accept queue overflowing? | `/proc/net/netstat` | `nstat -az \| grep -i listen`, `ss -tln` (Recv-Q on a LISTEN socket) | `ListenOverflows`/`ListenDrops` rising = backlog too small or the server too slow to `accept()` |
| What is the routing table? | `/proc/net/route` (hex) | `ip route` | default gateway, per-interface routes |
| Which DNS servers am I using? | `/etc/resolv.conf` | `cat /etc/resolv.conf` | not a kernel file; systemd-resolved may point it at `127.0.0.53` |
| Which ports may a client use? | `/proc/sys/net/ipv4/ip_local_port_range` | `sysctl net.ipv4.ip_local_port_range` | ~28,000 by default; exhausting them makes `connect()` fail with `EADDRNOTAVAIL` |
| Are packets being dropped by the kernel? | `/proc/net/softnet_stat`, `/proc/net/snmp` | `nstat`, `netstat -s` | retransmits, resets, listen drops |

## 4 · "What knob controls that?" (`/proc/sys`, a.k.a. sysctl)

Read with `sysctl <name>` or `cat /proc/sys/<name with dots as slashes>`. Write with `sysctl -w <name>=<value>` for now, and a file in `/etc/sysctl.d/` to survive reboot. Inside a container most of these are read-only or namespaced.

| knob | default (typical) | why a backend engineer touches it |
|---|---|---|
| `net.core.somaxconn` | 4096 | cap on the `listen()` backlog. A server under a connection burst refuses clients when the queue is full (Phase 2, lesson 09) |
| `net.ipv4.tcp_max_syn_backlog` | 1024 to 4096 | half-open connection queue during a burst or a SYN flood |
| `net.ipv4.ip_local_port_range` | 32768 60999 | widen it on a host that opens many outbound connections (a proxy, a crawler) |
| `net.ipv4.tcp_tw_reuse` | 2 | lets a client reuse TIME_WAIT ports; safe for clients, meaningless for servers |
| `net.ipv4.tcp_fin_timeout` | 60 | how long a closed socket lingers |
| `net.core.rmem_max`, `wmem_max` | ~200 KiB | socket buffer ceilings; raise for high-bandwidth, high-latency links |
| `fs.file-max` | huge | system-wide open file cap; rarely the limit you hit |
| `fs.nr_open` | 1048576 | ceiling for a process's `ulimit -n` |
| `fs.inotify.max_user_watches` | 8192 to 524288 | file watchers; dev tools and log shippers exhaust it |
| `vm.swappiness` | 60 (20 on some) | 0 to 100: how eagerly to swap anonymous memory vs drop page cache |
| `vm.overcommit_memory` | 0 | 0 heuristic, 1 always allow, 2 strict. Databases such as Redis ask for 1 |
| `vm.max_map_count` | 65530 | per-process mmap regions; Elasticsearch needs 262144 |
| `vm.dirty_ratio`, `vm.dirty_background_ratio` | 20, 10 | how much written-but-not-flushed data may sit in the page cache before writers are stalled |
| `kernel.pid_max` | 4194304 | largest PID; also the cap on threads system-wide |
| `kernel.panic`, `kernel.sysrq` | 0, 16 | reboot-on-panic delay; the magic SysRq key |

## 5 · Three habits

- **`self` is your friend.** Any `/proc/<pid>/` file can be tried on `/proc/self/` first to learn its format with zero risk.
- **Everything is text, so everything pipes.** `grep`, `awk` and `watch` work on these files exactly as on any other: `watch -n1 'grep -E "MemAvailable|Cached" /proc/meminfo'` is a memory monitor in one line (lesson 08).
- **Timestamps are yours to add.** The files show *now*. Two readings a second apart, subtracted, are a rate; that subtraction is all `vmstat`, `iostat` and `top` do.
