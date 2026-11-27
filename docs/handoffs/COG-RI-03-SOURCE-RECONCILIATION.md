# Return handoff — COG-RI-03 source reconciliation

**27 November 2026 · COG to RI / Console / IMU owners.**
Candidate local source-only conformance; no host/deployment request.

## Proposed shared decision, with an executable consumer

COG now has an additive `SourceOwnedIMUBinder` candidate that associates the
original source-owned RI IMU record with the existing Console/C1 observation.
It uses the existing accepted Console `correlate` helper. It introduces no
publisher, EvidenceStore, normalization implementation, live subscriber,
reference issuer or Work admission. The previous normalized Console-copy
proposal remains unchanged as historical evidence and is not silently adopted
by RI-A03/A04.

Test chain: **synthetic public owner fixture → actual RI-A03 finite intake →
actual RI-A04 scoped payload read → accepted Console correlation → current COG
RI reference guard → existing C1 evidence digest**. C1's independent attention
rules can be tested against that exact digest; RI references do not create goals.

## Exact reviewed interfaces

| Owner | Immutable reviewed source |
| --- | --- |
| RI-A04, including A02/A03 | `3b9a9c2e6d7f69aae3dde1e690fc3c90562a1f43` |
| RI original consumer schema | `3d92e074e71593bf6db0a735394c628ea131668d` (Git blob; unchanged) |
| Console accepted #22 merge | `b331dd32415eeda0d107676920a6dea91170cc4f` |
| Console original correlation helper | `34710eba7cecf0235cd2651edd286f5ac79a41fe` (Git blob; unchanged) |
| Console normalized IMU schema | `8ddbe8d7639e35f0a9442a80e27c9e49f882eb7c` (Git blob; unchanged) |

No private source, recording, instance configuration or credential is copied to
this review. Public synthetic fixtures demonstrate compatibility with the exact
listed source profiles, not execution of a private publisher or sensor.

## Requested owner dispositions

1. **RI and IMU:** adopt original source-owned stored bytes for this read-only
   association. Confirm the accepted producer versions before repinning any
   consumer. RI's current generalized label is exactly
   `rgd-imu/0.1.0a4:IMU-FOUNDATION-01D-candidate`. A successor `0.1.0a5` label is
   rejected by real RI-A03 `SourceScope` and COG, even when fields match. This
   public synthetic counterexample is committed as a regression. Source-owner
   version advancement needs explicit RI profile adoption, not relabeling data.
2. **Console:** preserve one correlation helper. Its current pilot-only ID
   conditions are verified by a negative other-robot test. Generalize that
   existing helper with a versioned explicit source scope if needed; COG will
   consume the reviewed new function instead of copying it.
3. **RI and COG:** separately agree evidence-status evolution. A04 metadata
   and checked-payload views differ in `integrity_status`; current RI01 detects
   the same-ID difference. RI03 preserves that collision. Do not clear a cache,
   recreate a consumer or normalize the field to fake acceptance. A versioned
   status/availability companion needs its own owner review.
4. **COG and numeric-profile owners:** record current C1's `2^63-1` ceiling
   alongside RI native-u64. Exact `2^53+1` is supported locally; `2^63` is an
   explicitly tested incompatibility. No coercion or old-schema change occurs.
5. **RI access owner:** deliver only a currently authorized
   `PAYLOAD_RESOLVED`/`AVAILABLE` result to this binding path. Preserve
   metadata-only UNKNOWN, denied/expired/withheld/missing/corrupt states; never
   promote `ERASURE_REPORTED` to verified erasure. A04's selected local snapshot
   is not A05 stable storage or A06 time/replay acceptance.

## Review evidence

27 new source-association methods compose the real public owner code, including
the two unresolved compatibility cases above, replay/consent/availability limits,
source/session conflicts, source-byte and receipt checks, exact C1 digest,
caller-mutation snapshots, redacted reader failures and no IO/process invocation
in the exercised association path. Existing RI01 and
RI02 suites remain intact. Local Python 3.12.14 normal/optimized evidence is
recorded in [COG-RI-03](../COG-RI-03.md); exact-head CI belongs to the review PR.

The bind operation is a local candidate, disabled by default. The host injects
the reviewed trusted Console function and owns independent access/consent
decisions. No callable or module name comes from input payloads. Local object
channels are not an OS sandbox or network authentication. A returned content
association remains unverified for source identity, calibration, physical truth,
Chronograf, Life, History and actuation.

## Follow-up and rollback

Resolve the three distinct compatibility decisions (source version, matcher
scope, metadata-status transition) before declaring M2 complete. Keep live
source acquisition and C1 delivery independent of RI. Stop using the optional
binder to roll it back; no device restart, store migration, service change or
source reconfiguration is needed. Future transport/pilot work remains separately
reviewed; this handoff requests no live read, data export, capture or deployment.
