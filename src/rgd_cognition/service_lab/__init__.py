"""RUNTIME-01C synthetic service driver; no live source or new Work authority.

The explicit operator invocation pumps the unchanged WorkerLab continuously for
one finite session. OS confinement is supplied and tested separately by the
reviewed Linux service, never inferred from this Python API or its status file.
"""
from __future__ import annotations

from dataclasses import dataclass
import fcntl
import json
import os
from pathlib import Path
import signal
import stat
from time import monotonic_ns, sleep
from uuid import uuid4

from ..attention_c1_demo import fixture_sample
from ..core_b_adapter import Limits
from ..runtime_lab import RuntimeLabConfig, RuntimeLabOwners
from ..worker_lab import WorkerLab, WorkerLabConfig


PROFILE = "cog.service.lab.v0.1-candidate"
STATUS_LIMIT = 16384
MAX_DURATION_SECONDS = 8 * 60 * 60
INPUT_PERIOD_NS = 100_000_000
PUMP_PERIOD_NS = 10_000_000
STATUS_PERIOD_NS = 250_000_000
_HEALTH_KEYS = frozenset({
    "state", "fault", "runtime_session", "fixture_only", "scope", "life_id",
    "chronon_status", "worker_connected", "last_session_elapsed_ns", "may_actuate",
    "external_effects", "pending_input", "pending_control", "replay_entries",
    "input_high_water", "control_high_water", "replay_high_water", "counters",
    "work_usage", "worker_active", "worker_reap_pending", "worker_reason",
})


class ServiceLabError(ValueError):
    """Stable diagnostic only; never a filesystem path or exception payload."""


def _require(condition, reason):
    if not condition:
        raise ServiceLabError(reason)


def monotonic_millisecond_ns():
    """Actual monotonic clock at explicit 1 ms resolution, always rounded down.

    Existing C1/Core-B uses integer-ms half-open lifetimes. Flooring the actual
    clock avoids the existing conservative next-bucket deferral without adding
    time, sleeping to fabricate a timestamp, changing TTL or using a fixture
    clock. WorkerLab's independent wall deadline retains full monotonic precision.
    """
    return monotonic_ns() // 1_000_000 * 1_000_000


@dataclass(frozen=True)
class ServiceConfig:
    enabled: bool = False
    duration_seconds: int = 60

    def __post_init__(self):
        _require(type(self.enabled) is bool and type(self.duration_seconds) is int and
                 1 <= self.duration_seconds <= MAX_DURATION_SECONDS,
                 "INVALID_SERVICE_POLICY")


class StopSignal:
    """Signal handlers only set a flag; the owner loop performs Work shutdown."""
    def __init__(self):
        self.requested = False
        self._previous = {}

    def _receive(self, _signum, _frame):
        self.requested = True

    def __enter__(self):
        try:
            for signum in (signal.SIGTERM, signal.SIGINT):
                self._previous[signum] = signal.signal(signum, self._receive)
        except (ValueError, OSError):
            self.__exit__(None, None, None)
            raise ServiceLabError("SIGNAL_SETUP_FAILED") from None
        return self

    def __exit__(self, *_):
        for signum, previous in self._previous.items():
            signal.signal(signum, previous)
        self._previous.clear()


