# Images, Layers & the Reproducible Build

> Three different diseases wear the same costume — "the build is bad." Measured here with a miniature OCI builder: moving two lines of a Dockerfile took a one-line code change from **551.21 s and 215.16 MB rebuilt down to 3.21 s and 410.4 KB — 171.6x faster, 537x fewer bytes** — and then the honest reverse, where changing the *lockfile* instead collapses that lead to **1.16x**. A `rm -rf` that deleted **30.38 MB** of files made the image **64 bytes bigger** and left the deploy key it "removed" sitting in layer 2, recovered verbatim. And the same source built twice produced two different images until three specific things were normalised, after which both builds landed on the identical digest `sha256:280fe298a8fa…`.

**Type:** Build
**Languages:** Python
**Prerequisites:** [What a Container Actually Is](../02-what-a-container-actually-is/)
**Time:** ~80 minutes

## The Problem

It is 16:40 on a Thursday. You changed one line in `src/routes.py` — a log message — and pushed. The pipeline has been running for nine minutes. You are watching a progress bar reinstall `gcc`.

Nothing is broken. This is the build working exactly as configured. Somebody wrote a Dockerfile that copies the whole repository in at the top and installs dependencies underneath it, and every build since has reinstalled the entire dependency tree because a log message changed. Nobody has looked at that file in two years, because it *works*.

While you wait, three other things are also true, and everyone in your team has learned to describe all three with the same sentence: "the build is bad."

**The image is 1.2 GB.** Your application is 400 KB of Python. Somebody added `RUN rm -rf /var/lib/apt/lists /root/.cache` at the end last quarter to fix it. The image did not get smaller. It got *very slightly larger*, and the person who did it assumed they had measured wrong and moved on.

**The build was green yesterday and is red today, and nothing changed.** Same commit hash. Same base image tag. Same lockfile. A transitive dependency published a new version four hours ago, your requirements file pins the top-level package but not that one, and the build resolved a different tree than it did yesterday. You cannot reproduce yesterday's artifact, because yesterday's artifact was never a function of your source alone.

**And the security review from last month is still open**, asking why a deploy key appears in the image history. It was copied in during the build and removed in the next instruction. Someone has already replied "that's fixed, we delete it."

These are **three distinct failures — cache invalidation, size, and non-determinism** — with three distinct causes and three distinct fixes. They get merged into one complaint because they share a symptom (the build is slow and annoying) and a venue (the Dockerfile). Treating them as one problem is why the fixes people reach for are so often the wrong ones: adding `--no-cache` to fix flakiness, adding `rm -rf` to fix size, adding a bigger CI runner to fix speed. None of those address what is actually happening.

The previous lesson took a container apart and found a process, some namespaces, some cgroups, and a stack of read-only layers with one writable layer on top. It built the overlay by hand: reads walk down, writes copy up, deletes write a whiteout. That is the *runtime* half. This lesson is the other half: **where those layers come from, what decides whether you have to make them again, and why the same source can produce two different ones.**

## The Concept

### What an image actually is

An image is not a filesystem, and it is not a tarball of a filesystem. Per the **OCI image specification** (OCI = Open Container Initiative, the vendor-neutral body that standardised the format Docker originally created), an image is three kinds of thing, each addressed by the SHA-256 hash of its own bytes:

- A **manifest** — a small JSON document listing one config descriptor and an ordered list of layer descriptors. Each descriptor is a media type, a `sha256:` digest, and a size in bytes. The manifest contains no file data at all.
- A **config blob** — the recipe. Environment variables, the entrypoint and command, working directory, architecture and OS, the build history, and `rootfs.diff_ids`: the **ordered** list of layer digests. Also no file data.
- **Layer blobs** — tar streams. These, and only these, contain bytes of files.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 500" width="100%" style="max-width:840px" role="img" aria-label="An OCI image drawn as three separate things. On the left a manifest lists one config descriptor and six layer descriptors, each a sha256 digest and a byte count. In the middle the config blob holds the recipe — environment, command and the ordered list of rootfs diff ids — and contains no file bytes at all, while below it the six layer blobs are the tar streams that do hold the bytes, from a forty five megabyte base to a thirty nine kilobyte compile step. On the right the six layers are stacked bottom up into the merged filesystem the process actually sees at slash, seventy seven files and two hundred sixty megabytes. The image digest at the bottom is the sha256 of the manifest, and that is what an at sha256 reference pins.">
  <defs>
    <marker id="l03-a1" markerWidth="10" markerHeight="10" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker>
  </defs>
  <text x="440" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">An image is not a filesystem. It is a recipe plus content-addressed tarballs.</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">

    <rect x="20" y="52" width="252" height="228" rx="11" fill="#7c5cff" fill-opacity="0.12" stroke="#7c5cff" stroke-width="2"/>
    <text x="32" y="74" font-size="11.5" font-weight="700" fill="#7c5cff">MANIFEST</text>
    <text x="32" y="88" font-size="8" fill="currentColor" opacity="0.8">vnd.oci.image.manifest.v1+json</text>
    <text x="32" y="106" font-size="8" fill="currentColor" opacity="0.6" font-weight="700">DESCRIPTOR</text>
    <text x="110" y="106" font-size="8" fill="currentColor" opacity="0.6" font-weight="700">sha256 (12)</text>
    <text x="262" y="106" font-size="8" fill="currentColor" opacity="0.6" font-weight="700" text-anchor="end">SIZE</text>
    <g fill="currentColor" font-size="9">
      <text x="32" y="124">config</text><text x="110" y="124">b42926188bc1</text><text x="262" y="124" text-anchor="end">1.3 KB</text>
      <text x="32" y="144">layer 0</text><text x="110" y="144">e693baeb1edf</text><text x="262" y="144" text-anchor="end">45.08 MB</text>
      <text x="32" y="162">layer 1</text><text x="110" y="162">b7ea1f01be65</text><text x="262" y="162" text-anchor="end">153.24 MB</text>
      <text x="32" y="180">layer 2</text><text x="110" y="180">2cccdc79f27c</text><text x="262" y="180" text-anchor="end">378 B</text>
      <text x="32" y="198">layer 3</text><text x="110" y="198">385710d90ae0</text><text x="262" y="198" text-anchor="end">61.52 MB</text>
      <text x="32" y="216">layer 4</text><text x="110" y="216">7b0253e55205</text><text x="262" y="216" text-anchor="end">371.5 KB</text>
      <text x="32" y="234">layer 5</text><text x="110" y="234">0497a31ba360</text><text x="262" y="234" text-anchor="end">39.0 KB</text>
    </g>
    <text x="32" y="256" font-size="9" fill="currentColor" opacity="0.9">6 layers, 260.24 MB of blobs</text>
    <text x="32" y="270" font-size="9" font-weight="700" fill="#7c5cff">the manifest holds no bytes either</text>

    <rect x="300" y="52" width="252" height="152" rx="11" fill="#3553ff" fill-opacity="0.11" stroke="#3553ff" stroke-width="2"/>
    <text x="312" y="74" font-size="11.5" font-weight="700" fill="#3553ff">CONFIG BLOB — the recipe half</text>
    <text x="312" y="88" font-size="8" fill="currentColor" opacity="0.8">vnd.oci.image.config.v1+json</text>
    <g fill="currentColor" font-size="9">
      <text x="312" y="108">Env</text><text x="372" y="108">PORT=8080</text>
      <text x="312" y="124">Cmd</text><text x="372" y="124">python /app/src/main.py</text>
      <text x="312" y="140">WorkingDir</text><text x="392" y="140">/</text>
    </g>
    <text x="312" y="160" font-size="9" font-weight="700" fill="#3553ff">rootfs.diff_ids — ORDERED, load-bearing</text>
    <text x="312" y="174" font-size="8.5" fill="currentColor" opacity="0.9">e693.. b7ea.. 2ccc.. 3857.. 7b02.. 0497..</text>
    <text x="312" y="192" font-size="9" font-weight="700" fill="#d64545">not one byte of any file lives here</text>

    <rect x="300" y="220" width="252" height="204" rx="11" fill="#7c5cff" fill-opacity="0.12" stroke="#7c5cff" stroke-width="2"/>
    <text x="312" y="242" font-size="11.5" font-weight="700" fill="#7c5cff">LAYER BLOBS — the bytes</text>
    <g stroke-width="1.4">
      <rect x="312" y="252" width="228" height="26" rx="5" fill="#7c5cff" fill-opacity="0.14" stroke="#7c5cff"/>
      <rect x="312" y="280" width="228" height="26" rx="5" fill="#7c5cff" fill-opacity="0.14" stroke="#7c5cff"/>
      <rect x="312" y="308" width="228" height="26" rx="5" fill="#7c5cff" fill-opacity="0.14" stroke="#7c5cff"/>
      <rect x="312" y="336" width="228" height="26" rx="5" fill="#7c5cff" fill-opacity="0.14" stroke="#7c5cff"/>
      <rect x="312" y="364" width="228" height="26" rx="5" fill="#7c5cff" fill-opacity="0.14" stroke="#7c5cff"/>
      <rect x="312" y="392" width="228" height="26" rx="5" fill="#7c5cff" fill-opacity="0.14" stroke="#7c5cff"/>
    </g>
    <g fill="currentColor" font-size="8.5">
      <text x="322" y="264" font-weight="700">FROM python:3.12-slim</text><text x="532" y="264" text-anchor="end" font-weight="700">45.08 MB</text><text x="322" y="274" opacity="0.75">e693baeb1edf</text>
      <text x="322" y="292" font-weight="700">RUN apt-get install</text><text x="532" y="292" text-anchor="end" font-weight="700">153.24 MB</text><text x="322" y="302" opacity="0.75">b7ea1f01be65</text>
      <text x="322" y="320" font-weight="700">COPY requirements.txt</text><text x="532" y="320" text-anchor="end" font-weight="700">378 B</text><text x="322" y="330" opacity="0.75">2cccdc79f27c</text>
      <text x="322" y="348" font-weight="700">RUN pip install</text><text x="532" y="348" text-anchor="end" font-weight="700">61.52 MB</text><text x="322" y="358" opacity="0.75">385710d90ae0</text>
      <text x="322" y="376" font-weight="700">COPY src /app/src</text><text x="532" y="376" text-anchor="end" font-weight="700">371.5 KB</text><text x="322" y="386" opacity="0.75">7b0253e55205</text>
      <text x="322" y="404" font-weight="700">RUN compileall</text><text x="532" y="404" text-anchor="end" font-weight="700">39.0 KB</text><text x="322" y="414" opacity="0.75">0497a31ba360</text>
    </g>

    <rect x="580" y="52" width="276" height="372" rx="11" fill="#0fa07f" fill-opacity="0.11" stroke="#0fa07f" stroke-width="2"/>
    <text x="592" y="74" font-size="11.5" font-weight="700" fill="#0fa07f">MERGED VIEW — what runs</text>
    <text x="592" y="88" font-size="8.5" fill="currentColor" opacity="0.85">the union mount lesson 2 built by hand</text>
    <g stroke-width="1.5">
      <rect x="600" y="100" width="240" height="24" rx="5" fill="#0fa07f" fill-opacity="0.10" stroke="#0fa07f" stroke-dasharray="5 4"/>
      <rect x="600" y="128" width="240" height="22" rx="5" fill="#7c5cff" fill-opacity="0.16" stroke="#7c5cff"/>
      <rect x="600" y="154" width="240" height="22" rx="5" fill="#7c5cff" fill-opacity="0.16" stroke="#7c5cff"/>
      <rect x="600" y="180" width="240" height="22" rx="5" fill="#7c5cff" fill-opacity="0.16" stroke="#7c5cff"/>
      <rect x="600" y="206" width="240" height="22" rx="5" fill="#7c5cff" fill-opacity="0.16" stroke="#7c5cff"/>
      <rect x="600" y="232" width="240" height="22" rx="5" fill="#7c5cff" fill-opacity="0.16" stroke="#7c5cff"/>
      <rect x="600" y="258" width="240" height="22" rx="5" fill="#7c5cff" fill-opacity="0.16" stroke="#7c5cff"/>
    </g>
    <g fill="currentColor" font-size="8.5">
      <text x="610" y="116" font-weight="700" fill="#0fa07f">upper — writable, private, EMPTY at start</text>
      <text x="610" y="143">diff_id 5&#8195;compiled bytecode</text>
      <text x="610" y="169">diff_id 4&#8195;your source</text>
      <text x="610" y="195">diff_id 3&#8195;site-packages</text>
      <text x="610" y="221">diff_id 2&#8195;requirements.txt</text>
      <text x="610" y="247">diff_id 1&#8195;gcc, headers, apt lists</text>
      <text x="610" y="273">diff_id 0&#8195;base OS + python</text>
    </g>
    <text x="600" y="296" font-size="8" fill="currentColor" opacity="0.75">applied bottom-up, in diff_ids order. reorder</text>
    <text x="600" y="307" font-size="8" fill="currentColor" opacity="0.75">them and the filesystem changes — order is content.</text>
    <rect x="600" y="318" width="240" height="52" rx="8" fill="#0fa07f" fill-opacity="0.16" stroke="#0fa07f" stroke-width="1.6"/>
    <text x="612" y="336" font-size="9.5" font-weight="700" fill="#0fa07f">MEASURED at /</text>
    <text x="612" y="350" font-size="9" fill="currentColor">77 files, 260.23 MB merged</text>
    <text x="612" y="363" font-size="9" fill="currentColor">260.24 MB of blobs to ship it</text>
    <text x="600" y="386" font-size="8.5" fill="currentColor" opacity="0.85">8 instructions produced 6 layers:</text>
    <text x="600" y="398" font-size="8.5" fill="currentColor" opacity="0.85">ENV and CMD touch the config only, and</text>
    <text x="600" y="410" font-size="8.5" fill="currentColor" opacity="0.85">cost 0 B — they are not filesystem changes.</text>

    <g fill="none" stroke="currentColor" stroke-width="1.6" opacity="0.75">
      <path d="M272 124 L 294 124" marker-end="url(#l03-a1)"/>
      <path d="M272 190 C 284 190, 286 250, 294 262" marker-end="url(#l03-a1)"/>
      <path d="M552 320 L 574 250" marker-end="url(#l03-a1)"/>
    </g>

    <rect x="20" y="436" width="836" height="34" rx="8" fill="#7c5cff" fill-opacity="0.13" stroke="#7c5cff" stroke-width="1.8"/>
    <text x="34" y="450" font-size="9.5" font-weight="700" fill="#7c5cff">IMAGE DIGEST = sha256(manifest bytes)</text>
    <text x="34" y="464" font-size="9" fill="currentColor">sha256:280fe298a8fa1e1aa00e578cab3b7def0763afd7f8e4882dca07b9862cada667&#8195;— this is what @sha256: pins</text>

    <text x="440" y="490" font-size="11" text-anchor="middle" fill="currentColor" opacity="0.9">Every arrow is a sha256 digest, not a path. Change any layer's bytes and the manifest changes, so the image name changes.</text>
  </g>
