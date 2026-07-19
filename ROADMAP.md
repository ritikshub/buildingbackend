# Roadmap

Status tracker for every phase and lesson. The status glyphs in this file feed
the website (`site/build.js` parses them into `site/data.js`); do not change
their shape.

**Legend:** ✅ Complete &nbsp;·&nbsp; 🚧 In Progress &nbsp;·&nbsp; ⬚ Planned

## Phase 0: Foundations — ✅ (~8 hours)

| # | Lesson | Status | Est. |
|---|--------|--------|------|
| 01 | Bits & Bytes | ✅ | ~40 min |
| 02 | Text & Encoding | ✅ | ~45 min |
| 03 | Transistors & Logic Gates | ✅ | ~50 min |
| 04 | From Sand to Chip | ✅ | ~40 min |
| 05 | The CPU | ✅ | ~50 min |
| 06 | Memory Hierarchy | ✅ | ~50 min |
| 07 | The GPU | ✅ | ~40 min |
| 08 | Comparing Hardware | ✅ | ~45 min |
| 09 | Running a Program | ✅ | ~45 min |
| 10 | Files & the Filesystem | ✅ | ~40 min |
| 11 | What a Network Is | ✅ | ~45 min |

## Phase 1: Networking and Protocols — ✅ (~16 hours)

Rebuilt bottom-up: climb the stack from the physical layer to the application
layer, then the modern protocols that ride on top. Every lesson is in Python.

| # | Lesson | Status | Est. |
|---|--------|--------|------|
| 01 | The Two Maps: OSI & TCP/IP Models | ✅ | ~50 min |
| 02 | Physical Layer: Topologies, Cables & Signals | ✅ | ~60 min |
| 03 | Data Link Layer: MAC, Frames & Switching | ✅ | ~60 min |
| 04 | Network Layer: IP, Subnets & Routing | ✅ | ~75 min |
| 05 | Transport Layer: TCP vs UDP | ✅ | ~75 min |
| 06 | Names on the Network: DNS | ✅ | ~60 min |
| 07 | Application Layer: Protocols & Ports | ✅ | ~75 min |
| 08 | HTTP in Depth: Methods, Status, Headers, Keep-Alive | ✅ | ~75 min |
| 09 | HTTP Server from a TCP Socket | ✅ | ~75 min |
| 10 | TLS, Certificates & mTLS | ✅ | ~90 min |
| 11 | HTTP/2 & HTTP/3 (QUIC) | ✅ | ~60 min |
| 12 | WebSockets & Server-Sent Events | ✅ | ~75 min |
| 13 | gRPC & Protocol Buffers | ✅ | ~90 min |
| 14 | Keep-Alive, Connection Pooling & Timeouts | ✅ | ~60 min |

## Phase 2: API Design — ✅ (~13 hours)

| # | Lesson | Status | Est. |
|---|--------|--------|------|
| 01 | REST Principles & Resource Modeling | ✅ | ~60 min |
| 02 | URLs, Verbs & Status Codes | ✅ | ~60 min |
| 03 | Request Validation & Error Contracts | ✅ | ~75 min |
| 04 | Pagination, Filtering & Sorting | ✅ | ~75 min |
| 05 | API Versioning Strategies | ✅ | ~45 min |
| 06 | OpenAPI & Contract-First Design | ✅ | ~75 min |
| 07 | Idempotency & Safe Retries | ✅ | ~60 min |
| 08 | GraphQL from Scratch | ✅ | ~90 min |
| 09 | Rate Limiting & Quotas | ✅ | ~60 min |
| 10 | API Gateways & the BFF Pattern | ✅ | ~45 min |

## Phase 3: Relational Databases — ✅ (~18 hours)

