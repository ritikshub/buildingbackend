# Users, Permissions & sudo

> In lesson 01, `chmod 000` did nothing to stop you, because you were root. This lesson is the eleven-line function inside the kernel that made that decision, rebuilt in Python and checked row by row against the real one, and then the practice that follows from it: a service gets a user of its own, reads config it cannot write, writes only where it owns, and the humans who operate it get `sudo` for exactly the commands their job needs. Measured on the sandbox: one file, three identities, three different answers; and a process with uid 1000 binding port 80 because it was handed one slice of root instead of all of it.

## The Problem

Every `Permission denied` you will ever see comes from one place. Not from the shell, not from the program, not from a policy file: from a small function in the kernel that runs at the end of `open`, `execve`, `unlink`, `chdir`, `bind` and every other syscall that touches something. It compares who is asking with what the file says, and answers yes or no. Programs then relay the no as `EACCES` (lesson 01).

Most people learn permissions as a table of `chmod` numbers to memorise. That is backwards. Learn the check, and the numbers become obvious, the "why can't I delete a file I own" puzzles resolve themselves, and the security posture of a server stops being a checklist you follow and becomes a shape you can see. The shape is: **nothing runs as root that does not have to, and everything else is a user who can reach exactly its own files.** The sandbox has been hiding this from you by making you root. This lesson turns that off.

## The Concept

### Identity: what the kernel knows about a process

The kernel does not know your name. A process carries three numbers: a **uid** (user id), a **gid** (primary group id), and a list of **supplementary groups**. `id` prints them:

```console
$ id
uid=1000(dev) gid=1000(dev) groups=1000(dev),999(app)
```

The names in parentheses are decoration, looked up at print time from two text files. `/etc/passwd` maps each user to its uid, primary gid, home directory and login shell:

```text
root:x:0:0:root:/root:/bin/bash
daemon:x:1:1:daemon:/usr/sbin:/usr/sbin/nologin
app:x:999:999::/var/lib/app:/usr/sbin/nologin
dev:x:1000:1000::/home/dev:/bin/bash
```

Seven colon-separated fields: name, password placeholder, uid, gid, description, home, shell. The `x` means the password hash lives in `/etc/shadow`, which is readable only by root and the `shadow` group; `/etc/passwd` itself is world-readable, because every `ls -l` needs it to turn uids into names. `/etc/group` maps group names to gids and lists their members. Two conventions matter: uids below 1000 are **system accounts** (services), 1000 and up are people; and a shell of `/usr/sbin/nologin` means the account exists to **own files and run a daemon**, never to log in. The sandbox's fresh Debian image has 19 users, and 17 of them are of that kind.

An inode stores only the numbers. `chown 4242:4242 file` works even though no user 4242 exists, and `ls -l` then prints the raw numbers. Move a disk or a volume to another machine and the files still say `1000`, whoever that is over there. That is why service uids are pinned when volumes are shared, and why "the files on the volume are owned by the wrong user" is a Phase 11 problem with a lesson 06 cause.

### The nine bits, and the check that reads them

Every inode has a mode: three triplets of `rwx`, for the **owner**, the **group**, and **everyone else**, in that order. `ls -l` prints them as nine characters; `chmod` takes them as three octal digits, one per triplet, where `r` is 4, `w` is 2, `x` is 1, added together:

| octal | letters | meaning | used for |
|---|---|---|---|
| `644` | `rw-r--r--` | owner writes, everyone reads | ordinary files, public config |
| `600` | `rw-------` | owner only | private keys, `~/.ssh/id_ed25519`, secrets |
| `640` | `rw-r-----` | owner writes, group reads | config with secrets shared with a service group |
| `755` | `rwxr-xr-x` | everyone may run or enter, owner may change | programs, most directories |
| `750` | `rwxr-x---` | group may enter, others may not | a service's data and log directories |
| `700` | `rwx------` | owner only | home directories, `~/.ssh` |
| `777` | `rwxrwxrwx` | everyone may do anything | almost never right; a sign someone gave up |

Here is the check, from `path_resolution(7)` and the kernel's `generic_permission()`, as the script implements it:

