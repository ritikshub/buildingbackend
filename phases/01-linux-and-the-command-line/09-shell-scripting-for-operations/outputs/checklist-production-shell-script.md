---
name: checklist-production-shell-script
description: The review checklist for any shell script that will run on a server or in CI — strict mode, quoting and guards, exit codes and logging, temp files and traps, idempotency, argument handling, the environment it will actually run in, and the point at which it should be Python instead
phase: 01
lesson: 09
---

# Before a shell script runs on a server

A script is a command you will run without watching. Everything below
exists because the unwatched run is the one that deletes the wrong thing,
half-finishes, or reports success while failing. Work top to bottom; the
first section alone prevents most incidents.

## 1 · The header (non-negotiable)

- [ ] `#!/usr/bin/env bash` on line 1 (or `#!/bin/sh` if, and only if, the script uses no bash features and has been tested under `dash`). Never a bare `#!/bin/bash` on a box where bash might live elsewhere.
- [ ] `set -euo pipefail` on line 2. `-e` exits on the first failing command, `-u` makes an unset variable an error instead of an empty string, `pipefail` makes a pipeline fail when any stage fails. Know the exceptions: `-e` does not fire inside `if`, `while`, `&&`, `||` conditions, or in a command substitution assigned with `local`.
- [ ] `IFS=$'\n\t'` if the script loops over output that may contain spaces.
- [ ] A comment block: what the script does, what it needs (variables, files, permissions), what it changes, and an example invocation.
- [ ] `shellcheck script.sh` passes, or every ignored warning has a `# shellcheck disable=SCxxxx` with a reason beside it.

## 2 · Variables and quoting

- [ ] **Every** expansion is double-quoted: `"$var"`, `"$(cmd)"`, `"${arr[@]}"`, `"$@"`. The exceptions are deliberate and commented.
- [ ] Anything that feeds `rm -rf`, `mv`, `chown -R`, `find -delete` is guarded: `"${DIR:?DIR must be set}"` and, if it is a path, checked for the value you expect (`[[ "$DIR" == /srv/app/* ]] || die`).
- [ ] Optional settings use `"${VAR:-default}"`; required ones use `"${VAR:?message}"` near the top so the script fails before it does anything.
- [ ] `local` on every variable inside a function. Uppercase for configuration and exported names, lowercase for locals, so a reader can tell which is which.
- [ ] `--` before file arguments in `rm`, `mv`, `cp`, `ls`, `grep` when a name could start with `-`.
- [ ] No parsing of `ls` output. `find -print0 | xargs -0`, or a glob loop `for f in "$dir"/*.log; do [[ -e "$f" ]] || continue; ...; done`.
- [ ] Arithmetic in `$(( ))`, tests in `[[ ]]` (bash) or `[ ]` (POSIX), never `let` or backticks.

## 3 · Exit codes and errors

- [ ] The script exits **0 only when it did the whole job.** Partial success is a non-zero exit and a message that says how far it got.
- [ ] Every command whose failure matters is either covered by `set -e` or checked explicitly (`if ! cmd; then ... fi`). Commands allowed to fail say so: `cmd || true`.
- [ ] Failure output goes to **stderr** (`>&2`) with the script name and the reason. `die() { echo "$0: $*" >&2; exit 1; }` is enough.
- [ ] Output that another program will consume goes to **stdout** and nothing else does: no progress messages, no banners on descriptor 1.
- [ ] Pipelines that may legitimately be cut short by `head` handle exit 141 (`|| [[ $? -eq 141 ]]`) or avoid `pipefail` for that line.
- [ ] `trap 'echo "$0: failed at line $LINENO" >&2' ERR` in scripts long enough that "it failed" is not enough information.

## 4 · Temp files, cleanup, signals

- [ ] Temp files and directories come from `mktemp` / `mktemp -d`, never a fixed name in `/tmp`.
- [ ] `trap cleanup EXIT` removes them on success, failure and `Ctrl+C`. `EXIT` covers all three; `INT`/`TERM` are only needed to do something extra on a signal.
- [ ] Work happens in the temp dir; the real location is touched **last**, with one `mv` or `ln -sfn` + `mv -T`, so an interrupted run leaves the old state intact (lesson 05's atomic replace).
- [ ] Anything downloaded is verified (`sha256sum -c`) before it is used.
- [ ] Locking, if two copies must not overlap: `exec 9>/var/lock/name.lock; flock -n 9 || { echo "already running" >&2; exit 0; }`.

## 5 · Idempotency and safety

- [ ] Running the script twice is the same as running it once: `mkdir -p`, `ln -sfn`, `useradd` guarded by `id user &>/dev/null ||`, `install` instead of `cp` + `chmod` + `chown`.
- [ ] A dry-run mode (`--dry-run` that prints commands instead of running them) for anything destructive, and it was used once before the real run.
- [ ] Destructive steps print what they are about to do, with the expanded values, before doing it.
- [ ] Nothing is `rm -rf`'d that could be moved aside instead; old releases are pruned by count, keeping the current one and the previous one.
- [ ] The script never `cd`s and then uses relative paths without checking `cd` succeeded (`cd "$dir" || die`). Prefer absolute paths built from one root variable.

## 6 · Arguments and configuration

- [ ] Arguments are parsed with a `case` loop or `getopts`; an unknown argument is an error and prints usage; `-h`/`--help` prints usage and exits 0 (or 2, consistently).
- [ ] Configuration comes from environment variables or a sourced file with a documented name; secrets never appear on the command line (`ps` shows them to everyone) and never in the script.
- [ ] `"$@"` is passed through whole when the script wraps another command.

## 7 · The environment it will actually run in

- [ ] It has been run **from the context it will run in**: `cron`, a `systemd` unit, `sudo`, CI, `ssh host script` (lesson 03's runbook, section 4). PATH, HOME, the user, the working directory and the absence of a terminal all differ from your shell.
- [ ] Commands are invoked by absolute path or PATH is set explicitly at the top.
- [ ] It does not read stdin unless that is its job; under cron stdin is empty and an unexpected `read` hangs forever.
- [ ] It does not assume a terminal: no colours without an `isatty` check, no `sudo` password prompts (`sudo -n`), no interactive confirmations without a `--yes` flag for automation.
- [ ] It is executable (`chmod +x`), owned by root if it runs as root, and not writable by the user it runs as.
- [ ] Its output is captured somewhere (`>> /var/log/name.log 2>&1` in the crontab, or the journal under systemd) and someone reads failures.

## 8 · When it should be Python instead

Rewrite the script in Python (or another real language) when any of these is true:

- it parses structured data (JSON, CSV with quotes, YAML, HTML);
- it needs a data structure more complex than a flat array, or arithmetic on non-integers;
- it makes HTTP requests with headers and handles their errors;
- it has more than one non-trivial condition per function, or more than about 150 lines;
- it needs tests, retries with backoff, or concurrency;
- a `sed`/`awk` expression in it took more than a minute to get right.

Keep it in bash when it mostly composes other commands, runs in a place where Python may not exist (an initramfs, a minimal container, a CI image), or is under a screen long and read more than it is edited.
