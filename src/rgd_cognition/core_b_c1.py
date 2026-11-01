"""Opt-in C1 producer -> Core-B local consumer; no second C0 admission.

Exact C1 source preserved. Source sample transport/authentication remains external.
"""
from __future__ import annotations
from copy import deepcopy
from time import monotonic_ns
from uuid import uuid4

from .attention_c1 import ImuAttention, _validate, _digest
from .contracts import validate, local_digest
from .rgd_context import validate_context
from .core_b_adapter import (CoreBSchema, LocalOwners, Limits, KernelSession,
                             BridgeError, require, digest, make_goal, check_detail)


def cue_goal(schema, cue, *, context, created_ns: int, clock_domain: str,
             producer_ref: str, budget: dict):
    """Explicit host capture time; conservative ns/ms conversion never renews TTL."""
    _validate("AttentionCue", cue)
    require(_digest({k: v for k, v in cue.items() if k != "cue_id"}) == cue["cue_id"], "CUE_DIGEST_MISMATCH")
    require(cue["cue_kind"] == "IMU_DISCREPANCY", "UNSUPPORTED_CUE")
    require(type(created_ns) is int and created_ns >= 0, "CREATION_TIME_REQUIRED")
    require(cue["receipt_clock_domain"] == clock_domain, "CLOCK_UNALIGNED")
    require(cue["context_revision"] == context["revision"], "CONTEXT_OR_FENCE_MISMATCH")
    start_ms = (created_ns + 999999) // 1000000
    end_ms = cue["expires_at_monotonic_ns"] // 1000000
    require(end_ms > start_ms, "CUE_EXPIRED")
    # Ceiling start can defer acceptance by <1ms, never lengthen validity.
    goal = make_goal(schema, goal_id=cue["cue_id"], task_ref="cog.task.v1:imu-uncertainty",
                     context=context, clock_domain=clock_domain, created_ms=start_ms,
                     ttl_ms=end_ms-start_ms, producer_ref=producer_ref, origin="Work", budget=budget,
                     evidence_refs=cue["source_refs"],
                     provenance_class="SYNTHETIC" if cue["origin"] == "SYNTHETIC" else "DERIVED")
    detail = {"schema_version": "cog_core_b_task_detail_v1-candidate",
              "goal_id": goal["goal_id"], "goal_revision": goal["goal_revision"],
              "task_ref": goal["task_ref"], "source_cue": deepcopy(cue),
              "created_monotonic_ns": created_ns, "deadline_monotonic_ns": cue["expires_at_monotonic_ns"],
              "success_condition": "ANALYSIS_REPORTED_NOT_HYPOTHESIS_CONFIRMED",
              "stop_conditions": ["ORIGINAL_EVIDENCE_EXPIRED", "BUDGET_EXHAUSTED", "CONTEXT_CHANGED"],
              "evidence_quality": "DECLARED_ONLY", "verification": "UNVERIFIED", "life_id": None,
              "chronon_id": None, "grants_authority": False}
    return {"goal": goal, "detail": check_detail("TaskDetail", detail)}


class CoreBAttentionHost:
    """Trusted host owns all channels; do not hand this object to untrusted Python.

    A runtime UUID identifies this execution only. `role_fence` is local host
    configuration, not a verified/exclusive distributed lease or a Life epoch.
    """
    def __init__(self, schema_bytes, *, context_supplier, binding, policy=None,
                 attention_policy=None, clock=monotonic_ns, role_fence=0):
        require(type(role_fence) is int and 0 <= role_fence <= 2147483647, "INVALID_ROLE_FENCE")
        self._clock, self._supplier = clock, context_supplier
        self._policy = policy or Limits()
        self.schema = CoreBSchema(schema_bytes)
        self.owners = LocalOwners()
        self.attention = ImuAttention(binding, policy=attention_policy, clock=clock)
        self.runtime_id = "cog.core-b.runtime:" + str(uuid4())
        self._fence, self._paused, self._closed = role_fence, False, False
        self._resource = "UNKNOWN"
        self.work = KernelSession(self.schema, owners=self.owners, policy=self._policy,
                                  context_supplier=self._context, clock_ms=lambda: self.attention.now() // 1000000,
                                  clock_domain=self.attention.session_id)

    def _context(self):
        view = deepcopy(self._supplier())
        if view.get("schema_version") == "cog_context_slice_v0.2-candidate":
            validate_context(view)
            require(view["reference_status"] == "SOURCE_INTEGRITY_VERIFIED", "RGD_CONTEXT_NOT_CURRENT")
        else:
            validate("ContextSlice", view)
            require(local_digest({k: v for k, v in view.items() if k != "context_revision"}) == view["context_revision"],
                    "CONTEXT_REVISION_MISMATCH")
            require(self.attention.binding.mode == "SYNTHETIC_REPLAY", "LIVE_REQUIRES_RGD_CONTEXT")
        require(view["local_alias"] == self.attention.binding.local_alias, "ALIAS_MISMATCH")
        require(view["identity_status"] in {"UNBOUND", "UNKNOWN"} and
                all(view[k] is None for k in ("robot_id", "life_id", "agent_id", "persona_id")), "IDENTITY_UNSUPPORTED")
        return {"revision": view["context_revision"], "policy_revision": self._policy.revision,
                "session_id": self.attention.session_id, "runtime_instance_id": self.runtime_id,
                "scope": "SESSION_SCOPED", "life_binding_ref": None, "life_activation_epoch": None,
                "role_fencing_generation": self._fence}

    def ingest(self, payload, *, received_ns: int, freshness="UNKNOWN", consent=False):
        require(not self._closed, "HOST_CLOSED")
        try:
            self.work.inspect()
            ctx = self._context()
            result = self.attention.observe(payload, received_ns=received_ns, freshness=freshness,
                consent=consent, context_revision=ctx["revision"],
                allow_goal_generation=self._resource == "NORMAL" and not self._paused)
            if result["cue"] is None:
                return {"attention": result, "proposal": None}
            created_ns = self.attention.now()
            package = cue_goal(self.schema, result["cue"], context=ctx, created_ns=created_ns,
                clock_domain=self.attention.session_id, producer_ref=self.owners.producer(self.owners.attention)[0],
                budget={"wall_time_ms": 1000, "steps": 2, "subgoals": 0, "depth": 0, "queue_items": 1})
            decision = self.work.submit(self.owners.attention, package["goal"], key=result["cue"]["cue_id"])
            return {"attention": result, "proposal": {**package, "admission": decision}}
        except (BridgeError, ValueError):
            self.attention.invalidate()
            raise

    def set_resources(self, channel, state):
        self.work.set_resources(channel, state)
        self._resource = state
        self.attention.invalidate()

    def interrupt_user(self, channel):
        self.owners.owner(channel, "operator")
        report = self.work.inspect()
        for gid, item in report["goals"].items():
            if item["state"] == "RUNNING":
                self.work.move(self.owners.work, gid, "PAUSED", reason="PAUSED_USER",
                               key=digest({"user-pause": gid, "generation": item["generation"]}))
        self._paused = True
        self.attention.invalidate()

    def release_user_attention(self, channel):
        self.owners.owner(channel, "operator")
        self.work.inspect()
        self._paused = False  # Explicit Work resume remains separately required.

    def close(self):
        self.work.close()
        self.attention.close()
        self._closed = True
