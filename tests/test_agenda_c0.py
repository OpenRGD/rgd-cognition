"""Candidate COG-C0 tests; all inputs and evidence are laboratory fixtures."""
from copy import deepcopy
import json
import socket
import subprocess
import unittest
from unittest.mock import patch

from jsonschema import Draft202012Validator

from rgd_cognition.agenda_c0 import (
    AgendaError, SessionAgenda, _SCHEMA, _check, oneiric_review,
)
from rgd_cognition.context import context_slice
from rgd_cognition.contracts import ContractError
from rgd_cognition.demo import synthetic_event


class Clock:
    def __init__(self): self.ns = 1000000000
    def __call__(self): return self.ns
    def advance(self, ms): self.ns += int(ms * 1000000)


def observation(i=1):
    value = synthetic_event(i, text="PRIVATE_EVENT_TEXT")
    value.update(kind="OBSERVATION_NOTICE", calibration_status="UNVERIFIED",
                 epistemic_status="DERIVED", origin="SYNTHETIC")
    return value


class AgendaTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.view = context_slice("lab-robot")
        self.agenda = SessionAgenda(context_supplier=lambda: self.view, clock=self.clock, resource_state="NORMAL")

    def goal(self, i=1, cue="IMU_DISCREPANCY", **kwargs):
        return self.agenda.propose(observation(i), cue_kind=cue, **kwargs)

    def test_schema_is_valid_and_separate(self):
        Draft202012Validator.check_schema(_SCHEMA)
        self.assertIn("GoalCandidate", _SCHEMA["$defs"])
        self.assertIn("OneiricAnnotation", _SCHEMA["$defs"])
        self.assertNotIn("ActionIntent", _SCHEMA["$defs"])

    def test_autonomous_cue_admits_goal_only_inside_local_policy(self):
        result = self.goal()
        self.assertEqual(result["admission"]["outcome"], "ADMITTED")
        self.assertEqual(result["candidate"]["goal_kind"], "INVESTIGATE_IMU_UNCERTAINTY")
        self.assertEqual(result["candidate"]["requested_effect_scope"], "INTERNAL_READ_ONLY")
        self.assertEqual(self.agenda.start_next()["state"], "RUNNING")
        self.assertIsNone(result["candidate"]["life_id"])
        self.assertFalse(result["candidate"]["may_actuate"])

    def test_untrusted_requested_effects_and_network_rejected(self):
        for i, scope in enumerate(("HISTORY_COMMIT_REQUEST", "COMMUNICATION_REQUEST", "DIGITAL_EFFECT_REQUEST", "PHYSICAL_ACTION_REQUEST"), 10):
            result = self.goal(i, effect_scope=scope)
            self.assertEqual(result["admission"]["outcome"], "REJECTED")
            self.assertIsNone(result["admission"]["granted_effect_scope"])
        result = self.goal(20, external_network=True)
        self.assertEqual(result["admission"]["reason_code"], "EFFECT_NOT_GRANTED")
        self.assertIsNone(self.agenda.start_next())

    def test_resource_unknown_and_low_do_not_auto_admit(self):
        for state in ("UNKNOWN", "LOW"):
            agenda = SessionAgenda(context_supplier=lambda: self.view, clock=self.clock, resource_state=state)
            result = agenda.propose(observation(22), cue_kind="IMU_DISCREPANCY")
            self.assertEqual(result["admission"]["outcome"], "DEFERRED")
            self.assertIsNone(agenda.start_next())
            agenda.set_resources("NORMAL")
            self.assertIsNone(agenda.start_next())  # no stealth grants on resource recovery

    def test_life_low_pauses_and_requires_explicit_resume(self):
        gid = self.goal()["candidate"]["candidate_id"]
        self.agenda.start_next()
        old = self.agenda.view(gid)["generation"]
        self.agenda.set_resources("LOW")
        self.assertEqual(self.agenda.view(gid)["state"], "PAUSED_LIFE")
        self.assertFalse(self.agenda.accept_delegated_result(gid, generation=old, context_revision=self.view["context_revision"]))
        with self.assertRaises(AgendaError): self.agenda.resume(gid)
        self.agenda.set_resources("NORMAL")
        self.assertEqual(self.agenda.resume(gid)["state"], "RUNNING")
        self.assertNotEqual(old, self.agenda.view(gid)["generation"])

    def test_user_interrupt_pauses_without_voice_output(self):
        gid = self.goal()["candidate"]["candidate_id"]
        self.agenda.start_next()
        event = synthetic_event(90, text="DO_NOT_PERSIST_MY_WORDS")
        self.agenda.interrupt_user(event)
        self.assertEqual(self.agenda.view(gid)["state"], "PAUSED_USER")
        self.assertNotIn("DO_NOT_PERSIST", json.dumps(self.agenda.audit()))
        self.assertEqual(self.agenda.resume(gid)["state"], "RUNNING")

    def test_one_running_goal_per_session(self):
        self.goal(1); self.goal(2)
        self.assertIsNotNone(self.agenda.start_next())
        self.assertIsNone(self.agenda.start_next())

    def test_success_never_verified_with_declared_evidence(self):
        gid = self.goal()["candidate"]["candidate_id"]
        running = self.agenda.start_next()
        outcome = self.agenda.run_step(gid, evidence_refs=[running["candidate"]["source_event_ref"]],
                                       result_code="ANALYSIS_COMPLETE")
        self.assertEqual(outcome["state"], "COMPLETED_WITH_UNCERTAINTY")
        self.assertEqual(outcome["verification"], "UNVERIFIED")
        with self.assertRaises(AgendaError):
            self.agenda.run_step(gid, evidence_refs=[], result_code="ANALYSIS_COMPLETE")

    def test_unknown_evidence_rejected_without_mutating_goal(self):
        gid = self.goal()["candidate"]["candidate_id"]
        self.agenda.start_next()
        before = self.agenda.view(gid)
        with self.assertRaises(AgendaError):
            self.agenda.run_step(gid, evidence_refs=["fabricated-chronon"], result_code="ANALYSIS_COMPLETE")
        self.assertEqual(before, self.agenda.view(gid))

    def test_missing_evidence_not_marked_success(self):
        gid = self.goal()["candidate"]["candidate_id"]
        self.agenda.start_next()
        result = self.agenda.run_step(gid, evidence_refs=[], result_code="ANALYSIS_COMPLETE")
        self.assertEqual(result["state"], "WAITING_EVIDENCE")
        self.assertEqual(self.agenda.resume(gid)["state"], "RUNNING")
        self.assertEqual(self.agenda.run_step(gid, evidence_refs=[], result_code="ABSTAIN")["state"], "ABSTAINED")

    def test_unsupported_input_rejected_and_private_payload_not_logged(self):
        event = synthetic_event(10, text="private audio information")
        with self.assertRaises(AgendaError): self.agenda.propose(event, cue_kind="IMU_DISCREPANCY")
        event = observation(11)
        event["privacy_scope"] = "DENY"
        with self.assertRaises(AgendaError): self.agenda.propose(event, cue_kind="IMU_DISCREPANCY")
        self.assertNotIn("private audio", json.dumps(self.agenda.audit()))

    def test_idempotency_collision_and_no_duplicate_work(self):
        a = self.goal(3)
        b = self.goal(3)
        self.assertEqual(a, b)
        self.assertEqual(len(self.agenda.checkpoint()["goals"]), 1)
        event = observation(3); event["text"] = "DIFFERENT"
        with self.assertRaises(AgendaError): self.agenda.propose(event, cue_kind="IMU_DISCREPANCY")

    def test_depth_and_children_re_admitted_without_grants(self):
        root = self.goal(1)["candidate"]["candidate_id"]
        self.agenda.start_next()
        child1 = self.goal(2, cue="EVIDENCE_CONFLICT", parent_goal_id=root)
        child2 = self.goal(3, cue="POSSIBLE_FIRST_STEP", parent_goal_id=root)
        child3 = self.goal(4, cue="EVIDENCE_CONFLICT", parent_goal_id=root)
        self.assertEqual(child1["admission"]["outcome"], "ADMITTED")
        self.assertEqual(child2["candidate"]["depth"], 1)
        self.assertEqual(child3["admission"]["reason_code"], "CHILD_LIMIT")
        self.assertIsNone(child1["candidate"]["life_id"])
        self.assertEqual(child1["admission"]["granted_effect_scope"], "INTERNAL_READ_ONLY")

    def test_max_depth_stops_subgoal_cycle(self):
        a = SessionAgenda(context_supplier=lambda: self.view, clock=self.clock, resource_state="NORMAL", max_depth=1)
        root = a.propose(observation(1), cue_kind="IMU_DISCREPANCY")["candidate"]["candidate_id"]
        a.start_next()
        child = a.propose(observation(2), cue_kind="EVIDENCE_CONFLICT", parent_goal_id=root)
        self.assertEqual(child["admission"]["outcome"], "ADMITTED")
        a.run_step(root, evidence_refs=[], result_code="ABSTAIN")
        a.start_next()
        grandchild = a.propose(observation(3), cue_kind="EVIDENCE_CONFLICT", parent_goal_id=child["candidate"]["candidate_id"])
        self.assertEqual(grandchild["admission"]["reason_code"], "CHILD_LIMIT")

    def test_global_goal_quota_is_hard_and_audit_bounded(self):
        a = SessionAgenda(context_supplier=lambda: self.view, clock=self.clock, resource_state="NORMAL", max_goals=2)
        for i in range(3):
            result = a.propose(observation(i), cue_kind="IMU_DISCREPANCY")
        self.assertEqual(result["admission"]["reason_code"], "AGENDA_QUOTA")
        self.assertEqual(len(a.checkpoint()["goals"]), 2)
        self.assertLessEqual(len(a.audit()), 3)

    def test_ttl_expires_without_false_completion(self):
        result = self.goal(ttl_ms=5)
        gid = result["candidate"]["candidate_id"]
        self.clock.advance(5)
        self.assertIsNone(self.agenda.start_next())
        self.assertEqual(self.agenda.view(gid)["state"], "EXPIRED")

    def test_context_revision_change_invalidates_and_stale_result_fails(self):
        gid = self.goal()["candidate"]["candidate_id"]
        self.agenda.start_next()
        gen = self.agenda.view(gid)["generation"]
        self.view = context_slice("lab-robot", reference={"schema_version":"cog_reference_input_v0.1-candidate", "local_alias":"lab-robot", "source_ref":"fixture-rgd", "source_root":None, "composition_digest":None})
        self.assertFalse(self.agenda.accept_delegated_result(gid, generation=gen, context_revision=self.view["context_revision"]))
        self.assertEqual(self.agenda.view(gid)["state"], "CANCELLED")

    def test_late_delegated_response_and_revoked_generation(self):
        result = self.goal()
        gid = result["candidate"]["candidate_id"]
        self.agenda.start_next()
        gen = self.agenda.view(gid)["generation"]
        self.assertTrue(self.agenda.accept_delegated_result(gid, generation=gen, context_revision=self.view["context_revision"]))
        self.agenda.interrupt_user(synthetic_event(99))
        self.assertFalse(self.agenda.accept_delegated_result(gid, generation=gen, context_revision=self.view["context_revision"]))
        self.agenda.resume(gid)
        self.assertFalse(self.agenda.accept_delegated_result(gid, generation=gen, context_revision=self.view["context_revision"]))

    def test_session_checkpoint_never_claims_reboot_continuity(self):
        self.goal()
        a = self.agenda.checkpoint()
        b = SessionAgenda(context_supplier=lambda: self.view, clock=self.clock, resource_state="NORMAL").checkpoint()
        self.assertNotEqual(a["session_id"], b["session_id"])
        self.assertEqual(a["status"], "PROVISIONAL_NONCANONICAL")
        self.assertEqual(a["chronon_status"], "NOT_CONNECTED")
        self.assertIsNone(a["life_id"])
        self.assertEqual(b["goals"], {})

    def test_context_identity_spoof_fails_closed(self):
        bad = deepcopy(self.view); bad["life_id"] = "invented"
        a = SessionAgenda(context_supplier=lambda: bad, clock=self.clock, resource_state="NORMAL")
        with self.assertRaises((AgendaError, ValueError)):
            a.propose(observation(1), cue_kind="IMU_DISCREPANCY")

    def test_audit_capacity_prevents_unlogged_transitions(self):
        a = SessionAgenda(context_supplier=lambda: self.view, clock=self.clock, resource_state="NORMAL", max_audit=1)
        result = a.propose(observation(1), cue_kind="IMU_DISCREPANCY")
        with self.assertRaises(AgendaError): a.start_next()
        self.assertEqual(a.view(result["candidate"]["candidate_id"])["state"], "QUEUED")

    def test_clock_regression_never_creates_new_session_identity(self):
        gid = self.goal()["candidate"]["candidate_id"]
        self.clock.ns = 0
        with self.assertRaises(AgendaError): self.agenda.start_next()
        self.assertEqual(self.agenda.view(gid)["state"], "CANCELLED")
        self.clock.ns = 1000000001
        self.assertIsNone(self.agenda.checkpoint()["life_id"])

    def test_no_network_or_subprocess_in_lab_path(self):
        with patch.object(socket, "socket", side_effect=AssertionError("network")), patch.object(subprocess, "Popen", side_effect=AssertionError("process")):
            result = self.goal()
            self.agenda.start_next()
            self.agenda.run_step(result["candidate"]["candidate_id"], evidence_refs=[result["candidate"]["source_event_ref"]], result_code="ANALYSIS_COMPLETE")
            self.assertIsNotNone(self.agenda.checkpoint())

    def test_oneiric_two_revisions_never_rewrite_original(self):
        ref = "sha256:" + "a" * 64
        before = {"original": {"event_ref": ref, "label": "POSSIBLE_FIRST_STEP"}}
        preserved = deepcopy(before)
        rev1 = oneiric_review(source_event_ref=ref, observation_tags=["FOOT_LIFT", "CONTACT_CHANGE"])
        rev2 = oneiric_review(source_event_ref=ref, observation_tags=["NO_TRANSLATION"], previous=rev1)
        self.assertEqual(rev1["label"], "INSUFFICIENT_EVIDENCE")
        self.assertEqual(rev2["label"], "STEP_NOT_SUPPORTED_IN_FIXTURE")
        self.assertEqual(rev2["supersedes_annotation_ref"], rev1["annotation_id"])
        self.assertEqual(before, preserved)
        self.assertIsNone(rev2["chronon_id"])

    def test_oneiric_requires_running_admitted_work_goal(self):
        regular = self.goal(1)["candidate"]["candidate_id"]
        self.agenda.start_next()
        with self.assertRaises(AgendaError):
            self.agenda.reappraise_first_step(regular, observation_tags=["FOOT_LIFT"])
        self.agenda.run_step(regular, evidence_refs=[], result_code="ABSTAIN")
        review = self.goal(2, cue="POSSIBLE_FIRST_STEP")["candidate"]["candidate_id"]
        with self.assertRaises(AgendaError):
            self.agenda.reappraise_first_step(review, observation_tags=[])
        self.agenda.start_next()
        candidate = self.agenda.reappraise_first_step(review, observation_tags=["FOOT_LIFT"])
        self.assertEqual(candidate["scope"], "SYNTHETIC_FIXTURE_ONLY")

    def test_oneiric_positive_is_never_physical_certification(self):
        ref = "sha256:" + "b" * 64
        review = oneiric_review(source_event_ref=ref, observation_tags=["FOOT_LIFT", "CONTACT_CHANGE", "FORWARD_DISPLACEMENT"])
        self.assertEqual(review["label"], "STEP_PLAUSIBLE_IN_FIXTURE")
        self.assertEqual(review["physical_verification"], "NOT_VERIFIED")
        self.assertFalse(review["may_actuate"])

    def test_oneiric_cannot_accept_another_event_previous_annotation(self):
        rev = oneiric_review(source_event_ref="sha256:"+"1"*64, observation_tags=[])
        with self.assertRaises(AgendaError):
            oneiric_review(source_event_ref="sha256:"+"2"*64, observation_tags=[], previous=rev)

    def test_unsupported_tampering_and_no_action_intent_in_candidate(self):
        result = self.goal()
        bad = deepcopy(result["candidate"]); bad["action_intent"] = {"motor": "on"}
        with self.assertRaises(ContractError): _check("GoalCandidate", bad)

    def test_1000_synthetic_clock_ticks_and_bounded_memory(self):
        a = SessionAgenda(context_supplier=lambda: self.view, clock=self.clock, resource_state="NORMAL", max_goals=16, max_audit=64)
        for i in range(16):
            res = a.propose(observation(i), cue_kind="IMU_DISCREPANCY", ttl_ms=1000)
            self.assertEqual(res["admission"]["outcome"], "ADMITTED")
            self.clock.advance(1)
        for _ in range(1000):
            self.clock.advance(10)
            a.start_next()
        self.assertEqual(len(a.checkpoint()["goals"]), 16)
        self.assertTrue(all(g["state"] == "EXPIRED" for g in a.checkpoint()["goals"].values()))
        self.assertLessEqual(len(a.audit()), 64)


if __name__ == "__main__": unittest.main()
