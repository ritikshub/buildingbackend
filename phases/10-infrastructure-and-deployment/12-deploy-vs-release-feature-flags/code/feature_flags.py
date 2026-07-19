"""Deploy != Release: a feature-flag engine, sticky bucketing, and flag debt.

Lesson: phases/10-infrastructure-and-deployment/12-deploy-vs-release-feature-flags/docs/en.md
Standard library only, seeded (random.Random(7)), self-terminating, ~5 s.
Hashing follows the usual SDK convention: SHA-256 (FIPS 180-4) over
"<flag-salt>:<stable-user-key>", read as a 64-bit integer, taken mod 10000 to
produce a basis-point bucket. Everything below is measured, not asserted.
"""

from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

SEED = 7
BP = 10_000  # basis points: 10000 buckets, so a rollout has 0.01% granularity


# --------------------------------------------------------------------------
# 1 · THE FLAG ENGINE
# --------------------------------------------------------------------------

def bucket_bp(salt: str, key: str) -> int:
    """Deterministic bucket in [0, 10000) for a (flag, user) pair.

    The salt is what makes two flags at 10% pick DIFFERENT users. Drop it and
    every flag in your system selects the same unlucky cohort forever.
    """
    digest = hashlib.sha256(f"{salt}:{key}".encode()).digest()
    return int.from_bytes(digest[:8], "big") % BP


@dataclass
class Rule:
    """One targeting rule. `when` is an AND over attribute matches."""
    name: str
    when: dict[str, Any] = field(default_factory=dict)
    rollout_pct: float | None = None   # None = everyone the rule matched
    variant: bool = True

    def targets(self, user: dict[str, Any]) -> bool:
        for attr, want in self.when.items():
            have = user.get(attr)
            if isinstance(want, (list, tuple, set)):
                if have not in want:
                    return False
            elif have != want:
                return False
        return True


@dataclass
class Flag:
    key: str
    kind: str                      # release | operational | experiment | permission
    default: bool                  # the coded fallback: the KNOWN-GOOD value
    rules: list[Rule] = field(default_factory=list)
    salt: str | None = None        # defaults to the flag key
    owner: str = "unowned"
    age_days: int = 0

    @property
    def bucket_salt(self) -> str:
        return self.salt if self.salt is not None else self.key


def evaluate(flag: Flag, user: dict[str, Any]) -> tuple[bool, str]:
    """Return (variant, reason). The reason is what you need at 3am."""
    for rule in flag.rules:
        if not rule.targets(user):
            continue
        shown = ",".join(f"{k}={v}" for k, v in rule.when.items()) or "everyone"
        if rule.rollout_pct is None:
            return rule.variant, f"rule '{rule.name}' [{shown}]"
        b = bucket_bp(flag.bucket_salt, user["id"])
        cut = int(rule.rollout_pct * 100)
        if b < cut:
            return rule.variant, f"rule '{rule.name}' [{shown}] bucket {b} < {cut}"
        return flag.default, f"rule '{rule.name}' missed rollout: bucket {b} >= {cut}"
    return flag.default, "no rule matched -> coded default"


def section_1() -> Flag:
    print("== 1 · A FLAG ENGINE: TARGETING, ROLLOUT, DEFAULT — AND THE REASON ==")
    flag = Flag(
        key="checkout_v2",
        kind="release",
        default=False,                       # known-good: the new path is OFF
        owner="payments",
        rules=[
            Rule("internal staff first", {"internal": True}),
            Rule("kill for EU while DPA review runs", {"region": "eu"}, variant=False),
            Rule("enterprise opt-in beta", {"plan": "enterprise"}, rollout_pct=50.0),
            Rule("general rollout", {}, rollout_pct=10.0),
        ],
    )
    users = [
        {"id": "u-1041", "plan": "free", "region": "us", "internal": False},
        {"id": "u-2277", "plan": "free", "region": "us", "internal": False},
        {"id": "u-3313", "plan": "enterprise", "region": "us", "internal": False},
        {"id": "u-4128", "plan": "enterprise", "region": "us", "internal": False},
        {"id": "u-5002", "plan": "pro", "region": "eu", "internal": False},
        {"id": "u-6661", "plan": "pro", "region": "us", "internal": True},
    ]
    print(f"  flag '{flag.key}' kind={flag.kind} default={flag.default} "
          f"owner={flag.owner}  (4 rules, first match wins)")
    print(f"  {'user':<9} {'plan':<11} {'region':<7} {'->':<4} {'why'}")
    for u in users:
        variant, why = evaluate(flag, u)
        print(f"  {u['id']:<9} {u['plan']:<11} {u['region']:<7} "
              f"{('ON' if variant else 'off'):<4} {why}")
    print("  the rule ORDER is the policy: the EU kill rule sits above the")
    print("  rollout, so a region cannot be exposed by a percentage ramp.")
    print()
    return flag


