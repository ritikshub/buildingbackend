# Designing for Testability: Seams, Injection & the Untestable Function

> One branch in a 60-line `process_order()` decides which way a half-cent rounds. This lesson scans **2,000,000 amounts** and finds that **exactly 0 of them** can reach that branch through the function as written — not "we forgot to test it", but *arithmetically impossible*, because the payment sandbox quotes one fixed rate whose lowest-terms denominator is odd. On a day the real rate is 1.125 that same branch decides **12.5% of transactions**. Refactoring nothing but *who chooses the inputs* — same arithmetic, **240 of 240 cases byte-identical** — takes reachable behaviours from **15 of 24 to 24 of 24**, cuts one test's setup from **11 lines and 4 doubles to 2 lines and 0**, and raises the mutation kill rate of the *same 14 tests* from **57.8% to 73.4%**. Hard to test is not a testing problem. It is a design defect with a measurable size.

**Type:** Build
**Languages:** Python
**Prerequisites:** [Test Doubles: Mocks, Stubs, Fakes & the Lies They Tell](../04-test-doubles/), [Connection Pooling & N+1](../../03-relational-databases/14-connection-pooling-and-n-plus-1/)
**Time:** ~70 minutes

## The Problem

**Tuesday, 09:12.** Finance opens a ticket. Their reconciliation against the payment provider is out by **one penny on 312 invoices** — all of them Tuesday's, none of them Monday's. Not a crash, not an alert, not a failed request. Every one of those 312 invoices was issued by a service with a green build and a coverage report nobody had any reason to doubt.

**Tuesday, 11:40.** You find the suspect in four minutes. It is six lines inside `process_order()`, and it decides how a currency amount rounds when the converted value lands exactly halfway between two minor units — banker's rounding (round-half-to-even, IEEE 754-2019 clause 4.3) against the naive round-half-up. The two rules disagree on exactly one input: a fraction of exactly one half. Everywhere else they agree, which is why nobody has ever noticed.

**Tuesday, 11:52.** You go to write the test. This is where the day stops being about a penny.

`process_order()` takes one parameter, `order_id: int`. To make it price *anything*, you need a database with a merchant row, an order row and line items. To make it price anything *in another currency*, you need the payment gateway, because the exchange rate is fetched from it mid-function. To make it price anything *on a particular date*, you need the clock, because the invoice and renewal dates come from `datetime.now()`. To make it return at all you need the mailer, because it emails the customer before it returns. Four systems, standing up, to check one comparison.

**Tuesday, 14:20.** You write the test everyone writes. You point the database at a temp file, you patch the module's `datetime`, you swap the gateway singleton for a fake, you swap the mailer. Eleven lines of setup, four things substituted, and it works.

Then you try to make the rounding land on the halfway case, and you cannot. Not "it is fiddly" — you try every amount you can think of and none of them produce a tie. The sandbox gateway returns one fixed rate, and you begin to suspect the arithmetic is against you.

It is. The sandbox rate is 1.08, which is `27/25` in lowest terms. An integer number of minor units multiplied by a fraction with an **odd denominator** can never land on exactly one half. Not unlikely — impossible. Every amount you could ever seed, every merchant you could ever configure, every test you or anyone else could ever write against `process_order()` as it stands, misses that branch. On Monday the live rate was 1.08 and nothing happened. On Tuesday it was 1.125 — `9/8` — and one invoice in eight hit the tie.

The tests were not lazy. The test you wrote is the best test available. The coverage report will not help either: it will tell you the line never ran, which you will read as *untested*, when the truth is stranger and worse.

> The problem is not the test. The test is the best test that can be written against this function — and this function has quietly made a region of its own input space unreachable to every test that will ever be written.

## The Concept

### Hard to test is a design smell, not a testing problem

The claim sounds like taste, so measure it. `code/testability.py` contains `process_order_legacy()` written the way this function is really written: **57 non-blank lines, exactly one parameter**, and everything else fetched rather than received. Count the fetches by counting the call sites, which the program does by reading its own source:

| what it reads from the world | call sites |
|---|---|
| the wall clock, `datetime.now(...)` | **5** |
| its own database connection, `sqlite3.connect(...)` | 1 |
| a module-level payment gateway singleton | 2 |
| a module-level mailer singleton | 1 |
| module-level mutable state, the audit log | 1 |
| **total unparameterised reads** | **10** |

One input arrives as an argument. Ten arrive by the function reaching out and taking them. That ratio is the whole diagnosis, and everything measured in the rest of this lesson is a consequence of it.

Now write the smallest honest test of one pricing rule — *an order of exactly 500,000 minor units gets the 10% tier discount* — against the legacy function and against the refactored core. Both answer **486000**. They do not cost the same:

| test written against | setup lines | doubles | real I/O ops |
|---|---|---|---|
| `process_order_legacy()` | **11** | **4** | **8** |
| `price_order()` | **2** | **0** | **0** |

**5.5× the setup, four collaborators substituted, and eight real I/O operations** to check one comparison against a constant. The four are not exotic: the module's `datetime`, a database file on disk, the gateway singleton, the mailer singleton. And the cost is per-test, so it is paid again by every test after this one.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 480" width="100%" style="max-width:840px" role="img" aria-label="An anatomy of the untestable function beside its refactored replacement. On the left, process_order_legacy is 57 lines with exactly one parameter, order_id, and ten unparameterised reads of the world: five calls to datetime.now, one sqlite3.connect, two payment gateway calls, one mailer call and one append to a module-level audit log, each drawn as an arrow leaving the function towards the wall clock, a real database, the network, SMTP and module state. One pricing test through it costs eleven setup lines, four doubles and eight real input-output operations. On the right, the same behaviour split into a fifteen-line imperative shell that does only input and output, and a twenty-two line functional core of price_order and settle that has zero hidden inputs because every input it uses is a parameter. The test passes fakes through a Deps object and patches nothing, and the same pricing test costs two lines, zero doubles and zero input-output operations.">
  <defs>
    <marker id="p12-05-a1" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#7f7f7f"/></marker>
    <marker id="p12-05-a2" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#0fa07f"/></marker>
  </defs>
  <text x="440" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">A dependency is a value the function reads instead of receiving</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <text x="30" y="52" font-size="11" font-weight="700" fill="#d64545">BEFORE — one parameter, ten reads of the world</text>
    <text x="470" y="52" font-size="11" font-weight="700" fill="#0fa07f">AFTER — a shell that does I/O, a core that decides</text>
    <path d="M448 64 L 448 386" fill="none" stroke="currentColor" stroke-width="1" opacity="0.25"/>

    <rect x="30" y="66" width="248" height="298" rx="9" fill="#7c5cff" fill-opacity="0.13" stroke="#7c5cff" stroke-width="1.8"/>
    <text x="42" y="88" font-size="10.5" font-weight="700" fill="currentColor">def process_order_legacy(</text>
    <text x="42" y="103" font-size="10.5" font-weight="700" fill="#3553ff">        order_id: int</text>
    <text x="42" y="118" font-size="10.5" font-weight="700" fill="currentColor">) -&gt; dict:</text>
    <text x="42" y="136" font-size="9" fill="currentColor" opacity="0.75">57 lines · 1 parameter · everything</text>
    <text x="42" y="148" font-size="9" fill="currentColor" opacity="0.75">else it decides with, it fetches</text>

    <g font-size="9.5" fill="currentColor">
      <text x="42" y="176">datetime.now(...)</text><text x="256" y="176" text-anchor="end" font-weight="700" fill="#d64545">x5</text>
      <text x="42" y="202">sqlite3.connect(...)</text><text x="256" y="202" text-anchor="end" font-weight="700" fill="#d64545">x1</text>
      <text x="42" y="228">_GATEWAY.fx_rate / .charge</text><text x="256" y="228" text-anchor="end" font-weight="700" fill="#d64545">x2</text>
      <text x="42" y="254">_MAILER.send(...)</text><text x="256" y="254" text-anchor="end" font-weight="700" fill="#d64545">x1</text>
      <text x="42" y="280">_AUDIT.append(...)</text><text x="256" y="280" text-anchor="end" font-weight="700" fill="#d64545">x1</text>
    </g>
    <path d="M42 292 L 266 292" fill="none" stroke="currentColor" stroke-width="1" opacity="0.35"/>
    <text x="42" y="310" font-size="10" font-weight="700" fill="#d64545">10 unparameterised reads</text>
    <text x="42" y="334" font-size="9.5" fill="currentColor" opacity="0.9">one pricing test through it:</text>
    <text x="42" y="350" font-size="9.5" font-weight="700" fill="#e0930f">11 setup lines · 4 doubles · 8 I/O ops</text>

    <g stroke="#7f7f7f" stroke-width="1.5" fill="none">
      <path d="M280 172 L 300 172" marker-end="url(#p12-05-a1)"/>
      <path d="M280 198 L 300 198" marker-end="url(#p12-05-a1)"/>
      <path d="M280 224 L 300 224" marker-end="url(#p12-05-a1)"/>
      <path d="M280 250 L 300 250" marker-end="url(#p12-05-a1)"/>
      <path d="M280 276 L 300 276" marker-end="url(#p12-05-a1)"/>
    </g>
    <g stroke="#e0930f" stroke-width="1.5">
      <rect x="304" y="160" width="126" height="24" rx="5" fill="#e0930f" fill-opacity="0.13"/>
      <rect x="304" y="186" width="126" height="24" rx="5" fill="#e0930f" fill-opacity="0.13"/>
      <rect x="304" y="212" width="126" height="24" rx="5" fill="#e0930f" fill-opacity="0.13"/>
      <rect x="304" y="238" width="126" height="24" rx="5" fill="#e0930f" fill-opacity="0.13"/>
      <rect x="304" y="264" width="126" height="24" rx="5" fill="#e0930f" fill-opacity="0.13"/>
    </g>
    <g font-size="9" fill="currentColor" font-weight="700">
      <text x="312" y="176">the wall clock</text>
      <text x="312" y="202">a real database</text>
      <text x="312" y="228">the network</text>
      <text x="312" y="254">an SMTP server</text>
      <text x="312" y="280">module state</text>
    </g>

    <rect x="470" y="66" width="380" height="86" rx="9" fill="#7c5cff" fill-opacity="0.13" stroke="#7c5cff" stroke-width="1.8"/>
    <text x="484" y="88" font-size="10.5" font-weight="700" fill="currentColor">def process_order(order_id, <tspan fill="#3553ff">deps</tspan>) -&gt; dict:</text>
    <text x="484" y="106" font-size="9.5" fill="currentColor" opacity="0.85">the imperative shell · 15 lines</text>
    <text x="484" y="122" font-size="9.5" fill="currentColor" opacity="0.85">it loads, charges, saves, mails — and</text>
    <text x="484" y="138" font-size="9.5" fill="currentColor" opacity="0.85">decides nothing at all</text>

    <path d="M660 152 L 660 176" fill="none" stroke="#0fa07f" stroke-width="2" marker-end="url(#p12-05-a2)"/>
    <text x="672" y="170" font-size="9" fill="#0fa07f" font-weight="700">calls, with values</text>

    <rect x="470" y="180" width="380" height="106" rx="9" fill="#0fa07f" fill-opacity="0.13" stroke="#0fa07f" stroke-width="1.8"/>
    <text x="484" y="202" font-size="10.5" font-weight="700" fill="currentColor">price_order(order, <tspan fill="#3553ff">fx</tspan>, <tspan fill="#3553ff">now</tspan>)</text>
    <text x="700" y="202" font-size="9.5" fill="currentColor" opacity="0.8">12 lines</text>
    <text x="484" y="222" font-size="10.5" font-weight="700" fill="currentColor">settle(priced, outcome, <tspan fill="#3553ff">started</tspan>, <tspan fill="#3553ff">finished</tspan>)</text>
    <text x="484" y="240" font-size="9.5" fill="currentColor" opacity="0.8">10 lines</text>
    <text x="484" y="262" font-size="10" font-weight="700" fill="#0fa07f">0 hidden inputs — every input is a parameter</text>
    <text x="484" y="277" font-size="9.5" fill="currentColor" opacity="0.85">so a test writes the value it wants to see</text>

    <rect x="470" y="300" width="380" height="64" rx="9" fill="#3553ff" fill-opacity="0.11" stroke="#3553ff" stroke-width="1.8"/>
    <text x="484" y="320" font-size="10" font-weight="700" fill="#3553ff">Deps(repo, gateway, mailer, clock, audit)</text>
    <text x="484" y="336" font-size="9.5" fill="currentColor" opacity="0.9">the test constructs fakes and passes them in.</text>
    <text x="484" y="352" font-size="10" font-weight="700" fill="#0fa07f">2 setup lines · 0 doubles patched · 0 I/O ops</text>

    <rect x="30" y="386" width="820" height="52" rx="9" fill="#e0930f" fill-opacity="0.11" stroke="#e0930f" stroke-width="1.8"/>
    <text x="46" y="406" font-size="10" fill="currentColor"><tspan font-weight="700" fill="#e0930f">Nothing moved except the arrows.</tspan> The arithmetic is byte-identical — 240 of 240 cases return the same</text>
    <text x="46" y="424" font-size="10" fill="currentColor">invoice. What changed is who chooses the inputs: the function, or the caller. That is the whole refactor.</text>
    <text x="440" y="464" font-size="11" text-anchor="middle" fill="currentColor" opacity="0.9">"Dependency injection" names the right-hand picture. In Python it is spelled: pass the value.</text>
  </g>
