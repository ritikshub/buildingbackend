---
name: runbook-strace-first-look
description: A first-response runbook for reading a misbehaving process through strace — how to attach, which syscalls to watch, and how to map what you see (a repeated ENOENT, a hang in read or futex, an EMFILE, a connect that never returns) to the layer that is actually broken
phase: 01
lesson: 01
---

# strace, first look

Use this the moment a process on a Linux box is doing something you cannot
explain from its logs: it hangs, it spins, it "cannot find" a file that is
clearly there, it dies on start-up with a one-line error. `strace` shows you
every system call the process makes, and every system call is a request to the
kernel. If a program misbehaves, the misbehaviour is almost always visible as a
request that failed, a request that never returned, or a request made ten
thousand times when once would do.

Everything below assumes Linux. `strace` ships in every distribution's
package manager (`apt install strace`, `dnf install strace`, `apk add strace`)
and is preinstalled in this repo's sandbox (`make shell`).

## 0 · Before you attach

- [ ] You have the **PID** (`pgrep -f <name>`, `systemctl status <unit>`, or `ps aux | grep <name>`), or you can start the program yourself under strace.
- [ ] You are root or the same user as the target. Attaching to another user's process fails with `EPERM`; inside a container you may additionally need `--cap-add SYS_PTRACE`.
- [ ] You know that **strace slows the target down**, sometimes by an order of magnitude, because every syscall now stops twice. On a production process, prefer a short `-c` summary or `-e trace=` filter over a full trace, and detach as soon as you have what you need.

## 1 · Choose the shape of the trace

| You want to know | Command |
|---|---|
| Which syscalls, how many, how much time, how many failed | `strace -c -p <PID>` for ~10 s, then Ctrl+C |
| What a program does at start-up | `strace -f -o /tmp/trace.txt <command>` |
| Only files it touches | `strace -f -e trace=openat,stat,newfstatat,access <command>` |
| Only network calls | `strace -f -e trace=network <command>` |
| Only what it reads and writes | `strace -f -e trace=read,write -s 200 <command>` |
| Where a running process is stuck **right now** | `strace -p <PID>` and read the last line |
| A trace with timestamps and per-call duration | `strace -f -tt -T -o /tmp/trace.txt <command>` |

Flags that matter:

- `-f` follow child processes. Without it, anything the program forks is invisible, and web servers fork.
- `-p <PID>` attach to a running process. Ctrl+C detaches; the process keeps running.
- `-e trace=<set>` filter to a syscall list or a class: `file`, `network`, `process`, `signal`, `memory`, `desc`.
- `-s <N>` show up to N bytes of each string argument (default 32, which truncates every HTTP request).
- `-o <file>` write the trace to a file instead of stderr, so it does not mix with the program's own output.
- `-T` append the time spent in each call; `-tt` prefix each line with a wall-clock timestamp; `-r` show the time since the previous call.
- `-c` count instead of print: a table of calls, errors and time, per syscall.
- `-y` print the path or socket behind each file descriptor number.

## 2 · Read one line

Every line has the same shape:

```text
openat(AT_FDCWD, "/etc/app/config.yaml", O_RDONLY|O_CLOEXEC) = -1 ENOENT (No such file or directory)
|      |                                  |                     |    |
|      arguments, in order                flags, decoded       |    errno name and message
syscall name                                                   return value (-1 = failed)
```

- A **return value ≥ 0** is success. For `read` and `write` it is the byte count; for `openat`, `socket` and `accept` it is the new file descriptor number.
- A **return value of -1** is a failure, and the word after it is the `errno` the kernel set. That word is the diagnosis.
- A line that ends in `<unfinished ...>` or has no return value yet is a call **the process is still inside**. If the process is hung, this is where.
- `+++ exited with N +++` is the exit status; `--- SIGSEGV {...} ---` is a signal arriving.

## 3 · Map the symptom to the trace

**"File not found" / config not loading / library missing**

- [ ] Filter to files: `strace -f -e trace=openat,stat,newfstatat,access <command> 2>&1 | grep -v ENOENT` shows what it *did* find; drop the `grep -v` and look at the `ENOENT` lines in order. The program is looking in a path you did not expect: a wrong working directory, a wrong `HOME`, a relative path, a `PATH` search hitting the wrong binary.
- [ ] A long run of `ENOENT` for `.so` files across `/lib`, `/usr/lib`, `/usr/local/lib` followed by an exit is a **missing shared library**; the last path tried is the one to install.