| # | Lesson | Status | Est. |
|---|--------|--------|------|
| 01 | Why Databases Exist: Persistence & the Limits of Files | ✅ | ~50 min |
| 02 | A Field Guide to Databases: Types & Trade-offs | ✅ | ~50 min |
| 03 | The Relational Model | ✅ | ~60 min |
| 04 | Tables, Columns & Data Types | ✅ | ~55 min |
| 05 | Keys & Relationships | ✅ | ~60 min |
| 06 | Constraints & Data Integrity | ✅ | ~50 min |
| 07 | Schema Design & Normalization | ✅ | ~60 min |
| 08 | How Data Lives on Disk: Pages, Heaps & the Buffer Pool | ✅ | ~70 min |
| 09 | Indexes & the B-Tree | ✅ | ~90 min |
| 10 | How Queries Run: The Planner & EXPLAIN | ✅ | ~75 min |
| 11 | Transactions & ACID | ✅ | ~75 min |
| 12 | Isolation, Concurrency & MVCC | ✅ | ~60 min |
| 13 | Durability: Write-Ahead Logging | ✅ | ~90 min |
| 14 | Connection Pooling & the N+1 Problem | ✅ | ~60 min |
| 15 | Migrations & Schema Evolution | ✅ | ~60 min |
| 16 | Capstone: A Mini Relational Engine on a B-Tree | ✅ | ~120 min |

## Phase 4: NoSQL and Data Modeling — ✅ (~9 hours)

| # | Lesson | Status | Est. |
|---|--------|--------|------|
| 01 | When Not to Use SQL | ✅ | ~45 min |
| 02 | Key-Value Stores | ✅ | ~75 min |
| 03 | Document Databases | ✅ | ~75 min |
| 04 | Wide-Column Stores | ✅ | ~45 min |
| 05 | Time-Series Databases | ✅ | ~75 min |
| 06 | Graph Databases | ✅ | ~75 min |
| 07 | Data Modeling by Access Pattern | ✅ | ~75 min |
| 08 | Polyglot Persistence | ✅ | ~50 min |

## Phase 5: Caching — ✅ (~9 hours)

| # | Lesson | Status | Est. |
|---|--------|--------|------|
| 01 | Why & Where to Cache | ✅ | ~45 min |
| 02 | Build an LRU Cache | ✅ | ~75 min |
| 03 | Redis Fundamentals | ✅ | ~75 min |
| 04 | Cache Strategies: Aside, Through, Behind | ✅ | ~75 min |
| 05 | Invalidation & TTLs | ✅ | ~60 min |
| 06 | Cache Stampede & the Thundering Herd | ✅ | ~75 min |
| 07 | CDNs & Edge Caching | ✅ | ~45 min |
| 08 | HTTP Caching & ETags | ✅ | ~60 min |

## Phase 6: Messaging and Pub/Sub — ✅ (~16 hours)

Rebuilt bottom-up as a **tool-agnostic** arc. The phase teaches the *ideas* —
the message, the queue, the topic, the log, the delivery guarantee, the
partition, the dead-letter path, the outbox — and treats RabbitMQ, Kafka, SQS,
NATS and Pub/Sub as **examples** of those ideas rather than as chapters of their
own. A broker-specific deep dive belongs in its own phase; here, every
production tool appears only in `Use It`, mapped back to the primitive you just
built by hand. Every Build lesson is stdlib-first Python.

The spine: motivation → the three broker shapes (queue, topic, log) → the
guarantees they can and cannot give → what happens when things fail → the
production patterns that keep data correct → architecture → a capstone that
runs the whole pipeline end to end.

| # | Lesson | Status | Est. |
|---|--------|--------|------|
| 01 | Why Async? Coupling & the Cost of the Direct Call | ✅ | ~50 min |
| 02 | Anatomy of a Message: Envelope, Payload & Serialization | ✅ | ~65 min |
| 03 | Build a Message Queue: Work Distribution & Acknowledgement | ✅ | ~90 min |
| 04 | Pub/Sub: Topics, Subscriptions & Fan-Out | ✅ | ~75 min |
| 05 | The Log: Offsets, Replay & Retention | ✅ | ~90 min |
| 06 | Delivery Semantics & Idempotent Consumers | ✅ | ~80 min |
| 07 | Ordering, Partition Keys & Parallel Consumers | ✅ | ~80 min |
| 08 | Retries, Backoff, Dead-Letter Queues & Poison Messages | ✅ | ~75 min |
| 09 | Backpressure, Consumer Lag & Flow Control | ✅ | ~75 min |
| 10 | The Dual-Write Problem: Transactional Outbox & CDC | ✅ | ~85 min |
| 11 | Event-Driven Architecture: Commands, Choreography & Sagas | ✅ | ~60 min |
| 12 | Schema Evolution & Event Contracts | ✅ | ~70 min |
| 13 | Capstone: An Event-Driven Order Pipeline, End to End | ✅ | ~90 min |

## Phase 7: Auth and Security — ✅ (~15 hours)

