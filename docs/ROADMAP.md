# RGD Cognition — capability milestones

Candidate engineering roadmap, not a canonical contract or delivery commitment.
The mutable acceptance tracker is [issue #2](https://github.com/OpenRGD/rgd-cognition/issues/2).
Original Foundation/Context/Agenda/Attention/Core-B/Core-D/RI01/RI02/RC02A
reviewed heads are preserved by the atomic [integration PR #11](https://github.com/OpenRGD/rgd-cognition/pull/11).
Software CI and an approved merge do not confer physical or historical authority.

| Milestone | Deliverable | Acceptance boundary |
|---|---|---|
| M0 | Consolidated offline alpha | RC03B independent merge decision, RC03C exact tree/artifact evidence, separate release approval. |
| M1 | Bounded supervised runtime | [RUNTIME-01](https://github.com/OpenRGD/rgd-cognition/issues/12): A lifecycle, B worker/cancel, C isolation/package rehearsal, D N150 bench. Synthetic-only until authorized. |
| M2 | Evidence-grounded read-only context | RI/Console source-owned profile reconciliation, authorized transport, freshness/availability/replay. No second publisher or automatic goal from RI ref. |
| M3 | Bounded inference provider | Evidence-aware assessments, deterministic fallback, timeout/cancellation/fencing, privacy/egress and evals. |
| M4 | Interactive cognition | Authorized Voice/Visual lifecycle and delivery, independent output owners; no duplicate device access. |
| M5 | Life continuity and read-only recall | External verified identity/leases, qualified RecallBundle, reboot and revocation; no local invented Life. |
| M6A | Supervised session-only Paky-01 pilot | M0–M4 plus measured N150 acceptance, isolation, rollback, 8h soak; no motion or persistent history. |
| M6B | Verified continuity pilot | M6A + M5. |
| M7 | Longitudinal learning / Oneiric | External writer/gate/time authority, immutable events and revisable interpretations; versioned payload review. |

M5 may progress alongside M1–M4. M6A need not wait for positive Life. Future
world/prediction/planning remain distinct from actuation and independent Safety.
M1 initial proposed budgets: 512 MiB orchestration RAM, p95 local receipt to
Attention <=100 ms at 10 Hz; measure on N150 rather than assume. No positive
Life, persistent Chronon, live model or sensor service currently certified.
