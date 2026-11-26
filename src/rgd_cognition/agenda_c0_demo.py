"""Completely synthetic, non-actuating COG-C0 demonstration."""
from __future__ import annotations

import argparse
import json

from .agenda_c0 import SessionAgenda
from .context import context_slice
from .demo import synthetic_event


def run_demo(count: int = 12) -> dict:
    if type(count) is not int or not 1 <= count <= 32:
        raise ValueError("INVALID_DEMO_COUNT")
    context = context_slice("lab-robot")
    agenda = SessionAgenda(context_supplier=lambda: context, resource_state="NORMAL", max_goals=count)
    labels: dict[str, str] = {}
    first_ref = None
    for i in range(count):
        event = synthetic_event(i, text="fixture observation - no real sensor")
        event.update(kind="OBSERVATION_NOTICE", origin="SYNTHETIC", calibration_status="UNVERIFIED")
        cue = "POSSIBLE_FIRST_STEP" if i == 0 else "IMU_DISCREPANCY"
        result = agenda.propose(event, cue_kind=cue)
        if result["admission"]["outcome"] != "ADMITTED":
            raise RuntimeError("DEMO_ADMISSION_FAILED")
        gid = result["candidate"]["candidate_id"]
        if i == 0:
            first_ref = result["candidate"]["source_event_ref"]
        if agenda.start_next()["candidate"]["candidate_id"] != gid:
            raise RuntimeError("DEMO_SCHEDULING_FAILED")
        if i == 0:
            review1 = agenda.reappraise_first_step(gid, observation_tags=["FOOT_LIFT"])
            review2 = agenda.reappraise_first_step(gid, observation_tags=["NO_TRANSLATION"], previous=review1)
        outcome = agenda.run_step(gid, evidence_refs=[result["candidate"]["source_event_ref"]],
                                  result_code="ANALYSIS_COMPLETE")
        if outcome["state"] != "COMPLETED_WITH_UNCERTAINTY":
            raise RuntimeError("DEMO_OUTCOME_NOT_UNCERTAIN")
    if first_ref is None:
        raise RuntimeError("DEMO_NO_EVIDENCE")
    labels["initial"] = "POSSIBLE_FIRST_STEP"
    labels["review_1"] = review1["label"]
    labels["review_2"] = review2["label"]
    report = {
        "fixture_only": True, "goals_completed_with_uncertainty": count,
        "goal_records": len(agenda.checkpoint()["goals"]),
        "history_commit": False, "life_id": None, "chronon_status": "NOT_CONNECTED",
        "network_calls": 0, "digital_effects": 0, "motor_calls": 0,
        "oneiric_labels": labels, "oneiric_revision_chain_valid": review2["supersedes_annotation_ref"] == review1["annotation_id"],
        "audit_events": len(agenda.audit()),
    }
    agenda.close()
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="COG-C0 synthetic-only autonomous agenda replay")
    parser.add_argument("--events", type=int, default=12)
    args = parser.parse_args(argv)
    try:
        print(json.dumps(run_demo(args.events), indent=2, ensure_ascii=False))
    except ValueError:
        print(json.dumps({"fixture_only": True, "status": "INVALID_DEMO_REQUEST"}))
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
