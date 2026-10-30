"""Bounded, synchronous offline host. No daemon, network, hardware or durable store."""
from __future__ import annotations
from collections import Counter, OrderedDict, deque
from copy import deepcopy
from dataclasses import dataclass
from math import isfinite
from time import monotonic_ns
from typing import Callable
from uuid import uuid4

from .context import DisconnectedMemory, context_slice
from .contracts import ContractError, local_digest, validate
from .reasoning import BaselineReasoner, Reasoner, render


@dataclass(frozen=True)
class Submission:
    status: str
    event_ref: str | None = None


@dataclass
class _Pending:
    event: dict
    fingerprint: str
    event_ref: str
    received_ns: int


class CognitiveHost:
    """Single-threaded host; rebuild instance on profile change (no hot mutation).

    TTL measures LOCAL residence, never age in a foreign clock domain.
    Provider budget is checked AFTER return: this is not a preemptive deadline.
    No external or untrusted providers may be loaded in this foundation.
    """
    def __init__(self, local_alias: str = "lab-robot", reference: dict | None = None,
                 *, capacity: int = 64, seen_capacity: int = 256,
                 max_user_burst: int = 3, budget_ms: float = 100,
                 clock: Callable[[], int] = monotonic_ns,
                 reasoner: Reasoner | None = None):
        for value in (capacity, seen_capacity, max_user_burst):
            if type(value) is not int or not 1 <= value <= 4096:
                raise ValueError("INVALID_CAPACITY")
        if type(budget_ms) not in (int, float) or not isfinite(budget_ms) or budget_ms <= 0:
            raise ValueError("INVALID_BUDGET")
        self._context = context_slice(local_alias, reference)
        self._capacity, self._seen_capacity = capacity, seen_capacity
        self._burst_max, self._burst = max_user_burst, 0
        self._budget_ms, self._clock, self._last_ns = budget_ms, clock, -1
        self._reasoner = reasoner if reasoner is not None else BaselineReasoner()
        revision = self._reasoner.revision
        if not isinstance(revision, str) or not 1 <= len(revision) <= 128:
            raise ValueError("INVALID_REASONER_REVISION")
        self._revision = revision
        self._clock_domain = "cog.monotonic.session:" + str(uuid4())
        self._pending: dict[tuple, _Pending] = {}
        self._seen: OrderedDict[tuple, str] = OrderedDict()
        self._user: deque = deque()
        self._observation: deque = deque()
        self._stats: Counter = Counter()
        self._closed = False

    def _now(self) -> int:
        value = self._clock()
        if type(value) is not int or value < self._last_ns or value < 0:
            raise ValueError("LOCAL_CLOCK_REGRESSION")
        self._last_ns = value
        return value

    @property
    def context(self) -> dict:
        return deepcopy(self._context)

    def health(self) -> dict:
        return {
            "mode": "CLOSED" if self._closed else "OFFLINE_LAB", "identity_status": "UNBOUND",
            "memory_status": "NOT_CONNECTED", "network_provider": None,
            "actuation_interface": False, "pending": len(self._pending),
            "seen_size": len(self._seen), "counters": dict(self._stats),
        }

    def close(self) -> None:
        """Drop references, not a cryptographic RAM erasure guarantee."""
        self._pending.clear()
        self._seen.clear()
        self._user.clear()
        self._observation.clear()
        self._closed = True

    def submit(self, value: dict) -> Submission:
        if self._closed:
            raise ValueError("HOST_CLOSED")
        try:
            validate("InputEvent", value)
        except ContractError:
            self._stats["invalid"] += 1
            raise
        if value["privacy_scope"] == "DENY":
            self._stats["privacy_rejected"] += 1
            return Submission("REJECTED_PRIVACY")
        if value["local_alias"] != self._context["local_alias"]:
            self._stats["instance_rejected"] += 1
            return Submission("REJECTED_INSTANCE")
        key = tuple(value[k] for k in ("local_alias", "source_id", "source_session_id", "event_id"))
        fingerprint = local_digest(value)
        old = self._pending[key].fingerprint if key in self._pending else self._seen.get(key)
        if old is not None:
            status = "DUPLICATE" if old == fingerprint else "REJECTED_ID_COLLISION"
            self._stats[status.lower()] += 1
            return Submission(status)
        if len(self._pending) >= self._capacity:
            self._stats["capacity_rejected"] += 1
            return Submission("REJECTED_CAPACITY")
        event_ref = local_digest({"scope": key, "fingerprint": fingerprint})
        self._pending[key] = _Pending(deepcopy(value), fingerprint, event_ref, self._now())
        (self._user if value["kind"] == "USER_TEXT" else self._observation).append(key)
        self._stats["queued"] += 1
        return Submission("QUEUED", event_ref)

    def _take(self) -> _Pending:
        if self._user and (not self._observation or self._burst < self._burst_max):
            key = self._user.popleft()
            self._burst += 1
        else:
            key = self._observation.popleft()
            self._burst = 0
        item = self._pending.pop(key)
        self._seen[key] = item.fingerprint
        self._seen.move_to_end(key)
        while len(self._seen) > self._seen_capacity:
            self._seen.popitem(last=False)
        return item

    def next_result(self) -> dict | None:
        if self._closed:
            raise ValueError("HOST_CLOSED")
        while self._pending:
            item = self._take()
            started = self._now()
            if started - item.received_ns >= item.event["ttl_ms"] * 1_000_000:
                self._stats["expired"] += 1
                continue
            result = self._process(item, started)
            if result is not None:
                return result
        return None

    def _process(self, item: _Pending, started: int) -> dict | None:
        event = item.event
        failure = None
        try:
            assessment = self._reasoner.assess(
                deepcopy(event), self.context, DisconnectedMemory.status(), item.event_ref)
            validate("Assessment", assessment)
            allowed = {item.event_ref, *event["source_refs"]}
            if not set(assessment["evidence_refs"]).issubset(allowed):
                raise ContractError("UNKNOWN_EVIDENCE_REF")
            code = assessment["response_code"]
            expected_kind = "REPORT" if code in {"OBSERVATION_REPORTED", "STATUS_REPORT"} else "ABSTAIN"
            if assessment["kind"] != expected_kind:
                raise ContractError("INCONSISTENT_ASSESSMENT")
            if code == "OBSERVATION_REPORTED" and event["kind"] != "OBSERVATION_NOTICE":
                raise ContractError("INCONSISTENT_OBSERVATION")
            if not assessment["evidence_refs"]:
                raise ContractError("MISSING_EVIDENCE_REF")
        except ContractError:
            failure = "PROVIDER_INVALID"
        except Exception:
            failure = "PROVIDER_UNAVAILABLE"
        ended = self._now()
        compute_ms = (ended - started) / 1_000_000
        if ended - item.received_ns >= event["ttl_ms"] * 1_000_000:
            self._stats["expired_after_compute"] += 1
            return None
        if compute_ms > self._budget_ms:
            failure = "PROVIDER_BUDGET_EXCEEDED"
        if failure:
            self._stats[failure.lower()] += 1
            assessment = {"kind": "ABSTAIN", "response_code": failure, "evidence_refs": [item.event_ref]}
        proposal = {
            "schema_version": "cog_proposal_v0.1-candidate",
            "event_ref": item.event_ref, "context_revision": self._context["context_revision"],
            "kind": assessment["kind"], "response_code": assessment["response_code"],
            "response_text": render(assessment["response_code"], event),
            "evidence_refs": assessment["evidence_refs"],
            "limitations": ["IDENTITY_UNBOUND", "CHRONON_NOT_CONNECTED", "SOURCE_DECLARED_ONLY", "NO_GENERATIVE_MODEL"],
            "may_actuate": False,
        }
        proposal["proposal_id"] = local_digest({"proposal": proposal, "reasoner_revision": self._revision})
        trace = {
            "schema_version": "cog_trace_v0.1-candidate", "proposal_id": proposal["proposal_id"],
            "event_ref": item.event_ref, "context_revision": self._context["context_revision"],
            "input_origin": event["origin"], "epistemic_status": event["epistemic_status"],
            "calibration_status": event["calibration_status"], "evidence_level": "DECLARED_ONLY",
            "source_clock_domain": event["source_clock_domain"], "source_time": event["source_time"],
            "receipt_clock_domain": self._clock_domain, "receipt_monotonic_ns": item.received_ns,
            "policy_revision": self._context["policy_revision"], "reasoner_revision": self._revision,
            "reason_codes": [assessment["response_code"]], "evidence_refs": assessment["evidence_refs"],
            "queue_wait_ms": (started - item.received_ns) / 1_000_000, "compute_ms": compute_ms,
            "memory_status": "NOT_CONNECTED", "chronon_link_status": "NOT_CONNECTED",
            "privacy_scope": "EPHEMERAL_LOCAL", "may_actuate": False,
        }
        trace["trace_id"] = local_digest(trace)
        result = {"schema_version": "cog_turn_result_v0.1-candidate", "proposal": proposal, "trace": trace}
        validate("TurnResult", result)
        self._stats["processed"] += 1
        return result
