# Working with Files

> `mv` took **87 µs** to move a 64 MiB file within one filesystem and **39 ms** to move it to another. Same command, same file, four hundred times slower, because one was a `rename` and the other was a copy followed by a delete. This lesson rebuilds `touch`, `cp`, `mv`, `rm`, `tail -f` and `tar` from the syscalls underneath so you know which operations are instant, which are atomic, which a running process will notice, and why none of them can be undone.

## The Problem

Lesson 04 taught you to find anything on the box. Now you have to change it, and this is where people get hurt. `rm` has no trash. `mv` over an existing file replaces it without a word. `cp` onto a running binary can crash the process. `echo > config.yaml` empties the file *before* it writes, and a service that reads it in that instant reads nothing. A `tar` extracted in the wrong directory buries your home in a copy of `/etc`.

Every one of those is a one-line command that a beginner runs a hundred times without incident, until the one time it matters. The way out is not caution alone; it is knowing what each command asks the kernel to do. `mv` is a `rename`, which is why it is atomic. `rm` is an `unlink`, which is why it frees nothing while a file is open. `cp` is a loop of `read` and `write`, which is why it is never atomic. Once you have written each of them, the safe version of every operation becomes obvious.

## The Concept

### Creating: touch, mkdir -p, and a file with nothing in it

A file comes into existence through `open(2)` with the `O_CREAT` flag. `touch` is exactly that plus `utime(2)`: create the file if it is missing, otherwise bump its modification time to now. Its second use is the more common one on a server: `touch /var/lib/app/.migrated` as a marker that a step happened, checked later with `[ -f ]`.

`mkdir` creates one directory and fails with `EEXIST` if it is there or `ENOENT` if its parent is not. `mkdir -p` loops over the path's components, calling `mkdir` on each and ignoring `EEXIST`, so `mkdir -p app/etc/conf.d` creates three directories or none, and never complains. It is the form to use in scripts, because it is **idempotent**: running it twice is the same as running it once.

