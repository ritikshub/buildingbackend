---
name: runbook-the-box-is-slow
description: The ten-minute triage for a slow or dying Linux server, organised by resource (CPU, memory, disk, network, file descriptors) and by the three questions to ask of each (how used, how saturated, any errors), with the exact command, the number to read, the threshold that means trouble, and the next question
phase: 01
lesson: 12
---

# The box is slow

Work the resources in order; stop at the first one that is saturated.
For each: **utilisation** (how busy), **saturation** (how much is
queued), **errors**. The commands read `/proc`; the thresholds are rules
of thumb that are right far more often than they are wrong.

## 0 · Thirty seconds of orientation

```bash
uptime                     # load average vs nproc; how long since boot (did it reboot?)
dmesg -T | tail -30        # or journalctl -k -n 30: OOM kills, disk errors, NIC resets, kernel complaints
systemctl list-units --failed
top -bn1 | head -15        # the header, then the top processes by CPU
free -h; df -h; df -i      # memory, disk space, inodes
```

- [ ] `uptime` small: it rebooted. `journalctl -b -1 -e` is the previous boot's last lines.
- [ ] `dmesg` has `Out of memory`, `I/O error`, `link is down`, `hung task`: go straight to that resource.
- [ ] Something in `--failed`: `systemctl status name`, then the lesson 11 checklist.

## 1 · CPU

| question | command | read | trouble when |
|---|---|---|---|
| how busy | `top -bn1 \| head -3`, `vmstat 1 5` | `us` + `sy`; `id` | `id` near 0 for minutes |
| what kind of busy | `vmstat 1 5` | `us` vs `sy` vs `wa` vs `st` | `sy` high: syscalls or the kernel (lesson 01); `wa` high: it is the disk, not the CPU; `st` high: noisy neighbours on the VM |
| how saturated | `vmstat 1 5` first column `r`; `cat /proc/loadavg` | `r` and load vs `nproc` | `r` > CPUs, or load / CPUs > 1 sustained |
| who | `top -bn1 -o %CPU \| head -15`, `ps -eo pid,pcpu,etime,cmd --sort=-pcpu \| head` | the process, its age | one process at 100 × N%: a busy loop or real work; many: a fleet under load |
| pressure | `cat /proc/pressure/cpu` | `some avg10` | > 10% means tasks waited for a CPU in the last 10 s |

