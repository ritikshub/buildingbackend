#!/usr/bin/env python3
"""Config, Environments & the Twelve-Factor App -- runnable companion.

Lesson: phases/10-infrastructure-and-deployment/05-config-and-twelve-factor/docs/en.md
Sources: the twelve-factor app manifesto (https://12factor.net), factors III (Config),
V (Build, release, run), IX (Disposability), X (Dev/prod parity), XI (Logs).
Builds a layered config resolver with provenance, typed fail-fast validation, secret
redaction, deterministic release identities, and an environment parity checker.
Standard library only. Deterministic (random.Random(7)). Self-terminating, ~1 s.
"""

from __future__ import annotations

import difflib
import hashlib
import random
import time
from dataclasses import dataclass, field as dc_field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

# --------------------------------------------------------------------------------------
# The layers, in precedence order. Later layers win. This order is the contract; it is
# printed by --config-provenance so nobody has to guess at 03:00.
# --------------------------------------------------------------------------------------
LAYERS: Tuple[str, ...] = ("default", "file", "env", "cli")

_MISSING = object()


# --------------------------------------------------------------------------------------
# 1 · SCHEMA
# --------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Field:
    """One configuration key: its type, its bounds, and whether it is a secret."""

    name: str
    type: str                       # "int" | "float" | "bool" | "str"
    default: Any = _MISSING
    required: bool = False
    choices: Optional[Sequence[str]] = None
    minimum: Optional[float] = None
    maximum: Optional[float] = None
    min_len: Optional[int] = None
    secret: bool = False
    doc: str = ""

    @property
    def has_default(self) -> bool:
        return self.default is not _MISSING


SCHEMA: Tuple[Field, ...] = (
    Field("PORT", "int", default=8080, minimum=1, maximum=65535,
          doc="TCP port the HTTP server binds"),
    Field("LOG_LEVEL", "str", default="info",
          choices=("debug", "info", "warn", "error"), doc="minimum level emitted"),
    Field("REGION", "str", required=True,
          choices=("us-east-1", "eu-west-1", "ap-south-1"), doc="deployment region"),
    Field("DB_POOL_SIZE", "int", default=10, minimum=1, maximum=200,
          doc="max open database connections"),
    Field("REQUEST_TIMEOUT_MS", "int", default=3000, minimum=50, maximum=30000,
          doc="per-request deadline handed to downstream calls"),
    Field("RETRY_BUDGET_PCT", "float", default=10.0, minimum=0.0, maximum=100.0,
          doc="retries allowed as a percentage of real traffic"),
    Field("CACHE_TTL_S", "int", default=60, minimum=0, maximum=86400,
          doc="response cache time-to-live"),
    Field("MAX_UPLOAD_MB", "int", default=25, minimum=1, maximum=1024,
          doc="largest accepted request body"),
    Field("FEATURE_NEW_CHECKOUT", "bool", default=False,
          doc="serve the rewritten checkout flow"),
    Field("TRUSTED_PROXY_CIDRS", "str", default="",
          doc="comma-separated CIDRs whose X-Forwarded-For we believe"),
    Field("DATABASE_URL", "str", required=True, secret=True, min_len=12,
          doc="primary database DSN, including credentials"),
    Field("SESSION_SIGNING_KEY", "str", required=True, secret=True, min_len=32,
          doc="HMAC key for session cookies"),
)

BY_NAME: Dict[str, Field] = {f.name: f for f in SCHEMA}


# --------------------------------------------------------------------------------------
# 2 · TYPED COERCION -- the whole point is that a string from the environment is not
#     a value until it has been parsed and checked.
# --------------------------------------------------------------------------------------
_TRUE = {"1", "true", "t", "yes", "y", "on"}
_FALSE = {"0", "false", "f", "no", "n", "off"}


class CoercionError(ValueError):
    """Raised with a message that never contains the offending value."""


def coerce(field: Field, raw: str) -> Any:
    """Parse a raw string into the field's declared type. Never echoes a secret."""
    text = raw.strip()
    if field.type == "int":
        try:
            return int(text, 10)
        except ValueError:
            raise CoercionError("expected an integer") from None
    if field.type == "float":
        try:
            return float(text)
        except ValueError:
            raise CoercionError("expected a number") from None
    if field.type == "bool":
        low = text.lower()
        if low in _TRUE:
            return True
        if low in _FALSE:
            return False
        raise CoercionError("expected one of true/false/1/0/yes/no/on/off")
    return text


