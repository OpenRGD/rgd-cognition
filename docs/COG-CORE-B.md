# COG–CORE-B — Adapter & Conformance

2026-11-01. **Candidate / non-normative / opt-in / SESSION_SCOPED / non-actuating.**
No merge, deployment, official Life, Chronon, external tool or permission grant.

## Reviewed updates and independent pins

| Source | Exact revision | Use |
| --- | --- | --- |
| COG-C1 PR #5 | `a8ae925c9cacbce8bd7a6db01833d4159445d47a` | Stacked code baseline, all pre-existing files unchanged |
| Core runtime baseline | `afe1a831b950a4e6560f0285a0103fc4eaa343b7` | Existing COG-02 canonical inspection, NOT re-pinned |
| Core-B PR #11 | `55a034ceb1cdaab8bed6848fcdde85c9436bc9e0` | Optional schema bytes only, no runtime/FixtureConsumer import |
| Core P0 REVIEW-02 #12 | `ec8a11d38566b10bfd9045f02ddad3755ed39d41` | Field crosswalk and source inventory reviewed |
| Core-C #13 | `fa5e8ff713a28b69b7d39b2c18e8c9e0f6c72ee0` | Identity handoff reviewed, NOT consumed as verified identity |

Core-C's handoff explicitly still recommends this session-scoped Core-B bridge.
Its record shapes do not authenticate an issuer, owner, lease or physical body.
The main source-root remains `sha256:c049dc3fb91c19e668ef0d35b9b40d9052caf1a458b1a108d58b1896189dd5f9`.

## Actual implementation and one admission owner

`core_b_c1.CoreBAttentionHost` reuses the **actual existing ImuAttention C1**.
It consumes its numeric-data-derived cue before the old C0 admission path. It
produces a Core-B `CognitiveGoalCandidate` via a versioned factory, then sends it
to `core_b_adapter.KernelSession`, the **only admission/reservation owner on this
opt-in path**. It does not instantiate SessionAgenda/AttentionAgenda or chain two
admission services. The old C0/C1 public behavior and schemas are not changed.

`KernelSession` is a new explicitly versioned, experimental local Work consumer.
It creates Core-B admission and transition records and local typed companions.
It does not import Core's offline validator or synthetic fixture consumer. The
upstream validator is imported ONLY by tests to cross-check actual COG output.

The seven public Core-B shapes are validated using exact upstream schema bytes,
Git blob `ac1eb0809384214f81164bfc5a9daf8ad7ec66e0`. Input bytes are supplied by a
trusted host, with no automatic download. `referencing.Registry` is populated
in memory: no network resolution. A different candidate requires a new reviewed
pin/adapter, not an unnoticed schema replacement. Git SHA-1 here identifies the
upstream blob; it is not issuer/signature/supply-chain attestation.

The runtime admits only its typed task catalog and INTERNAL_READ_ONLY. Inbound
KernelEvent supports only negotiated goal_candidate, with an explicitly supplied
payload, full payload digest and matching lifetime/context/provenance. `advisory`
and other incoming decision/transition/effect records are refused. Work produces
its own transitions through locally bound channels; no generic event dispatcher.
Descriptors can be shape-checked but cannot register themselves or mint grants.

## Trust model: local owner binding, not remote authentication

The trusted application provisions `LocalOwners`, immutable `Limits`, current
context and a monotonic clock. In-process object-identity capability channels
separate producer, Work and operator calls. A role/name/string/JSON supplied by
a model is never accepted as an owner. Only the admission function produces an
admission; a schema-valid model admission record is not ingestible.

These checks are implemented and adversarially tested **in the real consumer**.
They are NOT signatures, an OS isolation boundary, or a safe sandbox for hostile
Python sharing the process. Do not expose the host/Work/operator objects to model
plugins. Future authenticated transport must bind its principal to a scoped
local channel; it must not accept a channel label from the message body.

Default policy is disabled; resources are UNKNOWN. The operator must explicitly
enable the profile and supply a resource envelope. No battery, temperature or
performance measurement is fabricated. Goal allocation remains a local report,
`grants_authority:false`, and evaluated grant refs are empty: the allowed local
computation policy is not a fake external credential.

## Exact context, deadlines and execution generations

The new ABI context is separate from RGDContextSlice. It consumes the existing
RGD context revision, a distinct admission policy revision, a runtime-execution
UUID, the real Attention session and a host-supplied local role fence. Life binding
and activation remain null. Attention's policy fingerprint is retained in the
unchanged source cue companion. C0 task generation is never cast as role fencing.

The factory requires the captured monotonic handoff time and the actual C1 cue
expiry. Conversion uses ceil(creation_ns/1e6), floor(expiry_ns/1e6): validity is
never extended. A fractional-millisecond start may defer/reject immediate use
until representable; there is no retry loop. Creation time is provided at capture,
not recomputed by a later converter. Other domains/UNALIGNED/future/expired inputs
are rejected. Duplicate conversions preserve the original deadline.

Every Work operation rechecks context, policy, session/runtime, fence, clock and
lifetime. Model-result tickets additionally bind the **task execution generation**.
Pause/resume invalidates older tickets. No RTX client, worker cancellation or model
inference is implemented. Clock regression closes the local session. A context
change invalidates active work; no automatic rebind restores old permissions.

## Idempotency and reservations

