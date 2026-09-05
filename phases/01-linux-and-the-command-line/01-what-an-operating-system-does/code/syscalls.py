"""
What an Operating System Does — the system call, made visible.

Every byte your program has ever read or written crossed one boundary: the
system call. This script makes that crossing visible without a debugger. It
writes to the screen with the raw write(2) call instead of print(), opens a
file with the raw open(2) / write(2) / close(2) trio, asks the kernel for
something it will refuse and reads the errno it answers with, identifies the
kernel it is running on, and then times the crossing itself. Self-terminating.

Docs: phases/01-linux-and-the-command-line/01-what-an-operating-system-does/docs/en.md
Spec: POSIX.1-2017 (IEEE Std 1003.1): open(), write(), close(), errno;
      Linux man-pages: syscalls(2), intro(2), proc(5)

Run:
    python syscalls.py
"""

import errno
import os
import sys
import tempfile
import time

STDOUT = 1  # file descriptor 1 is standard output; lesson 07 makes this precise


def banner(title):
    line = "=" * 72
    print(f"\n{line}\n{title}\n{line}")


# ─── 1 · The door: write(2) without print() ──────────────────────────────────
banner("1 · write(2): the raw system call that print() is built on")

# print() is Python code. It formats your objects, appends "\n", pushes the
# text into a buffer, and eventually hands bytes to the kernel with write(2).
# os.write is that last step with nothing in front of it: a number that names
# the destination (1 = standard output), and bytes. The kernel does the rest.
n = os.write(STDOUT, b"hello from user space -> kernel -> terminal\n")
print(f"write(1, ...) returned {n}: the kernel reports how many bytes it accepted")

# ─── 2 · open / write / close by hand ────────────────────────────────────────
banner("2 · open(2), write(2), close(2): a file, with no open() wrapper")

tmpdir = tempfile.mkdtemp(prefix="syscalls-")
path = os.path.join(tmpdir, "note.txt")

# Flags are the kernel's vocabulary: write-only, create if missing, empty it
# first. 0o644 is the permission set for a new file (owner rw, others r) and
# is the subject of lesson 06.
fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
print(f"open({path!r}) -> file descriptor {fd}")
print("   (0, 1 and 2 were taken by stdin, stdout and stderr, so the kernel handed out the next free number)")
written = os.write(fd, b"the kernel wrote this on my behalf\n")
os.close(fd)
print(f"write(fd={fd}) accepted {written} bytes, close(fd={fd}) released the number")

fd = os.open(path, os.O_RDONLY)
data = os.read(fd, 4096)
os.close(fd)
print(f"read back through a fresh descriptor: {data!r}")
os.unlink(path)
os.rmdir(tmpdir)

# ─── 3 · When the kernel says no: errno ──────────────────────────────────────
banner("3 · errno: how the kernel refuses")

# A system call that fails returns -1 and leaves a number in errno. Python
# turns that number into an OSError (and, since 3.3, into a named subclass).
try:
    os.open("/definitely/not/here.txt", os.O_RDONLY)
except OSError as e:
    print(f"open('/definitely/not/here.txt') failed: errno {e.errno} = {errno.errorcode[e.errno]}: {os.strerror(e.errno)}")
    print(f"   Python raised {type(e).__name__}: the same number, with a readable name")

locked_dir = tempfile.mkdtemp(prefix="syscalls-")
locked = os.path.join(locked_dir, "secret.txt")
with open(locked, "w") as f:
    f.write("you should not be able to read this\n")
os.chmod(locked, 0o000)  # no permission bits at all
try:
    fd = os.open(locked, os.O_RDONLY)
    os.close(fd)
    print(f"open({locked!r}) SUCCEEDED with mode 000: you are uid {os.getuid()} (root).")
    print("   Root bypasses permission bits entirely; that is why services never run as root (lesson 06).")
except OSError as e:
    print(f"open(mode 000 file) failed: errno {e.errno} = {errno.errorcode[e.errno]}: {os.strerror(e.errno)}")
    print(f"   Python raised {type(e).__name__}; the kernel checked the bits, not Python")
