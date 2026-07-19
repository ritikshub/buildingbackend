# Why Databases Exist: Persistence & the Limits of Files

> A running program's data lives in memory, and memory forgets the instant the power blinks. A database is the machinery we built so that data can *outlive the program that made it* — and be found, shared, and trusted while it does.

**Type:** Learn
**Languages:** —
**Prerequisites:** none
**Time:** ~50 minutes

## The Problem

Write a program that adds a user. Run it. The user exists — you can print it, update
it, query it. Now close the program.

It's gone. Not "deleted" — it was never anywhere durable to begin with. Your variables
lived in **RAM (Random-Access Memory)**, the fast working memory the CPU reads and
writes directly. RAM is **volatile**: cut the power and every bit resets to nothing.
The user you "created" existed only as a pattern of electrical charge that evaporated
the moment the process ended.

So the first thing any real system needs is **persistence** — the ability to write data
somewhere that survives a restart, a crash, or a power cut. That "somewhere" is
**non-volatile storage**: a disk (SSD or spinning platter) that keeps its bits with the
power off. The obvious move is to write your data to a **file**. And for about five
minutes, that works.

Then you try to do anything real with it — look one record up out of a million, let two
users write at once, survive a crash halfway through a save, stop a bug from writing
garbage — and the file fights you at every step. Every one of those fights is a problem
somebody already solved, packaged, and hardened. That package is a **database**. This
lesson is about *why it had to exist* — what a plain file cannot do, so you understand
what every feature in this phase is actually buying you.

## The Concept

### Volatile vs. durable: the two kinds of memory

Every computer has a split personality when it comes to remembering things:

| | Volatile (RAM) | Non-volatile (disk) |
|---|---|---|
| Survives power loss? | **No** | **Yes** |
| Speed | ~100 ns per access | ~100 µs (SSD) to ~10 ms (HDD) |
| Cost per GB | High | Low |
| Addressed by | Byte, directly by the CPU | Block/page, via the OS |
| Holds your data when the program exits? | No | **Yes** |

Your program computes in RAM because RAM is fast. But anything you want to *keep* has to
be copied down to disk before the process ends. **Persistence is that copy** — the
deliberate act of moving state from volatile to durable storage. Everything else in this
phase is a consequence of doing that copy *well*: quickly, safely, for many writers at
once, without ever leaving the data half-written or wrong.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 680 210" width="100%" style="max-width:640px" role="img" aria-label="Your program and RAM live in volatile memory that forgets on power loss; the disk is non-volatile and survives restart. Persisting writes from RAM to disk, loading reads back from disk to RAM." font-family="'JetBrains Mono', ui-monospace, monospace" fill="currentColor">
  <defs><marker id="l01a-ah" markerWidth="10" markerHeight="10" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker></defs>
  <text x="340.0" y="26" text-anchor="middle" font-size="14" font-weight="700">Volatile RAM vs. durable disk</text>
  <g fill="none">
  <path d="M170 127.0 L 188 127.0" fill="none" stroke="currentColor" stroke-width="1.6" marker-end="url(#l01a-ah)"/>
  <path d="M270 113 L 470 113" fill="none" stroke="currentColor" stroke-width="1.6" marker-end="url(#l01a-ah)"/>
  <path d="M470 141 L 270 141" fill="none" stroke="currentColor" stroke-width="1.6" marker-end="url(#l01a-ah)"/>
  </g>
  <g>
  <rect x="18" y="60" width="264" height="130" rx="14" fill="#7f7f7f" fill-opacity="0.05" stroke="currentColor" stroke-width="2" stroke-dasharray="7 6" stroke-opacity="0.55" stroke-linejoin="round"/>
  <rect x="30" y="100" width="140" height="54" rx="9" fill="#3553ff" fill-opacity="0.14" stroke="#3553ff" stroke-width="2" stroke-linejoin="round"/>
  <rect x="188" y="100" width="82" height="54" rx="9" fill="#7c5cff" fill-opacity="0.14" stroke="#7c5cff" stroke-width="2" stroke-linejoin="round"/>
  <rect x="420" y="60" width="242" height="130" rx="14" fill="#7f7f7f" fill-opacity="0.05" stroke="currentColor" stroke-width="2" stroke-dasharray="7 6" stroke-opacity="0.55" stroke-linejoin="round"/>
  <rect x="470" y="100" width="142" height="54" rx="9" fill="#e0930f" fill-opacity="0.14" stroke="#e0930f" stroke-width="2" stroke-linejoin="round"/>
  </g>
  <g>
  <text x="150.0" y="82" font-size="11" text-anchor="middle" font-weight="700" opacity="0.9" >Volatile - forgets on power loss</text>
  <text x="100.0" y="122.9" font-size="11.5" text-anchor="middle" font-weight="700" >Your program</text>
  <text x="100.0" y="138.9" font-size="10" text-anchor="middle" opacity="0.85" >variables, objects</text>
  <text x="229.0" y="130.9" font-size="11.5" text-anchor="middle" >RAM</text>
  <text x="541.0" y="82" font-size="11" text-anchor="middle" font-weight="700" opacity="0.9" >Non-volatile - survives restart</text>
  <text x="541.0" y="122.9" font-size="11.5" text-anchor="middle" font-weight="700" >Disk</text>
  <text x="541.0" y="138.9" font-size="10" text-anchor="middle" opacity="0.85" >files, database</text>
  <text x="370.0" y="107.0" font-size="9.5" text-anchor="middle" opacity="0.75" >persist (write)</text>
  <text x="370.0" y="135.0" font-size="9.5" text-anchor="middle" opacity="0.75" >load (read)</text>
  </g>
  
