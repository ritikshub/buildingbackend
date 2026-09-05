---
name: runbook-command-not-found
description: A diagnosis runbook for the four ways a command fails to start — "command not found", "Permission denied", "bad interpreter", and "works in my terminal but not in cron/systemd/sudo/Docker" — organised around the exact order the shell resolves a name and the two exit codes (127 and 126) it uses to tell you which step failed
phase: 01
lesson: 03
---

# The command will not start

Four messages, four causes, one order of resolution. Work top to bottom; the
shell tells you which step failed through the exit code (`echo $?` right
after the failure): **127** means the name was never resolved, **126** means
it was found but could not be executed, anything else means it ran.

## 0 · How the shell resolves a name (the order that explains everything)

When you type `name args`, bash tries, in this order, and stops at the first hit:

1. **Alias**: `alias ll='ls -l'`. Text substitution before anything else.
2. **Function**: a shell function you or a dotfile defined.
3. **Builtin**: `cd`, `export`, `echo`, `pwd`, `exit`, `source`, `read`. Run inside the shell process; no program is started.
4. **Hash table**: the shell remembers where it found a program last time.
5. **PATH search**: for each directory in `$PATH`, left to right, is there an executable file with this name?

A name containing a slash (`./run.sh`, `/usr/bin/python3`, `bin/app`) skips all five: it is a path, used as given.

```bash
type -a name        # shows EVERY match in order: alias, function, builtin, and each PATH hit
which name          # only the PATH hit; silent about aliases, functions and builtins
command -v name     # POSIX-portable version of type
hash                # what the shell has cached; hash -r forgets it all
echo "$PATH" | tr ':' '\n'
```

## 1 · `command not found` (exit 127)

- [ ] **Typo, or the program is not installed.** `type -a name`. Nothing? Then either install it (lesson 13) or it is in a directory that is not on your PATH.
- [ ] **It is installed, but not on PATH.** `ls -l /usr/local/bin/name ~/.local/bin/name /opt/*/bin/name`. Found one? Add its directory: `export PATH="$HOME/.local/bin:$PATH"`, then put that line in `~/.bashrc` or `~/.profile` so it survives a new shell.
- [ ] **It is in the current directory.** The current directory is deliberately not on PATH. Run it as `./name`, never by adding `.` to PATH (a malicious `ls` in any directory you `cd` into would then run).
- [ ] **The PATH was changed by something.** `echo $PATH` looks wrong or short. A dotfile, a `PATH=` line in a script that forgot `:$PATH`, or `env -i`. Compare with `getconf PATH` (the system default) and check `~/.bashrc`, `~/.profile`, `/etc/profile`, `/etc/environment`.
- [ ] **It was just installed and the shell cached a stale location.** `hash -r`.
- [ ] **You are root via `sudo`, and root's PATH is different.** See section 4.

## 2 · `Permission denied` (exit 126)

The name resolved to a file. The kernel refused to execute it.

- [ ] **No execute bit.** `ls -l name` shows `-rw-r--r--`. Fix: `chmod +x name` (lesson 06). Scripts you wrote or downloaded are the usual case.
- [ ] **You are not the owner and the mode denies you.** `ls -l` shows `-rwx------ root`. Either you need to be that user (`sudo -u`), or the mode is wrong.
- [ ] **The filesystem is mounted `noexec`.** `findmnt -T name` and look for `noexec` in OPTIONS. `/tmp`, `/dev/shm`, and many container volumes are. Move the file or run it through its interpreter explicitly: `python3 name.py`, `sh name.sh`.
- [ ] **It is a directory.** `type -a name` says the PATH hit is a directory, or you typed a directory name. `ls -ld name`.
- [ ] **SELinux or AppArmor denied it.** On RHEL-family, `ausearch -m avc -ts recent`; the mode bits are fine but a policy is not.

## 3 · `bad interpreter: No such file or directory` (exit 126)

The script's first line, the **shebang** `#!`, names a program that does not exist at that path.