</svg>
```

Three consequences fall straight out of that structure, and they are worth stating before anything else.

**Everything is addressed by content, not by name.** A layer's identity is the hash of its bytes. Two images built by two teams that happen to contain the identical base layer reference the identical digest, so the registry stores it once and you download it once. This is also why `FROM` is free in a rebuild: it does not build anything, it references a blob someone else already built, and nothing in your build configuration can change its digest. In the measured run, layer 0 is `e693baeb1edf` in every single build — the deps-first build, the source-first build, the deterministic build, the non-deterministic one, both stages of the multi-stage build. It never moves. (The hash function itself is the same SHA-256 built up in [Cryptographic Building Blocks](../../07-auth-and-security/02-cryptographic-building-blocks/); here it is being used as an *address*, not a signature.)

**Order is content.** `rootfs.diff_ids` is an ordered array, and the layers are applied bottom-up in exactly that order. Two images with the same set of layers in a different order are different images producing different filesystems, because a file in a later layer shadows the same path in an earlier one. There is no such thing as an unordered set of layers.

**Not every instruction makes a layer.** `ENV`, `CMD`, `WORKDIR`, `LABEL`, `EXPOSE` and friends change the *config blob* only. The measured build runs 8 instructions and produces 6 layers; the two config-only instructions contribute **0 B**. They still change the image digest, because the config's digest is in the manifest — which is the mechanism behind a fact that surprises people: you can produce a new image, with a new digest, that shares every single layer blob with the old one. Changing `CMD` costs one small JSON blob and zero layer bytes.

### The layer cache, and what invalidates it

A builder keys each instruction's result on **the chain of everything above it, the instruction text itself, and the content it consumes.** In the miniature builder that is three lines:

```python
chain = hashlib.sha256(("%s\n%s\n%s" % (chain, line, input_key)).encode()).hexdigest()
if chain in self.cache:
    ...                                  # HIT: reuse the layer, cost 0 s
