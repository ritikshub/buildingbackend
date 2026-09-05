# Runbook: Diagnosing a Slow I/O Server

For a network server that has gone slow, stopped accepting, or grown a latency tail.
Covers **event-driven** servers (one loop over epoll/kqueue — nginx, Redis, Node,
asyncio, Netty) and **thread-per-connection** servers (classic Java, Python
`threading`, Puma). Work top to bottom; §1 routes you to one of five classes.

## 0 · Capture before you change anything

```bash
PID=$(pgrep -f <your-process>)
ps -o pid,nlwp,pcpu,pmem,rss,vsz,etime -p $PID   # nlwp = thread count
ls /proc/$PID/fd | wc -l                          # open descriptors
grep -E 'open files|processes|stack' /proc/$PID/limits
ss -tn state established | wc -l                  # established connections
ss -tln '( sport = :<PORT> )'                     # Recv-Q on LISTEN = pending accepts
top -H -p $PID                                    # CPU PER THREAD, not per process
```

- [ ] Thread count, fd count (and the limit), accept backlog, connection count, per-thread CPU

## 1 · Triage

| Symptom | Class | Go to |
|---|---|---|
| p99 high, p50 fine, **CPU < 30%** | Blocking in the loop | §2 |
| One thread pinned ~100%, others idle | Loop CPU saturation | §3 |
| `EMFILE` in logs, fd count near limit | fd exhaustion | §4 |
| Timeouts *at connect*, `Recv-Q` on LISTEN growing | Accept backlog overflow | §5 |
| `nlwp` in thousands, RSS climbing, `pthread_create` fails | Thread explosion | §6 |

> Key discriminator: **is the latency tail accompanied by CPU?** High latency with
> idle CPU means something is parked that should not be. High latency with a pinned
> core means you are out of compute. These have opposite fixes.

## 2 · Blocking inside an event loop

**Signature:** p50 single-digit ms, p99 in the hundreds, CPU < 30%, and spikes
correlate across *unrelated* endpoints at the same instant.

```bash
top -H -p $PID                                       # find the loop thread's TID
awk '{print $3}' /proc/$PID/task/<TID>/stat          # S = sleeping (bad), R = running
strace -f -p $PID -T -e trace=network,file,poll      # Linux
sudo dtruss -p $PID                                  # macOS
```

Look for **any syscall between two `epoll_wait` returns taking > ~1 ms**:

```text
epoll_wait(...) = 3 <0.000012>
openat("/data/x")   <0.041300>   <-- 41 ms of disk. Every connection waited.
connect(... :53)    <0.198441>   <-- blocking DNS. 198 ms.
```

- [ ] **DNS** — `getaddrinfo()` blocks in nearly every library
- [ ] **Disk** — `epoll` cannot make files async; a regular file is *always* "ready"
- [ ] **Sync client in an async handler** (`psycopg2` vs `asyncpg`, `requests` vs `httpx`)
- [ ] **`sleep()`** instead of the loop's timer
- [ ] **CPU-heavy handler work** — bcrypt/argon2, big JSON, regex, compression
- [ ] **Lock contention** — the loop waiting on a mutex held by a worker

