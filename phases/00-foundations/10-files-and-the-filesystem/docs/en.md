# Files & the Filesystem

> RAM forgets everything when the power goes out. Files are how a computer remembers — and a file is, you guessed it, just a named pile of bytes.

**Type:** Learn
**Languages:** Python
**Prerequisites:** [How a Computer Runs a Program](../09-how-a-computer-runs-a-program/)
**Time:** ~40 minutes

## The Problem

Last lesson: RAM is fast but **volatile** — kill the power and it's wiped. So how does
anything survive? Your photos, your code, a database's records — they're all still
there tomorrow. Where do they live, and how does the computer find one specific thing
among millions?

The answer is **files** and the **filesystem**. Every log a server writes, every
config it reads, and (this surprises people) every database, ultimately bottoms out
here.

## The Concept

### A file is just named bytes

A **file** is a sequence of bytes stored on persistent storage (disk/SSD), with a
**name** so you can find it again. That's the whole definition. The bytes are the same
kind you met in lesson 1; the name and location are what let you come back to them
after the power cycle.

There is **no real difference between a "text file" and a "binary file."** Both are
just bytes. "Text file" only means *the bytes are intended to be read with a text
encoding* (lesson 2) — open a `.png` in a text editor and you see garbage because
those bytes were never meant for that table. Underneath, it's all bytes.

### The filesystem: a tree of folders