```

`chain` folds in the parent, so it is a Merkle chain: any change anywhere above you changes your key too. That single property is the whole of layer caching, and it produces the rule that decides your build times:

> **A cache miss invalidates every instruction below it. Not the ones that depend on it — every one of them.**

The builder does not know that `RUN apt-get install build-essential` has nothing to do with `src/routes.py`. It cannot know. A `RUN` is an opaque shell command; the builder has no model of what it reads. All it knows is that the parent chain changed, so the precondition under which it recorded that result no longer holds, so the result is not reusable. This is conservative and it is correct — and it means **the position of an instruction in your Dockerfile is a performance decision, not a stylistic one.**

The classic error follows immediately. `COPY . /app` near the top puts your most volatile input — source code, edited many times a day — *underneath* your most expensive and most stable one, the dependency install. Every code change invalidates the dependency install. Here is the same one-line edit against both orderings:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 512" width="100%" style="max-width:840px" role="img" aria-label="Two Dockerfile orderings rebuilt after the identical one-line source edit. On the left, dependencies are installed before the source is copied: the base, the apt install, the requirements copy and the pip install are all cache hits, and only the source copy and the bytecode compile are rebuilt, for four hundred and ten kilobytes and three point two one seconds. On the right, the whole context is copied first: that copy misses, and because a miss invalidates every later instruction, the apt install, the pip install and the compile are all rebuilt in a cascade, for two hundred and fifteen megabytes and five hundred fifty one seconds. That is one hundred seventy one times slower and five hundred thirty seven times more bytes. The bottom note gives the honest reverse case: when the lockfile itself changes, the good ordering wins by only one point one six times.">
  <defs>
    <marker id="l03-a2" markerWidth="9" markerHeight="9" refX="5.5" refY="3" orient="auto"><path d="M0,0 L6.5,3 L0,6 Z" fill="#3553ff"/></marker>
    <marker id="l03-a2r" markerWidth="9" markerHeight="9" refX="5.5" refY="3" orient="auto"><path d="M0,0 L6.5,3 L0,6 Z" fill="#d64545"/></marker>
  </defs>
  <text x="440" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">One cache miss invalidates every layer below it. Order is a performance decision.</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">

    <rect x="16" y="44" width="414" height="356" rx="12" fill="#0fa07f" fill-opacity="0.08" stroke="#0fa07f" stroke-width="2"/>
    <rect x="450" y="44" width="414" height="356" rx="12" fill="#d64545" fill-opacity="0.08" stroke="#d64545" stroke-width="2"/>
    <text x="223" y="68" font-size="12.5" font-weight="700" text-anchor="middle" fill="#0fa07f">A · DEPS FIRST, SOURCE LAST</text>
    <text x="223" y="84" font-size="9" text-anchor="middle" fill="currentColor" opacity="0.85">stable things low, volatile things high</text>
    <text x="657" y="68" font-size="12.5" font-weight="700" text-anchor="middle" fill="#d64545">B · COPY . /app UP FRONT</text>
    <text x="657" y="84" font-size="9" text-anchor="middle" fill="currentColor" opacity="0.85">the ordering almost everyone writes first</text>

    <g stroke-width="1.7">
      <rect x="30" y="98" width="386" height="32" rx="6" fill="#0fa07f" fill-opacity="0.15" stroke="#0fa07f"/>
      <rect x="30" y="134" width="386" height="32" rx="6" fill="#0fa07f" fill-opacity="0.15" stroke="#0fa07f"/>
      <rect x="30" y="170" width="386" height="32" rx="6" fill="#0fa07f" fill-opacity="0.15" stroke="#0fa07f"/>
      <rect x="30" y="206" width="386" height="32" rx="6" fill="#0fa07f" fill-opacity="0.15" stroke="#0fa07f"/>
      <rect x="30" y="242" width="386" height="32" rx="6" fill="#e0930f" fill-opacity="0.17" stroke="#e0930f"/>
      <rect x="30" y="278" width="386" height="32" rx="6" fill="#e0930f" fill-opacity="0.17" stroke="#e0930f"/>
    </g>
    <g fill="currentColor" font-size="9.5">
      <text x="42" y="118">FROM python:3.12-slim</text><text x="404" y="118" text-anchor="end" font-weight="700" fill="#0fa07f">HIT</text>
      <text x="42" y="154">RUN apt-get install build-essential</text><text x="404" y="154" text-anchor="end" font-weight="700" fill="#0fa07f">HIT</text>
      <text x="42" y="190">COPY requirements.txt</text><text x="404" y="190" text-anchor="end" font-weight="700" fill="#0fa07f">HIT</text>
      <text x="42" y="220">RUN pip install -r requirements.txt</text><text x="404" y="220" text-anchor="end" font-weight="700" fill="#0fa07f">HIT</text>
      <text x="42" y="230" font-size="8" opacity="0.8">the 470 s step — untouched, because the lockfile did not move</text>
      <text x="42" y="258" font-weight="700">COPY src /app/src</text><text x="404" y="258" text-anchor="end" font-weight="700" fill="#e0930f">REBUILT</text>
      <text x="42" y="268" font-size="8" opacity="0.85" fill="#3553ff">your one-line edit lands here — 371.5 KB</text>
      <text x="42" y="294" font-weight="700">RUN python -m compileall /app/src</text><text x="404" y="294" text-anchor="end" font-weight="700" fill="#e0930f">REBUILT</text>
      <text x="42" y="304" font-size="8" opacity="0.85">the only thing downstream of the edit — 39.0 KB</text>
    </g>

    <g stroke-width="1.7">
      <rect x="464" y="98" width="386" height="32" rx="6" fill="#0fa07f" fill-opacity="0.15" stroke="#0fa07f"/>
      <rect x="464" y="134" width="386" height="32" rx="6" fill="#d64545" fill-opacity="0.18" stroke="#d64545"/>
      <rect x="464" y="170" width="386" height="32" rx="6" fill="#d64545" fill-opacity="0.12" stroke="#d64545"/>
      <rect x="464" y="206" width="386" height="32" rx="6" fill="#d64545" fill-opacity="0.12" stroke="#d64545"/>
      <rect x="464" y="242" width="386" height="32" rx="6" fill="#d64545" fill-opacity="0.12" stroke="#d64545"/>
    </g>
    <g fill="currentColor" font-size="9.5">
      <text x="476" y="118">FROM python:3.12-slim</text><text x="838" y="118" text-anchor="end" font-weight="700" fill="#0fa07f">HIT</text>
      <text x="476" y="148" font-weight="700">COPY . /app</text><text x="838" y="148" text-anchor="end" font-weight="700" fill="#d64545">MISS</text>
      <text x="476" y="160" font-size="8" opacity="0.85" fill="#3553ff">the identical one-line edit lands here</text>
      <text x="476" y="184" font-weight="700">RUN apt-get install build-essential</text><text x="838" y="184" text-anchor="end" font-weight="700" fill="#d64545">REBUILT</text>
      <text x="476" y="194" font-size="8" opacity="0.85">78 s of apt, for a change to a .py file — 153.24 MB</text>
      <text x="476" y="220" font-weight="700">RUN pip install -r /app/requirements.txt</text><text x="838" y="220" text-anchor="end" font-weight="700" fill="#d64545">REBUILT</text>
      <text x="476" y="230" font-size="8" opacity="0.85">470 s. the lockfile is byte-identical and it runs anyway — 61.52 MB</text>
      <text x="476" y="258" font-weight="700">RUN python -m compileall /app/src</text><text x="838" y="258" text-anchor="end" font-weight="700" fill="#d64545">REBUILT</text>
    </g>
    <path d="M458 152 C 452 176, 452 240, 458 262" fill="none" stroke="#d64545" stroke-width="1.8" marker-end="url(#l03-a2r)"/>
    <text x="476" y="292" font-size="9" font-weight="700" fill="#d64545">CASCADE: one MISS invalidated the three instructions below it,</text>
    <text x="476" y="305" font-size="9" fill="currentColor" opacity="0.9">none of which read the file that changed. 78 s + 470 s of rework.</text>

    <rect x="30" y="318" width="386" height="70" rx="8" fill="#0fa07f" fill-opacity="0.14" stroke="#0fa07f" stroke-width="1.8"/>
    <rect x="464" y="318" width="386" height="70" rx="8" fill="#d64545" fill-opacity="0.14" stroke="#d64545" stroke-width="1.8"/>
    <g fill="currentColor">
      <text x="42" y="336" font-size="9.5" font-weight="700" fill="#0fa07f">MEASURED — rebuild after the edit</text>
      <text x="42" y="354" font-size="10">6 layers</text><text x="150" y="354" font-size="10">4 HIT</text><text x="240" y="354" font-size="10">2 rebuilt</text>
      <text x="42" y="372" font-size="10">bytes rebuilt</text><text x="240" y="372" font-size="10" font-weight="700" fill="#0fa07f">410.4 KB</text>
      <text x="42" y="384" font-size="10">wall time</text><text x="240" y="384" font-size="10" font-weight="700" fill="#0fa07f">3.21 s</text>

      <text x="476" y="336" font-size="9.5" font-weight="700" fill="#d64545">MEASURED — rebuild after the edit</text>
      <text x="476" y="354" font-size="10">5 layers</text><text x="584" y="354" font-size="10">1 HIT</text><text x="674" y="354" font-size="10">4 rebuilt</text>
      <text x="476" y="372" font-size="10">bytes rebuilt</text><text x="674" y="372" font-size="10" font-weight="700" fill="#d64545">215.16 MB</text>
      <text x="476" y="384" font-size="10">wall time</text><text x="674" y="384" font-size="10" font-weight="700" fill="#d64545">551.21 s</text>
    </g>

    <rect x="16" y="410" width="848" height="62" rx="9" fill="#3553ff" fill-opacity="0.09" stroke="#3553ff" stroke-width="1.8"/>
    <text x="440" y="430" font-size="11.5" font-weight="700" text-anchor="middle" fill="#3553ff">3.21 s vs 551.21 s = 171.6x&#8195;&#8195;410.4 KB vs 215.16 MB = 537x</text>
    <text x="440" y="446" font-size="9" text-anchor="middle" fill="currentColor" opacity="0.9">Same base, same lockfile, same source, same .dockerignore. Two lines moved. A cold build is a tie: 551.22 s vs 551.21 s.</text>
    <text x="440" y="462" font-size="9" text-anchor="middle" fill="currentColor" opacity="0.9">THE HONEST REVERSE: bump the lockfile instead and A must rerun pip too — 473.22 s vs 551.21 s, a lead of just 1.16x.</text>

    <text x="440" y="500" font-size="11" text-anchor="middle" fill="currentColor" opacity="0.9">Order cheapest-and-most-stable first. The win is only as large as the share of builds that touch code and not dependencies.</text>
  </g>
</svg>
```

Read the bottom band twice, because both halves matter and only the first one usually gets taught.

**The win is enormous and it is free.** 171.6x on time, 537x on bytes, from moving two lines. Note also that the cold build is a *tie* — 551.22 s against 551.21 s, with the good ordering **0.010 s slower** because it writes one extra layer. Ordering costs you nothing to adopt and pays only on rebuilds, which is every build after the first.

**And the win is a bet, not a law.** If the thing you changed is the *lockfile*, no ordering helps: the expensive step consumes the file that moved, so it reruns either way. Measured, the good ordering's advantage collapses from **171.6x to 1.16x** — 473.22 s against 551.21 s, and the only remaining difference is that the source copy sits below the install. Weighted over 100 builds a week:

| dependency-change share | A total | B total | A wins by |
|---|---|---|---|
| 0% | 5.4 min | 918.7 min | 171.6x |
| 5% | 44.5 min | 918.7 min | 20.6x |
| 25% | 201.2 min | 918.7 min | 4.6x |
| 100% | 788.7 min | 918.7 min | 1.2x |

At a realistic 5% the good ordering saves **14.6 hours of CI time per week** (CI = continuous integration, the automation that builds every commit). At 100% it saves 2.2 hours — and if you have a bot that bumps your lockfile on every build, **100% is the number you actually get**, which is the case where ordering has run out of road and you need a cache mount instead. Knowing which regime you are in is the difference between a fix and a ritual.

One more input feeds this and is invisible until it bites: the **build context**. `COPY . /app` copies whatever the build context contains, and the context is whatever you did not exclude. Measured on the identical instruction: **371.8 KB with a `.dockerignore`, 80.00 MB without — 220x bigger**, because the context dragged in `.git`, `.venv`, `__pycache__` and `.env`. The size is the boring half. The `.env` file is the other half: it is now in a layer, and the layer is in the image, and the image goes to a registry.

### Reproducibility: same input, same digest

