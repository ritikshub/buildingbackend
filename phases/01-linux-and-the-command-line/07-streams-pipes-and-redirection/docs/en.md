# Streams, Pipes & Redirection: Everything Is a File Descriptor

> `ls / | wc -l` is one `pipe2`, two `clone`s, a `dup3(4, 1)` in one child and a `dup3(3, 0)` in the other, then two `execve`s. That is the whole of the pipe operator, and this lesson builds it, along with `>`, `>>`, `<`, `2>&1` and `tee`, from those syscalls. Along the way: why `2>&1 > log` loses your errors, why a pipe holds exactly **64 KiB**, how `head` kills `yes` with signal 13 and an exit status of **141**, and why a service prints nothing for minutes and then everything at once.

## The Problem

You have seen descriptors 0, 1 and 2 in every `strace`, every `ls -l /proc/<pid>/fd`, every `write(1, ...)` since lesson 01. You have typed `>` and `|` for years. And you have almost certainly been bitten by at least one of these: the log file that has the output but not the errors; the script whose `2>&1` did nothing because it was on the wrong side of the `>`; the pipeline that reported success when its first command failed; the service whose logs arrived in one lump ten minutes late; the `subprocess` call that hung forever with nothing in `top`.

Every one of those is the same small mechanism misunderstood. A process has a table of numbered slots. The shell rewires the slots of a child *between* `fork` and `exec`, so the program never knows where its bytes are going. A pipe is a kernel buffer with a slot at each end. Once you have written that rewiring yourself, the rules stop being folklore. There are about six of them and they all follow from `dup2`.

## The Concept

### Three numbers, no names

Every process starts with three open **file descriptors**: `0` is standard input, `1` is standard output, `2` is standard error. They are small integers that index a per-process table, and each entry points at something the kernel knows how to read or write: a terminal, a file, a pipe, a socket, `/dev/null`. The program does not know which. `print()` writes to `1`; `logging` writes to `2`; `input()` reads from `0`; and none of them care what is on the other end. That indifference is the entire design.

The table is inherited. A child gets a copy of its parent's table at `fork`, and `execve` leaves it alone, so `ls` writes to the same terminal the shell was writing to without any arrangement being made. Inside the sandbox, where `docker compose run -T` connects the container to pipes instead of a terminal, the table looks like this:

```console
$ ls -l /proc/self/fd
lr-x------ 1 root root 64 Sep  5 04:06 0 -> pipe:[7500267]
l-wx------ 1 root root 64 Sep  5 04:06 1 -> pipe:[7500268]
l-wx------ 1 root root 64 Sep  5 04:06 2 -> pipe:[7500269]
lr-x------ 1 root root 64 Sep  5 04:06 3 -> /proc/6/fd
```

