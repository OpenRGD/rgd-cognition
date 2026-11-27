# COG-RI-03 — Source-owned IMU evidence reconciliation

**27 November 2026 · candidate / non-normative / offline / SESSION_SCOPED.**
This additive consumer does not install a service, enable evidence access or
alter the current publisher. Source-only integration is independent of physical
commissioning and canonical contract acceptance.

## Decision

Use the **original source-owned IMU record** as the evidence representation for
this integration. The original Console ingest sample, receipt pair, source,
session and sequence remain inside its existing RI generic record. RI owns
storage and scoped access; the accepted Console helper owns numeric correlation;
COG relates a successful content match to its existing C1 local evidence digest.

The normalized Console-copy proposal in [COG-RI-02](COG-RI-02.md) remains an
independently tested historical candidate. It is not rewritten, deleted or
silently treated as an A03/A04 producer profile. No stored record is migrated and
no existing schema or dependency pin changes in this increment.

This resolves a practical source-representation choice for a **reviewable local
consumer**. It does not make all owner profiles interoperable: the current
Console matcher is restricted to its Paky-01 pilot, producer-version adoption
and the metadata-to-payload transition remain explicit gates below.

## Current reviewed owner snapshots

| Surface | Revision / exact artifact | Role |
| --- | --- | --- |
| RI-A02 #8 | `161318d2897d07d5628ef502cafba1c7c489fff0` | Original source session/content matching; COG normalized copy unresolved |
| RI-A03 #10 | `3a2b827ab9a07d8b0d6670dff6840d3234895e13` | Bounded finite source-owned spool intake |
| RI-A04 #11 | `3b9a9c2e6d7f69aae3dde1e690fc3c90562a1f43` | Optional scoped local reader; `evidence_access.py` blob `42cf218b38b49083e2201e10fa2f33bba94ed6df` |
| Console #22, merged | `b331dd32415eeda0d107676920a6dea91170cc4f` | Accepted source consolidation, not hardware/deployment acceptance |
| Console correlation helper | `scripts/ri_periph_compat.py`, blob `34710eba7cecf0235cd2651edd286f5ac79a41fe` | Existing original-source-to-normalized-record comparison, unchanged by #22 |
| Existing Console schema | blob `8ddbe8d7639e35f0a9442a80e27c9e49f882eb7c` | Existing `ConsoleImuSchema` pin retained |
| Existing RI consumer schema | blob `3d92e074e71593bf6db0a735394c628ea131668d` | Existing `RIReferenceContract` pin retained |

New tests use public source snapshots. They do not vendor or execute private
Paky/IMU code, raw recordings, instance configuration, tokens or enrollment data.
They exercise the original public Console synthetic fixture through real RI
A03, A04 and COG code. The generalized export shape is the profile already
documented in RI-A03; its test uses synthetic values and the same pilot IDs.

## Local API and ownership

`ri_source_binding.SourceOwnedIMUBinder` is disabled by default. The trusted host
provisions an existing `ConsoleImuSchema`, `RIReferenceConsumer`, a C1
`SourceBinding`, opaque local channels, and the already reviewed Console
`correlate` function. It does not accept an import path, module name, executable,
plugin or callback supplied by observations or a language model. This package
does not dynamically load the helper or add a Console runtime dependency.

The callback is **trusted installed Python**, not a sandbox. CI checks its exact
source blob. Constants naming revisions in COG are descriptive pins for review,
not an authentication mechanism or a proof that an arbitrary injected function
is that source. A deployment must provision the reviewed callable itself.

`bind(publisher_channel, ri_reader_channel, reference=..., sample=...,
stored_payload=..., availability=...)` receives only already supplied data. The
trusted host must obtain current access/consent and availability from the
evidence owner before every call. It must not reuse a cached AVAILABLE label
after access revocation or retention expiry. In-process channels are not
cryptographic credentials and cannot isolate hostile code in the same process.

The operation performs:

1. Explicit enable/channel/metadata/payload/consent and availability checks before
   data processing. Default policies remain denied.
2. Existing byte-pinned Console and C1 schema validation. Source/session/frame
   match the host's preconfigured C1 binding. Bounded strict JSON rejects duplicate
   keys, nonfinite values, excessive depth and noncanonical stored bytes.
3. Known source-owned representation checks and local payload hash/size matching.
   The two RI-A03 producer labels are explicit; no future version auto-adoption.
4. The existing Console helper compares original sample values, SI units,
   receipt, source/session/sequence, frame and reference. It retains unverified
   source/identity/calibration/time labels and its existing pilot restriction.
5. The **same existing RI consumer** accepts the exact checked reference and
   bytes using its original complete-reference fingerprint. No new admission,
   EvidenceStore, reference issuer, publisher or goal generator is created.
6. A local association links the original RI ID/hash to C1's existing digest.
   It carries no sample payload or path. `freshness=UNKNOWN`,
   `time_alignment=NOT_ESTABLISHED`, unverified source/calibration, null
   Life/Chronon and false goal/actuation/grant/history flags remain explicit.

The local association is not a new wire contract, a `CognitiveProposal`, a
Core-D `EvidenceAvailability`, a Chronon or a transport authorization. C1 receives
numeric observations through its separately authorized owner path. This API
does not call C1 `observe`, Work `submit`, a model or any output service.

