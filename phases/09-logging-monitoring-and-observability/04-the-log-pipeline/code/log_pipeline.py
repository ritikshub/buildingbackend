#!/usr/bin/env python3
"""
A complete log pipeline, simulated end to end — and priced.

Companion to docs/en.md (Phase 10, Lesson 04 - The Log Pipeline). Every stage a
real logging stack has, built small enough to read in one sitting:

  EMIT    an app writes structured events to stdout at a fixed rate.
  COLLECT an agent tails the stream and ENRICHES it with the platform labels
          the app cannot know (pod, node, namespace).
  SHIP    a BOUNDED buffer batches to a backend that is sometimes slow. When it
          fills, the pipeline must be lossy: drop the LOWEST severity first,
          ship the highest first, and never block the producer.
  SAMPLE  error-biased head sampling - keep 100% of errors and slow requests,
          a few percent of routine traffic, and record the sample rate on every
          kept event so population counts can be reconstructed.
  STORE   the same corpus in two storage models side by side: an inverted index
          over every token (Elasticsearch's design) and a label-indexed
          compressed chunk store (Grafana Loki's design).
  QUERY   one LogQL-flavoured query against both, measuring bytes read.
  BILL    bytes/day -> GB/month -> dollars, for raw, sampled and tiered.

Deterministic: `random` is seeded and the clock is virtual, so every run prints
exactly the same numbers.

Runs on the Python standard library only:  python log_pipeline.py
"""

from __future__ import annotations

import json
import random
import zlib
from collections import deque
from dataclasses import dataclass, field

SEED = 1729
BASE_TS = 1_700_000_000.0        # fixed epoch so output never drifts
RATE_PER_SEC = 2_000             # events per second the app emits
N_EVENTS = 12_000                # 6 seconds of traffic
DEGRADED = (2.0, 4.5)            # backend is slow during this window
BURST = (2.5, 3.5)               # ...and errors spike inside it. Of course they do.

LEVELS = ["debug", "info", "warn", "error"]          # ordered low -> high severity
SEVERITY = {lvl: (i + 1) * 10 for i, lvl in enumerate(LEVELS)}


# ─── Stage 1: the emitter — an app writing structured events ─────────────────

@dataclass
class Event:
    ts: float
    level: str
    service: str
    route: str
    method: str
    status: int
    duration_ms: float
    trace_id: str
    span_id: str
    user_id: str
    remote_ip: str
    user_agent: str
    bytes_out: int
    msg: str
    labels: dict[str, str] = field(default_factory=dict)   # added by the agent
    sample_rate: float = 1.0                               # added by the sampler

    def to_json(self) -> str:
        d = {k: v for k, v in self.__dict__.items() if k != "labels"}
        d["ts"], d["duration_ms"] = round(self.ts, 3), round(self.duration_ms, 2)
        d.update(self.labels)
        return json.dumps(d, sort_keys=True, separators=(",", ":"))


SERVICES = {
    "checkout-api": ["/checkout", "/checkout/confirm"],
    "cart-api": ["/cart", "/cart/items"],
    "search-api": ["/search", "/search/suggest"],
}
MESSAGES = {
    "debug": ["cache lookup hit", "config snapshot reloaded", "span exported to collector"],
    "info": ["request completed", "order created", "session token refreshed"],
    "warn": ["retry scheduled after upstream 503", "slow query detected", "rate limit at 80 percent"],
    "error": ["connection pool exhausted", "upstream timeout contacting bank", "payment declined by issuer"],
}
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0 Safari/537.36"


def _pick_level(rnd: random.Random, t: float) -> str:
    r = rnd.random()
    if BURST[0] <= t < BURST[1]:                      # the error burst
        return "error" if r < 0.45 else "warn" if r < 0.60 else "info" if r < 0.95 else "debug"
    return "debug" if r < 0.25 else "info" if r < 0.90 else "warn" if r < 0.97 else "error"