A build is **reproducible** if the same inputs always produce the same output bytes — and therefore the same digest. This is not an aesthetic goal. It is what makes the other two properties possible: without it you cannot tell whether an image matches the source it claims to be built from, and you cannot verify anyone's signature over it (which is lesson 4's subject).

The default is not reproducible, and the reasons are unglamorous:

- **Timestamps.** Every file written into a layer carries an mtime, and the default mtime is *now*. Two builds a second apart produce different bytes for identical files. The convention for fixing this is **`SOURCE_DATE_EPOCH`** — an environment variable holding a Unix timestamp, honoured by a growing number of build tools, that says "pretend the build happened then." Use your source's commit timestamp and the value becomes a function of your source.
- **Entry order.** A tar stream is ordered. If the build walks a directory with `readdir()` and does not sort, the order is whatever the filesystem returns, which can differ between machines and even between runs. Same files, different stream, different digest.
- **Unpinned dependencies.** `pip install flask` resolves against an index whose "latest" moves under you. Your source did not change; the world did.
- **Network fetches of moving targets.** `curl https://example.com/install.sh | sh`, `apt-get install` without a pinned snapshot, `FROM python:3.12-slim` where the tag is reassigned. A tag is a mutable pointer.
- **Locale, uid/gid and umask.** Sort order depends on locale; file ownership and modes are recorded in the tar header; a build running as uid 1000 writes different headers than one running as uid 0.

The measured experiment isolates each cause by building the identical Dockerfile against the identical source twice, with a fresh cache each time:

| variant | build 1 | build 2 | layers that differ |
|---|---|---|---|
| as people write it | `08f31dbf00b6` | `e2e5430c0565` | 1, 2, 3, 4, 5 |
| mtimes only | `da06025628fb` | `245595deec1d` | 1, 2, 3, 4, 5 |
| entry order only | `ea1ca6bd05d8` | `8050749021b2` | 1, 3, 4, 5 |
| unpinned deps only | `ec90b5e6f3d7` | `c6882e1f8e8f` | **3** |
| all three normalised | `280fe298a8fa` | `280fe298a8fa` | **none** |

Two things in that table are worth sitting with. **The blast radii are completely different.** Timestamps and entry order poison *every layer the build produces* — they are properties of how bytes are written, so they touch everything. An unpinned version poisons exactly one layer, the dependency install. But that layer is the one everything downstream is stacked on, so a single unpinned transitive dependency changes the image digest just as thoroughly as a wall clock does. And **layer 0 never differs in any row**, because `FROM` pulls something someone else already built.

Then the deepest interaction in this lesson, and it is the reason non-determinism survives so long undetected:

> **A `RUN` instruction's cache key is the command string, not its result.** `RUN pip install flask` is a cache *hit* on a machine that has seen that string before — and it will happily install a different Flask on a machine that has not.

Caching and non-determinism hide each other. On your laptop the layer is cached, so the drift never happens. On a fresh CI runner the layer is cold, so it does. That is the precise shape of "works on my machine, red in CI, and green again when I retry," and no amount of staring at the diff will explain it, because the difference is not in the diff.

### Size: you cannot delete bytes out of an image

Lesson 2 established the mechanism: overlay deletes are **whiteouts**, markers in an upper layer that hide a name from the merged view. The lower layer is read-only and untouched. The build-time consequence is the one that costs money:

> **Deleting a file in a later layer does not make the image smaller. The bytes stay in the layer below, and you still download them.**

`RUN rm -rf /root/.cache/pip` after a `RUN pip install` frees nothing. It adds a layer containing whiteout markers. The measured single-stage build deletes the deploy key, the pip cache and the apt lists in one step, and the numbers are exactly as unhelpful as the mechanism predicts: the merged filesystem drops from **73 files and 271.91 MB to 70 files and 241.54 MB — 30.38 MB gone** — while the image total goes from **271.92 MB to 271.92 MB, up by 64 bytes.** The `rm` layer is three whiteout markers and zero reclaimed bytes.

