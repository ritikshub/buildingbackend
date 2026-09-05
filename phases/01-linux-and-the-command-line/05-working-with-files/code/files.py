"""
Working with Files — touch, mkdir -p, cat, cp, mv, rm, tail -f and tar,
rebuilt from the syscalls they wrap.

Each command in this file is a few lines over one or two syscalls:
touch is open(O_CREAT) + utime; mkdir -p is mkdir until EEXIST; cat is a
read/write loop; cp is the same loop into a new file (plus the mode bits);
mv is rename(2), which is atomic and instant on one filesystem and a copy
plus unlink across two; rm is unlink(2), which removes a name and nothing
else, as a still-open descriptor proves; and tar is 512-byte headers with
octal fields and a checksum, written by hand and readable by real tar.
Self-terminating; everything happens in a temp directory that is removed.

Docs: phases/01-linux-and-the-command-line/05-working-with-files/docs/en.md
Spec: POSIX.1-2017 open(), read(), write(), rename(), unlink(), mkdir(),
      rmdir(), utime(); POSIX "pax" ustar header format (XCU pax, Extended
      tar format); Linux man-pages rename(2), unlink(2), copy_file_range(2)

Run:
    python files.py
"""

import errno
import os
import shutil
import stat
import struct
import tempfile
import time


def banner(title):
    line = "=" * 72
    print(f"\n{line}\n{title}\n{line}")


