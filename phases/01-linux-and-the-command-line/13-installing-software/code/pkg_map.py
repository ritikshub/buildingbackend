"""
Installing Software — the package database read directly: what dpkg knows
about every file on a Debian box, rebuilt from /var/lib/dpkg.

A package manager is a database plus a downloader plus a dependency solver.
The database is plain text: /var/lib/dpkg/status has one record per
installed package (name, version, size, what it depends on), and
/var/lib/dpkg/info/<pkg>.list has every path the package owns. This script
reads both and answers the questions you would otherwise ask dpkg and apt:
which package owns this file, what does this package need, what needs it,
what are the biggest packages, and what is on the box that no package
owns. Self-terminating; on a non-Debian system it says what it would read.

Docs: phases/01-linux-and-the-command-line/13-installing-software/docs/en.md
Spec: Debian Policy Manual ch. 5 (control files and fields) and ch. 7
      (relationships: Depends, Recommends, Conflicts); dpkg(1), dpkg-query(1)

Run:
    python pkg_map.py                 # a tour
    python pkg_map.py /usr/bin/curl   # who owns this path?
"""

import os
import re
import sys
from collections import defaultdict

STATUS = "/var/lib/dpkg/status"
INFO = "/var/lib/dpkg/info"


def parse_status(path=STATUS):
    """One dict per stanza; stanzas are separated by blank lines, fields by 'Key: value'."""
    packages = {}
    with open(path, encoding="utf-8", errors="replace") as f:
        stanza, key = {}, None
        for line in f:
            if line.strip() == "":
                if stanza.get("Package"):
                    packages[stanza["Package"]] = stanza
                stanza, key = {}, None
            elif line[0] in " \t" and key:               # a continuation line (long Description)
                stanza[key] += "\n" + line.strip()
            else:
                key, _, value = line.partition(":")
                stanza[key] = value.strip()
        if stanza.get("Package"):
            packages[stanza["Package"]] = stanza
    return {n: p for n, p in packages.items() if p.get("Status", "").endswith("installed")}


def dep_names(field):
    """'libc6 (>= 2.34), libcurl4t64 (= 8.14.1) | other' -> ['libc6', 'libcurl4t64', 'other']"""
    names = []
    for clause in field.split(","):
        for alt in clause.split("|"):
            name = re.sub(r"[\s(].*", "", alt.strip())
            name = name.split(":")[0]                          # drop :arch qualifiers
            if name:
                names.append(name)
    return names


def owned_files(pkg):
    for candidate in (f"{INFO}/{pkg}.list", f"{INFO}/{pkg}:arm64.list", f"{INFO}/{pkg}:amd64.list"):
        if os.path.exists(candidate):
            with open(candidate) as f:
                return [l.strip() for l in f if l.strip()]
    return []


if __name__ == "__main__":
    if not os.path.exists(STATUS):
        print("no /var/lib/dpkg/status here: this is not a Debian-family system.")
        print("  Red Hat family keeps the same facts in an rpm database (rpm -qa, rpm -qf, rpm -ql);")
        print("  Alpine in /lib/apk/db/installed (apk info -W, apk info -L); macOS Homebrew in $(brew --prefix)/Cellar.")
        print("  Run this inside `make shell`.")
        sys.exit(0)

    pkgs = parse_status()
    print(f"/var/lib/dpkg/status: {len(pkgs)} installed packages, {sum(1 for _ in open(STATUS))} lines of plain text\n")

    if len(sys.argv) > 1:                                      # dpkg -S <path>
        target = sys.argv[1]
        for name in pkgs:
            if target in owned_files(name):
                print(f"{name}: {target}   (from {INFO}/{name}.list)")
                break
        else:
            print(f"no package owns {target}: it was put there by hand, by pip, or by a build (dpkg -S would say the same)")
        sys.exit(0)

    print("=== 1 · who owns what: dpkg -S, from the .list files")
    for path in ("/usr/bin/curl", "/usr/bin/ls", "/etc/passwd", "/usr/local/bin/python3", "/usr/bin/python3"):
        owner = next((n for n in pkgs if path in owned_files(n)), None)
        print(f"   {path:28} -> {owner or 'nobody (not from a package)'}")

    print("\n=== 2 · what a package needs: Depends, from the status record")
    for name in ("curl", "jq", "strace"):
        if name in pkgs:
            print(f"   {name:8} {pkgs[name]['Version']:22} depends on: {', '.join(dep_names(pkgs[name].get('Depends', ''))) or 'nothing'}")

    print("\n=== 3 · what needs a package: the reverse edges (apt-cache rdepends)")
    rdeps = defaultdict(list)
    for name, p in pkgs.items():
        for dep in dep_names(p.get("Depends", "") + "," + p.get("Pre-Depends", "")):
            rdeps[dep].append(name)
    for name in ("libc6", "libcurl4t64", "python3", "zlib1g"):
        print(f"   {name:12} is needed by {len(rdeps.get(name, [])):3} installed packages" + (f": {', '.join(sorted(rdeps[name])[:6])} ..." if rdeps.get(name) else ""))
    print("   remove libc6 and every one of those breaks: that is why apt refuses, and why 'Essential: yes' exists")

    print("\n=== 4 · the biggest packages: Installed-Size is in KiB")
    big = sorted(pkgs.values(), key=lambda p: -int(p.get("Installed-Size", "0")))[:6]
    for p in big:
        print(f"   {int(p['Installed-Size']) / 1024:8.1f} MiB  {p['Package']:24} {p.get('Section', '')}")

    print("\n=== 5 · what is on the box that no package owns (the /usr/local and pip half)")
    owned = set()
    for name in pkgs:
        owned.update(owned_files(name))
    for d in ("/usr/local/bin", "/usr/local/lib/python3.12/site-packages", "/usr/bin", "/etc"):
        if os.path.isdir(d):
            entries = [os.path.join(d, e) for e in os.listdir(d)]
            unowned = [e for e in entries if e not in owned]
            print(f"   {d:44} {len(entries):5} entries, {len(unowned):5} owned by no package" + (f"   e.g. {', '.join(os.path.basename(e) for e in unowned[:3])}" if unowned else ""))
    print("   /usr/bin belongs to apt; /usr/local and site-packages belong to you and pip. Neither touches the other's files")

    print("\n=== 6 · essential and priority: what apt will not let you remove")
    essential = sorted(n for n, p in pkgs.items() if p.get("Essential") == "yes")
    print(f"   {len(essential)} packages marked Essential: yes: {', '.join(essential[:10])} ...")
    print("   apt asks you to type 'Yes, do as I say!' before removing one; the box would not boot or run a shell without them")
