# Config, Environments & the Twelve-Factor App

> Nobody in the incident channel can answer "which value is actually live right now?" — and the reason is that four layers all set the same key and none of them can be introspected. This lesson builds the answer: a resolver that reports the effective value *and* its source for every key, a boot check that caught **7 configuration defects in 0.2 ms before a socket was opened**, and a release identity that gave **one immutable artifact 4 distinct release ids** — because a config change is a deploy, and "roll back" needs a target.

**Type:** Build
**Languages:** Python
**Prerequisites:** [Images, Layers & the Reproducible Build](../03-images-layers-and-builds/), [Secrets Management & Rotation](../../07-auth-and-security/13-secrets-management-and-rotation/)
**Time:** ~65 minutes

## The Problem

**03:04.** Checkout p99 has been climbing for forty minutes. Someone notices that the downstream timeout looks wrong in the traces — requests are hanging around for three seconds when the budget is supposed to be one and a half. So the question goes into the channel, and it is the simplest question in the world:

> what is `REQUEST_TIMEOUT_MS` set to in production right now?

Here is what comes back over the next eleven minutes.

The Helm chart has a default of `3000`. The ConfigMap for this namespace sets `2000`. The Deployment's `env:` block sets `1500` for this one container, because someone needed it for a load test in April. There is a `--request-timeout-ms` flag in the container's `args` that nobody remembers adding. And six weeks ago, during an incident, someone exec'd into a pod and exported a value in the shell before restarting the process by hand — which does nothing now, but the story of it is still in the runbook, so somebody spends four minutes chasing it.

Five plausible answers, four of them wrong, and the only way to find out which is to `kubectl exec` into a running pod and read `/proc/1/environ`. **Eleven minutes of an outage were spent reading configuration.** Not fixing it. Reading it.

**03:31.** They find it. The fix is to change one integer. And here is the second half of the disease: that integer is baked into the image, because the deployment template renders it at build time. Changing it means a rebuild — a fresh CI (continuous integration) run, a fresh image, a fresh push to the registry, a fresh rollout. **Twenty-two minutes to change a number**, and at the end of it the running system has a different artifact than the one that was tested, so the change to a timeout is now also, technically, an untested deploy.

**08:50.** The follow-up. Someone asks the reasonable question — "did anything else drift?" — and it turns out `FEATURE_NEW_CHECKOUT` is set to `true` in staging and is set nowhere at all in production. It has been like that for five weeks. Every sign-off, every demo, every "it works in staging" was exercising a code path production has never run.

Three failures, one disease. Config that has no **provenance** (you cannot ask where a value came from), no **identity** (a config change is not a versioned thing), and no **parity** (nothing compares two environments). Everything below is the cure for those three, and none of it requires a framework.

## The Concept

### The twelve-factor app, and where it has aged

