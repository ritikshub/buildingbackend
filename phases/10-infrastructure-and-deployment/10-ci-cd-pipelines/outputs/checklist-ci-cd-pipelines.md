---
name: checklist-ci-cd-pipelines
description: Audit a delivery pipeline for the four properties that make it trustworthy — one artifact built once and promoted by digest, a critical path short enough to hold a human's attention, content-derived caching, and a credential model with no standing production secret.
phase: 10
lesson: 10
---

# CI/CD pipeline — audit checklist

Run this against an existing pipeline, or before a new service's first production deploy.
Every item exists because skipping it has caused a real outage, a real leak, or a real
loss of trust in the pipeline — which reliably causes the first two.

Score honestly. A pipeline that fails section 1 does not benefit from sections 2-6.

## 1 · One artifact, built once, promoted

- [ ] **Exactly one job in the entire pipeline produces the artifact.** Grep every deploy
      job for `docker build`, `pack`, `mvn package`, `npm run build`. Each hit is a place
      where the thing you tested and the thing you shipped can differ.
- [ ] The build job **exports the digest as an output**, and every downstream job consumes
      that output. Not a tag. Not `latest`. Not `${GIT_SHA}` re-resolved through a registry.
- [ ] Deployment manifests reference the image **by digest** (`image: repo@sha256:…`).
      A tag in a production manifest is a mutable pointer to bytes nobody has re-verified.
- [ ] The artifact **contains no environment-specific values**. If the build takes an
      environment name as an input, build and release have been merged and you have N
      artifacts, not one.
- [ ] Each environment's deploy records a **release id** = hash(artifact digest + config
      hash), so a config-only change is a first-class, rollback-able event with a target.
- [ ] You can answer, in under a minute and without SSH, **"which digest is running in
      production, and which pipeline run produced it?"**
- [ ] Build provenance and an SBOM (software bill of materials) are attached to the digest
      as attestations, and something verifies them at admission — not just at build time.

## 2 · The critical path

- [ ] You have **computed the critical path**, not just looked at per-job durations. The
      forward/backward pass is thirty lines; most CI UIs will not do it for you.
- [ ] Every stage on the path has an owner and a recorded duration trend.
- [ ] **The critical path is under 10 minutes** for the pre-merge gate. If it is not, the
      pipeline has stopped being a feedback loop and people are context-switching on it.
- [ ] No optimisation work is scheduled against an **off-path** stage without someone first
      stating what the new critical path will be. Halving a stage with slack saves zero.
- [ ] You know the **runner count at which wall time stops improving**. Concurrency past
      the critical-path floor is money spent on idle machines.
- [ ] The slow, thorough suite (full end-to-end, performance, deep security) runs **after**
      merge or on a schedule, and the risk that trade accepts is written down.
- [ ] Someone checks whether an edge on the critical path is **real**. "Integration tests
      need the production image" is often "integration tests need an image".

## 3 · Caching and hermeticity

- [ ] Every cache key is derived from the **content of its inputs** — lock file hash, source
      tree hash, tool versions. Never a branch name, a date, or a build number.
- [ ] Nothing ambient enters a build: no hostname, no wall clock, no globally installed
      tool, no dependency version resolved at build time.
- [ ] Base images and third-party CI actions are **pinned by digest or commit SHA**, updated
      by automation, and merged by a human as a reviewable diff.
- [ ] **Cache restore time is measured.** A cache that costs more to restore than the stage
      it skips should be deleted; they exist in real pipelines more often than anyone admits.
- [ ] The cache is stored somewhere **every runner can reach**, not on one machine's disk.
- [ ] Two builds of the same commit, run a week apart on different runners, produce the
      **same digest**. If you have never tested this, you do not know that they do.
- [ ] Cache scope is understood: a cache writable from a pull-request branch is an
      **attack surface** — poisoned entries are served to later trusted builds.

## 4 · Flakiness and trust

- [ ] The **green rate on clean changes** is measured and graphed. If you cannot state it
      as a number, you cannot tell noise from signal, and neither can the team.
