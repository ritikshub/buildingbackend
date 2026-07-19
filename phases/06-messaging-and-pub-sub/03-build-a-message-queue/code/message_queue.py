#!/usr/bin/env python3
"""
Build a message queue: durability, atomic claim, leases and acknowledgement.

Companion to phases/06-messaging-and-pub-sub/03-build-a-message-queue/docs/en.md.
The on-disk format is a write-ahead log in the sense of Phase 3 Lesson 13:
length-prefixed, CRC32-checksummed records (zlib.crc32) appended before an
operation is acknowledged, and replayed on startup to rebuild memory state.

Deterministic: every RNG is seeded and time is a virtual clock, so two runs print
identical output apart from the two throughput lines in section 9, which measure
your disk. Standard library only:  python message_queue.py
"""

from __future__ import annotations

import heapq
import json
import os
import random
import shutil
import struct
import tempfile
import threading
import time
import zlib
from collections import Counter, deque
from dataclasses import dataclass, field

SEED = 20260718
HEADER = struct.Struct("<II")          # u32 payload length, u32 CRC32 of payload
MAX_RECORD = 1 << 20                   # sanity bound: a length larger than this is garbage

READY, IN_FLIGHT, DONE = "ready", "in_flight", "done"


# ── the virtual clock ────────────────────────────────────────────────────────

class Clock:
    """Time the queue can see. Never time.sleep() in a simulation you want to
    finish, or to reproduce."""

    def __init__(self) -> None:
        self.now = 0.0

    def advance(self, dt: float) -> float:
        self.now = round(self.now + dt, 6)
        return self.now


# ── the record framing ───────────────────────────────────────────────────────

def frame(payload: bytes) -> bytes:
    """[u32 length][u32 crc32][payload] — the whole on-disk format."""
    return HEADER.pack(len(payload), zlib.crc32(payload)) + payload


def scan_log(path: str) -> tuple[list[dict], int, str | None]:
    """Read every intact record. Returns (records, bytes_of_good_prefix, damage).

    A crash can leave a half-written record at the tail, and a bad disk can flip
    a bit anywhere. Both are detected here, and neither is allowed to poison the
    records that came before: recovery keeps the good prefix and stops.
    """
    with open(path, "rb") as f:
        data = f.read()
    recs: list[dict] = []
    off = 0
    while off < len(data):
        if len(data) - off < HEADER.size:
            return recs, off, f"torn header: {len(data) - off} of {HEADER.size} bytes at offset {off}"
        n, crc = HEADER.unpack_from(data, off)
        body = off + HEADER.size
        if n > MAX_RECORD:
            return recs, off, f"implausible length {n} at offset {off}"
        if len(data) - body < n:
            return recs, off, f"torn payload: {len(data) - body} of {n} bytes at offset {off}"
        payload = data[body:body + n]
        if zlib.crc32(payload) != crc:
            return recs, off, f"CRC mismatch at offset {off} (record {len(recs)})"
        recs.append(json.loads(payload))
        off = body + n
    return recs, off, None


# ── the message ──────────────────────────────────────────────────────────────

@dataclass
class Message:
    id: str
    body: str
    enqueued_at: float
    state: str = READY
    owner: str | None = None
    lease_until: float = 0.0
    deliveries: int = 0            # SQS calls this ApproximateReceiveCount
    epoch: int = 0                 # bumped on every transition; invalidates heap entries


# ── the queue ────────────────────────────────────────────────────────────────