```python
def may(uid, gids, st, want):
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
```

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 520" width="100%" style="max-width:880px" role="img" aria-label="The kernel's permission check as a flowchart. Inputs on the left: the process's credentials, uid 1000, gid 1000, supplementary groups 999; and on the right the inode's fields, owner uid 0, group gid 999, mode 640 shown as rw- r-- ---. Step one: is the effective uid zero? If yes, allow, with the footnote that execute still requires some x bit on a regular file. Step two: does uid equal the file's owner? If yes, use the first triplet and stop. Step three: is the file's gid in the process's groups? If yes, use the second triplet and stop. Otherwise use the third triplet. Final step: does the chosen triplet contain every requested bit? Yes means proceed; no means EACCES. Three worked rows below: root reading secrets.env, allowed by the bypass; app, uid 999 whose primary group is 999, reading it, allowed by the group triplet r; nobody, uid 65534, denied because the third triplet is empty. A note stresses that exactly one triplet is consulted, so an owner with mode 077 cannot read their own file while strangers can.">
  <defs>
    <marker id="p1l06a-ar" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker>
    <marker id="p1l06a-arg" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#0fa07f"/></marker>
    <marker id="p1l06a-ard" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#d64545"/></marker>
  </defs>
  <text x="450" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">The check: pick ONE triplet by who you are, then compare bits. Root skips it.</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <!-- inputs -->
    <rect x="40" y="48" width="250" height="70" rx="9" fill="#7c5cff" fill-opacity="0.10" stroke="#7c5cff" stroke-width="1.7" stroke-linejoin="round"/>
    <text x="165" y="68" text-anchor="middle" font-size="10" font-weight="700" fill="#7c5cff">THE PROCESS (credentials)</text>
    <text x="165" y="86" text-anchor="middle" font-size="9" fill="currentColor">uid 1000 · gid 1000 · groups {1000, 999}</text>
    <text x="165" y="102" text-anchor="middle" font-size="8" fill="currentColor" opacity="0.75">effective uid: what setuid and sudo change</text>
    <rect x="610" y="48" width="250" height="70" rx="9" fill="#e0930f" fill-opacity="0.10" stroke="#e0930f" stroke-width="1.7" stroke-linejoin="round"/>
    <text x="735" y="68" text-anchor="middle" font-size="10" font-weight="700" fill="#e0930f">THE INODE (/etc/app/secrets.env)</text>
    <text x="735" y="86" text-anchor="middle" font-size="9" fill="currentColor">owner uid 0 · group gid 999 · mode 640</text>
    <text x="735" y="102" text-anchor="middle" font-size="8" fill="currentColor" opacity="0.75">rw- r-- ---  = owner 6, group 4, other 0</text>
    <rect x="330" y="48" width="240" height="70" rx="9" fill="#7f7f7f" fill-opacity="0.12" stroke="#7f7f7f" stroke-width="1.7" stroke-linejoin="round"/>
    <text x="450" y="68" text-anchor="middle" font-size="10" font-weight="700" fill="currentColor">THE REQUEST</text>
    <text x="450" y="86" text-anchor="middle" font-size="9" fill="currentColor">open(..., O_RDONLY) wants R</text>
    <text x="450" y="102" text-anchor="middle" font-size="8" fill="currentColor" opacity="0.75">write wants W; execve and chdir want X</text>

    <!-- steps -->
    <g fill="none" stroke-linejoin="round" stroke-width="1.7">
      <rect x="250" y="140" width="400" height="40" rx="9" fill="#d64545" fill-opacity="0.08" stroke="#d64545"/>
      <rect x="250" y="200" width="400" height="40" rx="9" fill="#7f7f7f" fill-opacity="0.12" stroke="#7f7f7f"/>
      <rect x="250" y="260" width="400" height="40" rx="9" fill="#7f7f7f" fill-opacity="0.12" stroke="#7f7f7f"/>
      <rect x="250" y="320" width="400" height="40" rx="9" fill="#7f7f7f" fill-opacity="0.12" stroke="#7f7f7f"/>
      <rect x="250" y="380" width="400" height="40" rx="9" fill="#0fa07f" fill-opacity="0.12" stroke="#0fa07f" stroke-width="2"/>
    </g>
    <g text-anchor="middle" font-size="9.5" fill="currentColor">
      <text x="450" y="158" font-weight="700" fill="#d64545">1 · is the effective uid 0?</text>
      <text x="450" y="172" font-size="8" opacity="0.8">yes → ALLOW (execute on a regular file still needs some x bit) · no → continue</text>
      <text x="450" y="218" font-weight="700">2 · uid == the inode's owner?</text>
      <text x="450" y="232" font-size="8" opacity="0.8">yes → use the FIRST triplet, stop looking</text>
      <text x="450" y="278" font-weight="700">3 · the inode's gid in the process's groups?</text>
      <text x="450" y="292" font-size="8" opacity="0.8">yes → use the SECOND triplet, stop looking</text>
      <text x="450" y="338" font-weight="700">4 · otherwise: use the THIRD triplet</text>
      <text x="450" y="352" font-size="8" opacity="0.8">"other" means "not the owner and not in the group"</text>
      <text x="450" y="398" font-weight="700" fill="#0fa07f">5 · (triplet &amp; wanted) == wanted ?</text>
      <text x="450" y="412" font-size="8" opacity="0.8">yes → proceed · no → return -EACCES, which becomes "Permission denied"</text>
    </g>
    <g fill="none" stroke="currentColor" stroke-width="1.5">
      <path d="M450 120 L450 136" marker-end="url(#p1l06a-ar)"/>
      <path d="M450 182 L450 196" marker-end="url(#p1l06a-ar)"/>
      <path d="M450 242 L450 256" marker-end="url(#p1l06a-ar)"/>
      <path d="M450 302 L450 316" marker-end="url(#p1l06a-ar)"/>
      <path d="M450 362 L450 376" marker-end="url(#p1l06a-ar)"/>
    </g>
    <path d="M652 220 L700 220 L700 396 L654 396" fill="none" stroke="#0fa07f" stroke-width="1.5" marker-end="url(#p1l06a-arg)"/>
    <path d="M652 280 L720 280 L720 400 L654 400" fill="none" stroke="#0fa07f" stroke-width="1.5" marker-end="url(#p1l06a-arg)"/>
    <text x="760" y="300" font-size="8" fill="#0fa07f">one triplet chosen;</text>
    <text x="760" y="312" font-size="8" fill="#0fa07f">the others never read</text>

    <!-- worked rows -->
    <g font-size="8.5" fill="currentColor">
      <text x="40" y="450" font-weight="700" fill="#0fa07f">root (uid 0) reads secrets.env:</text><text x="280" y="450">step 1 → allowed. It did not look at the mode at all.</text>
      <text x="40" y="468" font-weight="700" fill="#0fa07f">app (uid 999, gid 999):</text><text x="280" y="468">not owner; gid 999 matches → second triplet r-- has R → allowed.</text>
      <text x="40" y="486" font-weight="700" fill="#d64545">nobody (uid 65534):</text><text x="280" y="486">not owner, not in group → third triplet --- lacks R → EACCES.</text>
      <text x="40" y="506" opacity="0.8">chmod 077 on your own file: step 2 picks the owner triplet ---, and you are denied while everyone else is allowed. Triplets do not add up.</text>
    </g>
  </g>
