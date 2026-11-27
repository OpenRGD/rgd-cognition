"""Offline candidate inventory; hashes prove byte consistency, not publisher trust.

No download, execution, installation, archive extraction or authority assignment.
The caller supplies reviewed wheels and exact Core-B schema bytes.
Filesystem inputs must be trusted and quiescent. Bounded reads and exact
inventory checks do not authenticate a publisher or provide a transactional
snapshot of a filesystem controlled by a concurrent adversary.
"""
from __future__ import annotations

import argparse
import errno
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat

PROFILE = "cog-runtime01c-offline-bundle-v1"
SCHEMA_PATH = "core-b/contracts/kernel/v0.1.0/schemas/kernel-goal-effect.schema.json"
SCHEMA_SHA256 = "f9250f564db290532937ad9f5cbad8f03007f840100bc7c7f40a358f5146ce03"
MAX_BYTES = 128 * 1024 * 1024
MAX_FILES = 32
REQUIRED = {"requirements-ci.txt", "rgd-cog-lab.service", SCHEMA_PATH}


class ArtifactError(ValueError):
    pass


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ArtifactError("DUPLICATE_KEY")
        result[key] = value
    return result


def _file(path: Path, limit=MAX_BYTES):
    # Open the checked object once. O_NONBLOCK prevents a replaced FIFO from
    # blocking before fstat can reject it; O_NOFOLLOW rejects a final symlink.
    fd = None
    try:
        fd = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK)
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_size > limit:
            raise ArtifactError("NONREGULAR_OR_OVERSIZED_FILE")
        remaining, chunks = limit + 1, []
        while remaining:
            block = os.read(fd, min(remaining, 1024 * 1024))
            if not block:
                break
            chunks.append(block)
            remaining -= len(block)
        after = os.fstat(fd)
        current = Path(path).lstat()
        identity = lambda meta: (meta.st_dev, meta.st_ino, meta.st_mode, meta.st_size,
                                 meta.st_mtime_ns, meta.st_ctime_ns)
        data = b"".join(chunks)
        if (len(data) > limit or len(data) != before.st_size or
                identity(before) != identity(after) or identity(after) != identity(current)):
            raise ArtifactError("FILE_CHANGED_OR_OVERSIZED")
        return data
    except OSError as error:
        if error.errno == errno.ELOOP:
            raise ArtifactError("NONREGULAR_OR_OVERSIZED_FILE") from None
        raise ArtifactError("FILE_UNAVAILABLE") from None
    finally:
        if fd is not None:
            os.close(fd)


def _digest(data):
    return hashlib.sha256(data).hexdigest()


def _name(name):
    if (type(name) is not str or len(name) > 240 or
            not re.fullmatch(r"[A-Za-z0-9_./+-]+", name) or
            PurePosixPath(name).as_posix() != name or
            PurePosixPath(name).is_absolute() or ".." in PurePosixPath(name).parts):
        raise ArtifactError("INVALID_PATH")
    return name


def _inventory(root, files):
    # The manifest is validated before walking. Its closed member kinds imply
    # a small finite directory set; never descend into an unlisted directory.
    directories = {parent.as_posix() for name in files for parent in
                   PurePosixPath(name).parents if parent.as_posix() != "."}
    expected_files = set(files) | {"manifest.json"}
    actual_files, actual_directories = set(), set()
    pending, visited = [(Path(root), "")], 0
    maximum = len(expected_files) + len(directories)
    while pending:
        directory, prefix = pending.pop()
        try:
            with os.scandir(directory) as entries:
                for entry in entries:
                    visited += 1
                    if visited > maximum:
                        raise ArtifactError("INVENTORY_MISMATCH")
                    name = prefix + entry.name
                    mode = entry.stat(follow_symlinks=False).st_mode
                    if stat.S_ISDIR(mode):
                        if name not in directories:
                            raise ArtifactError("INVENTORY_MISMATCH")
                        actual_directories.add(name)
                        pending.append((directory / entry.name, name + "/"))
                    elif stat.S_ISREG(mode):
                        if name not in expected_files:
                            raise ArtifactError("INVENTORY_MISMATCH")
                        actual_files.add(name)
                    else:
                        raise ArtifactError("NONREGULAR_MEMBER")
        except OSError:
            raise ArtifactError("INVENTORY_UNAVAILABLE") from None
    if actual_files != expected_files or actual_directories != directories:
        raise ArtifactError("INVENTORY_MISMATCH")


