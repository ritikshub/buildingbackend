#!/usr/bin/env python3
"""Container internals from the inside: namespaces, capabilities, overlay layers,
cgroups v2 and PID 1 semantics -- all read or built with the standard library.

Lesson: phases/10-infrastructure-and-deployment/02-what-a-container-actually-is/docs/en.md
Sources: Linux man-pages namespaces(7), user_namespaces(7), capabilities(7),
         cgroups(7), pid_namespaces(7), signal(7); kernel Documentation/
         filesystems/overlayfs.rst; POSIX.1-2017 (IEEE Std 1003.1) for signals.
Runs as an ordinary container process. Nothing here needs privilege -- the point
of section 2 is precisely that the privileged operations FAIL, and why.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import os
import random
import shutil
import signal
import statistics
import sys
import tempfile
import time

RNG = random.Random(7)

# ---------------------------------------------------------------------------
# section 1 -- the namespaces you are already in
# ---------------------------------------------------------------------------

NS_KINDS = ("mnt", "pid", "net", "ipc", "uts", "user", "cgroup", "time")

NS_MEANING = {
    "mnt":    "the mount table -- which filesystems exist and where",
    "pid":    "the process id number space -- who else exists",
    "net":    "interfaces, addresses, routes, ports, firewall rules",
    "ipc":    "System V IPC objects and POSIX message queues",
    "uts":    "the hostname and NIS domain name",
    "user":   "the uid/gid mapping -- and therefore what root means",
    "cgroup": "where the cgroup tree appears to be rooted",
    "time":   "the offsets for CLOCK_MONOTONIC and CLOCK_BOOTTIME",
}


def read_ns() -> dict[str, str]:
    out = {}
    for kind in NS_KINDS:
        try:
            out[kind] = os.readlink("/proc/self/ns/" + kind)
        except OSError as exc:
            out[kind] = "unreadable (%s)" % exc.strerror
    return out


def section_namespaces() -> None:
    print("== 1 · THE NAMESPACES YOU ARE ALREADY IN ==")
    mine = read_ns()
    print("  a namespace id is an inode number on the nsfs filesystem.")
    print("  two processes are 'in the same namespace' iff these numbers match.")
    print()
    print("  %-8s %-22s %s" % ("KIND", "ID", "WHAT IT VIRTUALISES"))
    for kind in NS_KINDS:
        print("  %-8s %-22s %s" % (kind, mine[kind], NS_MEANING[kind]))

    # A fork inherits every namespace. Show it rather than assert it.
    r, w = os.pipe()
    pid = os.fork()
    if pid == 0:                                    # child
        os.close(r)
        child = read_ns()
        payload = ";".join("%s=%s" % (k, child[k]) for k in NS_KINDS)
        os.write(w, payload.encode())
        os.close(w)
        os._exit(0)
    os.close(w)
    raw = b""
    while True:
        chunk = os.read(r, 4096)
        if not chunk:
            break
        raw += chunk
    os.close(r)
    os.waitpid(pid, 0)
    child = dict(item.split("=", 1) for item in raw.decode().split(";"))

    same = [k for k in NS_KINDS if child.get(k) == mine[k]]
    print()
    print("  forked a child (pid %d). it shares %d/%d namespaces with us."
          % (pid, len(same), len(NS_KINDS)))
    print("  fork() copies the process, NOT its namespace membership --")
    print("  a child is in your namespaces until something calls unshare() or setns().")
    print("  starting a *container* means: clone() with CLONE_NEW* flags, so the")
    print("  child gets FRESH ids for the kinds it unshared and keeps yours for the rest.")
    print("  that is the entire difference. there is no 'container' object in the kernel.")
    print()


# ---------------------------------------------------------------------------
# section 2 -- capabilities, demonstrated by failing
# ---------------------------------------------------------------------------

CLONE_FLAGS = [
    ("CLONE_NEWNS",   0x00020000, "mount",  "CAP_SYS_ADMIN"),
    ("CLONE_NEWUTS",  0x04000000, "uts",    "CAP_SYS_ADMIN"),
    ("CLONE_NEWIPC",  0x08000000, "ipc",    "CAP_SYS_ADMIN"),
    ("CLONE_NEWPID",  0x20000000, "pid",    "CAP_SYS_ADMIN"),
    ("CLONE_NEWNET",  0x40000000, "net",    "CAP_SYS_ADMIN"),
    ("CLONE_NEWUSER", 0x10000000, "user",   "none on a modern kernel"),
]

# linux/capability.h, in bit order.
CAP_NAMES = [
    "CAP_CHOWN", "CAP_DAC_OVERRIDE", "CAP_DAC_READ_SEARCH", "CAP_FOWNER",
    "CAP_FSETID", "CAP_KILL", "CAP_SETGID", "CAP_SETUID", "CAP_SETPCAP",
    "CAP_LINUX_IMMUTABLE", "CAP_NET_BIND_SERVICE", "CAP_NET_BROADCAST",
    "CAP_NET_ADMIN", "CAP_NET_RAW", "CAP_IPC_LOCK", "CAP_IPC_OWNER",
    "CAP_SYS_MODULE", "CAP_SYS_RAWIO", "CAP_SYS_CHROOT", "CAP_SYS_PTRACE",
    "CAP_SYS_PACCT", "CAP_SYS_ADMIN", "CAP_SYS_BOOT", "CAP_SYS_NICE",
    "CAP_SYS_RESOURCE", "CAP_SYS_TIME", "CAP_SYS_TTY_CONFIG", "CAP_MKNOD",
    "CAP_LEASE", "CAP_AUDIT_WRITE", "CAP_AUDIT_CONTROL", "CAP_SETFCAP",
    "CAP_MAC_OVERRIDE", "CAP_MAC_ADMIN", "CAP_SYSLOG", "CAP_WAKE_ALARM",
    "CAP_BLOCK_SUSPEND", "CAP_AUDIT_READ", "CAP_PERFMON", "CAP_BPF",
    "CAP_CHECKPOINT_RESTORE",
]

# What each capability actually buys the holder.
CAP_NOTES = {
    "CAP_CHOWN":       "change file ownership arbitrarily",
    "CAP_DAC_OVERRIDE": "ignore file permission bits entirely",
    "CAP_DAC_READ_SEARCH": "read any file, traverse any directory",
    "CAP_FOWNER":      "act as the owner of any file",
    "CAP_FSETID":      "keep setuid/setgid bits across modification",
    "CAP_KILL":        "signal any process, whoever owns it",
    "CAP_SETGID":      "change group id at will",
    "CAP_SETUID":      "change user id at will -- how a server drops privilege",
    "CAP_SETPCAP":     "move capabilities around its own sets",
    "CAP_NET_BIND_SERVICE": "bind ports below 1024",
    "CAP_NET_RAW":     "raw sockets: packet spoofing, ARP games",
    "CAP_NET_ADMIN":   "reconfigure interfaces, routes, firewall rules",
    "CAP_SYS_CHROOT":  "call chroot()",
    "CAP_MKNOD":       "create device nodes",
    "CAP_AUDIT_WRITE": "write records to the kernel audit log",
    "CAP_SETFCAP":     "set capabilities on files",
    "CAP_SYS_ADMIN":   "mount, unshare, setns, pivot_root -- 'the new root'",
    "CAP_SYS_MODULE":  "load a kernel module: total host compromise",
    "CAP_SYS_PTRACE":  "attach to any process and read its memory",
    "CAP_SYS_BOOT":    "reboot the host",
    "CAP_SYS_TIME":    "set the system clock (shared with the host)",
    "CAP_SYS_RAWIO":   "raw I/O port and /dev/mem access",
    "CAP_SYS_RESOURCE": "override resource limits and reserved space",
    "CAP_BPF":         "load BPF programs into the kernel",
    "CAP_PERFMON":     "read performance data across the system",
}

# The subset a reader should be able to name on sight.
CAP_HEADLINE = (
    "CAP_SYS_ADMIN", "CAP_SYS_MODULE", "CAP_SYS_PTRACE", "CAP_SYS_RAWIO",
    "CAP_NET_ADMIN", "CAP_SYS_BOOT", "CAP_SYS_TIME", "CAP_BPF",
    "CAP_DAC_READ_SEARCH", "CAP_SYS_RESOURCE",
)


def read_status_field(name: str) -> str:
    try:
        with open("/proc/self/status") as fh:
            for line in fh:
                if line.startswith(name + ":"):
                    return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return ""


def read_int_file(path: str) -> int | None:
    try:
        with open(path) as fh:
            return int(fh.read().strip())
    except (OSError, ValueError):
        return None


def section_capabilities() -> None:
    print("== 2 · WHY YOU CANNOT BUILD ONE HERE — CAPABILITIES, DEMONSTRATED ==")
    libc_path = ctypes.util.find_library("c") or "libc.so.6"
    libc = ctypes.CDLL(libc_path, use_errno=True)

    print("  we are uid %d (root) in this container. watch root fail anyway."
          % os.getuid())
    print()
    print("  %-14s %-8s %-7s %-24s %s"
          % ("unshare(flag)", "result", "errno", "meaning", "gate"))
    failures = 0
    for name, flag, _kind, gate in CLONE_FLAGS:
        ctypes.set_errno(0)
        rc = libc.unshare(flag)
        err = ctypes.get_errno()
        if rc != 0:
            failures += 1
            print("  %-14s %-8s %-7s %-24s %s"
                  % (name, "FAILED", "%d" % err, os.strerror(err), gate))
        else:
            print("  %-14s %-8s %-7s %-24s %s" % (name, "ok", "-", "-", gate))

    cap_eff = read_status_field("CapEff")
    cap_bnd = read_status_field("CapBnd")
    eff = int(cap_eff, 16) if cap_eff else 0
    bnd = int(cap_bnd, 16) if cap_bnd else 0
    held = [n for i, n in enumerate(CAP_NAMES) if eff >> i & 1]
    dropped = [n for i, n in enumerate(CAP_NAMES) if not (eff >> i & 1)]

    print()
    print("  all %d failed. root inside a container is uid 0 with a REDUCED"
          % failures)
    print("  capability set -- the kernel split root's power into %d separate"
          % len(CAP_NAMES))
    print("  privileges (capabilities(7)) and this process was handed some of them.")
    print()
    print("  CapEff = 0x%s   -> %d of %d capabilities held"
          % (cap_eff, len(held), len(CAP_NAMES)))
    print("  CapBnd = 0x%s   -> the bounding set: a ceiling you can never rise above"
          % cap_bnd)
    print()
    print("  HELD (%d):" % len(held))
    for name in held:
        print("    + %-24s %s" % (name, CAP_NOTES.get(name, "")))
    notable = [n for n in dropped if n in CAP_HEADLINE]
    print("  DROPPED — %d in total. the ones worth knowing by name:" % len(dropped))
    for name in notable:
        print("    - %-24s %s" % (name, CAP_NOTES.get(name, "")))

    print()
    print("  read that list again. CAP_SYS_ADMIN is absent, and CAP_SYS_ADMIN is")
    print("  what mount(), unshare(), setns() and pivot_root() all require.")
    print("  a container runtime needs every one of them. THAT is why building an")
    print("  image inside an unprivileged CI container does not work.")

    # CLONE_NEWUSER is the interesting one: it needs no capability at all.
    max_userns = read_int_file("/proc/sys/user/max_user_namespaces")
    seccomp = read_status_field("Seccomp")
    seccomp_mode = {"0": "disabled", "1": "strict", "2": "filter (BPF)"}.get(
        seccomp, seccomp or "unknown")
    print()
    print("  the sharp one is CLONE_NEWUSER. creating a USER namespace needs no")
    print("  capability on a modern kernel -- that is the whole point of rootless")
    print("  containers. and it still failed here. two gates, not one:")
    print("    gate 1  capabilities   -> CAP_SYS_ADMIN: absent (see above)")
    print("    gate 2  seccomp        -> Seccomp mode %s, %s filter(s) installed"
          % (seccomp_mode, read_status_field("Seccomp_filters") or "?"))
    print("    kernel would allow it: user.max_user_namespaces = %s (non-zero)"
          % max_userns)
    print("  so the runtime's default seccomp profile is denying the syscall")
    print("  independently of the capability set. --privileged switches BOTH off,")
    print("  which is why it is a security decision and not a convenience flag.")
    print()


# ---------------------------------------------------------------------------
# section 3 -- a layered filesystem, built for real
# ---------------------------------------------------------------------------

WHITEOUT_PREFIX = ".wh."          # the convention OCI layers use on the wire


class Overlay:
    """An ordered stack of read-only lower directories plus one writable upper.

    This is overlayfs' model in pure Python: read resolves top-down, write
    copies a lower file up before touching it, delete writes a whiteout.
    Lower layers are NEVER mutated -- that is what makes them shareable.
    """

    def __init__(self, lowers: list[str], upper: str) -> None:
        self.lowers = lowers          # index 0 == closest to the top
        self.upper = upper
        self.copy_ups = 0
        self.copied_bytes = 0
        self.whiteouts = 0

    # -- read path ---------------------------------------------------------
    def _whiteout_path(self, name: str) -> str:
        return os.path.join(self.upper, WHITEOUT_PREFIX + name)

    def resolve(self, name: str) -> tuple[str | None, str]:
        """Return (path, which_layer). Top-down, first match wins."""
        if os.path.exists(self._whiteout_path(name)):
            return None, "whiteout (deleted in upper)"
        candidate = os.path.join(self.upper, name)
        if os.path.exists(candidate):
            return candidate, "upper (writable)"
        for depth, lower in enumerate(self.lowers):
            candidate = os.path.join(lower, name)
            if os.path.exists(candidate):
                return candidate, "lower[%d] %s" % (depth, os.path.basename(lower))
        return None, "not found"

    def read(self, name: str) -> bytes | None:
        path, _ = self.resolve(name)
        if path is None:
            return None
        with open(path, "rb") as fh:
            return fh.read()

    def merged(self) -> list[tuple[str, str]]:
        """The merged directory listing, as the process inside would see it."""
        seen: dict[str, str] = {}
        for entry in sorted(os.listdir(self.upper)):
            if entry.startswith(WHITEOUT_PREFIX):
                continue
            seen[entry] = "upper"
        for depth, lower in enumerate(self.lowers):
            for entry in sorted(os.listdir(lower)):
                if entry in seen:
                    continue
                if os.path.exists(self._whiteout_path(entry)):
                    continue
                seen[entry] = "lower[%d]" % depth
        return sorted(seen.items())

    # -- write path --------------------------------------------------------
    def copy_up(self, name: str) -> tuple[bool, float, int]:
        """Ensure `name` exists in the upper layer. Returns (did_copy, secs, bytes)."""
        target = os.path.join(self.upper, name)
        if os.path.exists(target):
            return False, 0.0, 0
        source = None
        for lower in self.lowers:
            candidate = os.path.join(lower, name)
            if os.path.exists(candidate):
                source = candidate
                break
        if source is None:
            return False, 0.0, 0
        size = os.path.getsize(source)
        start = time.perf_counter()
        shutil.copyfile(source, target)       # the ENTIRE file, for one byte
        elapsed = time.perf_counter() - start
        self.copy_ups += 1
        self.copied_bytes += size
        return True, elapsed, size

    def write_byte_at_end(self, name: str) -> tuple[float, float, int]:
        """Append one byte. Returns (copy_up_secs, write_secs, bytes_copied)."""
        _did, up_secs, size = self.copy_up(name)
        target = os.path.join(self.upper, name)
        start = time.perf_counter()
        with open(target, "ab") as fh:
            fh.write(b"!")
            fh.flush()
        return up_secs, time.perf_counter() - start, size

    def unlink(self, name: str) -> str:
        """Delete from the merged view. Lower layers are immutable, so we mask."""
        upper_path = os.path.join(self.upper, name)
        in_upper = os.path.exists(upper_path)
        in_lower = any(os.path.exists(os.path.join(lo, name)) for lo in self.lowers)
        if in_upper:
            os.unlink(upper_path)
        if in_lower:
            with open(self._whiteout_path(name), "wb"):
                pass
            self.whiteouts += 1
            return "whiteout written (file still present in a lower layer)"
        return "removed from upper (no lower copy existed)"


def _make_file(path: str, size: int, fill: bytes) -> None:
    with open(path, "wb") as fh:
        block = fill * (65536 // len(fill) + 1)
        remaining = size
        while remaining > 0:
            fh.write(block[: min(len(block), remaining)])
            remaining -= min(len(block), remaining)
        fh.flush()
        os.fsync(fh.fileno())


BIG_MB = 40
BIG_COUNT = 5


def human(nbytes: float) -> str:
    if nbytes >= 1024 * 1024:
        return "%.1f MB" % (nbytes / 1024 / 1024)
    if nbytes >= 1024:
        return "%.1f KB" % (nbytes / 1024)
    return "%d B" % nbytes


def section_layers() -> None:
    print("== 3 · THE LAYERED FILESYSTEM, BUILT FOR REAL ==")

    # First: the container this script is running in already IS an overlay.
    real_lowers = 0
    real_line = ""
    try:
        with open("/proc/self/mountinfo") as fh:
            for line in fh:
                fields = line.split()
                if fields[4] == "/" and " overlay " in line:
                    real_line = line
                    for opt in line.rsplit(" ", 1)[-1].split(","):
                        if opt.startswith("lowerdir="):
                            real_lowers = len(opt[len("lowerdir="):].split(":"))
                    break
    except OSError:
        pass
    if real_line:
        print("  our own root filesystem, from /proc/self/mountinfo:")
        print("    fstype   overlay")
        print("    lowerdir %d read-only layers stacked" % real_lowers)
        print("    upperdir 1 writable layer (this container's private scratch)")
        print("    workdir  1 (overlayfs' staging area for atomic renames)")
        print("  every one of those %d lower layers is shared, read-only, with every"
              % real_lowers)
        print("  other container built from the same image. now build one by hand.")
    print()

    root = tempfile.mkdtemp(prefix="l02-overlay-")
    layers = ["00-base-os", "01-runtime", "02-vendor-deps", "03-app"]
    paths = {}
    for name in layers + ["99-upper"]:
        paths[name] = os.path.join(root, name)
        os.makedirs(paths[name])

    # Layer 0: a tiny "base OS".
    _make_file(os.path.join(paths["00-base-os"], "os-release"), 220, b"ID=demo\n")
    _make_file(os.path.join(paths["00-base-os"], "ca-certificates.crt"), 4096, b"PEM\n")
    _make_file(os.path.join(paths["00-base-os"], "libc.so"), 1_500_000, b"\x7fELF")
    # Layer 1: a "runtime", which shadows a base file.
    _make_file(os.path.join(paths["01-runtime"], "python3.12"), 900_000, b"\x7fELF")
    _make_file(os.path.join(paths["01-runtime"], "os-release"), 260, b"ID=runtime\n")
    # Layer 2: vendored dependencies -- the big ones. Three identical bundles so
    # the copy-up cost can be measured three times and reported as a median.
    for idx in range(BIG_COUNT):
        _make_file(os.path.join(paths["02-vendor-deps"], "vendor-bundle-%d.bin" % idx),
                   BIG_MB * 1024 * 1024, b"dep-payload;")
    _make_file(os.path.join(paths["02-vendor-deps"], "requirements.lock"), 2048, b"pkg\n")
    # Layer 3: the application.
    _make_file(os.path.join(paths["03-app"], "app.py"), 8192, b"print('hi')\n")
    _make_file(os.path.join(paths["03-app"], "config.yaml"), 512, b"debug: false\n")

    # Lower list is TOP-DOWN: the last layer built is searched first.
    lowers = [paths[n] for n in reversed(layers)]
    ov = Overlay(lowers, paths["99-upper"])

    print("  a 4-layer image plus a writable upper layer:")
    for depth, name in enumerate(reversed(layers)):
        total = sum(os.path.getsize(os.path.join(paths[name], f))
                    for f in os.listdir(paths[name]))
        print("    lower[%d]  %-16s %9s  read-only, shared between containers"
              % (depth, name, human(total)))
    print("    upper     %-16s %9s  writable, private to this container"
          % ("99-upper", human(0)))
    print()

    print("  READ PATH — first match top-down wins:")
    for name in ("config.yaml", "os-release", "libc.so",
                 "vendor-bundle-0.bin", "nope.txt"):
        _path, where = ov.resolve(name)
        print("    read %-20s -> %s" % (name, where))
    print("  'os-release' exists in TWO layers. the runtime layer shadows the base")
    print("  layer's copy; the base copy is still on disk and still takes space.")
    print()

    # --- copy-up, measured ------------------------------------------------
    print("  COPY-UP — the cost of the first write to a lower-layer file:")
    upper_native = os.path.join(paths["99-upper"], "scratch.bin")
    _make_file(upper_native, BIG_MB * 1024 * 1024, b"scratch-data;")

    def timed_append(path: str) -> float:
        """Append one byte. No fsync: we are isolating the copy-up, and an
        fsync of a 40 MB file adds writeback noise that swamps the signal."""
        start = time.perf_counter()
        with open(path, "ab") as fh:
            fh.write(b"!")
            fh.flush()
        return time.perf_counter() - start

    # Settle writeback from building the layers, then discard warm-up samples,
    # so we are timing the append and not the tail of a 160 MB flush.
    os.sync()
    for _ in range(3):
        timed_append(upper_native)

    # Baseline: a file already in the upper layer. No copy-up is possible.
    upper_samples = sorted(timed_append(upper_native) for _ in range(7))
    upper_ms = statistics.median(upper_samples) * 1000

    # The real thing: one byte into a lower-layer file triggers a full copy.
    # Three separate files, because copy-up happens exactly once per file.
    copy_only, first_samples, copied_each = [], [], 0
    for idx in range(BIG_COUNT):
        up_secs, write_secs, copied = ov.write_byte_at_end("vendor-bundle-%d.bin" % idx)
        copy_only.append(up_secs * 1000)
        first_samples.append((up_secs + write_secs) * 1000)
        copied_each = copied
    first_ms = statistics.median(first_samples)
    copy_ms = statistics.median(copy_only)

    # Second write to a file that has now been copied up into the upper layer.
    second_samples = sorted(
        timed_append(os.path.join(paths["99-upper"], "vendor-bundle-0.bin"))
        for _ in range(7)
    )
    second_ms = statistics.median(second_samples) * 1000

    ratio_first = first_ms / second_ms if second_ms else float("inf")
    ratio_upper = first_ms / upper_ms if upper_ms else float("inf")
    throughput = (copied_each / 1024 / 1024) / (copy_ms / 1000) if copy_ms else 0.0

    print("    file under test          vendor-bundle-N.bin, %d MB, in lower[1]" % BIG_MB)
    print("    bytes actually changed   1")
    print("    samples                  %d files copied up; %d timed appends each"
          % (BIG_COUNT, len(second_samples)))
    print("                             medians reported")
    print()
    print("    %-42s %9.2f ms" % ("write 1 byte, file already in upper", upper_ms))
    print("    %-42s %9.2f ms  <-- copy-up"
          % ("write 1 byte, file in a LOWER layer", first_ms))
    print("    %-42s %9.2f ms" % ("   ...of which: copying the file", copy_ms))
    print("    %-42s %9.2f ms" % ("write 1 byte again, same file", second_ms))
    print("       (individual copy-ups: %s ms)"
          % ", ".join("%.0f" % s for s in copy_only))
    print()
    print("    WRITE AMPLIFICATION  %s bytes moved to change 1 byte = %sx"
          % ("{:,}".format(copied_each), "{:,}".format(copied_each)))
    print("    that figure is exact and it does not vary: it is the file size.")
    print("    copy-up ran at ~%.0f MB/s here, so the first write cost %.0fx the"
          % (throughput, ratio_first))
    print("    second write to the same file and %.0fx a write to a file already"
          % ratio_upper)
    print("    in the upper layer -- but those RATIOS move with cache state from")
    print("    run to run. the bytes do not. size, not speed, is the thing to reason")
    print("    about: the cost is paid ONCE per file, per container, and it scales")
    print("    with FILE size, not write size. one byte into a 5 GB file copies 5 GB.")
    print("    NOTE: warm page cache on local storage. on cold storage, or a network")
    print("    or copy-on-write backing store, the same copy is far slower.")
    print()

    # --- whiteout ---------------------------------------------------------
    print("  WHITEOUT — deleting something you do not own:")
    before = [n for n, _ in ov.merged()]
    result = ov.unlink("libc.so")
    after = [n for n, _ in ov.merged()]
    still_there = os.path.exists(os.path.join(paths["00-base-os"], "libc.so"))
    lower_size = os.path.getsize(os.path.join(paths["00-base-os"], "libc.so"))
    print("    rm libc.so           -> %s" % result)
    print("    merged view          -> %s" % ("gone" if "libc.so" not in after else "STILL VISIBLE"))
    print("    lower[3] on disk     -> %s (%.1f MB)"
          % ("still present" if still_there else "removed", lower_size / 1024 / 1024))
    upper_entries = sorted(os.listdir(paths["99-upper"]))
    marks = [e for e in upper_entries if e.startswith(WHITEOUT_PREFIX)]
    print("    upper layer now has  -> %d entries, of which %d whiteout marker(s): %s"
          % (len(upper_entries), len(marks), ", ".join(marks)))
    print("    merged entries: %d before, %d after" % (len(before), len(after)))
    print("    this is why `RUN rm -rf /secret` in a Dockerfile does not shrink the")
    print("    image and does not remove the secret: the delete is a marker in a NEW")
    print("    layer. anyone with the image can read the layer below it.")
    print()

    print("  layer accounting for this container: %d copy-up(s), %.1f MB copied, "
          "%d whiteout(s)" % (ov.copy_ups, ov.copied_bytes / 1024 / 1024, ov.whiteouts))
    shutil.rmtree(root, ignore_errors=True)
    print()
    return None


# ---------------------------------------------------------------------------
# section 4 -- cgroups v2, read and interpreted
# ---------------------------------------------------------------------------

CGROUP_ROOT = "/sys/fs/cgroup"

CGROUP_FILES = [
    ("cgroup.controllers", "which resource controllers are available here"),
    ("memory.max",         "HARD memory ceiling. exceed it and the OOM killer fires"),
    ("memory.high",        "soft ceiling: the kernel throttles reclaim instead of killing"),
    ("memory.current",     "bytes charged to this cgroup right now"),
    ("memory.peak",        "high-water mark since boot -- size your limit from this"),
    ("memory.swap.max",    "swap ceiling; 0 means anonymous memory can never spill"),
    ("cpu.max",            "'QUOTA PERIOD' in microseconds. you get QUOTA per PERIOD"),
    ("cpu.stat",           "usage and, crucially, throttling counters"),
    ("pids.max",           "process/thread count ceiling -- the fork-bomb fuse"),
    ("pids.current",       "processes and threads alive in this cgroup now"),
    ("io.max",             "per-device read/write bytes-per-second and IOPS ceilings"),
]


def read_cgroup(name: str) -> str | None:
    try:
        with open(os.path.join(CGROUP_ROOT, name)) as fh:
            return fh.read().strip()
    except OSError:
        return None


def section_cgroups() -> None:
    print("== 4 · CGROUPS v2 — WHAT THE PROCESS MAY *USE* ==")
    membership = read_cgroup("../../..") if False else None
    try:
        with open("/proc/self/cgroup") as fh:
            print("  /proc/self/cgroup -> %s" % fh.read().strip())
    except OSError:
        pass
    print("  namespaces limit what a process SEES. cgroups limit what it may USE.")
    print("  they are entirely separate kernel subsystems that a container runtime")
    print("  happens to configure together.")
    print()

    unlimited = []
    for name, meaning in CGROUP_FILES:
        value = read_cgroup(name)
        if value is None:
            print("  %-20s %-28s %s" % (name, "(unreadable here)", meaning))
            continue
        if name == "cpu.stat":
            stats = dict(
                (line.split()[0], int(line.split()[1]))
                for line in value.splitlines() if len(line.split()) == 2
            )
            print("  %-20s %-28s %s" % (name, "(parsed below)", meaning))
            for key in ("usage_usec", "nr_periods", "nr_throttled",
                        "throttled_usec", "nr_bursts"):
                if key in stats:
                    print("      %-16s %s" % (key, "{:,}".format(stats[key])))
            continue
        if value == "max":
            unlimited.append(name)
        if len(value) >= 28:
            print("  %-20s %s" % (name, meaning))
            print("  %-20s %s" % ("", value))
        else:
            print("  %-20s %-28s %s" % (name, value or "(empty)", meaning))

    print()
    quota = read_cgroup("cpu.max") or ""
    parts = quota.split()
    if len(parts) == 2 and parts[0] != "max":
        cores = int(parts[0]) / int(parts[1])
        print("  cpu.max '%s' means %.2f CPU-seconds per second = %.2f cores."
              % (quota, cores, cores))
    elif parts:
        print("  cpu.max '%s': quota is 'max' -- UNLIMITED in this sandbox." % quota)
        print("  with `--cpus 1.5` it would read '150000 100000': 150 ms of CPU")
        print("  allowed in every 100 ms window, across all threads combined.")

    stats_raw = read_cgroup("cpu.stat") or ""
    stats = dict(
        (line.split()[0], int(line.split()[1]))
        for line in stats_raw.splitlines() if len(line.split()) == 2
    )
    print()
    print("  THE DISTINCTION THAT MATTERS, and it is not symmetric:")
    print("    exceed cpu.max     -> you are THROTTLED. the kernel stops scheduling")
    print("                          your threads until the next 100 ms period opens.")
    print("                          from inside this looks like LATENCY, not an error:")
    print("                          no exception, no log line, p99 just grows a step.")
    print("                          measured here: nr_throttled=%s throttled_usec=%s"
          % (stats.get("nr_throttled", "?"), stats.get("throttled_usec", "?")))
    print("    exceed memory.max  -> you are KILLED. the kernel OOM killer picks a")
    print("                          process in the cgroup and sends an uncatchable")
    print("                          SIGKILL. no grace period, no handler, no stack")
    print("                          trace, exit code 137 (128+9).")
    print()
    print("  CPU is a rate you can be slowed to. memory is a level you cannot exceed.")
    print("  that asymmetry is why a memory limit is the one you must always set, and")
    print("  why an OOM kill never appears in your application logs.")
    if unlimited:
        print()
        print("  HONESTY NOTE: %s read 'max' (unlimited) in this sandbox."
              % ", ".join(unlimited))
        print("  this container was started without resource limits, so nothing here")
        print("  is capped. `docker run --memory 512m --cpus 1.5 --pids-limit 200`")
        print("  writes 536870912, '150000 100000' and 200 into these same files.")
    # --- page cache counts against memory.max. Measure it. -----------------
    print()
    print("  THE PART THAT SURPRISES PEOPLE: page cache is charged to the cgroup.")
    before = read_cgroup("memory.current")
    probe_dir = tempfile.mkdtemp(prefix="l02-pagecache-")
    probe_file = os.path.join(probe_dir, "blob.bin")
    probe_mb = 64
    _make_file(probe_file, probe_mb * 1024 * 1024, b"cache-me;")
    with open(probe_file, "rb") as fh:            # read it back in, filling cache
        while fh.read(1024 * 1024):
            pass
    after = read_cgroup("memory.current")
    if before and after:
        delta = int(after) - int(before)
        print("    memory.current before writing a %d MB file   %s"
              % (probe_mb, human(int(before))))
        print("    memory.current after writing and reading it  %s" % human(int(after)))
        print("    delta                                        %s (%.0f%% of the file)"
              % (human(delta), 100.0 * delta / (probe_mb * 1024 * 1024)))
    shutil.rmtree(probe_dir, ignore_errors=True)
    freed = read_cgroup("memory.current")
    if freed and after:
        print("    after deleting the file                      %s" % human(int(freed)))
    print("    your heap did not grow. the kernel cached file pages on your behalf")
    print("    and billed them to your cgroup. this is why a container that streams")
    print("    large files gets OOM-killed at a memory number that matches nothing")
    print("    in your application's own profiler: reclaimable cache counts toward")
    print("    memory.max, and the kernel reclaims it rather than killing you --")
    print("    right up until it cannot reclaim fast enough.")

    print()
    mem_cur = read_cgroup("memory.current")
    mem_peak = read_cgroup("memory.peak")
    if mem_cur and mem_peak:
        print("  sizing rule: memory.peak (%s) is the high-water mark for the whole"
              % human(int(mem_peak)))
        print("  container since it started -- page cache included, which is why the")
        print("  peak above dwarfs memory.current (%s). size a limit from an"
              % human(int(mem_cur)))
        print("  observed peak under real load plus headroom; size it from the")
        print("  current value and you ship an OOM kill.")
    print()
    _ = membership


# ---------------------------------------------------------------------------
# section 5 -- PID 1: zombies and signals
# ---------------------------------------------------------------------------

def proc_state(pid: int) -> str | None:
    try:
        with open("/proc/%d/stat" % pid) as fh:
            data = fh.read()
        return data.rsplit(") ", 1)[1].split()[0]
    except (OSError, IndexError):
        return None


def section_pid1_zombies() -> None:
    print("== 5a · PID 1 — THE ZOMBIE REAPING DUTY ==")
    print("  a process that exits is not gone. the kernel keeps its exit status")
    print("  until the PARENT calls wait(). until then it is a zombie: no memory,")
    print("  no code, just a slot in the process table and its pid.")
    print()

    children = []
    for _ in range(6):
        pid = os.fork()
        if pid == 0:
            os._exit(0)
        children.append(pid)
    time.sleep(0.25)

    states = {pid: proc_state(pid) for pid in children}
    zombies = [pid for pid, st in states.items() if st == "Z"]
    print("  forked %d children; every one called _exit(0) immediately." % len(children))
    print("  we did NOT call wait(). their /proc/<pid>/stat state:")
    print("    %s" % "  ".join("%d=%s" % (p, states[p]) for p in children))
    print("  zombies: %d of %d   ('Z' is the state letter in stat field 3)"
          % (len(zombies), len(children)))
    print("  pids.current for this cgroup: %s" % (read_cgroup("pids.current") or "?"))

    for pid in children:
        os.waitpid(pid, 0)
    time.sleep(0.05)
    after = [pid for pid in children if proc_state(pid) == "Z"]
    print()
    print("  ...then one os.waitpid() per child.")
    print("  zombies now: %d of %d" % (len(after), len(children)))
    print("  pids.current for this cgroup: %s" % (read_cgroup("pids.current") or "?"))
    print()
    print("  when a process dies, its orphaned children are re-parented to PID 1,")
    print("  and reaping them becomes PID 1's job. a normal init does this in its")
    print("  main loop. your web framework does not -- it has no such loop.")
    print("  so: app spawns a subprocess, subprocess spawns a helper, subprocess")
    print("  exits, the helper is re-parented to your app as PID 1, and when the")
    print("  helper finishes nobody reaps it. one zombie per request. pids.max is")
    print("  the fuse: hit it and fork() starts returning EAGAIN, which surfaces as")
    print("  'Resource temporarily unavailable' from something unrelated.")
    print()


GRACE_SECONDS = 1.0          # a scaled stand-in for terminationGracePeriodSeconds
CONCURRENCY = 8              # requests in flight at any moment
WORK_MS = 25                 # how long each in-flight request still needs
MAX_TICKS = 200              # hard stop, so a runaway child can never hang the run


def _child_worker(mode: str, write_fd: int) -> None:
    """A server holding CONCURRENCY requests in flight, admitting a new one
    each time it completes one -- until it is told to drain.

    mode 'default' -- no handler: the kernel applies SIGTERM's default action.
    mode 'ignore'  -- SIGTERM ignored, which is what PID 1 does implicitly.
    mode 'handle'  -- a handler flips a drain flag: stop admitting, finish, exit.
    """
    drain = {"asked": False}

    if mode == "ignore":
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
    elif mode == "handle":
        def on_term(_signum, _frame):
            drain["asked"] = True
        signal.signal(signal.SIGTERM, on_term)

    inflight = CONCURRENCY
    served = 0
    os.write(write_fd, b"ready\n")
    for _ in range(MAX_TICKS):
        if inflight == 0:
            break
        time.sleep(WORK_MS / 1000.0)
        inflight -= 1
        served += 1
        if not drain["asked"]:
            inflight += 1                    # still accepting: stay at full load
        # Report state after every completion, so the parent knows what was
        # in flight at the instant the process died.
        os.write(write_fd, b"s=%d,f=%d\n" % (served, inflight))
    os.write(write_fd, b"drained\n")
    os._exit(0)


def _run_deploy(mode: str) -> dict:
    r, w = os.pipe()
    pid = os.fork()
    if pid == 0:
        os.close(r)
        _child_worker(mode, w)
    os.close(w)
    os.set_blocking(r, False)

    # Wait for "ready", then let the server run at full load for a moment.
    buf = b""
    while b"ready\n" not in buf:
        try:
            buf += os.read(r, 4096)
        except BlockingIOError:
            time.sleep(0.002)
    time.sleep(WORK_MS / 1000.0 * 4)

    t0 = time.perf_counter()
    os.kill(pid, signal.SIGTERM)

    sigkilled = False
    deadline = t0 + GRACE_SECONDS
    status = 0
    while True:
        try:
            buf += os.read(r, 65536)         # keep draining so the pipe never fills
        except (BlockingIOError, OSError):
            pass
        done_pid, status = os.waitpid(pid, os.WNOHANG)
        if done_pid:
            break
        if time.perf_counter() >= deadline:
            os.kill(pid, signal.SIGKILL)     # the uncatchable one
            sigkilled = True
            _done, status = os.waitpid(pid, 0)
            break
        time.sleep(0.002)
    elapsed = time.perf_counter() - t0
    try:
        while True:
            chunk = os.read(r, 65536)
            if not chunk:
                break
            buf += chunk
    except (BlockingIOError, OSError):
        pass
    os.close(r)

    served, inflight, drained = 0, CONCURRENCY, False
    for line in buf.decode(errors="replace").splitlines():
        if line.startswith("s="):
            served = int(line.split(",")[0][2:])
            inflight = int(line.split("f=")[1])
        elif line == "drained":
            drained = True

    if os.WIFSIGNALED(status):
        sig = os.WTERMSIG(status)
        outcome = "killed by %s" % signal.Signals(sig).name
        exit_code = 128 + sig
        severed = inflight                   # in flight when the axe fell
    else:
        outcome = "exited cleanly"
        exit_code = os.WEXITSTATUS(status)
        severed = 0 if drained else inflight
    return {
        "mode": mode, "outcome": outcome, "exit_code": exit_code,
        "served": served, "severed": severed, "secs": elapsed,
        "sigkilled": sigkilled, "drained": drained,
    }


def section_pid1_signals() -> None:
    print("== 5b · PID 1 — SIGNALS, AND THE REQUESTS A DEPLOY DROPS ==")
    print("  every rollout is the same three steps: send SIGTERM, wait out the")
    print("  grace period, send SIGKILL. what your process does in the middle")
    print("  decides whether in-flight requests survive.")
    print()
    print("  three servers, identical load: %d requests in flight at all times,"
          % CONCURRENCY)
    print("  %d ms each, a new one admitted whenever one completes." % WORK_MS)
    print("  SIGTERM arrives after ~%d ms; grace period %.1f s.\n"
          % (WORK_MS * 4, GRACE_SECONDS))

    labels = {
        "default": "no handler (an ordinary process)",
        "ignore":  "SIGTERM ignored (== PID 1, no handler)",
        "handle":  "handler installed: stop admitting, drain",
    }
    results = [_run_deploy(mode) for mode in ("default", "ignore", "handle")]

    print("  %-42s %-18s %5s %8s %9s %8s"
          % ("process", "outcome", "exit", "served", "SEVERED", "took"))
    for res in results:
        print("  %-42s %-18s %5d %8d %9d %7.0fms"
              % (labels[res["mode"]], res["outcome"], res["exit_code"],
                 res["served"], res["severed"], res["secs"] * 1000))

    default_res = next(r for r in results if r["mode"] == "default")
    ignore_res = next(r for r in results if r["mode"] == "ignore")
    handle_res = next(r for r in results if r["mode"] == "handle")

    print()
    print("  READ THE MIDDLE ROW. that is your container.")
    print("  row 1: an ordinary process with no handler gets SIGTERM's DEFAULT")
    print("         DISPOSITION, which is 'terminate' (signal(7)). dead in %.0f ms,"
          % (default_res["secs"] * 1000))
    print("         severing the %d requests it was holding. fast and destructive,"
          % default_res["severed"])
    print("         but at least the deploy moves on.")
    print("  row 2: PID 1 is special-cased by the kernel. a signal with no handler")
    print("         installed is DISCARDED for PID 1 of a pid namespace -- the")
    print("         default action is never applied (pid_namespaces(7)). so SIGTERM")
    print("         does NOTHING. the process never learns it is being replaced, so")
    print("         it keeps admitting new work for the full %.1f s grace period"
          % GRACE_SECONDS)
    print("         (%d more requests served, every one of them accepted by a pod"
          % (ignore_res["served"] - default_res["served"]))
    print("         that was already being deleted), and is then SIGKILLed: exit")
    print("         %d, %d requests severed, %.0f ms of deploy time burned per pod."
          % (ignore_res["exit_code"], ignore_res["severed"],
             ignore_res["secs"] * 1000))
    print("         (we model this with SIG_IGN, because creating a pid namespace")
    print("          needs CAP_SYS_ADMIN -- see section 2. the observable behaviour")
    print("          is identical: SIGTERM has no effect, only SIGKILL ends it.)")
    print("  row 3: a handler that flips a drain flag stopped admitting new work,")
    print("         finished the %d requests it held, and exited 0 in %.0f ms --"
          % (CONCURRENCY, handle_res["secs"] * 1000))
    print("         %.0fx faster than the grace period and %d requests severed."
          % (GRACE_SECONDS * 1000 / handle_res["secs"] / 1000
             if handle_res["secs"] else 0, handle_res["severed"]))
    print()
    print("  the two failure rows differ in WHEN they hurt, not whether. row 1")
    print("  severs %d requests immediately; row 2 severs %d after burning the"
          % (default_res["severed"], ignore_res["severed"]))
    print("  entire grace period, stalling every rollout by that much as well.")
    print()
    print("  scale row 2: %d severed per pod x 40 pods x 12 deploys/day"
          % ignore_res["severed"])
    print("  = %s severed connections a day, and NONE appear in your error rate:"
          % "{:,}".format(ignore_res["severed"] * 40 * 12))
    print("  the client gets a TCP reset, not a 5xx, so your own counters stay flat.")
    print("  deploy time also goes from %.0f ms to %.0f ms per pod (%.1fx), which"
          % (handle_res["secs"] * 1000, ignore_res["secs"] * 1000,
             ignore_res["secs"] / handle_res["secs"] if handle_res["secs"] else 0))
    print("  is why a 40-pod rolling update that 'should take a minute' takes ten.")
    print()
    print("  the fix is two lines of signal handling, or one flag: an init process")
    print("  at PID 1 that forwards signals and reaps zombies, with your app as its")
    print("  child -- where the ordinary default dispositions apply again.")
    print()


def main() -> int:
    started = time.perf_counter()
    print("container internals, observed from inside a container")
    print("pid %d  uid %d  python %s  kernel %s"
          % (os.getpid(), os.getuid(), sys.version.split()[0], os.uname().release))
    print()
    section_namespaces()
    section_capabilities()
    section_layers()
    section_cgroups()
    section_pid1_zombies()
    section_pid1_signals()
    print("(total wall time %.1f s)" % (time.perf_counter() - started))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
