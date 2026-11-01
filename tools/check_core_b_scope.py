"""CI-only: preserve pinned COG-C1/CORE-B code through a reviewed CORE-D stack.

CORE-B's original guard only allowed CORE-B paths and assumed the PR branch
ended there. CORE-D adds six reviewed files; this guard explicitly checks the
fixed CORE-B base first, then refuses any further changes outside that new
CORE-D file set plus this CI-only guard revision. No runtime/schema relaxation.
"""
import subprocess

C1_BASE = 'a8ae925c9cacbce8bd7a6db01833d4159445d47a'
CORE_B_BASE = 'a2526ba414409cc92641dc95bbddd6564317fcc4'
CORE_B_PREFIXES = (
    'src/rgd_cognition/core_b',
    'src/rgd_cognition/schemas/core-b-local.schema.json',
    'tests_core_b/',
    'docs/COG-CORE-B.md',
    'tools/check_core_b_scope.py',
    '.github/workflows/core-b-adapter.yml',
)
CORE_D_ADDITIONS = {
    'src/rgd_cognition/core_d_projection.py',
    'src/rgd_cognition/core_d_demo.py',
    'tests_core_d/test_core_d_projection.py',
    'docs/COG-CORE-D.md',
    'tools/check_core_d_scope.py',
    '.github/workflows/core-d-projection.yml',
}


def diff(left, right):
    return [line.split('\t', 1) for line in subprocess.check_output(
        ['git', 'diff', '--name-status', left, right], text=True).splitlines()]


# GitHub PR synthetic-merge checkout is shallow: the reviewed CORE-B base
# commit is not always present, even though the merge points to that parent.
# Fetch only this exact public baseline for verification; never move a branch.
subprocess.run(['git', 'fetch', '--no-tags', '--depth=1', 'origin', CORE_B_BASE],
               check=True, stdout=subprocess.DEVNULL)

for status, path in diff(C1_BASE, CORE_B_BASE):
    if status != 'A' or not path.startswith(CORE_B_PREFIXES):
        raise SystemExit('CORE_B_BASELINE_DRIFT:' + path)

actual=set()
for status, path in diff(CORE_B_BASE, 'HEAD'):
    if path == 'tools/check_core_b_scope.py':
        if status != 'M':
            raise SystemExit('CORE_B_GUARD_REVISION_INVALID')
    elif status == 'A' and path in CORE_D_ADDITIONS:
        actual.add(path)
    else:
        raise SystemExit('UNEXPECTED_CORE_D_STACK_CHANGE:' + path)
if actual != CORE_D_ADDITIONS:
    raise SystemExit('MISSING_CORE_D_STACK_PATHS:' + str(sorted(CORE_D_ADDITIONS - actual)))
print('Protected C1/CORE-B files unchanged; only exact CORE-D additions + CI guard revision.')
