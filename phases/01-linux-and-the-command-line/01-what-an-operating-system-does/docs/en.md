# Kernel, User Space & Syscalls

> Your program has never touched the disk, the network card or the screen. Not once. Every byte it ever read or wrote went through one door, the system call, and the kernel did the real work on the other side. This lesson opens that door and times it: a crossing costs about **450 ns** in this repo's sandbox, five times a Python function call, and a plain `python3 -c pass` makes **280** of them before it exits.

## The Problem

In Foundations you learned that a running program is a process: instructions and data in RAM, stepped through by the CPU. You also read one sentence that this whole phase is about: *"A program can't touch the disk or network directly; it asks the OS through a system call."* That sentence is doing a lot of work. It is the reason your backend can crash without taking the machine down, the reason two services on one box cannot read each other's memory, and the reason a slow server is so often slow at exactly one place.

It is also the thing nobody shows you. You type `print("hello")` and letters appear. You call `open("config.yaml")` and get an error that says `No such file or directory`. Who put the letters on the screen? Who decided the file was not there, and where did that wording come from? Python did not write it. Python asked.

Every backend you will ever run lives on top of an operating system, and on servers that operating system is Linux almost without exception. Before you can read a log, find a port, write a deploy script or understand why a container is "just a process," you need a clear picture of the two worlds your code lives between, and the one door that connects them.

## The Concept

### Two worlds: user space and kernel space

The CPU you built in Foundations has a switch in it that we skipped: a **privilege mode**. In **user mode**, some instructions are forbidden, some memory ranges are invisible, and the hardware cannot be touched. In **supervisor mode** (also called kernel mode; x86 calls the levels rings, ARM calls them exception levels), everything is allowed. The CPU flips the switch on exactly two occasions: when a program deliberately asks for the kernel, and when hardware interrupts.

