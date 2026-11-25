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
rows = [x.split("\t", 1) for x in subprocess.check_output(
    ["git", "diff", "--name-status", BASE, "HEAD"], text=True).splitlines()]
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
