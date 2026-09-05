"""
The Filesystem Hierarchy — ls -l, find, du and df rebuilt from stat(2).

Everything `ls -l` prints comes from one syscall per file, stat(2), which
returns the inode: type and permission bits, link count, owner, size, times,
and the inode number itself. This script rebuilds `ls -l` from that struct,
walks a tree the way `find` does, measures disk usage the way `du` does
(blocks, not bytes: a sparse file shows the difference), and asks the
filesystem for its free space the way `df` does (statvfs). It builds a small
tree in a temp directory first so hard links, symlinks and a dangling link are
all present. Self-terminating.

Docs: phases/01-linux-and-the-command-line/04-the-filesystem-hierarchy/docs/en.md
Spec: POSIX.1-2017 stat(), lstat(), readlink(), statvfs(), <sys/stat.h>;
      Linux man-pages stat(2), inode(7), hier(7); Filesystem Hierarchy Standard 3.0

Run:
    python ls_and_find.py
"""

import fnmatch
import grp
import os
import pwd
import stat
import sys
import tempfile
import time


def banner(title):
    line = "=" * 72
    print(f"\n{line}\n{title}\n{line}")


# ─── 1 · ls -l from stat(2) ──────────────────────────────────────────────────
def mode_string(mode):
    """Turn st_mode's bits into the ten characters ls prints: -rwxr-xr-x."""
    kind = {stat.S_IFDIR: "d", stat.S_IFLNK: "l", stat.S_IFCHR: "c", stat.S_IFBLK: "b",
            stat.S_IFIFO: "p", stat.S_IFSOCK: "s"}.get(stat.S_IFMT(mode), "-")
    bits = ""
    for who, r, w, x in (("u", stat.S_IRUSR, stat.S_IWUSR, stat.S_IXUSR),
                         ("g", stat.S_IRGRP, stat.S_IWGRP, stat.S_IXGRP),
                         ("o", stat.S_IROTH, stat.S_IWOTH, stat.S_IXOTH)):
        bits += "r" if mode & r else "-"
        bits += "w" if mode & w else "-"
        bits += "x" if mode & x else "-"
    return kind + bits


def owner(uid):
    try:
        return pwd.getpwuid(uid).pw_name
    except KeyError:
        return str(uid)


def group(gid):
    try:
        return grp.getgrgid(gid).gr_name
    except KeyError:
        return str(gid)


def ls_l(path, show_inode=False):
    """`ls -l path` (and `-i`): one lstat per entry, formatted like the real thing."""
    entries = sorted(os.scandir(path), key=lambda e: e.name)   # getdents64 under the hood
    for e in entries:
        st = e.stat(follow_symlinks=False)                      # lstat: describe the link itself
        when = time.strftime("%b %d %H:%M", time.localtime(st.st_mtime))
        name = e.name
        if stat.S_ISLNK(st.st_mode):
            name += " -> " + os.readlink(e.path)                # readlink(2): where it points
        inode = f"{st.st_ino:>8} " if show_inode else ""
        print(f"{inode}{mode_string(st.st_mode)} {st.st_nlink:>2} {owner(st.st_uid):<8} {group(st.st_gid):<8} {st.st_size:>7} {when} {name}")


# ─── 2 · find from os.walk ───────────────────────────────────────────────────
def find(root, name=None, kind=None, min_size=None, newer_than=None):
    """A `find` that understands -name, -type, -size + and -mmin -N.
    os.walk is opendir/getdents64 recursively; every test is one lstat."""
    for dirpath, dirnames, filenames in os.walk(root):
        for entry in [dirpath] if dirpath == root else [] + [os.path.join(dirpath, n) for n in dirnames + filenames]:
            st = os.lstat(entry)
            if name and not fnmatch.fnmatch(os.path.basename(entry), name):
                continue
            if kind == "f" and not stat.S_ISREG(st.st_mode):
                continue
            if kind == "d" and not stat.S_ISDIR(st.st_mode):
                continue
            if kind == "l" and not stat.S_ISLNK(st.st_mode):
                continue
            if min_size is not None and st.st_size < min_size:
                continue
            if newer_than is not None and st.st_mtime < newer_than:
                continue
            yield entry


# ─── 3 · du: blocks, not bytes ───────────────────────────────────────────────
def du(path):
    """Disk usage the way du measures it: 512-byte blocks actually allocated."""
    total_bytes = total_alloc = 0
    for dirpath, _, filenames in os.walk(path):
        for n in filenames:
            st = os.lstat(os.path.join(dirpath, n))
            total_bytes += st.st_size
            total_alloc += st.st_blocks * 512
    return total_bytes, total_alloc


# ─── 4 · df: statvfs ─────────────────────────────────────────────────────────
def df(path):
    v = os.statvfs(path)
    size = v.f_blocks * v.f_frsize
    free = v.f_bavail * v.f_frsize
    return size, free, v.f_files, v.f_favail