</svg>
```

### The naïve fix, and where it starts to hurt: a flat file

Say you skip databases and just append each user as a line of text:

```text
1,Ada Lovelace,ada@analytical.org,1815-12-10
2,Alan Turing,alan@bletchley.uk,1912-06-23
3,Grace Hopper,grace@navy.mil,1906-12-09
```

This is a real, persistent data store. It even has a name — a **flat file**. It's fine
until the system grows, and then five distinct things break, each one a pillar that a
database was built to hold up.

### Break #1 — Finding data means reading *everything*

"Get me the user with email `grace@navy.mil`." With a flat file your only option is to
open it and read line by line until you find her — a **full scan**. Ten users: instant.
Ten million users: you read all ten million rows to answer one question, every time. The
cost of a lookup grows linearly with the size of the data — **O(n)** — which is exactly
the wrong direction.

A database can answer the same question by touching a *handful* of rows instead of all
of them, because it keeps a sorted side-structure — an **index** — that jumps straight to
the answer in **O(log n)** steps (Lesson 9). That single capability is most of why
databases feel fast.

### Break #2 — Two writers at once corrupt each other

Two requests both add a user at the same moment. Both read the file's end position, both
write there, and one silently overwrites the other — or worse, their bytes interleave
into a mangled half-line that belongs to neither. This is a **race condition**, and a
flat file has no defense against it. The moment more than one thing writes to your data,
you need someone arbitrating who goes when.

A database provides **concurrency control** — locks, and the transactions of Lessons 11
and 12 — so thousands of clients can read and write the same data at once and each sees
a coherent result, never a torn one.

### Break #3 — Nothing stops you writing nonsense

A flat file will happily accept `banana,,not-an-email,` as a "user." There's no rule that
every user needs an email, that IDs are unique, or that a date is really a date. The file
stores bytes; it has no opinion about whether they *mean* anything. So the burden of
correctness falls entirely on every piece of code that ever touches the file — and the
day one of them has a bug, the bad data is now permanent.

A database enforces **data integrity**: types, uniqueness, required fields, and
relationships between records are declared once as **constraints** (Lesson 6) and the
database *refuses* any write that would violate them. Correctness becomes a property of
the data itself, not a promise every program has to keep.

### Break #4 — A crash mid-write leaves you broken

To "update" Ada's email in a flat file you often rewrite the whole file. Suppose the
power dies when you're 60% through. Now you have a file that is part old, part new, and
part nothing — **corrupt**, and there's no old copy left. The write was neither fully
done nor fully undone.

A database guarantees **atomicity** and **durability** (the A and D of ACID, Lesson 11):
a change either lands *completely* or not at all, and once it says "saved," a crash one
millisecond later cannot lose it. It achieves this with techniques like the
**write-ahead log** of Lesson 13 — writing down what it's *about* to do before it does
it, so recovery can always finish or reverse a half-done change.

### Break #5 — There are no relationships

Real data is connected: users have orders, orders have line items, line items point at
products. In flat files you'd either copy the user's details onto every order (and now
they disagree the moment one copy changes) or invent your own scheme of IDs pointing
across files — and then hand-write, and hand-debug, the code that keeps them in sync.

The **relational model** (Lesson 3) makes those connections first-class: data lives in
tables, and **keys** (Lesson 5) link rows across them, with the database itself enforcing
that a line item can never point at an order that doesn't exist. Relationships stop being
your bug to maintain.

### Putting it together: what a database *is*

Stack those five up and you've described a **Database Management System (DBMS)** — the
software that sits between your application and the raw bytes on disk and provides, in one
hardened package, what every serious application needs and no flat file gives:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 600 444" width="100%" style="max-width:560px" role="img" aria-label="An application asks a DBMS in a query language. The DBMS bundles a query engine, concurrency control, integrity and constraints, and transactions and recovery, and reads and writes durable storage on disk." font-family="'JetBrains Mono', ui-monospace, monospace" fill="currentColor">
  <defs><marker id="l01b-ah" markerWidth="10" markerHeight="10" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker></defs>
  <text x="300.0" y="26" text-anchor="middle" font-size="14" font-weight="700">What a DBMS provides</text>
  <g fill="none">
  <path d="M300.0 96 L 300 130" fill="none" stroke="currentColor" stroke-width="1.6" marker-end="url(#l01b-ah)"/>
  <path d="M300 320 L 300 352" fill="none" stroke="currentColor" stroke-width="1.6" marker-end="url(#l01b-ah)"/>
  </g>
  <g>
  <rect x="218" y="50" width="164" height="46" rx="9" fill="#3553ff" fill-opacity="0.14" stroke="#3553ff" stroke-width="2" stroke-linejoin="round"/>
  <rect x="34" y="130" width="532" height="190" rx="14" fill="#7f7f7f" fill-opacity="0.05" stroke="currentColor" stroke-width="2" stroke-dasharray="7 6" stroke-opacity="0.55" stroke-linejoin="round"/>
  <rect x="58" y="168" width="230" height="58" rx="9" fill="#3553ff" fill-opacity="0.14" stroke="#3553ff" stroke-width="2" stroke-linejoin="round"/>
  <rect x="312" y="168" width="230" height="58" rx="9" fill="#7c5cff" fill-opacity="0.14" stroke="#7c5cff" stroke-width="2" stroke-linejoin="round"/>
  <rect x="58" y="244" width="230" height="58" rx="9" fill="#0fa07f" fill-opacity="0.14" stroke="#0fa07f" stroke-width="2" stroke-linejoin="round"/>
  <rect x="312" y="244" width="230" height="58" rx="9" fill="#12a05a" fill-opacity="0.14" stroke="#12a05a" stroke-width="2" stroke-linejoin="round"/>
  <path d="M190 361 a 110.0 9 0 0 1 220 0 v 54 a 110.0 9 0 0 1 -220 0 Z" fill="#e0930f" fill-opacity="0.13" stroke="#e0930f" stroke-width="2"/>
  <path d="M190 361 a 110.0 9 0 0 0 220 0" fill="none" stroke="#e0930f" stroke-width="2"/>
  </g>
  <g>
  <text x="300.0" y="76.9" font-size="11.5" text-anchor="middle" >Your application</text>
  <text x="300" y="152" font-size="12" text-anchor="middle" font-weight="700" opacity="0.95" >Database Management System (DBMS)</text>
  <text x="312" y="110" font-size="9.5" text-anchor="start" opacity="0.75" >asks in a query language</text>
  <text x="173.0" y="192.9" font-size="11.5" text-anchor="middle" font-weight="700" >Query engine</text>
  <text x="173.0" y="208.9" font-size="10" text-anchor="middle" opacity="0.85" >find data fast - indexes</text>
  <text x="427.0" y="192.9" font-size="11.5" text-anchor="middle" font-weight="700" >Concurrency control</text>
  <text x="427.0" y="208.9" font-size="10" text-anchor="middle" opacity="0.85" >many writers, safely</text>
  <text x="173.0" y="268.9" font-size="11.5" text-anchor="middle" font-weight="700" >Integrity &amp; constraints</text>
  <text x="173.0" y="284.9" font-size="10" text-anchor="middle" opacity="0.85" >no invalid data</text>
  <text x="427.0" y="268.9" font-size="11.5" text-anchor="middle" font-weight="700" >Transactions &amp; recovery</text>
  <text x="427.0" y="284.9" font-size="10" text-anchor="middle" opacity="0.85" >all-or-nothing, crash-safe</text>
  <text x="312" y="332" font-size="9.5" text-anchor="start" opacity="0.75" >reads / writes</text>
  <text x="300.0" y="396.4" font-size="11.5" text-anchor="middle" >Durable storage (disk)</text>
  </g>
  
</svg>
```