And the security version of the same fact:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 528" width="100%" style="max-width:840px" role="img" aria-label="A single-stage build compared with a multi-stage one. On the left, eight layers totalling two hundred seventy one megabytes, including a layer holding a deploy key and a final remove step. That remove step deleted thirty point three eight megabytes of files from the merged filesystem but the image grew by sixty four bytes, because the removal is only three whiteout markers and the bytes stay in the layers below. On the right, a builder stage of six layers and two hundred sixty two megabytes is discarded entirely, and the final stage copies only the virtual environment and the wheel from it, giving three layers and one hundred eight point nine four megabytes, two and a half times smaller. The red band at the bottom shows the deploy key was recovered verbatim from layer two of the single-stage image even though it is absent from the merged filesystem.">
  <defs>
    <marker id="l03-a3" markerWidth="10" markerHeight="10" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#0fa07f"/></marker>
  </defs>
  <text x="440" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">You cannot delete bytes out of an image. You can only decline to put them in.</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">

    <rect x="16" y="44" width="414" height="362" rx="12" fill="#d64545" fill-opacity="0.07" stroke="#d64545" stroke-width="2"/>
    <rect x="450" y="44" width="414" height="362" rx="12" fill="#0fa07f" fill-opacity="0.08" stroke="#0fa07f" stroke-width="2"/>
    <text x="223" y="66" font-size="12.5" font-weight="700" text-anchor="middle" fill="#d64545">SINGLE STAGE + rm -rf at the end</text>
    <text x="657" y="66" font-size="12.5" font-weight="700" text-anchor="middle" fill="#0fa07f">MULTI-STAGE — build here, ship there</text>

    <text x="28" y="84" font-size="8.5" font-weight="700" fill="currentColor" opacity="0.7">ONE STAGE&#8195;— 271.92 MB, 8 layers, ALL SHIPPED</text>
    <g stroke-width="1.4">
      <rect x="28" y="90" width="390" height="21" rx="4" fill="#7c5cff" fill-opacity="0.13" stroke="#7c5cff"/>
      <rect x="28" y="113" width="390" height="21" rx="4" fill="#e0930f" fill-opacity="0.16" stroke="#e0930f"/>
      <rect x="28" y="136" width="390" height="21" rx="4" fill="#d64545" fill-opacity="0.20" stroke="#d64545"/>
      <rect x="28" y="159" width="390" height="21" rx="4" fill="#7c5cff" fill-opacity="0.13" stroke="#7c5cff"/>
      <rect x="28" y="182" width="390" height="21" rx="4" fill="#e0930f" fill-opacity="0.16" stroke="#e0930f"/>
      <rect x="28" y="205" width="390" height="21" rx="4" fill="#7c5cff" fill-opacity="0.13" stroke="#7c5cff"/>
      <rect x="28" y="228" width="390" height="21" rx="4" fill="#7c5cff" fill-opacity="0.13" stroke="#7c5cff"/>
      <rect x="28" y="251" width="390" height="21" rx="4" fill="#e0930f" fill-opacity="0.20" stroke="#e0930f"/>
    </g>
    <g fill="currentColor" font-size="8">
      <text x="36" y="104" opacity="0.7">e693baeb1edf</text><text x="164" y="104" text-anchor="end" font-size="8.5" font-weight="700">45.08 MB</text><text x="174" y="104" font-size="8.5">FROM python:3.12-slim</text>
      <text x="36" y="127" opacity="0.7">b7ea1f01be65</text><text x="164" y="127" text-anchor="end" font-size="8.5" font-weight="700" fill="#e0930f">153.24 MB</text><text x="174" y="127" font-size="8.5">RUN apt-get install build-essential</text>
      <text x="36" y="150" opacity="0.7">9d74698ed8d1</text><text x="164" y="150" text-anchor="end" font-size="8.5" font-weight="700" fill="#d64545">118 B</text><text x="174" y="150" font-size="8.5" font-weight="700" fill="#d64545">COPY deploy_key /tmp/deploy_key</text>
      <text x="36" y="173" opacity="0.7">2cccdc79f27c</text><text x="164" y="173" text-anchor="end" font-size="8.5" font-weight="700">378 B</text><text x="174" y="173" font-size="8.5">COPY requirements.txt</text>
      <text x="36" y="196" opacity="0.7">8b518ce679c7</text><text x="164" y="196" text-anchor="end" font-size="8.5" font-weight="700" fill="#e0930f">70.89 MB</text><text x="174" y="196" font-size="8.5">RUN pip install (no --no-cache-dir)</text>
      <text x="36" y="219" opacity="0.7">7b0253e55205</text><text x="164" y="219" text-anchor="end" font-size="8.5" font-weight="700">371.5 KB</text><text x="174" y="219" font-size="8.5">COPY src /app/src</text>
      <text x="36" y="242" opacity="0.7">ee47b26affaa</text><text x="164" y="242" text-anchor="end" font-size="8.5" font-weight="700">2.34 MB</text><text x="174" y="242" font-size="8.5">RUN python -m build --wheel</text>
      <text x="36" y="265" opacity="0.7">c1f71ce35f44</text><text x="164" y="265" text-anchor="end" font-size="8.5" font-weight="700" fill="#e0930f">64 B</text><text x="174" y="265" font-size="8.5" font-weight="700">RUN rm -rf deploy_key, pip cache, apt lists</text>
    </g>

    <rect x="28" y="284" width="390" height="110" rx="8" fill="#d64545" fill-opacity="0.12" stroke="#d64545" stroke-width="1.8"/>
    <text x="38" y="302" font-size="9.5" font-weight="700" fill="#d64545">MEASURED on both sides of that rm -rf</text>
    <g fill="currentColor" font-size="9">
      <text x="38" y="322">merged filesystem BEFORE</text><text x="300" y="322" text-anchor="end">73 files</text><text x="408" y="322" text-anchor="end">271.91 MB</text>
      <text x="38" y="338">merged filesystem AFTER</text><text x="300" y="338" text-anchor="end">70 files</text><text x="408" y="338" text-anchor="end" font-weight="700" fill="#0fa07f">241.54 MB</text>
      <text x="38" y="354">image total BEFORE</text><text x="408" y="354" text-anchor="end">271.92 MB</text>
      <text x="38" y="370">image total AFTER</text><text x="408" y="370" text-anchor="end" font-weight="700" fill="#d64545">271.92 MB</text>
    </g>
    <text x="38" y="388" font-size="9" font-weight="700" fill="#d64545">-30.38 MB of files, +64 B of image. 3 whiteouts, 0 bytes freed.</text>

    <text x="462" y="84" font-size="8.5" font-weight="700" fill="currentColor" opacity="0.7">STAGE 1&#8195;builder&#8195;— 262.54 MB, 6 layers, THROWN AWAY</text>
    <g stroke-width="1.4">
      <rect x="462" y="90" width="390" height="19" rx="4" fill="#7f7f7f" fill-opacity="0.10" stroke="currentColor" stroke-opacity="0.4" stroke-dasharray="4 3"/>
      <rect x="462" y="111" width="390" height="19" rx="4" fill="#7f7f7f" fill-opacity="0.10" stroke="currentColor" stroke-opacity="0.4" stroke-dasharray="4 3"/>
      <rect x="462" y="132" width="390" height="19" rx="4" fill="#7f7f7f" fill-opacity="0.10" stroke="currentColor" stroke-opacity="0.4" stroke-dasharray="4 3"/>
      <rect x="462" y="153" width="390" height="19" rx="4" fill="#7c5cff" fill-opacity="0.16" stroke="#7c5cff"/>
      <rect x="462" y="174" width="390" height="19" rx="4" fill="#7f7f7f" fill-opacity="0.10" stroke="currentColor" stroke-opacity="0.4" stroke-dasharray="4 3"/>
      <rect x="462" y="195" width="390" height="19" rx="4" fill="#7c5cff" fill-opacity="0.16" stroke="#7c5cff"/>
    </g>
    <g fill="currentColor" font-size="8">
      <text x="470" y="103" opacity="0.7">e693baeb1edf</text><text x="600" y="103" text-anchor="end" font-size="8.5">45.08 MB</text><text x="610" y="103" font-size="8.5" opacity="0.8">FROM python:3.12-slim AS builder</text>
      <text x="470" y="124" opacity="0.7">b7ea1f01be65</text><text x="600" y="124" text-anchor="end" font-size="8.5">153.24 MB</text><text x="610" y="124" font-size="8.5" opacity="0.8">RUN apt-get install build-essential</text>
      <text x="470" y="145" opacity="0.7">2cccdc79f27c</text><text x="600" y="145" text-anchor="end" font-size="8.5">378 B</text><text x="610" y="145" font-size="8.5" opacity="0.8">COPY requirements.txt</text>
      <text x="470" y="166" opacity="0.75">260ee0cf82a6</text><text x="600" y="166" text-anchor="end" font-size="8.5" font-weight="700">61.52 MB</text><text x="610" y="166" font-size="8.5" font-weight="700">RUN venv /opt/venv &amp;&amp; pip install</text>
      <text x="470" y="187" opacity="0.7">7b0253e55205</text><text x="600" y="187" text-anchor="end" font-size="8.5">371.5 KB</text><text x="610" y="187" font-size="8.5" opacity="0.8">COPY src /app/src</text>
      <text x="470" y="208" opacity="0.75">ee47b26affaa</text><text x="600" y="208" text-anchor="end" font-size="8.5" font-weight="700">2.34 MB</text><text x="610" y="208" font-size="8.5" font-weight="700">RUN python -m build --wheel</text>
    </g>

    <path d="M472 220 L 472 238" fill="none" stroke="#0fa07f" stroke-width="1.8" marker-end="url(#l03-a3)"/>
    <text x="488" y="232" font-size="8.5" font-weight="700" fill="#0fa07f">only what a COPY --from names survives — and it keeps its digest</text>

    <text x="462" y="254" font-size="8.5" font-weight="700" fill="#0fa07f">STAGE 2&#8195;final&#8195;— this is the image you push</text>
    <g stroke-width="1.6">
      <rect x="462" y="258" width="390" height="22" rx="4" fill="#7c5cff" fill-opacity="0.16" stroke="#7c5cff"/>
      <rect x="462" y="282" width="390" height="22" rx="4" fill="#7c5cff" fill-opacity="0.16" stroke="#7c5cff"/>
      <rect x="462" y="306" width="390" height="22" rx="4" fill="#7c5cff" fill-opacity="0.16" stroke="#7c5cff"/>
    </g>
    <g fill="currentColor" font-size="8">
      <text x="470" y="273" opacity="0.75">e693baeb1edf</text><text x="600" y="273" text-anchor="end" font-size="8.5" font-weight="700">45.08 MB</text><text x="610" y="273" font-size="8.5">FROM python:3.12-slim</text>
      <text x="470" y="297" opacity="0.75">260ee0cf82a6</text><text x="600" y="297" text-anchor="end" font-size="8.5" font-weight="700">61.52 MB</text><text x="610" y="297" font-size="8.5">COPY --from=builder /opt/venv</text>
      <text x="470" y="321" opacity="0.75">ee47b26affaa</text><text x="600" y="321" text-anchor="end" font-size="8.5" font-weight="700">2.34 MB</text><text x="610" y="321" font-size="8.5">COPY --from=builder /app/dist</text>
    </g>

    <rect x="462" y="336" width="390" height="58" rx="8" fill="#0fa07f" fill-opacity="0.15" stroke="#0fa07f" stroke-width="1.8"/>
    <text x="472" y="354" font-size="9.5" font-weight="700" fill="#0fa07f">271.92 MB -&gt; 108.94 MB&#8195;=&#8195;2.50x smaller, 162.98 MB saved</text>
    <text x="472" y="370" font-size="8.5" fill="currentColor">the 153.24 MB toolchain and the 9.38 MB pip cache are never</text>
    <text x="472" y="384" font-size="8.5" fill="currentColor">present to be deleted. final filesystem: 51 files, 108.93 MB.</text>

    <rect x="16" y="416" width="848" height="66" rx="9" fill="#d64545" fill-opacity="0.12" stroke="#d64545" stroke-width="2"/>
    <text x="30" y="435" font-size="10.5" font-weight="700" fill="#d64545">THE SAME MECHANISM, AS A BREACH</text>
    <text x="30" y="452" font-size="9" fill="currentColor">/tmp/deploy_key in the merged filesystem after the rm:&#8195;<tspan font-weight="700" fill="#0fa07f">absent</tspan>&#8195;&#8195;in layer 2 (9d74698ed8d1), 84 bytes:&#8195;<tspan font-weight="700" fill="#d64545">still there</tspan></text>
    <text x="30" y="468" font-size="9" fill="currentColor">recovered verbatim from the layer blob by anyone who can pull the image:&#8195;<tspan font-weight="700" fill="#d64545">'AAAAdeploy-key-do-not-ship-9f31c0'</tspan></text>

    <text x="440" y="508" font-size="11" text-anchor="middle" fill="currentColor" opacity="0.9">A later layer can hide a file. It can never unwrite one. Rotate the key — the image is the disclosure.</text>
  </g>
</svg>
```

**A secret copied into a layer is in that layer forever.** The measured build proves both halves at once: `/tmp/deploy_key` is **absent from the merged filesystem** — so a shell inside the running container cannot find it, and a scanner that inspects the running container reports nothing — and it is **still in layer 2 (`9d74698ed8d1`), 84 bytes**, from which the script reads it straight back out: `'AAAAdeploy-key-do-not-ship-9f31c0'`. Anyone who can pull the image can do the same with `tar`. There is no fix after the fact; there is only rotation, because **publishing the image was the disclosure.** ([Secrets Management & Rotation](../../07-auth-and-security/13-secrets-management-and-rotation/) covers the rotation side.)

The real fix for both problems is the same, and it is structural rather than cosmetic. A **multi-stage build** runs your compiler, headers, caches and secrets in a stage that is **thrown away**, and the final stage starts from a fresh base and copies in only the artifacts you name. Measured: a builder stage of **262.54 MB across 6 layers is discarded entirely**, and the final image is **108.94 MB in 3 layers against the single-stage 271.92 MB in 8 — 2.50x smaller, 162.98 MB saved.** The 153.24 MB toolchain layer and the 9.38 MB pip cache are never present to be deleted in the first place.

There is a lovely detail in the measured output that explains why stage boundaries are cheap: **the venv layer keeps its digest across the `COPY --from`** — `260ee0cf82a6` in the builder, `260ee0cf82a6` in the final image. Same bytes, same address. Content addressing means moving an artifact between stages is a reference, not a copy.

Smaller bases push the same idea further. `python:3.12-slim` instead of `python:3.12` drops the compilers and docs. **Distroless** images go further still — the language runtime and its libraries, with no shell, no package manager, no `ls`. The attack surface shrinks to almost nothing, and so does the CVE (Common Vulnerabilities and Exposures) count your scanner reports, because most of what a scanner finds is in packages your application never calls. The cost is real and you should know it before you adopt it: **there is no shell, so `docker exec -it … sh` does not work.** Debugging means ephemeral debug containers, a sidecar, or rebuilding with a `:debug` tag. Choose it deliberately, not because it scored well on a comparison table.

## Build It

[`code/image_builder.py`](code/image_builder.py) is a miniature OCI-style image builder: it parses a tiny Dockerfile dialect, executes each instruction against an in-memory layer model, content-addresses every layer with `hashlib.sha256`, and keeps a layer cache keyed the way a real one is. Standard library only, deterministic, **3.5 seconds** end to end.

Be clear about what is real and what is modelled, because the distinction is the difference between a measurement and a story. **Every digest and every byte count below is real SHA-256 work over real bytes** — the file *contents* are synthetic (generated deterministically with `shake_128`, sized to match the order of magnitude of a real Python service image), but the hashing, the layering, the merge, the cache keying and the totals are all genuine. **The per-step wall-clock seconds are a modelled cost table** (`STEP_SECONDS`: 78 s for the apt install, 470 s for pip, and so on), because this sandbox cannot run `apt-get`. Ratios of time therefore inherit that model; ratios of *bytes* do not.

A layer is an ordered set of entries plus whiteouts, and its digest is the hash of the stream it serialises to. This is the entire content-addressing story in fifteen lines:

```python
class Layer:
    def __init__(self, entries, whiteouts=()):
        self.entries = tuple(entries)
        self.whiteouts = tuple(whiteouts)
        h = hashlib.sha256()
        size = 0
        for e in self.entries:
            hdr = ("%s\x00%o\x00%d\x00%d\x00" % (e.path, e.mode, len(e.data), e.mtime)).encode()
            h.update(hdr)                    # path, mode, length, MTIME
            h.update(e.data)
            size += len(hdr) + len(e.data)
        for w in self.whiteouts:             # OCI: .wh.<name> marks a deletion
            hdr = (".wh.%s\x00" % w).encode()
            h.update(hdr)
            size += len(hdr)
        self.digest = "sha256:" + h.hexdigest()
        self.size = size
