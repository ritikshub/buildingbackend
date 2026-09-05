# Installing Software: Packages, Repositories & Where Files Land

> `apt install curl` is a download, a signature check, a dependency solve, and the unpacking of a tar archive into `/usr`, all recorded in a plain-text database you can read with `cat`. This lesson opens that database on the sandbox: **169** packages, **3,903** lines of text, `libc6` needed by **147** of them, **22** marked essential, and **32** binaries in `/usr/local/bin` that no package owns because `pip` put them there. Then the same job on Alpine and Fedora, which differ from Debian by exactly one lesson's worth: the package manager, and nothing above the kernel that you type.

## The Problem

Every box you will ever operate has software on it that you did not put there, and software you did. In six months nobody will remember which is which, whether the `python3` that runs the service is the distribution's or one somebody built, why `nginx` is held at an old version, or what that script in `/opt` was downloaded from. The box becomes un-rebuildable, and Phase 11's whole approach to operations, replacing boxes rather than repairing them, depends on being able to rebuild one from a list.

The package manager is what makes the list possible. It knows every file it installed, what depends on what, which version came from where, and what changed when. Learn to read it and "what is on this server" has an answer; learn its boundaries and the things it does not manage (`/usr/local`, `pip`, `/opt`, `curl | bash`) stop being surprises. And because Debian, Red Hat and Alpine solve the same problem with different tools, one hour on the model covers all three.

## The Concept

### A package is a tar archive with a manifest

A `.deb` is an `ar` archive containing three members: a version marker, `control.tar` with the metadata and maintainer scripts, and `data.tar` with the files, which is lesson 05's format with a list of paths that begin at `/`. The metadata is a handful of fields: `Package`, `Version`, `Depends`, `Installed-Size`, `Description`. In the sandbox:

```console
$ apt-get download jq;  ls -la jq_*.deb | awk '{print $5, $9}'
78328 jq_1.7.1-6+deb13u3_arm64.deb
$ dpkg-deb -c jq_*.deb | head -4
drwxr-xr-x root/root         0 2026-08-04 12:56 ./
drwxr-xr-x root/root         0 2026-08-04 12:56 ./usr/
drwxr-xr-x root/root         0 2026-08-04 12:56 ./usr/bin/
-rwxr-xr-x root/root     67592 2026-08-04 12:56 ./usr/bin/jq
$ dpkg-deb -f jq_*.deb Package Version Depends
Package: jq
Version: 1.7.1-6+deb13u3
Depends: libc6 (>= 2.38), libjq1 (= 1.7.1-6+deb13u3)
```

