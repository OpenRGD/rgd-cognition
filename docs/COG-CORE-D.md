# COG–CORE-D — Temporal / Oneiric draft projection consumer

**2026-11-02 · CANDIDATE / NON-NORMATIVE / opt-in / SESSION_SCOPED / INTERNAL_READ_ONLY.**

This is a **read-only, synthetic, session-scoped producer/consumer conformance** over genuine COG Work/ONEIRIC output and exact CORE-D draft JSON Schema. It is not a Chronograf/Physics/History/Memory runtime, not an authenticated Life, not a Chronon, not a durable autobiographical projection, and not authority to talk, actuate, run tools, use the network or write history.

## Reviewed independent pins

| Role | Commit / identifier | Purpose |
| --- | --- | --- |
| Existing canonical RGD reference toolchain | `afe1a831b950a4e6560f0285a0103fc4eaa343b7` | **Unchanged** COG-02 profile inspection/source-root |
| CORE-B contract candidate | `55a034ceb1cdaab8bed6848fcdde85c9436bc9e0`, exact schema blob `ac1eb0809384214f81164bfc5a9daf8ad7ec66e0` | Independent opt-in goal/admission/Work ABI |
| CORE-C identity candidate | `fa5e8ff713a28b69b7d39b2c18e8c9e0f6c72ee0` | Reviewed only; cannot issue actual Life |
| CORE-D temporal/memory candidate | `7b15fda5c825f9359ce0045377ec38364de19efb`, exact schema blob `9ed412fb8749cd7aeb8eeb23f2305d98ecfc0de8` | Optional schema-only validation, **no Core runtime import** |
| COG–CORE-B Review Closure | `a2526ba414409cc92641dc95bbddd6564317fcc4` | **New exact COG baseline**, replaces the old compatibility test pin `877a450...` |

All original COG PRs #1/#3/#4/#5 and PR #6 **runtime/schema code** remain unchanged. This PR is separately stacked on COG #6. The only pre-existing path edited in this stack is a CI-only scope checker, adapted to recognize exactly the new CORE-D files while still rejecting any earlier code changes. The CORE-D GitHub Actions workflow originally pinned COG `877a450...`, so green CORE-D CI on that pin is legacy compatibility evidence only. The **new COG workflow** must test the exact new COG stack; the Core owner can separately decide to update its own CI pin.

## Data boundary — actual COG producer to CORE-D shapes

```text
Actual C0 synthetic oneiric_review observations
    → COG CORE-B KernelSession (ONE admission, finite reservations, Work-owned review)
    → ONEIRIC_REVIEW outcome + versioned CognitiveTraceCoreB
    → validate_result_bundle (cross-record context/goal/revision/trace)
    → core_d_projection.project_oneiric (schema-pin + semantic checks)
    → ephemeral SalienceHint + MemoryAnnotation revisions + OneiricReview
      + CognitiveCommitment candidate; all marked SYNTHETIC/UNVERIFIED
    → history_commit_preview (BLOCKED_NOT_CONNECTED; request/receipt null)
```

The `MemoryAnnotation` record type is a **Core-D candidate data shape** here, not an assertion that an L2/Chronon writer or L3/L4 materialization exists. All records have local content identifiers only; none is a Chronon ID or authenticated writer receipt. The draft produces one `MemoryAnnotation` per existing C0 revision and links them through the **draft** `supersedes_annotation_ref` chain. It preserves the original interpretation digest and the same subject; the full C0 history stays available only while the trusted owner retains that result. A meaningful replay does not automatically become canonically memorable.

The source may report `STEP_NOT_SUPPORTED_IN_FIXTURE` (`REFUTED`) or `INSUFFICIENT_EVIDENCE` (`UNRESOLVED`). `STEP_PLAUSIBLE_IN_FIXTURE` remains **UNRESOLVED**, never physically `SUPPORTED` or `physical_milestone_verified=true`. This mapping is **review-proposed, not normative**. Completion of the Work inquiry never establishes the truth of the first step. The local cognitive commitment is a proposal, not an applied learning update.

## Time and provenance

`knowledge_at_ms` on every **draft** is the time at which this projection was assembled, in the *same trusted local monotonic session domain* as the Core-B result. The original C0 annotation generation times are **not recoverable from the C0 record**, so this profile never invents individual historical knowledge times. The entire review chain is projected now and the provenance remains SYNTHETIC_REVIEW/SYNTHETIC_REPLAY. This is **not** a Chronograf TimeAtom, an AnchorRef64, a ledger commit time or an `AS_KNOWN_AT` query. `about_valid_time_assertion_ref` is null: no backdated historical event-time attestation. A future qualified-time integration requires external owners.

