"""CI-only stacked scope: preserve COG C1/Core-B/Core-D, allow exact RI candidate files.

No runtime/schema/policy permission changes. All source upgrades are opt-in.
"""
import subprocess

C1_BASE = "a8ae925c9cacbce8bd7a6db01833d4159445d47a"
CORE_B_BASE = "a2526ba414409cc92641dc95bbddd6564317fcc4"
CORE_D_BASE = "3b78e835ca963ea80ee20885d3552e5f200c2b99"
CORE_B_PREFIXES = (
    "src/rgd_cognition/core_b", "src/rgd_cognition/schemas/core-b-local.schema.json",
    "tests_core_b/", "docs/COG-CORE-B.md", "tools/check_core_b_scope.py",
    ".github/workflows/core-b-adapter.yml",
)
CORE_D_ADDITIONS = {
    "src/rgd_cognition/core_d_projection.py", "src/rgd_cognition/core_d_demo.py",
    "tests_core_d/test_core_d_projection.py", "docs/COG-CORE-D.md",
    "tools/check_core_d_scope.py", ".github/workflows/core-d-projection.yml",
}
RI_ADDITIONS = {
    "src/rgd_cognition/ri_observation_ref.py",
    "src/rgd_cognition/schemas/ri-reference-notice.schema.json",
    "tests_ri/test_ri_observation_ref.py", "docs/COG-RI-01.md",
    "tools/check_ri_scope.py", ".github/workflows/ri-cognition.yml",
}
CI_GUARDS = {"tools/check_core_b_scope.py", "tools/check_core_d_scope.py"}


def diff(left, right):
    return [x.split("\t", 1) for x in subprocess.check_output(
        ["git", "diff", "--name-status", left, right], text=True).splitlines()]


for sha in (CORE_B_BASE, CORE_D_BASE):
    subprocess.run(["git", "fetch", "--no-tags", "--depth=1", "origin", sha],
                   check=True, stdout=subprocess.DEVNULL)
for status, path in diff(C1_BASE, CORE_B_BASE):
    if status != "A" or not path.startswith(CORE_B_PREFIXES):
        raise SystemExit("CORE_B_BASELINE_DRIFT:" + path)
base_seen, guard_changed = set(), False
for status, path in diff(CORE_B_BASE, CORE_D_BASE):
    if path == "tools/check_core_b_scope.py" and status == "M":
        guard_changed = True
    elif status == "A" and path in CORE_D_ADDITIONS:
        base_seen.add(path)
    else:
        raise SystemExit("CORE_D_BASELINE_DRIFT:" + path)
if base_seen != CORE_D_ADDITIONS or not guard_changed:
    raise SystemExit("CORE_D_BASELINE_MISSING")
seen, guards = set(), set()
for status, path in diff(CORE_D_BASE, "HEAD"):
    if status == "A" and path in RI_ADDITIONS:
        seen.add(path)
    elif status == "M" and path in CI_GUARDS:
        guards.add(path)
    else:
        raise SystemExit("UNEXPECTED_RI_STACK_CHANGE:" + path)
if seen != RI_ADDITIONS or guards != CI_GUARDS:
    raise SystemExit("MISSING_RI_STACK_PATHS")
print("COG-C1/Core-B/Core-D immutable source preserved; RI only exact additions + two CI checker edits.")