Three more ways to make a file, each with a job: `echo "port: 8080" > app.yaml` creates a file with content (the `>` is lesson 07's subject; for now it means "into this file, replacing it"); `mktemp` creates a uniquely named temporary file (or directory with `-d`) so two runs of your script never collide; `truncate -s 1G disk.img` creates a sparse file of a given logical size instantly, using no blocks (lesson 04), which is how VM images and test fixtures start.

### Reading: cat, head, tail, less, and the loop under all of them

Every reading command is one loop: `read` into a buffer until `read` returns 0, and do something with each chunk. `cat` writes the chunks to descriptor 1. `head -n 3` stops after three newlines. `tail -n 2` keeps the last two. `wc` counts newlines, words and bytes as they pass. `cp` writes them into another file. `tee` writes them to a file *and* to descriptor 1. They are the same program with a different body:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 420" width="100%" style="max-width:880px" role="img" aria-label="The read-write loop that underlies cat, cp, head, tail, wc, tee and every download, drawn as a flowchart. Open the source and get a descriptor. Read up to 64 kilobytes into a buffer. If read returned zero bytes, that is end of file: close and finish. Otherwise hand the chunk to the body and loop back to read. Six bodies are listed beside the loop: cat writes the chunk to descriptor 1; cp writes it to a second descriptor opened with O_CREAT and O_TRUNC; head counts newlines and stops after N; tail keeps the last N lines in memory and prints them at the end; wc adds up bytes, words and newlines; tee writes to both a file and descriptor 1. A note says that tail -f is the same loop that, on reaching end of file, sleeps briefly and reads again instead of finishing, and that on Linux cp can skip the loop entirely by asking the kernel to copy with copy_file_range.">
  <defs>
    <marker id="p1l05a-ar" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker>
    <marker id="p1l05a-arg" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#0fa07f"/></marker>
  </defs>
  <text x="450" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">One loop, seven commands: read until zero, do something with each chunk</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <!-- loop boxes -->
    <g fill="none" stroke-linejoin="round" stroke-width="1.8">
      <rect x="40" y="56" width="300" height="44" rx="9" fill="#7f7f7f" fill-opacity="0.12" stroke="#7f7f7f"/>
      <rect x="40" y="128" width="300" height="44" rx="9" fill="#0fa07f" fill-opacity="0.12" stroke="#0fa07f"/>
      <rect x="40" y="200" width="300" height="52" rx="9" fill="#e0930f" fill-opacity="0.12" stroke="#e0930f"/>
      <rect x="40" y="280" width="300" height="44" rx="9" fill="#c94a12" fill-opacity="0.12" stroke="#c94a12"/>
      <rect x="40" y="352" width="300" height="40" rx="9" fill="#7f7f7f" fill-opacity="0.12" stroke="#7f7f7f"/>
    </g>
    <g text-anchor="middle" fill="currentColor">
      <text x="190" y="75" font-size="10.5" font-weight="700">fd = open(path, O_RDONLY)</text>
      <text x="190" y="90" font-size="8.5" opacity="0.8">one syscall; a number comes back</text>
      <text x="190" y="147" font-size="10.5" font-weight="700" fill="#0fa07f">buf = read(fd, 65536)</text>
      <text x="190" y="162" font-size="8.5" opacity="0.8">up to 64 KiB; maybe less; the kernel decides</text>
      <text x="190" y="219" font-size="10.5" font-weight="700" fill="#e0930f">len(buf) == 0 ?</text>
      <text x="190" y="234" font-size="8.5" opacity="0.8">zero bytes means end of file: nothing else does</text>
      <text x="190" y="246" font-size="8" opacity="0.7">(a short read is NOT the end; keep going)</text>
      <text x="190" y="299" font-size="10.5" font-weight="700" fill="#c94a12">BODY(buf)</text>
      <text x="190" y="314" font-size="8.5" opacity="0.8">the only line that differs between commands</text>
      <text x="190" y="371" font-size="10.5" font-weight="700">close(fd); exit 0</text>
      <text x="190" y="385" font-size="8.5" opacity="0.8">release the number</text>
    </g>
    <g fill="none" stroke="currentColor" stroke-width="1.6">
      <path d="M190 102 L190 124" marker-end="url(#p1l05a-ar)"/>
      <path d="M190 174 L190 196" marker-end="url(#p1l05a-ar)"/>
      <path d="M190 254 L190 276" marker-end="url(#p1l05a-ar)"/>
    </g>
    <text x="202" y="268" font-size="8.5" fill="currentColor" opacity="0.85">no</text>
    <!-- yes branch to close -->
    <path d="M342 226 L372 226 L372 372 L344 372" fill="none" stroke="currentColor" stroke-width="1.6" marker-end="url(#p1l05a-ar)"/>
    <text x="358" y="218" font-size="8.5" fill="currentColor" opacity="0.85">yes</text>
    <!-- loop back -->
    <path d="M38 302 L20 302 L20 150 L36 150" fill="none" stroke="#0fa07f" stroke-width="1.8" marker-end="url(#p1l05a-arg)"/>
    <text x="14" y="228" text-anchor="middle" font-size="8" fill="#0fa07f" transform="rotate(-90 14 228)">read again</text>

    <!-- bodies -->
    <rect x="420" y="56" width="440" height="270" rx="10" fill="#c94a12" fill-opacity="0.06" stroke="#c94a12" stroke-width="1.6" stroke-linejoin="round"/>
    <text x="640" y="78" text-anchor="middle" font-size="10.5" font-weight="700" fill="#c94a12">THE BODY, PER COMMAND</text>
    <g font-size="9" fill="currentColor">
      <text x="436" y="104" font-weight="700">cat</text>     <text x="500" y="104">write(1, buf)</text>
      <text x="436" y="126" font-weight="700">cp</text>      <text x="500" y="126">write(out_fd, buf)   · out_fd = open(dst, O_WRONLY|O_CREAT|O_TRUNC)</text>
      <text x="436" y="148" font-weight="700">tee</text>     <text x="500" y="148">write(1, buf); write(file_fd, buf)</text>
      <text x="436" y="170" font-weight="700">head -n N</text><text x="500" y="170">print up to the Nth newline, then stop reading</text>
      <text x="436" y="192" font-weight="700">tail -n N</text><text x="500" y="192">keep the last N lines; print them after the zero</text>
      <text x="436" y="214" font-weight="700">wc</text>      <text x="500" y="214">bytes += len(buf); count b"\n" and word breaks</text>
      <text x="436" y="236" font-weight="700">tail -f</text> <text x="500" y="236">on zero: sleep 50 ms and read again, forever</text>
      <text x="436" y="266" opacity="0.8">Linux shortcut for cp: copy_file_range(src_fd, dst_fd, n) asks the</text>
      <text x="436" y="280" opacity="0.8">kernel to move the bytes itself; nothing visits user space. shutil.copyfile,</text>
      <text x="436" y="294" opacity="0.8">GNU cp and rsync use it when they can. Same result, fewer crossings (lesson 01).</text>
      <text x="436" y="314" opacity="0.7">every HTTP download, every database dump, every log shipper is this loop too</text>
    </g>
  </g>
  <text x="450" y="410" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="10.5" fill="currentColor" opacity="0.9">Read until zero. A short read is not the end. The command is whatever you do with each chunk.</text>
</svg>
```

Two details of the loop matter beyond this lesson. A `read` may return **fewer** bytes than you asked for; only a return of **zero** means end of file. And `tail -f` is the same loop that, on reaching zero, waits and reads again instead of stopping: it is how you watch a log grow, and it is the first command you will type on any misbehaving server (`tail -f /var/log/app/app.log`). The real `tail` uses `inotify` to be woken by the kernel instead of polling, but the shape is identical.

`less` is `cat` with a pager: it reads on demand, so it opens a 10 GB log instantly, and it is interactive: `/pattern` searches forward, `n` for the next match, `G` for the end, `g` for the start, `q` to quit, and `F` turns it into `tail -f` until you press `Ctrl+C`. For anything you would `cat` and then scroll, `less` is the answer.

Two more readers for when the bytes are not text. `file` looks at the content and tells you what it is (lesson 04). `hexdump -C` shows every byte in hexadecimal with the printable characters alongside, which is how you find the carriage return that is breaking a script or the byte-order mark at the top of a config:

```console
$ hexdump -C app/etc/app.yaml | head -2
00000000  70 6f 72 74 3a 20 38 30  38 30 0a 77 6f 72 6b 65  |port: 8080.worke|
00000010  72 73 3a 20 34 0a 6c 6f  67 3a 20 2f 76 61 72 2f  |rs: 4.log: /var/|
```

The `0a` after `8080` is the newline, shown as `.` on the right. Foundations lesson 1 in one command. And `diff -u old new` shows what changed between two files in the format every code review uses, while `cmp` says only whether they differ and where.

### Copying: what cp keeps and what it makes up

`cp src dst` is the read/write loop into a freshly created `dst`. Only the bytes are copied. The new file gets the **mode** the source had (filtered through your umask, lesson 06), **your** ownership, and **now** as its timestamp, because it is a new inode and those are the defaults for a new inode. `cp -p` preserves mode, owner and times; `cp -a` (archive) preserves those and also copies symlinks as links instead of following them, and recurses. The sandbox shows the difference in one `ls`:

```console
$ ls -l app/etc/app.yaml plain.yaml preserved.yaml
-rw-r----- 1 root root 40 Jan  1  2020 app/etc/app.yaml
-rw-r----- 1 root root 40 Sep  5 03:52 plain.yaml        <- cp: today's date
-rw-r----- 1 root root 40 Jan  1  2020 preserved.yaml    <- cp -a: the original's
```

For anything a service will read, use `cp -a`, or `install -m 640 -o root -g app src dst`, which sets mode and owner explicitly in one step. `cp -r` recurses into directories; `cp -n` never overwrites and `cp -i` asks first. And the trap that catches everyone: `cp -r src dst` produces `dst/src` if `dst` already exists and a copy named `dst` if it does not. Run it twice and you have `dst/src/src`. `mv` behaves the same way.

### Moving: rename is atomic, and a copy is not

`mv old new` is one syscall, `rename(2)`. The kernel changes the directory entry: the same inode, the same blocks, a different name. It takes microseconds regardless of the file's size, and it is **atomic**: at every instant the name `new` refers to either the old file or the moved one, never to nothing and never to half of either. That single property is the foundation of every safe write on Unix.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 470" width="100%" style="max-width:880px" role="img" aria-label="Two panels. Left: mv within one filesystem is rename. A directory table entry big.bin pointing at inode 186699962 becomes an entry app/big.bin pointing at the same inode; the data blocks are untouched; measured at 87 microseconds for 64 megabytes; atomic, so a reader sees the old name or the new one and nothing in between. Right: mv across filesystems is a copy followed by an unlink. The kernel refuses rename with EXDEV, so mv opens the source, creates a new inode number 2 on the other device, runs the read-write loop over all 64 megabytes, then unlinks the source; measured at 39 milliseconds; not atomic, since both files exist during the copy and a failure halfway leaves both. Below both panels, the atomic replace pattern as a timeline: write the new content to a temp file in the same directory, fsync it, then rename it over the target; readers before the rename see the complete old file, readers after see the complete new file, and no reader ever sees an empty or partial file, unlike cp or shell redirection which truncate the target first.">
  <defs>
    <marker id="p1l05b-ar" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker>
    <marker id="p1l05b-arg" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#0fa07f"/></marker>
    <marker id="p1l05b-ard" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#d64545"/></marker>
  </defs>
  <text x="450" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">mv is rename(2) on one filesystem, and copy + unlink across two. Only one of them is atomic.</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <!-- left panel -->
    <rect x="40" y="46" width="400" height="200" rx="10" fill="#0fa07f" fill-opacity="0.07" stroke="#0fa07f" stroke-width="1.8" stroke-linejoin="round"/>
    <text x="240" y="68" text-anchor="middle" font-size="10.5" font-weight="700" fill="#0fa07f">SAME FILESYSTEM: rename(2)</text>
    <rect x="60" y="86" width="150" height="40" rx="7" fill="#7c5cff" fill-opacity="0.12" stroke="#7c5cff" stroke-width="1.3"/>
    <text x="135" y="103" text-anchor="middle" font-size="9" fill="currentColor">big.bin</text>
    <text x="135" y="117" text-anchor="middle" font-size="8" fill="currentColor" opacity="0.7">→ inode 186699962</text>
    <rect x="270" y="86" width="150" height="40" rx="7" fill="#7c5cff" fill-opacity="0.12" stroke="#7c5cff" stroke-width="1.3"/>
    <text x="345" y="103" text-anchor="middle" font-size="9" fill="currentColor">app/big.bin</text>
    <text x="345" y="117" text-anchor="middle" font-size="8" fill="currentColor" opacity="0.7">→ inode 186699962</text>
    <path d="M212 106 L266 106" fill="none" stroke="#0fa07f" stroke-width="2" marker-end="url(#p1l05b-arg)"/>
    <rect x="130" y="146" width="220" height="30" rx="7" fill="#0fa07f" fill-opacity="0.12" stroke="#0fa07f" stroke-width="1.3"/>
    <text x="240" y="165" text-anchor="middle" font-size="9" fill="currentColor">64 MiB of data blocks: untouched</text>
    <g text-anchor="middle" font-size="8.5" fill="currentColor">
      <text x="240" y="200">one directory entry rewritten · 87 µs measured</text>
      <text x="240" y="214" font-weight="700" fill="#0fa07f">atomic: a reader sees the old name or the new, never neither</text>
      <text x="240" y="230" opacity="0.75">the file's inode, mode, owner and open descriptors are all unchanged</text>
    </g>

    <!-- right panel -->
    <rect x="460" y="46" width="400" height="200" rx="10" fill="#d64545" fill-opacity="0.06" stroke="#d64545" stroke-width="1.8" stroke-linejoin="round"/>
    <text x="660" y="68" text-anchor="middle" font-size="10.5" font-weight="700" fill="#d64545">DIFFERENT FILESYSTEM: rename fails with EXDEV</text>
    <rect x="480" y="86" width="150" height="40" rx="7" fill="#7c5cff" fill-opacity="0.12" stroke="#7c5cff" stroke-width="1.3"/>
    <text x="555" y="103" text-anchor="middle" font-size="9" fill="currentColor">app/big.bin (overlay)</text>
    <text x="555" y="117" text-anchor="middle" font-size="8" fill="currentColor" opacity="0.7">inode 186699962, device 108</text>
    <rect x="690" y="86" width="150" height="40" rx="7" fill="#7c5cff" fill-opacity="0.12" stroke="#7c5cff" stroke-width="1.3"/>
    <text x="765" y="103" text-anchor="middle" font-size="9" fill="currentColor">/dev/shm/big.bin (tmpfs)</text>
    <text x="765" y="117" text-anchor="middle" font-size="8" fill="currentColor" opacity="0.7">inode 2, device 150: a NEW file</text>
    <path d="M632 106 L686 106" fill="none" stroke="#d64545" stroke-width="2" marker-end="url(#p1l05b-ard)"/>
    <text x="659" y="99" text-anchor="middle" font-size="7.5" fill="#d64545">copy</text>
    <rect x="550" y="146" width="220" height="30" rx="7" fill="#d64545" fill-opacity="0.10" stroke="#d64545" stroke-width="1.3"/>
    <text x="660" y="165" text-anchor="middle" font-size="9" fill="currentColor">the read/write loop over all 64 MiB, then unlink</text>
    <g text-anchor="middle" font-size="8.5" fill="currentColor">
      <text x="660" y="200">every byte through the kernel twice · 39 ms measured</text>
      <text x="660" y="214" font-weight="700" fill="#d64545">not atomic: both files exist during the copy; a crash leaves both</text>
      <text x="660" y="230" opacity="0.75">400x slower here; on a real disk, minutes for a large tree</text>
    </g>

    <!-- atomic replace timeline -->
    <rect x="40" y="268" width="820" height="150" rx="10" fill="#e0930f" fill-opacity="0.08" stroke="#e0930f" stroke-width="1.8" stroke-linejoin="round"/>
    <text x="450" y="290" text-anchor="middle" font-size="10.5" font-weight="700" fill="#e0930f">THE ATOMIC REPLACE: how every editor, package manager and config writer saves a file</text>
    <path d="M80 340 L820 340" fill="none" stroke="currentColor" stroke-width="1.6" marker-end="url(#p1l05b-ar)"/>
    <g fill="none" stroke="currentColor" stroke-width="1.4">
      <path d="M200 332 L200 348"/><path d="M420 332 L420 348"/><path d="M640 332 L640 348"/>
    </g>
    <g text-anchor="middle" font-size="8.5" fill="currentColor">
      <text x="200" y="324" font-weight="700">1 · write app.yaml.tmp</text>
      <text x="420" y="324" font-weight="700">2 · fsync(tmp)</text>
      <text x="640" y="324" font-weight="700">3 · rename(tmp, app.yaml)</text>
      <text x="200" y="362">same directory, so rename is possible</text>
      <text x="420" y="362">the bytes are on disk, not just in the page cache</text>
      <text x="640" y="362">one atomic step: the name flips</text>
      <text x="300" y="386" fill="#0fa07f" font-weight="700">readers here see the complete OLD file</text>
      <text x="740" y="386" fill="#0fa07f" font-weight="700">readers here see the complete NEW file</text>
      <text x="450" y="406" opacity="0.8">cp new app.yaml and echo > app.yaml both TRUNCATE first, then fill: a reader in that window gets an empty or partial file</text>
    </g>
  </g>
  <text x="450" y="446" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="10.5" fill="currentColor" opacity="0.9">Rename changes a name, not data. Write the new file beside the old one, then rename over it: nobody ever reads a half-written file.</text>
  <text x="450" y="462" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="9.5" fill="currentColor" opacity="0.72">A running process keeps its open descriptor to the old inode; it sees the new file only when it reopens (a reload, a SIGHUP, a restart).</text>
</svg>
```

Across filesystems the kernel refuses `rename` with `EXDEV` ("Invalid cross-device link"), and `mv` falls back to the loop: copy every byte into a new inode on the other device, then `unlink` the original. That is slow, not atomic, and can fail halfway leaving both copies. The sandbox has a tmpfs at `/dev/shm`, so the two cases are one `df` apart:

```console
$ stat -c 'inode %i on device %d' big.bin;  time mv big.bin app/big.bin
inode 186699867 on device 108
real    0m0.003s
$ stat -c 'inode %i on device %d' app/big.bin;  time mv app/big.bin /dev/shm/big.bin
inode 186699867 on device 108
real    0m0.153s
$ stat -c 'inode %i on device %d' /dev/shm/big.bin
inode 2 on device 150
```

Same inode after the first `mv`; a brand-new inode on a different device after the second, and fifty times the wall time. `mv` also **overwrites silently** if the destination exists (`mv -n` refuses, `mv -i` asks), and it renames directories just as cheaply as files, since a directory is one entry in its parent.

### The atomic replace

Put `rename`'s guarantee to work. To replace a file that something might be reading, never write into it in place. Write the new content to a temporary file **in the same directory**, `fsync` it so the bytes are on disk and not just in the page cache (lesson 02), then `rename` it over the target. Before the rename, every reader sees the old file, complete. After it, every reader sees the new file, complete. There is no window in which the file is empty or half-written, which is exactly the window that `cp new old` and `echo > old` open, because both **truncate the target first** and then fill it.

This is how `vim` and `nano` save, how `apt` installs, how `git` writes objects, how Kubernetes updates a mounted ConfigMap, and how you should write anything a running service reads. Two footnotes: the temp file must be on the same filesystem as the target (that is why "same directory"), and it is a *new* inode, so it gets a fresh mode and owner unless you copy the old ones across first, as the **Build It** script demonstrates by accident.

### Deleting: rm removes a name, and that is all it does

`rm file` is `unlink(2)`: remove one directory entry. The inode's link count drops by one; if it reaches zero *and* no process holds the file open, the blocks are freed. Otherwise nothing is freed yet, which lesson 04 met as the `df`-versus-`du` mystery and which the script reproduces with a descriptor held across an `unlink`. `rm -r` walks a tree bottom-up, unlinking files and `rmdir`-ing each directory once it is empty; `rm -f` suppresses errors and prompts; `rm -rf` is both, and it is the command that has deleted more production data than every disk failure combined.

There is no trash and no confirmation. The defences are habits, and the sandbox shows three of them:

```console
$ rm -i t.txt < /dev/null
rm: remove regular file 't.txt'?          <- -i asks; with no terminal it cannot, so it refuses
$ touch -- -rf;  ls
-rf  app  notes.txt
$ rm -- -rf;  ls                          <- the -- says "what follows is a name, not an option"
app  notes.txt
$ rm -rf app-copy                          <- gone, no prompt, no undo
$ rmdir app
rmdir: failed to remove 'app': Directory not empty   <- rmdir is the safe one: it only removes empty directories
```

The habits that matter most live in the checklist: see the expansion before you run it (`ls` or `echo` in place of `rm`), double-quote every variable, guard against empty ones (`"${DIR:?}"`), and to free space taken by a log a process is writing, **truncate it** (`: > app.log`) rather than delete it, because deleting keeps the blocks and loses the name.

### Archiving: tar is a stream of 512-byte blocks, and gzip is a separate step

A `.tar` file is not compressed and has no index. It is the files, one after another, each preceded by a **512-byte header** that records its name, mode, owner, size and modification time as ASCII octal digits, followed by the file's bytes padded to the next 512-byte boundary, and finished with two blocks of zeros. The format is called **ustar** and is specified by POSIX in the `pax` utility's description. The **Build It** script writes one by hand, and the real `tar` reads it.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 400" width="100%" style="max-width:880px" role="img" aria-label="The layout of a tar archive as a row of 512-byte blocks. Block one is the header for app/etc/, a directory: name, mode 0755, size 0, type flag 5. Block two is the header for app/etc/app.yaml, mode 0644, size 22 as the octal string 00000000026. Block three is its data, 22 bytes followed by 490 bytes of zero padding. Then a header and a padded data block for app.yaml.bak, a header and a data block for app.log, and finally two all-zero blocks marking the end. A total of 9 blocks, 4,608 bytes, matching the script. Below, the fields inside one header are listed with their byte offsets: name at 0 to 99, mode at 100, uid and gid, size at 124 to 135 in octal, mtime at 136, checksum at 148, type flag at 156, magic ustar at 257, and the checksum rule: sum every byte of the header with the checksum field replaced by eight spaces. A note explains that gzip wraps the whole stream afterwards, so .tar.gz is two formats, tar then gzip, and that is why tar has -z and why the whole archive must be decompressed to list it.">
  <defs>
    <marker id="p1l05c-ar" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker>
  </defs>
  <text x="450" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">A tar file is headers and data in 512-byte blocks; gzip is a wrapper around the whole stream</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <!-- blocks -->
    <g stroke-linejoin="round" stroke-width="1.5">
      <rect x="40"  y="60" width="86" height="60" rx="6" fill="#c94a12" fill-opacity="0.14" stroke="#c94a12"/>
      <rect x="130" y="60" width="86" height="60" rx="6" fill="#c94a12" fill-opacity="0.14" stroke="#c94a12"/>
      <rect x="220" y="60" width="86" height="60" rx="6" fill="#0fa07f" fill-opacity="0.12" stroke="#0fa07f"/>
      <rect x="310" y="60" width="86" height="60" rx="6" fill="#c94a12" fill-opacity="0.14" stroke="#c94a12"/>
      <rect x="400" y="60" width="86" height="60" rx="6" fill="#0fa07f" fill-opacity="0.12" stroke="#0fa07f"/>
      <rect x="490" y="60" width="86" height="60" rx="6" fill="#c94a12" fill-opacity="0.14" stroke="#c94a12"/>
      <rect x="580" y="60" width="86" height="60" rx="6" fill="#0fa07f" fill-opacity="0.12" stroke="#0fa07f"/>
      <rect x="670" y="60" width="86" height="60" rx="6" fill="#7f7f7f" fill-opacity="0.14" stroke="#7f7f7f"/>
      <rect x="760" y="60" width="86" height="60" rx="6" fill="#7f7f7f" fill-opacity="0.14" stroke="#7f7f7f"/>
    </g>
    <g text-anchor="middle" font-size="7.8" fill="currentColor">
      <text x="83"  y="78" font-weight="700">header</text><text x="83"  y="90">app/etc/</text><text x="83" y="102">type 5 · size 0</text><text x="83" y="114" opacity="0.7">dir: no data</text>
      <text x="173" y="78" font-weight="700">header</text><text x="173" y="90">app.yaml</text><text x="173" y="102">0644 · 26 octal</text><text x="173" y="114" opacity="0.7">= 22 bytes</text>
      <text x="263" y="78" font-weight="700">data</text><text x="263" y="90">22 bytes</text><text x="263" y="102">+ 490 zeros</text><text x="263" y="114" opacity="0.7">padded to 512</text>
      <text x="353" y="78" font-weight="700">header</text><text x="353" y="90">app.yaml.bak</text><text x="353" y="102">0640 · 22</text>
      <text x="443" y="78" font-weight="700">data</text><text x="443" y="90">22 + pad</text>
      <text x="533" y="78" font-weight="700">header</text><text x="533" y="90">app.log</text><text x="533" y="102">0644 · 91</text>
      <text x="623" y="78" font-weight="700">data</text><text x="623" y="90">91 + pad</text>
      <text x="713" y="78" font-weight="700">zeros</text><text x="713" y="96">end of</text>
      <text x="803" y="78" font-weight="700">zeros</text><text x="803" y="96">archive</text>
    </g>
    <text x="450" y="140" text-anchor="middle" font-size="9" fill="currentColor" opacity="0.85">9 blocks × 512 = 4,608 bytes: exactly what the script wrote and `ls -l app.tar` reported. No index: to list it, tar reads every header and seeks past every data run.</text>

    <!-- header fields -->
    <rect x="40" y="162" width="500" height="150" rx="10" fill="#c94a12" fill-opacity="0.07" stroke="#c94a12" stroke-width="1.6" stroke-linejoin="round"/>
    <text x="290" y="184" text-anchor="middle" font-size="10" font-weight="700" fill="#c94a12">INSIDE ONE 512-BYTE HEADER (ustar)</text>
    <g font-size="8.5" fill="currentColor">
      <text x="56" y="206">offset   0  name (100)      "app/etc/app.yaml"</text>
      <text x="56" y="220">offset 100  mode (8)        "0000644\0"  ← ASCII octal, not binary</text>
      <text x="56" y="234">offset 124  size (12)       "00000000026\0"  ← 22 in octal</text>
      <text x="56" y="248">offset 136  mtime (12)      seconds since 1970, octal</text>
      <text x="56" y="262">offset 148  checksum (8)    sum of all 512 bytes, with this field as 8 spaces</text>
      <text x="56" y="276">offset 156  typeflag (1)    '0' file · '5' directory · '2' symlink</text>
      <text x="56" y="290">offset 257  magic (6)       "ustar\0"   ← how `file` knows it is a tar</text>
      <text x="56" y="304" opacity="0.75">uid, gid, uname, gname, linkname, prefix fill the rest; 1979 design, still everywhere</text>
    </g>

    <!-- gzip wrapper -->
    <rect x="560" y="162" width="300" height="150" rx="10" fill="#7c5cff" fill-opacity="0.08" stroke="#7c5cff" stroke-width="1.6" stroke-linejoin="round"/>
    <text x="710" y="184" text-anchor="middle" font-size="10" font-weight="700" fill="#7c5cff">THEN gzip, SEPARATELY</text>
    <g text-anchor="middle" font-size="8.5" fill="currentColor">
      <text x="710" y="206">.tar.gz = gzip(the whole tar stream)</text>
      <text x="710" y="220">4,608 bytes → 246 bytes here</text>
      <text x="710" y="240">tar -z runs gzip for you on the way in</text>
      <text x="710" y="254">and gunzip on the way out; -j is bzip2,</text>
      <text x="710" y="268">-J is xz, --zstd is zstd</text>
      <text x="710" y="290" opacity="0.75">two formats stacked, which is why listing</text>
      <text x="710" y="304" opacity="0.75">a .tar.gz decompresses all of it first</text>
    </g>
  </g>
  <text x="450" y="342" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="10.5" fill="currentColor" opacity="0.9">tar -c creates, -x extracts, -t lists, -v narrates, -f names the file, -z gzips, -C picks the directory to extract into.</text>
  <text x="450" y="360" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="10.5" fill="currentColor" opacity="0.9">Always -t before -x. An archive extracts relative to where you stand, and can contain paths you did not expect.</text>
  <text x="450" y="382" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="9.5" fill="currentColor" opacity="0.72">Docker image layers, Debian packages and Python source distributions are all tar streams inside; you will meet this format again.</text>
</svg>
```

Compression is a separate program applied to the whole stream afterwards: `gzip` turns `app.tar` into `app.tar.gz`, and `tar -z` just runs it for you. That is why a `.tar.gz` has two extensions and why `tar -tzf` on a large archive is slow: every byte must be decompressed to reach the next header. The flags you need: `-c` create, `-x` extract, `-t` list, `-v` narrate, `-f file` (always, and always last before the filename), `-z` gzip, `-C dir` extract into `dir`. Two rules: **list before you extract** (`tar -tzf x.tar.gz | head`), because an archive extracts relative to your current directory and may contain paths like `../../etc/passwd`; and never extract an untrusted archive as root.

You will meet this format constantly without seeing it: a Docker image layer is a tar stream, a `.deb` package contains two, a Python source distribution is one. `gzip -k file` compresses a single file (keeping the original), `gunzip -c` decompresses to the screen, and `zcat` or `less` read `.gz` logs directly, which is how you read last week's rotated log without unpacking it.

### Editing: enough nano and vim to survive

On a server you will eventually need to change a file in place. `nano file` is the safe choice: type, `Ctrl+O` to save, `Ctrl+X` to leave. `vim` is on every box and is what opens when a tool consults `$EDITOR` without asking you; the four keys that get you out: `i` to start typing, `Esc` to stop, `:wq` to save and quit, `:q!` to quit without saving. Both save with the atomic replace above. Set `export EDITOR=nano` in your dotfiles if you would rather never learn the rest. For system config, `sudoedit /etc/app/app.yaml` edits a copy as you and installs it as root, which is the atomic replace again with a permission check.

## Build It

The script for this lesson is [`code/files.py`](../code/files.py). It works in a temporary directory, builds each command from the syscalls named above, and removes everything at the end; pass `--keep` to leave the directory so you can run the real `tar` on the archive it wrote. It runs on macOS and Linux.

```bash
python3 phases/01-linux-and-the-command-line/05-working-with-files/code/files.py
make shell   # then the same, with --keep, and: tar -tvf /tmp/files-*/app.tar
```

**`touch`, `mkdir -p`** are `O_CREAT` and a loop that ignores `EEXIST`:

```python
def touch(path):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT, 0o644)   # make it if it is not there
    os.close(fd)
    os.utime(path, None)                                   # None = now

