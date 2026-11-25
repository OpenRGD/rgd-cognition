"""CI-only: preserve the original CORE-D integration while permitting RI candidate files."""
import subprocess

BASE = "a2526ba414409cc92641dc95bbddd6564317fcc4"
CORE_D_BASE = "3b78e835ca963ea80ee20885d3552e5f200c2b99"
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
subprocess.run(["git", "fetch", "--no-tags", "--depth=1", "origin", BASE],
               check=True, stdout=subprocess.DEVNULL)
subprocess.run(["git", "fetch", "--no-tags", "--depth=1", "origin", CORE_D_BASE],
               check=True, stdout=subprocess.DEVNULL)

subprocess.run(["git", "fetch", "--no-tags", "--depth=1", "origin", "29a8a0b60ce365d2a0fd1f38313a3a319793bc6a"],
               check=True, stdout=subprocess.DEVNULL)

def diff(a, b):
    return [x.split("\t",1) for x in subprocess.check_output(
        ["git", "diff", "--name-status", a, b], text=True).splitlines()]

seen, b_guard = set(), False
for status,path in diff(BASE, CORE_D_BASE):
    if path == "tools/check_core_b_scope.py" and status == "M":
        b_guard = True
    elif status == "A" and path in CORE_D_ADDITIONS:
        seen.add(path)
    else:
        raise SystemExit("CORE_D_BASELINE_DRIFT:"+path)
if seen != CORE_D_ADDITIONS or not b_guard:
    raise SystemExit("CORE_D_BASELINE_MISSING")
seen, guards = set(), set()
for status,path in diff(CORE_D_BASE, "29a8a0b60ce365d2a0fd1f38313a3a319793bc6a"):
    if status == "A" and path in RI_ADDITIONS:
        seen.add(path)
    elif status == "M" and path in CI_GUARDS:
        guards.add(path)
    else:
        raise SystemExit("UNEXPECTED_RI_SCOPE:"+path)
if seen != RI_ADDITIONS or guards != CI_GUARDS:
    raise SystemExit("MISSING_RI_SCOPE")
print("CORE-D original additions preserved; RI only exactly six additions plus two CI guard edits.")

# RI-02 is independently stacked on immutable RI-01 reviewed head.
RI01_BASE = "29a8a0b60ce365d2a0fd1f38313a3a319793bc6a"
RI02_ADDITIONS = {
    "src/rgd_cognition/ri_imu_binding.py",
    "src/rgd_cognition/schemas/ri-imu-binding.schema.json",
    "tests_ri02/test_imu_evidence_binding.py",
    "docs/COG-RI-02.md",
    "tools/check_ri02_scope.py",
    ".github/workflows/ri-imu-binding.yml",
}
RI02_CI_GUARDS = {
    "tools/check_ri_scope.py",
    "tools/check_core_b_scope.py",
    "tools/check_core_d_scope.py",
}
subprocess.run(["git", "fetch", "--no-tags", "--depth=1", "origin", RI01_BASE],
               check=True, stdout=subprocess.DEVNULL)
ri02_rows = [r.split("\t", 1) for r in subprocess.check_output(
    ["git", "diff", "--name-status", RI01_BASE, "HEAD"],
    text=True).splitlines()]
new_seen, guard_seen = set(), set()
for status, path in ri02_rows:
    if status == "A" and path in RI02_ADDITIONS:
        new_seen.add(path)
    elif status == "M" and path in RI02_CI_GUARDS:
        guard_seen.add(path)
    else:
        raise SystemExit("RI02_STACK_SCOPE_ESCAPE:" + path)
if new_seen != RI02_ADDITIONS or guard_seen != RI02_CI_GUARDS:
    raise SystemExit("RI02_STACK_SCOPE_MISSING")
print("RI02 opt-in evidence binding: exactly six new files and three CI-only scope guards.")