Rebuilt bottom-up as a defense-in-depth arc: the security mindset and threat
model first, then the cryptographic primitives every mechanism is made of, then
identity (passwords, MFA, sessions, tokens, OAuth, keys), then authorization,
then the browser trust boundary and the injection classes, and finally abuse
prevention and secrets. Every Build lesson is stdlib-first Python.

| # | Lesson | Status | Est. |
|---|--------|--------|------|
| 01 | Authentication, Authorization & the Security Mindset | ✅ | ~50 min |
| 02 | Cryptographic Building Blocks | ✅ | ~75 min |
| 03 | Password Storage & Hashing (bcrypt, argon2) | ✅ | ~70 min |
| 04 | Multi-Factor Auth: TOTP & Passkeys (WebAuthn) | ✅ | ~80 min |
| 05 | Sessions & Secure Cookies | ✅ | ~65 min |
| 06 | JWT & Token Auth from Scratch | ✅ | ~85 min |
| 07 | OAuth 2.0 & OIDC | ✅ | ~90 min |
| 08 | API Keys, HMAC Signing & Webhooks | ✅ | ~70 min |
| 09 | Authorization: RBAC, ABAC & ReBAC | ✅ | ~80 min |
| 10 | The Browser Trust Boundary: CORS, CSRF & XSS | ✅ | ~75 min |
| 11 | Injection & the OWASP Top 10 for Backends | ✅ | ~70 min |
| 12 | Abuse Prevention: Bots, Credential Stuffing & Account Takeover | ✅ | ~65 min |
| 13 | Secrets Management & Rotation | ✅ | ~65 min |

## Phase 8: Concurrency and Performance — ✅ (~20 hours)

Rebuilt bottom-up from 8 planned chapters into a 15-lesson arc, in Python. The
spine: why waiting dominates (the queueing math) → what the machine actually
gives you (processes, threads, the GIL) → how one thread serves thousands of
sockets (non-blocking I/O, the event loop, coroutines, structured concurrency)
→ what breaks when work is shared (races, locks, deadlock) → how a system
survives more load than it can serve (backpressure, pooling) → how you know any
of it is true (profiling, benchmarking) → a capstone that makes a deliberately
slow service fast and measures every step.

Each of the eight original chapters survives as a lesson or a section, but the
topics that were one bullet each — races, locks and deadlock crammed together;
profiling and benchmarking as a single chapter — are split, because each is a
distinct failure mode with its own diagnosis. Every Build lesson is stdlib-first
Python and every claim in the prose is a number the lesson's code prints.

| # | Lesson | Status | Est. |
|---|--------|--------|------|
| 01 | Why Concurrency? Latency, Throughput & Little's Law | ✅ | ~60 min |
| 02 | Processes, Threads & the GIL | ✅ | ~85 min |
| 03 | Blocking vs Non-Blocking I/O: select, poll & epoll | ✅ | ~85 min |
| 04 | The Event Loop: Build a Reactor from Scratch | ✅ | ~85 min |
| 05 | Coroutines & Async/Await from the Ground Up | ✅ | ~90 min |
| 06 | Structured Concurrency: Tasks, Cancellation & Timeouts | ✅ | ~80 min |
| 07 | Thread Pools, Work Queues & Executors | ✅ | ~80 min |
| 08 | Race Conditions, Atomicity & Critical Sections | ✅ | ~80 min |
| 09 | Locks & Coordination Primitives | ✅ | ~80 min |
| 10 | Deadlock, Livelock & Starvation | ✅ | ~80 min |
| 11 | Backpressure, Queueing & Load Shedding | ✅ | ~80 min |
| 12 | Connection & Resource Pooling | ✅ | ~75 min |
| 13 | Profiling: Finding the Real Bottleneck | ✅ | ~85 min |
| 14 | Benchmarking & Load Testing: Numbers You Can Trust | ✅ | ~85 min |
| 15 | Capstone: Make a Slow Service Fast | ✅ | ~100 min |

## Phase 9: Logging, Monitoring and Observability — ✅ (~14 hours)

Rebuilt as a bottom-up arc: what went dark and why, then each pillar built from
scratch in Python (the event, the correlation, the pipeline and its bill; the
registry, the scrape, the query; the span, the waterfall, the sampler), then the
practices that turn signals into decisions — SLOs, alerting, dashboards — and a
capstone where a fully instrumented system breaks and you find it from the
telemetry alone.