A useful one-line definition: **a database is a durable, queryable, concurrent, and
consistent store of data.** Take any of those four words away and you've got something
weaker — a file gives you only "durable," and barely that.

### A little history: how we got here

Databases weren't designed in a day; each generation fixed the pain of the last.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 760 478" width="100%" style="max-width:680px" role="img" aria-label="A timeline from the 1950s to 1986: magnetic tape and punch cards, direct-access disks and ISAM, IBM IMS, CODASYL network model, Codd's relational model in 1970 (the turning point), System R and Ingres, Oracle, and SQL becoming an ANSI/ISO standard." font-family="'JetBrains Mono', ui-monospace, monospace" fill="currentColor">
  
  <text x="380.0" y="26" text-anchor="middle" font-size="14" font-weight="700">From tape to SQL</text>
  <g fill="none">
  <path d="M196 56 L 196 454" fill="none" stroke="currentColor" stroke-width="1.6"/>
  </g>
  <g>
  <rect x="190" y="60" width="12" height="12" rx="6" fill="#7f7f7f" fill-opacity="0.05" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/>
  <rect x="190" y="114" width="12" height="12" rx="6" fill="#7f7f7f" fill-opacity="0.05" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/>
  <rect x="190" y="168" width="12" height="12" rx="6" fill="#7f7f7f" fill-opacity="0.05" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/>
  <rect x="190" y="222" width="12" height="12" rx="6" fill="#7f7f7f" fill-opacity="0.05" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/>
  <rect x="212" y="261" width="274" height="42" rx="9" fill="#7c5cff" fill-opacity="0.14" stroke="#7c5cff" stroke-width="2" stroke-linejoin="round"/>
  <rect x="189" y="275" width="14" height="14" rx="7" fill="#7c5cff" fill-opacity="0.9" stroke="#7c5cff" stroke-width="2" stroke-linejoin="round"/>
  <rect x="190" y="330" width="12" height="12" rx="6" fill="#7f7f7f" fill-opacity="0.05" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/>
  <rect x="190" y="384" width="12" height="12" rx="6" fill="#7f7f7f" fill-opacity="0.05" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/>
  <rect x="190" y="438" width="12" height="12" rx="6" fill="#7f7f7f" fill-opacity="0.05" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/>
  </g>
  <g>
  <text x="174" y="69" font-size="11.5" text-anchor="end" font-weight="700" opacity="0.9" >1950s</text>
  <text x="226" y="62" font-size="11" text-anchor="start" font-weight="700" opacity="0.8" >Magnetic tape &amp; punch cards</text>
  <text x="226" y="79" font-size="10" text-anchor="start" opacity="0.8" >data is sequential, read start-to-finish</text>
  <text x="174" y="123" font-size="11.5" text-anchor="end" font-weight="700" opacity="0.9" >1960s</text>
  <text x="226" y="116" font-size="11" text-anchor="start" font-weight="700" opacity="0.8" >Direct-access disks &amp; ISAM</text>
  <text x="226" y="133" font-size="10" text-anchor="start" opacity="0.8" >random reads become possible</text>
  <text x="174" y="177" font-size="11.5" text-anchor="end" font-weight="700" opacity="0.9" >1966</text>
  <text x="226" y="170" font-size="11" text-anchor="start" font-weight="700" opacity="0.8" >IBM IMS (hierarchical model)</text>
  <text x="226" y="187" font-size="10" text-anchor="start" opacity="0.8" >data as a strict tree, built for Apollo</text>
  <text x="174" y="231" font-size="11.5" text-anchor="end" font-weight="700" opacity="0.9" >1969</text>
  <text x="226" y="224" font-size="11" text-anchor="start" font-weight="700" opacity="0.8" >CODASYL / network model</text>
  <text x="226" y="241" font-size="10" text-anchor="start" opacity="0.8" >records linked by explicit pointers, rigid</text>
  <text x="174" y="285" font-size="11.5" text-anchor="end" font-weight="700" >1970</text>
  <text x="226" y="278" font-size="11" text-anchor="start" font-weight="700" opacity="0.8" >Codd's relational model</text>
  <text x="226" y="295" font-size="10" text-anchor="start" opacity="0.8" >data as simple tables, queried by logic</text>
  <text x="174" y="339" font-size="11.5" text-anchor="end" font-weight="700" opacity="0.9" >1974</text>
  <text x="226" y="332" font-size="11" text-anchor="start" font-weight="700" opacity="0.8" >System R (IBM) &amp; Ingres (Berkeley)</text>
  <text x="226" y="349" font-size="10" text-anchor="start" opacity="0.8" >first working relational systems, and SQL</text>
  <text x="174" y="393" font-size="11.5" text-anchor="end" font-weight="700" opacity="0.9" >1979</text>
  <text x="226" y="386" font-size="11" text-anchor="start" font-weight="700" opacity="0.8" >Oracle</text>
  <text x="226" y="403" font-size="10" text-anchor="start" opacity="0.8" >ships the first commercial relational database</text>
  <text x="174" y="447" font-size="11.5" text-anchor="end" font-weight="700" opacity="0.9" >1986</text>
  <text x="226" y="440" font-size="11" text-anchor="start" font-weight="700" opacity="0.8" >SQL becomes an ANSI/ISO standard</text>
  <text x="226" y="457" font-size="10" text-anchor="start" opacity="0.8" >one query language across vendors</text>
  </g>
  