</svg>
```

Notice what the right-hand side is *not*. There is no container, no registry, no decorator, no annotation scanner and no configuration file. The arithmetic is unchanged — the program proves that below. The only thing that changed is the direction of the arrows.

### Seams: the places you can change behaviour without editing the code

Michael Feathers gave the idea its name in *Working Effectively with Legacy Code* (Prentice Hall, 2004): a **seam** is a place where you can change a program's behaviour without editing the source at that place. Every test double you have ever written went in through a seam. Python has an unusual number of them, which is a mixed blessing — it means almost anything *can* be tested, and it hides the fact that the ways differ enormously in what they cost you later.

| seam | where it acts | blast radius | how it breaks |
|---|---|---|---|
| pass it as an argument | the call site | none | none |
| default argument value | the `def` line | none | binds once, at def time |
| constructor injection | construction | one object | none |
| rebind a module global | an import path | the module | silent on aliasing |
| `mock.patch` a name | an import path | the module | silent on aliasing |
| subclass and override | a class | a subclass | needs a class to exist |
| `side_effect` call list | call order | the caller | counts the calls |
| environment variable | the process | the process | leaks between tests |

That table is an opinion until you measure it, so the program does. It takes one small function, fixes its clock through four different seams, then applies **three refactors that change no observable behaviour at all** — hoisting a repeated clock read into a variable, adding a default argument, and aliasing the clock to a module-level name at import — and retries each seam:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 380" width="100%" style="max-width:840px" role="img" aria-label="A measured four by four matrix. Four seams are used to fix the clock in one small function, then three behaviour-preserving refactors are applied to that function and each seam is retried. Passing the value as a parameter passes all four columns, four out of four. An argument with a default fails the original and the hoisted-read variants, passes when a default argument is added, and fails when the clock is aliased at import: one out of four. Rebinding the module global passes the original and the hoisted read but fails once a default argument captures the old value at definition time and fails when the name is aliased at import: two out of four. A side-effect call list passes only the original and fails all three refactors: one out of four. The conclusion is that only a parameter is coupled to the behaviour rather than to an import path, a definition site or the number of calls.">
  <text x="440" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">Every seam is a promise about the code. Only one is about the behaviour.</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <text x="440" y="46" text-anchor="middle" font-size="10" fill="currentColor" opacity="0.85">measured: 4 seams fix the clock, then 3 behaviour-preserving refactors are applied and each seam is retried</text>

    <g font-size="9" font-weight="700" fill="currentColor" opacity="0.7">
      <text x="30" y="76">SEAM USED TO FIX THE CLOCK</text>
      <text x="336" y="76" text-anchor="middle">original</text>
      <text x="452" y="76" text-anchor="middle">hoist the read</text>
      <text x="568" y="76" text-anchor="middle">add a default arg</text>
      <text x="684" y="76" text-anchor="middle">alias at import</text>
      <text x="800" y="76" text-anchor="middle">SURVIVES</text>
    </g>
    <path d="M30 84 L 850 84" fill="none" stroke="currentColor" stroke-width="1.2" opacity="0.4"/>
    <path d="M394 62 L 394 232" fill="none" stroke="currentColor" stroke-width="1" opacity="0.3" stroke-dasharray="4 3"/>
    <text x="510" y="60" text-anchor="middle" font-size="9" font-weight="700" fill="#7f7f7f">— three refactors that change no behaviour at all —</text>

    <g stroke-width="1.6">
      <rect x="294" y="94" width="84" height="26" rx="5" fill="#0fa07f" fill-opacity="0.16" stroke="#0fa07f"/>
      <rect x="410" y="94" width="84" height="26" rx="5" fill="#0fa07f" fill-opacity="0.16" stroke="#0fa07f"/>
      <rect x="526" y="94" width="84" height="26" rx="5" fill="#0fa07f" fill-opacity="0.16" stroke="#0fa07f"/>
      <rect x="642" y="94" width="84" height="26" rx="5" fill="#0fa07f" fill-opacity="0.16" stroke="#0fa07f"/>

      <rect x="294" y="130" width="84" height="26" rx="5" fill="#d64545" fill-opacity="0.16" stroke="#d64545"/>
      <rect x="410" y="130" width="84" height="26" rx="5" fill="#d64545" fill-opacity="0.16" stroke="#d64545"/>
      <rect x="526" y="130" width="84" height="26" rx="5" fill="#0fa07f" fill-opacity="0.16" stroke="#0fa07f"/>
      <rect x="642" y="130" width="84" height="26" rx="5" fill="#d64545" fill-opacity="0.16" stroke="#d64545"/>

      <rect x="294" y="166" width="84" height="26" rx="5" fill="#0fa07f" fill-opacity="0.16" stroke="#0fa07f"/>
      <rect x="410" y="166" width="84" height="26" rx="5" fill="#0fa07f" fill-opacity="0.16" stroke="#0fa07f"/>
      <rect x="526" y="166" width="84" height="26" rx="5" fill="#d64545" fill-opacity="0.16" stroke="#d64545"/>
      <rect x="642" y="166" width="84" height="26" rx="5" fill="#d64545" fill-opacity="0.16" stroke="#d64545"/>

      <rect x="294" y="202" width="84" height="26" rx="5" fill="#0fa07f" fill-opacity="0.16" stroke="#0fa07f"/>
      <rect x="410" y="202" width="84" height="26" rx="5" fill="#d64545" fill-opacity="0.16" stroke="#d64545"/>
      <rect x="526" y="202" width="84" height="26" rx="5" fill="#d64545" fill-opacity="0.16" stroke="#d64545"/>
      <rect x="642" y="202" width="84" height="26" rx="5" fill="#d64545" fill-opacity="0.16" stroke="#d64545"/>
    </g>

    <g font-size="9.5" font-weight="700" text-anchor="middle">
      <text x="336" y="111" fill="#0fa07f">PASS</text><text x="452" y="111" fill="#0fa07f">PASS</text><text x="568" y="111" fill="#0fa07f">PASS</text><text x="684" y="111" fill="#0fa07f">PASS</text>
      <text x="336" y="147" fill="#d64545">FAIL</text><text x="452" y="147" fill="#d64545">FAIL</text><text x="568" y="147" fill="#0fa07f">PASS</text><text x="684" y="147" fill="#d64545">FAIL</text>
      <text x="336" y="183" fill="#0fa07f">PASS</text><text x="452" y="183" fill="#0fa07f">PASS</text><text x="568" y="183" fill="#d64545">FAIL</text><text x="684" y="183" fill="#d64545">FAIL</text>
      <text x="336" y="219" fill="#0fa07f">PASS</text><text x="452" y="219" fill="#d64545">FAIL</text><text x="568" y="219" fill="#d64545">FAIL</text><text x="684" y="219" fill="#d64545">FAIL</text>
    </g>

    <g font-size="10" fill="currentColor">
      <text x="30" y="107" font-weight="700" fill="#0fa07f">value passed as a parameter</text>
      <text x="30" y="143">argument with a default</text>
      <text x="30" y="179">rebind the module global</text>
      <text x="30" y="215">side_effect call list</text>
    </g>
    <g font-size="11" font-weight="700" text-anchor="middle">
      <text x="800" y="111" fill="#0fa07f">4/4</text>
      <text x="800" y="147" fill="#d64545">1/4</text>
      <text x="800" y="183" fill="#e0930f">2/4</text>
      <text x="800" y="219" fill="#d64545">1/4</text>
    </g>

    <rect x="30" y="248" width="820" height="66" rx="9" fill="#3553ff" fill-opacity="0.10" stroke="#3553ff" stroke-width="1.8"/>
    <text x="46" y="268" font-size="10" fill="currentColor"><tspan font-weight="700" fill="#3553ff">Read the FAIL cells as what each seam is really coupled to.</tspan> The module-global seam is a bet on an</text>
    <text x="46" y="285" font-size="10" fill="currentColor">import path; the call-list seam is a bet on how many times you call a collaborator. Neither is a behaviour,</text>
    <text x="46" y="302" font-size="10" fill="currentColor">so both break on refactors that change nothing a user could observe — 0 of 3, measured, for the call list.</text>
    <text x="440" y="344" font-size="11" text-anchor="middle" fill="currentColor" opacity="0.9">This is the whole of "the tests broke and nothing changed". The tests were never about the behaviour.</text>
  </g>
</svg>
```