| # | Lesson | Status | Est. |
|---|--------|--------|------|
| 01 | Why Systems Go Dark: Monitoring, Observability & the Three Pillars | ✅ | ~50 min |
| 02 | Logs: From print() to Structured Events | ✅ | ~65 min |
| 03 | Correlation: Request IDs, Trace Context & Propagation | ✅ | ~70 min |
| 04 | The Log Pipeline: Ship, Store, Query — and What It Costs | ✅ | ~70 min |
| 05 | Metrics: Counters, Gauges & Histograms from Scratch | ✅ | ~75 min |
| 06 | Prometheus: Pull, Exposition & PromQL | ✅ | ~80 min |
| 07 | Distributed Tracing & OpenTelemetry | ✅ | ~90 min |
| 08 | Health Checks, Readiness & Graceful Shutdown | ✅ | ~65 min |
| 09 | SLIs, SLOs & Error Budgets | ✅ | ~65 min |
| 10 | Alerting & On-Call That Doesn't Burn People Out | ✅ | ~60 min |
| 11 | Dashboards: RED, USE & Grafana | ✅ | ~65 min |
| 12 | Capstone: Debugging a Real Incident | ✅ | ~120 min |

## Phase 10: Infrastructure and Deployment — ✅ (~20 hours)

Rebuilt bottom-up from 8 planned chapters into a 15-lesson arc, in Python. This
phase answers one question end to end: **your code works on your laptop — what
has to exist, and what has to happen, for it to serve real users and keep
serving them while you change it?**

The spine: where code actually runs (the compute ladder from bare metal to
serverless) → what a container really is, built from the kernel primitives up →
how an image is built, trusted and distributed → how a service is configured →
how the infrastructure under it is declared instead of clicked → how many copies
of it get scheduled and kept alive → how a request finds a healthy one → how a
change travels from a commit to production → how that change lands without
dropping traffic → how the database and the API contract change underneath a
running fleet → how you undo any of it → a capstone that ships one service
through every stage.

**Tool-agnostic, like Phase 6.** The lessons teach the *ideas* — the image, the
control loop, the desired state, the rollout, the expand/contract migration —
and treat Docker, Kubernetes, Terraform, GitHub Actions and Argo CD as
**examples** in `Use It`, mapped back to the primitive you just built by hand.
Kubernetes and Terraform get a working overview, deliberately not a deep dive:
enough to read a real cluster and a real plan, and to know what each is doing on
your behalf, without turning the phase into a certification course.

Every Build lesson is stdlib-first Python; the YAML, HCL and Dockerfiles appear
in `Use It` where they belong.

| # | Lesson | Status | Est. |
|---|--------|--------|------|
| 01 | Where Code Actually Runs: Bare Metal, VMs, Containers & Serverless | ✅ | ~60 min |
| 02 | What a Container Actually Is: Namespaces, cgroups & Layers | ✅ | ~90 min |
| 03 | Images, Layers & the Reproducible Build | ✅ | ~80 min |
| 04 | Registries, Digests & the Software Supply Chain | ✅ | ~70 min |
| 05 | Config, Environments & the Twelve-Factor App | ✅ | ~65 min |
| 06 | Infrastructure as Code: Desired State, Plan, Apply & Drift | ✅ | ~85 min |
| 07 | Orchestration: Control Loops, Schedulers & Kubernetes | ✅ | ~95 min |
| 08 | Service Discovery & Health-Aware Routing | ✅ | ~75 min |
| 09 | Reverse Proxies, Load Balancers & Ingress | ✅ | ~80 min |
| 10 | CI/CD: From Commit to Artifact to Environment | ✅ | ~80 min |
| 11 | Deployment Strategies: Rolling, Blue-Green & Canary | ✅ | ~85 min |
| 12 | Deploy ≠ Release: Feature Flags & Progressive Delivery | ✅ | ~70 min |
| 13 | Zero-Downtime Schema & Contract Changes | ✅ | ~85 min |
| 14 | Rollback, Backups & Disaster Recovery | ✅ | ~75 min |
| 15 | Capstone: Ship a Service End to End | ✅ | ~110 min |

## Phase 11: Scalability and Reliability — ✅ (~18.5 hours)

