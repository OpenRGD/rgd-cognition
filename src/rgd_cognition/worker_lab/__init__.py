"""RUNTIME-01B: explicit synthetic-only subprocess delegation over RuntimeLab.

Caller-pumped; a separate fixed trusted fixture, not an OS sandbox or LLM.
The sole Work owner remains KernelSession. No public IPC, shell or plugin API.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import os
from pathlib import Path
import subprocess
import sys
from time import monotonic_ns
from uuid import uuid4

from ..core_b_adapter import digest, validate_result_bundle
from ..runtime_lab import RuntimeLab, RuntimeLabError, _require
from .fixture import (MAX_FRAME, MODES, PROFILE, TASK, encode_frame,
                                     validate_request, validate_response, WorkerProtocolError)


@dataclass(frozen=True)
class WorkerLabConfig:
    enabled: bool = False
    wall_ms: int = 750
    terminate_grace_ms: int = 100
    fixture_mode: str = "NORMAL"

    def __post_init__(self):
        _require(type(self.enabled) is bool and type(self.wall_ms) is int and
                 1 <= self.wall_ms <= 1000 and type(self.terminate_grace_ms) is int and
                 10 <= self.terminate_grace_ms <= 250 and type(self.fixture_mode) is str and
                 self.fixture_mode in MODES, "INVALID_WORKER_POLICY")


@dataclass
class _Flight:
    process: subprocess.Popen
    ticket: dict
    request: dict
    session_deadline_ns: int
    real_deadline_ns: int
    output: bytearray
    eof: bool = False


class WorkerLab(RuntimeLab):
    """Opt-in subclass; 01A and its no-worker behavior remain unchanged.

    Private, version-bound read access to the actual Work job is used solely to
    obtain its immutable task/evidence and remaining allowance. It is never
    mutated directly. All admission/start/finish/termination remains Work-owned.
    """
    def __init__(self, *args, worker=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._worker_config = WorkerLabConfig() if worker is None else worker
        _require(type(self._worker_config) is WorkerLabConfig, "INVALID_WORKER_POLICY")
        self._flight = None
        self._unreaped = None
        self._last_worker_reason = None

    def start(self, channel):
        self._operator(channel)
        _require(self._flight is None and self._unreaped is None, "WORKER_REAP_REQUIRED")
        self._last_worker_reason = None
        return super().start(channel)

    def _read_job(self, goal_id):
        # Exact pinned local Work API companion; serialized supervisor thread
        # plus Work lock. No job object escapes; no private state is modified.
        work = self._host.work
        with work._lock:
            job = work._jobs.get(goal_id)
            _require(job is not None, "UNKNOWN_WORK_GOAL")
            return deepcopy(job.goal), job.state, job.generation, job.remaining_wall, job.remaining_steps

    def eligible(self, channel):
        self._operator(channel)
        _require(self._state in self._ACTIVE, "RUNTIME_NOT_ACTIVE")
        report = self._snapshot()
        if (not self._worker_config.enabled or self._flight is not None or self._unreaped is not None or
                self._controls or report["user_paused"] or report["resource"] != "NORMAL"):
            return []
        result = []
        for goal_id, item in report["goals"].items():
            if item["state"] in {"ADMITTED", "PAUSED"}:
                goal, state, _, wall, steps = self._read_job(goal_id)
                if (goal["task_ref"] == TASK and goal["provenance"]["class"] == "SYNTHETIC" and wall and steps):
                    result.append({"goal_id": goal_id, "state": state})
        return result

    @staticmethod
    def _close_pipes(p):
        for pipe in (p.stdin, p.stdout):
            if pipe is not None:
                try:
                    pipe.close()
                except OSError:
                    pass

    def _reap(self, p):
        """Bounded TERM then KILL and wait. Fixed worker has no children.

        No process-tree/hostile-code isolation guarantee. If reap fails, retain
        handle and refuse new sessions until explicit stop retries cleanup.
        """
        grace = self._worker_config.terminate_grace_ms / 1000
        try:
            if p.poll() is None:
                try:
                    p.terminate()
                except ProcessLookupError:
                    pass
                try:
                    p.wait(timeout=grace)
                except subprocess.TimeoutExpired:
                    try:
                        p.kill()
                    except ProcessLookupError:
                        pass
                    p.wait(timeout=grace)
            else:
                p.wait(timeout=grace)
            self._count("worker_reaped")
            return True
        except (OSError, subprocess.TimeoutExpired):
            self._unreaped = p
            self._count("worker_reap_failed")
            return False
        finally:
            self._close_pipes(p)

    def _end(self, fault=None):
        # Detach and revoke Work before touching process cancellation.
        flight, self._flight = self._flight, None
        pending, self._unreaped = self._unreaped, None
        super()._end(fault)
        for process in (flight.process if flight else None, pending):
            if process is not None:
                if flight is not None:
                    self._count("worker_cancelled")
                    self._last_worker_reason = "SESSION_ENDED"
                if not self._reap(process):
                    self._state, self._fault = "FAULT", "WORKER_REAP_FAILED"

    def offer(self, channel, **kwargs):
        result = super().offer(channel, **kwargs)
        # This lab treats consent denial as whole-session revocation once a
        # worker-capable host is enabled; no retained goal can be dispatched.
        if result == "CONSENT_DENIED" and self._worker_config.enabled:
            self._end("RUNTIME_CONSENT_DENIED")
        return result

    def _retire(self, reason, *, fail_running=False):
        flight, self._flight = self._flight, None
        if flight is None:
            return None
        self._last_worker_reason = reason
        self._count("worker_rejected" if fail_running else "worker_cancelled")
        # No result accepted after detachment. Work may already have cancelled
        # the goal by expiry or paused it through the operator barrier.
        work_failure = False
        if fail_running and self._host is not None:
            try:
                w = self._host.work
                view = w.inspect()["goals"].get(flight.ticket["goal_id"])
                if view and view["state"] == "RUNNING" and view["generation"] == flight.ticket["task_generation"]:
                    w.move(self._host.owners.work, flight.ticket["goal_id"], "FAILED",
                           key=digest({"worker-failed": flight.request["request_id"]}))
            except Exception:
                work_failure = True
        if not self._reap(flight.process):
            self._fail("WORKER_REAP_FAILED")
        if work_failure:
            self._fail("WORKER_TERMINAL_TRANSITION_FAILED")
        if self._host is not None:
            self._snapshot()
        return {"status": "REJECTED" if fail_running else "CANCELLED", "reason": reason}

    def dispatch(self, channel, goal_id, *, resume=False):
        self._operator(channel)
        _require(self._worker_config.enabled, "WORKER_DISABLED")
        _require(sys.platform.startswith("linux"), "WORKER_PLATFORM_UNSUPPORTED")
        _require(self._state in self._ACTIVE and self._flight is None and self._unreaped is None,
                 "WORKER_NOT_AVAILABLE")
        _require(type(goal_id) is str and type(resume) is bool, "INVALID_DISPATCH")
        report = self._snapshot()
        _require(not self._controls and not report["user_paused"] and report["resource"] == "NORMAL",
                 "WORK_CONTROL_BLOCKED")
        goal, state, generation, wall, steps = self._read_job(goal_id)
        _require(state == ("PAUSED" if resume else "ADMITTED") and wall > 0 and steps > 0 and
                 goal["task_ref"] == TASK and goal["provenance"]["class"] == "SYNTHETIC",
                 "WORK_NOT_DISPATCHABLE")
        now = self._checked_now()
        lifetime = goal["lifetime"]
        end = (lifetime["created_ms"] + lifetime["ttl_ms"]) * 1_000_000
        # Work wall accounting is millisecond-based; conservatively use an
        # absolute floor bucket rather than renewing the last fractional ms.
        cap = min(end, (now // 1_000_000 + wall) * 1_000_000,
                  now + self._worker_config.wall_ms * 1_000_000)
        _require(cap > now, "WORK_DEADLINE_EXPIRED")
        work, owner = self._host.work, self._host.owners.work
        try:
            work.move(owner, goal_id, "RUNNING", key=digest({"worker-start": goal_id, "generation": generation}))
            ticket = work.ticket(owner, goal_id)
        except Exception:
            self._fail("WORKER_START_TRANSITION_FAILED")
        p = None
        try:
            req = validate_request({"profile": PROFILE, "task_ref": TASK,
                "request_id": digest({"ticket": ticket, "dispatch": uuid4().hex}),
                "ticket_digest": digest(ticket), "evidence_refs": goal["provenance"]["evidence_refs"],
                "fixture_only": True})
            raw = encode_frame(req)
            remaining = cap - self._checked_now()
            _require(remaining > 0, "WORK_DEADLINE_EXPIRED")
            deadline = monotonic_ns() + remaining
            # Fixed reviewed path and fixed enum, never caller/model argv. No
            # shell, inherited credentials, arbitrary PYTHONPATH or open FDs.
            script = Path(__file__).with_name("fixture.py").resolve(strict=True)
            p = subprocess.Popen([sys.executable, "-I", "-B", str(script), self._worker_config.fixture_mode],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                cwd="/", env={"LANG": "C", "LC_ALL": "C"}, close_fds=True, start_new_session=True)
            self._flight = _Flight(p, ticket, deepcopy(req), cap, deadline, bytearray())
            os.set_blocking(p.stdin.fileno(), False)
            os.set_blocking(p.stdout.fileno(), False)
            # <= PIPE_BUF on target Linux, one write, no blocking communication.
            _require(os.write(p.stdin.fileno(), raw) == len(raw), "WORKER_REQUEST_WRITE_FAILED")
            p.stdin.close()
        except Exception:
            if self._flight is not None:
                return self._retire("WORKER_LAUNCH_FAILED", fail_running=True)
            if p is not None and not self._reap(p):
                self._fail("WORKER_REAP_FAILED")
            self._fail("WORKER_LAUNCH_FAILED")
        self._count("worker_dispatched")
        self._snapshot()
        return {"status": "DISPATCHED", "goal_id": goal_id, "request_id": req["request_id"]}

    def _current_flight(self, flight):
        report = self._snapshot()
        item = report["goals"].get(flight.ticket["goal_id"])
        return (not report["user_paused"] and report["resource"] == "NORMAL" and item is not None and
                item["state"] == "RUNNING" and item["generation"] == flight.ticket["task_generation"])

    def _advance_worker(self):
        f = self._flight
        if f is None:
            return None
        if not self._current_flight(f):
            return self._retire("WORK_REVOKED")
        if self._checked_now() >= f.session_deadline_ns or monotonic_ns() >= f.real_deadline_ns:
            return self._retire("WORKER_DEADLINE", fail_running=True)
        if self._controls:
            return None  # no result publication ahead of pending operator controls
        if not f.eof:
            try:
                raw = os.read(f.process.stdout.fileno(), MAX_FRAME + 1 - len(f.output))
                f.output.extend(raw)
                f.eof = not raw
            except BlockingIOError:
                pass
            except OSError:
                return self._retire("WORKER_READ_FAILED", fail_running=True)
            if len(f.output) > MAX_FRAME:
                return self._retire("WORKER_FRAME_LIMIT", fail_running=True)
        exit_code = f.process.poll()
        if exit_code is None or not f.eof:
            return None
        if exit_code != 0:
            return self._retire("WORKER_EXIT_FAILURE", fail_running=True)
        try:
            response = validate_response(bytes(f.output), f.request)
        except WorkerProtocolError:
            return self._retire("WORKER_RESPONSE_INVALID", fail_running=True)
        # Check both clocks and exact current Work ticket immediately before
        # publication; never reuse a cached finish or a worker-supplied ticket.
        if not self._current_flight(f):
            return self._retire("WORK_REVOKED")
        if self._checked_now() >= f.session_deadline_ns or monotonic_ns() >= f.real_deadline_ns:
            return self._retire("WORKER_DEADLINE", fail_running=True)
        work, owner = self._host.work, self._host.owners.work
        try:
            _require(work.ticket(owner, f.ticket["goal_id"]) == f.ticket, "STALE_WORKER_TICKET")
            if self._checked_now() >= f.session_deadline_ns or monotonic_ns() >= f.real_deadline_ns:
                return self._retire("WORKER_DEADLINE", fail_running=True)
            # Work validates current generation/context/expiry inside its lock.
            result = work.finish(owner, f.ticket, code=response["code"],
                evidence_refs=response["evidence_refs"], key=digest({"worker-finish": f.request["request_id"]}))
        except RuntimeLabError:
            if self._host is None:
                raise
            return self._retire("WORKER_RESULT_REJECTED", fail_running=True)
        except Exception:
            return self._retire("WORKER_RESULT_REJECTED", fail_running=True)
        try:
            validate_result_bundle(self._host.schema, result)
        except Exception:
            # Work may already have applied the terminal transition. Do not
            # publish a contradictory bundle or continue an inconsistent session.
            self._fail("WORKER_RESULT_INTEGRITY_FAILED")
        self._flight = None
        if not self._reap(f.process):
            self._fail("WORKER_REAP_FAILED")
        self._count("worker_completed")
        self._last_worker_reason = "FIXTURE_INQUIRY_UNVERIFIED"
        self._snapshot()
        return {"status": "COMPLETED", "reason": self._last_worker_reason, "result": result}

    def tick(self, channel):
        # First run the actual 01A priority control/heartbeat. Even a ready
        # result cannot win a race with an already queued pause or stop.
        report = super().tick(channel)
        if self._host is not None:
            event = self._advance_worker()
            if event is not None:
                report["worker"] = event
            report["status"] = self._state
        return report

    def health(self, channel):
        report = super().health(channel)
        report.update(worker_connected=self._worker_config.enabled and self._host is not None,
                      worker_active=self._flight is not None, worker_reap_pending=self._unreaped is not None,
                      worker_reason=self._last_worker_reason)
        return report
