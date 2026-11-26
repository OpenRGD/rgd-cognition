# OpenRGD Cognition

**COG-0.1 Foundation / 0.1.0a1 — candidate, non-normative, offline lab.**

A first executable foundation for OpenRGD cognitive orchestration, not a complete
intelligent robot, a deployed daemon, or a wrapper that gives an LLM motor access.
The current reasoner is deterministic and deliberately limited. No language model,
Chronon store, physical identity verifier, Voice device or remote GPU is connected.

## What works in this PR

```text
Typed input -> unbound context -> bounded attention queue -> memory availability
            -> deterministic assessment -> CognitiveProposal + CognitiveTrace
```

- Eight strict candidate schema definitions; bounded JSON, unknown-field rejection,
  duplicate-key/nonfinite protection and explicit timestamp validation.
- Reference-only context with distinct robot/life/agent/persona fields. They remain
  null/UNBOUND. A source digest supplied by a caller is DECLARED_ONLY, not verified.
- Two-lane attention queue, bounded deduplication, identity-collision detection,
  per-host alias isolation, local residence TTL and observation-lane fairness.
- Typed unavailable memory boundary, without reimplementing `RecallBundle`.
- Deterministic status/identity/memory replies or abstention. Provider output is a
  constrained assessment, never arbitrary tools, raw commands or a prompt authority.
- Structured trace without transcript, raw audio/video or private chain of thought.
- Synthetic replay and negative tests; no network client, process launcher, CAN,
  serial, Body Adapter, dynamic plugin loader, persistence or auto-install code.

## Run locally in a development environment

Python 3.10+ is the target. Initial dependency installation requires package access;
subsequent execution of the synthetic demo requires no network.

```bash
python -m venv .venv
# Linux/macOS: source .venv/bin/activate
# PowerShell: .\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-ci.txt
python -m pip install --no-build-isolation --no-deps -e .
python -m unittest discover -s tests -v
python -m rgd_cognition demo --events 1000
```

The demo generates only project-owned SYNTHETIC events for `lab-robot`; it never
reads Paky-01, a microphone, a local database, credentials or existing recordings.
All successful outputs say `identity_status=UNBOUND`, `memory_status=NOT_CONNECTED`
and `actuation_interface=false`. These are lab states, not physical attestations.

## Honest limits

This is a synchronous Python library + CLI, **not yet an installed service**.
The queue must be pumped by its caller. TTL is checked on dequeue and before
publication; it is not an autonomous erasure timer. `close()` releases buffered
references, not a secure-memory-erasure guarantee. Deduplication ends when its
bounded cache evicts a key; it is not durable exactly-once delivery.

In-process reasoners are trusted development code. Budget overruns are detected
**after** return, not preempted. Network model adapters require a future bounded
RPC/cancellation design and a separate egress/privacy review. The current code
cannot answer general questions or verify external evidence references.

No claim of N150 performance, physical safety, live voice integration or OS-level
sandbox enforcement is made. `may_actuate=false` alone cannot establish isolation.
See [SECURITY.md](SECURITY.md) and [local verification](docs/VALIDATION.md).

## Architecture and next steps

The five RGD microkernels — Safety, Life, Work, Relation, Imagination — remain
first-class architecture owned by OpenRGD, not subsystems whose authority this
repository absorbs. None is implemented or reinstated in the Canonical Core here.
Chronograf/Chronon own time/history; Memory owns projections; World providers own
predictions; the independent Somatic safety path owns any future physical execution.

- [Architecture and ownership](docs/ARCHITECTURE.md)
- [Candidate contracts](contracts/README.md) and [maturity](contracts/STATUS.json)
- [Roadmap and review gates](docs/ROADMAP.md)
- [Contribution policy](CONTRIBUTING.md)

All changes are proposed through branches and pull requests. Do not merge/release,
register this module in the Console, create Life identities, or deploy on Paky-01
as a consequence of this foundation PR alone. Server-side branch protection must
be configured separately; a documented PR policy does not enforce it.
