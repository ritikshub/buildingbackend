# Shell Scripting for Operations: Variables, Quoting, Loops, Exit Codes & set -euo pipefail

> A shell script is a command you will run without watching. This lesson takes one real one, a deploy script that fetches a release, verifies it, installs it atomically, switches the live symlink, checks health and rolls back, and shows the six habits that make it safe to run on a server: strict mode, quoting everything, guards on the variables that feed `rm -rf`, a `trap` for cleanup, exit codes that mean something, and logs on stderr. Then the same script in Python, line for line, so you can see where bash stops being the right tool. Both run in the sandbox; the broken release rolls back and the script exits **1**, because a failed deploy is a failed script.

## The Problem

Every one-liner from lesson 08 that you run twice becomes a script. Every script that works from your terminal gets put in `cron`, in CI, in a `systemd` unit, and is then run at 3 a.m. by nobody. That is when the shell's defaults hurt you. By default, a script **keeps going after a command fails**, treats an **unset variable as an empty string**, and reports a pipeline as successful if its last command was. A script with those defaults can `cd` into a directory that does not exist, and then `rm -rf ./*` in whatever directory it was already in. It has happened to every team.

The fix is not to avoid shell. Bash is on every box, it composes commands better than anything else, and a 60-line deploy script in it is clearer than the Python equivalent. The fix is six habits, applied every time, plus a linter that catches the rest, plus an honest rule for when the job has outgrown the language. This lesson is those things, demonstrated on a script you could deploy with.

## The Concept

### From a one-liner to a script