Read the FAIL cells as a statement about what each seam is secretly coupled to. **The parameter survives all three refactors, 3 of 3.** The module-global rebind survives **1 of 3** — it is a bet on an import path, and the moment someone writes `from mod import now` at the top of a file, the copy you patch is not the copy that runs. That is the *patch where it is used, not where it is defined* rule from [Test Doubles](../04-test-doubles/), stated as a measurement rather than as folklore.

The `side_effect` call list survives **0 of 3**, and it is the most instructive failure. Handing a double a list of return values encodes *how many times, and in what order*, the code under test calls its collaborator. Call count is not a behaviour. No user can observe it, no requirement mentions it, and hoisting one repeated read into a variable — the most innocuous refactor in this list — breaks every test that asserted on it.

### Dependency injection is just passing arguments

The term does more harm than any other in this lesson. It arrived attached to Java containers and XML wiring files, and it now scares people away from a technique that is, in Python, one keystroke wide.

Here are four styles the literature gives four names to, applied to the same clock, in the program:

| style | answer | framework lines needed |
|---|---|---|
| parameter injection | `2024-02-29` | **0** |
| constructor injection | `2024-02-29` | **0** |
| default-argument injection | `2024-02-29` | **0** |
| `functools.partial` | `2024-02-29` | **0** |

Identical answers, and **zero lines of container, registry or annotation** in any of them. There is no framework here — and, importantly, there is no framework in FastAPI's `Depends` either. `Depends` is a default argument that the framework happens to evaluate for you, which is why overriding it in a test is a dictionary assignment (`Use It` shows this).

So drop the phrase and keep the idea:

> **A dependency is a value your function needs. Injecting it is passing it.**

Everything else in the dependency-injection literature is about *naming*, *lifetime* (who builds it and how long it lives) and *wiring* (how the values reach the top of the call stack). Those are real problems at scale. They are not this problem, and you do not need to solve them to make a function testable today.

### Functional core, imperative shell

Once you accept that inputs should arrive rather than be fetched, a shape falls out on its own. Push every I/O operation to the *edges* of the call and keep the *decisions* in the middle, where they take values and return values.

The program's split:

- `price_order(order, fx, now)` — **12 lines**. The functional core. No clock, no connection, no globals, no branching on the environment. Same inputs, same output, always.
- `settle(priced, outcome, started, finished)` — **10 lines**. The rest of the core: the decision that needs the *post-charge* clock.
- `process_order(order_id, deps)` — **15 lines**. The imperative shell. It loads, charges, saves, mails, and decides nothing.

The second bullet is the part that gets skipped in most explanations of this pattern, and it is where the pattern earns its keep. The shell does not call the core once in the middle; it **interleaves**. Load, read the clock, decide, do I/O, read the clock again, decide again. A core is not a layer, it is a set of pure functions the shell calls whenever it has gathered enough facts to make a decision.

And a refactor that changes behaviour is a rewrite with a nicer name, so the program proves it did not: **240 generated cases run through both versions, with every field of the returned invoice compared — 240 identical, 0 differing.**

Note the qualifier carefully, because it is the hinge of the whole lesson. That is 240 of 240 cases *that the legacy version can be driven into*. For the cases it cannot be driven into there is no equivalence evidence at all — and that turns out to be the strongest argument for doing the refactor rather than an objection to it.

### Reachability: the behaviours no test could reach

Here is the measurement this lesson exists for. The pricing rules contain **24 decision branches** — the discount tiers, the tax classes, the FX path, the rounding modes, the date clamping, the late fee bands, the payment window and the charge outcomes. The program marks each one as it executes, which is a six-line coverage tracer, and then asks a question coverage tools cannot: **not which branches a suite did run, but which branches a suite could ever run.**

Three harnesses, defined honestly:

- **Tier 0** — seed the database, call the function. No patching of any kind. This is what a unit test is.
- **Tier 1** — tier 0, plus rebinding module globals: a frozen clock, a substituted gateway. This is what a real suite does.
- **The core** — pass the value you want to see. That is the entire harness.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 486" width="100%" style="max-width:840px" role="img" aria-label="A measured reachability chart over the twenty-four decision branches that carry the pricing behaviour. Calling the legacy function with only seeded database rows reaches fifteen of twenty-four branches. Adding a frozen clock and a substituted gateway, which costs four doubles, reaches twenty of twenty-four. Calling the functional core with the values the test wants reaches all twenty-four with no doubles at all. The four branches no legacy harness ever reached are round dot halfway, round dot halfway dot even, round dot halfway dot up and window dot timeout. Below, three cards explain why: an arithmetic blocker where the sandbox rate of one point zero eight is twenty-seven twenty-fifths so zero of two million amounts can produce an exact half, while at a live rate of one point one two five the same branch decides twelve point five percent of transactions; a calendar blocker where the clamping branch is reachable on only seven of three hundred and sixty-five days and the leap anchor on one day, the twenty-ninth of February 2024; and a blocker created by the fix itself, where freezing the clock makes all five clock reads return one instant so a timeout can never elapse.">
  <text x="440" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">Coverage tells you a line did not run. It cannot tell you a line could not run.</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <text x="440" y="46" text-anchor="middle" font-size="10" fill="currentColor" opacity="0.85">24 decision branches carry the pricing behaviour; a branch a test cannot execute is a behaviour no test can check</text>

    <g font-size="9" font-weight="700" fill="currentColor" opacity="0.65">
      <text x="30" y="74">HARNESS</text><text x="742" y="74">REACHED</text><text x="828" y="74" text-anchor="end">DOUBLES</text>
    </g>
    <path d="M30 80 L 850 80" fill="none" stroke="currentColor" stroke-width="1.2" opacity="0.4"/>

    <g stroke-width="1.8">
      <rect x="300" y="92" width="420" height="26" rx="4" fill="none" stroke="currentColor" stroke-opacity="0.3"/>
      <rect x="300" y="92" width="262" height="26" rx="4" fill="#d64545" fill-opacity="0.20" stroke="#d64545"/>
      <rect x="300" y="134" width="420" height="26" rx="4" fill="none" stroke="currentColor" stroke-opacity="0.3"/>
      <rect x="300" y="134" width="350" height="26" rx="4" fill="#e0930f" fill-opacity="0.22" stroke="#e0930f"/>
      <rect x="300" y="176" width="420" height="26" rx="4" fill="#0fa07f" fill-opacity="0.20" stroke="#0fa07f"/>
    </g>

    <g font-size="10" fill="currentColor">
      <text x="30" y="104" font-weight="700">legacy, tier 0</text>
      <text x="30" y="116" font-size="8.5" opacity="0.8">seed the DB, call it</text>
      <text x="30" y="146" font-weight="700">legacy, tier 1</text>
      <text x="30" y="158" font-size="8.5" opacity="0.8">+ freeze the clock, fake the gateway</text>
      <text x="30" y="188" font-weight="700" fill="#0fa07f">core, tier 0</text>
      <text x="30" y="200" font-size="8.5" opacity="0.8">pass the value you want to see</text>
    </g>
    <g font-size="11" font-weight="700" text-anchor="middle">
      <text x="756" y="110" fill="#d64545">15 / 24</text>
      <text x="756" y="152" fill="#e0930f">20 / 24</text>
      <text x="756" y="194" fill="#0fa07f">24 / 24</text>
    </g>
    <g font-size="11" font-weight="700" text-anchor="end" fill="currentColor">
      <text x="828" y="110">2</text><text x="828" y="152">4</text><text x="828" y="194" fill="#0fa07f">0</text>
    </g>

    <rect x="30" y="216" width="820" height="34" rx="7" fill="#d64545" fill-opacity="0.10" stroke="#d64545" stroke-width="1.6"/>
    <text x="44" y="237" font-size="10" fill="currentColor"><tspan font-weight="700" fill="#d64545">Never reached by any legacy harness, at any effort:</tspan> round.halfway · round.halfway.even · round.halfway.up · window.timeout</text>

    <g stroke-width="1.8">
      <rect x="30" y="264" width="264" height="132" rx="9" fill="#7c5cff" fill-opacity="0.11" stroke="#7c5cff"/>
      <rect x="308" y="264" width="264" height="132" rx="9" fill="#7c5cff" fill-opacity="0.11" stroke="#7c5cff"/>
      <rect x="586" y="264" width="264" height="132" rx="9" fill="#7c5cff" fill-opacity="0.11" stroke="#7c5cff"/>
    </g>
    <g font-size="10" font-weight="700" fill="#7c5cff">
      <text x="44" y="284">A · ARITHMETIC</text>
      <text x="322" y="284">B · CALENDAR</text>
      <text x="600" y="284">C · THE FIX ITSELF</text>
    </g>
    <g font-size="9" fill="currentColor">
      <text x="44" y="304">The sandbox quotes one rate,</text>
      <text x="44" y="317">1.08 = 27/25. An odd denominator</text>
      <text x="44" y="330">can never land on exactly 1/2.</text>
      <text x="44" y="352" font-weight="700" fill="#d64545">0 of 2,000,000 amounts reach it</text>
      <text x="44" y="368">On a day the live rate is 1.125</text>
      <text x="44" y="384" font-weight="700" fill="#e0930f">that branch decides 12.5% of pay-ins</text>

      <text x="322" y="304">At tier 0 the dates come from the</text>
      <text x="322" y="317">machine clock, so which branch runs</text>
      <text x="322" y="330">is a property of the calendar.</text>
      <text x="322" y="352" font-weight="700" fill="#d64545">date.clamp: 7 of 365 days</text>
      <text x="322" y="368">and the leap anchor on exactly one:</text>
      <text x="322" y="384" font-weight="700" fill="#e0930f">2024-02-29 — once every four years</text>

      <text x="600" y="304">Tier 1 fixes B by freezing time.</text>
      <text x="600" y="317">But the function reads the clock 5</text>
      <text x="600" y="330">times, and frozen, all 5 agree.</text>
      <text x="600" y="352" font-weight="700" fill="#d64545">finished - started is always 0</text>
      <text x="600" y="368">so the timeout branch is now dead.</text>
      <text x="600" y="384" font-weight="700" fill="#e0930f">A frozen clock cannot test a timeout</text>
    </g>
    <text x="440" y="424" font-size="11" text-anchor="middle" fill="currentColor" opacity="0.9">The core reaches all three in one line each, because the rate, the instant and the elapsed time are arguments.</text>
    <text x="440" y="452" font-size="11" text-anchor="middle" font-weight="700" fill="#3553ff">An unreachable branch is not untested code. It is code no test could ever have been written for.</text>
  </g>
</svg>
```

**15 of 24 at tier 0. 20 of 24 at tier 1, and that costs four doubles. 24 of 24 against the core, with none.** Four branches were never reached by any legacy harness at any effort: `round.halfway`, `round.halfway.even`, `round.halfway.up` and `window.timeout`.

Blocker A is the one from the problem scene, and the program proves it rather than asserting it. The rounding branch is entered only when `amount × rate` has a fractional part of exactly one half. Write the rate as a fraction in lowest terms: the reachable fractional parts are the multiples of `1/denominator`, so one half is reachable **if and only if that denominator is even**.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 430" width="100%" style="max-width:840px" role="img" aria-label="Two number lines showing the fractional part that an integer minor-unit amount can produce after multiplying by an exchange rate. At the sandbox rate of one point zero eight, which is twenty-seven twenty-fifths in lowest terms, the reachable fractional parts are the twenty-five multiples of zero point zero four; the nearest values to one half are zero point four eight and zero point five two, so exactly one half is never produced and a scan of two million amounts finds zero. At a live rate of one point one two five, which is nine eighths, the reachable fractional parts are the eight multiples of zero point one two five and one half is one of them, so two hundred and fifty thousand of the same two million amounts land exactly on the tie. The banker's rounding branch is therefore unreachable through the legacy function by arithmetic rather than by oversight, while deciding twelve point five percent of transactions in production.">
  <text x="440" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">The branch no test could reach, and the day it decides one payment in eight</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <text x="440" y="46" text-anchor="middle" font-size="10" fill="currentColor" opacity="0.85">fractional part of (integer minor units x rate) — the only inputs round_money() can ever be given</text>

    <text x="60" y="76" font-size="11" font-weight="700" fill="#e0930f">the sandbox rate the test is stuck with: 1.08 = 27/25</text>
    <text x="450" y="100" text-anchor="middle" font-size="10" font-weight="700" fill="#d64545">1/2 — the tie</text>
    <path d="M450 106 L 450 146" fill="none" stroke="#d64545" stroke-width="2" stroke-dasharray="5 4"/>
    <path d="M90 124 L 810 124" fill="none" stroke="currentColor" stroke-width="1.5"/>
    <g stroke="#e0930f" stroke-width="2">
      <path d="M90 116 L 90 132"/><path d="M118.8 116 L 118.8 132"/><path d="M147.6 116 L 147.6 132"/><path d="M176.4 116 L 176.4 132"/>
      <path d="M205.2 116 L 205.2 132"/><path d="M234 116 L 234 132"/><path d="M262.8 116 L 262.8 132"/><path d="M291.6 116 L 291.6 132"/>
      <path d="M320.4 116 L 320.4 132"/><path d="M349.2 116 L 349.2 132"/><path d="M378 116 L 378 132"/><path d="M406.8 116 L 406.8 132"/>
      <path d="M435.6 116 L 435.6 132"/><path d="M464.4 116 L 464.4 132"/><path d="M493.2 116 L 493.2 132"/><path d="M522 116 L 522 132"/>
      <path d="M550.8 116 L 550.8 132"/><path d="M579.6 116 L 579.6 132"/><path d="M608.4 116 L 608.4 132"/><path d="M637.2 116 L 637.2 132"/>
      <path d="M666 116 L 666 132"/><path d="M694.8 116 L 694.8 132"/><path d="M723.6 116 L 723.6 132"/><path d="M752.4 116 L 752.4 132"/>
      <path d="M781.2 116 L 781.2 132"/>
    </g>
    <circle cx="450" cy="124" r="5.5" fill="none" stroke="#d64545" stroke-width="2"/>
    <g font-size="8.5" fill="currentColor" opacity="0.8">
      <text x="90" y="152" text-anchor="middle">0.00</text>
      <text x="430" y="152" text-anchor="end">0.48</text>
      <text x="470" y="152" text-anchor="start">0.52</text>
      <text x="781.2" y="152" text-anchor="middle">0.96</text>
    </g>
    <text x="810" y="174" text-anchor="end" font-size="10" font-weight="700" fill="#d64545">25 reachable values, in steps of 0.04 — and 1/2 is not one of them</text>

    <text x="60" y="216" font-size="11" font-weight="700" fill="#0fa07f">the rate production actually quoted on Tuesday: 1.125 = 9/8</text>
    <text x="450" y="240" text-anchor="middle" font-size="10" font-weight="700" fill="#0fa07f">1/2 — hit, by every 8th amount</text>
    <path d="M450 246 L 450 286" fill="none" stroke="#0fa07f" stroke-width="2.2"/>
    <path d="M90 264 L 810 264" fill="none" stroke="currentColor" stroke-width="1.5"/>
    <g stroke="#0fa07f" stroke-width="2">
      <path d="M90 256 L 90 272"/><path d="M180 256 L 180 272"/><path d="M270 256 L 270 272"/><path d="M360 256 L 360 272"/>
      <path d="M540 256 L 540 272"/><path d="M630 256 L 630 272"/><path d="M720 256 L 720 272"/><path d="M810 256 L 810 272"/>
    </g>
    <circle cx="450" cy="264" r="7" fill="#0fa07f" fill-opacity="0.35" stroke="#0fa07f" stroke-width="2.4"/>
    <g font-size="8.5" fill="currentColor" opacity="0.8">
      <text x="90" y="292" text-anchor="middle">0.000</text>
      <text x="810" y="292" text-anchor="middle">0.875</text>
    </g>
    <text x="810" y="314" text-anchor="end" font-size="10" font-weight="700" fill="#0fa07f">8 reachable values, in steps of 0.125 — and 1/2 is one of them</text>

    <rect x="30" y="330" width="820" height="58" rx="9" fill="#7c5cff" fill-opacity="0.11" stroke="#7c5cff" stroke-width="1.8"/>
    <g font-size="10" fill="currentColor">
      <text x="46" y="350"><tspan font-weight="700" fill="#7c5cff">Scanned 2,000,000 integer amounts at each rate.</tspan> At 1.08: <tspan font-weight="700" fill="#d64545">0 exact ties</tspan> — so the half_even /</text>
      <text x="46" y="367">half_up branch is unreachable by arithmetic, not by oversight. At 1.125: <tspan font-weight="700" fill="#0fa07f">250,000 ties, 12.5%</tspan>, where the</text>
      <text x="46" y="384">two rounding modes return 4 and 5. A cent apart, on every eighth invoice, on a branch no test ever ran.</text>
    </g>
    <text x="440" y="416" font-size="11" text-anchor="middle" fill="currentColor" opacity="0.9">A fixed collaborator does not merely make a test slow. It can delete a region of the input space entirely.</text>
  </g>
</svg>
```