Everything you have ever written runs in user mode. That includes Python, the shell, your web framework, the database client and the database itself. Collectively this is **user space**. The one program that runs in supervisor mode is the **kernel**, and the RAM and hardware it controls is **kernel space**. The line between them is enforced by the CPU, not by convention: a user-mode program that tries to execute a privileged instruction or read kernel memory does not get a warning. The CPU traps, the kernel takes over, and the process is usually killed.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 620" width="100%" style="max-width:880px" role="img" aria-label="One system call traced end to end, drawn as two horizontal bands separated by a thick boundary line. The upper band is user space, your unprivileged process. Inside it, left to right: your code calls print hello; the Python runtime formats the text and buffers it; the C library function write puts the syscall number 1 and the arguments into CPU registers and runs the syscall instruction. A downward arrow from that box crosses the boundary, labelled the CPU switches from user mode to supervisor mode. The lower band is kernel space, privileged. Inside it, right to left: the syscall entry checks the number, the file descriptor and the buffer pointer; the virtual filesystem finds that descriptor 1 is a terminal; the tty driver copies the five bytes out. A final arrow leads down into a hardware band where the terminal shows hello. An upward arrow from the kernel entry back across the boundary carries the return value, 5, meaning five bytes written, or a negative errno on failure. Callouts on the right explain user mode, which cannot touch hardware or kernel memory and traps on a forbidden instruction; the door, one instruction and one number, write is syscall 1 on x86-64 and 64 on 64-bit ARM; kernel mode, where every instruction and every byte of RAM is allowed and every argument is checked before it is trusted; and the cost, about 450 nanoseconds per crossing in the sandbox versus about 90 for a Python function call.">
  <defs>
    <marker id="p1l01a-ar" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker>
    <marker id="p1l01a-aro" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#c94a12"/></marker>
    <marker id="p1l01a-arg" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#0fa07f"/></marker>
  </defs>
  <text x="450" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">One door: every byte your program touches goes through a system call</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">

    <!-- USER SPACE band -->
    <rect x="40" y="48" width="600" height="204" rx="12" fill="#7c5cff" fill-opacity="0.06" stroke="#7c5cff" stroke-width="2" stroke-linejoin="round"/>
    <text x="56" y="70" font-size="11.5" font-weight="700" fill="#7c5cff">USER SPACE</text>
    <text x="150" y="70" font-size="9" fill="currentColor" opacity="0.8">your process, unprivileged: Python, the shell, your framework, the database</text>

    <g fill="none" stroke-linejoin="round" stroke-width="1.7">
      <rect x="60" y="100" width="170" height="60" rx="9" fill="#7f7f7f" fill-opacity="0.12" stroke="#7f7f7f"/>
      <rect x="260" y="100" width="170" height="60" rx="9" fill="#7f7f7f" fill-opacity="0.12" stroke="#7f7f7f"/>
      <rect x="460" y="100" width="170" height="60" rx="9" fill="#c94a12" fill-opacity="0.12" stroke="#c94a12"/>
    </g>
    <g text-anchor="middle" fill="currentColor">
      <text x="145" y="121" font-size="10.5" font-weight="700">your code</text>
      <text x="145" y="137" font-size="9">print("hello")</text>
      <text x="145" y="151" font-size="7.8" opacity="0.7">a Python function</text>
      <text x="345" y="121" font-size="10.5" font-weight="700">Python runtime</text>
      <text x="345" y="137" font-size="9">format, then buffer</text>
      <text x="345" y="151" font-size="7.8" opacity="0.7">still your process, still user mode</text>
      <text x="545" y="121" font-size="10.5" font-weight="700" fill="#c94a12">libc write()</text>
      <text x="545" y="137" font-size="9">rax=1  rdi=1  rsi=buf  rdx=5</text>
      <text x="545" y="151" font-size="7.8" opacity="0.7">then one instruction: syscall</text>
    </g>
    <g fill="none" stroke="currentColor" stroke-width="1.6">
      <path d="M232 130 L256 130" marker-end="url(#p1l01a-ar)"/>
      <path d="M432 130 L456 130" marker-end="url(#p1l01a-ar)"/>
    </g>
    <text x="345" y="196" text-anchor="middle" font-size="8.5" fill="currentColor" opacity="0.75">everything above this line is code you (or someone) wrote and can read</text>
    <text x="345" y="210" text-anchor="middle" font-size="8.5" fill="currentColor" opacity="0.75">none of it can touch the screen: it can only ask</text>

    <!-- the crossing down -->
    <path d="M530 162 L530 286" fill="none" stroke="#c94a12" stroke-width="2.4" marker-end="url(#p1l01a-aro)"/>
    <text x="520" y="236" text-anchor="end" font-size="8.5" font-weight="700" fill="#c94a12">syscall</text>
    <text x="520" y="248" text-anchor="end" font-size="8" fill="currentColor" opacity="0.8">CPU → supervisor mode</text>

    <!-- the return up -->
    <path d="M600 292 L600 164" fill="none" stroke="#0fa07f" stroke-width="2.4" marker-end="url(#p1l01a-arg)"/>
    <text x="608" y="236" font-size="8.5" font-weight="700" fill="#0fa07f">= 5</text>
    <text x="608" y="248" font-size="8" fill="currentColor" opacity="0.8">or -errno</text>

    <!-- BOUNDARY -->
    <path d="M40 270 L640 270" fill="none" stroke="#c94a12" stroke-width="3" stroke-dasharray="10 6"/>
    <text x="60" y="264" font-size="8.5" font-weight="700" fill="#c94a12">THE BOUNDARY · enforced by the CPU's privilege bit, not by convention</text>

    <!-- KERNEL SPACE band -->
    <rect x="40" y="290" width="600" height="204" rx="12" fill="#0fa07f" fill-opacity="0.06" stroke="#0fa07f" stroke-width="2" stroke-linejoin="round"/>
    <text x="56" y="312" font-size="11.5" font-weight="700" fill="#0fa07f">KERNEL SPACE</text>
    <text x="172" y="312" font-size="9" fill="currentColor" opacity="0.8">one program, loaded at boot, privileged: Linux</text>

    <g fill="none" stroke-linejoin="round" stroke-width="1.7">
      <rect x="460" y="340" width="170" height="60" rx="9" fill="#0fa07f" fill-opacity="0.12" stroke="#0fa07f"/>
      <rect x="260" y="340" width="170" height="60" rx="9" fill="#7f7f7f" fill-opacity="0.12" stroke="#7f7f7f"/>
      <rect x="60" y="340" width="170" height="60" rx="9" fill="#7f7f7f" fill-opacity="0.12" stroke="#7f7f7f"/>
    </g>
    <g text-anchor="middle" fill="currentColor">
      <text x="545" y="361" font-size="10.5" font-weight="700" fill="#0fa07f">syscall entry</text>
      <text x="545" y="377" font-size="9">number 1? fd 1 open? buf readable?</text>
      <text x="545" y="391" font-size="7.8" opacity="0.7">every argument checked before trusted</text>
      <text x="345" y="361" font-size="10.5" font-weight="700">virtual filesystem</text>
      <text x="345" y="377" font-size="9">fd 1 → this is a terminal</text>
      <text x="345" y="391" font-size="7.8" opacity="0.7">a file, a pipe, a socket: same call</text>
      <text x="145" y="361" font-size="10.5" font-weight="700">tty driver</text>
      <text x="145" y="377" font-size="9">copy 5 bytes out</text>
      <text x="145" y="391" font-size="7.8" opacity="0.7">the only code that touches hardware</text>
    </g>
    <g fill="none" stroke="currentColor" stroke-width="1.6">
      <path d="M458 370 L434 370" marker-end="url(#p1l01a-ar)"/>
      <path d="M258 370 L234 370" marker-end="url(#p1l01a-ar)"/>
    </g>
    <text x="345" y="436" text-anchor="middle" font-size="8.5" fill="currentColor" opacity="0.75">the kernel does the work with your process's identity: your uid, your open files, your limits</text>
    <text x="345" y="450" text-anchor="middle" font-size="8.5" fill="currentColor" opacity="0.75">it decides yes or no, and never trusts a pointer you handed it</text>

    <!-- down to hardware -->
    <path d="M145 402 L145 522" fill="none" stroke="currentColor" stroke-width="1.8" marker-end="url(#p1l01a-ar)"/>

    <!-- HARDWARE band -->
    <rect x="40" y="524" width="600" height="46" rx="12" fill="#7f7f7f" fill-opacity="0.10" stroke="#7f7f7f" stroke-width="2" stroke-linejoin="round"/>
    <text x="56" y="544" font-size="11.5" font-weight="700" fill="currentColor">HARDWARE</text>
    <text x="56" y="559" font-size="8.5" fill="currentColor" opacity="0.8">the terminal shows: hello</text>
    <text x="345" y="551" text-anchor="middle" font-size="9" fill="currentColor" opacity="0.85">disk, network card, screen, keyboard: reachable from supervisor mode only</text>

    <!-- callouts -->
    <g fill="none" stroke-linejoin="round" stroke-width="1.6">
      <rect x="660" y="56" width="224" height="96" rx="9" fill="#7c5cff" fill-opacity="0.07" stroke="#7c5cff" stroke-opacity="0.8"/>
      <rect x="660" y="176" width="224" height="88" rx="9" fill="#c94a12" fill-opacity="0.07" stroke="#c94a12" stroke-opacity="0.8"/>
      <rect x="660" y="300" width="224" height="96" rx="9" fill="#0fa07f" fill-opacity="0.07" stroke="#0fa07f" stroke-opacity="0.8"/>
      <rect x="660" y="420" width="224" height="80" rx="9" fill="#7f7f7f" fill-opacity="0.08" stroke="#7f7f7f" stroke-opacity="0.8"/>
    </g>
    <text x="672" y="76" font-size="9.5" font-weight="700" fill="#7c5cff">USER MODE</text>
    <text x="672" y="92" font-size="8.5" fill="currentColor" opacity="0.9">cannot touch hardware</text>
    <text x="672" y="106" font-size="8.5" fill="currentColor" opacity="0.9">cannot read kernel memory</text>
    <text x="672" y="120" font-size="8.5" fill="currentColor" opacity="0.9">cannot read another process</text>
    <text x="672" y="134" font-size="8.5" fill="currentColor" opacity="0.9">a forbidden instruction traps</text>
    <text x="672" y="196" font-size="9.5" font-weight="700" fill="#c94a12">THE DOOR</text>
    <text x="672" y="212" font-size="8.5" fill="currentColor" opacity="0.9">one instruction, one number</text>
    <text x="672" y="226" font-size="8.5" fill="currentColor" opacity="0.9">write = 1 on x86-64, 64 on ARM64</text>
    <text x="672" y="240" font-size="8.5" fill="currentColor" opacity="0.9">the CPU jumps to the kernel's</text>
    <text x="672" y="254" font-size="8.5" fill="currentColor" opacity="0.9">entry point, never to your address</text>
    <text x="672" y="320" font-size="9.5" font-weight="700" fill="#0fa07f">KERNEL MODE</text>
    <text x="672" y="336" font-size="8.5" fill="currentColor" opacity="0.9">every instruction allowed</text>
    <text x="672" y="350" font-size="8.5" fill="currentColor" opacity="0.9">every byte of RAM visible</text>
    <text x="672" y="364" font-size="8.5" fill="currentColor" opacity="0.9">so it checks your arguments</text>
    <text x="672" y="378" font-size="8.5" fill="currentColor" opacity="0.9">before it trusts a single one</text>
    <text x="672" y="440" font-size="9.5" font-weight="700" fill="currentColor">THE PRICE</text>
    <text x="672" y="456" font-size="8.5" fill="currentColor" opacity="0.9">~450 ns per crossing (sandbox)</text>
    <text x="672" y="470" font-size="8.5" fill="currentColor" opacity="0.9">~90 ns for a Python call</text>
    <text x="672" y="484" font-size="8.5" fill="currentColor" opacity="0.9">so real programs batch I/O</text>
  </g>
  <text x="450" y="596" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="10.5" fill="currentColor" opacity="0.9">User space can only ask. The kernel checks, decides, and is the only code that touches hardware.</text>
  <text x="450" y="612" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="10.5" fill="currentColor" opacity="0.9">The door between them is one CPU instruction carrying one number, and every return value is a yes or a named no.</text>