On a terminal all three would say `/dev/pts/0`. Descriptor 3 is `ls` itself holding the directory it is listing. New descriptors always get the lowest free number, which is why `open()` in a fresh process returns 3.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 470" width="100%" style="max-width:880px" role="img" aria-label="Three snapshots of one process's descriptor table, side by side. First, as inherited from the shell: 0, 1 and 2 all point at the terminal /dev/pts/0. Second, after the shell ran cmd greater-than log 2 greater-than ampersand 1: the shell opened log as descriptor 3, called dup2 of 3 onto 1 so 1 now points at log, closed 3, then dup2 of 1 onto 2 so 2 also points at log; 0 still points at the terminal. Third, the wrong order, cmd 2 greater-than ampersand 1 greater-than log: dup2 of 1 onto 2 happened while 1 was still the terminal, so 2 points at the terminal; only then did 1 move to log; errors therefore reach the screen and not the file. A footnote says dup2 copies what a number points at right now, not a link to the number, and that the two descriptors pointing at log share one open file description and therefore one write offset, so the lines interleave correctly.">
  <defs>
    <marker id="p1l07a-ar" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker>
  </defs>
  <text x="450" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">The descriptor table, and what one redirection does to it (order included)</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <!-- panel 1 -->
    <rect x="30" y="50" width="260" height="250" rx="10" fill="#7f7f7f" fill-opacity="0.10" stroke="#7f7f7f" stroke-width="1.7" stroke-linejoin="round"/>
    <text x="160" y="72" text-anchor="middle" font-size="10" font-weight="700" fill="currentColor">1 · AS INHERITED</text>
    <text x="160" y="86" text-anchor="middle" font-size="8" fill="currentColor" opacity="0.7">$ cmd</text>
    <g font-size="9.5" fill="currentColor">
      <text x="50" y="120">fd 0</text><text x="50" y="150">fd 1</text><text x="50" y="180">fd 2</text>
    </g>
    <g fill="none" stroke="currentColor" stroke-width="1.5">
      <path d="M90 116 L170 116" marker-end="url(#p1l07a-ar)"/>
      <path d="M90 146 L170 146" marker-end="url(#p1l07a-ar)"/>
      <path d="M90 176 L170 176" marker-end="url(#p1l07a-ar)"/>
    </g>
    <rect x="178" y="100" width="96" height="92" rx="7" fill="#7c5cff" fill-opacity="0.12" stroke="#7c5cff" stroke-width="1.3"/>
    <text x="226" y="150" text-anchor="middle" font-size="9" fill="#7c5cff" font-weight="700">/dev/pts/0</text>
    <text x="226" y="164" text-anchor="middle" font-size="7.5" fill="currentColor" opacity="0.7">the terminal</text>
    <text x="160" y="230" text-anchor="middle" font-size="8.5" fill="currentColor">read from 0, write to 1 and 2:</text>
    <text x="160" y="244" text-anchor="middle" font-size="8.5" fill="currentColor">all the same terminal</text>
    <text x="160" y="272" text-anchor="middle" font-size="8" fill="currentColor" opacity="0.7">the program never sees the names;</text>
    <text x="160" y="284" text-anchor="middle" font-size="8" fill="currentColor" opacity="0.7">only the numbers</text>

    <!-- panel 2 -->
    <rect x="320" y="50" width="260" height="250" rx="10" fill="#0fa07f" fill-opacity="0.08" stroke="#0fa07f" stroke-width="1.7" stroke-linejoin="round"/>
    <text x="450" y="72" text-anchor="middle" font-size="10" font-weight="700" fill="#0fa07f">2 · > log 2>&amp;1  (right)</text>
    <text x="450" y="86" text-anchor="middle" font-size="8" fill="currentColor" opacity="0.7">open(log)=3 · dup2(3,1) · close(3) · dup2(1,2)</text>
    <g font-size="9.5" fill="currentColor">
      <text x="340" y="120">fd 0</text><text x="340" y="150">fd 1</text><text x="340" y="180">fd 2</text>
    </g>
    <g fill="none" stroke="currentColor" stroke-width="1.5">
      <path d="M380 116 L460 116" marker-end="url(#p1l07a-ar)"/>
      <path d="M380 146 L460 166" marker-end="url(#p1l07a-ar)"/>
      <path d="M380 176 L460 172" marker-end="url(#p1l07a-ar)"/>
    </g>
    <rect x="468" y="100" width="96" height="32" rx="7" fill="#7c5cff" fill-opacity="0.12" stroke="#7c5cff" stroke-width="1.3"/>
    <text x="516" y="120" text-anchor="middle" font-size="9" fill="#7c5cff" font-weight="700">/dev/pts/0</text>
    <rect x="468" y="150" width="96" height="42" rx="7" fill="#0fa07f" fill-opacity="0.14" stroke="#0fa07f" stroke-width="1.3"/>
    <text x="516" y="170" text-anchor="middle" font-size="9" fill="#0fa07f" font-weight="700">log</text>
    <text x="516" y="184" text-anchor="middle" font-size="7.5" fill="currentColor" opacity="0.7">one offset, shared</text>
    <text x="450" y="230" text-anchor="middle" font-size="8.5" fill="currentColor">1 moved to the file FIRST,</text>
    <text x="450" y="244" text-anchor="middle" font-size="8.5" fill="currentColor">then 2 was copied from 1</text>
    <text x="450" y="272" text-anchor="middle" font-size="8" fill="currentColor" opacity="0.7">both streams land in log,</text>
    <text x="450" y="284" text-anchor="middle" font-size="8" fill="currentColor" opacity="0.7">interleaved in write order</text>

    <!-- panel 3 -->
    <rect x="610" y="50" width="260" height="250" rx="10" fill="#d64545" fill-opacity="0.07" stroke="#d64545" stroke-width="1.7" stroke-linejoin="round"/>
    <text x="740" y="72" text-anchor="middle" font-size="10" font-weight="700" fill="#d64545">3 · 2>&amp;1 > log  (wrong)</text>
    <text x="740" y="86" text-anchor="middle" font-size="8" fill="currentColor" opacity="0.7">dup2(1,2) · open(log)=3 · dup2(3,1) · close(3)</text>
    <g font-size="9.5" fill="currentColor">
      <text x="630" y="120">fd 0</text><text x="630" y="150">fd 1</text><text x="630" y="180">fd 2</text>
    </g>
    <g fill="none" stroke="currentColor" stroke-width="1.5">
      <path d="M670 116 L750 116" marker-end="url(#p1l07a-ar)"/>
      <path d="M670 146 L750 172" marker-end="url(#p1l07a-ar)"/>
      <path d="M670 176 L750 122" marker-end="url(#p1l07a-ar)"/>
    </g>
    <rect x="758" y="100" width="96" height="42" rx="7" fill="#7c5cff" fill-opacity="0.12" stroke="#7c5cff" stroke-width="1.3"/>
    <text x="806" y="120" text-anchor="middle" font-size="9" fill="#7c5cff" font-weight="700">/dev/pts/0</text>
    <text x="806" y="134" text-anchor="middle" font-size="7.5" fill="currentColor" opacity="0.7">errors go here</text>
    <rect x="758" y="156" width="96" height="32" rx="7" fill="#0fa07f" fill-opacity="0.14" stroke="#0fa07f" stroke-width="1.3"/>
    <text x="806" y="176" text-anchor="middle" font-size="9" fill="#0fa07f" font-weight="700">log</text>
    <text x="740" y="230" text-anchor="middle" font-size="8.5" fill="currentColor">2 was copied from 1 while 1</text>
    <text x="740" y="244" text-anchor="middle" font-size="8.5" fill="currentColor">was STILL the terminal</text>
    <text x="740" y="272" text-anchor="middle" font-size="8" fill="currentColor" opacity="0.7">stdout in the file, stderr on</text>
    <text x="740" y="284" text-anchor="middle" font-size="8" fill="currentColor" opacity="0.7">the screen: the classic lost error</text>

    <rect x="30" y="322" width="840" height="90" rx="10" fill="#e0930f" fill-opacity="0.08" stroke="#e0930f" stroke-width="1.6" stroke-linejoin="round"/>
    <text x="450" y="344" text-anchor="middle" font-size="10" font-weight="700" fill="#e0930f">dup2(a, b): make b point at whatever a points at RIGHT NOW</text>
    <g text-anchor="middle" font-size="8.5" fill="currentColor">
      <text x="450" y="364">it is a copy of the pointer, not a link to the number. Redirections are applied left to right, each one a dup2, in the child, before exec.</text>
      <text x="450" y="380">Two numbers pointing at the same file share one "open file description": one offset, so both streams append in order rather than overwriting.</text>
      <text x="450" y="400" opacity="0.8">> truncates the file first (O_TRUNC); >> opens it with O_APPEND, so every write lands at the end even with several writers.</text>
    </g>
  </g>
  <text x="450" y="446" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="10.5" fill="currentColor" opacity="0.9">Read the redirections left to right and picture the table after each one. That is all the shell does, and all you need to predict it.</text>
