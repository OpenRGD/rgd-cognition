"""RUNTIME-01A: bounded, serialized synthetic-only supervisor (not a daemon).

This local lab owns no hardware, transport, provider or new goal authority.
One actual CoreBAttentionHost/KernelSession owns all cognitive admissions.
The caller drives tick(); no background threads, worker processes or OS sandbox.
"""
from __future__ import annotations

from collections import Counter, deque
from dataclasses import dataclass, field
from copy import deepcopy
from threading import current_thread
from time import monotonic_ns
from uuid import uuid4

from .attention_c1 import AttentionPolicy, SourceBinding, _validate, _digest
from .attention_c1_demo import fixture_binding, fixture_sample, FixtureClock
from .context import context_slice
from .contracts import encode
from .core_b_adapter import BridgeError, Limits
from .core_b_c1 import CoreBAttentionHost
from .rgd_context import RGDContextResolver


class RuntimeLabError(ValueError):
    """Stable error reason, never a source payload or exception text."""


def _require(condition, code):
    if not condition:
        raise RuntimeLabError(code)


@dataclass(frozen=True)
class RuntimeLabConfig:
    enabled: bool = False
    input_capacity: int = 64
    control_capacity: int = 8
    replay_capacity: int = 256
    max_session_ms: int = 86_400_000
    attention: AttentionPolicy = field(default_factory=AttentionPolicy)
    work: Limits = field(default_factory=Limits)

    def __post_init__(self):
        _require(type(self.enabled) is bool, "INVALID_RUNTIME_POLICY")
        for value, lo, hi in ((self.input_capacity, 1, 64),
                              (self.control_capacity, 1, 8),
                              (self.replay_capacity, 1, 4096),
                              (self.max_session_ms, 1, 86_400_000)):
            _require(type(value) is int and lo <= value <= hi, "INVALID_RUNTIME_POLICY")
        _require(type(self.attention) is AttentionPolicy and type(self.work) is Limits,
                 "INVALID_RUNTIME_POLICY")


class RuntimeLabOwners:
    """Opaque local fixture capabilities, not remote credentials or a sandbox."""
    def __init__(self):
        self.operator, self.synthetic_source = object(), object()


@dataclass(frozen=True)
class _Input:
    record: dict
    receipt_ns: int
    deadline_ns: int


