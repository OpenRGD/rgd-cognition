# Validation evidence — 2026-10-30

## Local execution

Environment: isolated authoring container, Python 3.13.5; not the N150 or RTX host.
Executed: `PYTHONPATH=src python -m unittest discover -s tests -v`.
Result: **45 tests passed**, including eight schema-definition checks, a 1000-event
synthetic replay, privacy/instance rejection, bounds, fairness, local TTL,
identity spoofing, provider exceptions/invalid refs, post-return budgets, typed
prediction provenance, and socket/Popen-disabled execution.

Executed separately: `PYTHONPATH=src python -m rgd_cognition demo --events 1000`.
Result: 1000 queued/processed, 0 pending, dedup cache bounded at 256,
UNBOUND identity, NOT_CONNECTED memory, no actuation interface.

Local dependency versions: jsonschema 4.26.0, attrs 26.1.0, referencing 0.37.0,
rpds-py 2026.5.1, jsonschema-specifications 2025.9.1. Dependency installation from
PyPI was unavailable in this container. Local execution uses preinstalled packages;
it is NOT an independent network-install reproducibility test.

CI is configured for Python 3.10 and 3.12 with an explicit dependency set. Its
status must be checked on the exact PR head; workflow configuration is not proof
that CI ran. `requirements-ci.txt` uses an older Python-3.10-compatible rpds pin on
3.10; that dependency combination is not claimed locally tested here.

## Local package smoke test

Built a wheel with preinstalled setuptools 82.0.1 (CI pins 80.9.0), installed it
into a separate target directory without fetching dependencies, and ran the CLI
from `/tmp`: 10/10 synthetic events processed with packaged schemas present.
This confirms local wheel contents, not byte-reproducible builds or clean dependency
installation. No package was published.

## Scope limits

No hardware, actual RGD issuance/binding, real Chronograf writer, stored personal
memories, model inference, camera, microphone, speaker, LED or remote workstation
was used. There was no 30-minute physical network-partition test or kernel-level
sandbox verification. A static import guard and monkeypatched exercised paths are
regression evidence, not a proof of zero possible effects on an arbitrary host.

Benchmarks are functional replay, not latency certification. No RFC SLA or
hard-real-time claim is made. The provider budget detects an overrun after return;
a non-returning in-process provider is explicitly out of scope.