```

Notice `e.mtime` inside the hash. That one field is the entire timestamp half of non-determinism, and the whole fix is one branch:

```python
def _mtime(self) -> int:
    if self.flags.fixed_mtime:
        return SOURCE_DATE_EPOCH          # the Reproducible Builds convention
    self.clock += 1                       # a real build stamps the wall clock
    return self.clock

def _layer(self, pairs, whiteouts=()):
    items = list(pairs)
    if self.flags.sorted_entries:
        items.sort(key=lambda p: p[0])
    else:
        self.rng.shuffle(items)           # stand-in for readdir() order
    return Layer([Entry(p, d, self._mtime()) for p, d in items], sorted(whiteouts))
```

And the cache key, which is the heart of the whole lesson. `input_key` is computed only for `COPY` — the builder hashes the paths and contents it is about to copy, because that is the one instruction whose inputs it can actually see. A `RUN` contributes only its command string:

```python
chain = hashlib.sha256(("%s\n%s\n%s" % (chain, line, input_key)).encode()).hexdigest()
if chain in self.cache:
    lyr, secs, delta = self.cache[chain]
    steps.append(Step(line, True, 0.0, lyr))       # HIT: zero seconds
    ...
    continue
```

Because `chain` folds in its own previous value, this is a Merkle chain and the cascade is automatic: nothing special implements "invalidate everything below," it is a consequence of hashing the parent. Run it:

```bash
docker compose exec -T app python \
  phases/10-infrastructure-and-deployment/03-images-layers-and-builds/code/image_builder.py
```

```console
miniature OCI image builder -- stdlib only, seeded, in-memory
file contents are synthetic; every digest and byte count is real sha256 work.
per-step SECONDS are a modelled cost table, not a measurement.

== 1 · AN IMAGE IS A MANIFEST, A CONFIG AND A LIST OF TARBALLS ==
  manifest (OCI image-spec v1.1, application/vnd.oci.image.manifest.v1+json):
    config   sha256:b42926188bc1ff73991...  1.3 KB
    layer 0  sha256:e693baeb1edfcea2e9c...    45.08 MB
    layer 1  sha256:b7ea1f01be65d546488...   153.24 MB
    layer 2  sha256:2cccdc79f27c77948d1...       378 B
    layer 3  sha256:385710d90ae08442337...    61.52 MB
    layer 4  sha256:7b0253e552052b6ad10...    371.5 KB
    layer 5  sha256:0497a31ba360e474ff9...     39.0 KB
  image digest (what `@sha256:` pins, and what lesson 4 pushes to a registry):
    sha256:280fe298a8fa1e1aa00e578cab3b7def0763afd7f8e4882dca07b9862cada667

  config blob -> the recipe half. No file bytes live here:
    Env         ['PATH=/usr/local/bin:/usr/bin:/bin', 'PORT=8080', 'PYTHON_VERSION=3.12.7']
    Cmd         ['python', '/app/src/main.py']
    rootfs.diff_ids  (ordered, and the order is load-bearing)
      0  sha256:e693baeb1edfcea2e9c9425ad8...
      1  sha256:b7ea1f01be65d546488a0755bd...
      2  sha256:2cccdc79f27c77948d1492f034...
      3  sha256:385710d90ae084423374848a44...
      4  sha256:7b0253e552052b6ad10fef3ceb...
      5  sha256:0497a31ba360e474ff9fe87c94...

  the build, step by step (this is `docker history`, bottom-up):
    #    LAYER                SIZE  CREATED BY
    0    e693baeb1edf     45.08 MB  FROM python:3.12-slim
    1    b7ea1f01be65    153.24 MB  RUN apt-get update && apt-get install -y --no-instal
    2    2cccdc79f27c        378 B  COPY requirements.txt /app/requirements.txt
    3    385710d90ae0     61.52 MB  RUN pip install --no-cache-dir -r /app/requirements.
    4    7b0253e55205     371.5 KB  COPY src /app/src
    5    0497a31ba360      39.0 KB  RUN python -m compileall -q /app/src
    -    <no layer>            0 B  ENV PORT=8080
    -    <no layer>            0 B  CMD ["python", "/app/src/main.py"]

  merged filesystem: 77 files, 260.23 MB
  image total (sum of layer blobs): 260.24 MB across 6 layers
  6 filesystem layers, 8 instructions: ENV and CMD change the config only.

== 2 · INSTRUCTION ORDER IS A PERFORMANCE DECISION (THE CACHE CASCADE) ==
  Same application, same base, same lockfile. The only difference is WHERE
  the source is copied relative to the dependency install.
  Both builds use the same .dockerignore, so the contexts are byte-identical.

  a) COLD BUILD (empty cache)
    ordering            layers    hit  rebuilt  bytes rebuilt      sim time
    A deps-first             6      0        6      260.24 MB      551.22 s
    B source-first           5      0        5      260.24 MB      551.21 s
    identical work; A is 0.010 s slower -- it writes one extra layer.

  b) ONE-LINE EDIT to src/routes.py, rebuild both
    ordering            layers    hit  rebuilt  bytes rebuilt      sim time
    A deps-first             6      4        2       410.4 KB        3.21 s
    B source-first           5      1        4      215.16 MB      551.21 s
    A rebuilt: COPY src, RUN python
    B rebuilt: COPY ., RUN apt-get, RUN pip, RUN python
    -> 3.2 s vs 551.2 s  =  171.6x.  bytes rebuilt 410.4 KB vs 215.16 MB  =  537x.
    B's COPY . missed, and EVERY later layer was invalidated with it.

  c) ONE-LINE LOCKFILE BUMP (sqlalchemy 2.0.43 -> 2.0.44), rebuild both
    ordering            layers    hit  rebuilt  bytes rebuilt      sim time
    A deps-first             6      2        4       61.92 MB      473.22 s
    B source-first           5      1        4      215.16 MB      551.21 s
    A rebuilt: COPY requirements.txt, RUN pip, COPY src, RUN python
    -> 473.2 s vs 551.2 s = 1.16x. A's advantage collapsed from 171.6x to 1.16x:
    no ordering can save you when the thing you changed feeds the expensive step.

  d) THE HONEST TRADE: it is a bet on how often you touch the lockfile.
    100 builds/week, varying the share that are dependency changes:
    dep-change %          A total        B total A wins by
    0%                     5.4 min       918.7 min   171.6x
    5%                    44.5 min       918.7 min    20.6x
    10%                   83.7 min       918.7 min    11.0x
    25%                  201.2 min       918.7 min     4.6x
    50%                  397.0 min       918.7 min     2.3x
    100%                 788.7 min       918.7 min     1.2x
    At 5%  the good ordering saves 14.6 hours of CI time per week.
    At 100% it saves 2.2 hours -- and if a bot bumps your lockfile on every
    build, that is the number you actually get. Reach for a cache mount instead.

  e) AND THE .dockerignore, measured on the same COPY . instruction:
    with .dockerignore     COPY . layer =   371.8 KB
    without .dockerignore  COPY . layer =   80.00 MB   (.git, .venv, __pycache__, .env)
    220x bigger, and .env went into a layer that anyone who pulls the image can read.

== 3 · SAME SOURCE, DIFFERENT IMAGE: NON-DETERMINISM, THEN A FIXED DIGEST ==
  Two builds of the identical Dockerfile and the identical source tree.
  Each run gets a fresh cache, so every layer is genuinely re-executed.

    variant                build 1        build 2        layers that differ cause
    as people write it     08f31dbf00b6   e2e5430c0565   layers 1,2,3,4,5   wall-clock mtimes + readdir order + unpinned versions
    mtimes only            da06025628fb   245595deec1d   layers 1,2,3,4,5   the build stamps time.time() into every file header
    entry order only       ea1ca6bd05d8   8050749021b2   layers 1,3,4,5     readdir() order differs; the tar stream differs
    unpinned deps only     ec90b5e6f3d7   c6882e1f8e8f   layers 3           3 of 20 requirements have no ==pin
        the index moved under us: flask -> 3.1.4, sqlalchemy -> 2.0.45, pydantic-core -> 2.33.4
    all three normalised   280fe298a8fa   280fe298a8fa   IDENTICAL          SOURCE_DATE_EPOCH + sorted entries + a full lockfile

  the two normalised builds, in full:
    build 1  sha256:280fe298a8fa1e1aa00e578cab3b7def0763afd7f8e4882dca07b9862cada667
    build 2  sha256:280fe298a8fa1e1aa00e578cab3b7def0763afd7f8e4882dca07b9862cada667
    equal:   True

  layer 0 never moves: FROM pulls a blob someone else already built.
  mtimes and entry order poison EVERY layer this build produces; an unpinned
  version poisons only the dependency layer -- but that is the layer everything
  downstream is stacked on. And a RUN's cache key is the COMMAND STRING, not
  its result, so `pip install flask` is a cache HIT that can install a different
  flask on a different machine. Non-determinism and caching hide each other.