</svg>
```

### The system call: the only door

A **system call** (syscall) is how a user-mode program asks the kernel to do something on its behalf. There are a few hundred of them. Each has a name and a number: on x86-64 Linux, `read` is 0, `write` is 1, `open` is 2, `close` is 3, `getpid` is 39. On 64-bit ARM the same names carry different numbers (`write` is 64). The names are the stable thing; the numbers are per-architecture bookkeeping.

The mechanics are simpler than they sound. Your program puts the syscall number in one CPU register (`rax` on x86-64), the arguments in a few more (`rdi`, `rsi`, `rdx`, then `r10`, `r8`, `r9`), and executes one instruction, `syscall`. The CPU flips to supervisor mode and jumps to a single address the kernel registered at boot: its entry point. The kernel reads the number, looks up the matching function in its table, **checks every argument** (is that file descriptor open in this process? is that pointer inside this process's memory? is that length sane?), does the work, puts a result in `rax`, and executes `sysret`, which flips the CPU back to user mode at the instruction after your `syscall`. To your program it looked like a function call that took a little longer than usual.

You almost never write that register dance yourself. The **C library** (libc, which on most Linux systems is glibc, and on Alpine is musl) provides a small wrapper function for every syscall with the same name: `write()`, `open()`, `read()`. Python's `os.write` calls libc's `write()`, which does the register dance. That is the whole chain: your code → Python → libc → `syscall` instruction → kernel. The Linux manual describes the convention in `syscall(2)` and lists every call in `syscalls(2)`; the number in parentheses is the **manual section**, and section 2 is exactly "system calls." Section 1 is user commands, section 3 is library functions. `man 2 write` and `man 1 ls` will be the two most useful things you type in this phase.

### What print() actually does

Take `print("hello")` apart, because you will do this with every "magic" thing in this phase:

1. `print` converts its arguments to text and appends `"\n"`. Pure Python, user mode.
2. It writes that text into `sys.stdout`, a Python object with a **buffer** in front of the real destination. Still user mode; nothing has left the process.
3. When the buffer decides to flush (on a newline if stdout is a terminal, on 8 KiB if it is a file or a pipe, or at exit), Python calls libc `write(1, buf, n)`. The `1` is a **file descriptor**, a small integer the kernel handed this process to name its standard output. Lesson 07 makes descriptors precise.
4. `write()` executes `syscall`. The CPU switches mode. The kernel checks that descriptor 1 is open, finds what it points at (a terminal, a file, a pipe: same call either way), copies the bytes out of your buffer, and returns the count.
5. The CPU switches back. Python gets `5` and moves on. Some time later, a terminal program (also user mode, also using syscalls) reads those bytes from the other end and draws glyphs.

The strace of exactly this, from the sandbox, is two system calls:

```console
$ strace -e trace=write python3 -c 'print("hello")'
write(1, "hello", 5)                    = 5
write(1, "\n", 1)                       = 1
+++ exited with 0 +++
```

Two crossings for one print. That number becomes interesting when a hot loop prints a million lines, which is the point of the timing you will run in **Build It**.

### The kernel is a program that never runs on its own

It is tempting to picture the kernel as a boss process that sits somewhere scheduling everyone. It is not a process at all. The kernel is a single large program that the bootloader copied into RAM once, at power-on, and that stays resident until shutdown. It has no main loop. It runs only when something enters it, and there are exactly three ways in:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 430" width="100%" style="max-width:880px" role="img" aria-label="The kernel drawn as a single box in the centre, labelled resident in RAM since boot, no main loop, asleep until something enters. Three arrows enter it. From the top, system calls: a process asks for something, write, open, connect, fork. From the left, hardware interrupts: a key was pressed, a packet arrived, the disk finished a read; the device raises a wire and the CPU jumps into the kernel whatever was running. From the right, the timer tick: a clock interrupt every few milliseconds that lets the scheduler decide whether another process should have the CPU. One arrow leaves the kernel downward: it returns to a process, possibly a different one than the one that was running, which is how one CPU appears to run many programs at once.">
  <defs>
    <marker id="p1l01b-ar" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker>
    <marker id="p1l01b-aro" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#c94a12"/></marker>
    <marker id="p1l01b-arp" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#7c5cff"/></marker>
    <marker id="p1l01b-ara" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#e0930f"/></marker>
    <marker id="p1l01b-arg" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#0fa07f"/></marker>
  </defs>
  <text x="450" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">The kernel never runs on its own: three things wake it, one thing leaves</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">

    <!-- top: syscalls -->
    <rect x="290" y="46" width="320" height="58" rx="10" fill="#c94a12" fill-opacity="0.10" stroke="#c94a12" stroke-width="1.8" stroke-linejoin="round"/>
    <text x="450" y="67" text-anchor="middle" font-size="11" font-weight="700" fill="#c94a12">1 · SYSTEM CALLS · from above</text>
    <text x="450" y="83" text-anchor="middle" font-size="9" fill="currentColor">a process asks: write, open, connect, fork, exit</text>
    <text x="450" y="96" text-anchor="middle" font-size="8" fill="currentColor" opacity="0.7">deliberate: the program chose to cross</text>
    <path d="M450 106 L450 160" fill="none" stroke="#c94a12" stroke-width="2.2" marker-end="url(#p1l01b-aro)"/>

    <!-- left: interrupts -->
    <rect x="30" y="170" width="220" height="90" rx="10" fill="#7c5cff" fill-opacity="0.10" stroke="#7c5cff" stroke-width="1.8" stroke-linejoin="round"/>
    <text x="140" y="191" text-anchor="middle" font-size="11" font-weight="700" fill="#7c5cff">2 · INTERRUPTS · from below</text>
    <text x="140" y="208" text-anchor="middle" font-size="9" fill="currentColor">a key was pressed</text>
    <text x="140" y="221" text-anchor="middle" font-size="9" fill="currentColor">a packet arrived on the NIC</text>
    <text x="140" y="234" text-anchor="middle" font-size="9" fill="currentColor">the disk finished a read</text>
    <text x="140" y="250" text-anchor="middle" font-size="8" fill="currentColor" opacity="0.7">the device raises a wire; the CPU jumps in</text>
    <path d="M252 215 L306 215" fill="none" stroke="#7c5cff" stroke-width="2.2" marker-end="url(#p1l01b-arp)"/>

    <!-- right: timer -->
    <rect x="650" y="170" width="220" height="90" rx="10" fill="#e0930f" fill-opacity="0.10" stroke="#e0930f" stroke-width="1.8" stroke-linejoin="round"/>
    <text x="760" y="191" text-anchor="middle" font-size="11" font-weight="700" fill="#e0930f">3 · THE TIMER TICK</text>
    <text x="760" y="208" text-anchor="middle" font-size="9" fill="currentColor">a clock interrupt, every few ms</text>
    <text x="760" y="221" text-anchor="middle" font-size="9" fill="currentColor">the scheduler asks: has this</text>
    <text x="760" y="234" text-anchor="middle" font-size="9" fill="currentColor">process had its turn?</text>
    <text x="760" y="250" text-anchor="middle" font-size="8" fill="currentColor" opacity="0.7">how one CPU runs many programs</text>
    <path d="M648 215 L594 215" fill="none" stroke="#e0930f" stroke-width="2.2" marker-end="url(#p1l01b-ara)"/>

    <!-- centre: the kernel -->
    <rect x="310" y="162" width="280" height="106" rx="12" fill="#0fa07f" fill-opacity="0.10" stroke="#0fa07f" stroke-width="2.2" stroke-linejoin="round"/>
    <text x="450" y="188" text-anchor="middle" font-size="13" font-weight="700" fill="#0fa07f">THE KERNEL</text>
    <text x="450" y="206" text-anchor="middle" font-size="9" fill="currentColor">resident in RAM since boot</text>
    <text x="450" y="220" text-anchor="middle" font-size="9" fill="currentColor">no main loop, no PID</text>
    <text x="450" y="234" text-anchor="middle" font-size="9" fill="currentColor">asleep until something enters</text>
    <text x="450" y="254" text-anchor="middle" font-size="8" fill="currentColor" opacity="0.7">handles the entry, then leaves</text>

    <!-- bottom: return -->
    <path d="M450 270 L450 322" fill="none" stroke="#0fa07f" stroke-width="2.2" marker-end="url(#p1l01b-arg)"/>
    <rect x="250" y="326" width="400" height="58" rx="10" fill="#7f7f7f" fill-opacity="0.10" stroke="#7f7f7f" stroke-width="1.8" stroke-linejoin="round"/>
    <text x="450" y="347" text-anchor="middle" font-size="11" font-weight="700" fill="currentColor">RETURN to a process · maybe a different one</text>
    <text x="450" y="363" text-anchor="middle" font-size="9" fill="currentColor">the syscall's result goes back to the caller,</text>
    <text x="450" y="376" text-anchor="middle" font-size="9" fill="currentColor">or the scheduler hands the CPU to someone who has waited longer</text>
  </g>
  <text x="450" y="412" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="10.5" fill="currentColor" opacity="0.9">Syscalls come from above, interrupts from below, the tick from the clock. Between entries the kernel does nothing at all.</text>
</svg>
```

