"""CORE-B experimental ONEIRIC_REVIEW package; only synthetic local evidence.

This factory proposes a goal and typed task. It does not admit the goal,
create autobiographical memory, verify a physical step or write a Chronon.
"""
from __future__ import annotations
from copy import deepcopy

from .core_b_adapter import CoreBSchema, require, check_detail, make_goal, digest


def oneiric_goal(schema: CoreBSchema, *, source_event_ref: str, context: dict,
                 clock_domain: str, created_ms: int, ttl_ms: int, producer_ref: str,
                 budget: dict, goal_id: str | None = None) -> dict:
    """Construct an opt-in synthetic first-step reappraisal task."""
    require(type(source_event_ref) is str and source_event_ref.startswith("sha256:")
            and len(source_event_ref) == 71, "INVALID_ONEIRIC_SOURCE")
    goal_id = goal_id or digest({"oneiric_source": source_event_ref,
                                  "session": context["session_id"],
                                  "task_ref": "cog.task.v1:oneiric-first-step"})
    goal = make_goal(schema, goal_id=goal_id,
                     task_ref="cog.task.v1:oneiric-first-step",
                     context=context, clock_domain=clock_domain,
                     created_ms=created_ms, ttl_ms=ttl_ms,
                     producer_ref=producer_ref, origin="Imagination", budget=budget,
                     evidence_refs=[source_event_ref], provenance_class="SYNTHETIC")
    detail = {
        "schema_version": "cog_core_b_oneiric_task_detail_v1-candidate",
        "goal_id": goal["goal_id"], "goal_revision": goal["goal_revision"],
        "task_ref": goal["task_ref"], "context": deepcopy(context),
        "source_event_ref": source_event_ref, "source_quality": "SYNTHETIC_FIXTURE_ONLY",
        "initial_label": "POSSIBLE_FIRST_STEP",
        "success_condition": "REVIEW_ANNOTATED_NOT_MILESTONE_CONFIRMED",
        "stop_conditions": ["EVIDENCE_EXPIRED", "BUDGET_EXHAUSTED", "CONTEXT_CHANGED"],
        "verification": "UNVERIFIED", "life_id": None, "chronon_id": None,
        "grants_authority": False,
    }
    return {"goal": goal, "detail": check_detail("OneiricTaskDetail", detail)}