Admission commits a decision and reserves steps, wall-time allowance and queue
slots under one RLock-protected local transaction. Concurrent calls cannot
oversubscribe. This is in-process serialization, not a distributed transaction.
A child needs a running parent, proper lineage/depth, a fresh decision and a fresh
aggregate reservation. Siblings and lifetime child counts are bounded. Ending a
parent invalidates active descendants on the next boundary check.

Keys are scoped by principal/session and fingerprint the full immutable request.
KernelEvent intake also fingerprints the full envelope/payload, not just its cue.
Exact duplicate returns the same inert record without reserving or executing again.
Changed budget, TTL, task, effects, evidence or envelope gives a conflict. No keys
are evicted during the session; capacity applies backpressure. This deliberately
stronger retention covers accepted TTL but does not persist across restart.

Running wall time is charged from the trusted monotonic clock at API boundaries;
this is **not real-time preemption or an inference timeout controller**. Pause
retains reservations. Terminal/invalidation releases unused reservation once.
Already spent steps/wall time remain charged. Resource LOW/UNKNOWN pauses Work;
explicit resume is required. At audit saturation an administrative stop invalidates
and closes the session rather than continuing unaudited work.

## Lifecycle, typed results and lossless boundaries

| Operation | Core-B state | Local companion meaning |
| --- | --- | --- |
| New admitted work | ADMITTED | Exact goal/admission refs; not yet executed |
| Start/resume | RUNNING | New task generation, original deadline |
| User/resource/evidence pause | PAUSED | PAUSED_USER / PAUSED_LIFE / INSUFFICIENT_EVIDENCE retained |
| Analysis done | COMPLETED | ANALYSIS_COMPLETE, still UNVERIFIED |
| Deliberate abstention | COMPLETED | ABSTAIN: inquiry ended without a verified conclusion |
| Cancel/failure | CANCELLED / FAILED | Explicit Work reason |
| Expiry/context loss/clock loss | local CANCELLED | Local invalidation report; NOT a new current-context Core event |
| Rejected admission | REJECTED | Terminal; never silently expires into another state |
| Deferred admission | no admitted transition | DEFER preserved; cannot become a fresh admission by retry |

This is a **new COG consumer profile**, not a lossy enum cast of old C0 records.
Arbitrary old ABSTAINED/EXPIRED/DEFERRED records are not imported as if they were
Core transitions. Unknown outcome/task/event versions fail closed. Transition
sequences and predecessor refs are produced from owned state, never from model
suggestions. Local companions use `schemas/core-b-local.schema.json` and are NOT
injected as extra fields into closed Core schemas. Advisory negotiation remains
unsupported. The existing CognitiveTrace and physical DecisionTrace are unchanged.

The typed task catalog currently covers IMU uncertainty and synthetic oneiric
review. Inquiry completion is not proposition confirmation: reviewing a first
step may support, refute or leave it unresolved. Tests reuse the actual C0
`oneiric_review` pure fixture function, preserve superseding labels and null
Chronon/Life. No autonomous learned skill update or durable annotation is performed.

## Effects, identity and deployment limits

No CAN/USB/network/TTS/digital/history writer is reachable from this API. All five
explicit EffectRequest categories are refused when submitted to the disconnected
gate boundary; local computation occurs only through the Work API. A supplied
ALLOW/receipt never creates a gate. Reading a schema is not executing an effect.
No claim of complete device isolation follows from Python code inspection/tests.

No Core-C Life adoption, enrollment, durable exclusive lease, copied-disk detection,
checkpoint restore, Chronon commit, live IMU transport or physical certification.
The actual C1 producer is exercised with synthetic observations; the baseline
Core profile is real. This distinction also applies to all replay results.

## Verification

`tests_core_b/` contains producer/consumer tests, strict parsing, upstream positive
and negative fixtures, model self-admission/forged-owner checks, aggregate and
concurrent reservations, child budgets, full-record duplicate conflicts, revoked
contexts, pause/resume/terminal behavior, typed companion outputs, no-I/O paths and
actual C1 + COG-02 + pinned Core flows. Missing upstream inputs fail, never skip.
Normal and `-O` runs exercise the same tests. CI runs Python 3.10/3.12, existing
133+32 regression cases, wheel smoke outside checkout and an all-new-files scope
check against C1. Exact-head execution evidence is in the PR, not implied by text.

Local development obtained public source archives through a read-only GitHub
Actions input snapshot because container GitHub DNS was unavailable. The exact
Core-B schema blob and COG-02 verifier fingerprints were checked. Local execution
uses real code, NOT test stubs. The temporary input-export workflow is replaced
by the actual conformance workflow in this PR's final revision.

```sh
CORE_B_CHECKOUT=/path/to/pinned-core-b RGD_CORE_CHECKOUT=/path/to/pinned-baseline-core \
  python -m unittest discover -s tests_core_b -v
python -m rgd_cognition.core_b_demo --core-b-checkout /path/to/pinned-core-b
```

No schema vendoring, Core toolchain re-pin, edits to previous COG files, implicit
merge, release or robot installation. Pending: review of this consumer profile,
external authority, larger measured sessions, OS isolation and independent Core-C/D.

Sources: Core #11 README/schema and handoff; Core #12
`docs/reconciliation/p0/COG_CORE_B_CROSSWALK.md`; Core #13
`contracts/identity/v0.1.0/COG_EXT_MEM_HANDOFF.md`. Primary JSON Schema resolution
reference: https://python-jsonschema.readthedocs.io/en/stable/referencing/ .
