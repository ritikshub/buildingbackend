"""
Shell Scripting for Operations — the same deploy script as deploy.sh, in
Python, so the two can be read side by side.

Bash is the right tool up to about this size: it composes commands, it is
on every box, and its failure modes are the habits the lesson teaches. This
file shows what each of those habits becomes in Python (subprocess.run with
check=True instead of set -e; a list of arguments instead of quoting; try /
finally instead of trap; os.rename for the atomic switch; sys.exit for the
exit code), and where Python starts to win: real error handling, data
structures, and tests. Self-terminating; only touches DEPLOY_ROOT.

Docs: phases/01-linux-and-the-command-line/09-shell-scripting-for-operations/docs/en.md
Spec: subprocess (PEP 324); os.rename atomicity per POSIX.1-2017 rename()

Run:
    python deploy.py            # deploy the sample release into /tmp/deploy-demo
    python deploy.py --break    # a release whose health check fails, to see the rollback
"""

import hashlib
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time

DEPLOY_ROOT = os.environ.get("DEPLOY_ROOT", "/tmp/deploy-demo")       # ${VAR:-default}
SERVICE_NAME = os.environ.get("SERVICE_NAME", "app")
KEEP_RELEASES = int(os.environ.get("KEEP_RELEASES", "3"))


def log(*parts):                                                       # log to stderr, data to stdout
    print(time.strftime("%H:%M:%S"), *parts, file=sys.stderr, flush=True)


class DeployError(Exception):
    pass


def make_release(work, version, broken):
    d = os.path.join(work, f"release-{version}")
    os.makedirs(os.path.join(d, "bin"))
    script = "#!/bin/sh\necho 'health: FAILING'; exit 1\n" if broken else "#!/bin/sh\necho 'health: ok'; exit 0\n"
    with open(os.path.join(d, "bin", "healthcheck"), "w") as f:
        f.write(script)
    os.chmod(os.path.join(d, "bin", "healthcheck"), 0o755)
    with open(os.path.join(d, "VERSION"), "w") as f:
        f.write(f"version={version}\n")
    tarball = os.path.join(work, f"release-{version}.tar.gz")
    with tarfile.open(tarball, "w:gz") as t:
        t.add(d, arcname=f"release-{version}")
    with open(tarball, "rb") as f:
        digest = hashlib.sha256(f.read()).hexdigest()
    with open(tarball[:-len(".tar.gz")] + ".sha256", "w") as f:
        f.write(digest + "\n")
    return tarball


def verify(tarball):
    with open(tarball[:-len(".tar.gz")] + ".sha256") as f:
        expected = f.read().strip()
    with open(tarball, "rb") as f:
        actual = hashlib.sha256(f.read()).hexdigest()
    if expected != actual:                                             # die "checksum mismatch"
        raise DeployError(f"checksum mismatch for {tarball}")
    log(f"verified {os.path.basename(tarball)} ({actual})")


def install_release(tarball, version):
    target = os.path.join(DEPLOY_ROOT, "releases", version)
    if os.path.exists(target):
        raise DeployError(f"release {version} already installed at {target}")
    os.makedirs(os.path.join(DEPLOY_ROOT, "releases"), exist_ok=True)
    staging = tempfile.mkdtemp(prefix=".staging-", dir=os.path.join(DEPLOY_ROOT, "releases"))
    with tarfile.open(tarball) as t:
        for member in t.getmembers():
            member.name = member.name.split("/", 1)[1] if "/" in member.name else ""   # --strip-components=1
            if member.name:
                kwargs = {"filter": "data"} if hasattr(tarfile, "data_filter") else {}   # 3.12+: refuse ../ paths
                t.extract(member, staging, **kwargs)
    os.rename(staging, target)                                         # one rename makes it appear whole
    log(f"installed {version} -> {target}")
    return target


def switch_current(version):
    link = os.path.join(DEPLOY_ROOT, "current")
    tmp = link + ".tmp"
    if os.path.lexists(tmp):
        os.unlink(tmp)
    os.symlink(os.path.join("releases", version), tmp)
    os.rename(tmp, link)                                               # atomic: rename over the old symlink
    log(f"current -> releases/{version}")


def current_version():
    link = os.path.join(DEPLOY_ROOT, "current")
    return os.path.basename(os.readlink(link)) if os.path.islink(link) else ""


def restart_service():
    log(f"restart {SERVICE_NAME} (simulated)")                        # subprocess.run(["systemctl", "restart", SERVICE_NAME], check=True)


def health_check():
    check = os.environ.get("HEALTH_CMD") or os.path.join(DEPLOY_ROOT, "current", "bin", "healthcheck")
    result = subprocess.run([check], capture_output=True, text=True)   # a LIST: no shell, no quoting problems
    sys.stderr.write(result.stdout)
    return result.returncode == 0                                      # test the exit code, not the output


def prune_old(keep):
    releases_dir = os.path.join(DEPLOY_ROOT, "releases")
    cur = current_version()
    names = [n for n in os.listdir(releases_dir) if not n.startswith(".") and n != cur]
    names.sort(key=lambda n: os.stat(os.path.join(releases_dir, n)).st_mtime, reverse=True)
    for old in names[keep - 1:]:
        log(f"pruning old release {old}")
        shutil.rmtree(os.path.join(releases_dir, old))


def main(argv):
    broken = "--break" in argv
    for arg in argv:
        if arg not in ("--break",):
            print(f"usage: {sys.argv[0]} [--break]", file=sys.stderr)
            return 2
    version = "v" + time.strftime("%Y%m%d%H%M%S")
    previous = current_version()
    log(f"deploying {version} to {DEPLOY_ROOT} (previous: {previous or 'none'})")
    work = tempfile.mkdtemp()
    try:                                                               # try/finally is the trap
        tarball = make_release(work, version, broken)
        verify(tarball)
        install_release(tarball, version)
        switch_current(version)
        restart_service()
        if health_check():
            log(f"health check passed; deploy of {version} complete")
            prune_old(KEEP_RELEASES)
            return 0
        log(f"health check FAILED for {version}")
        if previous:
            switch_current(previous)
            restart_service()
            log(f"rolled back to {previous}")
        else:
            log("no previous release to roll back to")
        return 1
    except DeployError as e:
        log(f"ERROR: {e}")
        return 1
    finally:
        shutil.rmtree(work, ignore_errors=True)                        # cleanup on every exit path


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
