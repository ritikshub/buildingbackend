# Determinism: Time, Randomness, IDs & Order

> A test that reads `datetime.now()` is not one test. Measured here: the same subscription-renewal test, evaluated at every one of the **8,784 hours of 2024**, computes the wrong answer at **1,454 of them — 16.6%** — and CI picks which hour you get. Two more results worth the click. A **frozen clock cannot test a timeout**: freezing reached 4 of 6 behaviours, and the two it missed were not slow, they were unreachable. And shuffling a 200-test suite finds *some* order dependency in **3 runs** at 99% confidence — but finding the rarest of the three takes **182 shuffled runs**, which at one CI run per merge is weeks.

**Type:** Build
**Languages:** Python
**Prerequisites:** [Designing for Testability](../05-designing-for-testability/), [Test Data & Fixtures](../07-test-data-and-fixtures/)
**Time:** ~70 minutes

## The Problem

The board has three cards on it and they have been there for eleven days.

**Card one: "checkout suite red overnight, green by standup."** It fails at 23:00 UTC. Not near 23:00 — *at* 23:00, on the nightly cron, every night, and never on the 09:40 run. Someone has already re-run it enough times to be sure. The failing assertion is `test_renewal_lands_on_the_same_day_of_month`, and it says a subscription created today renews on the same day next month. The build servers are in Frankfurt. At 23:00 UTC a Frankfurt wall clock reads **00:00 tomorrow**, so `date.today()` on the runner is a different day from the UTC day the code stored — and the test compares one to the other. Measured across the whole year, that property fails at **704 of 8,784 hours**, and **572 of those 704 failures are at 22:00 and 23:00 UTC**. It is not flaky. It is a 5%-of-the-day-wide hole that the nightly cron happens to sit exactly inside.

**Card two: "annual plans broke on 29 Feb."** One day, one traceback, `ValueError: day is out of range for month`, and a renewal batch that stopped halfway. The code did `renewal.replace(year=renewal.year + 1)` on a subscription that started **2024-02-29**. There is no 29 February in 2025. Nobody wrote a test for it because the test would have to have been written on, or about, a date that occurs once every 1,461 days. The correct answer — the one the program in this lesson computes — is **2025-02-28**, but only because *someone decided that*. Clamping is a product decision. If your code does not make it, `ValueError` makes it for you.

**Card three, the one nobody wants: "`test_cache_stays_small` fails sometimes."** No pattern. Roughly **once every 40 runs**. It has been re-run, quarantined, un-quarantined, and re-run. The last comment is "can't reproduce, closing". It reproduces perfectly — you just have to run the suite in an order where all 39 of the tests that leak one cache entry each happen to sit before it, which a random permutation does exactly **1 time in 40**.

**16:20 — the three cards are the same card.** All three tests read a value the test did not set. The first reads the runner's timezone. The second reads the calendar. The third reads how many other tests ran first. None of these is an argument. None appears in the test body. None is visible in the diff, the traceback, or the test name. Every one of them is an input, and every one of them is being chosen by something other than you: the cron schedule, the date, the plugin that shuffles collection order.

The word for this is **determinism** — same input, same result, every run, every machine, every order — and the reason it is worth a lesson of its own is that the second half of the definition is where all the bugs are. Nobody ships a test that gives two answers for the same input. People ship tests every day whose inputs they cannot enumerate.

> **A test that reads the wall clock is not one test. It is 8,784 tests, and CI decides which one runs.**

## The Concept

### What determinism actually means, and every hidden input you have

A function is **deterministic** when its output is a function of its arguments. That is the whole definition, and the useful thing about phrasing it that way is that it turns "why is this test flaky" into a question you can answer by reading the code: *what does this function read that the caller did not give it?*

Everything on that list is a **hidden input** — an argument the test never passed, whose value is chosen by the machine, the moment, or the run. Take a six-line pricing function of the kind that exists in every codebase, and count them.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 452" width="100%" style="max-width:840px" role="img" aria-label="Two versions of the same pricing function. The top version is passed only the items and reads five further inputs on its own: the clock, the environment, a random number generator, set iteration order and a module-level counter. Run in six ordinary machine states it produces six different results. The bottom version takes all five as arguments; run in the same six machine states it produces one result. The takeaway is that determinism is a property of how much of the world a function is allowed to read, not of the code itself.">
  <defs>
    <marker id="p12-08-a1" markerWidth="9" markerHeight="9" refX="5.5" refY="3" orient="auto"><path d="M0,0 L6.5,3 L0,6 Z" fill="#3553ff"/></marker>
    <marker id="p12-08-a2" markerWidth="9" markerHeight="9" refX="5.5" refY="3" orient="auto"><path d="M0,0 L6.5,3 L0,6 Z" fill="#d64545"/></marker>
  </defs>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <text x="440" y="26" text-anchor="middle" font-size="14.5" font-weight="700" fill="currentColor">A hidden input is an argument the test never passed</text>
    <text x="440" y="45" text-anchor="middle" font-size="10" fill="currentColor" opacity="0.8">the same 6-line function, run in 6 ordinary machine states</text>

    <text x="30" y="72" font-size="11.5" font-weight="700" fill="#d64545">1 · the version everyone writes — 1 argument, 5 hidden inputs</text>

    <rect x="30" y="88" width="168" height="52" rx="8" fill="#3553ff" fill-opacity="0.12" stroke="#3553ff" stroke-width="1.8"/>
    <text x="114" y="108" text-anchor="middle" font-size="10.5" font-weight="700" fill="#3553ff">the test</text>
    <text x="114" y="126" text-anchor="middle" font-size="9" fill="currentColor" opacity="0.9">sets: items</text>
    <path d="M198 114 L 292 114" fill="none" stroke="#3553ff" stroke-width="1.8" marker-end="url(#p12-08-a1)"/>

    <rect x="298" y="82" width="182" height="64" rx="9" fill="#7c5cff" fill-opacity="0.13" stroke="#7c5cff" stroke-width="1.9"/>
    <text x="389" y="104" text-anchor="middle" font-size="10.5" font-weight="700" fill="#7c5cff">price_order(items)</text>
    <text x="389" y="122" text-anchor="middle" font-size="8.5" fill="currentColor" opacity="0.85">the code under test</text>
    <text x="389" y="136" text-anchor="middle" font-size="8.5" fill="currentColor" opacity="0.85">reads 5 more inputs by itself</text>

    <g fill="#d64545" fill-opacity="0.11" stroke="#d64545" stroke-width="1.4">
      <rect x="604" y="56" width="246" height="24" rx="6"/><rect x="604" y="84" width="246" height="24" rx="6"/><rect x="604" y="112" width="246" height="24" rx="6"/><rect x="604" y="140" width="246" height="24" rx="6"/><rect x="604" y="168" width="246" height="24" rx="6"/>
    </g>
    <g fill="none" stroke="#d64545" stroke-width="1.5" opacity="0.85">
      <path d="M480 108 C 540 100, 552 68, 600 68" marker-end="url(#p12-08-a2)"/>
      <path d="M480 111 C 540 106, 552 96, 600 96" marker-end="url(#p12-08-a2)"/>
      <path d="M480 114 L 600 124" marker-end="url(#p12-08-a2)"/>
      <path d="M480 117 C 540 122, 552 152, 600 152" marker-end="url(#p12-08-a2)"/>
      <path d="M480 120 C 540 128, 552 180, 600 180" marker-end="url(#p12-08-a2)"/>
    </g>
    <g fill="currentColor" font-size="9">
      <text x="614" y="72"><tspan font-weight="700" fill="#d64545">the clock</tspan><tspan opacity="0.85"> — the date rolls at midnight</tspan></text>
      <text x="614" y="100"><tspan font-weight="700" fill="#d64545">os.environ</tspan><tspan opacity="0.85"> — set on CI, not on your laptop</tspan></text>
      <text x="614" y="128"><tspan font-weight="700" fill="#d64545">random / uuid4()</tspan><tspan opacity="0.85"> — a fresh value/call</tspan></text>
      <text x="614" y="156"><tspan font-weight="700" fill="#d64545">set iteration order</tspan><tspan opacity="0.85"> — the hash seed</tspan></text>
      <text x="614" y="184"><tspan font-weight="700" fill="#d64545">a global counter</tspan><tspan opacity="0.85"> — how many ran first</tspan></text>
    </g>

    <rect x="298" y="202" width="552" height="30" rx="7" fill="#d64545" fill-opacity="0.10" stroke="#d64545" stroke-width="1.5"/>
    <text x="312" y="221" font-size="10.5" font-weight="700" fill="#d64545">6 machine states → 6 results</text>
    <text x="606" y="221" font-size="9" fill="currentColor" opacity="0.9">every one of those reads is correct</text>

    <path d="M30 252 L 850 252" fill="none" stroke="currentColor" stroke-width="1.2" opacity="0.3"/>

    <text x="30" y="274" font-size="11.5" font-weight="700" fill="#0fa07f">2 · the same arithmetic with every hidden input promoted to an argument</text>

    <rect x="30" y="290" width="168" height="70" rx="8" fill="#3553ff" fill-opacity="0.12" stroke="#3553ff" stroke-width="1.8"/>
    <text x="114" y="310" text-anchor="middle" font-size="10.5" font-weight="700" fill="#3553ff">the test</text>
    <text x="114" y="328" text-anchor="middle" font-size="8.5" fill="currentColor" opacity="0.9">sets: items, now, promo,</text>
    <text x="114" y="342" text-anchor="middle" font-size="8.5" fill="currentColor" opacity="0.9">order_id, seq, tags</text>
    <path d="M198 325 L 292 325" fill="none" stroke="#3553ff" stroke-width="1.8" marker-end="url(#p12-08-a1)"/>

    <rect x="298" y="293" width="182" height="64" rx="9" fill="#0fa07f" fill-opacity="0.13" stroke="#0fa07f" stroke-width="1.9"/>
    <text x="389" y="315" text-anchor="middle" font-size="10.5" font-weight="700" fill="#0fa07f">price_order(...)</text>
    <text x="389" y="333" text-anchor="middle" font-size="8.5" fill="currentColor" opacity="0.85">the same arithmetic,</text>
    <text x="389" y="347" text-anchor="middle" font-size="8.5" fill="currentColor" opacity="0.85">6 arguments, 0 hidden inputs</text>

    <rect x="604" y="293" width="246" height="64" rx="8" fill="#7f7f7f" fill-opacity="0.08" stroke="currentColor" stroke-opacity="0.4" stroke-width="1.4" stroke-dasharray="5 4"/>
    <text x="727" y="316" text-anchor="middle" font-size="9.5" font-weight="700" fill="currentColor" opacity="0.75">reads nothing else</text>
    <text x="727" y="333" text-anchor="middle" font-size="8.5" fill="currentColor" opacity="0.7">the clock, the RNG and the</text>
    <text x="727" y="346" text-anchor="middle" font-size="8.5" fill="currentColor" opacity="0.7">environment are now the caller's</text>
    <path d="M480 325 L 598 325" fill="none" stroke="currentColor" stroke-width="1.3" stroke-dasharray="4 4" opacity="0.4"/>

    <rect x="298" y="370" width="552" height="30" rx="7" fill="#0fa07f" fill-opacity="0.12" stroke="#0fa07f" stroke-width="1.5"/>
    <text x="312" y="389" font-size="10.5" font-weight="700" fill="#0fa07f">6 machine states → 1 result</text>
    <text x="606" y="389" font-size="9" fill="currentColor" opacity="0.9">now an assertion has something to name</text>

    <text x="440" y="428" text-anchor="middle" font-size="11.5" font-weight="700" fill="currentColor">Determinism is not a property of the code. It is a property of how much of the world the code may read.</text>
    <text x="440" y="446" text-anchor="middle" font-size="9.5" fill="currentColor" opacity="0.85">Injection did not make the function correct — it made the output a function of the arguments.</text>
  </g>
