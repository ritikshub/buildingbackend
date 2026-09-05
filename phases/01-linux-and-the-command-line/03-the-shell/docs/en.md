# The Shell

> `ls` is not a feature of your terminal. It is a file at `/usr/bin/ls` that the shell found by searching seven directories, started with `fork` and `execve`, and waited for with `wait4`. This lesson builds that shell in about 120 lines of Python, then puts `strace` on bash to show it doing exactly the same thing, and settles the three questions every "command not found", "Permission denied" and "works in my terminal but not in cron" comes down to.

## The Problem

You have typed commands into a black window for years and most of it worked. But three programs are cooperating every time you press Enter, and when something goes wrong you have to know which one failed. "command not found" is one of them refusing. "Permission denied" is a different one. A script that runs perfectly when you type it and dies in `cron` at 3 a.m. is the third, and it is not even a bug in the script.

Lessons 01 and 02 gave you the kernel: the door and the map. The shell is the program you will use to drive it for the rest of this phase, and for the rest of your career. It is worth an hour to see it as what it is: a small loop that reads a line, finds a program, and asks the kernel to run it. By the end, `bash` will be a program you could have written, because you will have written one.

## The Concept

### Three programs, not one

When you open a terminal on your laptop or `ssh` into a server, three separate things are involved, and only one of them is "the shell":

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 440" width="100%" style="max-width:880px" role="img" aria-label="Three boxes in a row with a fourth below. On the left, the terminal emulator, a user-space program: Terminal.app, iTerm, the VS Code panel, or on a server the sshd daemon; it draws glyphs and sends keystrokes. In the middle, inside the kernel, the pseudo-terminal, a device file such as /dev/pts/3 with a line discipline that buffers a line until Enter, echoes what you type, turns Ctrl+C into the signal SIGINT and Ctrl+D into end-of-file. On the right, the shell, a user-space process, bash with PID 22: it prints the prompt, reads a line from descriptor 0, parses it, forks, execs and waits. Below the shell, the command: ls with PID 23, a child of the shell that inherited descriptors 0, 1 and 2, all pointing at the same pseudo-terminal, so its output reaches the screen without the shell touching it. Arrows show keystrokes travelling right from the terminal through the pty to the shell, and output bytes travelling left from the shell and from ls through the pty to the terminal. A note at the bottom says that cron, systemd and docker run -T attach no pty at all, so the tty command reports not a tty and programs that expect a terminal behave differently.">
  <defs>
    <marker id="p1l03a-ar" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker>
    <marker id="p1l03a-aro" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#c94a12"/></marker>
    <marker id="p1l03a-arg" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#0fa07f"/></marker>
  </defs>
  <text x="450" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">Between a keystroke and ls: a terminal, a kernel device, a shell, and a child</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">

    <!-- terminal emulator -->
    <rect x="40" y="90" width="210" height="130" rx="10" fill="#7f7f7f" fill-opacity="0.10" stroke="#7f7f7f" stroke-width="1.8" stroke-linejoin="round"/>
    <text x="145" y="112" text-anchor="middle" font-size="10.5" font-weight="700" fill="currentColor">THE TERMINAL EMULATOR</text>
    <text x="145" y="126" text-anchor="middle" font-size="8" fill="currentColor" opacity="0.7">user space · a normal program</text>
    <g text-anchor="middle" font-size="8.5" fill="currentColor">
      <text x="145" y="146">Terminal.app, iTerm, VS Code's panel</text>
      <text x="145" y="160">on a server: sshd stands in for it</text>
      <text x="145" y="178">draws glyphs from bytes it reads</text>
      <text x="145" y="192">sends keystrokes as bytes it writes</text>
      <text x="145" y="208" opacity="0.7">knows nothing about commands</text>
    </g>

    <!-- pty (kernel) -->
    <rect x="300" y="90" width="230" height="130" rx="10" fill="#0fa07f" fill-opacity="0.10" stroke="#0fa07f" stroke-width="2" stroke-linejoin="round"/>
    <text x="415" y="112" text-anchor="middle" font-size="10.5" font-weight="700" fill="#0fa07f">THE PSEUDO-TERMINAL</text>
    <text x="415" y="126" text-anchor="middle" font-size="8" fill="currentColor" opacity="0.7">kernel · a device: /dev/pts/3</text>
    <g text-anchor="middle" font-size="8.5" fill="currentColor">
      <text x="415" y="146">buffers a line until Enter</text>
      <text x="415" y="160">echoes what you type back to you</text>
      <text x="415" y="174">Ctrl+C → SIGINT to the foreground</text>
      <text x="415" y="188">Ctrl+D → end-of-file on read()</text>
      <text x="415" y="208" opacity="0.7">the "line discipline" · lesson 10</text>
    </g>

    <!-- shell -->
    <rect x="580" y="90" width="280" height="130" rx="10" fill="#c94a12" fill-opacity="0.10" stroke="#c94a12" stroke-width="2" stroke-linejoin="round"/>
    <text x="720" y="112" text-anchor="middle" font-size="10.5" font-weight="700" fill="#c94a12">THE SHELL · bash, pid 22</text>
    <text x="720" y="126" text-anchor="middle" font-size="8" fill="currentColor" opacity="0.7">user space · the only "shell" in the picture</text>
    <g text-anchor="middle" font-size="8.5" fill="currentColor">
      <text x="720" y="146">write(1, prompt) · read(0, line)</text>
      <text x="720" y="160">split, expand, resolve the first word</text>
      <text x="720" y="174">fork() · execve() · wait4()</text>
      <text x="720" y="188">remember $? · print the prompt again</text>
      <text x="720" y="208" opacity="0.7">a loop; the mini shell below is this loop</text>
    </g>

    <!-- child -->
    <path d="M720 222 L720 272" fill="none" stroke="#c94a12" stroke-width="2.2" marker-end="url(#p1l03a-aro)"/>
    <text x="732" y="252" font-size="8.5" font-weight="700" fill="#c94a12">fork + execve</text>
    <rect x="580" y="276" width="280" height="76" rx="10" fill="#7c5cff" fill-opacity="0.10" stroke="#7c5cff" stroke-width="1.8" stroke-linejoin="round"/>
    <text x="720" y="298" text-anchor="middle" font-size="10.5" font-weight="700" fill="#7c5cff">THE COMMAND · ls, pid 23</text>
    <g text-anchor="middle" font-size="8.5" fill="currentColor">
      <text x="720" y="316">a child of the shell; inherits fd 0, 1, 2</text>
      <text x="720" y="330">all three point at the same /dev/pts/3</text>
      <text x="720" y="344" opacity="0.7">its output reaches the screen without the shell</text>
    </g>

    <!-- arrows: keystrokes right, bytes left -->
    <path d="M252 130 L296 130" fill="none" stroke="currentColor" stroke-width="1.8" marker-end="url(#p1l03a-ar)"/>
    <path d="M532 130 L576 130" fill="none" stroke="currentColor" stroke-width="1.8" marker-end="url(#p1l03a-ar)"/>
    <text x="274" y="122" text-anchor="middle" font-size="7.5" fill="currentColor" opacity="0.8">keys</text>
    <text x="554" y="122" text-anchor="middle" font-size="7.5" fill="currentColor" opacity="0.8">a line</text>
    <path d="M576 180 L532 180" fill="none" stroke="#0fa07f" stroke-width="1.8" marker-end="url(#p1l03a-arg)"/>
    <path d="M296 180 L252 180" fill="none" stroke="#0fa07f" stroke-width="1.8" marker-end="url(#p1l03a-arg)"/>
    <text x="554" y="194" text-anchor="middle" font-size="7.5" fill="#0fa07f">output</text>
    <text x="274" y="194" text-anchor="middle" font-size="7.5" fill="#0fa07f">bytes</text>
    <!-- child output goes to pty too -->
    <path d="M578 300 L560 300 L560 236 L470 236 L470 222" fill="none" stroke="#0fa07f" stroke-width="1.6" stroke-dasharray="5 4" marker-end="url(#p1l03a-arg)"/>
    <text x="552" y="250" text-anchor="end" font-size="7.5" fill="#0fa07f">ls writes to fd 1 → the pty</text>

    <!-- no pty note -->
    <rect x="40" y="276" width="490" height="76" rx="10" fill="#e0930f" fill-opacity="0.08" stroke="#e0930f" stroke-width="1.6" stroke-linejoin="round"/>
    <text x="285" y="298" text-anchor="middle" font-size="10" font-weight="700" fill="#e0930f">WHEN THERE IS NO TERMINAL AT ALL</text>
    <g text-anchor="middle" font-size="8.5" fill="currentColor">
      <text x="285" y="316">cron, systemd, docker run -T, a CI job: fd 0, 1, 2 are pipes or files, not a pty</text>
      <text x="285" y="330">`tty` prints "not a tty"; there is no echo, no Ctrl+C, no prompt, no ~/.bashrc</text>
      <text x="285" y="344" opacity="0.7">programs notice (Python buffers differently, ls drops colour) and so must your scripts</text>
    </g>
  </g>
  <text x="450" y="392" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="10.5" fill="currentColor" opacity="0.9">The terminal draws. The pty is a kernel device that turns keystrokes into lines and Ctrl+C into a signal.</text>
  <text x="450" y="408" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="10.5" fill="currentColor" opacity="0.9">The shell is an ordinary process that reads those lines and starts children. The command is the child.</text>
  <text x="450" y="426" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="9.5" fill="currentColor" opacity="0.72">Replace any one of the three and the other two do not notice: that is why ssh, tmux and Docker work at all.</text>