class PrivateStatus:
    """One ephemeral cached diagnostic, plus an advisory local singleton lock.

    The caller must provision a private owned 0700 directory with trusted parent
    directories (systemd RuntimeDirectory in the service profile). Directory FD
    operations and O_NOFOLLOW avoid following replaced status/lock symlinks.
    The lock is not a distributed lease or identity/authorization proof.
    """
    def __init__(self, directory, *, writer=False):
        self._dir = self._lock = None
        try:
            self._dir = os.open(os.fspath(directory), os.O_RDONLY | os.O_DIRECTORY |
                                os.O_NOFOLLOW | os.O_CLOEXEC)
            metadata = os.fstat(self._dir)
            _require(metadata.st_uid == os.geteuid() and
                     stat.S_IMODE(metadata.st_mode) == 0o700,
                     "PRIVATE_RUNTIME_DIRECTORY_REQUIRED")
            if writer:
                self._lock = os.open("service.lock", os.O_RDWR | os.O_CREAT |
                                     os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK,
                                     0o600, dir_fd=self._dir)
                self._check_file(self._lock)
                try:
                    fcntl.flock(self._lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    raise ServiceLabError("SERVICE_ALREADY_RUNNING") from None
        except ServiceLabError:
            self.close()
            raise
        except OSError:
            self.close()
            raise ServiceLabError("PRIVATE_RUNTIME_DIRECTORY_UNAVAILABLE") from None

    @staticmethod
    def _check_file(fd):
        metadata = os.fstat(fd)
        _require(stat.S_ISREG(metadata.st_mode) and metadata.st_uid == os.geteuid() and
                 stat.S_IMODE(metadata.st_mode) == 0o600 and metadata.st_nlink == 1,
                 "PRIVATE_RUNTIME_FILE_REQUIRED")

    def publish(self, status):
        _require(self._lock is not None, "STATUS_WRITER_REQUIRED")
        raw = encode_status(status)
        temporary = ".status-" + uuid4().hex
        fd = None
        try:
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                         os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, dir_fd=self._dir)
            self._check_file(fd)
            offset = 0
            while offset < len(raw):
                written = os.write(fd, raw[offset:])
                _require(written > 0, "STATUS_WRITE_FAILED")
                offset += written
            os.close(fd)
            fd = None
            os.replace(temporary, "status.json", src_dir_fd=self._dir, dst_dir_fd=self._dir)
        except OSError:
            raise ServiceLabError("STATUS_WRITE_FAILED") from None
        finally:
            if fd is not None:
                os.close(fd)
            try:
                os.unlink(temporary, dir_fd=self._dir)
            except FileNotFoundError:
                pass

    def read(self):
        fd = None
        try:
            fd = os.open("status.json", os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK,
                         dir_fd=self._dir)
            self._check_file(fd)
            raw = os.read(fd, STATUS_LIMIT + 1)
        except OSError:
            raise ServiceLabError("STATUS_UNAVAILABLE") from None
        finally:
            if fd is not None:
                os.close(fd)
        _require(0 < len(raw) <= STATUS_LIMIT, "STATUS_SIZE_INVALID")
        try:
            def pairs(items):
                out = {}
                for key, value in items:
                    _require(key not in out, "STATUS_INVALID")
                    out[key] = value
                return out
            value = json.loads(raw, object_pairs_hook=pairs)
            _require(encode_status(value) == raw, "STATUS_INVALID")
            return value
        except (ValueError, TypeError, RecursionError, UnicodeError):
            raise ServiceLabError("STATUS_INVALID") from None

    def close(self):
        for attribute in ("_lock", "_dir"):
            fd = getattr(self, attribute, None)
            if fd is not None:
                os.close(fd)
                setattr(self, attribute, None)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def encode_status(value):
    expected = {"profile", "pid", "cache_only", "liveness_verified", "fixture_only",
                "scope", "clock", "captured_monotonic_ns", "elapsed_ms", "duration_ms",
                "ticks", "generated_samples", "missed_input_slots", "stop_reason", "health"}
    _require(type(value) is dict and set(value) == expected and value["profile"] == PROFILE and
             value["cache_only"] is True and value["liveness_verified"] is False and
             value["fixture_only"] is True and value["scope"] == "SESSION_SCOPED" and
             value["clock"] == "REAL_MONOTONIC_FLOOR_MS", "STATUS_INVALID")
    for key in ("pid", "captured_monotonic_ns", "elapsed_ms", "duration_ms", "ticks",
                "generated_samples", "missed_input_slots"):
        _require(type(value[key]) is int and 0 <= value[key] <= 9223372036854775807,
                 "STATUS_INVALID")
    _require(value["stop_reason"] in {None, "DURATION_COMPLETE", "SIGNAL_STOP",
             "SERVICE_RUNTIME_FAILED", "SERVICE_CLEANUP_FAILED", "STATUS_WRITE_FAILED"},
             "STATUS_INVALID")
    health = value["health"]
    _require(type(health) is dict and set(health) <= _HEALTH_KEYS and
             health.get("fixture_only") is True and health.get("may_actuate") is False and
             health.get("external_effects") is False and health.get("life_id") is None and
             health.get("chronon_status") == "NOT_CONNECTED", "STATUS_INVALID")
    try:
        raw = json.dumps(value, allow_nan=False, ensure_ascii=True, sort_keys=True,
                         separators=(",", ":")).encode("ascii")
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise ServiceLabError("STATUS_INVALID") from None
    _require(len(raw) <= STATUS_LIMIT, "STATUS_SIZE_INVALID")
    return raw