# --------------------------------------------------------------------------
# 2 · STICKY BUCKETING, MEASURED
# --------------------------------------------------------------------------

def section_2() -> tuple[float, float, float]:
    print("== 2 · STICKY BUCKETING: THE SAME USER MUST GET THE SAME VARIANT ==")
    n_users, n_reqs, pct = 5_000, 40, 10.0
    rng = random.Random(SEED)
    cut = int(pct * 100)

    def run(assign: Callable[[str], bool]) -> dict[str, float]:
        both = switches = on_reqs = 0
        on_users = 0
        for i in range(n_users):
            uid = f"user-{i:06d}"
            seen_on = seen_off = False
            prev: bool | None = None
            for _ in range(n_reqs):
                v = assign(uid)
                on_reqs += v
                seen_on |= v
                seen_off |= not v
                if prev is not None and v != prev:
                    switches += 1
                prev = v
            both += seen_on and seen_off
            on_users += seen_on and not seen_off
        return {
            "flicker_pct": 100.0 * both / n_users,
            "switches": switches,
            "req_on_pct": 100.0 * on_reqs / (n_users * n_reqs),
            "user_on_pct": 100.0 * on_users / n_users,
            "ever_on_pct": 100.0 * (on_users + both) / n_users,
        }

    random_run = run(lambda uid: rng.random() * 100.0 < pct)
    hashed_run = run(lambda uid: bucket_bp("checkout_v2", uid) < cut)

    print(f"  {n_users:,} users x {n_reqs} requests = {n_users * n_reqs:,} "
          f"evaluations of a {pct:.0f}% rollout, run twice")
    print(f"  {'bucketing':<26}{'flicker':>9}{'switches':>10}"
          f"{'% of reqs ON':>14}{'% users ever ON':>17}")
    for label, r in (("fresh random per request", random_run),
                     ("sha256(salt + user id)", hashed_run)):
        print(f"  {label:<26}{r['flicker_pct']:>8.2f}%{r['switches']:>10,}"
              f"{r['req_on_pct']:>13.2f}%{r['ever_on_pct']:>16.2f}%")
    print(f"  random bucketing hit the target {pct:.0f}% of REQUESTS "
          f"({random_run['req_on_pct']:.2f}%) and still exposed")
    print(f"  {random_run['ever_on_pct']:.2f}% of users to the new path at least once — "
          f"a 10% rollout that")
    print(f"  is really a 100% rollout, {random_run['switches']:,} variant switches deep.")
    print(f"  hashed bucketing: flicker {hashed_run['flicker_pct']:.2f}%, "
          f"{hashed_run['switches']} switches, and the")
    print(f"  realised rollout is the same number for users and requests: "
          f"{hashed_run['user_on_pct']:.2f}%.")
    print(f"  ({hashed_run['user_on_pct']:.2f}% and not 10.00%: that is sampling error "
          f"at {n_users:,} users, not")
    print("   bias — section 3 buckets 50,000 users and lands on 9.98%.)")

    # Distribution quality: deterministic is not enough, it must be FAIR.
    n_big = 50_000
    buckets = [0] * 100
    for i in range(n_big):
        buckets[bucket_bp("checkout_v2", f"user-{i:06d}") // 100] += 1
    mean = n_big / 100
    lo, hi = min(buckets), max(buckets)
    dev = 100.0 * max(abs(lo - mean), abs(hi - mean)) / mean
    print(f"  distribution over 100 buckets, {n_big:,} users: "
          f"min {lo}  mean {mean:.0f}  max {hi}")
    print(f"  worst bucket is {dev:.1f}% off the mean — deterministic AND fair.")
    print()
    return random_run["flicker_pct"], hashed_run["flicker_pct"], dev


# --------------------------------------------------------------------------
# 3 · SALT INDEPENDENCE
# --------------------------------------------------------------------------

def section_3() -> tuple[float, float]:
    print("== 3 · THE PER-FLAG SALT: OR ONE COHORT IS EVERY EXPERIMENT'S SUBJECT ==")
    n, pct = 50_000, 10.0
    cut = int(pct * 100)
    ids = [f"user-{i:06d}" for i in range(n)]

    def cohort(salt: str) -> set[str]:
        return {u for u in ids if bucket_bp(salt, u) < cut}

    salted_a, salted_b = cohort("checkout_v2"), cohort("new_search_ranker")
    shared = cohort("GLOBAL")          # both flags hashing the user id alone
    unsalted_a = unsalted_b = shared

    def overlap(a: set[str], b: set[str]) -> float:
        return 100.0 * len(a & b) / len(a)

    sal = overlap(salted_a, salted_b)
    uns = overlap(unsalted_a, unsalted_b)
    print(f"  two flags, both at {pct:.0f}%, over {n:,} users")
    print(f"  {'scheme':<34}{'A':>8}{'B':>8}{'A n B':>9}{'overlap':>10}")
    print(f"  {'per-flag salt (sha256(key+id))':<34}{len(salted_a):>8,}"
          f"{len(salted_b):>8,}{len(salted_a & salted_b):>9,}{sal:>9.2f}%")
    print(f"  {'no salt (sha256(id) only)':<34}{len(unsalted_a):>8,}"
          f"{len(unsalted_b):>8,}{len(unsalted_a & unsalted_b):>9,}{uns:>9.2f}%")
    print(f"  each cohort is {100.0 * len(salted_a) / n:.2f}% of {n:,} users — "
          f"the {pct:.0f}% rollout, realised.")
    print(f"  salted, the overlap is {sal:.2f}% — what independence predicts "
          f"({pct:.0f}% of {pct:.0f}%).")
    print(f"  unsalted, it is {uns:.0f}%: the SAME {len(shared):,} people are the "
          f"test subjects for")
    print("  every flag you own. They see each new bug first, every single time,")
    print("  and your experiment results are confounded by every other experiment.")
    print()
    return sal, uns


# --------------------------------------------------------------------------
# 4 · WHAT HAPPENS WHEN THE FLAG SERVICE IS UNREACHABLE
# --------------------------------------------------------------------------

def section_4() -> dict[str, dict[str, int]]:
    print("== 4 · THE FLAG SERVICE GOES AWAY. WHAT DOES YOUR USER SEE? ==")
    total, down_from, down_to = 6_000, 2_000, 4_500
    outage = down_to - down_from

    kill = Flag("recommendations_enabled", "operational", default=True,
                rules=[Rule("on for everyone", {})])
    risky = Flag("new_pricing_engine", "release", default=False,
                 rules=[Rule("ramp", {}, rollout_pct=10.0)])

    def simulate(mode: str, flag: Flag) -> dict[str, int]:
        errors = wrong_on = wrong_off = 0
        for i in range(total):
            uid = f"user-{i:06d}"
            truth, _ = evaluate(flag, {"id": uid})
            reachable = not (down_from <= i < down_to)
            if reachable:
                continue                       # correct by construction
            if mode == "hard":
                errors += 1                    # 500: the flag call IS the request
                continue
            if mode == "open":
                got = True
            elif mode == "closed":
                got = False
            else:                              # cached ruleset, local evaluation
                got = truth
            wrong_on += got and not truth
            wrong_off += truth and not got
        return {"errors": errors, "wrong_on": wrong_on, "wrong_off": wrong_off}

    print(f"  {total:,} requests; the flag service is unreachable for requests "
          f"{down_from:,}-{down_to:,} ({outage:,} requests)")
    print(f"  {'behaviour':<40}{'5xx':>8}{'wrongly ON':>13}{'wrongly OFF':>13}")
    results: dict[str, dict[str, int]] = {}
    rows = [
        ("hard", kill, "network call per eval, no fallback"),
        ("open", kill, "fail-open  on kill switch (correct)"),
        ("closed", kill, "fail-closed on kill switch (WRONG)"),
        ("open", risky, "fail-open  on new risky path (WRONG)"),
        ("closed", risky, "fail-closed on new risky path (correct)"),
        ("cache", risky, "cached ruleset + local evaluation"),
    ]
    for mode, flag, label in rows:
        r = simulate(mode, flag)
        results[label] = r
        print(f"  {label:<40}{r['errors']:>8,}{r['wrong_on']:>13,}"
              f"{r['wrong_off']:>13,}")
    print("  the hard dependency turned someone else's outage into "
          f"{outage:,} of YOUR 5xx.")
    print("  fail-open is right for a kill switch (known-good = feature ON) and")
    print("  catastrophic for a new path — it ships 100% of an unfinished feature.")
    print("  fail-closed is the mirror image. Neither is 'safe'; the safe default is")
    print("  per-flag, and the cached ruleset is wrong 0 times because it still knows")
    print("  the rules — that is why local evaluation beats a per-call network hop.")
    print()
    return results


# --------------------------------------------------------------------------
# 5 · KILL SWITCH VS ROLLBACK, TIMED
# --------------------------------------------------------------------------

def section_5() -> tuple[float, float, float, float]:
    print("== 5 · MITIGATING THE SAME FAILURE TWO WAYS, TIMED ==")
    rate, err_rate = 850.0, 0.041     # req/s hitting the bad path, and its error rate

    flag_stream = [
        ("operator flips the flag in the console", 2.0),
        ("control plane writes + validates the ruleset", 0.4),
        ("streaming push to every SDK (p95 fan-out)", 0.9),
        ("in-process eval cache TTL expires", 1.0),
    ]
    flag_poll = [
        ("operator flips the flag in the console", 2.0),
        ("control plane writes + validates the ruleset", 0.4),
        ("SDK polling interval (worst case)", 30.0),
        ("in-process eval cache TTL expires", 1.0),
    ]
    rollback = [
        ("find the last-good image digest, get approval", 45.0),
        ("trigger the rollout, control plane reconciles", 10.0),
        ("batch 1/4: image pull 25s + start 8s + readiness 15s", 48.0),
        ("batch 1/4: drain old pods (30s deregistration delay)", 30.0),
        ("batch 2/4: pull (cached) 4s + start 8s + readiness 15s", 27.0),
        ("batch 2/4: drain old pods", 30.0),
        ("batch 3/4: start + readiness", 27.0),
        ("batch 3/4: drain old pods", 30.0),
        ("batch 4/4: start + readiness", 27.0),
        ("batch 4/4: drain old pods", 30.0),
    ]

    def show(title: str, stages: Iterable[tuple[str, float]]) -> float:
        print(f"  {title}")
        t = 0.0
        for name, dur in stages:
            t += dur
            print(f"    {dur:>7.1f}s  {name:<52} t+{t:>6.1f}s")
        return t

    t_stream = show("A · flag flip, streaming SDK + local evaluation", flag_stream)
    t_poll = show("B · flag flip, 30 s polling SDK", flag_poll)
    t_roll = show("C · roll back the deploy (12 instances, 4 batches of 3)", rollback)

    print(f"  {'mitigation':<44}{'TTM':>10}{'bad requests':>15}{'errors':>10}")
    out = []
    for label, t in (("flag flip (streaming + local eval)", t_stream),
                     ("flag flip (30 s polling SDK)", t_poll),
                     ("deploy rollback", t_roll)):
        bad = int(rate * t)
        print(f"  {label:<44}{t:>9.1f}s{bad:>15,}{int(bad * err_rate):>10,}")
        out.append(t)
    ratio = t_roll / t_stream
    machine_ratio = (t_roll - rollback[0][1]) / (t_stream - flag_stream[0][1])
    print(f"  time-to-mitigate ratio: rollback is {ratio:.0f}x the flag flip "
          f"({t_roll:.0f}s vs {t_stream:.1f}s).")
    print(f"  at {rate:.0f} req/s that is "
          f"{int(rate * (t_roll - t_stream) * err_rate):,} extra failed requests, and the")
    print("  rollback also reverts every OTHER change in the same artifact.")
    print(f"  subtract the human stage from both ({rollback[0][1]:.0f}s vs "
          f"{flag_stream[0][1]:.0f}s) and the ratio gets WORSE,")
    print(f"  not better: {machine_ratio:.0f}x. The machinery is the cost, not the "
          f"decision.")
    print()
    return t_stream, t_poll, t_roll, ratio


# --------------------------------------------------------------------------
# 6 · FLAG DEBT, QUANTIFIED
# --------------------------------------------------------------------------

def section_6() -> tuple[int, int, int, float]:
    print("== 6 · FLAG DEBT IS ARITHMETIC, NOT AN OPINION ==")
    print(f"  {'live flags N':>13}{'configurations 2^N':>22}{'tested (1+N+pairs)':>21}"
          f"{'you cover 1 in':>17}")
    for n in (5, 10, 20, 30, 40):
        configs = 2 ** n
        tested = 1 + n + n * (n - 1) // 2      # baseline, each flag alone, each pair
        print(f"  {n:>13}{configs:>22,}{tested:>21,}"
              f"{configs // tested:>17,}")
    print("  the pair column is generous — almost nobody tests pairs. Even if you do,")
    print("  at 30 flags you exercise 1 configuration in 2.3 million. Production")
    print("  picks from all of them, one user at a time.")
    print()

    rng = random.Random(SEED)
    kinds = (["release"] * 22) + (["experiment"] * 7) + \
            (["operational"] * 6) + (["permission"] * 5)
    expiry = {"release": 60, "experiment": 90, "operational": None, "permission": None}
    inventory = []
    for i, kind in enumerate(kinds):
        age = rng.choice([3, 9, 15, 22, 34, 48, 61, 77, 96, 130, 190, 260, 410])
        inventory.append(Flag(f"flag_{i:02d}", kind, default=False, age_days=age))
    n = len(inventory)

    print(f"  a real inventory: {n} live flags")
    print(f"  {'kind':<14}{'count':>7}{'expiry':>9}{'past expiry':>13}   "
          f"{'who owns it, and for how long'}")
    removable = 0
    for kind in ("release", "experiment", "operational", "permission"):
        group = [f for f in inventory if f.kind == kind]
        limit = expiry[kind]
        stale = [f for f in group if limit is not None and f.age_days > limit]
        removable += len(stale)
        life = {"release": "feature team, delete after rollout",
                "experiment": "product, life of the test",
                "operational": "whoever is on call, permanent",
                "permission": "permanent — it is business logic"}[kind]
        print(f"  {kind:<14}{len(group):>7}{(str(limit) + 'd' if limit else '--'):>9}"
              f"{len(stale):>13}   {life}")
    kept = n - removable
    oldest = max(f.age_days for f in inventory if f.kind == "release")
    print(f"  {removable} of {n} flags are past their expiry date and are pure debt.")
    print(f"  the oldest release toggle is {oldest} days old — it was 'temporary'.")
    print(f"  removing them: {n} flags -> {kept} flags, "
          f"2^{n} = {2 ** n:,} configurations -> 2^{kept} = {2 ** kept:,}")
    print(f"  that is a {2 ** n / 2 ** kept:,.0f}x reduction in reachable states "
          f"from deleting {removable} if-statements.")
    print(f"  {2 ** n / 2 ** kept:,.0f}x, for work that ships no features and takes an "
          f"afternoon.")
    print()
    return n, kept, removable, 2 ** n / 2 ** kept


def main() -> None:
    section_1()
    rand_flicker, hash_flicker, dev = section_2()
    salted, unsalted = section_3()
    section_4()
    t_stream, t_poll, t_roll, ratio = section_5()
    n, kept, removable, factor = section_6()

    print("== SUMMARY ==")
    print(f"  flicker rate       random {rand_flicker:.2f}%   hashed {hash_flicker:.2f}%")
    print(f"  cohort overlap     salted {salted:.2f}%   unsalted {unsalted:.0f}%")
    print(f"  time to mitigate   flag {t_stream:.1f}s   rollback {t_roll:.0f}s "
          f"({ratio:.0f}x)")
    print(f"  flag debt          {n} flags -> {kept} after expiry "
          f"= {factor:,.0f}x fewer states")


if __name__ == "__main__":
    main()
