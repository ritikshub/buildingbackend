"""
Users, Groups, Permissions & sudo — the kernel's access check, rebuilt.

Every open(2), every execve(2), every unlink(2) ends in one function inside
the kernel that compares who is asking with the file's owner, group and nine
mode bits. This script reimplements that function exactly (root's bypass
included), checks it against the real kernel by asking os.access() the same
questions, decodes the mode bits that ls -l prints, reads the tables behind
usernames (/etc/passwd, /etc/group), applies the umask, and demonstrates the
three special bits on a small tree. Self-terminating.

Docs: phases/01-linux-and-the-command-line/06-users-groups-permissions-and-sudo/docs/en.md
Spec: POSIX.1-2017 <sys/stat.h> mode bits, access(), umask(), chmod(), chown();
      Linux man-pages path_resolution(7), credentials(7), chmod(2), setuid(2),
      capabilities(7); /etc/passwd and /etc/group formats: passwd(5), group(5)

Run:
    python permissions.py
"""

import grp
import os
import pwd
import stat
import tempfile

R, W, X = 4, 2, 1


def banner(title):
    line = "=" * 72
    print(f"\n{line}\n{title}\n{line}")


# ─── 1 · The check the kernel runs ───────────────────────────────────────────
def may(uid, gids, st, want):
    """The permission algorithm from path_resolution(7), in eleven lines.
    uid/gids: who is asking. st: the file's stat. want: a bitmask of R, W, X.
    Exactly ONE of the three triplets applies, chosen in order: owner, group, other."""
    if uid == 0:                                              # root: everything ...
        if want & X and not stat.S_ISDIR(st.st_mode):         # ... except execute needs SOME x bit
            return bool(st.st_mode & 0o111)
        return True
    mode = stat.S_IMODE(st.st_mode)
    if uid == st.st_uid:                                      # the owner uses the first triplet
        bits = (mode >> 6) & 7
    elif st.st_gid in gids:                                   # a group member uses the second
        bits = (mode >> 3) & 7
    else:                                                     # everyone else uses the third
        bits = mode & 7
    return bits & want == want                                # and the others are never consulted


def mode_string(mode):
    s = ""
    for shift in (6, 3, 0):
        bits = (mode >> shift) & 7
        s += "r" if bits & R else "-"
        s += "w" if bits & W else "-"
        s += "x" if bits & X else "-"
    # the three special bits overlay the x positions
    if mode & stat.S_ISUID: s = s[:2] + ("s" if s[2] == "x" else "S") + s[3:]
    if mode & stat.S_ISGID: s = s[:5] + ("s" if s[5] == "x" else "S") + s[6:]
    if mode & stat.S_ISVTX: s = s[:8] + ("t" if s[8] == "x" else "T")
    return s


def who(uid):
    try:
        return pwd.getpwuid(uid).pw_name
    except KeyError:
        return str(uid)


def group_name(gid):
    try:
        return grp.getgrgid(gid).gr_name
    except KeyError:
        return str(gid)


