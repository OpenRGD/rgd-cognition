"""Actual subprocess + actual C1/Core-B lab; no hardware, network or live provider."""
import ast
from copy import deepcopy
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import unittest
from unittest.mock import patch

from rgd_cognition.attention_c1_demo import FixtureClock, fixture_sample
from rgd_cognition.core_b_adapter import Limits, digest, validate_result_bundle
from rgd_cognition.rgd_context import RGDContextResolver
from rgd_cognition.runtime_lab import RuntimeLabConfig, RuntimeLabOwners, RuntimeLabError
from rgd_cognition.worker_lab import WorkerLab, WorkerLabConfig
from rgd_cognition.worker_lab.fixture import (PROFILE, TASK, MAX_FRAME, WorkerProtocolError,
    encode_frame, decode_frame, expected_response, validate_request, validate_response)

CORE = Path(os.environ["RGD_CORE_CHECKOUT"])
RAW = (Path(os.environ["CORE_B_CHECKOUT"]) / "contracts/kernel/v0.1.0/schemas/kernel-goal-effect.schema.json").read_bytes()
ROOT = "sha256:c049dc3fb91c19e668ef0d35b9b40d9052caf1a458b1a108d58b1896189dd5f9"


class ProtocolTests(unittest.TestCase):
    def request(self):
        return {"profile": PROFILE, "task_ref": TASK, "request_id": digest("one"),
                "ticket_digest": digest("ticket"), "evidence_refs": [digest("ref")], "fixture_only": True}

    def test_extended_architecture_guard_only_worker_boundary_may_spawn(self):
        # Keep Foundation's existing root-module guard unchanged. Explicitly
        # extend its coverage recursively for this new process compartment.
        root = Path(__file__).resolve().parents[1] / "src/rgd_cognition"
        forbidden = {"socket", "subprocess", "requests", "httpx", "urllib", "http", "serial", "can", "ctypes", "pickle", "shelve"}
        launch_sites = []
        for path in root.rglob("*.py"):
            rel = path.relative_to(root).as_posix()
            tree = ast.parse(path.read_text())
            allowed = forbidden - {"subprocess"} if rel == "worker_lab/__init__.py" else forbidden
            for node in ast.walk(tree):
                names = ([n.name for n in node.names] if isinstance(node, ast.Import) else
                         [node.module or ""] if isinstance(node, ast.ImportFrom) else [])
                for name in names:
                    self.assertNotIn(name.split(".")[0], allowed, rel)
                if isinstance(node, ast.Call):
                    if isinstance(node.func, ast.Name):
                        self.assertNotIn(node.func.id, {"eval", "exec", "__import__"}, rel)
                    if isinstance(node.func, ast.Attribute) and node.func.attr == "Popen":
                        launch_sites.append(rel)
        self.assertEqual(launch_sites, ["worker_lab/__init__.py"])

    def test_exact_response(self):
        req = self.request(); result = expected_response(req)
        self.assertEqual(validate_response(encode_frame(result), req), result)

    def test_duplicate_nonfinite_trailing_and_oversize(self):
        for raw in (b'{"x":1,"x":2}', b'{"x":NaN}', b'{}\n{}', b'x'*(MAX_FRAME+1), b'[]', b'{"x": 1}'):
            with self.subTest(raw=raw[:12]), self.assertRaises(WorkerProtocolError):
                decode_frame(raw)

    def test_no_arbitrary_task_or_capability(self):
        for update in ({"task_ref": "shell"}, {"operator": "pretend"}, {"fixture_only": False},
                       {"evidence_refs": ["file:/private"]}, {"evidence_refs": []},
                       {"evidence_refs": [digest("x")]*2}):
            with self.subTest(update=update), self.assertRaises(WorkerProtocolError):
                validate_request({**self.request(), **update})

    def test_response_binding_cannot_be_changed(self):
        req = self.request()
        for update in ({"request_id": digest("other")}, {"ticket_digest": digest("old")},
                       {"request_sha256": "0"*64}, {"evidence_refs": [digest("fake")]},
                       {"code": "ABSTAIN"}, {"grants_authority": True}, {"fixture_only": 1}):
            with self.subTest(update=update), self.assertRaises(WorkerProtocolError):
                validate_response(encode_frame({**expected_response(req), **update}), req)

    def test_previous_response_not_accepted_in_new_request(self):
        req = self.request(); old = encode_frame(expected_response(req))
        newer = {**req, "request_id": digest("new")}
        with self.assertRaises(WorkerProtocolError): validate_response(old, newer)


