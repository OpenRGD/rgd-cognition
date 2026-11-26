"""CI-only strict additive scope guard for COG–RI–01, stacked after COG CORE-D."""
import subprocess

BASE = "3b78e835ca963ea80ee20885d3552e5f200c2b99"
RI_ADDITIONS = {
    "src/rgd_cognition/ri_observation_ref.py",
    "src/rgd_cognition/schemas/ri-reference-notice.schema.json",
    "tests_ri/test_ri_observation_ref.py",
    "docs/COG-RI-01.md",
    "tools/check_ri_scope.py",
    ".github/workflows/ri-cognition.yml",
}
CI_GUARDS = {"tools/check_core_b_scope.py", "tools/check_core_d_scope.py"}

subprocess.run(["git", "fetch", "--no-tags", "--depth=1", "origin", BASE],
               check=True, stdout=subprocess.DEVNULL)
subprocess.run(["git", "fetch", "--no-tags", "--depth=1", "origin", "29a8a0b60ce365d2a0fd1f38313a3a319793bc6a"],
               check=True, stdout=subprocess.DEVNULL)
rows = [x.split("\t", 1) for x in subprocess.check_output(
    ["git", "diff", "--name-status", BASE, "29a8a0b60ce365d2a0fd1f38313a3a319793bc6a"], text=True).splitlines()]
seen = set()
guards = set()
for status, path in rows:
    if path in CI_GUARDS and status == "M":
        guards.add(path)
    elif path in RI_ADDITIONS and status == "A":
        seen.add(path)
    else:
        raise SystemExit("RI_SCOPE_ESCAPE:" + path)
if seen != RI_ADDITIONS or guards != CI_GUARDS:
    raise SystemExit("RI_SCOPE_MISSING:" + str(sorted(RI_ADDITIONS - seen)) +
                     " GUARDS:" + str(sorted(CI_GUARDS - guards)))
print("RI-COG-01: six additive files and exactly two CI-only guard adaptations; prior COG paths unchanged.")

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
subprocess.run(["git", "fetch", "--no-tags", "--depth=1", "origin", "9235d3759b263bfde2d8644c46845e9a338e9238"],
               check=True, stdout=subprocess.DEVNULL)
ri02_rows = [r.split("\t", 1) for r in subprocess.check_output(
    ["git", "diff", "--name-status", RI01_BASE, "9235d3759b263bfde2d8644c46845e9a338e9238"],
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

# Validate the reviewed RI02 delta first, then the explicit RC02A patch.
from check_rc02a_scope import check as check_rc02a
check_rc02a()
