# Cognitive foundation roadmap

| Wave | Scope | Exit evidence |
|---|---|---|
| COG-01 / this PR | Repository, local candidate schemas, synchronous host, cheap attention, deterministic reasoner, proposals/traces, synthetic replay | Local tests plus remote CI; review required |
| COG-02 | Typed RGD/instance context consumer and lifecycle service design | Reference-only vs bound/stale/conflicted contract fixtures; no invented IDs |
| COG-03 | Memory boundary conformance, fuller workspace and attention | Upstream RecallBundle alignment; bounded state, replay/fairness tests |
| COG-04 | One real model adapter and evidence-aware reasoning | Offline fallback, request cancellation, resource/egress/retention tests |
| COG-05 | Voice adapter and passive IMU/scene notifications | Exact producer/consumer versions; no direct device access from COG |
| COG-06 | Reviewed Paky-01 deployment pilot | Dedicated-user sandbox, backups/rollback, actual N150 tests |
| COG-07 | World prediction and consultative planning | Typed hypothesis/plan results, simulation isolation, result verification |

Naming/versioning is an implementation plan, not a replacement for COG-ARCH RFC
waves. COG-0.1 Foundation is not the completed voice-enabled COG-0.1 pilot.

Before merge: verify exact-head CI, review scope/schema/identity boundaries,
configure PR-required branch protection once check names exist. Before release:
separate governance approval and reproducible packaging. Before physical deploy:
security/operational acceptance independent of software CI. No automatic updates,
module-catalog registration, physical identities, motion grants or CAN tests here.