The vocabulary everyone uses for this comes from **the twelve-factor app** (Adam Wiggins, 2011, <https://12factor.net>), a manifesto written at Heroku from watching a few hundred thousand applications deploy onto a platform-as-a-service. It is the single most influential document in this phase, and it is fifteen years old. Both facts matter.

The twelve, one clause each, so you have the map:

| # | Factor | The claim |
|---|---|---|
| I | **Codebase** | One codebase in version control, many deploys of it |
| II | **Dependencies** | Declare dependencies explicitly; never rely on what happens to be on the host |
| III | **Config** | Store config in the environment, not in the code |
| IV | **Backing services** | Treat databases, queues and caches as attached resources, swappable by URL |
| V | **Build, release, run** | Strictly separate the three stages; a release is immutable |
| VI | **Processes** | Execute the app as one or more stateless, share-nothing processes |
| VII | **Port binding** | Export the service by binding a port, not by living inside a web server |
| VIII | **Concurrency** | Scale out by adding processes, not by growing one |
| IX | **Disposability** | Fast startup, graceful shutdown; a process must survive being killed |
| X | **Dev/prod parity** | Keep development, staging and production as similar as you can |
| XI | **Logs** | Treat logs as an event stream on stdout; do not manage files |
| XII | **Admin processes** | Run migrations and one-off tasks as processes against the same release |

This phase leans hardest on **III, V, IX, X and XI**, and this lesson builds III, V and X directly.

Now the part a manifesto will not tell you, which is where it has aged.

**Factor III's headline is wrong in its literal form and right in its spirit.** "Store config in the environment" is usually read as "put everything in environment variables," and environment variables are a genuinely poor secret channel: they are visible in `/proc/<pid>/environ` to anything running as the same user, they are inherited by every child process you spawn, they show up in `docker inspect`, in crash dumps, in exception reporters that helpfully attach the environment, and in the process listing on some platforms. They are also flat strings with no structure and no size discipline. The durable idea underneath is not "environment variables." It is: **config must not live in the build artifact, and the artifact must not know which environment it is in.** Env vars are one delivery mechanism for that. Mounted files are another, often a better one for secrets.

**Factor IV was written before anyone had operated a database at scale.** "Attached resources, swappable by changing a URL" is true of the *connection*, and false of everything else. Postgres, MySQL and DynamoDB do not have interchangeable semantics; swapping one for another is a rewrite, not a config change. What survives, and it is worth a lot, is the narrower claim: your code should not need to change between a database on your laptop and a managed one in production. That is a statement about *config*, not about portability.

**Factor XI assumed a platform that solved logging for you.** "Write to stdout and never concern yourself with routing or storage" made sense when a PaaS ran a log router on your behalf. In a container world stdout is still correct — [Structured Logging](../../09-logging-monitoring-and-observability/02-structured-logging/) and [The Log Pipeline](../../09-logging-monitoring-and-observability/04-the-log-pipeline/) cover why — but routing, storage, ingest cost and retention are now *your* problem, and unbuffered writes to a pipe with a slow reader are a blocking call in your request path. The factor tells you where to write. It no longer tells you that you are done.

**Factors II, VI, VII and VIII have been overtaken.** Explicit dependency declaration is now lockfiles and content-addressed layers, which Lesson 3 does far more rigorously. Statelessness and port binding are assumptions of every container runtime. "Scale out via the process model" predates goroutines, async runtimes and the whole of Phase 8.

Cite the manifesto, use its vocabulary — everyone in the industry shares it — and read factors III, IV and XI with the era in mind. A senior reader will trust you more for saying so.

### The central identity: `release = build + config`

Factor V is the one this lesson is built on, and it is worth stating as an equation rather than a paragraph.

Lesson 3 produced an **artifact**: an image, identified by a content digest, byte-identical no matter who builds it or when. That artifact is immutable and it is *environment-agnostic* — there is no such thing as "the staging image," and if you have one, you have already lost.

Config is what varies per environment. It is not part of the artifact.

The **release** is the pair. And the point everyone misses: **the pair needs its own identity**, deterministic and independent of both halves:

```text
release_id = hash(artifact_digest + config_hash)
```

Once you have that, a lot of ambiguity disappears at once. "Roll back" stops being a question. When someone says it during an incident, they mean *return to the last state that worked* — and that state was an artifact **and** a set of values. If you version only the artifact, and the last three changes were config-only, then rolling back the artifact returns you to exactly the state you are already in, and the fault survives the rollback. That failure is common enough to have a shape you will recognise: the rollback "completes successfully" and nothing improves.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 470" width="100%" style="max-width:840px" role="img" aria-label="One immutable artifact combined with three different configurations produces three releases, each with its own deterministic release identifier derived from a hash of the artifact digest and the configuration hash. The staging config yields release 789ff3a47436, the production config yields e1b2f40f9cf7, and changing one integer in the production config yields 3e5fa9b041f9 over the same unchanged artifact.">
  <defs>
    <marker id="l05-a1" markerWidth="10" markerHeight="10" refX="6.5" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker>
    <marker id="l05-a1p" markerWidth="10" markerHeight="10" refX="6.5" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#7c5cff"/></marker>
  </defs>
  <text x="440" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">release = build + config — and the release needs its own name</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">

    <rect x="30" y="42" width="820" height="58" rx="11" fill="#7c5cff" fill-opacity="0.13" stroke="#7c5cff" stroke-width="2"/>
    <g fill="currentColor">
      <text x="48" y="66" font-size="11.5" font-weight="700" fill="#7c5cff">THE BUILD — one artifact, built once (lesson 3)</text>
      <text x="48" y="86" font-size="9.5" opacity="0.92">sha256:9f2b41c7d0e8a35b6c1f4e92a7d83b05e6c14f7a92d3b8e05c71f4a6d29b8e30</text>
      <text x="836" y="66" font-size="9.5" text-anchor="end" opacity="0.85">immutable · byte-identical</text>
      <text x="836" y="86" font-size="9.5" text-anchor="end" opacity="0.85">never rebuilt for a config change</text>
    </g>

    <path d="M356 100 L 356 350" fill="none" stroke="#7c5cff" stroke-width="1.6" stroke-dasharray="5 4" opacity="0.8"/>
    <g fill="none" stroke="#7c5cff" stroke-width="1.6">
      <path d="M356 152 L 372 152" marker-end="url(#l05-a1p)"/>
      <path d="M356 244 L 372 244" marker-end="url(#l05-a1p)"/>
      <path d="M356 336 L 372 336" marker-end="url(#l05-a1p)"/>
    </g>
    <text x="364" y="117" font-size="8.5" fill="#7c5cff" font-weight="700" font-family="'JetBrains Mono', ui-monospace, monospace">same artifact feeds all three</text>

    <g fill="none" stroke-width="2" stroke-linejoin="round">
      <rect x="30" y="124" width="278" height="56" rx="9" fill="#e0930f" fill-opacity="0.12" stroke="#e0930f"/>
      <rect x="30" y="216" width="278" height="56" rx="9" fill="#e0930f" fill-opacity="0.12" stroke="#e0930f"/>
      <rect x="30" y="308" width="278" height="56" rx="9" fill="#e0930f" fill-opacity="0.14" stroke="#e0930f"/>
      <rect x="378" y="124" width="280" height="56" rx="9" fill="#0fa07f" fill-opacity="0.12" stroke="#0fa07f"/>
      <rect x="378" y="216" width="280" height="56" rx="9" fill="#0fa07f" fill-opacity="0.12" stroke="#0fa07f"/>
      <rect x="378" y="308" width="280" height="56" rx="9" fill="#0fa07f" fill-opacity="0.14" stroke="#0fa07f"/>
      <rect x="706" y="124" width="144" height="56" rx="9" fill="#7f7f7f" fill-opacity="0.10" stroke="currentColor" stroke-opacity="0.5"/>
      <rect x="706" y="216" width="144" height="56" rx="9" fill="#7f7f7f" fill-opacity="0.10" stroke="currentColor" stroke-opacity="0.5"/>
      <rect x="706" y="308" width="144" height="56" rx="9" fill="#7f7f7f" fill-opacity="0.10" stroke="currentColor" stroke-opacity="0.5"/>
    </g>

    <g fill="currentColor">
      <text x="44" y="145" font-size="11" font-weight="700" fill="#e0930f">staging config</text>
      <text x="44" y="161" font-size="9" opacity="0.9">cfg 50c6ea3de20efcba</text>
      <text x="44" y="174" font-size="9" opacity="0.9">FEATURE_NEW_CHECKOUT=true</text>
      <text x="44" y="237" font-size="11" font-weight="700" fill="#e0930f">production config</text>
      <text x="44" y="253" font-size="9" opacity="0.9">cfg 3f5f623718513046</text>
      <text x="44" y="266" font-size="9" opacity="0.9">REQUEST_TIMEOUT_MS=2000</text>
      <text x="44" y="329" font-size="11" font-weight="700" fill="#e0930f">production config v2</text>
      <text x="44" y="345" font-size="9" opacity="0.9">cfg cf2629aee7108df9</text>
      <text x="44" y="358" font-size="9" opacity="0.9">REQUEST_TIMEOUT_MS=1500</text>

      <text x="392" y="145" font-size="11" font-weight="700" fill="#0fa07f">RELEASE  rel-789ff3a47436</text>
      <text x="392" y="163" font-size="9" opacity="0.9">id = sha256(artifact + config hash)</text>
      <text x="392" y="176" font-size="9" opacity="0.9">this is the thing you deploy</text>
      <text x="392" y="237" font-size="11" font-weight="700" fill="#0fa07f">RELEASE  rel-e1b2f40f9cf7</text>
      <text x="392" y="255" font-size="9" opacity="0.9">same artifact, different config</text>
      <text x="392" y="268" font-size="9" opacity="0.9">different id — as it must be</text>
      <text x="392" y="329" font-size="11" font-weight="700" fill="#0fa07f">RELEASE  rel-3e5fa9b041f9</text>
      <text x="392" y="347" font-size="9" opacity="0.9">one integer changed. New id.</text>
      <text x="392" y="360" font-size="9" opacity="0.9">Nothing was rebuilt.</text>

      <text x="778" y="147" font-size="10" text-anchor="middle" font-weight="700">RUN</text>
      <text x="778" y="164" font-size="9" text-anchor="middle" opacity="0.85">staging pods</text>
      <text x="778" y="239" font-size="10" text-anchor="middle" font-weight="700">RUN</text>
      <text x="778" y="256" font-size="9" text-anchor="middle" opacity="0.85">prod pods</text>
      <text x="778" y="331" font-size="10" text-anchor="middle" font-weight="700">RUN</text>
      <text x="778" y="348" font-size="9" text-anchor="middle" opacity="0.85">prod pods, rolled</text>
    </g>

    <g fill="currentColor" font-size="15" font-weight="700" text-anchor="middle" opacity="0.8">
      <text x="343" y="158">+</text><text x="343" y="250">+</text><text x="343" y="342">+</text>
    </g>
    <g fill="none" stroke="currentColor" stroke-width="1.6" opacity="0.7">
      <path d="M662 152 L 698 152" marker-end="url(#l05-a1)"/>
      <path d="M662 244 L 698 244" marker-end="url(#l05-a1)"/>
      <path d="M662 336 L 698 336" marker-end="url(#l05-a1)"/>
    </g>

    <path d="M596 274 C 634 284, 634 296, 598 306" fill="none" stroke="#d64545" stroke-width="1.8" marker-end="url(#l05-a1)"/>
    <text x="640" y="293" font-size="9" font-weight="700" fill="#d64545" font-family="'JetBrains Mono', ui-monospace, monospace">config-only change</text>

    <text x="440" y="404" font-size="10.5" text-anchor="middle" fill="currentColor" opacity="0.95">Measured: 1 artifact, 4 distinct release ids (a rotated signing key is the fourth). Version only the</text>
    <text x="440" y="422" font-size="10.5" text-anchor="middle" fill="currentColor" opacity="0.95">artifact and all four collapse to one digest — so &quot;roll back&quot; has 1 target where it needs 4.</text>
    <text x="440" y="450" font-size="11" text-anchor="middle" fill="currentColor" opacity="0.9">A config change is a deploy. Record it, name it, and make it rollback-able like any other release.</text>
  </g>
</svg>
```

Two consequences worth writing on the wall.

**A release is immutable, and it is created at deploy time, not at build time.** The build stage produces an artifact and knows nothing about environments. The release stage combines that artifact with one environment's config and stamps an id. The run stage does nothing but execute a release. If your CI pipeline renders environment values into the image, you have merged build and release, and the thing you tested in staging is not the thing running in production — it is a different artifact that was built from the same source. That is a much weaker guarantee, and it is the one most pipelines actually provide.

**A secret rotation is a release.** The build code's config hash covers every effective value, including secrets. Rotating a signing key with no other change produced a fourth release id over the same artifact. That is correct and it is useful: a rotation is a change to the running system, so it belongs in the same audit trail, the same change log, and the same rollback story as everything else. Lesson 14 will come back to this when it asks what "restore to 14:00" actually means.

### Precedence and provenance

Every real system ends up with layers, because every layer is individually reasonable: a default so the thing runs at all, a file so the common case is committed and reviewable, the environment so a deploy can override without a rebuild, a command-line flag so an operator can override without a redeploy. Four is normal. The order used here — and the order almost everyone converges on — is:

```text
schema defaults  →  config file  →  environment  →  command line
     lowest                                            highest
```

Three properties make that safe, and the third is the one that is almost never implemented.

1. **Documented.** Written down where someone can find it during an incident, not inferred from the order of `dict.update()` calls.
2. **Deterministic.** The same inputs resolve to the same outputs, every boot, on every host. No wall-clock, no hostname-dependent branches, no "whichever file the glob returned first."
3. **Introspectable.** The running process can tell you, for each key, the effective value **and which layer supplied it**, and what the other layers said.

That third property is the direct answer to the 03:04 question. Without it, "what is `REQUEST_TIMEOUT_MS` right now" is answered by reading four files and guessing. With it, it is answered by one command, in one second, by whoever is nearest.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 440" width="100%" style="max-width:840px" role="img" aria-label="Four configuration layers all set the key LOG_LEVEL: the schema default says info, the config file says warn, the container environment says info, and the command line flag says debug. Later layers win, so the command line value debug is the live one and the other three are shadowed. The provenance record on the right names the effective value, the layer it came from, and every layer that lost.">
  <defs>
    <marker id="l05-a2" markerWidth="10" markerHeight="10" refX="6.5" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker>
    <marker id="l05-a2g" markerWidth="10" markerHeight="10" refX="6.5" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#0fa07f"/></marker>
  </defs>
  <text x="440" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">Four layers set LOG_LEVEL. Only one is live — and the process can say which.</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">

    <path d="M32 66 L 32 336" fill="none" stroke="#3553ff" stroke-width="1.8" marker-end="url(#l05-a2)" stroke-opacity="0.8"/>
    <text x="20" y="204" font-size="10" fill="#3553ff" font-weight="700" text-anchor="middle" transform="rotate(-90 20 204)">later layers win</text>

    <g fill="none" stroke-width="1.9" stroke-linejoin="round">
      <rect x="52" y="60" width="524" height="58" rx="9" fill="#7f7f7f" fill-opacity="0.08" stroke="currentColor" stroke-opacity="0.45"/>
      <rect x="52" y="130" width="524" height="58" rx="9" fill="#7f7f7f" fill-opacity="0.08" stroke="currentColor" stroke-opacity="0.45"/>
      <rect x="52" y="200" width="524" height="58" rx="9" fill="#7f7f7f" fill-opacity="0.08" stroke="currentColor" stroke-opacity="0.45"/>
      <rect x="52" y="270" width="524" height="58" rx="9" fill="#0fa07f" fill-opacity="0.15" stroke="#0fa07f" stroke-width="2.4"/>
    </g>

    <g fill="currentColor">
      <text x="70" y="82" font-size="11" font-weight="700" opacity="0.85">1 · default</text>
      <text x="70" y="99" font-size="9" opacity="0.75">the schema, compiled in</text>
      <text x="70" y="112" font-size="9" opacity="0.75">Field(&quot;LOG_LEVEL&quot;, default=&quot;info&quot;)</text>
      <text x="70" y="152" font-size="11" font-weight="700" opacity="0.85">2 · file</text>
      <text x="70" y="169" font-size="9" opacity="0.75">/etc/app/config.toml</text>
      <text x="70" y="182" font-size="9" opacity="0.75">shipped next to the code</text>
      <text x="70" y="222" font-size="11" font-weight="700" opacity="0.85">3 · env</text>
      <text x="70" y="239" font-size="9" opacity="0.75">the container environment</text>
      <text x="70" y="252" font-size="9" opacity="0.75">from a ConfigMap via envFrom</text>
      <text x="70" y="292" font-size="11" font-weight="700" fill="#0fa07f">4 · cli</text>
      <text x="70" y="309" font-size="9" opacity="0.85">the process command line</text>
      <text x="70" y="322" font-size="9" opacity="0.85">--log-level=debug</text>

      <text x="350" y="90" font-size="12.5" font-weight="700" opacity="0.55">LOG_LEVEL = info</text>
      <text x="350" y="160" font-size="12.5" font-weight="700" opacity="0.55">LOG_LEVEL = warn</text>
      <text x="350" y="230" font-size="12.5" font-weight="700" opacity="0.55">LOG_LEVEL = info</text>
      <text x="350" y="300" font-size="12.5" font-weight="700" fill="#0fa07f">LOG_LEVEL = debug</text>

      <text x="560" y="95" font-size="9.5" font-weight="700" text-anchor="end" opacity="0.55">SHADOWED</text>
      <text x="560" y="165" font-size="9.5" font-weight="700" text-anchor="end" opacity="0.55">SHADOWED</text>
      <text x="560" y="235" font-size="9.5" font-weight="700" text-anchor="end" opacity="0.55">SHADOWED</text>
      <text x="560" y="305" font-size="9.5" font-weight="700" text-anchor="end" fill="#0fa07f">LIVE</text>
    </g>

    <g fill="none" stroke="currentColor" stroke-width="1.4" stroke-dasharray="4 4" opacity="0.4">
      <path d="M576 89 L 620 89"/><path d="M576 159 L 620 159"/><path d="M576 229 L 620 229"/>
    </g>
    <path d="M576 299 L 640 299" fill="none" stroke="#0fa07f" stroke-width="2" marker-end="url(#l05-a2g)"/>

    <rect x="646" y="60" width="204" height="268" rx="10" fill="#0fa07f" fill-opacity="0.10" stroke="#0fa07f" stroke-width="2"/>
    <g fill="currentColor">
      <text x="662" y="84" font-size="11" font-weight="700" fill="#0fa07f">PROVENANCE RECORD</text>
      <text x="662" y="100" font-size="8.5" opacity="0.75">what --config-provenance prints</text>
      <text x="662" y="128" font-size="9" opacity="0.7">EFFECTIVE</text>
      <text x="662" y="144" font-size="11.5" font-weight="700">debug</text>
      <text x="662" y="170" font-size="9" opacity="0.7">SOURCE</text>
      <text x="662" y="186" font-size="11.5" font-weight="700">cli</text>
      <text x="662" y="212" font-size="9" opacity="0.7">SHADOWED</text>
      <text x="662" y="228" font-size="10">default = info</text>
      <text x="662" y="243" font-size="10">file&#8195;&#8195;= warn</text>
      <text x="662" y="258" font-size="10">env&#8195;&#8195;&#8195;= info</text>
      <text x="662" y="286" font-size="9" opacity="0.7">SECRETS</text>
      <text x="662" y="302" font-size="9.5">redacted here too:</text>
      <text x="662" y="316" font-size="9.5">&lt;redacted sha256:41a3154e&gt;</text>
    </g>

    <text x="440" y="366" font-size="10.5" text-anchor="middle" fill="currentColor" opacity="0.95">Three of the four layers say &quot;info&quot; or &quot;warn&quot;. Read any one of them on its own and you get</text>
    <text x="440" y="384" font-size="10.5" text-anchor="middle" fill="currentColor" opacity="0.95">the wrong answer with total confidence — which is the whole 3am problem, in one key.</text>
    <text x="440" y="416" font-size="11" text-anchor="middle" fill="currentColor" opacity="0.9">Precedence must be documented, deterministic and introspectable. The third is the one everyone skips.</text>
  </g>
</svg>
```

### Fail fast at boot

Config arrives as strings. A string is not a value until something has parsed it and checked it. There are exactly two places that can happen: **at startup**, or **the first time the value is read**. Only one of those is a good idea.

The rule: **a process with invalid configuration must refuse to start, loudly, and it must report every problem at once.** Not the first one — every one. Failing on the first error turns three typos into three deploy cycles, and each cycle is minutes during which nobody is fixing the actual problem.

What "validated" has to mean, concretely:

- **Typed.** `PORT` is an integer. `RETRY_BUDGET_PCT` is a float. `FEATURE_NEW_CHECKOUT` is a boolean, and this is where the worst bug in the category lives — every environment variable is a string, and in Python **every non-empty string is truthy**, so `bool(os.environ["FEATURE_NEW_CHECKOUT"])` on the value `"false"` is `True`. That is not a hypothetical; it is how a feature you explicitly disabled goes to production enabled.
- **Bounded.** `DB_POOL_SIZE` between 1 and 200. `LOG_LEVEL` one of four strings. A value that parses but is absurd is not a valid value.
- **Required-ness checked.** A missing `REGION` is a boot failure, not a `None` that reaches a formatting call an hour later.
- **Closed.** Unknown keys are an *error*, not something to ignore. An ignored unknown key is exactly what a typo looks like, and a typo'd key is silent by construction: you set `LOG_LEVL=debug`, nothing reads it, the default stays in force, and nothing anywhere reports a problem. Reject unknown keys and offer a suggestion — `difflib.get_close_matches` in the standard library turns `LOG_LEVL` into "did you mean `LOG_LEVEL`?" in one line.

Fail-fast also serves factor IX (disposability). A process that boots fast and dies fast is a process the orchestrator can restart freely — but only if "dies fast" means dying *before* it takes traffic. A process that starts, passes its startup probe, and then fails on a bad config value forty minutes later at 03:00 has converted a deploy-time error into an incident. [Health Checks & Probes](../../09-logging-monitoring-and-observability/08-health-checks-and-probes/) is the other half of this: validate in the startup path so the failure is a crash loop with a clear message, which is a bad deploy, rather than a slow poisoning, which is an outage.

### Config and secrets: same pipe, different handling

A secret is delivered the same way as any other config value and is handled completely differently after that. The delivery mechanism is shared — env var, mounted file, whatever your platform gives you. What changes is everything downstream:

- **Never logged.** Not at DEBUG, not "temporarily."
- **Never in a crash dump**, an exception report, or an error message. This is the one that bites: a validation error that says `SESSION_SIGNING_KEY 'hunter2' is too short` has just written the secret to a log line, an alert, and probably a ticket. **The error path is where secrets leak**, because it is the path nobody reviews.
- **Redacted in any config dump**, including the provenance report you just built to answer the 3am question.

The redaction should still be *useful*. Replacing a secret with `****` makes it impossible to answer "do staging and production have the same signing key?" — a question with a correct answer (no) and a real failure mode if it is yes. Emitting a short digest of the value instead — `<redacted sha256:41a3154e>` — is comparable across environments and reveals nothing.

Secret storage, rotation, envelope encryption and key hierarchies are a whole topic and they belong to [Secrets Management & Rotation](../../07-auth-and-security/13-secrets-management-and-rotation/). What belongs here is narrower: **a secret is a config value with a redaction obligation on every output path**, and that obligation has to be enforced by the config system, not by everyone remembering.

### Dev/prod parity and environment drift

Factor X asks you to keep environments similar. In practice the gap between environments is not a similarity problem, it is an *information* problem: **the difference between staging and production is exactly the set of behaviour nobody has tested.**

Three kinds of drift, in increasing order of how badly they behave:

**Missing keys.** A key set in one environment and unset in the other. The unset side silently takes the default, so there is no error and no log line — just a system quietly running a different code path from the one that was signed off. `FEATURE_NEW_CHECKOUT` on in staging and absent in production is five weeks of testing the wrong thing.

**Source drift.** The same key with the same value, supplied by a *different layer* in each environment. This is invisible until someone tries to change it: edit the file that staging reads and production, which takes it from the environment, does not move. The engineer who made the change watches staging update, concludes it worked, and ships. Value parity is not parity.

**Type drift.** A value that parses in one environment and not in the other — `MAX_UPLOAD_MB=25` in staging, `MAX_UPLOAD_MB=25MB` in production. With fail-fast validation this is a boot failure, which is the right outcome and the wrong *time*: you discover it during the rollout, at whatever hour the rollout happens.

All three are findable before either environment boots, because all three are visible in the config *sources*. The check costs nothing and it runs in CI.

## Build It

[`code/config_system.py`](code/config_system.py) is a working config system in five numbered sections: a layered resolver with provenance, typed fail-fast validation, secret redaction, release identity, and a parity checker. Standard library only, seeded, and it finishes in about **5 milliseconds** — this is arithmetic over dictionaries, not a simulation.

The schema is a tuple of `Field`s carrying everything a value needs to be checked before it is used:

```python
Field("SESSION_SIGNING_KEY", "str", required=True, secret=True, min_len=32,
      doc="HMAC key for session cookies"),
Field("REQUEST_TIMEOUT_MS", "int", default=3000, minimum=50, maximum=30000,
      doc="per-request deadline handed to downstream calls"),
Field("LOG_LEVEL", "str", default="info",
      choices=("debug", "info", "warn", "error"), doc="minimum level emitted"),
```

Resolution walks the layers in precedence order and keeps the whole chain, not just the winner. That single decision — recording the losers — is what makes provenance possible:

```python
for layer, mapping in env.raw_layers():
    if field.name not in mapping:
        continue
    raw = mapping[field.name]
    try:
        value = coerce(field, raw)
        validate(field, value)
    except CoercionError as exc:
        problems.append(Problem(field.name, layer, str(exc),
                                "declared type %s" % field.type))
        bad = True
        continue
    chain.append((layer, value))
...
source, value = chain[-1]
resolved[field.name] = Resolved(field.name, value, source, chain[:-1])
```

Note `problems.append` rather than `raise`. Every problem in every layer is collected, and the exception is thrown once at the end with all of them. Unknown keys are checked first, with the standard library doing the suggestion:

```python
near = difflib.get_close_matches(key, sorted(known), n=1, cutoff=0.6)
problems.append(Problem(
    key, layer, "unknown configuration key",
    "did you mean %s?" % near[0] if near else "not in the schema"))
```

Redaction is one function, used by every output path — the dump, the provenance table, and the parity report all call the same `display()`, so there is no surface that can forget. The validation errors are safe by *construction*: a `CoercionError` message is built from the field's own constraints and never from the offending value.

```python
def validate(field: Field, value: Any) -> None:
    ...
    if field.min_len is not None and len(str(value)) < field.min_len:
        # Length, not content. A secret's own value never enters an error string.
        raise CoercionError("length %d, minimum %d" % (len(str(value)), field.min_len))
```

The release identity is four lines, and the comment is the lesson:

```python
def config_hash(resolved: Mapping[str, Resolved]) -> str:
    """A canonical, order-independent digest of the EFFECTIVE values.

    Secrets are included: rotating a signing key changes the running system, so it
    changes the release. The digest is safe to print; the values never are.
    """
    canonical = "\n".join("%s=%r" % (k, resolved[k].value) for k in sorted(resolved))
    return hashlib.sha256(canonical.encode()).hexdigest()
```

Sorting the keys is what makes it *canonical* — the same effective config produces the same hash regardless of which layer supplied what or what order anything was read in. Without that, two identical configurations get two release ids and the whole scheme is noise.

Run it:

```bash
docker compose exec -T app python \
  phases/10-infrastructure-and-deployment/05-config-and-twelve-factor/code/config_system.py
```

```console
== 1 · LAYERED RESOLUTION WITH PROVENANCE ==
  precedence: default -> file -> env -> cli   (later wins)
  KEY                   EFFECTIVE VALUE                SOURCE   SHADOWED (layers that lost)
  CACHE_TTL_S           30                             file     default=60
  DATABASE_URL          <redacted sha256:6d1f9227>     env      -
  DB_POOL_SIZE          40                             cli      default=10, file=25
  FEATURE_NEW_CHECKOUT  False                          default  -
  LOG_LEVEL             debug                          cli      default=info, file=warn, env=info
  MAX_UPLOAD_MB         25                             file     default=25
  PORT                  9090                           env      default=8080
  REGION                eu-west-1                      env      -
  REQUEST_TIMEOUT_MS    1500                           env      default=3000, file=2000
  RETRY_BUDGET_PCT      10.0                           default  -
  SESSION_SIGNING_KEY   <redacted sha256:41a3154e>     env      -
  TRUSTED_PROXY_CIDRS   (empty)                        default  -
  LOG_LEVEL was set by 4 of the 4 layers. The live value is 'debug', from cli.
  Without this table the only honest answer to 'which value is live?'
  is to read four files and hope nobody exported anything on the pod.

== 2 · TYPED, VALIDATED, FAIL-FAST AT BOOT ==
  FATAL: refusing to start -- 7 configuration problem(s)
    [file] LOG_LEVL             unknown configuration key
                                did you mean LOG_LEVEL?
    [file] REQUEST_TIMEOUT      unknown configuration key
                                did you mean REQUEST_TIMEOUT_MS?
    [env ] PORT                 expected an integer
                                declared type int
    [-   ] REGION               required, and set by no layer
                                expected in file or env or cli
    [env ] DB_POOL_SIZE         above maximum 200
                                declared type int
    [file] MAX_UPLOAD_MB        expected an integer
                                declared type int
    [env ] SESSION_SIGNING_KEY  length 9, minimum 32
                                declared type str
    no request was served with this configuration.
  detected in 0.18 ms, before the listening socket was opened.
  one restart reports all 7 problems, not the first one.

  the type that bites hardest is bool. Every value from the environment
  is a string, and every non-empty string is truthy:
    naive : bool(os.environ['FEATURE_NEW_CHECKOUT'])  raw='false'  -> True
    typed : coerce(bool, 'false')                                  -> False
    the naive form ships a feature you explicitly turned off.

  the lazy alternative: read config where you use it, not at boot.
    fail-fast : 0 requests served. The process refused to start.
    lazy      : 50000 requests served; 1254 of them took the path that reads
                the typo'd key. Errors raised: 0. All 1254 silently used
                the fallback 3000 ms instead of the intended 800 ms.
    a typo that fails at boot costs one deploy. The same typo read lazily
    costs 1254 wrong answers and produces no error to find them by.

== 3 · SECRETS: REDACTION ON EVERY PATH, NOT JUST THE HAPPY ONE ==
  full config dump (the thing an operator curls at 03:00):
    CACHE_TTL_S           = 30                             (int)
    DATABASE_URL          = <redacted sha256:6d1f9227>     (secret)
    DB_POOL_SIZE          = 40                             (int)
    FEATURE_NEW_CHECKOUT  = False                          (bool)
    LOG_LEVEL             = debug                          (str)
    MAX_UPLOAD_MB         = 25                             (int)
    PORT                  = 9090                           (int)
    REGION                = eu-west-1                      (str)
    REQUEST_TIMEOUT_MS    = 1500                           (int)
    RETRY_BUDGET_PCT      = 10.0                           (float)
    SESSION_SIGNING_KEY   = <redacted sha256:41a3154e>     (secret)
    TRUSTED_PROXY_CIDRS   = (empty)                        (str)

  the same secret failing validation:
  FATAL: refusing to start -- 1 configuration problem(s)
    [env ] SESSION_SIGNING_KEY  length 9, minimum 32
                                declared type str
    no request was served with this configuration.

  proof -- does the raw secret appear anywhere?
    config dump          raw secret present: False
    provenance report    raw secret present: False
    validation error     raw secret present: False
  the fingerprint is a sha256 prefix: it survives comparison across
  environments and reveals nothing. Redaction that covers only the
  happy path is not redaction; the error path is where secrets leak.

== 4 · BUILD + CONFIG = RELEASE (ONE ARTIFACT, FOUR RELEASES) ==
  artifact (immutable, built once in lesson 3):
    sha256:9f2b41c7d0e8a35b6c1f4e92a7d83b05e6c14f7a92d3b8e05c71f4a6d29b8e30

  CONFIG                             CONFIG HASH          RELEASE ID
  staging                            50c6ea3de20efcba..   rel-789ff3a47436
  production                         3f5f623718513046..   rel-e1b2f40f9cf7
  production, timeout 2000 -> 1500   cf2629aee7108df9..   rel-3e5fa9b041f9
  production, signing key rotated    f563a0386674f08d..   rel-c6a604312935

  RELEASE                            ARTIFACT                   RELEASE ID
  staging                            sha256:9f2b41c7d0e8a35b..  rel-789ff3a47436
  production                         sha256:9f2b41c7d0e8a35b..  rel-e1b2f40f9cf7
  production, timeout 2000 -> 1500   sha256:9f2b41c7d0e8a35b..  rel-3e5fa9b041f9
  production, signing key rotated    sha256:9f2b41c7d0e8a35b..  rel-c6a604312935
  one artifact, 4 release ids, all distinct.
  release 3 differs from release 2 by one integer (REQUEST_TIMEOUT_MS
  2000 -> 1500). Release 4 differs by a rotated secret. Nothing was rebuilt.
  If you version only the artifact, all four collapse to sha256:9f2b41c7d0e8a35b..,
  and 'roll back' has exactly 1 target where it needs 4.

== 5 · ENVIRONMENT PARITY: THE DRIFT REPORT ==
  comparing config SOURCES for staging vs production, in CI, before boot

  KIND     KEY                   DETAIL
  MISSING  FEATURE_NEW_CHECKOUT  set in staging (env), absent in production; production falls back to default False
  TYPE     MAX_UPLOAD_MB         declared int; production supplies a value that does not parse (expected an integer)
  SOURCE   REQUEST_TIMEOUT_MS    same key, different layer: staging=file vs production=env
  MISSING  TRUSTED_PROXY_CIDRS   set in production (file), absent in staging; staging falls back to default (empty)

  4 findings (MISSING=2, SOURCE=1, TYPE=1); 6 keys matching (same layer, both environments): CACHE_TTL_S, DATABASE_URL, DB_POOL_SIZE, LOG_LEVEL, REGION, SESSION_SIGNING_KEY

  secrets are compared by fingerprint, never by value -- and here you WANT
  them to differ. A shared signing key across environments is its own bug:
    DATABASE_URL          staging sha256:7cf6005d   production sha256:bc968728   distinct
    SESSION_SIGNING_KEY   staging sha256:7eb81caf   production sha256:9e839211   distinct

  what each finding costs if it ships:
    MISSING  FEATURE_NEW_CHECKOUT is on in staging and absent in production,
             so production runs the OLD checkout. Every staging sign-off
             tested code production is not running.
    MISSING  TRUSTED_PROXY_CIDRS is set only in production, so the one
             environment that parses X-Forwarded-For is the one nobody tests.
    TYPE     MAX_UPLOAD_MB='25MB' parses in nobody's schema. Staging boots,
             production refuses to start -- discovered during the rollout.
    SOURCE   REQUEST_TIMEOUT_MS is 2000 in both, but staging reads it from a
             file and production from the environment. Change the file and
             production does not move.

  production, booted for real -- the TYPE finding, discovered the
  expensive way, during a rollout:
    FATAL: refusing to start -- 1 configuration problem(s)
      [file] MAX_UPLOAD_MB        expected an integer
                                  declared type int
      no request was served with this configuration.
  the parity checker found the same defect in 0.06 ms, in CI, with no
  cluster, no image pull and no paged engineer involved.

  (total wall time 5 ms)
```

Read what each section proves.

**Section 1 is the answer to the opening scene, printed.** `LOG_LEVEL` was set by **4 of 4 layers**, and three of those four say something other than the live value. The default says `info`, the file says `warn`, the environment says `info`, and the effective value is `debug` because a command-line flag beat all of them. Every one of those layers is a file or a template someone could open during an incident, and **three of the four would give a confident wrong answer.** `REQUEST_TIMEOUT_MS` — the key from the 03:04 story — resolves to `1500` from the environment, shadowing a file that says `2000` and a default that says `3000`, which is exactly the three-way disagreement that cost eleven minutes. The table costs nothing to produce because the resolver kept the chain instead of throwing it away.

Two smaller things in that table are worth noticing. `MAX_UPLOAD_MB` shows `file` winning over a default of the *same* value, 25 — a config line that does nothing but will be treated as load-bearing by the next person to read it. And `FEATURE_NEW_CHECKOUT` shows `default` as its source, which is the flag production is silently running in the parity section below.

**Section 2 is the cost of the two strategies, side by side.** A single boot found **7 problems in 0.18 ms**, before a socket was opened: two typo'd keys with suggestions, two unparseable values, one out-of-range value, one missing required value, and one secret that is too short. Reporting all seven matters — at one problem per restart, this deploy takes seven cycles. The `bool` line is the trap in isolation: `bool("false")` is `True`, so the naive read of a feature flag ships a feature that was explicitly disabled, and it does so with no error anywhere.

Then the comparison that should settle the argument. **Fail-fast: 0 requests served with the wrong value.** Lazy: **50,000 requests served, 1,254 of which took the code path that reads the typo'd key, 0 errors raised**, and every one of those 1,254 silently used the fallback of 3000 ms instead of the intended 800 ms. That is the shape of the failure — not a crash, not an exception, not a log line. A wrong number, used correctly, 1,254 times. And a 3000 ms downstream timeout against a caller who gave up at 1000 ms is the exact waste Phase 8 measured: a worker occupied for three times the caller's remaining budget, producing an answer nobody is waiting for.

**Section 3 proves the redaction rather than claiming it.** The config dump, the provenance report and the validation error are all searched for the raw secret, and all three come back **False**. The important one is the third: the failing key is 9 characters against a 32-character minimum, and the error says `length 9, minimum 32` — enough to fix it, with nothing to leak. The fingerprints stay useful: `<redacted sha256:41a3154e>` is comparable across environments and reversible by nobody.

**Section 4 is the identity argument, measured.** One artifact digest, four configurations, **4 distinct release ids**. Releases 2 and 3 differ by a single integer. Releases 3 and 4 differ only by a rotated signing key. Nothing was rebuilt for any of them — the artifact string is byte-identical across all four rows. Now do the thought experiment the last two lines do for you: if your deployment history records only image digests, all four of those states collapse to one row, and the question "roll back to what we had before the timeout change" has **1 candidate answer where it needs 4**. The system cannot express the change you are trying to undo.

**Section 5 catches the 08:50 follow-up before it happens.** Comparing staging's and production's config sources produced **4 findings — 2 MISSING, 1 SOURCE, 1 TYPE — against 6 matching keys**, in **0.06 ms**. `FEATURE_NEW_CHECKOUT` is the five-week drift from the opening. `TRUSTED_PROXY_CIDRS` is the same problem pointing the other way: production is the only environment that parses `X-Forwarded-For`, so the header-handling code has never run anywhere it could be tested. `REQUEST_TIMEOUT_MS` is source drift with identical values — the kind that passes every review and then ignores your edit. And `MAX_UPLOAD_MB='25MB'` is a boot failure that production, and only production, would have discovered *during the rollout*: the section prints that failure, then points out the checker found it in CI for 0.06 ms and no cluster.

The secret comparison is the small feature with the largest payoff per line. The fingerprints differ across environments, which is what you want; had they matched, you would have found a staging key signing production sessions without ever printing either.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 500" width="100%" style="max-width:840px" role="img" aria-label="The parity drift report comparing staging and production configuration sources. Six keys match, shown in green, including secrets compared by fingerprint rather than value. One key, REQUEST_TIMEOUT_MS, has the same value but comes from a different layer in each environment and is marked amber for source drift. Two keys are set in only one environment and are marked red for missing. One key, MAX_UPLOAD_MB, has a production value that does not parse as an integer and is marked red for type drift. Four findings in total.">
  <text x="440" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">The drift report: 4 findings, 6 keys matching — found in CI, before either boots</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">

    <g fill="currentColor" font-size="9" font-weight="700" opacity="0.65">
      <text x="46" y="66">KEY</text>
      <text x="292" y="66">STAGING</text>
      <text x="484" y="66">PRODUCTION</text>
      <text x="672" y="66">VERDICT</text>
    </g>
    <path d="M32 74 L 848 74" fill="none" stroke="currentColor" stroke-width="1.2" opacity="0.4"/>

    <g fill="none" stroke-width="1.8" stroke-linejoin="round">
      <rect x="32" y="84" width="816" height="38" rx="7" fill="#0fa07f" fill-opacity="0.10" stroke="#0fa07f"/>
      <rect x="32" y="128" width="816" height="38" rx="7" fill="#0fa07f" fill-opacity="0.10" stroke="#0fa07f"/>
      <rect x="32" y="172" width="816" height="38" rx="7" fill="#0fa07f" fill-opacity="0.10" stroke="#0fa07f"/>
      <rect x="32" y="226" width="816" height="38" rx="7" fill="#e0930f" fill-opacity="0.14" stroke="#e0930f"/>
      <rect x="32" y="270" width="816" height="38" rx="7" fill="#d64545" fill-opacity="0.12" stroke="#d64545"/>
      <rect x="32" y="314" width="816" height="38" rx="7" fill="#d64545" fill-opacity="0.12" stroke="#d64545"/>
      <rect x="32" y="358" width="816" height="38" rx="7" fill="#d64545" fill-opacity="0.12" stroke="#d64545"/>
    </g>

    <g fill="currentColor" font-size="10">
      <text x="46" y="108" font-weight="700">REGION</text>
      <text x="292" y="108">env&#8195;= us-east-1</text>
      <text x="484" y="108">env&#8195;= eu-west-1</text>
      <text x="46" y="152" font-weight="700">LOG_LEVEL</text>
      <text x="292" y="152">file = debug</text>
      <text x="484" y="152">file = info</text>
      <text x="46" y="196" font-weight="700">DATABASE_URL</text>
      <text x="292" y="196">env&#8195;= &lt;sha256:7cf6005d&gt;</text>
      <text x="484" y="196">env&#8195;= &lt;sha256:bc968728&gt;</text>

      <text x="46" y="250" font-weight="700">REQUEST_TIMEOUT_MS</text>
      <text x="292" y="250">file = 2000</text>
      <text x="484" y="250">env&#8195;= 2000</text>
      <text x="46" y="294" font-weight="700">FEATURE_NEW_CHECKOUT</text>
      <text x="292" y="294">env&#8195;= true</text>
      <text x="484" y="294" opacity="0.75">— not set — default false</text>
      <text x="46" y="338" font-weight="700">TRUSTED_PROXY_CIDRS</text>
      <text x="292" y="338" opacity="0.75">— not set — default &quot;&quot;</text>
      <text x="484" y="338">file = 10.0.0.0/8</text>
      <text x="46" y="382" font-weight="700">MAX_UPLOAD_MB</text>
      <text x="292" y="382">file = 25</text>
      <text x="484" y="382">file = &quot;25MB&quot;</text>
    </g>

    <g font-size="10.5" font-weight="700">
      <text x="672" y="102" fill="#0fa07f">matching</text>
      <text x="672" y="146" fill="#0fa07f">matching</text>
      <text x="672" y="190" fill="#0fa07f">matching</text>
      <text x="672" y="244" fill="#e0930f">SOURCE drift</text>
      <text x="672" y="288" fill="#d64545">MISSING</text>
      <text x="672" y="332" fill="#d64545">MISSING</text>
      <text x="672" y="376" fill="#d64545">TYPE drift</text>
    </g>
    <g font-size="8.5">
      <text x="672" y="115" fill="#0fa07f" opacity="0.9">same layer, both envs</text>
      <text x="672" y="159" fill="#0fa07f" opacity="0.9">values differ — expected</text>
      <text x="672" y="203" fill="#0fa07f" opacity="0.9">fingerprints differ — good</text>
      <text x="672" y="257" fill="#e0930f" opacity="0.95">edit the file, prod ignores it</text>
      <text x="672" y="301" fill="#d64545" opacity="0.95">prod runs the OLD checkout</text>
      <text x="672" y="345" fill="#d64545" opacity="0.95">the path staging never tests</text>
      <text x="672" y="389" fill="#d64545" opacity="0.95">prod refuses to boot</text>
    </g>

    <text x="46" y="221" font-size="8.5" fill="currentColor" opacity="0.7">+ CACHE_TTL_S, DB_POOL_SIZE and SESSION_SIGNING_KEY also match — 6 matching keys in total</text>

    <text x="440" y="424" font-size="10.5" text-anchor="middle" fill="currentColor" opacity="0.95">Values are allowed to differ — that is what environments are for. What must not differ is which keys</text>
    <text x="440" y="442" font-size="10.5" text-anchor="middle" fill="currentColor" opacity="0.95">exist, what layer supplies them, and whether they parse. Checked in under a millisecond, in CI.</text>
    <text x="440" y="474" font-size="11" text-anchor="middle" fill="currentColor" opacity="0.9">A key that exists in staging and not in production is a latent outage with a deploy date.</text>
  </g>
</svg>
```

## Use It

### `pydantic-settings` — sections 2 and 3, as a dependency

Nobody hand-writes a coercion table in production Python. `pydantic-settings` (the settings half of Pydantic, and an allowed dependency in this curriculum) gives you the typed, validated, fail-fast layer directly:

```python
from typing import Literal
from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="APP_",
        env_file=".env",          # local development only — see below
        extra="forbid",           # unknown keys are an ERROR, not a shrug
        case_sensitive=True,
    )
    port: int = Field(8080, ge=1, le=65535)
    log_level: Literal["debug", "info", "warn", "error"] = "info"
    request_timeout_ms: int = Field(3000, ge=50, le=30000)
    region: Literal["us-east-1", "eu-west-1", "ap-south-1"]      # required
    feature_new_checkout: bool = False                            # parses "false"
    database_url: SecretStr                                       # required, redacted
    session_signing_key: SecretStr = Field(min_length=32)

