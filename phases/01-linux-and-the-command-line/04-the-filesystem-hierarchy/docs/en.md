# The Filesystem Hierarchy: Where Everything Lives

> `ls -l` is one system call per file. Every column it prints, the type, the nine permission characters, the link count, the owner, the size, the timestamp, comes out of `stat(2)`, and this lesson rebuilds `ls`, `find`, `du` and `df` from it. Then it walks the standard layout of a Linux box so that `/etc`, `/var/lib`, `/usr/local` and `/run` stop being names and become decisions: a 100 MiB file that occupies **4,096 bytes** of disk, a "full" disk with space left, and a deleted log that keeps filling it.

## The Problem

You are on a server you did not build. The service is misbehaving. Where is its config? Where are its logs? Which of the two `python3` binaries is it running? Is the disk actually full, and if `df` says yes while `du` says no, who is lying? Foundations told you a file is a named pile of bytes and a directory is a table of names; that is true and it is not enough. A Linux box has a **standard layout**, and every tool, every package, every `systemd` unit and every backup script assumes you know it.

The other half of the problem is the tool itself. `ls -l` prints ten columns and most people read two of them. `find` has fifty tests and most people know one. Both are thin layers over a single system call, and once you have written that layer yourself the fifty tests become obvious, because each one is a comparison against a field you have already printed.

## The Concept

### One tree, many disks