class ServiceLoop:
    """One bounded foreground synthetic session, continuously owner-pumped.

    Configuration enables the fixed synthetic lab and its fixed worker. An
    ADMITTED goal is explicitly dispatched by this trusted supervisor; paused
    work is never resumed. A missed input slot is dropped, not caught up in a
    burst with invented receipts. No result payload or transcript is retained.
    """
    def __init__(self, schema_bytes, config=None):
        self.config = ServiceConfig() if config is None else config
        _require(type(self.config) is ServiceConfig, "INVALID_SERVICE_POLICY")
        _require(self.config.enabled, "SERVICE_DISABLED")
        self.owners = RuntimeLabOwners()
        self.lab = WorkerLab(schema_bytes, owners=self.owners,
            config=RuntimeLabConfig(enabled=True, work=Limits(enabled=True)),
            worker=WorkerLabConfig(enabled=True), clock_ns=monotonic_millisecond_ns)
        self.ticks = self.samples = self.missed = 0
        self._started = None
        self._last = None

    def _now(self):
        value = monotonic_ns()
        _require(type(value) is int and value >= 0 and
                 (self._last is None or value >= self._last), "SERVICE_CLOCK_FAILED")
        self._last = value
        return value

    def snapshot(self, reason=None):
        now = self._now()
        health = self.lab.health(self.owners.operator)
        _require(set(health) <= _HEALTH_KEYS, "UNREVIEWED_HEALTH_FIELDS")
        result = {"profile": PROFILE, "pid": os.getpid(), "cache_only": True,
            "liveness_verified": False, "fixture_only": True, "scope": "SESSION_SCOPED",
            "clock": "REAL_MONOTONIC_FLOOR_MS", "captured_monotonic_ns": now,
            "elapsed_ms": 0 if self._started is None else (now-self._started)//1_000_000,
            "duration_ms": self.config.duration_seconds*1000, "ticks": self.ticks,
            "generated_samples": self.samples, "missed_input_slots": self.missed,
            "stop_reason": reason, "health": health}
        encode_status(result)
        return result

    def run(self, sink, stop):
        """Return final cached status; errors still stop/reap before propagating.

        `sink` is the trusted local diagnostic writer; `stop` is a StopSignal.
        Its flag is checked every loop, with no external command/transport API.
        """
        _require(self._started is None, "SERVICE_SESSION_ALREADY_USED")
        _require(type(stop) is StopSignal and callable(sink), "INVALID_SERVICE_DRIVER")
        self._started = self._now()
        deadline = self._started + self.config.duration_seconds*1_000_000_000
        next_input, next_status = self._started, self._started
        sequence = 0
        reason, failed, final = "SERVICE_RUNTIME_FAILED", False, None
        try:
            session = self.lab.start(self.owners.operator)
            self.lab.request_control(self.owners.operator, "RESOURCE_NORMAL")
            self.lab.tick(self.owners.operator)
            self.ticks += 1
            while True:
                now = self._now()
                if stop.requested:
                    reason = "SIGNAL_STOP"
                    break
                if now >= deadline:
                    reason = "DURATION_COMPLETE"
                    break
                if now >= next_input:
                    skipped = (now-next_input)//INPUT_PERIOD_NS
                    sequence += skipped
                    self.missed += skipped
                    sample = fixture_sample(sequence, 0.6 if (sequence//3) % 2 else 0.0)
                    sample["session_id"] = session["source_session"]
                    offered = self.lab.offer(self.owners.synthetic_source,
                        runtime_session=session["runtime_session"], sample=sample, consent=True)
                    _require(offered in {"QUEUED", "BACKPRESSURE"}, "SYNTHETIC_INPUT_REJECTED")
                    self.samples += 1
                    sequence += 1
                    next_input += (skipped+1)*INPUT_PERIOD_NS
                self.lab.tick(self.owners.operator)
                self.ticks += 1
                if not stop.requested and self._now() < deadline:
                    admitted = [goal for goal in self.lab.eligible(self.owners.operator)
                                if goal["state"] == "ADMITTED"]
                    if admitted:
                        self.lab.dispatch(self.owners.operator, admitted[0]["goal_id"])
                now = self._now()
                if now >= next_status:
                    try:
                        sink(self.snapshot())
                    except Exception:
                        reason = "STATUS_WRITE_FAILED"
                        raise
                    next_status = now + STATUS_PERIOD_NS
                remaining = min(PUMP_PERIOD_NS, next_input-now, deadline-now)
                if remaining > 0 and not stop.requested:
                    sleep(remaining/1_000_000_000)
        except Exception:
            failed = True
        finally:
            try:
                health = self.lab.stop(self.owners.operator)
                if health["state"] != "STOPPED" or health["worker_reap_pending"]:
                    reason, failed = "SERVICE_CLEANUP_FAILED", True
                final = self.snapshot(reason)
            except Exception:
                reason = "SERVICE_CLEANUP_FAILED"
                failed = True
            if final is not None:
                try:
                    sink(final)
                except Exception:
                    reason, failed = "STATUS_WRITE_FAILED", True
            if failed:
                raise ServiceLabError(reason) from None
        return final


def read_core_b_schema(checkout):
    try:
        path = Path(checkout) / "contracts/kernel/v0.1.0/schemas/kernel-goal-effect.schema.json"
        with path.open("rb") as handle:
            raw = handle.read(65537)
        _require(0 < len(raw) <= 65536, "SCHEMA_SIZE_INVALID")
        return raw  # The unchanged CoreBSchema checks the exact reviewed Git blob.
    except OSError:
        raise ServiceLabError("PINNED_SCHEMA_UNAVAILABLE") from None