def validate(field: Field, value: Any) -> None:
    """Range, enum and length checks. Messages are safe to print for secrets."""
    if field.choices is not None and value not in field.choices:
        raise CoercionError("not one of %s" % ("|".join(field.choices),))
    if field.minimum is not None and value < field.minimum:
        raise CoercionError("below minimum %s" % (field.minimum,))
    if field.maximum is not None and value > field.maximum:
        raise CoercionError("above maximum %s" % (field.maximum,))
    if field.min_len is not None and len(str(value)) < field.min_len:
        # Length, not content. A secret's own value never enters an error string.
        raise CoercionError("length %d, minimum %d" % (len(str(value)), field.min_len))


# --------------------------------------------------------------------------------------
# 3 · REDACTION -- a secret is delivered like config and handled like a secret.
#     The fingerprint lets you compare two environments without revealing either.
# --------------------------------------------------------------------------------------
def fingerprint(value: Any) -> str:
    return hashlib.sha256(str(value).encode()).hexdigest()[:8]


def display(field: Field, value: Any) -> str:
    if field.secret:
        return "<redacted sha256:%s>" % fingerprint(value)
    if value == "":
        return "(empty)"
    return str(value)


# --------------------------------------------------------------------------------------
# 4 · THE RESOLVER
# --------------------------------------------------------------------------------------
@dataclass
class Resolved:
    key: str
    value: Any
    source: str                                  # the layer that won
    shadowed: List[Tuple[str, Any]] = dc_field(default_factory=list)


@dataclass
class Problem:
    key: str
    layer: str
    detail: str
    hint: str = ""


@dataclass
class Environment:
    """One environment's raw config sources, before anything is parsed."""

    name: str
    file: Mapping[str, str] = dc_field(default_factory=dict)
    env: Mapping[str, str] = dc_field(default_factory=dict)
    cli: Mapping[str, str] = dc_field(default_factory=dict)

    def raw_layers(self) -> List[Tuple[str, Mapping[str, str]]]:
        return [("file", self.file), ("env", self.env), ("cli", self.cli)]

    def declared(self) -> Dict[str, str]:
        """key -> the layer that set it, highest precedence wins."""
        out: Dict[str, str] = {}
        for layer, mapping in self.raw_layers():
            for key in mapping:
                out[key] = layer
        return out


class ConfigBootError(Exception):
    def __init__(self, problems: List[Problem]) -> None:
        super().__init__("%d configuration problem(s)" % len(problems))
        self.problems = problems


def resolve(env: Environment) -> Dict[str, Resolved]:
    """Resolve every schema key through the layers. Raise with EVERY problem at once.

    Failing on the first error means one restart per typo. A boot check that reports
    all of them means one restart, total.
    """
    problems: List[Problem] = []
    resolved: Dict[str, Resolved] = {}

    # Unknown keys first: a typo is a key nobody will ever read.
    known = set(BY_NAME)
    for layer, mapping in env.raw_layers():
        for key in mapping:
            if key in known:
                continue
            near = difflib.get_close_matches(key, sorted(known), n=1, cutoff=0.6)
            problems.append(Problem(
                key, layer, "unknown configuration key",
                "did you mean %s?" % near[0] if near else "not in the schema"))

    for field in SCHEMA:
        chain: List[Tuple[str, Any]] = []
        if field.has_default:
            chain.append(("default", field.default))
        bad = False
        for layer, mapping in env.raw_layers():
            if field.name not in mapping:
                continue
            raw = mapping[field.name]
            try:
                value = coerce(field, raw)
                validate(field, value)
            except CoercionError as exc:
                problems.append(Problem(field.name, layer, str(exc),
                                        "declared type %s" % field.type))
                bad = True
                continue
            chain.append((layer, value))
        if bad:
            continue
        if not chain:
            if field.required:
                problems.append(Problem(field.name, "-", "required, and set by no layer",
                                        "expected in %s" % " or ".join(LAYERS[1:])))
            continue
        source, value = chain[-1]
        resolved[field.name] = Resolved(field.name, value, source, chain[:-1])

    if problems:
        raise ConfigBootError(problems)
    return resolved