</svg>
```

Three facts fall out of the code that no table of numbers teaches:

- **Exactly one triplet is consulted**, chosen by who you are, and the others are never read. A file with mode `077` (owner nothing, everyone else everything) cannot be read by its owner, while any stranger can read it. The script proves it; so does the kernel.
- **Root skips the check.** Uid 0 is allowed everything, with one exception: executing a regular file still requires *some* execute bit to be set, so that `chmod 000` on a program stops even root from running it by accident. That is why lesson 01's `chmod 000` did not stop you and why "it works as root" proves nothing about permissions.
- **The effective uid is what is checked.** Normally it equals your uid. A **setuid** program (below) runs with the file owner's uid instead, and `sudo` replaces your uid entirely. That single knob is how a normal user changes their password, which requires writing `/etc/shadow`.

### chmod: the two ways to say it

Numeric form sets all nine bits at once: `chmod 640 file`. Symbolic form changes some: `u`, `g`, `o`, `a` (all) plus `+`, `-` or `=` plus `r`, `w`, `x`. The sandbox, one line at a time:

```console
$ touch f;  chmod 644 f;   ls -l f       -rw-r--r--
$ chmod u+x f;             ls -l f       -rwxr--r--      <- add x for the owner
$ chmod go-r f;            ls -l f       -rwx------      <- remove r from group and others
$ chmod a=r f;             ls -l f       -r--r--r--      <- set everyone to exactly r
$ chmod +x f;              ls -l f       -r-xr-xr-x      <- +x with no who means all, filtered by umask
$ chmod -R g+w /var/log/app                              <- recurse
```

`chmod -R 755` on a directory of data is the common mistake: it makes every data file executable, which is harmless to the kernel and alarming to every security scanner. Fix a tree with `find ... -type d -exec chmod 750 {} +` and `find ... -type f -exec chmod 640 {} +`, or use `chmod -R u=rwX,g=rX,o=` where the capital `X` means "x only for directories and files that already have it."

### Directories: x is enter, r is list, w is create and delete

The same three bits mean something different on a directory, and this is where "but I own the file" confusion comes from:

- **`x` on a directory is permission to enter it**, that is, to look up a name inside it. Every component of a path needs `x` for the path to resolve at all: `/etc/app/secrets.env` needs `x` on `/`, `/etc` and `/etc/app`.
- **`r` is permission to list it**, to read the table of names. With `x` and no `r` you may open a file whose name you already know but you cannot discover names: `chmod 711` is how a home directory can hold a public `~/public_html` without exposing the rest.
- **`w` is permission to create or delete names in it.** Deleting a file is `unlink`, which edits the *directory*, so `rm` needs `w` on the directory and does not care about the file's own bits. A `777` file inside a `755` directory owned by root cannot be deleted by you. Conversely, you can delete a root-owned `600` file from a directory you own.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 400" width="100%" style="max-width:880px" role="img" aria-label="Two panels. Top: the path /etc/app/secrets.env resolved component by component for uid 999 in group 999. Root directory, mode 755, other triplet r-x, needs x: yes. etc, mode 755, needs x: yes. app, mode 750 owned by root with group app, group triplet r-x, needs x: yes. secrets.env, mode 640, group triplet r--, open for reading needs r: yes. The same walk for uid 65534: it fails at app because the third triplet is --- and has no x, so the file's own bits are never even examined. Bottom: three operations on the directory shared, mode 1777 sticky: creating a file needs w on the directory; deleting needs w on the directory plus, under the sticky bit, ownership of the file; listing needs r; and a file's own 777 mode does not help delete it, because unlink edits the directory, not the file.">
  <defs>
    <marker id="p1l06b-ar" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker>
    <marker id="p1l06b-arg" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#0fa07f"/></marker>
    <marker id="p1l06b-ard" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#d64545"/></marker>
  </defs>
  <text x="450" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">A path is checked one component at a time; x on every directory, then the file's own bit</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <!-- path walk -->
    <g stroke-linejoin="round" stroke-width="1.6">
      <rect x="40"  y="56" width="150" height="70" rx="9" fill="#7c5cff" fill-opacity="0.10" stroke="#7c5cff"/>
      <rect x="230" y="56" width="150" height="70" rx="9" fill="#7c5cff" fill-opacity="0.10" stroke="#7c5cff"/>
      <rect x="420" y="56" width="150" height="70" rx="9" fill="#7c5cff" fill-opacity="0.10" stroke="#7c5cff"/>
      <rect x="610" y="56" width="180" height="70" rx="9" fill="#e0930f" fill-opacity="0.12" stroke="#e0930f"/>
    </g>
    <g text-anchor="middle" fill="currentColor">
      <text x="115" y="76" font-size="10.5" font-weight="700" fill="#7c5cff">/</text>
      <text x="115" y="92" font-size="8.5">755 root:root</text>
      <text x="115" y="106" font-size="8.5">needs x to enter</text>
      <text x="305" y="76" font-size="10.5" font-weight="700" fill="#7c5cff">etc</text>
      <text x="305" y="92" font-size="8.5">755 root:root</text>
      <text x="305" y="106" font-size="8.5">needs x to enter</text>
      <text x="495" y="76" font-size="10.5" font-weight="700" fill="#7c5cff">app</text>
      <text x="495" y="92" font-size="8.5">750 root:app</text>
      <text x="495" y="106" font-size="8.5">needs x to enter</text>
      <text x="700" y="76" font-size="10.5" font-weight="700" fill="#e0930f">secrets.env</text>
      <text x="700" y="92" font-size="8.5">640 root:app</text>
      <text x="700" y="106" font-size="8.5">open(O_RDONLY) needs r</text>
    </g>
    <g fill="none" stroke="currentColor" stroke-width="1.5">
      <path d="M192 91 L226 91" marker-end="url(#p1l06b-ar)"/>
      <path d="M382 91 L416 91" marker-end="url(#p1l06b-ar)"/>
      <path d="M572 91 L606 91" marker-end="url(#p1l06b-ar)"/>
    </g>
    <!-- two identities -->
    <g font-size="8.5">
      <text x="40" y="152" font-weight="700" fill="#0fa07f">app · uid 999, group 999</text>
      <text x="115" y="170" text-anchor="middle" fill="#0fa07f">other r-x → x ✓</text>
      <text x="305" y="170" text-anchor="middle" fill="#0fa07f">other r-x → x ✓</text>
      <text x="495" y="170" text-anchor="middle" fill="#0fa07f">group r-x → x ✓</text>
      <text x="700" y="170" text-anchor="middle" fill="#0fa07f">group r-- → r ✓ · opened</text>
      <text x="40" y="200" font-weight="700" fill="#d64545">nobody · uid 65534</text>
      <text x="115" y="218" text-anchor="middle" fill="#0fa07f">other r-x → x ✓</text>
      <text x="305" y="218" text-anchor="middle" fill="#0fa07f">other r-x → x ✓</text>
      <text x="495" y="218" text-anchor="middle" fill="#d64545">other --- → no x ✗ EACCES</text>
      <text x="700" y="218" text-anchor="middle" fill="currentColor" opacity="0.6">never examined</text>
    </g>
    <text x="450" y="246" text-anchor="middle" font-size="8.5" fill="currentColor" opacity="0.85">"Permission denied" on a file you can see in ls is usually a missing x on a directory above it, not the file's bits.</text>

    <!-- directory operations -->
    <rect x="40" y="266" width="820" height="100" rx="10" fill="#7f7f7f" fill-opacity="0.10" stroke="#7f7f7f" stroke-width="1.6" stroke-linejoin="round"/>
    <text x="450" y="286" text-anchor="middle" font-size="10" font-weight="700" fill="currentColor">ON A DIRECTORY, THE BITS MEAN: r = list names · w = add or remove names · x = enter, look up a known name</text>
    <g font-size="8.5" fill="currentColor">
      <text x="56" y="308">touch shared/new      → needs w+x on shared (a new name goes into the table)</text>
      <text x="56" y="324">rm shared/theirs      → needs w+x on shared; the FILE's mode is irrelevant, even 777. unlink edits the directory</text>
      <text x="56" y="340">ls shared             → needs r (and x to see modes); with x but no r: cat shared/known works, ls does not</text>
      <text x="56" y="356">shared is 1777 (sticky, like /tmp) → w for everyone, but delete also requires owning the file. Shared scratch, safely</text>
    </g>
  </g>
  <text x="450" y="390" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="10.5" fill="currentColor" opacity="0.9">Enter needs x. Read needs r. Create and delete need w on the directory. Every path component is checked before the file is.</text>
</svg>
```