</svg>
```

Five, in six lines: the clock, the environment, an RNG, set iteration order, and a process-global counter. The program runs that function in six ordinary machine states — two times of day, `PROMO_RATE` set or unset, different hash seeds — and gets **6 different results out of 6**. Promote all five to arguments and the same six states produce **1 result**.

Read the middle box of that diagram carefully, because the temptation is to call the hidden version buggy and it is not. `datetime.now()` returns the correct time. `os.environ` returns what is actually set. `uuid4()` returns a genuinely random identifier. **Every one of those reads is correct.** What is wrong is that the test cannot see them, cannot set them, and therefore cannot assert about them — so the test is not asserting about your function, it is asserting about your function *on this machine, at this moment, in this order*.

Five is not the whole list, it is just the five that fit in six lines. The full catalogue for a backend test is worth having written down somewhere, because every entry is a real bug someone has shipped: **the clock** and the **timezone** the process resolved it in; **`random`, `uuid4()` and `secrets`**; **`os.environ`**, including the variables your framework reads that you have never heard of; **set and dict iteration order** and the hash seed behind it; **filesystem order** — `os.listdir()` and `glob` return entries in directory order, which is not sorted and differs between ext4, APFS and an overlay filesystem in a container; **the database**, which has its own clock, its own sequences and its own idea of row order; **locale**, which decides how `sorted()` orders strings and how numbers format; **the host**, meaning CPU count, hostname and the number of workers derived from them; **the network**, meaning DNS, latency and whether a service answered; **process-global state**, meaning module-level caches, singletons and anything a previous test mutated; and **the scheduler**, which the last section of this lesson shows you cannot inject at all.

The useful discipline is not to eliminate all of them — it is to be able to *name* which ones a given test reads. A test whose hidden inputs you can enumerate is a test you can debug at 03:00. A test whose hidden inputs you cannot enumerate is the one that gets re-run.

That reframing is the whole lesson, and it has a practical consequence: injection did not make the function correct. It made the output a function of the arguments, which is the only thing an assertion has ever been able to talk about. [Designing for Testability](../05-designing-for-testability/) built the seams; this lesson is the catalogue of what has to go through them.

### The clock: freezing is not controlling

The clock is the hidden input everyone finds first, and the fix everyone reaches for is `freezegun`: pin `now()` to a constant and the date-dependent test stops moving. That works, and it is not enough, and the gap between "frozen" and "controlled" is where a specific class of test quietly disappears.

The program builds three clocks behind one two-method port — `now()` and `sleep()` — and runs six behaviours of a 300-second TTL cache, a four-attempt exponential backoff and a 30-second timeout against each.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 452" width="100%" style="max-width:840px" role="img" aria-label="A six-by-three matrix comparing a real clock, a frozen clock and a controllable clock against six behaviours of a TTL cache, a retry with backoff and a timeout. The real clock reaches all six but bills 937 seconds of sleeping. The frozen clock reaches only four: the retry backoff schedule and the thirty-second timeout are unreachable, because a frozen clock cannot let time pass inside a single call. The controllable clock reaches all six for zero seconds. Below, the reason is drawn as two timelines: freezing gives one instant that the test may move between calls, while controlling gives the test the whole time axis.">
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <text x="440" y="26" text-anchor="middle" font-size="14.5" font-weight="700" fill="currentColor">Freezing a clock is not the same as controlling one</text>
    <text x="440" y="45" text-anchor="middle" font-size="10" fill="currentColor" opacity="0.8">a 300 s TTL cache + a 4-attempt backoff + a 30 s timeout — 6 behaviours, 3 strategies</text>

    <g fill="currentColor" font-size="8.5" font-weight="700" opacity="0.62">
      <text x="30" y="72">BEHAVIOUR THE TEST WANTS TO REACH</text><text x="470" y="72">REAL CLOCK</text><text x="610" y="72">FROZEN</text><text x="740" y="72">CONTROLLABLE</text>
    </g>
    <path d="M26 78 L 854 78" fill="none" stroke="currentColor" stroke-width="1.3" opacity="0.45"/>
    <g fill="none" stroke="currentColor" stroke-width="1" opacity="0.2">
      <path d="M26 104 L 854 104"/><path d="M26 130 L 854 130"/><path d="M26 156 L 854 156"/><path d="M26 182 L 854 182"/><path d="M26 208 L 854 208"/>
    </g>
    <path d="M26 234 L 854 234" fill="none" stroke="currentColor" stroke-width="1.3" opacity="0.45"/>

    <g fill="currentColor" font-size="9.5">
      <text x="30" y="96">B1 &#8195;a fresh key is a cache hit</text>
      <text x="30" y="122">B2 &#8195;still a hit 1 s before the TTL</text>
      <text x="30" y="148">B3 &#8195;a miss exactly AT the 300 s boundary</text>
      <text x="30" y="174">B4 &#8195;a miss 1 s after the TTL</text>
      <text x="30" y="200">B5 &#8195;the retry backoff emits 0 / 1 / 3 / 7 s</text>
      <text x="30" y="226">B6 &#8195;wait_for() gives up after 30 s</text>
    </g>

    <g font-size="9.5" font-weight="700">
      <text x="470" y="96" fill="#0fa07f">pass</text><text x="610" y="96" fill="#0fa07f">pass</text><text x="740" y="96" fill="#0fa07f">pass</text>
      <text x="470" y="122" fill="#0fa07f">pass</text><text x="610" y="122" fill="#0fa07f">pass</text><text x="740" y="122" fill="#0fa07f">pass</text>
      <text x="470" y="148" fill="#0fa07f">pass</text><text x="610" y="148" fill="#0fa07f">pass</text><text x="740" y="148" fill="#0fa07f">pass</text>
      <text x="470" y="174" fill="#0fa07f">pass</text><text x="610" y="174" fill="#0fa07f">pass</text><text x="740" y="174" fill="#0fa07f">pass</text>
      <text x="470" y="200" fill="#0fa07f">pass</text><text x="610" y="200" fill="#d64545">UNREACHABLE</text><text x="740" y="200" fill="#0fa07f">pass</text>
      <text x="470" y="226" fill="#0fa07f">pass</text><text x="610" y="226" fill="#d64545">UNREACHABLE</text><text x="740" y="226" fill="#0fa07f">pass</text>
    </g>
    <rect x="602" y="186" width="112" height="48" rx="5" fill="#d64545" fill-opacity="0.10" stroke="#d64545" stroke-width="1.6"/>

    <g font-size="10" font-weight="700">
      <text x="30" y="254" fill="currentColor">reachable</text>
      <text x="470" y="254" fill="#0fa07f">6 / 6</text><text x="610" y="254" fill="#e0930f">4 / 6</text><text x="740" y="254" fill="#0fa07f">6 / 6</text>
      <text x="30" y="272" fill="currentColor">wall-clock cost of the run</text>
      <text x="470" y="272" fill="#d64545">937 s = 15.6 min</text><text x="610" y="272" fill="#0fa07f">0 s</text><text x="740" y="272" fill="#0fa07f">0 s</text>
    </g>

    <path d="M26 288 L 854 288" fill="none" stroke="currentColor" stroke-width="1.2" opacity="0.3"/>

    <text x="30" y="310" font-size="10" font-weight="700" fill="#e0930f">frozen — one instant, movable only BETWEEN calls</text>
    <path d="M30 336 L 400 336" fill="none" stroke="currentColor" stroke-width="1.4" opacity="0.55"/>
    <g fill="#e0930f"><circle cx="120" cy="336" r="5"/></g>
    <text x="120" y="326" text-anchor="middle" font-size="8.5" font-weight="700" fill="#e0930f">now()</text>
    <text x="120" y="354" text-anchor="middle" font-size="8" fill="currentColor" opacity="0.8">a constant</text>
    <g fill="none" stroke="#e0930f" stroke-width="1.5" stroke-dasharray="4 3"><path d="M132 344 C 190 362, 240 362, 286 344"/></g>
    <text x="209" y="374" text-anchor="middle" font-size="8" fill="currentColor" opacity="0.8">re-freeze between calls</text>
    <text x="30" y="398" font-size="9.5" font-weight="700" fill="#d64545">sleep(30) inside the call advances 0 s. The deadline never arrives.</text>

    <text x="470" y="310" font-size="10" font-weight="700" fill="#0fa07f">controllable — the test owns the whole axis</text>
    <path d="M470 336 L 850 336" fill="none" stroke="currentColor" stroke-width="1.4" opacity="0.55"/>
    <g fill="#0fa07f"><circle cx="500" cy="336" r="4"/><circle cx="570" cy="336" r="4"/><circle cx="640" cy="336" r="4"/><circle cx="710" cy="336" r="4"/><circle cx="820" cy="336" r="4"/></g>
    <g fill="none" stroke="#0fa07f" stroke-width="1.6">
      <path d="M504 336 L 566 336"/><path d="M574 336 L 636 336"/><path d="M644 336 L 706 336"/><path d="M714 336 L 816 336"/>
    </g>
    <g fill="currentColor" font-size="8" text-anchor="middle" opacity="0.85">
      <text x="535" y="352">+1 s</text><text x="605" y="352">+2 s</text><text x="675" y="352">+4 s</text><text x="765" y="352">advance(30)</text>
    </g>
    <text x="470" y="398" font-size="9.5" font-weight="700" fill="#0fa07f">sleep(30) inside the call costs 0 real ms and 30 logical s.</text>

    <text x="440" y="428" text-anchor="middle" font-size="11.5" font-weight="700" fill="currentColor">A frozen clock answers "what time is it". A timeout asks "how much time has passed".</text>
    <text x="440" y="446" text-anchor="middle" font-size="9.5" fill="currentColor" opacity="0.85">Under a frozen clock wait_for() returned False having advanced 0.0 s — the right answer for the wrong reason.</text>
  </g>
</svg>
```

A **frozen** clock answers `now()` with a constant. You may re-freeze it at another instant between calls, so every "what is true at time T" assertion is available: B2, B3 and B4 all pass, including the exact-boundary case at 300 s that a real clock can only hit by luck.

What a frozen clock cannot do is let time pass **inside one call**. B5 asks the retry loop what offsets its four attempts landed at, and the loop reads the clock between its own sleeps. B6 asks whether `wait_for` gives up after 30 seconds, and `wait_for` compares `now()` against a deadline it computed itself. Under a frozen clock those are not slow — they are **unreachable**, `4 of 6`. And the failure is worse than a failure: `wait_for` under a frozen clock returned `False`, which is the answer the test wanted, having advanced **0.0 s**. It never reached a deadline; it exhausted its iteration guard. That test passes forever and would pass just as happily if you deleted the timeout entirely.

The **controllable** clock is one extra method — `advance(seconds)`, and `sleep()` that actually moves the same counter — and it reaches `6 of 6`. The **real** clock also reaches 6 of 6, at a measured bill of **937 seconds = 15.6 minutes of sleeping for six assertions**. That number is why "just use real time and a shorter TTL" fails: shortening the TTL to make the test fast is changing the code to suit the test, and you are then testing a 0.3-second cache you do not run in production.

The rule that falls out: **freeze when you are asserting about an instant; control when you are asserting about a duration.** Timeouts, retries, backoff schedules, TTL sweeps, rate-limiter windows, lease renewals and circuit-breaker half-open transitions are all durations.

### Timezones, DST and the 23:00 failure

Now the card-one bug, measured properly. The program implements a monthly subscription renewal twice. The correct version adds one calendar month on the **UTC** calendar and keeps the UTC time of day. The naive version does what `datetime.now()` plus `date` arithmetic gives you: it converts to the server's wall clock, adds a month on the **local** calendar, and converts back.