settings = Settings()          # raises ValidationError at import time: fail fast
```

Line by line against what you just built. `Field(..., ge=, le=)` is `minimum`/`maximum`. `Literal[...]` is `choices`. A field with no default is `required=True`. `bool` gets Pydantic's own string parsing, which handles `"false"` correctly — the trap from section 2 is closed for you. **`extra="forbid"` is the unknown-key check, and it is not the default** — leave it out and `APP_LOG_LEVL=debug` is silently ignored, exactly as in the naive case. Pydantic reports every violation in one `ValidationError` rather than the first, which is the multi-problem boot error. And constructing `Settings()` at import time is what makes it fail *at boot*.

`SecretStr` is the redaction: its `repr()` and `str()` render as `**********`, so the common accidental path — an f-string in a log line, an exception that prints the model — is covered. Be precise about what it does not do: `.get_secret_value()` returns the plaintext and nothing stops that plaintext reaching a logger. The obligation from section 3 still has to be a habit; `SecretStr` just removes the easiest way to break it.

The one thing it does **not** give you is section 1. Pydantic has a documented source precedence (init arguments, then environment, then dotenv, then a secrets directory) and you can reorder it with `settings_customise_sources`, but the resolved model does not carry *where each value came from*. If you want the provenance answer at 03:00 you still have to build it — keep the raw layers around and diff them against the resolved model, the way `Resolved.shadowed` does.

### Kubernetes: `ConfigMap`, `Secret`, and the annotation that everyone omits

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: api-config
data:
  LOG_LEVEL: "info"
  REQUEST_TIMEOUT_MS: "2000"
  MAX_UPLOAD_MB: "25"
---
apiVersion: v1
kind: Secret
metadata:
  name: api-secrets
type: Opaque
stringData:                       # base64 is an ENCODING, not encryption
  DATABASE_URL: "postgres://app:...@db.prod:5432/orders"
  SESSION_SIGNING_KEY: "..."
---
apiVersion: apps/v1
kind: Deployment
spec:
  template:
    metadata:
      annotations:
        # WITHOUT THIS LINE, editing the ConfigMap above changes nothing.
        # This is the config hash from section 4, in the one place the
        # control loop will notice it.
        checksum/config: "3f5f623718513046"
    spec:
      containers:
        - name: api
          image: registry.example.com/api@sha256:9f2b41c7d0e8a35b...
          envFrom:
            - configMapRef: { name: api-config }
            - secretRef:    { name: api-secrets }
```