@unittest.skipUnless(sys.platform.startswith("linux"), "Linux worker lab uses POSIX pipes/signals")
class ActualWorkerTests(unittest.TestCase):
    def setUp(self):
        self.clock, self.owners = FixtureClock(), RuntimeLabOwners()
        self.lab = None
        self.make()

    def tearDown(self):
        if self.lab is not None:
            self.lab.stop(self.owners.operator)
            self.assertFalse(self.lab.health(self.owners.operator)["worker_reap_pending"])

    def make(self, mode="NORMAL", enabled=True, wall_ms=1000, resolver=None, config=None, clock=None):
        if self.lab is not None:
            self.lab.stop(self.owners.operator)
        self.lab = WorkerLab(RAW, owners=self.owners,
            config=config or RuntimeLabConfig(enabled=True, work=Limits(enabled=True)),
            worker=WorkerLabConfig(enabled=enabled, wall_ms=wall_ms, terminate_grace_ms=50, fixture_mode=mode),
            clock_ns=clock or self.clock, resolver=resolver)
        self.session = self.lab.start(self.owners.operator)
        self.control("RESOURCE_NORMAL")
        return self.lab

    def tick(self):
        return self.lab.tick(self.owners.operator)

    def control(self, command):
        self.assertEqual(self.lab.request_control(self.owners.operator, command), "QUEUED")
        return self.tick()

    def health(self):
        return self.lab.health(self.owners.operator)

    def offer(self, seq, consent=True):
        row = fixture_sample(seq)
        row["session_id"] = self.session["source_session"]
        return self.lab.offer(self.owners.synthetic_source, runtime_session=self.session["runtime_session"],
                              sample=row, consent=consent)

    def admitted(self):
        for i in range(3):
            self.clock.advance(100)
            self.assertEqual(self.offer(i), "QUEUED")
            report = self.tick()
        self.assertEqual(report["admission"], "ADMIT")
        return next(iter(self.lab._host.work.inspect()["goals"]))

    def dispatch(self, goal=None, **kwargs):
        goal = self.admitted() if goal is None else goal
        report = self.lab.dispatch(self.owners.operator, goal, **kwargs)
        self.assertEqual(report["status"], "DISPATCHED")
        return goal, self.lab._flight

    def await_event(self, max_s=3):
        until = time.monotonic()+max_s
        while time.monotonic() < until:
            event = self.tick().get("worker")
            if event is not None:
                return event
            time.sleep(.005)
        self.fail("worker event missing within test bound")

    def test_worker_disabled_default_and_explicit_dispatch(self):
        self.make(enabled=False); g = self.admitted()
        self.assertEqual(self.lab.eligible(self.owners.operator), [])
        with self.assertRaisesRegex(RuntimeLabError, "WORKER_DISABLED"):
            self.lab.dispatch(self.owners.operator, g)
        self.assertEqual(self.health()["work_usage"]["spent_steps"], 0)

    def test_actual_process_outcome_trace_single_admission(self):
        with patch("rgd_cognition.agenda_c0.SessionAgenda.propose", side_effect=AssertionError("second admission")):
            g, f = self.dispatch(); p = f.process
            self.assertIsNotNone(p.pid)
            event = self.await_event()
        self.assertEqual(event["status"], "COMPLETED")
        bundle = validate_result_bundle(self.lab._host.schema, event["result"])
        self.assertEqual(bundle["outcome"]["goal_id"], g)
        self.assertEqual(bundle["outcome"]["verification"], "UNVERIFIED")
        self.assertEqual(bundle["cognitive_trace"]["provenance_class"], "SYNTHETIC")
        self.assertFalse(bundle["cognitive_trace"]["may_actuate"])
        self.assertIsNone(bundle["cognitive_trace"]["life_id"])
        self.assertEqual(self.health()["work_usage"]["spent_steps"], 1)
        self.assertEqual(self.health()["work_usage"]["reserved_slots"], 0)
        self.assertEqual(self.health()["counters"]["admission_admit"], 1)
        self.assertEqual(p.returncode, 0); self.assertTrue(p.stdout.closed)
        self.assertIsNone(self.tick().get("worker"))
        self.assertEqual(self.health()["counters"]["worker_completed"], 1)

    def test_unknown_goal_and_unauthorized_operator_refused(self):
        g = self.admitted()
        with self.assertRaisesRegex(RuntimeLabError, "UNAUTHORIZED_OPERATOR"):
            self.lab.dispatch(object(), g)
        with self.assertRaisesRegex(RuntimeLabError, "UNKNOWN_WORK_GOAL"):
            self.lab.dispatch(self.owners.operator, "fake")
        self.assertFalse(self.health()["worker_active"])

    def test_one_inflight_and_no_auto_dispatch(self):
        g = self.admitted(); self.tick()
        self.assertFalse(self.health()["worker_active"])
        self.dispatch(g)
        self.assertEqual(self.lab.eligible(self.owners.operator), [])
        with self.assertRaisesRegex(RuntimeLabError, "WORKER_NOT_AVAILABLE"):
            self.lab.dispatch(self.owners.operator, g)
        self.await_event()

    def test_fixed_process_arguments_and_no_inherited_environment(self):
        with patch.dict(os.environ, {"SECRET_TEST_TOKEN": "should-not-cross"}), \
                patch("rgd_cognition.worker_lab.subprocess.Popen", wraps=subprocess.Popen) as launch:
            g, f = self.dispatch()
            self.assertEqual(launch.call_count, 1)
            kwargs = launch.call_args.kwargs
            self.assertEqual(kwargs["env"], {"LANG": "C", "LC_ALL": "C"})
            self.assertTrue(kwargs["close_fds"])
            self.assertFalse(kwargs.get("shell", False))
            cmd = f.process.args
            self.assertEqual(cmd[1:3], ["-I", "-B"])
            self.assertTrue(Path(cmd[3]).is_absolute())
            self.assertEqual(Path(cmd[3]).name, "fixture.py")
            self.assertEqual(cmd[-1], "NORMAL")
            self.assertNotIn("SECRET_TEST_TOKEN", str(f.request))
        self.await_event()

    def test_real_deadline_with_frozen_fixture_clock(self):
        self.make(mode="BLOCK", wall_ms=75)
        g, f = self.dispatch(); before = self.clock.value
        event = self.await_event()
        self.assertEqual(event, {"status":"REJECTED", "reason":"WORKER_DEADLINE"})
        self.assertEqual(self.clock.value, before)
        self.assertIsNotNone(f.process.returncode)
        self.assertEqual(self.lab._host.work.inspect()["goals"][g]["state"], "FAILED")
        self.assertEqual(self.health()["work_usage"]["reserved_slots"], 0)
        self.assertEqual(self.health()["work_usage"]["spent_steps"], 0)

    def test_goal_expiry_wins_over_buffered_success(self):
        g, f = self.dispatch()
        f.process.wait(timeout=2)
        self.clock.advance(3000)
        event = self.tick()["worker"]
        self.assertEqual(event["status"], "CANCELLED")
        self.assertEqual(self.lab._host.work.inspect()["goals"][g]["state"], "CANCELLED")
        self.assertEqual(self.health()["work_usage"]["spent_steps"], 0)

    def test_wall_budget_caps_worker_and_is_charged(self):
        self.make(mode="BLOCK", wall_ms=1000)
        g, f = self.dispatch()
        self.assertLessEqual(f.session_deadline_ns-self.lab._now(), 1_000_000_000)
        self.clock.advance(1000)
        self.tick()
        usage = self.health()["work_usage"]
        self.assertEqual(usage["spent_wall_ms"], 1000)
        self.assertEqual(usage["reserved_wall_ms"], 0)
        self.assertIsNotNone(f.process.returncode)

    def test_ready_result_loses_to_queued_pause(self):
        g, f = self.dispatch(); f.process.wait(timeout=2)
        result = self.control("PAUSE")
        self.assertEqual(result["worker"]["status"], "CANCELLED")
        self.assertEqual(self.health()["state"], "PAUSED")
        self.assertEqual(self.health()["work_usage"]["spent_steps"], 0)
        self.assertEqual(self.lab._host.work.inspect()["goals"][g]["state"], "PAUSED")
        with self.assertRaisesRegex(RuntimeLabError, "WORK_CONTROL_BLOCKED"):
            self.lab.dispatch(self.owners.operator, g, resume=True)
        self.control("RELEASE"); self.tick()
        self.assertFalse(self.health()["worker_active"])
        self.assertEqual(self.lab.eligible(self.owners.operator), [{"goal_id":g,"state":"PAUSED"}])
        with self.assertRaisesRegex(RuntimeLabError, "WORK_NOT_DISPATCHABLE"):
            self.lab.dispatch(self.owners.operator, g)
        _, new = self.dispatch(g, resume=True)
        self.assertNotEqual(new.ticket, f.ticket)
        self.assertNotEqual(new.request["request_id"], f.request["request_id"])
        with self.assertRaises(WorkerProtocolError):
            validate_response(encode_frame(expected_response(f.request)), new.request)
        self.assertEqual(self.await_event()["status"], "COMPLETED")

    def test_resource_loss_cancels_and_no_auto_resume(self):
        self.make(mode="BLOCK")
        g, f = self.dispatch(); self.control("RESOURCE_LOW")
        self.assertIsNotNone(f.process.returncode)
        self.assertEqual(self.lab._host.work.inspect()["goals"][g]["state"], "PAUSED")
        self.control("RESOURCE_NORMAL"); self.tick()
        self.assertFalse(self.health()["worker_active"])
        self.assertEqual(self.health()["work_usage"]["spent_steps"], 0)

    def test_blocked_worker_does_not_starve_priority_control(self):
        self.make(mode="BLOCK"); g, f = self.dispatch()
        self.clock.advance(100); self.assertEqual(self.offer(3), "QUEUED")
        before = time.monotonic(); report = self.control("STOP")
        self.assertLess(time.monotonic()-before, 2)
        self.assertEqual(report["status"], "STOPPED")
        self.assertIsNotNone(f.process.returncode)
        self.assertEqual(self.health()["pending_input"], 0)
        self.assertEqual(self.health()["work_usage"]["reserved_steps"], 0)

    def test_ignore_term_fixture_is_killed_and_reaped(self):
        self.make(mode="IGNORE_TERM"); _, f = self.dispatch()
        deadline = time.monotonic()+.6
        while not f.output and time.monotonic()<deadline:
            self.tick(); time.sleep(.005)
        self.assertEqual(bytes(f.output), b"{")
        self.control("STOP")
        self.assertEqual(f.process.returncode, -signal.SIGKILL)
        self.assertFalse(self.health()["worker_reap_pending"])

    def test_actual_crash_malformed_oversize_wrong_and_trailing(self):
        cases = {"CRASH":"WORKER_EXIT_FAILURE", "MALFORMED":"WORKER_RESPONSE_INVALID",
                 "OVERSIZE":"WORKER_FRAME_LIMIT", "WRONG_TICKET":"WORKER_RESPONSE_INVALID",
                 "TRAILING":"WORKER_RESPONSE_INVALID"}
        for mode, reason in cases.items():
            with self.subTest(mode=mode):
                self.make(mode=mode); g, f = self.dispatch(); event = self.await_event()
                self.assertEqual(event, {"status":"REJECTED","reason":reason})
                self.assertEqual(self.health()["work_usage"]["spent_steps"], 0)
                self.assertEqual(self.health()["work_usage"]["reserved_steps"], 0)
                self.assertIsNotNone(f.process.returncode)
                self.assertEqual(self.lab._host.work.inspect()["goals"][g]["state"], "FAILED")

    def test_context_revocation_ends_session_and_reaps(self):
        resolver = RGDContextResolver(CORE, local_alias="lab-robot", expected_source_root=ROOT, clock=self.clock)
        self.assertEqual(resolver.refresh()["reference_status"], "SOURCE_INTEGRITY_VERIFIED")
        self.make(mode="BLOCK", resolver=resolver); _, f = self.dispatch(); resolver.invalidate()
        with self.assertRaisesRegex(RuntimeLabError, "RUNTIME_CONTEXT_OR_WORK_FAULT"):
            self.tick()
        self.assertEqual(self.health()["state"], "FAULT")
        self.assertIsNotNone(f.process.returncode)
        self.assertEqual(self.health()["work_usage"]["reserved_steps"], 0)

    def test_clock_regression_revokes_and_reaps(self):
        self.make(mode="BLOCK"); _, f = self.dispatch()
        self.clock.value -= 1
        with self.assertRaisesRegex(RuntimeLabError, "RUNTIME_CLOCK_REGRESSION"):
            self.tick()
        self.assertEqual(self.health()["state"], "FAULT")
        self.assertIsNotNone(f.process.returncode)
        self.assertEqual(self.health()["work_usage"]["reserved_slots"], 0)

    def test_consent_denial_revokes_even_admitted_work(self):
        self.make(mode="BLOCK"); _, f = self.dispatch()
        self.assertEqual(self.offer(3, consent=False), "CONSENT_DENIED")
        self.assertEqual(self.health()["state"], "FAULT")
        self.assertIsNotNone(f.process.returncode)
        self.assertEqual(self.health()["work_usage"]["reserved_slots"], 0)

    def test_restart_has_no_old_flight_or_ticket(self):
        self.make(mode="BLOCK"); _, f = self.dispatch(); old_session = self.session
        self.control("STOP")
        self.make(mode="NORMAL"); _, new = self.dispatch()
        self.assertNotEqual(old_session["runtime_session"], self.session["runtime_session"])
        with self.assertRaises(WorkerProtocolError):
            validate_response(encode_frame(expected_response(f.request)), new.request)
        self.assertEqual(self.await_event()["status"], "COMPLETED")

    def test_spawn_failure_fails_closed_and_releases(self):
        g = self.admitted()
        with patch("rgd_cognition.worker_lab.subprocess.Popen", side_effect=OSError("PRIVATE_TEST_DETAIL")):
            with self.assertRaisesRegex(RuntimeLabError, "WORKER_LAUNCH_FAILED"):
                self.lab.dispatch(self.owners.operator, g)
        self.assertEqual(self.health()["state"], "FAULT")
        self.assertNotIn("PRIVATE_TEST_DETAIL", str(self.health()))
        self.assertEqual(self.health()["work_usage"]["reserved_slots"], 0)

    def test_failed_reap_retains_handle_and_requires_explicit_cleanup(self):
        self.make(mode="BLOCK"); _, f = self.dispatch()
        with patch.object(f.process, "wait", side_effect=subprocess.TimeoutExpired("fixed", .05)):
            self.control("STOP")
            self.assertEqual(self.health()["state"], "FAULT")
            self.assertTrue(self.health()["worker_reap_pending"])
            with self.assertRaisesRegex(RuntimeLabError, "WORKER_REAP_REQUIRED"):
                self.lab.start(self.owners.operator)
        self.lab.stop(self.owners.operator)
        self.assertEqual(self.health()["state"], "STOPPED")
        self.assertIsNotNone(f.process.returncode)
        self.assertFalse(self.health()["worker_reap_pending"])

    def test_result_integrity_failure_faults_without_publication(self):
        _, f = self.dispatch(); f.process.wait(timeout=2)
        with patch("rgd_cognition.worker_lab.validate_result_bundle", side_effect=ValueError("bad")):
            with self.assertRaisesRegex(RuntimeLabError, "WORKER_RESULT_INTEGRITY_FAILED"):
                self.await_event()
        self.assertEqual(self.health()["state"], "FAULT")
        self.assertIsNotNone(f.process.returncode)
        self.assertEqual(self.health()["counters"].get("worker_completed", 0), 0)

    def test_session_expired_before_dispatch_never_spawns(self):
        g = self.admitted(); self.clock.advance(3000)
        with patch("rgd_cognition.worker_lab.subprocess.Popen", side_effect=AssertionError("spawned")):
            with self.assertRaisesRegex(RuntimeLabError, "WORK_NOT_DISPATCHABLE"):
                self.lab.dispatch(self.owners.operator, g)
        self.assertEqual(self.health()["work_usage"]["reserved_slots"], 0)


if __name__ == "__main__":
    unittest.main()