def render_boot_error(exc: ConfigBootError) -> List[str]:
    """The way a startup error should read: every problem, no secret values."""
    lines = ["FATAL: refusing to start -- %d configuration problem(s)"
             % len(exc.problems)]
    for p in exc.problems:
        lines.append("  [%-4s] %-20s %s" % (p.layer, p.key, p.detail))
        if p.hint:
            lines.append("%s%s" % (" " * 30, p.hint))
    lines.append("  no request was served with this configuration.")
    return lines


# --------------------------------------------------------------------------------------
# 5 · RELEASE IDENTITY -- release = build + config, and it needs its own name.
# --------------------------------------------------------------------------------------
def config_hash(resolved: Mapping[str, Resolved]) -> str:
    """A canonical, order-independent digest of the EFFECTIVE values.

    Secrets are included: rotating a signing key changes the running system, so it
    changes the release. The digest is safe to print; the values never are.
    """
    canonical = "\n".join("%s=%r" % (k, resolved[k].value) for k in sorted(resolved))
    return hashlib.sha256(canonical.encode()).hexdigest()


def release_id(artifact_digest: str, cfg_hash: str) -> str:
    pair = "%s+%s" % (artifact_digest, cfg_hash)
    return "rel-" + hashlib.sha256(pair.encode()).hexdigest()[:12]


# --------------------------------------------------------------------------------------
# 6 · PARITY CHECKER -- runs on the config SOURCES, in CI, before either env boots.
# --------------------------------------------------------------------------------------
@dataclass
class Finding:
    kind: str          # MISSING | SOURCE | TYPE
    key: str
    detail: str


def parity(a: Environment, b: Environment) -> Tuple[List[Finding], List[str]]:
    da, db = a.declared(), b.declared()
    findings: List[Finding] = []
    matching: List[str] = []

    for key in sorted(set(da) | set(db)):
        field = BY_NAME.get(key)
        in_a, in_b = key in da, key in db

        if in_a != in_b:
            present, absent = (a, b) if in_a else (b, a)
            layer = da[key] if in_a else db[key]
            if field is None:
                fallback = "no schema entry -- dead config"
            elif field.has_default:
                fallback = "%s falls back to default %s" % (
                    absent.name, display(field, field.default))
            else:
                fallback = "%s has no default -- it will refuse to boot" % absent.name
            findings.append(Finding(
                "MISSING", key,
                "set in %s (%s), absent in %s; %s"
                % (present.name, layer, absent.name, fallback)))
            continue

        if field is not None:
            va = a.file.get(key, a.env.get(key, a.cli.get(key, "")))
            vb = b.file.get(key, b.env.get(key, b.cli.get(key, "")))
            ta = tb = None
            for text, holder in ((va, "a"), (vb, "b")):
                try:
                    coerce(field, text)
                except CoercionError as exc:
                    if holder == "a":
                        ta = str(exc)
                    else:
                        tb = str(exc)
            if ta or tb:
                broken = a.name if ta else b.name
                findings.append(Finding(
                    "TYPE", key,
                    "declared %s; %s supplies a value that does not parse (%s)"
                    % (field.type, broken, ta or tb)))
                continue

        if da[key] != db[key]:
            findings.append(Finding(
                "SOURCE", key,
                "same key, different layer: %s=%s vs %s=%s"
                % (a.name, da[key], b.name, db[key])))
            continue

        matching.append(key)

    return findings, matching


# --------------------------------------------------------------------------------------
# PRINTING HELPERS
# --------------------------------------------------------------------------------------
def banner(n: int, title: str) -> None:
    print("\n== %d · %s ==" % (n, title))


def provenance_table(resolved: Mapping[str, Resolved]) -> None:
    print("  %-21s %-30s %-8s %s"
          % ("KEY", "EFFECTIVE VALUE", "SOURCE", "SHADOWED (layers that lost)"))
    for key in sorted(resolved):
        r = resolved[key]
        field = BY_NAME[key]
        lost = ", ".join("%s=%s" % (layer, display(field, val))
                         for layer, val in r.shadowed) or "-"
        print("  %-21s %-30s %-8s %s"
              % (key, display(field, r.value), r.source, lost))


# --------------------------------------------------------------------------------------
# THE ENVIRONMENTS
# --------------------------------------------------------------------------------------
ARTIFACT = "sha256:9f2b41c7d0e8a35b6c1f4e92a7d83b05e6c14f7a92d3b8e05c71f4a6d29b8e30"

