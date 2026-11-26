# COG-RC-02A — Lifecycle & Result Integrity Hardening

**26 November 2026 — CANDIDATE / NON-NORMATIVE / SESSION_SCOPED / INTERNAL_READ_ONLY.** No merge, release, deployment, enrollment, authority or effects.

## Reviewed baseline and disposition

Stack on RI02 PR #9 `9235d3759b263bfde2d8644c46845e9a338e9238`. This is an explicit patch to the candidate runtime, not a rewrite of the old PRs. Preserve C0 #4 `a964c2f...`, C1 #5 `a8ae925...`, Core-B #6 `a2526ba...`, Core-D #7 `3b78e83...`, RI01 #8 `29a8a0b...` and RI02 #9 as historical reviewed heads. Core-B schema blob `ac1eb0809384214f81164bfc5a9daf8ad7ec66e0`, Core `afe1a831...`, Core-D `7b15fda...`, RI `5372f758...` and Console `a0ef857...` pins do not change. All previous wire schemas are byte-identical.

Sources: [COG issue #2](https://github.com/OpenRGD/rgd-cognition/issues/2), [C0 review](https://github.com/OpenRGD/rgd-cognition/pull/4#pullrequestreview-6063723109), [C1 review](https://github.com/OpenRGD/rgd-cognition/pull/5#pullrequestreview-6063723707), [Core-B review](https://github.com/OpenRGD/rgd-cognition/pull/6#pullrequestreview-6063724432).

**C0 is a legacy lab path.** The hardened opt-in Core-B Work path is the intended future runtime candidate. Never invoke both admission engines for one goal. This disposition does not retire the C0 fixture APIs or approve Core-B normatively.

## Correction matrix

| ID | Baseline failure | Patched receiver invariant |
|---|---|---|
| RC-01 | Rejected goal expired | REJECTED and DEFERRED are final non-admission dispositions for the immutable request; expiry/context refresh cannot reclassify them or silently grant them. |
| RC-02 | Changed budget (or other request fields) returned old cached admission | Existing event/cue/parent key commits complete immutable request, including event, budget, TTL, requested effect/network and admission context revision. Exact repeat is inert; changed request conflicts. |
| RC-03 | Other queued C0 work starts during user interruption | SessionAgenda owns a session-wide pause latch. New admissions deferred, no starts/resumes/steps/delegated result acceptance or Oneiric review while latched. Explicit trusted-host release is necessary, never implicit start/resume. |
| RC-04 | Different transition context accepted | Exact equality of all three Core-B contexts (transition, outcome, trace), including revision, policy, session/runtime and fence. Existing causal refs and hashes still verified. |
| RC-05 | Inconsistent transition reason accepted | Shared mapping of result code to from/to state, detail reason and result semantics; reject contradictory bundles even when local digests are recalculated. ANALYSIS_COMPLETE requires evidence. |
| RC-06 | Modified goal TTL exceeded original evidence deadline | Attention channel requires its typed companion. Receiver revalidates cue digest, identity, evidence, origin class, session and clock; reconstructs ceil(created_ns/1e6), floor(original cue deadline_ns/1e6), exact lifetime and companion deadline. Reject missing/mismatched detail before reservation. |
| RC-07 | Core-B Work starts during operator interruption | Operator-only `KernelSession.set_user_pause` owns the barrier under the existing Work lock, checked in submit, start/resume, ticket, finish and Oneiric review. Host Attention reads that barrier instead of a separate pause flag. |

C0's original finite capacity limit does not provide durable deduplication of unretained over-capacity refusals. New intent under a distinct cue/parent is still a distinct request. A DEFER is not automatic retry. C0 does not implement aggregate reservation; use the opt-in Core-B profile, not C0 as an additional production scheduler.

### Pause and failure semantics

The trusted host sets the session latch before fallible audit work. In C0, an audit-full interruption can leave the prior recorded state unchanged, but the latch denies execution/results and release is refused if a prior RUNNING state remains; close/reconstruct a lab session instead of erasing or faking audit. In Core-B, failure to record an operator pause invalidates active jobs and closes the session; spent wall time charged at API boundaries, unused reservations released. An individual goal's PAUSED_USER transition is still a goal-level lifecycle operation; it does not by itself assert the session barrier. Only the trusted local operator channel changes the Core-B barrier. Resource recovery does not clear it. Release does not resume work; Work must explicitly start/resume, and old task-generation tickets remain stale. Both C1 host adapters clear the transient Attention window on interruption/release without resetting anti-replay or proposal quotas. The C0 host API adds explicit `release_user_attention()`; the two direct C0 pause/resume tests now require that call. No schema/version promotion or external transport API is implied.

The barrier serializes Work in-process, not OS/remote-provider cancellation or a real-time interrupt. The C1 detector/legacy C0 host still require trusted single-threaded hosting. A trusted producer could still invent a new cue; local digests are not signatures. Standalone `validate_result_bundle` checks internal causal consistency, not authentic issuer, admission lookup, external proof or physical truth. No new Life or Chronon authority.

## Reproducible regression evidence

Before changing the four runtime modules, re-ran the seven `test_rc01`…`test_rc07` methods on exact archived source blobs matching the reviewed stack: all seven failed for the expected reasons (RC02 multiple subcases). After applying the fix those seven and nine additional targeted methods pass. Additional tests cover explicit release, audit exhaustion, stale tickets, resource recovery, unauthorized operator, Oneiric pause, context fence/session/runtime/policy swaps, rehashed inconsistent semantics, missing companion, modified deadline/creation/provenance, and foreign cue clock/session. Two existing C0 tests updated for explicit release, not removed. Existing Core-D/RI01 and RI02 tests remain unchanged.

Local authoring used the verified archived COG #8 tree (four runtime and test paths are identical in #9), pinned Core, Core-B, Core-D and RI archives, Python 3.13.5, not fake providers. Test discovery: 138 COG, 32 genuine Core integration, 140 Core-B, 18 Core-D, 26 RI01 = 354 distinct PASS; Core-B also PASS in `-O`, Python 3.10 syntax parse PASS. RI02 suite requires the full published #9 stack, tested in remote CI rather than claimed locally. No real device, real authority, provider preemption, or N150 acceptance. Exact-head GitHub CI evidence recorded in the PR after execution.

Four previous CI-only scope guards now validate their own historical pinned delta, then call the exact RC02A guard. The allowed change list is four runtime modifications, three test modifications, four CI guard modifications, this doc and the new scope guard. All earlier commit/contract pins stay intact. No generic prefix exemption or silent baseline change.

## Still open

Independent maintainer approval and ordered integration of the stacked PRs, Core owner review of lifecycle/task/outcome/trace, replay/retention hardening outside this patch, authenticated transports, external identity/writer and actual isolated runtime acceptance. No merge or deployment is authorized by this result.