class DurableQueue:
    """A point-to-point queue: every message is claimed by exactly one consumer.

    mode="at_least_once"  claim makes the message invisible for lease_secs; only
                          an ack removes it. A crashed consumer's message comes
                          back. Duplicates are possible.
    mode="at_most_once"   claim deletes. Nothing ever comes back. Work is lost
                          silently when a consumer dies.
    """

    def __init__(self, path: str, clock: Clock, fsync: bool = True,
                 mode: str = "at_least_once") -> None:
        self.path, self.clock, self.fsync, self.mode = path, clock, fsync, mode
        self._lock = threading.Lock()
        self.msgs: dict[str, Message] = {}
        self.order: list[str] = []             # enqueue order, for compaction
        self.ready: deque[str] = deque()
        self.leases: list[tuple[float, str, int]] = []   # min-heap (deadline, id, epoch)
        self.seq = 0
        self.stats: Counter[str] = Counter()
        self.damage: str | None = None
        self.replayed = 0
        self.expiries: list[tuple[float, str]] = []      # (when, id), for the timeline

        if os.path.exists(path):
            self._replay()
        self._f = open(path, "ab", buffering=0)

    # -- durability ----------------------------------------------------------

    def _append(self, rec: dict) -> None:
        self._f.write(frame(json.dumps(rec, separators=(",", ":"), sort_keys=True).encode()))
        if self.fsync:
            os.fsync(self._f.fileno())         # the write is not durable until this returns
        self.stats["records_written"] += 1

    def _replay(self) -> None:
        recs, good, damage = scan_log(self.path)
        self.damage, self.replayed = damage, len(recs)
        for r in recs:
            op, mid = r["o"], r["id"]
            if op == "put":
                self.msgs[mid] = Message(mid, r["b"], r["t"])
                self.order.append(mid)
                self.seq = max(self.seq, int(mid.split("-")[1]))
            elif (m := self.msgs.get(mid)) is None:
                continue
            elif op == "clm":
                m.state, m.owner, m.lease_until, m.deliveries = IN_FLIGHT, r["c"], r["u"], r["n"]
            elif op == "ext":
                m.lease_until = r["u"]
            elif op == "ack":
                m.state, m.owner = DONE, None
            elif op == "nak":
                m.state, m.owner = READY, None
        # Rebuild the derived state. Anything that can be recomputed is not logged.
        for mid in self.order:
            m = self.msgs[mid]
            if m.state == READY:
                self.ready.append(mid)
            elif m.state == IN_FLIGHT:
                heapq.heappush(self.leases, (m.lease_until, mid, m.epoch))
        self._expire_locked()                  # leases that lapsed while we were down
        self.expiries.clear()
        if damage:
            os.truncate(self.path, good)       # drop the unusable tail, keep the good prefix

    # -- operations ----------------------------------------------------------

    def enqueue(self, body: str) -> str:
        with self._lock:
            self.seq += 1
            mid = f"m-{self.seq:04d}"
            self._append({"o": "put", "id": mid, "b": body, "t": round(self.clock.now, 3)})
            self.msgs[mid] = Message(mid, body, self.clock.now)
            self.order.append(mid)
            self.ready.append(mid)
            self.stats["enqueued"] += 1
            return mid

    def _expire_locked(self) -> list[str]:
        """Any lease whose deadline has passed makes its message visible again."""
        back = []
        while self.leases and self.leases[0][0] <= self.clock.now:
            _, mid, epoch = heapq.heappop(self.leases)
            m = self.msgs[mid]
            if m.state != IN_FLIGHT or m.epoch != epoch:
                continue                       # stale heap entry; the message moved on
            m.state, m.owner, m.epoch = READY, None, m.epoch + 1
            self.ready.append(mid)             # back of the queue, not the front
            self.stats["lease_expired"] += 1
            # how many messages it now has to wait behind: that, plus the lease,
            # is the real redelivery latency.
            self.expiries.append((self.clock.now, mid, len(self.ready) - 1))
            back.append(mid)
        return back

    def claim(self, consumer: str, lease_secs: float, prefetch: int = 1) -> list[Message]:
        """Atomically take up to `prefetch` messages. The lock is the whole point:
        read-then-write without it delivers one message to two consumers."""
        with self._lock:
            self._expire_locked()
            out: list[Message] = []
            while self.ready and len(out) < prefetch:
                mid = self.ready.popleft()
                m = self.msgs[mid]
                m.deliveries += 1
                m.owner, m.epoch = consumer, m.epoch + 1
                m.lease_until = round(self.clock.now + lease_secs, 6)
                if self.mode == "at_most_once":
                    m.state = DONE             # delete on read
                    self._append({"o": "ack", "id": mid, "c": consumer})
                else:
                    m.state = IN_FLIGHT
                    heapq.heappush(self.leases, (m.lease_until, mid, m.epoch))
                    self._append({"o": "clm", "id": mid, "c": consumer,
                                  "u": m.lease_until, "n": m.deliveries})
                self.stats["delivered"] += 1
                if m.deliveries > 1:
                    self.stats["redelivered"] += 1
                out.append(m)
            return out

    def ack(self, mid: str, consumer: str) -> bool:
        """Remove the message. Fails if the lease already expired and someone
        else took it — the late worker's result is a duplicate, not a delivery."""
        with self._lock:
            m = self.msgs.get(mid)
            if m is None or m.state != IN_FLIGHT or m.owner != consumer:
                self.stats["ack_rejected"] += 1
                return False
            m.state, m.owner, m.epoch = DONE, None, m.epoch + 1
            self._append({"o": "ack", "id": mid, "c": consumer})
            self.stats["acked"] += 1
            return True

    def nack(self, mid: str, consumer: str) -> bool:
        """Give the message back immediately instead of waiting out the lease."""
        with self._lock:
            m = self.msgs.get(mid)
            if m is None or m.state != IN_FLIGHT or m.owner != consumer:
                return False
            m.state, m.owner, m.epoch = READY, None, m.epoch + 1
            self.ready.append(mid)
            self._append({"o": "nak", "id": mid, "c": consumer})
            self.stats["nacked"] += 1
            return True

    def extend_lease(self, mid: str, consumer: str, extra: float) -> bool:
        """The heartbeat. A job that legitimately runs longer than the lease must
        say so, or the broker will conclude the consumer is dead."""
        with self._lock:
            m = self.msgs.get(mid)
            if m is None or m.state != IN_FLIGHT or m.owner != consumer:
                return False
            m.lease_until, m.epoch = round(self.clock.now + extra, 6), m.epoch + 1
            heapq.heappush(self.leases, (m.lease_until, mid, m.epoch))
            self._append({"o": "ext", "id": mid, "c": consumer, "u": m.lease_until})
            self.stats["lease_extended"] += 1
            return True

    # -- housekeeping --------------------------------------------------------

    def counts(self) -> dict[str, int]:
        c = Counter(m.state for m in self.msgs.values())
        return {"ready": c[READY], "in_flight": c[IN_FLIGHT], "done": c[DONE]}

    @property
    def pending(self) -> int:
        return sum(1 for m in self.msgs.values() if m.state != DONE)

    def compact(self) -> tuple[int, int, int]:
        """Checkpoint: rewrite the log with only the messages that still matter.

        Without this the file grows forever — every ack of a 200-byte message
        costs another record. The swap is os.replace, which is atomic, so a crash
        mid-compaction leaves either the old log or the new one, never a mix.
        """
        with self._lock:
            before = os.path.getsize(self.path)
            live = [mid for mid in self.order if self.msgs[mid].state != DONE]
            tmp = self.path + ".compact"
            with open(tmp, "wb") as f:
                for mid in live:
                    m = self.msgs[mid]
                    f.write(frame(json.dumps(
                        {"o": "put", "id": mid, "b": m.body, "t": round(m.enqueued_at, 3)},
                        separators=(",", ":"), sort_keys=True).encode()))
                    if m.state == IN_FLIGHT:
                        f.write(frame(json.dumps(
                            {"o": "clm", "id": mid, "c": m.owner, "u": m.lease_until,
                             "n": m.deliveries}, separators=(",", ":"), sort_keys=True).encode()))
                f.flush()
                os.fsync(f.fileno())
            self._f.close()
            os.replace(tmp, self.path)
            self._f = open(self.path, "ab", buffering=0)
            self.order = live
            return before, os.path.getsize(self.path), len(live)

    def close(self) -> None:
        self._f.close()


