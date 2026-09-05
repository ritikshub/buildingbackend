---
name: checklist-installing-software-on-a-server
description: How to put software on a server without making it un-rebuildable — the package manager first, pinned versions, dry runs, where each kind of install lands, language runtimes and venvs kept apart from the system, what to do about curl | bash, security updates, and the audit that finds what nobody installed on purpose
phase: 01
lesson: 13
---

# Installing software on a server

The goal is not "it works." The goal is that another engineer can rebuild
this box from a list, that every file has an owner, and that a security
update next month does not break anything. Every item below serves that.

## 1 · Before installing anything

- [ ] **Is it in the distribution's repository?** `apt-cache policy name` / `dnf info name` / `apk info name`. If yes, that is the version to use: it is built for this release, signed, and will receive security updates with everything else.
- [ ] **Dry run first**: `apt-get install --dry-run name` (`dnf install --assumeno`, `apk add --simulate`). Read the list of what else it pulls in. A one-line tool that wants 300 MB of dependencies is telling you something.
- [ ] **`--no-install-recommends`** on servers and in images. Recommends are "most people want this," which on a server usually means documentation, GUI bits and a second HTTP client.
- [ ] Write the install down **as a command in the provisioning script, Dockerfile or unit**, not as a thing you did. The list of packages a box needs is part of its definition (Phase 11).

## 2 · Where it will land

| installed by | lands in | owned by | never touch by hand |
|---|---|---|---|
| `apt` / `dnf` / `apk` | `/usr/bin`, `/usr/lib`, `/usr/share`, `/etc` | the package manager (`dpkg -S`, `rpm -qf`, `apk info -W`) | yes: edits are overwritten on upgrade |
| you, from source (`make install`) | `/usr/local/bin`, `/usr/local/lib` | nobody; `dpkg -S` says so | your responsibility to upgrade and remove |
| a vendor tarball | `/opt/name/` | nobody | one directory to delete |
| `pip install` as root | `/usr/local/lib/python3.X/site-packages` | pip | do not; see section 3 |
| `pip install` in a venv | `/opt/app/.venv/lib/...` | the venv | delete the directory to uninstall everything |
| `npm -g`, `go install`, `cargo install` | `/usr/local/lib/node_modules`, `~/go/bin`, `~/.cargo/bin` | the language tool | keep off the system PATH for services |

- [ ] `/usr/local/bin` comes before `/usr/bin` on `PATH`, so a hand-installed tool shadows the packaged one silently. `which -a name` when two versions exist (lesson 03).
- [ ] Config the package installs under `/etc` is yours to edit; the package manager will ask before overwriting a changed config file (`dpkg` conffile prompts, `.rpmnew` files). Read those prompts; do not blindly keep or replace.

## 3 · Language runtimes: keep the system's and yours apart

- [ ] The distribution's Python (`/usr/bin/python3`) belongs to the distribution: `apt` itself is written in it. Never `pip install` into it as root (`pip` will refuse on modern Debian: "externally-managed-environment", and that refusal is correct).
- [ ] Each service gets **its own virtual environment**: `python3 -m venv /opt/app/.venv && /opt/app/.venv/bin/pip install -r requirements.txt`, with pinned versions in the requirements file, and `ExecStart=/opt/app/.venv/bin/python3 ...` in the unit. Delete the directory to remove everything.
- [ ] Need a Python the distribution does not ship? A packaged alternative (`deadsnakes` on Ubuntu, `python3.12` from the repo), a container image, or `uv`/`pyenv` under `/opt`; not a `make install` over `/usr`.
- [ ] Same rule for Node, Ruby, Java: one runtime per service under `/opt/app`, pinned, or a container.

## 4 · Versions: pin, hold, and know what changed

