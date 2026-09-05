---
name: runbook-where-did-my-output-go
description: A diagnosis runbook for lost, delayed, garbled or stuck output — stderr versus stdout, redirection order, block buffering in pipes and services, SIGPIPE and exit 141, pipefail, /dev/null, full pipes that deadlock subprocess calls, and descriptors leaking into children — each with the one-line check and the fix
phase: 01
lesson: 07
---

# Where did my output go?

Every symptom below is a descriptor pointing somewhere you did not
expect, a buffer that has not flushed, or a pipe with nobody on the other
end. Find which, with the check beside it.

## 1 · "The error message is not in the log file"

- [ ] **stderr was not redirected.** `cmd > log` sends only descriptor 1. Errors go to 2, which still points at the terminal (or at nothing, under a service). Fix: `cmd > log 2>&1`, or `cmd &> log` in bash.
- [ ] **Redirections were in the wrong order.** `cmd 2>&1 > log` copies 2 from 1 *while 1 is still the terminal*, then moves 1 to the file. stdout lands in the file, stderr on the screen. The shell applies redirections left to right, and `2>&1` means "2 becomes a copy of what 1 is *right now*." Fix: `> log 2>&1`.
- [ ] **The pipe took only stdout.** `cmd | tee log` and `cmd | grep x` see descriptor 1 only. Fix: `cmd 2>&1 | tee log`.
- [ ] **The program writes its logs to stderr on purpose** (most do; Python's `logging` does by default). `cmd 2> errors.log` or `2>&1`, deliberately.
- [ ] **Under systemd** both streams go to the journal unless the unit says otherwise: `journalctl -u name`. Under cron, both are mailed or discarded; redirect explicitly in the crontab line.

## 2 · "Output appears late, all at once, or only when the program exits"

- [ ] **Block buffering.** When stdout is a pipe or a file, the C library and most runtimes buffer 4 to 8 KiB before writing; on a terminal they flush at every newline. So `python3 app.py` prints live in your terminal and prints nothing for minutes under systemd, in Docker, or through `| tee`. Check: does it behave in a terminal and not in a pipe? Then it is this.
- [ ] Fixes, in order of preference: make the program flush (`print(..., flush=True)`, `sys.stdout.reconfigure(line_buffering=True)`, `logging` to stderr which is unbuffered); run Python with `-u` or `PYTHONUNBUFFERED=1`; wrap a program you cannot change with `stdbuf -oL cmd` (line-buffered) or `stdbuf -o0 cmd` (unbuffered); for a tool that insists on a terminal, `script -q -c cmd /dev/null` or `unbuffer cmd` gives it a pty.
- [ ] **It crashed and the buffer was never flushed.** A process killed by `SIGKILL` (the OOM killer, `kill -9`, a Docker stop timeout) loses everything still in its stdio buffer. The last log lines before a crash are often missing for this reason, not because nothing happened. Log to stderr, or flush after every line that matters.
- [ ] **Interleaving is wrong** (stderr lines appear before stdout lines that were printed earlier): stderr is unbuffered and stdout is not. Same fix.

## 3 · "The pipeline exit status is 0 but a command in it failed"

- [ ] A pipeline's `$?` is the **last** command's status. `false | true` is 0. Check every stage with `echo "${PIPESTATUS[@]}"` (bash) immediately after.
- [ ] In scripts, `set -o pipefail`: the pipeline's status becomes the last non-zero status among its stages. Combine with `set -e` to stop on it (lesson 09).
- [ ] **Exit 141** (or `${PIPESTATUS[n]}` = 141) is 128 + 13 = killed by **SIGPIPE**: the command was writing to a pipe whose reader had already exited. `cmd | head -1` does this to `cmd` on purpose and it is fine. In a script with `pipefail`, it turns a healthy `head` into a failure; either accept it (`|| [ $? -eq 141 ]`), let the producer finish, or read everything.
- [ ] **"Broken pipe" errors in a service log** mean the same thing: the client or the log collector on the other end went away. Python raises `BrokenPipeError`; some programs print `write error: Broken pipe`. Usually harmless; if frequent, the consumer is the problem.

## 4 · "It hangs"

- [ ] **Full pipe, nobody reading.** A pipe holds 64 KiB. A writer blocks in `write()` when it is full until someone reads. Classic case: `subprocess.run(cmd, stdout=PIPE, stderr=PIPE)` in code that reads stdout to completion before touching stderr; the child fills stderr's pipe and blocks; the parent waits forever on stdout. Fix: `communicate()`, which reads both concurrently, or merge them with `stderr=STDOUT`.
- [ ] **A reader waiting for EOF that never comes.** EOF on a pipe arrives only when *every* write end is closed. A stray copy of the write descriptor in another process (a forked child that inherited it, a shell that did `exec 3>&1`) keeps the pipe open forever. Check: `ls -l /proc/*/fd 2>/dev/null | grep 'pipe:\[INODE\]'` for the inode shown on the stuck reader's descriptor. The shell for this lesson closes its copies after every fork for exactly this reason.
- [ ] **A program waiting on stdin you did not give it.** Under cron or a service, stdin is `/dev/null` or a closed pipe, and `read`, `ssh` without `-n`, `sudo` asking for a password, or an interactive prompt sits there forever. Check with `strace -p PID`: the last line is `read(0,`. Fix: `< /dev/null`, `ssh -n`, `-y`/`--batch`/`--non-interactive` flags, `sudo -n`.
- [ ] **`cat` or `less` with no argument and no pipe** is reading your terminal. `Ctrl+D` ends it.

## 5 · "The file is empty, or has only the last run's output"

- [ ] `>` **truncates** before the command runs. `cmd > out.txt` starts with an empty file every time; `>>` appends. And `sort file > file` empties the file before `sort` reads it: redirect to a temp file and `mv` it (lesson 05), or use `sponge` from moreutils.
- [ ] **`/dev/null` on purpose, forgotten later.** `2>/dev/null` in a script that is now failing silently. Grep the script for `null`.
- [ ] **Two processes appending to the same file** interleave and, without `O_APPEND`, overwrite each other. `>>` uses `O_APPEND` (atomic per write); `>` from two processes does not.
- [ ] **A rotated log**: the process is still writing to the old, renamed or deleted inode (lesson 04 and 05). The new file stays empty until the process reopens: `SIGHUP`, `copytruncate`, or a restart.

## 6 · "Something is holding a descriptor it should not"

- [ ] **Children inherit every open descriptor** unless it was opened `O_CLOEXEC` (Python does this by default since 3.4; shells do not). A daemon started from a script that had `exec 3>file` keeps that file open forever; a server's listening socket inherited by a child that outlives it makes the port stay busy after the server dies (`EADDRINUSE`, lesson 14). Check: `ls -l /proc/PID/fd` on the child.
- [ ] **A service started from a terminal dies when the terminal closes**: it inherited the pty and got `SIGHUP`. Use `nohup cmd &`, `setsid`, or better, a `systemd` unit (lesson 10, lesson 11).
- [ ] **Too many open files** (`EMFILE`): count with `ls /proc/PID/fd | wc -l`, compare with `ulimit -n`; leaks are pipes from `subprocess.Popen` never waited on, or files opened per request and never closed (lesson 12).

## 7 · Five checks that answer most of it

```bash
ls -l /proc/PID/fd                  # where 0, 1, 2 (and the rest) actually point right now
strace -p PID -e trace=write,read   # is it writing? to which fd? is it blocked in read(0)?
cmd > /tmp/o 2> /tmp/e; wc -c /tmp/o /tmp/e   # which stream carries what
cmd | cat                            # does the program change behaviour when stdout is a pipe? (buffering)
echo "${PIPESTATUS[@]}"              # what each stage of the last pipeline returned
```
