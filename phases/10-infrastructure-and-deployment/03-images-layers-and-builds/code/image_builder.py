#!/usr/bin/env python3
"""
A miniature OCI-style image builder, for
phases/10-infrastructure-and-deployment/03-images-layers-and-builds/docs/en.md

Parses a tiny Dockerfile dialect (FROM/RUN/COPY/ENV/CMD), executes each instruction
against an in-memory layer model, content-addresses every layer with hashlib.sha256,
and keeps a layer cache keyed the way a real builder keys one (parent chain + the
instruction + the content it consumes).

Specs: OCI Image Format Specification v1.1 (image-spec) -- manifest, config,
rootfs.diff_ids, layer media types.  Reproducible Builds' SOURCE_DATE_EPOCH convention.

Stdlib only, deterministic, self-terminating.  Every digest and byte count printed
below is computed by hashlib over real bytes; the FILE CONTENTS are synthetic and the
sizes are chosen to match the order of magnitude of a real Python service image.
The per-step wall-clock SECONDS are a MODELLED cost table (see STEP_SECONDS) -- they
are the one thing here that is not measured.
"""

from __future__ import annotations

import hashlib
import json
import random
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple

KIB = 1024
MIB = 1024 * 1024
SOURCE_DATE_EPOCH = 1_700_000_000          # the Reproducible Builds convention

# --------------------------------------------------------------------------- bytes
_BLOBS: Dict[Tuple[str, int], bytes] = {}


def blob(tag: str, n: int) -> bytes:
    """Deterministic pseudo-file content. Same tag + size -> same bytes, always."""
    key = (tag, n)
    b = _BLOBS.get(key)
    if b is None:
        b = hashlib.shake_128(tag.encode("utf-8")).digest(n)
        _BLOBS[key] = b
    return b


def fmt(n: int) -> str:
    if n >= MIB:
        return "%.2f MB" % (n / MIB)
    if n >= KIB:
        return "%.1f KB" % (n / KIB)
    return "%d B" % n


def short(digest: str, n: int = 12) -> str:
    return digest.split(":", 1)[1][:n]


# --------------------------------------------------------------------- layer model
@dataclass(frozen=True)
class Entry:
    path: str
    data: bytes
    mtime: int
    mode: int = 0o644


class Layer:
    """A layer blob: an ordered set of file entries plus whiteouts, addressed by digest.

    The serialization is a stand-in for a tar stream: a header per entry followed by
    its bytes. `size` is the real byte count of that stream, `digest` its sha256 --
    which is exactly what an OCI descriptor and a rootfs.diff_id record.
    """

    __slots__ = ("entries", "whiteouts", "digest", "size")

    def __init__(self, entries: Sequence[Entry], whiteouts: Sequence[str] = ()) -> None:
        self.entries = tuple(entries)
        self.whiteouts = tuple(whiteouts)
        h = hashlib.sha256()
        size = 0
        for e in self.entries:
            hdr = ("%s\x00%o\x00%d\x00%d\x00" % (e.path, e.mode, len(e.data), e.mtime)).encode()
            h.update(hdr)
            h.update(e.data)
            size += len(hdr) + len(e.data)
        for w in self.whiteouts:                       # OCI: .wh.<name> marks a deletion
            hdr = (".wh.%s\x00" % w).encode()
            h.update(hdr)
            size += len(hdr)
        self.digest = "sha256:" + h.hexdigest()
        self.size = size


def merge(layers: Iterable[Layer]) -> Dict[str, Entry]:
    """Stack layers bottom-up into the filesystem the container actually sees.

    Lesson 2 built the copy-up and whiteout behaviour these layers rely on; this is
    just the resulting view.
    """
    fs: Dict[str, Entry] = {}
    for lyr in layers:
        for w in lyr.whiteouts:
            pre = w.rstrip("/") + "/"
            for p in [k for k in fs if k == w or k.startswith(pre)]:
                del fs[p]
        for e in lyr.entries:
            fs[e.path] = e
    return fs


# --------------------------------------------------------------------------- image
@dataclass
class Image:
    layers: List[Layer]
    env: Dict[str, str]
    cmd: List[str]
    workdir: str
    history: List[Dict[str, object]]
    arch: str = "amd64"
    os_: str = "linux"

    def config_bytes(self) -> bytes:
        cfg = {
            "architecture": self.arch,
            "os": self.os_,
            "config": {
                "Env": ["%s=%s" % kv for kv in sorted(self.env.items())],
                "Cmd": self.cmd,
                "WorkingDir": self.workdir,
            },
            "rootfs": {"type": "layers", "diff_ids": [l.digest for l in self.layers]},
            "history": self.history,
        }
        return json.dumps(cfg, sort_keys=True, separators=(",", ":")).encode()

    def manifest_bytes(self) -> bytes:
        cb = self.config_bytes()
        man = {
            "schemaVersion": 2,
            "mediaType": "application/vnd.oci.image.manifest.v1+json",
            "config": {
                "mediaType": "application/vnd.oci.image.config.v1+json",
                "digest": "sha256:" + hashlib.sha256(cb).hexdigest(),
                "size": len(cb),
            },
            "layers": [
                {
                    "mediaType": "application/vnd.oci.image.layer.v1.tar",
                    "digest": l.digest,
                    "size": l.size,
                }
                for l in self.layers
            ],
        }
        return json.dumps(man, sort_keys=True, separators=(",", ":")).encode()

    def digest(self) -> str:
        """The image digest: sha256 of the manifest. This is what `@sha256:...` pins."""
        return "sha256:" + hashlib.sha256(self.manifest_bytes()).hexdigest()

    def total_size(self) -> int:
        return sum(l.size for l in self.layers)


