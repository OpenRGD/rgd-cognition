"""CI-only: verify the stacked increment did not alter any existing C1 file."""
from pathlib import Path
import subprocess

BASE='a8ae925c9cacbce8bd7a6db01833d4159445d47a'
rows=subprocess.check_output(['git','diff','--name-status',BASE,'HEAD'],text=True).splitlines()
for row in rows:
    status,path=row.split('\t')
    if status!='A' or not path.startswith(('src/rgd_cognition/core_b',
        'src/rgd_cognition/schemas/core-b-local.schema.json','tests_core_b/',
        'docs/COG-CORE-B.md','tools/check_core_b_scope.py','.github/workflows/core-b-adapter.yml')):
        raise SystemExit('UNEXPECTED_SCOPE_CHANGE:'+path)
print('All changes are new opt-in files; C1 and all preceding paths preserved.')