</svg>
```

### Redirection is dup2 between fork and exec

Lesson 03 said the gap between `fork` and `exec` is where the shell sets things up for the child. Redirection is what it sets up. For `cmd < in > out`, the child, before it becomes `cmd`, opens `in` and calls `dup2(fd, 0)`, opens `out` with `O_TRUNC` and calls `dup2(fd, 1)`, closes the spare numbers, and only then calls `execve`. `cmd` wakes up with its slots already rewired; `wc -l < in.txt` never sees a filename, and `wc` did not need any code to support redirection. No program does.

The operators are all the same call with different arguments:

| you write | the child does | meaning |
|---|---|---|
| `< file` | `dup2(open(file, O_RDONLY), 0)` | stdin from the file |
| `> file` | `dup2(open(file, O_WRONLY\|O_CREAT\|O_TRUNC), 1)` | stdout to the file, emptied first |
| `>> file` | `dup2(open(file, ...\|O_APPEND), 1)` | stdout appended to the file |
| `2> file` | the same, onto `2` | stderr to the file |
| `2>&1` | `dup2(1, 2)` | stderr goes wherever stdout goes *now* |
| `&> file` | `> file 2>&1`, bash shorthand | both to the file |
| `1>&2` | `dup2(2, 1)` | stdout onto stderr (for error messages in scripts) |
| `> /dev/null` | the same, onto a device that discards | throw it away |

The one rule people get wrong follows from `dup2` copying a pointer, not creating a link: **redirections are applied left to right, and `2>&1` copies what `1` points at at that moment.** So `> log 2>&1` first moves `1` to the file and then makes `2` a copy of it (both in the file), while `2>&1 > log` makes `2` a copy of `1` while `1` is still the terminal, then moves only `1` (errors on screen, output in the file). The sandbox, both ways:

```console
$ ls /nope f.txt > both.txt 2>&1;  cat both.txt
ls: cannot access '/nope': No such file or directory
f.txt
$ ls /nope f.txt 2>&1 > only.txt;  cat only.txt
ls: cannot access '/nope': No such file or directory     <- printed to the screen by ls
f.txt                                                   <- the only line in only.txt
```

Three more forms of stdin worth knowing. A **here-document** feeds the lines up to a marker as stdin, with variables expanded unless the marker is quoted; a **here-string** feeds one string; and `exec 3< file` opens a descriptor *in the shell itself*, for scripts that read one file while stdin is busy:

```console
$ cat <<MARK
a here-document, with \$HOME expanded: $HOME
MARK
a here-document, with $HOME expanded: /root
$ tr a-z A-Z <<< "a here-string"
A HERE-STRING
$ exec 3< f.txt;  read -r first <&3;  echo "fd 3 first line: $first";  ls -l /proc/$$/fd/3;  exec 3<&-
fd 3 first line: hello
lr-x------ 1 root root 64 Sep  5 04:06 /proc/1/fd/3 -> /tmp/f.txt
```

### A pipe is one buffer with two ends

`pipe(2)` asks the kernel for a buffer and returns two descriptors: a read end and a write end. Bytes written to one come out of the other, in order, and that is the whole object. A **pipeline** `a | b | c` is three children and two pipes: the shell creates a pipe, forks `a` with its `1` replaced by the write end, forks `b` with its `0` replaced by the read end, and so on down the line. `strace` on bash shows exactly that:

```console
$ strace -f -e trace=pipe2,dup3,clone,execve -o /tmp/p.txt bash -c 'ls / | wc -l'
33    pipe2([3, 4], 0)                  = 0                  <- one pipe: read end 3, write end 4
33    clone(...) = 34                                        <- fork for ls
33    clone(...) = 35                                        <- fork for wc
34    dup3(4, 1, 0)                     = 1                  <- ls: stdout is now the write end
35    dup3(3, 0, 0)                     = 0                  <- wc: stdin is now the read end
34    execve("/usr/bin/ls", ["ls", "/"], ...) = 0
35    execve("/usr/bin/wc", ["wc", "-l"], ...) = 0
```

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 440" width="100%" style="max-width:880px" role="img" aria-label="The wiring of ls slash pipe wc minus l. The shell, PID 33, calls pipe2 and receives descriptors 3, the read end, and 4, the write end, both pointing at one 64-kilobyte kernel buffer drawn in the centre. It forks twice. In child 34, dup3 of 4 onto 1 makes stdout the write end; the child closes 3 and 4 and execs ls. In child 35, dup3 of 3 onto 0 makes stdin the read end; it closes 3 and 4 and execs wc. The shell then closes its own 3 and 4 and waits. Arrows show ls writing into the buffer and wc reading from it. A note explains that the pipe delivers end of file to wc only when every write end is closed, which is why the shell and wc must close their copies, and that the shell holds no pipe ends after the setup so that it cannot accidentally keep the pipeline alive.">
  <defs>
    <marker id="p1l07b-ar" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker>
    <marker id="p1l07b-arg" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#0fa07f"/></marker>
    <marker id="p1l07b-aro" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#c94a12"/></marker>
  </defs>
  <text x="450" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">ls / | wc -l: one pipe, two children, one dup each, then exec</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <!-- shell -->
    <rect x="330" y="50" width="240" height="70" rx="10" fill="#c94a12" fill-opacity="0.10" stroke="#c94a12" stroke-width="1.8" stroke-linejoin="round"/>
    <text x="450" y="70" text-anchor="middle" font-size="10.5" font-weight="700" fill="#c94a12">the shell · pid 33</text>
    <text x="450" y="86" text-anchor="middle" font-size="8.5" fill="currentColor">pipe2() → [3, 4]  · clone() ×2</text>
    <text x="450" y="100" text-anchor="middle" font-size="8.5" fill="currentColor">then close(3), close(4), wait4() ×2</text>
    <text x="450" y="112" text-anchor="middle" font-size="7.5" fill="currentColor" opacity="0.7">holds no pipe end once the children exist</text>
    <!-- the pipe -->
    <rect x="330" y="200" width="240" height="60" rx="10" fill="#0fa07f" fill-opacity="0.14" stroke="#0fa07f" stroke-width="2.2" stroke-linejoin="round"/>
    <text x="450" y="222" text-anchor="middle" font-size="10.5" font-weight="700" fill="#0fa07f">THE PIPE · kernel buffer, 64 KiB</text>
    <text x="450" y="238" text-anchor="middle" font-size="8.5" fill="currentColor">bytes in at the write end, out at the read end, in order</text>
    <text x="450" y="251" text-anchor="middle" font-size="7.5" fill="currentColor" opacity="0.7">full → writers sleep · empty → readers sleep · no writers left → EOF</text>
    <!-- ls -->
    <rect x="40" y="170" width="230" height="120" rx="10" fill="#7c5cff" fill-opacity="0.10" stroke="#7c5cff" stroke-width="1.8" stroke-linejoin="round"/>
    <text x="155" y="192" text-anchor="middle" font-size="10.5" font-weight="700" fill="#7c5cff">child 34 → ls /</text>
    <g text-anchor="middle" font-size="8.5" fill="currentColor">
      <text x="155" y="212">dup3(4, 1): stdout = write end</text>
      <text x="155" y="226">close(3); close(4)</text>
      <text x="155" y="240">execve("/usr/bin/ls")</text>
      <text x="155" y="262" opacity="0.75">ls writes to fd 1 as always;</text>
      <text x="155" y="276" opacity="0.75">it has no idea it is a pipe</text>
    </g>
    <!-- wc -->
    <rect x="630" y="170" width="230" height="120" rx="10" fill="#7c5cff" fill-opacity="0.10" stroke="#7c5cff" stroke-width="1.8" stroke-linejoin="round"/>
    <text x="745" y="192" text-anchor="middle" font-size="10.5" font-weight="700" fill="#7c5cff">child 35 → wc -l</text>
    <g text-anchor="middle" font-size="8.5" fill="currentColor">
      <text x="745" y="212">dup3(3, 0): stdin = read end</text>
      <text x="745" y="226">close(3); close(4)</text>
      <text x="745" y="240">execve("/usr/bin/wc")</text>
      <text x="745" y="262" opacity="0.75">wc reads fd 0 until it returns 0,</text>
      <text x="745" y="276" opacity="0.75">which happens when ls exits</text>
    </g>
    <!-- arrows -->
    <g fill="none" stroke="#c94a12" stroke-width="1.6">
      <path d="M380 122 L200 166" marker-end="url(#p1l07b-aro)"/>
      <path d="M520 122 L700 166" marker-end="url(#p1l07b-aro)"/>
    </g>
    <text x="270" y="140" text-anchor="middle" font-size="8" fill="#c94a12">fork</text>
    <text x="630" y="140" text-anchor="middle" font-size="8" fill="#c94a12">fork</text>
    <path d="M272 230 L326 230" fill="none" stroke="#0fa07f" stroke-width="2.2" marker-end="url(#p1l07b-arg)"/>
    <text x="299" y="222" text-anchor="middle" font-size="8" fill="#0fa07f">write(1)</text>
    <path d="M574 230 L628 230" fill="none" stroke="#0fa07f" stroke-width="2.2" marker-end="url(#p1l07b-arg)"/>
    <text x="601" y="222" text-anchor="middle" font-size="8" fill="#0fa07f">read(0)</text>
    <!-- the EOF rule -->
    <rect x="40" y="318" width="820" height="70" rx="10" fill="#e0930f" fill-opacity="0.08" stroke="#e0930f" stroke-width="1.6" stroke-linejoin="round"/>
    <text x="450" y="340" text-anchor="middle" font-size="10" font-weight="700" fill="#e0930f">THE CLOSE RULE: EOF arrives only when EVERY write end is closed</text>
    <g text-anchor="middle" font-size="8.5" fill="currentColor">
      <text x="450" y="360">the shell closes its 3 and 4; wc closes its copy of 4. If either kept a write end, wc would wait forever after ls finished.</text>
      <text x="450" y="376" opacity="0.8">A forgotten descriptor in some other process is the usual reason a pipeline "hangs at the end" (the runbook's section 4).</text>
    </g>
  </g>
  <text x="450" y="416" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="10.5" fill="currentColor" opacity="0.9">Neither program was written to work in a pipeline. They read 0 and write 1; the shell decided what those were.</text>
</svg>
```