</svg>
```

- **The terminal emulator** is an ordinary program that draws characters and sends keystrokes. Terminal.app, iTerm, the panel inside VS Code. On a server there is no screen, so `sshd` plays this role, forwarding bytes over the network to the terminal on your laptop (lesson 17).
- **The pseudo-terminal** (pty) is a kernel device between them, `/dev/pts/3` or similar. Its **line discipline** collects keystrokes into a line before handing it over, echoes what you type so you can see it, and turns `Ctrl+C` into a signal and `Ctrl+D` into end-of-file. The `tty` command prints which one you are on.
- **The shell** is a user-space process, usually `bash`, that reads lines from the pty and starts programs. It is the only one of the three that knows what a command is.

The command you run is a fourth thing: a **child process** of the shell, which inherits the shell's connection to the pty so that its output appears on your screen without passing through the shell at all.

This matters the first time you run something with no terminal: a `cron` job, a `systemd` service, `docker run` without `-t`, a CI step. There is no pty; descriptors 0, 1 and 2 are pipes or files; `tty` says `not a tty`. No prompt, no echo, no `Ctrl+C`, no `~/.bashrc`. Programs that check `isatty()` behave differently (Python buffers output in 8 KiB blocks instead of per line; `ls` drops its colours), which is why output "disappears" from services until they exit. Lesson 07 and lesson 11 come back to this.

### The prompt is a string, and the shell is asleep behind it

The prompt is not a special mode. It is the shell writing the string in the variable `PS1` to descriptor 1 and then blocking in `read(0)` until the pty delivers a line. On Debian the default `PS1` is `\u@\h:\w\$ `: user, `@`, host, `:`, working directory, and `$` for a normal user or `#` for root. A prompt ending in `#` is the shell telling you every command you type will run with root's identity. Notice it.

While the prompt is showing, `strace -p` on the shell shows exactly one line: `read(0,` with no return value. The shell is in state S from lesson 02, waiting for you.

### Anatomy of a command line

```bash
ls -l --color=auto /var/log
```

The first word is the **command**. Words beginning with `-` are **options** (also called flags or switches): `-l` is a short option, `--color=auto` a long one with a value, and short options can be combined, so `-la` is `-l -a`. Everything else is an **argument**, usually a file or a name. Three conventions are nearly universal: `--help` prints usage, `man <command>` opens the manual, and `--` says "everything after this is an argument even if it starts with a dash," which is how you delete a file called `-rf`.