== 4 · SIZE: THE DELETION TRAP AND THE MULTI-STAGE FIX ==
  single-stage build, layer by layer:
    #    LAYER                SIZE  CREATED BY
    0    e693baeb1edf     45.08 MB  FROM python:3.12-slim
    1    b7ea1f01be65    153.24 MB  RUN apt-get update && apt-get install -y --no-install-re
    2    9d74698ed8d1        118 B  COPY deploy_key /tmp/deploy_key
    3    2cccdc79f27c        378 B  COPY requirements.txt /app/requirements.txt
    4    8b518ce679c7     70.89 MB  RUN pip install -r /app/requirements.txt
    5    7b0253e55205     371.5 KB  COPY src /app/src
    6    ee47b26affaa      2.34 MB  RUN python -m build --wheel -o /app/dist
    7    c1f71ce35f44         64 B  RUN rm -rf /tmp/deploy_key /root/.cache/pip /var/lib/apt

  the `rm -rf` step, measured on both sides of the mount:
    merged filesystem BEFORE rm       73 files    271.91 MB
    merged filesystem AFTER  rm       70 files    241.54 MB   (-30.38 MB)
    image total BEFORE rm                         271.92 MB
    image total AFTER  rm                         271.92 MB   (+64 B)
    deleting 30.38 MB of files made the image 64 B BIGGER.
    the rm layer is 3 whiteout markers and zero reclaimed bytes.

  and the part that ends careers -- the secret is still in the blob:
    /tmp/deploy_key in the merged filesystem: False
    /tmp/deploy_key in layer 2 (9d74698ed8d1), 84 bytes, readable by anyone
    recovered from the layer blob: 'AAAAdeploy-key-do-not-ship-9f31c0'

  the multi-stage fix -- the toolchain never enters the final stage:
    STAGE     LAYER                SIZE  CREATED BY
    builder 0 e693baeb1edf     45.08 MB  FROM python:3.12-slim AS builder
    builder 1 b7ea1f01be65    153.24 MB  RUN apt-get update && apt-get install -y --no-instal
    builder 2 2cccdc79f27c        378 B  COPY requirements.txt /app/requirements.txt
    builder 3 260ee0cf82a6     61.52 MB  RUN python -m venv /opt/venv && /opt/venv/bin/pip in
    builder 4 7b0253e55205     371.5 KB  COPY src /app/src
    builder 5 ee47b26affaa      2.34 MB  RUN python -m build --wheel -o /app/dist
    FINAL 0   e693baeb1edf     45.08 MB  FROM python:3.12-slim
    FINAL 1   260ee0cf82a6     61.52 MB  COPY --from=builder /opt/venv /opt/venv
    FINAL 2   ee47b26affaa      2.34 MB  COPY --from=builder /app/dist /app/dist
      the builder stage is thrown away: only what a COPY --from names survives.
      note that the venv layer keeps its digest across the copy -- same bytes,
      same address. Content addressing is what makes a stage boundary cheap.

    builder stage total   262.54 MB   6 layers (discarded)
    single-stage image    271.92 MB   8 layers
    multi-stage image     108.94 MB   3 layers
    saved 162.98 MB  =  2.50x smaller. The 153.24 MB toolchain layer and the
    9.38 MB pip cache are never in the final image to be deleted in the first place.
    final merged filesystem: 51 files, 108.93 MB -- no gcc, no headers, no source.