Two details make or break a pipeline implementation, and both are in the diagram. **The shell must close its own copies** of both ends after forking, and each child must close the end it does not use. EOF on a pipe is delivered only when *every* write end in *every* process is closed; a single forgotten copy keeps the reader waiting forever. And the **parent never reads or writes the pipe**; it only wires and waits. You can see two processes sharing one pipe from the outside:

```console
$ sleep 2 | sleep 2 &
$ ls -l /proc/50/fd /proc/51/fd | grep pipe
/proc/50/fd: 1 -> pipe:[7503244]          <- the first sleep's stdout
/proc/51/fd: 0 -> pipe:[7503244]          <- the second sleep's stdin: the same inode
```

### Capacity, backpressure, and why pipes never lose data

A pipe's buffer is **64 KiB** by default on Linux (`/proc/sys/fs/pipe-max-size` caps how large a program may make it). When it is full, a `write` on the write end **blocks** until a reader drains some; when it is empty, a `read` blocks until a writer adds some. Nothing is dropped and nothing accumulates beyond 64 KiB. The **Build It** script fills a pipe with non-blocking writes and gets exactly 65,536 bytes before `EAGAIN`, then times a fast writer feeding a slow reader: 1 MiB took 727 ms, because the writer spent almost all of it asleep in `write()`.