- [ ] One process pegged with no traffic: a busy loop, a GC storm, a regex on a huge input. `strace -c -p PID` (lesson 01's runbook) and `py-spy`/`perf top` (Phase 9, lesson 13).
- [ ] `sy` dominates: too many small syscalls (lesson 01), or the kernel doing something on the process's behalf (copying, TCP, page faults).
- [ ] Load is high but `id` is also high: the load is `D`-state tasks. It is the disk or a network mount, section 3.
- [ ] Inside a container: `nproc` may say 10 while `cat /sys/fs/cgroup/cpu.max` says `200000 100000` (2 CPUs). `cpu.stat` shows `nr_throttled`. The cgroup is the real ceiling (Phase 11).

## 2 · Memory

| question | command | read | trouble when |
|---|---|---|---|
| how much is really left | `free -h` | `available` (not `free`) | `available` < 10% of total and falling |
| is it swapping now | `vmstat 1 5` | `si`, `so` | non-zero for several seconds in a row: thrashing |
| is the kernel stalling | `cat /proc/pressure/memory` | `some avg10`, `full avg10` | `full` > 0 means everyone waited for memory |
| who | `ps -eo pid,rss,vsz,etime,cmd --sort=-rss \| head`; `smem` if installed | RSS, and whether it grows over time | one process's RSS climbing steadily: a leak |
| did something die | `dmesg -T \| grep -i 'killed process'`, `journalctl -k \| grep -i oom` | the victim's PID, RSS, and `oom_score_adj` | any line: the OOM killer fired |
| in a container | `cat /sys/fs/cgroup/memory.max`, `memory.current`, `memory.events` | `oom_kill` count | `oom_kill` > 0: the cgroup limit, not the box, killed it |

- [ ] The OOM killer chooses by `oom_score` (roughly: RSS share, adjusted by `oom_score_adj`). Protect the service that must survive with `OOMScoreAdjust=-500` in its unit; make the disposable one `+500`. Never `-1000` on something that can leak.
- [ ] `available` low but `free -h` shows a large `buff/cache`: healthy. The cache is reclaimable and counted in `available`. Low `available` with small cache is real pressure.
- [ ] A slow leak: `ps -o rss= -p PID` every minute (or the metric in Phase 10) and plot it. Restarting buys time; the fix is in the code (Phase 9, lesson 13).
- [ ] `Dirty` in `/proc/meminfo` large and growing: the disk cannot keep up with writes; section 3.
- [ ] Swap: a little used and stable is fine (old pages evicted). `so` non-zero every second is not. `vm.swappiness` tunes eagerness; adding swap adds a cliff, not capacity.

## 3 · Disk

| question | command | read | trouble when |
|---|---|---|---|
| how busy | `iostat -x 1 5` | `%util`, `r/s`, `w/s`, `rMB/s`, `wMB/s` | `%util` > 80 sustained (for a single spindle or a cloud disk with an IOPS cap) |
| how saturated | `iostat -x 1 5` | `aqu-sz` (queue), `r_await`, `w_await` (ms) | `await` far above the device's normal (NVMe < 1 ms, cloud disk 1 to 10 ms, spinning 10+) |
| is the CPU waiting on it | `vmstat 1 5` | `wa`, `b` | `wa` high while `us` is low |
| space and inodes | `df -h`, `df -i` | `Use%`, `IUse%` | either near 100 (lesson 04) |
| who | `iotop -o` (if installed); `pidstat -d 1`; `cat /proc/PID/io` | read_bytes, write_bytes per process | one process dominating |
| errors | `dmesg -T \| grep -iE 'i/o error\|ata\|nvme\|blk'`; `smartctl -a /dev/sda` | resets, timeouts, reallocated sectors | any: replace the disk |
| pressure | `cat /proc/pressure/io` | `some avg10` | > 10% |

- [ ] The database is slow and `w_await` is high: the disk is the bottleneck, and the fix is a faster disk, more IOPS, or fewer `fsync`s per second (Phase 4, lesson 13), not more CPU.
- [ ] A cloud disk has an IOPS ceiling; `%util` 100 with modest MB/s means you hit it. Check the volume's provisioned IOPS.
- [ ] Log shippers, backups and `updatedb` at the wrong hour cause `wa` spikes; `ionice -c3` them or move them.
- [ ] A network filesystem (NFS) that hangs puts processes in `D` for as long as it likes (lesson 10's runbook).

## 4 · Network

| question | command | read | trouble when |
|---|---|---|---|
| how busy | `ip -s link`, `sar -n DEV 1 5`, `/proc/net/dev` twice | bytes/s vs link speed | near the NIC's or the instance's bandwidth cap |
| drops and errors | `ip -s link`; `ethtool -S eth0 \| grep -i drop` | RX/TX errors, dropped, overruns | any non-zero and growing |
| the queues | `ss -tlnp` (Recv-Q on LISTEN), `nstat -az \| grep -iE 'ListenOverflows\|ListenDrops'` | accept-queue overflows | growing: the server is not calling `accept()` fast enough, or `somaxconn` is too small |
| connections | `ss -s`; `ss -tan state established \| wc -l`; `ss -tan state time-wait \| wc -l` | totals by state | thousands of `SYN-RECV`: a flood or a broken client; `TIME-WAIT` in the tens of thousands after a burst is normal |
| retransmits | `nstat -az \| grep -i retrans`; `ss -ti` | TCP retransmit counters | growing: packet loss between here and there |
| conntrack (if NAT/firewall) | `cat /proc/sys/net/netfilter/nf_conntrack_count` vs `_max` | count vs max | near max: new connections are dropped silently |
| DNS | `time getent hosts api.example.com`; `resolvectl statistics` | latency, failures | > 100 ms or intermittent failures: the resolver, not your code |

Lesson 14 is the full version of this section.

## 5 · File descriptors and process limits

| question | command | read | trouble when |
|---|---|---|---|
| per process | `ls /proc/PID/fd \| wc -l` vs `grep 'open files' /proc/PID/limits` | count vs soft limit | within 10% of the limit |
| what they are | `ls -l /proc/PID/fd \| awk '{print $NF}' \| sed 's/:.*//' \| sort \| uniq -c \| sort -rn` | sockets, pipes, files, `anon_inode` | thousands of `socket:` = connections not closed; `pipe:` = subprocesses not reaped |
| system-wide | `cat /proc/sys/fs/file-nr` | used / max | used near max |
| processes | `ps -e \| wc -l` vs `ulimit -u`; `cat /proc/sys/kernel/pid_max`; `cat /proc/sys/kernel/threads-max` | counts vs limits | `fork: retry: Resource temporarily unavailable` |
| the limit a service got | `systemctl show app -p LimitNOFILE`; `cat /proc/PID/limits` | the effective value | 1024: the default; raise with `LimitNOFILE=65536` |

- [ ] `Too many open files` (`EMFILE`) in the log: a leak (sockets, files, pipes) or a limit that was never raised. Count, categorise, then raise the limit *and* fix the leak.
- [ ] `EMFILE` on `accept()` specifically is dangerous: some servers spin on it at 100% CPU. That is the CPU symptom with a descriptor cause.

## 6 · When nothing is saturated

- [ ] It is waiting on something remote: the database, a downstream API, DNS. `ss -tan state established` shows where the connections go; `strace -p PID` shows `read(` or `recvfrom(` on a socket to it (lesson 01's runbook). Their box is the slow one.
- [ ] It is a lock: threads in `futex(` (Phase 9, lesson 09).
- [ ] The clock: `timedatectl`, `chronyc tracking`. A skewed clock breaks TLS, tokens and logs before it breaks anything obvious.
- [ ] It is not the box: the load balancer, the client, the network between. Measure from the box itself with `curl -w` (lesson 16) before blaming it.

## 7 · Write down what you saw

The numbers from `vmstat 1 5`, `iostat -x 1 5`, `free -h`, `ss -s`, `dmesg | tail`, and `top -bn1 | head -20`, with a timestamp, into the incident note. The next person, or you next month, needs the shape of the failure more than the fix.
