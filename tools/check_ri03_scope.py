"""Exact additive RI03 reconciliation over the frozen 01C candidate tree."""
import argparse
import subprocess

BASE = "2612703c7a13efc474dab376c9fa689662183c25"
MODIFIED = {"tools/check_release_scope.py", "tools/release-scope.json",
            ".github/workflows/runtime-isolation.yml"}
ADDED = {
    "src/rgd_cognition/ri_source_binding.py", "tests_ri03/test_source_binding.py",
    "docs/COG-RI-03.md", "docs/handoffs/COG-RI-03-SOURCE-RECONCILIATION.md",
    ".github/workflows/ri-source-binding.yml", "tools/check_ri03_scope.py",
}


def check(end="HEAD"):
    subprocess.run(["git", "fetch", "--no-tags", "--depth=1", "origin", BASE], check=True)
    fields = subprocess.check_output(["git", "diff", "--no-renames", "--name-status", "-z", BASE, end]).decode().split("\0")[:-1]
    expected = {("M", path) for path in MODIFIED} | {("A", path) for path in ADDED}
    if len(fields) != 2 * len(expected) or set(zip(fields[::2], fields[1::2])) != expected:
        raise SystemExit("RI03_SCOPE_MISMATCH")
    subprocess.run(["git", "diff", "--check", BASE, end], check=True)
    print("RI03_SCOPE_PASS: six additive files, three CI/scope changes; prior source and schemas preserved.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--end", default="HEAD")
    check(parser.parse_args().end)