DEMO = Environment(
    name="demo",
    file={                              # /etc/app/config.toml, baked next to the code
        "LOG_LEVEL": "warn",
        "DB_POOL_SIZE": "25",
        "REQUEST_TIMEOUT_MS": "2000",
        "CACHE_TTL_S": "30",
        "MAX_UPLOAD_MB": "25",
    },
    env={                               # the container's environment
        "PORT": "9090",
        "LOG_LEVEL": "info",
        "REGION": "eu-west-1",
        "REQUEST_TIMEOUT_MS": "1500",
        "DATABASE_URL": "postgres://app:s3cr3t-pw@db.internal:5432/orders",
        "SESSION_SIGNING_KEY": "8f14e45fceea167a5a36dedd4bea2543ab7c9e01",
    },
    cli={                               # flags on the process command line
        "LOG_LEVEL": "debug",
        "DB_POOL_SIZE": "40",
    },
)

STAGING = Environment(
    name="staging",
    file={
        "LOG_LEVEL": "debug",
        "DB_POOL_SIZE": "5",
        "REQUEST_TIMEOUT_MS": "2000",
        "CACHE_TTL_S": "30",
        "MAX_UPLOAD_MB": "25",
    },
    env={
        "REGION": "us-east-1",
        "FEATURE_NEW_CHECKOUT": "true",
        "DATABASE_URL": "postgres://app:staging-pw@db.stg:5432/orders",
        "SESSION_SIGNING_KEY": "1a79a4d60de6718e8e5b326e338ae533ab7c9e01",
    },
)

PRODUCTION = Environment(
    name="production",
    file={
        "LOG_LEVEL": "info",
        "DB_POOL_SIZE": "40",
        "CACHE_TTL_S": "30",
        "MAX_UPLOAD_MB": "25MB",                       # type drift, prod only
        "TRUSTED_PROXY_CIDRS": "10.0.0.0/8",           # prod only
    },
    env={
        "REGION": "eu-west-1",
        "REQUEST_TIMEOUT_MS": "2000",                  # same value, different layer
        "DATABASE_URL": "postgres://app:prod-pw@db.prod:5432/orders",
        "SESSION_SIGNING_KEY": "3c59dc048e8850243be8079a5c74d079ab7c9e01",
    },
)


# --------------------------------------------------------------------------------------
def section_1() -> Dict[str, Resolved]:
    banner(1, "LAYERED RESOLUTION WITH PROVENANCE")
    print("  precedence: " + " -> ".join(LAYERS) + "   (later wins)")
    resolved = resolve(DEMO)
    provenance_table(resolved)
    four = resolved["LOG_LEVEL"]
    print("  LOG_LEVEL was set by %d of the %d layers. The live value is %r, from %s."
          % (len(four.shadowed) + 1, len(LAYERS), four.value, four.source))
    print("  Without this table the only honest answer to 'which value is live?'")
    print("  is to read four files and hope nobody exported anything on the pod.")
    return resolved


def section_2() -> None:
    banner(2, "TYPED, VALIDATED, FAIL-FAST AT BOOT")

    broken = Environment(
        name="broken",
        file={
            "LOG_LEVL": "debug",                 # typo: transposed characters
            "REQUEST_TIMEOUT": "2000",           # typo: wrong key name entirely
            "MAX_UPLOAD_MB": "25MB",             # wrong type
        },
        env={
            "PORT": "eighty",                    # wrong type
            "DB_POOL_SIZE": "4000",              # out of range
            "SESSION_SIGNING_KEY": "hunter2xy",  # secret, too short
            "DATABASE_URL": "postgres://app:prod-pw@db.prod:5432/orders",
        },
    )
    t0 = time.perf_counter()
    try:
        resolve(broken)
        print("  unexpected: the broken config booted")
    except ConfigBootError as exc:
        dt = (time.perf_counter() - t0) * 1000.0
        for line in render_boot_error(exc):
            print("  " + line)
        print("  detected in %.2f ms, before the listening socket was opened."
              % dt)
        print("  one restart reports all %d problems, not the first one."
              % len(exc.problems))

    print()
    print("  the type that bites hardest is bool. Every value from the environment")
    print("  is a string, and every non-empty string is truthy:")
    raw_flag = "false"
    print("    naive : bool(os.environ['FEATURE_NEW_CHECKOUT'])  raw='false'  -> %s"
          % bool(raw_flag))
    print("    typed : coerce(bool, 'false')                                  -> %s"
          % coerce(BY_NAME["FEATURE_NEW_CHECKOUT"], raw_flag))
    print("    the naive form ships a feature you explicitly turned off.")

    print()
    print("  the lazy alternative: read config where you use it, not at boot.")
    rng = random.Random(7)
    total, hits = 50_000, 0
    for _ in range(total):
        if rng.random() < 0.025:            # the refund path reads RETRY_BACKOFF_MS
            hits += 1
    print("    fail-fast : 0 requests served. The process refused to start.")
    print("    lazy      : %d requests served; %d of them took the path that reads"
          % (total, hits))
    print("                the typo'd key. Errors raised: 0. All %d silently used" % hits)
    print("                the fallback 3000 ms instead of the intended 800 ms.")
    print("    a typo that fails at boot costs one deploy. The same typo read lazily")
    print("    costs %d wrong answers and produces no error to find them by." % hits)