If files were a flat heap, you'd never find anything. The **filesystem** organizes
them into a tree of **directories** (folders), which contain files and other
directories:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 584" width="100%" style="max-width:880px" role="img" aria-label="The filesystem tree, and how an absolute path is assembled by walking it. On the left is the root directory, written as a single slash. From root, two edges lead to the directories home and etc. From home an edge leads to the directory user. From user, two edges lead to notes.txt, which is a file, and to projects, which is a directory. From projects a final edge leads to server.py, another file. Directories are drawn as purple rounded boxes; files are drawn as gray page shapes with a folded corner, so the two leaves that are files are obvious at a glance. One route is highlighted in green: root, then home, then user, then projects, then server.py. That is four edges. Below the tree, each node on that route drops down to a chip carrying its name, and each of the four edges drops down to a green slash sitting in the gap between the chips it connects. Read the row left to right and you get slash, home, slash, user, slash, projects, slash, server.py. Closing the gaps gives the assembled absolute path /home/user/projects/server.py. The leading slash comes from starting at the root, which is exactly what makes the path absolute. At the bottom, the directory user is marked as the working directory, and the same file is named two ways: the absolute path /home/user/projects/server.py works from any working directory because it starts at the root, while the relative path projects/server.py is shorter but only means this file while you are in /home/user. Likewise notes.txt relative equals /home/user/notes.txt absolute. Using a relative path from the wrong working directory produces a file not found error even though you can see the file, which is one of the most common beginner bugs. A directory is really just a table mapping names to inode numbers: notes.txt to 8814 and server.py to 8815.">
  <defs>
    <marker id="p0l10a-ar" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker>
    <marker id="p0l10a-arg" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#0fa07f"/></marker>
  </defs>
  <text x="450" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="15" font-weight="700" fill="currentColor">A path IS the route through the tree — walk the edges, collect the names</text>

  <g font-family="'JetBrains Mono', ui-monospace, monospace">

    <!-- legend -->
    <rect x="311" y="42" width="16" height="12" rx="3" fill="#7c5cff" fill-opacity="0.16" stroke="#7c5cff" stroke-width="1.4"/>
    <text x="333" y="52" font-size="9" fill="currentColor" opacity="0.85">directory</text>
    <rect x="406" y="42" width="16" height="12" rx="2" fill="#7f7f7f" fill-opacity="0.18" stroke="#7f7f7f" stroke-width="1.4"/>
    <text x="428" y="52" font-size="9" fill="currentColor" opacity="0.85">file</text>
    <rect x="474" y="46" width="16" height="3" rx="1.5" fill="#0fa07f"/>
    <text x="496" y="52" font-size="9" fill="#0fa07f" font-weight="700">the walk we trace</text>

    <!-- highlighted-walk rings -->
    <g fill="none" stroke="#0fa07f" stroke-width="1.6" stroke-opacity="0.5" stroke-linejoin="round">
      <rect x="19" y="113" width="110" height="50" rx="15"/>
      <rect x="175" y="155" width="134" height="50" rx="15"/>
      <rect x="355" y="155" width="134" height="50" rx="15"/>
      <rect x="535" y="183" width="158" height="50" rx="15"/>
      <rect x="739" y="183" width="146" height="50" rx="15"/>
    </g>

    <!-- directories -->
    <g fill="#7c5cff" fill-opacity="0.10" stroke="#7c5cff" stroke-width="1.8" stroke-linejoin="round">
      <rect x="24" y="118" width="100" height="40" rx="11"/>
      <rect x="180" y="76" width="124" height="40" rx="11"/>
      <rect x="180" y="160" width="124" height="40" rx="11"/>
      <rect x="360" y="160" width="124" height="40" rx="11"/>
      <rect x="540" y="188" width="148" height="40" rx="11"/>
    </g>

    <!-- files: page shape with a folded corner -->
    <g fill="#7f7f7f" fill-opacity="0.12" stroke="#7f7f7f" stroke-width="1.8" stroke-linejoin="round">
      <path d="M540 132 H677 L688 143 V172 H540 Z"/>
      <path d="M744 188 H869 L880 199 V228 H744 Z"/>
    </g>
    <g fill="none" stroke="#7f7f7f" stroke-width="1.5" stroke-linejoin="round">
      <path d="M677 132 V143 H688"/>
      <path d="M869 188 V199 H880"/>
    </g>

    <!-- node labels -->
    <g text-anchor="middle">
      <text x="74" y="140" font-size="15" font-weight="700" fill="#7c5cff">/</text>
      <text x="74" y="152" font-size="7.5" fill="currentColor" opacity="0.65">root</text>
      <text x="242" y="97" font-size="12" font-weight="700" fill="#7c5cff">etc</text>
      <text x="242" y="109" font-size="7.5" fill="currentColor" opacity="0.65">dir</text>
      <text x="242" y="181" font-size="12" font-weight="700" fill="#7c5cff">home</text>
      <text x="242" y="193" font-size="7.5" fill="currentColor" opacity="0.65">dir</text>
      <text x="422" y="181" font-size="12" font-weight="700" fill="#7c5cff">user</text>
      <text x="422" y="193" font-size="7.5" fill="currentColor" opacity="0.65">dir</text>
      <text x="614" y="209" font-size="12" font-weight="700" fill="#7c5cff">projects</text>
      <text x="614" y="221" font-size="7.5" fill="currentColor" opacity="0.65">dir</text>
      <text x="614" y="153" font-size="12" font-weight="700" fill="currentColor">notes.txt</text>
      <text x="614" y="165" font-size="7.5" fill="currentColor" opacity="0.65">file</text>
      <text x="812" y="209" font-size="12" font-weight="700" fill="currentColor">server.py</text>
      <text x="812" y="221" font-size="7.5" fill="currentColor" opacity="0.65">file</text>
    </g>

    <!-- working-directory marker -->
    <rect x="364" y="130" width="116" height="18" rx="6" fill="#3553ff" fill-opacity="0.12" stroke="#3553ff" stroke-width="1.4"/>
    <text x="422" y="143" text-anchor="middle" font-size="8.5" font-weight="700" fill="#3553ff">cwd · you are here</text>

    <!-- tree edges NOT on the traced walk -->
    <g fill="none" stroke="currentColor" stroke-width="1.6" stroke-opacity="0.55" stroke-linejoin="round">
      <path d="M129 138 H154 V96 H175" marker-end="url(#p0l10a-ar)"/>
      <path d="M489 180 H512 V152 H535" marker-end="url(#p0l10a-ar)"/>
    </g>

    <!-- tree edges ON the traced walk -->
    <g fill="none" stroke="#0fa07f" stroke-width="2.2" stroke-linejoin="round">
      <path d="M129 138 H154 V180 H171" marker-end="url(#p0l10a-arg)"/>
      <path d="M309 180 H350" marker-end="url(#p0l10a-arg)"/>
      <path d="M489 180 H512 V208 H531" marker-end="url(#p0l10a-arg)"/>
      <path d="M693 208 H735" marker-end="url(#p0l10a-arg)"/>
    </g>

    <!-- droppers: each walked NODE gives a name, each walked EDGE gives a slash -->
    <g fill="none" stroke="#0fa07f" stroke-width="1.5" stroke-opacity="0.6" stroke-dasharray="4 5">
      <path d="M242 205 V296" marker-end="url(#p0l10a-arg)"/>
      <path d="M422 205 V296" marker-end="url(#p0l10a-arg)"/>
      <path d="M614 233 V296" marker-end="url(#p0l10a-arg)"/>
      <path d="M812 233 V296" marker-end="url(#p0l10a-arg)"/>
      <path d="M154 186 V306" marker-end="url(#p0l10a-arg)"/>
      <path d="M330 186 V306" marker-end="url(#p0l10a-arg)"/>
      <path d="M512 214 V306" marker-end="url(#p0l10a-arg)"/>
      <path d="M714 214 V306" marker-end="url(#p0l10a-arg)"/>
      <path d="M74 163 V320 H146" marker-end="url(#p0l10a-arg)"/>
    </g>
    <text x="74" y="348" text-anchor="middle" font-size="8.5" font-weight="700" fill="#0fa07f">starts at / = absolute</text>

    <!-- the separators, each sitting under the edge it came from -->
    <g text-anchor="middle" font-size="16" font-weight="700" fill="#0fa07f">
      <text x="154" y="324">/</text>
      <text x="330" y="324">/</text>
      <text x="512" y="324">/</text>
      <text x="714" y="324">/</text>
    </g>

    <!-- the name chips, each sitting under the node it came from -->
    <g fill="#7c5cff" fill-opacity="0.10" stroke="#7c5cff" stroke-width="1.7" stroke-linejoin="round">
      <rect x="202" y="302" width="80" height="30" rx="8"/>
      <rect x="382" y="302" width="80" height="30" rx="8"/>
      <rect x="560" y="302" width="108" height="30" rx="8"/>
    </g>
    <rect x="754" y="302" width="116" height="30" rx="3" fill="#7f7f7f" fill-opacity="0.12" stroke="#7f7f7f" stroke-width="1.7"/>
    <g text-anchor="middle" font-size="12.5" font-weight="700">
      <text x="242" y="322" fill="#7c5cff">home</text>
      <text x="422" y="322" fill="#7c5cff">user</text>
      <text x="614" y="322" fill="#7c5cff">projects</text>
      <text x="812" y="322" fill="currentColor">server.py</text>
    </g>

    <!-- close the gaps -->
    <path d="M450 340 V362" fill="none" stroke="#0fa07f" stroke-width="1.8" marker-end="url(#p0l10a-arg)"/>
    <text x="462" y="356" font-size="8.5" fill="currentColor" opacity="0.8">join them up</text>

    <rect x="276" y="368" width="348" height="32" rx="9" fill="#0fa07f" fill-opacity="0.08" stroke="#0fa07f" stroke-width="1.8"/>
    <text x="450" y="390" text-anchor="middle" font-size="18"><tspan fill="#0fa07f">/</tspan><tspan fill="#7c5cff">home</tspan><tspan fill="#0fa07f">/</tspan><tspan fill="#7c5cff">user</tspan><tspan fill="#0fa07f">/</tspan><tspan fill="#7c5cff">projects</tspan><tspan fill="#0fa07f">/</tspan><tspan fill="currentColor">server.py</tspan></text>
    <text x="636" y="384" font-size="9" font-weight="700" fill="#0fa07f">the absolute path</text>
    <text x="636" y="396" font-size="8.5" fill="currentColor" opacity="0.75">same file, from anywhere</text>

    <text x="450" y="418" text-anchor="middle" font-size="10" fill="currentColor" opacity="0.85">Every / is one edge walked; every name between the slashes is one node you entered.</text>

    <!-- absolute vs relative -->
    <rect x="20" y="436" width="860" height="88" rx="11" fill="#3553ff" fill-opacity="0.05" stroke="#3553ff" stroke-opacity="0.55" stroke-width="1.7"/>
    <text x="36" y="458" font-size="11" font-weight="700" fill="#3553ff">Working directory (cwd) = /home/user — a relative path only means something from HERE</text>

    <text x="36" y="480" font-size="9.5" font-weight="700" fill="#0fa07f">ABSOLUTE</text>
    <text x="104" y="480" font-size="11" fill="currentColor">/home/user/projects/server.py</text>
    <text x="312" y="480" font-size="8.5" fill="currentColor" opacity="0.8">works from any cwd — it starts at /</text>
    <text x="560" y="480" font-size="8.5" fill="currentColor" opacity="0.8">· /home/user/notes.txt</text>

    <text x="36" y="498" font-size="9.5" font-weight="700" fill="#3553ff">RELATIVE</text>
    <text x="104" y="498" font-size="11" fill="currentColor">projects/server.py</text>
    <text x="312" y="498" font-size="8.5" fill="currentColor" opacity="0.8">shorter — breaks the moment cwd changes</text>
    <text x="560" y="498" font-size="8.5" fill="currentColor" opacity="0.8">· notes.txt</text>

    <text x="36" y="516" font-size="9" fill="#d64545">Wrong cwd + relative path = "file not found" while you can see the file sitting right there — the classic beginner bug.</text>
  </g>

  <text x="450" y="548" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="10.5" fill="currentColor" opacity="0.9">A path is not a label stuck on a file — it is the sequence of edges you walk to reach it.</text>
  <text x="450" y="568" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="9.5" fill="currentColor" opacity="0.75">A directory is just a table of names → inode numbers: notes.txt → 8814, server.py → 8815.</text>