def verify_bundle(root: Path):
    root = Path(root)
    if root.is_symlink() or not root.is_dir():
        raise ArtifactError("INVALID_BUNDLE_ROOT")
    try:
        def nonfinite(_):
            raise ArtifactError("INVALID_MANIFEST")
        manifest = json.loads(_file(root / "manifest.json", 32768),
                              object_pairs_hook=_unique, parse_constant=nonfinite)
    except ArtifactError:
        raise
    except (ValueError, TypeError, RecursionError, UnicodeError):
        raise ArtifactError("INVALID_MANIFEST") from None
    if (type(manifest) is not dict or set(manifest) != {
            "profile", "source_commit", "source_tree", "fixture_only", "files"} or
            manifest["profile"] != PROFILE or manifest["fixture_only"] is not True or
            not all(type(manifest[k]) is str and re.fullmatch(r"[0-9a-f]{40}", manifest[k])
                    for k in ("source_commit", "source_tree")) or
            type(manifest["files"]) is not dict or
            not 4 <= len(manifest["files"]) <= MAX_FILES):
        raise ArtifactError("INVALID_MANIFEST")
    names = set(manifest["files"])
    if not REQUIRED <= names:
        raise ArtifactError("INVENTORY_MISMATCH")
    wheels = []
    total = 0
    for name, expected in manifest["files"].items():
        _name(name)
        if (type(expected) is not dict or set(expected) != {"sha256", "size"} or
                type(expected["size"]) is not int or not 0 <= expected["size"] <= MAX_BYTES or
                type(expected["sha256"]) is not str or not re.fullmatch(r"[0-9a-f]{64}", expected["sha256"])):
            raise ArtifactError("INVALID_INVENTORY_ENTRY")
        if name not in REQUIRED:
            if not re.fullmatch(r"wheelhouse/[A-Za-z0-9_.+-]+\.whl", name):
                raise ArtifactError("UNEXPECTED_MEMBER_KIND")
            wheels.append(name)
        total += expected["size"]
        if total > MAX_BYTES:
            raise ArtifactError("BUNDLE_LIMIT")
    _inventory(root, names)
    total = 0
    for name, expected in manifest["files"].items():
        data = _file(root / name)
        total += len(data)
        if total > MAX_BYTES or len(data) != expected["size"] or _digest(data) != expected["sha256"]:
            raise ArtifactError("CONTENT_MISMATCH")
    if _digest(_file(root / SCHEMA_PATH)) != SCHEMA_SHA256:
        raise ArtifactError("CORE_B_SCHEMA_PIN_MISMATCH")
    if len([w for w in wheels if re.fullmatch(r"wheelhouse/rgd_cognition-0\.1\.0a1-py3-none-any\.whl", w)]) != 1:
        raise ArtifactError("CANDIDATE_WHEEL_MISSING")
    return manifest


def assemble(*, source: Path, wheels: Path, core_b: Path, output: Path,
             source_commit: str, source_tree: str):
    source, wheels, core_b, output = map(Path, (source, wheels, core_b, output))
    if not all(re.fullmatch(r"[0-9a-f]{40}", x) for x in (source_commit, source_tree)):
        raise ArtifactError("INVALID_SOURCE_REFERENCE")
    inputs = {
        "requirements-ci.txt": source / "requirements-ci.txt",
        "rgd-cog-lab.service": source / "tools/runtime01c/rgd-cog-lab.service",
        SCHEMA_PATH: core_b / "contracts/kernel/v0.1.0/schemas/kernel-goal-effect.schema.json",
    }
    for wheel in sorted(wheels.iterdir()):
        if wheel.name.endswith(".whl"):
            inputs["wheelhouse/" + wheel.name] = wheel
    if not 4 <= len(inputs) <= MAX_FILES:
        raise ArtifactError("FILE_COUNT")
    data, total = {}, 0
    for name, path in inputs.items():
        raw = _file(path)
        total += len(raw)
        if total > MAX_BYTES:
            raise ArtifactError("BUNDLE_LIMIT")
        data[_name(name)] = raw
    # Never overwrite an existing bundle or unrelated files.
    output.mkdir(parents=False, exist_ok=False)
    for name, raw in data.items():
        dest = output / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(raw)
    manifest = {"profile": PROFILE, "source_commit": source_commit, "source_tree": source_tree,
                "fixture_only": True, "files": {
                    name: {"sha256": _digest(raw), "size": len(raw)} for name, raw in sorted(data.items())}}
    (output / "manifest.json").write_text(json.dumps(manifest, sort_keys=True, indent=2) + "\n")
    return verify_bundle(output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("assemble")
    for arg in ("source", "wheels", "core-b", "output"):
        create.add_argument("--" + arg, type=Path, required=True)
    for arg in ("source-commit", "source-tree"):
        create.add_argument("--" + arg, required=True)
    check = sub.add_parser("verify")
    check.add_argument("bundle", type=Path)
    args = vars(parser.parse_args())
    command = args.pop("command")
    result = assemble(**args) if command == "assemble" else verify_bundle(args["bundle"])
    print(json.dumps({"status": "CONTENT_CONSISTENCY_PASS", "profile": PROFILE,
                      "source_commit": result["source_commit"], "files": len(result["files"]),
                      "publisher_verified": False, "deployment_authorized": False}, sort_keys=True))


if __name__ == "__main__":
    main()
