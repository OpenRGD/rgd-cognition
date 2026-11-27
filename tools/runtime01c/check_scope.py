"""Exact reviewed 01C delta; no old runtime, schema, version or pin edits."""
from pathlib import Path
import subprocess

BASE = "a2e8690781d9acfa2c134a0ce9722285d0723d57"
MODIFIED = {"tools/check_release_scope.py", "tools/release-scope.json",
            ".github/workflows/runtime-worker.yml"}
ADDED = {
    ".github/workflows/runtime-isolation.yml", "docs/COG-RUNTIME-01C.md",
    "docs/COG-RC-03B-INTEGRATION.md", "src/rgd_cognition/service_lab/__init__.py",
    "src/rgd_cognition/service_lab/__main__.py", "tests_service/test_service_lab.py",
    "tests_service/test_runtime01c_artifact.py", "tools/runtime01c/artifact.py",
    "tools/runtime01c/probe.py", "tools/runtime01c/rehearse.py",
    "tools/runtime01c/rgd-cog-lab.service", "tools/runtime01c/check_scope.py",
}


def check(end="HEAD"):
    subprocess.run(["git", "fetch", "--no-tags", "--depth=1", "origin", BASE], check=True)
    fields = subprocess.check_output(["git", "diff", "--no-renames", "--name-status", "-z", BASE, end]).decode().split("\0")[:-1]
    expected = {("M", path) for path in MODIFIED} | {("A", path) for path in ADDED}
    if len(fields) != 2*len(expected) or set(zip(fields[::2], fields[1::2])) != expected:
        raise SystemExit("RUNTIME01C_SCOPE_MISMATCH")
    subprocess.run(["git", "diff", "--check", BASE, end], check=True)
    print("RUNTIME01C_SCOPE_PASS: exact additive service/tools/tests, three CI-only changes.")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--end", default="HEAD")
    check(parser.parse_args().end)