The server is in Berlin — UTC+1 in winter, UTC+2 in summer, transitions at 01:00 UTC on the last Sunday of March and of October (Directive 2000/84/EC). The timezone rules are implemented by hand in about twenty lines so the program needs no `tzdata` and the rule is visible rather than magic. Then every one of the 8,784 hours of 2024 is used as a subscription start.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 486" width="100%" style="max-width:840px" role="img" aria-label="Measured results for a subscription renewal implemented against a Berlin server's wall clock, evaluated at every one of the 8784 hours of 2024. On the left, a histogram of the hours at which the same-day-of-month property fails: 361 failures at 23:00 UTC, 211 at 22:00 UTC, and only 132 spread across all twenty-two other hours combined, because at 22:00 and 23:00 UTC the Berlin calendar has already rolled over to tomorrow. On the right, the renewal instant itself is wrong for 1454 of the 8784 hours, 16.6 percent: 1438 are an hour out because the renewal crosses a daylight-saving change and 16 land on the wrong day because the two calendars clamp a short month differently. Below, the two wall-clock times that are not instants at all: 02:30 on 31 March maps to no UTC instant, and 02:30 on 27 October maps to two.">
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <text x="440" y="26" text-anchor="middle" font-size="14.5" font-weight="700" fill="currentColor">"It only fails at 23:00" is not a coincidence. It is an offset.</text>
    <text x="440" y="45" text-anchor="middle" font-size="10" fill="currentColor" opacity="0.8">every one of the 8,784 hours of 2024 as a subscription start, Berlin server (UTC+1 / UTC+2)</text>

    <text x="40" y="72" font-size="11" font-weight="700" fill="#3553ff">test_renewal_lands_on_the_same_day_of_month()</text>
    <text x="40" y="88" font-size="8.5" fill="currentColor" opacity="0.8">by the UTC hour at which CI happened to run it</text>

    <g fill="none" stroke="currentColor" stroke-width="1.3">
      <path d="M56 262 L 546 262"/><path d="M56 262 L 56 128"/>
    </g>
    <g fill="none" stroke="currentColor" stroke-width="1" opacity="0.4">
      <path d="M51 262 L 56 262"/><path d="M51 195 L 56 195"/><path d="M51 128 L 56 128"/>
    </g>
    <g fill="currentColor" font-size="8" text-anchor="end" opacity="0.7">
      <text x="47" y="265">0</text><text x="47" y="198">180</text><text x="47" y="131">361</text>
    </g>

    <g fill="#7f7f7f" fill-opacity="0.40" stroke="#7f7f7f" stroke-width="0.9">
      <rect x="60" y="260" width="16" height="2"/><rect x="80" y="260" width="16" height="2"/><rect x="100" y="260" width="16" height="2"/><rect x="120" y="260" width="16" height="2"/><rect x="140" y="260" width="16" height="2"/><rect x="160" y="260" width="16" height="2"/><rect x="180" y="260" width="16" height="2"/><rect x="200" y="260" width="16" height="2"/><rect x="220" y="260" width="16" height="2"/><rect x="240" y="260" width="16" height="2"/><rect x="260" y="260" width="16" height="2"/><rect x="280" y="260" width="16" height="2"/>
      <rect x="300" y="260" width="16" height="2"/><rect x="320" y="260" width="16" height="2"/><rect x="340" y="260" width="16" height="2"/><rect x="360" y="260" width="16" height="2"/><rect x="380" y="260" width="16" height="2"/><rect x="400" y="260" width="16" height="2"/><rect x="420" y="260" width="16" height="2"/><rect x="440" y="260" width="16" height="2"/><rect x="460" y="260" width="16" height="2"/><rect x="480" y="260" width="16" height="2"/>
    </g>
    <rect x="500" y="192" width="16" height="70" fill="#e0930f" fill-opacity="0.45" stroke="#e0930f" stroke-width="1.4"/>
    <rect x="520" y="142" width="16" height="120" fill="#d64545" fill-opacity="0.45" stroke="#d64545" stroke-width="1.4"/>

    <text x="528" y="136" text-anchor="middle" font-size="9.5" font-weight="700" fill="#d64545">361</text>
    <text x="508" y="186" text-anchor="middle" font-size="9.5" font-weight="700" fill="#e0930f">211</text>
    <path d="M60 254 L 496 254" fill="none" stroke="currentColor" stroke-width="1" stroke-dasharray="3 3" opacity="0.45"/>
    <text x="278" y="249" text-anchor="middle" font-size="8.5" fill="currentColor" opacity="0.8">132 failures across all 22 of these hours combined</text>

    <g fill="currentColor" font-size="8" text-anchor="middle" opacity="0.7">
      <text x="68" y="276">00</text><text x="188" y="276">06</text><text x="308" y="276">12</text><text x="428" y="276">18</text><text x="508" y="276" font-weight="700" fill="#e0930f">22</text><text x="528" y="276" font-weight="700" fill="#d64545">23</text>
    </g>
    <text x="301" y="292" text-anchor="middle" font-size="8.5" fill="currentColor" opacity="0.75">UTC hour at which the test ran</text>
    <text x="301" y="310" text-anchor="middle" font-size="9.5" font-weight="700" fill="#3553ff">704 of 8,784 hours fail — 8.0% — and 572 of them are these two bars</text>

    <path d="M566 62 L 566 320" fill="none" stroke="currentColor" stroke-width="1.2" opacity="0.28"/>

    <text x="586" y="72" font-size="11" font-weight="700" fill="#7c5cff">the renewal INSTANT, wall clock vs UTC</text>

    <rect x="586" y="86" width="262" height="26" rx="6" fill="#d64545" fill-opacity="0.13" stroke="#d64545" stroke-width="1.5"/>
    <text x="596" y="104" font-size="10" font-weight="700" fill="#d64545">1,454 of 8,784 wrong &#8195; 16.6%</text>

    <g fill="currentColor" font-size="9">
      <text x="596" y="134"><tspan font-weight="700" fill="#e0930f">1,438</tspan><tspan opacity="0.9">  an hour out — the renewal</tspan></text>
      <text x="596" y="147" opacity="0.9">&#8195;&#8195;&#8195;&#8195;crosses a DST change</text>
      <text x="596" y="169"><tspan font-weight="700" fill="#d64545">16</tspan><tspan opacity="0.9">  a whole DAY out — the two</tspan></text>
      <text x="596" y="182" opacity="0.9">&#8195;&#8195;&#8195;calendars clamp a short month</text>
      <text x="596" y="195" opacity="0.9">&#8195;&#8195;&#8195;differently</text>
      <text x="596" y="217"><tspan font-weight="700" fill="#7c5cff">1</tspan><tspan opacity="0.9">  lands in the hour that happens</tspan></text>
      <text x="596" y="230" opacity="0.9">&#8195;&#8195;twice; fold=0 picks for you</text>
    </g>

    <rect x="586" y="246" width="262" height="62" rx="7" fill="#7f7f7f" fill-opacity="0.07" stroke="currentColor" stroke-opacity="0.35" stroke-width="1.3"/>
    <text x="596" y="264" font-size="8.5" font-weight="700" fill="currentColor" opacity="0.7">2025, THE NON-LEAP YEAR</text>
    <text x="596" y="280" font-size="9" fill="currentColor" opacity="0.9">1,433 of 8,760 wrong — 16.4%</text>
    <text x="596" y="296" font-size="9" fill="currentColor" opacity="0.9">a 2024-02-29 annual renewal → 2025-02-28</text>

    <path d="M32 330 L 848 330" fill="none" stroke="currentColor" stroke-width="1.2" opacity="0.3"/>

    <text x="40" y="352" font-size="11" font-weight="700" fill="currentColor">and the two wall-clock readings that are not instants at all</text>

    <rect x="40" y="364" width="392" height="58" rx="8" fill="#d64545" fill-opacity="0.10" stroke="#d64545" stroke-width="1.6"/>
    <text x="54" y="384" font-size="10" font-weight="700" fill="#d64545">Berlin 2024-03-31 02:30 &#8195;spring forward</text>
    <text x="54" y="402" font-size="9.5" fill="currentColor" opacity="0.92">→ 0 UTC instants. This wall time never happens.</text>
    <text x="54" y="416" font-size="8.5" fill="currentColor" opacity="0.75">a renewal scheduled here has no time to fire at</text>

    <rect x="452" y="364" width="396" height="58" rx="8" fill="#e0930f" fill-opacity="0.11" stroke="#e0930f" stroke-width="1.6"/>
    <text x="466" y="384" font-size="10" font-weight="700" fill="#e0930f">Berlin 2024-10-27 02:30 &#8195;autumn back</text>
    <text x="466" y="402" font-size="9.5" fill="currentColor" opacity="0.92">→ 2 UTC instants: 00:30Z and 01:30Z.</text>
    <text x="466" y="416" font-size="8.5" fill="currentColor" opacity="0.75">a nightly job here runs twice, or bills twice</text>

    <text x="440" y="450" text-anchor="middle" font-size="11.5" font-weight="700" fill="currentColor">A test that reads the wall clock is not one test. It is 8,784 tests, and CI picks which one runs.</text>
    <text x="440" y="470" text-anchor="middle" font-size="9.5" fill="currentColor" opacity="0.85">Fixing the timezone fixes 1,438 of the 1,454. Fixing the calendar arithmetic fixes the other 16.</text>
  </g>
