# AGENTS.md

Operating manual for contributors and AI agents touching this repo. Read it before opening a PR.

The repo is a **curriculum, not a SaaS app**. The lessons are the product. Every rule below keeps the lessons coherent and beginner-friendly over time.

---

## Philosophy

164 lessons across 13 phases, all written. Every backend primitive built by hand before a single framework gets imported — the TCP server, the router, the B-tree, the write-ahead log, the message queue, the cache, the container, the orchestrator — in **Python, standard library only**. Then you run the same thing through the production tool (Postgres, Redis, Kafka, a web framework) so it stops being a black box. The **"Build It / Use It"** split is the spine. Each lesson ships a reusable artifact — a runbook, checklist, or prompt — you can keep.

---

## Beginner-first (the north star)

This curriculum is aimed at people who may not yet know what binary is. Non-negotiable:

- **Start from the bottom.** Introduce a concept from first principles before using it. The first time a reader meets bits, packets, sockets, or SQL, explain it — don't assume it.
- **Define every acronym on first use**, per lesson (TCP = Transmission Control Protocol). Lessons are self-contained.
- **One new idea at a time.** If a lesson needs three prerequisites the reader doesn't have, those are three earlier lessons.
- **Show the whole path.** Prefer explanations that trace data end to end (e.g., application → transport → network → link → physical, and back) over isolated fragments.
- **No unexplained magic.** If a framework does something, the Build-It half already did it by hand.

---

## Repo layout

```
phases/
  NN-phase-slug/
    NN-lesson-slug/
      docs/en.md              # lesson explainer (the narrative)
      code/                   # runnable implementation(s), optional tests/
      quiz.json               # quiz questions (schema below)
      outputs/                # reusable artifact (prompt- / runbook- / checklist-)
README.md                     # public face; the table of contents build.js parses
ROADMAP.md                    # phase/lesson status (✅ 🚧 ⬚)
glossary/terms.md             # canonical term definitions
site/
  build.js                    # parses README + ROADMAP + glossary -> data.js
  data.js                     # GENERATED; do not edit or commit by hand
  lesson.html                 # fetches each lesson's docs/en.md at runtime
Dockerfile, docker-compose.yml, requirements.txt, Makefile   # the experiment sandbox
```

---

## Hard rules

1. **One commit per lesson directory.** Never batch multiple lessons into one commit. A 10-lesson PR has 10 commits.
2. **Conventional commit subjects** ≤72 chars: `feat(phase-NN/MM): <slug>`. Body explains *why*, not *what*.
3. **Diagrams: prefer a `​```svg` fence with a self-contained, crisp inline SVG.** No ASCII / Unicode box-drawing. Use `currentColor` for text/strokes/arrows (so the diagram follows the light/dark theme) and **no filters** (they blur on zoom); give each SVG unique element/marker ids. The renderer injects `​```svg` blocks directly and reuses the diagram Expand/modal UX. Legacy `​```mermaid` fences still render natively, but new diagrams should be SVG.
4. **Every fenced code block needs a language tag** — one of `text`, `json`, `python`, `typescript`, `javascript`, `go`, `rust`, `bash`, `console`, `sql`, `http`, `lua`, `yaml`, `dockerfile`, `hcl`, `rego`, `graphql`, `markdown`, `mermaid`, `svg`. The renderer highlights Python, Go, JS/TS and Rust; anything else renders correctly but unhighlighted, with its language label. Prefer an accurate tag over a generic `text` one.
5. **Original implementations only.** Don't cite external tutorials or curriculum repos in docs, code, or commits. When you state a fact, cite the canonical source — an **RFC, an official spec, or a paper** — not a secondary summary.
6. **Stdlib-first, dependency allowlist** (see below). The *Build It* half uses only the standard library; the *Use It* half may use the one production tool the lesson is teaching.
7. **Never commit generated files.** `site/data.js`, `site/sitemap.xml`, `site/llms.txt`, `site/build-meta.js` are rebuilt by `node site/build.js`. `.venv/`, `__pycache__/`, and the Docker `pgdata` volume are never tracked.

---

## Languages & dependencies

Curriculum language: **Python, standard library only** — no third-party imports in `code/`.
Go, TypeScript and Rust appear only in the Phase 13 capstone plan, which is not written yet. A lesson's `**Languages:**` field must match the files present in `code/`.

| Language   | Build It (from scratch)                     | Use It (the tool the lesson teaches)                    |
|------------|---------------------------------------------|--------------------------------------------------------|
| Go         | stdlib (`net`, `net/http`, `database/sql`, `encoding/json`) | e.g. `chi`, `pgx`, `go-redis`, `sarama` — one per lesson |
| Python     | stdlib (`socket`, `http`, `asyncio`, `sqlite3`) | `fastapi`, `uvicorn`, `pydantic`, `sqlalchemy`, `asyncpg`, `redis`, `httpx`, `strawberry-graphql` (see `requirements.txt`) |
| TypeScript | Node 20+ stdlib (`node:net`, `node:http`)   | `express` / `fastify` / `hono`, `pg`, `ioredis`         |
| Rust       | stdlib (single-file `rustc --edition 2021`) | `tokio`, `axum`, `sqlx` — only when the lesson needs it  |

If a suggested dependency isn't teaching-essential, skip it: "stays stdlib-first for educational clarity."

---

## Lesson contract

### docs/en.md

```markdown
# <Title>

