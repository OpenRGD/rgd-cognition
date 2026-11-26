# Architecture / reconciliation baseline

Design sources: RGD-EXT-0001 DRAFT, CHRONON-MEM-0001 DRAFT,
COG-ARCH-0001 REVIEW-01 and COG Master Reconciliation of 2026-10-30.
This document summarizes accepted work direction, not normative adoption. Private
handoffs, keys, profile bundles and robot logs are deliberately not republished.

## Ownership

| Component | Owner / implementation in this PR |
|---|---|
| RGD schema/reference/profile composition | Canonical Core and EXT owners; no mutation, only declared-reference input here |
| Physical robot/Life/persona/relation registration | Identity services; no ID generation in COG |
| Safety, Life, Work, Relation, Imagination definitions/registry/ABI | RGD first-class architecture; historical code not restored by this PR |
| Safety/reflex runtime | Independent Operation/Somatic path; not inside this process |
| Time domains/anchors | Chronograf; disconnected |
| Canonical history/Chronon/Aion | Physics/history authority; disconnected |
| Memory projections/retrieval | Memory owner; only unavailable adapter here |
| Observations/scene graphs | Ingress/Perception/Voice; synthetic notifications here |
| Attention/context/assessment/proposal/trace | COG host, synchronous and bounded |
| WorldStateReader/WorldPredictor/WorldSimulator/VLA ActionPolicyProvider | Distinct future interfaces, none implemented here |
| Voice/Console/Visual output | Future typed consumers, no side effects here |

No fifth-to-first authority collapse occurs because some future noncritical modules
may share a process. Safety cannot be masked by attention. Life homeostasis is not
permission to self-issue Life identity. Microkernel ABI work remains a Core review.

## Executable foundation

The host has one alias per instance, a bounded FIFO user lane and observation lane.
After at most three user selections an observation is served when present. This is
an inexpensive attention baseline, not semantic salience or a safety scheduler.
Events are deduplicated by alias/source/session/event ID plus a full-input digest.
Conflicting reuse is rejected. Completed fingerprints use a bounded LRU cache;
there is no across-restart exactly-once guarantee. Overflow is explicit rejection.

The context is immutable-by-copy and UNBOUND. Changing a reference requires a new
host in this wave. A memory status is queried, not a historical DB. The baseline
recognizes a few exact intents; other requests abstain. No autonomous task planner,
LLM chain, vector index, training loop, policy broker or world simulator is hidden
behind those names. The purpose is to test boundaries before adding intelligence.

Proposal and trace IDs are local content digests. Input text is not copied to the
trace/response. Actual local receipt clock domains are per-host session, not
Chronograf anchors. Simulated/predicted/derived labels remain distinct. No external
reference is resolved or verified; schemas alone never authenticate input.

## Explicit next integration gates

- External RGD snapshot adapter: consume genuine canonical check/boot output and
  typed instance/Life evidence, preserving missing/stale/conflicting states.
- Memory: consume the reviewed RecallBundle and watermark semantics without
  owning history or inventing unavailable canonical events.
- Reasoning: replace baseline via explicit provider adapters with bounded RPC,
  provenance checks, independently evaluated output and privacy/egress controls.
- Voice: add authenticated local transcript/response handoff; preserve independent
  audio ownership, measured playback events and human data policy.
- World: predictive provider asynchronous and cancellable; never a reflex blocker.

`world_model.jsonc` deprecation, microkernel recovery, registry enrollment and
canonical schema promotion are deliberately outside this implementation PR.
