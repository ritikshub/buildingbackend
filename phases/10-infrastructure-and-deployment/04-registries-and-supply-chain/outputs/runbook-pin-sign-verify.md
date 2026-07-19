---
name: runbook-pin-sign-verify
description: The procedure for producing, signing and admitting an artifact you can name — one-time registry setup, the per-build pin-sign-attest sequence, the admission gate rollout, moving a pin on purpose, and the four incidents that start with "we do not know what is running".
phase: 10
lesson: 04
---

# Pin, sign, verify — the supply-chain runbook

Sections 1–3 are set-up you do once per registry and once per pipeline. Sections 4–5 run
on every build and every deploy. Sections 6–9 are incident procedures; read them before
you need them, because each one is unrunnable if the earlier sections were skipped.

The one sentence the whole runbook defends: **a tag is a mutable pointer in someone
else's database; a digest is the content.** Two pulls of the identical reference
`registry.internal/app:1.0` returned `sha256:f29d198c…` and `sha256:2e3da6b0…` in this
lesson's run, while the same two pulls pinned by digest returned byte-identical content
both times.

## 1 · One-time: the registry

- [ ] **Turn on tag immutability** on every repository that supports it (ECR and ACR do).
      A re-push to an existing tag becomes an error rather than a silent overwrite. This is
      a checkbox and it is the highest-value single setting in this lesson.
- [ ] Audit who holds **push** credentials, and whether any of them is a long-lived static
      token. Every one of them can re-point every tag, today, with no audit trail a client
      can see.
- [ ] Stand up a **pull-through cache** inside your network, configured as a mirror. Without
      it, an upstream outage or a `TOOMANYREQUESTS` rate limit — Docker Hub's anonymous
      limit is per-IP, and a NAT gateway makes your whole cluster one IP — stops you
      scaling up at exactly the moment you are scaling up under load.
- [ ] Give the registry the availability requirements of a **database, not a wiki**.
      If it is unreachable, you cannot start pods: not "deploys are blocked" but
      "you cannot recover from an unrelated outage".
- [ ] Write the **lifecycle policy** so that your rollback window is strictly shorter than
      your retention window, and confirm that before enabling it:
  - [ ] keep the last N tagged releases indefinitely (N ≥ your rollback depth);
  - [ ] never expire a digest currently referenced by a running workload;
  - [ ] expire **untagged** images after 14–30 days;
  - [ ] state your rollback window out loud. If it is six weeks, retention is not 14 days.

## 2 · One-time: the pipeline identity

- [ ] Signing uses **keyless / OIDC** (Sigstore + cosign) where the platform allows it. The
      signer authenticates with an existing identity, gets a short-lived certificate, signs,
      and discards the key. There is no key to steal because after ~10 minutes there is no
      key.
- [ ] If you must use long-lived keys, they have a **key id in the artifact metadata** and a
      rotation date. A cryptographically valid signature from a rotated key must verify
      **False** — trust is a policy question, not a maths question.
- [ ] The list of **allowed source repositories** and **trusted builders** is written down,
      in version control, as the policy's input. Provenance naming a fork or a laptop is a
      deny.
- [ ] Everyone knows that **provenance is worth exactly as much as the isolation of the
      thing that generated it.** Provenance emitted by a build script the attacker controls
      proves nothing.

## 3 · One-time: the admission gate

- [ ] Deploy the policy (Kyverno or Gatekeeper) in **`Audit` mode first** and read the
      report. In any real cluster the first run flags things you did not know you were
      running.
- [ ] The policy requires **three independent things**, because each one alone is defeated
      by an attack the other two catch:
  - [ ] pinned by digest,
  - [ ] signature from a trusted identity,
  - [ ] provenance naming an allowed source repo and a trusted builder.
- [ ] The verify step pins the **identity**, not just the presence of a signature —
      `--certificate-identity-regexp` and `--certificate-oidc-issuer`. Verifying without
      them proves only that *somebody* signed it. Anyone can sign anything.