# ── 1. the naive queue ───────────────────────────────────────────────────────

def demo_naive() -> None:
    print("== 1. THE NAIVE QUEUE: three ways `jobs.pop()` loses your work ==")
    jobs = [f"refund order {5000 + i}" for i in range(5)]
    print(f"  jobs = [] with {len(jobs)} refunds queued, in a Python list")

    survivors = []                                   # a restart = a fresh process = a fresh list
    print(f"  (a) process restarts        -> backlog after restart: {len(survivors)} of {len(jobs)}"
          "   the whole queue was in RAM")

    # (b) "take the tail" is two operations: read it, then trim it. Interleave them.
    shared = list(jobs)
    a_got = shared[len(shared) - 1]                  # A reads the tail
    b_got = shared[len(shared) - 1]                  # B reads it too, before A trims
    del shared[len(shared) - 1]                      # A trims the tail
    dropped = shared[len(shared) - 1]
    del shared[len(shared) - 1]                      # B trims -- a job nobody ever saw
    print(f"  (b) two workers pop() at once -> A got {a_got!r}")
    print(f"                                   B got {b_got!r}   <- the same job, refunded twice")
    print(f"                                   {dropped!r} was deleted undelivered; "
          f"{len(shared)} of {len(jobs)} left")

    # (c) delete-on-read plus a crash.
    taken = shared.pop()
    print(f"  (c) worker claims {taken!r}, then crashes mid-refund")
    print(f"      not in the list, not in memory: gone silently, and no error was ever logged")
    print(f"  (d) worker hangs holding a job -> nothing reclaims it; the job is stuck forever")