But before `ls` sees any of that, the shell has rewritten the line. This is the part nobody explains, and it is where half of all shell bugs live:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 560" width="100%" style="max-width:880px" role="img" aria-label="The line echo, then in double quotes hi with two spaces and dollar USER, then star dot md, traced through six steps. Step one, read: the shell reads that raw line from descriptor zero. Step two, split into words honouring quotes: three words, echo, the quoted string, and star dot md. Step three, expand: dollar USER becomes root, star dot md becomes AGENTS.md README.md ROADMAP.md because the shell matched the pattern against the directory, and the quotes are removed, leaving five words: echo, hi with two spaces root, AGENTS.md, README.md, ROADMAP.md. Step four, resolve the first word in order: alias, function, builtin, then a PATH search, which finds /usr/bin/echo. Step five, fork and execve with those five words as argv: the program never sees the quotes, the dollar sign or the star. Step six, wait, and remember the exit status as dollar question mark. A right-hand column notes who does each step: the shell for one to four, the kernel for five and six. A caption says that single quotes stop step three entirely, double quotes stop the splitting and globbing but keep variable expansion, and that a pattern with no match is passed through literally.">
  <defs>
    <marker id="p1l03b-ar" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker>
  </defs>
  <text x="450" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">What the shell does to a line before the program sees a single byte of it</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">

    <!-- the raw line -->
    <rect x="40" y="46" width="820" height="34" rx="8" fill="#7c5cff" fill-opacity="0.10" stroke="#7c5cff" stroke-width="1.8"/>
    <text x="450" y="68" text-anchor="middle" font-size="11.5" font-weight="700" fill="#7c5cff">echo "hi  $USER" *.md</text>

    <!-- steps -->
    <g fill="none" stroke-linejoin="round" stroke-width="1.7">
      <rect x="40"  y="104" width="640" height="52" rx="9" fill="#7f7f7f" fill-opacity="0.10" stroke="#7f7f7f"/>
      <rect x="40"  y="176" width="640" height="52" rx="9" fill="#7f7f7f" fill-opacity="0.10" stroke="#7f7f7f"/>
      <rect x="40"  y="248" width="640" height="72" rx="9" fill="#e0930f" fill-opacity="0.10" stroke="#e0930f" stroke-width="2"/>
      <rect x="40"  y="340" width="640" height="52" rx="9" fill="#7f7f7f" fill-opacity="0.10" stroke="#7f7f7f"/>
      <rect x="40"  y="412" width="640" height="52" rx="9" fill="#0fa07f" fill-opacity="0.10" stroke="#0fa07f" stroke-width="2"/>
      <rect x="40"  y="484" width="640" height="40" rx="9" fill="#0fa07f" fill-opacity="0.10" stroke="#0fa07f"/>
    </g>
    <g fill="none" stroke="currentColor" stroke-width="1.5">
      <path d="M360 82 L360 100" marker-end="url(#p1l03b-ar)"/>
      <path d="M360 158 L360 172" marker-end="url(#p1l03b-ar)"/>
      <path d="M360 230 L360 244" marker-end="url(#p1l03b-ar)"/>
      <path d="M360 322 L360 336" marker-end="url(#p1l03b-ar)"/>
      <path d="M360 394 L360 408" marker-end="url(#p1l03b-ar)"/>
      <path d="M360 466 L360 480" marker-end="url(#p1l03b-ar)"/>
    </g>

    <text x="56" y="124" font-size="10" font-weight="700" fill="currentColor">1 · READ</text>
    <text x="56" y="140" font-size="9" fill="currentColor">read(0, ...) returns the raw line; nothing has been interpreted yet</text>

    <text x="56" y="196" font-size="10" font-weight="700" fill="currentColor">2 · SPLIT INTO WORDS, HONOURING QUOTES</text>
    <text x="56" y="212" font-size="9" fill="currentColor">[echo]  ["hi  $USER"]  [*.md]   ← three words; the quoted one kept its two spaces</text>

    <text x="56" y="268" font-size="10" font-weight="700" fill="#e0930f">3 · EXPAND, THEN REMOVE THE QUOTES</text>
    <text x="56" y="284" font-size="9" fill="currentColor">$USER → root    *.md → AGENTS.md README.md ROADMAP.md  (the shell read the directory, not echo)</text>
    <text x="56" y="298" font-size="9" fill="currentColor">[echo]  [hi  root]  [AGENTS.md]  [README.md]  [ROADMAP.md]   ← five words now</text>
    <text x="56" y="312" font-size="8" fill="currentColor" opacity="0.75">single quotes would have stopped this step entirely; double quotes stopped the splitting and the glob but not $USER</text>

    <text x="56" y="360" font-size="10" font-weight="700" fill="currentColor">4 · RESOLVE THE FIRST WORD, IN ORDER</text>
    <text x="56" y="376" font-size="9" fill="currentColor">alias? function? builtin? (bash: yes, echo is one) else search $PATH left to right → /usr/bin/echo</text>

    <text x="56" y="432" font-size="10" font-weight="700" fill="#0fa07f">5 · fork(), THEN execve("/usr/bin/echo", argv)</text>
    <text x="56" y="448" font-size="9" fill="currentColor">argv = ["echo", "hi  root", "AGENTS.md", "README.md", "ROADMAP.md"]: no quotes, no $, no * ever reach the program</text>

    <text x="56" y="501" font-size="10" font-weight="700" fill="#0fa07f">6 · wait4(): the child's exit status becomes $?</text>
    <text x="56" y="515" font-size="9" fill="currentColor">0 here; then the shell prints the prompt and goes back to step 1</text>

    <!-- who column -->
    <rect x="700" y="104" width="160" height="288" rx="9" fill="#c94a12" fill-opacity="0.08" stroke="#c94a12" stroke-width="1.6" stroke-linejoin="round"/>
    <text x="780" y="126" text-anchor="middle" font-size="10" font-weight="700" fill="#c94a12">WHO DOES IT</text>
    <g text-anchor="middle" font-size="9" fill="currentColor">
      <text x="780" y="150">steps 1 to 4:</text>
      <text x="780" y="164" font-weight="700">the shell</text>
      <text x="780" y="184">pure string work in</text>
      <text x="780" y="198">user space; the same in</text>
      <text x="780" y="212">bash, zsh, sh, and the</text>
      <text x="780" y="226">mini shell you will read</text>
      <text x="780" y="256">what a program receives</text>
      <text x="780" y="270">is argv, already final;</text>
      <text x="780" y="284">ls does not expand *,</text>
      <text x="780" y="298">and never sees a quote</text>
      <text x="780" y="330" opacity="0.75">a pattern with no match</text>
      <text x="780" y="344" opacity="0.75">is passed through as-is,</text>
      <text x="780" y="358" opacity="0.75">star included</text>
    </g>
    <rect x="700" y="412" width="160" height="112" rx="9" fill="#0fa07f" fill-opacity="0.08" stroke="#0fa07f" stroke-width="1.6" stroke-linejoin="round"/>
    <text x="780" y="434" text-anchor="middle" font-size="10" font-weight="700" fill="#0fa07f">steps 5 and 6:</text>
    <text x="780" y="450" text-anchor="middle" font-size="10" font-weight="700" fill="currentColor">the kernel</text>
    <g text-anchor="middle" font-size="9" fill="currentColor">
      <text x="780" y="472">three syscalls that</text>
      <text x="780" y="486">every command in this</text>
      <text x="780" y="500">phase runs through,</text>
      <text x="780" y="514">bash and Python alike</text>
    </g>
  </g>
  <text x="450" y="548" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="10.5" fill="currentColor" opacity="0.9">Half of all shell bugs are step 3 happening when you did not expect it, or not happening when you did. Quote deliberately.</text>