</svg>
```

**1,454 of 8,784 renewals — 16.6% — land on the wrong instant**, and the breakdown is the interesting part because the two causes want different fixes.

**1,438 are exactly one hour out.** The subscription starts under one UTC offset and renews under the other, so "the same wall-clock time next month" is a different instant. This is the big one, and it is a pure timezone bug: the fix is to do the arithmetic in UTC and never round-trip through a wall clock.

**16 land on a different day entirely** — and these survive the timezone fix, because they are a *calendar* bug. When the local date sits in a different month from the UTC date (Berlin at 23:00 UTC is already tomorrow), "add one month" runs against a different starting month, and the two clamps disagree. The first instance the program finds is a start at **2024-01-29 23:00Z**, which is Berlin 2024-01-30 00:00: the UTC-correct renewal is **2024-02-29 23:00Z** and the wall-based one is **2024-02-28 23:00Z**, a full day apart.

Then the two wall-clock readings that are not instants at all. Berlin **2024-03-31 02:30** maps to **0** UTC instants — the clocks jump 02:00 → 03:00 and that wall time never happens, so a renewal scheduled there has no moment to fire at. Berlin **2024-10-27 02:30** maps to **2**, at 00:30Z and 01:30Z — a nightly job scheduled there runs twice, and if it charges cards, it charges twice. Python's `fold` attribute (PEP 495) exists precisely to name which of the two you meant, and if you never set it, `fold=0` picks the first for you.

The histogram is card one. `test_renewal_lands_on_the_same_day_of_month` fails at **704 of 8,784 hours — 8.0%** — and **361 of those failures are at 23:00 UTC, 211 at 22:00, and 132 spread across all twenty-two other hours combined.** Two hours of the day carry 81% of the failures, because those are the hours at which Berlin's calendar has already rolled over. This is why the bug reads as "flaky at night" rather than "wrong": you are not sampling a random variable, you are sampling a step function, and the nightly cron sits on the step.

One more, because it is the leap-year card: an annual renewal started **2024-02-29** is due **2025-02-28**. Not because a library decided — because *the code* decided, explicitly, that a missing day clamps backwards. Rerun the whole matrix against 2025 and the shape holds (**1,433 of 8,760 wrong, 16.4%**), which tells you the bug is structural rather than a leap-year special case.

### Randomness: the seed you share is the seed you lose

Seeding an RNG is necessary and it is not sufficient. The failure mode is specific to parallel test execution and it is not intuitive: the problem is not that the workers are random, it is that they are **identical**.

Eight workers, each generating 500 email addresses with `random.randrange(0, 1_000_000)`:

```text
strategy                          generated   unique    duplicates   dup rate
one global seed, all workers      4000        499       3501         87.52%
per-worker seed (SEED ^ worker)   4000        3993      7            0.18%
per-worker namespaced sequence    4000        4000      0            0.00%
```

With one shared seed every worker replays the identical stream, so **3,501 of 4,000 values are duplicates — 87.52%** — and only **499** distinct values exist across the whole run. Under a `UNIQUE` constraint that is thousands of `IntegrityError`s whose stack traces point at your factory, when the actual cause is a line in `conftest.py` that nobody has read in two years. It also gets *worse* with parallelism, which is the opposite of the direction people expect, and it disappears entirely when you run with `-p no:xdist` to debug it.

Per-worker seeding fixes the duplication and — read the third row against the second — **does not fix collisions**. The birthday model for 4,000 draws from a million values predicts **7.99 expected collisions** and a **99.9664%** chance of at least one; the simulation produced **7**. Model and measurement agree, which means this is not bad luck you can re-run away from. It is arithmetic: a "random" unique field over a small value space collides in essentially every run, and each collision is a flake that is genuinely irreproducible because the seed that produced it is gone.

Two related traps sit next to this one. `secrets` and `os.urandom` cannot be seeded at all — they read the operating system's entropy source by design, which is correct for tokens and fatal for test data, so anything that has to be reproducible must come from a `random.Random` instance you own rather than the module-level functions that share one global state. And `Faker` is a seeded RNG wearing a friendly interface: unseeded, `fake.email()` is exactly the `randrange` above with better-looking output, and it produces the identical collision curve. `Faker.seed()` is a class method that sets shared state for every instance, which is why `pytest-randomly` reseeding it per test is worth more than any amount of care in your factories.

The fix is not a bigger space. It is to stop asking for uniqueness probabilistically: give each worker a **namespace** and count inside it — `f"u{worker}-{i}@test"` — and uniqueness becomes a property of the design, at **0 collisions**. Keep the seeded RNG for the values that only need to be *plausible*, and note the second-order point for [Property-Based Testing & Fuzzing](../12-property-based-testing-and-fuzzing/): a seeded test that passes is evidence about that seed and no other.

### Identifiers: sorting by ID is not sorting by time

Two habits collide here. The first is asserting on an identifier. The second is *ordering* by one — and the second is worse, because it produces a test that is right most of the time.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 464" width="100%" style="max-width:840px" role="img" aria-label="The 128-bit layouts of UUIDv4 and UUIDv7 drawn to scale side by side: version 4 spends all 122 free bits on randomness, while version 7 spends the leading 48 on a big-endian Unix millisecond timestamp and the remaining 74 on randomness. Below, a logarithmic chart of the fraction of pairs that come out inverted when ten thousand identifiers generated in creation order are sorted by value: UUIDv4 inverts 49.74 percent, a coin flip, while UUIDv7 inverts 5.0161 percent at a thousand identifiers per millisecond, 0.4927 percent at a hundred, 0.0456 percent at ten, and nothing at all at one per millisecond or with a monotonic counter. At the bottom, the assertion that the first identifier is less than the second fails half the time under UUIDv4, and the assertion that a new row has id 1 passes or fails depending on whether the schema says AUTOINCREMENT.">
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <text x="440" y="26" text-anchor="middle" font-size="14.5" font-weight="700" fill="currentColor">Sorting by id is sorting by time only if the id contains the time</text>
    <text x="440" y="45" text-anchor="middle" font-size="10" fill="currentColor" opacity="0.8">128 bits, drawn to scale (RFC 9562, 2024)</text>

    <text x="30" y="86" font-size="10" font-weight="700" fill="#d64545">UUIDv4</text>
    <text x="30" y="99" font-size="8" fill="currentColor" opacity="0.75">122 free bits</text>
    <g stroke-width="1.4">
      <rect x="90" y="70" width="262" height="28" fill="#d64545" fill-opacity="0.20" stroke="#d64545"/>
      <rect x="352" y="70" width="22" height="28" fill="#7f7f7f" fill-opacity="0.30" stroke="#7f7f7f"/>
      <rect x="374" y="70" width="66" height="28" fill="#d64545" fill-opacity="0.20" stroke="#d64545"/>
      <rect x="440" y="70" width="11" height="28" fill="#7f7f7f" fill-opacity="0.30" stroke="#7f7f7f"/>
      <rect x="451" y="70" width="339" height="28" fill="#d64545" fill-opacity="0.20" stroke="#d64545"/>
    </g>
    <text x="221" y="89" text-anchor="middle" font-size="9.5" font-weight="700" fill="#d64545">random</text>
    <text x="620" y="89" text-anchor="middle" font-size="9.5" font-weight="700" fill="#d64545">random &#8212; nothing in here is a clock</text>

    <text x="30" y="132" font-size="10" font-weight="700" fill="#0fa07f">UUIDv7</text>
    <text x="30" y="145" font-size="8" fill="currentColor" opacity="0.75">48 + 74 bits</text>
    <g stroke-width="1.4">
      <rect x="90" y="116" width="262" height="28" fill="#0fa07f" fill-opacity="0.22" stroke="#0fa07f"/>
      <rect x="352" y="116" width="22" height="28" fill="#7f7f7f" fill-opacity="0.30" stroke="#7f7f7f"/>
      <rect x="374" y="116" width="66" height="28" fill="#e0930f" fill-opacity="0.22" stroke="#e0930f"/>
      <rect x="440" y="116" width="11" height="28" fill="#7f7f7f" fill-opacity="0.30" stroke="#7f7f7f"/>
      <rect x="451" y="116" width="339" height="28" fill="#7f7f7f" fill-opacity="0.20" stroke="#7f7f7f"/>
    </g>
    <text x="221" y="135" text-anchor="middle" font-size="9.5" font-weight="700" fill="#0fa07f">48-bit Unix ms, big-endian</text>
    <text x="407" y="135" text-anchor="middle" font-size="8" font-weight="700" fill="#e0930f">rand_a</text>
    <text x="620" y="135" text-anchor="middle" font-size="9.5" font-weight="700" fill="currentColor" opacity="0.8">62 random bits</text>

    <g fill="currentColor" font-size="7.5" text-anchor="middle" opacity="0.65">
      <text x="363" y="110">ver</text><text x="445" y="110">var</text>
    </g>
    <path d="M90 154 L 352 154" fill="none" stroke="#0fa07f" stroke-width="1.2"/>
    <text x="221" y="166" text-anchor="middle" font-size="8" fill="#0fa07f" opacity="0.95">a byte-order compare reads these first: value order IS time order</text>
    <text x="620" y="166" text-anchor="middle" font-size="8" fill="#e0930f" opacity="0.95">rand_a can hold a monotonic counter instead (RFC 9562 §6.2)</text>

    <path d="M26 180 L 854 180" fill="none" stroke="currentColor" stroke-width="1.2" opacity="0.3"/>
    <text x="30" y="200" font-size="11" font-weight="700" fill="currentColor">10,000 ids created in order, then sorted by VALUE &#8212; how many of the 49,995,000 pairs come out inverted</text>

    <g fill="none" stroke="currentColor" stroke-width="1.1" opacity="0.35" stroke-dasharray="3 3">
      <path d="M422 212 L 422 326"/><path d="M535 212 L 535 326"/><path d="M647 212 L 647 326"/><path d="M760 212 L 760 326"/>
    </g>
    <path d="M310 326 L 790 326" fill="none" stroke="currentColor" stroke-width="1.2" opacity="0.5"/>
    <path d="M310 212 L 310 326" fill="none" stroke="currentColor" stroke-width="1.2" opacity="0.5"/>

    <g>
      <rect x="310" y="216" width="416" height="14" fill="#d64545" fill-opacity="0.45" stroke="#d64545" stroke-width="1.2"/>
      <rect x="310" y="238" width="304" height="14" fill="#e0930f" fill-opacity="0.45" stroke="#e0930f" stroke-width="1.2"/>
      <rect x="310" y="260" width="190" height="14" fill="#e0930f" fill-opacity="0.35" stroke="#e0930f" stroke-width="1.2"/>
      <rect x="310" y="282" width="74" height="14" fill="#0fa07f" fill-opacity="0.35" stroke="#0fa07f" stroke-width="1.2"/>
      <rect x="310" y="304" width="3" height="14" fill="#0fa07f" fill-opacity="0.55" stroke="#0fa07f" stroke-width="1.2"/>
    </g>

    <g fill="currentColor" font-size="9" text-anchor="end">
      <text x="302" y="227" font-weight="700" fill="#d64545">UUIDv4, any rate</text>
      <text x="302" y="249">UUIDv7 &#8195;1,000 ids/ms</text>
      <text x="302" y="271">UUIDv7 &#8195;&#8195;&#8195;100 ids/ms</text>
      <text x="302" y="293">UUIDv7 &#8195;&#8195;&#8195;&#8195;10 ids/ms</text>
      <text x="302" y="315" font-weight="700" fill="#0fa07f">UUIDv7 1/ms &#183; or +counter</text>
    </g>
    <g fill="currentColor" font-size="9.5" font-weight="700">
      <text x="798" y="227" fill="#d64545">49.74%</text>
      <text x="798" y="249">5.0161%</text>
      <text x="798" y="271">0.4927%</text>
      <text x="798" y="293">0.0456%</text>
      <text x="798" y="315" fill="#0fa07f">0 inv.</text>
    </g>
    <g fill="currentColor" font-size="7.5" text-anchor="middle" opacity="0.65">
      <text x="310" y="338">0.01%</text><text x="422" y="338">0.1%</text><text x="535" y="338">1%</text><text x="647" y="338">10%</text><text x="760" y="338">100%</text>
    </g>
    <text x="535" y="350" text-anchor="middle" font-size="8" fill="currentColor" opacity="0.7">inverted pairs, log scale &#8212; UUIDv7's only inversions are the ties inside one millisecond</text>

    <path d="M26 362 L 854 362" fill="none" stroke="currentColor" stroke-width="1.2" opacity="0.3"/>

    <rect x="30" y="376" width="400" height="54" rx="8" fill="#d64545" fill-opacity="0.10" stroke="#d64545" stroke-width="1.5"/>
    <text x="44" y="394" font-size="9.5" font-weight="700" fill="#d64545">assert first.id &lt; second.id &#8195;10,000 fresh pairs</text>
    <text x="44" y="409" font-size="9" fill="currentColor" opacity="0.92">UUIDv4 fails 5,000 times &#8212; 50.00%</text>
    <text x="44" y="423" font-size="9" fill="currentColor" opacity="0.92">UUIDv7 inside one millisecond fails 4,968 &#8212; 49.68%</text>

    <rect x="450" y="376" width="400" height="54" rx="8" fill="#7c5cff" fill-opacity="0.11" stroke="#7c5cff" stroke-width="1.5"/>
    <text x="464" y="394" font-size="9.5" font-weight="700" fill="#7c5cff">assert order.id == 1 &#8195;after an earlier test cleaned up</text>
    <text x="464" y="409" font-size="9" fill="currentColor" opacity="0.92">INTEGER PRIMARY KEY &#8195;&#8195;&#8195;&#8195;&#8195;&#8195;id = 1 &#8195;passes</text>
    <text x="464" y="423" font-size="9" fill="currentColor" opacity="0.92">INTEGER PRIMARY KEY AUTOINCREMENT &#8195;id = 4 &#8195;fails</text>

    <text x="440" y="456" text-anchor="middle" font-size="11.5" font-weight="700" fill="currentColor">An id is a fact about the database's history. Never assert on one; assert on what you put in it.</text>
  </g>
</svg>
```

