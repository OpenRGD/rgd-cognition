"""COG-02: read-only consumer of the pinned canonical check/boot implementation.

Source integrity is NOT issuer authentication, identity enrollment or safety.
No canonical hash implementation, subprocess, device or network API lives here.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import os
import re
import stat
from tempfile import TemporaryDirectory
from time import monotonic_ns
from typing import Callable

from jsonschema import Draft202012Validator

from .contracts import ContractError, encode, local_digest

CORE_COMMIT = "afe1a831b950a4e6560f0285a0103fc4eaa343b7"
# Code compatibility fingerprints, not signatures or a complete supply-chain proof.
CORE_BLOBS = {
    "profile": "c436ee4cc0fa1bece4b575cdbfc590c0695ff5dc",
    "canonical": "543f4da4754aa74a952aadd0c3a04724d77d0eab",
    "utils": "ed9ed2279b8a75362096a311e608b7e07bdef73d",
}
MAX_FILES = 512
MAX_FILE_BYTES = 1024 * 1024
MAX_TREE_BYTES = 16 * 1024 * 1024
DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")
_SCHEMA = json.loads((Path(__file__).parent / "schemas/rgd-context-v0.2.schema.json").read_text())
Draft202012Validator.check_schema(_SCHEMA)
_VALIDATOR = Draft202012Validator(_SCHEMA)


class ProfileContextError(ValueError):
    """Stable error code only. Never disclose paths, source text or credentials."""


def validate_context(view: dict) -> dict:
    encode(view)
    if next(_VALIDATOR.iter_errors(view), None) is not None:
        raise ContractError("SCHEMA_VIOLATION:RGDContextSlice")
    if view["profile"] is not None and view["source_root"] != view["expected_source_root"]:
        raise ContractError("CONTEXT_SOURCE_CONFLICT")
    unhashed = {k: v for k, v in view.items() if k != "context_revision"}
    if local_digest(unhashed) != view["context_revision"]:
        raise ContractError("CONTEXT_REVISION_MISMATCH")
    return view


def _core_api():
    try:
        from openrgd.core import canonical, profile, utils
    except ImportError:
        raise ProfileContextError("RGD_VERIFIER_UNAVAILABLE") from None
    for name, module in (("profile", profile), ("canonical", canonical), ("utils", utils)):
        try:
            raw = Path(module.__file__).read_bytes()
        except (OSError, TypeError):
            raise ProfileContextError("RGD_TOOLCHAIN_UNVERIFIABLE") from None
        blob = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
        if blob != CORE_BLOBS[name]:
            raise ProfileContextError("RGD_TOOLCHAIN_MISMATCH")
    return canonical, profile, utils


def _capture(spec: Path) -> dict[str, bytes]:
    """Bounded capture; reject links, special files and changed reads.

    Requires an operator-controlled local filesystem. This is not an OS sandbox
    against an attacker concurrently replacing ancestor directories.
    """
    for parent in (spec, *spec.parents):
        if parent.is_symlink():
            raise ProfileContextError("RGD_UNSAFE_PATH")
    if not spec.is_dir():
        raise ProfileContextError("RGD_SOURCE_UNAVAILABLE")
    captured: dict[str, bytes] = {}
    total = entries = 0
    def walk_error(_error):
        raise ProfileContextError("RGD_SOURCE_UNAVAILABLE")
    for directory, dirs, names in os.walk(spec, followlinks=False, onerror=walk_error):
        base = Path(directory)
        if len(base.relative_to(spec).parts) > 12:
            raise ProfileContextError("RGD_SOURCE_LIMIT")
        for name in sorted(dirs + names):
            entries += 1
            if entries > MAX_FILES:
                raise ProfileContextError("RGD_SOURCE_LIMIT")
            path = base / name
            before = path.lstat()
            if stat.S_ISLNK(before.st_mode):
                raise ProfileContextError("RGD_UNSAFE_PATH")
            if stat.S_ISDIR(before.st_mode):
                continue
            if not stat.S_ISREG(before.st_mode):
                raise ProfileContextError("RGD_UNSAFE_PATH")
            if path.suffix != ".jsonc" and path != spec / "MANIFESTO.md":
                continue
            if before.st_size > MAX_FILE_BYTES:
                raise ProfileContextError("RGD_SOURCE_LIMIT")
            flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
            fd = os.open(path, flags)
            with os.fdopen(fd, "rb") as stream:
                opened = os.fstat(stream.fileno())
                if not stat.S_ISREG(opened.st_mode) or (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino):
                    raise ProfileContextError("RGD_SOURCE_CHANGED")
                raw = stream.read(MAX_FILE_BYTES + 1)
                after = os.fstat(stream.fileno())
            if (opened.st_size, opened.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                raise ProfileContextError("RGD_SOURCE_CHANGED")
            total += len(raw)
            if len(raw) > MAX_FILE_BYTES or total > MAX_TREE_BYTES:
                raise ProfileContextError("RGD_SOURCE_LIMIT")
            captured[path.relative_to(spec).as_posix()] = raw
    return captured


def _strict_jsonc(path: Path, utils) -> dict:
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ProfileContextError("RGD_DUPLICATE_KEY")
            result[key] = value
        return result
    def nonfinite(_value):
        raise ProfileContextError("RGD_NONFINITE")
    # Reuse the canonical JSONC stripper; add ambiguity/size guards, not hashing.
    result = json.loads(utils.strip_jsonc(path.read_text(encoding="utf-8")),
                        object_pairs_hook=pairs, parse_constant=nonfinite, strict=False)
    if not isinstance(result, dict):
        raise ProfileContextError("RGD_OBJECT_REQUIRED")
    # Bound depth/node count separately from the much smaller context wire limit.
    stack = [(result, 0)]
    count = 0
    while stack:
        item, depth = stack.pop()
        count += 1
        if depth > 24 or count > 65536:
            raise ProfileContextError("RGD_SOURCE_LIMIT")
        if isinstance(item, dict):
            stack.extend((v, depth + 1) for v in item.values())
        elif isinstance(item, list):
            stack.extend((v, depth + 1) for v in item)
    return result


def _declared_projection(snapshot, grounding: dict, manifest: dict) -> dict:
    modules = {m.ref: m for m in snapshot.modules}
    module_refs = [m.summary() for m in snapshot.modules]
    skills = []
    module = modules.get("03_agency/skills_library.jsonc")
    if module is not None:
        skills_map = module.content.get("skills_map", {})
        if not isinstance(skills_map, dict) or len(skills_map) > 128:
            raise ProfileContextError("RGD_SKILLS_SHAPE")
        for key, record in sorted(skills_map.items()):
            if not isinstance(record, dict) or record.get("skill_id_str") != key or not TOKEN.fullmatch(key):
                raise ProfileContextError("RGD_SKILLS_SHAPE")
            skills.append({
                "capability_id": key, "source_module": module.ref,
                "source_sha256": "sha256:" + module.sha256,
                "declaration": "DECLARED", "installation": "UNKNOWN",
                "physical_verification": "UNKNOWN", "availability": "UNKNOWN",
                "authorization": "NOT_GRANTED",
            })
    meta = manifest.get("meta_group", {})
    if not isinstance(meta, dict):
        raise ProfileContextError("RGD_MANIFEST_SHAPE")
    # Names/descriptions/priors/persona and raw policy text never become prompts.
    return {
        "bundle_id": meta.get("bundle_id_str"),
        "kernel_reference_id": snapshot.robot_id,
        "modules": module_refs,
        "declared_capabilities": skills,
        "policy_declaration_refs": [m.ref for m in snapshot.modules if m.ref.startswith(("02_operation/", "04_volition/"))],
        "described_joints_count": grounding["summary"]["described_joints_count"],
        "source_files_count": snapshot.integrity.files_count,
        "toolchain_commit": CORE_COMMIT,
        "verification_scope": "SOURCE_INTEGRITY_ONLY",
        "issuer_status": "NOT_VERIFIED", "registry_status": "NOT_CHECKED",
        "physical_execution_authorized": False,
    }


def _load_projection(spec: Path, expected_root: str) -> dict:
    canonical, profile, utils = _core_api()
    captured = _capture(spec)
    # Validate an isolated byte snapshot. Never repair or modify the input tree.
    with TemporaryDirectory(prefix="rgd-cog-context-") as temporary:
        staged = Path(temporary) / "spec"
        staged.mkdir()
        for relative, raw in captured.items():
            destination = staged / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(raw)
            destination.chmod(0o600)
        for path in canonical.discover_source_paths(staged):
            if path.suffix == ".jsonc":
                _strict_jsonc(path, utils)
        snapshot = profile.inspect_profile(staged / "00_core/kernel.jsonc")
        # The exact producer functions used by canonical check/boot, not a mock.
        checked = snapshot.validation_payload()
        grounding = profile.build_grounding_context(snapshot)
        if checked["status"] != "VALID" or not snapshot.integrity.matches:
            raise ProfileContextError("RGD_PROFILE_INVALID")
        if snapshot.integrity.computed != expected_root:
            raise ProfileContextError("RGD_ROOT_CONFLICT")
        if grounding["physical_execution"]["authorized"] is not False:
            raise ProfileContextError("RGD_UNEXPECTED_AUTHORITY")
        manifest = _strict_jsonc(staged / "manifest.jsonc", utils)
        projection = _declared_projection(snapshot, grounding, manifest)
    if _capture(spec) != captured:
        raise ProfileContextError("RGD_SOURCE_CHANGED")
    return projection


class RGDContextResolver:
    """Explicit refresh + bounded freshness. Failures discard previous facts.

    Negative binding states are conservatively supplied by the trusted caller;
    positive identity enrollment/verification is intentionally NOT implemented.
    An exported JSON view is informational, not an importable proof or credential.
    """
    def __init__(self, profile_root: str | Path, *, local_alias: str,
                 expected_source_root: str, ttl_ms: int = 60000,
                 binding_status: str = "UNBOUND", clock: Callable[[], int] = monotonic_ns):
        if not isinstance(local_alias, str) or not TOKEN.fullmatch(local_alias):
            raise ValueError("INVALID_LOCAL_ALIAS")
        if not isinstance(expected_source_root, str) or not DIGEST.fullmatch(expected_source_root):
            raise ValueError("INVALID_EXPECTED_ROOT")
        if type(ttl_ms) is not int or not 1 <= ttl_ms <= 3600000:
            raise ValueError("INVALID_CONTEXT_TTL")
        if binding_status not in {"UNBOUND", "UNKNOWN", "STALE", "CONFLICT"}:
            raise ValueError("UNSUPPORTED_IDENTITY_BINDING")
        root = Path(os.path.abspath(profile_root))
        self._spec = root if root.name == "spec" else root / "spec"
        self._alias, self._expected = local_alias, expected_source_root
        self._binding, self._ttl_ns, self._clock = binding_status, ttl_ms * 1000000, clock
        self._last_ns = -1
        self._loaded_ns = None
        self._projection = None
        self._status, self._reason = "UNAVAILABLE", "RGD_NOT_LOADED"

    def _now(self) -> int:
        value = self._clock()
        if type(value) is not int or value < 0 or value < self._last_ns:
            self.invalidate("RGD_CLOCK_INVALID")
            raise ProfileContextError("RGD_CLOCK_INVALID")
        self._last_ns = value
        return value

    def invalidate(self, reason: str = "RGD_INVALIDATED") -> None:
        if reason not in {"RGD_INVALIDATED", "RGD_CLOCK_INVALID", "RGD_HOST_CLOSED"}:
            raise ValueError("INVALID_REASON_CODE")
        self._projection = None
        self._loaded_ns = None
        self._status, self._reason = "STALE", reason

    def refresh(self) -> dict:
        self._projection, self._loaded_ns = None, None
        self._status, self._reason = "INVALID", "RGD_PROFILE_INVALID"
        try:
            self._now()
            projection = _load_projection(self._spec, self._expected)
            loaded = self._now()
            self._projection, self._loaded_ns = projection, loaded
            self._status, self._reason = "SOURCE_INTEGRITY_VERIFIED", None
            return self.read()
        except ProfileContextError as exc:
            code = str(exc)
            self._status = "CONFLICT" if code == "RGD_ROOT_CONFLICT" else "INVALID"
            if code in {"RGD_VERIFIER_UNAVAILABLE", "RGD_SOURCE_UNAVAILABLE"}:
                self._status = "UNAVAILABLE"
            self._reason = code
        except Exception:
            # Redact parser, filesystem and dependency exception text.
            self._status, self._reason = "INVALID", "RGD_PROFILE_INVALID"
        self._projection, self._loaded_ns = None, None
        return self._view()

    def read(self) -> dict:
        now = self._now()
        if self._loaded_ns is not None and now - self._loaded_ns >= self._ttl_ns:
            self.invalidate()
            self._reason = "RGD_CONTEXT_EXPIRED"
        return self._view()

    def _view(self) -> dict:
        valid = self._projection is not None
        unknowns = ["IDENTITY_" + self._binding, "CHRONON_NOT_CONNECTED",
                    "ISSUER_NOT_VERIFIED", "REGISTRY_NOT_CHECKED", "CAPABILITIES_NOT_PHYSICALLY_VERIFIED"]
        if self._reason:
            unknowns.append(self._reason)
        view = {
            "schema_version": "cog_context_slice_v0.2-candidate",
            "local_alias": self._alias,
            "robot_id": None, "life_id": None, "agent_id": None, "persona_id": None,
            "identity_status": self._binding, "reference_status": self._status,
            "source_ref": "urn:openrgd:source:" + self._expected,
            "expected_source_root": self._expected,
            "source_root": self._expected if valid else None,
            "composition_digest": None, "policy_revision": "cog-lab-no-effects-v1",
            "instance_binding_revision": None, "life_binding_epoch": None, "chronon_watermark": None,
            "profile": deepcopy(self._projection), "unknowns": unknowns, "may_actuate": False,
        }
        view["context_revision"] = local_digest(view)
        return validate_context(view)


def main(argv=None) -> int:
    """Operator-invoked local inspection. No service, install, enrollment or writes."""
    import argparse
    parser = argparse.ArgumentParser(description="COG-02 canonical RGD context (non-actuating)")
    parser.add_argument("--profile-root", required=True)
    parser.add_argument("--alias", required=True)
    parser.add_argument("--expected-source-root", required=True)
    arguments = parser.parse_args(argv)
    try:
        resolver = RGDContextResolver(arguments.profile_root, local_alias=arguments.alias,
                                      expected_source_root=arguments.expected_source_root)
        result = resolver.refresh()
    except ValueError:
        print(json.dumps({"status": "INVALID", "reason": "INVALID_CONTEXT_CONFIGURATION"}))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["reference_status"] == "SOURCE_INTEGRITY_VERIFIED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