# ------------------------------------------------------------------ the fake world
BASE_ROOTFS: List[Tuple[str, int]] = [
    ("/bin/sh", 125 * KIB),
    ("/etc/passwd", 1_260),
    ("/etc/ssl/certs/ca-certificates.crt", 214 * KIB),
    ("/usr/local/bin/python3.12", 15 * KIB),
    ("/usr/local/lib/libpython3.12.so.1.0", 22 * MIB),
    ("/usr/local/lib/python3.12/stdlib.pack", 18 * MIB),
    ("/usr/lib/x86_64-linux-gnu/libc.so.6", 1_950 * KIB),
    ("/usr/lib/x86_64-linux-gnu/libssl.so.3", 680 * KIB),
    ("/usr/lib/x86_64-linux-gnu/libz.so.1", 112 * KIB),
    ("/var/lib/dpkg/status", 2_100 * KIB),
]

_BASE: List[Layer] = []


def base_layer() -> Layer:
    """`FROM` does not build anything: it pulls a blob someone else already built.
    Its digest is fixed, so nothing in this builder's configuration can change it."""
    if not _BASE:
        _BASE.append(Layer([Entry(p, blob(p, n), SOURCE_DATE_EPOCH) for p, n in sorted(BASE_ROOTFS)]))
    return _BASE[0]


TOOLCHAIN: List[Tuple[str, int]] = [
    ("/usr/bin/gcc-12", 1_320 * KIB),
    ("/usr/libexec/gcc/x86_64-linux-gnu/12/cc1", 52 * MIB),
    ("/usr/libexec/gcc/x86_64-linux-gnu/12/cc1plus", 56 * MIB),
    ("/usr/bin/ld", 6_400 * KIB),
    ("/usr/bin/make", 240 * KIB),
    ("/usr/lib/gcc/x86_64-linux-gnu/12/libgcc.a", 4_800 * KIB),
    ("/usr/include/postgresql/libpq-fe.h", 62 * KIB),
    ("/usr/lib/x86_64-linux-gnu/libpq.a", 2_400 * KIB),
    ("/usr/include/linux/headers.pack", 9_600 * KIB),
    ("/var/lib/apt/lists/deb.debian.org_debian_dists_bookworm_main_binary-amd64_Packages", 21 * MIB),
]

# name -> (default version, uncompressed size in bytes)
PACKAGES: Dict[str, Tuple[str, int]] = {
    "flask": ("3.1.2", 2_150 * KIB),
    "werkzeug": ("3.1.5", 2_400 * KIB),
    "jinja2": ("3.1.6", 1_330 * KIB),
    "markupsafe": ("3.0.3", 92 * KIB),
    "click": ("8.3.0", 1_120 * KIB),
    "psycopg2-binary": ("2.9.10", 5_600 * KIB),
    "sqlalchemy": ("2.0.43", 16_800 * KIB),
    "greenlet": ("3.2.4", 4_200 * KIB),
    "pydantic": ("2.11.9", 3_400 * KIB),
    "pydantic-core": ("2.33.2", 18_200 * KIB),
    "typing-extensions": ("4.15.0", 430 * KIB),
    "annotated-types": ("0.7.0", 62 * KIB),
    "uvicorn": ("0.37.0", 1_430 * KIB),
    "h11": ("0.16.0", 512 * KIB),
    "httpx": ("0.28.1", 2_200 * KIB),
    "httpcore": ("1.0.9", 920 * KIB),
    "anyio": ("4.11.0", 940 * KIB),
    "sniffio": ("1.3.1", 52 * KIB),
    "certifi": ("2025.8.3", 310 * KIB),
    "idna": ("3.10", 736 * KIB),
}

PINNED_REQS = "".join("%s==%s\n" % (n, v) for n, (v, _) in PACKAGES.items())
# The same lockfile with three top-level pins removed. Everything else is identical.
UNPINNED_REQS = "".join(
    ("%s\n" % n) if n in ("flask", "sqlalchemy", "pydantic-core") else ("%s==%s\n" % (n, v))
    for n, (v, _) in PACKAGES.items()
)
BUMPED_REQS = PINNED_REQS.replace("sqlalchemy==2.0.43", "sqlalchemy==2.0.44")

