"""Pure C1 tests; real C0/Core integration lives in tests_integration."""
from copy import deepcopy
import json
from pathlib import Path
import socket
import subprocess
import unittest
from unittest.mock import patch

from jsonschema import Draft202012Validator
from rgd_cognition.attention_c1 import AttentionError, AttentionPolicy, ImuAttention, SourceBinding, _SCHEMA
from rgd_cognition.attention_c1_demo import FixtureClock, fixture_binding, fixture_sample

REV = "sha256:" + "1" * 64


class AttentionTests(unittest.TestCase):
    def setUp(self):
        self.clock = FixtureClock()
        self.engine = ImuAttention(fixture_binding(), policy=AttentionPolicy(cooldown_ms=100), clock=self.clock)

    def feed(self, index, rate=0.0, engine=None, **kwargs):
        self.clock.advance(100)
        return (engine or self.engine).observe(fixture_sample(index, rate), received_ns=self.clock(),
            freshness="FRESH", consent=True, context_revision=REV, allow_goal_generation=True, **kwargs)

    def series(self, start=0, rate=0.0, engine=None):
        return [self.feed(i, rate, engine) for i in range(start, start + 3)]

    def test_schema_and_policy_are_valid(self):
        Draft202012Validator.check_schema(_SCHEMA)
        self.assertNotIn("cog_input_v0.1", json.dumps(_SCHEMA))

    def test_no_cue_before_confirmation_window(self):
        self.assertEqual(self.feed(0)["reason_code"], "WARMING_UP")
        self.assertIsNone(self.feed(1)["cue"])

    def test_uncalibrated_context_creates_one_question(self):
        result = self.series()[-1]
        self.assertEqual(result["reason_code"], "UNCALIBRATED_IMU_CONTEXT")
        self.assertEqual(len(result["cue"]["source_refs"]), 3)
        self.assertTrue(all(self.feed(i)["cue"] is None for i in range(3, 25)))

    def test_sustained_numeric_signal_generates_cue(self):
        result = self.series(rate=0.6)[-1]
        self.assertEqual(result["reason_code"], "SUSTAINED_RATE_UNVERIFIED_FRAME")
        self.assertEqual(result["cue"]["cue_kind"], "IMU_DISCREPANCY")
        self.assertFalse(result["cue"]["decision_eligible"])

    def test_single_spike_not_a_sustained_change(self):
        self.series()
        self.feed(3, 2)
        self.assertIsNone(self.feed(4)["cue"])
        self.assertIsNone(self.feed(5)["cue"])

    def test_hysteresis_requires_low_samples_to_rearm(self):
        self.series(rate=0.6)
        self.assertTrue(all(self.feed(i, 0.6)["cue"] is None for i in range(3, 9)))
        self.series(9)
        self.assertEqual(self.series(12, 0.6)[-1]["status"], "CUE")

    def test_dead_band_does_not_rearm(self):
        self.series(rate=0.6)
        self.series(3, 0.2)
        self.assertIsNone(self.series(6, 0.6)[-1]["cue"])

    def test_motion_hint_is_not_a_detector_or_authority(self):
        self.series()
        for i in range(3, 9):
            sample = fixture_sample(i)
            sample["motion_hint"] = "rotation_observed"
            self.clock.advance(100)
            result = self.engine.observe(sample, received_ns=self.clock(), freshness="FRESH", consent=True,
                context_revision=REV, allow_goal_generation=True)
            self.assertIsNone(result["cue"])

    def test_fixture_stays_synthetic_despite_source_kind(self):
        cue = self.series(rate=0.6)[-1]["cue"]
        self.assertEqual(cue["origin"], "SYNTHETIC")
        self.assertEqual(cue["epistemic_status"], "DERIVED")
        self.assertIsNone(cue["life_id"])
        self.assertEqual(cue["chronon_status"], "NOT_CONNECTED")

    def test_configured_feed_still_declared_and_unverified(self):
        engine = ImuAttention(fixture_binding("AUTHORIZED_LOCAL_FEED"), clock=self.clock)
        cue = self.series(engine=engine)[-1]["cue"]
        self.assertEqual(cue["origin"], "PHYSICAL")
        self.assertEqual(cue["evidence_level"], "DECLARED_ONLY")
        self.assertEqual(cue["calibration_status"], "UNVERIFIED")
        self.assertFalse(cue["may_actuate"])

    def test_no_first_step_from_imu(self):
        cue = self.series(rate=10)[-1]["cue"]
        self.assertNotIn("FIRST_STEP", json.dumps(cue))
        self.assertEqual(cue["scope"], "EPISTEMIC_INQUIRY_ONLY")

    def test_manual_cue_parameter_is_not_supported(self):
        with self.assertRaises(TypeError):
            self.engine.observe({}, received_ns=self.clock(), context_revision=REV, cue_kind="POSSIBLE_FIRST_STEP")

    def test_privacy_denial_has_no_refs_and_clears_window(self):
        self.feed(0)
        result = self.engine.observe({"private": "DO_NOT_LOG"}, received_ns=self.clock(), context_revision=REV)
        self.assertEqual(result["reason_code"], "CONSENT_DENIED")
        self.assertNotIn("DO_NOT_LOG", json.dumps(result))
        self.assertEqual(self.engine.stats()["window_size"], 0)

    def test_unknown_or_stale_freshness_is_not_recent_evidence(self):
        for freshness in ("UNKNOWN", "STALE"):
            result = self.engine.observe(fixture_sample(), received_ns=self.clock(), consent=True,
                freshness=freshness, context_revision=REV, allow_goal_generation=True)
            self.assertEqual(result["reason_code"], "OBSERVATION_NOT_FRESH")

    def test_local_expiry_is_exact_boundary(self):
        received = self.clock()
        self.clock.advance(3000)
        result = self.engine.observe(fixture_sample(), received_ns=received, consent=True,
            freshness="FRESH", context_revision=REV, allow_goal_generation=True)
        self.assertEqual(result["reason_code"], "OBSERVATION_NOT_FRESH")

    def test_future_or_boolean_receipt_rejected(self):
        for received in (self.clock() + 1, -1, True):
            with self.assertRaises(AttentionError):
                self.engine.observe(fixture_sample(), received_ns=received, consent=True, context_revision=REV)

    def test_duplicate_is_not_retimestamped(self):
        self.feed(0)
        self.clock.advance(100)
        result = self.engine.observe(fixture_sample(0), received_ns=self.clock(), freshness="FRESH", consent=True,
            context_revision=REV, allow_goal_generation=True)
        self.assertEqual(result["reason_code"], "DUPLICATE")
        self.assertEqual(self.engine.stats()["window_size"], 1)

    def test_sequence_collision_is_rejected(self):
        self.feed(0)
        self.assertEqual(self.feed(0, 0.7)["reason_code"], "SEQUENCE_COLLISION")
        self.assertEqual(self.engine.stats()["window_size"], 0)

    def test_source_sequence_and_clock_order_both_checked(self):
        self.feed(3)
        self.assertEqual(self.feed(2)["reason_code"], "OUT_OF_ORDER")
        sample = fixture_sample(4)
        sample["host_monotonic_ns"] = 1
        result = self.engine.observe(sample, received_ns=self.clock(), freshness="FRESH", consent=True,
            context_revision=REV, allow_goal_generation=True)
        self.assertEqual(result["reason_code"], "OUT_OF_ORDER")

    def test_source_clock_is_not_compared_to_receipt_clock(self):
        for i in range(3):
            sample = fixture_sample(i)
            sample["host_monotonic_ns"] = 9000000000000 + i
            sample["host_receive_utc"] = "2001-01-01T00:00:00Z"
            self.clock.advance(100)
            result = self.engine.observe(sample, received_ns=self.clock(), freshness="FRESH", consent=True,
                context_revision=REV, allow_goal_generation=True)
        self.assertEqual(result["cue"]["source_time"], "2001-01-01T00:00:00Z")
        self.assertIn("console.host_receive", result["cue"]["source_clock_domain"])

    def test_no_session_rollover_or_cross_source(self):
        for key, value in (("session_id", "b" * 32), ("source_id", "other"), ("sensor_id", "other"),
                           ("robot_id", "other"), ("sensor_frame_id", "other")):
            sample = fixture_sample(); sample[key] = value
            result = self.engine.observe(sample, received_ns=self.clock(), freshness="FRESH", consent=True,
                context_revision=REV, allow_goal_generation=True)
            self.assertEqual(result["reason_code"], "SOURCE_BINDING_MISMATCH")

    def test_sequence_gap_resets_window(self):
        self.feed(0, 0.7); self.feed(1, 0.7)
        self.assertEqual(self.feed(4, 0.7)["reason_code"], "WARMING_UP")

    def test_receipt_gap_resets_window(self):
        self.feed(0); self.feed(1)
        self.clock.advance(1100)
        self.assertEqual(self.feed(2)["reason_code"], "WARMING_UP")

    def test_context_revision_resets_window_not_quota(self):
        self.series()
        for i in range(3, 6):
            self.clock.advance(100)
            result = self.engine.observe(fixture_sample(i), received_ns=self.clock(), freshness="FRESH", consent=True,
                context_revision="sha256:" + "2" * 64, allow_goal_generation=True)
        self.assertIsNone(result["cue"])
        self.assertEqual(self.engine.stats()["proposals"], 1)

    def test_pause_defers_question_without_consuming_it(self):
        for i in range(3):
            self.clock.advance(100)
            result = self.engine.observe(fixture_sample(i), received_ns=self.clock(), freshness="FRESH", consent=True,
                context_revision=REV, allow_goal_generation=False)
        self.assertEqual(result["reason_code"], "GENERATION_PAUSED")
        self.assertEqual(self.feed(3)["status"], "CUE")

    def test_global_cooldown_covers_different_cue_reasons(self):
        engine = ImuAttention(fixture_binding(), policy=AttentionPolicy(cooldown_ms=1000), clock=self.clock)
        self.series(engine=engine)
        self.assertEqual(self.series(3, 0.6, engine)[-1]["reason_code"], "COOLDOWN")
        self.clock.advance(1000)
        # Gap resets the window; new evidence is needed, not a stale cue retry.
        self.assertIsNone(self.feed(6, 0.6, engine)["cue"])

    def test_hard_session_quota_and_bounded_stream(self):
        engine = ImuAttention(fixture_binding(), policy=AttentionPolicy(max_proposals=2, cooldown_ms=1), clock=self.clock)
        for i in range(1000):
            self.feed(i, 0.6 if (i // 3) % 2 else 0.0, engine)
        self.assertEqual(engine.stats()["proposals"], 2)
        self.assertLessEqual(engine.stats()["window_size"], 3)
        self.assertLessEqual(len(engine.stats()["counts"]), 6)

    def test_no_unknown_fields_or_privilege_claims(self):
        for key, value in (("grants", ["CAN"]), ("cue_kind", "POSSIBLE_FIRST_STEP"),
                           ("decision_eligible", True), ("heading_calibrated", True),
                           ("calibration_revision", "verified"), ("observation_only", False)):
            sample = fixture_sample(); sample[key] = value
            with self.assertRaises(AttentionError):
                self.engine.observe(sample, received_ns=self.clock(), freshness="FRESH", consent=True,
                    context_revision=REV, allow_goal_generation=True)

    def test_malformed_nonfinite_and_oversized_data_rejected(self):
        for key, value in (("angular_velocity_rad_s", [float("nan"), 0, 0]),
                           ("angular_velocity_rad_s", [float("inf"), 0, 0]),
                           ("angular_velocity_rad_s", [True, 0, 0]),
                           ("angular_velocity_rad_s", [1000, 0, 0]), ("sequence", True),
                           ("source_id", "x" * 5000), ("temperature_c", float("nan")),
                           ("host_receive_utc", "2026-02-30T00:00:00Z"),
                           ("host_receive_utc", "2026-10-31T00:00:00")):
            sample = fixture_sample(); sample[key] = value
            with self.assertRaises(AttentionError):
                self.engine.observe(sample, received_ns=self.clock(), freshness="FRESH", consent=True,
                    context_revision=REV, allow_goal_generation=True)

    def test_bad_inputs_do_not_leak_values(self):
        sample = fixture_sample(); sample["secret"] = "PRIVATE_TEXT"
        with self.assertRaises(AttentionError) as error:
            self.engine.observe(sample, received_ns=self.clock(), freshness="FRESH", consent=True,
                context_revision=REV, allow_goal_generation=True)
        self.assertNotIn("PRIVATE_TEXT", str(error.exception))

    def test_policy_binding_and_close_guards(self):
        for args in ({"min_samples": True}, {"min_samples": 1}, {"max_proposals": 0},
                     {"rotation_high_rad_s": float("nan")}, {"rotation_low_rad_s": 0.9},
                     {"max_gap_ms": 4000}):
            with self.assertRaises(AttentionError): AttentionPolicy(**args)
        with self.assertRaises(AttentionError):
            SourceBinding("x", "x", "x", "x", "x", "not-a-session")
        self.engine.close()
        with self.assertRaises(AttentionError): self.feed(0)

    def test_clock_regression_closes_the_engine(self):
        self.feed(0)
        self.clock.value = 0
        with self.assertRaises(AttentionError): self.feed(1)
        self.assertTrue(self.engine.stats()["closed"])

    def test_no_runtime_network_process_or_file_open(self):
        with patch.object(socket, "socket", side_effect=AssertionError("network")), \
             patch.object(subprocess, "Popen", side_effect=AssertionError("process")), \
             patch("builtins.open", side_effect=AssertionError("file")):
            self.assertEqual(self.series(rate=0.6)[-1]["status"], "CUE")

    def test_output_mutation_cannot_change_detector_state(self):
        cue = self.series()[-1]["cue"]
        cue["source_refs"].clear()
        cue["may_actuate"] = True
        self.assertEqual(self.engine.stats()["proposals"], 1)
        self.assertEqual(self.engine.stats()["window_size"], 3)


if __name__ == "__main__":
    unittest.main()