def emit(n: int) -> list[Event]:
    """Produce n structured events on a virtual clock at RATE_PER_SEC."""
    rnd = random.Random(SEED)
    out: list[Event] = []
    for i in range(n):
        t = i / RATE_PER_SEC
        level = _pick_level(rnd, t)
        service = rnd.choice(list(SERVICES))
        route = rnd.choice(SERVICES[service])
        slow = rnd.random() < 0.01                    # 1% long tail
        dur = rnd.uniform(1200, 9000) if slow else rnd.uniform(8, 240)
        out.append(Event(
            ts=BASE_TS + t, level=level, service=service, route=route,
            method="POST" if route.endswith(("confirm", "items")) else "GET",
            status=500 if level == "error" else 200,
            duration_ms=dur,
            trace_id="%032x" % rnd.getrandbits(128),
            span_id="%016x" % rnd.getrandbits(64),
            user_id="u_%05d" % rnd.randrange(50_000),
            remote_ip="10.%d.%d.%d" % (rnd.randrange(256), rnd.randrange(256), rnd.randrange(256)),
            user_agent=UA, bytes_out=rnd.randrange(200, 40_000),
            msg=rnd.choice(MESSAGES[level]),
        ))
    return out


# ─── Stage 2: the agent — enrich with platform labels the app cannot know ────

def enrich(events: list[Event]) -> list[Event]:
    """What Fluent Bit's kubernetes filter does: attach pod/node/namespace."""
    rnd = random.Random(SEED + 1)
    for ev in events:
        ordinal = rnd.randrange(4)
        ev.labels = {
            "k8s_namespace": "prod",
            "k8s_pod": f"{ev.service}-7d9f4b-{ordinal}",
            "k8s_node": f"ip-10-0-{ordinal}-17.ec2.internal",
            "cluster": "eu-west-1a",
            "version": "2.14.3",
        }
    return events


# ─── Stage 3: the shipper — bounded buffer, batching, and the drop decision ──

@dataclass
class ShipStats:
    shipped: int = 0
    batches: int = 0
    peak_queue: int = 0
    dropped: dict[str, int] = field(default_factory=lambda: {lvl: 0 for lvl in LEVELS})

    @property
    def total_dropped(self) -> int:
        return sum(self.dropped.values())


class BoundedShipper:
    """A severity-tiered bounded buffer.

    Full buffer -> evict the lowest-severity event to make room for a
    higher-severity one; if the arrival is itself the lowest, drop the arrival.
    Draining always takes the highest severity first. Blocking the producer is
    never an option: that stalls the service the logs exist to observe.
    """

    def __init__(self, capacity: int, batch_size: int, flush_interval: float, latency):
        self.capacity, self.batch_size = capacity, batch_size
        self.flush_interval, self.latency = flush_interval, latency
        self.q: dict[str, deque[Event]] = {lvl: deque() for lvl in LEVELS}
        self.n = 0
        self.busy_until = 0.0
        self.last_flush = 0.0
        self.stats = ShipStats()

    def offer(self, ev: Event) -> None:
        if self.n >= self.capacity:
            victim = next((lvl for lvl in LEVELS if self.q[lvl]), None)
            if victim is not None and SEVERITY[victim] < SEVERITY[ev.level]:
                self.q[victim].popleft()
                self.n -= 1
                self.stats.dropped[victim] += 1
            else:
                self.stats.dropped[ev.level] += 1       # the arrival is the least valuable
                return
        self.q[ev.level].append(ev)
        self.n += 1
        self.stats.peak_queue = max(self.stats.peak_queue, self.n)

    def pump(self, now: float, sink, force: bool = False) -> None:
        if now < self.busy_until or self.n == 0:
            return
        if not (force or self.n >= self.batch_size or now - self.last_flush >= self.flush_interval):
            return
        batch: list[Event] = []
        for lvl in reversed(LEVELS):                    # errors leave the buffer first
            while self.q[lvl] and len(batch) < self.batch_size:
                batch.append(self.q[lvl].popleft())
                self.n -= 1
        sink(batch)
        self.stats.shipped += len(batch)
        self.stats.batches += 1
        self.busy_until = now + self.latency(now)
        self.last_flush = now


def backend_latency(now: float) -> float:
    """Seconds to accept one batch. The backend degrades under load."""
    return 1.0 if DEGRADED[0] <= now < DEGRADED[1] else 0.05


