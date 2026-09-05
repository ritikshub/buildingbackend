"""
Streams, Pipes & Redirection — the shell's plumbing, rebuilt from
pipe(2), dup2(2), fork(2) and execve(2).

Every process starts with three descriptors: 0 (stdin), 1 (stdout),
2 (stderr). Redirection is the shell changing what those numbers point at
in the child, between fork and exec, so the program never knows. A pipe
is one kernel buffer with a write end and a read end; a pipeline is N
children whose stdout and stdin have been wired into N-1 pipes. This file
implements  cmd < in > out 2>&1 | cmd2 | cmd3  exactly the way bash does,
shows the descriptor table before and after, measures the pipe buffer,
demonstrates backpressure and SIGPIPE, and prints why `2>&1 >file` and
`>file 2>&1` differ. Self-terminating; runs on macOS and Linux.

Docs: phases/01-linux-and-the-command-line/07-streams-pipes-and-redirection/docs/en.md
Spec: POSIX.1-2017 pipe(), dup2(), Shell Command Language 2.7 (Redirection)
      and 2.9.2 (Pipelines); Linux man-pages pipe(7), dup(2), fcntl(2),
      signal(7) (SIGPIPE)

Run:
    python pipes.py
"""

import errno
import fcntl
import os
import shlex
import signal
import sys
import time


def banner(title):
    line = "=" * 72
    print(f"\n{line}\n{title}\n{line}")
    sys.stdout.flush()


FD_DIR = "/proc/self/fd" if os.path.exists("/proc/self/fd") else "/dev/fd"


def fd_target(fd):
    """Where a descriptor points: readlink on /proc/self/fd on Linux, F_GETPATH on macOS."""
    if FD_DIR.startswith("/proc"):
        return os.readlink(f"{FD_DIR}/{fd}")
    try:
        path = fcntl.fcntl(fd, fcntl.F_GETPATH, bytes(1024)).rstrip(b"\0").decode()
        return path or "pipe"
    except OSError:
        return "pipe" if os.fstat(fd).st_mode & 0o170000 == 0o010000 else "?"


def fd_table(label):
    """What the descriptor numbers point at right now."""
    rows = []
    for name in sorted(os.listdir(FD_DIR), key=int):
        try:
            rows.append(f"{name}->{fd_target(int(name))}")
        except OSError:
            continue
    print(f"   {label}: " + "  ".join(rows))


# ─── 1 · Parse one command's redirections ────────────────────────────────────
def parse(words):
    """Split ['cmd', 'a', '>', 'out', '2>&1'] into argv and an ordered list of
    redirections. ORDER MATTERS: the shell applies them left to right."""
    argv, redirs = [], []
    i = 0
    while i < len(words):
        w = words[i]
        if w in ("<", ">", ">>", "2>", "2>>"):
            redirs.append((w, words[i + 1]))
            i += 2
        elif w in ("2>&1", "1>&2"):
            redirs.append((w, None))
            i += 1
        else:
            argv.append(w)
            i += 1
    return argv, redirs


def apply_redirections(redirs):
    """Runs IN THE CHILD, after fork and before exec: rewire 0, 1 and 2."""
    for op, target in redirs:
        if op == "<":
            fd = os.open(target, os.O_RDONLY)
            os.dup2(fd, 0); os.close(fd)                      # 0 now IS the file
        elif op in (">", "2>"):
            fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
            os.dup2(fd, 1 if op == ">" else 2); os.close(fd)
        elif op in (">>", "2>>"):
            fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
            os.dup2(fd, 1 if op == ">>" else 2); os.close(fd)
        elif op == "2>&1":
            os.dup2(1, 2)                                     # 2 becomes a copy of whatever 1 is NOW
        elif op == "1>&2":
            os.dup2(2, 1)


# ─── 2 · Run a pipeline: N children, N-1 pipes ───────────────────────────────
def run_pipeline(line):
    """`a | b | c`, each stage with its own redirections. Returns the exit
    status of every stage (what bash exposes as PIPESTATUS)."""
    stages = [parse(shlex.split(s)) for s in line.split("|")]
    pids, prev_read = [], None
    for i, (argv, redirs) in enumerate(stages):
        last = i == len(stages) - 1
        if not last:
            read_end, write_end = os.pipe()                   # one kernel buffer, two descriptors
        pid = os.fork()
        if pid == 0:
            # ── child ──
            if prev_read is not None:
                os.dup2(prev_read, 0); os.close(prev_read)    # my stdin is the previous pipe
            if not last:
                os.dup2(write_end, 1); os.close(write_end)    # my stdout is the next pipe
                os.close(read_end)                            # not mine; a stray copy would keep the pipe alive
            apply_redirections(redirs)                        # explicit < > 2>&1 come AFTER the pipe wiring
            signal.signal(signal.SIGPIPE, signal.SIG_DFL)     # Python ignores SIGPIPE; a real program must not
            try:
                os.execvp(argv[0], argv)                      # the program inherits the rewired table
            except OSError as e:
                os.write(2, f"{argv[0]}: {e.strerror}\n".encode())
                os._exit(127)
        # ── parent ──
        pids.append(pid)
        if prev_read is not None:
            os.close(prev_read)                               # the parent holds no pipe ends ...
        if not last:
            os.close(write_end)                               # ... otherwise readers would never see EOF
            prev_read = read_end
    statuses = []
    for pid in pids:
        _, st = os.waitpid(pid, 0)
        statuses.append(os.WEXITSTATUS(st) if os.WIFEXITED(st) else 128 + os.WTERMSIG(st))
    return statuses