SRC_FILES: List[Tuple[str, int]] = [
    ("src/main.py", 4_820),
    ("src/routes.py", 11_400),
    ("src/models.py", 22_600),
    ("src/db.py", 8_900),
    ("src/config.py", 3_100),
    ("src/serializers.py", 14_800),
    ("src/util.py", 6_400),
    ("src/static/app.css", 96_000),
    ("src/static/app.js", 212_000),
]
NOISE_FILES: List[Tuple[str, int]] = [   # what a context WITHOUT a .dockerignore drags in
    (".git/objects/pack/pack-9f2c.pack", 18 * MIB),
    (".git/index", 640 * KIB),
    (".venv/lib/python3.12/site-packages/blob.pack", 61 * MIB),
    ("src/__pycache__/routes.cpython-312.pyc", 9_200),
    (".env", 412),
]
SECRET = b"-----BEGIN OPENSSH PRIVATE KEY-----\nAAAAdeploy-key-do-not-ship-9f31c0\n-----END-----\n"


class PackageIndex:
    """A package index whose 'latest' moves. `epoch` stands in for the passage of time."""

    def __init__(self, epoch: int = 0) -> None:
        self.epoch = epoch
        self.floated: List[str] = []

    def resolve(self, spec: str) -> Tuple[str, str]:
        name, sep, pin = spec.partition("==")
        if sep:
            return name, pin
        base = PACKAGES[name][0]
        head, _, tail = base.rpartition(".")
        newest = "%s.%d" % (head, int(tail) + self.epoch)
        self.floated.append("%s -> %s" % (name, newest))
        return name, newest


def package_files(name: str, version: str) -> List[Tuple[str, int]]:
    total = PACKAGES[name][1]
    drift = int(version.rpartition(".")[2]) * 1024 if version.rpartition(".")[2].isdigit() else 0
    return [
        ("%s/__init__.py" % name, 4_096),
        ("%s/_speedups.so" % name, total - 4_096 + drift),
    ]


# ------------------------------------------------------------------- the cost model
# MODELLED, not measured: wall-clock seconds each step costs on a warm CI runner.
STEP_SECONDS = {
    "apt": 78.0,          # apt-get update + build-essential + libpq-dev
    "pip": 470.0,         # pip install -r requirements.txt (two packages build from sdist)
    "compileall": 3.2,
    "wheel": 41.0,        # python -m build --wheel
    "rm": 0.4,
    "venv": 470.0,
}
COPY_FIXED_S = 0.010                    # per-layer overhead: create, hash, commit
COPY_RATE = 200 * MIB                   # bytes/second


def copy_seconds(nbytes: int) -> float:
    return COPY_FIXED_S + nbytes / COPY_RATE


# ------------------------------------------------------------------------- builder
@dataclass
class BuildFlags:
    fixed_mtime: bool = True            # SOURCE_DATE_EPOCH instead of the wall clock
    sorted_entries: bool = True         # sort, instead of trusting readdir order
    label: str = ""


@dataclass
class Step:
    instruction: str
    cached: bool
    seconds: float
    layer: Optional[Layer]


@dataclass
class BuildResult:
    image: Image
    steps: List[Step]

    @property
    def seconds(self) -> float:
        return sum(s.seconds for s in self.steps)

    @property
    def layer_steps(self) -> List[Step]:
        return [s for s in self.steps if s.layer is not None]

    @property
    def rebuilt(self) -> List[Step]:
        return [s for s in self.layer_steps if not s.cached]

    @property
    def hits(self) -> int:
        return sum(1 for s in self.layer_steps if s.cached)

    @property
    def bytes_rebuilt(self) -> int:
        return sum(s.layer.size for s in self.rebuilt if s.layer is not None)