- [ ] Pin in the definition, not in your head: `apt-get install nginx=1.26.0-1` (`dnf install nginx-1.26.0`, `apk add nginx=1.26.0-r0`). `apt-cache madison name` lists what is available.
- [ ] `apt-mark hold name` freezes a package against `upgrade`; `apt-mark showhold` lists them. A hold is a note to future you: document why, and review it quarterly.
- [ ] Before an upgrade: `apt-get upgrade --dry-run` (or `apt list --upgradable`) and read the list. After: `journalctl -u dpkg` / `/var/log/apt/history.log` (`dnf history`) is the record of what changed and when, which is the first place to look when "nothing changed" and something broke.
- [ ] `apt-get upgrade` never removes packages; `apt-get dist-upgrade` / `apt full-upgrade` may. Use the first for routine updates.

## 5 · Security updates

- [ ] Security updates are applied on a schedule, automatically for the security suite: `unattended-upgrades` on Debian/Ubuntu (`/etc/apt/apt.conf.d/50unattended-upgrades`), `dnf-automatic` on Red Hat. Reboots for kernel updates are scheduled, not skipped: `needrestart` / `checkrestart` lists services running old libraries after an update.
- [ ] The base image of every container is rebuilt on a schedule for the same reason; a container's packages do not update themselves (Phase 11, lesson 04).
- [ ] Repositories are **signed** and the keys are in `/etc/apt/keyrings/` or `/usr/share/keyrings/`, referenced by `Signed-By=` in the source file. Never `apt-key add` a key into the global keyring (deprecated because it trusts that key for every repository).

## 6 · Third-party repositories and curl | bash

- [ ] A vendor repository (Docker, PostgreSQL, Node) is added as a `.sources` file with its own key and `Signed-By=`, pinned to the suite it serves. Now its packages are managed like any other.
- [ ] `curl https://example.com/install.sh | bash` runs whatever the server sends, as you, with no record. If you must: download the script, read it, check its hash against what the vendor publishes, then run it. Better: find the package or the tarball the script would have installed and put that in the definition.
- [ ] A tarball goes under `/opt/name-version` with a `/opt/name` symlink (lesson 09's layout), its checksum verified (`sha256sum -c`), and its own user if it runs as a service.
- [ ] Anything built from source is built in a container or a build host and shipped as an artifact; a compiler on a production server is a liability and a slow deploy.

## 7 · Removing

- [ ] `apt-get remove name` keeps its config under `/etc`; `apt-get purge name` removes that too. `apt-get autoremove` removes dependencies nothing needs any more; run it after removals, and read the list.
- [ ] A hand-installed tool is removed by deleting what `make install` created; `make uninstall` if it exists, else the file list you kept. This is why section 2 prefers packages.
- [ ] A venv or an `/opt` tree is one `rm -rf` of a directory you own (lesson 05's checklist first).

## 8 · The audit: what is on this box, and why

```bash
dpkg -l | grep '^ii' | wc -l                            # how many packages (rpm -qa | wc -l; apk list --installed | wc -l)
apt-mark showmanual                                     # what someone installed on purpose, vs pulled in as a dependency
apt-mark showhold                                       # what is frozen, and whether anyone remembers why
apt list --upgradable 2>/dev/null                       # what is behind
comm -23 <(find /usr/local/bin /usr/local/sbin -type f | sort) <(dpkg -S /usr/local 2>/dev/null | cut -d' ' -f2 | sort)   # hand-installed binaries
ls /opt                                                 # vendor trees
find / -xdev -name 'site-packages' -path '*/lib/*' 2>/dev/null   # where pip installed things
grep -rl "curl.*|.*bash\|wget.*|.*sh" /etc/cron* /opt/*/bin 2>/dev/null   # scripts that fetch and run
cat /etc/apt/sources.list /etc/apt/sources.list.d/* 2>/dev/null | grep -vE '^#|^$'   # every repository trusted
```

- [ ] Every line of output is either in the box's definition or gets added to it or removed. A box whose package list cannot be reproduced is a box you cannot replace, and replacing boxes is Phase 11's whole approach to operations.