> <One-line hook — this becomes the lesson's summary on the site>

**Type:** <Learn | Build>
**Languages:** <comma-list matching the files in code/, or "—" for a Learn lesson>
**Prerequisites:** <upstream lesson links, or "none">
**Time:** ~<estimate> minutes

## The Problem
## The Concept        (### sub-headings become the lesson's search keywords)
## Build It           (raw implementation, stdlib only)
## Use It             (the same thing through the production tool)
## Key takeaways
```

The first `>` blockquote is extracted as the site summary. `###` headings are indexed as keywords. Keep both meaningful.

### quiz.json  (the ACTUAL schema the renderer accepts)

A flat JSON array (the renderer also accepts `{ "questions": [ … ] }`):

```json
[
  { "stage": "pre",   "question": "…", "options": ["a","b","c","d"], "correct": 1, "explanation": "…" },
  { "stage": "check", "question": "…", "options": ["a","b","c","d"], "correct": 0, "explanation": "…" },
  { "stage": "post",  "question": "…", "options": ["a","b","c","d"], "correct": 2, "explanation": "…" }
]
```

- `correct` is **zero-indexed**. `stage` is `pre` | `check` | `post`; the site renders each stage as its own section.
- Aim for **6 questions (1 pre · 3 check · 2 post)** for a full lesson. `explanation` is required — it teaches on a wrong answer.

### code/

- **Runs end-to-end** on the canonical command (`python file.py`, `go run file.go`, `npx tsx file.ts`, `rustc file.rs && ./file`).
- **Self-terminating.** No infinite stdin loops, no hangs waiting on a missing service; if it needs Postgres/Redis, it reads `DATABASE_URL`/`REDIS_URL` and fails fast with a clear message.
- **4–6 line header comment** citing the lesson's `docs/en.md` path and any RFC/spec sources.
- Run it inside the Docker sandbox (`make shell`) so service dependencies are present.

### outputs/

One reusable artifact, filename-prefixed by kind: `prompt-<slug>.md`, `runbook-<slug>.md`, or `checklist-<slug>.md`. `build.js` discovers `prompt-*` today; add new prefixes to `VALID_TYPES` in `build.js` if you introduce one.

---

## You handle vs. the build handles

**You handle when adding/completing a lesson:**

| Surface                      | When                                                                 |
|------------------------------|----------------------------------------------------------------------|
| `README.md` lesson-link row  | Adding a lesson — link `[Title](phases/NN-phase/MM-lesson/)`. Without the link, `build.js` can't derive the URL and the lesson stays "planned". |
| `ROADMAP.md` status          | Marking a lesson ✅ complete / 🚧 in-progress / ⬚ planned.            |
| `glossary/terms.md`          | Introducing a term used by more than one lesson.                     |

**The build handles (leave it):** `site/data.js`, `site/sitemap.xml`, `site/llms.txt`, `site/build-meta.js` — all regenerated by `node site/build.js`.

---

## Local validation before a PR

```bash
node site/build.js                 # must parse cleanly; check the printed Stats
make up                            # start the sandbox (app + postgres + redis)
make run FILE=phases/NN-phase/MM-lesson/code/main.py   # the lesson runs & exits 0
# preview: python3 -m http.server 8099 --directory .  ->  http://localhost:8099/site/lesson.html?path=phases/NN-phase/MM-lesson
```

`site/data.js` regenerates from the lesson folders — never hand-edit it.

---

Last reviewed: 2026-07-17.
