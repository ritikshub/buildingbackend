---
name: checklist-images-layers-and-builds
description: A pre-merge review pass for any Dockerfile — cache ordering, build context, secrets, size, and the reproducibility switches — with the measured cost of skipping each item.
phase: 10
lesson: 03
---

# Dockerfile & build review — pre-merge checklist

Run this against any Dockerfile before it merges, and again whenever a build gets slow,
an image gets big, or CI goes red on an unchanged commit. Every item exists because
skipping it has cost somebody a nine-minute build, a gigabyte of registry storage, or a
key rotation.

Diagnose first. **These are three separate diseases with three separate cures**, and
treating them as one complaint ("the build is bad") is why the wrong fix gets applied:

| symptom | disease | section |
|---|---|---|
| slow rebuild on a small change | cache invalidation | 1, 2 |
| image far larger than the app | size | 4 |
| green yesterday, red today, same commit | non-determinism | 5 |

## 1 · Instruction order

- [ ] Instructions run **cheapest-and-most-stable first, most volatile last**: base →
      system packages → lockfile → dependency install → application source.
- [ ] `COPY . /app` does **not** appear above the dependency install. Measured cost of
      getting this wrong on a one-line source edit: **551.21 s and 215.16 MB rebuilt
      instead of 3.21 s and 410.4 KB — 171.6x and 537x.**
- [ ] Only the lockfile is copied before the install (`COPY requirements.txt .`), not the
      whole tree.
- [ ] You know your **dependency-change rate**. Reordering buys ~20x at 5% and ~1.2x at
      100%; if a bot bumps your lockfile on every build, ordering is not your fix and a
      cache mount is.
- [ ] Anything downstream of a frequently-edited file genuinely needs to be there. Every
      instruction below a miss reruns, whether or not it reads the changed file.
- [ ] Verified, not assumed: `docker build --progress=plain . 2>&1 | grep CACHED` on a
      realistic edit shows the layers you expected to hit.

## 2 · The build context

- [ ] A `.dockerignore` exists **before** the first `COPY .`. Measured: the same
      instruction produced a **371.8 KB layer with one and 80.00 MB without — 220x.**
- [ ] It excludes at minimum: `.git`, `.venv`, `node_modules`, `__pycache__`, `*.pyc`,
      `.env` and `.env.*`, test caches, `dist/`, `build/`, `*.egg-info`.
- [ ] It is treated as a **security control**: an ignored `.env` cannot be swept into a
      layer by an over-broad `COPY .`, and over-broad `COPY .` describes most Dockerfiles.
- [ ] `COPY` targets are as narrow as they can be (`COPY src/ ./src/`, not `COPY . .`).
      A narrower copy is also a narrower cache key.

## 3 · Secrets

- [ ] **No secret is ever `COPY`ed into a layer.** Not even one removed on the next line:
      measured, the key was absent from the merged filesystem and still readable in
      layer 2, 84 bytes, recovered verbatim.
- [ ] Build-time credentials use `RUN --mount=type=secret,id=…` (read from
      `/run/secrets/<id>`) or live only in a discarded build stage.
- [ ] No credential is passed via `ARG` — build arguments are recorded in the image
      history and `docker history` prints them.
- [ ] No credential is set via `ENV` — every ENV value lands in the config blob, and a
      later `ENV X=` overwrites the value while the history still carries the original.
- [ ] `docker history` on the built image has been read by a human before the first push.
- [ ] If a secret has already shipped: **rotate it.** Deleting the tag is not remediation;
      publishing the image was the disclosure. Deleting the tag comes after rotation, and
      only after you have checked the registry's pull logs.

## 4 · Size

- [ ] The build is **multi-stage**: compilers, headers, dev dependencies and build caches
      live in a stage that is thrown away. Measured: **271.92 MB in 8 layers → 108.94 MB
      in 3 layers, 2.50x smaller, 162.98 MB saved.**
- [ ] Cleanup happens **inside the same `RUN`** that created the mess
      (`apt-get install … && rm -rf /var/lib/apt/lists/*`). A separate `rm -rf` adds a
      whiteout layer and frees nothing: measured **-30.38 MB of files, +64 B of image.**
- [ ] Package-manager caches are suppressed at source (`pip --no-cache-dir`,
      `npm ci --omit=dev`, `apt-get --no-install-recommends`) rather than deleted later.
      That cache was **9.38 MB of a 70.89 MB install layer.**
- [ ] The base is the smallest one that works: `-slim` over the full image; distroless
      when you have decided you can live without a shell.
- [ ] If distroless: the **debugging story is written down** — ephemeral debug container,
      a sidecar, or a `:debug` tag — before it reaches production, not during an incident.
- [ ] `docker history` has been checked for a layer much larger than its instruction
      suggests. That is a cleanup that did not clean, a committed cache, or a missing
      `.dockerignore`.
- [ ] `dive` has been run once to see the shadowed and deleted-but-present files you are
      shipping and can never open.

## 5 · Reproducibility

- [ ] The base image is pinned **by digest** (`FROM python:3.12-slim@sha256:…`), not by
      tag. A tag is a mutable pointer; a digest is a promise about bytes.
- [ ] Dependencies come from a **generated lockfile with hashes**
      (`pip-compile --generate-hashes`, `package-lock.json`, `go.sum`, `Cargo.lock`).
      A version pin says "3.1.2"; a hash says "these bytes".
- [ ] Transitive dependencies are pinned too. A single unpinned transitive package
      changes the dependency layer's digest — and everything is stacked on that layer.
- [ ] `SOURCE_DATE_EPOCH` is set from the commit timestamp
      (`git log -1 --pretty=%ct`) and the builder is told to normalise timestamps
      (`--output type=image,rewrite-timestamp=true`).
- [ ] The build is **hermetic**: no `curl | sh`, no unpinned `apt-get install`, no fetch
      of a moving target at build time.
- [ ] **Tested, not claimed:** the same commit has been built twice on two different
      runners with cold caches and the digests compared. An untested reproducibility
      claim is a hope.

## 6 · Runtime posture

- [ ] A non-root `USER` with an explicit numeric uid, and `COPY --chown` so it can write
      where it must.
- [ ] `ENTRYPOINT` / `CMD` in **exec form** (`["python", "-m", "app"]`). Shell form makes
      `sh` PID 1, and `sh` does not forward `SIGTERM` to your process.
- [ ] Multi-arch handled deliberately: `buildx --platform linux/amd64,linux/arm64` with
      native runners per architecture if emulated builds are too slow.
- [ ] The image is referenced downstream **by digest**, so what you tested is what deploys.

> ## The one-line test for each disease
>
> **Slow?** Make a one-line source edit and rebuild. If anything but your source layer
> reruns, an instruction is in the wrong place.
> **Big?** Run `docker history` and find the layer that is larger than its instruction
> deserves.
> **Flaky?** Build the same commit twice, cold, on two machines. If the digests differ,
> your image is not a function of your source — and neither is anything you deploy.