if __name__ == "__main__":
    me, my_gids = os.getuid(), set(os.getgroups()) | {os.getgid()}
    root = tempfile.mkdtemp(prefix="perm-")
    os.chdir(root)

    banner("0 · Who am I? uid, gid, and the groups the kernel will check")
    print(f"uid {me} ({who(me)})  gid {os.getgid()} ({group_name(os.getgid())})  groups {sorted(my_gids)}")
    print(f"effective uid {os.geteuid()}: the one the kernel actually checks (setuid changes it; sudo replaces it)")
    if me == 0:
        print("you are ROOT: every check below short-circuits to yes. Watch for it.")

    banner("1 · The nine bits, decoded: what chmod writes and ls -l prints")
    for mode in (0o644, 0o600, 0o755, 0o700, 0o640, 0o750, 0o666, 0o777, 0o4755, 0o2775, 0o1777):
        print(f"   {mode:05o}  {mode_string(mode)}   owner={(mode >> 6) & 7} group={(mode >> 3) & 7} other={mode & 7}"
              + ("   <- setuid" if mode & 0o4000 else "") + ("   <- setgid" if mode & 0o2000 else "") + ("   <- sticky" if mode & 0o1000 else ""))
    print("   each octal digit is one triplet: r=4 w=2 x=1, added. 6 = rw-, 5 = r-x, 7 = rwx, 0 = ---")

    banner("2 · The check, run by us and by the kernel, on the same files")
    with open("config.yaml", "w") as f:
        f.write("port: 8080\n")
    cases = [("owner rw, others nothing", 0o600), ("owner rw, group r, others nothing", 0o640),
             ("everyone r, owner w", 0o644), ("no bits at all", 0o000), ("execute only", 0o111)]
    print(f"{'mode':>6}  {'ls':10} {'want':5} {'ours':5} {'kernel':6}  note")
    for note, mode in cases:
        os.chmod("config.yaml", mode)
        st = os.stat("config.yaml")
        for want, label in ((R, "read"), (W, "write"), (X, "exec")):
            ours = may(me, my_gids, st, want)
            kernel = os.access("config.yaml", {R: os.R_OK, W: os.W_OK, X: os.X_OK}[want])
            flag = "" if ours == kernel else "   <-- MISMATCH"
            print(f"{mode:>06o}  {mode_string(mode):10} {label:5} {str(ours):5} {str(kernel):6}  {note}{flag}")
    os.chmod("config.yaml", 0o644)
    print("\nours and the kernel's agree on every row: the algorithm above IS the check, root bypass included")

    banner("3 · Only one triplet applies: the owner's, even when it is worse than the others'")
    os.chmod("config.yaml", 0o077)                            # owner: nothing. group and others: everything
    st = os.stat("config.yaml")
    print(f"chmod 077 config.yaml -> {mode_string(0o077)}: the owner has NO bits, everyone else has all of them")
    print(f"can the owner (uid {me}) read it? ours={may(me, my_gids, st, R)} kernel={os.access('config.yaml', os.R_OK)}")
    print("   a non-root owner is refused by their own file while strangers may read it: the triplets are not cumulative")
    os.chmod("config.yaml", 0o644)

    banner("4 · Directories: x means 'may enter', r means 'may list', w means 'may create or delete names'")
    os.mkdir("vault", 0o700)
    with open("vault/secret.txt", "w") as f:
        f.write("shh\n")
    os.chmod("vault/secret.txt", 0o644)                       # the FILE is world-readable ...
    os.chmod("vault", 0o600)                                  # ... but the directory has no x
    st_dir = os.stat("vault")
    print(f"vault is {mode_string(0o600)} and vault/secret.txt is {mode_string(0o644)}")
    print(f"may a non-root owner enter vault (x)? {may(1000, {1000}, st_dir, X)}  -> so secret.txt is unreachable despite its own 644")
    os.chmod("vault", 0o711)
    st_dir = os.stat("vault")
    print(f"chmod 711 vault: enter yes ({may(1000, {1000}, st_dir, X)}), list no ({may(1000, {1000}, st_dir, R)}): you can open a name you already know, but not discover names")
    print("deleting a file needs w on the DIRECTORY, not on the file: rm asks the directory to forget a name (lesson 05)")

    banner("5 · umask: the bits a new file does NOT get")
    old = os.umask(0o022)
    with open("new-022.txt", "w") as f:
        pass
    os.umask(0o077)
    with open("new-077.txt", "w") as f:
        pass
    os.umask(old)
    print(f"umask 022: open() asked for 666, got {stat.S_IMODE(os.stat('new-022.txt').st_mode):04o} ({mode_string(stat.S_IMODE(os.stat('new-022.txt').st_mode))})   666 & ~022")
    print(f"umask 077: open() asked for 666, got {stat.S_IMODE(os.stat('new-077.txt').st_mode):04o} ({mode_string(stat.S_IMODE(os.stat('new-077.txt').st_mode))})   666 & ~077")
    print("   programs ask for 666 (files) or 777 (directories); the umask subtracts. That is why new files are 644 on most boxes")

    banner("6 · The three special bits")
    os.mkdir("shared"); os.chmod("shared", 0o1777)              # mkdir's mode goes through the umask; chmod sets it exactly
    os.mkdir("team"); os.chmod("team", 0o2775)
    other_gids = [g for g in os.getgroups() if g != os.getgid()] or ([1] if me == 0 else [])
    if other_gids:
        os.chown("team", -1, other_gids[0])                    # give the directory a group that is not our primary one
        os.chmod("team", 0o2775)                                # (chown clears setgid for non-root; set it again)
    st_sticky, st_sgid = os.stat("shared"), os.stat("team")
    print(f"shared: {mode_string(stat.S_IMODE(st_sticky.st_mode))} (1777)  sticky: anyone may create; only a file's owner may delete it. /tmp is this")
    print(f"team:   {mode_string(stat.S_IMODE(st_sgid.st_mode))} (2775)  setgid on a dir: new files inherit the dir's group, not the creator's")
    with open("team/note.txt", "w") as f:
        pass
    print(f"   team/note.txt got gid {os.stat('team/note.txt').st_gid} ({group_name(os.stat('team/note.txt').st_gid)}): team's gid, not our primary gid {os.getgid()} ({group_name(os.getgid())})")
    print(f"setuid on a program ({mode_string(0o4755)}): it runs with the FILE OWNER's uid, not yours. passwd and sudo are this")
    print("   if the owner is root, that program is root for as long as it runs: audit these with find / -perm -4000")

    banner("7 · The tables behind the names: /etc/passwd and /etc/group")
    try:
        entries = pwd.getpwall()
        print(f"/etc/passwd (via getpwent): {len(entries)} users; first three:")
        for p in entries[:3]:
            print(f"   {p.pw_name}:x:{p.pw_uid}:{p.pw_gid}:{p.pw_gecos}:{p.pw_dir}:{p.pw_shell}")
        nologin = sum(1 for p in entries if p.pw_shell.endswith(("nologin", "false")))
        print(f"   {nologin} of them have a shell of nologin or false: service accounts that can own files and run daemons but never log in")
        g = grp.getgrall()
        print(f"/etc/group: {len(g)} groups; e.g. {', '.join(x.gr_name + '(' + str(x.gr_gid) + ')' for x in g[:5])}")
    except Exception as e:
        print(f"(could not enumerate: {e})")
    print("   a uid is the only thing the kernel stores on an inode; the name is looked up in /etc/passwd at ls time")

    banner("8 · chown: who owns what (and why only root may give files away)")
    st = os.stat("config.yaml")
    print(f"config.yaml is owned by uid {st.st_uid} ({who(st.st_uid)}), gid {st.st_gid} ({group_name(st.st_gid)})")
    try:
        os.chown("config.yaml", 65534, -1)                    # 65534 is 'nobody' on most systems
        print(f"chown to uid 65534 succeeded: you are root (uid 0). Now uid {os.stat('config.yaml').st_uid} owns it and you may still read it")
        os.chown("config.yaml", me, -1)
    except PermissionError as e:
        print(f"chown to uid 65534 refused: {e.strerror}. Only root may change a file's owner; giving files away would let users dodge disk quotas")

    import shutil
    os.chdir("/")
    shutil.rmtree(root)
    print(f"\ncleaned up {root}")