if __name__ == "__main__":
    root = tempfile.mkdtemp(prefix="hier-")
    os.chdir(root)

    banner(f"0 · A small tree to look at, built in {root}")
    os.makedirs("etc/app", exist_ok=True)
    os.makedirs("var/log/app", exist_ok=True)
    with open("etc/app/config.yaml", "w") as f:
        f.write("port: 8080\n")
    with open("var/log/app/app.log", "w") as f:
        f.write("2026-09-05 started\n" * 50)
    os.link("etc/app/config.yaml", "etc/app/config.hardlink")       # link(2): a second name, same inode
    os.symlink("config.yaml", "etc/app/config.symlink")             # symlink(2): a file whose content is a path
    os.symlink("/definitely/not/here", "etc/app/dangling")          # points at nothing
    os.symlink("../../var/log/app", "etc/app/logs")                 # a symlink to a directory, relative
    os.chmod("etc/app/config.yaml", 0o640)
    with open("var/log/app/sparse.bin", "wb") as f:                 # 100 MiB of "size", almost no blocks
        f.seek(100 * 1024 * 1024 - 1)
        f.write(b"\0")
    print("etc/app/config.yaml, a hard link to it, a symlink to it, a dangling symlink, a symlink to a directory,")
    print("var/log/app/app.log, and a 100 MiB sparse file. Now look at them the way ls does.")

    banner("1 · ls -li etc/app  (one lstat per entry; inode numbers on the left)")
    ls_l("etc/app", show_inode=True)
    print("\nread the columns: type+mode · link count · owner · group · size · mtime · name")
    print("config.yaml and config.hardlink share an inode and both show a link count of 2: two names, one file")
    print("config.symlink is type 'l' and its size is the length of the path it stores; the arrow is readlink(2)")

    banner("2 · stat vs lstat: following the link or describing it")
    for p in ("etc/app/config.symlink", "etc/app/dangling"):
        l = os.lstat(p)
        print(f"lstat({p}): {mode_string(l.st_mode)} size {l.st_size}  (the link itself)")
        try:
            s = os.stat(p)
            print(f"stat ({p}): {mode_string(s.st_mode)} size {s.st_size}  (what it points at)")
        except FileNotFoundError as e:
            print(f"stat ({p}): {e.strerror}: the link exists, its target does not")

    banner("3 · find: a recursive walk with tests")
    print("find . -name '*.yaml'      ->", [p for p in find(".", name="*.yaml")])
    print("find . -type l             ->", [p for p in find(".", kind="l")])
    print("find . -type f -size +1k   ->", [p for p in find(".", kind="f", min_size=1024)])
    print("find . -type d             ->", [p for p in find(".", kind="d")])
    print("find . -mmin -1 -type f    ->", len([p for p in find(".", kind="f", newer_than=time.time() - 60)]), "files changed in the last minute")

    banner("4 · du vs ls: bytes versus blocks")
    st = os.lstat("var/log/app/sparse.bin")
    print(f"ls -l says sparse.bin is {st.st_size:,} bytes ({st.st_size / 2**20:.0f} MiB): that is the file's logical length")
    print(f"du says it uses {st.st_blocks * 512:,} bytes: st_blocks × 512, the blocks actually allocated")
    b, a = du("var")
    print(f"du -s var: {b:,} bytes of file length, {a:,} bytes allocated on disk")
    print("a hole in a file costs nothing until something is written into it; databases and VM images rely on this")

    banner("5 · df: what the filesystem under this path has left (statvfs)")
    size, free, inodes, inodes_free = df(root)
    print(f"{root}: {size / 2**30:.1f} GiB total, {free / 2**30:.1f} GiB available, {inodes:,} inodes, {inodes_free:,} free")
    print("df -h reads the first three; df -i reads the last two. A disk can be 'full' with space left: no inodes")

    banner("6 · Where am I? Paths, . and .., and what a directory really is")
    print(f"absolute: {os.getcwd()}")
    print(f"relative from here: etc/app/config.yaml -> exists: {os.path.exists('etc/app/config.yaml')}")
    os.chdir("etc/app")
    print(f"after chdir('etc/app'), the same relative path -> exists: {os.path.exists('etc/app/config.yaml')}")
    print(f"'.' is inode {os.stat('.').st_ino}, '..' is inode {os.stat('..').st_ino}: every directory holds those two entries")
    print(f"realpath of logs -> {os.path.realpath('logs')}  (readlink until no symlink is left)")

    banner("7 · The hierarchy on this machine: the top level")
    purpose = {
        "bin": "essential commands (on modern distros a symlink into /usr/bin)", "boot": "the kernel and bootloader",
        "dev": "device files: the drivers' doors", "etc": "system-wide configuration, all of it text",
        "home": "users' home directories", "lib": "shared libraries (symlink into /usr/lib)",
        "media": "removable media mounts", "mnt": "temporary mounts", "opt": "self-contained third-party software",
        "proc": "the kernel's process and system window (lesson 02)", "root": "root's home directory",
        "run": "runtime state since boot: PID files, sockets (tmpfs)", "sbin": "system commands (symlink into /usr/sbin)",
        "srv": "data served by this host (rarely used)", "sys": "the kernel's device tree (lesson 02)",
        "tmp": "scratch space, cleared on reboot", "usr": "installed software: bin, lib, share, local",
        "var": "variable data: logs, caches, databases, spools", "Users": "macOS: home directories",
        "Applications": "macOS: applications", "Library": "macOS: system and app support files",
        "System": "macOS: the operating system itself", "Volumes": "macOS: mounted disks", "private": "macOS: where /etc, /var and /tmp really live",
    }
    for e in sorted(os.scandir("/"), key=lambda e: e.name):
        if e.name.startswith("."):
            continue
        st = e.stat(follow_symlinks=False)
        tag = " -> " + os.readlink(e.path) if stat.S_ISLNK(st.st_mode) else ""
        try:
            n = len(os.listdir(e.path))
        except OSError:
            n = "?"
        print(f"/{e.name:<13}{str(n):>5} entries{tag:<16}  {purpose.get(e.name, '')}")
    print(f"\nkernel: {os.uname().sysname}. On Linux this layout is the Filesystem Hierarchy Standard; macOS keeps /etc, /usr, /var and adds its own.")