- [ ] **Carriage returns.** The file was edited on Windows: the line is really `#!/bin/bash\r`, and the kernel looks for `bash\r`. Confirm with `head -1 name | od -c` (you will see `\r`). Fix: `sed -i 's/\r$//' name` or `dos2unix name`.
- [ ] **The interpreter is somewhere else on this box.** `#!/usr/bin/python3` on a machine where Python is `/usr/local/bin/python3`. Prefer `#!/usr/bin/env python3`, which searches PATH for it.
- [ ] **The interpreter is not installed.** `#!/bin/bash` on Alpine (which ships `ash` only). Install it, or write for `#!/bin/sh`.
- [ ] **No shebang at all**, and you ran `./name`. The kernel tries it as a binary and fails; bash falls back to running it as a shell script, which works until the script is not a shell script. Add the shebang.

## 4 · "It works in my terminal but not in cron / systemd / sudo / Docker"

The command is fine. The **environment** it runs in is not yours.

- [ ] **cron** starts jobs with a minimal PATH (`/usr/bin:/bin`) and no dotfiles. Use absolute paths inside the crontab, or set `PATH=` at the top of the crontab (lesson 11).
- [ ] **systemd** units get a fixed default PATH and none of your `~/.bashrc`. Use absolute paths in `ExecStart=`, and `Environment=` or `EnvironmentFile=` for variables (lesson 11).
- [ ] **sudo** resets PATH to `secure_path` from `/etc/sudoers` and drops most variables. `sudo name` fails where `name` works: run `sudo $(which name)` or `sudo env "PATH=$PATH" name`, or add the directory to `secure_path` (lesson 06).
- [ ] **Docker** `RUN`/`CMD` lines run in `/bin/sh -c`, with the image's PATH, as the image's user, and without your shell's aliases and functions. `ENV PATH=...` in the Dockerfile, or an absolute path.
- [ ] **SSH non-interactive commands** (`ssh host name`) run without an interactive shell, so `~/.bashrc` may exit early (many distributions put `[ -z "$PS1" ] && return` at the top). Put PATH changes in `~/.profile` or `~/.bash_profile`, or use `ssh host 'bash -lc name'` (lesson 17).
- [ ] **A different user.** `id` in the failing context. Their HOME, PATH and dotfiles are not yours.
- [ ] **A virtual environment** was activated in your terminal and not in the job. `which python3` in both contexts. Use the venv's absolute interpreter path: `/opt/app/.venv/bin/python3`.

Prove it: run `env` from inside the failing context (`* * * * * env > /tmp/cron-env.txt` in cron, `ExecStart=/usr/bin/env` in a throwaway unit, `sudo env`) and diff it against your terminal's `env`.

## 5 · The program starts, then dies immediately

Not a resolution problem, but the same first minute of debugging:

- [ ] `echo $?` right after. **1** or **2** is usually a usage error: read stderr. **126/127** inside a script means a command *inside* the script had one of the problems above. **128 + N** means killed by signal N: 137 is `SIGKILL` (the OOM killer, or `kill -9`), 139 is `SIGSEGV` (a crash), 143 is `SIGTERM` (lesson 10).
- [ ] `strace -f -o /tmp/t.txt name` and read the last twenty lines (lesson 01's runbook). The `execve` line shows what was actually executed with which arguments; a failing `openat` right after it shows the config or library it wanted.
- [ ] `bash -x script.sh` prints every line as it runs, after expansion. The first line that looks wrong is the bug.

## 6 · Write the fix where it will survive

| you changed | put it in | so that |
|---|---|---|
| your PATH | `~/.profile` (login shells) and `~/.bashrc` (interactive shells) | every new terminal and SSH session has it |
| everyone's PATH | `/etc/profile.d/name.sh` | every user has it |
| a service's PATH or variables | the unit's `Environment=` / `EnvironmentFile=` | it does not depend on any human's dotfiles |
| a cron job's PATH | the top of the crontab | the job runs the same at 3 a.m. as in your terminal |
