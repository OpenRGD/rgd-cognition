"""CORE-D opt-in synthetic memory projection: candidate schemas, no history writer.

Only an existing, validated COG Core-B ONEIRIC_REVIEW result can be projected.
The output is an EPHEMERAL draft assembled at the caller's session clock.
It is not Chronograf time, a Chronon, a Memory retrieval response, a grant or
an authenticated historical event. There is deliberately no IO/commit API.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from typing import Any

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from .core_b_adapter import CoreBSchema, BridgeError, digest, wire, validate_result_bundle

CORE_D_COMMIT = "7b15fda5c825f9359ce0045377ec38364de19efb"
CORE_D_SCHEMA_BLOB = "9ed412fb8749cd7aeb8eeb23f2305d98ecfc0de8"
CORE_D_PROFILE = "openrgd_temporal_memory_v0.1-candidate"
LOCAL_PROFILE = "cog_core_d_ephemeral_projection_v0.1-candidate"
_ALLOWED = ("SalienceHint", "MemoryAnnotation", "OneiricReview", "CognitiveCommitment")
_LABEL_ASSESSMENT = {
    "STEP_NOT_SUPPORTED_IN_FIXTURE": "REFUTED",
    "INSUFFICIENT_EVIDENCE": "UNRESOLVED",
    # Plausibility in a synthetic replay is not physical support or verification.
    "STEP_PLAUSIBLE_IN_FIXTURE": "UNRESOLVED",
}


def require(ok: bool, code: str) -> None:
    if not ok:
        raise BridgeError(code)


class CoreDShape:
    """Pinned offline CORE-D schema validation; not a history service."""
    def __init__(self, raw: bytes):
        require(type(raw) is bytes and len(raw) <= 65536, "CORE_D_SCHEMA_LIMIT")
        blob = hashlib.sha1(b"blob " + str(len(raw)).encode("ascii") + b"\0" + raw).hexdigest()
        require(blob == CORE_D_SCHEMA_BLOB, "CORE_D_SCHEMA_PIN_MISMATCH")
        try:
            schema = json.loads(raw.decode("utf-8"))
            Draft202012Validator.check_schema(schema)
            registry = Registry().with_resource(schema["$id"], Resource.from_contents(schema))
            self._validators = {
                kind: Draft202012Validator({"$schema": schema["$schema"],
                    "$ref": schema["$id"] + "#/$defs/" + kind}, registry=registry)
                for kind in (*_ALLOWED, "HistoryCommitRequest", "HistoryCommitReceipt")
            }
        except (ValueError, KeyError, UnicodeError):
            raise BridgeError("INVALID_CORE_D_SCHEMA") from None

    def check(self, kind: str, record: dict) -> dict:
        require(kind in self._validators, "CORE_D_TYPE_NOT_NEGOTIATED")
        wire(record)
        require(type(record) is dict and record.get("record_type") == kind,
                "CORE_D_RECORD_KIND_MISMATCH")
        require(next(self._validators[kind].iter_errors(record), None) is None,
                "CORE_D_SHAPE_VIOLATION")
        return deepcopy(record)


def _record(shape: CoreDShape, kind: str, fields: dict) -> dict:
    data = {"schema_version": CORE_D_PROFILE, "record_type": kind,
            "producer_ref": "cog.local:work", "grants_authority": False, **fields}
    require("record_id" not in data, "DRAFT_RECORD_ID_UNTRUSTED")
    # Digest is local draft identity only; no canonical Chronon ID or issuer.
    data["record_id"] = digest(data)
    return shape.check(kind, data)


def _oneiric_parts(core_b: CoreBSchema, result: dict) -> tuple[dict, dict, dict]:
    result = validate_result_bundle(core_b, result)
    transition, outcome, trace = result["transition"], result["outcome"], result["cognitive_trace"]
    context = outcome["context"]
    require(context["scope"] == "SESSION_SCOPED" and context["life_binding_ref"] is None
            and context["life_activation_epoch"] is None, "CORE_D_LIFE_BOUND_UNSUPPORTED")
    require(outcome["task_ref"] == "cog.task.v1:oneiric-first-step" and
            outcome["code"] == "ANALYSIS_COMPLETE" and transition["to_state"] == "COMPLETED",
            "CORE_D_NON_ONEIRIC_OUTCOME")
    require(trace["memory_status"] == "NOT_CONNECTED" and
            trace["chronon_link_status"] == "NOT_CONNECTED" and trace["life_id"] is None and
            not trace["may_actuate"] and trace["privacy_scope"] == "EPHEMERAL_LOCAL",
            "CORE_D_MEMORY_AUTHORITY_UNAVAILABLE")
    require(trace["provenance_class"] == "SYNTHETIC" and
            outcome["verification"] == "UNVERIFIED", "CORE_D_SYNTHETIC_ONLY")
    annotations = outcome["annotation_history"]
    require(bool(annotations) and outcome["interpretation"] == annotations[-1],
            "CORE_D_ANNOTATION_REQUIRED")
    require(all(x["scope"] == "SYNTHETIC_FIXTURE_ONLY" and x["life_id"] is None
            and x["chronon_id"] is None and x["physical_verification"] == "NOT_VERIFIED"
            and not x["may_actuate"] for x in annotations), "CORE_D_PHYSICAL_CLAIM")
    src = annotations[-1]["source_event_ref"]
    require(src in outcome["evidence_refs"] and all(x["source_event_ref"] == src for x in annotations),
            "CORE_D_SOURCE_NOT_BOUND")
    return transition, outcome, trace


def project_oneiric(core_d: CoreDShape, core_b: CoreBSchema, result: dict, *,
                    knowledge_at_ms: int, clock_domain: str) -> dict:
    """Convert actual COG Work result into 4 kinds of *uncommitted* Core-D drafts.

    knowledge_at_ms is a trusted local projection-time reading, NOT the original
    revision time, Chronograf TimeAtom, or globally aligned historical time.
    The original per-revision timestamps are unavailable in C0; never invent them.
    """
    require(isinstance(core_d, CoreDShape) and isinstance(core_b, CoreBSchema),
            "CORE_D_VALIDATOR_REQUIRED")
    tr, out, trace = _oneiric_parts(core_b, result)
    life = tr["lifetime"]
    require(type(knowledge_at_ms) is int and 0 <= knowledge_at_ms <= 9007199254740991,
            "CORE_D_INVALID_PROJECTION_TIME")
    require(type(clock_domain) is str and clock_domain == life["clock_domain"] and
            life["quality"] == "MONOTONIC_SESSION", "CORE_D_UNALIGNED_CLOCK")
    require(knowledge_at_ms >= life["created_ms"], "CORE_D_PROJECTION_TIME_BEFORE_RESULT")
    # This bound uses local session monotonic time; no claim of Chronograf qualification.
    event_ref = out["interpretation"]["source_event_ref"]
    evidence = deepcopy(out["evidence_refs"])
    known = {"knowledge_clock_domain_ref": clock_domain, "knowledge_at_ms": knowledge_at_ms}
    salience = _record(core_d, "SalienceHint", {
        "evidence_refs": evidence, "source_event_ref": event_ref,
        "previous_hint_ref": None, "salience_band": "MEDIUM",
        "confidence_state": "PROVISIONAL", "reason_code": "POSSIBLE_FIRST_STEP_REVIEW_CANDIDATE",
        "physical_verification": "NOT_VERIFIED", **known,
    })
    annotations = []
    previous = None
    for original in out["annotation_history"]:
        assessment = _LABEL_ASSESSMENT.get(original["label"])
        require(assessment is not None, "CORE_D_UNKNOWN_ONEIRIC_LABEL")
        draft = _record(core_d, "MemoryAnnotation", {
            "evidence_refs": evidence, "subject_ref": event_ref,
            "about_valid_time_assertion_ref": None, "assessment": assessment,
            "supersedes_annotation_ref": previous,
            "interpretation_payload_sha256": digest(original),
            "provenance_class": "SYNTHETIC_REVIEW",
            "physical_milestone_verified": False, "projection_only": True, **known,
        })
        annotations.append(draft)
        previous = draft["record_id"]
    last = annotations[-1]
    oneiric = _record(core_d, "OneiricReview", {
        "evidence_refs": evidence, "work_goal_ref": out["goal_id"],
        "source_event_ref": event_ref,
        "prior_annotation_ref": annotations[-2]["record_id"] if len(annotations) > 1 else None,
        "simulated_scene_refs": [], "assessment": last["assessment"],
        "review_outcome": "REVIEW_COMPLETED", "provenance_class": "SYNTHETIC_REPLAY",
        "physical_milestone_verified": False, "history_committed": False, **known,
    })
    commitment = _record(core_d, "CognitiveCommitment", {
        "evidence_refs": evidence, "goal_ref": out["goal_id"],
        "admission_ref": out["admission_ref"],
        "commitment_kind": "CORRECTION" if last["assessment"] == "REFUTED" else "DECISION",
        "subject_ref": event_ref, "delta_payload_sha256": digest({
            "oneiric_result": oneiric["record_id"], "interpretation": out["interpretation"]}),
        "assessment": last["assessment"], "provenance_class": "SYNTHETIC_REVIEW",
        "physical_milestone_verified": False, **known,
    })
    proposal = {
        "schema_version": LOCAL_PROFILE, "scope": "SESSION_SCOPED",
        "source_trace_ref": trace["trace_id"],
        "source_goal_ref": out["goal_id"], "source_goal_revision": out["goal_revision"],
        "source_event_ref": event_ref,
        "evidence_quality": "SYNTHETIC_FIXTURE_ONLY", "verification": "UNVERIFIED",
        "projection_time_domain": clock_domain, "projection_at_ms": knowledge_at_ms,
        "salience_hint": salience, "memory_annotations": annotations,
        "oneiric_review": oneiric, "cognitive_commitment": commitment,
        "history_status": "NOT_CONNECTED", "life_id": None,
        "chronon_id": None, "grants_authority": False,
    }
    proposal["projection_ref"] = digest(proposal)
    return validate_projection(core_d, core_b, result, proposal)


def validate_projection(core_d: CoreDShape, core_b: CoreBSchema, result: dict,
                        proposal: dict) -> dict:
    """Recheck COG causal links and Core-D draft semantics at each consumer boundary."""
    _, out, trace = _oneiric_parts(core_b, result)
    require(type(proposal) is dict and set(proposal) == {
        "schema_version", "scope", "source_trace_ref", "source_goal_ref",
        "source_goal_revision", "source_event_ref", "evidence_quality", "verification",
        "projection_time_domain", "projection_at_ms", "salience_hint",
        "memory_annotations", "oneiric_review", "cognitive_commitment",
        "history_status", "life_id", "chronon_id", "grants_authority", "projection_ref",
    }, "CORE_D_PROJECTION_SHAPE")
    wire(proposal)
    require(proposal["schema_version"] == LOCAL_PROFILE and proposal["scope"] == "SESSION_SCOPED"
            and proposal["evidence_quality"] == "SYNTHETIC_FIXTURE_ONLY" and
            proposal["verification"] == "UNVERIFIED" and
            proposal["history_status"] == "NOT_CONNECTED" and
            proposal["life_id"] is None and proposal["chronon_id"] is None and
            proposal["grants_authority"] is False, "CORE_D_PROJECTION_AUTHORITY_MISMATCH")
    require((proposal["source_trace_ref"], proposal["source_goal_ref"],proposal["source_goal_revision"],
             proposal["source_event_ref"]) ==
            (trace["trace_id"], out["goal_id"], out["goal_revision"],
             out["interpretation"]["source_event_ref"]), "CORE_D_PROJECTION_SOURCE_MISMATCH")
    life = result["transition"]["lifetime"]
    require(proposal["projection_time_domain"] == life["clock_domain"] and
            type(proposal["projection_at_ms"]) is int and
            proposal["projection_at_ms"] >= life["created_ms"], "CORE_D_PROJECTION_TIME_MISMATCH")
    hints = core_d.check("SalienceHint", proposal["salience_hint"])
    annotations = proposal["memory_annotations"]
    require(type(annotations) is list and len(annotations) == len(out["annotation_history"])
            and 0 < len(annotations) <= 8, "CORE_D_ANNOTATION_COUNT_MISMATCH")
    prev = None
    for original, draft in zip(out["annotation_history"], annotations):
        draft = core_d.check("MemoryAnnotation", draft)
        require(draft["record_id"] == digest({k:v for k,v in draft.items() if k != "record_id"})
                and draft["supersedes_annotation_ref"] == prev
                and draft["subject_ref"] == proposal["source_event_ref"]
                and draft["interpretation_payload_sha256"] == digest(original)
                and draft["assessment"] == _LABEL_ASSESSMENT[original["label"]]
                and draft["about_valid_time_assertion_ref"] is None
                and draft["provenance_class"] == "SYNTHETIC_REVIEW"
                and draft["projection_only"] is True
                and draft["physical_milestone_verified"] is False,
                "CORE_D_ANNOTATION_LINEAGE_MISMATCH")
        prev = draft["record_id"]
    oneiric = core_d.check("OneiricReview", proposal["oneiric_review"])
    commitment = core_d.check("CognitiveCommitment", proposal["cognitive_commitment"])
    for item in (hints, *annotations, oneiric, commitment):
        require(item["record_id"] == digest({k:v for k,v in item.items() if k != "record_id"})
                and item["producer_ref"] == "cog.local:work"
                and item["grants_authority"] is False
                and item["evidence_refs"] == out["evidence_refs"]
                and item["knowledge_clock_domain_ref"] == proposal["projection_time_domain"]
                and item["knowledge_at_ms"] == proposal["projection_at_ms"],
                "CORE_D_RECORD_PROVENANCE_MISMATCH")
    require(hints["source_event_ref"] == proposal["source_event_ref"] and
            hints["confidence_state"] == "PROVISIONAL" and
            hints["physical_verification"] == "NOT_VERIFIED", "CORE_D_SALIENCE_MISMATCH")
    require(oneiric["source_event_ref"] == proposal["source_event_ref"] and
            oneiric["work_goal_ref"] == out["goal_id"] and
            oneiric["prior_annotation_ref"] == (annotations[-2]["record_id"] if len(annotations)>1 else None)
            and oneiric["assessment"] == annotations[-1]["assessment"] and
            oneiric["review_outcome"] == "REVIEW_COMPLETED" and
            oneiric["provenance_class"] == "SYNTHETIC_REPLAY" and
            oneiric["history_committed"] is False and
            oneiric["physical_milestone_verified"] is False, "CORE_D_ONEIRIC_MISMATCH")
    require(commitment["goal_ref"] == out["goal_id"] and
            commitment["admission_ref"] == out["admission_ref"] and
            commitment["subject_ref"] == proposal["source_event_ref"] and
            commitment["assessment"] == oneiric["assessment"] and
            commitment["delta_payload_sha256"] == digest({
                "oneiric_result": oneiric["record_id"], "interpretation": out["interpretation"]})
            and commitment["commitment_kind"] == (
                "CORRECTION" if oneiric["assessment"] == "REFUTED" else "DECISION")
            and commitment["physical_milestone_verified"] is False,
            "CORE_D_COMMITMENT_MISMATCH")
    require(proposal["projection_ref"] == digest({k:v for k,v in proposal.items()
                                                if k != "projection_ref"}),
            "CORE_D_PROJECTION_DIGEST_MISMATCH")
    return deepcopy(proposal)


def history_commit_preview(core_d: CoreDShape, core_b: CoreBSchema,
                          result: dict, proposal: dict) -> dict:
    """Never create HistoryCommitRequest: required Life, gate and writer absent.

    Output only references a local draft and defines the future request boundary;
    this API has no writer/client, serial/USB/CAN/voice/network or effect dispatcher.
    """
    draft = validate_projection(core_d, core_b, result, proposal)
    return {
        "schema_version": "cog_core_d_history_preview_v0.1-candidate",
        "status": "BLOCKED_NOT_CONNECTED", "payload_kind": "ONEIRIC_REVIEW",
        "uncommitted_record_ref": draft["oneiric_review"]["record_id"],
        "uncommitted_payload_sha256": digest(draft["oneiric_review"]),
        "block_reasons": ["LIFE_BINDING_UNVERIFIED", "WRITER_ROLE_NOT_CONNECTED",
                           "HISTORY_EFFECT_GATE_NOT_CONNECTED", "CHRONOGRAF_NOT_CONNECTED"],
        "history_commit_request": None, "effect_request": None,
        "history_commit_receipt": None, "life_id": None,
        "chronon_id": None, "history_committed": False,
        "grants_authority": False,
    }
