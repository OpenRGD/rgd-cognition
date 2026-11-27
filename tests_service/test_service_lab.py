"""Actual finite service pumping, private diagnostics and POSIX signal shutdown.

The Linux/systemd privilege boundary is exercised by the separate disposable
host rehearsal. These tests never claim that ordinary user processes are OS
isolated, and do not change any existing Foundation/Runtime code or tests.
"""
from copy import deepcopy
import json
import os
from pathlib import Path
import signal
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from rgd_cognition import service_lab as service


CORE_B = Path(os.environ["CORE_B_CHECKOUT"])
RAW = service.read_core_b_schema(CORE_B)


class ServicePolicyTests(unittest.TestCase):
    def test_explicit_enable_and_bounded_integer_duration(self):
        with self.assertRaisesRegex(service.ServiceLabError, "SERVICE_DISABLED"):
            service.ServiceLoop(RAW)
        for duration in (False, 0, -1, 28801, 1.0, "1"):
            with self.subTest(duration=duration), self.assertRaises(service.ServiceLabError):
                service.ServiceConfig(enabled=True, duration_seconds=duration)
        self.assertEqual(service.ServiceConfig(True, 28800).duration_seconds, 28800)

    def test_real_clock_floor_never_creates_time_and_preserves_order(self):
        source = [0, 999999, 1000000, 1000001, 1999999, 2000000]
        with patch.object(service, "monotonic_ns", side_effect=source):
            result = [service.monotonic_millisecond_ns() for _ in source]
        self.assertEqual(result, [0, 0, 1000000, 1000000, 1000000, 2000000])
        self.assertTrue(all(0 <= raw-rounded < 1000000 for raw, rounded in zip(source, result)))
        self.assertEqual(result, sorted(result))

    def test_full_precision_service_clock_refuses_regression(self):
        loop = service.ServiceLoop(RAW, service.ServiceConfig(True, 1))
        with patch.object(service, "monotonic_ns", side_effect=[2000001, 2000000]):
            self.assertEqual(loop._now(), 2000001)
            with self.assertRaisesRegex(service.ServiceLabError, "SERVICE_CLOCK_FAILED"):
                loop._now()

    def test_signal_handler_only_sets_flag_and_restores_handlers(self):
        before = {s: signal.getsignal(s) for s in (signal.SIGINT, signal.SIGTERM)}
        with service.StopSignal() as stop:
            stop._receive(signal.SIGTERM, None)
            self.assertTrue(stop.requested)
        self.assertEqual(before, {s: signal.getsignal(s) for s in before})


class PrivateStatusTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.root.chmod(0o700)
        self.loop = service.ServiceLoop(RAW, service.ServiceConfig(True, 1))

    def tearDown(self):
        self.directory.cleanup()

    def test_atomic_private_cached_status_and_single_writer(self):
        with service.PrivateStatus(self.root, writer=True) as out:
            with self.assertRaisesRegex(service.ServiceLabError, "SERVICE_ALREADY_RUNNING"):
                service.PrivateStatus(self.root, writer=True)
            for _ in range(2):
                out.publish(self.loop.snapshot())
                with service.PrivateStatus(self.root) as reader:
                    report = reader.read()
                self.assertTrue(report["cache_only"])
                self.assertFalse(report["liveness_verified"])
                self.assertEqual(report["health"]["state"], "STOPPED")
                self.assertEqual(stat.S_IMODE((self.root/"status.json").stat().st_mode), 0o600)
                self.assertLess((self.root/"status.json").stat().st_size, service.STATUS_LIMIT)
                self.assertEqual({p.name for p in self.root.iterdir()}, {"status.json", "service.lock"})
        with service.PrivateStatus(self.root, writer=True):
            pass

    def test_shared_or_symlink_directory_is_refused(self):
        self.root.chmod(0o755)
        with self.assertRaisesRegex(service.ServiceLabError, "PRIVATE_RUNTIME_DIRECTORY_REQUIRED"):
            service.PrivateStatus(self.root)
        self.root.chmod(0o700)
        link = self.root/"alias"
        link.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(service.ServiceLabError):
            service.PrivateStatus(link)

    def test_symlink_lock_is_not_opened(self):
        target = self.root/"target"
        target.write_text("unchanged")
        (self.root/"service.lock").symlink_to(target)
        with self.assertRaises(service.ServiceLabError):
            service.PrivateStatus(self.root, writer=True)
        self.assertEqual(target.read_text(), "unchanged")

    def test_special_status_and_lock_files_are_refused_without_blocking(self):
        os.mkfifo(self.root/"status.json", 0o600)
        with service.PrivateStatus(self.root) as reader:
            with self.assertRaisesRegex(service.ServiceLabError, "PRIVATE_RUNTIME_FILE_REQUIRED"):
                reader.read()
        os.mkfifo(self.root/"service.lock", 0o600)
        with self.assertRaisesRegex(service.ServiceLabError, "PRIVATE_RUNTIME_FILE_REQUIRED"):
            service.PrivateStatus(self.root, writer=True)

    def test_symlink_status_read_is_refused_and_write_never_follows_it(self):
        target = self.root/"target"
        target.write_text("unchanged")
        (self.root/"status.json").symlink_to(target)
        with service.PrivateStatus(self.root, writer=True) as out:
            with self.assertRaises(service.ServiceLabError):
                out.read()
            out.publish(self.loop.snapshot())
            self.assertEqual(target.read_text(), "unchanged")
            self.assertFalse((self.root/"status.json").is_symlink())

    def test_reader_rejects_size_noncanonical_and_authority_tampering(self):
        with service.PrivateStatus(self.root, writer=True) as out:
            report = self.loop.snapshot()
            for raw in (b"x"*(service.STATUS_LIMIT+1), b'{"x":1,"x":2}',
                        json.dumps(report, indent=2).encode()):
                (self.root/"status.json").write_bytes(raw)
                (self.root/"status.json").chmod(0o600)
                with self.assertRaises(service.ServiceLabError):
                    out.read()
            for update in ({"liveness_verified": True}, {"fixture_only": False},
                           {"authority": "granted"}):
                value = {**report, **update}
                with self.assertRaises(service.ServiceLabError):
                    out.publish(value)
            value = deepcopy(report)
            value["health"]["may_actuate"] = True
            with self.assertRaises(service.ServiceLabError):
                out.publish(value)

    def test_failed_atomic_write_does_not_replace_prior_status(self):
        with service.PrivateStatus(self.root, writer=True) as out:
            out.publish(self.loop.snapshot())
            before = (self.root/"status.json").read_bytes()
            with patch.object(service.os, "write", side_effect=OSError("PRIVATE_TEST_DETAIL")):
                with self.assertRaisesRegex(service.ServiceLabError, "^STATUS_WRITE_FAILED$"):
                    out.publish(self.loop.snapshot())
            self.assertEqual((self.root/"status.json").read_bytes(), before)
            self.assertFalse(any(p.name.startswith(".status-") for p in self.root.iterdir()))


