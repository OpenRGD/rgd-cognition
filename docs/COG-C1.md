# COG-C1 — Attention & Autonomous Goal Generation

Candidate / NON-NORMATIVE / session-scoped / not deployed. Extends COG-C0
PR #4 at `a964c2f3bd65969267b9d6ca14b5eb8557f40f35`. No edits to COG-01,
COG-02, COG-C0, Core spec, existing schemas, or device services.

## Actual increment

C0 needed a trusted adapter to explicitly supply `cue_kind`. C1 derives that cue
from supplied, structured IMU records. Two deterministic rules are implemented:

1. A confirmation window with unverified calibration/frame produces one bounded
   investigation into interpretation limits (`UNCALIBRATED_IMU_CONTEXT`).
2. Consecutive angular-rate magnitudes above an experimental threshold produce
   `SUSTAINED_RATE_UNVERIFIED_FRAME`. Sustained low readings re-arm this rule.

These are reasons to investigate, NOT diagnoses of hardware failure, imbalance,
pose or successful locomotion. Both map to C0's existing `IMU_DISCREPANCY` cue and
`INVESTIGATE_IMU_UNCERTAINTY` goal; that legacy cue name does not assert a measured
physical fault. No first-step milestone is derived from IMU alone. No LLM, learned
salience model, vision interpretation, or generalized curiosity planner is added.

`ImuAttention` selects information; `AttentionAgenda` sends candidates to the
existing `SessionAgenda.propose`. Work/GoalAdmission still decides admission and
runs tasks. C1 never calls a model or executes a goal on receipt. Demo completion
uses a declared fixture result, not a demonstrated answer to the investigation.

## Source boundary and provenance

The inspected Console contract is `console.imu.v0.1-candidate`, normalized sample
shape from `contracts/console/v1/imu-observation.v0.1.schema.json` in rgd-console
(blob `8ddbe8d7639e35f0a9442a80e27c9e49f882eb7c`). The repository was private at
inspection: no private source file, recording, token, configuration or device
identity is vendored here. The C1 schema is a hand-authored **consumer restriction**,
not the upstream schema or its authority. Manual field mapping is reviewed;
CI tests generated fixtures, NOT a live Console connection or private producer.

Acceleration is in m/s2 and angular rate in rad/s in unverified **sensor axes**.
Vendor Euler angles in degrees are not body pose or a verified world heading.
`calibration_revision=null`, `heading_calibrated=false`, `decision_eligible=false`,
`observation_only=true`, and `time_quality=host_receive_only_not_chronograph` are
preserved; extra fields, unsupported versions and positive authority claims fail.

SourceBinding pins source, sensor, frame, routing alias and collector session.
The Console field robot_id is a routing alias: it does not enroll a robot or Life.
A new collector session requires a new explicit binding/engine, never an automatic
rollover mixing clock domains. Foreign-source sequences are not compared.

**Transport is deliberately outside C1.** The host supplies an already obtained
normalized record; this code never connects to WebSocket/HTTP, opens USB/CAN,
starts capture, reads credentials, writes files or publishes Console/TTS events.
The adapter is a read-only data consumer, not an installed sensor bridge.
Reality Ingress remains a bootstrap/contract-design candidate in the inspected
repository; no invented generic Ingress wire format is used.

The trusted host supplies consent, receipt_monotonic_ns and freshness. Defaults
are consent false and freshness UNKNOWN. Payload text cannot set these fields.
`AUTHORIZED_LOCAL_FEED` is host configuration, **not authentication implemented
here**; callers must authenticate/authorize the feed and check upstream freshness.
For that mode C1 also requires COG-02 source-integrity-verified RGD context.
It still cannot claim verified observation identity or physical truth.

Synthetic replay always emits `origin=SYNTHETIC`, even though the generated packet
has the upstream shape's `source_kind=physical`. No physical recordings are used.

## Time, relevance and boundedness

