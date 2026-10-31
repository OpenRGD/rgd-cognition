"""COG-C0: bounded, non-actuating, session-only cognitive agenda laboratory.

No persistent memory, identity enrollment, clock authority, I/O, plugins or motors.
Every goal is admitted by local policy and is NOT an ActionIntent.
"""
from __future__ import annotations

from collections import OrderedDict
from copy import deepcopy
from dataclasses import dataclass
from time import monotonic_ns
from typing import Callable
from uuid import uuid4

from jsonschema import Draft202012Validator
from pathlib import Path
import json

from .contracts import ContractError, local_digest, validate, encode

_SCHEMA = json.loads((Path(__file__).parent / "schemas" / "agenda-c0.schema.json").read_text(encoding="utf-8"))
Draft202012Validator.check_schema(_SCHEMA)
_VALIDATORS = {
    name: Draft202012Validator({"$schema": _SCHEMA["$schema"], "$defs": _SCHEMA["$defs"], "$ref": "#/$defs/" + name})
    for name in _SCHEMA["$defs"]
}


def _check(kind: str, value: dict) -> dict:
    encode(value)
    if next(_VALIDATORS[kind].iter_errors(value), None) is not None:
        raise ContractError("AGENDA_SCHEMA:" + kind)
    return value


# These are INTERNAL lab classifications, not authenticated kernel origins.
_CUES = {
    "IMU_DISCREPANCY": ("work", "INVESTIGATE_IMU_UNCERTAINTY"),
    "POSSIBLE_FIRST_STEP": ("imagination", "REAPPRAISE_FIRST_STEP"),
    "EVIDENCE_CONFLICT": ("work", "INVESTIGATE_EVIDENCE_CONFLICT"),
}
_TERMINAL = frozenset({"COMPLETED_WITH_UNCERTAINTY", "ABSTAINED", "EXPIRED", "CANCELLED", "FAILED"})
_POLICY = "cog-c0-session-internal-readonly-v1"


class AgendaError(ValueError):
    """Fixed public error codes; no transcript or private source payloads."""


@dataclass
class _Goal:
    candidate: dict
    state: str
    deadline_ns: int
    generation: int = 0
    used_steps: int = 0
    children: int = 0


