"""Strict additive COG-RI-02 stack guard, no previous source/schema edits."""
import subprocess

BASE="29a8a0b60ce365d2a0fd1f38313a3a319793bc6a"
NEW={
  "src/rgd_cognition/ri_imu_binding.py",
  "src/rgd_cognition/schemas/ri-imu-binding.schema.json",
  "tests_ri02/test_imu_evidence_binding.py",
  "docs/COG-RI-02.md",
  "tools/check_ri02_scope.py",
  ".github/workflows/ri-imu-binding.yml",
}
GUARDS={"tools/check_core_b_scope.py","tools/check_core_d_scope.py","tools/check_ri_scope.py"}
subprocess.run(["git","fetch","--no-tags","--depth=1","origin",BASE],check=True,stdout=subprocess.DEVNULL)
rows=[r.split("\t",1) for r in subprocess.check_output(["git","diff","--name-status",BASE,"HEAD"],text=True).splitlines()]
seen,guard=set(),set()
for status,path in rows:
    if status=="A" and path in NEW:seen.add(path)
    elif status=="M" and path in GUARDS:guard.add(path)
    else:raise SystemExit("RI02_SCOPE_ESCAPE:"+path)
if seen!=NEW or guard!=GUARDS:
    raise SystemExit("RI02_SCOPE_MISSING:"+str(sorted(NEW-seen))+"; guards="+str(sorted(GUARDS-guard)))
print("RI02 exact six additions and three CI-only scope guards; all previous runtime/schema code immutable.")