- **System calls** enter from above. A process asked for something.
- **Hardware interrupts** enter from below. A device raised a wire: a packet arrived, a disk read finished, a key was pressed. Whatever was running is paused, the kernel handles the device, and returns.
- **The timer tick** is an interrupt from a clock, every few milliseconds. It exists so the **scheduler** can ask whether the running process has had its turn and hand the CPU to another one. This is the mechanism behind the "rapid switching" that Foundations called concurrency.

When the kernel is done with an entry it returns to user mode, and not necessarily to the process that was running before. Lesson 02 draws the map of what is inside the box; lesson 10 shows you the scheduler's decisions in `ps` and `top`.

### errno: how the kernel says no

A syscall can fail, and when it does the kernel does not throw an exception or print a message. It returns a negative number. libc turns that into a return value of `-1` and stores the positive number in a variable called **errno**. Every failure has a small integer, a short name, and a standard sentence:

| errno | name | the kernel's sentence | you will meet it when |
|---|---|---|---|
| 1 | `EPERM` | Operation not permitted | you are not root and the call needs it |
| 2 | `ENOENT` | No such file or directory | a path is wrong, or the working directory is not what you think |
| 13 | `EACCES` | Permission denied | the file's mode bits say no (lesson 06) |
| 11 | `EAGAIN` | Resource temporarily unavailable | a non-blocking socket has nothing to read yet (Phase 9) |
| 24 | `EMFILE` | Too many open files | a descriptor leak hit the per-process limit (lesson 12) |
| 98 | `EADDRINUSE` | Address already in use | a port is still held by the previous copy of your server (lesson 14) |
| 111 | `ECONNREFUSED` | Connection refused | nothing is listening at that address and port (lesson 14) |