Three things in there deserve to be surprising.

**Editing a ConfigMap does not restart anything.** This is the genuinely counterintuitive default. A Deployment rolls out when its **pod template** changes — that is the object the controller hashes to decide whether it needs a new ReplicaSet. Editing a ConfigMap leaves the pod template byte-identical, so no new ReplicaSet is created, no pod is replaced, and the running processes keep the values they read at startup. You changed the config, `kubectl apply` reported success, and **nothing happened**. New pods created later for unrelated reasons will pick up the new value, which produces the worst possible state: a fleet running two different configurations with no record of which is which.

The fix is the `checksum/config` annotation: a digest of the ConfigMap's contents, written into the pod template. Change the ConfigMap, the digest changes, the pod template changes, and a normal rolling update happens. Helm charts conventionally generate it with `sha256sum` over the rendered ConfigMap; any templating tool can do the same. **This annotation is precisely the release id from section 4** — it is the mechanism by which `release = build + config` becomes true in a system that would otherwise only version the build.

**Mounted ConfigMaps behave differently from `envFrom`.** A ConfigMap mounted as a volume *is* updated in place by the kubelet, eventually — on its sync period, typically around a minute, and not at all if you used `subPath`. Environment variables are read once, at `execve`, and never change for the life of the process. So "does my config update without a restart?" has three different answers depending on how you delivered it, and only one of them is "no, and reliably so." Prefer the reliable one: deliver via environment or a file, validate at boot, and make a config change a rollout.