### umask: the bits a new file does not get

Programs create files by asking for `666` and directories by asking for `777`, and the process's **umask** subtracts. With the usual `022`, that yields `644` and `755`; with `077`, `600` and `700`. The sandbox, in one shell and a subshell:

```console
$ umask;  umask -S
0022
u=rwx,g=rx,o=rx
$ touch u1;  mkdir d1;  ls -ld u1 d1
-rw-r--r-- 1 root root 0 Sep  5 03:59 u1
drwxr-xr-x 1 root root 0 Sep  5 03:59 d1
$ (umask 077;  touch u2;  mkdir d2;  ls -ld u2 d2)
-rw------- 1 root root 0 Sep  5 03:59 u2
drwx------ 1 root root 0 Sep  5 03:59 d2
```

The umask is per process and inherited at fork, so a service's is set in its unit (`UMask=027`, giving `640` files and `750` directories) rather than trusted to every code path. When a service creates world-readable files it should not, the umask is the first suspect.

### The three special bits

Three more bits sit above the nine, shown in the `x` positions of `ls -l` and as a fourth leading octal digit:

- **setuid** (`4000`, `s` in the owner's x): a program with this bit runs with the **file owner's** uid, not the caller's. `/usr/bin/passwd` is `-rwsr-xr-x root`, so any user runs it as root for exactly as long as it takes to update `/etc/shadow`. So is `sudo`, so is `su`. A setuid-root binary is a root shell waiting for a bug; the sandbox has ten of them, and `find / -xdev -perm -4000 -type f` should always return a list you recognise.
- **setgid** (`2000`, `s` in the group's x): on a program, run with the file's gid. On a **directory**, more useful: files created inside inherit the directory's group instead of the creator's primary group, which is how a team or a service group shares a tree without everyone remembering `chgrp`. The script shows `team/note.txt` getting gid 999 (`app`) rather than the creator's gid 1000.
- **sticky** (`1000`, `t` in the others' x): on a directory, anyone with `w` may create files but only a file's owner may delete or rename it. `/tmp` is `drwxrwxrwt` for this reason; without it, any user could delete any other user's temp files.

### Root, sudo, and the pieces of root

**Root is uid 0**, and the kernel skips the check for it. That is the whole definition, and it is why nothing that faces the network should run as root: a bug in a root process is a bug with no permission check between it and every file, every socket, every other process on the box.

**`sudo`** is a setuid-root program with a policy file. When `dev` runs `sudo systemctl restart app`, `sudo` starts as root (the setuid bit), reads `/etc/sudoers` and `/etc/sudoers.d/*`, and if a rule allows this user this command, runs it with uid 0. The policy is a text file with its own syntax, checked with `visudo -c` (a syntax error in sudoers locks everyone out of root at once), and `sudo -l` shows a user what they may do:

```text
dev ALL=(ALL) NOPASSWD: /usr/bin/journalctl, /usr/bin/id
dev ALL=(app) NOPASSWD: ALL
```

The first line: on any host (`ALL`), `dev` may run those two programs as any user (`(ALL)`) without a password. The second: `dev` may run anything **as the `app` user**, which is how an operator inspects a service's files without becoming root: `sudo -u app -s`. `sudo` also resets the environment (`env_reset`) and replaces `PATH` with `secure_path`, which is why a command that works for you fails under `sudo` with "command not found" (lesson 03's runbook).

Between "a normal user" and "root" Linux has a finer scale: **capabilities**, about forty named slices of what root can do. `CAP_NET_BIND_SERVICE` is the right to bind a port below 1024. `CAP_CHOWN` is the right to give files away. `CAP_SYS_ADMIN` is most of the rest. A file or a process can hold some of them without uid 0:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 430" width="100%" style="max-width:880px" role="img" aria-label="A ladder of privilege from left to right. A normal user, uid 1000: only their own files, only ports above 1023. A service user, uid 999, nologin: its own /var/lib and /var/log directories, its config via a group, nothing else. A service user with one capability, CAP_NET_BIND_SERVICE, granted through setcap on the binary or AmbientCapabilities in its unit: the same, plus port 80, and it is still uid 1000 or 999, so the permission check still applies to every file. A setuid-root program such as passwd or sudo: root for the duration of one program, with a policy file in the case of sudo. Root, uid 0: the check is skipped entirely. A caption says that every step to the right should be a documented decision, that services belong in the second or third column, that humans reach root only through sudo with a specific command list, and that the container in Phase 11 is itself a process holding a reduced capability set.">
  <defs>
    <marker id="p1l06c-ar" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker>
  </defs>
  <text x="450" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">The ladder of privilege: every step to the right is a decision someone should have written down</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <path d="M40 330 L860 330" fill="none" stroke="currentColor" stroke-width="1.6" marker-end="url(#p1l06c-ar)"/>
    <text x="450" y="348" text-anchor="middle" font-size="8.5" fill="currentColor" opacity="0.8">more power, less protection</text>
    <g stroke-linejoin="round" stroke-width="1.7">
      <rect x="40"  y="56" width="150" height="250" rx="10" fill="#0fa07f" fill-opacity="0.10" stroke="#0fa07f"/>
      <rect x="210" y="56" width="150" height="250" rx="10" fill="#0fa07f" fill-opacity="0.12" stroke="#0fa07f" stroke-width="2.2"/>
      <rect x="380" y="56" width="150" height="250" rx="10" fill="#e0930f" fill-opacity="0.12" stroke="#e0930f"/>
      <rect x="550" y="56" width="150" height="250" rx="10" fill="#c94a12" fill-opacity="0.12" stroke="#c94a12"/>
      <rect x="720" y="56" width="140" height="250" rx="10" fill="#d64545" fill-opacity="0.10" stroke="#d64545"/>
    </g>
    <g text-anchor="middle" font-size="8.5" fill="currentColor">
      <text x="115" y="78" font-size="10" font-weight="700" fill="#0fa07f">A PERSON</text>
      <text x="115" y="92" opacity="0.75">uid 1000, a shell, a key</text>
      <text x="115" y="116">their own files</text>
      <text x="115" y="130">ports above 1023</text>
      <text x="115" y="144">group-shared files</text>
      <text x="115" y="170" opacity="0.8">reaches root only via</text>
      <text x="115" y="184" opacity="0.8">sudo, with a command</text>
      <text x="115" y="198" opacity="0.8">list, logged</text>
      <text x="115" y="230" font-weight="700">where operators live</text>

      <text x="285" y="78" font-size="10" font-weight="700" fill="#0fa07f">A SERVICE USER</text>
      <text x="285" y="92" opacity="0.75">uid 999, nologin, no password</text>
      <text x="285" y="116">/var/lib/app, /var/log/app</text>
      <text x="285" y="130">config via group app</text>
      <text x="285" y="144">nothing else on the box</text>
      <text x="285" y="170" opacity="0.8">a bug reaches only</text>
      <text x="285" y="184" opacity="0.8">what this uid owns</text>
      <text x="285" y="230" font-weight="700">where services live</text>
      <text x="285" y="244" font-weight="700">(User= in the unit)</text>

      <text x="455" y="78" font-size="10" font-weight="700" fill="#e0930f">+ ONE CAPABILITY</text>
      <text x="455" y="92" opacity="0.75">still uid 999</text>
      <text x="455" y="116">CAP_NET_BIND_SERVICE:</text>
      <text x="455" y="130">may bind port 80 or 443</text>
      <text x="455" y="144">every file check still applies</text>
      <text x="455" y="170" opacity="0.8">setcap on the binary, or</text>
      <text x="455" y="184" opacity="0.8">AmbientCapabilities= in</text>
      <text x="455" y="198" opacity="0.8">the unit (lesson 11)</text>
      <text x="455" y="230" font-weight="700">when a service "needs"</text>
      <text x="455" y="244" font-weight="700">root for a port number</text>

      <text x="625" y="78" font-size="10" font-weight="700" fill="#c94a12">A SETUID-ROOT PROGRAM</text>
      <text x="625" y="92" opacity="0.75">passwd, su, sudo, mount</text>
      <text x="625" y="116">root for the life of</text>
      <text x="625" y="130">one program</text>
      <text x="625" y="144">sudo adds a policy file</text>
      <text x="625" y="170" opacity="0.8">every one is a root shell</text>
      <text x="625" y="184" opacity="0.8">waiting for a bug:</text>
      <text x="625" y="198" opacity="0.8">find / -perm -4000</text>
      <text x="625" y="230" font-weight="700">keep the list short</text>
      <text x="625" y="244" font-weight="700">and known</text>

      <text x="790" y="78" font-size="10" font-weight="700" fill="#d64545">ROOT</text>
      <text x="790" y="92" opacity="0.75">uid 0</text>
      <text x="790" y="116">the check is skipped</text>
      <text x="790" y="130">every file, every</text>
      <text x="790" y="144">socket, every process</text>
      <text x="790" y="170" opacity="0.8">a bug here has no</text>
      <text x="790" y="184" opacity="0.8">permission check</text>
      <text x="790" y="198" opacity="0.8">between it and the box</text>
      <text x="790" y="230" font-weight="700">nothing that faces</text>
      <text x="790" y="244" font-weight="700">the network</text>
    </g>
  </g>
  <text x="450" y="380" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="10.5" fill="currentColor" opacity="0.9">Services in the second column, one capability at most. Humans in the first, with sudo. Root is a place you visit, not a place you run.</text>
  <text x="450" y="400" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="9.5" fill="currentColor" opacity="0.72">A container (Phase 11) is a process holding a reduced capability set: the sandbox's root has 14 of the 41, which is why some things in earlier lessons were refused.</text>
</svg>
```

The sandbox shows the capability alone doing the job: a uid-1000 process fails to bind port 80 with `EACCES`, and after `setcap 'cap_net_bind_service=+ep'` on the interpreter it succeeds, still as uid 1000. That is the answer to "the service needs root because it listens on 443": it does not, it needs one capability, or a reverse proxy in front (lesson 11 and Phase 11). And it is why some things were refused in lesson 02: the sandbox's "root" holds 14 of the 41 capabilities, so `dmesg` failed. A container is a process wearing a trimmed root.

### The service-user pattern

Put all of it together and you get the shape every well-run service has, which the **Use It** section builds by hand and lesson 11 will put under `systemd`:

- a **system user and group** with no password and no shell: `groupadd --system app; useradd --system --gid app --shell /usr/sbin/nologin app`;
- **config owned by root, readable by the group**: `/etc/app/secrets.env` is `root:app 640`, so the service reads it and cannot change it, and nobody outside the group reads it at all;
- **data and logs owned by the service**: `/var/lib/app` and `/var/log/app` are `app:app 750`, the only places it can write;
- **operators in the group**, or with `sudo -u app`, and a short `sudoers.d` file listing the exact commands they may run as root.

## Build It

The script for this lesson is [`code/permissions.py`](../code/permissions.py). It runs the check on files it creates and, for every row, asks the kernel the same question through `os.access` so you can see the two agree. Run it as yourself on your Mac, then in the sandbox as root and as a normal user, because the answers differ and the differences are the lesson:

```bash
python3 phases/01-linux-and-the-command-line/06-users-groups-permissions-and-sudo/code/permissions.py
make shell
python3 phases/01-linux-and-the-command-line/06-users-groups-permissions-and-sudo/code/permissions.py          # as root
useradd -m dev && su - dev -c 'python3 /workspace/phases/01-linux-and-the-command-line/06-users-groups-permissions-and-sudo/code/permissions.py'
```

**The check against the kernel.** Fifteen rows, five modes, three requests each, first as a normal user:

```console
  mode  ls         want  ours  kernel  note
000600  rw-------  read  True  True    owner rw, others nothing
000600  rw-------  exec  False False   owner rw, others nothing
000000  ---------  read  False False   no bits at all
000111  --x--x--x  read  False False   execute only
000111  --x--x--x  exec  True  True    execute only

ours and the kernel's agree on every row
```

Then as root, where the same rows flip, except one:

```console
000000  ---------  read  True  True    no bits at all
000000  ---------  write True  True    no bits at all
000000  ---------  exec  False False   no bits at all      <- root still needs an x bit to execute
```

**One triplet.** `chmod 077` on your own file, then ask to read it:

```console
chmod 077 config.yaml -> ---rwxrwx: the owner has NO bits, everyone else has all of them
can the owner (uid 1000) read it? ours=False kernel=False
```

**Directories, umask, the special bits.** A `600` directory hides a `644` file inside it; `711` lets you open a known name but not list; the umask turns a requested `666` into `644` or `600`; a setgid directory gives new files its group rather than yours:

```console
vault is rw------- and vault/secret.txt is rw-r--r--
may a non-root owner enter vault (x)? False  -> so secret.txt is unreachable despite its own 644
umask 022: open() asked for 666, got 0644 (rw-r--r--)   666 & ~022
umask 077: open() asked for 666, got 0600 (rw-------)   666 & ~077
team:   rwxrwsr-x (2775)  setgid on a dir: new files inherit the dir's group, not the creator's
   team/note.txt got gid 999 (app): team's gid, not our primary gid 1000 (dev)
```

**The tables and `chown`.** The script reads `/etc/passwd` through `getpwent`, counts the `nologin` accounts, and tries to give a file away: refused as a user with `Operation not permitted` (`EPERM`, the errno for "you would need root"), accepted as root. Only root may change a file's owner, because giving files away would let a user dodge disk quotas and plant files in someone else's name.

## Use It

The whole pattern, built by hand inside `make shell`, where you start as root. First the identities and the layout:

```console
$ groupadd --system app
$ useradd --system --gid app --home-dir /var/lib/app --shell /usr/sbin/nologin app
$ useradd -m -s /bin/bash -G app dev          # a human, who is also in the app group
$ id app;  id dev
uid=999(app) gid=999(app) groups=999(app)
uid=1000(dev) gid=1000(dev) groups=1000(dev),999(app)
$ mkdir -p /etc/app /var/lib/app /var/log/app
$ printf 'db_password=hunter2\n' > /etc/app/secrets.env
$ chown root:app /etc/app/secrets.env;  chmod 640 /etc/app/secrets.env
$ chown app:app /var/lib/app /var/log/app;  chmod 750 /var/lib/app /var/log/app
$ stat -c '%A %U:%G %n' /etc/app/secrets.env /var/lib/app
-rw-r----- root:app /etc/app/secrets.env
drwxr-x--- app:app /var/lib/app
```

Now the same file, read by four identities, and written by the one that should not be able to:

```console
$ cat /etc/app/secrets.env                                     # root
db_password=hunter2
$ su -s /bin/sh app -c 'cat /etc/app/secrets.env'              # the service, via the group triplet
db_password=hunter2
$ su -s /bin/sh dev -c 'cat /etc/app/secrets.env'              # an operator in the app group
db_password=hunter2
$ su -s /bin/sh nobody -c 'cat /etc/app/secrets.env'           # anyone else
cat: /etc/app/secrets.env: Permission denied
$ su -s /bin/sh app -c 'echo x >> /etc/app/secrets.env'        # the service, trying to write its config
sh: 1: cannot create /etc/app/secrets.env: Permission denied
$ su -s /bin/sh app -c 'touch /var/lib/app/data.db && echo yes'  # the service, writing where it owns
yes
```

That is the pattern in six lines: read config, cannot change it; write data, cannot reach anything else. Directories and the sticky bit behave exactly as the diagram says:

```console
$ mkdir -m 711 enter-only;  echo secret > enter-only/known.txt;  chmod 644 enter-only/known.txt
$ su -s /bin/sh nobody -c 'ls /tmp/enter-only'
ls: cannot open directory '/tmp/enter-only': Permission denied
$ su -s /bin/sh nobody -c 'cat /tmp/enter-only/known.txt'
secret
$ chmod 777 rdir/owned-by-root;  su -s /bin/sh nobody -c 'rm /tmp/rdir/owned-by-root'
rm: cannot remove '/tmp/rdir/owned-by-root': Permission denied     <- 777 on the file; no w on the directory
$ ls -ld /tmp;  su -s /bin/sh dev -c 'touch /tmp/devs-file';  su -s /bin/sh nobody -c 'rm /tmp/devs-file'
drwxrwxrwt 1 root root 46 Sep  5 03:59 /tmp
rm: cannot remove '/tmp/devs-file': Operation not permitted        <- the sticky bit
```

The setuid programs on a fresh image, each one a root escalation path that should be on a known list:

```console
$ find / -xdev -perm -4000 -type f 2>/dev/null
/usr/bin/chfn  /usr/bin/chsh  /usr/bin/gpasswd  /usr/bin/mount  /usr/bin/newgrp
/usr/bin/passwd  /usr/bin/su  /usr/bin/umount  /usr/lib/openssh/ssh-keysign
$ ls -l /usr/bin/passwd /usr/bin/sudo
-rwsr-xr-x 1 root root 142424 Apr 19  2025 /usr/bin/passwd
-rwsr-xr-x 1 root root 335168 Apr 11 12:21 /usr/bin/sudo
```

`sudo` itself, with a rule for the operator, validated, listed, and tested against something the rule does not cover:

```console
$ cat /etc/sudoers.d/dev
dev ALL=(ALL) NOPASSWD: /usr/bin/journalctl, /usr/bin/id
dev ALL=(app) NOPASSWD: ALL
$ chmod 440 /etc/sudoers.d/dev;  visudo -c
/etc/sudoers: parsed OK
/etc/sudoers.d/dev: parsed OK
$ su - dev -c 'sudo -l'
User dev may run the following commands on 3c0be1d4e17a:
    (ALL) NOPASSWD: /usr/bin/journalctl, /usr/bin/id
    (app) NOPASSWD: ALL
$ su - dev -c 'sudo -n /usr/bin/id'
uid=0(root) gid=0(root) groups=0(root)
$ su - dev -c 'sudo -n cat /etc/app/secrets.env'
sudo: a password is required                                  <- not in the list; no password set; refused
$ su - dev -c 'sudo -n -u app cat /etc/app/secrets.env'       <- allowed: as app, not as root
db_password=hunter2
$ grep secure_path /etc/sudoers
Defaults	secure_path="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
```

And the capability, doing the one thing people run services as root for:

```console
$ su - dev -c "python3 -c 'import socket; socket.socket().bind((\"0.0.0.0\", 80))'"
PermissionError: [Errno 13] Permission denied
$ setcap 'cap_net_bind_service=+ep' /usr/local/bin/python3.12;  getcap /usr/local/bin/python3.12
/usr/local/bin/python3.12 cap_net_bind_service=ep
$ su - dev -c "python3 -c 'import socket, os; socket.socket().bind((\"0.0.0.0\", 80)); print(\"bound port 80 as uid\", os.getuid())'"
bound port 80 as uid 1000
```

Same user, same port, one capability on the binary. (`setcap -r` removes it again; in practice you grant it in the unit file rather than on the interpreter, so that only that service gets it.)

## Ship It

The artifact for this lesson is a checklist: [`outputs/checklist-service-user-and-permissions.md`](../outputs/checklist-service-user-and-permissions.md). It is the pattern from this lesson applied to one service, as commands: the system user and group to create and why to pin the uid; a table of owner, group and mode for the binary, config, secrets, data, logs, socket and cache; the umask to set in the unit; the tests to run *as the service user* that prove it cannot write its own config or read another service's secrets; the `sudoers.d` rules that give operators exactly their commands; a monthly audit for setuid binaries, world-writable files, readable secrets and orphaned uids; and the five-step diagnosis for a `Permission denied` that starts with `id` in the failing context and ends with SELinux.

## Think about it

1. A service runs as `app` and logs `Permission denied` opening `/etc/app/app.yaml`, which is `root:app 640`. `id app` shows `groups=999(app)`. `ls -ld /etc/app` shows `drwx------ root root`. What is wrong, and why did the file's mode not matter?
2. Your teammate fixes a permission problem with `chmod -R 777 /var/lib/app`. It works. List three things that are now true that were not before, and the two commands that restore a correct tree.
3. `/tmp` is `1777`. A build system running as `ci` creates `/tmp/build.lock` and a cron job running as `app` needs to delete it when stale. Why does that fail, and what are two designs that do not?
4. A container runs its process as root but `dmesg` says `Operation not permitted`. Reconcile that with "root skips the check."

## Key takeaways

- A process is a **uid, a gid and a group list**; an inode is an **owner uid, a group gid and nine mode bits**. Names are decoration from `/etc/passwd` and `/etc/group`; the kernel compares numbers.
- The check picks **one triplet** (owner, else group, else other) and requires every requested bit in it. Triplets do not add up. **Root skips the check**, except that executing needs some `x` bit.
- `chmod` in octal sets all nine bits (`640`, `750`); symbolic form edits some (`u+x`, `go-r`, `a=r`). `644` for files, `755` for programs and directories, `600` for keys, `640`/`750` for what a service group shares, never `777`.
- On a **directory**, `x` is enter, `r` is list, `w` is create or delete names. Every path component needs `x`. **Deleting needs `w` on the directory**, not on the file.
- The **umask** subtracts from `666`/`777`; `022` gives `644`/`755`. Set it in the unit for a service.
- **setuid** runs a program as its owner (`passwd`, `sudo`); **setgid** on a directory makes new files inherit its group; **sticky** on a directory lets only owners delete (`/tmp`). Audit setuid-root binaries.
- **Services run as their own nologin user**: config `root:app 640`, data and logs `app:app 750`. **Humans use `sudo`** with a specific command list in `/etc/sudoers.d/`, checked with `visudo -c`, and `sudo -u app` to inspect without becoming root.
- **Capabilities** are slices of root. A service that "needs root for port 443" needs `CAP_NET_BIND_SERVICE`. A container's root is a process with a trimmed capability set.

Next: [Pipes & Redirection](../07-streams-pipes-and-redirection/). You have seen file descriptors 0, 1 and 2 in every `strace` and every `/proc/<pid>/fd`. Now what they are, how `>`, `2>&1` and `|` rewire them between `fork` and `exec`, and a real pipeline built from `os.pipe` and `dup2`.
