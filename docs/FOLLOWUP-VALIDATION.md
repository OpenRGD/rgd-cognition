# Follow-up verification — 2026-10-30

Code review found a side effect inside a demo assertion: `host.submit(event)`
would be removed by Python optimization (`-O`). Submission is now explicit,
followed by a normal runtime check. Added `tests/test_cli.py`, executing a four-event
synthetic replay under `-O` in a subprocess.

Local Python 3.13.5: **46/46 tests passed**, including the original 1000-event
socket/Popen-disabled replay and the optimized CLI regression. The CLI subprocess
is test-only; the cognition runtime still has no process-launch interface.
Prior dependency/build/hardware limitations in `VALIDATION.md` remain unchanged.