- [ ] **No blanket auto-retry** of failed jobs. It buys green by selling detection of
      exactly the defects — races, ordering, timing — that are hardest to find any other way.
- [ ] Flaky tests are **quarantined with a named owner and a deadline**, not skipped, not
      retried, not deleted. A quarantined test protects nothing; it is a named debt.
- [ ] The **count of quarantined tests** is a tracked metric with a ceiling. Crossing the
      ceiling stops feature work; otherwise quarantine becomes a landfill.
- [ ] Each job's failure output identifies **which assertion failed**, in the first screen,
      without opening an artifact. Cheap to read means people read it.
- [ ] Tests do not share mutable global state — no fixed ports, no shared fixture rows, no
      reliance on unordered query results, no dependence on wall-clock time.
- [ ] Test shards are balanced by **measured duration**, not file count. A matrix job's
      wall time is its slowest shard.

## 5 · Credentials and identity

- [ ] **No long-lived cloud key exists in CI variables.** Use OIDC federation; the runner
      proves its identity and receives a credential that expires in minutes.
- [ ] The cloud-side trust policy matches the **full subject claim** (repo, ref *and*
      environment). Audit for wildcards — `repo:org/*` grants the role to the whole org.
- [ ] Job permissions default to **read-only**, and write scopes are granted per job. A
      test job needs no deploy credential and no registry write.
- [ ] **Pull-request code from forks never runs with secrets in scope.** A build step is
      arbitrary code execution with your job's permissions, written by a stranger.
- [ ] A pull request **cannot modify the gate that governs it** — required reviewers and
      environment protection live outside the workflow file.
- [ ] Deploy credentials are isolated in a job that does **nothing but deploy**: no user
      code, no test execution, no third-party actions beyond the credential exchange.
- [ ] Secrets are **masked in logs**, and you have verified that masking survives base64,
      JSON encoding and multi-line values. It usually does not.
- [ ] Every credential CI holds has an **owner, an expiry, and a documented blast radius**.

## 6 · Gates, promotion and rollback

- [ ] The release branch requires pull requests, forbids force pushes, and requires the
      **specific named** status checks — so deleting a job does not satisfy the requirement.
- [ ] **"Include administrators" is enabled.** A rule you can bypass gets bypassed at 03:00,
      by the person under the most pressure, in the situation with the least review.
- [ ] A **merge queue** tests the prospective merge result. Two individually green changes
      can be collectively red, and no amount of pre-merge testing on either branch finds it.
- [ ] Production promotion is an explicit gate with **required reviewers**, and the reviewer
      can see the digest, the diff since the current production release, and the test results.
- [ ] Promotion is a **pointer move** — a digest copied from one environment's manifest to
      another. If promotion runs a build, this checklist starts again at section 1.
- [ ] **Rollback is the same mechanism in reverse**, and it has been executed in a drill in
      the last quarter. Point at the previous digest; do not rebuild an old commit.
- [ ] If deploys are **push**-based, you know the full list of what can reach production
      with CI's credential. Prefer **pull**-based: the cluster reaches out, nothing reaches in.
- [ ] With GitOps, `prune` and `selfHeal` behaviour is understood by everyone on call, and a
      **break-glass procedure** exists for the 03:00 case where a controller will revert
      your manual fix — including what stops break-glass becoming the normal path.

## 7 · Observability of the pipeline itself

- [ ] Pipeline duration, queue time, green rate and flake count are on a dashboard someone
      looks at weekly. A pipeline is production infrastructure for the people who ship.
- [ ] **Queue time is separated from run time.** "CI is slow" is often "runners are busy",
      which is a completely different fix from "the critical path is long".
- [ ] Deploy frequency, lead time from commit to production, change failure rate and time
      to restore are tracked. These are the four metrics that correlate with both speed
      and stability — they move together, not against each other.
- [ ] Every deploy emits an event your monitoring can overlay on graphs, carrying the
      release id. "What changed at 14:12?" should be one glance, not an archaeology project.