Installing it is unpacking that tar over `/` (so `./usr/bin/jq` lands at `/usr/bin/jq`), running the maintainer scripts, and writing two records: the package's stanza into `/var/lib/dpkg/status`, and its file list into `/var/lib/dpkg/info/jq.list`. An `.rpm` and an `.apk` are the same idea with a different container format. That is the whole trick, and everything else the package manager does is bookkeeping around it.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 470" width="100%" style="max-width:880px" font-family="'JetBrains Mono', ui-monospace, monospace" role="img" aria-label="What apt install does, as seven steps. One, sources: /etc/apt/sources.list.d names repositories, each a URL, a suite such as trixie, and components, with a signing key. Two, update: apt-get update downloads each repository's package index, about ten megabytes, into /var/lib/apt/lists, and verifies its signature against the keyring. Three, resolve: apt reads the requested package's Depends from the index and computes the closure, refusing conflicts and warning about Essential packages. Four, download: the .deb files go to /var/cache/apt/archives. Five, verify: each file's hash is checked against the signed index. Six, unpack and configure: dpkg extracts data.tar over the root filesystem, then runs the maintainer scripts, preinst, postinst. Seven, record: the stanza is appended to /var/lib/dpkg/status and the file list to /var/lib/dpkg/info/name.list, and the action is logged to /var/log/apt/history.log. A note says dpkg does steps six and seven only, apt does the rest, and dnf and rpm, apk and its database, are the same split.">
  <defs>
    <marker id="p1l13a-ar" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker>
  </defs>
  <text x="450" y="26" text-anchor="middle" font-size="14.5" font-weight="700" fill="currentColor">apt install, step by step: an index, a solver, a download, a signature, a tar, and a record</text>
  <g stroke-linejoin="round" stroke-width="1.6">
    <rect x="30"  y="50" width="200" height="86" rx="9" fill="#7f7f7f" fill-opacity="0.12" stroke="#7f7f7f"/>
    <rect x="250" y="50" width="200" height="86" rx="9" fill="#7f7f7f" fill-opacity="0.12" stroke="#7f7f7f"/>
    <rect x="470" y="50" width="200" height="86" rx="9" fill="#e0930f" fill-opacity="0.12" stroke="#e0930f"/>
    <rect x="690" y="50" width="180" height="86" rx="9" fill="#7f7f7f" fill-opacity="0.12" stroke="#7f7f7f"/>
    <rect x="30"  y="180" width="200" height="86" rx="9" fill="#0fa07f" fill-opacity="0.12" stroke="#0fa07f"/>
    <rect x="250" y="180" width="200" height="86" rx="9" fill="#c94a12" fill-opacity="0.12" stroke="#c94a12" stroke-width="2"/>
    <rect x="470" y="180" width="200" height="86" rx="9" fill="#7c5cff" fill-opacity="0.12" stroke="#7c5cff" stroke-width="2"/>
  </g>
  <g text-anchor="middle" font-size="8.5" fill="currentColor">
    <text x="130" y="70" font-size="10" font-weight="700">1 · SOURCES</text>
    <text x="130" y="88">/etc/apt/sources.list.d/*.sources</text>
    <text x="130" y="102">URIs, Suites (trixie, -security),</text>
    <text x="130" y="116">Components (main), Signed-By</text>
    <text x="130" y="130" opacity="0.75">which repositories are trusted</text>
    <text x="350" y="70" font-size="10" font-weight="700">2 · UPDATE</text>
    <text x="350" y="88">apt-get update fetches each</text>
    <text x="350" y="102">repository's package index</text>
    <text x="350" y="116">→ /var/lib/apt/lists (10 MB here)</text>
    <text x="350" y="130" opacity="0.75">and verifies its signature</text>
    <text x="570" y="70" font-size="10" font-weight="700" fill="#e0930f">3 · RESOLVE</text>
    <text x="570" y="88">read Depends from the index,</text>
    <text x="570" y="102">compute the closure, refuse</text>
    <text x="570" y="116">Conflicts, warn on Essential</text>
    <text x="570" y="130" opacity="0.75">--dry-run shows the answer</text>
    <text x="780" y="70" font-size="10" font-weight="700">4 · DOWNLOAD</text>
    <text x="780" y="88">the .deb files, into</text>
    <text x="780" y="102">/var/cache/apt/archives</text>
    <text x="780" y="116">78 KB for jq</text>
    <text x="780" y="130" opacity="0.75">apt-get download does only this</text>
    <text x="130" y="200" font-size="10" font-weight="700" fill="#0fa07f">5 · VERIFY</text>
    <text x="130" y="218">each file's hash against the</text>
    <text x="130" y="232">signed index; the key lives in</text>
    <text x="130" y="246">/usr/share/keyrings or /etc/apt/keyrings</text>
    <text x="130" y="260" opacity="0.75">a bad hash stops here</text>
    <text x="350" y="200" font-size="10" font-weight="700" fill="#c94a12">6 · UNPACK + CONFIGURE (dpkg)</text>
    <text x="350" y="218">extract data.tar over /</text>
    <text x="350" y="232">./usr/bin/jq → /usr/bin/jq</text>
    <text x="350" y="246">run preinst, postinst scripts</text>
    <text x="350" y="260" opacity="0.75">conffiles under /etc: ask before replacing</text>
    <text x="570" y="200" font-size="10" font-weight="700" fill="#7c5cff">7 · RECORD</text>
    <text x="570" y="218">stanza → /var/lib/dpkg/status</text>
    <text x="570" y="232">file list → /var/lib/dpkg/info/jq.list</text>
    <text x="570" y="246">action → /var/log/apt/history.log</text>
    <text x="570" y="260" opacity="0.75">what dpkg -S, -L, -s read later</text>
  </g>
  <g fill="none" stroke="currentColor" stroke-width="1.5">
    <path d="M232 93 L246 93" marker-end="url(#p1l13a-ar)"/>
    <path d="M452 93 L466 93" marker-end="url(#p1l13a-ar)"/>
    <path d="M672 93 L686 93" marker-end="url(#p1l13a-ar)"/>
    <path d="M780 138 L780 160 L130 160 L130 176" marker-end="url(#p1l13a-ar)"/>
    <path d="M232 223 L246 223" marker-end="url(#p1l13a-ar)"/>
    <path d="M452 223 L466 223" marker-end="url(#p1l13a-ar)"/>
  </g>
  <rect x="690" y="180" width="180" height="86" rx="9" fill="#7f7f7f" fill-opacity="0.08" stroke="#7f7f7f" stroke-width="1.4" stroke-linejoin="round"/>
  <g text-anchor="middle" font-size="8.5" fill="currentColor">
    <text x="780" y="200" font-size="10" font-weight="700">THE SPLIT</text>
    <text x="780" y="218">apt: steps 1 to 5</text>
    <text x="780" y="232">dpkg: steps 6 and 7</text>
    <text x="780" y="246">dnf : rpm and apk : its db</text>
    <text x="780" y="260" opacity="0.75">are the same two layers</text>
  </g>
  <rect x="30" y="292" width="840" height="120" rx="10" fill="#0fa07f" fill-opacity="0.07" stroke="#0fa07f" stroke-width="1.5" stroke-linejoin="round"/>
  <text x="450" y="314" text-anchor="middle" font-size="10" font-weight="700" fill="#0fa07f">WHAT THE RECORD MAKES POSSIBLE (all read from /var/lib/dpkg, no network)</text>
  <g font-size="8.5" fill="currentColor">
    <text x="46" y="338">dpkg -S /usr/bin/curl  → curl            which package owns this file (the .list files, searched)</text>
    <text x="46" y="354">dpkg -L curl           → 23 paths        every file a package put on the box</text>
    <text x="46" y="370">dpkg -s curl           → the stanza      version, Depends, Installed-Size, Status</text>
    <text x="46" y="386">apt-cache rdepends libc6 → 147 packages  what would break if this were removed</text>
    <text x="46" y="402" opacity="0.8">removing a package is the .list in reverse; purge also removes its conffiles under /etc</text>
  </g>
  <text x="450" y="446" text-anchor="middle" font-size="10.5" fill="currentColor" opacity="0.9">Nothing in this pipeline is magic: an index, a solver, a tar, and two text files. The value is the record.</text>
</svg>
```

### The repository and the index

Where do the packages come from? A **repository** is a web server with a signed index and the `.deb` files; `/etc/apt/sources.list.d/debian.sources` names the ones this box trusts:

```text
Types: deb
URIs: http://deb.debian.org/debian
Suites: trixie trixie-updates
Components: main
```

`apt-get update` downloads each repository's index (about 10 MB here, into `/var/lib/apt/lists`) and checks its signature against a key in `/usr/share/keyrings` or `/etc/apt/keyrings`. Everything `apt` knows about *available* packages comes from those indexes, which is why `apt install` fails with "unable to locate" on a fresh box until `update` has run, and why a Dockerfile always writes `apt-get update && apt-get install` on one line (Phase 11, lesson 03). `apt-cache policy name` shows what the indexes offer and which version would be chosen:

```console
$ apt-cache policy curl
curl:
  Installed: 8.14.1-2+deb13u4
  Candidate: 8.14.1-2+deb13u4
  Version table:
 *** 8.14.1-2+deb13u4 500
        500 http://deb.debian.org/debian trixie/main arm64 Packages
        100 /var/lib/dpkg/status
```

The suite `trixie` is Debian 13; `trixie-security` is where security fixes arrive; the `500` and `100` are priorities that decide which source wins when several offer the same package. A third-party repository (Docker's, PostgreSQL's) is one more `.sources` file with its own key, after which its packages are managed like every other.

### The database

The record `apt` writes is two plain-text structures, and reading them directly is the point of this lesson's script. `/var/lib/dpkg/status` is one stanza per package, blank-line separated:

```console
$ grep -A3 '^Package: jq$' /var/lib/dpkg/status
Package: jq
Status: install ok installed
Priority: optional
Section: utils
$ grep -c '^Package:' /var/lib/dpkg/status;  wc -l < /var/lib/dpkg/status
169
3903
```

And `/var/lib/dpkg/info/<pkg>.list` is the file list. From those two, every question about "what is on this box and why" has an answer without touching the network: which package owns a path (`dpkg -S`), which paths a package owns (`dpkg -L`), what a package needs (`Depends:`), and, by inverting the `Depends` fields across all stanzas, what needs it:

```console
   libc6        is needed by 147 installed packages: apt, base-passwd, bash, bind9-dnsutils ...
   libcurl4t64  is needed by   1 installed packages: curl
   zlib1g       is needed by  16 installed packages: bind9-libs, curl, dpkg, libapt-pkg7.0 ...
```

That reverse map is why `apt` refuses to remove `libc6`, and why 22 packages carry `Essential: yes` (`bash`, `coreutils`, `dpkg` itself): removing one requires typing `Yes, do as I say!`, because the box would not run a shell afterwards.

### Dependencies, and the words on the package

`Depends` must be installed for the package to work. `Recommends` is "most people want this too" and is installed by default, which on a server means documentation, a second HTTP client, and the reason `--no-install-recommends` is in every Dockerfile. `Suggests` is never installed automatically. `Conflicts` prevents two packages from coexisting. `Provides` lets several packages satisfy one name (any `mail-transport-agent`). The solver turns your one request into a set that satisfies all of it, and `--dry-run` prints that set before anything happens:

```console
$ apt-get install --dry-run -y htop | grep -E '^Inst|newly'
Inst htop (3.4.1-5 Debian:13.6/stable [arm64])
0 upgraded, 1 newly installed, 0 to remove and 0 not upgraded.
```

Removal has two strengths: `remove` deletes the files but keeps the configuration under `/etc` (so reinstalling restores your settings), `purge` deletes both. `autoremove` removes packages that were pulled in as dependencies and are needed by nothing any more. `dpkg -l` (or `apt list --installed`) is the inventory; `apt-mark showmanual` separates what someone asked for from what came along.

### Versions: upgrade, pin, hold, and the history

`apt-get upgrade` installs newer versions of what is installed and never removes anything; `full-upgrade` may remove packages to resolve a change, which is what a release upgrade needs and a routine one does not. Both take `--dry-run`. To stay on a version: install it by name (`apt-get install curl=8.14.1-2+deb13u4`; `apt-cache madison curl` lists what is available) and `apt-mark hold curl` so `upgrade` leaves it alone:

```console
$ apt-mark hold curl;  apt-mark showhold;  apt-mark unhold curl
curl set on hold.
curl
Canceled hold on curl.
```

Every action is logged to `/var/log/apt/history.log` with a timestamp, which is the first file to open when "nothing changed" and something broke. Security updates from the `-security` suite are the one category to apply automatically: `unattended-upgrades` on Debian and Ubuntu, `dnf-automatic` on Red Hat, and `needrestart` afterwards to list services still running the old library in memory (a library upgrade does not touch a running process; lesson 04's inode rules).

### Where things land, and who owns them

The package manager owns `/usr/bin`, `/usr/lib`, `/usr/share` and the package's files under `/etc`. It does not own `/usr/local`, `/opt`, or anything a language tool installs, and it never will:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 430" width="100%" style="max-width:880px" font-family="'JetBrains Mono', ui-monospace, monospace" role="img" aria-label="Four territories on the filesystem and who owns each. First, the package manager's: /usr/bin, /usr/lib, /usr/share, and package config under /etc; 394 binaries in /usr/bin on the sandbox, 371 owned by packages; upgraded and removed by apt; never edit by hand. Second, yours by hand: /usr/local/bin and /usr/local/lib, which come first on PATH; on the sandbox 32 of 32 entries are owned by no package, all put there by pip and the image build; you upgrade and remove them. Third, vendors: /opt/name, one directory per product, with its own libraries; one directory to delete. Fourth, language tools: dist-packages under /usr/lib/python3 is apt's, site-packages under /usr/local or a venv is pip's; a venv under /opt/app/.venv is the only one a service should use. Notes: PATH order means /usr/local/bin shadows /usr/bin silently; pip refuses to write into the distribution's Python; dpkg -S answers nobody for everything outside the first territory.">
  <defs>
    <marker id="p1l13b-ar" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker>
  </defs>
  <text x="450" y="26" text-anchor="middle" font-size="14.5" font-weight="700" fill="currentColor">Four territories: the package manager's, yours, the vendor's, and the language tool's</text>
  <g stroke-linejoin="round" stroke-width="1.7">
    <rect x="30"  y="50" width="200" height="220" rx="10" fill="#7c5cff" fill-opacity="0.10" stroke="#7c5cff"/>
    <rect x="250" y="50" width="200" height="220" rx="10" fill="#e0930f" fill-opacity="0.10" stroke="#e0930f"/>
    <rect x="470" y="50" width="200" height="220" rx="10" fill="#7f7f7f" fill-opacity="0.12" stroke="#7f7f7f"/>
    <rect x="690" y="50" width="180" height="220" rx="10" fill="#0fa07f" fill-opacity="0.10" stroke="#0fa07f"/>
  </g>
  <g text-anchor="middle" font-size="8.5" fill="currentColor">
    <text x="130" y="72" font-size="10" font-weight="700" fill="#7c5cff">THE PACKAGE MANAGER</text>
    <text x="130" y="92">/usr/bin  /usr/lib  /usr/share</text>
    <text x="130" y="106">package config under /etc</text>
    <text x="130" y="128">394 binaries in /usr/bin here,</text>
    <text x="130" y="142">371 owned by a package</text>
    <text x="130" y="164">upgraded and removed by apt</text>
    <text x="130" y="178">every file in a .list</text>
    <text x="130" y="200" font-weight="700">never edit by hand:</text>
    <text x="130" y="214">the next upgrade overwrites it</text>
    <text x="130" y="236" opacity="0.75">conffiles: apt asks first</text>
    <text x="350" y="72" font-size="10" font-weight="700" fill="#e0930f">YOURS, BY HAND</text>
    <text x="350" y="92">/usr/local/bin  /usr/local/lib</text>
    <text x="350" y="106">make install lands here</text>
    <text x="350" y="128">32 of 32 entries here owned</text>
    <text x="350" y="142">by nobody: pip and the image</text>
    <text x="350" y="164">FIRST on PATH: shadows</text>
    <text x="350" y="178">/usr/bin silently</text>
    <text x="350" y="200" font-weight="700">you upgrade, you remove,</text>
    <text x="350" y="214">you remember what it was</text>
    <text x="350" y="236" opacity="0.75">dpkg -S says: nobody</text>
    <text x="570" y="72" font-size="10" font-weight="700">THE VENDOR</text>
    <text x="570" y="92">/opt/name/</text>
    <text x="570" y="106">bin, lib, etc inside one tree</text>
    <text x="570" y="128">a tarball with its own</text>
    <text x="570" y="142">libraries and runtime</text>
    <text x="570" y="164">one directory to delete</text>
    <text x="570" y="178">one symlink to switch versions</text>
    <text x="570" y="200" font-weight="700">verify the checksum,</text>
    <text x="570" y="214">give it its own user</text>
    <text x="570" y="236" opacity="0.75">lesson 09's releases/ layout</text>
    <text x="780" y="72" font-size="10" font-weight="700" fill="#0fa07f">THE LANGUAGE TOOL</text>
    <text x="780" y="92">apt's Python libs:</text>
    <text x="780" y="106">/usr/lib/python3/dist-packages</text>
    <text x="780" y="128">pip's: .../site-packages</text>
    <text x="780" y="142">(128 entries here, unowned)</text>
    <text x="780" y="164">a service's: /opt/app/.venv</text>
    <text x="780" y="178">pinned, deletable, its own</text>
    <text x="780" y="200" font-weight="700">pip refuses the system</text>
    <text x="780" y="214">Python: that refusal is right</text>
    <text x="780" y="236" opacity="0.75">npm -g, cargo, go: the same</text>
  </g>
  <rect x="30" y="292" width="840" height="86" rx="10" fill="#d64545" fill-opacity="0.07" stroke="#d64545" stroke-width="1.5" stroke-linejoin="round"/>
  <text x="450" y="314" text-anchor="middle" font-size="10" font-weight="700" fill="#d64545">THE TWO WAYS THIS GOES WRONG</text>
  <g font-size="8.5" fill="currentColor">
    <text x="46" y="338">a `make install` or `pip install` as root into /usr: the next apt upgrade overwrites half of it, and dpkg -S cannot tell you which half</text>
    <text x="46" y="356">a hand-built /usr/local/bin/python3 in front of /usr/bin/python3 on PATH: "python3" means two different things depending on who asks and from where</text>
    <text x="46" y="372" opacity="0.8">both are solved by the same rule: the package manager's territory is read-only to you; yours is a venv, /usr/local, or /opt, and it is written down</text>
  </g>
  <text x="450" y="412" text-anchor="middle" font-size="10.5" fill="currentColor" opacity="0.9">Every file on the box should have an owner you can name: apt, pip in this venv, this vendor tree, or this line of the provisioning script.</text>
</svg>
```

The sandbox is a live example of the second territory. Its `python3` is `/usr/local/bin/python3`, built into the image by the official Python Dockerfile rather than installed by `apt`, so `dpkg -S` says nobody owns it, and the 128 entries in its `site-packages` are `pip`'s. Debian's own `/usr/bin/python3` is not even installed. That is a deliberate design: the image's Python and the distribution's never share a directory, so neither can break the other. On a server the same separation is a **virtual environment** per service, `/opt/app/.venv`, with `ExecStart=/opt/app/.venv/bin/python3` in the unit (lesson 11), and modern `pip` enforces it by refusing to install into the distribution's Python at all (`externally-managed-environment`).

### The same lesson on Alpine and Fedora

Lesson 01 promised that only the package manager changes between families. Here is the proof, on three containers:

| task | Debian, Ubuntu | Fedora, RHEL, Rocky, Amazon Linux | Alpine |
|---|---|---|---|
| refresh the index | `apt-get update` | `dnf makecache` (automatic) | `apk update` |
| install | `apt-get install curl` | `dnf install curl` | `apk add curl` |
| remove | `apt-get remove` / `purge` | `dnf remove` | `apk del` |
| upgrade everything | `apt-get upgrade` | `dnf upgrade` | `apk upgrade` |
| search | `apt-cache search x` | `dnf search x` | `apk search x` |
| which package owns a file | `dpkg -S /usr/bin/curl` | `rpm -qf /usr/bin/curl` | `apk info -W /usr/bin/curl` |
| list a package's files | `dpkg -L curl` | `rpm -ql curl` | `apk info -L curl` |
| package details | `dpkg -s curl`, `apt show curl` | `rpm -qi curl`, `dnf info curl` | `apk info -a curl` |
| inventory | `dpkg -l` | `rpm -qa` | `apk list --installed` |
| pin / hold | `apt-mark hold` | `dnf versionlock` | `apk add curl=8.14.1-r2` |
| the database | `/var/lib/dpkg/` | `/var/lib/rpm/` (a real database) | `/lib/apk/db/installed` (text) |
| the archive format | `.deb` (ar + tar) | `.rpm` (cpio + header) | `.apk` (tar.gz) |
| libc | glibc | glibc | musl |

The Alpine column carries the one difference that matters beyond commands. It replaces glibc with **musl** and the GNU coreutils with **BusyBox** (every command a symlink to one binary), which is why a fresh Alpine root is 10 MB against Debian's hundreds, why it is the base image of half the containers in existence, and why a pre-built binary or a Python wheel compiled against glibc will not run on it:

```console
$ docker run --rm alpine:3.20 sh -c 'ls -la /bin/ls; du -sh /; apk add --no-cache curl; ldd /usr/bin/curl | head -2'
lrwxrwxrwx    1 root     root            12 Apr 15 16:14 /bin/ls -> /bin/busybox
10.0M   /
OK: 15 MiB in 24 packages
        /lib/ld-musl-aarch64.so.1 (0xffff891d0000)
        libcurl.so.4 => /usr/lib/libcurl.so.4 (0xffff890be000)
$ docker run --rm fedora:41 bash -c 'dnf -y -q install jq; rpm -qf /usr/bin/jq; rpm -ql jq | head -2; rpm -qa | wc -l'
jq-1.7.1-8.fc41.aarch64
/usr/bin/jq
/usr/lib/.build-id
127
```

Twenty-four packages on Alpine, 127 on Fedora, 169 on the Debian sandbox: the same `curl` and `jq` under three managers, and the commands in this phase unchanged on all of them.

### Three things the package manager cannot protect you from

**`curl https://example.com/install.sh | bash`** runs whatever the server sends, as you, with no record, no signature, and no file list. If a vendor offers only that, download the script, read it, compare its hash with what they publish, and put the *result* (a package, a tarball under `/opt`) in the provisioning script. **Building from source** on a production box leaves files nobody can enumerate and a compiler where an attacker would like one; build elsewhere and ship an artifact. And **an image or a VM that nobody rebuilds** does not get security updates by itself: `apt list --upgradable` on a six-month-old container is a long list, which is why base images are rebuilt on a schedule (Phase 11, lesson 04).

## Try It

The script for this lesson is [`code/pkg_map.py`](../code/pkg_map.py). It parses `/var/lib/dpkg/status` and the `.list` files and answers the questions `dpkg` and `apt-cache` answer, so you can see there is nothing behind them but text. On a Mac it explains where the equivalent databases are and stops; run it in the sandbox:

```bash
make shell
python3 phases/01-linux-and-the-command-line/13-installing-software/code/pkg_map.py
python3 phases/01-linux-and-the-command-line/13-installing-software/code/pkg_map.py /usr/local/bin/python3
```

The parser is a stanza reader, blank-line separated, with continuation lines for long descriptions:

```python
for line in f:
    if line.strip() == "":
        if stanza.get("Package"):
            packages[stanza["Package"]] = stanza          # one record per package
        stanza, key = {}, None
    elif line[0] in " \t" and key:                        # a continuation line
        stanza[key] += "\n" + line.strip()
    else:
        key, _, value = line.partition(":")
        stanza[key] = value.strip()
```

And the reverse-dependency map is one loop over every `Depends` field:

```python
for name, p in pkgs.items():
    for dep in dep_names(p.get("Depends", "") + "," + p.get("Pre-Depends", "")):
        rdeps[dep].append(name)                           # what apt-cache rdepends computes
```

Read the output against the concept section: ownership of five paths (two of which nobody owns), three packages' dependencies, the reverse counts, the biggest packages (`shellcheck` at 39 MiB, which lesson 04 found the hard way), the unowned half of the box, and the 22 essential packages. Then ask it about a path of your own.

## Use It

The real tools, inside `make shell`, in the order you would use them on a box you are learning. Where things come from, and the refresh:

```console
$ cat /etc/apt/sources.list.d/debian.sources | grep -E '^(URIs|Suites|Components)'
URIs: http://deb.debian.org/debian
Suites: trixie trixie-updates
Components: main
$ apt-get update | tail -2;  du -sh /var/lib/apt/lists
Fetched 10.1 MB in 2s (4802 kB/s)
Reading package lists...
21M     /var/lib/apt/lists
```

Who owns what, what a package contains, and what it needs:

```console
$ dpkg -l | grep -c '^ii';  dpkg -S /usr/bin/curl;  dpkg -S /usr/local/bin/python3
169
curl: /usr/bin/curl
dpkg-query: no path found matching pattern /usr/local/bin/python3
$ dpkg -L curl | wc -l;  dpkg -s curl | grep -E '^(Version|Depends|Installed-Size)'
23
Installed-Size: 503
Version: 8.14.1-2+deb13u4
Depends: libc6 (>= 2.34), libcurl4t64 (= 8.14.1-2+deb13u4), zlib1g (>= 1:1.1.4)
$ apt-cache depends --no-recommends curl | head -4
curl
  Depends: libc6
  Depends: libcurl4t64
  Depends: zlib1g
```

Dry runs for install, remove, purge and upgrade, so the answer is known before anything changes:

```console
$ apt-get install --dry-run -y htop | grep '^Inst'
Inst htop (3.4.1-5 Debian:13.6/stable [arm64])
$ apt-get remove --dry-run -y jq | grep '^Remv';  apt-get purge --dry-run -y jq | grep '^Purg'
Remv jq [1.7.1-6+deb13u3]
Purg jq [1.7.1-6+deb13u3]
$ apt-get upgrade --dry-run | grep '^[0-9]* upgraded'
0 upgraded, 0 newly installed, 0 to remove and 0 not upgraded.
```

The two Pythons, and which files belong to whom:

```console
$ which python3 pip3;  python3 -c 'import sys; print(sys.prefix)'
/usr/local/bin/python3
/usr/local/bin/pip3
/usr/local
$ pip3 show requests | grep -E '^(Version|Location)'
Version: 2.34.2
Location: /usr/local/lib/python3.12/site-packages
$ ls /usr/local/bin | head -3
2to3
2to3-3.12
cffi-gen-src
```

Nothing under `/usr/local` is in `dpkg`'s database, by design. On a Debian server with the distribution's Python, `pip3 install` as root would answer `externally-managed-environment` and point you at a venv, which is the right answer.

## Ship It

The artifact for this lesson is a checklist: [`outputs/checklist-installing-software-on-a-server.md`](../outputs/checklist-installing-software-on-a-server.md). It is the discipline that keeps a box rebuildable: the repository first, a dry run, `--no-install-recommends`, the install written into the provisioning script; the table of where each kind of install lands and who owns it; runtimes kept apart with a venv per service; pinning, holds and the history log; automatic security updates and `needrestart`; what to do with third-party repositories, `curl | bash` and tarballs; removing cleanly; and the eight-command audit that lists what is on a box and flags what nobody put there on purpose.

## Think about it

1. `dpkg -S /usr/local/bin/python3` says no package owns it, yet `python3` runs. Name the two other places it could have come from, the command that tells you which, and the risk the next `apt upgrade` poses to each.
2. A colleague fixes a bug by editing `/usr/lib/python3/dist-packages/requests/api.py` on the server. What happens on the next security update of `python3-requests`, and where should the fix have gone?
3. A Dockerfile has `RUN apt-get update` on one line and `RUN apt-get install -y nginx` on the next. Explain, with the index and the layer cache, why this installs a stale `nginx` a month later.
4. A Python wheel that works on Debian fails on Alpine with `Error loading shared library ld-linux-x86-64.so.2`. Which layer of lesson 01's stack differs, and what are the two ways out?

## Key takeaways

- A package is a **tar archive plus a manifest** (`Package`, `Version`, `Depends`, file list). Installing is unpacking it over `/` and writing a **record**: the stanza in `/var/lib/dpkg/status`, the paths in `/var/lib/dpkg/info/*.list`. `dpkg -S`, `-L`, `-s` read that record; `rpm` and `apk` keep the same one differently.
- A **repository** is a signed index plus the archives; `apt-get update` fetches the index, `apt install` resolves `Depends` against it, verifies, unpacks, records. `apt-cache policy` shows the candidates; `--dry-run` shows the plan.
- `Depends` is required, `Recommends` is installed by default (use `--no-install-recommends` on servers), `Essential` cannot be removed, `autoremove` clears orphans, `remove` keeps config, `purge` does not.
- **Pin** with `name=version`, **hold** with `apt-mark hold`, read `/var/log/apt/history.log`, apply security updates automatically, and `needrestart` afterwards.
- **Four territories**: `/usr` is the package manager's (never edit); `/usr/local` and `/opt` are yours (write it down); language tools get a **venv per service**. `PATH` puts `/usr/local/bin` first, so know which `python3` you mean.
- Debian, Red Hat and Alpine differ in the manager (`apt`/`dpkg`, `dnf`/`rpm`, `apk`) and Alpine in libc (`musl`); every other command in this phase is identical.
- `curl | bash`, source builds on production, and never-rebuilt images all leave files with no owner and no updates. Prefer the package, the tarball under `/opt`, or a rebuilt image.

Next: [Networking from the Shell: ip, ss, ping, dig, nc & tcpdump](../14-networking-from-the-shell/). The software is on the box. Now the questions you ask when it cannot reach anything, or nothing can reach it: which address, which route, which port, who is listening, and what is actually on the wire.