class Builder:
    def __init__(
        self,
        flags: BuildFlags = BuildFlags(),
        cache: Optional[Dict[str, Tuple[Optional[Layer], float, dict]]] = None,
        index: Optional[PackageIndex] = None,
        clock: int = 1_752_000_000,
        seed: int = 7,
    ) -> None:
        self.flags = flags
        self.cache = {} if cache is None else cache
        self.index = index or PackageIndex()
        self.clock = clock
        self.rng = random.Random(seed)
        self.stages: Dict[str, Dict[str, Entry]] = {}

    # -- helpers ----------------------------------------------------------------
    def _mtime(self) -> int:
        if self.flags.fixed_mtime:
            return SOURCE_DATE_EPOCH
        self.clock += 1                     # a real build stamps the wall clock
        return self.clock

    def _layer(self, pairs: Sequence[Tuple[str, bytes]], whiteouts: Sequence[str] = ()) -> Layer:
        items = list(pairs)
        if self.flags.sorted_entries:
            items.sort(key=lambda p: p[0])
        else:
            self.rng.shuffle(items)         # stand-in for readdir() order
        return Layer([Entry(p, d, self._mtime()) for p, d in items], sorted(whiteouts))

    # -- RUN effects ------------------------------------------------------------
    def _run_effect(self, cmd: str, fs: Dict[str, Entry]) -> Tuple[List[Tuple[str, bytes]], List[str], float]:
        if cmd.startswith("apt-get update"):
            return [(p, blob(p, n)) for p, n in TOOLCHAIN], [], STEP_SECONDS["apt"]

        if "pip install" in cmd:
            req_path = "/app/requirements.txt"
            if req_path not in fs:
                raise KeyError("pip install ran before %s existed in the image" % req_path)
            prefix = "/opt/venv/lib/python3.12/site-packages" if "venv" in cmd \
                else "/usr/local/lib/python3.12/site-packages"
            out: List[Tuple[str, bytes]] = []
            for line in fs[req_path].data.decode().split():
                name, ver = self.index.resolve(line)
                for fn, size in package_files(name, ver):
                    out.append(("%s/%s" % (prefix, fn), blob("%s-%s/%s" % (name, ver, fn), size)))
            if "--no-cache-dir" not in cmd:      # pip's HTTP cache, left in the layer
                out.append(("/root/.cache/pip/wheels/blob.bin", blob("pipcache", 9_600 * KIB)))
            key = "venv" if "venv" in cmd else "pip"
            return out, [], STEP_SECONDS[key]

        if cmd.startswith("python -m compileall"):
            out = [(p.replace(".py", ".pyc"), blob("pyc:" + p, max(512, len(e.data) * 55 // 100)))
                   for p, e in sorted(fs.items()) if p.endswith(".py") and p.startswith("/app/src")]
            return out, [], STEP_SECONDS["compileall"]

        if cmd.startswith("python -m build"):
            return [("/app/dist/service-1.4.0-py3-none-any.whl", blob("wheel", 2_400 * KIB))], \
                   [], STEP_SECONDS["wheel"]

        if cmd.startswith("rm -rf"):
            return [], [t.rstrip("*").rstrip("/") for t in cmd.split()[2:]], STEP_SECONDS["rm"]

        raise ValueError("unknown RUN: %r" % cmd)

    # -- COPY -------------------------------------------------------------------
    @staticmethod
    def _select(src: str, dst: str, source: Dict[str, bytes]) -> List[Tuple[str, bytes]]:
        out = []
        base = dst.rstrip("/")
        for p in sorted(source):
            if src == ".":
                rel = p
            elif p == src:
                out.append((base, source[p]))
                continue
            elif p.startswith(src.rstrip("/") + "/"):
                rel = p[len(src.rstrip("/")) + 1:]
            else:
                continue
            out.append(("%s/%s" % (base, rel), source[p]))
        return out

    # -- the build loop ---------------------------------------------------------
    def build(self, dockerfile: str, context: Dict[str, bytes]) -> BuildResult:
        chain = ""
        layers: List[Layer] = []
        steps: List[Step] = []
        env: Dict[str, str] = {}
        cmd: List[str] = []
        workdir = "/"
        history: List[Dict[str, object]] = []
        stage_name = ""

        for raw in dockerfile.strip().splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            op, _, arg = line.partition(" ")
            op = op.upper()
            arg = arg.strip()

            if op == "FROM" and layers:                 # a new stage begins
                self.stages[stage_name] = merge(layers)
                chain, layers, env, cmd, workdir, history = "", [], {}, [], "/", []

            # ---- cache key: the parent chain, the instruction, and its inputs ----
            payload: List[Tuple[str, bytes]] = []
            whiteouts: List[str] = []
            input_key = ""
            if op == "COPY":
                parts = arg.split()
                if parts[0].startswith("--from="):
                    stage = parts[0].split("=", 1)[1]
                    src, dst = parts[1], parts[2]
                    source = {p: e.data for p, e in self.stages[stage].items()}
                    sel = self._select(src, dst, source)
                    sel = [(p, d) for p, d in sel] if sel else \
                          [(p.replace(src.rstrip("/"), dst.rstrip("/"), 1), e.data)
                           for p, e in sorted(self.stages[stage].items())
                           if p == src or p.startswith(src.rstrip("/") + "/")]
                else:
                    src, dst = parts[0], parts[1]
                    sel = self._select(src, dst, context)
                payload = sel
                h = hashlib.sha256()
                for p, d in sorted(sel):
                    h.update(p.encode())
                    h.update(hashlib.sha256(d).digest())
                input_key = h.hexdigest()

            chain = hashlib.sha256(("%s\n%s\n%s" % (chain, line, input_key)).encode()).hexdigest()

            if chain in self.cache:
                lyr, secs, delta = self.cache[chain]
                steps.append(Step(line, True, 0.0, lyr))
                if lyr is not None:
                    layers.append(lyr)
                env.update(delta.get("env", {}))
                if "cmd" in delta:
                    cmd = list(delta["cmd"])
                if "workdir" in delta:
                    workdir = delta["workdir"]
                history.append({"created_by": line, "empty_layer": lyr is None})
                continue

            # ---- cache miss: actually execute ----
            delta: Dict[str, object] = {}
            secs = 0.0
            lyr = None
            if op == "FROM":
                name = arg.split(" AS ")[0].strip()
                stage_name = arg.split(" AS ")[1].strip() if " AS " in arg else ""
                lyr = base_layer()
                delta["env"] = {"PATH": "/usr/local/bin:/usr/bin:/bin", "PYTHON_VERSION": "3.12.7"}
                delta["workdir"] = "/"
                secs = 0.0                              # already in the local store
                _ = name
            elif op == "RUN":
                payload, whiteouts, secs = self._run_effect(arg, merge(layers))
                lyr = self._layer(payload, whiteouts)
            elif op == "COPY":
                lyr = self._layer(payload)
                secs = copy_seconds(sum(len(d) for _, d in payload))
            elif op == "ENV":
                k, _, v = arg.partition("=")
                delta["env"] = {k.strip(): v.strip()}
            elif op == "CMD":
                delta["cmd"] = json.loads(arg)
            elif op == "WORKDIR":
                delta["workdir"] = arg
            else:
                raise ValueError("unknown instruction %r" % op)

            self.cache[chain] = (lyr, secs, delta)
            steps.append(Step(line, False, secs, lyr))
            if lyr is not None:
                layers.append(lyr)
            env.update(delta.get("env", {}))
            if "cmd" in delta:
                cmd = list(delta["cmd"])
            if "workdir" in delta:
                workdir = delta["workdir"]
            history.append({"created_by": line, "empty_layer": lyr is None})

        return BuildResult(Image(layers, env, cmd, workdir, history), steps)


# ------------------------------------------------------------------------ contexts
def context(reqs: str = PINNED_REQS, src_bump: int = 0, noise: bool = False,
            secret: bool = False) -> Dict[str, bytes]:
    ctx: Dict[str, bytes] = {"requirements.txt": reqs.encode()}
    for p, n in SRC_FILES:
        tag = p if (src_bump == 0 or p != "src/routes.py") else "%s#edit%d" % (p, src_bump)
        ctx[p] = blob(tag, n)
    if noise:
        for p, n in NOISE_FILES:
            ctx[p] = blob(p, n)
    if secret:
        ctx["deploy_key"] = SECRET
    return ctx


# ----------------------------------------------------------------------- pipelines
DOCKERFILE_DEPS_FIRST = """
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends build-essential libpq-dev
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt
COPY src /app/src
RUN python -m compileall -q /app/src
ENV PORT=8080
CMD ["python", "/app/src/main.py"]
"""

DOCKERFILE_SOURCE_FIRST = """
FROM python:3.12-slim
COPY . /app
RUN apt-get update && apt-get install -y --no-install-recommends build-essential libpq-dev
RUN pip install --no-cache-dir -r /app/requirements.txt
RUN python -m compileall -q /app/src
ENV PORT=8080
CMD ["python", "/app/src/main.py"]
"""

DOCKERFILE_SINGLE_STAGE = """
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends build-essential libpq-dev
COPY deploy_key /tmp/deploy_key
COPY requirements.txt /app/requirements.txt
RUN pip install -r /app/requirements.txt
COPY src /app/src
RUN python -m build --wheel -o /app/dist
RUN rm -rf /tmp/deploy_key /root/.cache/pip /var/lib/apt/lists/
CMD ["python", "/app/src/main.py"]
"""

DOCKERFILE_MULTI_STAGE = """
FROM python:3.12-slim AS builder
RUN apt-get update && apt-get install -y --no-install-recommends build-essential libpq-dev
COPY requirements.txt /app/requirements.txt
RUN python -m venv /opt/venv && /opt/venv/bin/pip install --no-cache-dir -r /app/requirements.txt
COPY src /app/src
RUN python -m build --wheel -o /app/dist
FROM python:3.12-slim
COPY --from=builder /opt/venv /opt/venv
COPY --from=builder /app/dist /app/dist
ENV PATH=/opt/venv/bin:/usr/local/bin:/usr/bin:/bin
CMD ["python", "-m", "service"]
"""


def rule(title: str) -> None:
    print("\n== %s ==" % title)


# ------------------------------------------------------------------------ 1 · what
def section1() -> None:
    rule("1 · AN IMAGE IS A MANIFEST, A CONFIG AND A LIST OF TARBALLS")
    res = Builder().build(DOCKERFILE_DEPS_FIRST, context())
    img = res.image

    print("  manifest (OCI image-spec v1.1, application/vnd.oci.image.manifest.v1+json):")
    man = json.loads(img.manifest_bytes())
    print("    config   %s  %s" % (man["config"]["digest"][:26] + "...", fmt(man["config"]["size"])))
    for i, d in enumerate(man["layers"]):
        print("    layer %d  %s  %10s" % (i, d["digest"][:26] + "...", fmt(d["size"])))
    print("  image digest (what `@sha256:` pins, and what lesson 4 pushes to a registry):")
    print("    %s" % img.digest())

    print("\n  config blob -> the recipe half. No file bytes live here:")
    cfg = json.loads(img.config_bytes())
    print("    Env         %s" % cfg["config"]["Env"])
    print("    Cmd         %s" % cfg["config"]["Cmd"])
    print("    rootfs.diff_ids  (ordered, and the order is load-bearing)")
    for i, d in enumerate(cfg["rootfs"]["diff_ids"]):
        print("      %d  %s" % (i, d[:33] + "..."))

    print("\n  the build, step by step (this is `docker history`, bottom-up):")
    print("    %-4s %-13s %11s  %s" % ("#", "LAYER", "SIZE", "CREATED BY"))
    n = 0
    for s in res.steps:
        if s.layer is None:
            print("    %-4s %-13s %11s  %s" % ("-", "<no layer>", "0 B", s.instruction[:52]))
            continue
        print("    %-4d %-13s %11s  %s" % (n, short(s.layer.digest), fmt(s.layer.size),
                                           s.instruction[:52]))
        n += 1

    fs = merge(img.layers)
    print("\n  merged filesystem: %d files, %s" % (len(fs), fmt(sum(len(e.data) for e in fs.values()))))
    print("  image total (sum of layer blobs): %s across %d layers" % (fmt(img.total_size()),
                                                                       len(img.layers)))
    print("  6 filesystem layers, 8 instructions: ENV and CMD change the config only.")


# ------------------------------------------------------------------- 2 · the cache
HEAD = "    %-18s %7s %6s %8s %14s %13s" % ("ordering", "layers", "hit", "rebuilt",
                                            "bytes rebuilt", "sim time")


def _report(tag: str, res: BuildResult) -> None:
    print("    %-18s %7d %6d %8d %14s %11.2f s" % (
        tag, len(res.layer_steps), res.hits, len(res.rebuilt),
        fmt(res.bytes_rebuilt), res.seconds))


def _which(res: BuildResult) -> str:
    return ", ".join(" ".join(s.instruction.split()[:2]) for s in res.rebuilt)


def section2() -> None:
    rule("2 · INSTRUCTION ORDER IS A PERFORMANCE DECISION (THE CACHE CASCADE)")
    print("  Same application, same base, same lockfile. The only difference is WHERE")
    print("  the source is copied relative to the dependency install.")
    print("  Both builds use the same .dockerignore, so the contexts are byte-identical.")

    cache_a: Dict[str, Tuple[Optional[Layer], float, dict]] = {}
    cache_b: Dict[str, Tuple[Optional[Layer], float, dict]] = {}
    mk = lambda c: Builder(cache=c)

    cold_a = mk(cache_a).build(DOCKERFILE_DEPS_FIRST, context())
    cold_b = mk(cache_b).build(DOCKERFILE_SOURCE_FIRST, context())

    print("\n  a) COLD BUILD (empty cache)")
    print(HEAD)
    _report("A deps-first", cold_a)
    _report("B source-first", cold_b)
    print("    identical work; A is %.3f s slower -- it writes one extra layer."
          % (cold_a.seconds - cold_b.seconds))

    edit_a = mk(cache_a).build(DOCKERFILE_DEPS_FIRST, context(src_bump=1))
    edit_b = mk(cache_b).build(DOCKERFILE_SOURCE_FIRST, context(src_bump=1))

    print("\n  b) ONE-LINE EDIT to src/routes.py, rebuild both")
    print(HEAD)
    _report("A deps-first", edit_a)
    _report("B source-first", edit_b)
    print("    A rebuilt: %s" % _which(edit_a))
    print("    B rebuilt: %s" % _which(edit_b))
    ratio_edit = edit_b.seconds / edit_a.seconds
    print("    -> %.1f s vs %.1f s  =  %.1fx.  bytes rebuilt %s vs %s  =  %.0fx."
          % (edit_a.seconds, edit_b.seconds, ratio_edit,
             fmt(edit_a.bytes_rebuilt), fmt(edit_b.bytes_rebuilt),
             edit_b.bytes_rebuilt / edit_a.bytes_rebuilt))
    print("    B's COPY . missed, and EVERY later layer was invalidated with it.")

    dep_a = mk(cache_a).build(DOCKERFILE_DEPS_FIRST, context(reqs=BUMPED_REQS, src_bump=1))
    dep_b = mk(cache_b).build(DOCKERFILE_SOURCE_FIRST, context(reqs=BUMPED_REQS, src_bump=1))

    print("\n  c) ONE-LINE LOCKFILE BUMP (sqlalchemy 2.0.43 -> 2.0.44), rebuild both")
    print(HEAD)
    _report("A deps-first", dep_a)
    _report("B source-first", dep_b)
    ratio_dep = dep_b.seconds / dep_a.seconds
    print("    A rebuilt: %s" % _which(dep_a))
    print("    -> %.1f s vs %.1f s = %.2fx. A's advantage collapsed from %.1fx to %.2fx:"
          % (dep_a.seconds, dep_b.seconds, ratio_dep, ratio_edit, ratio_dep))
    print("    no ordering can save you when the thing you changed feeds the expensive step.")

    print("\n  d) THE HONEST TRADE: it is a bet on how often you touch the lockfile.")
    print("    100 builds/week, varying the share that are dependency changes:")
    print("    %-14s %14s %14s %8s" % ("dep-change %", "A total", "B total", "A wins by"))
    for pct in (0, 5, 10, 25, 50, 100):
        deps = pct
        code = 100 - pct
        ta = code * edit_a.seconds + deps * dep_a.seconds
        tb = code * edit_b.seconds + deps * dep_b.seconds
        print("    %-14s %11.1f min %11.1f min %7.1fx" % ("%d%%" % pct, ta / 60, tb / 60, tb / ta))
    print("    At 5%%  the good ordering saves %.1f hours of CI time per week."
          % ((95 * edit_b.seconds + 5 * dep_b.seconds
              - 95 * edit_a.seconds - 5 * dep_a.seconds) / 3600))
    print("    At 100%% it saves %.1f hours -- and if a bot bumps your lockfile on every"
          % ((100 * dep_b.seconds - 100 * dep_a.seconds) / 3600))
    print("    build, that is the number you actually get. Reach for a cache mount instead.")

    noisy = mk({}).build(DOCKERFILE_SOURCE_FIRST, context(noise=True))
    clean = cold_b
    print("\n  e) AND THE .dockerignore, measured on the same COPY . instruction:")
    print("    with .dockerignore     COPY . layer = %10s" % fmt(clean.steps[1].layer.size))
    print("    without .dockerignore  COPY . layer = %10s   (.git, .venv, __pycache__, .env)"
          % fmt(noisy.steps[1].layer.size))
    print("    %.0fx bigger, and .env went into a layer that anyone who pulls the image can read."
          % (noisy.steps[1].layer.size / clean.steps[1].layer.size))


# ----------------------------------------------------------- 3 · non-determinism
def _twice(flags_maker: Callable[[int], BuildFlags], reqs: str) -> Tuple[List[str], List[List[str]], List[str]]:
    digests, per_layer, floated = [], [], []
    for i in (1, 2):
        idx = PackageIndex(epoch=i)
        b = Builder(flags=flags_maker(i), cache={}, index=idx,
                    clock=1_752_000_000 + i * 3_600, seed=7 + i)
        res = b.build(DOCKERFILE_DEPS_FIRST, context(reqs=reqs))
        digests.append(res.image.digest())
        per_layer.append([l.digest for l in res.image.layers])
        floated = idx.floated
    return digests, per_layer, floated


def _divergence(a: List[str], b: List[str]) -> str:
    bad = [str(i) for i, (x, y) in enumerate(zip(a, b)) if x != y]
    return "layers " + ",".join(bad) if bad else "IDENTICAL"


def section3() -> None:
    rule("3 · SAME SOURCE, DIFFERENT IMAGE: NON-DETERMINISM, THEN A FIXED DIGEST")
    print("  Two builds of the identical Dockerfile and the identical source tree.")
    print("  Each run gets a fresh cache, so every layer is genuinely re-executed.")

    variants = [
        ("as people write it", lambda i: BuildFlags(fixed_mtime=False, sorted_entries=False),
         UNPINNED_REQS, "wall-clock mtimes + readdir order + unpinned versions"),
        ("mtimes only", lambda i: BuildFlags(fixed_mtime=False, sorted_entries=True),
         PINNED_REQS, "the build stamps time.time() into every file header"),
        ("entry order only", lambda i: BuildFlags(fixed_mtime=True, sorted_entries=False),
         PINNED_REQS, "readdir() order differs; the tar stream differs"),
        ("unpinned deps only", lambda i: BuildFlags(fixed_mtime=True, sorted_entries=True),
         UNPINNED_REQS, "3 of 20 requirements have no ==pin"),
        ("all three normalised", lambda i: BuildFlags(fixed_mtime=True, sorted_entries=True),
         PINNED_REQS, "SOURCE_DATE_EPOCH + sorted entries + a full lockfile"),
    ]

    print("\n    %-22s %-14s %-14s %-18s %s" % ("variant", "build 1", "build 2",
                                                "layers that differ", "cause"))
    final = None
    for name, mk_flags, reqs, cause in variants:
        digests, per_layer, floated = _twice(mk_flags, reqs)
        print("    %-22s %-14s %-14s %-18s %s" % (
            name, short(digests[0]), short(digests[1]),
            _divergence(per_layer[0], per_layer[1]), cause))
        if name == "unpinned deps only":
            print("        the index moved under us: %s" % ", ".join(floated))
        if name == "all three normalised":
            final = digests

    print("\n  the two normalised builds, in full:")
    print("    build 1  %s" % final[0])
    print("    build 2  %s" % final[1])
    print("    equal:   %s" % (final[0] == final[1]))
    print("\n  layer 0 never moves: FROM pulls a blob someone else already built.")
    print("  mtimes and entry order poison EVERY layer this build produces; an unpinned")
    print("  version poisons only the dependency layer -- but that is the layer everything")
    print("  downstream is stacked on. And a RUN's cache key is the COMMAND STRING, not")
    print("  its result, so `pip install flask` is a cache HIT that can install a different")
    print("  flask on a different machine. Non-determinism and caching hide each other.")


# --------------------------------------------------------------------- 4 · size
def section4() -> None:
    rule("4 · SIZE: THE DELETION TRAP AND THE MULTI-STAGE FIX")
    single = Builder(cache={}).build(DOCKERFILE_SINGLE_STAGE, context(secret=True))
    img = single.image

    print("  single-stage build, layer by layer:")
    print("    %-4s %-13s %11s  %s" % ("#", "LAYER", "SIZE", "CREATED BY"))
    n = 0
    for s in single.steps:
        if s.layer is None:
            continue
        print("    %-4d %-13s %11s  %s" % (n, short(s.layer.digest), fmt(s.layer.size),
                                           s.instruction[:56]))
        n += 1

    before = merge(img.layers[:-1])
    after = merge(img.layers)
    b_bytes = sum(len(e.data) for e in before.values())
    a_bytes = sum(len(e.data) for e in after.values())
    rm_layer = img.layers[-1]

    print("\n  the `rm -rf` step, measured on both sides of the mount:")
    print("    merged filesystem BEFORE rm   %6d files   %10s" % (len(before), fmt(b_bytes)))
    print("    merged filesystem AFTER  rm   %6d files   %10s   (-%s)"
          % (len(after), fmt(a_bytes), fmt(b_bytes - a_bytes)))
    print("    image total BEFORE rm                        %10s"
          % fmt(sum(l.size for l in img.layers[:-1])))
    print("    image total AFTER  rm                        %10s   (+%s)"
          % (fmt(img.total_size()), fmt(rm_layer.size)))
    print("    deleting %s of files made the image %s BIGGER."
          % (fmt(b_bytes - a_bytes), fmt(rm_layer.size)))
    print("    the rm layer is %d whiteout markers and zero reclaimed bytes." % len(rm_layer.whiteouts))

    print("\n  and the part that ends careers -- the secret is still in the blob:")
    print("    /tmp/deploy_key in the merged filesystem: %s" % ("/tmp/deploy_key" in after))
    for i, lyr in enumerate(img.layers):
        for e in lyr.entries:
            if e.path == "/tmp/deploy_key":
                print("    /tmp/deploy_key in layer %d (%s), %d bytes, readable by anyone"
                      % (i, short(lyr.digest), len(e.data)))
                print("    recovered from the layer blob: %r"
                      % e.data.decode().splitlines()[1])

    multi = Builder(cache={}).build(DOCKERFILE_MULTI_STAGE, context())
    final = multi.image
    print("\n  the multi-stage fix -- the toolchain never enters the final stage:")
    print("    %-9s %-13s %11s  %s" % ("STAGE", "LAYER", "SIZE", "CREATED BY"))
    stage, n = "builder", 0
    for s in multi.steps:
        if s.layer is None:
            continue
        if s.instruction.startswith("FROM") and n:
            stage, n = "FINAL", 0
        print("    %-9s %-13s %11s  %s" % ("%s %d" % (stage, n), short(s.layer.digest),
                                           fmt(s.layer.size), s.instruction[:52]))
        n += 1
    print("      the builder stage is thrown away: only what a COPY --from names survives.")
    print("      note that the venv layer keeps its digest across the copy -- same bytes,")
    print("      same address. Content addressing is what makes a stage boundary cheap.")

    toolchain = sum(n for _, n in TOOLCHAIN)
    builder_layers, seen_from = [], False
    for s in multi.steps:
        if s.layer is None:
            continue
        if s.instruction.startswith("FROM") and seen_from:
            break
        seen_from = True
        builder_layers.append(s.layer)
    print("\n    builder stage total  %10s   %d layers (discarded)"
          % (fmt(sum(l.size for l in builder_layers)), len(builder_layers)))
    print("    single-stage image   %10s   %d layers" % (fmt(img.total_size()), len(img.layers)))
    print("    multi-stage image    %10s   %d layers" % (fmt(final.total_size()), len(final.layers)))
    print("    saved %s  =  %.2fx smaller. The %s toolchain layer and the"
          % (fmt(img.total_size() - final.total_size()),
             img.total_size() / final.total_size(), fmt(toolchain)))
    print("    %s pip cache are never in the final image to be deleted in the first place."
          % fmt(9_600 * KIB))
    fsf = merge(final.layers)
    print("    final merged filesystem: %d files, %s -- no gcc, no headers, no source."
          % (len(fsf), fmt(sum(len(e.data) for e in fsf.values()))))


def main() -> None:
    t0 = time.perf_counter()
    print("miniature OCI image builder -- stdlib only, seeded, in-memory")
    print("file contents are synthetic; every digest and byte count is real sha256 work.")
    print("per-step SECONDS are a modelled cost table, not a measurement.")
    section1()
    section2()
    section3()
    section4()
    print("\n(total wall time %.1f s)" % (time.perf_counter() - t0))


if __name__ == "__main__":
    main()