- [ ] Work the Audit report to zero, then switch to `Enforce`. Expect the shape this lesson
      measured: **1 of 6 candidates admitted**, with the correct, signed, well-provenanced
      image denied purely for being referenced by tag. That is not pedantry — a gate that
      admits a tag has verified a pointer, and the pointer can be moved after the check.
- [ ] `mutateDigest: true` is enabled as a **safety net**, not as the plan. It resolves a tag
      to a digest at admission and rewrites the pod spec, so the running object records the
      exact artifact — but it cannot tell you which bytes you *intended*.

## 4 · Every build

1. **Build**, with the base image itself pinned by digest (`FROM python:3.12-slim@sha256:…`).
2. **Push**, then immediately capture the digest — this is the only identifier that matters
   from here on:
   ```bash
   DIGEST=$(crane digest registry.internal/app:1.1)
   ```
3. **Check you captured the index digest, not a platform's.** If the tag points at a
   multi-platform index, `sha256:f0f8e9b7712b` is the index and `sha256:021ff5d9dff0` /
   `sha256:6903a610c98a` are the amd64 and arm64 manifests underneath it. Pinning a
   platform manifest silently pins your architecture — it works until someone adds an
   arm64 node pool.
4. **Sign the digest**, never the tag. Signing a tag would be signing a pointer:
   ```bash
   cosign sign --yes "registry.internal/app@${DIGEST}"
   ```
5. **Generate and attach an SBOM** as an attestation on the same subject:
   ```bash
   syft "registry.internal/app@${DIGEST}" -o spdx-json > sbom.spdx.json
   cosign attest --yes --type spdxjson --predicate sbom.spdx.json \
     "registry.internal/app@${DIGEST}"
   ```
6. **Attach provenance** — source repo, commit, builder, build parameters — generated by the
   build platform, not by the build.
7. **Scan the digest you just built**, and gate on *reachable and fixable* findings (see §8).
8. **Emit the digest as a build output** so the deploy step cannot re-resolve the tag. If
   your deploy job runs `crane digest` a second time, you have reintroduced the whole
   problem.

## 5 · Every deploy

- [ ] The manifest in git contains `@sha256:…`. The tag lives next to it **in a comment**,
      for humans:
      ```yaml
      # registry.internal/app:1.1
      image: registry.internal/app@sha256:f0f8e9b7712b7c0561a5b126130c4fa54226425ab5672695c821a5119d0df182
      imagePullPolicy: IfNotPresent
      ```
- [ ] `imagePullPolicy: IfNotPresent` — with a digest this is not merely safe but strictly
      correct: a cached blob whose sha256 matches the request **is** the request, by
      definition. `Always` exists to work around mutable tags (which is why Kubernetes
      special-cases `:latest` to default to it) and it puts a registry round-trip in the
      recovery path of every pod start.
- [ ] The digest in the running object matches the digest CI signed. Verify this, do not
      assume it.
- [ ] The release record — deploy log, change ticket, incident timeline — carries the
      **digest**. "We deployed 1.1" is not a record of anything.

## 6 · Moving a pin on purpose

A digest pin with no automation behind it is a decision to run unpatched software. Six
months after pinning you are shipping a two-hundred-day-old TLS library, and the pin is
doing exactly what you asked.

- [ ] Everything is pinned by digest **in a file committed to git**.
- [ ] A dependency-update bot (Renovate, Dependabot) watches upstream and opens a **pull
      request** proposing the new digest, with the changelog attached.
- [ ] CI runs against the proposal exactly as it would for a code change.
- [ ] A **human merges it.** The pin moves; the audit trail is a commit with a diff.
- [ ] If the bot is off, you have chosen "frozen". Say so out loud and put a date on it.

## 7 · Incident: a push credential may have leaked

Assume every tag that credential could reach has been re-pointed. Nothing will have
alerted; a re-point is a database write.

1. **Revoke the credential first.** Everything below is invalid while it is still live.
2. Enumerate **which digests are actually running**, from the running objects — not from
   the Deployment's tag, and not from `APP_VERSION`, which the attacker controls.