Linux has one directory tree, starting at `/`, and it does not care how many disks are underneath. A second disk, a network share, a USB stick, a filesystem that lives in RAM: each is attached at a **mount point**, a directory whose contents are replaced by the root of that filesystem. `findmnt` and `/proc/mounts` list them (lesson 02). The layout of the tree is standardised by the **Filesystem Hierarchy Standard** (FHS), and knowing it is knowing where to look:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 640" width="100%" style="max-width:880px" role="img" aria-label="The top of the Linux directory tree, drawn as a table of directories under root, coloured by role. In purple, read-only during operation and owned by the package manager or the image: usr with bin, sbin, lib, share and local; etc, the system-wide configuration; boot, the kernel; opt, self-contained third-party software; and bin, sbin and lib, which on current distributions are symlinks into usr. In amber, written at runtime and therefore the directories that belong on volumes and in backups: var with lib for persistent data, log, cache, spool and tmp; run, runtime state since boot on a tmpfs; tmp, scratch cleared at boot; home and root, the users' directories. In green, not storage at all: proc, sys and dev, the kernel's windows from lesson 02, and workspace, this repo bind-mounted into the sandbox. A legend explains the colours. A caption states the rule that everything a service reads lives in purple and everything it writes lives in amber, which is what lets an image be read-only and a volume be attached.">
  <defs>
    <marker id="p1l04a-ar" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker>
  </defs>
  <text x="450" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">The hierarchy: what is read-only, what is written, and what is not a disk at all</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">

    <!-- legend -->
    <rect x="40" y="42" width="14" height="12" rx="3" fill="#7c5cff" fill-opacity="0.18" stroke="#7c5cff" stroke-width="1.3"/>
    <text x="60" y="52" font-size="8.5" fill="currentColor">read-only in operation · owned by the package manager or the image</text>
    <rect x="440" y="42" width="14" height="12" rx="3" fill="#e0930f" fill-opacity="0.18" stroke="#e0930f" stroke-width="1.3"/>
    <text x="460" y="52" font-size="8.5" fill="currentColor">written at runtime · volumes and backups</text>
    <rect x="700" y="42" width="14" height="12" rx="3" fill="#0fa07f" fill-opacity="0.18" stroke="#0fa07f" stroke-width="1.3"/>
    <text x="720" y="52" font-size="8.5" fill="currentColor">the kernel, not storage</text>

    <!-- root -->
    <rect x="40" y="70" width="820" height="26" rx="7" fill="#7f7f7f" fill-opacity="0.14" stroke="currentColor" stroke-opacity="0.5" stroke-width="1.4"/>
    <text x="56" y="87" font-size="11" font-weight="700" fill="currentColor">/</text>
    <text x="80" y="87" font-size="9" fill="currentColor" opacity="0.85">the root: one tree, whatever disks are underneath · in the sandbox an overlay, on a server ext4 or xfs</text>

    <!-- purple column -->
    <g fill="none" stroke-linejoin="round" stroke-width="1.5">
      <rect x="40"  y="106" width="400" height="60" rx="8" fill="#7c5cff" fill-opacity="0.09" stroke="#7c5cff"/>
      <rect x="40"  y="172" width="400" height="46" rx="8" fill="#7c5cff" fill-opacity="0.09" stroke="#7c5cff"/>
      <rect x="40"  y="224" width="400" height="34" rx="8" fill="#7c5cff" fill-opacity="0.09" stroke="#7c5cff"/>
      <rect x="40"  y="264" width="400" height="34" rx="8" fill="#7c5cff" fill-opacity="0.09" stroke="#7c5cff"/>
      <rect x="40"  y="304" width="400" height="46" rx="8" fill="#7c5cff" fill-opacity="0.09" stroke="#7c5cff"/>
    </g>
    <text x="52" y="124" font-size="10.5" font-weight="700" fill="#7c5cff">/usr</text>
    <text x="100" y="124" font-size="9" fill="currentColor">installed software: the bulk of the system</text>
    <text x="52" y="140" font-size="8.5" fill="currentColor">bin · sbin: the commands (390 in the sandbox) · lib: shared libraries · share: docs, locales, data</text>
    <text x="52" y="156" font-size="8.5" fill="currentColor">local: the same layout for things YOU installed by hand: /usr/local/bin is first on PATH</text>
    <text x="52" y="190" font-size="10.5" font-weight="700" fill="#7c5cff">/etc</text>
    <text x="100" y="190" font-size="9" fill="currentColor">system-wide configuration, all of it plain text (89 entries in the sandbox)</text>
    <text x="52" y="206" font-size="8.5" fill="currentColor">passwd, group, hosts, fstab, ssh/, systemd/, nginx/, app/ · /etc/default and *.d/ directories for drop-ins</text>
    <text x="52" y="246" font-size="10.5" font-weight="700" fill="#7c5cff">/opt</text>
    <text x="100" y="246" font-size="9" fill="currentColor">self-contained third-party trees: /opt/app/bin, /opt/app/lib, one directory per product</text>
    <text x="52" y="286" font-size="10.5" font-weight="700" fill="#7c5cff">/boot</text>
    <text x="100" y="286" font-size="9" fill="currentColor">the kernel image and the bootloader (empty in a container: no kernel of its own)</text>
    <text x="52" y="322" font-size="10.5" font-weight="700" fill="#7c5cff">/bin /sbin /lib</text>
    <text x="180" y="322" font-size="9" fill="currentColor">symlinks: bin → usr/bin, lib → usr/lib</text>
    <text x="52" y="340" font-size="8.5" fill="currentColor" opacity="0.8">the "merged /usr": the historical split is gone, the names survive so old scripts keep working</text>

    <!-- amber column -->
    <g fill="none" stroke-linejoin="round" stroke-width="1.5">
      <rect x="460" y="106" width="400" height="74" rx="8" fill="#e0930f" fill-opacity="0.09" stroke="#e0930f"/>
      <rect x="460" y="186" width="400" height="34" rx="8" fill="#e0930f" fill-opacity="0.09" stroke="#e0930f"/>
      <rect x="460" y="226" width="400" height="34" rx="8" fill="#e0930f" fill-opacity="0.09" stroke="#e0930f"/>
      <rect x="460" y="266" width="400" height="34" rx="8" fill="#e0930f" fill-opacity="0.09" stroke="#e0930f"/>
    </g>
    <text x="472" y="124" font-size="10.5" font-weight="700" fill="#e0930f">/var</text>
    <text x="520" y="124" font-size="9" fill="currentColor">variable data: everything that grows while the machine runs</text>
    <text x="472" y="140" font-size="8.5" fill="currentColor">lib: persistent data (postgresql, docker, app) · log: logs · cache: regenerable</text>
    <text x="472" y="154" font-size="8.5" fill="currentColor">spool: queued work (mail, cron) · tmp: scratch that survives reboot · run → /run</text>
    <text x="472" y="170" font-size="8.5" fill="currentColor" opacity="0.8">/var/lib is the one directory that must be on a backed-up volume</text>
    <text x="472" y="208" font-size="10.5" font-weight="700" fill="#e0930f">/run</text>
    <text x="520" y="208" font-size="9" fill="currentColor">runtime state since boot: PID files, Unix sockets · a tmpfs, empty at every boot</text>
    <text x="472" y="248" font-size="10.5" font-weight="700" fill="#e0930f">/tmp</text>
    <text x="520" y="248" font-size="9" fill="currentColor">scratch, cleared at boot, often small and in RAM · world-writable, the sticky bit (lesson 06)</text>
    <text x="472" y="288" font-size="10.5" font-weight="700" fill="#e0930f">/home /root</text>
    <text x="580" y="288" font-size="9" fill="currentColor">users' directories; root's is separate so it works when /home is missing</text>

    <!-- green column -->
    <g fill="none" stroke-linejoin="round" stroke-width="1.5">
      <rect x="460" y="310" width="400" height="40" rx="8" fill="#0fa07f" fill-opacity="0.09" stroke="#0fa07f"/>
    </g>
    <text x="472" y="328" font-size="10.5" font-weight="700" fill="#0fa07f">/proc /sys /dev</text>
    <text x="600" y="328" font-size="9" fill="currentColor">the kernel's windows and the drivers' doors (lesson 02)</text>
    <text x="472" y="343" font-size="8.5" fill="currentColor" opacity="0.8">not on any disk; a backup of them is meaningless, and du across them is misleading</text>

    <!-- the rest -->
    <rect x="40" y="366" width="820" height="46" rx="8" fill="#7f7f7f" fill-opacity="0.10" stroke="#7f7f7f" stroke-width="1.4" stroke-linejoin="round"/>
    <text x="52" y="384" font-size="9.5" font-weight="700" fill="currentColor">/mnt /media</text>
    <text x="150" y="384" font-size="9" fill="currentColor">temporary and removable mounts</text>
    <text x="400" y="384" font-size="9.5" font-weight="700" fill="currentColor">/srv</text>
    <text x="440" y="384" font-size="9" fill="currentColor">data this host serves (rarely used)</text>
    <text x="680" y="384" font-size="9.5" font-weight="700" fill="currentColor">/workspace</text>
    <text x="52" y="402" font-size="8.5" fill="currentColor" opacity="0.8">on a Mac: /Users, /Applications, /Library, /System, and /private where /etc, /var and /tmp really live</text>
    <text x="680" y="402" font-size="8.5" fill="currentColor" opacity="0.8">this repo, bind-mounted in</text>

    <!-- the rule -->
    <rect x="40" y="428" width="820" height="92" rx="10" fill="#c94a12" fill-opacity="0.08" stroke="#c94a12" stroke-width="1.8" stroke-linejoin="round"/>
    <text x="450" y="450" text-anchor="middle" font-size="10.5" font-weight="700" fill="#c94a12">THE RULE FOR ONE SERVICE CALLED app</text>
    <g text-anchor="middle" font-size="9" fill="currentColor">
      <text x="450" y="470">it reads from purple:  /usr/local/bin/app (or /opt/app)  ·  /etc/app/app.yaml  ·  /etc/systemd/system/app.service</text>
      <text x="450" y="486">it writes to amber:  /var/lib/app (data)  ·  /var/log/app (logs)  ·  /var/cache/app  ·  /run/app (socket, pid)  ·  /tmp</text>
      <text x="450" y="506" opacity="0.8">so the purple half can be an immutable image or a read-only mount, and the amber half a volume, a backup, or a tmpfs, independently</text>
    </g>
  </g>
  <text x="450" y="556" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="10.5" fill="currentColor" opacity="0.9">Config in /etc, software in /usr and /opt, state in /var, runtime in /run, scratch in /tmp, the kernel in /proc and /sys.</text>
  <text x="450" y="574" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="10.5" fill="currentColor" opacity="0.9">Every package, unit file, backup and container image on the box assumes this split. Deploy into it, and look in it.</text>
  <text x="450" y="596" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="9.5" fill="currentColor" opacity="0.72">Nothing you write at runtime goes under /etc, /usr or /opt. Nothing you need to keep goes under /tmp or /run.</text>