At **1.08 = 27/25**, denominator 25, odd: the program scans **2,000,000 integer amounts and finds 0 exact ties**. At **1.125 = 9/8**, denominator 8, even: **250,000 of the same 2,000,000 — 12.5%** — land exactly on the tie, where the two rounding modes return **4 and 5**. One cent apart, on one invoice in eight, on the branch no test ever ran.

That is the generalisable lesson, and it is bigger than rounding. **A fixed collaborator does not merely make a test slow. It can delete a region of the input space entirely** — silently, permanently, and invisibly to every coverage report you will ever read.

Blocker B is a different flavour of the same disease. Because the legacy function derives its dates from `datetime.now()`, which branch a tier-0 test reaches is a property of the *calendar*, not of the test. The date-clamping branch — the one that turns "the 31st, one month on" into the 28th or 30th — is reachable on **7 of 365 days in 2023 and 7 of 366 in 2024**, and the leap-day anniversary branch on **exactly one day: 2024-02-29**. Your suite tests a different thing on those 7 days than on the other 358, nothing anywhere records which day it was, and if you are unlucky the one day it would have caught the bug is a Sunday four years away.

### Hidden inputs, and the second blind spot the fix creates

The standard fix for Blocker B is the one everyone reaches for: freeze the clock. It works — tier 1 recovers the date branches. Then measure what it broke.

`process_order_legacy()` reads the clock **5 times**: to stamp the start, to derive the invoice date, to compare against the prior due date, to stamp the finish, and to write the audit line. Freeze it, and all five return the same instant. So `finished - started` is always exactly zero, and the branch that marks a payment for review when the charge took too long **can never be taken** — not at tier 0, where the clock is real but uncontrollable, and not at tier 1, where the clock is controllable but frozen.

> **A frozen clock cannot test a timeout.** Freezing is not the same as controlling; it is the degenerate case of controlling, and it trades one blind spot for another.

You can reach it at tier 2, by handing the clock a *list* of instants and letting successive calls consume them. But look at what that test now asserts: it asserts that the function reads the clock exactly this many times, in this order. Section 2 already priced that seam — it survived **0 of 3** behaviour-preserving refactors, against **3 of 3** for a parameter. You have bought reachability with a test that a variable rename can break.

The core has no such problem, because `settle(priced, outcome, started, finished)` takes the two instants as two parameters. Elapsed time is an input, so the test writes the elapsed time it wants. This is the general shape of every hidden input — the clock, the random source, the environment, the network, the process's own module state — and [Determinism: Time, Randomness, IDs & Order](../08-determinism-time-randomness-order/) takes the clock apart properly. The design point here is narrower and comes first: **you cannot control an input you did not accept.**

### Testable design catches more bugs per test written

Reachability is a satisfying number, but it is one step removed from what anyone cares about, which is whether the suite finds bugs. So price it directly with mutation testing (DeMillo, Lipton & Sayward, "Hints on Test Data Selection", *IEEE Computer* 11(4), 1978): rewrite the source in small ways, and see whether the suite notices. The program generates **64 mutants** of the 6 pricing rules by AST rewriting — boundary flips, comparison negation, arithmetic swaps and constant bumps — and a mutant is *killed* if any test's answer changes.

The comparison has to be fair or it proves nothing, so all three suites are generated from **one table of 14 behaviours**. Matched suite size is structural here, not a claim: same count, same names, same subjects. The only thing that differs is which inputs each harness is allowed to choose.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 428" width="100%" style="max-width:840px" role="img" aria-label="Measured mutation kill rates for three suites of exactly fourteen tests each, generated from one table of fourteen behaviours and run against sixty-four mutants of the pricing rules. Fourteen tests driven through the legacy function with a frozen clock kill thirty-seven mutants, a rate of fifty-seven point eight percent, and cost one hundred and twelve real input-output operations. The same fourteen tests against the functional core, asserting on exactly the same finished invoice but free to choose the exchange rate and the instant, kill forty-seven, a rate of seventy-three point four percent, at zero input-output operations: fifteen point six points from reachability alone. A third suite of fourteen tests aimed at individual decisions kills forty-four, sixty-eight point eight percent, which is four point seven points lower than the end-to-end core suite because each end-to-end test exercises every rule. Fourteen mutants survive all three suites; seven of those are provably equivalent mutants that produce identical output on a dense input sweep and no suite of any design can kill them.">
  <defs>
    <marker id="p12-05-m1" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#0fa07f"/></marker>
    <marker id="p12-05-m2" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#e0930f"/></marker>
  </defs>
  <text x="440" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">Same 14 tests, same assertions, same author — 15.6 points of detection</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <text x="440" y="46" text-anchor="middle" font-size="10" fill="currentColor" opacity="0.85">64 mutants of the 6 pricing rules; all three suites generated from one table of 14 behaviours, so the sizes match by construction</text>

    <g font-size="9" font-weight="700" fill="currentColor" opacity="0.65">
      <text x="30" y="76">SUITE OF 14 TESTS</text><text x="300" y="76">KILL RATE</text><text x="828" y="76" text-anchor="end">I/O OPS</text>
    </g>
    <path d="M30 82 L 850 82" fill="none" stroke="currentColor" stroke-width="1.2" opacity="0.4"/>

    <g fill="none" stroke="currentColor" stroke-width="1" opacity="0.28">
      <path d="M300 92 L 300 130"/><path d="M300 142 L 300 180"/><path d="M300 192 L 300 232"/><path d="M425 92 L 425 130"/><path d="M425 142 L 425 180"/><path d="M425 192 L 425 232"/><path d="M550 92 L 550 130"/><path d="M550 142 L 550 180"/><path d="M550 192 L 550 232"/><path d="M675 92 L 675 130"/><path d="M675 142 L 675 180"/><path d="M675 192 L 675 232"/><path d="M800 92 L 800 130"/><path d="M800 142 L 800 180"/><path d="M800 192 L 800 232"/>
    </g>

    <g stroke-width="1.8">
      <rect x="300" y="96" width="289" height="30" rx="4" fill="#d64545" fill-opacity="0.20" stroke="#d64545"/>
      <rect x="300" y="146" width="367" height="30" rx="4" fill="#0fa07f" fill-opacity="0.20" stroke="#0fa07f"/>
      <rect x="300" y="196" width="344" height="30" rx="4" fill="#3553ff" fill-opacity="0.18" stroke="#3553ff"/>
    </g>

    <g font-size="10" fill="currentColor">
      <text x="30" y="108" font-weight="700">through process_order_legacy()</text>
      <text x="30" y="121" font-size="8.5" opacity="0.8">tier 1: frozen clock, faked gateway</text>
      <text x="30" y="158" font-weight="700" fill="#0fa07f">core, same assertions</text>
      <text x="30" y="171" font-size="8.5" opacity="0.8">on the same finished invoice</text>
      <text x="30" y="208" font-weight="700" fill="#3553ff">core, one decision per test</text>
      <text x="30" y="221" font-size="8.5" opacity="0.8">asserting on each rule directly</text>
    </g>
    <g font-size="11.5" font-weight="700">
      <text x="601" y="116" fill="#d64545">57.8%</text>
      <text x="679" y="166" fill="#0fa07f">73.4%</text>
      <text x="656" y="216" fill="#3553ff">68.8%</text>
    </g>
    <g font-size="9.5" fill="currentColor" opacity="0.85">
      <text x="655" y="116">37 killed</text><text x="733" y="166">47 killed</text><text x="710" y="216">44 killed</text>
    </g>
    <g font-size="11" font-weight="700" text-anchor="end" fill="currentColor">
      <text x="828" y="116" fill="#d64545">112</text><text x="828" y="166" fill="#0fa07f">0</text><text x="828" y="216" fill="#3553ff">0</text>
    </g>
    <g font-size="9" fill="currentColor" text-anchor="middle" opacity="0.7">
      <text x="300" y="246">0%</text><text x="425" y="246">25%</text><text x="550" y="246">50%</text><text x="675" y="246">75%</text><text x="800" y="246">100%</text>
    </g>

    <path d="M589 134 L 589 140 L 661 140" fill="none" stroke="#0fa07f" stroke-width="2" marker-end="url(#p12-05-m1)"/>
    <path d="M667 140 L 667 146" fill="none" stroke="#0fa07f" stroke-width="2"/>
    <text x="678" y="144" font-size="10.5" font-weight="700" fill="#0fa07f">+15.6 points — pure design</text>
    <path d="M667 184 L 667 190 L 650 190" fill="none" stroke="#e0930f" stroke-width="2" marker-end="url(#p12-05-m2)"/>
    <path d="M644 190 L 644 196" fill="none" stroke="#e0930f" stroke-width="2"/>
    <text x="690" y="194" font-size="10.5" font-weight="700" fill="#e0930f">-4.7 — the surprise</text>

    <rect x="30" y="262" width="404" height="106" rx="9" fill="#0fa07f" fill-opacity="0.10" stroke="#0fa07f" stroke-width="1.8"/>
    <text x="44" y="282" font-size="10" font-weight="700" fill="#0fa07f">Row 1 to row 2 is pure design.</text>
    <g font-size="9.5" fill="currentColor">
      <text x="44" y="300">Same count, same names, same assertions on the</text>
      <text x="44" y="315">same invoice. Row 2 may simply choose the FX</text>
      <text x="44" y="330">rate and the instant. The 4 extra kills are all</text>
      <text x="44" y="345">in round_money — the branch fig. 4 proved was</text>
      <text x="44" y="360">arithmetically out of reach.</text>
    </g>

    <rect x="446" y="262" width="404" height="106" rx="9" fill="#e0930f" fill-opacity="0.10" stroke="#e0930f" stroke-width="1.8"/>
    <text x="460" y="282" font-size="10" font-weight="700" fill="#e0930f">Row 3 went the other way, and that is honest.</text>
    <g font-size="9.5" fill="currentColor">
      <text x="460" y="300">One test per decision localises a failure better</text>
      <text x="460" y="315">but detects worse: an end-to-end core test runs</text>
      <text x="460" y="330">every rule, so a tax mutant faces 14 tests, not 3.</text>
      <text x="460" y="345">Testable design buys the choice — it does not</text>
      <text x="460" y="360">tell you to shatter the suite into units.</text>
    </g>
    <text x="440" y="394" font-size="11" text-anchor="middle" fill="currentColor" opacity="0.9">14 mutants survived all three suites. 7 are provably equivalent — identical output on a dense sweep.</text>
    <text x="440" y="414" font-size="11" text-anchor="middle" font-weight="700" fill="#7c5cff">So 100% is not an ambitious target. It is a category error.</text>
  </g>
