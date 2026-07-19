#!/usr/bin/env python3
"""
Property-based testing and fuzzing measured rather than argued: forty hand-written
example tests against three properties over one buggy pagination cursor codec, a
property-testing engine built from scratch (generators, runner, shrinker), what
generator distribution is worth, stateful model-based testing of an LRU cache,
differential testing against a slow oracle, and a coverage-guided byte fuzzer.

Companion to docs/en.md (Phase 12, Lesson 12). Standard library only, every RNG
seeded from random.Random(20260718), no network, no files written,
self-terminating in about ten seconds. Sources: Miller, Fredriksen & So, "An
Empirical Study of the Reliability of UNIX Utilities", CACM 33(12), 1990 (the
original random-fuzz result); Claessen & Hughes, "QuickCheck: A Lightweight Tool
for Random Testing of Haskell Programs", ICFP 2000 (properties and shrinking);
Zeller & Hildebrandt, "Simplifying and Isolating Failure-Inducing Input", IEEE
TSE 28(2), 2002 (delta debugging); Unicode Standard Annex #15, "Unicode
Normalization Forms" (NFC); RFC 4648, "The Base16, Base32, and Base64 Data
Encodings", 2006 (§5, base64url).

Run:  python3 property_testing.py
"""

from __future__ import annotations

import base64
import random
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterator, List, Optional, Sequence, Set, Tuple

SEED = 20260718


def banner(n: int, title: str) -> None:
    print(f"\n== {n} · {title} ==")


def show(value: Any, width: int = 58) -> str:
    """A stable, printable repr. Non-ASCII is escaped so the output is
    byte-identical on any terminal, which the diff-two-runs check needs."""
    text = repr(value)
    text = text.encode("unicode_escape").decode("ascii")
    if len(text) > width:
        text = text[: width - 3] + "..."
    return text


# ══ 0 · THE ENGINE ═══════════════════════════════════════════════════════════
# A property-testing engine is three parts and nothing else: something that
# draws a value, something that runs the property over many drawn values, and
# something that makes a failing value smaller. The third part is the one that
# turns "it broke on 4,000 characters of noise" into a bug report.


@dataclass
class Result:
    """What one `check()` run learned."""

    passed: bool
    cases: int                                     # drawn before the verdict
    failing: Any = None                            # the first failing value
    shrunk: Any = None                             # the minimal failing value
    shrink_evals: int = 0                          # candidates tried while shrinking
    trace: List[Tuple[int, int, Any]] = field(default_factory=list)
    error: str = ""


class Gen:
    """A generator: how to draw a value, and how to make one smaller."""

    def draw(self, rng: random.Random) -> Any:
        raise NotImplementedError

    def candidates(self, value: Any) -> Iterator[Any]:
        """Smaller values to try, most aggressive first. Yielding a value that
        does not reproduce the failure is free — the driver just moves on."""
        return iter(())

    def size(self, value: Any) -> int:
        """The number printed in a shrink trace. Purely cosmetic."""
        try:
            return len(value)
        except TypeError:
            return abs(int(value))


class Ints(Gen):
    """Uniform over [lo, hi]. `pool` is the boundary bias: with probability
    `bias`, draw a known-interesting value instead of a uniform one."""

    def __init__(self, lo: int, hi: int, pool: Sequence[int] = (), bias: float = 0.0):
        self.lo, self.hi, self.pool, self.bias = lo, hi, tuple(pool), bias

    def draw(self, rng: random.Random) -> int:
        if self.pool and rng.random() < self.bias:
            return rng.choice(self.pool)
        return rng.randint(self.lo, self.hi)

    def candidates(self, n: int) -> Iterator[int]:
        """Every candidate is STRICTLY closer to `floor` than `n` is. That
        predicate is what stops the shrinker cycling: without it, 0 offers 1 and
        1 offers 0 and the loop never terminates."""
        floor = min(max(0, self.lo), self.hi)      # the in-range value nearest 0

        def ok(v: int) -> bool:
            return self.lo <= v <= self.hi and abs(v - floor) < abs(n - floor)

        if ok(floor):
            yield floor
        cur = n
        while True:                                # then halve the distance
            nxt = floor + (cur - floor) // 2
            if nxt == cur or not ok(nxt):
                break
            cur = nxt
            yield cur
        for step in (n - 1, n + 1):
            if ok(step):
                yield step


# The codepoint distribution matters enough that it is a named table rather than
# a literal. This is roughly what hypothesis's st.text() reaches for: mostly
# ASCII, with a real tail into the rest of the Basic Multilingual Plane.
ASCII_PRINTABLE = [chr(c) for c in range(0x20, 0x7F)]
INTERESTING_CHARS = (
    [chr(c) for c in range(0x300, 0x370)]          # combining marks
    + ["\x00", "\n", "\t", "\r", "|", "+", "/", "=", "%", "&", "[", "]", " ", "\x1f"]
    + ["Å", "Ω", "ﬁ", "ẛ"]     # singleton/compat decompositions
)


