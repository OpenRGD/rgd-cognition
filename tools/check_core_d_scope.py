"""CI-only exact additive scope guard for COG-D candidate stacked on CORE-B closure."""
from pathlib import Path
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
for row in rows:
    status, path=row.split("\t",1)
    if status!="A" or path not in allowed:
        raise SystemExit("UNEXPECTED_SCOPE_CHANGE:"+path)
    seen.add(path)
if seen!=allowed:
    raise SystemExit("MISSING_SCOPE_PATHS:"+str(sorted(allowed-seen)))
print("CORE-D integration is additive, pinned and leaves all COG CORE-B/C1 files unchanged.")