UUIDv4 is 122 random bits (RFC 9562, 2024, §5.4). Sorting 10,000 of them by value and comparing against creation order inverts **24,868,131 of 49,995,000 pairs — 49.74%**. That is a coin flip, which is exactly what "sorted by a random number" means. The assertion `assert first.id < second.id` fails **5,000 times in 10,000 — 50.00%**, so on a two-row fixture it is not a test, it is a coin.

UUIDv7 (§5.7) puts a 48-bit big-endian Unix millisecond timestamp in the leading bits, and since byte-order comparison reads those first, value order *is* time order — to the millisecond. Its only inversions are ties inside a single millisecond, which makes the inversion rate a function of your generation rate: **0 at 1 id/ms, 0.0456% at 10/ms, 0.4927% at 100/ms, 5.0161% at 1,000/ms**. Filling `rand_a` with a monotonic counter instead of randomness (RFC 9562 §6.2, "fixed bit-length dedicated counter") removes the ties and takes it to **0** at 1,000/ms.

Note the honest version of the rule, though: inside one millisecond, UUIDv7 is as unordered as UUIDv4 — the program measures `assert first.id < second.id` failing **4,968 times in 10,000, 49.68%**, for two v7 ids created in the same millisecond. A test that creates two records back to back creates them in the same millisecond. **UUIDv7 fixes your index locality and your range scans; it does not make an ordering assertion in a fast test safe.**

Sequences are not a refuge either, and the last block of the diagram is the sharpest thing in this section. `assert order.id == 1`, after an earlier test inserted three rows and cleaned up after itself:

```sql
-- INTEGER PRIMARY KEY                 -> id = 1   the test passes
-- INTEGER PRIMARY KEY AUTOINCREMENT   -> id = 4   the test fails
```

Same test, same data, same cleanup. The only difference is a keyword in a `CREATE TABLE` that the test author never read. `AUTOINCREMENT` (and Postgres `SERIAL`/`IDENTITY`, whose sequences are non-transactional and burn values on rollback) guarantees monotonicity, which means it *must* leave gaps. An id is a fact about the database's history, not about your test. Assert on what you put in the row.

### Iteration order: sets, hash seeds, and the query with no ORDER BY

CPython randomises the hash of `str` and `bytes` once per process (PEP 456, 2013 — SipHash, adopted to close a denial-of-service attack in which an attacker sends keys that all collide). The hash decides the slot; the slot order is the iteration order; so **the order a `set` iterates in is chosen by a per-process random seed you did not set.**

Demonstrating that in a program that must itself be reproducible takes some care, so the lesson does it twice. First with a seed we control: a small open-addressed set whose keyed hash is a seeded FNV-1a with a MurmurHash3 finaliser. Four tags, 512 seeds:

```text
distinct orders observed        24 of 24 possible
the order YOUR machine showed   auth,search,reports,billing
seeds that reproduce it         22 of 512  (4.30%)
```

All **24 of the 24 possible orderings** appear, near-uniformly. The specific order your laptop showed you the day you wrote the assertion — the one you pasted into `assert ",".join(tags) == "auth,search,reports,billing"` — holds on **22 of 512 seeds, 4.30%**. That test does not fail *sometimes*. It passes about one process in twenty-three.

Then with real CPython, five subprocesses at pinned `PYTHONHASHSEED` values:

```text
PYTHONHASHSEED=0   set of str -> billing,auth,reports,search        set of int -> 40,10,20,30
PYTHONHASHSEED=1   set of str -> billing,auth,search,reports        set of int -> 40,10,20,30
PYTHONHASHSEED=2   set of str -> auth,billing,search,reports        set of int -> 40,10,20,30
```

Nearly every seed produces a different string order — and the integer set never moves, because **CPython does not randomise `hash(int)`**. Run that yourself and you will very likely see *different* strings in those rows than are printed above: pinning `PYTHONHASHSEED` makes string hashing deterministic for one CPython build, not across builds, so the exact orderings are a property of the interpreter that produced them. The pattern is what reproduces — strings reorder, integers never do — which is precisely why the specific order is the wrong thing for a test to assert on. That asymmetry is why the bug hides so well: half the sets in your suite are integer sets and behave perfectly, so "sets are unordered" gets filed as pedantry rather than as something that will fail in CI. `dict` is a third case again: insertion order has been a language guarantee since Python 3.7, so `list(d)` is stable and `list(set(d))` is not.

The database version is the same idea with a different seed. **A `SELECT` with no `ORDER BY` has no defined order** — the engine returns rows in whatever order the plan produced them — and the plan is not part of your test. Same table, same five rows, same query, in `sqlite3`:

```sql
SELECT seq FROM events WHERE tenant = 'acme';
-- full table scan          -> [50, 40, 30, 20, 10]
CREATE INDEX ix_events_tenant_seq ON events (tenant, seq);
SELECT seq FROM events WHERE tenant = 'acme';
-- index scan               -> [10, 20, 30, 40, 50]
```

The only thing that changed is that somebody shipped a migration that added an index. The rows are identical; the answer is reversed. And it moves for a second, more insidious reason — a fixture that deletes a row and re-creates it:

```sql
DELETE FROM events WHERE seq = 30;
INSERT INTO events (tenant, seq) VALUES ('acme', 30);
-- full table scan          -> [50, 40, 20, 10, 30]
```

Logically the same five rows. The re-inserted row got a new rowid, so it moved to the end of the scan. Both of these break `assert rows[0].seq == 50` and neither shows up as a change to any data your test can see. The same defect has a third form that catches people migrating CI runners: `os.listdir()` and `glob.glob()` return directory entries in whatever order the filesystem stores them, which on ext4 with `dir_index` is hash order, on APFS is roughly insertion order, and inside a container overlay is neither. A fixture loader that reads `fixtures/*.json` and applies them in the returned order works perfectly on a laptop and applies them in a different order on the runner. `sorted(glob.glob(...))` is a one-word fix and it belongs in every fixture loader you write.

Add `ORDER BY` to every query whose order you assert on, and sort before comparing collections — or compare as a set when order genuinely does not matter, which says so in the assertion instead of hoping.

### Test execution order: independence is a property you must verify

Test independence is a *property*: any test must pass in any order. Nobody writes it down, everybody assumes it, and the only way to know you have it is to violate the file order deliberately.

The program builds a 200-test suite with three real order dependencies, arranged — as real suites are — so that **file order is completely green**. Then it shuffles 4,000 times with a seeded permutation, exactly as `pytest-randomly` reshuffles once per run.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 476" width="100%" style="max-width:840px" role="img" aria-label="The detection power of shuffling a 200-test suite that contains three deliberate order dependencies and is completely green in file order. Measured over 4000 seeded shuffles: a leaked global config is caught with probability 0.4928, a shared table plus a truncating test with 0.6645, but a count dependency in which 39 tests each leak one cache entry with only 0.0265, against analytic values of one half, two thirds and one fortieth. Detecting that any dependency exists takes three shuffled runs for 99 percent confidence; detecting the rarest one takes 182. A single reversed run caught two of the three for free and missed the count dependency entirely. The curve at the bottom right plots the probability a dependency is still undetected after N shuffled runs on a logarithmic axis, showing the any-dependency curve crossing one percent at run three and the rare dependency crossing it at run 182.">
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <text x="440" y="26" text-anchor="middle" font-size="14.5" font-weight="700" fill="currentColor">Shuffling finds "a" dependency in 3 runs. Finding them all takes 182.</text>
    <text x="440" y="45" text-anchor="middle" font-size="10" fill="currentColor" opacity="0.8">200 tests · 3 real order dependencies · 0 failures in file order · 4,000 seeded shuffles</text>

    <g fill="currentColor" font-size="8.5" font-weight="700" opacity="0.62">
      <text x="30" y="70">THE DEPENDENCY</text><text x="290" y="70">WHAT IT NEEDS TO FAIL</text><text x="486" y="70">P(CAUGHT PER SHUFFLED RUN)</text><text x="700" y="70">MEASURED</text><text x="772" y="70">EXACT</text><text x="824" y="70">RUNS@99%</text>
    </g>
    <path d="M26 76 L 854 76" fill="none" stroke="currentColor" stroke-width="1.3" opacity="0.45"/>
    <g fill="none" stroke="currentColor" stroke-width="1" opacity="0.2">
      <path d="M26 112 L 854 112"/><path d="M26 148 L 854 148"/>
    </g>
    <path d="M26 184 L 854 184" fill="none" stroke="currentColor" stroke-width="1.2" opacity="0.35"/>

    <g stroke-width="4" stroke-linecap="round">
      <path d="M28 86 L 28 106" stroke="#0fa07f"/><path d="M28 122 L 28 142" stroke="#0fa07f"/><path d="M28 158 L 28 178" stroke="#d64545"/>
    </g>

    <g fill="currentColor" font-size="9.5">
      <text x="38" y="94" font-weight="700">D1 leaked global config</text><text x="38" y="106" font-size="8.5" opacity="0.8">a test sets CONFIG; another reads default</text>
      <text x="38" y="130" font-weight="700">D2 shared table + a truncate</text><text x="38" y="142" font-size="8.5" opacity="0.8">seed 3 rows, count them, another clears</text>
      <text x="38" y="166" font-weight="700" fill="#d64545">D3 39 tests leak one entry each</text><text x="38" y="178" font-size="8.5" opacity="0.8">asserts the cache holds fewer than 39</text>
    </g>
    <g fill="currentColor" font-size="8.5" opacity="0.9">
      <text x="290" y="94">the setter runs first</text><text x="290" y="106" opacity="0.75">a precedence flip &#8212; 1 in 2</text>
      <text x="290" y="130">count runs outside the pair</text><text x="290" y="142" opacity="0.75">2 of the 6 orderings survive</text>
      <text x="290" y="166" font-weight="700" fill="#d64545">ALL 39 leakers run first</text><text x="290" y="178" opacity="0.75">a count, not a precedence: 1 in 40</text>
    </g>

    <g>
      <rect x="486" y="83" width="79" height="14" fill="#0fa07f" fill-opacity="0.45" stroke="#0fa07f" stroke-width="1.2"/>
      <rect x="486" y="119" width="106" height="14" fill="#0fa07f" fill-opacity="0.45" stroke="#0fa07f" stroke-width="1.2"/>
      <rect x="486" y="155" width="4" height="14" fill="#d64545" fill-opacity="0.55" stroke="#d64545" stroke-width="1.2"/>
      <rect x="486" y="191" width="134" height="14" fill="#3553ff" fill-opacity="0.40" stroke="#3553ff" stroke-width="1.2"/>
    </g>
    <path d="M486 78 L 486 212" fill="none" stroke="currentColor" stroke-width="1" opacity="0.35"/>
    <path d="M646 78 L 646 212" fill="none" stroke="currentColor" stroke-width="1" stroke-dasharray="3 3" opacity="0.3"/>
    <text x="646" y="222" text-anchor="middle" font-size="7.5" fill="currentColor" opacity="0.6">1.0</text>
    <text x="486" y="222" text-anchor="middle" font-size="7.5" fill="currentColor" opacity="0.6">0</text>

    <g font-size="9.5" font-weight="700">
      <text x="700" y="94">0.4928</text><text x="772" y="94" fill="currentColor" opacity="0.75">0.5000</text><text x="838" y="94" text-anchor="end">7</text>
      <text x="700" y="130">0.6645</text><text x="772" y="130" fill="currentColor" opacity="0.75">0.6667</text><text x="838" y="130" text-anchor="end">5</text>
      <text x="700" y="166" fill="#d64545">0.0265</text><text x="772" y="166" fill="currentColor" opacity="0.75">0.0250</text><text x="838" y="166" text-anchor="end" fill="#d64545">182</text>
      <text x="700" y="202" fill="#3553ff">0.8353</text><text x="772" y="202" fill="currentColor" opacity="0.75">0.8375</text><text x="838" y="202" text-anchor="end" fill="#3553ff">3</text>
    </g>
    <text x="38" y="202" font-size="9.5" font-weight="700" fill="#3553ff">ANY of the three detected</text>
    <text x="290" y="202" font-size="8.5" fill="currentColor" opacity="0.9">the question CI actually asks</text>

    <text x="440" y="240" text-anchor="middle" font-size="9" fill="currentColor" opacity="0.8">simulation and closed form agree to within 0.008 on every row — combinatorics, not weather</text>

    <path d="M26 254 L 854 254" fill="none" stroke="currentColor" stroke-width="1.2" opacity="0.3"/>

    <text x="30" y="276" font-size="11" font-weight="700" fill="currentColor">what the cheap alternatives buy you</text>

    <rect x="30" y="288" width="392" height="34" rx="7" fill="#0fa07f" fill-opacity="0.10" stroke="#0fa07f" stroke-width="1.5"/>
    <text x="44" y="303" font-size="9.5" font-weight="700" fill="#0fa07f">run the suite in file order</text>
    <text x="44" y="316" font-size="8.5" fill="currentColor" opacity="0.85">0 failures. Green. Ships. This is the state every suite starts in.</text>

    <rect x="30" y="330" width="392" height="46" rx="7" fill="#e0930f" fill-opacity="0.11" stroke="#e0930f" stroke-width="1.5"/>
    <text x="44" y="346" font-size="9.5" font-weight="700" fill="#e0930f">run it once in REVERSE order &#8212; 2 of 3 caught, free</text>
    <text x="44" y="359" font-size="8.5" fill="currentColor" opacity="0.85">reversing a green order flips every precedence pair, so D1 and D2</text>
    <text x="44" y="371" font-size="8.5" fill="currentColor" opacity="0.85">fail with certainty. Do this before you do anything else.</text>

    <rect x="30" y="384" width="392" height="46" rx="7" fill="#d64545" fill-opacity="0.10" stroke="#d64545" stroke-width="1.5"/>
    <text x="44" y="400" font-size="9.5" font-weight="700" fill="#d64545">&#8230; and it cannot ever catch D3</text>
    <text x="44" y="413" font-size="8.5" fill="currentColor" opacity="0.85">D3 depends on HOW MANY leakers precede it (20 in file order,</text>
    <text x="44" y="425" font-size="8.5" fill="currentColor" opacity="0.85">19 reversed, 39 needed). No single fixed order reaches it.</text>

    <text x="470" y="276" font-size="11" font-weight="700" fill="currentColor">P(still undetected) after N shuffled runs</text>

    <g fill="none" stroke="currentColor" stroke-width="1.3">
      <path d="M470 420 L 850 420"/><path d="M470 420 L 470 296"/>
    </g>
    <g fill="none" stroke="currentColor" stroke-width="1" opacity="0.35" stroke-dasharray="3 3">
      <path d="M470 340 L 850 340"/><path d="M470 380 L 850 380"/>
    </g>
    <g fill="currentColor" font-size="7.5" text-anchor="end" opacity="0.7">
      <text x="466" y="303">100%</text><text x="466" y="343">10%</text><text x="466" y="383">1%</text><text x="466" y="423">0.1%</text>
    </g>

    <path d="M470 300 L 472 332 L 474 363 L 476 395 L 477 420" fill="none" stroke="#3553ff" stroke-width="2.6"/>
    <path d="M470 300 L 516 311 L 563 322 L 609 333 L 655 344 L 690 352 L 748 366 L 807 380 L 840 388" fill="none" stroke="#d64545" stroke-width="2.6"/>

    <circle cx="476" cy="380" r="4" fill="#3553ff"/><circle cx="807" cy="380" r="4" fill="#d64545"/>
    <text x="486" y="373" font-size="9" font-weight="700" fill="#3553ff">N = 3</text>
    <text x="803" y="373" text-anchor="end" font-size="9" font-weight="700" fill="#d64545">N = 182</text>

    <g fill="currentColor" font-size="8" text-anchor="middle" opacity="0.7">
      <text x="470" y="434">0</text><text x="563" y="434">50</text><text x="655" y="434">100</text><text x="748" y="434">150</text><text x="840" y="434">200</text>
    </g>
    <text x="660" y="447" text-anchor="middle" font-size="8.5" fill="currentColor" opacity="0.75">shuffled runs (pytest-randomly reshuffles once per run)</text>
    <text x="500" y="308" font-size="8.5" font-weight="700" fill="#3553ff">any dependency</text>
    <text x="700" y="336" font-size="8.5" font-weight="700" fill="#d64545">the rare one, p = 1/40</text>

    <text x="440" y="468" text-anchor="middle" font-size="11.5" font-weight="700" fill="currentColor">"Is this suite order-independent?" is a cheap question. "Have I found them all?" is priced by the rarest one.</text>
  </g>