## Deliberately blocked HistoryCommitRequest boundary

CORE-D `HistoryCommitRequest` requires *positive verified* `life_id`, Life binding/activation, writer role lease, an authenticated independent CORE-B `HISTORY_COMMIT_REQUEST` effect gate, exact payload digest/idempotency and actual historical time. **The COG session lab lacks all of these.**

`history_commit_preview` can produce a **non-executable local preview** with `payload_kind=ONEIRIC_REVIEW` and a draft payload hash. It always includes:

- `status: BLOCKED_NOT_CONNECTED` with explicit missing-authority reasons;
- `history_commit_request: null`, `effect_request: null`, `history_commit_receipt: null`;
- `life_id: null`, `chronon_id: null`, `history_committed: false`.

The API does **not** create a shape-valid CORE-D `HistoryCommitRequest`, synthesize a Life, accept a caller-provided `COMMITTED` receipt, retry a lost ACK, or contact a writer. This is intentional, not an incomplete authorization bypass. Later integration requires a *separately reviewed* authority resolver + actual gate + writer receipt/lookup. In particular, `NOT_CONFIRMED` after a lost acknowledgement must never be interpreted as permission for a new idempotency key.

## Ownership and review decisions

| Surface | Owning service / status |
| --- | --- |
| Attention cues and epistemic goal proposals | COG-C1, does not admit goals |
| Goal admission, reservations, Work transitions | COG CORE-B KernelSession, one owner, unchanged |
| Task/Outcome/CognitiveTraceCoreB | Existing COG #6 candidate, already structurally tested; cross-owner approval outstanding |
| Synthetic Oneiric annotations and ephemeral CORE-D drafts | COG/Imagination/Work here; **no durable memory** |
| Qualified import/commit anchor and old timestamp provenance | Chronograf + Core-D Temporal delta, *not COG* |
| Life enrollment / writer fencing / effect gate | RGD-EXT / Life / Identity / Somatic, *not COG* |
| Canonical Chronon + authenticated receipts | RGD-Physics/History writer, **NOT_CONNECTED** |
| Vault evidence retention and bitemporal Memory queries | Memory/Vault, **NOT_CONNECTED** |
| Privacy erasure/replica propagation | Memory/Vault governance; no deletion claimed |

### Pending cross-owner decisions

1. Approve/modify the current COG outcome and `CognitiveTraceCoreB` local profile, including the rule `COMPLETED ≠ hypothesis SUPPORTED`.
2. Agree which local projection identifier, evidence hash encoding and typed `supersedes` mapping can be adopted for actual Memory/History and which require a new version; local digests here are not universal Chronon identifiers.
3. Define a true authenticated `HistoryCommitRequest` caller and writer, role fencing, mutable policy revocation, durable idempotency and idempotent receipt lookup under Core-C/History governance.
4. Decide whether to persist each oneiric revision, a summarized commitment, or both; if the raw evidence is unavailable, label its retrieval limits, not fabricate evidence. Define retention and legitimate erasure constraints.
5. Agree on a verified knowledge-time source for bitemporal query; never promote a local monotonic timestamp into Chronograf history.

## Conformance gates and limitations

Tests use the **real COG #6 KernelSession, real C0 oneiric_review function, exact CORE-B and CORE-D schemas**. They verify: linked state/goal/trace, timeline projection not backdating, source/clock mismatch rejection, synthetic/provisional provenance, correction vs uncertainty, supersession integrity, tampering, idempotent pure projection, no secondary admission or resource charge and no IO/writer/EffectRequest. The official CORE-D offline shape validator checks the generated records as a test oracle only. CORE-D's own synthetic fake Chronograf/writer conformance runs as a separate CI step, not inside COG runtime. Existing 129 CORE-B + 133 unit + 32 baseline Core integrations are also rerun.

Tests **do not** prove authenticated producer identity, measured global time, L1 evidence availability, persistent L2 history, bitemporal queries, legal privacy erasure, source calibration, memory projections after reboot, RTX remote cancellation, N150 OS isolation or physical safety. No installed Paky-01 service, motor transport or state mutation is part of this candidate.

A valid CORE-D `HistoryCommitReceipt` **fixture** does not prove that the request was committed. A valid shape and an external signature are different guarantees. Keep all stacked PRs draft; no merge, release, registration, Life activation or robot deployment follows from a passing test.