**A ConfigMap key that is not a valid environment variable name is silently skipped** by `envFrom`. Kubernetes records an event on the pod; your process just never sees the variable, and with a closed schema it will at least fail on a missing required key rather than run with a default.

Two more rules that belong here. A `Secret`'s `data` is **base64, which is an encoding and not encryption** — anyone with read access to the object has the plaintext, so RBAC (role-based access control) on Secrets is the actual control. And use a **digest reference** (`image: repo/api@sha256:...`) rather than a tag: a tag is mutable, so `image: api:v2` means two pods created a day apart can be running different code with identical manifests. Lesson 4 covers why.

### `.env` files, and why baking one into an image is an anti-pattern

A `.env` file is a good local-development affordance: it keeps your shell clean, it is easy to share the *shape* of (commit a `.env.example` with keys and no values), and every framework reads one. Two rules.

**Never commit it.** It will contain a credential eventually, and git history is forever — this is the single most common way a secret reaches a public repository.

**Never bake it into an image.** It breaks build/release/run at the most fundamental level: the artifact now knows which environment it is for, so there is no longer one artifact promoted through environments, there are N artifacts that were built from the same source and tested separately. And it is worse than it looks, because of how images are built — as Lesson 3 showed, layers are additive and content-addressed. A `COPY .env .` in one layer followed by `RUN rm .env` in a later one **does not remove the secret**; the earlier layer still contains it, it is still in the image, it is still pushed to the registry, and anyone who can pull the image can extract it with `docker save`. Deleting a file in a later layer hides it from the running filesystem and from nobody else.