- Source timestamp, clock-domain label and local receipt domain remain distinct.
  Host receive time is not sensor acquisition time or a Chronograf anchor.
- Local TTL rejects resident stale samples; stale/unknown transport freshness also
  rejects them. A numeric source timestamp is never compared to a foreign clock.
- Duplicate sequence+payload is ignored WITHOUT renewing residence. Same sequence
  with different bytes, sequence rollback, monotonic-source rollback or local
  receipt regression is rejected. Latest sequence is retained for the session.
- Sequence gaps, receipt gaps and context revisions clear the confirmation window.
  They do not assert that the sensor itself failed or that physics changed.
- A cue expires with the oldest contributing receipt, not a new arbitrary timeout.
  The C0 event and goal receive only its remaining lifetime. Context is rechecked
  before admission; C0 rechecks on scheduling. No stale cue retries occur.
- Window size is bounded, no raw sample archive is maintained, and cue cooldown,
  hysteresis and a hard per-session proposal cap apply across rule types/context
  refreshes. Rejected/deferred proposals consume the finite attention allocation;
  retries are not automatically spawned. Full C0 agenda/audit limits remain.
- Resource UNKNOWN/LOW and explicit user attention pause suppress goal generation,
  without opening another sensor stream. New fresh samples are needed on recovery.
  Work.resume is explicit; C1 cannot resurrect cancelled/expired work.
- No automatic history commit or persistence; Life null, Chronon NOT_CONNECTED.
  References are local content fingerprints, not global evidence certification or
  durable storage. Their payload availability depends on the authorized upstream
  evidence owner; C1 does not promise future retrieval from those hashes.

The default 3-sample window, 0.3/0.15 rad/s hysteresis, 3-second residence bound,
1-second maximum receipt gap, 30-second cooldown and eight-proposal quota are
**lab policy**, not calibrated robot thresholds or N150 performance guarantees.
Changes alter the recorded attention policy fingerprint. Numerical input caps
are parser/resource defenses, not safe motion envelopes.

## Usage boundary

Construct one AttentionAgenda for one trusted, session-pinned source and one
Work agenda. Supply `context_supplier=rgd_resolver.read` and a reviewed SourceBinding.
Deliver normalized samples via `ingest(payload, received_ns=local_receipt,
freshness=adapter_freshness, consent=adapter_consent)`. Start with resource UNKNOWN.
Only the authorized host/resource adapter may call `set_resources`; packet data
and model output cannot self-assert resources NORMAL. Use `interrupt_user` for an
already authorized COG-01 user event, then explicit Work resume after revalidation.

No shell/service installation instructions are part of this increment.

## Tests and limitations

34 new unit tests exercise numeric rule generation, persistence/hysteresis,
semantic cooldown, quotas, bad data, source/session isolation, clock domains,
staleness, privacy, injection, evidence quality and no I/O on the exercised path.
10 integration tests compose **real C0, COG-02 and the pinned Canonical Core**;
Console-shaped observations remain synthetic. Existing CI integration must fail,
not silently skip, if the pinned Core is unavailable. Dedicated C1 CI runs both
Python 3.10/3.12, numeric replay and installed-wheel smoke outside the checkout.

Local authoring can run C1 pure unit tests with installed jsonschema. Full stack
execution is separately verified in GitHub Actions; no local Core checkout was
available because container DNS could not reach GitHub. Final CI evidence belongs
to the exact PR head, not this document's prose.

Not claimed: live sensor feed, robot deployment, OS sandbox certification, live
resource telemetry, continuous process preemption, 8-hour real-time soak, durable
identity, Chronon storage, autonomous model inference or physical safety proof.
Trusted in-process Python and trusted transport metadata are explicit assumptions.

Next acceptance gate: operator-supervised replay of consented real observations,
then a separate read-only local transport adapter and measured N150 commissioning.
No merge, Core normative promotion or robot installation follows automatically.