</svg>
```

### Quoting: the three kinds

The shell has exactly three ways to treat text, and everything about quoting follows from step 3 of the diagram:

| you write | the shell does | the program gets |
|---|---|---|
| `echo a   b` | splits on whitespace | two words, `a` and `b` |
| `echo "a   b"` | expands `$vars` inside, but does **not** split or glob | one word, `a   b` |
| `echo 'a   $HOME'` | nothing at all | one word, `a   $HOME`, literally |

The sandbox shows all three in one breath:

```console
$ echo "double: $HOME";  echo 'single: $HOME'
double: /root
single: $HOME
$ echo unquoted   spaces   collapse;  echo "quoted   spaces   stay"
unquoted spaces collapse
quoted   spaces   stay
```

The rule that will save you from real damage: **double-quote every variable that might contain a space or be empty.** `rm -rf $DIR/` with `DIR` unset expands to `rm -rf /`. `rm -rf "$DIR/"` with `DIR` unset tries to remove a directory literally called `/` relative to nothing, and fails. Lesson 09 makes this a habit.

### Expansion: variables and globs

`$NAME` is replaced with the variable's value. A few variables are set by the shell itself and you will read them constantly: `$HOME` (your home directory), `$USER`, `$PWD` (the working directory), `$PATH`, `$?` (the exit status of the last command), `$$` (the shell's own PID), and inside scripts `$0`, `$1`, `$2` (the script name and its arguments) and `$#` (how many). `${NAME}` is the same with unambiguous edges: `${NAME}_backup`. `~` alone is `$HOME`.

A **glob** is a pattern that the shell replaces with matching filenames: `*` any run of characters, `?` one character, `[abc]` one of those. The program never sees the pattern. `echo *.md` in the repo root prints `AGENTS.md README.md ROADMAP.md` because the *shell* read the directory and handed `echo` three arguments. When nothing matches, bash passes the pattern through unchanged, `*.zzz` stays `*.zzz`, which is why `ls *.log` in an empty directory complains about a file literally named `*.log`.

### Environment variables, and why cd is not a program

`NAME=value` sets a variable in the shell. Nothing else can see it yet. `export NAME` marks it as part of the **environment**: the set of `name=value` strings that the kernel copies into every child at `fork` and hands to every new program at `execve`. The sandbox shows the difference:

```console
$ GREETING=hi;      sh -c 'echo child sees: [$GREETING]'
child sees: []
$ export GREETING;  sh -c 'echo child sees: [$GREETING]'
child sees: [hi]
```

The environment is copied **downward, once, at fork**. A child cannot change its parent's environment, a change in the parent after the fork does not reach an already-running child, and a program sees exactly the environment of the process that started it. That last clause is why a service started by `systemd` does not see the `DATABASE_URL` you exported in your terminal (lesson 11), and why the runbook for this lesson has a whole section on it. `env` prints the current environment; the sandbox's shell had fifteen variables.

It is also why two commands must be **builtins**, code inside the shell rather than programs. `cd` calls `chdir(2)`, which changes the working directory of *the calling process*. If `cd` were a program, it would change the child's directory and then exit, and the shell would still be where it was. The same goes for `export`, `exit`, and anything else that must change the shell itself. `type` tells you which is which:

```console
$ type cd;  type ls;  type python3;  type echo
cd is a shell builtin
ls is /usr/bin/ls
python3 is /usr/local/bin/python3
echo is a shell builtin
```

### PATH: how the shell finds a program

`$PATH` is a colon-separated list of directories. When the first word is not an alias, function or builtin, the shell tries each directory in order and runs the first executable file with that name. Nothing else is searched. In the sandbox:

```console
$ echo $PATH | tr ':' '\n'
/usr/local/bin
/usr/local/sbin
/usr/local/bin
/usr/sbin
/usr/bin
/sbin
/bin
```

Seven entries, in priority order, which is why `python3` resolves to `/usr/local/bin/python3` (the one the sandbox image installed) even though Debian's own would be in `/usr/bin`. `which -a python3` lists every hit; `type -a` lists those plus any alias or builtin ahead of them; `hash` shows the cache the shell keeps of where it last found things, which is why a freshly installed program sometimes needs `hash -r` before the shell notices it.

The current directory is deliberately **not** on `PATH`. A program in the directory you are standing in is run as `./name`; the slash tells the shell to skip the search entirely and use the path as given. Putting `.` on `PATH` means that any directory you `cd` into can carry a file called `ls` that runs instead of the real one.