That is **backpressure**, and it comes free with every pipe: the producer runs at the consumer's pace, automatically, with bounded memory. Phase 7 and Phase 9 spend whole lessons building this property into queues and servers, and the reason it is hard there is that a network has no pipe in the middle to do it for you.

### EOF, SIGPIPE, and the exit status of a pipeline

A reader learns the writer is gone by `read` returning 0. A writer learns the reader is gone the hard way: the kernel sends it **`SIGPIPE`** (signal 13) on the next `write`, and the default action is to die. That is how `yes | head -2` ends: `head` prints two lines and exits, `yes` writes once more, and the kernel kills it. The shell reports it as 128 + 13:

```console
$ yes | head -1 > /dev/null;  echo "${PIPESTATUS[0]}"
141
```

Which raises the question of what a pipeline's exit status *is*. By default it is the **last** command's: `false | true` succeeds. `PIPESTATUS` holds every stage; `set -o pipefail` makes the pipeline fail if any stage did. Both matter in scripts (lesson 09), and `pipefail` turns the healthy `SIGPIPE` above into a failure you have to decide about:

```console
$ false | true;  echo $?;  echo "${PIPESTATUS[@]}"
0
1 0
$ set -o pipefail;  false | true;  echo $?
1
```

One trap sits in Python specifically. Python **ignores** `SIGPIPE` at startup so that a `BrokenPipeError` can be raised instead of the process dying. That disposition is inherited across `exec`, so a program started by Python without care does not die on `SIGPIPE`; it gets `EPIPE`, prints `Broken pipe`, and exits 1. The script restores the default in each child before `execvp`, exactly as `subprocess` does with `restore_signals=True`.

### Buffering: the thing that eats logs