# ── 2 + 3: the durable log and the atomic claim ──────────────────────────────

def demo_log(dirpath: str) -> None:
    print("\n== 2. THE DURABLE LOG: length + CRC32 + payload, replayed on open ==")
    path = os.path.join(dirpath, "demo.log")
    q = DurableQueue(path, Clock(), fsync=True)
    q.enqueue("refund order 5000")
    q.close()
    raw = open(path, "rb").read()
    n, crc = HEADER.unpack_from(raw, 0)
    print(f"  one enqueue produced {len(raw)} bytes on disk")
    print(f"    header  {raw[:8].hex(' ')}   length={n}  crc32=0x{crc:08x}")
    print(f"    payload {raw[8:].decode()}")
    print(f"  8 bytes of header per record; the CRC is what makes a torn write detectable")


def demo_atomic_claim(dirpath: str) -> None:
    print("\n== 3. ATOMIC CLAIM: 4 threads racing for 400 messages ==")
    q = DurableQueue(os.path.join(dirpath, "race.log"), Clock(), fsync=False)
    for i in range(400):
        q.enqueue(f"job-{i}")
    got: dict[str, list[str]] = {}
    lock = threading.Lock()

    def worker(name: str) -> None:
        mine = []
        while True:
            batch = q.claim(name, lease_secs=1e9, prefetch=1)
            if not batch:
                break
            mine.append(batch[0].id)
        with lock:
            got[name] = mine

    threads = [threading.Thread(target=worker, args=(f"t{i}",)) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    total = sum(len(v) for v in got.values())
    distinct = len({mid for v in got.values() for mid in v})
    print(f"  4 threads claimed {total} messages, {distinct} distinct, "
          f"{total - distinct} delivered twice")
    print(f"  the claim path holds one lock across read-decide-write, so the read-then-write")
    print(f"  race from 1(b) cannot happen -- this is the primitive a broker must provide")
    q.close()


# ── 4. the crash test ────────────────────────────────────────────────────────

N_JOBS = 60
LEASE = 5.0
TICK = 0.25
CRASH_WORKER, CRASH_ON_CLAIM = "w1", 4      # w1 dies the instant it claims its 4th job
HANG_WORKER, HANG_ON_CLAIM = "w3", 3        # w3's 3rd job takes 13s under a 5s lease
HANG_SECS = 13.0


@dataclass
class Worker:
    wid: str
    dead: bool = False
    claimed: int = 0
    completed: int = 0
    holding: list = field(default_factory=list)      # (Message, finish_at)


def run_crash_sim(dirpath: str, mode: str, heartbeat: bool, label: str) -> dict:
    clock = Clock()
    q = DurableQueue(os.path.join(dirpath, f"sim-{label}.log"), clock, fsync=False, mode=mode)
    for i in range(N_JOBS):
        q.enqueue(f"refund order {5000 + i}")
    rnd = random.Random(SEED)
    workers = [Worker(f"w{i}") for i in range(4)]
    duplicates, timeline = 0, []

    while clock.now < 400 and (q.pending or any(w.holding for w in workers)):
        while q.expiries:
            when, mid, behind = q.expiries.pop(0)
            timeline.append((when, f"{mid} lease expired, no ack -> visible again at the "
                                   f"BACK of the queue, behind {behind} messages"))
        for w in workers:
            if w.dead:
                continue
            for held in list(w.holding):
                m, finish_at = held
                if clock.now >= finish_at:
                    w.holding.remove(held)
                    w.completed += 1
                    if mode == "at_most_once":
                        continue               # already deleted at claim; nothing to ack
                    if not q.ack(m.id, w.wid):
                        duplicates += 1
                        timeline.append((clock.now, f"{w.wid} finished {m.id} after "
                                        f"{HANG_SECS:.0f}s -- ack REJECTED, lease long gone: "
                                        f"this refund ran twice"))
            if heartbeat:
                for m, finish_at in w.holding:
                    if m.lease_until - clock.now <= LEASE / 2:
                        q.extend_lease(m.id, w.wid, LEASE)
            if not w.holding:
                for m in q.claim(w.wid, LEASE, prefetch=1):
                    w.claimed += 1
                    if m.deliveries > 1:
                        timeline.append((clock.now, f"{m.id} redelivered to {w.wid} "
                                        f"(delivery #{m.deliveries}) once the backlog drained to it"))
                    if w.wid == CRASH_WORKER and w.claimed == CRASH_ON_CLAIM:
                        w.dead = True
                        timeline.append((clock.now, f"{w.wid} CRASHED holding {m.id} "
                                        f"(its lease runs out at t={m.lease_until:.2f})"))
                        break
                    svc = HANG_SECS if (w.wid == HANG_WORKER and w.claimed == HANG_ON_CLAIM) \
                        else rnd.uniform(0.4, 1.6)
                    if svc == HANG_SECS:
                        timeline.append((clock.now, f"{w.wid} claimed {m.id}, which needs "
                                        f"{svc:.1f}s under a {LEASE:.1f}s lease"))
                    w.holding.append((m, round(clock.now + svc, 6)))
        clock.advance(TICK)

    c = q.counts()
    lost = c["ready"] + c["in_flight"] if mode == "at_least_once" else N_JOBS - sum(
        w.completed for w in workers)
    out = {
        "label": label, "enqueued": q.stats["enqueued"], "delivered": q.stats["delivered"],
        "acked": q.stats["acked"], "redelivered": q.stats["redelivered"],
        "processed": sum(w.completed for w in workers), "duplicates": duplicates,
        "lost": lost, "makespan": clock.now, "timeline": sorted(timeline),
        "per_worker": {w.wid: w.completed for w in workers},
    }
    q.close()
    return out


def demo_crash(dirpath: str) -> None:
    print("\n== 4. THE CRASH TEST: same seed, same failures, three delivery designs ==")
    print(f"  {N_JOBS} refunds, 4 workers, {LEASE:.0f}s lease, prefetch 1")
    print(f"  {CRASH_WORKER} dies the instant it claims its {CRASH_ON_CLAIM}th job; "
          f"{HANG_WORKER}'s {HANG_ON_CLAIM}rd job takes {HANG_SECS:.0f}s")

    runs = [
        run_crash_sim(dirpath, "at_most_once", False, "at-most-once"),
        run_crash_sim(dirpath, "at_least_once", False, "at-least-once"),
        run_crash_sim(dirpath, "at_least_once", True, "at-least-once+hb"),
    ]
    hdr = f"  {'design':<20}{'enqueued':>9}{'delivered':>10}{'acked':>7}{'redelivered':>13}" \
          f"{'processed':>11}{'duplicates':>12}{'LOST':>7}"
    print("\n" + hdr)
    print("  " + "-" * (len(hdr) - 2))
    names = {"at-most-once": "ack on delivery", "at-least-once": "ack after work",
             "at-least-once+hb": "ack after + heartbeat"}
    for r in runs:
        print(f"  {names[r['label']]:<20}{r['enqueued']:>9}{r['delivered']:>10}{r['acked']:>7}"
              f"{r['redelivered']:>13}{r['processed']:>11}{r['duplicates']:>12}{r['lost']:>7}")
    print("  (ack-on-delivery shows 0 acks because there is no ack step: claim deletes)")

    for r in runs:
        print(f"\n  -- {names[r['label']]} ({r['label']}) --")
        for when, text in r["timeline"]:
            print(f"     t={when:6.2f}  {text}")
        if not r["timeline"]:
            print("     (no redelivery: the message was deleted at claim, so nothing came back)")
        print(f"     finished at t={r['makespan']:.2f}s   per worker: "
              + "  ".join(f"{k}={v}" for k, v in r["per_worker"].items()))


# ── 5 + 6: recovery and corruption ───────────────────────────────────────────

def demo_recovery(dirpath: str) -> str:
    print("\n== 5. RECOVERY: reopen the file, replay the log, rebuild the state ==")
    path = os.path.join(dirpath, "recover.log")
    clock = Clock()
    q = DurableQueue(path, clock, fsync=True)
    ids = [q.enqueue(f"refund order {7000 + i}") for i in range(12)]
    for mid in ids[:5]:                              # 5 claimed and acked: really done
        q.claim("w0", LEASE)
        q.ack(mid, "w0")
    clock.advance(1.0)
    q.claim("w0", LEASE, prefetch=3)                 # 3 claimed, leases end at t=6.0
    clock.advance(6.0)                               # w0 never acks; the leases lapse
    q.claim("w2", LEASE, prefetch=7)                 # w2 takes everything, expired ones included
    before = q.counts()
    before_deliveries = {mid: q.msgs[mid].deliveries for mid in ids[5:8]}
    print(f"  before crash: {before}   log {os.path.getsize(path)} bytes, "
          f"{q.stats['records_written']} records, clock t={clock.now:.1f}")
    print(f"  3 were delivered, left unacked, expired, redelivered: {before_deliveries}")
    q.close()                                        # <- pretend this is a SIGKILL

    clock2 = Clock()
    clock2.advance(7.0)                              # the broker restarts at the same instant
    q2 = DurableQueue(path, clock2, fsync=True)
    print(f"  after replay: {q2.counts()}   replayed {q2.replayed} records, damage={q2.damage}")
    print(f"  state matches: {q2.counts() == before}   "
          f"delivery counts survived: {q2.msgs[ids[5]].deliveries == 2}"
          "   (this is SQS's ApproximateReceiveCount)")
    clock2.advance(6.0)                              # walk past the restored leases
    q2.claim("w9", LEASE, prefetch=0)                # a claim of zero still runs lease expiry
    print(f"  t={clock2.now:.1f}, restored leases lapse: {q2.counts()}"
          f"  -> {q2.stats['lease_expired']} visible again")
    print(f"  nothing was lost across the restart: "
          f"{q2.counts()['ready'] + q2.counts()['in_flight'] + q2.counts()['done']} of "
          f"{len(ids)} messages accounted for")
    q2.close()
    return path


def demo_corruption(dirpath: str, path: str) -> None:
    print("\n== 6. TORN AND CORRUPT RECORDS: what the CRC is for ==")
    good_records, good_bytes, _ = scan_log(path)
    print(f"  intact log: {len(good_records)} records, {good_bytes} bytes")

    torn = os.path.join(dirpath, "torn.log")
    shutil.copy(path, torn)
    with open(torn, "ab") as f:                      # power cut halfway through an append
        f.write(HEADER.pack(96, 0xDEADBEEF) + b'{"o":"put","id":"m-0013"')
    recs, ok, damage = scan_log(torn)
    print(f"  torn write appended 32 bytes of a 104-byte record")
    print(f"    scan stopped: {damage}")
    print(f"    kept {len(recs)} records ({ok} bytes), discarded the tail")
    q = DurableQueue(torn, Clock(), fsync=True)
    print(f"    reopened: {q.counts()}   file truncated to {os.path.getsize(torn)} bytes")
    q.enqueue("refund order 7099")
    print(f"    and it still accepts writes: {q.counts()}")
    q.close()

    rot = os.path.join(dirpath, "rot.log")
    shutil.copy(path, rot)
    data = bytearray(open(rot, "rb").read())
    data[good_bytes - 6] ^= 0x20                     # one bit flip in the last payload
    open(rot, "wb").write(bytes(data))
    recs2, ok2, damage2 = scan_log(rot)
    print(f"  bit rot: one byte flipped inside the last record's payload")
    print(f"    scan stopped: {damage2}")
    print(f"    kept {len(recs2)} of {len(good_records)} records -- length alone would not "
          f"have caught this")


# ── 7. compaction ────────────────────────────────────────────────────────────

def demo_compaction(dirpath: str) -> None:
    print("\n== 7. COMPACTION: stopping the log growing forever ==")
    clock = Clock()
    q = DurableQueue(os.path.join(dirpath, "compact.log"), clock, fsync=False)
    for i in range(2000):
        q.enqueue(f"refund order {9000 + i}")
    for _ in range(1900):                            # churn: claim and ack most of them
        for m in q.claim("w0", LEASE):
            q.ack(m.id, "w0")
        clock.advance(0.01)
    q.claim("w0", LEASE, prefetch=5)                 # leave 5 in flight, 95 ready
    pre = q.counts()
    before, after, live = q.compact()
    print(f"  2,000 enqueued, 1,900 claimed and acked -> {pre}")
    print(f"  log before compaction {before:>9,} bytes  ({q.stats['records_written']:,} records)")
    print(f"  log after  compaction {after:>9,} bytes  "
          f"({after / before * 100:.1f}% -- {before / after:.0f}x smaller)")
    q.close()
    q2 = DurableQueue(os.path.join(dirpath, "compact.log"), clock, fsync=False)
    print(f"  reopened from the checkpoint: {q2.counts()}"
          f"   replayed {q2.replayed} records, not {q.stats['records_written']:,}")
    q2.close()


# ── 8. prefetch ──────────────────────────────────────────────────────────────

def run_prefetch(dirpath: str, prefetch: int) -> tuple[float, dict[str, int]]:
    """One consumer is 6x slower than the others. Long lease so redelivery does
    not confuse the measurement — this isolates the fairness effect."""
    clock = Clock()
    q = DurableQueue(os.path.join(dirpath, f"pf-{prefetch}.log"), clock, fsync=False)
    for i in range(120):
        q.enqueue(f"job-{i}")
    workers = [Worker(f"w{i}") for i in range(4)]
    speed = {"w0": 0.5, "w1": 0.5, "w2": 0.5, "w3": 3.0}
    while clock.now < 500 and (q.pending or any(w.holding for w in workers)):
        for w in workers:
            for held in list(w.holding):
                m, finish_at = held
                if clock.now >= finish_at:
                    w.holding.remove(held)
                    w.completed += 1
                    q.ack(m.id, w.wid)
            if not w.holding:
                for m in q.claim(w.wid, 1e9, prefetch=prefetch):
                    w.holding.append((m, 0.0))
                # a consumer works its batch one at a time, in order
                for i, (m, _) in enumerate(w.holding):
                    w.holding[i] = (m, round(clock.now + speed[w.wid] * (i + 1), 6))
        clock.advance(0.25)
    q.close()
    return clock.now, {w.wid: w.completed for w in workers}


def demo_prefetch(dirpath: str) -> None:
    print("\n== 8. PREFETCH: the fairness cost of claiming in bulk ==")
    print("  120 jobs, 4 consumers; w0-w2 take 0.5s per job, w3 takes 3.0s (6x slower)")
    for pf in (1, 16):
        span, per = run_prefetch(dirpath, pf)
        print(f"  prefetch {pf:>2}: all work done at t={span:6.2f}s   "
              + "  ".join(f"{k}={v:>3}" for k, v in per.items()))
    print("  a big prefetch lets the slowest consumer hoard work the fast ones could have done")


# ── 9. the cost of fsync ─────────────────────────────────────────────────────

def demo_fsync(dirpath: str, n: int = 3000) -> None:
    print("\n== 9. THE COST OF fsync (the only machine-dependent numbers here) ==")
    results = {}
    for do_fsync in (True, False):
        path = os.path.join(dirpath, f"bench-{do_fsync}.log")
        q = DurableQueue(path, Clock(), fsync=do_fsync)
        t0 = time.perf_counter()
        for i in range(n):
            q.enqueue(f"refund order {i}")
        dt = time.perf_counter() - t0
        q.close()
        results[do_fsync] = (n / dt, dt / n * 1e6)
    for do_fsync in (True, False):
        rate, us = results[do_fsync]
        tag = "fsync per enqueue  (durable)" if do_fsync else "OS page cache only (fast, lossy)"
        print(f"  {tag:<34} {rate:>10,.0f} msg/s   {us:>8.1f} us/msg")
    print(f"  durability costs {results[False][0] / results[True][0]:.1f}x throughput -- which is "
          "why real brokers batch the fsync across many messages")
    print("  caveat: on macOS os.fsync() does not flush the drive's own write")
    print("  cache -- only F_FULLFSYNC does, and it is slower still")


# ── main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    dirpath = tempfile.mkdtemp(prefix="mq-")
    try:
        demo_naive()
        demo_log(dirpath)
        demo_atomic_claim(dirpath)
        demo_crash(dirpath)
        path = demo_recovery(dirpath)
        demo_corruption(dirpath, path)
        demo_compaction(dirpath)
        demo_prefetch(dirpath)
        demo_fsync(dirpath)
    finally:
        shutil.rmtree(dirpath, ignore_errors=True)


if __name__ == "__main__":
    main()