class Text(Gen):
    """Draws a string of exactly/at most `size` characters from a mixed
    codepoint distribution. `plain=True` restricts it to ASCII, which is the
    naive generator that never finds a unicode bug."""

    def __init__(self, max_len: int, exact: bool = False, plain: bool = False):
        self.max_len, self.exact, self.plain = max_len, exact, plain

    def _char(self, rng: random.Random) -> str:
        if self.plain:
            return rng.choice(ASCII_PRINTABLE)
        r = rng.random()
        if r < 0.60:
            return rng.choice(ASCII_PRINTABLE)
        if r < 0.72:
            return chr(rng.randint(0xA0, 0xFF))
        if r < 0.86:
            return rng.choice(INTERESTING_CHARS)
        c = rng.randint(0x100, 0xFFFF)
        while 0xD800 <= c <= 0xDFFF:               # lone surrogates are not text
            c = rng.randint(0x100, 0xFFFF)
        return chr(c)

    def draw(self, rng: random.Random) -> str:
        n = self.max_len if self.exact else rng.randint(0, self.max_len)
        return "".join(self._char(rng) for _ in range(n))

    def candidates(self, s: str) -> Iterator[str]:
        n = len(s)
        block = n
        while block >= 1:                          # delete blocks, largest first
            for i in range(0, n, block):
                cand = s[:i] + s[i + block:]
                if cand != s:
                    yield cand
            block //= 2
        for i, ch in enumerate(s):                 # then simplify each character
            for repl in ("a", "0", " "):
                if repl < ch:
                    yield s[:i] + repl + s[i + 1:]
            half = chr(ord(ch) // 2)
            if half != ch and ord(ch) > 1:
                yield s[:i] + half + s[i + 1:]


class Lists(Gen):
    def __init__(self, elem: Gen, max_size: int, min_size: int = 0):
        self.elem, self.max_size, self.min_size = elem, max_size, min_size

    def draw(self, rng: random.Random) -> List[Any]:
        n = rng.randint(self.min_size, self.max_size)
        return [self.elem.draw(rng) for _ in range(n)]

    def candidates(self, xs: List[Any]) -> Iterator[List[Any]]:
        n = len(xs)
        block = n
        while block >= 1:
            for i in range(0, n, block):
                cand = xs[:i] + xs[i + block:]
                if len(cand) >= self.min_size and cand != xs:
                    yield cand
            block //= 2
        for i, x in enumerate(xs):
            for smaller in self.elem.candidates(x):
                yield xs[:i] + [smaller] + xs[i + 1:]


class Tuples(Gen):
    def __init__(self, *gens: Gen):
        self.gens = gens

    def draw(self, rng: random.Random) -> Tuple[Any, ...]:
        return tuple(g.draw(rng) for g in self.gens)

    def candidates(self, t: Tuple[Any, ...]) -> Iterator[Tuple[Any, ...]]:
        for i, g in enumerate(self.gens):
            for smaller in g.candidates(t[i]):
                yield t[:i] + (smaller,) + t[i + 1:]

    def size(self, t: Tuple[Any, ...]) -> int:
        return sum(g.size(t[i]) for i, g in enumerate(self.gens))


def fails(prop: Callable[[Any], Any], value: Any) -> bool:
    """A property fails if it returns False or raises. Catching the exception is
    the whole "never crashes" property class, for free."""
    try:
        return prop(value) is False
    except Exception:
        return True


def why(prop: Callable[[Any], Any], value: Any) -> str:
    try:
        return "returned False" if prop(value) is False else "passed"
    except Exception as exc:
        return f"{type(exc).__name__}: {exc}"[:70]


def shrink(prop: Callable[[Any], Any], gen: Gen, value: Any,
           limit: int = 20000) -> Tuple[Any, int, List[Tuple[int, int, Any]]]:
    """Greedy fixed point: keep the first candidate that still fails, restart.
    Restarting matters — after a big deletion succeeds, the next big deletion is
    usually available again, so the sequence is roughly a binary search."""
    best, evals = value, 0
    trace = [(0, gen.size(best), best)]
    progress = True
    while progress and evals < limit:
        progress = False
        for cand in gen.candidates(best):
            evals += 1
            if evals >= limit:
                break
            if fails(prop, cand):
                best = cand
                trace.append((evals, gen.size(best), best))
                progress = True
                break
    return best, evals, trace


def check(prop: Callable[[Any], Any], gen: Gen, *, max_examples: int = 200,
          seed: int = SEED, do_shrink: bool = True) -> Result:
    """Draw up to `max_examples` values; stop at the first failure and shrink."""
    rng = random.Random(seed)
    for i in range(1, max_examples + 1):
        value = gen.draw(rng)
        if fails(prop, value):
            if not do_shrink:
                return Result(False, i, value, value, 0, [], why(prop, value))
            small, evals, trace = shrink(prop, gen, value)
            return Result(False, i, value, small, evals, trace, why(prop, small))
    return Result(True, max_examples)


# ══ 1 · THE TARGET: A PAGINATION CURSOR CODEC WITH THREE REAL BUGS ═══════════
# Keyset pagination: the client sends back an opaque cursor naming the last row
# it saw, and the server returns everything after it. Three bugs, each one a
# line that reads as correct.

BUG_ALPHABET = "url alphabet"          # standard base64 (+ and /) in a URL
BUG_NFC = "unicode normalisation"      # encode normalises, decode cannot undo it
BUG_TIE = "tie ordering"               # cursor compares the sort key only

ACTIVE: frozenset = frozenset()
ALL_BUGS = (BUG_ALPHABET, BUG_NFC, BUG_TIE)


def bug(name: str) -> bool:
    return name in ACTIVE


SEP = "\x1f"                            # ASCII unit separator: not a legal key char


def encode_cursor(sort_key: str, row_id: int) -> str:
    """Pack (sort_key, row_id) into one opaque URL-safe token."""
    key = unicodedata.normalize("NFC", sort_key) if bug(BUG_NFC) else sort_key
    payload = f"{key}{SEP}{row_id}".encode("utf-8")
    raw = base64.b64encode(payload) if bug(BUG_ALPHABET) else base64.urlsafe_b64encode(payload)
    return raw.decode("ascii").rstrip("=")


def decode_cursor(token: str) -> Tuple[str, int]:
    padded = token + "=" * (-len(token) % 4)
    data = (base64.b64decode(padded) if bug(BUG_ALPHABET)
            else base64.urlsafe_b64decode(padded))
    text = data.decode("utf-8")
    key, sep, rid = text.rpartition(SEP)
    if not sep:
        raise ValueError("cursor has no separator")
    return key, int(rid)


def through_url(token: str) -> str:
    """What a cursor survives on the way back. A browser form post and
    URLSearchParams both decode "+" as a space (application/x-www-form-urlencoded),
    so a token containing "+" arrives with a space in it."""
    return token.replace("+", " ")


Row = Tuple[str, int]


def page(rows: Sequence[Row], after: Optional[Row], size: int) -> List[Row]:
    ordered = sorted(rows)
    if after is None:
        window = ordered
    elif bug(BUG_TIE):
        window = [r for r in ordered if r[0] > after[0]]
    else:
        window = [r for r in ordered if r > after]
    return window[:size]


def walk_pages(rows: Sequence[Row], size: int) -> List[Row]:
    seen: List[Row] = []
    after: Optional[Row] = None
    for _ in range(len(rows) + 2):
        chunk = page(rows, after, size)
        if not chunk:
            break
        seen.extend(chunk)
        after = chunk[-1]
    return seen


# ── the three properties. Fifteen lines, and they are the whole suite. ────────

def prop_roundtrip(case: Tuple[str, int]) -> bool:
    key, rid = case
    return decode_cursor(encode_cursor(key, rid)) == (key, rid)


def prop_survives_url(case: Tuple[str, int]) -> bool:
    key, rid = case
    return decode_cursor(through_url(encode_cursor(key, rid))) == (key, rid)


def prop_pagination(case: Tuple[List[Row], int]) -> bool:
    rows, size = case
    rows = dedupe_ids(rows)
    return walk_pages(rows, size) == sorted(rows)


def dedupe_ids(rows: Sequence[Row]) -> List[Row]:
    """Row ids are unique in a table; make the generated input obey that."""
    out, used = [], set()
    for key, rid in rows:
        while rid in used:
            rid += 1
        used.add(rid)
        out.append((key, rid))
    return out


# ── the forty hand-written example tests ─────────────────────────────────────
# What a diligent engineer writes without a generator: real values, real
# boundaries, the unicode they can type, and pagination fixtures with the
# distinct sort keys everyone uses.

ROUNDTRIP_EXAMPLES: List[Tuple[str, str, int]] = [
    ("simple_key", "alice", 1),
    ("second_key", "bob", 2),
    ("empty_key", "", 0),
    ("zero_id", "carol", 0),
    ("negative_id", "dave", -1),
    ("large_id", "erin", 2 ** 31 - 1),
    ("long_key", "z" * 200, 12345),
    ("spaces", "ada lovelace", 17),
    ("apostrophe", "O'Brien", 18),
    ("punctuation", "a,b;c:d", 19),
    ("precomposed_accent", "café", 7),
    ("cjk", "日本語", 42),
    ("emoji", "party \U0001f389", 3),
    ("umlaut", "Über", 10),
    ("separator_lookalike", "with|pipe", 5),
    ("equals_in_key", "with=equals", 6),
    ("percent_in_key", "percent%20", 14),
    ("newline_in_key", "line\nbreak", 12),
    ("tab_in_key", "tab\there", 11),
    ("digits_only_key", "20260718", 99),
]

URL_EXAMPLES: List[Tuple[str, str, int]] = [
    ("url_simple", "alice", 1),
    ("url_second", "bob", 2),
    ("url_empty", "", 0),
    ("url_hyphenated", "user-42", 42),
    ("url_dotted", "a.b.c", 7),
    ("url_long", "z" * 64, 8),
    ("url_accent", "café", 9),
    ("url_mixed", "Order#1001", 1001),
]

PAGE_EXAMPLES: List[Tuple[str, List[Row], int]] = [
    ("page_empty", [], 10),
    ("page_single", [("a", 1)], 10),
    ("page_exact_fit", [("a", 1), ("b", 2), ("c", 3)], 3),
    ("page_two_pages", [("a", 1), ("b", 2), ("c", 3), ("d", 4)], 2),
    ("page_size_one", [("a", 1), ("b", 2), ("c", 3)], 1),
    ("page_unsorted_input", [("c", 3), ("a", 1), ("b", 2)], 2),
    ("page_size_bigger_than_data", [("a", 1), ("b", 2)], 50),
    ("page_ten_rows", [(chr(97 + i), i) for i in range(10)], 3),
    ("page_numeric_keys", [(f"{i:03d}", i) for i in range(7)], 2),
    ("page_unicode_keys", [("å", 1), ("b", 2), ("ç", 3)], 2),
]

DECODE_ERROR_EXAMPLES: List[Tuple[str, str]] = [
    ("reject_garbage", "!!!not-base64!!!"),
    ("reject_empty_token", ""),
]


def run_example_suite() -> Tuple[int, int, List[str]]:
    """Returns (passed, total, names of failures)."""
    failures: List[str] = []
    total = 0
    for name, key, rid in ROUNDTRIP_EXAMPLES:
        total += 1
        if fails(prop_roundtrip, (key, rid)):
            failures.append(name)
    for name, key, rid in URL_EXAMPLES:
        total += 1
        if fails(prop_survives_url, (key, rid)):
            failures.append(name)
    for name, rows, size in PAGE_EXAMPLES:
        total += 1
        if fails(prop_pagination, (rows, size)):
            failures.append(name)
    for name, token in DECODE_ERROR_EXAMPLES:
        total += 1
        try:
            decode_cursor(token)
            failures.append(name)                  # should have raised
        except Exception:
            pass
    return total - len(failures), total, failures


CURSOR_GEN = Tuples(Text(24), Ints(-(2 ** 31), 2 ** 31 - 1,
                                   pool=(0, 1, -1, 2 ** 31 - 1, -(2 ** 31)), bias=0.25))
PAGE_GEN = Tuples(Lists(Tuples(Text(3, plain=True), Ints(0, 50)), max_size=8),
                  Ints(1, 4))

PROPERTIES = [
    ("round-trip", prop_roundtrip, CURSOR_GEN),
    ("survives a URL", prop_survives_url, CURSOR_GEN),
    ("pagination is complete", prop_pagination, PAGE_GEN),
]


def section1() -> None:
    global ACTIVE
    banner(1, "FORTY EXAMPLES VERSUS THREE PROPERTIES")
    print("  one pagination cursor codec, three seeded bugs, two suites over it.")
    print("  a suite `kills` a bug if it is green with no bug and red with it.\n")

    ACTIVE = frozenset()
    base_pass, base_total, base_fail = run_example_suite()
    print(f"  baseline (no bugs): example suite {base_pass}/{base_total} green, "
          f"failures {base_fail or 'none'}")
    for label, prop, gen in PROPERTIES:
        r = check(prop, gen, max_examples=1000, do_shrink=False)
        print(f"  baseline: property `{label}` "
              f"{'holds' if r.passed else 'FAILS'} over {r.cases} generated cases")

    print("\n    bug                     example suite (40 tests)   the property that "
          "found it   cases")
    ex_kills = prop_kills = 0
    per_bug: Dict[str, int] = {}
    for name in ALL_BUGS:
        ACTIVE = frozenset({name})
        passed, total, failed = run_example_suite()
        ex_dead = passed < base_pass
        ex_kills += ex_dead
        found_by, cases = "-", "-"
        for label, prop, gen in PROPERTIES:
            r = check(prop, gen, max_examples=2000, do_shrink=False)
            if not r.passed:
                found_by, cases = label, str(r.cases)
                per_bug[name] = r.cases
                break
        prop_kills += found_by != "-"
        verdict = f"KILLED ({total - passed} red)" if ex_dead else "silent, 40/40 green"
        print(f"    {name:<23} {verdict:<26} {found_by:<25} {cases}")
    ACTIVE = frozenset()

    print(f"\n  kill rate: 40 hand-written examples {ex_kills}/3   ·   "
          f"3 properties {prop_kills}/3")
    print("  the examples are ~120 lines of test code; the properties are 15.")

    ACTIVE = frozenset({BUG_TIE})
    r = check(prop_pagination, PAGE_GEN, max_examples=2000)
    rows, size = r.shrunk
    print(f"\n  the tie bug, shrunk in {r.shrink_evals} evaluations: "
          f"rows={show(dedupe_ids(rows))} page_size={size}")
    print(f"    walk_pages returned {show(walk_pages(dedupe_ids(rows), size))}, "
          f"expected {show(sorted(dedupe_ids(rows)))}")
    print("    two rows share a sort key and the page boundary falls between them.")
    ACTIVE = frozenset()


# ══ 2 · THE SHRINKER ═════════════════════════════════════════════════════════

def section2() -> None:
    global ACTIVE
    banner(2, "SHRINKING: 4,000 CHARACTERS OF NOISE TO A BUG REPORT")
    ACTIVE = frozenset({BUG_NFC})
    big = Tuples(Text(4000, exact=True), Ints(0, 1000))
    r = check(prop_roundtrip, big, max_examples=400)
    assert not r.passed, "the NFC bug must be reachable"

    key0, id0 = r.failing
    keyN, idN = r.shrunk
    print(f"  first failing case: a {len(key0):,}-character sort key, row id {id0}")
    print(f"    {show(key0, 66)}")
    print(f"  after shrinking:    a {len(keyN)}-character sort key, row id {idN}")
    print(f"    {show(keyN, 66)}  ->  {r.error}")
    print(f"  {r.shrink_evals:,} candidate inputs evaluated, "
          f"{len(r.trace) - 1} of them accepted as smaller.\n")

    print("    accepted   after N evals   key chars   the input that still fails")
    for i, (evals, _sz, value) in enumerate(r.trace):
        k, rid = value
        print(f"    {i:>8}   {evals:>13}   {len(k):>9}   {show((k, rid), 42)}")

    ACTIVE = frozenset()
    print(f"\n  a {len(key0) / max(1, len(keyN)):,.0f}x reduction in key length for "
          f"{r.shrink_evals} property evaluations. Shrinking is cheap")
    print("  because deleting half of a failing input either still fails — in which")
    print("  case you keep it — or does not, in which case you have lost one call.")


# ══ 3 · GENERATOR DISTRIBUTION ═══════════════════════════════════════════════
# The generator decides which bugs are reachable at all. This is the part
# everybody skips and it dominates everything else.

LIMIT_MIN, LIMIT_MAX = 1, 100


def normalise_limit(raw: int) -> int:
    """Clamp a client-supplied `?limit=` into [1, 100]. Three edge bugs."""
    if raw < 0:
        return raw if LIMIT_BUGS["negative"] else LIMIT_MIN
    if raw == 0:
        return 0 if LIMIT_BUGS["zero"] else LIMIT_MIN
    if raw >= LIMIT_MAX:
        return LIMIT_MAX + 1 if (LIMIT_BUGS["upper"] and raw == LIMIT_MAX) else LIMIT_MAX
    return raw


LIMIT_BUGS = {"negative": True, "zero": True, "upper": True}


def prop_limit_in_range(raw: int) -> bool:
    return LIMIT_MIN <= normalise_limit(raw) <= LIMIT_MAX


BOUNDARY_POOL = (0, 1, -1, 2, 99, 100, 101, 255, 256, 1000,
                 2 ** 31 - 1, -(2 ** 31), 2 ** 63 - 1)

DISTRIBUTIONS = [
    ("uniform over int32", Ints(-(2 ** 31), 2 ** 31 - 1)),
    ("uniform over 0..1000", Ints(0, 1000)),
    ("boundary-biased (25%)", Ints(-(2 ** 31), 2 ** 31 - 1, pool=BOUNDARY_POOL, bias=0.25)),
]

TRIGGERS = {"negative": "raw < 0", "zero": "raw == 0", "upper": "raw == 100"}
WIDTH = {"negative": 2 ** 31, "zero": 1, "upper": 1}


def section3() -> None:
    banner(3, "GENERATOR DISTRIBUTION: THE SAME PROPERTY, THREE GENERATORS")
    print("  target: normalise_limit(raw) must return a value in [1, 100].")
    print("  three independent edge bugs, three ways of drawing one integer.")
    print(f"  the property is identical in all nine cells. Only draw() changes.\n")

    budget = 200_000
    head = "".join(f"{label:>23}" for label, _ in DISTRIBUTIONS)
    print(f"    bug        triggers when   share of int32{head}")
    rows: Dict[str, List[Optional[int]]] = {}
    for key in ("negative", "zero", "upper"):
        for other in LIMIT_BUGS:
            LIMIT_BUGS[other] = other == key
        found: List[Optional[int]] = []
        for _label, gen in DISTRIBUTIONS:
            r = check(prop_limit_in_range, gen, max_examples=budget, do_shrink=False)
            found.append(None if r.passed else r.cases)
        rows[key] = found
        cells = "".join(f"{(f'{c:,} cases' if c else 'NOT FOUND'):>23}" for c in found)
        print(f"    {key:<10} {TRIGGERS[key]:<15} {WIDTH[key] / 2 ** 32:>13.2e}{cells}")
    for other in LIMIT_BUGS:
        LIMIT_BUGS[other] = True

    print(f"\n  budget: {budget:,} cases per cell. `NOT FOUND` means the generator")
    print("  drew 200,000 values and never once produced an input that could fail.\n")
    print("    bug        boundary-biased  vs int32 uniform                  multiple")
    for key in ("negative", "zero", "upper"):
        wide, _narrow, biased = rows[key]
        if wide and biased:
            print(f"    {key:<10} {biased:>15,}  {wide:>16,} cases          "
                  f"{wide / biased:>12,.1f}x")
        elif biased:
            expected = 2 ** 32 / WIDTH[key]
            print(f"    {key:<10} {biased:>15,}  {expected:>16,.0f} cases expected  "
                  f"{expected / biased:>12,.0f}x")

    print("\n  stare at the middle column. rng.randint(0, 1000) is what a person writes")
    print("  when asked to generate `a page size`; it beats the honest uniform generator")
    print("  on two bugs and is blind to the third. A generator is a hypothesis about")
    print("  where the bugs are, and an unstated hypothesis is still a hypothesis.")


# ══ 4 · STATEFUL, MODEL-BASED TESTING ════════════════════════════════════════
# Some bugs are not in any single call. They are in the sequence.

class LRUCache:
    """Capacity-bounded cache. The bug: `get` does not refresh recency, so the
    eviction order is insertion order rather than least-recently-used."""

    def __init__(self, capacity: int, buggy: bool = True) -> None:
        self.capacity = capacity
        self.buggy = buggy
        self.store: Dict[str, int] = {}
        self.order: List[str] = []

    def _touch(self, key: str) -> None:
        if key in self.order:
            self.order.remove(key)
        self.order.append(key)

    def get(self, key: str) -> Optional[int]:
        if key not in self.store:
            return None
        if not self.buggy:
            self._touch(key)
        return self.store[key]

    def put(self, key: str, value: int) -> None:
        self.store[key] = value
        self._touch(key)
        while len(self.order) > self.capacity:
            self.store.pop(self.order.pop(0), None)


class ModelCache:
    """The obviously-correct reference: a list in true recency order. Slow and
    unmistakably right, which is the only requirement for a model."""

    def __init__(self, capacity: int) -> None:
        self.capacity = capacity
        self.items: List[Tuple[str, int]] = []

    def get(self, key: str) -> Optional[int]:
        for i, (k, v) in enumerate(self.items):
            if k == key:
                self.items.append(self.items.pop(i))
                return v
        return None

    def put(self, key: str, value: int) -> None:
        self.items = [(k, v) for k, v in self.items if k != key]
        self.items.append((key, value))
        while len(self.items) > self.capacity:
            self.items.pop(0)


Op = Tuple[str, str, int]
CAPACITY = 3


class Ops(Gen):
    """Draws a sequence of cache operations over a deliberately tiny key space —
    three keys and a capacity of three, so evictions actually happen."""

    KEYS = ("a", "b", "c", "d")

    def __init__(self, max_len: int):
        self.max_len = max_len

    def draw(self, rng: random.Random) -> List[Op]:
        n = rng.randint(1, self.max_len)
        return [(rng.choice(("get", "put")), rng.choice(self.KEYS), rng.randint(0, 9))
                for _ in range(n)]

    def candidates(self, ops: List[Op]) -> Iterator[List[Op]]:
        n = len(ops)
        block = n
        while block >= 1:
            for i in range(0, n, block):
                cand = ops[:i] + ops[i + block:]
                if cand and cand != ops:
                    yield cand
            block //= 2
        for i, (kind, key, val) in enumerate(ops):     # simplify each operation
            for k2 in self.KEYS:
                if k2 < key:
                    yield ops[:i] + [(kind, k2, val)] + ops[i + 1:]
            if val != 0:
                yield ops[:i] + [(kind, key, 0)] + ops[i + 1:]


def run_sequence(ops: Sequence[Op], buggy: bool = True) -> Optional[int]:
    """Run the same operations against implementation and model. Returns the
    1-based index of the first disagreement, or None."""
    real, model = LRUCache(CAPACITY, buggy=buggy), ModelCache(CAPACITY)
    for i, (kind, key, val) in enumerate(ops, 1):
        if kind == "put":
            real.put(key, val)
            model.put(key, val)
        else:
            if real.get(key) != model.get(key):
                return i
        for k in Ops.KEYS:                              # the invariant, checked fully
            if (k in real.store) != any(mk == k for mk, _ in model.items):
                return i
    return None


def prop_cache_agrees(ops: List[Op]) -> bool:
    return run_sequence(ops) is None


def section4() -> None:
    banner(4, "STATEFUL TESTING: THE BUG IS IN THE SEQUENCE, NOT THE CALL")
    print(f"  an LRU cache of capacity {CAPACITY} against a dict+list model. The bug:")
    print("  get() does not refresh recency, so eviction is insertion-ordered.\n")

    print("  first, the stateless property — every single operation in isolation:")
    single = Ops(1)
    r1 = check(prop_cache_agrees, single, max_examples=50_000, do_shrink=False)
    print(f"    sequences of length 1, {50_000:,} cases: "
          f"{'no disagreement' if r1.passed else 'failed at ' + str(r1.cases)}")
    print("    a one-operation cache is always correct. There is nothing to evict.\n")

    print("  now sequences. how long must a sequence be before it can disagree?")
    print("    max sequence length   sequences drawn to the first disagreement")
    for max_len in (2, 3, 4, 5, 6, 8, 12, 40):
        gen = Ops(max_len)
        r = check(prop_cache_agrees, gen, max_examples=20_000, do_shrink=False)
        cell = f"{r.cases:,}" if not r.passed else f"NOT FOUND in 20,000"
        print(f"    {max_len:>19}   {cell}")

    gen = Ops(40)
    r = check(prop_cache_agrees, gen, max_examples=20_000)
    print(f"\n  the raw failing sequence: {len(r.failing)} operations")
    print(f"    {show(r.failing, 70)}")
    print(f"  shrunk to {len(r.shrunk)} operations in {r.shrink_evals:,} evaluations:")
    for i, (kind, key, val) in enumerate(r.shrunk, 1):
        print(f"    {i}. {kind}({key!r}" + (f", {val})" if kind == "put" else ")"))
    idx = run_sequence(r.shrunk)
    print(f"    disagreement at operation {idx}.")

    real, model = LRUCache(CAPACITY), ModelCache(CAPACITY)
    for kind, key, val in r.shrunk:
        if kind == "put":
            real.put(key, val)
            model.put(key, val)
        else:
            real.get(key)
            model.get(key)
    print(f"    implementation holds {sorted(real.store)}, model holds "
          f"{sorted(k for k, _ in model.items)}")

    lengths = []
    for s in range(60):
        rr = check(prop_cache_agrees, Ops(40), max_examples=20_000, seed=SEED + s)
        if not rr.passed:
            lengths.append(len(rr.shrunk))
    counts = sorted((lengths.count(v), v) for v in set(lengths))
    print(f"\n  over 60 seeds the shrinker landed on a minimal sequence of length "
          f"{min(lengths)}-{max(lengths)};")
    print("    length  seeds")
    for cnt, val in sorted(counts, key=lambda t: t[1]):
        print(f"    {val:>6}  {cnt}")
    print("  different seeds, essentially the same bug report. That convergence is")
    print("  what makes a shrunk counterexample worth putting in a ticket.")


# ══ 5 · DIFFERENTIAL TESTING AGAINST A SLOW ORACLE ═══════════════════════════
# When you cannot state a property, state an equivalence: the fast thing must
# agree with the obviously-correct slow thing.

Range = Tuple[int, int]


def merge_fast(ranges: Sequence[Range]) -> List[Range]:
    """Sort and sweep. The bug: `<` where `<=` belongs, so ranges that touch
    exactly (end == next start) are not merged."""
    if not ranges:
        return []
    out: List[Range] = []
    for lo, hi in sorted((min(a, b), max(a, b)) for a, b in ranges):
        if out and lo < out[-1][1]:            # BUG: should be lo <= out[-1][1]
            out[-1] = (out[-1][0], max(out[-1][1], hi))
        else:
            out.append((lo, hi))
    return out


def merge_slow(ranges: Sequence[Range]) -> List[Range]:
    """Union any two ranges that overlap or touch, until nothing changes.
    Quadratic per pass and obviously correct, which is the whole job."""
    items = [(min(a, b), max(a, b)) for a, b in ranges]
    changed = True
    while changed:
        changed = False
        for i in range(len(items)):
            for j in range(i + 1, len(items)):
                (a1, b1), (a2, b2) = items[i], items[j]
                if a1 <= b2 and a2 <= b1:
                    items[i] = (min(a1, a2), max(b1, b2))
                    items.pop(j)
                    changed = True
                    break
            if changed:
                break
    return sorted(items)


def prop_merge_agrees(ranges: List[Range]) -> bool:
    return merge_fast(ranges) == merge_slow(ranges)


def section5() -> None:
    banner(5, "DIFFERENTIAL TESTING: THE FAST ONE MUST AGREE WITH THE SLOW ONE")
    print("  merge_fast (sort + sweep) versus merge_slow (union to a fixed point).")
    print("  no property about merging is stated at all — only that they agree.")
    print("  the bug is `<` where `<=` belongs, so ranges that touch exactly")
    print("  at a point are not merged. It needs two coordinates to be EQUAL.\n")

    budget = 60_000
    print(f"    coordinates drawn from   cases to first disagreement   expected   "
          f"(budget {budget:,})")
    results: Dict[int, Optional[int]] = {}
    for hi in (20, 5_000, 1_000_000):
        gen = Lists(Tuples(Ints(0, hi), Ints(0, hi)), max_size=4, min_size=2)
        r = check(prop_merge_agrees, gen, max_examples=budget, do_shrink=False)
        results[hi] = None if r.passed else r.cases
        cell = f"{r.cases:,}" if not r.passed else f"NOT FOUND"
        print(f"    0..{hi:<21,} {cell:>27}   {(hi + 1) / 12.0:>8,.0f}")

    near, mid, far = results[20], results[5_000], results[1_000_000]
    print(f"\n  the identical bug, the identical property, the identical budget:")
    print(f"    0..20 vs 0..5,000        {mid / near:>10,.0f}x the cases")
    print(f"    0..20 vs 0..1,000,000    {far / near:>10,.0f}x the cases")
    print("  nothing about the code changed. The generator's range did.")

    gen = Lists(Tuples(Ints(0, 20), Ints(0, 20)), max_size=4, min_size=2)
    r = check(prop_merge_agrees, gen, max_examples=budget)
    print(f"\n  shrunk counterexample: {r.shrunk}   ({r.shrink_evals} candidates)")
    print(f"    merge_fast -> {merge_fast(r.shrunk)}")
    print(f"    merge_slow -> {merge_slow(r.shrunk)}")
    print("    two ranges that touch at a point, and nothing else.")


# ══ 6 · FUZZING AT THE BYTE LEVEL ════════════════════════════════════════════
# Miller, Fredriksen & So (CACM 33(12), 1990) fed random bytes to 88 UNIX
# utilities and crashed or hung 25-33% of them. The idea has not changed; the
# only thing that changed is that a modern fuzzer watches which branches it hit.

BRANCHES: Set[int] = set()


def br(i: int) -> None:
    BRANCHES.add(i)


def pct_decode(raw: bytes) -> str:
    out = bytearray()
    i = 0
    while i < len(raw):
        c = raw[i]
        if c == 0x2B:                                  # "+" means space
            br(1)
            out.append(0x20)
            i += 1
        elif c == 0x25 and i + 2 < len(raw) + 0:       # "%XX"
            br(2)
            pair = raw[i + 1:i + 3]
            try:
                out.append(int(pair, 16))
                br(3)
                i += 3
                continue
            except ValueError:
                br(4)
                out.append(c)
                i += 1
        else:
            br(5)
            out.append(c)
            i += 1
    return out.decode("utf-8", "replace")


def parse_query(raw: bytes) -> Dict[str, Any]:
    """A query-string parser with array syntax: `tags[0]=x&tags[1]=y`.
    The crash: the index between the brackets is assumed to be digits."""
    out: Dict[str, Any] = {}
    if not raw:
        br(6)
        return out
    br(7)
    for part in raw.split(b"&"):
        if not part:
            br(8)
            continue
        if b"=" in part:
            br(9)
            k, _, v = part.partition(b"=")
        else:
            br(10)
            k, v = part, b""
        key, val = pct_decode(k), pct_decode(v)
        if "[" in key:
            br(11)
        if key.endswith("]"):
            br(12)
        if "[" in key and key.endswith("]"):
            br(13)
            name, _, idx = key[:-1].partition("[")
            slot = int(idx)                            # BUG: idx may be "" or "x"
            br(14)
            arr = out.setdefault(name, [])
            while len(arr) <= slot:
                arr.append(None)
            arr[slot] = val
        else:
            br(15)
            out[key] = val
    return out


PRINTABLE = bytes(range(0x20, 0x7F))
SEED_CORPUS = [b"a=1&b=2", b"name=alice", b"q=hello+world"]


def execute(data: bytes) -> Tuple[Optional[str], frozenset]:
    """Run the parser, returning (crash description or None, branches hit)."""
    BRANCHES.clear()
    try:
        parse_query(data)
        return None, frozenset(BRANCHES)
    except Exception as exc:
        return f"{type(exc).__name__}: {exc}"[:60], frozenset(BRANCHES)


@dataclass
class FuzzRun:
    cases: Optional[int] = None            # executions to the first crash
    crashing: bytes = b""
    crash: str = ""
    first_seen: Dict[int, int] = field(default_factory=dict)   # branch -> execution


def fuzz_random(budget: int, rng: random.Random, stop_on_crash: bool = True,
                alphabet: bytes = PRINTABLE) -> FuzzRun:
    run = FuzzRun()
    for i in range(1, budget + 1):
        data = bytes(rng.choice(alphabet) for _ in range(rng.randint(1, 24)))
        crash, hit = execute(data)
        for b in sorted(hit):
            run.first_seen.setdefault(b, i)
        if crash and run.cases is None:
            run.cases, run.crashing, run.crash = i, data, crash
            if stop_on_crash:
                return run
    return run


def mutate(data: bytes, rng: random.Random) -> bytes:
    kind = rng.randint(0, 3)
    if not data:
        return bytes([rng.choice(PRINTABLE)])
    i = rng.randrange(len(data))
    if kind == 0:                                      # overwrite a byte
        return data[:i] + bytes([rng.choice(PRINTABLE)]) + data[i + 1:]
    if kind == 1:                                      # insert a byte
        return data[:i] + bytes([rng.choice(PRINTABLE)]) + data[i:]
    if kind == 2:                                      # delete a byte
        return data[:i] + data[i + 1:]
    j = rng.randrange(len(data))                       # splice a chunk onto itself
    return (data + data[min(i, j):max(i, j) + 1])[:64]


def fuzz_guided(budget: int, rng: random.Random, stop_on_crash: bool = True) -> FuzzRun:
    """The AFL insight in ten lines: keep any input that reached a branch no
    previous input reached, and mutate the corpus instead of the void."""
    run = FuzzRun()
    corpus = list(SEED_CORPUS)
    seen: Set[int] = set()
    for data in corpus:
        _c, hit = execute(data)
        for b in sorted(hit):
            run.first_seen.setdefault(b, 0)
        seen |= hit
    for i in range(1, budget + 1):
        data = mutate(rng.choice(corpus), rng)
        crash, hit = execute(data)
        for b in sorted(hit):
            run.first_seen.setdefault(b, i)
        if crash and run.cases is None:
            run.cases, run.crashing, run.crash = i, data, crash
            if stop_on_crash:
                return run
        elif hit - seen:                   # a branch nobody had reached: keep it
            seen |= hit
            corpus.append(data)
    return run


def shrink_bytes(data: bytes) -> Tuple[bytes, int]:
    """Delta-debug the crashing input: delete blocks, then simplify bytes."""
    best, evals = data, 0
    progress = True
    while progress:
        progress = False
        n = len(best)
        cands: List[bytes] = []
        block = n
        while block >= 1:
            cands += [best[:i] + best[i + block:] for i in range(0, n, block)]
            block //= 2
        cands += [best[:i] + b"a" + best[i + 1:] for i in range(n) if best[i:i + 1] != b"a"]
        for cand in cands:
            evals += 1
            if cand == best:
                continue
            if execute(cand)[0]:
                best, progress = cand, True
                break
    return best, evals


BRANCH_NAMES = {
    7: "a non-empty query string", 9: "a segment containing '='",
    10: "a segment with no '='", 8: "an empty segment (&&)",
    1: "'+' decoded as a space", 2: "a '%' escape", 3: "a valid %XX pair",
    4: "an invalid %XX pair", 11: "'[' inside a key",
    12: "a key ending in ']'", 13: "BOTH -> the crash path",
}


def section6() -> None:
    banner(6, "FUZZING: RANDOM BYTES VERSUS COVERAGE-GUIDED MUTATION")
    print("  target: a query-string parser with array syntax, tags[0]=x.")
    print("  the crash needs a key that contains '[' AND ends in ']', before an '='.")
    print(f"  {len(SEED_CORPUS)} seed inputs for the guided run: "
          f"{', '.join(repr(x) for x in SEED_CORPUS)}\n")

    budget = 200_000
    all_bytes = bytes(range(256))
    runs = {
        "random bytes (Miller 1990)": fuzz_random(budget, random.Random(SEED),
                                                  alphabet=all_bytes),
        "random printable ASCII": fuzz_random(budget, random.Random(SEED)),
        "coverage-guided": fuzz_guided(budget, random.Random(SEED)),
    }

    print("    fuzzer                       branches   cases to crash   the crashing input")
    for label, run in runs.items():
        cell = f"{run.cases:,}" if run.cases else f"none in {budget:,}"
        print(f"    {label:<28} {len(run.first_seen):>8}   {cell:>14}   "
              f"{show(run.crashing, 24) if run.cases else '-'}")

    raw, rnd, gui = (runs["random bytes (Miller 1990)"],
                     runs["random printable ASCII"], runs["coverage-guided"])
    print(f"\n  guided vs printable-ASCII random:  {rnd.cases / gui.cases:>6,.1f}x fewer "
          "executions to the same crash")
    if raw.cases:
        print(f"  guided vs uniform random bytes:    {raw.cases / gui.cases:>6,.1f}x")
    else:
        print(f"  guided vs uniform random bytes:    never crashed in {budget:,} runs")
    print(f"  the crash: {gui.crash}")

    small, evals = shrink_bytes(gui.crashing)
    print(f"  shrunk from {len(gui.crashing)} bytes to {len(small)}: {small!r}  "
          f"({evals} candidates) — the whole bug report is an empty index.")

    print("\n  the ladder, measured: executions before each branch was first reached")
    print("  (both run to 50,000 executions; crashes recorded but not fatal)")
    ladder_budget = 50_000
    full = {"random": fuzz_random(ladder_budget, random.Random(SEED), stop_on_crash=False),
            "guided": fuzz_guided(ladder_budget, random.Random(SEED), stop_on_crash=False)}
    print("    branch                       random bytes   coverage-guided")
    for bid in (7, 9, 10, 1, 2, 4, 11, 12, 13):
        cells = ""
        for run in full.values():
            v = run.first_seen.get(bid)
            cells += f"{('never' if v is None else f'{v:,}'):>17}"
        print(f"    {BRANCH_NAMES[bid]:<28}{cells}")
    print("  the honest surprise is in the middle rows: random noise reaches each")
    print("  INDIVIDUAL rung sooner, because it contains '[' and ']' more often than a")
    print("  mutated query string does. What it cannot build is the CONJUNCTION — it")
    print("  discards every near miss. Guidance is memory, not better random numbers.")


# ══ 7 · SEEDS, REPRODUCIBILITY, AND THE FLAKINESS THAT ISN'T ═════════════════

def section7() -> None:
    global ACTIVE
    banner(7, "SEEDS: A PROPERTY TEST THAT FINDS A NEW BUG IS NOT FLAKY")
    print("  the same property, the same commit, 300 different seeds.")
    print("  a run is `red` if it found the bug within max_examples cases.\n")

    seeds = 300
    print("    max_examples   red runs (bug present)   red runs (bug fixed)")
    for max_examples in (5, 10, 25, 50, 100, 250):
        ACTIVE = frozenset({BUG_NFC})
        red = sum(not check(prop_roundtrip, CURSOR_GEN, max_examples=max_examples,
                            seed=SEED + s, do_shrink=False).passed for s in range(seeds))
        ACTIVE = frozenset()
        false_red = sum(not check(prop_roundtrip, CURSOR_GEN, max_examples=max_examples,
                                  seed=SEED + s, do_shrink=False).passed
                        for s in range(seeds))
        print(f"    {max_examples:>12}   {red:>6}/{seeds}  ({red / seeds:>6.1%})       "
              f"{false_red:>6}/{seeds}  ({false_red / seeds:>6.1%})")

    print("\n  read the two columns as a suite owner would.")
    print("  left column: the verdict varies run to run -> by lesson 9's definition,")
    print("    a test that is red on some runs and green on others is flaky.")
    print("  right column: on correct code it is ZERO at every setting. The test")
    print("    never once went red on a codebase that was right.")
    print("  so the variance is entirely in DISCOVERY, never in the verdict about")
    print("  correct code. A flaky test costs you trust; this costs you latency.\n")

    ACTIVE = frozenset({BUG_NFC})
    database: List[Tuple[str, int]] = []

    def run_with_db(seed: int, max_examples: int = 25) -> Tuple[bool, int]:
        """Replay the regression database first, then generate. Exactly what
        hypothesis's .hypothesis/examples directory does."""
        for case in database:
            if fails(prop_roundtrip, case):
                return False, 1
        r = check(prop_roundtrip, CURSOR_GEN, max_examples=max_examples,
                  seed=seed, do_shrink=True)
        if not r.passed:
            database.append(r.shrunk)
        return r.passed, r.cases

    print("    run   seed      cases in db   verdict   cases to red")
    for i in range(8):
        held = len(database)
        passed, cases = run_with_db(SEED + 400 + i)
        print(f"    {i + 1:>3}   {SEED + 400 + i}   {held:>11}   "
              f"{'green' if passed else 'RED':>7}   {'-' if passed else cases}")
    print(f"  after the first red run the database holds {show(database[0], 30)},")
    print("  and every later run is red on case 1 regardless of its seed.")
    ACTIVE = frozenset()

    print("\n  and the same database on the FIXED code, to check it is not a landmine:")
    for i in range(3):
        ok = all(not fails(prop_roundtrip, c) for c in database)
        print(f"    replay {i + 1}: {len(database)} recorded case(s) -> "
              f"{'all pass' if ok else 'FAIL'}")


# ══ 8 · THE PROPERTY THAT PROVES NOTHING ═════════════════════════════════════

def prop_tautology(case: Tuple[str, int]) -> bool:
    """The trap: a property written by reading the implementation. It restates
    encode_cursor's body, so it agrees with every bug encode_cursor has."""
    key, rid = case
    normalised = unicodedata.normalize("NFC", key) if bug(BUG_NFC) else key
    payload = f"{normalised}{SEP}{rid}".encode("utf-8")
    expected = (base64.b64encode(payload) if bug(BUG_ALPHABET)
                else base64.urlsafe_b64encode(payload))
    return encode_cursor(key, rid) == expected.decode("ascii").rstrip("=")


def prop_never_crashes(case: Tuple[str, int]) -> bool:
    """The weakest useful property: whatever else happens, do not raise."""
    key, rid = case
    try:
        decode_cursor(through_url(encode_cursor(key, rid)))
    except (ValueError, UnicodeDecodeError):
        return False
    return True


def section8() -> None:
    global ACTIVE
    banner(8, "WHAT PROPERTY TESTING IS BAD AT")
    print("  five properties over the same codec, against the same three bugs.")
    print("  `restates the implementation` was written by reading encode_cursor's")
    print("  body — which is exactly how a hand-written mock gets written.\n")

    candidates = [
        ("round-trip", prop_roundtrip, CURSOR_GEN),
        ("survives a URL", prop_survives_url, CURSOR_GEN),
        ("pagination is complete", prop_pagination, PAGE_GEN),
        ("never crashes (the weakest)", prop_never_crashes, CURSOR_GEN),
        ("restates the implementation", prop_tautology, CURSOR_GEN),
    ]
    header = "".join(f"{b:>23}" for b in ALL_BUGS)
    print(f"    property                      {header}   killed")
    union = set()
    for label, prop, gen in candidates:
        cells, killed = "", 0
        for name in ALL_BUGS:
            ACTIVE = frozenset({name})
            r = check(prop, gen, max_examples=3000, do_shrink=False)
            if not r.passed:
                killed += 1
                if label != "restates the implementation":
                    union.add(name)
            cells += f"{(f'case {r.cases}' if not r.passed else 'silent'):>23}"
        print(f"    {label:<30}{cells}   {killed}/3")
    ACTIVE = frozenset()
    print(f"    {'the first four, together':<30}{'':>69}   {len(union)}/3")

    print("\n  two results. First: no single property covers the codec — the best of")
    print("  the four kills 2 of 3 and the rest kill 1. Properties compose, and the")
    print("  practical move is always to write another one, not a better one.")
    print("  Second, and this is the one to keep: the tautology kills 0 of 3 while")
    print("  looking identical to its neighbours. It is universally quantified, it")
    print("  draws 3,000 cases, it is green, and it cannot fail — it asserts that")
    print("  encode_cursor equals encode_cursor. A property read off the implementation")
    print("  inherits the implementation's bugs, exactly as a hand-written mock inherits")
    print("  its author's misreading. `never crashes` is weak and honest for the mirror")
    print("  reason: it was written from the caller's side, so it cannot agree with a bug.")


def main() -> None:
    print("PROPERTY-BASED TESTING & FUZZING — Phase 12, Lesson 12")
    print(f"seed = {SEED}; every number below is produced by this file.")
    section1()
    section2()
    section3()
    section4()
    section5()
    section6()
    section7()
    section8()
    print()


if __name__ == "__main__":
    main()