**Permission denied**

- [ ] `EACCES` on `openat` or `EPERM` on `bind`, `setuid`, `chown`: the process's user does not own that path or port. Note the uid the process runs as (`ps -o user= -p <PID>`), then check the file's mode and owner (`ls -l`), or the port (`< 1024` needs `CAP_NET_BIND_SERVICE` or root).

**It hangs**

- [ ] Attach with `strace -p <PID>`. The last incomplete line is where it sleeps:
  - `read(<fd>` on a socket → waiting for the other side to send. Use `-y` or `ls -l /proc/<PID>/fd/<fd>` to see who the other side is. Check that server.
  - `read(<fd>` on a pipe → the writer has not written and has not closed.
  - `connect(` → the remote host is not answering the handshake (firewall, wrong port, host down). `ETIMEDOUT` will arrive eventually.
  - `futex(` → waiting on a lock or a condition in the program's own threads. Not the kernel's fault; this is a deadlock or a thread that never signals (Phase 9).
  - `epoll_wait(` / `poll(` / `select(` with a long timeout → **idle and healthy**: the program is waiting for work. That is not a hang.
  - `wait4(` → waiting for a child process to exit. Find the child (`ps --ppid <PID>`) and strace that instead.
  - `flock(` / `fcntl(F_SETLKW` → blocked on a file lock another process holds.

**It spins at 100% CPU but does nothing useful**

- [ ] `strace -c -p <PID>` for ten seconds. Thousands of calls per second of the same syscall is a busy loop: `read` returning `0` or `-1 EAGAIN` forever (the program ignores end-of-file or a non-blocking socket with no data), `poll` with timeout `0` in a loop, or `gettimeofday`/`clock_gettime` hammered by a sleep that was written as a spin.
- [ ] No syscalls at all while the CPU is pegged: the loop is pure computation. strace cannot help; use a profiler (Phase 9, lesson 13).

**Too many open files**

- [ ] `EMFILE` on `openat`, `socket` or `accept`: the process hit its descriptor limit. Count what it holds with `ls /proc/<PID>/fd | wc -l` and see what they are with `ls -l /proc/<PID>/fd`. Almost always a leak: a file or a socket that is opened per request and never closed. Raising the limit (`ulimit -n`, `LimitNOFILE=` in systemd) buys time; closing the leak fixes it (lesson 12).

**Connection refused / cannot connect**

- [ ] `connect(...) = -1 ECONNREFUSED`: nothing is listening at that address and port. Check with `ss -tlnp` on the target host (lesson 14). `EHOSTUNREACH` / `ENETUNREACH` means routing; `ETIMEDOUT` means something silently dropped the packets (a firewall).
- [ ] `bind(...) = -1 EADDRINUSE`: the port is already taken, often by the previous copy of the same program still shutting down (lesson 10 and lesson 14).

**Slow**

- [ ] `strace -c` and look at the `% time` column. If one syscall dominates and it is `read`/`write`/`fsync` on a file, the disk is the bottleneck; if it is `recvfrom`/`sendto`/`read` on a socket, the remote is slow; if it is `futex`, threads are fighting over a lock.
- [ ] `strace -T` and sort: `sort -t'<' -k2 -rn` on the trace file finds the single slowest calls. A `connect` taking 5 s, a `fsync` taking 300 ms, a `read` on a network filesystem taking seconds.
- [ ] A call count that is far too high for the work done: `write(fd, "x", 1)` a million times instead of once with a buffer, `stat` on the same path thousands of times, `openat` of the same config file on every request. These are the "one syscall per byte" patterns this lesson measured.

## 4 · When strace is the wrong tool

- The problem is **inside** the program, between syscalls (a slow algorithm, a lock in user space): use a profiler.
- You need to watch **many processes** or the **whole machine**: use `perf trace` or the eBPF tools (`execsnoop`, `opensnoop`, `tcpconnect`), which do not stop the target on every call.
- You are on **macOS**: there is no strace. `dtruss` exists but needs System Integrity Protection relaxed; run the program in the Linux sandbox instead.
- The process is **multi-threaded and busy**: a full trace becomes gigabytes in seconds. Use `-e trace=` and `-c`, and detach fast.

## 5 · Write it down

Record the exact command you ran, the PID, the timestamp, and the two or three lines that told you the answer. A `strace` line is the most precise bug report there is: it names the syscall, the arguments and the kernel's exact refusal, and it cannot be argued with.