@unittest.skipUnless(sys.platform.startswith("linux"), "Linux fixture worker and signals")
class ActualLoopTests(unittest.TestCase):
    def test_real_monotonic_loop_executes_original_worker_and_stops_once(self):
        loop = service.ServiceLoop(RAW, service.ServiceConfig(True, 1))
        reports = []
        result = loop.run(reports.append, service.StopSignal())
        self.assertEqual(result["stop_reason"], "DURATION_COMPLETE")
        self.assertGreaterEqual(result["elapsed_ms"], 1000)
        self.assertGreaterEqual(result["generated_samples"], 5)
        self.assertGreater(result["ticks"], result["generated_samples"])
        self.assertGreaterEqual(result["health"]["counters"].get("worker_completed", 0), 1)
        self.assertGreaterEqual(result["health"]["work_usage"]["spent_wall_ms"], 1)
        self.assertEqual(result["health"]["work_usage"]["reserved_slots"], 0)
        self.assertFalse(result["health"]["worker_active"])
        self.assertFalse(result["health"]["worker_reap_pending"])
        self.assertEqual(result["health"]["state"], "STOPPED")
        self.assertEqual(len({r["health"]["runtime_session"] for r in reports}), 1)
        self.assertNotIn("result", result)
        with self.assertRaisesRegex(service.ServiceLabError, "SERVICE_SESSION_ALREADY_USED"):
            loop.run(reports.append, service.StopSignal())

    def test_stop_already_requested_does_not_dispatch_or_roll_session(self):
        loop = service.ServiceLoop(RAW, service.ServiceConfig(True, 1))
        stop = service.StopSignal()
        stop.requested = True
        result = loop.run(lambda _: None, stop)
        self.assertEqual(result["stop_reason"], "SIGNAL_STOP")
        self.assertEqual(result["generated_samples"], 0)
        self.assertEqual(result["health"]["work_usage"]["spent_steps"], 0)
        self.assertEqual(result["health"]["state"], "STOPPED")

    def test_status_sink_failure_stops_session_and_redacts_error(self):
        loop = service.ServiceLoop(RAW, service.ServiceConfig(True, 1))
        def fail(_):
            raise OSError("PRIVATE_TEST_DETAIL")
        with self.assertRaisesRegex(service.ServiceLabError, "^STATUS_WRITE_FAILED$"):
            loop.run(fail, service.StopSignal())
        health = loop.lab.health(loop.owners.operator)
        self.assertEqual(health["state"], "STOPPED")
        self.assertEqual(health["work_usage"]["reserved_slots"], 0)

    def test_missing_opt_in_does_not_start_or_create_status(self):
        with tempfile.TemporaryDirectory() as directory:
            command = [sys.executable, "-m", "rgd_cognition.service_lab", "run",
                       "--core-b-checkout", str(CORE_B), "--runtime-dir", directory]
            result = subprocess.run(command, capture_output=True, text=True, timeout=5)
            self.assertEqual(result.returncode, 1)
            self.assertEqual(json.loads(result.stderr)["error"], "SERVICE_DISABLED")
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_real_sigterm_stops_and_reaps_fixed_term_ignoring_worker(self):
        # Test-only finite worker mode through a trusted in-process patch. The
        # production CLI has no mode/executable/task option and remains NORMAL.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            root.chmod(0o700)
            marker = root/"test-child.json"
            script = "\n".join([
                "import json",
                "from pathlib import Path",
                "from rgd_cognition import service_lab as s",
                "from rgd_cognition import worker_lab as w",
                "from rgd_cognition.worker_lab import WorkerLabConfig",
                "from rgd_cognition.service_lab.__main__ import main",
                "s.WorkerLabConfig = lambda **kwargs: WorkerLabConfig(enabled=True, wall_ms=1000, terminate_grace_ms=50, fixture_mode='IGNORE_TERM')",
                f"marker = Path({str(marker)!r})",
                "original, children = w.subprocess.Popen, []",
                "def track(*args, **kwargs):",
                "    child = original(*args, **kwargs)",
                "    children.append(child)",
                "    marker.write_text(json.dumps({'started': [p.pid for p in children]}))",
                "    return child",
                "w.subprocess.Popen = track",
                "code = main()",
                "marker.write_text(json.dumps({'finished': [{'pid': p.pid, 'returncode': p.returncode} for p in children]}))",
                "raise SystemExit(code)",
            ])
            proc = subprocess.Popen([sys.executable, "-c", script, "run", "--enable-synthetic-lab",
                "--core-b-checkout", str(CORE_B), "--runtime-dir", directory,
                "--duration-seconds", "60"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            children = []
            try:
                deadline = time.monotonic()+6
                report = None
                while time.monotonic() < deadline and proc.poll() is None:
                    try:
                        report = json.loads((root/"status.json").read_bytes())
                    except (FileNotFoundError, json.JSONDecodeError):
                        pass
                    if report and report["health"]["worker_active"]:
                        try:
                            children = json.loads(marker.read_text()).get("started", [])
                        except (FileNotFoundError, json.JSONDecodeError):
                            pass
                        if children:
                            break
                    time.sleep(.01)
                self.assertTrue(children, "actual supervised fixture child was not observed")
                time.sleep(.05)  # allow finite fixture to install its SIGTERM handler
                proc.send_signal(signal.SIGTERM)
                stdout, stderr = proc.communicate(timeout=5)
                self.assertEqual(proc.returncode, 0, stderr)
                final = json.loads(stdout)
                self.assertEqual(final["stop_reason"], "SIGNAL_STOP")
                self.assertEqual(final["health"]["state"], "STOPPED")
                self.assertFalse(final["health"]["worker_reap_pending"])
                self.assertFalse(final["liveness_verified"])
                self.assertEqual(final["health"]["work_usage"]["reserved_slots"], 0)
                self.assertGreaterEqual(final["health"]["counters"].get("worker_reaped", 0), 1)
                ended = json.loads(marker.read_text())["finished"]
                self.assertEqual([p["pid"] for p in ended], children)
                self.assertTrue(all(p["returncode"] == -signal.SIGKILL for p in ended))
            finally:
                if proc.poll() is None:
                    proc.kill()
                    proc.communicate(timeout=5)
                for child in children:
                    try:
                        os.kill(child, signal.SIGKILL)
                    except ProcessLookupError:
                        pass


if __name__ == "__main__":
    unittest.main()