if __name__ == "__main__":
    sys.stdout.reconfigure(line_buffering=True)
    import tempfile
    work = tempfile.mkdtemp(prefix="pipes-")
    os.chdir(work)

    banner("1 · The descriptor table: three numbers every process is born with")
    fd_table("this script")
    print("   0 = stdin, 1 = stdout, 2 = stderr. Inherited from the shell; a terminal, a pipe or a file, the program cannot tell")

    banner("2 · Redirection is dup2 in the child, between fork and exec")
    with open("in.txt", "w") as f:
        f.write("one\ntwo\nthree\n")
    print("$ wc -l < in.txt > out.txt   (the child's 0 becomes in.txt, its 1 becomes out.txt; wc never sees a filename)")
    run_pipeline("wc -l < in.txt > out.txt")
    print("   out.txt contains:", open("out.txt").read().strip())
    print("$ ls /nope in.txt > both.txt 2>&1   (2 copied from 1 AFTER 1 points at the file: both streams land in it)")
    run_pipeline("ls /nope in.txt > both.txt 2>&1")
    print("   both.txt:", open("both.txt").read().strip().replace("\n", " | "))
    print("$ ls /nope in.txt 2>&1 > only-stdout.txt   (2 copied from 1 BEFORE 1 is redirected: 2 still points at the terminal)")
    run_pipeline("ls /nope in.txt 2>&1 > only-stdout.txt")
    print("   only-stdout.txt:", open("only-stdout.txt").read().strip(), "  <- the error line went to the screen above, not the file")
    print("   order matters because dup2 copies what a number points at NOW, not a promise about later")

    banner("3 · A pipe is one buffer with two ends; a pipeline is children wired through them")
    r, w = os.pipe()
    print(f"os.pipe() -> read end fd {r}, write end fd {w}")
    fd_table("after pipe()")
    os.write(w, b"through the kernel\n")
    print("   wrote to fd", w, "; reading fd", r, "gives:", os.read(r, 100).strip().decode())
    os.close(r); os.close(w)
    print("$ printf 'b\\na\\nc\\na\\n' | sort | uniq -c | sort -rn")
    st = run_pipeline("printf 'b\\na\\nc\\na\\n' | sort | uniq -c | sort -rn")
    print(f"   four children, three pipes, exit statuses {st}: that is what bash's PIPESTATUS holds")

    banner("4 · How big is a pipe? Fill it until the kernel says 'would block'")
    r, w = os.pipe()
    fcntl.fcntl(w, fcntl.F_SETFL, os.O_NONBLOCK)              # ask for EAGAIN instead of sleeping
    total = 0
    try:
        while True:
            total += os.write(w, b"x" * 4096)
    except BlockingIOError:
        pass
    print(f"   the pipe accepted {total:,} bytes ({total // 1024} KiB) before it was full")
    print("   a blocking writer would now SLEEP until a reader drains it: that is backpressure, for free")
    os.close(r); os.close(w)

    banner("5 · Backpressure: a fast writer, a slow reader, and the writer waits")
    r, w = os.pipe()
    pid = os.fork()
    if pid == 0:                                              # the slow reader
        os.close(w)
        got = 0
        while True:
            buf = os.read(r, 65536)
            if not buf:
                break
            got += len(buf)
            time.sleep(0.05)                                  # pretend to be a slow disk or network
        os._exit(0)
    os.close(r)
    t0 = time.perf_counter()
    for _ in range(16):
        os.write(w, b"y" * 65536)                             # 1 MiB total; the pipe holds far less
    elapsed = time.perf_counter() - t0
    os.close(w)
    os.waitpid(pid, 0)
    print(f"   writing 1 MiB into a pipe read at ~1.3 MiB/s took {elapsed * 1000:.0f} ms: the writer was parked in write() each time the pipe was full")
    print("   nothing was lost, nothing was buffered in RAM beyond the pipe: the producer ran at the consumer's pace")

    banner("6 · SIGPIPE: writing to a pipe nobody reads any more")
    print("$ yes | head -2   (head exits after two lines; yes is still writing)")
    st = run_pipeline("yes | head -2")
    print(f"   exit statuses {st}: head 0, yes {st[0]} = 128 + {st[0] - 128} = killed by SIGPIPE (signal {signal.SIGPIPE})")
    print("   the kernel delivers SIGPIPE on the first write after the last reader closed; that is how head stops an infinite producer")

    banner("7 · The order problem, once more, with the descriptor table as proof")
    pid = os.fork()
    if pid == 0:
        fd = os.open("trace.txt", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
        fd_table("child before any dup2")
        os.dup2(fd, 1)
        fd_table("after dup2(file, 1)")
        os.dup2(1, 2)
        fd_table("after dup2(1, 2)   ")
        os._exit(0)
    os.waitpid(pid, 0)
    print("   read the last row: 1 and 2 both point at trace.txt; that is what '> trace.txt 2>&1' does")

    import shutil
    os.chdir("/")
    shutil.rmtree(work)