class SessionAgenda:
    """Deterministic, single-threaded Work agenda fed by already authorized events.

    The context_supplier can be `RGDGroundedHost.context` via a zero-argument
    lambda. A context revision is *not* a permission grant. Only internal
    computation is admitted, and no provider/tool is executed by this class.
    """

    def __init__(self, *, context_supplier: Callable[[], dict], clock: Callable[[], int] = monotonic_ns,
                 max_goals: int = 32, max_depth: int = 2, max_total_steps: int = 128,
                 max_audit: int = 512, resource_state: str = "UNKNOWN"):
        for value, cap in ((max_goals, 64), (max_depth, 4), (max_total_steps, 4096), (max_audit, 8192)):
            if type(value) is not int or not 1 <= value <= cap:
                raise AgendaError("INVALID_LIMIT")
        if resource_state not in {"UNKNOWN", "LOW", "NORMAL"}:
            raise AgendaError("INVALID_RESOURCE_STATE")
        self.session_id = "cog-c0-session:" + str(uuid4())  # not a boot or Life identity
        self._supplier = context_supplier
        self._clock = clock
        self._last_ns = -1
        self._max_goals, self._max_depth = max_goals, max_depth
        self._max_steps, self._audit_cap = max_total_steps, max_audit
        self._resource = resource_state
        self._steps = 0
        self._goals: OrderedDict[str, _Goal] = OrderedDict()
        self._seen: dict[tuple, tuple[str, str]] = {}
        self._decisions: dict[str, dict] = {}
        self._audit: list[dict] = []
        self._running: str | None = None
        self._closed = False

    def _now(self) -> int:
        value = self._clock()
        if type(value) is not int or value < 0 or value < self._last_ns:
            self._invalidate_active("CLOCK_REGRESSION")
            raise AgendaError("CLOCK_REGRESSION")
        self._last_ns = value
        return value

    def _context(self) -> dict:
        try:
            view = self._supplier()
            if not isinstance(view, dict) or view.get("may_actuate") is not False:
                raise AgendaError("CONTEXT_UNTRUSTED")
            if view.get("schema_version") == "cog_context_slice_v0.1-candidate":
                validate("ContextSlice", view)
            elif view.get("schema_version") == "cog_context_slice_v0.2-candidate":
                from .rgd_context import validate_context
                validate_context(view)
            else:
                raise AgendaError("CONTEXT_UNTRUSTED")
            if view.get("identity_status") not in {"UNBOUND", "UNKNOWN", "STALE", "CONFLICT"}:
                raise AgendaError("IDENTITY_NOT_SUPPORTED_IN_C0")
            if any(view.get(k) is not None for k in ("life_id", "robot_id", "agent_id", "persona_id")):
                raise AgendaError("UNVERIFIED_IDENTITY_NOT_ALLOWED")
            if not isinstance(view.get("context_revision"), str) or not view["context_revision"].startswith("sha256:"):
                raise AgendaError("CONTEXT_UNTRUSTED")
            if not isinstance(view.get("local_alias"), str):
                raise AgendaError("CONTEXT_UNTRUSTED")
            return deepcopy(view)
        except (AgendaError, ContractError):
            raise
        except Exception:
            raise AgendaError("CONTEXT_UNAVAILABLE") from None

    def _audit_event(self, goal_id: str | None, action: str, code: str, now: int) -> None:
        if len(self._audit) >= self._audit_cap:
            raise AgendaError("AUDIT_CAPACITY")
        self._audit.append(_check("AgendaAudit", {
            "schema_version": "cog_agenda_audit_v0.1-candidate", "session_id": self.session_id,
            "goal_id": goal_id, "action": action, "reason_code": code,
            "local_monotonic_ns": now, "chronon_status": "NOT_CONNECTED", "may_actuate": False,
        }))

    def _transition(self, goal_id: str, state: str, reason: str, now: int) -> None:
        self._audit_event(goal_id, state, reason, now)
        goal = self._goals[goal_id]
        if goal.state == "RUNNING" and state != "RUNNING":
            self._running = None
        goal.state = state
        goal.generation += 1  # stale callbacks cannot revive prior execution

    def _invalidate_active(self, reason: str) -> None:
        for goal_id, goal in self._goals.items():
            if goal.state not in _TERMINAL:
                # Never mutate state without an auditable transition.
                self._transition(goal_id, "CANCELLED", reason, max(0, self._last_ns))

    def _refresh(self, now: int) -> dict:
        try:
            view = self._context()
        except (AgendaError, ContractError):
            self._invalidate_active("CONTEXT_UNAVAILABLE")
            raise
        for goal_id, goal in self._goals.items():
            if goal.state in _TERMINAL:
                continue
            if now >= goal.deadline_ns:
                self._transition(goal_id, "EXPIRED", "GOAL_TTL_EXPIRED", now)
            elif goal.candidate["context_revision"] != view["context_revision"]:
                self._transition(goal_id, "CANCELLED", "CONTEXT_CHANGED", now)
        return view

    @staticmethod
    def _event_ref(event: dict) -> str:
        scope = tuple(event[k] for k in ("local_alias", "source_id", "source_session_id", "event_id"))
        return local_digest({"scope": scope, "fingerprint": local_digest(event)})

    def propose(self, event: dict, *, cue_kind: str, effect_scope: str = "INTERNAL_READ_ONLY",
                external_network: bool = False, budget_steps: int = 2, ttl_ms: int = 60000,
                parent_goal_id: str | None = None) -> dict:
        """Accept a trusted adapter cue over a validated observation; no text parsing.

        The caller must control cue_kind; it is not an authenticated kernel claim.
        A rejected proposal never executes, and does not gain authority by being logged.
        """
        if self._closed:
            raise AgendaError("AGENDA_CLOSED")
        now = self._now()
        view = self._refresh(now)
        validate("InputEvent", event)  # COG-01 schema stays unchanged.
        if event["kind"] != "OBSERVATION_NOTICE" or event["privacy_scope"] != "EPHEMERAL_LOCAL":
            raise AgendaError("UNAUTHORIZED_CUE_SOURCE")
        if event["local_alias"] != view["local_alias"]:
            raise AgendaError("INSTANCE_MISMATCH")
        if cue_kind not in _CUES:
            raise AgendaError("UNSUPPORTED_CUE")
        if type(budget_steps) is not int or not 1 <= budget_steps <= 8:
            raise AgendaError("INVALID_BUDGET")
        if type(ttl_ms) is not int or not 1 <= ttl_ms <= 300000:
            raise AgendaError("INVALID_TTL")
        if type(external_network) is not bool:
            raise AgendaError("INVALID_EFFECT_REQUEST")
        parent = None
        if parent_goal_id is not None:
            parent = self._goals.get(parent_goal_id)
            if parent is None or parent.state != "RUNNING":
                raise AgendaError("PARENT_NOT_RUNNING")
        event_ref = self._event_ref(event)
        key = (event["local_alias"], event["source_id"], event["source_session_id"],
               event["event_id"], cue_kind, parent_goal_id)
        fingerprint = local_digest(event)
        previous = self._seen.get(key)
        if previous is not None:
            if previous[0] != fingerprint:
                raise AgendaError("EVENT_ID_COLLISION")
            goal_id = previous[1]
            return {"candidate": deepcopy(self._goals[goal_id].candidate),
                    "admission": deepcopy(self._decisions[goal_id])}
        depth = parent.candidate["depth"] + 1 if parent else 0
        kernel, goal_kind = _CUES[cue_kind]
        candidate_id = local_digest({"session": self.session_id, "event_ref": event_ref,
                                     "cue": cue_kind, "parent": parent_goal_id})
        candidate = _check("GoalCandidate", {
            "schema_version": "cog_goal_candidate_v0.1-candidate", "candidate_id": candidate_id,
            "session_id": self.session_id, "context_revision": view["context_revision"],
            "source_event_ref": event_ref, "origin_role_hint": kernel, "cue_kind": cue_kind,
            "goal_kind": goal_kind, "parent_goal_id": parent_goal_id, "depth": depth,
            "evidence_refs": [event_ref, *event["source_refs"]],
            "requested_effect_scope": effect_scope, "external_network_requested": external_network,
            "requested_budget_steps": budget_steps, "ttl_ms": ttl_ms, "life_id": None,
            "chronon_status": "NOT_CONNECTED", "evidence_quality": "DECLARED_ONLY", "may_actuate": False,
        })
        reason = "ADMITTED_INTERNAL_LAB"
        admission = "ADMITTED"
        if effect_scope != "INTERNAL_READ_ONLY" or external_network:
            admission, reason = "REJECTED", "EFFECT_NOT_GRANTED"
        elif depth > self._max_depth or (parent and parent.children >= 2):
            admission, reason = "REJECTED", "CHILD_LIMIT"
        elif len(self._goals) >= self._max_goals or self._steps >= self._max_steps:
            admission, reason = "REJECTED", "AGENDA_QUOTA"
        elif self._resource != "NORMAL":
            admission, reason = "DEFERRED", "LIFE_RESOURCE_" + self._resource
        decision = _check("GoalAdmission", {
            "schema_version": "cog_goal_admission_v0.1-candidate", "candidate_id": candidate_id,
            "session_id": self.session_id, "outcome": admission,
            "reason_code": reason, "policy_revision": _POLICY,
            "granted_effect_scope": "INTERNAL_READ_ONLY" if admission == "ADMITTED" else None,
            "may_actuate": False,
        })
        self._audit_event(candidate_id, "GOAL_" + admission, reason, now)
        # When at capacity only the bounded audit record is stored, never a new
        # goal or unbounded dedup entry. No candidate is automatically retried.
        if len(self._goals) >= self._max_goals:
            return {"candidate": deepcopy(candidate), "admission": deepcopy(decision)}
        state = "QUEUED" if admission == "ADMITTED" else admission
        self._goals[candidate_id] = _Goal(candidate=deepcopy(candidate), state=state,
                                         deadline_ns=now + ttl_ms * 1_000_000)
        self._decisions[candidate_id] = deepcopy(decision)
        self._seen[key] = (fingerprint, candidate_id)
        if parent:
            parent.children += 1
        return {"candidate": deepcopy(candidate), "admission": deepcopy(decision)}

    def start_next(self) -> dict | None:
        if self._closed:
            raise AgendaError("AGENDA_CLOSED")
        now = self._now()
        self._refresh(now)
        if self._running is not None or self._resource != "NORMAL":
            return None
        for goal_id, goal in self._goals.items():
            if goal.state == "QUEUED":
                self._transition(goal_id, "RUNNING", "WORK_START", now)
                self._running = goal_id
                return self.view(goal_id)
        return None

    def run_step(self, goal_id: str, *, evidence_refs: list[str], result_code: str) -> dict:
        """Offline result admission, not model inference or proof of physical truth."""
        if self._closed:
            raise AgendaError("AGENDA_CLOSED")
        now = self._now()
        self._refresh(now)
        goal = self._goals.get(goal_id)
        if not goal or goal.state != "RUNNING" or self._resource != "NORMAL":
            raise AgendaError("GOAL_NOT_RUNNING")
        if result_code not in {"ANALYSIS_COMPLETE", "INSUFFICIENT_EVIDENCE", "ABSTAIN"}:
            raise AgendaError("UNSUPPORTED_RESULT")
        if not isinstance(evidence_refs, list) or len(evidence_refs) > 16 or len(set(evidence_refs)) != len(evidence_refs):
            raise AgendaError("INVALID_EVIDENCE")
        if not set(evidence_refs).issubset(set(goal.candidate["evidence_refs"])):
            raise AgendaError("UNKNOWN_EVIDENCE_REF")
        if self._steps >= self._max_steps or goal.used_steps >= goal.candidate["requested_budget_steps"]:
            self._transition(goal_id, "ABSTAINED", "BUDGET_EXHAUSTED", now)
        elif result_code == "ABSTAIN":
            self._transition(goal_id, "ABSTAINED", "EXPLICIT_ABSTENTION", now)
        elif result_code == "INSUFFICIENT_EVIDENCE" or not evidence_refs:
            self._transition(goal_id, "WAITING_EVIDENCE", "EVIDENCE_INSUFFICIENT", now)
        else:
            self._transition(goal_id, "COMPLETED_WITH_UNCERTAINTY", "DECLARED_EVIDENCE_ONLY", now)
        if self._steps < self._max_steps:
            self._steps += 1
        goal.used_steps += 1
        return _check("GoalOutcome", {
            "schema_version": "cog_goal_outcome_v0.1-candidate", "goal_id": goal_id,
            "session_id": self.session_id, "state": goal.state,
            "evidence_refs": evidence_refs, "verification": "UNVERIFIED",
            "chronon_status": "NOT_CONNECTED", "life_id": None, "may_actuate": False,
        })

    def set_resources(self, new_state: str) -> None:
        if self._closed:
            raise AgendaError("AGENDA_CLOSED")
        if new_state not in {"NORMAL", "LOW", "UNKNOWN"}:
            raise AgendaError("INVALID_RESOURCE_STATE")
        now = self._now()
        self._refresh(now)
        self._audit_event(None, "LIFE_RESOURCE_CHANGED", new_state, now)
        self._resource = new_state  # operator/fixture input, not physical telemetry
        if new_state != "NORMAL" and self._running:
            self._transition(self._running, "PAUSED_LIFE", "LIFE_RESOURCE_" + new_state, now)

    def interrupt_user(self, event: dict) -> None:
        if self._closed:
            raise AgendaError("AGENDA_CLOSED")
        validate("InputEvent", event)
        if event["kind"] != "USER_TEXT" or event["privacy_scope"] != "EPHEMERAL_LOCAL":
            raise AgendaError("INVALID_USER_INTERRUPTION")
        now = self._now()
        view = self._refresh(now)
        if event["local_alias"] != view["local_alias"]:
            raise AgendaError("INSTANCE_MISMATCH")
        self._audit_event(None, "USER_INTERRUPTION", "EXTERNAL_ATTENTION", now)
        if self._running:
            self._transition(self._running, "PAUSED_USER", "USER_PREEMPTION", now)

    def resume(self, goal_id: str) -> dict:
        if self._closed:
            raise AgendaError("AGENDA_CLOSED")
        now = self._now()
        self._refresh(now)
        goal = self._goals.get(goal_id)
        if not goal or goal.state not in {"PAUSED_USER", "PAUSED_LIFE", "WAITING_EVIDENCE"}:
            raise AgendaError("GOAL_NOT_RESUMABLE")
        if self._resource != "NORMAL" or self._running is not None:
            raise AgendaError("RESUME_NOT_ADMITTED")
        self._transition(goal_id, "RUNNING", "WORK_RESUME", now)
        self._running = goal_id
        return self.view(goal_id)

    def reappraise_first_step(self, goal_id: str, *, observation_tags: list[str],
                              previous: dict | None = None) -> dict:
        """Schedule a pure synthetic review only under a running Work goal."""
        if self._closed:
            raise AgendaError("AGENDA_CLOSED")
        now = self._now()
        self._refresh(now)
        goal = self._goals.get(goal_id)
        if (not goal or goal.state != "RUNNING" or self._resource != "NORMAL"
                or goal.candidate["goal_kind"] != "REAPPRAISE_FIRST_STEP"):
            raise AgendaError("ONEIRIC_GOAL_NOT_ADMITTED")
        return oneiric_review(source_event_ref=goal.candidate["source_event_ref"],
                              observation_tags=observation_tags, previous=previous)

    def accept_delegated_result(self, goal_id: str, *, generation: int, context_revision: str) -> bool:
        """Validation only; never sends network requests or applies remote effects."""
        if self._closed:
            return False
        try:
            now = self._now()
            view = self._refresh(now)
        except AgendaError:
            return False
        goal = self._goals.get(goal_id)
        return bool(goal and goal.state == "RUNNING" and generation == goal.generation
                    and context_revision == view["context_revision"] and self._resource == "NORMAL")

    def view(self, goal_id: str) -> dict:
        goal = self._goals[goal_id]
        return deepcopy({"candidate": goal.candidate, "state": goal.state,
                         "generation": goal.generation, "used_steps": goal.used_steps,
                         "children": goal.children})

    def checkpoint(self) -> dict:
        """Volatile inspection, NOT a restorable authoritative Life checkpoint."""
        if self._closed:
            raise AgendaError("AGENDA_CLOSED")
        now = self._now()
        self._refresh(now)
        return {"status": "PROVISIONAL_NONCANONICAL", "session_id": self.session_id,
                "life_id": None, "chronon_watermark": None, "chronon_status": "NOT_CONNECTED",
                "goals": {gid: {"state": g.state, "generation": g.generation,
                                "context_revision": g.candidate["context_revision"]}
                          for gid, g in self._goals.items()},
                "policy_revision": _POLICY, "may_actuate": False}

    def audit(self) -> list[dict]:
        return deepcopy(self._audit)

    def close(self) -> None:
        self._goals.clear()
        self._seen.clear()
        self._decisions.clear()
        self._audit.clear()
        self._running = None
        self._closed = True