3. For each running digest, confirm a **valid signature from a trusted identity** exists.
   An unsigned digest that is running is the finding.
4. Compare each running digest against the digest your pipeline recorded for that release.
   A mismatch is a confirmed substitution.
5. Check registry logs for pushes to existing tags in the exposure window. With tag
   immutability on, these are errors and trivially visible; without it, they are silent.
6. Re-deploy from known-good pinned digests. Note that a pinned deployment **was not
   affected by the re-point at all** — it never asked a question whose answer someone else
   controls.
7. If any node pulled during the window, treat that node's image cache as suspect.

## 8 · Incident: a serious advisory just dropped

This is the question an SBOM exists to answer, and the only one that turns a week of
archaeology into a lookup.

1. Query your stored SBOM attestations for the component and version across every released
   digest. Do not rebuild anything to find out.
2. Split the hits into **reachable** and **present but never loaded**. A scanner reads the
   SBOM, not the call graph, and cannot make this distinction for you — in this lesson's
   run `app:1.0` had 5 findings of which 2 were in packages the image actually loads.
3. For reachable and fixable: rebuild on a patched base, move the pins by PR (§6), deploy.
4. For reachable and **not** fixable (`fixed_in` empty, no upstream patch): mitigate at
   another layer, and record a **named, dated, expiring exception**. Do not silently
   suppress — that is how a suppression list grows until it matches everything.
5. For present-but-unreachable: publish a VEX statement rather than blocking a release on
   it. `app:1.1` finished with 1 finding and 0 reachable, and that one had no upstream fix,
   which is exactly the case where a "no MEDIUM or above" gate blocks releases forever on
   something no attacker can reach.
6. Re-scan **what is deployed** on a schedule, not only what you build. A new advisory makes
   yesterday's clean image vulnerable without anything about it changing.

## 9 · Incident: the rollback target will not pull

Symptom: the pinned rollback digest returns **`MANIFEST_UNKNOWN`** and the deploy stops.

1. Recognise this as the pinned path **failing closed**, which is the property that makes
   pinning safe to rely on. It did not quietly resolve to something else.
2. The manifest was garbage-collected by a lifecycle policy. Check the policy's age and
   count rules against the age of the release you are trying to reach.
3. Recover by finding the digest in any surviving location: a pull-through cache, another
   region's registry, a node's local image store, or a re-push from an archived export.
4. If it is genuinely gone, you are rebuilding from the recorded commit — which only works
   if the build is reproducible and the base image digest was pinned in the repo. This is
   the moment §4 step 1 pays for itself.
5. Fix the lifecycle policy before closing the incident (§1). Then state the new rollback
   window in the runbook.

## 10 · Anti-patterns to grep for

- [ ] `image: .*:latest` or any tag reference in a production manifest, Helm value, or
      Terraform file.
- [ ] `crane digest` / `docker inspect` run in the **deploy** job rather than consumed from
      the build job's output.
- [ ] `cosign verify` without `--certificate-identity-regexp`.
- [ ] A signature or attestation whose subject is a tag.
- [ ] A pinned platform manifest where an index digest was meant.
- [ ] A lifecycle policy with an age rule and no exemption for referenced or tagged releases.
- [ ] A scanner gate defined by a count of findings rather than by reachability and
      fixability.
- [ ] A registry with no pull-through cache in front of it and `imagePullPolicy: Always`
      everywhere — a self-inflicted hard dependency on an external service during recovery.
- [ ] Tag immutability available and not enabled.

> ## Decision shortcuts
>
> **"Can I name the exact bytes running in production right now, from a record, without
> asking a node?"** No → you are deploying pointers.
>
> **"Does this check verify a pointer or content?"** A signature on a tag, a scan of a tag,
> an admission rule that allows a tag: all three verify something that can be moved
> afterwards.
>
> **"If the registry is down for an hour, what breaks?"** If the answer is more than
> "deploys", fix that before you fix anything else in this document.
>
> **"When did this pin last move, and who reviewed it?"** No answer → the pin is a freeze,
> not a policy.
