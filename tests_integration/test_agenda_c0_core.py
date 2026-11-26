"""C0 uses the actual COG-02 source verifier against pinned OpenRGD Core.

Run only in the separate Core conformance workflow. No robot/device involved.
"""
import os
from pathlib import Path
import unittest
from unittest.mock import patch
import socket
import subprocess

from rgd_cognition.agenda_c0 import SessionAgenda, AgendaError
from rgd_cognition.demo import synthetic_event
from rgd_cognition.rgd_context import RGDContextResolver
from rgd_cognition.rgd_host import RGDGroundedHost

CORE = Path(os.environ["RGD_CORE_CHECKOUT"])
REFERENCE_ROOT = "sha256:c049dc3fb91c19e668ef0d35b9b40d9052caf1a458b1a108d58b1896189dd5f9"


def notice(index=1):
    event = synthetic_event(index)
    event.update(kind="OBSERVATION_NOTICE", origin="SYNTHETIC", calibration_status="UNVERIFIED")
    return event


class AgendaCoreIntegration(unittest.TestCase):
    def setUp(self):
        self.resolver = RGDContextResolver(CORE, local_alias="lab-robot", expected_source_root=REFERENCE_ROOT)
        self.assertEqual(self.resolver.refresh()["reference_status"], "SOURCE_INTEGRITY_VERIFIED")
        self.host = RGDGroundedHost(self.resolver)
        self.agenda = SessionAgenda(context_supplier=lambda: self.host.context, resource_state="NORMAL")

    def test_lab_goal_consumes_real_integrity_checked_context_only(self):
        with patch.object(socket,"socket",side_effect=AssertionError("network forbidden")), patch.object(subprocess,"Popen",side_effect=AssertionError("process forbidden")):
            result = self.agenda.propose(notice(), cue_kind="IMU_DISCREPANCY")
            self.assertEqual(result["admission"]["outcome"], "ADMITTED")
            self.assertEqual(result["candidate"]["context_revision"], self.host.context["context_revision"])
            self.assertIsNone(result["candidate"]["life_id"])
            self.assertEqual(result["candidate"]["chronon_status"], "NOT_CONNECTED")
            self.assertFalse(result["candidate"]["may_actuate"])

    def test_context_invalidation_cancels_goal_not_revives_it(self):
        goal = self.agenda.propose(notice(), cue_kind="EVIDENCE_CONFLICT")["candidate"]
        self.agenda.start_next()
        gid = goal["candidate_id"]
        generation = self.agenda.view(gid)["generation"]
        self.resolver.invalidate()
        self.assertFalse(self.agenda.accept_delegated_result(gid, generation=generation,
                            context_revision=goal["context_revision"]))
        self.assertEqual(self.agenda.view(gid)["state"], "CANCELLED")

    def test_reference_skill_is_never_admitted_as_effect(self):
        candidate = self.agenda.propose(notice(), cue_kind="IMU_DISCREPANCY", effect_scope="PHYSICAL_ACTION_REQUEST")
        self.assertEqual(candidate["admission"]["reason_code"], "EFFECT_NOT_GRANTED")
        self.assertIsNone(self.agenda.start_next())

    def test_context_without_upstream_identity_does_not_fabricate_life(self):
        self.assertIsNone(self.host.context["robot_id"])
        self.assertIsNone(self.host.context["life_id"])
        self.assertEqual(self.agenda.checkpoint()["status"], "PROVISIONAL_NONCANONICAL")
        self.assertIsNone(self.agenda.checkpoint()["life_id"])


if __name__ == "__main__": unittest.main()