### fork, exec, wait: how a command actually runs

Here is the mechanism underneath steps 5 and 6, and it is the same four syscalls for every command you will ever run:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 470" width="100%" style="max-width:880px" role="img" aria-label="A sequence diagram with two lifelines: the shell, PID 22, on the left, and its child on the right. The shell reads the line ls /etc from descriptor zero. It calls fork, shown in the trace as clone, and the kernel creates PID 23 as an exact copy of the shell: same memory, same open descriptors, same environment. The child calls execve with the path /usr/bin/ls and the argument vector; the kernel throws away the copy's memory and loads ls into it, keeping the PID and the descriptors. ls runs: openat, getdents64, write to descriptor one. It calls exit_group with status zero and becomes a zombie holding only that number. Meanwhile the shell has been blocked in wait4 for PID 23; it now returns with the status, the shell stores it as dollar question mark and prints the prompt again. A side table lists the exit status conventions: zero success, one or two an error the program chose, 126 found but not executable, 127 not found, 128 plus N killed by signal N, so 143 is SIGTERM and 137 is SIGKILL.">
  <defs>
    <marker id="p1l03c-ar" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker>
    <marker id="p1l03c-arg" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#0fa07f"/></marker>
  </defs>
  <text x="450" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">fork, exec, wait: the four syscalls under every command</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <!-- actors -->
    <rect x="60" y="46" width="200" height="30" rx="8" fill="#c94a12" fill-opacity="0.12" stroke="#c94a12" stroke-width="1.7"/>
    <text x="160" y="65" text-anchor="middle" font-size="10.5" font-weight="700" fill="#c94a12">the shell · pid 22</text>
    <rect x="360" y="46" width="240" height="30" rx="8" fill="#7c5cff" fill-opacity="0.12" stroke="#7c5cff" stroke-width="1.7"/>
    <text x="480" y="65" text-anchor="middle" font-size="10.5" font-weight="700" fill="#7c5cff">the child · pid 23</text>
    <!-- lifelines -->
    <g stroke="currentColor" stroke-opacity="0.3" stroke-width="1.3" stroke-dasharray="4 5">
      <path d="M160 76 L160 430"/>
      <path d="M480 150 L480 372"/>
    </g>

    <!-- 1 read -->
    <rect x="70" y="92" width="180" height="30" rx="6" fill="#7f7f7f" fill-opacity="0.12" stroke="#7f7f7f" stroke-width="1.3"/>
    <text x="160" y="105" text-anchor="middle" font-size="8.5" fill="currentColor">read(0) → "ls /etc"</text>
    <text x="160" y="117" text-anchor="middle" font-size="7.5" fill="currentColor" opacity="0.7">split · expand · PATH → /usr/bin/ls</text>

    <!-- 2 fork -->
    <text x="160" y="146" text-anchor="middle" font-size="9.5" font-weight="700" fill="#c94a12">fork()  (clone in strace)</text>
    <path d="M168 154 L474 154" fill="none" stroke="currentColor" stroke-width="1.7" marker-end="url(#p1l03c-ar)"/>
    <text x="320" y="148" text-anchor="middle" font-size="8" fill="currentColor" opacity="0.8">the kernel makes an exact copy</text>
    <rect x="370" y="162" width="220" height="42" rx="6" fill="#7c5cff" fill-opacity="0.10" stroke="#7c5cff" stroke-width="1.3"/>
    <text x="480" y="177" text-anchor="middle" font-size="8.5" fill="currentColor">pid 23: same memory, same fds,</text>
    <text x="480" y="190" text-anchor="middle" font-size="8.5" fill="currentColor">same environment, same cwd</text>
    <text x="480" y="200" text-anchor="middle" font-size="7.5" fill="currentColor" opacity="0.7">fork returns 23 to the parent and 0 to the child</text>

    <!-- 3 execve -->
    <text x="480" y="228" text-anchor="middle" font-size="9.5" font-weight="700" fill="#7c5cff">execve("/usr/bin/ls", ["ls","/etc"], env)</text>
    <rect x="370" y="236" width="220" height="42" rx="6" fill="#7c5cff" fill-opacity="0.10" stroke="#7c5cff" stroke-width="1.3"/>
    <text x="480" y="251" text-anchor="middle" font-size="8.5" fill="currentColor">the copy's memory is thrown away and</text>
    <text x="480" y="264" text-anchor="middle" font-size="8.5" fill="currentColor">ls is loaded into it; pid and fds survive</text>
    <text x="480" y="274" text-anchor="middle" font-size="7.5" fill="currentColor" opacity="0.7">execve never returns on success</text>

    <!-- 4 ls runs -->
    <rect x="370" y="292" width="220" height="30" rx="6" fill="#7f7f7f" fill-opacity="0.12" stroke="#7f7f7f" stroke-width="1.3"/>
    <text x="480" y="305" text-anchor="middle" font-size="8.5" fill="currentColor">ls runs: openat · getdents64 · write(1)</text>
    <text x="480" y="317" text-anchor="middle" font-size="7.5" fill="currentColor" opacity="0.7">its output goes to the pty, not to the shell</text>

    <!-- 5 exit -->
    <text x="480" y="346" text-anchor="middle" font-size="9.5" font-weight="700" fill="#7c5cff">exit_group(0)</text>
    <text x="480" y="380" text-anchor="middle" font-size="8" fill="currentColor" opacity="0.8">pid 23 is now a zombie: a PID and one number</text>

    <!-- parent waiting -->
    <rect x="70" y="162" width="180" height="42" rx="6" fill="#c94a12" fill-opacity="0.10" stroke="#c94a12" stroke-width="1.3"/>
    <text x="160" y="177" text-anchor="middle" font-size="8.5" fill="currentColor">wait4(23, &amp;status)</text>
    <text x="160" y="190" text-anchor="middle" font-size="8.5" fill="currentColor">blocked, state S, for as long</text>
    <text x="160" y="200" text-anchor="middle" font-size="7.5" fill="currentColor" opacity="0.7">as ls takes: that is the "wait"</text>

    <!-- status back -->
    <path d="M474 366 L168 366" fill="none" stroke="#0fa07f" stroke-width="1.9" marker-end="url(#p1l03c-arg)"/>
    <text x="320" y="360" text-anchor="middle" font-size="8" fill="#0fa07f" font-weight="700">wait4 returns: status 0, the zombie is reaped</text>
    <rect x="70" y="380" width="180" height="42" rx="6" fill="#0fa07f" fill-opacity="0.10" stroke="#0fa07f" stroke-width="1.3"/>
    <text x="160" y="395" text-anchor="middle" font-size="8.5" fill="currentColor">$? = 0</text>
    <text x="160" y="408" text-anchor="middle" font-size="8.5" fill="currentColor">write(1, prompt) · read(0) again</text>

    <!-- exit status table -->
    <rect x="640" y="92" width="230" height="270" rx="9" fill="#e0930f" fill-opacity="0.08" stroke="#e0930f" stroke-width="1.6" stroke-linejoin="round"/>
    <text x="755" y="114" text-anchor="middle" font-size="10" font-weight="700" fill="#e0930f">WHAT $? MEANS</text>
    <g font-size="8.5" fill="currentColor">
      <text x="654" y="140" font-weight="700">0</text><text x="690" y="140">success, by convention</text>
      <text x="654" y="162" font-weight="700">1, 2 ...</text><text x="700" y="162">an error the program chose</text>
      <text x="690" y="175" opacity="0.75">(ls uses 2 for a bad path)</text>
      <text x="654" y="198" font-weight="700">126</text><text x="690" y="198">found, but not executable</text>
      <text x="690" y="211" opacity="0.75">(no x bit, or a bad #!)</text>
      <text x="654" y="234" font-weight="700">127</text><text x="690" y="234">not found on PATH</text>
      <text x="654" y="257" font-weight="700">128+N</text><text x="690" y="257">killed by signal N</text>
      <text x="690" y="270" opacity="0.75">143 = SIGTERM (15)</text>
      <text x="690" y="283" opacity="0.75">137 = SIGKILL (9): OOM, kill -9</text>
      <text x="690" y="296" opacity="0.75">130 = SIGINT (2): Ctrl+C</text>
      <text x="654" y="322" opacity="0.8">the shell sets 126 and 127 itself;</text>
      <text x="654" y="335" opacity="0.8">everything else comes out of</text>
      <text x="654" y="348" opacity="0.8">wait4, straight from the kernel</text>
    </g>
  </g>
  <text x="450" y="446" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="10.5" fill="currentColor" opacity="0.9">Fork copies the shell; exec replaces the copy with the program; wait collects the number it left behind.</text>
  <text x="450" y="462" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="10.5" fill="currentColor" opacity="0.9">There is no other way to start a program on Unix. Every service, every cron job, every Docker container begins this way.</text>
</svg>
```

- **`fork()`** asks the kernel to make an exact copy of the calling process: same memory, same open descriptors, same environment, same working directory. It returns twice: the child's PID to the parent, `0` to the child. (Modern libc implements it with `clone`, which is what `strace` shows.)
- **`execve()`** in the child replaces the copy's memory with a new program loaded from disk, keeping the PID and the descriptors. It never returns on success; the process that called it *is now* `ls`.
- **`wait4()`** in the parent blocks until the child exits, then returns the number the child passed to `exit()`. Until the parent collects it, the exited child lingers as a **zombie**: a PID and a status, nothing else (lesson 10).
- The shell stores that number in `$?`. Zero means success; anything else is failure, by convention, and the value is a code the program chose. Two are set by the shell itself: **127** when the name was not found anywhere, **126** when it was found but could not be executed. **128 + N** means the child was killed by signal N, so 143 is `SIGTERM` and 137 is `SIGKILL`.

The reason fork copies and exec replaces, rather than one call that "starts a program," is that the gap between them is where the shell sets things up for the child: which files its descriptors point at (that is redirection, lesson 07), which directory it runs in, which environment it gets. The child inherits all of it and then becomes something else.

### Which shell, and the shebang

There is more than one shell. `bash` is what you get on most Linux distributions for interactive use. `sh` is the POSIX shell, and on Debian `/bin/sh` is actually `dash`, a smaller and faster shell used for running scripts, which is why a script that uses bash features under `#!/bin/sh` fails. `zsh` is the macOS default and is bash-compatible for daily use. `/etc/shells` lists the ones a user may log in with. `echo $0` tells you which one you are in.

When you run `./script.sh`, the kernel's `execve` reads the first two bytes of the file. If they are `#!`, the rest of the line names an **interpreter**, and the kernel runs *that* program with the script's path appended as an argument: `#!/bin/sh` turns `./hi.sh one two` into `/bin/sh ./hi.sh one two`. That is the entire mechanism behind "executable scripts" in every language. Two things go wrong constantly, and the sandbox shows the first:

```console
$ printf '#!/bin/sh\necho running as $0 with $# args: $@\n' > /tmp/hi.sh
$ /tmp/hi.sh
bash: /tmp/hi.sh: Permission denied
$ echo $?
126
$ chmod +x /tmp/hi.sh;  /tmp/hi.sh one two
running as /tmp/hi.sh with 2 args: one two
```

The file existed and the shell found it, but the kernel refused `execve` because the execute permission bit was not set: exit 126, and lesson 06 is about that bit. The second failure is `bad interpreter: No such file or directory` when the path after `#!` is wrong on this machine, most often because the file was saved with Windows line endings and the kernel is looking for `sh\r`. The runbook covers both.

### The keys, and the files that run before you type

A few things the interactive shell does that scripts do not:

| key or command | what happens |
|---|---|
| `Tab` | complete a command or path; twice to list the options |
| `Ctrl+C` | the pty sends `SIGINT` to the foreground process; it usually dies |
| `Ctrl+D` | end-of-file on stdin; at a prompt, the shell exits |
| `Ctrl+Z` | suspend the foreground process (lesson 10 explains `fg`, `bg`, `jobs`) |
| `Ctrl+R` | search command history backwards |
| `Ctrl+L`, `clear` | redraw the screen |
| `history`, `!!`, `!$` | list history, repeat the last command, reuse its last argument |
| `Ctrl+A`, `Ctrl+E`, `Ctrl+W` | start of line, end of line, delete the previous word |

Before you see the first prompt, bash reads **dotfiles**: `/etc/profile` and `~/.profile` (or `~/.bash_profile`) for a **login shell**, the one `ssh` and a console login give you; `~/.bashrc` for every **interactive** shell after that. Aliases, `PATH` changes, and prompt tweaks go there. A **non-interactive** shell, the kind that runs a script, `cron` job or `ssh host command`, reads none of them, which is the entire reason for "it works when I type it and fails from cron." Lesson 09 and lesson 11 return to this; the runbook tells you where to put each kind of setting so that it survives.

## Build It

The shell for this lesson is [`code/minishell.py`](../code/minishell.py): about 120 lines, no dependencies, and it runs on macOS and Linux. By default it plays a scripted session and exits; pass `-i` to type into it yourself.

```bash
python3 phases/01-linux-and-the-command-line/03-the-shell/code/minishell.py
python3 phases/01-linux-and-the-command-line/03-the-shell/code/minishell.py -i    # Ctrl+D to leave
```

It is the six-step diagram, in order. **The PATH search** is a loop over `$PATH` looking for an executable file; a name with a slash skips it:

```python
def find_in_path(name):
    if "/" in name:
        return name                                   # a path already; use it as given
    for directory in os.environ.get("PATH", "").split(":"):
        candidate = os.path.join(directory or ".", name)
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return None
```

**The builtins** are the commands that must change the shell's own process. `cd` is `chdir(2)` called on ourselves, and `export` writes into our own environment so that later forks inherit it:

```python
def builtin_cd(args):
    target = args[0] if args else os.environ.get("HOME", "/")
    try:
        os.chdir(os.path.expanduser(target))          # changes THIS process's cwd
        return 0
    except OSError as e:
        print(f"minishell: cd: {target}: {e.strerror}", file=sys.stderr)
        return 1
```

**Expansion** handles the four things you just read about, `$?`, `$$`, `$NAME`, `~` and globs, on each word; `shlex.split` did the quoting-aware split one line earlier, which is why `"a  b"` arrives as one word and `'$HOME'` arrives with its dollar sign intact.

**Running a command** is fork, exec, wait, with the exit-status conventions bash uses:

```python
pid = os.fork()                                       # one process becomes two
if pid == 0:
    try:
        os.execv(program, [name] + args)              # the child becomes the program
    except OSError as e:
        print(f"minishell: {name}: {e.strerror}", file=sys.stderr)
        os._exit(126)
else:
    _, status = os.waitpid(pid, 0)                    # the parent waits
    if os.WIFEXITED(status):
        last_status = os.WEXITSTATUS(status)          # what the program passed to exit()
    elif os.WIFSIGNALED(status):
        last_status = 128 + os.WTERMSIG(status)       # killed by a signal: bash adds 128
```

Run it and read the transcript against the diagram. The prompt shows `$?` in brackets:

```console
[0] minishell $ cd /definitely/not/here
minishell: cd: /definitely/not/here: No such file or directory

[1] minishell $ echo the last exit status was $?
the last exit status was 1

[0] minishell $ export GREETING=hi

[0] minishell $ sh -c 'echo child sees GREETING=$GREETING'
child sees GREETING=hi

[0] minishell $ echo *.py
minishell.py

[0] minishell $ ls /definitely/not/here
ls: cannot access '/definitely/not/here': No such file or directory

[2] minishell $ definitely-not-a-command
minishell: definitely-not-a-command: command not found

[127] minishell $ /etc/hostname
minishell: /etc/hostname: Permission denied

[126] minishell $ python3 -c 'import os, signal; os.kill(os.getpid(), signal.SIGTERM)'
minishell: python3: terminated by signal 15

[143] minishell $ echo 'single quotes: $HOME stays literal'
single quotes: $HOME stays literal
```

Every number in the brackets came out of `waitpid`, except 127 and 126, which the shell decided itself, exactly as bash does. The `sh -c` line proves the environment travels down at fork: the exported variable reached a grandchild. And `echo *.py` printed a filename because the mini shell expanded the glob; `echo` was handed a name, not a star.

Now put `strace` on the mini shell inside the sandbox, showing only the four calls that matter:

```console
$ strace -f -e trace=execve,clone,wait4,chdir,exit_group -o /tmp/ms.txt python3 minishell.py
$ grep -E 'clone|execve|exit_group|chdir|killed' /tmp/ms.txt
22  execve("/usr/local/bin/python3", ["python3", "minishell.py"], ...) = 0
22  clone(child_stack=NULL, flags=...|SIGCHLD, ...) = 23
23  execve("/usr/bin/echo", ["echo", "hello", "from", "a", "shell", "written", "in", "Python"], ...) = 0
23  exit_group(0)
22  chdir("/tmp")                     = 0
22  chdir("/definitely/not/here")     = -1 ENOENT (No such file or directory)
22  clone(...) = 28
28  execve("/usr/bin/ls", ["ls", "/definitely/not/here"], ...) = 0
28  exit_group(2)
22  clone(...) = 31
31  execve("/usr/local/bin/python3", ["python3", "-c", "import os, signal; os.kill(os.ge"...], ...) = 0
31  +++ killed by SIGTERM +++
```

PID 22 is the shell. Every command is a `clone` that makes a new PID, an `execve` in that PID with the finished `argv`, and an `exit_group` with the number that became `$?`. `cd` is two `chdir` calls by PID 22 itself, no child, and the failed one is the kernel's `ENOENT` from lesson 01. The signal death shows as `killed by SIGTERM`, which `waitpid` reported and the shell turned into 143.

## Use It

Everything the mini shell did, bash does the same way, and you can watch it. Inside `make shell`:

```console
$ ls /nope;  echo "exit status: $?"
ls: cannot access '/nope': No such file or directory
exit status: 2
$ true;  echo $?;  false;  echo $?
0
1
$ definitely-not-a-command;  echo $?
bash: definitely-not-a-command: command not found
127
$ /etc/hostname;  echo $?
bash: /etc/hostname: Permission denied
126
```

The same four numbers, 2, 0, 1, 127, 126, for the same four reasons. Trace bash running a command and you get the same syscalls as the mini shell, with one refinement worth knowing about:

```console
$ strace -f -e trace=execve,clone,wait4,chdir -o /tmp/t.txt bash -c 'cd /tmp; ls /etc/hostname'
$ grep -vE 'resumed|unfinished' /tmp/t.txt
27  execve("/usr/bin/bash", ["bash", "-c", "cd /tmp; ls /etc/hostname"], ...) = 0
27  chdir("/tmp")                     = 0
27  execve("/usr/bin/ls", ["ls", "/etc/hostname"], ...) = 0
27  +++ exited with 0 +++
```

`cd` is a `chdir` by bash itself, as expected. But there is no `clone`: bash noticed that `ls` was the *last* command of `-c` and executed it directly in its own process, skipping the fork, since it had nothing left to do afterwards. Same PID 27 all the way through. It is a small optimisation with one visible consequence: the process `systemd` or Docker sees is `ls`, not `bash`, which is why a `CMD ["sh", "-c", "exec myserver"]` in a Dockerfile makes signals reach `myserver` directly (Phase 11, lesson 02).

Now the shell's own tools for the three questions this lesson keeps asking:

```console
$ type -a python3;  which -a python3          # where does the name resolve, and are there others?
python3 is /usr/local/bin/python3
/usr/local/bin/python3
$ hash                                        # what has the shell cached?
hits    command
   1    /usr/bin/ls
$ bash -x -c 'NAME=world; echo hello $NAME; ls /nope 2>/dev/null || echo fallback'
+ NAME=world
+ echo hello world
hello world
+ ls /nope
+ echo fallback
fallback
```

`bash -x` prints each command **after expansion** and before it runs; every `+` line is what the program actually received. It is the single best tool for a shell script that does the wrong thing, because it shows you step 3 of the diagram happening.

Two more, for orientation on any box you land on:

```console
$ echo $0;  echo $SHELL;  cat /etc/shells
bash
/bin/bash
/bin/sh
/bin/bash
/bin/rbash
/usr/bin/dash
$ tty;  ps -o pid,ppid,comm
not a tty
    PID    PPID COMMAND
      1       0 bash
     20       1 ps
```

`$0` is the shell you are in, `$SHELL` the one your account is configured to start, and `/etc/shells` the ones allowed. The `tty` line says `not a tty` because this session came through `docker compose run -T`, with pipes instead of a pty: the "no terminal at all" case from the first diagram, live. And `ps` shows the relationship the whole lesson is about: `ps` is PID 20, a child of the shell at PID 1, which is what `fork` produced a moment before `execve` turned it into `ps`.

## Ship It

The artifact for this lesson is a runbook: [`outputs/runbook-command-not-found.md`](../outputs/runbook-command-not-found.md). It is organised around the resolution order the shell uses (alias, function, builtin, hash, PATH) and the two exit codes that tell you which step failed. `command not found` (127): typo, not installed, not on PATH, in the current directory, cached stale. `Permission denied` (126): no execute bit, wrong owner, a `noexec` mount, a directory. `bad interpreter`: a shebang that names a missing path, almost always Windows line endings. And the big one, "it works in my terminal but not in cron, systemd, sudo or Docker," which is never the command and always the environment, with a table of where to put each setting so it survives.

## Think about it

1. `cd /tmp && ls` works, but a script containing only `cd /tmp` leaves you where you were when it finishes. Explain both with fork and `chdir`.
2. A teammate adds `.` to the front of their `PATH` "so I can run my scripts without `./`". Describe an attack that now works against them the next time they `cd` into a directory they do not control.
3. `for f in *.log; do rm "$f"; done` runs in a directory with no `.log` files and prints `rm: cannot remove '*.log'`. Which step of the six did not do what the author assumed?
4. `python3 app.py` prints its log lines immediately in your terminal and prints nothing for minutes when run under `systemd`, then dumps everything at once. Which of the three programs in the first diagram is missing, and what did Python conclude from its absence?

## Key takeaways

- A terminal session is **three programs and a device**: the terminal emulator draws, the kernel's **pty** turns keystrokes into lines and `Ctrl+C` into a signal, and the **shell** reads lines and starts children. `cron`, `systemd` and Docker have no pty, and programs notice.
- The prompt is `PS1` written to fd 1 followed by a blocking `read(0)`. `#` at the end means root.
- Before a program runs, the shell **splits** the line honouring quotes, **expands** `$vars`, `~` and globs, removes the quotes, and **resolves** the first word as alias, function, builtin, or a left-to-right **PATH** search. The program receives a finished `argv` and never sees a quote, a `$` or a `*`.
- **Double quotes** keep spaces and stop globbing but expand variables; **single quotes** stop everything. Quote every variable that could contain a space or be empty.
- `NAME=v` is a shell variable; `export` puts it in the **environment**, which is copied into children at `fork`. Children cannot change a parent's environment. That is why `cd` and `export` are **builtins**.
- Every command is **fork, exec, wait**: copy the shell, replace the copy with the program, collect its exit status into `$?`. 0 is success; 126 is found-but-not-executable; 127 is not found; 128+N is killed by signal N.
- The current directory is not on `PATH` on purpose; run local programs as `./name`. A script runs through its `#!` interpreter and needs the execute bit.
- `type -a`, `which -a`, `hash -r`, `bash -x` and `echo $?` answer nearly every "why did that not run" in under a minute; the runbook orders the rest.

Next: [The Filesystem Hierarchy](../04-the-filesystem-hierarchy/). You can run commands. Now learn where things are on a Linux box, why `/etc`, `/var` and `/usr/local` exist, and build `ls` from `stat`.