def mkdir_p(path):
    for i in range(1, len(path.split("/")) + 1):
        try:
            os.mkdir("/".join(path.split("/")[:i]), 0o755)
        except FileExistsError:                            # EEXIST: fine, that is the -p
            pass
```

**`cat` and `cp`** share the loop, and `cp` adds the mode bits:

```python
def copy_fd(src_fd, dst_fd, chunk=64 * 1024):
    while True:
        buf = os.read(src_fd, chunk)
        if not buf:                                        # read returned 0: end of file
            return
        os.write(dst_fd, buf)

def cp(src, dst):
    st = os.stat(src)
    src_fd = os.open(src, os.O_RDONLY)
    dst_fd = os.open(dst, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, stat.S_IMODE(st.st_mode))
    copy_fd(src_fd, dst_fd)
```

The script times the loop against `shutil.copyfile` on 32 MiB: 36 ms versus 32 ms in the sandbox, because `copyfile` asks the kernel to do the copy with `copy_file_range` and the bytes never visit user space. On a Mac the gap is wider (23 ms versus 8 ms) for the same reason with a different syscall.

**`mv`** tries `rename` and falls back to copy-plus-unlink only on `EXDEV`:

```python
def mv(src, dst):
    try:
        os.rename(src, dst)                                # atomic: the name flips in one step
        return "rename"
    except OSError as e:
        if e.errno != errno.EXDEV:                         # 'Invalid cross-device link'
            raise
        cp(src, dst)                                       # different filesystem: copy the bytes
        os.unlink(src)                                     # then forget the old name
        return "copy+unlink"