def run_shipper(events: list[Event], capacity: int = 2_000, batch_size: int = 500) -> tuple[list[Event], ShipStats]:
    shipper = BoundedShipper(capacity, batch_size, flush_interval=0.25, latency=backend_latency)
    received: list[Event] = []
    sink = received.extend
    now = 0.0
    for ev in events:
        now = ev.ts - BASE_TS
        shipper.pump(now, sink)
        shipper.offer(ev)
    while shipper.n:                                    # drain on shutdown
        now = max(now, shipper.busy_until)
        shipper.pump(now, sink, force=True)
    return received, shipper.stats


# ─── Stage 4: the sampler — error-biased, with the rate recorded ─────────────

def sample(events: list[Event], info_rate: float = 0.05, debug_rate: float = 0.01) -> list[Event]:
    """Keep every error, warning and slow request; a few percent of the rest."""
    rnd = random.Random(SEED + 2)
    kept: list[Event] = []
    for ev in events:
        if ev.level in ("warn", "error") or ev.duration_ms >= 1000:
            rate = 1.0
        else:
            rate = debug_rate if ev.level == "debug" else info_rate
        if rate >= 1.0 or rnd.random() < rate:
            copy = Event(**{**ev.__dict__, "sample_rate": rate})
            kept.append(copy)
    return kept


def estimate(kept: list[Event], predicate) -> float:
    """Reconstruct a population count from sampled events: sum of 1/sample_rate."""
    return sum(1.0 / ev.sample_rate for ev in kept if predicate(ev))


# ─── Stage 5a: storage model A — index every token (Elasticsearch's bet) ─────

def tokenize(line: str) -> set[str]:
    """field:token pairs, the way an analyzed inverted index sees a document."""
    doc = json.loads(line)
    terms = set()
    for k, v in doc.items():
        for tok in str(v).lower().replace("/", " ").replace(",", " ").split():
            terms.add(f"{k}:{tok}")
    return terms