Python does you a favour: it reads errno and raises an `OSError`, and since Python 3.3 a named subclass for the common ones: `FileNotFoundError` is `ENOENT`, `PermissionError` is `EACCES` or `EPERM`, `ConnectionRefusedError` is `ECONNREFUSED`. The sentence in the exception message, `No such file or directory`, is the kernel's, relayed by libc's `strerror`. This is why the wording is identical across every language and tool on the box: they are all quoting the same source. Knowing the errno names means knowing what the kernel actually said, which is the first step of every diagnosis in this phase.

### What "Linux" actually is

Here is the thing most people get wrong for years. **Linux is only the kernel.** It is the program in the green band of the first diagram and nothing else: the scheduler, the memory manager, the filesystems, the network stack, the drivers, the syscall table. It was started by Linus Torvalds in 1991 and is released under the GPLv2 licence. It contains no shell, no `ls`, no text editor, no package manager. You cannot log into "Linux."

Everything you actually type into is user space, written by other projects:

- **libc** (glibc on most distributions, musl on Alpine): the wrappers around the syscalls, plus `printf`, `malloc` and the rest of C's standard library. Every program on the box, Python included, is built on it.
- **The shell** (`bash`, `zsh`, `sh`): the program that reads your typed commands and starts other programs. Lesson 03.
- **The coreutils** (`ls`, `cp`, `mv`, `cat`, `chmod`, and about a hundred more): small user-space programs, each one a thin layer over a few syscalls. You will rebuild several of them in this phase to prove it.
- **The init system** (`systemd` nearly everywhere now): the first user-space process the kernel starts, which starts everything else. Lesson 11.
- **The package manager** (`apt`, `dnf`, `apk`): the tool that installs and upgrades all of the above. Lesson 13.

A **distribution** is the kernel plus a chosen set of all of that, packaged, configured and versioned together. The three families you will meet on servers:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 540" width="100%" style="max-width:880px" role="img" aria-label="Two things side by side. On the left, a five-layer stack drawn bottom to top: hardware; the Linux kernel, highlighted, with the caption this and only this is Linux, scheduler, memory, filesystems, network stack, drivers, syscall table; libc, the wrappers around the syscalls, glibc or musl; userland, the shell, the coreutils, systemd, the package manager, all separate projects; and your backend, Python and your code, at the top. A note beside the boundary between kernel and libc says the syscall door is here and is the same across every distribution. On the right, three distribution cards. Debian and Ubuntu: apt and dpkg, .deb packages, glibc, the default of most cloud images and of this repo's sandbox, which is Debian 13. RHEL, Fedora, Rocky, Alma and Amazon Linux: dnf and rpm, .rpm packages, glibc, the enterprise and AWS family. Alpine: apk, musl, BusyBox, about five megabytes, the container base image. A caption reads: same kernel, same door, different packaging above it.">
  <defs>
    <marker id="p1l01c-ar" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker>
  </defs>
  <text x="450" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">"Linux" is one layer. A distribution is the whole stack, packaged.</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">

    <!-- left: the stack -->
    <text x="250" y="56" text-anchor="middle" font-size="10" font-weight="700" fill="currentColor" opacity="0.85">what is actually running on the box</text>
    <g fill="none" stroke-linejoin="round" stroke-width="1.8">
      <rect x="40" y="70"  width="420" height="62" rx="10" fill="#c94a12" fill-opacity="0.10" stroke="#c94a12"/>
      <rect x="40" y="142" width="420" height="92" rx="10" fill="#7c5cff" fill-opacity="0.08" stroke="#7c5cff"/>
      <rect x="40" y="244" width="420" height="56" rx="10" fill="#7f7f7f" fill-opacity="0.12" stroke="#7f7f7f"/>
      <rect x="40" y="322" width="420" height="92" rx="10" fill="#0fa07f" fill-opacity="0.12" stroke="#0fa07f" stroke-width="2.4"/>
      <rect x="40" y="424" width="420" height="50" rx="10" fill="#7f7f7f" fill-opacity="0.10" stroke="#7f7f7f"/>
    </g>
    <text x="56" y="92" font-size="11" font-weight="700" fill="#c94a12">YOUR BACKEND</text>
    <text x="56" y="108" font-size="9" fill="currentColor">python3, your code, your framework, the database</text>
    <text x="56" y="122" font-size="8" fill="currentColor" opacity="0.7">user space · the top of the stack · what you deploy</text>

    <text x="56" y="164" font-size="11" font-weight="700" fill="#7c5cff">USERLAND</text>
    <text x="56" y="180" font-size="9" fill="currentColor">the shell (bash) · the coreutils (ls, cp, cat, chmod ...)</text>
    <text x="56" y="194" font-size="9" fill="currentColor">the init system (systemd) · the package manager (apt, dnf, apk)</text>
    <text x="56" y="208" font-size="8" fill="currentColor" opacity="0.7">separate projects, each a thin layer over a few syscalls</text>
    <text x="56" y="222" font-size="8" fill="currentColor" opacity="0.7">this is what you type into; none of it is "Linux"</text>

    <text x="56" y="266" font-size="11" font-weight="700" fill="currentColor">LIBC</text>
    <text x="56" y="282" font-size="9" fill="currentColor">glibc (most distributions) or musl (Alpine): write(), open(), malloc(), printf()</text>
    <text x="56" y="294" font-size="8" fill="currentColor" opacity="0.7">the wrappers around the door; every program above is built on it</text>

    <path d="M40 311 L460 311" fill="none" stroke="#c94a12" stroke-width="2.4" stroke-dasharray="8 5"/>
    <text x="250" y="307" text-anchor="middle" font-size="8" font-weight="700" fill="#c94a12">the syscall door · identical on every distribution</text>

    <text x="56" y="346" font-size="12" font-weight="700" fill="#0fa07f">THE KERNEL · this, and only this, is Linux</text>
    <text x="56" y="364" font-size="9" fill="currentColor">scheduler · memory manager · filesystems · network stack</text>
    <text x="56" y="378" font-size="9" fill="currentColor">device drivers · the syscall table · namespaces and cgroups</text>
    <text x="56" y="394" font-size="8" fill="currentColor" opacity="0.7">one program, supervisor mode, resident since boot · started 1991, GPLv2</text>
    <text x="56" y="406" font-size="8" fill="currentColor" opacity="0.7">no shell, no ls, no editor: you cannot "log into Linux"</text>

    <text x="56" y="445" font-size="11" font-weight="700" fill="currentColor">HARDWARE</text>
    <text x="56" y="461" font-size="9" fill="currentColor">CPU · RAM · disk · network card (Foundations)</text>

    <!-- right: distributions -->
    <text x="700" y="56" text-anchor="middle" font-size="10" font-weight="700" fill="currentColor" opacity="0.85">the three families you will meet on servers</text>
    <g fill="none" stroke-linejoin="round" stroke-width="1.7">
      <rect x="500" y="70"  width="380" height="116" rx="10" fill="#7f7f7f" fill-opacity="0.08" stroke="currentColor" stroke-opacity="0.4"/>
      <rect x="500" y="200" width="380" height="116" rx="10" fill="#7f7f7f" fill-opacity="0.08" stroke="currentColor" stroke-opacity="0.4"/>
      <rect x="500" y="330" width="380" height="144" rx="10" fill="#7f7f7f" fill-opacity="0.08" stroke="currentColor" stroke-opacity="0.4"/>
    </g>
    <text x="516" y="92" font-size="11" font-weight="700" fill="currentColor">Debian · Ubuntu</text>
    <text x="516" y="110" font-size="9" fill="currentColor">packages: apt / dpkg, .deb files · libc: glibc</text>
    <text x="516" y="124" font-size="9" fill="currentColor">init: systemd · shell: bash</text>
    <text x="516" y="140" font-size="8.5" fill="currentColor" opacity="0.8">the default of most cloud images and most tutorials</text>
    <text x="516" y="154" font-size="8.5" font-weight="700" fill="#0fa07f">this repo's sandbox: Debian 13 (trixie)</text>
    <text x="516" y="170" font-size="8" fill="currentColor" opacity="0.7">Ubuntu is Debian with a release schedule and a company behind it</text>

    <text x="516" y="222" font-size="11" font-weight="700" fill="currentColor">RHEL · Fedora · Rocky · Alma · Amazon Linux</text>
    <text x="516" y="240" font-size="9" fill="currentColor">packages: dnf / rpm, .rpm files · libc: glibc</text>
    <text x="516" y="254" font-size="9" fill="currentColor">init: systemd · shell: bash · SELinux on by default</text>
    <text x="516" y="270" font-size="8.5" fill="currentColor" opacity="0.8">the enterprise family; Amazon Linux is what EC2 hands you</text>
    <text x="516" y="284" font-size="8" fill="currentColor" opacity="0.7">same commands as Debian except the package manager</text>
    <text x="516" y="300" font-size="8" fill="currentColor" opacity="0.7">Fedora is where RHEL's next version is tried first</text>

    <text x="516" y="352" font-size="11" font-weight="700" fill="currentColor">Alpine</text>
    <text x="516" y="370" font-size="9" fill="currentColor">packages: apk · libc: musl · coreutils: BusyBox (one binary)</text>
    <text x="516" y="384" font-size="9" fill="currentColor">init: OpenRC · shell: ash (not bash, until you install it)</text>
    <text x="516" y="400" font-size="8.5" fill="currentColor" opacity="0.8">about 5 MB: the base image of half the containers in existence</text>
    <text x="516" y="414" font-size="8.5" fill="currentColor" opacity="0.8">small because it replaced glibc and the GNU tools, not the kernel</text>
    <text x="516" y="430" font-size="8" fill="currentColor" opacity="0.7">musl is why some pre-built binaries and Python wheels</text>
    <text x="516" y="442" font-size="8" fill="currentColor" opacity="0.7">do not run on it: they were linked against glibc</text>
    <text x="516" y="462" font-size="8" fill="currentColor" opacity="0.7">(macOS: XNU kernel, BSD userland; the shell skills transfer, the syscall numbers do not)</text>
  </g>
  <text x="450" y="506" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="10.5" fill="currentColor" opacity="0.9">Same kernel, same door. What differs between distributions is the packaging above it.</text>
  <text x="450" y="524" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="10.5" fill="currentColor" opacity="0.9">Learn the commands once; only the package manager changes when you move between families.</text>
