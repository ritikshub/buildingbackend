"""
The Shell — a working shell in about 120 lines, so bash is never magic.

A shell is a loop: read a line, split it into words, expand variables and
globs, decide whether the first word is a builtin, otherwise search PATH for
a program, fork, exec it in the child, wait for it in the parent, and remember
the exit status. That is the whole job, and this file does all of it with the
same system calls bash uses: fork(2), execve(2), wait4(2), chdir(2).

Runs a scripted session by default and exits (self-terminating). Pass -i to
drive it interactively; Ctrl+D or `exit` leaves.

Docs: phases/01-linux-and-the-command-line/03-the-shell/docs/en.md
Spec: POSIX.1-2017 Shell Command Language (XCU 2), fork(), execve(), waitpid();
      Linux man-pages execve(2), wait4(2), bash(1) "COMMAND EXECUTION"

Run:
    python minishell.py        # scripted demo
    python minishell.py -i     # interactive
"""

import glob
import os
import shlex
import sys

last_status = 0  # what bash calls $?


# ─── 1 · Find the program: the PATH search ───────────────────────────────────
def find_in_path(name):
    """Return the first executable file called `name` in $PATH, or None.
    A name containing a slash is a path already: use it as given."""
    if "/" in name:
        return name
    for directory in os.environ.get("PATH", "").split(":"):
        candidate = os.path.join(directory or ".", name)
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return None


# ─── 2 · Builtins: things that must run inside the shell itself ──────────────
def builtin_cd(args):
    # cd cannot be a program: a child process changing ITS directory would not
    # change the shell's. It has to be the shell calling chdir(2) on itself.
    target = args[0] if args else os.environ.get("HOME", "/")
    try:
        os.chdir(os.path.expanduser(target))
        return 0
    except OSError as e:
        print(f"minishell: cd: {target}: {e.strerror}", file=sys.stderr)
        return 1


def builtin_export(args):
    # Same reason: the variable must land in the shell's own environment so
    # that every child forked afterwards inherits it.
    for pair in args:
        name, _, value = pair.partition("=")
        os.environ[name] = value
    return 0


def builtin_exit(args):
    raise SystemExit(int(args[0]) if args else last_status)


def builtin_pwd(args):
    print(os.getcwd())
    return 0


BUILTINS = {"cd": builtin_cd, "export": builtin_export, "exit": builtin_exit, "pwd": builtin_pwd}


# ─── 3 · Expansion: what the shell rewrites before the program ever sees it ──
def expand(words):
    out = []
    for w in words:
        if w == "$?":                              # the last exit status
            out.append(str(last_status))
        elif w == "$$":                            # this shell's own PID
            out.append(str(os.getpid()))
        elif w.startswith("$"):                    # $HOME -> /root
            out.append(os.environ.get(w[1:], ""))
        elif any(ch in w for ch in "*?["):        # *.md -> every matching name, sorted
            matches = sorted(glob.glob(w))
            out.extend(matches if matches else [w])
        elif w.startswith("~"):                   # ~/x -> /root/x
            out.append(os.path.expanduser(w))
        else:
            out.append(w)
    return out


# ─── 4 · Run one command: fork, exec, wait ───────────────────────────────────
def run(line):
    global last_status
    try:
        words = shlex.split(line, comments=True)  # quoting rules: "a b" is one word
    except ValueError as e:
        print(f"minishell: {e}", file=sys.stderr)
        last_status = 2
        return
    if not words:
        return
    words = expand(words)
    name, args = words[0], words[1:]

    if name in BUILTINS:                          # no new process for these
        last_status = BUILTINS[name](args)
        return

    program = find_in_path(name)
    if program is None:
        print(f"minishell: {name}: command not found", file=sys.stderr)
        last_status = 127                         # bash's number for "not found"
        return
    if not os.path.exists(program):
        print(f"minishell: {name}: No such file or directory", file=sys.stderr)
        last_status = 127
        return
    if not os.access(program, os.X_OK):
        print(f"minishell: {name}: Permission denied", file=sys.stderr)
        last_status = 126                         # bash's number for "found but cannot run"
        return

    pid = os.fork()                               # one process becomes two
    if pid == 0:
        # ── the child: replace myself with the program ──
        try:
            os.execv(program, [name] + args)      # never returns on success
        except OSError as e:
            print(f"minishell: {name}: {e.strerror}", file=sys.stderr)
            os._exit(126)                         # bash's number for "found but cannot run"
    else:
        # ── the parent: wait, then read the status out of the kernel ──
        _, status = os.waitpid(pid, 0)
        if os.WIFEXITED(status):
            last_status = os.WEXITSTATUS(status)  # the number the program passed to exit()
        elif os.WIFSIGNALED(status):
            last_status = 128 + os.WTERMSIG(status)  # killed by a signal: bash adds 128
            print(f"minishell: {name}: terminated by signal {os.WTERMSIG(status)}", file=sys.stderr)


# ─── 5 · The loop ────────────────────────────────────────────────────────────
def repl():
    while True:
        try:
            line = input(f"[{last_status}] minishell {os.path.basename(os.getcwd()) or '/'} $ ")
        except EOFError:                          # Ctrl+D: end of input
            print()
            return
        run(line)


DEMO = [
    "echo hello from a shell written in Python",
    "pwd",
    "cd /tmp",
    "pwd",
    "cd /definitely/not/here",
    "echo the last exit status was $?",
    "export GREETING=hi",
    "sh -c 'echo child sees GREETING=$GREETING'",
    "echo my home is $HOME and my shell pid is $$",
    "echo *.py",
    "ls /definitely/not/here",
    "true",
    "false",
    "definitely-not-a-command",
    "/etc/hostname",
    "python3 -c 'import os, signal; os.kill(os.getpid(), signal.SIGTERM)'",
    "echo 'single quotes: $HOME stays literal'",
    "echo \"a  b\"   c",
]

if __name__ == "__main__":
    if "-i" in sys.argv[1:]:
        repl()
        sys.exit(last_status)
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    for line in DEMO:
        print(f"\n[{last_status}] minishell $ {line}")
        sys.stdout.flush()
        run(line)
    print(f"\n[{last_status}] minishell $ exit")