def section_3(resolved: Mapping[str, Resolved]) -> None:
    banner(3, "SECRETS: REDACTION ON EVERY PATH, NOT JUST THE HAPPY ONE")
    secret_value = DEMO.env["SESSION_SIGNING_KEY"]
    db_value = DEMO.env["DATABASE_URL"]

    print("  full config dump (the thing an operator curls at 03:00):")
    dump_lines = []
    for key in sorted(resolved):
        field = BY_NAME[key]
        dump_lines.append("    %-21s = %-30s (%s)"
                          % (key, display(field, resolved[key].value),
                             "secret" if field.secret else field.type))
    for line in dump_lines:
        print(line)

    leaky = Environment(
        name="leaky",
        env=dict(DEMO.env, SESSION_SIGNING_KEY="hunter2xy", REGION="eu-west-1"),
        file=dict(DEMO.file),
        cli=dict(DEMO.cli),
    )
    err_lines: List[str] = []
    try:
        resolve(leaky)
    except ConfigBootError as exc:
        err_lines = render_boot_error(exc)
    print()
    print("  the same secret failing validation:")
    for line in err_lines:
        print("  " + line)

    surfaces = {
        "config dump": "\n".join(dump_lines),
        "provenance report": "\n".join(
            "%s %s" % (k, display(BY_NAME[k], resolved[k].value)) for k in resolved),
        "validation error": "\n".join(err_lines),
    }
    print()
    print("  proof -- does the raw secret appear anywhere?")
    for name, blob in surfaces.items():
        leaked = (secret_value in blob) or (db_value in blob) or ("hunter2xy" in blob)
        print("    %-20s raw secret present: %s" % (name, leaked))
    print("  the fingerprint is a sha256 prefix: it survives comparison across")
    print("  environments and reveals nothing. Redaction that covers only the")
    print("  happy path is not redaction; the error path is where secrets leak.")


