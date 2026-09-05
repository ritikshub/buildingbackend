#!/usr/bin/env bash
# Shell Scripting for Operations — a deploy script that is safe to run on a server.
#
# The same job as deploy.py, in bash: fetch a release, verify it, install it
# atomically, switch the "current" symlink, restart the service, roll back if
# the health check fails. Every habit the lesson teaches is in here and marked:
# the strict-mode line, quoting, ${VAR:?} guards, a trap for cleanup, functions,
# exit codes, logging to stderr, and no work outside a temp dir until the end.
#
# Docs: phases/01-linux-and-the-command-line/09-shell-scripting-for-operations/docs/en.md
# Spec: POSIX.1-2017 Shell Command Language (XCU 2); bash(1) "SHELL BUILTIN COMMANDS"
#       (set, trap); shellcheck.net wiki for each warning code
#
# Run (inside the sandbox or on any Linux/macOS box; it only touches $DEPLOY_ROOT):
#     bash deploy.sh                         # deploys the bundled sample release into /tmp/deploy-demo
#     bash deploy.sh --break                 # deploys a release whose health check fails, to see the rollback
#     DEPLOY_ROOT=/opt/app bash deploy.sh    # anywhere else

set -euo pipefail                     # HABIT 1: die on error, on unset variables, and on a failed pipe stage
IFS=$'\n\t'                           #          split only on newlines and tabs, never on spaces

# ── configuration: every knob is a variable with a default, never a magic string ──
DEPLOY_ROOT="${DEPLOY_ROOT:-/tmp/deploy-demo}"       # HABIT 2: ${VAR:-default} for optional settings
SERVICE_NAME="${SERVICE_NAME:-app}"
HEALTH_CMD="${HEALTH_CMD:-}"                         # empty means "use the release's own check"
KEEP_RELEASES="${KEEP_RELEASES:-3}"

# ── logging goes to stderr, so stdout stays usable by whoever calls us ──
log()  { printf '%s %s\n' "$(date +%H:%M:%S)" "$*" >&2; }        # HABIT 3: log to 2, data to 1
die()  { log "ERROR: $*"; exit 1; }                              #          and exit non-zero on failure

# ── cleanup runs no matter how we leave: success, die, Ctrl+C ──
WORK="$(mktemp -d)"                                              # HABIT 4: work in a temp dir ...
cleanup() { rm -rf -- "$WORK"; }                                 # ... and a trap removes it
trap cleanup EXIT                                                #          EXIT fires on every exit path

usage() {
  cat >&2 <<USAGE
usage: $0 [--break]
  Deploys the sample release under \$DEPLOY_ROOT (currently: $DEPLOY_ROOT).
  --break   deploy a release whose health check fails, to demonstrate rollback
USAGE
  exit 2
}

# ── argument parsing: explicit, and unknown flags are an error ──
BREAK=0
for arg in "$@"; do                                              # HABIT 5: "$@" keeps each argument whole
  case "$arg" in
    --break) BREAK=1 ;;
    -h|--help) usage ;;
    *) log "unknown argument: $arg"; usage ;;
  esac
done

# ── the release: in real life this is a tarball from CI; here we fabricate one ──
make_release() {
  local version="$1"                                             # local: variables do not leak out of functions
  local dir="$WORK/release-$version"                             # (two locals: the second uses the first)
  mkdir -p -- "$dir/bin"
  if [[ "$BREAK" == 1 ]]; then
    printf '#!/bin/sh\necho "health: FAILING"; exit 1\n' > "$dir/bin/healthcheck"
  else
    printf '#!/bin/sh\necho "health: ok"; exit 0\n' > "$dir/bin/healthcheck"
  fi
  printf 'version=%s\n' "$version" > "$dir/VERSION"
  chmod +x "$dir/bin/healthcheck"
  tar -C "$WORK" -czf "$WORK/release-$version.tar.gz" "release-$version"
  sha256sum "$WORK/release-$version.tar.gz" | cut -d' ' -f1 > "$WORK/release-$version.sha256"
  echo "$WORK/release-$version.tar.gz"                          # a function "returns" by printing
}

verify() {                                                       # the download is not trusted until its hash matches
  local tarball="$1" expected actual
  expected="$(cat "${tarball%.tar.gz}.sha256")"
  actual="$(sha256sum "$tarball" | cut -d' ' -f1)"
  [[ "$expected" == "$actual" ]] || die "checksum mismatch for $tarball"
  log "verified $(basename "$tarball") ($actual)"
}

install_release() {
  local tarball="$1" version="$2"
  local target="$DEPLOY_ROOT/releases/$version"
  [[ -e "$target" ]] && die "release $version already installed at $target"
  mkdir -p -- "$DEPLOY_ROOT/releases"
  local staging
  staging="$(mktemp -d "$DEPLOY_ROOT/releases/.staging-XXXXXX")"    # unpack beside the target ...
  tar -C "$staging" --strip-components=1 -xzf "$tarball"
  mv -- "$staging" "$target"                                       # ... then one rename makes it appear whole
  log "installed $version -> $target"
}

switch_current() {                                               # the atomic switch: a symlink replaced by rename
  local version="$1" link="$DEPLOY_ROOT/current"
  ln -sfn -- "releases/$version" "$link.tmp"
  if mv --version >/dev/null 2>&1; then                            # GNU mv (Linux): -T renames OVER the old link atomically
    mv -Tf -- "$link.tmp" "$link"
  else                                                             # BSD mv (macOS) has no -T: replace in two steps instead
    rm -f -- "$link.tmp"; ln -sfn -- "releases/$version" "$link"
  fi
  log "current -> releases/$version"
}

current_version() {
  [[ -L "$DEPLOY_ROOT/current" ]] && basename "$(readlink "$DEPLOY_ROOT/current")" || echo ""
}

restart_service() {                                              # on a real box: systemctl restart "$SERVICE_NAME"
  log "restart $SERVICE_NAME (simulated)"
}

health_check() {
  local check="${HEALTH_CMD:-$DEPLOY_ROOT/current/bin/healthcheck}"
  if "$check"; then return 0; else return 1; fi                  # HABIT 6: test the exit code, not the output
}

prune_old() {                                                    # keep the last N releases; never delete current
  local keep="$1" cur d
  cur="$(current_version)"
  for d in "$DEPLOY_ROOT"/releases/v*/; do                         # a glob, never `ls | grep` (shellcheck SC2010)
    [[ -d "$d" ]] || continue                                      # no match: the glob stays literal; skip it
    basename -- "$d"
  done | sort -r | grep -vx -- "$cur" | tail -n +"$keep" | while read -r old; do   # names are timestamps: sort -r is newest first
    log "pruning old release $old"
    rm -rf -- "${DEPLOY_ROOT:?}/releases/$old"                    # ${VAR:?} : refuse to run if DEPLOY_ROOT is empty
  done
}

main() {
  local version previous tarball
  version="v$(date +%Y%m%d%H%M%S)"
  previous="$(current_version)"
  log "deploying $version to $DEPLOY_ROOT (previous: ${previous:-none})"

  tarball="$(make_release "$version")"
  verify "$tarball"
  install_release "$tarball" "$version"
  switch_current "$version"
  restart_service

  if health_check; then
    log "health check passed; deploy of $version complete"
    prune_old "$KEEP_RELEASES"
  else
    log "health check FAILED for $version"
    if [[ -n "$previous" ]]; then
      switch_current "$previous"
      restart_service
      log "rolled back to $previous"
    else
      log "no previous release to roll back to"
    fi
    exit 1                                                       # a failed deploy is a failed script
  fi
}

main "$@"