Rebuilt from the planned 8 chapters into a 14-lesson arc. Three of the original
chapters — circuit breakers & bulkheads, retries/timeouts/jitter, graceful
degradation — are already taught in depth by Phase 8's backpressure lesson, so
this phase links to that work and takes the **fleet** view instead: what changes
when there are 300 instances rather than one. It also carries the practical half
of replication, consistency and partitioning.

The arc: the honest ceiling of one machine → the law that says N machines never
give N× → routing traffic to them → making them interchangeable → scaling the
data underneath → choosing the blast radius of a failure → surviving the loss of
a region → tolerating the tail that fan-out creates → buying the right amount of
capacity → automating that without oscillating → and a capstone that breaks all
of it on purpose and ablates each defence to see what it was actually worth.

> **Status: drafted, awaiting review.** Every lesson has prose, code that runs,
> a quiz and an artifact, but the syllabus and content have not been reviewed yet.

| # | Lesson | Status | Est. |
|---|--------|--------|------|
| 01 | What One Machine Can Actually Do | ✅ | ~60 min |
| 02 | The Universal Scalability Law: Why 2× the Machines Isn't 2× the Throughput | ✅ | ~75 min |
| 03 | Load Balancing Algorithms: Why Round-Robin Lies | ✅ | ~80 min |
| 04 | Layer 4 vs Layer 7, Health Checks & Outlier Ejection | ✅ | ~75 min |
| 05 | Service Discovery, Client-Side Balancing & Subsetting | ✅ | ~75 min |
| 06 | Stateless Services: Where the State Actually Went | ✅ | ~70 min |
| 07 | Read Replicas & Replication Lag | ✅ | ~80 min |
| 08 | Sharding the Data Tier | ✅ | ~85 min |
| 09 | Failure Domains, Blast Radius & Shuffle Sharding | ✅ | ~80 min |
| 10 | Multi-Region: Global Traffic, Failover & Data Gravity | ✅ | ~85 min |
| 11 | The Tail at Scale: Fan-Out, Hedged Requests & Correlated Failure | ✅ | ~80 min |
| 12 | Capacity Planning: Headroom, Peak & What to Actually Buy | ✅ | ~70 min |
| 13 | Autoscaling: Control Loops That Don't Oscillate | ✅ | ~75 min |
| 14 | Capstone: Survive the Region Loss | ✅ | ~120 min |

## Phase 12: Testing and Quality — ✅ (~19.2 hours)

| # | Lesson | Status | Est. |
|---|--------|--------|------|
| 01 | Why Tests Exist: The Cost of Finding a Bug Late | ✅ | ~65 min |
| 02 | The Shape of a Test Suite: Pyramid, Trophy & the Honest Trade-off | ✅ | ~70 min |
| 03 | Anatomy of a Unit Test | ✅ | ~70 min |
| 04 | Test Doubles: Mocks, Stubs, Fakes & the Lies They Tell | ✅ | ~75 min |
| 05 | Designing for Testability: Seams, Injection & the Untestable Function | ✅ | ~70 min |
| 06 | Integration Testing Against a Real Database | ✅ | ~80 min |
| 07 | Test Data & Fixtures: Factories, Builders & the Shared-State Trap | ✅ | ~70 min |
| 08 | Determinism: Time, Randomness, IDs & Order | ✅ | ~70 min |
| 09 | Flaky Tests: The Trust Arithmetic | ✅ | ~70 min |
| 10 | Contract Testing: The Seam Between Services | ✅ | ~75 min |
| 11 | Testing Async & Event-Driven Systems | ✅ | ~80 min |
| 12 | Property-Based Testing & Fuzzing: The Cases You Would Never Have Written | ✅ | ~80 min |
| 13 | Coverage Lies, Mutation Testing Doesn't | ✅ | ~75 min |
| 14 | Chaos Engineering & Testing in Production | ✅ | ~80 min |
| 15 | Capstone: A Suite That Catches Real Bugs | ✅ | ~120 min |

## Phase 13: Capstone Projects — ⬚ (~40 hours)

| # | Project | Status | Est. |
|---|--------|--------|------|
| 01 | URL Shortener at Scale | ⬚ | ~8 hours |
| 02 | A Rate-Limited Public API | ⬚ | ~8 hours |
| 03 | Real-Time Chat Backend | ⬚ | ~8 hours |
| 04 | Event-Driven Order System | ⬚ | ~8 hours |
| 05 | Distributed Job Scheduler | ⬚ | ~8 hours |