```

```console
mv big.bin app/big.bin: rename in 87 µs; inode 186699962 -> 186699962 (same file, new name)
mv app/big.bin /dev/shm/: copy+unlink in 39 ms; inode is now 2: a new file on a different filesystem
```

**`rm`** is `unlink`, and the script holds a descriptor open across it to show what that does and does not free:

```console
unlink('app/held.bin'): exists on disk by name? False
but the open descriptor still works: fstat says 33,554,432 bytes, link count 0; read() -> 1048576 bytes
this is the 'df says full, du says empty' file from lesson 04; the blocks free when this fd closes:
   closed. Gone now, and there was never an undo.
```

Link count zero, name gone, 32 MiB still readable through the descriptor. That file is invisible to `ls`, `find` and `du`, and it is the reason a server's disk fills after someone "cleaned up" the logs.

**The atomic replace** is nine lines, and every one earns its place:

```python
def atomic_write(path, data):
    tmp = f"{path}.tmp.{os.getpid()}"                      # same directory: rename must be possible
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    os.write(fd, data)
    os.fsync(fd)                                           # on disk, not just in the page cache
    os.close(fd)
    os.rename(tmp, path)                                   # the switch: one atomic step
```

Look at the archive listing the script prints afterwards: `app.yaml` has mode `0644` while its `.bak`, copied before the replace, has `0640`. The replace created a new inode and gave it the default mode; the original's `640` was lost. A careful tool reads the old file's mode and owner with `stat` and applies them to the temp file before the rename. That is the footnote from the concept section, caught in the act.

**`tail -f`** seeks to the end and reads in a loop, while a forked child appends lines; **`tar`** builds each header field by field, computes the checksum with the field blanked, pads the data, and finishes with two zero blocks:

```python
header = b"".join(fields).ljust(512, b"\0")
checksum = sum(header)                                     # with the checksum field as 8 spaces
return header[:148] + f"{checksum:06o}\0 ".encode() + header[156:]
```

```console
app.tar is 4608 bytes = 9 blocks of 512: one header per entry, data padded, two zero blocks at the end
first header: name=b'app/etc/' mode=b'0000755\x00' size=b'00000000000\x00' magic=b'ustar\x00'
gzip -> app.tar.gz, 246 bytes: .tar.gz is exactly a tar stream fed through gzip, nothing more
```

And the real tool reads it without complaint, which is the point of writing a format by hand:

```console
$ tar -tvf /tmp/files-hnc9m2vp/app.tar
drwxr-xr-x root/root         0 2026-09-05 03:53 app/etc/
-rw-r--r-- root/root        22 2026-09-05 03:53 app/etc/app.yaml
-rw-r----- root/root        22 2026-09-05 03:53 app/etc/app.yaml.bak
-rw-r--r-- root/root        91 2026-09-05 03:53 app/app.log
$ file /tmp/files-hnc9m2vp/app.tar
/tmp/files-hnc9m2vp/app.tar: POSIX tar archive
```

## Use It

The real commands, inside `make shell`, in the order you will use them on a server. Creating and reading:

```console
$ touch notes.txt;  mkdir -p app/etc/conf.d;  printf 'port: 8080\nworkers: 4\nlog: /var/log/app\n' > app/etc/app.yaml
$ seq 1 100 > numbers.txt;  head -3 numbers.txt;  tail -2 numbers.txt;  wc numbers.txt
1
2
3
99
100
100 100 292 numbers.txt          <- lines, words, bytes
$ T=$(mktemp);  D=$(mktemp -d);  echo $T $D
/tmp/tmp.BsoORAPWMJ /tmp/tmp.S7eKL2bnih
$ truncate -s 1G sparse.img;  ls -lh sparse.img;  du -h sparse.img
-rw-r--r-- 1 root root 1.0G Sep  5 03:52 sparse.img
0       sparse.img
```

Watching the syscalls under each command with `strace` confirms the whole lesson in three lines:

```console
$ strace -e trace=renameat2,unlinkat mv s.txt t.txt
renameat2(AT_FDCWD, "s.txt", AT_FDCWD, "t.txt", RENAME_NOREPLACE) = 0
$ strace -e trace=openat cp t.txt u.txt 2>&1 | grep txt
openat(AT_FDCWD, "t.txt", O_RDONLY)     = 3
openat(AT_FDCWD, "u.txt", O_WRONLY|O_CREAT|O_EXCL, 0644) = 4
$ strace -e trace=unlinkat rm u.txt
unlinkat(AT_FDCWD, "u.txt", 0)          = 0
```

`mv` is one `renameat2`. `cp` opens the source for reading and creates the destination, then loops. `rm` is one `unlinkat`. There is nothing else in any of them.

The deleted-but-open file, seen from the outside through `/proc`:

```console
$ sleep 30 < numbers.txt &  PID=$!
$ rm numbers.txt
$ ls -l /proc/$PID/fd/0
lr-x------ 1 root root 64 Sep  5 03:52 /proc/62/fd/0 -> /tmp/demo/numbers.txt (deleted)
$ tail -1 /proc/$PID/fd/0
100
```

The kernel labels it `(deleted)`, and the data is still readable through the process's descriptor, which is also how you recover a file someone deleted while a process still had it open: copy it out of `/proc/<pid>/fd/<n>` before the process exits.

Comparing, archiving, and reading compressed logs:

```console
$ diff -u app/etc/app.yaml app2.yaml
--- app/etc/app.yaml    2020-01-01 00:00:00.000000000 +0000
+++ app2.yaml           2026-09-05 03:52:46.674595728 +0000
@@ -1,3 +1,3 @@
-port: 8080
+port: 9090
 workers: 4
 log: /var/log/app
