# COG-C0 — Autonomous Cognitive Agenda Lab

**Candidate / experimental / non-normative / non-actuating / session-scoped.**

COG-C0 extends the *draft* COG-01 and COG-02 work without modifying their v0.1/v0.2 wire schemas. The five RGD microkernel roles remain first-class **architectural definitions**; Work, Attention, GoalAdmission, Life and Imagination runtime ownership here are **candidate lab functions**, not restored historical microkernel services or an accepted Core ABI.

## Architecture and ownership

```text
Existing typed InputEvent (COG-01)
      -> trusted, fixture-supplied AttentionCue classification
      -> Candidate goal (local Work/Imagination role hint, not authenticated kernel provenance)
      -> deterministic GoalAdmission [local strict no-effect lab policy]
      -> Work session Agenda [max one RUNNING goal]
      -> evidence-bounded, deterministic lab result / ONEIRIC review
      -> GoalOutcome / bounded AgendaAudit (local RAM only)
```

`SessionAgenda(context_supplier=lambda: host.context)` can consume an existing `RGDGroundedHost` from COG-02. Context schema v0.1 or v0.2 is checked; source hash and instance/Life trust remain the responsibility of their upstream resolver. **No imported JSON can self-grant source or identity verification.** The source revision, TTL and non-actuating constraints are rechecked before an agenda transition. A changed or unavailable source invalidates active goals.

The `cue_kind` is supplied by a **trusted lab adapter**, not extracted from an untrusted transcript or claimed to be authenticated from historical microkernel modules. Actual IMU/Perception cue adapters require separate producer-conformance review. This increment is not autonomous perception and does not contain LLM reasoning. It *does* autonomously map the typed cue to a bounded cognitive goal and admit or reject the goal without an additional user instruction.

## Denied effect surfaces

`INTERNAL_READ_ONLY` only. Explicitly deny `HISTORY_COMMIT_REQUEST`, `COMMUNICATION_REQUEST`, `DIGITAL_EFFECT_REQUEST`, `PHYSICAL_ACTION_REQUEST` and any external network access. There are no network, device, subprocess, filesystem-write, console, Voice, Chronograf or motor APIs. User-interruption is a local pause event, **not** an authenticated speaker identity or a TTS response. The `origin_role_hint` is a classification and **not an RGD kernel grant**.

`resource_state=NORMAL` must be supplied explicitly by a **synthetic/authorized caller** for the lab; default is `UNKNOWN` and defers goals. C0 does not read a physical BMS or temperature and does not turn a Life-state value into OS privileges. `LOW/UNKNOWN` suspends active tasks; the return to `NORMAL` does not silently re-admit previously deferred proposals.

## Admission, state and resource semantics

Goal candidates have finite TTL, step budgets, depth and parent refs, typed cue, source event refs, session id, context revision, declared provenance and `life_id=null`. The session is generated afresh per `SessionAgenda`, **not** a durable Life identity, `boot_id` or Chronon id.

One running goal, a fixed max 64 retained goal records (default 32), max four nesting levels (default two), max 2 children per parent, a bounded global step counter and bounded audit (default 512 events). `REJECTED/DEFERRED` are not runnable; `ADMITTED` becomes queued; queued can become running; running can be `PAUSED_USER`/`PAUSED_LIFE`, `WAITING_EVIDENCE`, `COMPLETED_WITH_UNCERTAINTY`, `ABSTAINED`, `EXPIRED`, `CANCELLED`. Stale context, TTL and local-clock regression cancel/expire; a new generation number fences old simulated callbacks after pauses and resumes.

The `AgendaAudit` is a bounded, volatile *lab log* of typed reasons (no transcript), **not a CognitiveTrace automatically committed to Chronon**. If audit capacity is exhausted, new transitions fail closed rather than happen invisibly. There is no serialization/rehydration API, and `checkpoint()` is explicitly `PROVISIONAL_NONCANONICAL`: the next process starts another independent lab session with `life_id=null`, `chronon_status=NOT_CONNECTED`, no autobiographical claim.

A result with declared evidence may finish `COMPLETED_WITH_UNCERTAINTY`, never `COMPLETED_VERIFIED`. A lack of evidence goes to `WAITING_EVIDENCE`, `ABSTAINED` or expires. Evidence reference membership is checked, but C0 has **no attested evidence service**. Model-output verification, source reliability and physical truth are future work.

The `accept_delegated_result()` function **only rejects stale simulated responses** by checking generation, context revision and live state. It does not send requests to the RTX or guarantee asynchronous process cancellation/preemption. No inference provider is installed or launched. For expensive model calls, a future worker isolation contract is required; an in-process timeout check does not stop blocked inference.

## ONEIRIC-001: first synthetic reassessment

`oneiric_review()` is pure and **fixture-only**, and `reappraise_first_step()` requires an admitted, RUNNING Work goal of type `REAPPRAISE_FIRST_STEP`. A hypothetical `POSSIBLE_FIRST_STEP` cue is assessed using explicitly synthetic observation tags. With `NO_TRANSLATION`, the revised annotation becomes `STEP_NOT_SUPPORTED_IN_FIXTURE`, superseding the earlier evaluation by reference, not editing it. With sufficient synthetic tags, `STEP_PLAUSIBLE_IN_FIXTURE` still **never means physically verified**. No Chronon is created, retagged, or deleted. The history of actual experiences must later be served by an authorized Chronon writer, with retention/consent and bitemporal review semantics from CHRONON-MEM and LIFE-CONT.

## Demo (developer-only)

```shell
python -m rgd_cognition.agenda_c0_demo --events 12
python -m unittest discover -s tests -p test_agenda_c0.py -v
```

The demo declares `fixture_only=true`, `life_id=null`, `chronon_status=NOT_CONNECTED`, zero network/digital/motor interactions, and two synthetic review revisions. Test scripts do not need the actual robot, time authority or an identity registry.

## Validation / acceptance

- Unit: synthetic cue -> admission, prohibited effects rejected, unknown Life resources deferred, user/Life pauses, resume, one running goal, stale delegation rejection, context changes, TTL, dedup/collision, child/step/audit bounds, evidence uncertainty, noncanonical checkpoint and Oneiric supersession. Tests temporarily replace socket/Popen with faulting implementations in exercised paths; not an OS isolation proof.
- Real upstream: separate integration suite uses existing `RGDContextResolver` + `RGDGroundedHost`, pinned BHL canonical profile, checks real RGD source integrity without fabricating Robot/Life IDs or authorization.
- CI: Python 3.10/3.12, foundation, source-context conformance, synthetic demo and wheel smoke. These are software tests, not N150 latency/CPU or 8-hour wall-clock soak measurements.

## Deferred P0/P1 external responsibilities

- **Core:** microkernel ABI, canonical source compatibility, distinct effect taxonomy/permissions, Life-Agent-Runtime identity/role fencing, versioned policy and admission semantics.
- **RGD-EXT:** forge (validated local vs official publication), robot enrollment, issuer/Registry authority, verified Life binding.
- **Chronograf/Physics/Memory:** writer/reader conformance, durable experience, provenance, bitemporal annotation, retention/erasure, Oneiric/RecallBundle interoperability.
- **COG:** true model reasoning adapter, robust safe preemption, Memory and Perception cue producers, session agenda integration, COG proposal/trace bridge, full lifecycle metrics.
- **Somatic/Relation:** independent real-time physical gate, digital and communication effect gates.

**No merge, release, enrollment, Core/instance file change, CAN access, OS sandbox installation or Paky-01 deployment is included.**