</svg>
```

Two of the dependencies are the textbook kind and they are cheap to find. **D1** is a leaked global: one test sets `CONFIG["currency"] = "EUR"`, another asserts the default, and it fails whenever the setter happens to run first — measured **0.4928** against an exact one-half. **D2** is a shared table with a third test that truncates it, so only 2 of the 6 relative orderings survive — **0.6645** against two-thirds. Simulation and closed form agree to within **0.008** on every row, which is worth knowing: this is combinatorics, not weather, and you can compute the answer for your own suite.

**D3 is the one that matters.** Thirty-nine tests each leak one entry into a module-level cache, and one assertion says the cache holds fewer than 39. It fails only when **all thirty-nine** leakers happen to precede it — probability **1/40**, measured **0.0265**. That is card three from The Problem: "fails roughly once every 40 runs, can't reproduce, closing."

Now the two numbers this experiment exists to produce. Detecting that the suite has *some* order dependence takes **3 shuffled runs for 99% confidence** (per-run detection 0.8353) — one afternoon, and you should just do it. Detecting **D3 specifically** takes **182 shuffled runs**, or 119 for 95%. At one CI run per merge, 182 runs is weeks, and during those weeks the test is failing occasionally and being re-run. **The cost of an order-dependence audit is not set by the average dependency; it is set by the rarest one.**

And the cheapest instrument first: running the suite once in **reverse order caught 2 of the 3 for free**. That is not luck. A green file order means every "A must precede B" pair is satisfied by file order, so reversing it violates every one of them with certainty. What reversal cannot touch is D3, because D3 is not a precedence dependency — it is a **count** dependency. Twenty leakers sit before the assertion in file order and nineteen after, so file order sees 20, reverse order sees 19, and it needs 39. **No single fixed ordering can reach it; only sampling can**, and sampling is priced by 1/40.

### Floating point: the tolerance you pick is a policy about money

IEEE 754-2019 `binary64` cannot represent 0.01, so a running total of prices is never the total you meant. Add a cent ten thousand times:

```text
float   100.00000000001425
Decimal 100.00
drift   1.43E-11  (1.43E-13 relative)
assert 0.1 + 0.2 == 0.3 -> False   (0.1 + 0.2 is 0.30000000000000004)
```

Everyone knows the last line. What almost nobody prices is the next decision: having accepted that `==` is wrong, *which* tolerance do you use? The program judges six basket totals from \$1.00 to \$50,000,000.00 twice — once against pure float drift, where calling them unequal is a **false alarm**, and once against a genuine one-cent error, where calling them equal is a **missed bug**.

```text
tolerance policy                      false alarms    missed 1c bugs    verdict
assert a == b                         4/6             0/6               too tight
math.isclose default (rel 1e-9)       0/6             1/6               too loose
pytest.approx default (rel 1e-6)      0/6             3/6               too loose
isclose(rel_tol=0, abs_tol=0.005)     0/6             0/6               ship this
Decimal, quantized to cents           0/6             0/6               ship this
```

The middle row is the one to take away, and it will be in a suite near you. **`pytest.approx` defaults to a relative tolerance of 1e-6, so it stops being able to see a one-cent error at a total of \$10,000** — and it missed the seeded bug on **3 of the 6 magnitudes**. Nothing about that is a bug in pytest; a relative tolerance is the right default for a physical quantity, where "correct to six significant figures" is a meaningful statement. It is exactly the wrong default for money, because a relative tolerance *scales the error you accept with the size of the number*, and a cent is a cent at every magnitude. The bigger the invoice, the less your assertion checks.

So: for money, compare in integer minor units or in `Decimal` — and if you must compare floats, set `abs_tol` to half the smallest unit you care about and set `rel_tol` explicitly to **0**, because `math.isclose` ORs the two conditions together and a non-zero `rel_tol` will quietly re-open the hole you just closed.

### The scheduler is a hidden input too

The last hidden input is the one you cannot inject: which of the legal interleavings the interpreter actually ran. Two threads each doing `counter = counter + 1` as READ / ADD / WRITE have 20 distinct interleavings, and the program enumerates all of them.

```text
distinct interleavings enumerated   20
end with counter == 2 (correct)     2   (10.0%)
end with counter == 1 (lost update) 18  (90.0%)

correct      A:READ A:ADD A:WRIT B:READ B:ADD B:WRIT   -> 2
lost update  A:READ A:ADD B:READ A:WRIT B:ADD B:WRIT   -> 1
```

**Ninety per cent of the possible schedules lose the update, and the test passes anyway.** Only the two fully serial orderings are correct. That gap — almost every schedule is wrong, almost every run is right — *is* what a race condition is, and it is why races reach production ([Race Conditions & Atomicity](../../08-concurrency-and-performance/08-race-conditions-and-atomicity/) builds the fix). A real run does not enumerate; it samples one schedule, and the vulnerable window is a handful of nanoseconds:

```text
q (switch per step)     P(lost update)      runs for a 50% chance     at 20 CI runs/day
1e-02                   2e-02               35                        2 days
1e-03                   2e-03               347                       17 days
1e-04                   2e-04               3,466                     173 days
1e-05                   2e-05               34,658                    1,733 days
```

That table is the honest version of "we've never seen it in CI". At a switch probability of 1e-4 per step you need **3,466 runs for an even chance** — 173 days at twenty runs a day — and the run that finally catches it will be closed as a flake, because by then the team has learned that red means re-run. Enumerating all 20 interleavings finds the bug with certainty in 20 executions. That is the argument for deterministic scheduling: not that it is tidier, but that it converts a 1-in-thousands lottery into an exhaustive check. [Testing Async & Event-Driven Systems](../11-testing-async-and-event-driven/) does this properly for `asyncio`, where you control the loop and the enumeration is actually tractable.

## Build It

[`code/determinism.py`](code/determinism.py) is nine numbered experiments matching the nine sub-headings above. Standard library only, every RNG seeded from `SEED = 20260718`, and — since this is a lesson about determinism — **no wall-clock value is ever printed**, so two runs of the program are byte-identical and so is a run under any `PYTHONHASHSEED`.

The clock is a two-method port. That is the entire abstraction, and the three implementations differ by four lines:

```python
class FrozenClock(Clock):
    def sleep(self, seconds: float) -> None:
        return                      # the wait is swallowed; the clock does not move

class ControllableClock(Clock):
    def sleep(self, seconds: float) -> None:
        self.t += seconds
    advance = sleep
```

`FrozenClock.sleep` returning `None` without moving `t` is the whole of "a frozen clock cannot test a timeout" — and the reason the program can *detect* that, rather than just hanging, is that `wait_for` reports how far the clock moved:

```python
def wait_for(clock, ready_at, timeout, interval) -> tuple[bool, float]:
    start = clock.now()
    deadline = start + timeout
    for _ in range(10_000):                     # a guard, not a deadline
        if clock.now() >= ready_at:
            return True, clock.now() - start
        if clock.now() >= deadline:
            return False, clock.now() - start
        clock.sleep(interval)
    return False, clock.now() - start