def oneiric_review(*, source_event_ref: str, observation_tags: list[str],
                   previous: dict | None = None) -> dict:
    """Pure fixture-only reinterpretation, no real Chronon or evidence authority."""
    if not isinstance(source_event_ref, str) or not source_event_ref.startswith("sha256:"):
        raise AgendaError("INVALID_SOURCE_REF")
    if not isinstance(observation_tags, list) or len(observation_tags) > 12 or not all(isinstance(x, str) for x in observation_tags):
        raise AgendaError("INVALID_TAGS")
    if not set(observation_tags).issubset({"FOOT_LIFT", "FORWARD_DISPLACEMENT", "CONTACT_CHANGE", "NO_TRANSLATION", "IMU_UNCALIBRATED"}):
        raise AgendaError("UNSUPPORTED_TAG")
    if len(set(observation_tags)) != len(observation_tags):
        raise AgendaError("DUPLICATE_TAG")
    if previous is not None:
        _check("OneiricAnnotation", previous)
        if previous["source_event_ref"] != source_event_ref:
            raise AgendaError("ANNOTATION_SOURCE_MISMATCH")
    tags = set(observation_tags)
    if "NO_TRANSLATION" in tags:
        label = "STEP_NOT_SUPPORTED_IN_FIXTURE"
    elif {"FOOT_LIFT", "FORWARD_DISPLACEMENT", "CONTACT_CHANGE"}.issubset(tags) and "IMU_UNCALIBRATED" not in tags:
        label = "STEP_PLAUSIBLE_IN_FIXTURE"
    else:
        label = "INSUFFICIENT_EVIDENCE"
    annotation = {
        "schema_version": "cog_oneiric_annotation_v0.1-candidate",
        "source_event_ref": source_event_ref, "label": label,
        "supersedes_annotation_ref": previous["annotation_id"] if previous else None,
        "observation_tags": sorted(tags), "scope": "SYNTHETIC_FIXTURE_ONLY",
        "physical_verification": "NOT_VERIFIED", "chronon_id": None,
        "life_id": None, "may_actuate": False,
    }
    annotation["annotation_id"] = local_digest(annotation)
    return _check("OneiricAnnotation", annotation)