Between `print()` and the kernel there is a second buffer, in user space, that this lesson has been quietly flushing since lesson 01. The C library and every language runtime decide how to use it by asking one question: **is descriptor 1 a terminal?** If yes, flush at every newline, so you see lines as they happen. If no (a pipe, a file, a socket), fill a 4 to 8 KiB block and flush only when it is full or at exit. Descriptor 2 is never buffered.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 400" width="100%" style="max-width:880px" role="img" aria-label="Two buffers between a print call and whoever reads the output. First, in user space, the stdio buffer inside the process, 8 kilobytes: on a terminal it is flushed at every newline, on a pipe or file only when full or at exit, and it is lost entirely if the process is killed with SIGKILL. Second, in the kernel, the pipe buffer, 64 kilobytes: full means the writer sleeps, empty means the reader sleeps, and it is never lost. Below, the consequences: in a terminal you see every line immediately; under systemd, docker or a pipe to tee, nothing appears until 8 kilobytes have accumulated or the process exits; a crash loses the last lines; and the fixes, python3 -u, PYTHONUNBUFFERED=1, flush=True, logging to stderr, or stdbuf -oL for a program you cannot change. A note says the sandbox sets PYTHONUNBUFFERED=1 in its Dockerfile, which is why Python in it never shows the problem while grep does.">
  <defs>
    <marker id="p1l07c-ar" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker>
  </defs>
  <text x="450" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">Two buffers between print() and the reader: only one of them is the kernel's</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <rect x="40" y="60" width="180" height="90" rx="10" fill="#7c5cff" fill-opacity="0.10" stroke="#7c5cff" stroke-width="1.7" stroke-linejoin="round"/>
    <text x="130" y="84" text-anchor="middle" font-size="10" font-weight="700" fill="#7c5cff">print("line")</text>
    <text x="130" y="102" text-anchor="middle" font-size="8.5" fill="currentColor">your code</text>
    <text x="130" y="118" text-anchor="middle" font-size="8" fill="currentColor" opacity="0.7">believes the line</text>
    <text x="130" y="130" text-anchor="middle" font-size="8" fill="currentColor" opacity="0.7">has been written</text>

    <rect x="270" y="60" width="240" height="90" rx="10" fill="#e0930f" fill-opacity="0.12" stroke="#e0930f" stroke-width="2" stroke-linejoin="round"/>
    <text x="390" y="82" text-anchor="middle" font-size="10" font-weight="700" fill="#e0930f">THE STDIO BUFFER · user space</text>
    <text x="390" y="98" text-anchor="middle" font-size="8.5" fill="currentColor">8 KiB inside the process</text>
    <text x="390" y="112" text-anchor="middle" font-size="8.5" fill="currentColor">terminal: flush at every newline</text>
    <text x="390" y="126" text-anchor="middle" font-size="8.5" fill="currentColor">pipe or file: flush when full, or at exit</text>
    <text x="390" y="140" text-anchor="middle" font-size="8" fill="#d64545" font-weight="700">SIGKILL: lost</text>

    <rect x="560" y="60" width="200" height="90" rx="10" fill="#0fa07f" fill-opacity="0.12" stroke="#0fa07f" stroke-width="2" stroke-linejoin="round"/>
    <text x="660" y="82" text-anchor="middle" font-size="10" font-weight="700" fill="#0fa07f">THE PIPE · kernel</text>
    <text x="660" y="98" text-anchor="middle" font-size="8.5" fill="currentColor">64 KiB</text>
    <text x="660" y="112" text-anchor="middle" font-size="8.5" fill="currentColor">full: writer sleeps</text>
    <text x="660" y="126" text-anchor="middle" font-size="8.5" fill="currentColor">empty: reader sleeps</text>
    <text x="660" y="140" text-anchor="middle" font-size="8" fill="#0fa07f" font-weight="700">never lost</text>

    <rect x="800" y="60" width="70" height="90" rx="10" fill="#7f7f7f" fill-opacity="0.12" stroke="#7f7f7f" stroke-width="1.7" stroke-linejoin="round"/>
    <text x="835" y="100" text-anchor="middle" font-size="9" font-weight="700" fill="currentColor">reader</text>
    <text x="835" y="116" text-anchor="middle" font-size="7.5" fill="currentColor" opacity="0.7">tee, journald,</text>
    <text x="835" y="128" text-anchor="middle" font-size="7.5" fill="currentColor" opacity="0.7">docker logs</text>

    <g fill="none" stroke="currentColor" stroke-width="1.6">
      <path d="M222 105 L266 105" marker-end="url(#p1l07c-ar)"/>
      <path d="M512 105 L556 105" marker-end="url(#p1l07c-ar)"/>
      <path d="M762 105 L796 105" marker-end="url(#p1l07c-ar)"/>
    </g>
    <text x="244" y="97" text-anchor="middle" font-size="7.5" fill="currentColor" opacity="0.8">no syscall</text>
    <text x="534" y="97" text-anchor="middle" font-size="7.5" fill="currentColor" opacity="0.8">write(1)</text>

    <rect x="40" y="180" width="830" height="150" rx="10" fill="#7f7f7f" fill-opacity="0.08" stroke="#7f7f7f" stroke-width="1.5" stroke-linejoin="round"/>
    <text x="455" y="202" text-anchor="middle" font-size="10" font-weight="700" fill="currentColor">WHAT YOU SEE</text>
    <g font-size="8.5" fill="currentColor">
      <text x="56" y="224" font-weight="700" fill="#0fa07f">in a terminal:</text><text x="200" y="224">every line, immediately (isatty(1) is true, so the runtime flushes on newline)</text>
      <text x="56" y="242" font-weight="700" fill="#d64545">under systemd, Docker, | tee:</text><text x="290" y="242">nothing for minutes, then a lump at 8 KiB or at exit. The program is fine; the buffer is full of your logs</text>
      <text x="56" y="260" font-weight="700" fill="#d64545">after a crash or kill -9:</text><text x="270" y="260">the last lines are simply gone; they never reached the kernel</text>
      <text x="56" y="284" font-weight="700">fixes:</text><text x="120" y="284">python3 -u · PYTHONUNBUFFERED=1 · print(..., flush=True) · log to stderr (never buffered)</text>
      <text x="120" y="300">stdbuf -oL cmd for a program you cannot change · a pty (script, unbuffer) for one that insists on a terminal</text>
      <text x="56" y="320" opacity="0.75">the sandbox's Dockerfile sets PYTHONUNBUFFERED=1, which is why Python never shows this there and grep does (see Use It)</text>
    </g>
  </g>
  <text x="450" y="364" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="10.5" fill="currentColor" opacity="0.9">"It prints in my terminal and not in production" is always this. The pipe is honest; the buffer in front of it is not.</text>
  <text x="450" y="384" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="9.5" fill="currentColor" opacity="0.72">Lesson 01 measured why the buffer exists: 6x fewer crossings. Lesson 11 is where you decide where a service's stdout goes.</text>