```

The behaviour asserts `ready is False and moved >= 30.0`. Under the frozen clock the first half holds and the second does not, which is how "passes for the wrong reason" becomes a measurement instead of an opinion.

The timezone rules are twenty lines and no `tzdata`, so the mechanism is visible. `from_wall` is the interesting one, because it is the only honest signature: a wall-clock reading does not map to *an* instant, it maps to zero, one or two:

```python
def from_wall(wall: dt.datetime) -> list[dt.datetime]:
    """0 = the spring gap, 2 = the autumn fold, 1 = an ordinary hour."""
    out = [c for h in (1, 2)
           if berlin_offset(c := wall.replace(tzinfo=UTC) - dt.timedelta(hours=h))
           == dt.timedelta(hours=h)]
    return sorted(out)
```

Returning a list rather than a datetime is what makes the gap and the fold countable instead of silently resolved. `sorted()` is not cosmetic either — taking `[0]` is exactly what PEP 495's `fold=0` means, so the naive implementation is modelling the default rather than a strawman.

The order-dependence suite is the one place the code has to be built carefully, because the whole result depends on file order being green. D3 is the subtle one: **twenty leakers are placed before the assertion and nineteen after**, which is what makes it invisible to both file order (20 < 39) and reverse order (19 < 39):

```python
tests.append(("test_reads_default_currency", d1_reader))
for i in range(20):                            # 20 leakers before the target
    tests.append((f"test_writes_audit_entry_{i:02d}", leak(i)))
tests.append(("test_cache_stays_small", d3_target))    # asserts len(cache) < 39
...
for i in range(20, LEAKERS):                   # 19 leakers after it
```

The detection numbers then come from running the real suite 4,000 times against a seeded shuffle and comparing to the closed form:

```python
analytic = {"test_reads_default_currency": 0.5,
            "test_counts_three_rows": 2 / 3,
            "test_cache_stays_small": 1 / (LEAKERS + 1)}

def runs_for(p: float, conf: float) -> int:
    return math.ceil(math.log(1 - conf) / math.log(1 - p))
```

`runs_for` is the number worth stealing: given a per-run detection probability `p`, the runs needed for confidence `conf` is `log(1 − conf) / log(1 − p)`. That is where 182 comes from, and you can point it at your own flake rates.

A lesson about determinism has to keep its own promise, so it is worth saying exactly how the program does. Nothing derived from an unordered container ever reaches a printed value; `time.perf_counter()` is never called and no duration is printed, so there is no elapsed line to drift; the real clock's 937-second bill is *accounted* rather than paid, which is both why the program finishes in seconds and why that number is stable; and the hash-seed experiment simulates a seed it controls rather than reading the ambient one, with the real-CPython demonstration pushed into subprocesses whose `PYTHONHASHSEED` is set explicitly. The result is checkable in one line, and you should check it rather than believe it:

```bash
python3 determinism.py > a.txt && python3 determinism.py > b.txt && diff a.txt b.txt
PYTHONHASHSEED=random python3 determinism.py | diff a.txt -
```

Both produce no output. If the second one ever does, the program has an iteration-order bug of exactly the kind section 6 is about — which is the point: this check is not ceremony, it is the same audit you should be running against your own suite.

Run it:

```bash
docker compose exec -T app python \
  phases/12-testing-and-quality/08-determinism-time-randomness-order/code/determinism.py
```

```console
DETERMINISM · Phase 12 Lesson 08 · every RNG seeded from SEED = 20260718; no wall-clock value is printed.

== 2 · THE CLOCK: FREEZING IS NOT CONTROLLING ==
  a 300 s TTL cache + a 4-attempt backoff + a 30 s timeout, 6 behaviours

    behaviour                             real clock   frozen       controllable
    B1 fresh key is a hit                 pass         pass         pass
    B2 hit 1 s before expiry              pass         pass         pass
    B3 miss exactly AT the ttl boundary   pass         pass         pass
    B4 miss 1 s after expiry              pass         pass         pass
    B5 retry backoff emits 0/1/3/7 s      pass         unreachable  pass
    B6 wait_for times out after 30 s      pass         unreachable  pass

    real clock (actually sleeps)          6/6 reachable    wall cost    937 s
    frozen (freezegun, no tick)           4/6 reachable    wall cost      0 s
    controllable (test owns time)         6/6 reachable    wall cost      0 s
  ... (one-line interpretation trimmed)

== 3 · TIMEZONES, DST AND LEAP YEARS: A YEAR OF DATE BOUNDARIES ==
  server in Europe/Berlin (UTC+1 winter, UTC+2 summer, EU transition rule)
  every hour of the year is a subscription start; renew it by one month

    year   instants   wrong           1 h off   >=1 day off  ambiguous
    2024   8784       1454      16.6% 1438      16           1
    2025   8760       1433      16.4% 1415      18           1

  and the two wall-clock times that are not instants at all:
    Berlin 2024-03-31 02:30 (spring forward) -> 0 UTC instant(s): nothing — this wall time never happens
    Berlin 2024-10-27 02:30 (autumn back   ) -> 2 UTC instant(s): 00:30Z, 01:30Z

  test_renewal_lands_on_the_same_day_of_month(), run at each hour of the year:
    2024: fails at  704 of 8784 hours (8.0%)
    2025: fails at  725 of 8760 hours (8.3%)
    2024 by UTC hour: 23:00 fails 361x, 22:00 fails 211x, all 22 other hours 132x combined
  ... (one-line interpretation trimmed)

== 4 · SEEDS UNDER PARALLEL WORKERS: THE STREAM YOU SHARE ==
  8 workers x 500 generated emails, random.randrange(0, 1,000,000)

    strategy                          generated   unique    duplicates   dup rate
    one global seed, all workers      4000        499       3501         87.52%
    per-worker seed (SEED ^ worker)   4000        3993      7            0.18%
    per-worker namespaced sequence    4000        4000      0            0.00%

    birthday model for 4,000 draws from 1,000,000 values:
      expected collisions      7.99
      P(at least one)          99.9664%
  ... (one-line interpretation trimmed)

== 5 · IDENTIFIERS: SORTING BY ID IS NOT SORTING BY TIME ==
  10,000 ids generated in creation order, sorted by VALUE, inverted pairs counted
  (49,995,000 pairs; a value-sort that ignores time inverts ~50% of them)

    scheme                                      rate          inversions    % of pairs
    UUIDv4 (122 random bits)                    any           24868131      49.74%
    UUIDv7 (48-bit ms + 74 random bits)         1/ms          0             0.0000%
    UUIDv7 (48-bit ms + 74 random bits)         10/ms         22774         0.0456%
    UUIDv7 (48-bit ms + 74 random bits)         100/ms        246331        0.4927%
    UUIDv7 (48-bit ms + 74 random bits)         1000/ms       2507789       5.0161%
    UUIDv7 + monotonic counter (RFC 9562 6.2)   1000/ms       0             0.0000%

    assert first.id < second.id, over 10,000 freshly created pairs:
      UUIDv4                 fails  5000 times  (50.00%)
      UUIDv7, same millisec  fails  4968 times  (49.68%)

    assert order.id == 1 after a previous test inserted 3 rows and cleaned up:
      INTEGER PRIMARY KEY                 id = 1  -> passes
      INTEGER PRIMARY KEY AUTOINCREMENT   id = 4  -> fails
  ... (one-line interpretation trimmed)

== 6 · ITERATION ORDER: HASH SEEDS AND THE QUERY WITH NO ORDER BY ==
  4 tags in a set, 512 hash seeds, result serialised with ','.join()
    distinct orders observed        24 of 24 possible
    the order YOUR machine showed   auth,search,reports,billing
    seeds that reproduce it         22 of 512  (4.30%)
    a hard-coded assertion on it passes on 4.3% of processes

  the same thing in real CPython, PYTHONHASHSEED pinned per subprocess:
    PYTHONHASHSEED=0   set of str -> billing,auth,reports,search        set of int -> 40,10,20,30
    PYTHONHASHSEED=1   set of str -> billing,auth,search,reports        set of int -> 40,10,20,30
    5 distinct string orders across 5 seeds; the int order never moves — CPython does not randomise hash(int).
    NOTE: the orderings above are specific to CPython 3.9 on this machine and will
          differ on another build. What reproduces everywhere is the pattern:
          pinning the seed fixes the order, strings reorder across seeds, ints never do.

  SELECT with no ORDER BY, in sqlite3 — same query, same rows, two answers:
    before the migration (full table scan ) -> [50, 40, 30, 20, 10]
    after  the migration (index scan      ) -> [10, 20, 30, 40, 50]
    identical? False. The only change was CREATE INDEX.
    after DELETE seq=30 + re-INSERT the same row  -> [50, 40, 20, 10, 30]
    identical to before? False. A fixture that re-creates a row moves it.
  ... (one-line interpretation trimmed)

== 7 · TEST EXECUTION ORDER: THE DETECTION POWER OF A SHUFFLE ==
  200 tests, 3 deliberate order dependencies, no reset between tests
    run in file order      0 failures  -> green, ships
    run in reverse order   2 failures  -> D1, D2

  4,000 shuffled runs (a seeded permutation each, as pytest-randomly does)

    dependency                                measured    analytic    runs @95%   runs @99%
    D1 leaked global config                   0.4928      0.5000      5           7
    D2 shared table + a truncating test       0.6645      0.6667      3           5
    D3 39 tests each leaking one entry        0.0265      0.0250      119         182
    ANY dependency detected                   0.8353      0.8375      2           3
  ... (one-line interpretation trimmed)

== 8 · FLOATING POINT: THE TOLERANCE IS A POLICY ABOUT MONEY ==
  0.01 added 10,000 times
    float   100.00000000001425
    Decimal 100.00
    drift   1.43E-11  (1.43E-13 relative)
    assert 0.1 + 0.2 == 0.3 -> False   (0.1 + 0.2 is 0.30000000000000004)

  6 basket totals from $1.00 to $50,000,000.00; each judged twice:
    (a) float drift vs the exact total  — saying 'unequal' is a FALSE ALARM
    (b) a real 1-cent bug               — saying 'equal'   is a MISSED BUG

    tolerance policy                      false alarms    missed 1c bugs    verdict
    assert a == b                         4/6             0/6               too tight
    math.isclose default (rel 1e-9)       0/6             1/6               too loose
    pytest.approx default (rel 1e-6)      0/6             3/6               too loose
    isclose(rel_tol=0, abs_tol=0.005)     0/6             0/6               ship this
    Decimal, quantized to cents           0/6             0/6               ship this
  ... (one-line interpretation trimmed)

== 9 · THE SCHEDULER IS A HIDDEN INPUT TOO ==
  two threads, each doing counter = counter + 1 as READ / ADD / WRITE
    distinct interleavings enumerated   20
    end with counter == 2 (correct)     2   (10.0%)
    end with counter == 1 (lost update) 18  (90.0%)

    correct      A:READ A:ADD A:WRIT B:READ B:ADD B:WRIT   -> 2
    lost update  A:READ A:ADD B:READ A:WRIT B:ADD B:WRIT   -> 1

  a real thread pair does not enumerate; it samples one schedule. If the
  interpreter switches between two of the six steps with probability q,
  the race is observable at roughly 2q per operation:

    q (switch per step)     P(lost update)      runs for a 50% chance     at 20 CI runs/day
    1e-02                   2e-02               35                        2 days
    1e-03                   2e-03               347                       17 days
    1e-04                   2e-04               3,466                     173 days
    1e-05                   2e-05               34,658                    1,733 days
  ... (one-line interpretation trimmed)