</svg>
```

Two things surprise people on their first real box. First, `/bin`, `/sbin` and `/lib` are **symlinks** into `/usr` on every current distribution; the historical reason for a split (a small root disk that had to boot before `/usr` was mounted) is gone, and only the names survive. Second, `/proc`, `/sys` and `/dev` look like directories and are not storage at all; they are the kernel's windows from lesson 02, generated on demand, which is why `du -sh /` gives nonsense unless you tell it to stay on one filesystem (`-x`).

The rule at the bottom of the diagram is the one that matters for a backend engineer, and it is the reason the layout exists: **a service reads from the read-only half and writes to the runtime half.** Config in `/etc/app`, code in `/usr/local` or `/opt/app`, data in `/var/lib/app`, logs in `/var/log/app`, sockets and PID files in `/run/app`. Keep to it and the read-only half can be baked into a container image or mounted read-only, while the runtime half becomes a volume that outlives the container. Phase 11 builds on exactly this split; lesson 11 here puts a real service into it.

### Paths, and where you are standing

An **absolute path** starts at `/` and means the same file from anywhere. A **relative path** starts from the **working directory**, the directory the process is standing in (`pwd` prints it; every process has one, inherited from its parent at fork). The classic failure, reproduced in the sandbox:

```console
$ cd /;    ls etc/hostname
etc/hostname
$ cd /var; ls etc/hostname
ls: cannot access 'etc/hostname': No such file or directory
$ ls /etc/hostname
/etc/hostname
```

Same file, same command, different working directory, and the relative path stopped meaning anything. Under `systemd` a service's working directory is `/` unless the unit says otherwise; under `cron` it is the user's home. When a deployed service "cannot find" a file that is plainly there, `ls -l /proc/<pid>/cwd` is the first check.

Every directory contains two entries the kernel maintains: `.` (itself) and `..` (its parent). They are real directory entries with inode numbers, which is why `ls -la` lists them and why `..` works even across mount points. `~` is your home directory, `cd` with no argument goes there, and `cd -` goes back to wherever you were before. Names starting with `.` are **hidden** only in the sense that `ls` skips them without `-a`; `.env`, `.git` and `.ssh` are ordinary directories that a careless `ls` will not show you.

### What ls -l actually prints

Every line of `ls -l` is the result of one `stat` call, formatted:

```console
$ ls -li /etc/passwd
186253716 -rw-r--r-- 1 root root 889 Sep  5 03:20 /etc/passwd
```

Left to right: the **inode number** (with `-i`), the **type** (`-` regular file, `d` directory, `l` symlink, `c` and `b` character and block devices, `p` pipe, `s` socket), nine **permission** characters in three groups of `rwx` for owner, group and everyone else (lesson 06 owns these), the **link count** (how many names this inode has), the **owner** and **group**, the **size** in bytes, the **modification time**, and the **name**. The `stat` command prints the same struct without the formatting, including three timestamps: `Access` (last read), `Modify` (last content change, what `ls` shows) and `Change` (last change to the inode itself: a `chmod`, a rename, a new link).

The flags you will use daily: `-l` long, `-a` all (dotfiles), `-h` human sizes, `-t` newest first, `-S` largest first, `-r` reverse, `-d` the directory itself rather than its contents, `-R` recursive, and `-i` inodes. `ls -lt /var/log | head` is "what changed most recently"; `ls -lS /usr/bin | head` is "what is biggest." Combine them: `ls -laht`.

### Names and inodes: hard links, symlinks, and what rm does

Foundations said a directory is a table mapping names to inode numbers. Take that literally and three things follow that trip people up for years:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 470" width="100%" style="max-width:880px" role="img" aria-label="On the left, a directory called etc slash app drawn as a table of five names and the inode number each maps to. config.yaml and config.hardlink both map to inode 186402333, which is a regular file with a link count of 2 and data blocks holding port colon 8080; that is a hard link, two names for one file, and rm of either name only decrements the count. config.symlink maps to its own inode 186402335, whose content is the eleven-character text config.yaml; that is a symbolic link, a file whose data is a path that the kernel follows on open. dangling maps to inode 186402336 whose text is slash definitely slash not slash here, a path that leads nowhere, so opening it fails with ENOENT while lstat succeeds. logs maps to an inode whose text is dot dot slash dot dot slash var slash log slash app, a relative path resolved from the link's own directory. A note explains that the data blocks are freed only when the link count reaches zero and no process holds the file open, which is how a deleted log can keep consuming disk.">
  <defs>
    <marker id="p1l04b-ar" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker>
    <marker id="p1l04b-ard" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#d64545"/></marker>
  </defs>
  <text x="450" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">A directory is a table of names → inodes. Links are what happens when you take that literally.</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">

    <!-- directory table -->
    <rect x="40" y="56" width="300" height="200" rx="10" fill="#7c5cff" fill-opacity="0.08" stroke="#7c5cff" stroke-width="1.8" stroke-linejoin="round"/>
    <text x="190" y="78" text-anchor="middle" font-size="10.5" font-weight="700" fill="#7c5cff">the directory etc/app  (inode 186402329)</text>
    <text x="60" y="98" font-size="8.5" font-weight="700" fill="currentColor" opacity="0.8">name</text>
    <text x="240" y="98" font-size="8.5" font-weight="700" fill="currentColor" opacity="0.8">inode</text>
    <g font-size="9.5" fill="currentColor">
      <text x="60" y="122">config.yaml</text>       <text x="240" y="122">186402333</text>
      <text x="60" y="146">config.hardlink</text>   <text x="240" y="146">186402333</text>
      <text x="60" y="170">config.symlink</text>    <text x="240" y="170">186402335</text>
      <text x="60" y="194">dangling</text>          <text x="240" y="194">186402336</text>
      <text x="60" y="218">logs</text>              <text x="240" y="218">186402337</text>
      <text x="60" y="242" opacity="0.6">. and ..</text> <text x="240" y="242" opacity="0.6">186402329, 186402328</text>
    </g>

    <!-- inodes -->
    <g fill="none" stroke-linejoin="round" stroke-width="1.7">
      <rect x="420" y="96" width="440" height="66" rx="9" fill="#0fa07f" fill-opacity="0.10" stroke="#0fa07f"/>
      <rect x="420" y="176" width="440" height="46" rx="9" fill="#e0930f" fill-opacity="0.10" stroke="#e0930f"/>
      <rect x="420" y="236" width="440" height="46" rx="9" fill="#d64545" fill-opacity="0.08" stroke="#d64545"/>
      <rect x="420" y="296" width="440" height="46" rx="9" fill="#e0930f" fill-opacity="0.10" stroke="#e0930f"/>
    </g>
    <text x="432" y="114" font-size="10" font-weight="700" fill="#0fa07f">inode 186402333 · regular file · links: 2 · mode 640 · size 11</text>
    <text x="432" y="130" font-size="9" fill="currentColor">data blocks: "port: 8080\n"</text>
    <text x="432" y="146" font-size="8.5" fill="currentColor" opacity="0.8">a HARD LINK: two names, one inode, one copy of the bytes; rm either name and the count drops to 1</text>
    <text x="432" y="194" font-size="10" font-weight="700" fill="#e0930f">inode 186402335 · symbolic link · links: 1 · size 11</text>
    <text x="432" y="210" font-size="9" fill="currentColor">content: "config.yaml"  ← a path, followed by the kernel at open(); resolved relative to etc/app</text>
    <text x="432" y="254" font-size="10" font-weight="700" fill="#d64545">inode 186402336 · symbolic link · size 20</text>
    <text x="432" y="270" font-size="9" fill="currentColor">content: "/definitely/not/here"  ← lstat succeeds, open() fails: ENOENT. A DANGLING link</text>
    <text x="432" y="314" font-size="10" font-weight="700" fill="#e0930f">inode 186402337 · symbolic link · size 17</text>
    <text x="432" y="330" font-size="9" fill="currentColor">content: "../../var/log/app"  ← relative to the link's directory, not to your cwd; readlink -f resolves it</text>

    <!-- arrows from names to inodes -->
    <g fill="none" stroke="currentColor" stroke-width="1.4" stroke-opacity="0.7">
      <path d="M310 118 L416 118" marker-end="url(#p1l04b-ar)"/>
      <path d="M310 142 L380 142 L380 126 L416 126" marker-end="url(#p1l04b-ar)"/>
      <path d="M310 166 L416 196" marker-end="url(#p1l04b-ar)"/>
      <path d="M310 214 L416 318" marker-end="url(#p1l04b-ar)"/>
    </g>
    <path d="M310 190 L416 258" fill="none" stroke="#d64545" stroke-width="1.4" marker-end="url(#p1l04b-ard)"/>

    <!-- rm note -->
    <rect x="40" y="362" width="820" height="66" rx="10" fill="#7f7f7f" fill-opacity="0.10" stroke="#7f7f7f" stroke-width="1.6" stroke-linejoin="round"/>
    <text x="450" y="382" text-anchor="middle" font-size="10" font-weight="700" fill="currentColor">WHAT rm DOES: unlink(2) removes a NAME from the table, nothing else</text>
    <g text-anchor="middle" font-size="9" fill="currentColor">
      <text x="450" y="400">the data blocks are freed only when the link count reaches 0 AND no process still has the file open</text>
      <text x="450" y="416" opacity="0.8">rm a log that a server is writing: the name is gone, df keeps counting the blocks, du cannot see them. lsof +L1 finds it</text>
    </g>
  </g>
  <text x="450" y="452" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="10.5" fill="currentColor" opacity="0.9">Hard link: another name for the same inode. Symlink: a file whose bytes are a path. rm: forget a name. Nothing here copies data.</text>
</svg>
```