A script is a text file whose first line names its interpreter (lesson 03's shebang) and which has the execute bit set (lesson 06): `#!/usr/bin/env bash`, `chmod +x deploy.sh`, `./deploy.sh`. It receives arguments as `$1`, `$2`, ..., all of them as `"$@"`, their count as `$#`, and it ends with an exit status that the caller sees in `$?`. Inside, it is the shell language you have been typing all along, with three additions you have not needed at a prompt: functions, control flow, and the discipline to survive running unattended.

### Habit 1: strict mode, and what it does not catch

The second line of every script:

```bash
set -euo pipefail
```

`-e` exits the script the moment a command fails. `-u` makes an unset variable an error instead of silently empty. `-o pipefail` makes a pipeline fail if any stage fails, not only the last (lesson 07). The sandbox shows each one changing a script's behaviour:

```console
$ bash -c 'false; echo reached-without-e'
reached-without-e
$ bash -c 'set -e; false; echo not-reached';  echo "exit: $?"
exit: 1
$ bash -c 'echo [$UNSET_VAR] without -u'
[] without -u
$ bash -c 'set -u; echo [$UNSET_VAR]';  echo "exit: $?"
bash: line 1: UNSET_VAR: unbound variable
exit: 127
$ bash -c 'false | true; echo pipeline-status=$?';  bash -c 'set -o pipefail; false | true; echo with-pipefail=$?'
pipeline-status=0
with-pipefail=1
```

`-e` has exceptions, and they are the reason it is a habit rather than a guarantee:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 430" width="100%" style="max-width:880px" role="img" aria-label="A decision flow for what set -e does when a command returns non-zero. Start: a command fails. Is it the condition of an if, while or until? Then no exit: the failure is the test's answer. Is it followed by or-or or and-and, or is it any stage but the last of such a chain? Then no exit: the operator consumes the status. Is it inside a command substitution assigned on the same line as local, export or declare? Then no exit: the status of the assignment is that of the builtin, which succeeded, so the failure is swallowed silently; the fix is to declare on one line and assign on the next. Is it in a pipeline that is not the last stage, without pipefail? Then no exit. Otherwise: the script exits with that status, and the EXIT trap runs. A footnote lists the three lines from the sandbox: survives-inside-if, survives-with-or, and local swallowed the failure printing zero.">
  <defs>
    <marker id="p1l09a-ar" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker>
  </defs>
  <text x="450" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">set -e: when a failing command stops the script, and the four places it does not</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <rect x="330" y="46" width="240" height="36" rx="9" fill="#c94a12" fill-opacity="0.12" stroke="#c94a12" stroke-width="1.8" stroke-linejoin="round"/>
    <text x="450" y="69" text-anchor="middle" font-size="10.5" font-weight="700" fill="#c94a12">a command returns non-zero</text>
    <g stroke-linejoin="round" stroke-width="1.6">
      <rect x="40"  y="112" width="195" height="86" rx="9" fill="#7f7f7f" fill-opacity="0.12" stroke="#7f7f7f"/>
      <rect x="255" y="112" width="195" height="86" rx="9" fill="#7f7f7f" fill-opacity="0.12" stroke="#7f7f7f"/>
      <rect x="470" y="112" width="195" height="86" rx="9" fill="#d64545" fill-opacity="0.08" stroke="#d64545"/>
      <rect x="685" y="112" width="195" height="86" rx="9" fill="#7f7f7f" fill-opacity="0.12" stroke="#7f7f7f"/>
    </g>
    <g text-anchor="middle" font-size="8.5" fill="currentColor">
      <text x="137" y="132" font-weight="700">the condition of</text>
      <text x="137" y="146" font-weight="700">if / while / until ?</text>
      <text x="137" y="166">no exit: the failure IS</text>
      <text x="137" y="180">the answer to the test</text>
      <text x="352" y="132" font-weight="700">followed by || or &amp;&amp;,</text>
      <text x="352" y="146" font-weight="700">or not last in the chain?</text>
      <text x="352" y="166">no exit: the operator</text>
      <text x="352" y="180">consumes the status</text>
      <text x="567" y="132" font-weight="700" fill="#d64545">inside $( ) on a line with</text>
      <text x="567" y="146" font-weight="700" fill="#d64545">local / export / declare ?</text>
      <text x="567" y="166">no exit, SILENTLY: the status</text>
      <text x="567" y="180">is the builtin's, which is 0</text>
      <text x="782" y="132" font-weight="700">a non-final stage</text>
      <text x="782" y="146" font-weight="700">of a pipeline ?</text>
      <text x="782" y="166">no exit without pipefail:</text>
      <text x="782" y="180">only the last stage counts</text>
    </g>
    <g fill="none" stroke="currentColor" stroke-width="1.5">
      <path d="M420 84 L160 108" marker-end="url(#p1l09a-ar)"/>
      <path d="M440 84 L360 108" marker-end="url(#p1l09a-ar)"/>
      <path d="M460 84 L560 108" marker-end="url(#p1l09a-ar)"/>
      <path d="M480 84 L760 108" marker-end="url(#p1l09a-ar)"/>
      <path d="M450 84 L450 226" marker-end="url(#p1l09a-ar)"/>
    </g>
    <rect x="300" y="230" width="300" height="56" rx="9" fill="#0fa07f" fill-opacity="0.12" stroke="#0fa07f" stroke-width="2" stroke-linejoin="round"/>
    <text x="450" y="252" text-anchor="middle" font-size="10" font-weight="700" fill="#0fa07f">none of the above</text>
    <text x="450" y="268" text-anchor="middle" font-size="8.5" fill="currentColor">the script exits with that status; the EXIT trap runs</text>
    <text x="450" y="280" text-anchor="middle" font-size="7.5" fill="currentColor" opacity="0.7">this is the case you want, and it is most of them</text>
    <rect x="40" y="306" width="840" height="96" rx="10" fill="#e0930f" fill-opacity="0.08" stroke="#e0930f" stroke-width="1.5" stroke-linejoin="round"/>
    <text x="450" y="326" text-anchor="middle" font-size="10" font-weight="700" fill="#e0930f">SEEN IN THE SANDBOX</text>
    <g font-size="8.5" fill="currentColor">
      <text x="56" y="346">set -e; if false; then :; fi; echo survives-inside-if          → survives-inside-if</text>
      <text x="56" y="362">set -e; false || echo survives-with-or                         → survives-with-or</text>
      <text x="56" y="378">set -e; f() { local x=$(false); echo "swallowed: $?"; }; f      → local swallowed the failure: 0    ← the dangerous one</text>
      <text x="56" y="394" opacity="0.8">set -e; f() { local x; x=$(false); echo not-reached; }; f       → exits 1, as intended: declare on one line, assign on the next</text>
    </g>
  </g>
  <text x="450" y="422" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="10.5" fill="currentColor" opacity="0.9">Strict mode catches the failures you did not think about. The four exceptions are the ones you have to think about.</text>
</svg>
```

The third exception is the one that bites: `local x=$(cmd)` on one line swallows `cmd`'s failure, because the line's status is that of `local`, which succeeded. Declare first, assign second. `shellcheck` warns about it (SC2155). Alongside strict mode, `IFS=$'\n\t'` tells the shell to split unquoted expansions only on newlines and tabs, never on spaces, which removes half the quoting accidents before they happen.

### Habit 2: quote everything, and guard what feeds rm

Lesson 03 gave the rule; scripts are where it pays. Every `$var`, `$(cmd)` and `"$@"` is double-quoted. The sandbox shows the two classic failures live, with a file called `my file.log` in the directory:

```console
$ for f in $(ls *.log); do echo "[$f]"; done        # unquoted, and parsing ls
[my]
[file.log]
[other.log]
$ for f in *.log; do echo "[$f]"; done              # a glob loop: each name whole
[my file.log]
[other.log]
$ DIR="";  echo "rm -rf $DIR/build"                  # what the unguarded line would run
rm -rf /build
$ bash -c 'rm -rf "${DIR:?DIR is not set}/build"';  echo "exit: $?"
bash: line 1: DIR: DIR is not set
exit: 127
```

`"${VAR:?message}"` refuses to run if the variable is empty or unset; `"${VAR:-default}"` supplies a default. Those two, plus the slicing forms, cover most of what you will need from **parameter expansion**:

| form | meaning | example (`f=release-v1.tar.gz`) |
|---|---|---|
| `${f:-x}` | `f`, or `x` if unset or empty | defaults for optional config |
| `${f:?msg}` | `f`, or exit with `msg` if unset or empty | guards before anything destructive |
| `${f%.tar.gz}` | strip a suffix | `release-v1` |
| `${f#release-}` | strip a prefix | `v1.tar.gz` |
| `${f/v1/v2}` | replace | `release-v2.tar.gz` |
| `${#f}` | length | `17` |
| `${f:0:7}` | substring | `release` |
| `"${arr[@]}"` | every element, each one whole | loops over arrays |

Use `local` for every variable inside a function, `--` before file arguments, `[[ ]]` for tests, `$(( ))` for arithmetic, and never `ls` as a source of filenames.

### Habit 3: log to stderr, data to stdout, exit codes that mean something

A script is a program, so lesson 07 applies: what it *produces* goes to descriptor 1 and what it *says* goes to descriptor 2. That way `./deploy.sh | tee log` and `version=$(./get-version.sh)` both work. Two helpers are enough:

```bash
log() { printf '%s %s\n' "$(date +%H:%M:%S)" "$*" >&2; }
die() { log "ERROR: $*"; exit 1; }
```

And the script exits **0 only when it did the whole job**. A deploy whose health check failed and which rolled back has not deployed; it exits 1, so that whatever called it (a human, CI, a cron job that mails failures) knows. Exit 2 for a usage error, by convention.

### Habit 4: work in a temp dir, and let a trap clean it up

Anything the script downloads or builds goes into `mktemp -d`, and a `trap` removes it whether the script succeeds, dies, or is interrupted:

```bash
WORK="$(mktemp -d)"
cleanup() { rm -rf -- "$WORK"; }
trap cleanup EXIT
```

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 380" width="100%" style="max-width:880px" font-family="'JetBrains Mono', ui-monospace, monospace" role="img" aria-label="The lifecycle of one script run as a timeline with three possible endings. Start: mktemp -d creates a work directory and trap cleanup EXIT is registered. The middle: build, verify, and stage the release inside the work directory; the real location is not touched yet. Three endings branch from the middle: success, where the last step renames the staged release into place and exits 0; die, where a failed check or a set -e exit leaves with status 1; and Ctrl+C or SIGTERM, which interrupts at any point. All three arrive at the same box: the EXIT trap runs cleanup, the work directory is removed, and the exit status is preserved. A note says that because the real location is touched only by a final rename, an interrupted run leaves the old release exactly as it was, which is lesson 05's atomic replace applied to a whole deploy.">
  <defs>
    <marker id="p1l09b-ar" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker>
    <marker id="p1l09b-arg" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#0fa07f"/></marker>
  </defs>
  <text x="450" y="26" text-anchor="middle" font-size="14.5" font-weight="700" fill="currentColor">One run, three endings, one cleanup: the EXIT trap fires on every path out</text>
  <rect x="40" y="56" width="200" height="70" rx="9" fill="#7c5cff" fill-opacity="0.10" stroke="#7c5cff" stroke-width="1.7" stroke-linejoin="round"/>
  <text x="140" y="78" text-anchor="middle" font-size="10" font-weight="700" fill="#7c5cff">START</text>
  <text x="140" y="96" text-anchor="middle" font-size="8.5" fill="currentColor">WORK=$(mktemp -d)</text>
  <text x="140" y="110" text-anchor="middle" font-size="8.5" fill="currentColor">trap cleanup EXIT</text>
  <rect x="290" y="56" width="320" height="70" rx="9" fill="#7f7f7f" fill-opacity="0.12" stroke="#7f7f7f" stroke-width="1.7" stroke-linejoin="round"/>
  <text x="450" y="78" text-anchor="middle" font-size="10" font-weight="700" fill="currentColor">THE WORK · all inside $WORK</text>
  <text x="450" y="96" text-anchor="middle" font-size="8.5" fill="currentColor">make · verify · unpack into a staging dir</text>
  <text x="450" y="110" text-anchor="middle" font-size="8.5" fill="currentColor" opacity="0.8">the real location has not been touched</text>
  <path d="M242 91 L286 91" fill="none" stroke="currentColor" stroke-width="1.5" marker-end="url(#p1l09b-ar)"/>
  <g stroke-linejoin="round" stroke-width="1.6">
    <rect x="40"  y="176" width="250" height="70" rx="9" fill="#0fa07f" fill-opacity="0.12" stroke="#0fa07f"/>
    <rect x="325" y="176" width="250" height="70" rx="9" fill="#d64545" fill-opacity="0.08" stroke="#d64545"/>
    <rect x="610" y="176" width="250" height="70" rx="9" fill="#e0930f" fill-opacity="0.10" stroke="#e0930f"/>
  </g>
  <g text-anchor="middle" font-size="8.5" fill="currentColor">
    <text x="165" y="196" font-size="10" font-weight="700" fill="#0fa07f">SUCCESS</text>
    <text x="165" y="214">mv staging → releases/v3 (one rename)</text>
    <text x="165" y="228">switch current · health ok · exit 0</text>
    <text x="450" y="196" font-size="10" font-weight="700" fill="#d64545">die / set -e</text>
    <text x="450" y="214">checksum mismatch, tar failed,</text>
    <text x="450" y="228">health failed → rolled back · exit 1</text>
    <text x="735" y="196" font-size="10" font-weight="700" fill="#e0930f">Ctrl+C / SIGTERM</text>
    <text x="735" y="214">interrupted at any line</text>
    <text x="735" y="228">exit 130 or 143</text>
  </g>
  <g fill="none" stroke="currentColor" stroke-width="1.5">
    <path d="M400 128 L200 172" marker-end="url(#p1l09b-ar)"/>
    <path d="M450 128 L450 172" marker-end="url(#p1l09b-ar)"/>
    <path d="M500 128 L700 172" marker-end="url(#p1l09b-ar)"/>
  </g>
  <rect x="250" y="286" width="400" height="56" rx="9" fill="#0fa07f" fill-opacity="0.14" stroke="#0fa07f" stroke-width="2.2" stroke-linejoin="round"/>
  <text x="450" y="308" text-anchor="middle" font-size="10" font-weight="700" fill="#0fa07f">EXIT trap: cleanup runs, $WORK is removed</text>
  <text x="450" y="326" text-anchor="middle" font-size="8.5" fill="currentColor">the exit status is preserved; nothing half-made is left in /tmp</text>
  <g fill="none" stroke="#0fa07f" stroke-width="1.8">
    <path d="M165 248 L380 282" marker-end="url(#p1l09b-arg)"/>
    <path d="M450 248 L450 282" marker-end="url(#p1l09b-arg)"/>
    <path d="M735 248 L520 282" marker-end="url(#p1l09b-arg)"/>
  </g>
  <text x="450" y="368" text-anchor="middle" font-size="10" fill="currentColor" opacity="0.9">Touch the real location last, with one rename. An interrupted run then leaves the old state exactly as it was.</text>
</svg>
```

`EXIT` covers all three endings. A second trap, `trap 'log "failed at line $LINENO"' ERR`, tells you *where* a strict-mode exit happened, which in a 200-line script is the difference between a fix and a guess.

### Habit 5: arguments, explicitly

`"$@"` passes the arguments on whole; `$*` mashes them into one string. Parse them with a `case` loop or `getopts`, reject anything unknown, and print usage to stderr on `-h`:

```console
$ bash -c 'while getopts "vn:" opt; do case $opt in v) echo verbose;; n) echo name=$OPTARG;; *) exit 2;; esac; done; shift $((OPTIND-1)); echo rest=$*' -- -v -n app extra
verbose
name=app
rest=extra
```

Configuration comes from environment variables with defaults (`"${DEPLOY_ROOT:-/opt/app}"`), never from editing the script, and secrets never appear on the command line, because `ps` shows every argument to every user on the box (lesson 10).

### Habit 6: test the exit code, not the output

`if cmd; then` runs `cmd` and branches on its status; that is how every check in a script should be written, rather than comparing printed text. Functions return a status with `return` (or the status of their last command), so `if is_healthy; then` reads like English. The tests you will use: `[[ -f path ]]` regular file, `-d` directory, `-e` exists, `-w` writable, `-L` symlink, `-z "$s"` empty string, `-n` non-empty, `==` with glob patterns, `=~` regex (captures in `BASH_REMATCH`), `-gt -lt -eq` for numbers:

```console
$ x=5;  [[ $x -gt 3 ]] && echo "5 > 3";  [[ "abc" == a* ]] && echo "glob match"
5 > 3
glob match
$ [[ "v1.2.3" =~ ^v([0-9]+)\.([0-9]+) ]] && echo "major=${BASH_REMATCH[1]} minor=${BASH_REMATCH[2]}"
major=1 minor=2
$ is_up() { [ "$1" = ok ]; };  is_up bad;  echo "is_up bad -> $?"
is_up bad -> 1
$ printf 'a 1\nb 2\n' | while read -r name num; do echo "$name=$num"; done
a=1
b=2
```

`while read -r line` is the loop over input lines; `-r` keeps backslashes literal. Arrays hold lists safely (`arr=(a "b c" d)`, `"${arr[@]}"`, `${#arr[@]}`), and a here-document is the right way to write a usage message.

### Idempotent, atomic, and single-instance

Three properties turn a script from a sequence of commands into something you can run again after it failed halfway:

**Idempotent**: running it twice is the same as running it once. `mkdir -p`, `ln -sfn`, `useradd` guarded by `id user &>/dev/null ||`, `install -m 640` instead of `cp` plus `chmod` plus `chown`.

**Atomic where it matters**: build in a staging directory, then one `mv` into the final name; replace the `current` symlink with a temp link and a `mv -T` over it (GNU) so there is no instant when `current` points nowhere. That is lesson 05's atomic replace applied to a whole release, and it is the layout every deploy tool from Capistrano to Kubernetes' volume symlinks uses:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 400" width="100%" style="max-width:880px" font-family="'JetBrains Mono', ui-monospace, monospace" role="img" aria-label="The releases-and-current layout. Under the deploy root there is a releases directory holding v1, v2 and v3, each a complete tree, and a symlink named current that points at releases/v2. A new deploy unpacks v3 into a hidden staging directory inside releases and renames it to v3 in one step. It then creates current.tmp pointing at releases/v3 and renames it over current, so that current flips from v2 to v3 in one atomic step. If the health check fails, the same rename points current back at v2. Old releases beyond the keep count are pruned, never the current one. A note says the service always sees a complete release, that rollback is a symlink change taking microseconds, and that nothing in the root is ever edited in place.">
  <defs>
    <marker id="p1l09c-ar" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker>
    <marker id="p1l09c-arg" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#0fa07f"/></marker>
    <marker id="p1l09c-ard" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#d64545"/></marker>
  </defs>
  <text x="450" y="26" text-anchor="middle" font-size="14.5" font-weight="700" fill="currentColor">releases/ plus a current symlink: deploy is a rename, rollback is a rename</text>
  <rect x="40" y="50" width="380" height="300" rx="10" fill="#7f7f7f" fill-opacity="0.08" stroke="#7f7f7f" stroke-width="1.6" stroke-linejoin="round"/>
  <text x="60" y="72" font-size="10" font-weight="700" fill="currentColor">$DEPLOY_ROOT/</text>
  <text x="80" y="96" font-size="9.5" fill="currentColor">releases/</text>
  <g font-size="9" fill="currentColor">
    <text x="100" y="118">v1/   bin/ VERSION      (oldest; pruned once beyond KEEP)</text>
    <text x="100" y="140">v2/   bin/ VERSION      ← current points here</text>
    <text x="100" y="162">v3/   bin/ VERSION      (just installed by one mv)</text>
    <text x="100" y="184" opacity="0.7">.staging-Ab3x/         (being unpacked; not a release yet)</text>
  </g>
  <rect x="76" y="214" width="320" height="30" rx="7" fill="#0fa07f" fill-opacity="0.14" stroke="#0fa07f" stroke-width="1.4"/>
  <text x="236" y="233" text-anchor="middle" font-size="9.5" font-weight="700" fill="#0fa07f">current → releases/v2</text>
  <text x="60" y="270" font-size="8.5" fill="currentColor" opacity="0.8">the service runs $DEPLOY_ROOT/current/bin/app</text>
  <text x="60" y="284" font-size="8.5" fill="currentColor" opacity="0.8">and never sees a half-unpacked tree</text>
  <text x="60" y="310" font-size="8.5" fill="currentColor" opacity="0.8">nothing here is edited in place; directories</text>
  <text x="60" y="324" font-size="8.5" fill="currentColor" opacity="0.8">are created whole and the link is flipped</text>
  <!-- steps -->
  <g stroke-linejoin="round" stroke-width="1.6">
    <rect x="460" y="60" width="400" height="56" rx="9" fill="#7c5cff" fill-opacity="0.10" stroke="#7c5cff"/>
    <rect x="460" y="130" width="400" height="56" rx="9" fill="#0fa07f" fill-opacity="0.12" stroke="#0fa07f"/>
    <rect x="460" y="200" width="400" height="56" rx="9" fill="#d64545" fill-opacity="0.08" stroke="#d64545"/>
    <rect x="460" y="270" width="400" height="56" rx="9" fill="#e0930f" fill-opacity="0.10" stroke="#e0930f"/>
  </g>
  <g font-size="8.5" fill="currentColor">
    <text x="476" y="80" font-size="10" font-weight="700" fill="#7c5cff">1 · install: unpack beside, then rename</text>
    <text x="476" y="96">tar -C .staging-X -xzf release.tar.gz;  mv .staging-X v3</text>
    <text x="476" y="108" opacity="0.75">v3 appears complete or not at all</text>
    <text x="476" y="150" font-size="10" font-weight="700" fill="#0fa07f">2 · switch: a temp link, renamed over current</text>
    <text x="476" y="166">ln -sfn releases/v3 current.tmp;  mv -T current.tmp current</text>
    <text x="476" y="178" opacity="0.75">current flips v2 → v3 in one step; then restart</text>
    <text x="476" y="220" font-size="10" font-weight="700" fill="#d64545">3 · health failed? the same switch, backwards</text>
    <text x="476" y="236">ln -sfn releases/v2 current.tmp;  mv -T current.tmp current</text>
    <text x="476" y="248" opacity="0.75">rollback is microseconds and needs nothing downloaded</text>
    <text x="476" y="290" font-size="10" font-weight="700" fill="#e0930f">4 · prune: keep N, never the current one</text>
    <text x="476" y="306">sort the names newest-first, skip current, remove the tail</text>
    <text x="476" y="318" opacity="0.75">the previous release stays: it is the rollback target</text>
  </g>
  <text x="450" y="378" text-anchor="middle" font-size="10" fill="currentColor" opacity="0.9">Every deploy tool you will meet later does this with more decoration. The shape is two renames.</text>
</svg>
```

**Single-instance**: two copies of a deploy running at once is a corrupted deploy. `flock` on a lock file makes the second one refuse:

```console
$ ( exec 9>/tmp/demo.lock; flock -n 9 && echo "got the lock" )
got the lock
$ # while another copy holds it:
already running
```

### The environment it will actually run in

A script that works in your terminal and fails in `cron` is lesson 03's runbook, section 4, and it is worth seeing once with your own eyes:

```console
$ env -i /bin/sh -c 'echo PATH=$PATH HOME=[$HOME] TERM=[$TERM]'
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin HOME=[] TERM=[]
```

No `HOME`, no `TERM`, a default `PATH`, no dotfiles, no terminal, an empty stdin. So: absolute paths or an explicit `PATH=` at the top, `sudo -n`, no prompts without a `--yes` flag, and run it once *from* the context it will live in before trusting it there.

### shellcheck, bash -n, bash -x

`shellcheck` is a linter for shell scripts, and it catches most of what this lesson warns about, with a wiki page per warning. The sandbox has it. Run it on a deliberately bad four-line script:

```console
$ cat /tmp/bad.sh
#!/bin/bash
for f in $(ls *.log); do rm $f; done
if [ $x == 1 ]; then echo yes; fi
cat file | grep foo
$ shellcheck /tmp/bad.sh | grep -oE 'SC[0-9]+ \([a-z]+\): .*'
SC2045 (error): Iterating over ls output is fragile. Use globs.
SC2035 (info): Use ./*glob* or -- *glob* so names with dashes won't become options.
SC2086 (info): Double quote to prevent globbing and word splitting.
SC2154 (warning): x is referenced but not assigned.
SC2002 (style): Useless cat. Consider 'cmd < file | ..' or 'cmd file | ..' instead.
```

Five findings in four lines, every one of them a real bug or a habit from this lesson. `bash -n script.sh` checks syntax without running anything; `bash -x script.sh` prints each command after expansion as it runs (lesson 03), which is how you find where a script's idea of a variable diverged from yours.

### When it should be Python

Bash is the right tool for a script that mostly runs other commands, is under about 150 lines, and needs to exist on boxes where Python may not. It is the wrong tool the moment the script parses JSON, needs a dictionary, makes an HTTP request with headers and error handling, or needs a test suite. The two versions of the deploy script in this lesson mark the boundary. Every habit has a Python equivalent:

| bash | Python |
|---|---|
| `set -e` | `subprocess.run(..., check=True)` and exceptions |
| quoting `"$var"` | pass a list to `subprocess.run`: no shell, no quoting |
| `${VAR:?}` | `os.environ["VAR"]` raises `KeyError` |
| `trap cleanup EXIT` | `try` / `finally` |
| `$?` | `result.returncode` |
| `die` and `exit 1` | `raise`, and `sys.exit(1)` at the top level |
| `mv -T` over a symlink | `os.rename` |
| `awk '{...}'` over output | a real parser, and a data structure |

## Build It

The two scripts for this lesson are [`code/deploy.sh`](../code/deploy.sh) and [`code/deploy.py`](../code/deploy.py). They do the same job: fabricate a release tarball (in real life CI would have built it), verify its checksum, unpack it into a staging directory and rename it into `releases/`, flip the `current` symlink, restart the service (simulated), run the release's health check, and roll back if it fails. Both only touch `$DEPLOY_ROOT`, which defaults to `/tmp/deploy-demo`, and both run on macOS and Linux:

```bash
bash phases/01-linux-and-the-command-line/09-shell-scripting-for-operations/code/deploy.sh
bash phases/01-linux-and-the-command-line/09-shell-scripting-for-operations/code/deploy.sh --break   # a release whose health check fails
python3 phases/01-linux-and-the-command-line/09-shell-scripting-for-operations/code/deploy.py
```

Read `deploy.sh` top to bottom with the habits in mind; each one is marked in a comment. The header, the configuration with defaults, the two logging helpers, and the trap are the first twenty lines:

```bash
set -euo pipefail                     # HABIT 1: die on error, on unset variables, and on a failed pipe stage
IFS=$'\n\t'

DEPLOY_ROOT="${DEPLOY_ROOT:-/tmp/deploy-demo}"       # HABIT 2: ${VAR:-default} for optional settings

log()  { printf '%s %s\n' "$(date +%H:%M:%S)" "$*" >&2; }        # HABIT 3: log to 2, data to 1
die()  { log "ERROR: $*"; exit 1; }

WORK="$(mktemp -d)"                                              # HABIT 4: work in a temp dir ...
cleanup() { rm -rf -- "$WORK"; }
trap cleanup EXIT
```

The install and the switch are the two renames from the diagram, and the prune is a glob loop with the guard on the variable that feeds `rm -rf`:

```bash
install_release() {
  local tarball="$1" version="$2"
  local target="$DEPLOY_ROOT/releases/$version"
  [[ -e "$target" ]] && die "release $version already installed at $target"
  local staging
  staging="$(mktemp -d "$DEPLOY_ROOT/releases/.staging-XXXXXX")"    # unpack beside the target ...
  tar -C "$staging" --strip-components=1 -xzf "$tarball"
  mv -- "$staging" "$target"                                       # ... then one rename makes it appear whole
}

switch_current() {
  local version="$1" link="$DEPLOY_ROOT/current"
  ln -sfn -- "releases/$version" "$link.tmp"
  mv -Tf -- "$link.tmp" "$link"                                    # GNU mv -T: rename OVER the old link, atomically
}

rm -rf -- "${DEPLOY_ROOT:?}/releases/$old"                         # ${VAR:?}: refuse to run if DEPLOY_ROOT is empty
```

Run it three times in the sandbox, the third with `--break`:

```console
04:23:46 deploying v20260905042346 to /tmp/deploy-demo (previous: v20260905042345)
04:23:46 verified release-v20260905042346.tar.gz (729c0bff...)
04:23:46 installed v20260905042346 -> /tmp/deploy-demo/releases/v20260905042346
04:23:46 current -> releases/v20260905042346
04:23:46 restart app (simulated)
health: ok
04:23:46 health check passed; deploy of v20260905042346 complete

04:23:47 deploying v20260905042347 to /tmp/deploy-demo (previous: v20260905042346)
04:23:47 installed v20260905042347 -> /tmp/deploy-demo/releases/v20260905042347
04:23:47 current -> releases/v20260905042347
health: FAILING
04:23:47 health check FAILED for v20260905042347
04:23:47 current -> releases/v20260905042346
04:23:47 rolled back to v20260905042346
exit=1
$ ls -l /tmp/deploy-demo;  cat /tmp/deploy-demo/current/VERSION
lrwxrwxrwx 1 root root 24 Sep  5 04:23 current -> releases/v20260905042346
drwxr-xr-x 1 root root 90 Sep  5 04:23 releases
version=v20260905042346
```

The broken release is installed, switched to, found unhealthy, and the link is flipped back to the previous one; the script exits 1; the bad release is still on disk for inspection and will be pruned on a later run. `shellcheck deploy.sh` reports nothing.

`deploy.py` is the same functions in the same order, and the differences are the table above made concrete. There is no quoting problem because the health check is run as a list, there is no `set -e` because failures are exceptions, and the trap is a `finally`:

```python
result = subprocess.run([check], capture_output=True, text=True)   # a LIST: no shell, no quoting problems
return result.returncode == 0                                      # test the exit code, not the output

os.rename(tmp, link)                                               # atomic: rename over the old symlink

try:                                                               # try/finally is the trap
    ...
finally:
    shutil.rmtree(work, ignore_errors=True)                        # cleanup on every exit path
```

Run both against the same `$DEPLOY_ROOT` and they interoperate: the Python deploy sees the bash deploy's releases as the previous version, prunes the oldest once the count exceeds `KEEP_RELEASES`, and rolls back to a bash-installed release when its own health check fails. Two languages, one layout, because the layout is the contract.

## Use It

The habits, each demonstrated in one line inside `make shell`. Strict mode and its exceptions were shown above; here are the tools around a script:

```console
$ shellcheck --version | head -2
ShellCheck - shell script analysis tool
version: 0.10.0
$ shellcheck deploy.sh && echo "deploy.sh: shellcheck clean"
deploy.sh: shellcheck clean
$ bash -n deploy.sh && echo "syntax ok"
syntax ok
$ bash -x deploy.sh 2>&1 | grep -E '^\+ (tar|mv|ln)' | head -3
+ tar -C /tmp/tmp.2ilGoUCc4C -czf /tmp/tmp.2ilGoUCc4C/release-v20260905042350.tar.gz release-v20260905042350
+ tar -C /tmp/deploy-demo/releases/.staging-Q7bK2m --strip-components=1 -xzf /tmp/tmp.2ilGoUCc4C/release-v20260905042350.tar.gz
+ mv -- /tmp/deploy-demo/releases/.staging-Q7bK2m /tmp/deploy-demo/releases/v20260905042350
```

The trap firing on a non-zero exit and preserving the status, and the `ERR` trap naming the line:

```console
$ bash -c 'trap "echo cleanup ran" EXIT; echo working; exit 3';  echo "exit: $?"
working
cleanup ran
exit: 3
$ bash -c 'trap "echo failed at line \$LINENO" ERR; set -e; echo one; false; echo two'
one
failed at line 1
```

Parameter expansion, arithmetic and arrays on one line each:

```console
$ f=release-v1.tar.gz;  echo "${f%.tar.gz}  ${f#release-}  ${f/v1/v2}  ${#f}  ${f:0:7}"
release-v1  v1.tar.gz  release-v2.tar.gz  17  release
$ echo $(( 7 * 6 ));  n=3;  (( n++ ));  echo "n=$n"
42
n=4
$ arr=(a "b c" d);  echo "len=${#arr[@]} second=[${arr[1]}]";  for a in "${arr[@]}"; do printf '[%s] ' "$a"; done;  echo
len=3 second=[b c]
[a] [b c] [d]
```

And the loop over a file's lines, which is how a script reads a list of hosts, users or paths:

```console
$ count=0;  while read -r line; do count=$((count+1)); done < /etc/passwd;  echo "$count users"
19 users
```

## Ship It

The artifact for this lesson is a checklist: [`outputs/checklist-production-shell-script.md`](../outputs/checklist-production-shell-script.md). It is the review to run on any script before it runs on a server or in CI: the header (shebang, strict mode, a comment block, `shellcheck`), variables and quoting (every expansion quoted, `${VAR:?}` on anything that feeds `rm -rf`, `local`, `--`, no `ls` parsing), exit codes and errors (0 only for the whole job, stderr for messages, `ERR` traps), temp files and cleanup (`mktemp`, `trap EXIT`, touch the real location last, `flock`), idempotency and dry-run, argument handling, the environment it will actually run in (`cron`, `systemd`, `sudo`, CI), and the list of conditions under which it should be Python instead.

## Think about it

1. A script has `set -e` and the line `count=$(grep -c ERROR app.log)`. The log has no errors. What happens, why, and what is the fix that keeps strict mode?
2. `cd "$BUILD_DIR" && rm -rf ./*` is "safe because of the `&&`." Describe the run where `BUILD_DIR` is unset with and without `set -u`, and rewrite the line so it is safe under both.
3. The deploy script switches `current` with `ln -sfn` alone instead of a temp link and `mv -T`. What can a request that arrives in the middle of that command observe, and why does the two-step version prevent it?
4. A teammate wants to add JSON parsing of the health-check response to `deploy.sh` with `grep` and `cut`. Using the table in the last concept section, argue for which file that logic belongs in.

## Key takeaways

- A script is a command run unattended. Its defaults (continue after failure, empty for unset, last-stage status for pipes) are wrong for that, so **`set -euo pipefail`** is line two of every script, and `IFS=$'\n\t'` is line three when it loops over output.
- `-e` does not fire in `if`/`while` conditions, after `||`/`&&`, in non-final pipeline stages without `pipefail`, or in `local x=$(cmd)`. **Declare, then assign.**
- **Quote every expansion.** Guard destructive paths with `"${VAR:?}"`, default optional ones with `"${VAR:-x}"`, slice with `${f%.ext}` and `${f#pre}`, loop over globs and `"${arr[@]}"`, never over `ls`.
- **Logs to stderr, data to stdout, exit 0 only for the whole job.** `die()` is two lines. Test exit codes with `if cmd; then`, not printed text.
- **`mktemp -d` plus `trap cleanup EXIT`** covers success, failure and `Ctrl+C`. Build in staging, then one rename; flip a symlink with a temp link and `mv -T`; rollback is the same rename backwards. **Idempotent** steps make a rerun safe; **`flock`** stops a second copy.
- The script will run with **no `HOME`, no terminal, a default `PATH` and an empty stdin**. Absolute paths, `sudo -n`, no prompts, and one test run from that context.
- **`shellcheck`** finds the bugs this lesson describes; `bash -n` checks syntax; `bash -x` shows expansion. When the script needs JSON, a dictionary, HTTP or tests, it is Python now, and every habit has a Python equivalent.

Next: [Processes & Signals: ps, top, kill, jobs & /proc](../10-processes-and-signals/). The deploy script "restarted the service" with an `echo`. Now the real thing: what a process is to the kernel, how `kill -TERM` differs from `kill -KILL`, what a zombie and an orphan are, and a `ps` built from `/proc`.