```

Three things in that output are arguments rather than demonstrations.

**Section 2's `4/6` is not a performance number.** Nothing about the frozen clock is slow; two behaviours simply do not exist under it. When you audit a suite for time dependence, the tests to worry about are not the slow ones — they are the timeout tests that pass in a millisecond.

**Section 3's split between 1,438 and 16 is a two-bug diagnosis.** Moving all arithmetic to UTC fixes 1,438 of the 1,454. The remaining 16 need a decision about what "one month after 31 January" means, and no library can make that decision for you.

**Section 7's last two columns are the deliverable.** Everything else in that section is scaffolding for `3` and `182` — the price of the cheap question and the price of the complete answer.

## Use It

You will not write any of the above. You will turn on four settings, and the point of the sections above is to know which four and what they cost.

**`pytest-randomly` is the highest-value plugin in this lesson**, because it does three things at once: it shuffles test order within each module, it reseeds `random` before every single test, and it reseeds `Faker` and `factory_boy` too. Installing it turns section 7's experiment on permanently.

```bash
pytest -p randomly                    # on by default once installed
pytest -p no:randomly                 # turn it OFF to bisect a failure
pytest --randomly-seed=1234           # replay a specific run
pytest --randomly-seed=last           # replay the previous run
```

The seed is printed at the top of every run, and **that line is the artifact** — a failure report without it is not reproducible. Record it in CI alongside the test id and the worker. Note the default granularity: it shuffles *within* modules, not across the whole session, so cross-module leaks like D3 need `-p randomly --randomly-dont-reorganize` off and, realistically, repeated runs. And note the interaction with `pytest-xdist`: tests are distributed across workers, so a same-worker ordering assumption can survive a shuffle. `--dist loadfile` makes that reproducible; `--dist load` does not.

**`PYTHONHASHSEED=random` in CI, always.** It is the default for the interpreter, so the mistake is the opposite one — pinning it in a Dockerfile or a `tox.ini` to make a suite green. Pinning does not fix the bug; it hides it until production, where the seed is random again. If you need reproducibility for a *specific* failing run, pin it for that run only, from the value the failure printed.

```yaml
env:
  PYTHONHASHSEED: random          # the default — never pin it to make CI green
```

**`freezegun` vs `time-machine`.** Both freeze the clock. `freezegun` patches at the Python level and is slow enough to show up in a large suite; `time-machine` patches at the C level (`datetime` and `time` at once) and is roughly an order of magnitude faster, at the price of being CPython-specific. Both offer `tick=True` and a `move_to()` / `shift()` API, which is the *controllable* mode from section 2 — use it, because the default is frozen.

```python
import time_machine

@time_machine.travel("2024-03-31 00:30:00+00:00", tick=False)
def test_renewal_across_the_spring_gap():
    ...

def test_timeout_fires(time_machine):          # the pytest fixture
    time_machine.move_to("2024-01-01 00:00:00+00:00")
    started = begin_lease()
    time_machine.shift(31)                     # 31 s later — controlled, not frozen
    assert lease_expired(started)
```

The honest recommendation is stronger than either library, though: **prefer a clock port to patching `datetime` globally.** `@freeze_time` patches a module-level name, which means it works only if you guessed where the code under test imported `datetime` from, it freezes time for every library in the process (including the ones your database driver uses for timeouts), and it gives you no way to advance time *inside* a call. A `Clock` parameter with a default of `SystemClock()` costs one argument and gives you section 2's `6/6`. Reach for `time-machine` for the code you cannot change, and for third-party code that reads the clock itself.

**Timezone data.** Use `zoneinfo` (Python 3.9+, PEP 615) with the IANA database, never fixed offsets, and pin `tzdata` as an explicit dependency — the rules change several times a year by government decree, and a container built from a slim base image may have no tz database at all. Store instants in UTC, store the *user's IANA zone name* alongside any wall-clock intention ("bill on the 1st at 09:00 local"), and convert at the edges. `datetime.now(tz=UTC)` — never the naive `datetime.utcnow()`, which is deprecated in 3.12 precisely because it returns a naive object that lies about being UTC.

**Identifiers.** Python 3.14 ships `uuid.uuid7()`; before that, `uuid6` or `uuid-utils` on PyPI. Postgres 18 has `uuidv7()` natively. Adopt it for primary keys — the index-locality argument is real and separate from this lesson — but do not let it become an ordering assertion. Add an explicit `created_at` and `ORDER BY created_at, id`.

**Repetition and shuffling as gates.** `pytest-repeat` (`--count=20`) reruns each test in place; `pytest-flakefinder` reruns the whole selection. Both are for the *specific* test you already suspect. For section 7's audit, what you actually want is a nightly job that runs the full suite N times with different seeds and diffs the failure sets — and now you can size N from `runs_for(p, 0.99)` instead of guessing.

**`hypothesis`** deserves a note here because it looks like it contradicts everything above. It deliberately varies its input, and `@settings(derandomize=True)` makes a run reproducible from the source alone. Use `derandomize=True` in CI when you need a green build to mean the same thing twice, and leave it off in a nightly job where finding a *new* failure is the point — with `.hypothesis/examples` cached so the case is pinned once found. [Property-Based Testing & Fuzzing](../12-property-based-testing-and-fuzzing/) reconciles that properly.

**What to actually turn on today**, in this order:

1. **Run the suite in reverse order once.** It costs one command, needs no plugin, and section 7 measured it catching **2 of 3** dependencies. Do this before you install anything.
2. **`pytest-randomly`**, and record the printed seed on every CI failure. This is the one with the highest ratio of bugs found to config changed.
3. **A `Clock` port** on anything with a timeout, TTL, retry or schedule; `time-machine` for the code you do not own. Freeze for instants, control for durations.
4. **`Decimal` or integer minor units for money**, and if you must use `pytest.approx`, pass `abs=` explicitly — its 1e-6 relative default goes blind at **\$10,000**.

Everything here makes failures *reproducible*. Deciding what to do about the ones that remain — the trust arithmetic, quarantine, and why auto-retry hides real bugs — is [Flaky Tests](../09-flaky-tests/).

## Think about it

1. Section 2 measured the frozen clock reaching 4 of 6 behaviours, and the two it missed both *returned the value the test expected*. Design a check you could run across an existing suite that finds tests in that state — passing, fast, and asserting nothing about the duration they claim to test. What signal distinguishes them from a genuinely correct timeout test?
2. Section 3 split 1,454 wrong renewals into 1,438 timezone errors and 16 calendar errors. A colleague proposes storing every timestamp in UTC and calls the problem solved. Which of the 16 does that fix, and what would you have to add to the codebase — not to the tests — to make the other cases decidable?
3. Section 7 found that one reversed run catches every *precedence* dependency but cannot ever catch a *count* dependency. Construct a third category that neither reversal nor uniform shuffling detects efficiently, and say what sampling strategy would.
4. `runs_for(p, 0.99)` gave 182 runs for D3 at p = 1/40. Your team can afford 20 shuffled runs a night. Using that formula, what per-run detection probability can you actually cover in a week, and what does that tell you to do about dependencies rarer than that — given that section 4 showed the birthday collision rate is itself about 1 in 500 per generated value?
5. Section 5 showed UUIDv7 inverting 49.68% of pairs created inside the same millisecond — statistically indistinguishable from UUIDv4's 50.00%. Yet section 5 also recommends UUIDv7. Reconcile those two facts, and state the exact circumstance under which switching to UUIDv7 would make an existing ordering assertion *more* dangerous rather than less.

## Key takeaways

- **Determinism is a property of inputs, not of code.** A six-line pricing function with five hidden inputs — clock, environment, RNG, set iteration, a process counter — produced **6 different results across 6 ordinary machine states**; promoting all five to arguments produced **1**. Every one of those reads was correct. The bug was that the test could not see them.
- **Freezing a clock is not controlling one, and a frozen clock cannot test a timeout.** Across six behaviours the frozen clock reached **4 of 6** — and its failure on the timeout was to return the expected `False` having advanced **0.0 s**. A real clock reached 6 of 6 and billed **937 s = 15.6 minutes of sleeping for six assertions**; a controllable clock reached 6 of 6 for **0 s**. Freeze for instants, control for durations.
- **A test that reads the wall clock is 8,784 tests, and CI picks which one runs.** A wall-clock renewal implementation was wrong at **1,454 of 8,784 hours of 2024 — 16.6%**: **1,438** an hour out across a DST change and **16** a whole day out from disagreeing month clamps. The same-day-of-month property failed at **704 hours**, **572 of them at 22:00 and 23:00 UTC** — which is why the report reads "only fails at night" rather than "wrong".
- **A wall-clock reading is not an instant.** Berlin 2024-03-31 02:30 maps to **0** UTC instants and 2024-10-27 02:30 maps to **2**. A nightly job in the second window runs twice; one in the first never runs. And an annual renewal from 2024-02-29 is due 2025-02-28 only because the code decided so — otherwise `ValueError` decides.
- **A shared seed under parallel workers is worse than no seed.** Eight workers on one seed replayed one stream: **3,501 of 4,000 values duplicated, 87.52%**, with only 499 distinct. Per-worker seeding fixed the duplication and left **7 collisions**, matching the birthday model's 7.99 expected and **99.9664%** chance of at least one. Only a per-worker namespace reached **0** — uniqueness has to be a property of the design, not a probability.
- **Sorting by id is sorting by time only if the id contains the time.** UUIDv4 inverted **24,868,131 of 49,995,000 pairs — 49.74%** — and `assert first.id < second.id` failed **50.00%** of the time. UUIDv7 inverted **0** at 1 id/ms and **5.0161%** at 1,000/ms, but still **49.68%** for two ids inside one millisecond. And `assert order.id == 1` passes or fails purely on whether the schema says `AUTOINCREMENT` (id = 1 vs id = 4).
- **Collection order is a hash seed, a query plan and a row's insertion history.** Four tags in a set produced **all 24 possible orderings** across 512 hash seeds; the order your machine showed you holds on **4.30%** of them, while integer sets never move at all. In SQLite the same `ORDER BY`-less query returned `[50, 40, 30, 20, 10]` before a migration and `[10, 20, 30, 40, 50]` after `CREATE INDEX` — and `[50, 40, 20, 10, 30]` after a fixture deleted and re-inserted one row.
- **The cost of an order-dependence audit is set by the rarest dependency, not the average one.** A green-in-file-order 200-test suite gave up *some* dependency in **3 shuffled runs at 99% confidence**, but its rarest needed **182**. One reversed run caught **2 of 3 for free** — reversal breaks every precedence pair with certainty — and could never catch the third, because a count dependency (20 leakers before, 19 after, 39 needed) is unreachable from any fixed order.
- **A relative tolerance on money is a promise that gets weaker as the invoice gets bigger.** `pytest.approx`'s 1e-6 default missed a seeded one-cent error on **3 of 6 magnitudes**, going blind above **\$10,000**; `math.isclose`'s 1e-9 missed **1 of 6**; `isclose(rel_tol=0, abs_tol=0.005)` and `Decimal` each scored **0 false alarms and 0 missed bugs**.
- **The scheduler is a hidden input you cannot inject, only enumerate.** Of the 20 interleavings of two threads incrementing a counter, **18 — 90% — lose the update**, and the test passes anyway. At a per-step switch probability of 1e-4 you need **3,466 runs for an even chance** of observing it: 173 days at twenty CI runs a day, and the run that finally sees it gets closed as a flake.

Next: [Flaky Tests: The Trust Arithmetic](../09-flaky-tests/) — what a 0.2% per-test flake rate does to a 3,000-test suite, why "just re-run it" turns a real intermittent bug into an invisible one, and how to write a quarantine policy that has numbers in it.