os.chmod(locked, 0o600)
os.unlink(locked)
os.rmdir(locked_dir)

# ─── 4 · Which kernel is this? ───────────────────────────────────────────────
banner("4 · uname(2), getpid(2): identify the kernel and this process")

u = os.uname()
print(f"kernel   : {u.sysname} {u.release} on {u.machine}")
print(f"python   : sys.platform = {sys.platform!r}")
print(f"process  : pid {os.getpid()}, parent pid {os.getppid()}, uid {os.getuid()}")

if os.path.exists("/proc/version"):
    with open("/proc/version") as f:
        print(f"/proc/version  : {f.read().strip()[:90]}")
    if os.path.exists("/etc/os-release"):
        with open("/etc/os-release") as f:
            pretty = [l for l in f if l.startswith("PRETTY_NAME=")]
        if pretty:
            print(f"/etc/os-release: {pretty[0].split('=', 1)[1].strip().strip(chr(34))}   <- the distribution; the kernel above is Linux")
    wanted = ("Name", "State", "Pid", "PPid", "Threads", "VmRSS")
    with open("/proc/self/status") as f:
        fields = dict(l.split(":", 1) for l in f if ":" in l)
    print("/proc/self/status: " + ", ".join(f"{k}={fields[k].strip()}" for k in wanted if k in fields))
    print("   /proc is not on disk: every read is the kernel answering a question about itself (lesson 02)")
else:
    print("no /proc here: this kernel (probably macOS's XNU) exposes the same facts through sysctl instead.")
    print("   Run this inside the Debian sandbox (`make shell`) to see the Linux view.")

# ─── 5 · What a crossing costs ───────────────────────────────────────────────
banner("5 · The price of the door: a syscall vs a Python call")


def plain_call():
    return 1


N = 200_000
t0 = time.perf_counter()
for _ in range(N):
    plain_call()
t_call = (time.perf_counter() - t0) / N

t0 = time.perf_counter()
for _ in range(N):
    os.getpid()  # the smallest useful syscall: ask the kernel for one integer
t_getpid = (time.perf_counter() - t0) / N

devnull = os.open(os.devnull, os.O_WRONLY)
t0 = time.perf_counter()
for _ in range(N):
    os.lseek(devnull, 0, os.SEEK_CUR)  # a guaranteed crossing with nothing to do on the other side
t_lseek = (time.perf_counter() - t0) / N

M = 100_000
t0 = time.perf_counter()
for _ in range(M):
    os.write(devnull, b"x")  # one syscall per byte
t_raw = (time.perf_counter() - t0) / M
os.close(devnull)

with open(os.devnull, "w") as f:  # Python's open(): a buffer in front of the door
    t0 = time.perf_counter()
    for _ in range(M):
        f.write("x")  # lands in an 8 KiB buffer; the kernel sees one write per 8192 bytes
    f.flush()
    t_buffered = (time.perf_counter() - t0) / M

ns = lambda s: f"{s * 1e9:8.0f} ns"
print(f"{'plain Python function call':34} {ns(t_call)}   (no kernel involved)")
print(f"{'os.getpid()  -> getpid(2)':34} {ns(t_getpid)}   (one crossing, no work)")
print(f"{'os.lseek(devnull) -> lseek(2)':34} {ns(t_lseek)}   (one crossing, no work, never cached)")
print(f"{'os.write(1 byte) -> write(2)':34} {ns(t_raw)}   (one crossing per byte)")
print(f"{'f.write(1 byte), buffered':34} {ns(t_buffered)}   (one crossing per 8192 bytes)")
if t_getpid < 1.5 * t_call:
    print("\n(getpid was as cheap as a function call: this libc answers it from a cache without crossing.)")
print(f"\ncrossing the door cost about {t_lseek / t_call:.0f}x a function call here,")
print(f"and buffering made writing {t_raw / t_buffered:.0f}x cheaper per byte by crossing it {M // 8192 + 1} times instead of {M}.")
print("That ratio is the reason every serious program batches its I/O. Remember it in Phase 9.")
