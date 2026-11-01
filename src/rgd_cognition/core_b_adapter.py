"""Opt-in Core-B consumer. Session-only; no effects, devices, or Core runtime.

Trusted in-process host provisions owners/policy/clock. Object-identity channels
are NOT remote authentication or an OS sandbox. Existing C0/C1 paths are intact.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
import hashlib
import json
import re
from threading import RLock
from typing import Callable

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

CORE_B_COMMIT = "55a034ceb1cdaab8bed6848fcdde85c9436bc9e0"
CORE_B_SCHEMA_BLOB = "ac1eb0809384214f81164bfc5a9daf8ad7ec66e0"
ENCODING_PROFILE = "COG_CORE_B_SORTED_JSON_INTEGER_V1"
TYPES = ("KernelDescriptor", "KernelEvent", "CognitiveGoalCandidate",
         "GoalAdmissionDecision", "AgendaTransition", "EffectRequest", "EffectGateDecision")
REF = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:/#@+-]{0,255}\Z")
TERMINAL = frozenset({"COMPLETED", "CANCELLED", "REJECTED", "FAILED"})
TASKS = {
    "cog.task.v1:imu-uncertainty": ("INVESTIGATE", "IMU_DISCREPANCY"),
    "cog.task.v1:oneiric-first-step": ("ONEIRIC_REVIEW", "POSSIBLE_FIRST_STEP"),
}


class BridgeError(ValueError):
    """Fixed public code only; no payload/path/credential disclosure."""


def require(condition: bool, code: str) -> None:
    if not condition:
        raise BridgeError(code)


def wire(value) -> bytes:
    """Negotiated local integer-only encoding; NOT RGD/Chronon canonicalization."""
    stack, count = [(value, 0)], 0
    while stack:
        obj, depth = stack.pop()
        count += 1
        require(depth <= 24 and count <= 4096, "STRUCTURE_LIMIT")
        if type(obj) is dict:
            require(all(type(k) is str for k in obj), "INVALID_JSON_KEY")
            stack.extend((v, depth + 1) for v in obj.values())
        elif type(obj) is list:
            stack.extend((v, depth + 1) for v in obj)
        elif type(obj) is int:
            require(abs(obj) <= 9007199254740991, "INTEGER_LIMIT")
        elif type(obj) is str:
            require(len(obj) <= 65536, "STRING_LIMIT")
        elif obj is not None and type(obj) is not bool:
            raise BridgeError("NON_PROTOCOL_VALUE")
    try:
        raw = json.dumps(value, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (ValueError, TypeError, UnicodeError):
        raise BridgeError("INVALID_JSON") from None
    require(len(raw) <= 65536, "RECORD_LIMIT")
    return raw


def digest(value) -> str:
    return "sha256:" + hashlib.sha256(wire(value)).hexdigest()


def decode(raw: bytes) -> dict:
    require(type(raw) is bytes and len(raw) <= 65536, "RECORD_LIMIT")
    def pairs(items):
        out = {}
        for key, value in items:
            require(key not in out, "DUPLICATE_KEY")
            out[key] = value
        return out
    def bad(_value):
        raise BridgeError("NON_PROTOCOL_VALUE")
    try:
        result = json.loads(raw, object_pairs_hook=pairs, parse_constant=bad)
    except (ValueError, UnicodeError, RecursionError):
        raise BridgeError("INVALID_JSON") from None
    wire(result)
    require(type(result) is dict, "OBJECT_REQUIRED")
    return result


class CoreBSchema:
    """Exact pinned schema bytes supplied by operator; offline resolution only."""
    def __init__(self, schema_bytes: bytes):
        require(type(schema_bytes) is bytes and len(schema_bytes) <= 65536, "SCHEMA_LIMIT")
        blob = hashlib.sha1(b"blob " + str(len(schema_bytes)).encode() + b"\0" + schema_bytes).hexdigest()
        require(blob == CORE_B_SCHEMA_BLOB, "CANDIDATE_SCHEMA_PIN_MISMATCH")
        schema = decode(schema_bytes)
        Draft202012Validator.check_schema(schema)
        registry = Registry().with_resource(schema["$id"], Resource.from_contents(schema))
        self._validators = {name: Draft202012Validator(
            {"$schema": schema["$schema"], "$ref": schema["$id"] + "#/$defs/" + name},
            registry=registry) for name in (*TYPES, "Context", "Budget", "Lifetime")}

    def check(self, kind: str, value: dict) -> dict:
        require(kind in self._validators, "UNKNOWN_CONTRACT")
        wire(value)
        require(next(self._validators[kind].iter_errors(value), None) is None, "SCHEMA_VIOLATION:" + kind)
        return deepcopy(value)


_DETAIL_SCHEMA = json.loads((Path(__file__).parent / "schemas/core-b-local.schema.json").read_text(encoding="utf-8"))
Draft202012Validator.check_schema(_DETAIL_SCHEMA)
_DETAIL_VALIDATORS = {name: Draft202012Validator({"$schema": _DETAIL_SCHEMA["$schema"],
    "$defs": _DETAIL_SCHEMA["$defs"], "$ref": "#/$defs/" + name}) for name in _DETAIL_SCHEMA["$defs"]}


def check_detail(kind: str, value: dict) -> dict:
    require(kind in _DETAIL_VALIDATORS, "UNKNOWN_DETAIL")
    wire(value)
    require(next(_DETAIL_VALIDATORS[kind].iter_errors(value), None) is None, "INVALID_DETAIL")
    return deepcopy(value)


def goal_revision(goal: dict) -> str:
    return digest({k: v for k, v in goal.items() if k != "goal_revision"})


@dataclass(frozen=True)
class Limits:
    """Host policy, never loaded from a proposed goal. Finite session quotas."""
    revision: str = "cog-core-b-internal-v1"
    enabled: bool = False
    total_steps: int = 32
    total_wall_ms: int = 60000
    queue_items: int = 8
    records: int = 256
    max_depth: int = 2
    max_children: int = 2
    def __post_init__(self):
        require(type(self.revision) is str and REF.fullmatch(self.revision), "INVALID_POLICY")
        require(type(self.enabled) is bool, "INVALID_POLICY")
        for value, low, high in ((self.total_steps, 1, 4096), (self.total_wall_ms, 1, 3600000),
                                 (self.queue_items, 1, 64), (self.records, 8, 4096),
                                 (self.max_depth, 0, 4), (self.max_children, 0, 16)):
            require(type(value) is int and low <= value <= high, "INVALID_POLICY")


class LocalOwners:
    """Host-owned capability channels; payload strings cannot impersonate them.

    All loaded Python remains trusted. No cryptographic, network, distributed or
    persistent identity guarantee. Do not expose operator/work tokens to models.
    """
    def __init__(self):
        self.operator, self.work, self.attention, self.model = (object() for _ in range(4))
        self.admission_ref = "cog.local:admission"
        self.work_ref = "cog.local:work"
        self._producers = {self.attention: ("cog.local:attention", "Work"),
                           self.model: ("cog.local:model", "MODEL")}

    def producer(self, channel) -> tuple[str, str]:
        for token, producer in self._producers.items():
            if channel is token:
                return producer
        raise BridgeError("UNAUTHENTICATED_PRODUCER")

    def owner(self, channel, role: str) -> None:
        require(channel is getattr(self, role), "WRONG_" + role.upper() + "_OWNER")


@dataclass
class _Job:
    goal: dict
    decision: dict
    state: str
    detail: dict
    generation: int = 0
    sequence: int = 0
    previous: str | None = None
    children: int = 0
    remaining_steps: int = 0
    remaining_wall: int = 0
    slots: int = 0
    last_run_ms: int | None = None
    released: bool = False
    transitions: list = field(default_factory=list)


class KernelSession:
    """One admission + reservation owner in a bounded, serialized local session.

    Replaces (does NOT chain after) C0 admission on the opt-in path. No providers
    are executed. Results are admitted as UNVERIFIED, never as physical success.
    """
    def __init__(self, schema: CoreBSchema, *, owners: LocalOwners, policy: Limits,
                 context_supplier: Callable[[], dict], clock_ms: Callable[[], int], clock_domain: str):
        require(isinstance(schema, CoreBSchema) and isinstance(owners, LocalOwners)
                and isinstance(policy, Limits), "INVALID_HOST_CONFIGURATION")
        require(type(clock_domain) is str and REF.fullmatch(clock_domain), "INVALID_CLOCK_DOMAIN")
        self.schema, self._owners, self._policy = schema, owners, policy
        self._supplier, self._clock, self.clock_domain = context_supplier, clock_ms, clock_domain
        self._lock = RLock()
        self._last = -1
        self._closed = False
        self._resource = "UNKNOWN"
        self._seen = {}
        self._jobs: dict[str, _Job] = {}
        self._audit = []
        self._spent_steps = self._spent_wall = 0
        self._bound_context = self._context()

    def _context(self):
        try:
            ctx = self.schema.check("Context", self._supplier())
        except Exception:
            raise BridgeError("CONTEXT_UNAVAILABLE") from None
        require(ctx["scope"] == "SESSION_SCOPED" and ctx["life_binding_ref"] is None
                and ctx["life_activation_epoch"] is None, "LIFE_BOUND_UNSUPPORTED")
        require(ctx["policy_revision"] == self._policy.revision
                and type(ctx["role_fencing_generation"]) is int, "POLICY_OR_FENCE_UNBOUND")
        return ctx

    def _now(self):
        require(not self._closed, "SESSION_CLOSED")
        now = self._clock()
        if type(now) is not int or not 0 <= now <= 9007199254740991 or now < self._last:
            self._closed = True
            self._stop_all("CLOCK_REGRESSION")
            raise BridgeError("CLOCK_REGRESSION")
        self._last = now
        return now

    def _release(self, job):
        if not job.released:
            job.remaining_steps = job.remaining_wall = job.slots = 0
            job.released = True

    def _stop(self, job, reason):
        if job.state not in TERMINAL:
            job.state = "CANCELLED"
            job.generation += 1
            job.last_run_ms = None
            job.detail = {"code": reason, "verification": "UNVERIFIED", "local_invalidation": True}
            self._release(job)

    def _stop_all(self, reason):
        for job in self._jobs.values():
            self._stop(job, reason)

    def _current(self):
        now = self._now()
        try:
            ctx = self._context()
        except BridgeError:
            self._stop_all("CONTEXT_UNAVAILABLE")
            raise
        if ctx != self._bound_context:
            self._stop_all("CONTEXT_OR_FENCE_CHANGED")
            raise BridgeError("CONTEXT_OR_FENCE_CHANGED")
        for job in self._jobs.values():
            if job.state in TERMINAL:
                continue
            if job.state == "RUNNING" and job.last_run_ms is not None:
                elapsed = now - job.last_run_ms
                charge = min(elapsed, job.remaining_wall)
                job.remaining_wall -= charge
                self._spent_wall += charge
                job.last_run_ms = now
                if not job.remaining_wall:
                    self._stop(job, "WALL_BUDGET_EXHAUSTED")
            lifetime = job.goal["lifetime"]
            if now >= lifetime["created_ms"] + lifetime["ttl_ms"]:
                self._stop(job, "EXPIRED")
        # An ended parent cannot leave autonomous descendants active.
        for _ in range(self._policy.max_depth + 1):
            for job in self._jobs.values():
                parent = self._jobs.get(job.goal["parent_goal_id"])
                if parent and parent.state in TERMINAL:
                    self._stop(job, "PARENT_TERMINATED")
        return now, ctx

    def _lifetime(self, record, now, ctx):
        require(record["context"] == ctx, "CONTEXT_OR_FENCE_MISMATCH")
        life = record["lifetime"]
        require(life["quality"] == "MONOTONIC_SESSION" and life["clock_domain"] == self.clock_domain,
                "CLOCK_UNALIGNED")
        require(life["created_ms"] <= now < life["created_ms"] + life["ttl_ms"], "EXPIRED_OR_FUTURE")

    def _remembered(self, principal, key, fingerprint):
        require(type(key) is str and REF.fullmatch(key), "INVALID_IDEMPOTENCY_KEY")
        scoped = (principal, self._bound_context["session_id"], key)
        if scoped in self._seen:
            old, result = self._seen[scoped]
            require(old == fingerprint, "IDEMPOTENCY_CONFLICT")
            return scoped, deepcopy(result)
        require(len(self._seen) < self._policy.records and len(self._audit) < self._policy.records,
                "BACKPRESSURE")
        return scoped, None

    def _remember(self, scoped, fingerprint, result):
        self._seen[scoped] = (fingerprint, deepcopy(result))
        self._audit.append({"key": scoped[2], "fingerprint": fingerprint})

    def _usage(self):
        return {"spent_steps": self._spent_steps, "spent_wall_ms": self._spent_wall,
                "reserved_steps": sum(j.remaining_steps for j in self._jobs.values()),
                "reserved_wall_ms": sum(j.remaining_wall for j in self._jobs.values()),
                "reserved_slots": sum(j.slots for j in self._jobs.values()),
                "idempotency_entries": len(self._seen)}

    def submit(self, channel, goal: dict, *, key: str) -> dict:
        with self._lock:
            producer, origin = self._owners.producer(channel)
            goal = self.schema.check("CognitiveGoalCandidate", goal)
            now, ctx = self._current()
            self._lifetime(goal, now, ctx)
            require(goal["provenance"]["producer_ref"] == producer and goal["origin"] == origin,
                    "PRODUCER_ROLE_MISMATCH")
            require(goal_revision(goal) == goal["goal_revision"], "GOAL_REVISION_MISMATCH")
            scoped, old = self._remembered(producer, key, digest(goal))
            if old is not None:
                return old
            require(goal["goal_id"] not in self._jobs, "GOAL_ID_CONFLICT")
            require(len(self._jobs) < self._policy.records, "BACKPRESSURE")
            budget = goal["budget"]
            reason, outcome = "ADMITTED_INTERNAL_READ_ONLY", "ADMIT"
            parent = self._jobs.get(goal["parent_goal_id"])
            usage = self._usage()
            if not self._policy.enabled:
                reason, outcome = "POLICY_DISABLED", "REJECT"
            elif goal["requested_effects"] != ["INTERNAL_READ_ONLY"]:
                reason, outcome = "EFFECT_NOT_GRANTED", "REJECT"
            elif goal["task_ref"] not in TASKS or TASKS[goal["task_ref"]][0] != goal["goal_kind"]:
                reason, outcome = "UNKNOWN_TYPED_TASK", "REJECT"
            elif goal["provenance"]["class"] not in {"DERIVED", "SYNTHETIC", "FIXTURE"}:
                reason, outcome = "EVIDENCE_UPGRADE_REFUSED", "REJECT"
            elif (goal["depth"] > min(budget["depth"], self._policy.max_depth)
                  or budget["depth"] > self._policy.max_depth
                  or budget["subgoals"] > self._policy.max_children):
                reason, outcome = "DEPTH_OR_CHILD_LIMIT", "REJECT"
            elif goal["parent_goal_id"] is not None and (parent is None or parent.state != "RUNNING"
                    or parent.goal["context"] != ctx or goal["depth"] != parent.goal["depth"] + 1
                    or parent.children >= parent.goal["budget"]["subgoals"]
                    or budget["depth"] > parent.goal["budget"]["depth"]):
                reason, outcome = "PARENT_NOT_ELIGIBLE", "REJECT"
            elif self._resource != "NORMAL":
                reason, outcome = "RESOURCE_" + self._resource, "DEFER"
            elif (usage["spent_steps"] + usage["reserved_steps"] + budget["steps"] > self._policy.total_steps
                  or usage["spent_wall_ms"] + usage["reserved_wall_ms"] + budget["wall_time_ms"] > self._policy.total_wall_ms
                  or usage["reserved_slots"] + budget["queue_items"] > self._policy.queue_items):
                reason, outcome = "AGGREGATE_BUDGET_EXHAUSTED", "DEFER"
            decision = self.schema.check("GoalAdmissionDecision", {
                "schema_version": "openrgd_goal_admission_decision_v0.1-candidate",
                "decision_id": digest({"decision": goal["goal_revision"], "key": key, "outcome": outcome}),
                "goal_id": goal["goal_id"], "goal_revision": goal["goal_revision"],
                "admission_authority_ref": self._owners.admission_ref,
                "outcome": outcome, "reason_codes": [reason],
                "eligible_effects": ["INTERNAL_READ_ONLY"] if outcome == "ADMIT" else [],
                "evaluated_grant_refs": [], "allocated_budget": budget if outcome == "ADMIT" else None,
                "context": ctx, "lifetime": deepcopy(goal["lifetime"]), "grants_authority": False})
            state = "ADMITTED" if outcome == "ADMIT" else ("REJECTED" if outcome == "REJECT" else "PROPOSED")
            job = _Job(goal, decision, state, {"code": reason, "verification": "UNVERIFIED"})
            if outcome == "ADMIT":
                job.remaining_steps, job.remaining_wall, job.slots = budget["steps"], budget["wall_time_ms"], budget["queue_items"]
                if parent:
                    parent.children += 1
                self._transition(job, "PROPOSED", "ADMITTED", "ADMISSION_ACCEPTED", key + ":admit", now)
            else:
                job.released = True
            self._jobs[goal["goal_id"]] = job
            self._remember(scoped, digest(goal), decision)
            return deepcopy(decision)

    def _transition(self, job, from_state, to_state, reason, key, now):
        life = job.goal["lifetime"]
        record = self.schema.check("AgendaTransition", {
            "schema_version": "openrgd_agenda_transition_v0.1-candidate",
            "transition_id": digest({"goal": job.goal["goal_revision"], "seq": job.sequence,
                                     "key": key, "from": from_state, "to": to_state}),
            "goal_id": job.goal["goal_id"], "goal_revision": job.goal["goal_revision"],
            "admission_ref": job.decision["decision_id"], "previous_transition_ref": job.previous,
            "sequence": job.sequence, "from_state": from_state, "to_state": to_state,
            "work_owner_ref": self._owners.work_ref, "idempotency_key": digest(key),
            "context": deepcopy(job.goal["context"]),
            "lifetime": {**life, "created_ms": now, "ttl_ms": life["created_ms"] + life["ttl_ms"] - now},
            "grants_authority": False})
        detail = {"schema_version": "cog_core_b_transition_detail_v1-candidate",
                  "transition_ref": record["transition_id"], "task_ref": job.goal["task_ref"],
                  "reason_code": reason, "verification": "UNVERIFIED", "chronon_id": None, "life_id": None}
        job.previous = record["transition_id"]
        job.sequence += 1
        job.generation += 1
        job.state = to_state
        job.last_run_ms = now if to_state == "RUNNING" else None
        job.detail = check_detail("TransitionDetail", detail)
        job.transitions.append({"transition": record, "detail": detail})
        return deepcopy(job.transitions[-1])

    def move(self, channel, goal_id: str, to_state: str, *, key: str, reason: str = "WORK_REQUEST") -> dict:
        with self._lock:
            self._owners.owner(channel, "work")
            now, _ = self._current()
            require(reason in {"WORK_REQUEST", "PAUSED_USER", "PAUSED_LIFE", "WAITING_EVIDENCE", "USER_CANCELLED"},
                    "UNKNOWN_TRANSITION_REASON")
            fingerprint = digest({"goal": goal_id, "to": to_state, "reason": reason})
            scoped, old = self._remembered(self._owners.work_ref, key, fingerprint)
            if old is not None:
                return old
            job = self._jobs.get(goal_id)
            require(job is not None and job.decision["outcome"] == "ADMIT", "GOAL_NOT_ADMITTED")
            allowed = {"ADMITTED": {"RUNNING", "CANCELLED"}, "RUNNING": {"PAUSED", "CANCELLED", "FAILED"},
                       "PAUSED": {"RUNNING", "CANCELLED", "FAILED"}}
            require(to_state in allowed.get(job.state, set()), "ILLEGAL_TRANSITION")
            if to_state == "RUNNING":
                require(self._resource == "NORMAL", "RESOURCE_NOT_AVAILABLE")
                require(not any(j.state == "RUNNING" for j in self._jobs.values()), "RUNNING_SLOT_BUSY")
                require(job.remaining_steps > 0 and job.remaining_wall > 0, "BUDGET_EXHAUSTED")
            record = self._transition(job, job.state, to_state, reason, key, now)
            if to_state in TERMINAL:
                self._release(job)
            self._remember(scoped, fingerprint, record)
            return record

    def ticket(self, channel, goal_id: str) -> dict:
        with self._lock:
            self._owners.owner(channel, "work")
            self._current()
            job = self._jobs.get(goal_id)
            require(job is not None and job.state == "RUNNING" and self._resource == "NORMAL", "NOT_RUNNING")
            return {"goal_id": goal_id, "goal_revision": job.goal["goal_revision"],
                    "context": deepcopy(job.goal["context"]), "task_generation": job.generation}

    def finish(self, channel, ticket: dict, *, code: str, evidence_refs: list[str], key: str) -> dict:
        with self._lock:
            self._owners.owner(channel, "work")
            now, _ = self._current()
            fingerprint = digest({"ticket": ticket, "code": code, "evidence_refs": evidence_refs})
            scoped, old = self._remembered(self._owners.work_ref, key, fingerprint)
            if old is not None:
                return old
            require(type(ticket) is dict and set(ticket) == {"goal_id", "goal_revision", "context", "task_generation"},
                    "INVALID_TICKET")
            job = self._jobs.get(ticket["goal_id"])
            require(job is not None and job.state == "RUNNING" and self._resource == "NORMAL", "NOT_RUNNING")
            expected = {"goal_id": job.goal["goal_id"], "goal_revision": job.goal["goal_revision"],
                        "context": job.goal["context"], "task_generation": job.generation}
            require(wire(ticket) == wire(expected), "STALE_TASK_RESULT")
            require(code in {"ANALYSIS_COMPLETE", "INSUFFICIENT_EVIDENCE", "ABSTAIN"}, "UNKNOWN_OUTCOME")
            require(type(evidence_refs) is list and all(type(r) is str for r in evidence_refs)
                    and len(evidence_refs) <= 64 and len(set(evidence_refs)) == len(evidence_refs), "INVALID_EVIDENCE")
            require(set(evidence_refs) <= set(job.goal["provenance"]["evidence_refs"]), "UNKNOWN_EVIDENCE")
            require(job.remaining_steps > 0, "BUDGET_EXHAUSTED")
            if code == "ANALYSIS_COMPLETE":
                require(bool(evidence_refs), "EVIDENCE_REQUIRED")
            job.remaining_steps -= 1
            self._spent_steps += 1
            to_state = "PAUSED" if code == "INSUFFICIENT_EVIDENCE" else "COMPLETED"
            # COMPLETED describes the inquiry, not the truth of a physical claim.
            result = self._transition(job, job.state, to_state, code, key, now)
            result["outcome"] = {"schema_version": "cog_core_b_outcome_v1-candidate", "code": code,
                                 "verification": "UNVERIFIED", "evidence_refs": evidence_refs,
                                 "task_generation": ticket["task_generation"], "grants_authority": False}
            check_detail("Outcome", result["outcome"])
            if to_state in TERMINAL:
                self._release(job)
            self._remember(scoped, fingerprint, result)
            return deepcopy(result)

    def set_resources(self, channel, state: str) -> None:
        with self._lock:
            self._owners.owner(channel, "operator")
            require(type(state) is str and state in {"UNKNOWN", "LOW", "NORMAL"}, "INVALID_RESOURCE_STATE")
            now, _ = self._current()
            if state != "NORMAL":
                for job in self._jobs.values():
                    if job.state == "RUNNING":
                        try:
                            self.move(self._owners.work, job.goal["goal_id"], "PAUSED",
                                      key=digest({"resource-pause": job.goal["goal_id"],
                                                  "generation": job.generation}), reason="PAUSED_LIFE")
                        except BridgeError:
                            self._stop_all("AUDIT_EXHAUSTED")
                            self._closed = True
                            raise
            self._resource = state

    def accept_record(self, channel, kind: str, record: dict, *, payload: dict | None = None):
        """Only negotiated goal events enter the runtime; no generic tool dispatch."""
        with self._lock:
            producer, _ = self._owners.producer(channel)
            item = self.schema.check(kind, record)
            now, ctx = self._current()
            if "context" in item:
                self._lifetime(item, now, ctx)
            require(kind == "KernelEvent", "RECORD_NOT_INGESTIBLE")
            require(item["kind"] == "openrgd.kernel.v0_1.goal_candidate", "UNNEGOTIATED_EVENT_KIND")
            require(item["producer_kernel_id"] == producer and item["provenance"]["producer_ref"] == producer,
                    "PRODUCER_ROLE_MISMATCH")
            goal = self.schema.check("CognitiveGoalCandidate", payload)
            require(item["payload_ref"] == goal["goal_id"] and item["payload_digest"] == digest(goal)
                    and item["context"] == goal["context"] and item["lifetime"] == goal["lifetime"]
                    and item["provenance"] == goal["provenance"],
                    "PAYLOAD_BINDING_MISMATCH")
            fingerprint = digest({"event": item, "payload": goal})
            scoped, old = self._remembered(producer, item["idempotency_key"], fingerprint)
            if old is not None:
                return old
            require(len(self._seen) + 2 <= self._policy.records and
                    len(self._audit) + 2 <= self._policy.records, "BACKPRESSURE")
            result = self.submit(channel, goal, key=digest({"event-key": scoped[2]}))
            self._remember(scoped, fingerprint, result)
            return result

    def reject_effect(self, channel, request: dict):
        with self._lock:
            self._owners.owner(channel, "work")
            self.schema.check("EffectRequest", request)
            now, ctx = self._current()
            self._lifetime(request, now, ctx)
            # No externally authenticated gates exist in this profile, even for
            # a supplied ALLOW receipt. Local computation uses the Work API only.
            raise BridgeError("EFFECT_GATE_NOT_CONNECTED")

    def inspect(self) -> dict:
        with self._lock:
            self._current()
            return {"scope": "SESSION_SCOPED", "life_id": None, "chronon_status": "NOT_CONNECTED",
                    "resource": self._resource, "usage": self._usage(),
                    "goals": {k: {"state": j.state, "generation": j.generation, "detail": deepcopy(j.detail)}
                              for k, j in self._jobs.items()}}

    def transitions(self, goal_id):
        with self._lock:
            return deepcopy(self._jobs[goal_id].transitions)

    def close(self):
        with self._lock:
            self._stop_all("SESSION_CLOSED")
            self._closed = True
            self._seen.clear()
            self._jobs.clear()
            self._audit.clear()


def make_goal(schema: CoreBSchema, *, goal_id: str, task_ref: str, context: dict, clock_domain: str,
              created_ms: int, ttl_ms: int, producer_ref: str, origin: str, budget: dict,
              evidence_refs: list[str], provenance_class: str = "SYNTHETIC",
              parent_goal_id: str | None = None, depth: int = 0) -> dict:
    """Producer only. Cannot admit goals; all claims are rechecked by consumer."""
    require(task_ref in TASKS, "UNKNOWN_TYPED_TASK")
    record = {"schema_version": "openrgd_cognitive_goal_candidate_v0.1-candidate", "goal_id": goal_id,
              "goal_revision": "sha256:" + "0" * 64, "parent_goal_id": parent_goal_id, "depth": depth,
              "origin": origin, "goal_kind": TASKS[task_ref][0], "task_ref": task_ref,
              "requested_effects": ["INTERNAL_READ_ONLY"], "budget": deepcopy(budget),
              "context": deepcopy(context), "lifetime": {"clock_domain": clock_domain,
                  "created_ms": created_ms, "ttl_ms": ttl_ms, "quality": "MONOTONIC_SESSION"},
              "provenance": {"class": provenance_class, "producer_ref": producer_ref,
                             "evidence_refs": list(evidence_refs)}, "grants_authority": False}
    record["goal_revision"] = goal_revision(record)
    return schema.check("CognitiveGoalCandidate", record)