</svg>
```

You point at any file with a **path** — the route through the tree:

- **Absolute path** starts from the root (`/` on Linux/macOS): `/home/user/notes.txt`.
  It's unambiguous from anywhere.
- **Relative path** starts from wherever you currently are (the *working directory*):
  `notes.txt` or `projects/server.py`. Shorter, but only meaningful relative to "here."

A `.` means "current directory," `..` means "parent directory." Getting paths wrong —
absolute vs relative, wrong working directory — is one of the most common beginner (and
not-so-beginner) bugs.

### Extensions are hints, not truth

The `.txt` / `.png` / `.json` on the end of a name is a **file extension** — a
*convention*, not a rule. It hints to the OS and to programs how to open the file. But
the bytes decide what a file really is: rename `photo.png` to `photo.txt` and it's
still a PNG image; you've only changed the hint. Trusting extensions blindly is, in
fact, a security hole we revisit in Phase 7.

### Metadata: the file's label

Beyond its bytes, a file carries **metadata** — information *about* the file that the
filesystem tracks: its **name**, **size** (in bytes — lesson 1 units!), timestamps
(created/modified), and **permissions** (who may read, write, or execute it).
Permissions are the filesystem's first line of security; you'll meet them again when a
server needs to read a secret file but not let the world read it.

### What's actually on the disk: blocks and inodes

Zoom in one more level. A disk is divided into fixed-size **blocks** (often 4 KB). A
file's bytes are stored across some set of blocks — not necessarily next to each other. So
how does the system find them? With an **inode** (index node): a small record holding the
file's **metadata** plus **pointers to the blocks** that make up its contents.

A **directory** is then just a table mapping **names → inode numbers**:

| Name | inode |
|---|---|
| notes.txt | 8814 |
| server.py | 8815 |

Two things suddenly make sense:

- **Renaming a file is cheap** and never touches the data — you only change a name→inode
  entry in the directory, not the blocks.
- **The name and the file are separate things.** One inode can even have two names (a
  "hard link"). The bytes live in the blocks; names are just labels pointing at the inode.

This is the shape everything durable builds on: bytes live in blocks, and an index points
at them — foreshadowing the B-tree and write-ahead-log lessons in Phase 3.

### Reading and writing

A program doesn't touch the disk directly — the **OS** (operating system) mediates every access (lesson 9).
The pattern is always the same three steps:

1. **Open** the file (by path) — the OS checks permissions and gives you a handle.
2. **Read** bytes from it, or **write** bytes to it.
3. **Close** it — flush anything pending and release the handle.

Most languages wrap this so you can't forget to close (Python's `with` block, below).

### Why this matters for backend

"Where does the data live?" is *the* backend question, and it always ends at files:

- **Config** and **secrets** are files the server reads at startup.
- **Logs** are files the server appends to (Phase 9).
- **Uploads** are user files you store and serve.
- A **database** (Phase 3) is, underneath all its cleverness, a set of carefully managed
  files on disk — which is exactly why the write-ahead log and B-tree lessons later make
  sense.

## Try It

Run [`code/files.py`](../code/files.py) — it writes bytes to a file, reads them back,
and inspects the file's metadata:

```python
from pathlib import Path