</svg>
```

The turning point is **1970**, when Edgar F. Codd, a mathematician at IBM, published *"A
Relational Model of Data for Large Shared Data Banks"* (Communications of the ACM, 13(6)).
The systems before it — hierarchical and network databases — stored data as trees and
webs of pointers, and to ask a question you had to know the physical path to the data and
follow it by hand. Codd's radical idea was to **separate the logical shape of the data
from how it's stored**: put everything in simple tables, and let people ask questions by
*describing what they want* rather than *navigating to it*. That idea — data independence
— is why the relational database, born in 1970, is still the default choice today, and
it's the subject of the rest of this phase.

### When a plain file really is enough

Databases earn their complexity by solving the five breaks — so when none of them bite, a
file is the right, honest choice. Skip the database when: the data is written once and
read start-to-finish (logs, an export), there's a **single** writer and no concurrency,
you never need to look up a record by anything but reading the whole thing, and a rare
corruption is recoverable from a re-run. Config files, application logs, and CSV exports
live happily as files for exactly these reasons. Reach for a database the moment you need
to *find*, *share*, *trust*, or *crash-proof* your data — which, for anything with users,
is almost immediately.

## Think about it

1. You store 5 million products in a flat file and need "find the product named
   *Widget-X*." Roughly how many rows do you read? Now the file is sorted by name — does
   that help a *plain file* lookup, and what would you need to make it a fast one?
2. Two web requests both append an order to the same file at the same millisecond. Name
   two distinct bad outcomes, and say which of the "five breaks" each one is.
3. Which of the five breaks does simply making a nightly backup copy of the file *not*
   solve? (Hint: think about what happens *between* backups.)
4. Give one real dataset in a system you know that is genuinely fine as a flat file, and
   say which of the five breaks never applies to it.

## Key takeaways

- Program data lives in **volatile RAM** and vanishes on exit; **persistence** is the act
  of copying it to **durable disk** so it outlives the process.
- A **flat file** persists data but breaks on five fronts: slow lookups (**querying**),
  clobbering writers (**concurrency**), no rules (**integrity**), corruption on crash
  (**atomicity/durability**), and no **relationships**.
- A **DBMS** is the hardened package that solves all five at once: it's a store of data
  that is **durable, queryable, concurrent, and consistent** — remove any of those and
  you're back to a file.
- The **relational model (Codd, 1970)** won by separating the *logical* shape of data
  (tables you query by describing what you want) from *how* it's physically stored — the
  idea the whole phase builds on.
- A file is still the right tool when you have a single writer, whole-file reads, and no
  need to enforce correctness — reach for a database the moment you must find, share,
  trust, or crash-proof your data.

Next: [A Field Guide to Databases: Types & Trade-offs](../02-database-landscape/) — before
we commit to the relational model, a tour of the whole database family and how to tell
which shape fits a problem.
