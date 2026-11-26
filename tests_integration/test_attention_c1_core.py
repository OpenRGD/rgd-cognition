"""Real C0/C02/Core composition; Console samples here are synthetic, not live."""
import os
from pathlib import Path
import socket
import subprocess
import unittest
from unittest.mock import patch

from rgd_cognition.attention_c1 import AttentionPolicy
from rgd_cognition.attention_c1_bridge import AttentionAgenda
from rgd_cognition.attention_c1_demo import FixtureClock, fixture_binding, fixture_sample, run_demo
from rgd_cognition.context import context_slice
from rgd_cognition.demo import synthetic_event
from rgd_cognition.rgd_context import RGDContextResolver

CORE = Path(os.environ["RGD_CORE_CHECKOUT"])
PIN = "sha256:c049dc3fb91c19e668ef0d35b9b40d9052caf1a458b1a108d58b1896189dd5f9"


class AttentionCoreIntegration(unittest.TestCase):
    def setUp(self):
        self.clock = FixtureClock()
        self.resolver = RGDContextResolver(CORE, local_alias="lab-robot", expected_source_root=PIN,
                                            clock=self.clock, ttl_ms=60000)
        self.assertEqual(self.resolver.refresh()["reference_status"], "SOURCE_INTEGRITY_VERIFIED")
        self.host = AttentionAgenda(context_supplier=self.resolver.read, binding=fixture_binding(),
                                   policy=AttentionPolicy(cooldown_ms=100), clock=self.clock, resource_state="NORMAL")

    def feed(self, index, rate=0.0, host=None, freshness="FRESH", consent=True):
        self.clock.advance(100)
        return (host or self.host).ingest(fixture_sample(index, rate), received_ns=self.clock(),
                                         freshness=freshness, consent=consent)

    def goal(self):
        self.feed(0); self.feed(1)
        result = self.feed(2)
        self.assertEqual(result["proposal"]["admission"]["outcome"], "ADMITTED")
        return result

    def test_real_core_context_and_real_work_admission(self):
        result = self.goal()
        candidate = result["proposal"]["candidate"]
        self.assertEqual(candidate["context_revision"], self.resolver.read()["context_revision"])
        self.assertIsNone(candidate["life_id"])
        self.assertEqual(candidate["goal_kind"], "INVESTIGATE_IMU_UNCERTAINTY")
        self.assertEqual(candidate["requested_effect_scope"], "INTERNAL_READ_ONLY")
        self.assertFalse(candidate["external_network_requested"])
        self.assertTrue(set(result["attention"]["cue"]["source_refs"]).issubset(candidate["evidence_refs"]))
        goal = self.host.work.start_next()
        outcome = self.host.work.run_step(goal["candidate"]["candidate_id"],
            evidence_refs=candidate["evidence_refs"][:1], result_code="ANALYSIS_COMPLETE")
        self.assertEqual(outcome["state"], "COMPLETED_WITH_UNCERTAINTY")

    def test_default_unknown_resources_pause_generation(self):
        host = AttentionAgenda(context_supplier=self.resolver.read, binding=fixture_binding(), clock=self.clock)
        for i in range(3):
            self.assertIsNone(self.feed(i, host=host)["proposal"])
        self.assertEqual(len(host.work.checkpoint()["goals"]), 0)
        host.set_resources("NORMAL")  # explicit synthetic resource input, not telemetry
        self.assertIsNotNone(self.feed(3, host=host)["proposal"])

    def test_unknown_freshness_or_denied_consent_produces_no_goal(self):
        for i in range(6):
            result = self.feed(i, freshness="UNKNOWN" if i < 3 else "FRESH", consent=i < 3)
            self.assertIsNone(result["proposal"])
        self.assertEqual(len(self.host.work.checkpoint()["goals"]), 0)

    def test_cue_remaining_ttl_is_not_restarted_at_admission(self):
        result = self.goal()
        candidate = result["proposal"]["candidate"]
        self.assertLess(candidate["ttl_ms"], 3000)
        self.clock.advance(3000)
        self.assertIsNone(self.host.work.start_next())
        self.assertEqual(self.host.work.view(candidate["candidate_id"])["state"], "EXPIRED")

    def test_context_invalidation_cancels_work_and_blocks_new_goals(self):
        result = self.goal()
        gid = result["proposal"]["candidate"]["candidate_id"]
        self.resolver.invalidate()
        self.assertIsNone(self.feed(3, 0.6)["proposal"])
        self.assertEqual(self.host.work.view(gid)["state"], "CANCELLED")

    def test_user_interruption_pauses_goal_and_goal_generation(self):
        self.goal()
        goal = self.host.work.start_next()
        gid = goal["candidate"]["candidate_id"]
        self.host.interrupt_user(synthetic_event(99))
        self.assertEqual(self.host.work.view(gid)["state"], "PAUSED_USER")
        for i in range(3, 6):
            self.assertIsNone(self.feed(i, 0.6)["proposal"])
        self.host.release_user_attention()
        self.host.work.resume(gid)
        self.assertEqual(self.host.work.view(gid)["state"], "RUNNING")
        self.assertFalse(self.host.work.accept_delegated_result(gid, generation=goal["generation"],
            context_revision=goal["candidate"]["context_revision"]))

    def test_real_feed_requires_integrity_checked_rgd(self):
        host = AttentionAgenda(context_supplier=lambda: context_slice("lab-robot"),
            binding=fixture_binding("AUTHORIZED_LOCAL_FEED"), clock=self.clock, resource_state="NORMAL")
        result = self.feed(0, host=host)
        self.assertEqual(result["attention"]["reason_code"], "CONTEXT_UNAVAILABLE")
        self.assertEqual(len(host.work.checkpoint()["goals"]), 0)

    def test_network_and_process_launch_are_not_needed(self):
        with patch.object(socket, "socket", side_effect=AssertionError("network")), \
             patch.object(subprocess, "Popen", side_effect=AssertionError("process")):
            self.goal()

    def test_generated_demo_has_no_manual_cues_or_physical_claims(self):
        result = run_demo(12)
        self.assertTrue(result["fixture_only"])
        self.assertFalse(result["manual_cue_kind_supplied"])
        self.assertGreaterEqual(len(result["generated_goals"]), 2)
        self.assertTrue(all(r["origin"] == "SYNTHETIC" for r in result["generated_goals"]))
        self.assertFalse(result["external_effects"])

    def test_close_purges_session_without_claiming_life_recovery(self):
        self.goal()
        self.host.close()
        self.assertTrue(self.host.attention.stats()["closed"])
        self.assertEqual(self.host.work.audit(), [])


if __name__ == "__main__":
    unittest.main()
