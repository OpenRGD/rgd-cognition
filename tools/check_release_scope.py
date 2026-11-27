"""Review-owned exact delta over the immutable RC02A candidate tree.

This is a CI regression guard, not an authorization boundary. Changes to its
manifest require the same independent review as any other source change.
"""
from __future__ import annotations

import json
from pathlib import Path, PurePosixPath
import subprocess

BASE = "b601674bf3a539ce029e1c2253c2ae4b49e291e9"
BASE_TREE = "aec46c865420d0d975fef4ca420e973e8d723ae3"
MODIFIED = frozenset({"README.md", "SECURITY.md", "docs/ROADMAP.md",
                      "tools/check_rc02a_scope.py"})
REQUIRED_ADDITIONS = frozenset({"docs/COG-RC-03C.md", "tools/check_release_scope.py",
    "tools/release-scope.json", "tests_release/test_release_scope.py",
    ".github/workflows/release-readiness.yml"})
PREFIXES = ("docs/", "tools/", "tests_release/", "tests_runtime/", "tests_service/",
            "src/rgd_cognition/", ".github/workflows/")


def _unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("DUPLICATE_MANIFEST_KEY")
        value[key] = item
    return value


def _paths(values):
    if type(values) is not list or len(values) > 128:
        raise ValueError("INVALID_PATH_LIST")
    paths = set()
    for name in values:
        if (type(name) is not str or not name or len(name) > 240 or
                any(c in name for c in ("\\", "\x00", "\n", "\r", "\t")) or
                name.startswith("/") or PurePosixPath(name).as_posix() != name or
                ".." in PurePosixPath(name).parts or name in paths):
            raise ValueError("INVALID_OR_DUPLICATE_PATH")
        paths.add(name)
    return paths


def expected_delta(raw: bytes):
    if type(raw) is not bytes or len(raw) > 32768:
        raise ValueError("MANIFEST_LIMIT")
    manifest = json.loads(raw, object_pairs_hook=_unique_object)
    if (type(manifest) is not dict or
            set(manifest) != {"version", "baseline", "baseline_tree", "modified", "added"} or
            manifest["version"] != "cog-release-scope-v1" or
            manifest["baseline"] != BASE or manifest["baseline_tree"] != BASE_TREE):
        raise ValueError("BASELINE_PIN_MISMATCH")
    modified, added = _paths(manifest["modified"]), _paths(manifest["added"])
    if modified != MODIFIED or not REQUIRED_ADDITIONS <= added or modified & added:
        raise ValueError("REQUIRED_DELTA_MISMATCH")
    for path in added:
        if not path.startswith(PREFIXES) or path.startswith("src/rgd_cognition/schemas/"):
            raise ValueError("ADDITION_OUTSIDE_REVIEW_SCOPE")
    return {("M", p) for p in modified} | {("A", p) for p in added}


def verify_delta(raw, rows, modes):
    expected = expected_delta(raw)
    actual = set(rows)
    if len(actual) != len(rows) or actual != expected:
        raise ValueError("RELEASE_SCOPE_MISMATCH: unexpected=" + str(sorted(actual - expected)) +
                         "; missing=" + str(sorted(expected - actual)))
    if any(modes.get(path) != "100644" for _, path in expected):
        raise ValueError("RELEASE_SCOPE_NONREGULAR_FILE")


def check():
    subprocess.run(["git", "fetch", "--no-tags", "--depth=1", "origin", BASE],
                   check=True, stdout=subprocess.DEVNULL)
    tree = subprocess.check_output(["git", "rev-parse", BASE + "^{tree}"], text=True).strip()
    if tree != BASE_TREE:
        raise SystemExit("RELEASE_BASE_TREE_MISMATCH")
    # The historical candidate itself remains valid without a future manifest.
    # A descendant is checked by its exact reviewed manifest, not by ancestry alone.
    raw = Path(__file__).with_name("release-scope.json").read_bytes()
    data = subprocess.check_output(["git", "diff", "--no-renames", "--name-status", "-z", BASE, "HEAD"])
    fields = data.decode("utf-8").split("\0")[:-1]
    if len(fields) % 2:
        raise SystemExit("INVALID_GIT_DIFF")
    rows = list(zip(fields[::2], fields[1::2]))
    modes = {}
    for entry in subprocess.check_output(["git", "ls-tree", "-r", "-z", "HEAD"]).decode("utf-8").split("\0"):
        if entry:
            header, path = entry.split("\t", 1)
            modes[path] = header.split(" ", 1)[0]
    verify_delta(raw, rows, modes)
    subprocess.run(["git", "diff", "--check", BASE, "HEAD"], check=True)
    print("RELEASE_SCOPE_PASS: fixed RC02A tree + exact reviewed delta; previous runtime/schemas preserved.")


if __name__ == "__main__":
    check()