class RuntimeLab:
    """Caller-pumped, one-thread supervisor. No providers execute in 01A.

    Explicit restart produces a new source and runtime session. Accepted input
    sequence/monotonic high-water survives expiry/pressure throughout a session;
    no LRU eviction can turn an old sample into a new receipt. Only the existing
    Work owner decides admission. This is a local fixture boundary, not network
    authentication or hostile Python isolation.
    """
    _CONTROLS = frozenset({"PAUSE", "RELEASE", "STOP", "RESOURCE_NORMAL",
                           "RESOURCE_LOW", "RESOURCE_UNKNOWN"})
    _ACTIVE = frozenset({"READY_LAB", "DEGRADED", "PAUSED"})

    def __init__(self, schema_bytes: bytes, *, owners: RuntimeLabOwners,
                 config: RuntimeLabConfig | None = None, clock_ns=monotonic_ns,
                 resolver: RGDContextResolver | None = None):
        _require(type(owners) is RuntimeLabOwners and type(schema_bytes) is bytes and
                 0 < len(schema_bytes) <= 65536 and callable(clock_ns), "INVALID_RUNTIME_CONFIG")
        _require(resolver is None or type(resolver) is RGDContextResolver, "INVALID_RESOLVER")
        self._config = RuntimeLabConfig() if config is None else config
        _require(type(self._config) is RuntimeLabConfig, "INVALID_RUNTIME_CONFIG")
        self._owners, self._schema, self._clock, self._resolver = owners, schema_bytes, clock_ns, resolver
        self._thread = current_thread()
        self._host = None
        self._state, self._fault = "STOPPED", None
        self._origin = self._last_raw = None
        self._binding = None
        self._session = None
        self._inputs, self._controls = deque(), deque()
        self._seen = {}
        self._last_seq = self._last_source_ns = None
        self._counts = Counter()
        self._last_work = None
        self._max_input = self._max_control = self._max_seen = 0

    def _owner_thread(self):
        _require(current_thread() is self._thread, "WRONG_SUPERVISOR_THREAD")

    def _operator(self, channel):
        self._owner_thread()
        _require(channel is self._owners.operator, "UNAUTHORIZED_OPERATOR")

    def _count(self, key, amount=1):
        self._counts[key] = min(self._counts[key] + amount, 9007199254740991)

    def _raw_now(self):
        try:
            value = self._clock()
        except Exception:
            raise BridgeError("RUNTIME_CLOCK_FAILURE") from None
        if type(value) is not int or not 0 <= value <= 9223372036854775807:
            raise BridgeError("RUNTIME_CLOCK_FAILURE")
        return value

    def _now(self):
        raw = self._raw_now()
        if self._last_raw is None or raw < self._last_raw or raw < self._origin:
            raise BridgeError("RUNTIME_CLOCK_REGRESSION")
        self._last_raw = raw
        relative = raw - self._origin
        if relative >= self._config.max_session_ms * 1_000_000:
            raise BridgeError("RUNTIME_SESSION_LIMIT")
        return relative

    def _purge(self):
        self._inputs.clear()
        self._controls.clear()
        self._seen.clear()
        self._binding = None
        self._last_seq = self._last_source_ns = None

    def _end(self, fault=None):
        # No worker exists. Detach first; never resurrect an old session on error.
        self._state = "STOPPING"
        host, self._host = self._host, None
        self._purge()
        self._last_work = None
        if host is not None:
            try:
                self._last_work = deepcopy(host.close()["usage"])
            except Exception:
                fault = fault or "RUNTIME_CLOSE_FAILED"
        self._fault = fault
        self._state = "FAULT" if fault else "STOPPED"

    def _fail(self, code):
        self._count("faults")
        self._end(code)
        raise RuntimeLabError(code) from None

    def _checked_now(self):
        try:
            return self._now()
        except BridgeError as exc:
            self._fail(str(exc))  # _now emits only fixed codes, never raw exception text

    def _snapshot(self):
        try:
            work = self._host.work.inspect()
            self._last_work = deepcopy(work["usage"])
            self._state = ("PAUSED" if work["user_paused"] else
                           "READY_LAB" if work["resource"] == "NORMAL" else "DEGRADED")
            return work
        except Exception:
            self._fail("RUNTIME_CONTEXT_OR_WORK_FAULT")

    def start(self, channel):
        self._operator(channel)
        _require(self._state == "STOPPED", "EXPLICIT_STOP_REQUIRED")
        _require(self._config.enabled, "RUNTIME_DISABLED")
        self._state = "STARTING"
        self._fault = None
        self._session = None
        self._counts.clear()
        self._max_input = self._max_control = self._max_seen = 0
        self._last_work = None
        self._purge()
        try:
            self._origin = self._last_raw = self._raw_now()
            fixture = fixture_binding()
            self._binding = SourceBinding(fixture.local_alias, fixture.console_robot_alias,
                fixture.source_id, fixture.sensor_id, fixture.sensor_frame_id, uuid4().hex,
                "SYNTHETIC_REPLAY")
            supplier = self._resolver.read if self._resolver is not None else lambda: context_slice(fixture.local_alias)
            self._host = CoreBAttentionHost(self._schema, context_supplier=supplier,
                binding=self._binding, policy=self._config.work, attention_policy=self._config.attention,
                clock=self._now)
            self._session = self._host.runtime_id
            self._snapshot()  # resource starts UNKNOWN; do not auto-approve NORMAL
        except RuntimeLabError:
            raise
        except Exception:
            self._fail("RUNTIME_START_FAILED")
        return {"runtime_session": self._session, "source_session": self._binding.source_session_id,
                "state": self._state, "fixture_only": True, "life_id": None}

    def stop(self, channel):
        self._operator(channel)
        if self._state != "STOPPED":
            self._end()
        return self.health(channel)

    def request_control(self, channel, command):
        self._operator(channel)
        _require(self._state in self._ACTIVE, "RUNTIME_NOT_ACTIVE")
        _require(type(command) is str and command in self._CONTROLS, "UNKNOWN_CONTROL")
        if "STOP" in self._controls:
            return "STOP_PENDING"
        if command in {"STOP", "PAUSE"}:
            # Priority controls supersede queued normal operations. Work owns
            # the actual pause barrier; this queue is not a second authority.
            self._count("control_superseded", len(self._controls))
            self._controls.clear()
        elif command == "RELEASE" and (self._state != "PAUSED" or "PAUSE" in self._controls):
            return "NOT_PAUSED"
        elif len(self._controls) >= self._config.control_capacity:
            self._count("control_backpressure")
            return "BACKPRESSURE"
        self._controls.append(command)
        self._max_control = max(self._max_control, len(self._controls))
        return "QUEUED"

    def _expire(self, now):
        for key, (_, deadline) in list(self._seen.items()):
            if now >= deadline:
                del self._seen[key]
        dropped = 0
        while self._inputs and now >= self._inputs[0].deadline_ns:
            self._inputs.popleft()
            dropped += 1
        if dropped:
            self._count("expired", dropped)
            self._host.attention.invalidate()

    def offer(self, channel, *, runtime_session, sample, consent=False):
        self._owner_thread()
        _require(channel is self._owners.synthetic_source, "UNAUTHORIZED_SOURCE")
        _require(self._state in self._ACTIVE, "RUNTIME_NOT_ACTIVE")
        if type(runtime_session) is not str or runtime_session != self._session:
            self._count("foreign_session")
            return "FOREIGN_SESSION"
        _require(type(consent) is bool, "INVALID_CONSENT")
        now = self._checked_now()
        self._expire(now)
        if not consent:
            # No retention or parsing of denied content. Drop queued evidence.
            self._count("consent_denied")
            self._count("discarded", len(self._inputs))
            self._inputs.clear()
            self._host.attention.invalidate()
            return "CONSENT_DENIED"
        try:
            encode(sample)  # structural/byte bounds before JSON Schema traversal
            _validate("ConsoleImuRecord", sample)
            seq, source_ns = sample["sequence"], sample["host_monotonic_ns"]
            _require(type(seq) is int and type(source_ns) is int, "INVALID_SEQUENCE")
            fingerprint = _digest(sample)
        except Exception:
            self._count("invalid")
            return "INVALID_SAMPLE"
        b = self._binding
        if (sample["robot_id"], sample["source_id"], sample["sensor_id"],
                sample["sensor_frame_id"], sample["session_id"]) != (
                b.console_robot_alias, b.source_id, b.sensor_id, b.sensor_frame_id, b.source_session_id):
            self._count("source_mismatch")
            return "SOURCE_MISMATCH"
        old = self._seen.get(seq)
        if old is not None:
            status = "DUPLICATE" if old[0] == fingerprint else "SEQUENCE_COLLISION"
            self._count(status.lower())
            return status
        if self._last_seq is not None and (seq <= self._last_seq or source_ns <= self._last_source_ns):
            self._count("replay_or_out_of_order")
            return "REPLAY_OR_OUT_OF_ORDER"
        # A valid sequence presented while paused or under pressure is consumed
        # as a terminal drop. It cannot be retimestamped by retrying it later.
        self._last_seq, self._last_source_ns = seq, source_ns
        if self._state == "PAUSED" or "PAUSE" in self._controls or "STOP" in self._controls:
            self._count("discarded")
            return "CONTROL_PENDING_OR_PAUSED"
        if len(self._inputs) >= self._config.input_capacity or len(self._seen) >= self._config.replay_capacity:
            self._count("input_backpressure")
            return "BACKPRESSURE"
        deadline = now + self._config.attention.max_age_ms * 1_000_000
        self._seen[seq] = (fingerprint, deadline)
        self._inputs.append(_Input(deepcopy(sample), now, deadline))
        self._count("queued")
        self._max_input = max(self._max_input, len(self._inputs))
        self._max_seen = max(self._max_seen, len(self._seen))
        return "QUEUED"

    def tick(self, channel):
        """At most one control or input, plus actual Work heartbeat. No sleep/I/O."""
        self._operator(channel)
        _require(self._state in self._ACTIVE, "RUNTIME_NOT_ACTIVE")
        # Stop must work even after a clock/context failure.
        if self._controls and self._controls[0] == "STOP":
            self._end()
            return {"status": self._state, "kind": "CONTROL", "command": "STOP"}
        now = self._checked_now()
        self._expire(now)
        if self._controls:
            command = self._controls.popleft()
            try:
                if command == "PAUSE":
                    self._host.interrupt_user(self._host.owners.operator)
                    self._count("discarded", len(self._inputs))
                    self._inputs.clear()
                elif command == "RELEASE":
                    self._host.release_user_attention(self._host.owners.operator)
                else:
                    self._host.set_resources(self._host.owners.operator, command.removeprefix("RESOURCE_"))
            except Exception:
                self._fail("RUNTIME_CONTROL_FAILED")
            self._snapshot()
            self._count("controls")
            return {"status": self._state, "kind": "CONTROL", "command": command}
        work = self._snapshot()  # real Work expiry/context check even when idle
        if not self._inputs or work["user_paused"]:
            self._count("heartbeats")
            return {"status": self._state, "kind": "HEARTBEAT"}
        item = self._inputs.popleft()
        try:
            result = self._host.ingest(item.record, received_ns=item.receipt_ns, freshness="FRESH", consent=True)
        except Exception:
            self._fail("RUNTIME_INGEST_FAILED")
        proposal = result["proposal"]
        self._count("processed")
        if result["attention"]["cue"] is not None:
            self._count("cues")
        decision = None
        if proposal is not None:
            decision = proposal["admission"]["outcome"]
            self._count("admission_" + decision.lower())
        if result.get("deferral") is not None:
            self._count("conservative_deferrals")
        self._snapshot()
        return {"status": self._state, "kind": "INPUT", "attention": result["attention"]["status"],
                "admission": decision, "fixture_only": True, "may_actuate": False}

    def health(self, channel):
        self._operator(channel)
        # Cached report only: health reads never advance Work or expose tokens.
        return {"state": self._state, "fault": self._fault, "runtime_session": self._session,
                "fixture_only": True, "scope": "SESSION_SCOPED", "life_id": None,
                "chronon_status": "NOT_CONNECTED", "worker_connected": False,
                "last_session_elapsed_ns": (self._last_raw - self._origin
                    if self._origin is not None and self._last_raw is not None else None),
                "may_actuate": False, "external_effects": False,
                "pending_input": len(self._inputs), "pending_control": len(self._controls),
                "replay_entries": len(self._seen), "input_high_water": self._max_input,
                "control_high_water": self._max_control, "replay_high_water": self._max_seen,
                "counters": dict(self._counts), "work_usage": deepcopy(self._last_work)}