</svg>
```

The practical consequence: **the commands in this phase are the same on every distribution.** `ls`, `grep`, `ps`, `ss`, `curl`, `systemctl` behave identically on Ubuntu and on Amazon Linux. The one thing that changes when you move between families is how you install software, which is one lesson (13), not eighteen. This repo's sandbox is Debian, so everything in the **Use It** sections runs as printed inside `make shell`.

One more clarification, because you are probably on a Mac. macOS is not Linux; its kernel is XNU, and its userland descends from BSD. But it is a Unix, so the shell, the files, the permissions and the pipes work the same way, and nearly every command in this phase exists there too. The syscall numbers differ, `/proc` does not exist, and a few tools (`strace`, `ss`, `systemctl`) are Linux-only. When a lesson needs the Linux view, it says so and the sandbox provides it.

### Why servers run Linux

Not because it is free, though it is. Servers run Linux because:

- **The syscall interface does not break.** The kernel's first rule, enforced by its maintainers for three decades, is that a program compiled against an old kernel keeps working on a new one. A binary from 2010 still runs. Nothing else you deploy on has that guarantee.
- **It runs everywhere.** The same kernel boots on a phone, a Raspberry Pi, a laptop, a rack server and a 10,000-core supercomputer, on x86 and on ARM, which is why the cloud can offer you any of them at the same price list.
- **Containers are a Linux feature.** What you will meet as Docker and Kubernetes in Phase 11 is built from two kernel mechanisms, **namespaces** and **cgroups**, that exist in Linux and nowhere else. A container on a Mac is a Linux virtual machine running containers. This is why the sandbox works: your Mac is running a small Linux kernel underneath it.
- **It is inspectable.** The source is public and every fact about a running system is a file you can read (`/proc`, `/sys`, lesson 02). When something goes wrong at 3 a.m. there is no vendor to call, and there does not need to be.

### POSIX: why the door has the same shape everywhere

The reason `open`, `read`, `write`, `close`, `fork` and `exec` exist on Linux and macOS and the BSDs with the same names and the same behaviour is a standard: **POSIX** (Portable Operating System Interface, IEEE Std 1003.1, currently the 2017 edition with 2024 updates). It specifies the C-level interface to a Unix-like operating system: the syscall wrappers, the shell language, the core utilities. Linux is not formally certified but follows it closely; macOS is certified. When this phase says "a file is a sequence of bytes, opened with `open` and read with `read`," that is POSIX talking, and it is the reason the Python `os` module works unchanged on both your laptop and your server.

## Build It

The script for this lesson is [`code/syscalls.py`](../code/syscalls.py). It has no dependencies and runs on macOS and Linux; the Linux-only part explains itself and steps aside on a Mac. Run it, then run it again inside the sandbox to see the difference:

```bash
python3 phases/01-linux-and-the-command-line/01-what-an-operating-system-does/code/syscalls.py
make shell    # then the same command inside
```

It does five things, each one a door you have just read about.

**1 · `write(2)` with nothing in front of it.** `print` is Python; `os.write` is the raw syscall wrapper, a descriptor number and bytes:

```python
sys.stdout.flush()  # push print()'s buffer through the door first, so the lines stay in order
n = os.write(1, b"hello from user space -> kernel -> terminal\n")
```

The return value, `44`, is the kernel reporting how many bytes it accepted. If you delete the `flush()` line and run with output going to a pipe (`python3 syscalls.py | cat`), the `os.write` line appears *before* everything `print` said earlier, because `print`'s text was still sitting in the user-space buffer when `os.write` went straight through. That reordering is the buffer made visible.

**2 · A file with no `open()` wrapper.** Python's `open()` gives you a buffered, text-decoding object. Underneath it is three syscalls:

```python
fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)  # -> 3, the next free descriptor
os.write(fd, b"the kernel wrote this on my behalf\n")
os.close(fd)
```

The flags are the kernel's vocabulary (write-only, create if missing, truncate first), and the descriptor comes back as `3` inside the sandbox because `0`, `1` and `2` are already taken by standard input, output and error. On your Mac it may say `4`, because something in the Python start-up sequence is holding `3`. Same rule: the lowest free number.

**3 · How the kernel refuses.** Ask for a file that does not exist and read the answer:

```console
open('/definitely/not/here.txt') failed: errno 2 = ENOENT: No such file or directory
   Python raised FileNotFoundError: the same number, with a readable name