</svg>
```

**Row 1 against row 2 is the result.** Fourteen tests through the legacy function kill **37 of 64 — 57.8%** — and cost **112 real I/O operations**. The same fourteen tests against the core, asserting on exactly the same observable (the finished invoice), kill **47 — 73.4%** — at **0 I/O operations**. Same count, same names, same assertions, same author. The difference is **+15.6 points**, and it comes entirely from being allowed to choose the FX rate and the instant. All four extra kills are in `round_money`, on the branch the previous section proved was arithmetically out of reach.

**Row 3 was a surprise, and it went the wrong way.** A third suite of fourteen tests aimed at the individual rules — one assertion per decision, the shape most people mean by "unit test" — killed **44, 68.8%**: **4.7 points worse** than driving the whole core. The reason is mundane once you see it: an end-to-end core test executes *every* rule, so a tax mutant faces all 14 tests instead of the 3 that name tax. Granularity trades **detection** against **failure localisation** — the axis [The Shape of a Test Suite](../02-the-shape-of-a-test-suite/) measures directly. Testable design buys you the *choice* of granularity; it does not instruct you to shatter a suite into one test per function, and this measurement is a caution against doing so reflexively.

One more honest number. **14 mutants survived all three suites.** The program then runs each survivor over a dense sweep of its own inputs and finds that **7 of them produce byte-identical output** — they are **equivalent mutants**, changes to the source that are not changes to the behaviour, and no test of any design can ever kill them. (The clearest is `day.day > last` becoming `day.day >= last` in the date clamp: when `day.day == last`, clamping to `last` returns the very same date.) The other 7 are simply untested, which is a backlog item rather than a design problem. Deciding which is which is undecidable in general — so a mutation score is a number you *read*, never a number you *meet*. [Coverage Lies, Mutation Testing Doesn't](../13-coverage-and-mutation-testing/) builds the engine properly.

### The cost: indirection is not free

Everything so far argues one way, which should make you suspicious. So apply the identical technique to a function that has **no hidden inputs at all** and measure what it buys:

| design | lines | names to learn | hops to the arithmetic | behaviours unblocked |
|---|---|---|---|---|
| `format_receipt_line(name, qty, minor)` | **2** | 1 | 1 | 0 |
| `ReceiptFormatter` + `CurrencyPolicy` + a `Protocol` port | **13** | 3 | 3 | **0** |

Same answer, `widget x2 123.45`, from both. **+11 lines, +2 names, +2 hops from the call site to the arithmetic, and zero behaviours unblocked** — because none were blocked. Nothing was hidden, so nothing could be revealed.

This is the honest core of the **"test-induced design damage"** critique, and it deserves to be stated at full strength rather than dismissed. An interface extracted so a test can pass a stub, when the concrete thing had no hidden inputs, is a permanent tax: a name every future reader must learn, a hop every future debugger must follow, and a second place every future change must be made. The tests get easier and the code gets worse. When someone says a codebase has been damaged by its tests, this is usually what they are looking at, and they are usually right.

The measurements point at a rule that decides the cases cleanly:

> **Inject a dependency when it is a hidden input** — something the function reads from the world instead of receiving. The clock, the database, the network, the environment, the random source, module-level mutable state.
>
> **Do not inject arithmetic, formatting, or anything a caller can already vary by passing a different value.**

`process_order_legacy()` had **10** hidden inputs, and removing them took reachability from 15 of 24 to 24 of 24 and bought 15.6 points of detection. `format_receipt_line()` has **0**, and abstracting it unblocks nothing. The test is not "could this be mocked" — in Python everything can be. The test is *what does the function read that its caller cannot choose*.

Two more limits worth stating plainly. A `Protocol` with exactly one implementation forever is a synonym, not an abstraction. And a shell that has grown decisions of its own has stopped being a shell — if you find yourself wanting to unit-test `process_order()` rather than the core, that is a signal the split has drifted, not a signal to start mocking.

### Legacy code: characterization first, then extract

None of this helps with the function you already have, whose behaviour nobody fully knows and whose 60 lines are load-bearing in ways the ticket does not mention. You cannot refactor safely towards tests you do not have yet, and you cannot write the tests you want until you refactor. Feathers' way out of that circle is the **characterization test**: a test that asserts nothing about what the code *should* do, and instead records what it *does* — bugs included — so that any change to that behaviour shows up as a failure. It is a tripwire, not a specification.

The program builds one. It records the legacy function's output over **120 generated cases**, refactors, and replays: **120 of 120 identical**. Then it introduces an accidental behaviour change — an off-by-one in the date clamp, exactly the kind of thing that happens during a careless extraction — and the harness catches it, on **4 of 120 cases (3.3%)**.

Read that rate rather than just the verdict, because the rate is the lesson:

| corpus size | cases flagging the regression | caught? |
|---|---|---|
| 10 | 0 | **NO** |
| 20 | 0 | **NO** |
| 40 | 1 | yes |
| 80 | 3 | yes |
| 120 | 4 | yes |

**A corpus of 20 recorded cases would have shipped this regression.** The clamp fires only on the handful of dates the calendar blocker counted, so a small corpus never contains one. And note the recursion: a characterization suite is only as good as the inputs it recorded, and the inputs it can record are exactly the ones the legacy design permits. It cannot pin behaviour it cannot reach — the rounding tie is invisible to it too.

So the order of operations, and the last step matters most:

1. **Record**, over a corpus large enough to contain the rare inputs — generated, not hand-picked.
2. **Extract** the pure decision, leaving the I/O where it is.
3. **Write real tests** against the extracted core, where the previously unreachable cases are now one argument away.
4. **Delete the recording.** A characterization suite kept forever pins the bugs in place along with the behaviour, and turns every intentional fix into a failing build.

## Build It

[`code/testability.py`](code/testability.py) is standard library only, seeded at 20260718, and runs in about six seconds. It defines the legacy function and its refactored replacement, then drives both through eight measured sections.

**The branch tracer is six lines**, and it is what makes "reachable" a measurement instead of an opinion. Every decision in the pricing rules records that it was taken:

```python
BRANCHES: set[str] = set()

def mark(name: str) -> None:
    BRANCHES.add(name)
```

Then a harness attempt is just: clear the set, run something, and see what came back. `run_isolated()` catches exceptions so an attempt that raises still reports the branches it reached before dying.

**The rounding rule is where the lesson lives.** It is deliberately ordinary — the kind of code that passes review in ten seconds:

```python
def round_money(exact: Fraction, mode: str) -> int:
    whole = exact.numerator // exact.denominator
    frac = exact - whole
    if frac > Fraction(1, 2):
        mark("round.up")
        return whole + 1
    if frac < Fraction(1, 2):
        mark("round.down")
        return whole
    mark("round.halfway")                       # <- reachable only if 2*frac == 1
    if mode == "half_even":
        mark("round.halfway.even")
        return whole if whole % 2 == 0 else whole + 1
    mark("round.halfway.up")
    return whole + 1
