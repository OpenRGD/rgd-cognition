"""CI-only exact bounded scope guard for COG-D stacked on CORE-B closure."""
import subprocess
BASE="a2526ba414409cc92641dc95bbddd6564317fcc4"
allowed={
    "src/rgd_cognition/core_d_projection.py",
    "src/rgd_cognition/core_d_demo.py",
    "tests_core_d/test_core_d_projection.py",
    "docs/COG-CORE-D.md",
    "tools/check_core_d_scope.py",
    ".github/workflows/core-d-projection.yml",
}
rows=subprocess.check_output(["git","diff","--name-status",BASE,"HEAD"],text=True).splitlines()
seen=set()
saw_guard=False
for row in rows:
    status,path=row.split("\t",1)
    if path=="tools/check_core_b_scope.py" and status=="M":
        saw_guard=True
        continue
    if status!="A" or path not in allowed:
        raise SystemExit("UNEXPECTED_SCOPE_CHANGE:"+path)
    seen.add(path)
if seen!=allowed or not saw_guard:
    raise SystemExit("MISSING_SCOPE_PATHS:"+str(sorted(allowed-seen))+" guard="+str(saw_guard))
print("CORE-D integration adds only six opt-in files and a narrowly bounded CORE-B CI guard revision.")