```

Then the script creates a file, strips every permission bit with `chmod 000`, and tries to open it. On your laptop you get `errno 13 = EACCES: Permission denied` and a `PermissionError`. Inside the sandbox you get something more interesting:

```console
open('/tmp/syscalls-pel179t_/secret.txt') SUCCEEDED with mode 000: you are uid 0 (root).
   Root bypasses permission bits entirely; that is why services never run as root (lesson 06).
```

Same code, same syscall, opposite answer, because the kernel checked *who was asking*. Docker runs you as root inside the sandbox by default, and root skips the permission check. Hold on to that; it is the single most important fact in lesson 06.

**4 · Which kernel is this?** `os.uname()` is the `uname(2)` syscall. On the sandbox it reports `Linux 7.0.14` on `aarch64`; the script then reads three files that exist only on Linux:

```console
/proc/version  : Linux version 7.0.14-orbstack-00380-ga7e0a2dc9535 (orbstack@builder) ...
/etc/os-release: Debian GNU/Linux 13 (trixie)   <- the distribution; the kernel above is Linux
/proc/self/status: Name=python, State=R (running), Pid=6, PPid=1, Threads=1, VmRSS=11460 kB
```

Read the middle two lines together and you have the whole "what is Linux" section in two lines of output: the kernel is Linux 7.0, the distribution wrapped around it is Debian 13. The third line is the kernel describing *this very process* through a file that is not on any disk; `/proc` is the kernel answering questions about itself, and lesson 02 is largely a tour of it.

**5 · What a crossing costs.** This is the number to remember. The script times a Python function call, the smallest possible syscall, a one-byte raw `write`, and a one-byte buffered `write`, two hundred thousand times each. Inside the sandbox:

```console
plain Python function call               93 ns   (no kernel involved)
os.getpid()  -> getpid(2)               460 ns   (one crossing, no work)
os.lseek(devnull) -> lseek(2)           446 ns   (one crossing, no work, never cached)
os.write(1 byte) -> write(2)            420 ns   (one crossing per byte)
f.write(1 byte), buffered                68 ns   (one crossing per 8192 bytes)

crossing the door cost about 5x a function call here,
and buffering made writing 6x cheaper per byte by crossing it 13 times instead of 100000.
```

Every crossing costs roughly 450 ns *before the kernel does anything*: that is the price of the mode switch, the register save and restore, the argument checks, and on modern CPUs the security mitigations at the boundary. A `getpid` that copies one integer costs the same as a `write` that copies one byte, because the crossing dominates. And a buffer in front of the door, which is all that Python's `open()` adds, cut the per-byte cost by six times by crossing 13 times instead of 100,000.

On a Mac the numbers are different in one telling way: `os.getpid()` comes back at 69 ns, the same as a function call, because Apple's libc answers it from a cache without crossing at all. The script notices and says so. That is why it also times `lseek`, which cannot be cached: 501 ns on the same Mac. The lesson is the same on both machines: **the crossing is the expensive part, and real programs batch to cross less often.** You will spend Phase 9 on exactly this trade-off, at the scale of ten thousand sockets.

## Use It

### strace: watch the door

You do not need to guess what a program asks the kernel. On Linux, `strace` sits at the boundary and prints every crossing as it happens: the syscall name, its arguments decoded, and the return value or the errno. It is the most direct debugging tool that exists, and it is preinstalled in the sandbox:

```bash
make shell
strace -e trace=write python3 -c 'print("hello")'
```

```console
write(1, "hello", 5)                    = 5
write(1, "\n", 1)                       = 1
+++ exited with 0 +++
```

Every line has the same shape: `name(arguments) = result`. A result of `-1` is followed by the errno name and its sentence. Trace a file that does not exist and you see the kernel's refusal and Python's translation of it, one after the other:

```console
$ strace -e trace=openat python3 -c 'open("/etc/app/config.yaml")'
openat(AT_FDCWD, "/etc/app/config.yaml", O_RDONLY|O_CLOEXEC) = -1 ENOENT (No such file or directory)
FileNotFoundError: [Errno 2] No such file or directory: '/etc/app/config.yaml'
```

The `openat` is `open` with a directory argument (`AT_FDCWD` means "relative to the current working directory"); modern libc routes every `open()` through it, which is why you will see `openat` in traces and rarely `open`. That trace also tells you the single most common cause of "file not found" in a deployed service: the process is looking in a path you did not expect, and strace shows you the exact path.

### Reading the summary

`strace -c` counts instead of printing. Trace the smallest Python program there is:

```console
$ strace -c python3 -c pass
% time     seconds  usecs/call     calls    errors syscall
------ ----------- ----------- --------- --------- ----------------
 25.99    0.000112          11        10           getdents64
 15.08    0.000065           0        66           rt_sigaction
 13.23    0.000057           1        43        14 newfstatat
 10.21    0.000044           1        24         9 openat
  5.10    0.000022           1        15           close
  5.10    0.000022           1        11           read
  4.41    0.000019           0        23           mmap
  ...