```

`Fraction` rather than `float` is deliberate: the tie must be *exactly* one half, and binary floating point cannot represent 1.08 exactly, so a float implementation would make the whole question about representation error instead of about design. Here the arithmetic is exact and the reachability result is about the rate, which is the point.

**The unreachability proof is one line of integer arithmetic**, and it is worth more than any amount of prose about mocking:

```python
hits = sum(1 for m in range(1, scan + 1)
           if (m * r.numerator) % r.denominator * 2 == r.denominator)
```

`m * numerator % denominator` is the numerator of the fractional part over `denominator`. It equals exactly half when doubling it gives the denominator. Run that over 2,000,000 amounts at `27/25` and you get zero, because an odd denominator has no multiple of `1/denominator` equal to `1/2`. Run it at `9/8` and you get 250,000.

**The shell is the whole of the refactor**, and it is short enough to read in one breath. Note that it calls the core *twice* — once when it has the facts to price, and again when it has the facts to settle:

```python
def process_order(order_id: int, deps: Deps) -> dict[str, Any]:
    order = deps.repo.load(order_id)
    started = deps.clock()
    priced = price_order(order, deps.gateway.fx_rate(order.currency), deps.clock())
    outcome = deps.gateway.charge(order.customer,
                                  priced.total_minor + priced.fee_minor, order.currency)
    status = settle(priced, outcome, started, deps.clock())
    deps.repo.save_invoice(order_id, priced.total_minor, priced.fee_minor, status)
    ...
```

`deps` is a plain dataclass of five values. There is no framework, no registry and no lifecycle. The ports it holds are `typing.Protocol` classes, so `SqliteOrderRepository` does not import, subclass or register anything — it simply has the right methods.

**The matched-suite comparison is generated from one table**, which is the only way "same size" means anything:

```python
SUBJECTS: list[tuple[str, dict[str, Any], Fraction, datetime]] = [
    ("round_halfway_half_even", dict(items=((1, 4),)), Fraction(9, 8), NOW),
    ...
]
```

The legacy suite ignores the `Fraction` column entirely — it cannot choose a rate, so it gets whatever the sandbox returns. The parity suite passes it. That single column is the entire difference between 57.8% and 73.4%.

Run it:

```bash
docker compose exec -T app python \
  phases/12-testing-and-quality/05-designing-for-testability/code/testability.py
```

```console
==========================================================================
DESIGNING FOR TESTABILITY: SEAMS, INJECTION & THE UNTESTABLE FUNCTION
seed=20260718 · stdlib only · every number below is measured, not asserted
==========================================================================

== 1 · THE UNTESTABLE FUNCTION: WHAT ONE PRICING TEST COSTS ==
  process_order_legacy() is 57 non-blank lines and takes exactly one
  parameter: order_id. Everything else it decides with, it fetches itself.
  Count the hidden inputs by counting the call sites:
  hidden input                                 call sites
  the wall clock                                        5
  its own database connection                           1
  a module-level payment gateway singleton              2
  a module-level mailer singleton                       1
  module-level mutable state                            1
                                                    -----
  total unparameterised reads of the world             10

  Now write the smallest possible test of one pricing rule -- 'an order of
  exactly 500000 minor units gets the 10% discount' -- against each.
  test written against        setup lines  doubles  I/O ops   answer
  process_order_legacy()               11        4        8   486000
  price_order()                         2        0        0   486000
  Both answer 486000. One needed a database on disk, a frozen clock, a
  fake gateway and a fake mailer to say so -- 5.5x the setup and 8 real I/O
  operations. The test is not badly written; there is no better one to write.

== 2 · SEAMS: WHERE YOU CAN CHANGE BEHAVIOUR WITHOUT EDITING THE CODE ==
  seam used to fix the clock            original    hoist the read add a default arg   alias at import   survives
  value passed as a parameter               PASS              PASS              PASS              PASS        4/4
  argument with a default                   FAIL              FAIL              PASS              FAIL        1/4
  rebind the module global                  PASS              PASS              FAIL              FAIL        2/4
  side_effect call list                     PASS              FAIL              FAIL              FAIL        1/4

== 3 · DEPENDENCY INJECTION IS PASSING ARGUMENTS. THAT IS THE WHOLE IDEA. ==
  style                                 answer   framework lines
  parameter injection               2024-02-29                 0
  constructor injection             2024-02-29                 0
  default-argument injection        2024-02-29                 0
  functools.partial                 2024-02-29                 0
  identical answers: True. Container, registry or annotation lines: 0.

== 4 · THE REFACTOR: FUNCTIONAL CORE, IMPERATIVE SHELL ==
  price_order()   -- the core, 12 lines. No clock, no connection, no
                     globals. Every input it uses is a parameter.
  settle()        -- 10 more lines of core, for the post-charge decision.
  process_order() -- the shell, 15 lines. It does I/O and calls the core.
  cases run through both versions                      240
  identical total, fee, status, due and renewal        240
  any field differing                                    0