### Secrets at rest: SOPS, Sealed Secrets, External Secrets

Config can live in git. Secrets need one more step, and there are three common shapes. Details, rotation policy and key hierarchies are [Secrets Management & Rotation](../../07-auth-and-security/13-secrets-management-and-rotation/); the operational summary:

- **SOPS** (Secrets OPerationS) encrypts the *values* in a YAML or JSON file with a key from KMS, age or PGP, leaving the keys in plaintext. The file is safe to commit and still diffs usefully — you can see that `DATABASE_URL` changed without seeing what it changed to. Decryption happens at deploy time, wherever your pipeline holds the key.
- **Sealed Secrets** runs a controller in the cluster that holds a private key. You encrypt a `SealedSecret` with the matching public key and commit it; only that cluster can decrypt it into a real `Secret`. Simple, cluster-scoped, and rotation means re-sealing everything.
- **External Secrets Operator** keeps no ciphertext in git at all. A controller reads from Vault, AWS Secrets Manager, GCP Secret Manager or similar and syncs the values into a `Secret` on a refresh interval. The best rotation story of the three — rotate in the source of truth and the cluster follows — at the cost of a live dependency on that source of truth at deploy time.

Whichever you pick, the config system's job is unchanged: the secret arrives as a value, gets validated with the same schema, and is redacted on every output path.