class InvertedIndexStore:
    """Inverted index over every field + compressed stored documents."""

    BLOCK = 32                                         # docs per compressed block (~18 KB raw)

    def __init__(self) -> None:
        self.postings: dict[str, list[int]] = {}
        self.blocks: list[bytes] = []
        self.block_raw: list[int] = []
        self._pending: list[str] = []
        self.docs = 0

    def add(self, line: str) -> None:
        doc_id = self.docs
        for term in tokenize(line):
            self.postings.setdefault(term, []).append(doc_id)
        self._pending.append(line)
        self.docs += 1
        if len(self._pending) >= self.BLOCK:
            self._seal()

    def _seal(self) -> None:
        if not self._pending:
            return
        raw = "\n".join(self._pending).encode()
        self.blocks.append(zlib.compress(raw, 6))
        self.block_raw.append(len(raw))
        self._pending = []

    def close(self) -> None:
        self._seal()

    @property
    def index_bytes(self) -> int:
        # term dictionary entry (term text + 8 bytes of pointers) + 4 bytes per posting.
        # A floor: real engines also store positions, norms and doc values.
        return sum(len(t) + 8 for t in self.postings) + 4 * sum(len(p) for p in self.postings.values())

    @property
    def stored_bytes(self) -> int:
        return sum(len(b) for b in self.blocks)

    def query(self, terms: list[str], line_filter: str) -> tuple[int, int, int]:
        """AND the posting lists, then fetch only the blocks holding hits.

        Returns (hits, index bytes read, body bytes read). Counting matches
        touches only the index; showing the log lines costs the second number.
        """
        index_read = sum(len(t) + 8 + 4 * len(self.postings.get(t, [])) for t in terms)
        ids: set[int] | None = None
        for t in terms:
            p = set(self.postings.get(t, []))
            ids = p if ids is None else (ids & p)
        ids = ids or set()
        body_read = sum(self.block_raw[b] for b in {i // self.BLOCK for i in ids})
        hits = 0
        for i in sorted(ids):
            raw = zlib.decompress(self.blocks[i // self.BLOCK]).decode().split("\n")
            if line_filter in raw[i % self.BLOCK]:
                hits += 1
        return hits, index_read, body_read


# ─── Stage 5b: storage model B — index labels only (Loki's bet) ──────────────

class LabelStreamStore:
    """Index a small label set; store bodies as compressed per-stream chunks."""

    CHUNK_LINES = 500

    def __init__(self, label_keys: list[str]) -> None:
        self.label_keys = label_keys
        self.streams: dict[str, list[bytes]] = {}
        self.raw_sizes: dict[str, list[int]] = {}
        self._pending: dict[str, list[str]] = {}

    def _key(self, doc: dict) -> str:
        return ",".join(f'{k}="{doc.get(k)}"' for k in self.label_keys)

    def add(self, line: str) -> None:
        key = self._key(json.loads(line))
        buf = self._pending.setdefault(key, [])
        buf.append(line)
        if len(buf) >= self.CHUNK_LINES:
            self._seal(key)

    def _seal(self, key: str) -> None:
        buf = self._pending.get(key)
        if not buf:
            return
        raw = "\n".join(buf).encode()
        self.streams.setdefault(key, []).append(zlib.compress(raw, 6))
        self.raw_sizes.setdefault(key, []).append(len(raw))
        self._pending[key] = []

    def close(self) -> None:
        for key in list(self._pending):
            self._seal(key)

    @property
    def n_streams(self) -> int:
        return len(self.streams)

    @property
    def n_chunks(self) -> int:
        return sum(len(c) for c in self.streams.values())

    @property
    def index_bytes(self) -> int:
        # the label set text once per stream + 24 bytes of chunk metadata
        # (min ts, max ts, object-store offset) per chunk. That is the whole index.
        return sum(len(k) + 24 * len(self.streams[k]) for k in self.streams)

    @property
    def stored_bytes(self) -> int:
        return sum(len(c) for chunks in self.streams.values() for c in chunks)

    def query(self, selector: dict[str, str], line_filter: str) -> tuple[int, int]:
        """Select streams by label, then brute-force scan their chunks."""
        hits, scanned = 0, 0
        for key, chunks in self.streams.items():
            if not all(f'{k}="{v}"' in key for k, v in selector.items()):
                continue
            for ci, chunk in enumerate(chunks):
                scanned += self.raw_sizes[key][ci]
                for line in zlib.decompress(chunk).decode().split("\n"):
                    if line_filter in line:
                        hits += 1
        return hits, scanned


# ─── Stage 6: the bill ───────────────────────────────────────────────────────

GB = 1024 ** 3
PRICE_INGEST_GB = 0.50           # $/GB ingested+indexed  (stated assumption)
PRICE_HOT_GB_MONTH = 0.10        # $/GB/month kept searchable
PRICE_ARCHIVE_GB_MONTH = 0.023   # $/GB/month in object storage


def monthly_cost(bytes_per_day: float, hot_days: int, archive_days: int = 0) -> dict[str, float]:
    gb_day = bytes_per_day / GB
    ingest = gb_day * 30 * PRICE_INGEST_GB
    hot = gb_day * hot_days * PRICE_HOT_GB_MONTH
    archive = gb_day * archive_days * PRICE_ARCHIVE_GB_MONTH
    total = ingest + hot + archive
    return {"gb_day": gb_day, "ingest": ingest, "hot": hot,
            "archive": archive, "total": total, "year": total * 12}


def show_cost(name: str, c: dict[str, float], baseline: float | None = None) -> None:
    saved = "" if baseline is None else f"   saves {100 * (1 - c['total'] / baseline):5.1f}%"
    print(f"  {name:<22} {c['gb_day']:8.1f} GB/day   ingest ${c['ingest']:9,.0f}"
          f"   store ${c['hot'] + c['archive']:8,.0f}   = ${c['total']:9,.0f}/mo"
          f"  (${c['year']:11,.0f}/yr){saved}")


# ─── main ────────────────────────────────────────────────────────────────────

def main() -> None:
    print("== 1. EMIT + ENRICH ==")
    events = enrich(emit(N_EVENTS))
    lines = [ev.to_json() for ev in events]
    raw_bytes = sum(len(l) + 1 for l in lines)         # +1: the newline on stdout
    by_level = {lvl: sum(1 for e in events if e.level == lvl) for lvl in LEVELS}
    print(f"  emitted {len(events):,} events at {RATE_PER_SEC:,}/s over {N_EVENTS / RATE_PER_SEC:.1f}s")
    print(f"  levels: " + "  ".join(f"{k}={v:,}" for k, v in by_level.items()))
    print(f"  agent enriched with 5 platform labels the app never knew (k8s_pod, k8s_node, ...)")
    print(f"  raw JSON {raw_bytes:,} bytes, avg {raw_bytes / len(events):.0f} bytes/event")

    print("\n== 2. SHIP: bounded buffer, slow backend, and the drop decision ==")
    _, st = run_shipper(events)
    print(f"  buffer capacity 2,000 events   batch 500   backend 50ms/batch, 1000ms while degraded")
    print(f"  shipped {st.shipped:,} in {st.batches} batches   peak queue {st.peak_queue:,}")
    print(f"  dropped {st.total_dropped:,} ({100 * st.total_dropped / len(events):.1f}%) by level: "
          + "  ".join(f"{k}={v:,}" for k, v in st.dropped.items())
          + "   <- cheapest events spent first")

    print("\n== 3. SAMPLE: error-biased, with the rate recorded on every event ==")
    kept = sample(events)
    kept_bytes = sum(len(e.to_json()) + 1 for e in kept)
    print(f"  policy: error/warn/slow=100%   info=5%   debug=1%")
    print(f"  kept {len(kept):,} of {len(events):,} events ({100 * len(kept) / len(events):.1f}%)"
          f"   {kept_bytes:,} bytes ({100 * kept_bytes / raw_bytes:.1f}% of raw)")
    print(f"  reconstructed from 1/sample_rate weights:")
    for lvl, note in (("error", "kept 100%"), ("info", "sampled 5%"), ("debug", "sampled 1%")):
        true_n = by_level[lvl]
        est_n = estimate(kept, lambda e, L=lvl: e.level == L)
        print(f"    {lvl:<6} true {true_n:>6,}   estimated {est_n:>8,.0f}"
              f"   error {100 * abs(est_n - true_n) / true_n:5.2f}%   ({note})")
    est_total = estimate(kept, lambda e: True)
    print(f"    TOTAL  true {len(events):>6,}   estimated {est_total:>8,.0f}"
          f"   error {100 * abs(est_total - len(events)) / len(events):5.2f}%")
    _, st2 = run_shipper(kept)
    print(f"  re-shipping the sampled stream through the same buffer:"
          f" {st2.shipped:,} shipped, {st2.total_dropped} dropped"
          f"  <- sampling is also how you stop dropping")

    print("\n== 4. STORE: index everything vs index labels only ==")
    es = InvertedIndexStore()
    loki = LabelStreamStore(["service", "level", "route"])
    for line in lines:
        es.add(line)
        loki.add(line)
    es.close()
    loki.close()
    es_total, loki_total = es.index_bytes + es.stored_bytes, loki.index_bytes + loki.stored_bytes
    print(f"  corpus: {len(lines):,} events, {raw_bytes:,} bytes of JSON")
    print(f"  inverted index ({len(es.postings):,} terms) index {es.index_bytes:>9,} B"
          f"  bodies {es.stored_bytes:>9,} B  total {es_total:>9,} B  {100 * es_total / raw_bytes:5.1f}% of raw")
    print(f"  label streams  ({loki.n_streams} streams)   index {loki.index_bytes:>9,} B"
          f"  bodies {loki.stored_bytes:>9,} B  total {loki_total:>9,} B  {100 * loki_total / raw_bytes:5.1f}% of raw")
    print(f"  index overhead: {es.index_bytes / loki.index_bytes:,.0f}x     "
          f"total footprint: {es_total / loki_total:.1f}x")

    print("\n== 4b. CARDINALITY: what one trace_id label does to the label store ==")
    bad = LabelStreamStore(["service", "level", "route", "trace_id"])
    for line in lines:
        bad.add(line)
    bad.close()
    bad_total = bad.index_bytes + bad.stored_bytes
    print(f"  good labels (service, level, route):            {loki.n_streams:>7,} streams"
          f"   {loki.n_chunks:>6,} chunks   {loki_total:>9,} B")
    print(f"  + trace_id as a LABEL:                          {bad.n_streams:>7,} streams"
          f"   {bad.n_chunks:>6,} chunks   {bad_total:>9,} B")
    print(f"  one stream per event: index {bad.index_bytes / loki.index_bytes:,.0f}x bigger,"
          f" bodies {bad.stored_bytes / loki.stored_bytes:.1f}x bigger (chunks too small to compress)")

    print("\n== 5. QUERY: the same needle, two engines ==")
    print('  A: {service="checkout-api", level="error"} |= "pool exhausted"')
    es_hits, es_idx, es_body = es.query(
        ["service:checkout-api", "level:error", "msg:pool", "msg:exhausted"], "pool exhausted")
    lk_hits, lk_scan = loki.query({"service": "checkout-api", "level": "error"}, "pool exhausted")
    print(f"  label streams : {lk_hits:>4,} hits   read {lk_scan:>9,} B"
          f"  ({100 * lk_scan / raw_bytes:5.1f}% of corpus)  decompress + grep 2 of 24 streams")
    print(f"  inverted index: {es_hits:>4,} hits   read {es_idx:>9,} B index"
          f" + {es_body:,} B bodies ({100 * (es_idx + es_body) / raw_bytes:.1f}%)")

    needle = json.loads(lines[137])["user_id"]
    print(f'  B: {{}} |= "{needle}"   -- no label selector, one rare token')
    lk_hits2, lk_scan2 = loki.query({}, needle)
    es_hits2, es_idx2, es_body2 = es.query([f"user_id:{needle.lower()}"], needle)
    print(f"  label streams : {lk_hits2:>4,} hits   read {lk_scan2:>9,} B"
          f"  ({100 * lk_scan2 / raw_bytes:5.1f}% of corpus)  brute-force, every stream")
    print(f"  inverted index: {es_hits2:>4,} hits   read {es_idx2:>9,} B index"
          f" + {es_body2:,} B bodies ({100 * (es_idx2 + es_body2) / raw_bytes:.1f}%)")
    print(f"  ratio on this query: label store reads"
          f" {lk_scan2 / (es_idx2 + es_body2):,.0f}x more than the index")

    print("\n== 6. THE BILL: 2,000 events/s, 24x7 ==")
    bytes_day = raw_bytes / len(events) * RATE_PER_SEC * 86_400
    sampled_day = bytes_day * kept_bytes / raw_bytes
    print(f"  at {raw_bytes / len(events):.0f} bytes/event and {RATE_PER_SEC:,} events/s"
          f"  ->  {bytes_day / GB:,.0f} GB/day")
    print(f"  prices: ${PRICE_INGEST_GB:.2f}/GB ingest, ${PRICE_HOT_GB_MONTH:.2f}/GB/mo hot,"
          f" ${PRICE_ARCHIVE_GB_MONTH:.3f}/GB/mo archive")
    raw_c = monthly_cost(bytes_day, hot_days=30)
    smp_c = monthly_cost(sampled_day, hot_days=30)
    tier_c = monthly_cost(sampled_day, hot_days=7, archive_days=83)
    show_cost("raw, 30d hot", raw_c)
    show_cost("sampled, 30d hot", smp_c, raw_c["total"])
    show_cost("sampled, 7d+83d cold", tier_c, raw_c["total"])
    print(f"  annual difference: ${raw_c['year'] - tier_c['year']:,.0f}"
          f"  -- and the 90-day tail is now retained, not deleted")
    prod_gb_day = 1200 * RATE_PER_SEC * 86_400 / GB     # a 1.2 KB production event
    prod_year = (prod_gb_day * 30 * 2.00 + prod_gb_day * 30 * PRICE_HOT_GB_MONTH) * 12
    print(f"  sensitivity: a 1.2 KB production event at $2.00/GB ingest ->"
          f" {prod_gb_day:,.0f} GB/day = ${prod_year:,.0f}/yr for logs alone")


if __name__ == "__main__":
    main()