path = Path("hello.txt")

path.write_text("hi there\n", encoding="utf-8")   # open, write bytes, close — in one call
print("exists?", path.exists())
print("size (bytes):", path.stat().st_size)        # metadata: byte count
print("contents:", path.read_text(encoding="utf-8"))

# It's just bytes — read the SAME file as raw bytes:
print("raw bytes:", path.read_bytes())             # b'hi there\n'
path.unlink()                                       # delete it, leave no mess
```

**Think about it:**

1. You rename `report.pdf` to `report.txt`. Is it now a text file? What actually changed?
2. A program says "file not found," but you can see the file in your folder. What's the
   most likely cause involving paths?
3. `hello.txt` is 9 bytes and contains `hi there` plus a newline. Count the bytes — does 9
   check out?

## Key takeaways

- A **file** is a named sequence of bytes on persistent storage; "text" vs "binary" is
  just *intended interpretation*, not a real difference.
- The **filesystem** is a tree of **directories**; a **path** locates a file —
  **absolute** (from `/`) or **relative** (from the current directory).
- **Extensions** (`.png`, `.json`) are hints, not truth — the bytes decide.
- Files carry **metadata**: name, size, timestamps, and **permissions** (read/write/execute).
- Access is **open → read/write → close**, always mediated by the OS. Config, logs,
  uploads, and even **databases** are all files underneath.

Next: [What a Network Is](../11-what-a-network-is/) — now that one computer makes sense,
how do two of them talk?