The map retains at most 64 sample/observation fingerprints in a session. Exact
duplicates are inert; changed source/session/sequence content conflicts. Full
capacity returns backpressure without evicting prior keys. Duplicates still
recheck bytes, caller policy and the existing RI consumer. Closing clears local
references and is terminal; it is not secure erasure or durable anti-replay.

## A04 result mapping at the trusted host boundary

COG does not import A04, inspect its store or request a grant. The host maps an
actual owner result before calling the optional association API:

| Owner result | Permitted handling |
| --- | --- |
| `PAYLOAD_RESOLVED` / `AVAILABLE`, selected original payload | Supply the exact returned reference and bytes, with the current authorized Console record |
| `REFERENCE_ONLY` / `UNKNOWN` | Metadata may go to the existing RI01 notice consumer; no source association |
| Revoked/unknown/wrong-purpose grant, including lease expiry | No association; preserve denied status, no inferred existence |
| `EXPIRED` due retention | No association; access expiry is not erasure proof |
| `RESTRICTED`, `REDACTED`, `ERASURE_REPORTED` | No association; never cast erasure reported into verified `ERASED` |
| `MISSING`, `CORRUPT_OR_UNSUPPORTED`, `UNAVAILABLE`, reader `UNKNOWN` | No association; do not replace missing evidence with zeros or fabricated fresh samples |

A04 labels its successful read `SELECTED_LOCAL_SNAPSHOT`; COG's output labels
its own guarantee `SUPPLIED_SOURCE_BYTES_MATCHED`. Neither is store-wide stable
verification, source authentication, physical identity or proof of continued
availability. A05/A06 and durable host policy remain external work.

### Preserve the metadata-to-payload collision

An RI metadata reference says `integrity_status=not_verified`. The checked
payload view of the same observation says `verified_local_hash`. RI01 commits
the **entire** reference fingerprint. If metadata was already consumed, the new
checked view must continue to fail with a reference conflict. RI03 reuses that
consumer and explicitly tests this failure. It never clears a replay key,
creates a replacement consumer, normalizes the flag, updates an old notice, or
creates an implicit status sidecar to avoid the conflict.

The first association requires a first accepted checked-payload view. Already
consumed metadata needs a separately agreed evidence-status transition contract
and owner review; this increment deliberately does not invent it.

## Compatibility limits that must remain visible

**Pilot scope.** The accepted Console helper explicitly recognizes the current
Paky pilot source/robot/sensor/frame labels. It rejects another robot even when
its generic RI record is internally coherent. COG's `SourceBinding` abstraction
remains configurable; this does not make the current helper universal. The
Console owner should generalize its existing helper under a separate reviewed
profile instead of copying normalization or source-specific matching into COG.

**Producer version.** RI-A03/A04 accept the exact generalized producer label
`rgd-imu/0.1.0a4:IMU-FOUNDATION-01D-candidate`. The label embeds the package version.
A successor label, even with identical fields, is not automatically accepted.
A synthetic `0.1.0a5` counterexample reproduces both RI `SourceScope` rejection
and COG rejection. Validate the actual installed/source-owner package version
before claiming compatibility. RI owns a versioned profile adoption; changing
only COG's label allowlist would not fix A03/A04.

**Numbers and size.** RI's new native-u64 profile and C1's earlier parser limits
are separate. Current C1 accepts sequence up to `2^63-1` and positive monotonic
receipt up to `2^63-1`; this integration retains that narrower intersection.
Tests preserve exact values above `2^53-1` and at C1's ceiling, while RI accepts
and COG refuses `2^63`. No JS `Number`, float cast, truncation or timestamp
restamping is used. Source wall estimates remain native u64; their range is not
a qualified timestamp. The receipt-pair bracket remains at most 50 ms and
stored payload at most 4096 bytes. These limits are independent of physical
movement limits and do not certify synchronized sensor acquisition.

## Verification and remaining decisions

The 27 new methods test the real finite spool intake, original RI store and
reference, scoped A04 release, accepted Console matcher and actual C1 detector.
They cover source/session conflicts, metadata upgrade rejection, denied and
revoked access, retention, exact replay, duplicate corruption, bounded maps,
unsupported representation/version, generalized shape metadata, numeric domain,
receipt and byte bounds, owned snapshots during caller mutation, redacted
callback/reader failures and no IO/process calls in the association path. The
helper and A04 source blobs are verified in the suite.

Local evidence: Python 3.12.14, normal and optimized (`-O`) executions. Existing
RI01 (26 cases) and RI02 (33 cases) pass against the additive RI-A04 snapshot.
The exact final-head CI and installed-wheel evidence belong in the review PR.
Do not count interpreter or optimized reruns as additional distinct tests.

Before adoption: RI/Console/COG owners review this association, agree source
profile version compatibility and how to generalize the existing Console
matcher, and separately define the metadata-status transition. A live pilot
also requires authenticated read delivery, effective consent/retention,
availability/integrity/replay acceptance, source ownership, measured host
resources and rollback. No physical test, source migration, service start,
History/identity authority, normative promotion or release follows from this
candidate. See [return handoff](handoffs/COG-RI-03-SOURCE-RECONCILIATION.md).
