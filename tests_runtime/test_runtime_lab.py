"""Genuine pinned Core-B/C1 supervisor tests: synthetic only, no real sources."""
from copy import deepcopy
import os
from pathlib import Path
from threading import Thread
import unittest
from unittest.mock import patch

from rgd_cognition.attention_c1 import AttentionPolicy
from rgd_cognition.attention_c1_demo import FixtureClock, fixture_sample
from rgd_cognition.core_b_adapter import Limits
from rgd_cognition.rgd_context import RGDContextResolver
from rgd_cognition.runtime_lab import RuntimeLab, RuntimeLabConfig, RuntimeLabOwners, RuntimeLabError, run_replay

CORE = Path(os.environ["RGD_CORE_CHECKOUT"])
CORE_B = Path(os.environ["CORE_B_CHECKOUT"])
RAW = (CORE_B / "contracts/kernel/v0.1.0/schemas/kernel-goal-effect.schema.json").read_bytes()
ROOT = "sha256:c049dc3fb91c19e668ef0d35b9b40d9052caf1a458b1a108d58b1896189dd5f9"


class LabTests(unittest.TestCase):
    def setUp(self):
        self.clock = FixtureClock()
        self.owners = RuntimeLabOwners()
        self.config = RuntimeLabConfig(enabled=True, work=Limits(enabled=True))
        self.make()

    def make(self, **kwargs):
        self.lab = RuntimeLab(RAW, owners=self.owners, config=kwargs.pop("config", self.config),
                              clock_ns=kwargs.pop("clock_ns", self.clock), **kwargs)
        self.session = self.lab.start(self.owners.operator)
        return self.session

    def offer(self, i, *, sample=None, consent=True, session=None):
        row = fixture_sample(i) if sample is None else deepcopy(sample)
        if sample is None:
            row["session_id"] = self.session["source_session"]
        return self.lab.offer(self.owners.synthetic_source,
            runtime_session=self.session["runtime_session"] if session is None else session,
            sample=row, consent=consent)

    def cmd(self, name):
        self.assertEqual(self.lab.request_control(self.owners.operator, name), "QUEUED")
        return self.lab.tick(self.owners.operator)

    def tick(self):
        return self.lab.tick(self.owners.operator)

    def health(self):
        return self.lab.health(self.owners.operator)

    def series(self, n=3):
        report = None
        for i in range(n):
            self.clock.advance(100)
            self.assertEqual(self.offer(i), "QUEUED")
            report = self.tick()
        return report

    def test_default_disabled_and_work_default_disabled(self):
        lab = RuntimeLab(RAW, owners=self.owners, clock_ns=self.clock)
        with self.assertRaisesRegex(RuntimeLabError, "RUNTIME_DISABLED"):
            lab.start(self.owners.operator)
        self.assertEqual(lab.health(self.owners.operator)["state"], "STOPPED")
        self.make(config=RuntimeLabConfig(enabled=True))
        self.cmd("RESOURCE_NORMAL")
        self.assertEqual(self.series()["admission"], "REJECT")

    def test_unknown_resources_no_admission(self):
        self.assertEqual(self.session["state"], "DEGRADED")
        self.assertIsNone(self.series()["admission"])
        self.assertEqual(self.health()["work_usage"]["idempotency_entries"], 0)

    def test_actual_single_admission_and_no_worker(self):
        self.cmd("RESOURCE_NORMAL")
        with patch("rgd_cognition.agenda_c0.SessionAgenda.propose", side_effect=AssertionError("second admission")):
            result = self.series()
        self.assertEqual(result["admission"], "ADMIT")
        health = self.health()
        self.assertEqual(health["work_usage"]["reserved_steps"], 2)
        self.assertEqual(health["work_usage"]["spent_steps"], 0)
        self.assertFalse(health["worker_connected"])
        self.assertFalse(health["external_effects"])
        self.assertIsNone(health["life_id"])

    def test_idle_heartbeat_expires_real_work(self):
        self.cmd("RESOURCE_NORMAL")
        self.series()
        self.assertGreater(self.health()["work_usage"]["reserved_slots"], 0)
        self.clock.advance(3000)
        self.assertEqual(self.tick()["kind"], "HEARTBEAT")
        self.assertEqual(self.health()["work_usage"]["reserved_steps"], 0)
        self.assertEqual(self.health()["work_usage"]["reserved_wall_ms"], 0)

    def test_input_expiry_no_receipt_renewal(self):
        self.assertEqual(self.offer(0), "QUEUED")
        self.clock.advance(3000)
        self.assertEqual(self.tick()["kind"], "HEARTBEAT")
        self.assertEqual(self.health()["counters"]["expired"], 1)
        self.assertEqual(self.offer(0), "REPLAY_OR_OUT_OF_ORDER")
        self.assertEqual(self.health()["replay_entries"], 0)

    def test_duplicate_and_collision_in_validity_window(self):
        self.assertEqual(self.offer(0), "QUEUED")
        self.assertEqual(self.offer(0), "DUPLICATE")
        row = fixture_sample(0, 0.6)
        row["session_id"] = self.session["source_session"]
        self.assertEqual(self.offer(0, sample=row), "SEQUENCE_COLLISION")
        self.assertEqual(self.health()["pending_input"], 1)
        self.assertEqual(self.health()["replay_entries"], 1)

    def test_pressure_drops_are_terminal(self):
        self.make(config=RuntimeLabConfig(enabled=True, input_capacity=1, replay_capacity=2))
        self.assertEqual(self.offer(0), "QUEUED")
        self.assertEqual(self.offer(1), "BACKPRESSURE")
        self.tick()
        self.assertEqual(self.offer(1), "REPLAY_OR_OUT_OF_ORDER")
        self.assertEqual(self.offer(2), "QUEUED")
        self.tick()
        self.assertEqual(self.offer(3), "BACKPRESSURE")  # retained valid keys full
        self.clock.advance(3000)
        self.tick()
        self.assertEqual(self.offer(3), "REPLAY_OR_OUT_OF_ORDER")
        self.assertEqual(self.offer(4), "QUEUED")
        self.assertLessEqual(self.health()["replay_high_water"], 2)

    def test_source_clock_order_independent_from_receipt(self):
        self.assertEqual(self.offer(0), "QUEUED")
        row = fixture_sample(1)
        row["session_id"] = self.session["source_session"]
        row["host_monotonic_ns"] = fixture_sample(0)["host_monotonic_ns"]
        self.assertEqual(self.offer(1, sample=row), "REPLAY_OR_OUT_OF_ORDER")

    def test_foreign_source_and_runtime_session(self):
        self.assertEqual(self.offer(0, session="other"), "FOREIGN_SESSION")
        row = fixture_sample(0)
        self.assertEqual(self.offer(0, sample=row), "SOURCE_MISMATCH")
        self.assertEqual(self.health()["pending_input"], 0)

    def test_input_mutation_cannot_alter_queued_record(self):
        row = fixture_sample(0)
        row["session_id"] = self.session["source_session"]
        self.assertEqual(self.lab.offer(self.owners.synthetic_source, runtime_session=self.session["runtime_session"], sample=row, consent=True), "QUEUED")
        row["decision_eligible"] = True
        self.assertEqual(self.tick()["kind"], "INPUT")
        self.assertEqual(self.offer(0), "DUPLICATE")

    def test_consent_denial_retains_no_denied_payload(self):
        self.assertEqual(self.offer(0), "QUEUED")
        self.assertEqual(self.offer(1, sample={"private": "DO_NOT_RETAIN"}, consent=False), "CONSENT_DENIED")
        self.assertEqual(self.health()["pending_input"], 0)
        self.assertNotIn("DO_NOT_RETAIN", str(self.health()))
        self.assertEqual(self.tick()["kind"], "HEARTBEAT")

    def test_malformed_and_nonfinite_rejected_without_payload(self):
        for value in (float('nan'), True, 1.0):
            row = fixture_sample(0)
            row["session_id"] = self.session["source_session"]
            row["sequence"] = value
            self.assertEqual(self.offer(0, sample=row), "INVALID_SAMPLE")
        self.assertEqual(self.health()["pending_input"], 0)

    def test_priority_pause_flushes_backlog_and_requires_release(self):
        self.cmd("RESOURCE_NORMAL")
        for i in range(10):
            self.assertEqual(self.offer(i), "QUEUED")
        for _ in range(8):
            self.assertEqual(self.lab.request_control(self.owners.operator, "RESOURCE_LOW"), "QUEUED")
        self.assertEqual(self.lab.request_control(self.owners.operator, "RESOURCE_LOW"), "BACKPRESSURE")
        self.assertEqual(self.lab.request_control(self.owners.operator, "PAUSE"), "QUEUED")
        self.assertEqual(self.lab.request_control(self.owners.operator, "RELEASE"), "NOT_PAUSED")
        self.assertEqual(self.tick()["status"], "PAUSED")
        self.assertEqual(self.health()["pending_input"], 0)
        self.assertEqual(self.offer(10), "CONTROL_PENDING_OR_PAUSED")
        self.assertEqual(self.cmd("RESOURCE_NORMAL")["status"], "PAUSED")
        self.assertEqual(self.cmd("RELEASE")["status"], "READY_LAB")
        self.assertEqual(self.offer(10), "REPLAY_OR_OUT_OF_ORDER")
        self.assertEqual(self.health()["work_usage"]["spent_steps"], 0)
        self.assertEqual(self.tick()["kind"], "HEARTBEAT")

    def test_stop_priority_and_idempotent_purge(self):
        self.cmd("RESOURCE_NORMAL")
        self.series()
        self.offer(3)
        self.lab.request_control(self.owners.operator, "PAUSE")
        self.assertEqual(self.lab.request_control(self.owners.operator, "STOP"), "QUEUED")
        self.assertEqual(self.lab.request_control(self.owners.operator, "RELEASE"), "STOP_PENDING")
        self.assertEqual(self.tick()["status"], "STOPPED")
        h = self.health()
        self.assertEqual(h["pending_input"], 0)
        self.assertEqual(h["replay_entries"], 0)
        self.assertEqual(h["work_usage"]["reserved_steps"], 0)
        self.assertEqual(self.lab.stop(self.owners.operator), h)

    def test_restart_requires_stop_and_rotates_source_and_runtime(self):
        old = dict(self.session)
        with self.assertRaisesRegex(RuntimeLabError, "EXPLICIT_STOP_REQUIRED"):
            self.lab.start(self.owners.operator)
        self.lab.stop(self.owners.operator)
        self.session = self.lab.start(self.owners.operator)
        self.assertNotEqual(old["runtime_session"], self.session["runtime_session"])
        self.assertNotEqual(old["source_session"], self.session["source_session"])
        self.assertEqual(self.offer(0, session=old["runtime_session"]), "FOREIGN_SESSION")
        row = fixture_sample(0); row["session_id"] = old["source_session"]
        self.assertEqual(self.offer(0, sample=row), "SOURCE_MISMATCH")
        self.assertEqual(self.health()["work_usage"]["reserved_steps"], 0)
        self.assertEqual(self.health()["state"], "DEGRADED")

    def test_clock_regression_fault_purges_and_releases(self):
        self.cmd("RESOURCE_NORMAL"); self.series(); self.offer(3)
        self.clock.value -= 1
        with self.assertRaisesRegex(RuntimeLabError, "RUNTIME_CLOCK_REGRESSION"):
            self.tick()
        h = self.health()
        self.assertEqual(h["state"], "FAULT")
        self.assertEqual(h["pending_input"], 0)
        self.assertEqual(h["work_usage"]["reserved_steps"], 0)
        with self.assertRaises(RuntimeLabError): self.lab.start(self.owners.operator)

    def test_clock_exception_redacted(self):
        class BadClock(FixtureClock):
            broken = False
            def __call__(self):
                if self.broken: raise RuntimeError("SECRET_CLOCK_TEXT")
                return super().__call__()
        bad = BadClock(); self.make(clock_ns=bad); bad.broken = True
        with self.assertRaisesRegex(RuntimeLabError, "RUNTIME_CLOCK_FAILURE"):
            self.tick()
        self.assertEqual(self.health()["state"], "FAULT")
        self.assertNotIn("SECRET_CLOCK_TEXT", str(self.health()))

    def test_session_limit_no_automatic_rollover(self):
        self.make(config=RuntimeLabConfig(enabled=True, max_session_ms=20))
        self.clock.advance(20)
        with self.assertRaisesRegex(RuntimeLabError, "RUNTIME_SESSION_LIMIT"):
            self.tick()
        self.assertEqual(self.health()["state"], "FAULT")

    def test_real_pinned_context_revocation_on_idle_tick(self):
        resolver = RGDContextResolver(CORE, local_alias="lab-robot", expected_source_root=ROOT, clock=self.clock)
        self.assertEqual(resolver.refresh()["reference_status"], "SOURCE_INTEGRITY_VERIFIED")
        self.make(resolver=resolver)
        self.cmd("RESOURCE_NORMAL"); self.series()
        resolver.invalidate()
        with self.assertRaisesRegex(RuntimeLabError, "RUNTIME_CONTEXT_OR_WORK_FAULT"):
            self.tick()
        self.assertEqual(self.health()["state"], "FAULT")
        self.assertEqual(self.health()["work_usage"]["reserved_steps"], 0)

    def test_unloaded_resolver_cannot_start(self):
        resolver = RGDContextResolver(CORE, local_alias="lab-robot", expected_source_root=ROOT, clock=self.clock)
        with self.assertRaisesRegex(RuntimeLabError, "RUNTIME_START_FAILED"):
            self.make(resolver=resolver)
        self.assertEqual(self.health()["state"], "FAULT")

    def test_owner_and_thread_guards(self):
        with self.assertRaisesRegex(RuntimeLabError, "UNAUTHORIZED_OPERATOR"):
            self.lab.tick(self.owners.synthetic_source)
        with self.assertRaisesRegex(RuntimeLabError, "UNAUTHORIZED_SOURCE"):
            self.lab.offer(self.owners.operator, runtime_session=self.session["runtime_session"], sample={}, consent=True)
        errors = []
        def foreign():
            try: self.lab.tick(self.owners.operator)
            except RuntimeLabError as exc: errors.append(str(exc))
        t = Thread(target=foreign); t.start(); t.join()
        self.assertEqual(errors, ["WRONG_SUPERVISOR_THREAD"])

    def test_fractional_deadline_deferral_preserved(self):
        self.cmd("RESOURCE_NORMAL")
        self.clock.value += 1
        result = self.series()
        self.assertIsNone(result["admission"])
        self.assertEqual(self.health()["counters"]["conservative_deferrals"], 1)
        self.assertEqual(self.health()["work_usage"]["reserved_steps"], 0)

    def test_audit_exhaustion_fails_closed(self):
        # A small Core-B record budget: repeated cue admissions saturate the
        # actual Work audit; no second local admission bypasses backpressure.
        cfg = RuntimeLabConfig(enabled=True, work=Limits(enabled=True, records=8),
            attention=AttentionPolicy(cooldown_ms=1, max_proposals=16))
        self.make(config=cfg); self.cmd("RESOURCE_NORMAL")
        faulted = False
        for i in range(200):
            self.clock.advance(100)
            row = fixture_sample(i, 0.6 if (i // 3) % 2 else 0.0)
            row["session_id"] = self.session["source_session"]
            self.assertEqual(self.offer(i, sample=row), "QUEUED")
            try: self.tick()
            except RuntimeLabError:
                faulted = True; break
        self.assertTrue(faulted)
        self.assertEqual(self.health()["state"], "FAULT")
        self.assertEqual(self.health()["work_usage"]["reserved_steps"], 0)

    def test_1000_event_replay_bounded_no_network_process(self):
        with patch("socket.socket", side_effect=AssertionError("network")), patch("subprocess.Popen", side_effect=AssertionError("process")):
            r = run_replay(RAW, 1000)
        h = r["active"]
        self.assertEqual(h["counters"]["processed"], 1000)
        self.assertEqual(h["pending_input"], 0)
        self.assertEqual(h["replay_high_water"], 30)
        self.assertGreater(h["counters"]["admission_admit"], 0)
        self.assertEqual(h["work_usage"]["spent_steps"], 0)
        self.assertEqual(r["closed"]["state"], "STOPPED")
        self.assertEqual(r["closed"]["replay_entries"], 0)


if __name__ == "__main__":
    unittest.main()