</svg>
```

So a program that prints a line every second shows one line a second in your terminal and nothing at all under `systemd`, Docker or `| tee` until 8 KiB have piled up or it exits. If it is then killed with `SIGKILL`, the buffer's contents never existed. The fixes are on the diagram; the point is to recognise the symptom, because "it logs fine locally" is this every time. The sandbox sets `PYTHONUNBUFFERED=1` in its Dockerfile so that Python never shows the problem inside it; `grep` still does, and **Use It** catches it in the act.

### tee, xargs, and the rest of the plumbing

`tee` writes its stdin to a file *and* to stdout, so you can log and watch at once: `cmd 2>&1 | tee run.log`. `xargs` turns lines on stdin into arguments for a command, which is how the output of `find` or `grep -l` becomes the input of `rm`, `wc` or `gzip`; `xargs -n1` runs once per line, and `find -print0 | xargs -0` survives filenames with spaces. `mkfifo` creates a **named pipe**, a pipe with a path in the filesystem so that two unrelated processes can meet at it. And bash's `<(cmd)` **process substitution** gives you a `/dev/fd/N` path that reads from a command, so that `diff <(sort a) <(sort b)` works on programs that insist on filenames.

Behind all of it is the design decision that made Unix what it is: programs read text from `0`, write text to `1`, complain on `2`, and know nothing else. That is what lets `sort | uniq -c | sort -rn` count anything, and it is the subject of lesson 08.

## Build It

The script for this lesson is [`code/pipes.py`](../code/pipes.py). It is the mini shell from lesson 03 given redirection and pipelines, plus experiments on the pipe itself. It runs on macOS and Linux:

```bash
python3 phases/01-linux-and-the-command-line/07-streams-pipes-and-redirection/code/pipes.py
```

**Redirection** is a parse into an ordered list, then `dup2` per entry in the child. Note that `2>&1` is a single `dup2(1, 2)` with no `open`, which is the entire reason order matters:

```python
def apply_redirections(redirs):
    """Runs IN THE CHILD, after fork and before exec: rewire 0, 1 and 2."""
    for op, target in redirs:
        if op == "<":
            fd = os.open(target, os.O_RDONLY)
            os.dup2(fd, 0); os.close(fd)                      # 0 now IS the file
        elif op in (">", "2>"):
            fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
            os.dup2(fd, 1 if op == ">" else 2); os.close(fd)
        elif op == "2>&1":
            os.dup2(1, 2)                                     # 2 becomes a copy of whatever 1 is NOW
```

**The pipeline** is the diagram as code. Read the four `close` calls; each one is a hang if omitted:

```python
for i, (argv, redirs) in enumerate(stages):
    last = i == len(stages) - 1
    if not last:
        read_end, write_end = os.pipe()                       # one kernel buffer, two descriptors
    pid = os.fork()
    if pid == 0:
        if prev_read is not None:
            os.dup2(prev_read, 0); os.close(prev_read)        # my stdin is the previous pipe
        if not last:
            os.dup2(write_end, 1); os.close(write_end)        # my stdout is the next pipe
            os.close(read_end)                                # not mine; a stray copy would keep the pipe alive
        apply_redirections(redirs)                            # explicit < > 2>&1 come AFTER the pipe wiring
        signal.signal(signal.SIGPIPE, signal.SIG_DFL)         # Python ignores SIGPIPE; a real program must not
        os.execvp(argv[0], argv)
    pids.append(pid)
    if prev_read is not None:
        os.close(prev_read)                                   # the parent holds no pipe ends ...
    if not last:
        os.close(write_end)                                   # ... otherwise readers would never see EOF
        prev_read = read_end
```

Run it and read the transcript against the concepts. The order proof, with the errors landing in the file one way and on the screen the other:

```console
$ ls /nope in.txt > both.txt 2>&1
   both.txt: ls: cannot access '/nope': No such file or directory | in.txt
$ ls /nope in.txt 2>&1 > only-stdout.txt
ls: cannot access '/nope': No such file or directory
   only-stdout.txt: in.txt   <- the error line went to the screen above, not the file
```

A four-stage pipeline with its `PIPESTATUS`, the capacity measurement, backpressure, and `SIGPIPE`:

```console
$ printf 'b\na\nc\na\n' | sort | uniq -c | sort -rn
      2 a
      1 c
      1 b
   four children, three pipes, exit statuses [0, 0, 0, 0]

   the pipe accepted 65,536 bytes (64 KiB) before it was full
   writing 1 MiB into a pipe read at ~1.3 MiB/s took 727 ms: the writer was parked in write() each time the pipe was full

$ yes | head -2
   exit statuses [141, 0]: head 0, yes 141 = 128 + 13 = killed by SIGPIPE (signal 13)
```

And the descriptor table of a child, printed after each `dup2`, which is the first diagram happening in front of you:

```console
   child before any dup2: 0->pipe:[7503391]  1->pipe:[7503392]  2->pipe:[7503392]  3->/tmp/pipes-7au4ojl8/trace.txt
   after dup2(file, 1):   0->pipe:[7503391]  1->/tmp/.../trace.txt  2->pipe:[7503392]  3->/tmp/.../trace.txt
   after dup2(1, 2):      0->pipe:[7503391]  1->/tmp/.../trace.txt  2->/tmp/.../trace.txt  3->/tmp/.../trace.txt
```

Delete the `SIGPIPE` line in the child and run again: `yes` prints `yes: stdout: Broken pipe` and exits 1 instead of 141, because it inherited Python's ignored signal. That one line is the difference between a program that dies quietly when its reader leaves and one that logs an error and carries on.

## Use It

Everything above, in bash, inside `make shell`. The forms of redirection, and the file each one produces:

```console
$ echo hello > f.txt;  echo again >> f.txt;  cat f.txt
hello
again
$ ls /nope f.txt > out.txt 2> err.txt;  cat out.txt;  cat err.txt
f.txt
ls: cannot access '/nope': No such file or directory
$ ls /nope f.txt &> amp.txt;  cat amp.txt              # bash shorthand for > amp.txt 2>&1
ls: cannot access '/nope': No such file or directory
f.txt
$ ls /nope 2> /dev/null;  echo "exit: $?"              # the error is gone; the status is not
exit: 2
```

Pipes doing the work they were invented for, and `tee` keeping a copy:

```console
$ seq 1 10 | grep 5
5
$ printf 'b\na\nc\na\n' | sort | uniq -c | sort -rn
      2 a
      1 c
      1 b