### Production rules

- **Config comes from the environment; the artifact never knows which environment it is in.** One image promoted from staging to production, not one image built per environment. If your build pipeline takes an environment name as an input, build and release are merged.
- **Validate at boot, completely, and refuse to start.** Types, ranges, enums, required-ness, and unknown keys. Report every problem in one message. Measured here: 7 defects in 0.18 ms, versus 1,254 requests silently served with a wrong value under lazy reads.
- **Never log a secret, and check the error path.** The happy-path dump is the easy half. Make redaction a property of the config type, not a rule people remember, and assert in a test that no output surface contains a known secret value.
- **Version the release, not just the artifact.** `release_id = hash(artifact + config)`, recorded in your deploy history, so a config-only change is a first-class, rollback-able event. In Kubernetes this is the `checksum/config` annotation, and without it a ConfigMap edit rolls out nothing at all.
- **Keep an environment matrix in the repo** — every key, its type, whether it is required, whether it is a secret, and its value or source in each environment — and **run the parity check in CI**. Four findings in 0.06 ms is cheaper than one of them reaching a rollout.
- **Make the running config introspectable.** An authenticated endpoint (`/debug/config`) that returns each key's effective value, its source layer, and the layers it shadowed, with secrets redacted. Authenticated is not optional — the health-checks lesson makes the same point about probe endpoints, and a config endpoint is strictly more sensitive. This is the eleven minutes at 03:04, given back.