def run_replay(schema_bytes, count=1000):
    """Finite explicit synthetic CLI/test driver; no real-time performance claim."""
    _require(type(count) is int and 1 <= count <= 10000, "INVALID_REPLAY_COUNT")
    clock, owners = FixtureClock(), RuntimeLabOwners()
    config = RuntimeLabConfig(enabled=True, work=Limits(enabled=True))
    lab = RuntimeLab(schema_bytes, owners=owners, config=config, clock_ns=clock)
    session = lab.start(owners.operator)
    lab.request_control(owners.operator, "RESOURCE_NORMAL")
    lab.tick(owners.operator)
    for i in range(count):
        clock.advance(100)
        sample = fixture_sample(i, 0.6 if (i // 3) % 2 else 0.0)
        sample["session_id"] = session["source_session"]
        if lab.offer(owners.synthetic_source, runtime_session=session["runtime_session"], sample=sample, consent=True) != "QUEUED":
            raise RuntimeLabError("REPLAY_INPUT_NOT_ACCEPTED")
        lab.tick(owners.operator)
    active = lab.health(owners.operator)
    closed = lab.stop(owners.operator)
    return {"samples": count, "active": active, "closed": closed, "fixture_only": True}


def main():
    import argparse
    import json
    from pathlib import Path
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--core-b-checkout", required=True)
    p.add_argument("--events", type=int, default=1000)
    args = p.parse_args()
    with (Path(args.core_b_checkout) / "contracts/kernel/v0.1.0/schemas/kernel-goal-effect.schema.json").open("rb") as handle:
        raw = handle.read(65537)
    print(json.dumps(run_replay(raw, args.events), indent=2))


if __name__ == "__main__":
    main()