$ seq 1 3 | tee copy.txt | wc -l;  cat copy.txt
3
1
2
3
$ ls /nope f.txt 2>&1 | wc -l;  ls /nope f.txt | wc -l   # stderr into the pipe, then not
2
ls: cannot access '/nope': No such file or directory
1
```

Exit statuses, three ways, and the signal that ends an infinite producer:

```console
$ false | true;  echo "status: $?";  false | true;  echo "PIPESTATUS: ${PIPESTATUS[@]}"
status: 0
PIPESTATUS: 1 0
$ set -o pipefail;  false | true;  echo "with pipefail: $?";  set +o pipefail
with pipefail: 1
$ yes | head -1 > /dev/null;  echo "yes exit: ${PIPESTATUS[0]}"
yes exit: 141
```

The buffer that eats logs, caught with a timestamp on each line as it arrives. `grep`, a C program, holds its output until exit when stdout is a pipe; `stdbuf -oL` makes it flush per line:

```console
$ (echo a; sleep 0.3; echo a) | grep a | ts        # ts = a tiny Python loop printing arrival times
0.3s a
0.3s a                      <- both lines arrived together, when grep exited
$ (echo a; sleep 0.3; echo a) | stdbuf -oL grep a | ts
0.0s a
0.3s a                      <- line-buffered: each line as it happened
```

(Python in the sandbox shows lines immediately even without `-u`, because the Dockerfile sets `PYTHONUNBUFFERED=1`; unset it, or run on your Mac, and `python3 -c 'print(...)' | cat` waits until exit.) Finally `xargs`, a named pipe, and a descriptor opened in the shell:

```console
$ printf 'a b\nc\n' | xargs -n1 echo item
item a
item b
item c
$ find /etc -name '*.conf' | head -3 | xargs wc -l | tail -1
 149 total
$ mkfifo myfifo;  (cat myfifo &);  echo "through a named pipe" > myfifo;  ls -l myfifo
through a named pipe
prw-r--r-- 1 root root 0 Sep  5 04:06 myfifo         <- p: a pipe with a name
```

## Ship It

The artifact for this lesson is a runbook: [`outputs/runbook-where-did-my-output-go.md`](../outputs/runbook-where-did-my-output-go.md). It is organised by symptom: the error that is not in the log (stderr, or the order of redirections); output that arrives late or only at exit (block buffering, and the lines a crash loses); a pipeline that reports success when a stage failed (`PIPESTATUS`, `pipefail`, exit 141); a program that hangs (a full pipe with nobody reading, a reader waiting for an EOF that a stray descriptor withholds, a prompt on a stdin that is `/dev/null`); an empty file (`>` truncates, `sort f > f`); and descriptors leaking into children. Each symptom has the one-line check and the fix, and the last section is the five commands that answer most of it.

## Think about it

1. `python3 server.py > server.log 2>&1 &` in a terminal, then you log out. What happens to the process, why, and what does lesson 03's first diagram have to do with it?
2. `subprocess.run(["cmd"], stdout=PIPE, stderr=PIPE)` hangs when `cmd` prints 100 KB of warnings, and works when it prints 10 KB. Explain with the number 65,536 and name the fix.
3. `cat big.log | grep ERROR | head -1` returns instantly on a 50 GB file. Which signal made that possible, which process received it, and why does `pipefail` complain?
4. A service logs with `print()`. Its operator sees lines in `journalctl` in bursts of about 30 every few minutes. Explain the burst size, and give two one-word fixes that need no code change.

## Key takeaways

- A process has a table of numbered **descriptors**; `0`, `1`, `2` are stdin, stdout, stderr. Programs read and write numbers, not names, and inherit the table at `fork`. `ls -l /proc/<pid>/fd` shows where the numbers point.
- **Redirection is `dup2` in the child between `fork` and `exec`.** `> file` truncates, `>> file` appends, `< file` feeds stdin, `2>&1` copies stdout's pointer onto stderr. Applied left to right; **`> log 2>&1` captures both, `2>&1 > log` does not.**
- A **pipe** is a 64 KiB kernel buffer with a read end and a write end. A pipeline is N children wired through N-1 pipes; the shell closes every copy it holds, because **EOF arrives only when all write ends are closed**.
- **Backpressure is built in**: a full pipe parks the writer, an empty one parks the reader, nothing is lost. **`SIGPIPE`** kills a writer whose reader has gone; the shell shows it as **141**.
- A pipeline's status is the **last** command's unless `set -o pipefail`; `PIPESTATUS` has all of them.
- Between `print()` and the kernel sits a **user-space buffer** that flushes per line on a terminal and per 8 KiB in a pipe. That is why services log in bursts and lose their last lines on a crash. `-u`, `PYTHONUNBUFFERED`, `flush=True`, stderr, or `stdbuf -oL`.
- `tee` copies, `xargs` turns lines into arguments, `mkfifo` names a pipe, `<(cmd)` gives a command a filename. Small programs plus text plus pipes is the design; lesson 08 is the vocabulary.

Next: [The Text Toolkit: grep, sed, awk, sort, uniq, cut, tr & jq](../08-the-text-toolkit/). You can wire streams together. Now the tools you put in them, a streaming `grep` and a field-splitting `awk` built in Python, and the one-liners that turn a 2 GB log into an answer.