$ tar -czf app.tar.gz app;  tar -tzf app.tar.gz;  file app.tar.gz
app/
app/etc/
app/etc/app.yaml
app.tar.gz: gzip compressed data, from Unix, original size modulo 2^32 10240
$ mkdir restore && tar -xzf app.tar.gz -C restore && ls restore
app
$ gzip -k plain.yaml;  ls -l plain.yaml*;  gunzip -c plain.yaml.gz | head -1
-rw-r----- 1 root root 40 Sep  5 03:52 plain.yaml
-rw-r----- 1 root root 69 Sep  5 03:52 plain.yaml.gz
port: 8080
```

And the replace that is safe to run against a live service, as a shell one-liner:

```console
$ printf 'port: 2\n' > cfg.yaml.tmp && mv cfg.yaml.tmp cfg.yaml;  cat cfg.yaml
port: 2
```

The `mv` is the `rename`; the `&&` means the rename only happens if the write succeeded (lesson 09). Add `sync cfg.yaml.tmp` between them on a real disk if a crash in the next second would matter.

## Ship It

The artifact for this lesson is a checklist: [`outputs/checklist-safe-file-operations.md`](../outputs/checklist-safe-file-operations.md). It is the thirty seconds before any destructive file command on a server: see the expansion first, quote and guard every variable, use `--` and absolute paths, keep a way back with `cp -a`, `mv`-to-trash or a `tar` snapshot, replace files that something reads with the atomic pattern rather than `cp` or `>`, never `cp` over a running binary, truncate live logs rather than deleting them, and the `cp`, `mv`, `rsync` and `tar` semantics that produce `dst/src/src` or extract into the wrong place.

## Think about it

1. A deploy script does `cp new-config.yaml /etc/app/app.yaml` while the service re-reads its config every 10 seconds. Describe the failure that will happen eventually, and rewrite the line so it cannot.
2. `/var/log/app/app.log` is 40 GB and the disk is full. A colleague runs `rm` on it and the disk is still full. What happened, what command shows it, and what should they have run instead?
3. `mv /data/uploads /mnt/bigdisk/uploads` on a 2 TB directory takes an hour and is interrupted at the 40-minute mark. What state are the two directories in, and why would `rsync` have been the better tool?
4. Your hand-written tar archive gave `app.yaml` mode `0644` while the original was `0640`. Which line of the script caused that, and what two syscalls would fix it?

## Key takeaways

- **Creating** is `open(O_CREAT)`: `touch`, `mkdir -p` (idempotent), `mktemp` (unique), `truncate -s` (sparse). **Reading** is one loop, read until zero, and `cat`, `head`, `tail`, `wc`, `cp`, `tee` and `tail -f` differ only in the body.
- **`cp`** copies bytes into a new inode with your ownership and today's date unless you say `-a`. `cp -r src dst` makes `dst/src` if `dst` exists. On Linux the kernel can do the copy itself.
- **`mv` is `rename(2)`**: instant, atomic, same inode, regardless of size, on one filesystem. Across filesystems it is a copy plus a delete, 400× slower here, and not atomic. It overwrites silently.
- **The atomic replace**: temp file in the same directory, `fsync`, `rename` over the target. Readers see the old file or the new one, never a partial one. `cp` and `>` truncate first and open exactly that window. It creates a new inode, so copy the mode across.
- **`rm` is `unlink`**: it removes a name. Data goes when the last name and the last open descriptor are gone; until then the space stays used and the file is invisible. Truncate live logs; do not delete them. There is no undo.
- **`tar`** is 512-byte headers with octal fields plus padded data plus two zero blocks; **gzip** is a separate wrapper, hence `.tar.gz` and `-z`. List before you extract; extract with `-C`; never as root from a stranger.
- `nano` to edit safely, `vim` to escape (`Esc`, `:q!`), `less` to read anything big, `hexdump -C` when the bytes are lying to you, and `strace` when you want to see which of these syscalls a command really made.

Next: [Users, Permissions & sudo](../06-users-groups-permissions-and-sudo/). You have been running everything as root in the sandbox, which is why `chmod 000` did nothing in lesson 01. Now the nine bits that `ls -l` has been showing you, who they apply to, and why a service gets a user of its own.
