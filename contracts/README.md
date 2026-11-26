# Local candidate contracts v0.1

The sole schema source is `src/rgd_cognition/schemas/cog-v0.1.schema.json`, shipped
as package data. Eight `$defs`: ReferenceInput, InputEvent, ContextSlice,
MemoryAvailability, Assessment, CognitiveProposal, CognitiveTrace, TurnResult.
Schemas reject unknown fields. Runtime additionally checks reference membership,
assessment consistency and timing. These tests do not prove the truth of evidence.

## Compatibility map

| This PR | Intended upstream boundary | Limitation |
|---|---|---|
| ReferenceInput | RGD-EXT ValidatedProfileSnapshot/LifeBinding | Untrusted declared references ONLY; no signature/Core hash verification |
| InputEvent | Ingress/Voice/Console observation adapters | Local lab notification, NOT a replacement ObservationEnvelope |
| ContextSlice | Purpose-filtered cognitive context | UNBOUND-only until reviewed identity resolver |
| MemoryAvailability | Future MemoryQuery -> RecallBundle | No new RecallBundle schema, no memory store, unavailable only |
| Assessment | Internal reasoner output | Fixed code/kind/refs, no free-form generated response in foundation |
| CognitiveProposal | Non-actuating response contract | NOT `CognitionProposal` from Core agent/v0.1.0 |
| CognitiveTrace | Cognitive audit summary | NOT somatic DecisionTrace and not a Chronon |

Core `cognition-proposal.schema.json` at the pinned audit SHA requires both
`action_intent` and `aion_octant_obj`. This PR changes neither. No fake ActionIntent,
Life ID, Aion octant, Chronon ID or anchor is added to make a conversational turn fit.

`agent_id` and `life_id` remain separate nullable fields; no implicit alias.
`source_root`/`composition_digest` are declarations until an external verifier is
integrated. `context_revision` is a deterministic local view digest, never a
registry receipt. Context revision does not advance for each new transient event.

Input source IDs, origin, source times and refs are CLAIMS. All evidence is
DECLARED_ONLY, including physical-labelled input. Source timestamps are optional
RFC3339 strings with a required declared domain; no conversion to Chronograf.
Only local receipt monotonic time governs queue TTL. No inferred source freshness.

Input privacy is EPHEMERAL_LOCAL or DENY. Output trace contains IDs, reason codes,
reference hashes, origin/epistemic/calibration labels and timing, but no transcript.
Hashes remain potentially sensitive. Storage/export requires future policy gates.

Candidates are deliberately narrower than the RFC. `ANSWER` is a reserved proposal
kind; the baseline emits REPORT/ABSTAIN only. General reasoning, verified identity,
SUPPORTED recalls, persistent history, HTTP/model providers and live adapters require
separate reviewed additions, not silently widened fields or inferred privileges.