## Think about it

1. Your resolver has four layers and the effective `REQUEST_TIMEOUT_MS` is `1500` from the environment, shadowing a file that says `2000`. An engineer opens a pull request changing the file to `1200`, sees staging pick it up, and ships. What happens in production, how long before anyone notices, and which of the three drift categories would have caught it before merge?
2. The config hash covers secrets, so a key rotation produced a fourth release id over the same artifact. Argue the other side: what breaks if you *exclude* secret values from the config hash and hash only their names? Which of the two designs makes an incident timeline more truthful, and which makes your deploy history noisier?
3. `bool("false")` is `True`, and 1,254 requests used a 3000 ms fallback where 800 ms was intended, raising zero errors. Design a test that would have failed in CI for both defects. What does that test have to know that a unit test of your handler does not?
4. You add `checksum/config` and now every ConfigMap edit triggers a full rolling restart of 200 pods. A colleague proposes mounting the ConfigMap as a volume instead so pods pick up changes without restarting. Enumerate what that buys and what it costs — specifically, what is now true about the fleet during the kubelet's sync window, and which of your validations no longer runs.
5. Your parity checker reports 4 findings, and two of them (`TRUSTED_PROXY_CIDRS` in production only, and the source drift on `REQUEST_TIMEOUT_MS`) are deliberate. Design the suppression mechanism. Where does the suppression live, who reviews it, what stops it from silently accumulating until the check reports nothing, and how would you make an expired suppression fail the build?

## Key takeaways

- **The twelve-factor manifesto is the shared vocabulary and it is fifteen years old.** Use factors III, V, IX, X and XI; read IV and XI with the era in mind. Factor III's durable claim is not "put everything in environment variables" — env vars are readable in `/proc/<pid>/environ`, inherited by children, and visible in `docker inspect` — it is that **config must not live in the artifact**.
- **`release = build + config`, and the pair needs its own id.** One artifact digest plus four configurations produced **4 distinct release ids**, two of them differing by a single integer and a rotated secret respectively, with nothing rebuilt. Version only the artifact and all four collapse to one digest, so "roll back" has **1 target where it needs 4**.
- **Precedence must be documented, deterministic and *introspectable*.** `LOG_LEVEL` was set by **4 of 4 layers**; the live value came from the command line and **three of the four layers would have given a confident wrong answer** to someone reading a file at 03:00. Keeping the shadowed chain costs nothing and is the entire answer.
- **Validate at boot, report everything, refuse to start.** One boot check found **7 defects in 0.18 ms** — including two typo'd keys with "did you mean" suggestions — before a socket was opened. The lazy alternative served **50,000 requests, 1,254 of which used a 3000 ms fallback instead of the intended 800 ms and raised 0 errors.** And `bool("false")` is `True`, which is how a disabled feature ships enabled.
- **Redaction is a property of the config type, and the error path is where secrets leak.** All three output surfaces — dump, provenance report, and validation error — were checked for the raw secret and all three returned **False**; the failure still said `length 9, minimum 32`, enough to fix and nothing to leak. Fingerprints (`<redacted sha256:41a3154e>`) keep secrets comparable across environments without revealing them.
- **Drift is findable before anything boots.** Comparing two environments' config *sources* produced **4 findings — 2 MISSING, 1 SOURCE, 1 TYPE — against 6 matching keys, in 0.06 ms.** One of them was a boot failure production would otherwise have discovered mid-rollout. And in Kubernetes, **editing a ConfigMap rolls out nothing** unless a `checksum/config` annotation puts the config hash into the pod template.

Next: [Infrastructure as Code: Desired State, Plan, Apply & Drift](../06-infrastructure-as-code/) — you have now versioned the config that varies per environment; the next question is who creates the environment itself, and how a tool tells you what it is about to change before it changes it.