------ ----------- ----------- --------- --------- ----------------
100.00    0.000280           1       280        35 total
```

A program that does nothing made **280 system calls**, and **35 of them failed**. The failures are not bugs: Python probes a list of directories for its modules, and every `newfstatat` or `openat` that returns `ENOENT` is one directory that did not have the file. The `mmap` calls are the loader mapping shared libraries into memory; `rt_sigaction` is Python installing its signal handlers (lesson 10). Every one of those 280 lines is user space asking, and nothing in that table happened without the kernel.

Now trace a real coreutil, with the noise of library loading filtered out:

```console
$ strace -e trace=openat,read,write,close cat /etc/hostname
openat(AT_FDCWD, "/etc/hostname", O_RDONLY)  = 3
read(3, "bb3ad9fdd977\n", 262144)            = 13
write(1, "bb3ad9fdd977\n", 13)               = 13
read(3, "", 262144)                          = 0
close(3)                                     = 0
+++ exited with 0 +++
```

That is the whole of `cat`: open, read until `read` returns `0` (the kernel's way of saying end of file), write what you got to descriptor 1, close. Four syscalls. Every "command" in the next fifteen lessons is a program like this, a thin, readable layer over a handful of requests to the kernel, and you will rebuild several of them in Python to prove it.

### The tools you will use every day, named

You met the ideas; here are the commands that expose them, all of which you will use again in this phase:

| you want to know | command | what it is reading |
|---|---|---|
| which kernel, which architecture | `uname -a` | the `uname(2)` syscall |
| which distribution | `cat /etc/os-release` | a plain file the distribution installs |
| what a program asks the kernel | `strace <command>` | the syscall boundary, via `ptrace(2)` |
| what a running process is doing right now | `strace -p <PID>` | the same, attached to a live process |
| how a syscall behaves | `man 2 write` | section 2 of the manual: system calls |
| how a command behaves | `man 1 ls` or `ls --help` | section 1: user commands |
| the kernel's view of this process | `cat /proc/self/status` | the `/proc` filesystem (lesson 02) |
| what errno 13 means | `errno 13` (from `moreutils`) or `python3 -c 'import os; print(os.strerror(13))'` | libc's table of the kernel's sentences |

The manual pages are not installed in the sandbox to keep the image small, but they are on every real server and online at the Linux man-pages project. Section numbers matter: `man 2 open` describes the syscall, `man 3 fopen` the C library function on top of it, `man 1 open` a desktop tool that happens to share the name.

## Ship It

The artifact for this lesson is a runbook: [`outputs/runbook-strace-first-look.md`](../outputs/runbook-strace-first-look.md). It is the thing you open the first time a process on a server hangs, spins, or "cannot find" a file that is clearly there. It tells you which shape of trace to take (a summary, a filtered trace, an attach to a live PID), how to read one line, and how to map the syscall you see stuck or failing to the layer that is actually broken: a wrong path, a wrong user, a peer that never answered, a descriptor leak, a lock in your own threads. Every entry in it is a syscall name and an errno you now know how to read.

## Think about it

1. A colleague says "Python is slow at I/O, so I rewrote the loop in C." The loop calls `write()` once per byte. Will the rewrite help? What would?
2. Your service runs fine on your Mac and fails on the server with `Permission denied` opening `/var/log/app.log`. The file exists on both. Name two things the kernel checked that differ between the machines.
3. `strace -c` on your idle web server shows 50,000 `epoll_wait` calls per second, each taking 0 µs. Is it broken? What single fact would tell you?
4. A container image is 5 MB on Alpine and 120 MB on Debian for the same application. Which layer of the stack diagram got smaller, and which one is identical?

## Key takeaways

- The CPU has a **privilege mode**. Your code, the shell, the database, all of user space runs unprivileged; only the **kernel** runs in supervisor mode and only it touches hardware.
- A **system call** is the one door between them: a number in a register, one instruction, a mode switch, an argument check, a result. libc wraps each one in a C function; Python's `os` module wraps libc.
- `print("hello")` is two `write(1, ...)` crossings. `cat` is `openat`, `read`, `write`, `close`. `python3 -c pass` is 280 syscalls. **Nothing reaches the outside world without crossing.**
- A failed syscall returns `-1` and an **errno**: `ENOENT`, `EACCES`, `EADDRINUSE`. The sentence in every error message on the box is the kernel's, relayed. Learn the names.
- The kernel has **no main loop**. It runs only on a syscall, a hardware interrupt, or the timer tick, and then returns to some process. That tick is how one CPU appears to run everything.
- **Linux is only the kernel.** libc, the shell, the coreutils, systemd and the package manager are separate projects; a **distribution** packages them together. The commands are identical across Debian, Red Hat and Alpine; only the package manager differs.
- A crossing costs about **450 ns** in the sandbox, five Python function calls, before the kernel does any work. That is why every serious program **buffers and batches** its I/O, and why Phase 9 exists.
- **strace** shows you every crossing. When a process misbehaves on Linux, it is the first tool to reach for, and the runbook tells you how.

Next: [A Map of the Linux Kernel](../02-a-map-of-the-linux-kernel/). You have seen the door. Now open it and look at what is inside: the scheduler, the memory manager, the filesystems, the network stack, and the `/proc` window that lets you watch all of them.