A **hard link** (`ln target name`) is a second directory entry pointing at the *same inode*. Both names are equally the file; there is no original. The link count goes to 2, and `rm` of either name just takes it back to 1. The sandbox shows it, including the part that matters:

```console
$ echo hello > a.txt;  ln a.txt b.txt;  ln -s a.txt c.txt;  ln -s nothing d.txt
$ ls -li a.txt b.txt c.txt d.txt
186358033 -rw-r--r-- 2 root root 6 Sep  5 03:45 a.txt
186358033 -rw-r--r-- 2 root root 6 Sep  5 03:45 b.txt
186358034 lrwxrwxrwx 1 root root 5 Sep  5 03:45 c.txt -> a.txt
186358035 lrwxrwxrwx 1 root root 7 Sep  5 03:45 d.txt -> nothing
$ rm a.txt;  cat b.txt;  cat c.txt
hello
cat: c.txt: No such file or directory
```

`b.txt` still reads `hello` because the inode still has one name. `c.txt`, a **symbolic link** (`ln -s target name`), is a different kind of thing: its own inode, whose contents are the *text* `a.txt`, which the kernel follows when you open it. Delete what it points at and it **dangles**: `ls` still shows it, `open` fails with `ENOENT`. Symlinks can point across filesystems and at directories, which hard links cannot, and their target is resolved relative to the link's own directory, not to where you are standing. `readlink -f` follows the chain to the end; `file` tells you what something is by reading its bytes rather than trusting its name:

```console
$ readlink -f /bin/sh
/usr/bin/dash
$ file /usr/bin/ls /etc/passwd /bin /dev/null /usr/local/bin/python3
/usr/bin/ls:            ELF 64-bit LSB pie executable, ARM aarch64, ... dynamically linked ...
/etc/passwd:            ASCII text
/bin:                   symbolic link to usr/bin
/dev/null:              character special (1/3)
/usr/local/bin/python3: symbolic link to python3.12
```

The third consequence is the one that pages people. **`rm` does not delete data.** It removes a name; the blocks are freed only when the link count is zero *and* no process has the file open. Delete a log that a server is still writing and the space is not returned until the server closes it, which may be never. `df` shows the disk filling, `du` cannot find the file, and `lsof +L1` lists the deleted-but-open files that explain the difference.

### find: a walk with tests

`find` walks a tree, calling `lstat` on every entry and printing the ones that pass your tests. Each test is a comparison against a field of the struct you just read about, which is why its options map so cleanly:

| test | compares | example |
|---|---|---|
| `-name '*.conf'`, `-iname` | the name (glob, quoted so the shell does not expand it) | `find /etc -name '*.conf'` |
| `-type f` / `d` / `l` | the type bits | `find /usr/bin -type l` |
| `-size +100M`, `-size -1k` | `st_size` | `find / -xdev -type f -size +100M` |
| `-mmin -30`, `-mtime +7` | `st_mtime`, in minutes or days | `find /var/log -mmin -30` |
| `-newer ref` | `st_mtime` later than `ref`'s | `find . -newer deploy.marker` |
| `-user app`, `-perm -4000` | `st_uid`, the mode bits | `find / -perm -4000` (setuid, lesson 06) |
| `-xdev` | `st_dev`: stay on one filesystem | skips `/proc`, `/sys`, NFS |
| `-exec cmd {} \;`, `-delete` | actions on each match | `find /tmp -mtime +7 -delete` |

In the sandbox, `find /etc -name '*.conf'` finds 26 files; `find / -xdev -type f -size +20M` finds `/usr/bin/shellcheck` at 41 MB; `find /usr/bin -type l | wc -l` reports 54 of the 390 commands are symlinks. Two habits: quote the pattern (`'*.conf'`, or the shell expands it against the current directory first, step 3 of lesson 03), and append `2>/dev/null` when searching from `/`, because the permission errors on `/proc` are noise. `locate` answers name queries instantly from a nightly index, when it is installed and the index is fresh; `find` is always right and always slower.

### Space: bytes, blocks, inodes, and three ways a disk is full