(total wall time 3.5 s)
```

Read what each section proves.

**Section 1** is the structural claim, made concrete. Eight instructions, six layers, and two instructions (`ENV`, `CMD`) that produce **0 B** because they touch the config blob only. The merged filesystem is **77 files and 260.23 MB**; the sum of the layer blobs is **260.24 MB** — very nearly the same here because nothing in this Dockerfile shadows anything, which will not be true of a real image. And the image digest, `sha256:280fe298a8fa…`, is the hash of the manifest, which is the hash of a document containing the hashes of everything else. That chain is why a digest reference is a promise about bytes rather than a promise about a name.

**Section 2 is the centrepiece.** Start with the cold build, because it is the control: both orderings do **identical work, 260.24 MB, 551 seconds**, and the good ordering is *0.010 s slower* for writing one extra layer. There is no upfront cost to pay. Then the one-line edit to `src/routes.py`. The deps-first build gets **4 hits and rebuilds 2 layers — 410.4 KB, 3.21 s.** The source-first build gets **1 hit and rebuilds 4 — 215.16 MB, 551.21 s.** That is **171.6x on time and 537x on bytes**, and the mechanism is spelled out in the rebuild lists: B rebuilt `RUN apt-get` and `RUN pip`, neither of which reads a `.py` file, because `COPY .` missed above them.

Then the part that makes this an engineering decision rather than a slogan. Change the **lockfile** instead and A's lead falls to **1.16x** (473.22 s vs 551.21 s), because now the miss is at `COPY requirements.txt` and the expensive install is downstream of it. The weekly table prices that honestly: **20.6x at a 5% dependency-change rate, 1.2x at 100%.** If a bot bumps your lockfile on every build you are living in the last row, and the answer is not reordering — it is a cache mount, below. Finally, the `.dockerignore`: the same `COPY .` produces a **371.8 KB layer with one and an 80.00 MB layer without, 220x**, and the `.env` in that 80 MB is a credential you have now published.

**Section 3** isolates non-determinism one cause at a time, and the *shape* of the damage is the lesson. Wall-clock mtimes and unsorted entries corrupt **layers 1 through 5 — everything this build produces** — because they are properties of how bytes get written. An unpinned version corrupts **layer 3 alone**, but the run prints what moved (`flask -> 3.1.4, sqlalchemy -> 2.0.45, pydantic-core -> 2.33.4`) and layer 3 is the dependency layer that everything else sits on. Then the proof: with `SOURCE_DATE_EPOCH`, sorted entries and a complete lockfile, two independent builds with fresh caches produce `sha256:280fe298a8fa1e1aa00e578cab3b7def0763afd7f8e4882dca07b9862cada667` **twice**, `equal: True`. Same input, same digest, no exceptions.

**Section 4** is the deletion trap and its fix, with the numbers side by side. The `rm -rf` removes **30.38 MB of files from the merged view (73 files → 70)** and grows the image by **64 bytes** — three whiteout markers, zero bytes reclaimed. Meanwhile `/tmp/deploy_key` reports `False` for "in the merged filesystem" and is read straight back out of layer 2, 84 bytes, contents intact. The multi-stage version discards a **262.54 MB, 6-layer builder** and ships **108.94 MB in 3 layers, 2.50x smaller, 162.98 MB saved** — with a final filesystem of **51 files, 108.93 MB** containing no compiler, no headers and no source. Nothing was deleted to get there. The bytes were never added.

## Use It

Everything above maps onto a real builder with no translation. Here is the Dockerfile that produces the cascade, and the one that does not.

```dockerfile
# BAD — the source sits underneath the dependency install.
# Every edit to any .py file reruns apt AND pip.
FROM python:3.12-slim
COPY . /app                                     # <- volatile input, at the bottom
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential libpq-dev
RUN pip install -r requirements.txt             # 470 s, every single build
CMD ["python", "-m", "myapp"]
```

```dockerfile
# GOOD — cheapest and most stable first, most volatile last.
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential libpq-dev \
    && rm -rf /var/lib/apt/lists/*              # SAME layer: these bytes never land
WORKDIR /app
COPY requirements.txt .                         # <- just the lockfile, 378 B
RUN pip install --no-cache-dir -r requirements.txt
COPY src/ ./src/                                # <- volatile input, at the top
CMD ["python", "-m", "myapp"]
```

Two details in the good version carry real weight. The `rm -rf /var/lib/apt/lists/*` is chained with `&&` **inside the same `RUN`**, so those bytes are never committed to a layer at all — which is the only way a cleanup ever shrinks anything. Put it in its own `RUN` and you get section 4's result: a whiteout layer and no savings. And `--no-cache-dir` stops pip writing its download cache into the layer; in the measured single-stage build that cache was **9.38 MB** of the 70.89 MB install layer.

Then the file that decides what `COPY` can even see:

```text
.git
.venv
__pycache__/
*.pyc
.env
.env.*
node_modules
.pytest_cache
dist/
build/
*.egg-info
Dockerfile
.dockerignore
README.md
docs/
```

Measured, this is the difference between a **371.8 KB** and an **80.00 MB** context layer. Treat it as a security control, not a tidiness one: an ignored `.env` cannot be copied into a layer by an over-broad `COPY .`, and "over-broad `COPY .`" describes most Dockerfiles.

### Multi-stage, in full

```dockerfile
# ---------- stage 1: everything expensive, thrown away ----------
FROM python:3.12-slim AS builder
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential libpq-dev && rm -rf /var/lib/apt/lists/*
ENV VIRTUAL_ENV=/opt/venv
RUN python -m venv $VIRTUAL_ENV
ENV PATH="$VIRTUAL_ENV/bin:$PATH"
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ---------- stage 2: the image you actually ship ----------
FROM python:3.12-slim
RUN useradd --uid 10001 --create-home app       # never run as root
COPY --from=builder /opt/venv /opt/venv         # only the artifact, not the toolchain
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
WORKDIR /app
COPY --chown=10001:10001 src/ ./src/
USER 10001
CMD ["python", "-m", "myapp"]
```

The `venv` is the trick that makes this work cleanly in Python: it collects every installed dependency under one path, so a single `COPY --from` moves the whole dependency closure without moving the compiler that built it. The measured equivalent shipped **108.94 MB instead of 271.92 MB.** `--chown` matters too: without it the copy lands as root-owned and a non-root `USER` cannot write anywhere it needs to.

### BuildKit: cache mounts and secret mounts

BuildKit is the modern builder behind `docker build`, and it adds the two mounts that solve the two problems ordering cannot.

```dockerfile
# syntax=docker/dockerfile:1.7
FROM python:3.12-slim AS builder

# A CACHE MOUNT: persists across builds, and is NOT part of any layer.
# This is the answer to "our bot bumps the lockfile on every build".
RUN --mount=type=cache,target=/root/.cache/pip \
    --mount=type=bind,source=requirements.txt,target=requirements.txt \
    pip install -r requirements.txt

# A SECRET MOUNT: present during this RUN, in NO layer afterwards.
# This is the only correct way to use a credential at build time.
RUN --mount=type=secret,id=pip_token \
    PIP_INDEX_URL="https://$(cat /run/secrets/pip_token)@pypi.internal/simple" \
    pip install -r requirements-private.txt
```

```bash
docker build --secret id=pip_token,src=$HOME/.pip_token -t myapp:dev .
```

A **cache mount** is a persistent directory attached for the duration of one `RUN` and excluded from the resulting layer. When the lockfile changes the step still reruns, but it reruns against a warm package cache instead of an empty one — which is exactly the "100% dependency-change" row that no ordering could rescue. A **secret mount** is the fix for section 4's deploy key: the credential exists inside the `RUN`, at `/run/secrets/<id>`, and is in no layer afterwards. `COPY secret … && RUN rm secret` is not a weaker version of this; it does not work at all.

### Pin everything

```dockerfile
# A TAG IS A MUTABLE POINTER. This is not the same image tomorrow:
FROM python:3.12-slim

# A DIGEST IS AN IMMUTABLE PROMISE ABOUT BYTES:
FROM python:3.12-slim@sha256:5b4e0e4d4a3d5f1c9d5f0e6c8b7a9f2e1d0c3b4a5e6f7a8b9c0d1e2f3a4b5c6d
```

The same discipline applies one level up: `apt-get install libpq-dev=15.6-0+deb12u1` rather than `libpq-dev`, and a fully resolved lockfile with hashes rather than a hand-written requirements list.

```text
# requirements.txt — generated, never hand-edited
# pip-compile --generate-hashes --output-file=requirements.txt requirements.in
flask==3.1.2 \
    --hash=sha256:bf656c15c80190ed628ad08cdfd3aaa35beb087855e2f494910aa3774341...
sqlalchemy==2.0.43 \
    --hash=sha256:788bfcef6787a7764169cfe9859fe425bf44559619e1d9f56f5bddf2ebf6...
```

`--generate-hashes` is the part people skip and the part that matters: a version pin says "give me 3.1.2," a hash says "give me *these bytes*." Without hashes, a compromised or re-uploaded artifact still satisfies your pin. Lesson 4 takes this all the way to signing and provenance.

For reproducibility, hand the builder a fixed clock and let it normalise the rest:

```bash
export SOURCE_DATE_EPOCH=$(git log -1 --pretty=%ct)     # your commit's timestamp
docker buildx build \
  --build-arg SOURCE_DATE_EPOCH=$SOURCE_DATE_EPOCH \
  --output type=image,name=myapp:1.4.0,rewrite-timestamp=true \
  --provenance=true --sbom=true .
```

`rewrite-timestamp=true` normalises layer mtimes to `SOURCE_DATE_EPOCH`, which is the single highest-value reproducibility switch available and costs nothing. Note that hermeticity is the harder half and it is *your* job: a build that fetches from the network at build time can never be fully reproducible, no matter how the timestamps are normalised.

### Inspect what you actually built

```bash
docker history myapp:1.4.0                # every layer, its size, and the instruction
docker inspect myapp:1.4.0 --format '{{json .RootFS.Layers}}' | jq   # the diff_ids
docker buildx imagetools inspect myapp:1.4.0                          # the manifest
dive myapp:1.4.0                          # per-layer file browser + a "wasted bytes" score
docker build --progress=plain . 2>&1 | grep CACHED                    # what actually hit
```

`docker history` is the fastest audit in this lesson: a layer whose size is far larger than the instruction suggests is a cleanup that did not clean, a cache that was committed, or a `COPY .` with no `.dockerignore`. `dive` goes further and shows you the shadowed and deleted-but-present files — the ones you are downloading and can never open.

### Multi-architecture

```bash
docker buildx build --platform linux/amd64,linux/arm64 -t myapp:1.4.0 --push .
```

This produces one image per platform plus an index that maps platform to manifest, so a single tag serves both an arm64 laptop and an amd64 server. Cross-building under emulation is slow enough that native runners per architecture are usually worth it. Lesson 4 covers the index itself.

### Production rules

- **Order cheapest-and-most-stable first, most volatile last.** Base, system packages, lockfile, `pip install`, then source. Measured: 171.6x on a code change — and know that it collapses to 1.16x on a dependency change, which is when you reach for a cache mount instead.
- **Ship a `.dockerignore` before your first `COPY .`,** and treat it as a security control. Measured: 371.8 KB versus 80.00 MB, with a `.env` in the difference.
- **Never let a secret into a layer.** `--mount=type=secret` or a build stage that is discarded. If one has already shipped, the only response is rotation — the image is the disclosure.
- **Clean up in the same `RUN` that made the mess, or not at all.** A separate `rm -rf` adds a whiteout layer and frees nothing. Measured: -30.38 MB of files, +64 B of image.
- **Multi-stage by default.** Compilers, headers, dev dependencies and build caches belong in a stage you throw away. Measured: 2.50x smaller.
- **Pin the base by digest and the dependencies by lockfile with hashes.** A tag is a mutable pointer; a digest is a promise about bytes.
- **Make CI builds hermetic and set `SOURCE_DATE_EPOCH`.** No network fetch of a moving target, no `latest`, no `curl | sh`. Then verify it: build twice on different runners and compare digests. A reproducibility claim you have not tested is a hope.
- **Run as a non-root `USER` with an explicit uid**, and read `docker history` before you tag anything as a release.

## Think about it

1. Your team's bot opens a lockfile bump every day, so roughly 40% of your builds change dependencies. The measured table says ordering buys you about 3x in that regime rather than 171x. Design the build you would actually ship: what does a cache mount change about *which* work reruns, what does it not change, and what new failure mode does a persistent, unversioned cache directory introduce?
2. Two CI runners build the identical commit and produce different image digests. You have already set `SOURCE_DATE_EPOCH` and confirmed the lockfile is fully pinned with hashes. List the remaining candidate causes in the order you would test them, and say for each one whether you would expect it to corrupt one layer or all of them — and how that expectation narrows the search.
3. A `RUN`'s cache key is its command string, not its result. Construct a concrete scenario where that makes a build green on a developer's laptop and red in CI on the same commit, then green again on a retry. Which of the three runs is telling you the truth about your software?
4. You discover a `COPY .env` in a Dockerfile that has been shipping to a public registry for six months, followed by `RUN rm .env`. Write the incident response in order. What can you learn from the registry about who pulled it, what is recoverable, what is not, and at what point in your list does deleting the tag appear — and why is it not first?
5. A colleague proposes squashing every build to a single layer, arguing it makes images smaller and removes the whole class of secret-in-a-layer problems. Evaluate that against all three diseases in this lesson — cache efficiency, size on the wire, and reproducibility — and say what a fleet of 200 machines pulling that image would experience on the next deploy.

## Key takeaways

- **An image is a manifest, a config blob, and ordered layer blobs — all addressed by SHA-256, none of which is a filesystem.** The measured build turned 8 instructions into **6 layers, 260.24 MB of blobs, a 77-file 260.23 MB merged view**, and one image digest, `sha256:280fe298a8fa…`, which is the hash of the manifest. `ENV` and `CMD` produced **0 B**: they change the config only, and still change the image's name.
- **A cache miss invalidates every instruction below it, so instruction order is a performance decision.** The identical one-line edit cost **3.21 s and 410.4 KB** with dependencies installed first, and **551.21 s and 215.16 MB** with `COPY . /app` at the top — **171.6x and 537x** — while the cold build was a dead tie (551.22 s vs 551.21 s). The reordering costs nothing and pays on every rebuild.
- **But the win is a bet on what you change.** Bump the *lockfile* instead of the source and the same advantage collapses from **171.6x to 1.16x** (473.22 s vs 551.21 s): no ordering helps when the thing you changed feeds the expensive step. Weighted over 100 builds a week that is **20.6x at a 5% dependency-change rate and 1.2x at 100%** — and at 100% the answer is a BuildKit cache mount, not a Dockerfile reshuffle.
- **Same input, same digest — but only after you fix three specific things.** Wall-clock mtimes and unsorted entries corrupted **every layer the build produced (1 through 5)**; a single unpinned dependency corrupted **only layer 3**, which happens to be the one everything else stacks on. With `SOURCE_DATE_EPOCH`, sorted entries and a full lockfile, two independent cold builds produced `sha256:280fe298a8fa…` **twice, `equal: True`**. And remember that a `RUN`'s cache key is the **command string, not its result** — caching and non-determinism hide each other.
- **You cannot delete bytes out of an image; you can only decline to put them in.** `rm -rf` removed **30.38 MB from the merged filesystem (73 files → 70)** and made the image **64 bytes bigger** — three whiteouts, zero bytes reclaimed. The deploy key it "deleted" was **absent from the merged view and still readable in layer 2 (`9d74698ed8d1`), 84 bytes**, recovered verbatim. Clean up inside the same `RUN`, or use a stage you throw away.
- **Multi-stage is the structural fix for both size and secrets.** Discarding a **262.54 MB, 6-layer builder** produced a final image of **108.94 MB in 3 layers — 2.50x smaller, 162.98 MB saved** — with **51 files and no compiler, headers or source**. The venv layer kept its digest across the `COPY --from` (`260ee0cf82a6` on both sides): content addressing is what makes a stage boundary free.

Next: [Registries, Digests & the Software Supply Chain](../04-registries-and-supply-chain/) — you can now produce the same bytes twice; the next question is how those bytes get pushed, pulled, deduplicated and *trusted* by a machine that did not build them.