def section_4(demo_resolved: Mapping[str, Resolved]) -> None:
    banner(4, "BUILD + CONFIG = RELEASE (ONE ARTIFACT, FOUR RELEASES)")
    print("  artifact (immutable, built once in lesson 3):")
    print("    %s" % ARTIFACT)

    staging_cfg = resolve(STAGING)
    prod_env = Environment(
        name="production",
        file=dict(PRODUCTION.file, MAX_UPLOAD_MB="25"),   # type drift repaired
        env=dict(PRODUCTION.env),
    )
    prod_cfg = resolve(prod_env)

    rows = []
    for label, cfg in (("staging", staging_cfg), ("production", prod_cfg)):
        h = config_hash(cfg)
        rows.append((label, h, release_id(ARTIFACT, h)))

    # A config-only change: one integer, nothing rebuilt.
    prod_v2 = Environment(
        name="production",
        file=dict(prod_env.file),
        env=dict(prod_env.env, REQUEST_TIMEOUT_MS="1500"),
    )
    cfg_v2 = resolve(prod_v2)
    h2 = config_hash(cfg_v2)
    rows.append(("production, timeout 2000 -> 1500", h2, release_id(ARTIFACT, h2)))

    # A secret rotation is also a config change, and therefore also a release.
    prod_v3 = Environment(
        name="production",
        file=dict(prod_v2.file),
        env=dict(prod_v2.env,
                 SESSION_SIGNING_KEY="6f4922f45568161a8cdf4ad2299f6d23ab7c9e02"),
    )
    h3 = config_hash(resolve(prod_v3))
    rows.append(("production, signing key rotated", h3, release_id(ARTIFACT, h3)))

    short = ARTIFACT[:23] + ".."
    print()
    print("  %-34s %-20s %s" % ("CONFIG", "CONFIG HASH", "RELEASE ID"))
    for label, h, rid in rows:
        print("  %-34s %-20s %s" % (label, h[:16] + "..", rid))

    print()
    print("  %-34s %-26s %s" % ("RELEASE", "ARTIFACT", "RELEASE ID"))
    for label, _, rid in rows:
        print("  %-34s %-26s %s" % (label, short, rid))
    print("  one artifact, %d release ids, all distinct."
          % len({r[2] for r in rows}))
    print("  release 3 differs from release 2 by one integer (REQUEST_TIMEOUT_MS")
    print("  2000 -> 1500). Release 4 differs by a rotated secret. Nothing was rebuilt.")
    print("  If you version only the artifact, all four collapse to %s," % short)
    print("  and 'roll back' has exactly 1 target where it needs %d."
          % len({r[2] for r in rows}))


def section_5() -> None:
    banner(5, "ENVIRONMENT PARITY: THE DRIFT REPORT")
    t0 = time.perf_counter()
    findings, matching = parity(STAGING, PRODUCTION)
    parity_ms = (time.perf_counter() - t0) * 1000.0
    print("  comparing config SOURCES for staging vs production, in CI, before boot")
    print()
    print("  %-8s %-21s %s" % ("KIND", "KEY", "DETAIL"))
    for f in findings:
        print("  %-8s %-21s %s" % (f.kind, f.key, f.detail))
    counts: Dict[str, int] = {}
    for f in findings:
        counts[f.kind] = counts.get(f.kind, 0) + 1
    print()
    print("  %d findings (%s); %d keys matching (same layer, both environments): %s"
          % (len(findings),
             ", ".join("%s=%d" % (k, counts[k]) for k in sorted(counts)),
             len(matching), ", ".join(matching)))

    print()
    print("  secrets are compared by fingerprint, never by value -- and here you WANT")
    print("  them to differ. A shared signing key across environments is its own bug:")
    for key in ("DATABASE_URL", "SESSION_SIGNING_KEY"):
        fa = fingerprint(STAGING.env[key])
        fb = fingerprint(PRODUCTION.env[key])
        print("    %-21s staging sha256:%s   production sha256:%s   %s"
              % (key, fa, fb, "distinct" if fa != fb else "SHARED -- fix this"))

    print()
    print("  what each finding costs if it ships:")
    print("    MISSING  FEATURE_NEW_CHECKOUT is on in staging and absent in production,")
    print("             so production runs the OLD checkout. Every staging sign-off")
    print("             tested code production is not running.")
    print("    MISSING  TRUSTED_PROXY_CIDRS is set only in production, so the one")
    print("             environment that parses X-Forwarded-For is the one nobody tests.")
    print("    TYPE     MAX_UPLOAD_MB='25MB' parses in nobody's schema. Staging boots,")
    print("             production refuses to start -- discovered during the rollout.")
    print("    SOURCE   REQUEST_TIMEOUT_MS is 2000 in both, but staging reads it from a")
    print("             file and production from the environment. Change the file and")
    print("             production does not move.")

    try:
        resolve(PRODUCTION)
        print("  production booted")
    except ConfigBootError as exc:
        print()
        print("  production, booted for real -- the TYPE finding, discovered the")
        print("  expensive way, during a rollout:")
        for line in render_boot_error(exc):
            print("    " + line)
        print("  the parity checker found the same defect in %.2f ms, in CI, with no"
              % parity_ms)
        print("  cluster, no image pull and no paged engineer involved.")


def main() -> None:
    started = time.perf_counter()
    resolved = section_1()
    section_2()
    section_3(resolved)
    section_4(resolved)
    section_5()
    print("\n  (total wall time %.0f ms)"
          % ((time.perf_counter() - started) * 1000.0))


if __name__ == "__main__":
    main()
