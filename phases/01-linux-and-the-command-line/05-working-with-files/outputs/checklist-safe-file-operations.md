---
name: checklist-safe-file-operations
description: The pre-flight checklist for destructive file commands on a server (rm, mv, cp, tar, in-place edits) — dry-run first, quote and guard variables, use the atomic-replace pattern, keep a way back, and know which operations a running process will notice
phase: 01
lesson: 05
---

# Before you touch a file on a server

`rm` has no trash. `mv` over an existing file replaces it silently. `cp` onto
a running binary can crash the process. `tar` extracts wherever it is told.
None of these ask, and none can be undone. This checklist is the thirty
seconds that make them safe.

## 1 · Before any rm, mv or cp with a wildcard or a variable

- [ ] **See the list first.** Replace the command with `ls` or `echo` and read the expansion: `ls -d /var/log/app/*.log` before `rm /var/log/app/*.log`; `echo rm -rf "$DIR"/build` before running it. What you see is exactly what the program will receive (lesson 03).
- [ ] **Every variable is double-quoted**: `"$DIR"`, `"$f"`. An unquoted variable with a space in it becomes two arguments; an empty one vanishes.
- [ ] **Every variable that feeds `rm -rf` is guarded against being empty**: `rm -rf "${DIR:?DIR is not set}"/build`. With `DIR` unset, the unguarded form is `rm -rf /build`; with a trailing slash inside the quotes it is `rm -rf /`.
- [ ] **`--` before file arguments** when a name might start with a dash: `rm -- "$f"`. A file called `-rf` is otherwise an option.
- [ ] **Absolute paths, or a `cd` you have checked.** `rm -rf ./data` in the wrong directory is the most common self-inflicted outage there is. `pwd` first; better, `rm -rf /srv/app/data`.
- [ ] **No `rm -rf` of a directory you are inside**, and no `rm -rf` of a path built by string concatenation without printing it.
- [ ] **Globs: know what `*` matches.** It does not match dotfiles; `rm *` leaves `.env` behind, and `rm -rf .*` matches `..`, which is your parent directory (modern `rm` refuses it, but not every tool does).
- [ ] **`find` with `-delete` or `-exec rm`**: run the same `find` with `-print` first, read every line, then add the action. Put `-delete` last; before `-name` it deletes everything.

## 2 · Keep a way back

- [ ] **Move, do not delete**, when you are not certain: `mv /etc/app/app.yaml /etc/app/app.yaml.$(date +%F)` or `mkdir -p /root/trash && mv ... /root/trash/`. Delete the trash next week.
- [ ] **`cp -a` a config before editing it**: `cp -a app.yaml app.yaml.bak`. `-a` keeps mode, owner and timestamps so the backup is a faithful copy.
- [ ] **`tar -czf /root/backup-$(date +%F).tar.gz /etc/app /var/lib/app`** before a migration, a version bump or a bulk rename. Check it: `tar -tzf` lists what is inside.
- [ ] **For data directories, a snapshot** (LVM, ZFS, the cloud provider's disk snapshot) is faster and safer than tar. Take it, then act.
- [ ] **`rm -i`, `mv -i`, `cp -i`** prompt before overwriting; `cp -n` and `mv -n` never overwrite. In scripts prefer `-n` (no prompt to hang on) and check the exit status.

## 3 · Replacing a file something is reading

- [ ] **Use the atomic replace**: write to a temp file *in the same directory*, `sync` it, then `mv` it over the target. `mv` on one filesystem is `rename(2)`, one atomic step: readers see the old file or the new one, never a half-written one. `tmp=$(mktemp /etc/app/app.yaml.XXXXXX) && cat > "$tmp" && mv "$tmp" /etc/app/app.yaml`.
- [ ] **Not `cp new old` and not `echo > old`.** Both truncate the target first and then fill it; a reader in that window sees an empty or partial file. A service that reloads config on a timer can read the empty file and crash.
- [ ] **A binary that is running: `mv` the new one into place, never `cp` over it.** `cp` fails with `Text file busy` (ETXTBSY) on Linux or, worse, corrupts the mapped pages of the running process. `mv` gives the running process its old inode and new starts the new one.
- [ ] **After replacing a config, the running process still has the old one** until it re-reads. `systemctl reload`, a `SIGHUP`, or a restart (lesson 10 and lesson 11).
- [ ] **A log file that is being written: do not `rm` it to free space.** The process keeps the inode open and the space stays used (lesson 04). Truncate it in place instead: `: > /var/log/app/app.log` (or `truncate -s 0`), or rotate it properly with `logrotate` and a reopen signal.

## 4 · cp, mv and rsync semantics that bite

- [ ] `cp -r src dst`: if `dst` **exists**, the result is `dst/src`; if it does not, `dst` becomes a copy of `src`. Run it twice and you get `dst/src/src`. Same for `mv`. Check with `ls` after the first run.
- [ ] `cp` without `-a` or `-p` gives the copy **your** umask mode, **your** ownership and **now** as the timestamp. For anything a service reads, `cp -a` (or `install -m 640 -o root -g app`).
- [ ] `cp` follows symlinks and copies the **target**; `cp -a` copies the **link**. A tree with a symlink to `/` and a `cp -r` without `-a` is a disk-filling loop.
- [ ] `rsync -a src/ dst/` (trailing slashes) copies the contents of `src` into `dst`; `rsync -a src dst/` creates `dst/src`. The slash is the whole difference (lesson 17).
- [ ] `mv` across filesystems (a different disk, `/tmp` on tmpfs, a mounted volume) is a **copy then delete**: slow for large trees, not atomic, and it can fail halfway leaving both. Check `df` on both ends; if they differ, use `rsync -a --remove-source-files` and verify.
- [ ] `tar -xf` writes **relative to the current directory** unless `-C dir` is given, and an archive built with absolute paths (`tar -cf x.tar /etc`) is stored without the leading slash and extracts to `./etc`. List first: `tar -tf`. Never extract an untrusted archive as root; it can contain `../../etc/passwd`.

## 5 · The read-only commands that are safe to run first

`ls -la`, `stat`, `file`, `head`, `tail`, `less`, `wc`, `diff`, `cmp`, `tar -tf`, `find ... -print`, `du`, `df`, `hexdump -C`, `cat` (on files you know are text; on a binary it will spray your terminal, `reset` fixes it). None of them change anything. When in doubt, run one of these before the command that does.