**Fix:** move it to a thread pool (`loop.run_in_executor`, libuv's pool) or use a
non-blocking client. Then add a **loop-lag metric** permanently: schedule a timer
every 100 ms, record `actual_delay - 100 ms`, alert when p99 lag > 50 ms. That one
metric turns an invisible failure into a graph.

## 3 · Loop CPU saturation

**Signature:** exactly one thread at ~100%, throughput flat while offered load
rises. Adding CPUs changes nothing.

```bash
top -H -p $PID          # one TID at 100%, rest idle
perf top -p $PID        # or: py-spy top --pid $PID
```

Rule out the two self-inflicted spins before believing the work is real:

- [ ] **`EVENT_WRITE` registered permanently.** A connected socket is nearly always
      writable, so a level-triggered loop reports it every wait and spins. Register
      write interest **only while the output queue is non-empty**.
- [ ] **Hot listener after `EMFILE`.** `accept()` fails, the listener stays readable,
      the loop spins doing nothing. Check §4 first.

**Fix if the work is genuine:** N loop processes behind `SO_REUSEPORT`, one per core
— the nginx/Redis model. Do not add threads to an event loop.

## 4 · File descriptor exhaustion

**Signature:** `accept: Too many open files`, new connections refused while existing
ones work, often with a 100% CPU loop thread as a side effect.

```bash
ls /proc/$PID/fd | wc -l ; grep 'open files' /proc/$PID/limits
ls -l /proc/$PID/fd | awk '{print $11}' | sort | uniq -c | sort -rn | head   # find the leak
ss -tan state close-wait | wc -l                                            # unclosed by YOU
```

- [ ] Within 10% of the limit → raise the limit **and** find the leak
- [ ] Many `CLOSE_WAIT` → your code is not calling `close()` after the peer hung up
- [ ] Stable and far from the limit → not your problem, return to §1

```yaml
# systemd:        LimitNOFILE=1048576
# docker-compose: ulimits: { nofile: { soft: 1048576, hard: 1048576 } }
```

**Reserve an emergency fd at startup** (open `/dev/null`). On `EMFILE`: close it,
`accept()`, immediately reject with 503, reopen the reserve. Converts a hot spin
into a clean rejection. Budget: `nofile ≥ peak_conns × 1.2 + pools + files + 100`.

## 5 · Accept backlog overflow

**Signature:** clients time out *connecting*; the server looks idle from inside
because it never saw the connection.

```bash
ss -tln '( sport = :8080 )'                        # Recv-Q = pending, Send-Q = backlog
nstat -az TcpExtListenOverflows TcpExtListenDrops  # rising = silently dropping
sysctl net.core.somaxconn                          # caps listen(backlog)
```

- [ ] `Recv-Q` near `Send-Q`, `ListenOverflows` rising → backlog full

**Fix:** raise `listen()`'s backlog *and* `somaxconn` (they are a `min()`), and
drain the accept queue in a loop until `EAGAIN` per readiness event rather than
accepting one connection per wakeup. But a full backlog is usually a *symptom* of
§2 or §3 — the loop is not reaching `accept()` often enough.

## 6 · Thread explosion

```bash
ps -o nlwp= -p $PID ; grep -E 'VmRSS|VmSize' /proc/$PID/status
grep 'max processes' /proc/$PID/limits ; vmstat 1 5   # 'cs' = context switches/sec
```

Arithmetic to do before arguing (measured defaults, Linux/glibc, 8 MiB stacks):

```text
reserved = threads × RLIMIT_STACK    10,000 × 8 MiB    = 78.1 GiB address space
resident = threads × ~16 KiB         10,000 × 16.3 KiB = 159 MiB RAM
wakeups  = threads × ~17 us          10,000 × 16.8 us  = 168 ms per broadcast round
```

- [ ] Threads scale with **connections** rather than **cores** → architectural
- [ ] Most threads sleeping in `recv` → idle, and you are paying to have them
- [ ] Context switches/sec far exceeding request rate → scheduler thrash

**Fixes, cheapest first:** (1) bound concurrency with a thread pool + queue, so you
degrade by queueing instead of dying; (2) shrink stacks (`ulimit -s 512`) after
measuring your deepest stack — 16x less reserved space; (3) move idle connections
to a selector thread and keep a worker pool for handlers.

## 7 · Verify the fix

- [ ] Loop-lag p99 under 10 ms, with an alert on it
- [ ] fd count stable across a full traffic cycle, under 60% of `ulimit -n`
- [ ] `ListenOverflows` flat at zero for 30 minutes at peak
- [ ] Thread count no longer correlated with connection count
- [ ] p99/p50 ratio back to baseline — the tail is the signal, not the mean
- [ ] Load test at 2x concurrency **with throttled/slow readers** — that is what
      surfaces partial-write bugs, which only appear when the peer's window closes

## Prevention checklist for a new event-driven service

- [ ] Loop-lag metric exported and alerted from day one
- [ ] No blocking call in a handler — lint or CI check where possible
- [ ] Every write goes through an output queue that handles short `send()` returns
- [ ] Every read appends to a per-connection buffer with explicit message framing
- [ ] `LimitNOFILE` set explicitly in the unit/container, never inherited
- [ ] `listen()` backlog and `somaxconn` both set deliberately
- [ ] Idle-connection timeout, so a leaked socket cannot live forever
- [ ] `TCP_NODELAY` set where latency matters