# ─── touch ───────────────────────────────────────────────────────────────────
def touch(path):
    """Create if missing, else bump the modification time. open(2) + utime(2)."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT, 0o644)   # O_CREAT: make it if it is not there
    os.close(fd)
    os.utime(path, None)                                   # None = now


# ─── mkdir -p ────────────────────────────────────────────────────────────────
def mkdir_p(path):
    """mkdir(2) once per component, ignoring 'already exists'."""
    parts = path.split("/")
    for i in range(1, len(parts) + 1):
        prefix = "/".join(parts[:i])
        if not prefix:
            continue
        try:
            os.mkdir(prefix, 0o755)
        except FileExistsError:                            # EEXIST: fine, that is the -p
            pass


# ─── cat / cp: the read-write loop ───────────────────────────────────────────
def copy_fd(src_fd, dst_fd, chunk=64 * 1024):
    """The loop under cat, cp, tee and every download: read until 0, write what you got."""
    total = 0
    while True:
        buf = os.read(src_fd, chunk)
        if not buf:                                        # read returned 0: end of file
            return total
        os.write(dst_fd, buf)
        total += len(buf)


def cat(path, out_fd=1):
    fd = os.open(path, os.O_RDONLY)
    n = copy_fd(fd, out_fd)
    os.close(fd)
    return n


def cp(src, dst):
    """cp src dst: create dst, copy bytes, copy the mode bits. Not the owner, not the times."""
    st = os.stat(src)
    src_fd = os.open(src, os.O_RDONLY)
    dst_fd = os.open(dst, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, stat.S_IMODE(st.st_mode))
    n = copy_fd(src_fd, dst_fd)
    os.close(src_fd)
    os.close(dst_fd)
    return n


# ─── mv: rename, or copy + unlink ────────────────────────────────────────────
def mv(src, dst):
    """rename(2) if both are on the same filesystem; otherwise the slow way."""
    try:
        os.rename(src, dst)                                # atomic: the name flips in one step
        return "rename"
    except OSError as e:
        if e.errno != errno.EXDEV:                         # EXDEV: 'Invalid cross-device link'
            raise
        cp(src, dst)                                       # different filesystem: copy the bytes
        os.unlink(src)                                     # then forget the old name
        return "copy+unlink"


# ─── rm, rm -r ───────────────────────────────────────────────────────────────
def rm(path):
    os.unlink(path)                                        # remove one name; the data may live on


def rm_r(path):
    """Walk bottom-up: unlink every file, rmdir every directory once it is empty."""
    for dirpath, dirnames, filenames in os.walk(path, topdown=False):
        for n in filenames:
            os.unlink(os.path.join(dirpath, n))
        for n in dirnames:
            p = os.path.join(dirpath, n)
            if os.path.islink(p):
                os.unlink(p)                               # never descend into a symlinked directory
            else:
                os.rmdir(p)
    os.rmdir(path)


# ─── the atomic replace ──────────────────────────────────────────────────────
def atomic_write(path, data):
    """Write to a temp file in the same directory, fsync, then rename over the target.
    At every instant the target is either the old complete file or the new complete file."""
    tmp = f"{path}.tmp.{os.getpid()}"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    os.write(fd, data)
    os.fsync(fd)                                           # the bytes are on disk, not just in the page cache
    os.close(fd)
    os.rename(tmp, path)                                   # the switch: one atomic step


# ─── tail -f ─────────────────────────────────────────────────────────────────
def tail_f(path, seconds):
    """Seek to the end, then keep reading whatever appears. That is all tail -f is."""
    fd = os.open(path, os.O_RDONLY)
    os.lseek(fd, 0, os.SEEK_END)
    deadline = time.time() + seconds
    while time.time() < deadline:
        buf = os.read(fd, 4096)
        if buf:
            os.write(1, buf)
        else:
            time.sleep(0.05)                               # nothing new yet; real tail uses inotify
    os.close(fd)


# ─── tar: 512-byte headers, by hand ──────────────────────────────────────────
def tar_header(name, size, mode, mtime, typeflag=b"0"):
    """One ustar header block. Numbers are ASCII octal; the checksum is computed
    with the checksum field itself blanked to eight spaces."""
    fields = [
        name.encode().ljust(100, b"\0"),
        f"{mode:07o}\0".encode(),
        f"{0:07o}\0".encode(),          # uid
        f"{0:07o}\0".encode(),          # gid
        f"{size:011o}\0".encode(),
        f"{int(mtime):011o}\0".encode(),
        b"        ",                    # checksum placeholder
        typeflag,
        b"\0" * 100,                    # linkname
        b"ustar\0", b"00",              # magic, version
        b"root".ljust(32, b"\0"), b"root".ljust(32, b"\0"),
        b"\0" * 8, b"\0" * 8,           # devmajor, devminor
        b"\0" * 155,                    # prefix
    ]
    header = b"".join(fields).ljust(512, b"\0")
    checksum = sum(header)
    return header[:148] + f"{checksum:06o}\0 ".encode() + header[156:]


def tar_create(archive, paths):
    """tar -cf archive paths: for each file, a header block, then the data padded to 512."""
    with open(archive, "wb") as out:
        for p in paths:
            st = os.stat(p)
            if stat.S_ISDIR(st.st_mode):
                out.write(tar_header(p.rstrip("/") + "/", 0, stat.S_IMODE(st.st_mode), st.st_mtime, b"5"))
                continue
            out.write(tar_header(p, st.st_size, stat.S_IMODE(st.st_mode), st.st_mtime))
            with open(p, "rb") as f:
                data = f.read()
            out.write(data)
            out.write(b"\0" * (-len(data) % 512))          # pad to a block boundary
        out.write(b"\0" * 1024)                            # end of archive: two zero blocks


def tar_list(archive):
    """tar -tvf: walk the headers, skipping each file's data blocks."""
    with open(archive, "rb") as f:
        while True:
            header = f.read(512)
            if len(header) < 512 or header == b"\0" * 512:
                return
            name = header[:100].rstrip(b"\0").decode()
            mode = int(header[100:108].rstrip(b"\0 "), 8)
            size = int(header[124:136].rstrip(b"\0 "), 8)
            kind = "dir " if header[156:157] == b"5" else "file"
            print(f"   {kind} {mode:04o} {size:8d} {name}")
            f.seek(-(-size // 512) * 512, os.SEEK_CUR)       # skip the data, rounded up


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(line_buffering=True)   # print() and os.write(1) share fd 1; keep them in order
    root = tempfile.mkdtemp(prefix="files-")
    os.chdir(root)
    print(f"working in {root}")

    banner("1 · touch and mkdir -p: open(O_CREAT) and mkdir until EEXIST")
    mkdir_p("app/etc/conf.d")
    touch("app/etc/conf.d/empty.conf")
    st = os.stat("app/etc/conf.d/empty.conf")
    print(f"app/etc/conf.d/empty.conf exists, {st.st_size} bytes, mtime {time.strftime('%H:%M:%S', time.localtime(st.st_mtime))}")
    time.sleep(1.05)
    touch("app/etc/conf.d/empty.conf")
    print(f"touch again: mtime {time.strftime('%H:%M:%S', time.localtime(os.stat('app/etc/conf.d/empty.conf').st_mtime))} (bumped; size still 0)")

    banner("2 · cat and cp: the read/write loop")
    with open("app/etc/app.yaml", "w") as f:
        f.write("port: 8080\nworkers: 4\n")
    os.chmod("app/etc/app.yaml", 0o640)
    print("cat app/etc/app.yaml ->")
    n = cat("app/etc/app.yaml")
    print(f"   ({n} bytes: read until read() returned 0, write each chunk to fd 1)")
    n = cp("app/etc/app.yaml", "app/etc/app.yaml.bak")
    a, b = os.stat("app/etc/app.yaml"), os.stat("app/etc/app.yaml.bak")
    print(f"cp -> {n} bytes copied; mode preserved ({stat.S_IMODE(b.st_mode):o}), inode changed ({a.st_ino} -> {b.st_ino}): a second file, not a link")
    big = os.urandom(32 * 1024 * 1024)
    with open("big.bin", "wb") as f:
        f.write(big)
    t0 = time.perf_counter(); cp("big.bin", "big.copy"); t_loop = time.perf_counter() - t0
    t0 = time.perf_counter(); shutil.copyfile("big.bin", "big.copy2"); t_fast = time.perf_counter() - t0
    print(f"32 MiB: user-space read/write loop {t_loop * 1000:.0f} ms; shutil.copyfile {t_fast * 1000:.0f} ms"
          f" (on Linux it asks the kernel to copy with copy_file_range: no bytes visit user space)")

    banner("3 · mv: rename(2) is atomic and instant; across filesystems it is a copy")
    before = os.stat("big.bin").st_ino
    t0 = time.perf_counter(); how = mv("big.bin", "app/big.bin"); t_ren = time.perf_counter() - t0
    print(f"mv big.bin app/big.bin: {how} in {t_ren * 1e6:.0f} µs; inode {before} -> {os.stat('app/big.bin').st_ino} (same file, new name)")
    other = None
    for cand in ("/dev/shm", "/tmp", os.path.expanduser("~")):
        if os.path.isdir(cand) and os.access(cand, os.W_OK) and os.stat(cand).st_dev != os.stat(".").st_dev:
            other = cand
            break
    if other:
        dst = os.path.join(other, f"files-{os.getpid()}.bin")
        t0 = time.perf_counter(); how = mv("app/big.bin", dst); t_x = time.perf_counter() - t0
        print(f"mv app/big.bin {other}/: {how} in {t_x * 1000:.0f} ms; inode is now {os.stat(dst).st_ino}: a new file on a different filesystem")
        mv(dst, "app/big.bin")
    else:
        print("(no second filesystem writable here to show the copy+unlink path; try it inside `make shell`, where /dev/shm is a tmpfs)")

    banner("4 · rm: unlink removes a name. The data outlives it while someone holds it open")
    os.rename("big.copy", "app/held.bin")
    fd = os.open("app/held.bin", os.O_RDONLY)               # a process holds the file open ...
    rm("app/held.bin")                                      # ... and the name is removed
    print(f"unlink('app/held.bin'): exists on disk by name? {os.path.exists('app/held.bin')}")
    fst = os.fstat(fd)
    print(f"but the open descriptor still works: fstat says {fst.st_size:,} bytes, link count {fst.st_nlink}; read() ->", len(os.read(fd, 1 << 20)), "bytes")
    print("this is the 'df says full, du says empty' file from lesson 04; the blocks free when this fd closes:")
    os.close(fd)
    print("   closed. Gone now, and there was never an undo.")

    banner("5 · The atomic replace: write a temp file, fsync, rename over the target")
    atomic_write("app/etc/app.yaml", b"port: 9090\nworkers: 8\n")
    print("app/etc/app.yaml is now the new content, and at no instant was it half-written or missing.")
    print("   every editor's 'save', every package manager, every config-reloading service uses this shape")

    banner("6 · tail -f: seek to the end, then read whatever appears")
    with open("app/app.log", "w") as f:
        f.write("old line 1\nold line 2\n")
    writer = os.fork()
    if writer == 0:
        with open("app/app.log", "a") as f:
            for i in range(3):
                time.sleep(0.2)
                f.write(f"new line {i + 1} at {time.strftime('%H:%M:%S')}\n")
                f.flush()
        os._exit(0)
    print("tail -f app/app.log (for 1 s, while another process appends):")
    tail_f("app/app.log", 1.0)
    os.waitpid(writer, 0)

    banner("7 · tar: 512-byte headers with octal fields, written by hand")
    tar_create("app.tar", ["app/etc/", "app/etc/app.yaml", "app/etc/app.yaml.bak", "app/app.log"])
    size = os.stat("app.tar").st_size
    print(f"app.tar is {size} bytes = {size // 512} blocks of 512: one header per entry, data padded, two zero blocks at the end")
    with open("app.tar", "rb") as f:
        h = f.read(512)
    hname = h[:100].rstrip(b"\0")
    print(f"first header: name={hname!r} mode={h[100:108]!r} size={h[124:136]!r} magic={h[257:263]!r}")
    print("tar -tvf app.tar, read back by walking the headers:")
    tar_list("app.tar")
    import gzip
    with open("app.tar", "rb") as f, gzip.open("app.tar.gz", "wb") as g:
        g.write(f.read())
    print(f"gzip -> app.tar.gz, {os.stat('app.tar.gz').st_size} bytes: .tar.gz is exactly a tar stream fed through gzip, nothing more")
    print("verify with the real tool:  tar -tvf", os.path.join(root, "app.tar"))

    banner("8 · rm -r: unlink every file, rmdir every directory, bottom-up")
    if "--keep" not in os.sys.argv:
        os.chdir("/")
        rm_r(root)
        print(f"removed {root} and everything in it. There is no trash, no confirmation, no undo.")
    else:
        print(f"kept {root} (--keep) so you can run tar -tvf on app.tar yourself")