== 5 · REACHABILITY: THE TESTS YOU COULD NOT WRITE AT ALL ==
  harness                                               reached  of  doubles
  legacy, tier 0: seed the DB and call it                    15  24        2
  legacy, tier 1: + freeze the clock, fake the gateway       20  24        4
  core, tier 0: pass the value you want to see               24  24        0
  branches no legacy harness ever reached: round.halfway round.halfway.even round.halfway.up window.timeout

  A · THE ARITHMETIC BLOCKER -- round.halfway is unreachable, provably.
  rate       lowest terms   amounts scanned   exact halves    share
  1.08              27/25           2000000              0    0.0%
  1.125               9/8           2000000         250000   12.5%
  The core reaches it in one line, because the rate is an argument:
    round_money(apply_fx(4, Fraction(9,8)), 'half_even') -> 4
    round_money(apply_fx(4, Fraction(9,8)), 'half_up')   -> 5

  B · THE CALENDAR BLOCKER -- date.clamp depends on the day CI runs.
  year      days in year    days reaching date.clamp    share
  2023               365                           7    1.9%
  2024               366                           7    1.9%
  date.leap_anchor is reachable on 1 day in these two years: 2024-02-29

  C · THE BLOCKER THE FIX CREATES -- a frozen clock cannot test a timeout.
  harness                                         window.ok  window.timeout
  legacy, tier 0 (the machine's clock)                  yes              no
  legacy, tier 1 (one frozen instant)                   yes              no
  core, settle(started, finished) as params             yes             yes
  the clock, which is not a behaviour -- and section 2 priced it: that seam
  survived 0 of 3 no-op refactors, against 3 of 3 for a parameter.

== 6 · MUTATION KILL RATE AT MATCHED SUITE SIZE ==
  suite                                        tests  killed  survived  kill rate   I/O
  through process_order_legacy(), tier 1          14      37        27     57.8%   112
  core, same assertions on the invoice            14      47        17     73.4%     0
  core, asserting on each decision                14      44        20     68.8%     0
  Row 1 against row 2 is the lesson: +15.6%, from reachability alone. Row 2
  surviving the legacy suite, killed by the parity suite: 4
    round_money: Eq -> NotEq
    round_money: Gt -> GtE
    round_money: Lt -> LtE
    round_money: const 0 -> 1

  Row 3 is the surprise, and it went the other way: -4.7%. Fourteen tests
  aimed at single decisions killed FEWER mutants than fourteen driving the
  whole core, because every end-to-end test executes every rule.

  surviving all three suites: 14. Of those, 7 produce identical output on
  a dense sweep of their own inputs -- EQUIVALENT MUTANTS, which no test of
  any design can kill.

== 7 · THE PRICE OF INDIRECTION: WHEN NOT TO ABSTRACT ==
  design                                      lines  names  hops  unblocked            output
  format_receipt_line(name, qty, minor)           2      1     1          0  widget x2 123.45
  ReceiptFormatter + CurrencyPolicy + Port       13      3     3          0  widget x2 123.45
  Same answer. +11 lines, +2 names to learn, +2 hops from the call site
  to the arithmetic, and 0 behaviours unblocked -- because none were blocked.

== 8 · LEGACY CODE: PIN THE BEHAVIOUR FIRST, THEN CUT ==
  outputs of the legacy function, recorded                 120
  refactored version replayed, outputs identical           120
  cases flagging one off-by-one in the clamp                 4  (3.3%)
  corpus size        cases flagging the regression   caught?
  10                                             0        NO
  20                                             0        NO
  40                                             1       yes
  80                                             3       yes
  120                                            4       yes

==========================================================================
SUMMARY · the same rules, the same tests, the inputs made reachable
  one pricing test                     11 setup lines, 4 doubles, 8 I/O ops -> 2 lines, 0, 0
  behaviours reachable at all          legacy 15/24 unpatched, 20/24 patched -> core 24/24
  the rounding branch at rate 1.08     0 of 2000000 amounts reach it -> at 1.125 it decides 12.5%
  the clamp branch, tier 0             reachable on 7 of 365 days -> core: on demand, always
  mutation kill rate, 14 tests each   legacy 57.8% -> 73.4% same assertions -> 68.8% finer ones
  seam surviving 3 no-op refactors     parameter 3/3 -> module global 1/3, call list 0/3
  behaviour preserved                  240/240 cases identical; characterization caught 4/120
  indirection with nothing to unblock  +11 lines, 0 behaviours unblocked -- do not do this
==========================================================================
```

Three things in that output are worth more than the headline.

**Section 4's `240/240` and section 5's `15/24` have to be read together.** The refactor is provably behaviour-preserving on every case the legacy version can be driven into — and that set is 15 of the 24 branches. The equivalence evidence is strongest exactly where it matters least, and absent exactly where the bugs were hiding. This is not a flaw in the method; it is the reason the refactor is worth doing.

**Section 6's row 3 contradicts the intuition the rest of the lesson builds.** Finer-grained tests scored *lower*. Reported as measured, because the alternative is to quietly drop the row that disagreed.

**Section 7's `0` in the `unblocked` column is the load-bearing zero.** Every other measurement in this lesson says abstraction pays. That one says it does not, on a function whose inputs were never hidden — and it is the same technique, applied by the same person, in the same file.

## Use It

**FastAPI's `Depends` is the cleanest dependency-injection story in the Python ecosystem**, and once you have read section 3 you can see why: it is a default argument the framework evaluates. Nothing more.

```python
# deps.py — one function per dependency. Each is just a value provider.
from datetime import datetime, timezone
from fastapi import Depends, FastAPI
from typing import Annotated, Protocol

def get_clock():                       # the value, not a mock of the value
    return lambda: datetime.now(timezone.utc)

def get_repo(settings: Annotated[Settings, Depends(get_settings)]):
    return SqliteOrderRepository(settings.db_path)

app = FastAPI()

@app.post("/orders/{order_id}/process")
def process(order_id: int,
            repo: Annotated[OrderRepository, Depends(get_repo)],
            clock: Annotated[Clock, Depends(get_clock)]):
    return process_order(order_id, Deps(repo=repo, clock=clock, ...))
```

The payoff is `dependency_overrides`, a plain dict on the app object. In a test you replace the *provider*, not the module:

```python
# conftest.py
@pytest.fixture
def client():
    app.dependency_overrides[get_clock] = lambda: (lambda: FIXED_INSTANT)
    app.dependency_overrides[get_repo] = lambda: InMemoryOrderRepository()
    yield TestClient(app)
    app.dependency_overrides.clear()          # <- forget this and tests leak
```

Four things bite here, in order of how often they bite:

- **`dependency_overrides` is global mutable state on the app.** Always clear it in fixture teardown. A leaked override is a test that passes alone and fails in a suite — and passes again when re-run, which is the exact signature [Flaky Tests](../09-flaky-tests/) teaches you to distrust.
- **The key is the function object, not its name.** If you `from .deps import get_clock` in two modules you still get one object, so this works — but override the function that the *route* actually depends on, not a lookalike.
- **`Depends` resolves per request and caches within a request** by default. `Depends(f, use_cache=False)` if you genuinely need two instances.
- **`yield` dependencies run teardown after the response.** Useful for a session; a trap if your test asserts on state the teardown has already rolled back.

**`typing.Protocol` (PEP 544) is how you write a port without an inheritance tree.** The adapter does not import the protocol, does not subclass it, and does not register:

```python
class OrderRepository(Protocol):
    def load(self, order_id: int) -> OrderInput: ...
    def save_invoice(self, oid: int, total: int, fee: int, status: str) -> None: ...

class SqliteOrderRepository:      # note: no base class, no import of the port
    def load(self, order_id: int) -> OrderInput: ...
    def save_invoice(self, oid: int, total: int, fee: int, status: str) -> None: ...
```

The type checker verifies the shape structurally at the call site. Two notes: add `@runtime_checkable` only if you truly need `isinstance`, and know that it checks method *names* only, not signatures — it will happily accept an object whose `load` takes the wrong arguments. And a `Protocol` with one implementation and no test double is a synonym; delete it.

**`functools.partial` is dependency injection for functions**, and it is underused. `partial(price_order, fx=SANDBOX_FX)` produces a function with one fewer input, no class and no framework.

**pytest fixtures are the injection point for everything else.** Prefer building the object in a fixture and passing it, over `monkeypatch`:

```text
# pytest.ini
[pytest]
addopts = -q --strict-markers --strict-config
```

- **`monkeypatch` over `unittest.mock.patch`** when you must patch: it undoes itself at test teardown, which `patch` only does as a context manager or decorator.
- **`autospec=True` if you patch at all** — [Test Doubles](../04-test-doubles/) measures what a bare `Mock()` swallows. A patched name with no spec accepts every call you make and every attribute you invent.
- **The anti-pattern that makes all of this impossible: the module-level singleton.** `GATEWAY = StripeGateway(os.environ["KEY"])` at import time means the object is constructed before any test can intervene, it is shared across every test in the process, and the only seam left is the module-global rebind, which survived 1 of 3 refactors. Build it in a factory; call the factory from a `Depends`.

**What to actually pick.** In order, and stop as soon as the problem is solved:

1. **Pass the value as a parameter.** Free, survives every refactor, needs no library. This solves the clock, the RNG, the FX rate and most configuration.
2. **Constructor-inject the collaborators** — repository, gateway, mailer — into a small `Deps` dataclass, and type the fields with `Protocol` ports.
3. **Use `Depends` + `dependency_overrides`** at the HTTP boundary, because that is where the framework owns construction and you do not.
4. **Reach for `patch`/`monkeypatch` only for code you cannot change** — third-party imports, a library's module-level client. Treat every use as a note that a seam is missing, and write the characterization corpus before you remove it.

And measure the thing this lesson measured, on your own code, before you argue about it: pick one function, count what it reads that the caller cannot choose, and write down the number.

## Think about it

1. The rounding branch was unreachable at rate `27/25` and reachable 12.5% of the time at `9/8`. Your integration environment pins every third-party sandbox to fixed responses for determinism. Name two other classes of input that pinning could be making arithmetically unreachable in your own system, and describe how you would detect it without already knowing the answer.
2. Tier 1 recovered 5 branches for the price of 4 doubles, and simultaneously killed `window.timeout`. Given that freezing the clock both unblocks and blocks, write the rule you would give a team for when to freeze, when to control, and when to do neither — and say which measurement in this lesson justifies each clause.
3. The `side_effect` call-list seam survived 0 of 3 behaviour-preserving refactors, and it was the only seam that could reach `window.timeout` without changing the code. Argue both sides: when is a test coupled to call count worth writing anyway, and what would you have to write down alongside it?
4. Row 3 of the mutation table says one-test-per-decision detected 4.7 points *worse* than end-to-end core tests at the same suite size. Reconcile that with the failure-localisation argument for small tests. At what suite size or what codebase shape would you expect the sign to flip, and how would you check?
5. The characterization corpus caught the regression on 4 of 120 cases and 0 of 20. You are about to refactor a legacy function whose rare branches you do not yet know. Describe a procedure for choosing the corpus that does not require already knowing which inputs are rare — and state what your procedure still cannot cover.

## Key takeaways

- **"Hard to test" is a measurable design defect, not a complaint about testing.** `process_order_legacy()` takes **1 parameter and makes 10 unparameterised reads of the world** — 5 clock reads, a connection, 2 gateway calls, a mailer, a module-level log. Every other number in this lesson follows from that ratio.
- **The cost shows up per test, forever.** One assertion about one pricing rule costs **11 setup lines, 4 substituted collaborators and 8 real I/O operations** through the legacy function, against **2 lines, 0 doubles and 0 I/O** against the core. Both answer **486000**.
- **The real damage is reachability, and no coverage tool reports it.** Legacy reaches **15 of 24** branches unpatched and **20 of 24** with a frozen clock and a faked gateway; the core reaches **24 of 24** with nothing patched. A coverage report calls the missing 4 "not run", which reads as untested when the truth is *untestable*.
- **A fixed collaborator can delete a region of the input space.** At the sandbox rate 1.08 = **27/25**, **0 of 2,000,000** amounts can produce the rounding tie — an odd denominator never lands on 1/2. At a live rate of 1.125 = **9/8**, **250,000 of 2,000,000 (12.5%)** do, and the two modes return **4 and 5**.
- **Hidden inputs make your suite's power a property of the calendar.** With dates derived from `datetime.now()`, the clamping branch is reachable on **7 of 365 days** and the leap anniversary on **exactly one: 2024-02-29** — and nothing records which day CI ran.
- **Freezing the clock trades one blind spot for another.** The legacy function reads the clock **5 times**; frozen, all 5 agree, so the elapsed-time branch is dead at tier 0 *and* tier 1. Reaching it needs a call-list double, and that seam survived **0 of 3** behaviour-preserving refactors against **3 of 3** for a parameter.
- **Testable design catches more bugs per test written, and the gap is pure design.** Fourteen tests, same names, same assertions on the same invoice: **57.8% kill rate through the legacy function (112 I/O ops) versus 73.4% against the core (0)** — **+15.6 points** bought only by being allowed to choose the FX rate and the instant.
- **Granularity is a trade, not an improvement.** Fourteen tests aimed at single decisions killed **68.8%** — **4.7 points worse** than fourteen end-to-end core tests, because each end-to-end test exercises every rule. And **14 mutants survived all three suites, 7 of them provably equivalent**: 100% is a category error, not a target.
- **Indirection with nothing to unblock is pure cost, and the critics are right about it.** Applying the same refactor to a function with no hidden inputs added **+11 lines, +2 names and +2 call hops for 0 behaviours unblocked**. Inject hidden inputs; do not inject arithmetic.
- **For legacy code: record, extract, test, then delete the recording.** A 120-case characterization corpus caught an accidental clamp change on **4 of 120 cases** — but **0 of 20**, so a small corpus ships the regression. Kept forever, the recording pins the bugs in place along with the behaviour.

Next: [Integration Testing Against a Real Database](../06-integration-testing-real-database/) — the core is now pure and the I/O has been pushed into a shell you have never actually run against the real thing, which is where the next class of bug lives.