`du` and `df` answer different questions and disagree for good reasons. `du` walks a tree and sums what the files occupy; `df` asks the filesystem itself, through `statvfs`, how much of its capacity is used. Three things make them differ:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 400" width="100%" style="max-width:880px" role="img" aria-label="A diagnosis flow for the error No space left on device. Start: df -h on the path. Branch one: df says the filesystem is full and du -x agrees; the cause is real files, so find the big ones with du -xh --max-depth=1 sorted, and find slash -xdev -size +100M. Branch two: df says full but du finds far less; the cause is deleted files still held open by a process, found with lsof +L1, fixed by restarting or signalling the holder, or by log rotation that reopens. Branch three: df -h shows plenty of space but writes still fail; the cause is inodes, checked with df -i, caused by millions of tiny files, fixed by deleting them or changing the layout. A side note explains sparse files: ls shows the logical size and du shows allocated blocks, so a 100 MiB sparse file uses 4 KiB.">
  <defs>
    <marker id="p1l04c-ar" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker>
  </defs>
  <text x="450" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">"No space left on device": three different problems with the same message</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <rect x="300" y="46" width="300" height="40" rx="9" fill="#c94a12" fill-opacity="0.12" stroke="#c94a12" stroke-width="1.8" stroke-linejoin="round"/>
    <text x="450" y="64" text-anchor="middle" font-size="10.5" font-weight="700" fill="#c94a12">start: df -h /the/path  and  df -i /the/path</text>
    <text x="450" y="79" text-anchor="middle" font-size="8.5" fill="currentColor" opacity="0.8">bytes used, and inodes used, on the filesystem that holds the path</text>
    <g fill="none" stroke="currentColor" stroke-width="1.6">
      <path d="M380 88 L170 130" marker-end="url(#p1l04c-ar)"/>
      <path d="M450 88 L450 130" marker-end="url(#p1l04c-ar)"/>
      <path d="M520 88 L730 130" marker-end="url(#p1l04c-ar)"/>
    </g>
    <g fill="none" stroke-linejoin="round" stroke-width="1.7">
      <rect x="40"  y="134" width="260" height="150" rx="10" fill="#7f7f7f" fill-opacity="0.10" stroke="#7f7f7f"/>
      <rect x="320" y="134" width="260" height="150" rx="10" fill="#d64545" fill-opacity="0.08" stroke="#d64545"/>
      <rect x="600" y="134" width="260" height="150" rx="10" fill="#e0930f" fill-opacity="0.10" stroke="#e0930f"/>
    </g>
    <text x="170" y="156" text-anchor="middle" font-size="10" font-weight="700" fill="currentColor">df full, du -x agrees</text>
    <g text-anchor="middle" font-size="8.5" fill="currentColor">
      <text x="170" y="176">real files are using the space</text>
      <text x="170" y="196">du -xh --max-depth=1 / | sort -h</text>
      <text x="170" y="210">find / -xdev -type f -size +100M</text>
      <text x="170" y="224">ls -lS /var/log/app | head</text>
      <text x="170" y="248" opacity="0.8">usual suspects: logs that never</text>
      <text x="170" y="262" opacity="0.8">rotated, caches, old releases, core dumps</text>
    </g>
    <text x="450" y="156" text-anchor="middle" font-size="10" font-weight="700" fill="#d64545">df full, du finds much less</text>
    <g text-anchor="middle" font-size="8.5" fill="currentColor">
      <text x="450" y="176">deleted files a process still holds open</text>
      <text x="450" y="196">lsof +L1</text>
      <text x="450" y="210">ls -l /proc/&lt;pid&gt;/fd | grep deleted</text>
      <text x="450" y="230">the blocks return when it closes them:</text>
      <text x="450" y="244">restart, or SIGHUP for a log reopen</text>
      <text x="450" y="262" opacity="0.8">rm never freed anything; unlink forgot a name</text>
    </g>
    <text x="730" y="156" text-anchor="middle" font-size="10" font-weight="700" fill="#e0930f">df -h has space, writes still fail</text>
    <g text-anchor="middle" font-size="8.5" fill="currentColor">
      <text x="730" y="176">out of inodes, not bytes</text>
      <text x="730" y="196">df -i  →  IUse% 100%</text>
      <text x="730" y="210">find /path -xdev -type f | wc -l</text>
      <text x="730" y="230">millions of tiny files: sessions,</text>
      <text x="730" y="244">cache entries, mail, build artifacts</text>
      <text x="730" y="262" opacity="0.8">delete them, or change the layout</text>
    </g>
    <rect x="40" y="304" width="820" height="56" rx="10" fill="#0fa07f" fill-opacity="0.08" stroke="#0fa07f" stroke-width="1.6" stroke-linejoin="round"/>
    <text x="450" y="324" text-anchor="middle" font-size="10" font-weight="700" fill="#0fa07f">AND THE OTHER DIRECTION: ls says big, du says small</text>
    <text x="450" y="342" text-anchor="middle" font-size="8.5" fill="currentColor">a sparse file: ls -l shows the logical length (st_size), du shows allocated blocks (st_blocks × 512). 100 MiB of holes cost 4 KiB in the sandbox.</text>
    <text x="450" y="354" text-anchor="middle" font-size="8" fill="currentColor" opacity="0.8">databases, VM images and downloads-in-progress are sparse; du --apparent-size shows the other number</text>
  </g>
  <text x="450" y="386" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="10.5" fill="currentColor" opacity="0.9">df asks the filesystem; du walks the files. When they disagree, the disagreement is the diagnosis.</text>
</svg>
```

**Blocks, not bytes.** A file's size (`st_size`) is its logical length; what it occupies is `st_blocks × 512`. Filesystems allocate in blocks (4 KiB here), so a one-byte file uses 4 KiB, and a **sparse** file, one with holes that were never written, uses almost nothing. The script creates a 100 MiB sparse file; `ls -l` reports 104,857,600 bytes, `du` reports **4,096**. `du --apparent-size` shows the other number, which is why `du -sh /usr/bin` gives 83M and `du -sh --apparent-size /usr/bin` gives 82M.

**Inodes.** Every file needs one, and a filesystem is created with a fixed number of them. A million tiny session files can exhaust the inodes while `df -h` still shows space; `df -i` is the check. (The sandbox's overlay reports 0 inodes because the overlay driver does not expose a count; on ext4 you will see millions.)

**Deleted but open.** Described above. It is the most common reason `df` and `du` disagree on a server, and the first thing to check when a disk fills faster than any file grows.

## Build It

The script for this lesson is [`code/ls_and_find.py`](../code/ls_and_find.py). It builds a small tree in a temporary directory (a config file, a hard link to it, a symlink to it, a dangling symlink, a symlink to a directory, a log, and a 100 MiB sparse file), then rebuilds four tools from `stat` and runs them on it. It runs on macOS and Linux:

```bash
python3 phases/01-linux-and-the-command-line/04-the-filesystem-hierarchy/code/ls_and_find.py
```

**`ls -l` is `stat` plus string formatting.** The mode column is `st_mode` decoded bit by bit, the arrow after a symlink is `readlink`, and everything else is a field:

```python
def ls_l(path, show_inode=False):
    for e in sorted(os.scandir(path), key=lambda e: e.name):   # getdents64 under the hood
        st = e.stat(follow_symlinks=False)                      # lstat: describe the link itself
        when = time.strftime("%b %d %H:%M", time.localtime(st.st_mtime))
        name = e.name
        if stat.S_ISLNK(st.st_mode):
            name += " -> " + os.readlink(e.path)                # readlink(2): where it points
        print(f"{mode_string(st.st_mode)} {st.st_nlink:>2} {owner(st.st_uid):<8} {group(st.st_gid):<8} "
              f"{st.st_size:>7} {when} {name}")
