"""Project-owned synthetic replay. No Paky-01 hardware evidence or real voices."""
from __future__ import annotations
from .host import CognitiveHost


def synthetic_event(index: int = 0, *, text: str | None = None) -> dict:
    return {
        "schema_version": "cog_input_v0.1-candidate", "event_id": "fixture-" + str(index),
        "source_id": "synthetic-source", "source_session_id": "synthetic-session",
        "local_alias": "lab-robot", "kind": "USER_TEXT", "origin": "SYNTHETIC",
        "epistemic_status": "DERIVED", "evidence_level": "DECLARED_ONLY",
        "text": text if text is not None else ("chi sei?", "stato", "cosa ricordi?", "risolvi questo problema")[index % 4],
        "source_refs": [], "source_clock_domain": None, "source_time": None,
        "ttl_ms": 60000, "privacy_scope": "EPHEMERAL_LOCAL", "calibration_status": "NOT_APPLICABLE",
        "chronon_status": "NOT_CONNECTED", "chronograf_anchor_ref": None, "may_actuate": False,
    }


def run_replay(count: int = 1000) -> dict:
    if type(count) is not int or not 1 <= count <= 10000:
        raise ValueError("COUNT_OUT_OF_RANGE")
    host = CognitiveHost(budget_ms=1000)
    responses = {}
    for index in range(count):
        event = synthetic_event(index)
        assert host.submit(event).status == "QUEUED"
        result = host.next_result()
        if result is None:
            raise RuntimeError("REPLAY_EXPIRED")
        proposal = result["proposal"]
        responses[proposal["response_code"]] = proposal["response_text"]
    return {"fixture_only": True, "events": count, "health": host.health(), "responses": responses}
