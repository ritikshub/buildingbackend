# Backend Engineering Glossary

Plain-language definitions of the terms that get thrown around backend
engineering — what people say vs. what they actually mean.

## A

### ABAC (Attribute-Based Access Control)
- **What people say:** "Rules based on attributes"
- **What it actually means:** Authorization decided by a boolean policy over attributes of the subject, resource, action, and context (e.g. allow if `subject.dept == resource.dept` and it's business hours). More expressive than fixed roles, at the cost of complexity.
- **Why it's called that:** Access is granted based on attributes rather than roles.

### Access Token
- **What people say:** "The token that lets an app call an API"
- **What it actually means:** A short-lived bearer credential an OAuth authorization server issues to grant the holder specific scopes at a resource server. It proves *permission*, not identity — treating it as proof of who the user is (instead of an OIDC ID token) is a classic vulnerability.

### Amdahl's Law
- **What people say:** "Diminishing returns from more cores"
- **What it actually means:** The ceiling on any optimisation: if a component is fraction `f` of total runtime and you speed it up by `k`, the whole system improves by `1 / ((1 - f) + f/k)`. Make a component that is 5% of runtime *infinitely* fast and you win 5%. Used as a budgeting tool before optimising, it prevents the classic wasted fortnight — rewriting the serialization layer that was never the bottleneck. The same formula caps parallel speedup: a 5% serial fraction means no amount of hardware exceeds 20x.
- **Why it's called that:** Named for Gene Amdahl, who argued it in 1967 against the then-popular assumption that parallelism scaled indefinitely.

### Anycast
- **What people say:** "One IP address served from everywhere"
- **What it actually means:** Announcing the same IP prefix from many locations via BGP so the network itself routes each client to the topologically nearest one. Failover is a routing change rather than a client change, which makes it far faster than DNS failover — measured against a 60-second DNS record, anycast reached 0% traffic to a dead region immediately while DNS still had 5.24% an hour later. The cost: a route change mid-connection can break in-flight TCP, so it pairs best with short connections or edge termination.
- **Why it's called that:** *Any* of the advertised locations may answer, unlike unicast (one) or multicast (all).

### Async/Await
- **What people say:** "Non-blocking syntax"
- **What it actually means:** Syntax that lets a function suspend at a marked point and resume there later, so one thread can interleave thousands of in-flight operations. `await` does **not** mean 'wait here' — it means 'I may be suspended here; run something else.' Marking a function `async` buys no concurrency by itself; concurrency comes from scheduling several coroutines at once (`gather`, task groups). Because control transfers only at `await` points, the scheduling is *cooperative*: code between two awaits is effectively atomic, and a coroutine that never awaits stalls every other one on that loop.
- **Why it's called that:** The `async` keyword marks a function as suspendable; `await` marks the points where the suspension may occur.

### Atomic Operation
- **What people say:** "It happens all at once"
- **What it actually means:** An operation no other thread can observe half-finished. The bar is *visibility of intermediate state*, not speed or line count: `counter += 1` is one line and three operations (load, add, store), so two threads can both load 41 and both store 42, losing an update. Distinct from ACID's atomicity, which is about a transaction being all-or-nothing across failures rather than about concurrent observers.

### Authentication (AuthN)
- **What people say:** "Logging in"
- **What it actually means:** Proving *who you are* by presenting a credential (password, token, key, biometric) that the system verifies, producing an identity. Distinct from authorization, and answered first. Failing it returns HTTP 401.

### Authorization (AuthZ)
- **What people say:** "Permissions"
- **What it actually means:** Deciding *what an authenticated identity may do* — a decision over (subject, action, resource, context) → allow/deny. You authenticate first, then authorize *every* access. Failing it returns HTTP 403.

### ACID
- **What people say:** "The database keeps your data safe"
- **What it actually means:** Four guarantees around a transaction — Atomicity (all-or-nothing), Consistency (never violates constraints), Isolation (concurrent transactions don't step on each other), Durability (once committed, it survives a crash).
- **Why it's called that:** An acronym coined in 1983 to name the properties reliable transaction systems already had.

### Alert Fatigue
- **What people say:** "We get too many alerts"
- **What it actually means:** A detection failure with a human in the loop. When most pages are not actionable, engineers learn — correctly — that alerts don't mean anything, and the one real page gets swiped away at 4am. It is caused by the alerts themselves, so the fix is deleting and rewriting alerts (symptoms, not causes), not adding people.

### API Gateway
- **What people say:** "The front door to your services"
- **What it actually means:** A reverse proxy that sits in front of many backend services and handles cross-cutting concerns once — auth, rate limiting, routing, TLS termination — so each service doesn't reimplement them.

### Append-Only Log
- **What people say:** "A queue that keeps the messages around"
- **What it actually means:** A broker structure that is an ordered, immutable sequence of records: writes only ever append at the end, and reads are **non-destructive** — consuming does not remove anything, because each consumer tracks its own position (**offset**). That one change gives you replay (a new service reads history from the beginning), rewind (a buggy consumer reprocesses yesterday), and many independent readers of the same data, none of which a queue can do. Retention is by time, size, or **log compaction** rather than by consumption.
- **Why it's called that:** Records are only ever appended; nothing is updated or deleted in place.

### Arrange-Act-Assert (AAA)
- **What people say:** "The three-part shape of a test"
- **What it actually means:** Build the inputs, perform exactly *one* action, then assert on that action's outcome. The shape is not decoration — it enforces **one act, one reason to fail**, because a runner reports only the first failure in a test. Measured over 24 seeded bugs, a single 14-assertion test broke 35 assertions, reported 9, and masked 26 of them (74%), at a mean 3.89 broken facts per failing run — which is the number of fix-and-rerun round trips it costs you.

### At-Least-Once Delivery
- **What people say:** "The message won't get lost"
- **What it actually means:** The broker redelivers until a consumer acknowledges, so every message arrives one *or more* times — a consumer that processes successfully and then crashes before acking will see the message again. This is the default guarantee of essentially every real broker, and the trade is explicit: duplicates instead of loss. It is only safe if consumers are **idempotent**, which is the entry fee for async, not an optimisation. Note that your test suite is the one place the duplicate never happens: a naive consumer handed each event exactly once reported 0/400 wrong balances and a green build, while the same consumer at an 8% redelivery rate got 32/400 wrong and over-credited $3,571.20 — so the test has to send the duplicate on purpose.

### At-Most-Once Delivery
- **What people say:** "Fire and forget"
- **What it actually means:** Every message arrives zero *or one* times — typically because the consumer acknowledges *before* doing the work (or the producer never retries), so a crash mid-processing silently drops it with nothing to replay. Cheapest and duplicate-free; correct only where losing an event costs less than processing one twice, such as metric samples or best-effort telemetry.

### Autospec
- **What people say:** "Making the mock match the real class"
- **What it actually means:** Building a double from the real object's inspected signature (`create_autospec`, `Mock(spec=…)`) so a call to a method that no longer exists, or with the wrong arity, raises at the call site instead of silently returning another mock. Not a style preference: across 7 real test mistakes a bare `Mock()` caught 1, `Mock(spec=…)` caught 3, `create_autospec()` caught 5 and `spec_set=True` caught 6. The one nothing catches is `m.assert_called_once` without parentheses — a bound method is truthy, so only a linter sees it.

### Availability Zone (AZ)
- **What people say:** "A separate datacenter in the same region"
- **What it actually means:** An isolated failure domain inside a cloud region with its own power, cooling and network, linked to sibling AZs at ~1-2 ms. Independent for *physical* failures only — a bad deploy, a global config push, a shared control plane or one database ignore AZ boundaries entirely, which is why "we're multi-AZ" is not by itself an availability answer.

## B

### BFF (Backend for Frontend)
- **What people say:** "A backend just for the mobile app"
- **What it actually means:** A thin backend, owned by one frontend team, that aggregates shared services and shapes the response for exactly that client — lean for mobile, wide for a dashboard. It lets a frontend iterate on its own contract without waiting on a shared API. Keep it thin: aggregation and shaping, never business logic.
- **Why it's called that:** It's a backend that exists *for* one specific frontend (coined at SoundCloud/Netflix).

### Backpressure
- **What people say:** "Slowing down when overloaded"
- **What it actually means:** A signal that flows *upstream* telling producers to stop sending because the consumer can't keep up. When arrival rate exceeds service rate there are only ever three outcomes — **buffer** (bounded, or you die of memory), **drop** (shed load deliberately), or **block** (push the wait back onto the producer) — and backpressure is choosing one on purpose instead of letting the system default to "buffer until it falls over". A broker turns it into a number you can see and alarm on: **consumer lag**.

### Blast Radius
- **What people say:** "How much breaks when it breaks"
- **What it actually means:** The fraction of users, tenants or capacity affected by a single failure. Treated as a design parameter rather than an outcome: one poison tenant on a shared fleet took down 100% of customers, the same tenant on four fixed shards took 23.65%, and on a shuffle-sharded fleet 2.63%. You cannot prevent failure; you can choose the granularity at which it lands. In a chaos experiment it is also a dial you turn, and a small setting buys most of the signal for almost none of the damage — but only for *direct* effects: 1% fault injection recovered a Mann-Whitney z of 6.2 for 2 failed requests where 100% recovered z = 22.7 for 637, while peak queue depth over the same sweep went 2 → 4 → 34 → 180, so the emergent cascade has a threshold between 5% and 25% that no small experiment will ever find. Past 25% you also lose your own control group — the *uninjected* cohort's p50 rose from 90 ms to 252 ms.

### Branch Coverage
- **What people say:** "Coverage, but stricter"
- **What it actually means:** The share of *decision outcomes* executed rather than lines — an `if` with no `else` contributes two outcomes and needs both. That gap is exactly where backend code lives: one test over a six-line shipping function measured 6/6 lines (100.0%) and 2/4 branches (50.0%), because there is no statement on the false side to leave unexecuted. Turning on `--branch` is the difference between measuring statements and measuring decisions, and it is still a metric about *execution*, not detection.

### Brittle Assertion
- **What people say:** "The test broke but nothing's wrong"
- **What it actually means:** An assertion pinned to something that is not the behaviour — an error message string, a label, a column width, a call list, a formatted total — so a refactor that changes no observable outcome turns it red. Measured: a refactor proved behaviour-identical across 8,808 cases turned 6 of 10 weak tests red and 0 of 14 well-written ones; none of the six found a bug and all six had to be rewritten by hand. Assert the amount and the exception *type*, never the message, the format, or which calls were made.

### B-Tree
- **What people say:** "How database indexes work"
- **What it actually means:** A balanced tree that keeps data sorted and lets you find, insert, and delete in logarithmic time while reading as few disk pages as possible. It's the structure under almost every relational index.

### Buffer Pool
- **What people say:** "The database's memory cache"
- **What it actually means:** A RAM cache of disk pages (Postgres: `shared_buffers`) that every read and write goes through, because disk is ~1000x slower than memory. It has a hit ratio and an eviction policy like any cache, and holds "dirty" (modified-but-not-yet-flushed) pages — which is why a committed change is durable only once its page reaches disk.

### Bulkhead
- **What people say:** "Isolate the failures"
- **What it actually means:** Giving each dependency its own pool of workers or connections so one slow dependency cannot consume every thread in the process. Without it, a single degraded downstream saturates the shared pool and takes out endpoints that never called it — the failure spreads to code that has no bug. Pairs with the circuit breaker: the breaker stops the doomed calls, the bulkhead limits the blast radius while they are still in flight.
- **Why it's called that:** From ship design: a hull divided into watertight compartments floods one section instead of sinking.

### Burn Rate
- **What people say:** "How fast we're using up the error budget"
- **What it actually means:** The multiple of the budget-consumption rate that would exactly exhaust your error budget over the SLO window. Burn rate 1 means you finish the window with the budget exactly spent; burn rate 14.4 means you'd burn a 30-day budget in about two days. Modern alerting pages on a fast burn over a short window *and* a slow burn over a long one, so brief blips don't wake anyone but a slow bleed still does.

## C

### Cell-Based Architecture
- **What people say:** "Run several complete copies of the stack"
- **What it actually means:** Replicating the entire request path into independent cells, each serving a subset of customers behind a deliberately dumb router. A failure — including a bad deploy, which no AZ boundary contains — stops at one cell. The cost is real: every cell carries its own headroom, so smaller cells mean more total waste.

### Compare-and-Swap (CAS)
- **What people say:** "Lock-free updates"
- **What it actually means:** The hardware primitive underneath every lock: atomically write a new value **only if** the current value still equals what you last read, and report whether it succeeded. Algorithms built on it retry in a loop — read, compute, CAS, repeat if someone else got there first — so no thread ever blocks, though a thread can retry many times under contention. Lock-free means *some* thread always makes progress, not that it is faster. Its classic hazard is the **ABA problem**: a value changes A→B→A between your read and your CAS, which succeeds while the world has actually moved on; the fix is a version counter alongside the value. The same idea appears one layer up as optimistic concurrency control (`UPDATE ... WHERE version = $1`).

### Concurrency vs Parallelism
- **What people say:** "Two words for the same thing"
- **What it actually means:** They are not the same. **Concurrency** is a structuring property — the program is composed of independently-progressing tasks — and it exists even on a single core, where the tasks interleave. **Parallelism** is an execution property — work is physically happening at the same instant — and it requires multiple cores. An event loop handling 10,000 sockets is highly concurrent and not parallel at all. The distinction decides your tooling: concurrency solves *waiting*, parallelism solves *computing*.
- **Why it's called that:** Rob Pike's framing: concurrency is dealing with many things at once; parallelism is doing many things at once.

### Condition Variable
- **What people say:** "Wait until something is true"
- **What it actually means:** A primitive for sleeping until a predicate becomes true, without burning CPU polling it. It owns a lock; `wait()` atomically releases that lock and sleeps, and reacquires it before returning, which closes the window where the state could change while you were falling asleep. The rule everyone gets wrong: **always wait in a `while` loop on the predicate, never an `if`** — a wake-up is a hint that the state *might* have changed, not a promise, because of spurious wakeups and because another thread may consume the condition before you reacquire the lock.

### Context Switch
- **What people say:** "The CPU switches tasks"
- **What it actually means:** Saving one execution context (registers, program counter, stack pointer) and restoring another so a different thread can run. The direct cost is microseconds — kernel entry plus register save/restore, plus page-table and TLB work if it is a *process* switch. The larger, invisible cost is indirect: the incoming thread's working set evicts the outgoing one's from cache, so the next few thousand instructions run slower. This is why thread-per-connection collapses at scale — at ten thousand mostly-idle threads the machine spends its time switching rather than working.

### Coordinated Omission
- **What people say:** "The load test said p99 was fine"
- **What it actually means:** The measurement error that makes most published latency numbers fiction. A load generator that waits for each response before sending the next sends **nothing** while the server is stalled — so exactly the requests that would have experienced the worst latency are never issued and never recorded. The resulting distribution systematically omits the samples you care about, and corrected percentiles are routinely an order of magnitude worse. The fix is to schedule each request at an *intended* start time derived from the target rate and measure latency from that intended time, not from when you managed to send it.
- **Why it's called that:** Named by Gil Tene: the load generator inadvertently *coordinates* with the system under test, backing off exactly when it should be applying pressure.

### Coroutine
- **What people say:** "A lightweight thread"
- **What it actually means:** A function that can suspend mid-execution and be resumed later with its local variables and instruction pointer intact — its stack frame outlives the suspension instead of dying at `return`. Not a thread: coroutines are scheduled cooperatively by a runtime rather than preemptively by the kernel, they cost hundreds of bytes rather than megabytes of stack, and thousands run on one OS thread. A coroutine object is inert until something schedules it, which is why a forgotten `await` silently does nothing at all.

### CORS (Cross-Origin Resource Sharing)
- **What people say:** "The thing that blocks my API calls"
- **What it actually means:** A browser mechanism letting a server opt in to which *other* origins may read its responses, relaxing the Same-Origin Policy. It's enforced by the browser and protects browsers, not your server — it is not access control, and `Access-Control-Allow-Origin: *` with credentials is a hole.

### Critical Section
- **What people say:** "The part you lock"
- **What it actually means:** The region of code where a data invariant is temporarily false — where the money has left one account but not yet arrived in the other. Concurrency does not create the bug; it exposes this window to other threads. The discipline: identify the invariant first, make the lock cover the *entire* window (a lock that stops one instruction short is the most common real bug), keep it as short as possible, and never do I/O, acquire a second lock, or call unknown code inside it.

### CSRF (Cross-Site Request Forgery)
- **What people say:** "A malicious site acting as you"
- **What it actually means:** An attack abusing the browser's auto-attaching of cookies to any request to a site, so a malicious page triggers an authenticated state-changing request (the attacker never reads the response). Defended with `SameSite` cookies and unforgeable CSRF tokens.

### Credential Stuffing
- **What people say:** "Bots trying leaked passwords"
- **What it actually means:** Replaying `email:password` pairs leaked from *other* breaches against your login at scale; password reuse makes a small fraction succeed. The attacker holds *correct* passwords, so strong hashing barely helps — MFA and breach-password screening do.

### Cross-Site Scripting (XSS)
- **What people say:** "Injecting JavaScript into a page"
- **What it actually means:** Getting attacker-controlled data interpreted as code in a victim's browser, so a script runs as your origin and can read the DOM, tokens, and non-`HttpOnly` cookies. Root cause: untrusted data not encoded for its output context. Defended with output encoding and a Content-Security-Policy.

### CAP Theorem
- **What people say:** "You can only pick two of consistency, availability, partition tolerance"
- **What it actually means:** When the network partitions (and it will), a distributed system must choose between staying Consistent (reject requests it can't confirm) or staying Available (answer with possibly-stale data). Partition tolerance isn't optional, so the real choice is C vs. A during a partition.

### Cache-Aside
- **What people say:** "The app checks the cache first"
- **What it actually means:** The dominant caching pattern: on a read, look in the cache; on a miss, read the database, store the result in the cache, and return it. The application orchestrates the cache "on the side," so a cache outage degrades to slower reads instead of an error. On a write, update the DB then *delete* the cached key.

### Cache Hit Ratio
- **What people say:** "How often the cache works"
- **What it actually means:** Hits ÷ total lookups. The number a cache lives or dies by — and its payoff is non-linear: because misses cost far more than hits, raising the ratio from 90% to 99% can nearly quadruple average speed by eliminating the rare, expensive miss.

### Cache Stampede
- **What people say:** "The cache broke under load"
- **What it actually means:** A popular cached key expires and hundreds of concurrent requests all miss at once, hammering the database to recompute the same value simultaneously. Fixed with locks, request coalescing, or early/probabilistic refresh.

### Canary Analysis
- **What people say:** "Ship to 1% and watch the dashboard"
- **What it actually means:** Comparing a canary release's metrics against a baseline — which is a **hypothesis test** whether or not you write it as one, and writing it as a fixed threshold ("fail if errors are 50% above baseline") does the statistics badly rather than avoiding them. Measured against a genuine 1.0-point regression, the naive threshold false-alarmed on 33.1% of runs at 200 requests per arm and 0.0% at 100,000, while a z test held between 1.9% and 5.5% at every volume. A threshold is a false-alarm rate you did not choose; it is a property of your sample size, not of your service. Detecting that regression at 80% power needs 1,200 requests per arm, or a median of 305 with Wald's sequential test (Wald, *Sequential Analysis*, 1947).

### Canonical Log Line
- **What people say:** "One fat log line per request"
- **What it actually means:** Instead of scattering a dozen narrow log lines through a request, you accumulate context as it runs and emit exactly one wide event at the end — route, status, duration, user tier, db time, cache hits, trace ID, thirty fields. It's cheaper (one write, not twelve), more queryable (every fact is on the same row), and it makes a log store behave a lot like an analytics database.

### Cardinality
- **What people say:** "How many distinct values there are"
- **What it actually means:** In a time-series database, the number of distinct **series** — the product of how many distinct values each tag/label can take. It's the metric a TSDB lives or dies by: put a high-cardinality value (`user_id`, `request_id`, an email) in a tag and you spawn one series per value, exploding memory and taking the database down. (More generally: the count of distinct values in a column — low for `status`, huge for `email`.)

### CDN (Content Delivery Network)
- **What people say:** "It makes the site load faster worldwide"
- **What it actually means:** A globally distributed fleet of caching servers (edges) in Points of Presence near users. Requests hit the nearest edge instead of your distant origin, turning a cross-ocean round trip into a few milliseconds and offloading most traffic from origin. Controlled almost entirely via HTTP caching headers.

### Change Data Capture (CDC)
- **What people say:** "Streaming every change out of the database"
- **What it actually means:** Tailing the database's **write-ahead log** so every committed insert, update, and delete streams out to other systems (a search index, a cache, a data warehouse) with no change to application code. It costs nothing at write time and cannot miss a change, because it reads the log the database already writes for durability — but it exports *rows, not intent*: a consumer sees `status` go from `2` to `3`, never `OrderShipped`, and is now coupled to your physical schema, so a column rename becomes a breaking change downstream. Tools like Debezium turn that durability log into the integration backbone that keeps derived stores in sync in a polyglot system; compare the **outbox pattern**, where you get to choose the event's shape.
- **Why it's called that:** It captures the data changes, straight from the log, as they happen.

### Chaos Engineering
- **What people say:** "Breaking things in production on purpose"
- **What it actually means:** An experiment, and nothing about it is chaotic: define a steady state as a measurable *output*, hypothesise it holds in both the control and the experimental group, inject a fault that reflects a real-world event, try to **disprove** the hypothesis, and minimise the blast radius throughout (Basiri et al., *Chaos Engineering*, IEEE Software 33(3), 2016). Injecting a fault without having written down what you expected is not an experiment — it is an outage with an audience. Latency is the highest-value injection and the one staging has never produced: killing a dependency cost 0 minutes of error budget where making the same dependency 5× slower cost 130.7. It finds emergent failures only — nothing here catches a `<` that should be `<=`.

### Characterization Test
- **What people say:** "Pinning down what the legacy code does"
- **What it actually means:** A test that asserts nothing about what code *should* do and instead records what it *does*, bugs included, so any change to that behaviour shows up as a failure (Feathers, *Working Effectively with Legacy Code*, 2004). It is a tripwire, not a specification, and its power is entirely the corpus: a 120-case recording caught an accidental off-by-one in a date clamp on 4 cases (3.3%), while a 20-case recording caught 0 and would have shipped the regression. Delete it once real tests exist, or it pins the bugs in place along with the behaviour.

### Choreography vs Orchestration
- **What people say:** "Events versus a workflow engine"
- **What it actually means:** The two ways to drive a multi-service workflow. In **choreography** each service reacts to events and emits its own, with no central controller — maximally decoupled, but no single place knows the state of the flow, so "where is order 4471 stuck?" is answered by reconstructing it from logs across six services. In **orchestration** one coordinator explicitly invokes each step and owns the state machine — legible, queryable, and retryable, at the cost of a component that must know about everyone. Choreography scales the org chart; orchestration scales your ability to debug.
- **Why it's called that:** Dancers who each know their own steps versus a conductor directing the players.

### Claim Check
- **What people say:** "Put the big file in S3 and send the link"
- **What it actually means:** A pattern for oversized payloads: write the body to object storage and put only a reference — plus a hash and whatever metadata consumers filter on — in the message. Brokers cap message size (commonly around 1 MB) and large payloads wreck throughput, retention cost, and replay time. The price is that the message is no longer self-contained: the blob must outlive the topic's retention, and deleting it early turns a replayable log into a broken one.
- **Why it's called that:** Like a coat-check ticket — you hand over the stub, not the coat.

### Compensating Transaction
- **What people say:** "Undoing a step"
- **What it actually means:** A *new, forward* transaction that semantically negates an already-committed one — refund a charge, release a reservation, cancel a shipment — used because no distributed rollback exists once another service has committed. It is not a rollback in any real sense: the intermediate state was visible to everyone who looked, some actions have no true inverse (an email is sent), and the compensation must itself be idempotent and retryable because it can fail too. See **Saga**.

### Connection Pool
- **What people say:** "Reusing database connections"
- **What it actually means:** A fixed set of open connections kept ready and handed out to requests, because opening a new TCP+TLS+auth handshake per query is slow and databases cap total connections. The pool size is one of the most common production bottlenecks.

### Consistent Hashing
- **What people say:** "How distributed caches and databases spread keys across nodes"
- **What it actually means:** A scheme that maps both keys and nodes onto a hash **ring**, so a key belongs to the next node clockwise. Adding or removing a node moves only ~`1/N` of the keys (the slice beside it) instead of nearly all of them, the way plain `hash(key) % N` would. It's why key-value and wide-column clusters grow from three nodes to three hundred without a full reshuffle.
- **Why it's called that:** The mapping stays consistent — most keys keep their node — as the cluster changes size.

### Constraint
- **What people say:** "A rule on a column"
- **What it actually means:** A rule declared in the schema that the database enforces on every write — `NOT NULL`, `UNIQUE`, `CHECK`, or a foreign key — so invalid data is rejected no matter which app or query attempts it. The database is the one chokepoint every write passes through, making it the only place an invariant is truly guaranteed rather than merely hoped for.

### Consumer Group
- **What people say:** "The consumers reading the same topic"
- **What it actually means:** A named set of consumers that share one subscription and divide the partitions among themselves, so a message is processed once *per group* while every group keeps its own independent offsets and its own copy of the stream. This is the mechanism that lets a single log behave as both a queue (add members to one group to parallelise work) and as **pub/sub** (add groups to fan out). Its hard ceiling: useful members can never exceed partitions — extra consumers sit idle holding nothing.

### Consumer Lag
- **What people say:** "How far behind the consumer is"
- **What it actually means:** Two different numbers people conflate. **Count lag** is the number of messages between the consumer's committed offset and the end of the log — cheap, but "50,000" is meaningless without a drain rate. **Time lag** is the age of the oldest unprocessed message, i.e. how stale the consumer's view of the world is, and it's the one to page on, because your promises to users are stated in seconds, not messages. Either way the derivative matters more than the value: lag that rises steadily means arrival rate exceeds service rate, and waiting will never fix it.

### Consumer-Driven Contract
- **What people say:** "The consumer writes the test the provider runs"
- **What it actually means:** The flip that makes contract testing work: each consumer's own suite records the interactions it actually depends on, publishes that recording, and the *provider's* CI replays it and fails the provider's build. The contract therefore records **usage, not schema**, which is why it does not obstruct the provider — measured, a consumer constrained 4 of the provider's 11 top-level fields with 6 matching rules on type and pattern, so a build growing the response from 11 fields to 14 verified 3/3 while a build renaming one *used* field failed 2 of 3 with `$.total_cents: MISSING from the provider response`.

### Contract Testing
- **What people say:** "Testing the seam between two services"
- **What it actually means:** Verifying each side of an integration against a shared recorded contract, separately, instead of standing up every service at once. The shared environment loses on combinatorics and on availability rather than on effort: 11 services at 3 live versions each is 177,147 whole-system combinations against 19 contracts (9,324×), and an environment where each member is healthy 92.6% of the time answered on only 42.4% of days with a 52-day longest red streak. It is not the strongest gate, it is the strongest gate that always runs — weighted by that availability, end-to-end scored 1.69/6 defects per attempt against the contract's 3/6, every time. And it is structural, so it stops at meaning: a field redenominated from cents to dollars round-tripped 400/400 with verdict FULL while the consumer computed 1,857,277 where the provider meant 185,747,545.

### Correlation ID
- **What people say:** "The request ID in the logs"
- **What it actually means:** An identifier generated once at the edge and propagated through every service, thread, and queue a request touches, then stamped onto every log line and span it produces. Without it you have three haystacks; with it you can pull one request's entire story across forty machines with a single filter. In modern systems it's the **trace ID** from the W3C `traceparent` header.

### Coverage-Guided Fuzzing
- **What people say:** "Smart fuzzing"
- **What it actually means:** Fuzzing with memory: instrument the target, keep any input that reached a branch no earlier input did, and mutate onward from that corpus (the AFL insight). It is not a better source of randomness — it is retained near misses. Against a parser whose crash needs two conditions in one input, guided mutation crashed in 888 executions against 6,846 for random printable ASCII and 21,085 for uniform random bytes, while *losing* the race to every individual branch. All three found the same 13 branches; only one could stack two of them.

### Cursor Pagination
- **What people say:** "Pagination that doesn't break when data changes"
- **What it actually means:** Paging by a stable, unique sort key ("rows after this row") instead of a numeric offset. A composite-index seek makes every page cost the same regardless of depth, and it never duplicates or skips rows when the collection changes underneath you — the failure mode of offset pagination. The client carries an opaque cursor (the last row's sort keys) to fetch the next page.
- **Why it's called that:** The cursor marks your position in the result's key space, like a cursor in a file.

## D

### DataLoader
- **What people say:** "The thing that fixes GraphQL N+1"
- **What it actually means:** A per-request helper that batches all the individual `.load(key)` calls made in one execution tick into a single backend query, and caches results per request — turning 1 + N queries into 2. It must be instantiated **per request** so one user's cache never leaks into another's.
- **Why it's called that:** It loads data, in batches, on behalf of many independent resolvers.

### DDL & DML
- **What people say:** "SQL commands"
- **What it actually means:** The two halves of SQL. **DDL** (Data Definition Language) defines *shape* — `CREATE`, `ALTER`, `DROP TABLE`. **DML** (Data Manipulation Language) works with *data* — `SELECT`, `INSERT`, `UPDATE`, `DELETE`. DDL changes the schema; DML changes the rows.

### Dead Time
- **What people say:** "The autoscaler reacts too late"
- **What it actually means:** In a control loop, the delay between acting and being able to observe the effect. For autoscaling it is metric scrape + aggregation window + decision interval + boot + warmup — commonly 3-6 minutes. A loop whose dead time exceeds its reaction period **cannot** stabilise; it oscillates. Measured on a flat traffic plateau, 0 s of dead time held the fleet steady while the cloud-default 210 s swung it between 6 and 145 instances and launched 539 machines to do the work of 33.
- **Why it's called that:** From process control: the interval in which the loop is blind, acting on stale information.

### Dead-Letter Queue (DLQ)
- **What people say:** "Where failed messages go"
- **What it actually means:** A separate queue the broker moves a message into once it exceeds a redelivery limit, so one permanently-failing message stops consuming retries forever and stops blocking the pipeline behind it. It converts an infinite retry loop into a bounded one plus a bug report — but only if it is monitored and drained; an unwatched DLQ is silent data loss with extra steps. Messages should land there with the failure reason and delivery count attached, and replaying them after the fix is a first-class operation you build in advance, not a script someone improvises mid-incident.

### Deadlock
- **What people say:** "Everything froze"
- **What it actually means:** Two or more threads each holding a resource the other needs, waiting forever. There is no exception, no CPU usage, and no log line — the process looks healthy and simply stops, which is why health checks keep returning 200 through an outage. It requires all four **Coffman conditions** simultaneously (mutual exclusion, hold-and-wait, no preemption, circular wait), and because all four are required, breaking any *one* prevents it. The standard fix is a global lock ordering — always acquire in the same order — which makes circular wait impossible by construction. Databases take the other route: detect the cycle in a wait-for graph and abort a victim, which is why your application must expect and retry deadlock errors.

### Determinism (Testing)
- **What people say:** "The test gives the same answer every time"
- **What it actually means:** A property of a function's *inputs*, not of its code — every input the test cannot see is one CI picks for you. Measured: a six-line pricing function with five hidden inputs (clock, environment variable, RNG, set iteration order, a process counter) produced 6 different results across 6 ordinary machine states; promoting all five to arguments produced 1. Every one of those reads was correct code — the bug is that the test could not set them. The catalogue is short and worth memorising: the clock, the timezone, `random`/`uuid4`, `os.environ`, set and dict iteration order, filesystem order, the database's own clock and sequences, locale, the host, and the scheduler.

### Deterministic Subsetting
- **What people say:** "Each client only connects to some of the backends"
- **What it actually means:** Assigning every client a subset of backends such that each backend receives an almost exactly equal number of clients — clients are grouped into rounds and each round shuffles the backend list seeded by the round number. Random subsetting strands backends with zero clients; deterministic subsetting measured a standard deviation of 0.00 and a 1.00× imbalance. It is the standard fix for the N×M connection explosion.

### Differential Testing
- **What people say:** "Compare the fast version against the slow one"
- **What it actually means:** When you cannot state a property, state an *equivalence*: write the obvious, unmistakably-correct implementation and assert the real one agrees with it on every generated input. It asserts nothing about what the function does and everything about whether the optimisation was safe — usually the actual question. The whole result depends on the generator: the same `<`-should-be-`<=` bug in an interval merger took 4 cases to find with coordinates drawn from 0..20 and 35,648 from 0..1,000,000, an 8,912× spread with nothing else changed. The trap is writing the slow version by deleting the optimisation from the fast one — then you have two implementations of the same misunderstanding and the agreement is guaranteed.

### Dual-Write Problem
- **What people say:** "Keeping two databases in sync is hard"
- **What it actually means:** When an application writes the same change to two stores (a database and a search index, say) there is **no transaction spanning both**, so if one write succeeds and the other fails, the two disagree permanently — and simply ordering the writes can't close the gap. The reliable fixes remove the second synchronous write: the **outbox pattern** (commit the change and an event atomically, then a relay publishes) or **CDC**.

## E

### Envelope Encryption
- **What people say:** "Encrypting a key with another key"
- **What it actually means:** Encrypt data with a per-data Data Encryption Key (DEK), then wrap the DEK with a Key Encryption Key (KEK) that never leaves a KMS; store ciphertext and wrapped DEK together. A stolen database holds only wrapped DEKs (useless without KMS), and you rotate the KEK by re-wrapping small DEKs instead of re-encrypting everything. The pattern behind every cloud KMS.

### epoll / kqueue
- **What people say:** "The fast way to watch sockets"
- **What it actually means:** Kernel interfaces that tell one thread which of thousands of file descriptors can be read or written without blocking. They replaced `select`/`poll`, where the caller re-passes the entire watch set on every call and both sides scan it — O(n) in the number of *watched* descriptors, plus a hard 1024 limit for `select`. `epoll` (Linux) and `kqueue` (BSD/macOS) separate registration from waiting and maintain a ready list in the kernel, so a wait costs O(*ready*) instead. This is the mechanism that made one-thread-serves-10,000-connections practical. Note they signal **readiness** ('you may now read'), not **completion** ('the data is already in your buffer') — the latter is what IOCP and `io_uring` provide.

### Equivalent Mutant
- **What people say:** "The mutant no test can kill"
- **What it actually means:** A seeded change that is syntactically different and semantically identical, so nothing can detect it and it survives forever — which is why a 100% mutation score is not a target but a category error. Deciding equivalence in general reduces to program equivalence and is undecidable (Jia & Harman, IEEE TSE 37(5), 2011, treat it as the field's central open problem); a finite probe set can prove a mutant *killable* but never prove one equivalent. Measured: three survivors were indistinguishable from the original across 302 probe calls and then confirmed by hand, putting that module's real ceiling at 95.7% — which the best suite reached exactly.

### ETag (Entity Tag)
- **What people say:** "A version tag for caching"
- **What it actually means:** An opaque id (usually a content hash) the server attaches to a response. A cache echoes it back on `If-None-Match`; if it still matches, the server replies `304 Not Modified` with no body — revalidating a large unchanged resource for a few hundred bytes instead of re-downloading it.

### Event Loop
- **What people say:** "How async works under the hood"
- **What it actually means:** A single thread running one cycle forever: compute how long it may sleep (until the nearest timer, or not at all if callbacks are already queued), ask the OS which file descriptors are ready, collect the callbacks for those events plus any expired timers, run them, repeat. Because there is exactly one thread, shared state needs far fewer locks — and any callback that blocks or merely runs long stalls *every* other connection. The damage shows up as latency on requests that had nothing to do with the slow one, which is why **loop lag** is the metric that names the culprit.

### Event Sourcing
- **What people say:** "Storing events instead of state"
- **What it actually means:** Making the append-only sequence of state-changing events the **system of record**, with current state derived by replaying them into a projection (snapshotted, so a read isn't O(all history)). You get a perfect audit log by construction, time travel, and the ability to build a brand-new read model from history — and you pay in schema evolution over events you can never rewrite, no `UPDATE` or `DELETE`, and a query story that depends entirely on projections you maintain yourself. Routinely confused with merely *publishing* events from an ordinary CRUD service, which is not event sourcing — the test is whether you could drop the state table and rebuild it.

### Eventual Consistency
- **What people say:** "It'll be consistent... eventually"
- **What it actually means:** After a write, replicas may disagree for a while, but if writes stop, they all converge to the same value. The trade you accept to stay available and fast across many nodes.

### `eventually()` (Polling Assertion)
- **What people say:** "Wait for the async thing to happen"
- **What it actually means:** Re-checking a condition on a short interval until it holds or a generous deadline expires — which beats a fixed `sleep` on *both* axes at once rather than trading one for the other, because a passing test pays its own latency instead of the worst case. Measured over 200 builds of a 500-test suite, `eventually(10 ms, 10 s)` finished in 30.7 s at a 0.000% flake rate and 200/200 green, at 5.6 polls per test — 49× faster than the only fixed sleep that was actually safe. The failure message is the feature: keep the *last* exception and add a diagnostic probe, or five genuinely different broken systems all report the same one useless line (measured: 1 distinct message of 5, against 5 of 5).

### Exactly-Once Delivery
- **What people say:** "The message is delivered exactly once"
- **What it actually means:** Usually a lie at the transport layer — when an acknowledgement can be lost, the sender cannot distinguish "not processed" from "processed, ack lost," so it must pick retrying (**at-least-once**) or not (**at-most-once**). "Exactly-once *processing*" is real, and is achieved by making consumers idempotent — dedup on a message id, or commit the offset and the side effect in one transaction — not by the queue magically never redelivering. Vendor "exactly-once" is genuine only inside the broker's own boundary (read-process-write within one log) and says nothing about the email you sent or the third-party API you called.

### Error Budget
- **What people say:** "How much downtime we're allowed"
- **What it actually means:** `100% − SLO`, expressed as a quantity of allowed badness over a window — 99.9% over 28 days is about 40 minutes, or 10,000 failed requests out of 10 million. The point isn't the number, it's the reframe: the budget is a currency you spend on velocity. Budget left means ship and take risks; budget gone triggers a pre-agreed freeze. It converts "how reliable should we be?" from a values argument into arithmetic both sides agreed to beforehand.

### Exemplar
- **What people say:** "Clicking the graph takes you to a trace"
- **What it actually means:** A trace ID attached to a specific metric observation (usually a histogram bucket), which is how an aggregate number gets a link back to one concrete request. It's the bridge across the pillars: metrics can't identify an individual by design, so an exemplar keeps a handful of pointers to individuals that landed in each bucket.

## F

### Failure Domain
- **What people say:** "Things that die together"
- **What it actually means:** A set of components that share a fate because they share a dependency — a rack, an AZ, a region, but equally a deploy pipeline, a config push, a feature-flag service or one database. The non-physical domains cause the largest outages precisely because they cut across every physical boundary you paid for.

### Failure Localisation
- **What people say:** "Unit tests tell you where the bug is"
- **What it actually means:** How much code a single red test implicates — the transitive call closure of its entry point, which is a lower bound on the search. It is the only thing that justifies unit tests once detection has saturated. Measured on one service's call graph: a failing end-to-end test implicates 369 lines across 4.7 architectural layers — a fifth of the codebase — against a unit test's 28 lines in 1, which is 3.7 extra bisection halvings and 50.3 versus 9.3 minutes to diagnose. The advantage is real and *logarithmic*, not the order of magnitude folklore claims.

### Fake
- **What people say:** "A stub, basically"
- **What it actually means:** A working implementation with a shortcut — an in-memory repository, an in-process queue — and the only test double that has **state**, which is why it is the only one that can answer "was this customer charged twice?". Measured: identical assertions killed 2 of 10 seeded bugs over a stub and 7 of 10 over a fake, because a stub has nowhere to record the amount, the currency, or the second charge. Default to a fake plus a contract suite run against both it and the real thing; a fake without one is still a second implementation verified by nobody.

### Fan-Out
- **What people say:** "Sending a message to lots of consumers"
- **What it actually means:** One published message being delivered to N independent subscribers, each with its own copy, its own position, and its own failure domain — the defining property of a **topic** as opposed to a queue. The broker does N deliveries, so cost scales linearly with subscribers and one slow subscriber never slows the others. In feed and timeline design the same term names a different choice: **fan-out on write** copies an item into every follower's timeline at publish time (cheap reads, pathological for an account with 50 million followers) versus **fan-out on read**, which stores once and assembles per reader.

### Fixture
- **What people say:** "The test data setup"
- **What it actually means:** The data that must be in place before a test can run — and the only design question is whether each test states its own preconditions or inherits a shared seed. Sharing does not cause the damage; it makes the requirement *invisible*, so the only way to learn what a change breaks is to make it and count the corpses. Measured on the same 240-test suite: adding a third order to `user_id = 1` turned 52 tests (21.7%) red under a shared seed and 0 under per-test factories, with only 57 of 4,353 seeded rows (1.31%) load-bearing at all — the ballast is free, the head of the distribution is not.

### Flaky Test
- **What people say:** "It fails sometimes, just re-run it"
- **What it actually means:** A test that gives different verdicts on the same commit — an observation, not a cause, and it says nothing about which side of the test boundary the non-determinism lives on. A per-test rate is a per-build catastrophe because it compounds: `P(green) = (1 − f)^n`, so 0.2% across 3,000 tests gives a 0.25% green-build rate, and a 95% green build at that size demands every test be reliable to 1 flake in 58,488 runs. The damage is informational — at that rate `P(bug | red)` is 5.01% against a 5% prior, 0.003 bits against a deterministic suite's 4.322, a 1,420× collapse — so engineers who stop investigating are being correctly Bayesian, not lazy. Flakiness is strictly one-sided (`P(clean | green)` measured 99.4764% at *every* flake rate), which is why the fix is the delivery channel: blanket `--reruns 2` reports a race manifesting 3% of the time at 0.0027%, one build in 37,037, while retrying only on infrastructure error signatures found 6 of 6 real races.

### Flame Graph
- **What people say:** "The performance picture"
- **What it actually means:** A visualization of sampled stacks: each box is a frame, its **width** is the proportion of samples containing it, and the y-axis is stack depth. The x-axis is **not time** — frames are sorted alphabetically so identical stacks merge — so wide plateaus, not left-to-right position, are where the time goes. Underneath it is nothing exotic: a text file of `semicolon;separated;stacks count`. Differential flame graphs colour a before/after diff, which is the fastest way to see what a change actually did.
- **Why it's called that:** Named for the shape: hot, wide plateaus with flickering narrow frames above them.

### Foreign Key
- **What people say:** "A link between tables"
- **What it actually means:** A column that references another table's primary key, and which the database *enforces*: every foreign-key value must point at a row that exists (referential integrity). It's how relationships between tables become real and un-break-able — no orphan rows pointing at things that don't exist.

### Frozen Clock vs Controllable Clock
- **What people say:** "Just freeze time in the test"
- **What it actually means:** Two different tools. A **frozen** clock answers `now()` with a constant, which tests every "what is true at instant T" assertion and cannot let time pass *inside one call* — so a frozen clock cannot test a timeout. Measured across six time-dependent behaviours it reached 4 of 6, and its failure on the timeout was to return the expected answer having advanced 0.0 s, meaning that test would pass just as happily with the timeout deleted. A **controllable** clock adds one method, `advance(seconds)`, and reached 6 of 6 in 0 seconds against a real clock's 937 s (15.6 minutes) of sleeping for the same six assertions. Freeze for instants, control for durations — timeouts, retries, backoff ladders, TTL sweeps and lease renewals are all durations.

### Functional Core, Imperative Shell
- **What people say:** "Keep the business logic pure"
- **What it actually means:** Push every I/O operation to the edges of a call and keep the *decisions* in the middle, taking values and returning values. The part most explanations skip: the shell does not call the core once in the middle, it **interleaves** — load, read the clock, decide, do I/O, read the clock again, decide again — so a core is a set of pure functions, not a layer. Measured, fourteen tests with the same names and the same assertions killed 57.8% of seeded mutants through the legacy function (at 112 real I/O operations) and 73.4% against the core (at 0), a +15.6-point gain bought purely by being allowed to choose the FX rate and the instant; the refactor itself was proved behaviour-identical on 240 of 240 generated cases.

### Fuzzing
- **What people say:** "Throwing random garbage at it"
- **What it actually means:** Property testing where the input is bytes and the property is "do not crash" — older than the vocabulary around it and embarrassingly effective: Miller, Fredriksen and So (*An Empirical Study of the Reliability of UNIX Utilities*, CACM 33(12), 1990) fed pseudo-random character streams to 88 utilities across seven UNIX variants and crashed or hung 25–33% of them, with no models and no cleverness. Aim it at the code that turns bytes from someone who is not you into structure; already-validated objects are a poor fuzz target and an excellent property-test target.

## G

### GIL (Global Interpreter Lock)
- **What people say:** "Python can't do threads"
- **What it actually means:** A single mutex that a CPython thread must hold to execute bytecode, so CPU-bound threads take turns rather than running in parallel. It exists because CPython's memory management uses non-atomic reference counting. The nuance that matters: the GIL is **released** around blocking I/O syscalls, `time.sleep`, and many C extensions — so threads still give near-linear speedups on I/O-bound work while giving essentially none on pure Python computation. It is a CPython implementation detail, not a property of the language, and the free-threaded build (PEP 703) removes it. Removing it removes the bytecode serialization, *not* the need for locks — races and deadlocks become more likely, not less.

### Golden File (Approval Test)
- **What people say:** "Snapshot testing"
- **What it actually means:** Inverting the usual arrangement — record the output and assert it has not changed, rather than writing an assertion. It is the cheapest thorough check for anything with a big structured output, and the only fixture whose *review* is the test, which makes the serialisation format load-bearing: the same benign one-field change costs 32× more characters to read as one-line JSON than pretty-printed with sorted keys. One volatile field destroys it — put a `generated_at` timestamp in the golden and a real VAT regression arrives as 60 of 60 files changed, 1 of them real, a 3.3% signal ratio, which is how a genuine regression gets waved through by an accept-all.

### Golden Signals
- **What people say:** "The four things you should always monitor"
- **What it actually means:** Latency, traffic, errors, and saturation — Google's SRE answer to "which metrics do I even create?" Latency should be split by success and failure (a fast 500 flatters your latency graph during an outage), and saturation is the predictive one: how full the constrained resource is, which tells you about the outage you're *about* to have.

### Goodput
- **What people say:** "Successful throughput"
- **What it actually means:** The rate of responses that are both correct **and** delivered within their deadline — as opposed to throughput, which counts everything the server emitted. Under overload the two diverge violently: a system 'handling 10,000 rps' while every response arrives after the client gave up has a goodput of zero. Measuring goodput instead of throughput is what makes load shedding look like the improvement it is, since dropping work you cannot finish in time *raises* the number of users you actually serve.

### GraphQL
- **What people say:** "One endpoint where the client asks for exactly the fields it wants"
- **What it actually means:** A typed query language and runtime for APIs: the client sends a selection tree, the server resolves it field by field and returns matching JSON. It fixes over- and under-fetching, but trades away easy HTTP caching and hands clients a query planner you must bound with depth and cost limits. Best understood as a generalized, declarative BFF.
- **Why it's called that:** Queries traverse a graph of related types.

### Grey Failure
- **What people say:** "It's not down, it's just slow"
- **What it actually means:** A dependency that keeps answering correctly and answers late — the failure mode your defences are least prepared for, because every one of them counts *errors*. Measured over an identical 20-second window: killing a dependency outright cost 0 failed requests and 0.0 minutes of error budget (the error hit a fallback somebody wrote), while making the same dependency 5× slower cost 2,744 failed requests, 130.7 minutes of budget, a user-visible p50 of 2,006 ms, and a recovery that arrived 21 seconds after the fault was already gone. The circuit breaker built for that dependency tripped 10 times on the kill and 0 on the slowdown, and it is not broken — slow is not an error until a timeout makes it one.

## H

### Hedged Request
- **What people say:** "Send it twice and take the fastest"
- **What it actually means:** Issue a request to one replica; if no answer arrives by roughly its p95 latency, issue a second copy elsewhere and take whichever returns first. Because only ~5% of requests are ever hedged the extra load is small while the tail collapses — measured, a 100-way fan-out went from p99 1583.9 ms to 116.5 ms for +5.0% load. Requires idempotency and a hedge budget: unbudgeted hedging under overload measured a 95.2% hedge rate and made p99 **20× worse**.

### HMAC (Hash-based Message Authentication Code)
- **What people say:** "A signature with a shared secret"
- **What it actually means:** A keyed hash (RFC 2104) that proves a message's integrity *and* authenticity — only a holder of the shared secret can produce or verify a valid tag, and it's verified in constant time. The workhorse behind signed JWTs (HS256), API request signing, webhook verification, and tamper-proof session cookies.

### HATEOAS (Hypermedia as the Engine of Application State)
- **What people say:** "APIs that include links to what you can do next"
- **What it actually means:** The Richardson level-3 REST idea that a response embeds links describing the available next actions, so a client discovers state transitions from the payload instead of hardcoding URLs. Elegant but rare; most APIs stop at level 2.
- **Why it's called that:** Hypermedia (the links in the response) drives the client through application state.

### Head-of-Line Blocking
- **What people say:** "One slow item holds up everything behind it"
- **What it actually means:** When a strict ordering guarantee forces a stuck item to block every independent item queued behind it. In messaging it is the direct, unavoidable price of ordering: one **poison message** halts its entire partition's backlog, which is why per-key ordering across many partitions beats global ordering — you shrink the blast radius of a stuck message to one key. The same pathology appears in HTTP/1.1 pipelining and in TCP under packet loss, which is most of why HTTP/3 runs over QUIC.
- **Why it's called that:** The item at the head of the line blocks everyone standing behind it.

### Health Check
- **What people say:** "The endpoint that says if the service is up"
- **What it actually means:** An API for machines, not humans, and it's really two different questions. **Liveness** asks "is this process irrecoverably broken?" and failure means *restart* — so it must be shallow and must never check dependencies, or a 30-second database blip restarts your whole fleet at once. **Readiness** asks "should this instance get traffic right now?" and failure means *remove from the load balancer*, which is reversible and is where dependency checks belong.

### Heap File
- **What people say:** "Where a table's rows live"
- **What it actually means:** A table's rows stored in pages in *no particular order* — an insert just drops the row into any page with room. Fast to write, but finding a specific row means scanning every page, which is exactly the problem an index (a separate sorted structure on top) solves.

### Histogram
- **What people say:** "How you get p99"
- **What it actually means:** A metric that sorts observations into predefined cumulative buckets (`le` = less-than-or-equal) plus a sum and a count, so quantiles are estimated by finding which bucket holds the target rank and interpolating. The cumulative part is the whole trick: bucket counts from ten servers can be *added*, which is why you can compute a fleet-wide p99 from histograms — and why averaging ten servers' p99s, which people do constantly, is meaningless.

## I

### Ice-Cream Cone
- **What people say:** "An inverted test pyramid"
- **What it actually means:** A suite whose cost is dominated by its slowest level — and no team ever chose it. It accretes from a local policy nobody would defend if stated globally: *a defect reached production, so add an end-to-end test so it cannot happen again*. Simulated over 200 sprints against an identical defect stream, that policy produced 48 end-to-end tests holding 1.6% of the test count and 76.6% of the CI seconds — still a textbook pyramid drawn in the units most teams audit. Changing one word to "add a test at the cheapest level that could have caught it" tied on detection (47 escapes against 46) for 35% less CI and 483 engineer-hours.

### IDOR (Insecure Direct Object Reference)
- **What people say:** "Changing the id in the URL to see someone else's data"
- **What it actually means:** Broken object-level authorization — the code checks that the caller may use an endpoint but not that they may access the *specific* object, so incrementing an id exposes other users' records. The #1 API vulnerability; fixed by authorizing the object itself on every access.

### Idempotency
- **What people say:** "Safe to retry"
- **What it actually means:** An operation you can apply many times and get the same result as applying it once. Charging a card twice is not idempotent; setting a value to 5 is. Backends make writes idempotent with a client-supplied key so a retried request doesn't double-charge.

### Idempotency Key
- **What people say:** "A header that stops double-charges on retry"
- **What it actually means:** A client-chosen unique string (usually a UUID) sent with a non-idempotent `POST`; the server guarantees the operation runs *at most once* per key and replays the stored response for duplicates. The client generates it once per logical action and reuses the same key across every retry.
- **Why it's called that:** It's the key that makes an otherwise non-idempotent request idempotent.

### Index
- **What people say:** "Makes queries faster"
- **What it actually means:** A separate, sorted structure (almost always a B-tree) mapping a key to a row's location, so a lookup jumps straight to it instead of scanning the whole table. It's redundant data kept purely to trade write cost and disk space for read speed — so you index the columns you filter, join, and sort by, not every column.

### Index-Free Adjacency
- **What people say:** "Why graph databases are fast at traversals"
- **What it actually means:** Each node physically stores direct pointers to its adjacent edges, so following a relationship is an `O(1)` pointer dereference **independent of the total graph size** — not an index lookup that grows with all the edges and is repaid at every hop. It's the defining trick of a graph database, and why a `k`-hop traversal costs what the answer costs, not what the whole table costs.
- **Why it's called that:** A node's adjacency (its neighbors) is stored on the node itself, so no separate index is consulted to find it.

### Isolation Level
- **What people say:** "How strict the database is"
- **What it actually means:** How much one in-flight transaction can see of another's uncommitted or concurrent work. From Read Uncommitted (loosest, fastest) to Serializable (strictest, as if transactions ran one at a time). Looser levels trade correctness for throughput.

## J

### Jitter
- **What people say:** "Adding randomness to retries"
- **What it actually means:** Randomising a backoff delay so clients that failed at the same instant do not retry at the same instant. Without it, exponential backoff *synchronises* a fleet into a **thundering herd** that hits the recovering service in coordinated waves at 1s, 2s, 4s and knocks it straight back down — the retry storm becomes the outage. The standard choice is full jitter, `sleep = random(0, base × 2^attempt)`, which beats adding a small random nudge to a fixed schedule.

### JWT (JSON Web Token)
- **What people say:** "A signed token you put in a header"
- **What it actually means:** A compact, self-contained claim set (`header.payload.signature`, RFC 7519) any service with the key can verify without a database lookup. The payload is Base64url-*encoded*, not encrypted — readable by anyone; the signature gives integrity. Its whole security is verification: pin the algorithm (never trust the token's `alg`) and check `exp`/`aud`/`iss`.
- **Why it's called that:** A JSON token for the web, signed as a JSON Web Signature.

## L

### Line Coverage
- **What people say:** "How much of the code is tested"
- **What it actually means:** The share of executable lines a suite *ran* — which is not a measurement of testing at all. Six tests that call every function and assert nothing measured 100.0% line coverage (48 of 48) and 87.5% branch coverage while killing 0 of 70 seeded faults, and walked through a `fail_under = 90` gate by ten points. Read it as a ceiling, not a floor: `P(fault detected | line never ran)` is exactly 0 in every program and every language, while `P(detected | line ran)` measured 84.6% and is never 1. An uncovered line is hard evidence of a gap; a covered line is evidence of nothing. Gating on it actively buys assertion-free tests — a coverage-maximising suite filled 6 of its 8 slots with them, correctly, by its own objective.

### Little's Law
- **What people say:** "Queue math"
- **What it actually means:** `L = lambda × W` — in any stable system, the average number of items inside (`L`) equals the average arrival rate (`lambda`) times the average time each item spends inside (`W`). It assumes nothing about distributions, which is why it always applies. Two readings do all the work: **depth ÷ drain rate = seconds of backlog** (5,000 messages draining at 500/s means you are 10 seconds behind, and that's where the alarm threshold comes from), and **arrival rate × processing time = required concurrency** (500/s at 200 ms each needs `500 × 0.2 = 100` messages in flight, so 100 consumers).
- **Why it's called that:** Proved by John Little in 1961.

### Livelock
- **What people say:** "It's running but nothing happens"
- **What it actually means:** Threads that are actively executing, consuming CPU and changing state, while making no progress — two people stepping aside for each other in a corridor, forever. Harder to spot than deadlock precisely because the CPU graphs look *busy*, so monitoring reads as healthy. The usual cause is symmetric, unjittered backoff: every contender detects contention and retries after the same delay, in lockstep. The fix is randomisation — the same jitter that keeps retry storms and cache expiries from synchronising.

### Load Balancer
- **What people say:** "Spreads traffic across servers"
- **What it actually means:** A component that distributes incoming requests across a pool of backends by some algorithm (round-robin, least-connections, hashing) and stops sending to instances that fail health checks.

### Load Shedding
- **What people say:** "Dropping requests on purpose"
- **What it actually means:** Deliberately rejecting work you cannot complete in time, so the work you do accept still succeeds. The counterintuitive part is that it *increases* the number of users served: without it, an overloaded system spends all its capacity on requests whose callers have already timed out. The sharpest form is deadline-aware — check the deadline **when dequeuing**, not just when starting, and discard anything already expired. Related and equally counterintuitive: under overload **LIFO beats FIFO**, because FIFO makes everyone wait the maximum and time out, while LIFO serves the newest, still-live requests. Distinct from backpressure, which tells an upstream producer to slow down; you shed when the producer is the internet and cannot be told anything.

### Log Compaction
- **What people say:** "The broker deletes old messages"
- **What it actually means:** A retention policy that, instead of dropping records older than N days, keeps only the **latest record per key** and garbage-collects the superseded ones — so the log's size becomes proportional to the number of distinct keys rather than the number of writes. That turns an unbounded event stream into a replayable snapshot of current state, which is what lets a brand-new consumer rebuild an entire cache or lookup table from the topic alone. Deletion is expressed as a **tombstone** (a null-valued record for that key), and compaction never renumbers or reorders **offsets** — it only leaves gaps.

### Log Level
- **What people say:** "DEBUG, INFO, WARN, ERROR"
- **What it actually means:** A severity tag (inherited from syslog, RFC 5424) that doubles as a runtime volume filter. The discipline that matters: `ERROR` means a human should care, not "something unusual happened" — an ERROR nobody acts on is how a log stream becomes noise, and it's the logging equivalent of alert fatigue.

### LRU (Least Recently Used)
- **What people say:** "It keeps the recently used stuff"
- **What it actually means:** The default cache eviction policy: when full, throw out whatever was accessed longest ago, betting (via temporal locality) that it's the least likely to be needed next. Implemented in O(1) with a hash map plus a doubly linked list; Redis approximates it by sampling a few random keys rather than tracking exact order.

### LSM-Tree (Log-Structured Merge-Tree)
- **What people say:** "The write-optimized storage engine in Cassandra and RocksDB"
- **What it actually means:** A storage engine that never updates in place: writes append to a commit log and an in-memory sorted **memtable**, which is flushed as an immutable sorted file (an **SSTable**) and merge-**compacted** in the background. Writes are cheap sequential appends; a read may check several SSTables (rescued by **Bloom filters**). It's the write-optimized mirror of the read-optimized **B-tree**, and the engine under wide-column and time-series stores.
- **Why it's called that:** It's a log-structured (append-only) tree whose sorted runs are periodically merged.

## M

### Metastable Failure
- **What people say:** "It didn't recover after we fixed it"
- **What it actually means:** A failure state a system sustains on its own after the original trigger is gone. A brief slowdown grows the queue, latency crosses client timeouts, clients retry, retries raise the arrival rate exactly when capacity fell — and that loop feeds itself. Remove the original 20% slowdown and the system stays down, because the retries are now the load. The engineering consequence: you cannot recover by removing the trigger, only by shedding load or restarting, which means the ability to shed must be built and *tested* before you need it at 3am. Both halves are yours to choose: measured against a 30-second latency spike that was then fully removed, naive 3× retry burned 267.8 minutes of error budget against 230.1 for having no defence at all and was the only configuration of five that never recovered, while capping retry amplification at 1.24× instead of 1.64× was the entire difference between coming back and not.
- **Why it's called that:** From physics: a state that is stable against small perturbations but is not the true equilibrium.

### MFA (Multi-Factor Authentication)
- **What people say:** "Two-factor / a code from an app"
- **What it actually means:** Requiring credentials from two *different* categories — something you know (password), have (phone, security key), or are (biometric) — so stealing one isn't enough. The single most effective defense against account takeover. A password plus a security question is *not* MFA (both are "something you know").

### Message Broker
- **What people say:** "The queue in the middle"
- **What it actually means:** The intermediary that accepts messages from producers, stores them durably, and routes them to consumers — the component that actually breaks the three couplings between the two sides: **temporal** (the receiver may be down), **spatial** (the sender never names the receiver), and **load** (the buffer absorbs bursts). Its shape sets its semantics: a **queue** (one message → exactly one consumer), a **topic** (one message → every subscriber), or a **log** (retained and replayable, consumers track their own **offset**). Adopting one trades N specialised dependencies for a single shared critical one, which is usually an excellent deal and makes the broker the most consequential machine you operate.

### Metric
- **What people say:** "A number on a dashboard"
- **What it actually means:** A name plus labels plus a value, aggregated at the moment it's recorded. That aggregation is the whole trade: a counter costs a few bytes whether it counts ten requests or ten billion, so you keep it for a year — but the individual event is destroyed on the way in, which is why a metric can tell you 412 requests failed and never whose.

### Migration
- **What people say:** "A database schema change"
- **What it actually means:** A versioned, ordered, code-reviewed script that evolves the schema, applied by a runner that records which migrations have run so every environment converges to the same state. On a live database, changes use **expand-contract** (add new → backfill → switch code → drop old) to stay backward-compatible during a rolling deploy.

### Mock
- **What people say:** "Any fake object in a test"
- **What it actually means:** Precisely one of the five test doubles — the one that carries the expectation *before* the code runs and fails **at the call site**, so the stack trace points at the wrong call rather than at an assertion forty lines later. That is its entire legitimate advantage and it is narrower than most suites assume, because asserting on calls is both more brittle and less sensitive than asserting on outcomes: over two behaviour-preserving refactors an interaction suite raised 3 false alarms to an outcome suite's 0, and over 10 seeded bugs it killed 1 where a fake-based outcome suite killed 7. Not a trade — a loss on both axes, outside the narrow case where the interaction genuinely *is* the behaviour (an email sent exactly once, a card not charged twice).

### Mock Drift
- **What people say:** "The mock got out of date"
- **What it actually means:** The double and the code drifting together from the same misunderstanding, so the suite's agreement is guaranteed rather than earned — there is no provider behaviour that makes such a test fail, including the correct one. Measured across 12 releases of a payment provider that changed underneath it four times, a frozen hand-written stub reported 8/8 green every single time: 3 releases genuinely green, then 9 green while broken (75% of the year), and at the worst of them 1,902 of 2,000 orders (95.1%) got the wrong outcome with zero test failures. One renamed status string cost 90.7% of a day's traffic. The fix is one shared contract suite run against both the double and the real provider, which took defect exposure from 22 release-months to 0.

### MTTD / MTTR
- **What people say:** "How long incidents take"
- **What it actually means:** Mean time to **detect** and mean time to **resolve**. Worth separating because they're fixed by different things: MTTD is an alerting problem, and in a badly instrumented system most of MTTR is not the fix — it's *localization*, the hunt for which of forty services is at fault. That hunt is exactly what distributed tracing collapses from an hour to a minute.

### Mutation Testing
- **What people say:** "Testing your tests"
- **What it actually means:** Changing the program on purpose — one token at a time — and asking whether the suite objects (DeMillo, Lipton & Sayward, *Hints on Test Data Selection*, IEEE Computer 11(4), 1978). Each edited copy is a **mutant**; a suite that goes red **kills** it, and a green suite means it **survived**, which is a demonstrated, reproducible fault that ships past your tests. **Mutation score** is killed ÷ total, and it measures the *suite* where coverage measures the *program*: across five suites of rising quality, line coverage was already maxed on the first and branch coverage by the third, while the mutation score ran 0% → 30.0% → 78.6% → 88.6% → 95.7%. Cost is `mutants × suite runtime` at a measured 1.46 mutants per executable line — 18.2 hours for a 12,000-line service, 5.5 minutes for a 60-line pull request — so gate on the diff and run the repo nightly.

### Mutex
- **What people say:** "A lock"
- **What it actually means:** Mutual exclusion: at most one thread holds it at a time, so the critical section it guards is entered by one thread at a time. Always acquired with a scoped construct (`with`, RAII, `defer`) — an exception between acquire and release leaves it held forever and every subsequent thread hangs. An *uncontended* acquire is nanoseconds; a *contended* one parks the thread in the kernel and costs a context switch, which is why lock granularity, not lock existence, is what determines whether a service scales.

### MVCC (Multi-Version Concurrency Control)
- **What people say:** "How Postgres handles concurrent reads and writes"
- **What it actually means:** Instead of locking rows for readers, the database keeps multiple versions of a row so readers see a consistent snapshot while writers create new versions. Readers never block writers and vice versa.

## N

### N+1 Query Problem
- **What people say:** "The ORM is making too many queries"
- **What it actually means:** Fetching a list with one query, then firing one more query per item for its related data — 1 + N round trips where 1 or 2 would do. ORMs cause it by default via innocent-looking lazy property access; the fix is a JOIN or a batched `IN` query (eager loading).

### N+1 Redundancy
- **What people say:** "One spare"
- **What it actually means:** Provisioning enough capacity that losing one failure domain still serves peak, which caps steady-state utilization at (N−1)/N — 50% across 2 AZs, 67% across 3, 75% across 4. Compose it with the queueing knee (~0.71 measured under variable service times) and a 3-AZ fleet's honest steady-state target is **47%**. That is why a correctly sized fleet looks half idle, and why "why are we at 35% CPU?" has a real answer. Distinct from the N+1 *query* problem, which is unrelated.

### Non-Blocking I/O
- **What people say:** "I/O that doesn't wait"
- **What it actually means:** A mode in which a read or write returns immediately with `EAGAIN`/`EWOULDBLOCK` when it cannot proceed, instead of parking the calling thread. On its own this is *worse* than blocking — you have converted an efficient park into a busy loop that burns a core to accomplish nothing. It only becomes useful paired with readiness notification (`epoll`/`kqueue`), so the thread asks the kernel which descriptors are actionable and does work only on those. Note that non-blocking is not the same as asynchronous: non-blocking means 'tell me now if you can't', asynchronous means 'do it and tell me when it's done'.

### Normalization
- **What people say:** "Organizing the database properly"
- **What it actually means:** Arranging tables so each fact lives in exactly one place, eliminating the update/insert/delete anomalies that duplication causes. Formalized as normal forms (1NF–BCNF); the rule of thumb is every non-key column depends on "the key, the whole key, and nothing but the key." 3NF is the practical target.

### NULL
- **What people say:** "An empty value"
- **What it actually means:** A marker for "no value" — unknown or not applicable — that is *not* zero, empty string, or false. It triggers three-valued logic: any comparison with NULL is UNKNOWN, so you test it with `IS NULL` (never `= NULL`, which matches nothing) and aggregates silently skip it.

## O

### OAuth 2.0
- **What people say:** "Sign in with Google"
- **What it actually means:** A delegated *authorization* framework (RFC 6749) letting an app act on a user's behalf at another service **without** the user's password — the user authenticates to an authorization server, which issues the app a scoped, revocable access token. It is authorization, not login (that's OIDC). Use the Authorization Code flow with PKCE.

### OIDC (OpenID Connect)
- **What people say:** "The login version of OAuth"
- **What it actually means:** A thin *authentication* layer on top of OAuth 2.0: the same flow plus an ID token (a JWT) with verified identity claims (`sub`, `email`, `aud`) that your app checks to learn *who* logged in. OAuth gets a token to call an API; OIDC answers "who is this user."

### OWASP Top 10
- **What people say:** "The top web vulnerabilities list"
- **What it actually means:** The Open Worldwide Application Security Project's periodically-updated consensus ranking of the most critical web-application risks — broken access control, cryptographic failures, injection, SSRF, and more. Best used as a security-review checklist: it's the ranked shape of how backends actually get breached.

### Object Mother
- **What people say:** "A named helper that builds a ready-made test object"
- **What it actually means:** A fully-formed specimen whose *name is its precondition set* — `admin_user()`, `admin_user_on_pro_with_mfa()`. That is its whole appeal and its whole problem: a suite needs one mother per *distinct* combination of preconditions, so mothers scale with combinations rather than with tests. Measured, a 240-test suite demanded 145 distinct mothers at 1,063 lines against a factory's 55 (19×), and adding one required column cost 145 edits against 1. Prefer a **factory** (defaults plus overrides, `make_user(role='admin')`) for plain fields and a **builder** for lifecycle states with rules attached; the factory still leaves a residual, since 61 of 240 tests asserted on a default they never stated.

### Observability
- **What people say:** "Monitoring, but the new word for it"
- **What it actually means:** A property of a system, borrowed from control theory (Kálmán, 1960): how well you can infer what's happening *inside* from the signals it emits *outside*. The practical test is whether you can answer a question you never anticipated, about a failure you've never seen, without shipping new code. Monitoring — watching numbers you chose in advance — answers "is it broken?" for known unknowns; observability answers "why?" for the unknown ones.

### Offset
- **What people say:** "The consumer's position in the log"
- **What it actually means:** A monotonically increasing integer identifying a record's position within one partition, and the unit of consumer progress — the *consumer* owns it, so committing an offset is the durable claim "everything before this is handled." Where you put that commit is the entire delivery-semantics question: commit before processing and you get **at-most-once**, commit after and you get **at-least-once**, and there is no third placement. Offsets are per-partition and per-**consumer group**, never global, which is why two groups can read the same topic at wildly different positions.

### OpenAPI
- **What people say:** "The Swagger file that documents an API"
- **What it actually means:** A machine-readable description of an HTTP API — every path, method, parameter, schema, and auth scheme in one document — that tooling turns into typed client SDKs, server stubs, mocks, and contract tests. Kept honest by generating it from (or diffing it against) the code, so docs can't drift from behavior.
- **Why it's called that:** An open specification for describing APIs (formerly Swagger).

### OpenTelemetry (OTel)
- **What people say:** "The standard tracing library"
- **What it actually means:** A CNCF project that separates **how you instrument** from **where the data goes**, across all three signals. Before it, instrumenting meant importing a vendor's SDK, so switching vendors meant rewriting every instrumented line — teams were locked in by their own telemetry. With OTel you write against one API and change backends with a config edit. Formed in 2019 by merging OpenTracing and OpenCensus.

### Order Dependence
- **What people say:** "It only fails when the whole suite runs"
- **What it actually means:** A test that passes in file order because an earlier test left something behind — a committed row, a module-level cache, a consumed sequence value — so the suite's verdict is a property of its ordering rather than of the code. Independence is a property you must verify, not assume, and you budget by the *rarest* dependency rather than the average: a green 200-test suite gave up *some* dependency in 3 shuffled runs at 99% confidence while its rarest needed 182. One reversed run catches every precedence pair for free (2 of 3 here) and can never catch a *count* dependency — 39 leakers before one assertion — which is reachable only by sampling.

### Outbox Pattern
- **What people say:** "Reliably publishing events from a service"
- **What it actually means:** Write the domain change and the event to publish in the same database transaction (into an "outbox" table), then a separate relay process reads the outbox and publishes. It avoids the **dual-write problem** where the DB commits but the message broker publish fails — atomicity comes free because both writes land in one transaction on one database. The relay itself is still **at-least-once** (it can publish and then crash before marking the row sent), so consumers must dedup on the event id; publishing in outbox-id order is what preserves per-aggregate ordering.

## P

### Passkey (WebAuthn / FIDO2)
- **What people say:** "Logging in with your face or fingerprint, no password"
- **What it actually means:** A public-key credential whose private key never leaves the device's secure hardware, so the server stores only the public key. Phishing-proof (the browser binds each signature to the origin) and breach-proof (a leaked database holds only public keys). The passwordless successor to passwords.

### Pepper
- **What people say:** "A secret salt"
- **What it actually means:** A single secret value, the same for all users, mixed into password hashes (e.g. `HMAC(pepper, password)`) but stored *outside* the database — so a database-only breach can't begin cracking. Defense in depth on top of a per-user salt and a slow hash, not a replacement.

### PKCE (Proof Key for Code Exchange)
- **What people say:** "The OAuth thing for mobile apps"
- **What it actually means:** An OAuth extension (RFC 7636, say "pixy") that stops a stolen authorization code from being redeemed: the client sends only the hash (code challenge) of a secret it keeps (code verifier), and must present the verifier to exchange the code. Now recommended for all clients.

### Page
- **What people say:** "A block of the database file"
- **What it actually means:** The fixed-size chunk (Postgres: 8 KB) in which a database does all of its disk I/O, caching, and locking, packing many rows per page. Storage hardware transfers fixed-size blocks, so reading one row still costs a whole page — which is why databases think in pages, not rows.

### Parametrized Test (Table-Driven Test)
- **What people say:** "Running the same test with different inputs"
- **What it actually means:** One test body plus a table of cases, expanded into *one test per case* — nine independent tests with nine independent failures, not one test with nine assertions. It is what makes boundary coverage cheap enough to actually write, and boundaries are where the invisible bugs are: a tier off-by-one showed up on 0.338% of realistic orders, needing 887 random cases for 95% confidence, and a coupon-minimum boundary never appeared in 8,000 at all. Measured, one 6-line 9-case table killed 10 of 24 seeded bugs by itself, and four such tables at 20 lines killed 15 — beating an entire 59-line hand-written suite on 34% of the code. Name the cases with `ids=` so the failure reads as a proposition.

### Partition Key
- **What people say:** "The field that decides which partition a message lands on"
- **What it actually means:** The value hashed to select a partition — and it fixes three unrelated properties simultaneously, which is why it is the highest-leverage decision in a streaming design. It fixes **ordering** (only messages sharing a key are ordered relative to each other; there is no global order), **load distribution** (a skewed key gives you one hot partition while the rest idle), and **maximum parallelism** (a consumer group can never usefully exceed the partition count). `order_id` orders per order and spreads evenly; `country` orders per country and hands one partition 80% of the traffic. Changing the partition count later rehashes existing keys and breaks the ordering guarantee across the change.

### Path Coverage
- **What people say:** "Covering every way through the function"
- **What it actually means:** The share of distinct execution routes exercised — and unlike line and branch coverage it is not merely expensive, it is unreachable. A 10-branch function has 1,024 paths, all confirmed reachable by tracing, and two tests can score 100% line, 100% branch and 0.2% of paths. At a generous 1 ms per test, 20 branches is 17.5 minutes and 30 branches is 12.4 days — for one function. It is also undefined for a loop with a branch in its body and no static bound. The lesson generalises: there is no coverage criterion you can max out and then relax.

### Percentile (p50, p95, p99)
- **What people say:** "The 99th percentile latency"
- **What it actually means:** The value below which that share of requests fall — p99 = 1% of requests were slower. It matters because averages hide tails: 950 requests at 50ms and 50 at 6s average to a healthy-looking 350ms while 5% of users time out. And the tail isn't an edge case — a page making 20 requests has roughly an 18% chance of hitting at least one p99-slow response.

### Poison Message
- **What people say:** "A message that keeps failing"
- **What it actually means:** A message that will fail *every* time it is processed — malformed payload, a referenced row that no longer exists, an event written under a schema this consumer can't read — as opposed to a transient failure a retry would clear. **At-least-once** redelivery makes it immortal: it burns retry budget forever and, on an ordered partition, blocks everything queued behind it (**head-of-line blocking**). The fix is a redelivery cap that routes it to a **dead-letter queue**, plus classifying errors as retryable or not so a poison message is dead-lettered on attempt one rather than attempt ten.

### Polyglot Persistence
- **What people say:** "Using the best database for each job"
- **What it actually means:** Using several storage technologies in one system — a relational core, a cache, a search index, maybe a graph or time-series store — each matched to a slice of data's shape and pressure. Powerful but a permanent operational tax, so the discipline is: designate **one source of truth per fact**, keep the rest as rebuildable projections synced via the **outbox pattern** or **CDC**, and add a store only when a *named* pressure genuinely demands it.
- **Why it's called that:** By analogy to polyglot programming — many "languages" (stores) spoken in one system.

### Postmortem
- **What people say:** "The writeup after an outage"
- **What it actually means:** A blameless account of what happened, why, and what will change — blameless *by design*, because humans hide information from blame and the honest timeline is the entire value of the document. Judge it by one thing: whether the action items have owners, dates, and actually ship. An unshipped action item means the same incident is scheduled to happen again.

### Power of Two Choices
- **What people say:** "Pick two at random, use the better one"
- **What it actually means:** Sampling two backends uniformly at random and routing to the less loaded. Maximum load drops from Θ(log N / log log N) to Θ(log log N) — an exponential improvement bought with one extra sample — and it needs no global state, which is why it is the default in modern proxies (Envoy's `LEAST_REQUEST` with `choice_count: 2` *is* this). The randomness also prevents the herding that makes naive "least loaded" collapse: with a 250 ms-stale load view across 32 balancers, least-connections measured p99 1501.9 ms against P2C's 162.2 ms.
- **Why it's called that:** From Mitzenmacher's result that two random choices are exponentially better than one.

### Primary Key
- **What people say:** "The unique id of a row"
- **What it actually means:** One or more columns that uniquely identify each row — guaranteed unique and never NULL, one per table. Prefer a **surrogate key** (an auto-increment integer or UUID with no business meaning) over a **natural key** like email, because a changing primary key forces a cascading migration across every table that references it.

### Problem Details
- **What people say:** "The standard JSON error format"
- **What it actually means:** The IETF-standard error envelope (RFC 9457, media type `application/problem+json`) with members `type`, `title`, `status`, `detail`, `instance`, plus your own extensions like a machine `code`. Using one envelope for every error lets a client write a single error handler for the whole API instead of parsing a different shape per endpoint.
- **Why it's called that:** It carries the details of a problem that occurred, in a standard shape.

### PromQL
- **What people say:** "Prometheus's query language"
- **What it actually means:** A language over time series where the fundamental move is `rate(counter[5m])` — because a counter only ever goes up, its value is meaningless and its *slope* is the signal. `rate()` also repairs counter resets from process restarts, which is why the ordering rule `sum(rate(x[5m]))` (never `rate(sum(x)[5m])`) matters: summing across a reset destroys the information rate() needs to fix it.

### Property-Based Testing
- **What people say:** "Generating random test inputs"
- **What it actually means:** Stating a relationship that must hold for *all* inputs — round-trip, invariant, idempotence, order-independence, agreement with a slow oracle, a metamorphic relation, or merely "never crashes" — and letting a generator hunt for a counterexample. An example test can only check a case you already thought of, which is very nearly the set you already got right: measured on one pagination-cursor codec with three real bugs, 40 careful hand-written example tests killed 0 of 3 and stayed green on every one, while 3 properties in 15 lines killed 3 of 3 in 5, 4 and 10 generated cases. The generator is the hypothesis, not the assertion — boundary-biased integers found one bug in 8 cases where a uniform `int32` draw needed an expected 4,294,967,296, a 537-million-fold difference from nothing but how you draw a number. **Stateful (model-based)** testing extends it to *sequences*: an LRU bug that no single operation exposes survived 50,000 one-operation cases and is unfindable at any budget below its 5-operation minimum. Never state a property by recomputing the implementation's own expression — that killed 0 of 3 while generating 3,000 cases, the same failure mode as a hand-written mock.

### Provider State
- **What people say:** "The data the contract test needs to exist"
- **What it actually means:** A named precondition the consumer declares in the contract and the provider implements as a setup hook run immediately before its own interaction — written as a *condition* ("an order exists and is confirmed"), never as a fixture. Skip it and verification collapses into noise: the same contract verified 1 of 3 interactions against a provider with no state hook, and the failures read `expected HTTP 200, got 404`, which is a message about an empty database rather than about compatibility. It cannot be a shared seed, because four consumers already produced 7 distinct states and 2 contradictory pairs on the same order id. Treat the state list as an API: a fifteenth state is a design conversation, not a ticket.

### Pub/Sub (Publish-Subscribe)
- **What people say:** "Broadcasting messages"
- **What it actually means:** A messaging shape where producers publish to a named **topic** and every interested subscriber receives its own copy, while the producer never learns who — or how many — they are. That anonymity is the whole point: it breaks spatial coupling, so a sixth consumer of `OrderPlaced` can be added without touching, testing, or redeploying the producer. The bill arrives later — no backpressure reaches the publisher, a subscriber failing is invisible to it, and nobody owns the end-to-end flow. Contrast a **queue**, where each message goes to exactly one consumer.

## Q

### Quarantine (Tests)
- **What people say:** "Mark it non-gating until someone fixes it"
- **What it actually means:** Taking a flaky test out of the build's verdict while it keeps running and reporting, with a named owner. The uncomfortable measurement, over 100 simulated sprints on a shared seed: a no-expiry policy and a 2-sprint-expiry policy shipped *exactly* the same 2.08% of regressions, because a quarantined test and a deleted test gate the same amount — none. What moved the number was funding the work: 2 fixes per sprint took it to 0.33% under either policy. The expiry's real value is recoverability — 210 quarantined tests are a debt you can still pay down, 200 deletions are written off. A quarantine list that only grows is not a policy, it is an outbox.

### Query Planner
- **What people say:** "The thing that runs your SQL"
- **What it actually means:** The optimizer that compiles a declarative SQL query into a concrete execution plan — which scans, indexes, and join algorithms to use — by estimating cost from table statistics. The same query can run thousands of times faster or slower depending on its choice; `EXPLAIN` shows you what it picked.

## R

### Race Condition
- **What people say:** "A timing bug"
- **What it actually means:** A bug whose outcome depends on the interleaving of concurrent operations — better understood as a **broken invariant** than as a timing problem, because that reframing tells you how to fix it: find the invariant, find the window where it is false, and make the critical section cover that window. The two great families are the **lost update** (two threads read-modify-write the same value and one write vanishes) and **check-then-act**. Distinct from a *data race*, which is the low-level unsynchronized access to memory: you can have a race condition with no data races at all, since two individually thread-safe operations composed in sequence will still oversell the last seat. Notoriously unreproducible — a print statement, a debugger, or a lighter load changes the schedule — so 'I couldn't reproduce it' is worthless evidence.

### RBAC (Role-Based Access Control)
- **What people say:** "Permissions by role"
- **What it actually means:** Authorization where users are assigned roles and roles are granted permissions, so you grant a capability once per role instead of per user. Simple and the right default for coarse access; object- and context-specific rules cause "role explosion" — the signal to add ABAC or ReBAC.

### ReBAC (Relationship-Based Access Control)
- **What people say:** "Google Docs-style sharing permissions"
- **What it actually means:** Authorization modeled as a graph of relationships, answered by finding a path (`alice → member → group → editor → doc`). The Google Zanzibar model (OpenFGA, SpiceDB), ideal for sharing, folders, groups, and hierarchies that RBAC and ABAC express awkwardly.

### Raft
- **What people say:** "A consensus algorithm"
- **What it actually means:** A protocol that gets a cluster of nodes to agree on an ordered log of operations even when some nodes crash — by electing a leader, replicating entries, and committing once a majority acknowledges. Designed to be understandable, unlike Paxos.

### Rate Limiting
- **What people say:** "Blocking clients that send too many requests"
- **What it actually means:** Capping how many operations a key (API key, tenant, or IP) may perform per time window — to protect capacity, keep tenants fair, defend against abuse, and control downstream cost. Rejected requests get `429 Too Many Requests` + `Retry-After` so well-behaved clients back off instead of hammering. Common algorithms: fixed window, sliding-window counter, and token bucket.
- **Why it's called that:** It limits the rate — operations per unit of time.

### RED Method
- **What people say:** "Rate, errors, duration"
- **What it actually means:** The three metrics every request-driven service should expose, per route: how many requests, how many failed, how long they took. It's the service-side counterpart to USE (which covers resources), and between them they cover almost every dashboard worth building.

### Referential Integrity
- **What people say:** "Keeping the links between tables valid"
- **What it actually means:** The guarantee, enforced by foreign keys, that every reference points at a row that actually exists — you can't insert a child pointing at a missing parent, or delete a parent that still has children (unless you've said what should happen to them). The database simply refuses to enter the broken state.

### Regression Database
- **What people say:** "The folder the property tester writes to"
- **What it actually means:** The recorded shrunk counterexamples from past failures, replayed *before* any new generation — the only thing that converts a lucky random discovery into a deterministic test. Measured: run 1 found the bug at generated case 10 and recorded it; runs 2 through 8, on seven different seeds, all went red at case 1, and the variance in discovery time collapsed to zero. Better than pinning a seed, which makes the run reproducible by freezing the set of inputs you will ever try — an example suite with extra steps. `hypothesis` keeps it in `.hypothesis/examples`; that directory belongs in your CI cache, not in `.gitignore`.

### Relational Model
- **What people say:** "Storing data in tables"
- **What it actually means:** Edgar Codd's 1970 design: data as **relations** (tables) of **tuples** (rows) over **attributes** (columns), queried by describing the result you want rather than navigating to it. The name comes from "relation" (a single table), not from relationships between tables. Separating logical shape from physical storage is why it's still the default.

### Replication Lag
- **What people say:** "The replica is a bit behind"
- **What it actually means:** The delay between a write committing on the primary and becoming visible on a replica — properly measured in **bytes** (LSN difference), not seconds, because time-based lag reads zero on a completely stuck replica when no writes are arriving. It is a consistency boundary, not a performance detail: it sets the stale-read rate, and lag × write rate is exactly how many acknowledged writes a failover destroys. Split into send, receive and replay lag, since a replica can have received everything and applied almost none of it.

### REST (Representational State Transfer)
- **What people say:** "JSON over HTTP"
- **What it actually means:** An architectural *style* (Roy Fielding, 2000) defined by constraints — client–server, stateless, cacheable, a uniform interface, layered system — not a wire format. Statelessness is the constraint that buys horizontal scaling. Most "REST" APIs target Richardson level 2: resources as plural-noun URIs, correct HTTP verbs, and honest status codes.
- **Why it's called that:** The client transfers *representations* of resource state (a JSON document), rather than calling remote functions.

### Retry Storm
- **What people say:** "Everyone retried at once and made it worse"
- **What it actually means:** Retries raising the arrival rate exactly when capacity fell, so the retries become the load and the system cannot recover even after the trigger is removed. A retry is a bet that the failure is independent and transient; under a *saturation* failure the bet is not merely wrong, it is inverted. Measured against a 30-second latency spike that was then fully restored, naive 3× retry burned 267.8 minutes of error budget against 230.1 for having no defence at all, and was the only configuration of five that never recovered — wire attempts held at 110/s with goodput at exactly 0 for the rest of the run. The fix is a retry budget (each primary request minting ~0.10 retry tokens), which capped amplification at 1.24× instead of 1.64×; and every configuration that actually helped, helped by doing *less*.

### Reverse Proxy
- **What people say:** "Nginx in front of your app"
- **What it actually means:** A server that accepts client requests and forwards them to one or more backend servers, then returns the response — hiding the backends and adding TLS, caching, compression, and load balancing along the way.

### Richardson Maturity Model
- **What people say:** "How RESTful an API is, from 0 to 3"
- **What it actually means:** A four-level scale for an HTTP API: level 0 = one URI, one verb (HTTP as a dumb tunnel); level 1 = many resource URIs; level 2 = proper HTTP verbs + status codes; level 3 = hypermedia (HATEOAS). Level 2 is the pragmatic target that most well-regarded public APIs hit.
- **Why it's called that:** Named for Leonard Richardson, who presented it.

### RPO / RTO
- **What people say:** "How much we lose and how fast we're back"
- **What it actually means:** Recovery Point Objective is the acceptable amount of *data* loss, derived from replication lag; Recovery Time Objective is the acceptable *time* to restore service. Both are chosen and then paid for — an RPO of zero requires synchronous commit, which measured +75 ms on every write across regions. An untested failover has no real RTO, only an aspirational one.

### Runbook
- **What people say:** "The doc you follow during an incident"
- **What it actually means:** The page-specific instructions for what this alert means, how to confirm it, how to mitigate it, and when to escalate — written before 3am by someone with time to think. The rule that keeps alerting honest: **if there is no runbook, it is not a page.** A repeated runbook is also a specification for automation.

## S

### Salt
- **What people say:** "Random data added to a password before hashing"
- **What it actually means:** A unique, random, *non-secret* value hashed together with each password so identical passwords get different hashes and precomputed rainbow tables don't apply. Stored alongside the hash. It fixes precomputation and correlation but not speed — you also need a slow, memory-hard hash.

### Same-Origin Policy (SOP)
- **What people say:** "Browsers block cross-site requests"
- **What it actually means:** The browser's foundational rule isolating origins (scheme + host + port). Its key asymmetry: a page *can send* a cross-origin request (with cookies) but *cannot read* the response unless the target opts in via CORS. CSRF abuses the send; XSS defeats the SOP by running as your origin.

### Scatter-Gather
- **What people say:** "Query all the shards and merge"
- **What it actually means:** A fan-out query whose latency is the *maximum* of its parts, so it inherits every backend's tail rather than their average. Measured across shard counts, p99 went 61 → 409 → 622 ms at S = 1/8/16 while p50 barely moved (12 → 23 → 28 ms), tracking the `1−(1−p)^S` prediction to within 0.1 points. The main reason a shard key that misses most queries is so expensive.

### Semaphore
- **What people say:** "A counter you wait on"
- **What it actually means:** A count of permits: at most N holders at once, where N=1 degenerates to a mutex. The most under-used primitive in backend code, because so many capacity problems are exactly 'at most N at once' — bounding a fan-out, capping concurrent calls to a fragile dependency, or implementing a connection pool, which is a semaphore over a bag of reusable objects. A `BoundedSemaphore` additionally errors on a release that was never acquired, catching the bug where a permit is returned twice and the limit silently inflates.

### Sharding
- **What people say:** "Splitting the database across machines"
- **What it actually means:** Partitioning data across **independent** machines, each with its own resources and its own failure — distinct from replication (same data, many copies) and from single-node partitioning (one machine, many tables). The day you shard you give up cross-shard transactions, cross-shard joins, global auto-increment and global secondary indexes, and every query without the shard key becomes a scatter-gather. The shard key is effectively unchangeable, which makes it the most expensive decision in the system.

### Shuffle Sharding
- **What people say:** "Give every customer a random pair of servers"
- **What it actually means:** Assigning each tenant a random *combination* of k workers out of N instead of a fixed shard, so two tenants share their whole subset only with probability 1/C(N,k) — 1/28 for 2 of 8, and 1 in 75,287,520 for 5 of 100. The mechanism that converts it from redistribution into isolation is **retry to another subset member**: without failover it produces the same fleet-wide error volume as a fixed shard (both k/N), just spread thinner. It does nothing against a bad deploy or a shared dependency.

### Split Brain
- **What people say:** "Two primaries at once"
- **What it actually means:** Two nodes both believing they lead and both accepting writes, typically because a partition made a healthy primary merely *unreachable* rather than dead. Resolved by fencing — STONITH, or a fencing token: a monotonically increasing number the resource itself checks, so a paused leader that wakes up and writes is rejected. Measured, a lease without fencing produced 4 duplicated executions; with fencing, 0.

### SSRF (Server-Side Request Forgery)
- **What people say:** "Making the server fetch a URL you give it"
- **What it actually means:** Tricking your server — which sits inside the trust boundary — into fetching an attacker-chosen URL, reaching internal services or the cloud metadata endpoint (169.254.169.254) to steal credentials. Defended by allowlisting destinations and blocking loopback/private/link-local ranges after DNS resolution.

### Saga
- **What people say:** "A distributed transaction"
- **What it actually means:** A long-lived business transaction split into a sequence of *local* transactions, each committed independently, with a **compensating transaction** defined for every step so a later failure can semantically undo the earlier ones. You reach for it because two-phase commit across services is unavailable or unaffordable, and it explicitly trades away the **I** in ACID: intermediate states are visible, so other actors can read — and act on — a half-finished saga. Driven either by **choreography** (each step emits an event the next reacts to) or **orchestration** (a coordinator owns the state machine).
- **Why it's called that:** From Garcia-Molina and Salem's 1987 paper on long-lived transactions — a saga is a long story told in episodes.

### Sampling
- **What people say:** "We only keep some of the traces"
- **What it actually means:** Deliberately keeping a fraction of telemetry because keeping all of it costs more than the system it observes. **Head** sampling decides at the start of a request (cheap, but you decide before knowing if it was interesting) and propagates the decision so you don't get half a trace. **Tail** sampling buffers the whole trace and decides on the outcome (expensive, but keeps every error). The practical default: 100% of errors and slow requests, a few percent of the boring ones.

### Saturation
- **What people say:** "How busy something is"
- **What it actually means:** How much work is *queued* for a resource, not how utilized it is — and it's the most predictive signal you have. A thread pool at 100% utilization with an empty queue is fine; one at 70% with a growing queue is about to fall over. Connection pools, queues, and thread pools saturate silently while CPU and memory graphs look perfectly healthy, which is why "the cause metrics all look fine" is a classic incident moment.

### Schema
- **What people say:** "The structure of the database"
- **What it actually means:** The declared shape of the data — the tables, their columns and types, the keys, and the constraints — that the database enforces on every row. It's the contract that makes data predictable enough to query and trust. (Confusingly, in Postgres "schema" *also* means a namespace for grouping tables.)

### Schema Registry
- **What people say:** "Where the message schemas live"
- **What it actually means:** A service holding versioned schemas per topic that enforces a **compatibility rule** at registration — *backward* (new consumers can read old data), *forward* (old consumers can read new data), or *full* — so an incompatible producer change is rejected at deploy time instead of discovered as a consumer crash at 3am. Messages then carry a small schema id rather than an inline schema, which is where most of the size advantage of binary formats actually comes from. Its real job is being the one place a cross-team event contract is written down *and* mechanically checked. Which side may ship first follows from the direction: **backward** compatibility lets the *reader* ship first, **forward** lets the *writer* — and for a response the reader is the consumer while for a request it is the provider, which is the flip everyone gets wrong. The three cases intuition misjudges all look permissive: adding a value to an enum, removing one you no longer emit, and relaxing a required field to optional each broke a reader in measurement (318/400, 296/400 and 296/400 records respectively).

### Seam
- **What people say:** "The place you patch the dependency"
- **What it actually means:** A place where you can change a program's behaviour without editing the source at that place (Feathers, *Working Effectively with Legacy Code*, 2004) — every test double you have ever written went in through one. Python has an unusual number of them and they are not interchangeable, because each is secretly coupled to something different: an import path, a `def` site, a call *count*. Measured against three refactors that changed no observable behaviour, a value passed as a parameter survived 3 of 3, a rebound module global 1 of 3 (it is a bet on an import path), and a `side_effect` call list 0 of 3 — call count is not a behaviour anyone can observe. **Dependency injection** is the cheapest seam and is nothing more than passing the value: four styles the literature gives four names to all measured 0 lines of container, registry or annotation. Inject hidden inputs; do not inject arithmetic.

### Shrinking
- **What people say:** "It simplifies the failing input"
- **What it actually means:** After a property finds a counterexample, repeatedly proposing smaller values and keeping any that still fail, so the bug report is minimal rather than whatever the generator happened to draw — the feature that makes property testing practical rather than merely interesting. It is cheap: a 4,000-character failing input reduced to 2 characters in 58 property evaluations, of which only 15 were accepted, and the result named the bug with no prose attached. Two things break it: a slow property (58 evaluations is 58 database queries) and non-determinism, so determinism is a precondition for shrinking rather than a nicety.

### Single-Table Design
- **What people say:** "Putting everything in one DynamoDB table"
- **What it actually means:** A NoSQL modeling technique that stores multiple entity types in one table, co-located by partition key, so a query returns a parent and its children together (an **item collection**) — the join a join-free store can't do, precomputed by the key layout. Data is duplicated on write and keys are overloaded/encoded (`CUSTOMER#c-1`, `ORDER#<date>#<id>`) so each access pattern is a single lookup. Query-first modeling taken to its sharpest form.
- **Why it's called that:** One table serves every access pattern, instead of one table per entity as in a relational schema.

### SLI / SLO / SLA
- **What people say:** "Our uptime targets"
- **What it actually means:** Three distinct things. An **SLI** (indicator) is a *measurement* of user-visible behavior, canonically `good events / valid events`. An **SLO** (objective) is an internal *target* for that SLI over a window — "99.9% of valid requests succeed over 28 rolling days." An **SLA** (agreement) is an external *contract* with financial penalties, deliberately set looser than the SLO so you breach your own target and fix it long before you breach the customer's.

### Span
- **What people say:** "One step in a trace"
- **What it actually means:** A named, timed operation with a trace ID, its own span ID, a parent span ID, attributes, events, and a status. Parent links make the spans of one request into a tree, and that tree rendered as time-proportional bars is the waterfall you actually read: a long bar with a long child means the child is the problem, a long bar with short children means the time is in your own code, and a gap before the first child means queueing or lock wait.

### Starvation
- **What people say:** "One worker never gets a turn"
- **What it actually means:** A thread that is permanently able to run but never actually gets the resource it needs. Causes: unfair (barging) locks, where a newly-arriving thread beats the queue of waiters — most mutexes are unfair *by design* because fairness costs throughput; reader-preferring read-write locks, where a continuous read load means a writer never runs; and **priority inversion**, where a low-priority thread holds a lock a high-priority thread needs while medium-priority work preempts the holder. Priority inversion famously reset the Mars Pathfinder repeatedly on the surface; the fix, priority inheritance, was patched in from Earth.

### Static Stability
- **What people say:** "It keeps working without doing anything"
- **What it actually means:** The principle that a system should survive a failure *without needing to make changes* — no scale-up, no control-plane call, no configuration lookup at the worst possible moment. Pre-provisioned capacity is statically stable and held 100% of traffic through a simulated AZ loss; an elastic fleet that had to react dropped to 70% and took 450 seconds to recover. The reason autoscaling is a cost tool rather than a reliability one.

### Steady-State Hypothesis
- **What people say:** "What we expect to stay normal during the experiment"
- **What it actually means:** A falsifiable statement about a measurable, *user-visible* output that should hold in both the control and the experimental group — step one of a chaos experiment, and where most chaos programmes actually die, because you cannot state a hypothesis about a system that has no SLI saying it is fine. An average cannot be the steady state, since an average is exactly the statistic a saturated tail hides in; a latency SLI needs a threshold. The error budget is what makes the price legible — at 70 rps a 99.5% objective permits 0.35 bad requests per second, so 2,744 failures converts directly into 130.7 minutes. And note the instrument's own lag: a monitor that scores a one-second window only once it has closed reads the current second as healthy by construction (3.0 s in the measured harness), and every time-to-detect number sits on top of it.

### Structured Concurrency
- **What people say:** "Tasks with a parent"
- **What it actually means:** The discipline that a concurrent task may not outlive the scope that created it: on scope exit every child has completed, failed, or been cancelled. It makes concurrency composable — a function that internally fans out to five services is, to its caller, just a function that returns or raises. It exists because unowned tasks (`create_task`, a bare `go`, a raw thread) fail in three ways at once: their exceptions are retrieved by nobody and vanish, an unreferenced task can be garbage-collected mid-flight, and nothing can cancel them when the reason for the work disappears. Implemented as nurseries (Trio), `TaskGroup` (Python 3.11+), `StructuredTaskScope` (Java), and coroutine scopes (Kotlin).
- **Why it's called that:** By analogy with structured programming, which replaced `goto` with control flow that nests.

### Structured Logging
- **What people say:** "Logging in JSON"
- **What it actually means:** Writing log events as typed key-value fields rather than English sentences, so `Failed to process order for user 8842 after 3 retries` becomes an event name plus `user_id`, `retries`, and `error_kind` fields. The difference is that prose must be queried with regexes that break the moment someone rewords the message, while fields can be filtered, grouped, and aggregated like a database.

### Stub
- **What people say:** "A mock"
- **What it actually means:** The test double that returns canned answers and nothing else — no memory, no logic, no state. It exists to drive the code down a branch, and that missing state is exactly its limit: identical assertions killed 2 of 10 seeded bugs over a stub and 7 of 10 over a fake, because "was this customer charged twice?" is a question about state and a stub has nowhere to put the first charge.

## T

### Test Double
- **What people say:** "A mock"
- **What it actually means:** Any object substituted for a real dependency for the duration of a test — and there are five of them, precisely (Meszaros, *xUnit Test Patterns*, Addison-Wesley, 2007), because which one you pick decides what your test is allowed to prove. A **dummy** is never called and only fills a parameter; a **stub** returns canned answers; a **spy** is a stub that records calls so the test can inspect them *afterwards*; a **mock** carries the expectation up front and fails *at the call site*; a **fake** is a working implementation with a shortcut, and is the only one with state. Strip the vocabulary away and every double is a second implementation of somebody else's contract, written from your reading of their docs and verified by nobody — the only code in your repository with no tests, and the one on which every other verdict depends.
- **Why it's called that:** From stunt doubles in film — it looks like the real thing from the camera angle the test happens to use.

### Test Isolation
- **What people say:** "Each test starts from a clean database"
- **What it actually means:** Guaranteeing test 41 cannot see what test 40 wrote, without which the suite measures its own ordering rather than the code. Four strategies, priced in physical work over 200 tests rather than in seconds (which do not reproduce): recreate the schema (260 statements, 200 commits), truncate and reseed (251 statements, 482 row changes, 200 commits), **transaction rollback** (5 statements, 2.1 row changes, 0 commits — 50× fewer statements, 96,379 row changes reduced to 420, and the only strategy whose cost does not grow with your fixture, because it never re-seeds), and a **template database** (3 statements plus a 40,960-byte file copy, via `CREATE DATABASE … TEMPLATE`). Rollback is the correct default *and* the only one that can silently do nothing at all: three tests whose repository called `commit()` itself leaked 3 rows with zero failures reported, and the suite stays green in file order forever — shuffling caught it in 378 of 400 runs (94.50%). The fix is to move the seam, making the code's `commit()` a savepoint release.

### Test Pyramid
- **What people say:** "70% unit, 20% integration, 10% end-to-end"
- **What it actually means:** Mike Cohn's economic argument (*Succeeding with Agile*, 2009) that if your top level costs hundreds of times more and breaks for reasons unrelated to correctness, the optimal suite has few of them — a conditional about *your* cost ratios, not a claim about virtue, and the percentages were never his (his top level was a 2009 record-and-replay UI test). The unit you are billed in decides the picture: solved numerically, the optimum is a pyramid by test *count* and never by CI *seconds* — unit tests were 91.7% of the count at a 30-second budget while holding 26.1% of the seconds, and 6.1% of the count at 600 seconds while holding 0.1%. Teams argue past each other because every published shape is drawn in counts and every CI bill is denominated in seconds.

### Testing Trophy
- **What people say:** "Integration tests deserve the widest band"
- **What it actually means:** The shape named by Kent C. Dodds (2018), with Spotify's honeycomb (André Schaffer, 2018) making the same claim for services: a backend service is mostly *wiring* — HTTP in, database out, queue sideways — so the code with the fewest bugs per line is precisely what unit tests are best at. It is not a fashion cycle but a claim about what kind of code you have; a library is nearly all logic and boundary defects, so for a library the unit ceiling is near 1.0 and the pyramid is simply correct. Measured at one 600-second budget, the trophy reached 86.6% detection against both pyramid variants' 78.1% — purely because it is the only named shape that buys contract tests — with the true optimum at 89.0% and 52.6 points separating the best and worst named shape at identical cost.

### Thread
- **What people say:** "A lightweight process"
- **What it actually means:** An independent instruction stream inside one address space: its own registers, program counter and stack, but sharing the heap, globals and file descriptors with every other thread in the process. That sharing is the whole trade — it makes threads cheap to create and communicate between, and it is the reason races, locks and deadlocks exist at all. A **process**, by contrast, has its own address space, so a crash cannot corrupt a sibling and communication requires serializing through a pipe or shared memory. Rule of thumb: threads for I/O-bound work, processes for CPU-bound work and for isolation.

### Thread Pool
- **What people say:** "Reuse threads instead of creating them"
- **What it actually means:** A fixed set of long-lived workers pulling from a shared queue, with a future per submitted item carrying the result *or the exception* back to the submitter. It replaces thread-per-task, where the thread count is set by your arrival rate rather than your capacity. The load-bearing part is the queue: an **unbounded** queue is not a buffer but a delay line with an OOM at the end, converting overload from a fast visible failure into a slow invisible one. Sizing is not 'more is better' — past the point where the downstream resource saturates, extra workers add queueing there while throughput stays flat and latency climbs, so the pool is really a concurrency *limit* on whatever it calls. Its signature failure is **pool deadlock**: a task running in the pool waits on another task submitted to the same pool.

### TOCTOU (Time Of Check To Time Of Use)
- **What people say:** "Check then act"
- **What it actually means:** The race where a condition is verified and then acted on, with a window in between during which the condition can stop being true: `if balance >= amount: balance -= amount`, `if key not in cache: cache[key] = fetch()`, `if not exists(username): create(username)`. It looks like ordinary business logic, which is why it survives code review. The same pattern recurs at every layer with a different fix at each: a lock in memory, a transaction or `UNIQUE` constraint or `SELECT ... FOR UPDATE` in a database, and compare-and-set on a version number across services. Also a security-relevant class, since the window is exploitable when an attacker controls the timing.

### Toil
- **What people say:** "Ops busywork"
- **What it actually means:** Work that is manual, repetitive, automatable, tactical, and produces no lasting value — and that scales linearly with the size of your system while headcount doesn't. Every alert that fires and gets the same manual fix every time is not an alert; it's a specification for the automation nobody has written yet.

### Token Bucket
- **What people say:** "A rate limiter that allows short bursts"
- **What it actually means:** A rate-limiting algorithm: a bucket holds up to `capacity` tokens that refill at `rate` per second; each request spends one (or more for costly ops), and an empty bucket means reject. `capacity` forgives a burst; `rate` sets the sustained ceiling. Refill is lazy — recomputed from elapsed time on each check, no background timer.
- **Why it's called that:** Requests draw tokens from a bucket that drips full again over time.

### Tolerant Reader
- **What people say:** "Ignore fields you don't recognise"
- **What it actually means:** A consumer written to read only the fields it actually needs, ignore everything else, and not fail on added or reordered fields — the discipline that makes additive schema evolution possible without lockstep deploys of every producer and consumer. Its mirror is the producer rule: only ever add optional fields, never remove, rename, or repurpose one, and never quietly change a field's meaning. A strict reader that rejects unexpected properties converts every producer's harmless additive change into a fleet-wide outage. But tolerance *defers* breakage rather than removing it, and at a contract boundary that is a liability: across 12 provider releases a tolerant consumer raised 0 exceptions every time, absorbed 4 changes correctly — and turned 2 into 226 wrong receipts understating the bill by 101,132,788 minor units, silently. The 4 it absorbed are exactly the evidence that persuaded the provider the other 2 were safe. Be strict about the fields you read and tolerant about everything else, and never `.get(field, default)` a field your contract requires.
- **Why it's called that:** From Postel's robustness principle — be conservative in what you send, liberal in what you accept (RFC 761 §2.10, 1980; qualified by RFC 9413, 2023).

### Trace
- **What people say:** "The end-to-end view of a request"
- **What it actually means:** The tree of spans sharing one trace ID, covering every service a single request touched. It's the only pillar that captures causality *across process boundaries* — the thing you got for free as a stack trace when everything ran in one process, and lost the moment you split into services. It answers "where did the 4.2 seconds go?", which no volume of logs will tell you.

### Trace Context (`traceparent`)
- **What people say:** "The header that carries the trace ID"
- **What it actually means:** A W3C standard header — `00-<32 hex trace id>-<16 hex span id>-<flags>` — that lets a request keep one identity across services instrumented by *different vendors*. Before it, every vendor had its own header (`X-B3-TraceId`, `uber-trace-id`), so a request crossing a boundary lost its identity. The flags byte carries the sampling decision, so downstream services agree and you never get half a trace.

### Transaction
- **What people say:** "A group of database operations"
- **What it actually means:** A unit of work that is all-or-nothing: everything between `BEGIN` and `COMMIT` either takes effect together or not at all (`ROLLBACK`), with the ACID guarantees. The **commit point** is the single atomic instant where provisional changes become permanent and durable.

### TTL (Time To Live)
- **What people say:** "How long the cache keeps it"
- **What it actually means:** A per-entry expiry that bounds staleness — "trust this copy for N seconds, then discard it." It turns the unsolvable problem of knowing exactly when data changes into a tunable one (short = fresh but costly, long = cheap but staler), and is the backstop that caps how long any missed invalidation can serve stale data.

## U

### Universal Scalability Law (USL)
- **What people say:** "Adding workers stops helping"
- **What it actually means:** An extension of Amdahl's Law with a second penalty term for **coherency** — the cost of workers coordinating with each other, which grows quadratically. The consequence is sharper than Amdahl's: throughput does not merely plateau as you add workers, it **peaks and then declines**, so a system can be measurably slower with 1,024 workers than with 16. This is the arithmetic behind 'we doubled the thread pool and it got worse', and the reason capacity decisions come from a measured throughput curve rather than a formula or an intuition.
- **Why it's called that:** Formulated by Neil Gunther; 'universal' because the same two-term model fits software, hardware and human organisations.

### USE Method
- **What people say:** "Utilization, saturation, errors"
- **What it actually means:** Brendan Gregg's checklist for every *resource* — CPU, memory, disk, network, connection pools, thread pools, queues: how busy is it, how much work is queued for it, and is it failing. Where RED covers your services, USE covers the things they depend on, and its saturation term is what catches the outage before your users do.

## V

### Virtual Clock
- **What people say:** "Fake time for async tests"
- **What it actually means:** Replacing the event loop's own time source with a number the test controls, so scheduled work fires when the test advances the clock rather than when time passes. It turns every timeout, backoff ladder and reconciliation window into an assertion instead of a wait: measured over 40 tests of a workflow containing 30 seconds of deliberate delay, it advanced 20.0 minutes of virtual time in 160 scheduler steps with zero real sleeps, and the workflow state at `t = 20.0 s` was identical on every run. Determinism is the point and the speed is the bonus. Its limit is honest — it only controls waits that go *through* it, so a `time.sleep()` on a worker thread or an OS-level socket timeout is invisible to it.

### Visibility Timeout
- **What people say:** "How long a consumer has to process a message"
- **What it actually means:** The window, starting when a consumer receives a message, during which the broker hides it from every other consumer; if no acknowledgement arrives before it expires, the message becomes visible again and is redelivered. This is what makes a queue crash-safe without distributed locks — a dead consumer's work is reclaimed automatically — and it is the direct reason **at-least-once** is the default guarantee. Set it too short and a slow-but-healthy consumer has its message stolen and processed twice; too long and a crash strands that message for the full timeout, which is why long jobs heartbeat to extend the timeout rather than requesting a huge one up front.

## W

### Work Stealing
- **What people say:** "Idle workers take work from busy ones"
- **What it actually means:** A scheduling strategy where each worker owns a local deque of tasks and pushes/pops its own end, while an idle worker *steals* from the tail of a busy worker's deque. It removes the single shared queue as a contention point — the thing that limits a naive thread pool once the worker count is high and tasks are short. Used by Go's scheduler, Java's ForkJoinPool, Rust's Rayon and Tokio.

### Write-Ahead Log (WAL)
- **What people say:** "How databases don't lose data on a crash"
- **What it actually means:** Before changing the actual data pages, the database appends the change to a sequential log and flushes it to disk. On crash recovery it replays the log. Sequential appends are fast, and the log is the source of truth for durability and replication.