```

Run in the sandbox, the output is indistinguishable from the real thing, and it shows the two-names-one-inode fact directly:

```console
186402333 -rw-r-----  2 root  root  11 Sep 05 03:46 config.hardlink
186402335 lrwxrwxrwx  1 root  root  11 Sep 05 03:46 config.symlink -> config.yaml
186402333 -rw-r-----  2 root  root  11 Sep 05 03:46 config.yaml
186402336 lrwxrwxrwx  1 root  root  20 Sep 05 03:46 dangling -> /definitely/not/here
186402337 lrwxrwxrwx  1 root  root  17 Sep 05 03:46 logs -> ../../var/log/app
```

The symlink's size is 11 because its content is the eleven characters `config.yaml`. The `stat` versus `lstat` section then shows the two views of a link: `lstat` describes the link (`lrwxrwxrwx`, size 20), `stat` follows it, and for the dangling one, following it produces the kernel's `No such file or directory` while the link itself plainly exists.

**`find` is `os.walk` plus a test per field.** Each `-name`, `-type`, `-size` and `-mmin` is one comparison:

```python
for dirpath, dirnames, filenames in os.walk(root):            # opendir + getdents64, recursively
    for entry in (os.path.join(dirpath, n) for n in dirnames + filenames):
        st = os.lstat(entry)                                  # one stat per entry, like find
        if name and not fnmatch.fnmatch(os.path.basename(entry), name): continue
        if kind == "f" and not stat.S_ISREG(st.st_mode):      continue
        if min_size is not None and st.st_size < min_size:    continue
        if newer_than is not None and st.st_mtime < newer_than: continue
        yield entry
```

```console
find . -name '*.yaml'      -> ['./etc/app/config.yaml']
find . -type l             -> ['./etc/app/logs', './etc/app/dangling', './etc/app/config.symlink']
find . -type f -size +1k   -> ['./var/log/app/sparse.bin']
find . -mmin -1 -type f    -> 4 files changed in the last minute
```

**`du` sums blocks; `df` asks the filesystem.** The sparse file makes the difference impossible to miss:

```console
ls -l says sparse.bin is 104,857,600 bytes (100 MiB): that is the file's logical length
du says it uses 4,096 bytes: st_blocks × 512, the blocks actually allocated
du -s var: 104,858,550 bytes of file length, 8,192 bytes allocated on disk

/tmp/hier-tj72p5ov: 304.0 GiB total, 285.6 GiB available, 0 inodes, 0 free
```

On a Mac the same file allocates 16,384 bytes, because APFS uses larger blocks; the principle is identical. The `df` line is `os.statvfs`, which is all `df` calls, and its `0 inodes` is the overlay filesystem declining to report a count.

**Paths and the top level.** The last two sections reproduce the relative-path failure with `chdir`, print the inode numbers behind `.` and `..`, resolve the directory symlink with `realpath`, and then walk `/` printing each top-level directory's purpose and entry count, with the symlink arrows for `bin`, `lib` and `sbin`. On a Mac it annotates `/Users`, `/Applications` and `/private` instead, so you can see which parts of the hierarchy are Unix and which are Apple.

## Use It

The real tools on the real layout, inside `make shell`:

```console
$ ls -l / | grep -E 'bin|lib|sbin|tmp|usr|var'
lrwxrwxrwx   1 root root   7 Jul  4 09:05 bin -> usr/bin
lrwxrwxrwx   1 root root   7 Jul  4 09:05 lib -> usr/lib
lrwxrwxrwx   1 root root   8 Jul  4 09:05 sbin -> usr/sbin
drwxrwxrwt   1 root root   0 Aug 24 00:00 tmp
drwxr-xr-x   1 root root  10 Aug 24 00:00 usr
drwxr-xr-x   1 root root  22 Aug 24 00:00 var
```

The merged `/usr` in one screen: three symlinks. Note `/tmp`'s mode ends in `t` rather than `x`; that is the **sticky bit**, which lets everyone create files there while only the owner of a file may delete it (lesson 06).

```console
$ tree -L 1 /usr;  ls /usr/local
/usr
├── bin
├── include
├── lib
├── local
├── sbin
├── share
└── src
bin  etc  games  include  lib  libexec  man  sbin  share  src
```

`/usr/local` repeats the layout of `/usr` for software installed by hand, and it comes *first* on `PATH`, which is why the sandbox's `python3` is `/usr/local/bin/python3` (the image's) and not Debian's. `/etc`, `/var` and `/run` as they actually look:

```console
$ ls /etc | wc -l;  head -3 /etc/passwd
89
root:x:0:0:root:/root:/bin/bash
daemon:x:1:1:daemon:/usr/sbin:/usr/sbin/nologin
bin:x:2:2:bin:/bin:/usr/sbin/nologin
$ ls /var
backups  cache  lib  local  lock  log  mail  opt  run  spool  tmp
$ ls /var/log
alternatives.log  apt  btmp  dpkg.log  lastlog  wtmp
```

Every one of the 89 entries in `/etc` is text you can read with `cat`, starting with `/etc/passwd`, the table of users that lesson 06 takes apart. `/var/log` in a fresh container holds only the package manager's logs; on a server it is where your service's logs live and where lesson 08's text tools earn their keep.

Now the space questions, on the running sandbox:

```console
$ df -h /;  df -i /
Filesystem      Size  Used Avail Use% Mounted on
overlay         304G   19G  286G   7% /
Filesystem     Inodes IUsed IFree IUse% Mounted on
overlay             0     0     0     - /
$ du -sh /usr/lib /usr/bin /usr/local/lib/python3.12
95M     /usr/lib
83M     /usr/bin
195M    /usr/local/lib/python3.12
$ ls -lS /usr/bin | head -3
-rwxr-xr-x 1 root root   41042496 Mar 17  2024 shellcheck
-rwxr-xr-x 2 root root    3813416 Jul 27  2025 perl
-rwxr-xr-x 2 root root    3813416 Jul 27  2025 perl5.40.1
```

`perl` and `perl5.40.1` show a link count of 2 and identical sizes: a hard link, one 3.8 MB file under two names, which `du` counts once. `shellcheck`, the only file over 20 MB on the whole image, is the reason `find / -xdev -size +20M` returns exactly one line.

And the whole struct, when `ls` is not enough:

```console
$ stat /etc/passwd
  File: /etc/passwd
  Size: 889       	Blocks: 8          IO Block: 4096   regular file
Device: 0,108	Inode: 186253716   Links: 1
Access: (0644/-rw-r--r--)  Uid: (    0/    root)   Gid: (    0/    root)
Access: 2026-09-05 03:20:39.000000000 +0000
Modify: 2026-09-05 03:20:39.000000000 +0000
Change: 2026-09-05 03:21:05.257542897 +0000
 Birth: 2026-09-05 03:21:05.257496266 +0000
$ stat -c '%n inode=%i links=%h mode=%A owner=%U size=%s blocks=%b' /etc/passwd
/etc/passwd inode=186253716 links=1 mode=-rw-r--r-- owner=root size=889 blocks=8
```

889 bytes in 8 blocks of 512: 4 KiB allocated for less than 1 KiB of content, the block rounding from the script. `stat -c` with a format string is how scripts read one field without parsing `ls`.

## Ship It

The artifact for this lesson is a checklist: [`outputs/checklist-where-things-live.md`](../outputs/checklist-where-things-live.md). Half of it is the layout for **one deployed service**: which directory each kind of file belongs in (binary, config, data, logs, runtime state, cache, scratch, secrets), with the ownership and the reason, so that the read-only half and the runtime half stay separable. The other half is for **a box you did not build**: where to look for a service's config, data and logs before reading its docs, the `find`, `du`, `df` and `stat` recipes that locate things in seconds, and the traps: deleted-but-open files, `/tmp` in RAM, case sensitivity, symlink targets, inode exhaustion.

## Think about it

1. `df -h` says `/var` is 100% used. `du -sh /var/*` adds up to 40% of it. Name the cause, the command that proves it, and the fix that does not involve rebooting.
2. A deploy script does `cp -r /opt/app/config /etc/app` and later `rm -rf /etc/app/*`. Each of these has a symlink hazard. What are they?
3. You install a tool with `pip install` as root and it lands in `/usr/local/bin`. A teammate installs the same tool with `apt` and it lands in `/usr/bin`. Which one runs when either of you types its name, and how would you check?
4. Why does `ls -l` show a symlink's permissions as `lrwxrwxrwx` regardless of what it points at, and which permissions does the kernel actually check when you open it?

## Key takeaways

- Linux has **one tree** with disks attached at **mount points**. The **FHS** fixes what lives where: software in `/usr` and `/opt`, config in `/etc`, state in `/var`, runtime in `/run`, scratch in `/tmp`, the kernel's windows in `/proc`, `/sys` and `/dev`. `/bin`, `/sbin` and `/lib` are symlinks into `/usr`.
- A service **reads from the read-only half and writes to the runtime half**. That split is what makes images, volumes and backups possible.
- A **relative path** depends on the working directory, which a process inherits at fork and which is `/` under systemd. `ls -l /proc/<pid>/cwd` answers "where is it looking."
- Every column of `ls -l` is a field of **`stat(2)`**: type, mode, link count, owner, group, size, mtime. `stat` prints the struct; `find` is a recursive walk with one comparison per field; `du` sums `st_blocks`; `df` is `statvfs`.
- A directory maps **names to inodes**. A **hard link** is a second name for the same inode. A **symlink** is a file whose bytes are a path, followed at `open`, resolved relative to the link, and able to dangle. **`rm` removes a name**; the data goes when the last name and the last open descriptor are gone.
- `df` and `du` disagree for three reasons: **deleted-but-open** files (`lsof +L1`), **inodes** (`df -i`), and **sparse** files (`st_size` versus `st_blocks`). The disagreement is the diagnosis.
- `file` reads bytes, not names. `readlink -f` resolves the whole chain. `ls -lt` and `ls -lS` answer "what changed" and "what is big" faster than anything else.

Next: [Working with Files: Create, Read, Copy, Move, Delete, Archive](../05-working-with-files/). You can find anything on the box. Now change it: `cp`, `mv`, `rm` and `tar` rebuilt from their syscalls, including why `mv` is instant across a directory and slow across a disk, and why `rm` is not undo-able.
