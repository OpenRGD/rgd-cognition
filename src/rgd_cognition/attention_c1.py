"""COG-C1: bounded attention over supplied IMU records; no transport or devices.

The caller owns authentication, consent and receipt metadata. Numeric change is
an investigation cue, never a pose estimate, fault diagnosis or motion grant.
"""
from __future__ import annotations

from collections import Counter, deque
from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
import re
from time import monotonic_ns
from typing import Callable
from uuid import uuid4

from jsonschema import Draft202012Validator, FormatChecker

_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
_SCHEMA = json.loads((Path(__file__).parent / "schemas/attention-c1.schema.json").read_text(encoding="utf-8"))
Draft202012Validator.check_schema(_SCHEMA)
_FORMATS = FormatChecker()


@_FORMATS.checks("date-time", raises=(ValueError, TypeError))
def _timestamp(value):
    if not isinstance(value, str):
        return True
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})", value):
        return False
    return datetime.fromisoformat(value.replace("Z", "+00:00")).tzinfo is not None


_VALIDATORS = {name: Draft202012Validator(
    {"$schema": _SCHEMA["$schema"], "$defs": _SCHEMA["$defs"], "$ref": "#/$defs/" + name},
    format_checker=_FORMATS) for name in ("ConsoleImuRecord", "AttentionCue")}


class AttentionError(ValueError):
    """Stable code only, with no private sample or exception text."""


def _digest(value) -> str:
    # Local observation/assessment fingerprint, NOT canonical RGD or Chronon hashing.
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                     allow_nan=False).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _validate(name: str, value: dict) -> dict:
    try:
        if type(value) is not dict or next(_VALIDATORS[name].iter_errors(value), None) is not None:
            raise AttentionError("INVALID_" + name.upper())
        raw = json.dumps(value, allow_nan=False, ensure_ascii=False).encode("utf-8")
        if len(raw) > 16384:
            raise AttentionError("PAYLOAD_LIMIT")
    except AttentionError:
        raise
    except Exception:
        raise AttentionError("INVALID_PAYLOAD") from None
    return value


@dataclass(frozen=True)
class SourceBinding:
    """Trusted host configuration, never parsed from an observation or LLM output.

    A Console robot_id is a routing alias, NOT a physical enrollment proof.
    Session rotation requires a new binding/engine, preventing cross-boot deltas.
    """
    local_alias: str
    console_robot_alias: str
    source_id: str
    sensor_id: str
    sensor_frame_id: str
    source_session_id: str
    mode: str = "SYNTHETIC_REPLAY"

    def __post_init__(self):
        for value in (self.local_alias, self.console_robot_alias, self.source_id,
                      self.sensor_id, self.sensor_frame_id):
            if not isinstance(value, str) or not _TOKEN.fullmatch(value):
                raise AttentionError("INVALID_SOURCE_BINDING")
        if not isinstance(self.source_session_id, str) or not re.fullmatch(r"[0-9a-fA-F]{32}", self.source_session_id):
            raise AttentionError("INVALID_SOURCE_SESSION")
        if self.mode not in {"SYNTHETIC_REPLAY", "AUTHORIZED_LOCAL_FEED"}:
            raise AttentionError("INVALID_SOURCE_MODE")


@dataclass(frozen=True)
class AttentionPolicy:
    """Experimental signal thresholds; not calibrated robot or safety limits."""
    min_samples: int = 3
    max_age_ms: int = 3000
    max_gap_ms: int = 1000
    cooldown_ms: int = 30000
    max_proposals: int = 8
    rotation_high_rad_s: float = 0.3
    rotation_low_rad_s: float = 0.15

    def __post_init__(self):
        for value, low, high in ((self.min_samples, 2, 8), (self.max_age_ms, 1, 60000),
                                 (self.max_gap_ms, 1, 60000), (self.cooldown_ms, 1, 3600000),
                                 (self.max_proposals, 1, 16)):
            if type(value) is not int or not low <= value <= high:
                raise AttentionError("INVALID_ATTENTION_POLICY")
        if self.max_gap_ms > self.max_age_ms:
            raise AttentionError("INVALID_ATTENTION_POLICY")
        for value in (self.rotation_low_rad_s, self.rotation_high_rad_s):
            if type(value) not in (int, float) or not math.isfinite(value):
                raise AttentionError("INVALID_ATTENTION_POLICY")
        if not 0 <= self.rotation_low_rad_s < self.rotation_high_rad_s <= 100:
            raise AttentionError("INVALID_ATTENTION_POLICY")


class ImuAttention:
    """Single-source, session-only detector; no caller-supplied cue_kind.

    Freshness is the trusted adapter's assessment, not the packet's assertion.
    Local residence and source monotonic order are independent clock checks.
    There is no network/device reader and no automatic source-session rollover.
    """
    def __init__(self, binding: SourceBinding, *, policy: AttentionPolicy | None = None,
                 clock: Callable[[], int] = monotonic_ns):
        if not isinstance(binding, SourceBinding):
            raise AttentionError("SOURCE_BINDING_REQUIRED")
        self.binding = binding
        self.policy = policy if policy is not None else AttentionPolicy()
        if not isinstance(self.policy, AttentionPolicy):
            raise AttentionError("INVALID_ATTENTION_POLICY")
        self._clock, self._last_ns = clock, -1
        self._seq = self._source_ns = self._received_ns = None
        self._fingerprint = None
        self._context_revision = None
        self._window = deque(maxlen=self.policy.min_samples)
        self._high = self._low = 0
        self._rotation_latched = self._uncertainty_seen = False
        self._proposals = 0
        self._last_proposed_ns = None
        self._closed = False
        self._counts = Counter()
        self.session_id = "cog-c1-session:" + str(uuid4())
        self.policy_revision = _digest({"rule_version": "cog-c1-imu-rules-v1", **vars(self.policy)})

    def now(self) -> int:
        if self._closed:
            raise AttentionError("ATTENTION_CLOSED")
        value = self._clock()
        if type(value) is not int or value < 0 or value < self._last_ns:
            self.close()
            raise AttentionError("LOCAL_CLOCK_REGRESSION")
        self._last_ns = value
        return value

    def _clear_window(self):
        self._window.clear()
        self._high = self._low = 0
        self._rotation_latched = False

    def invalidate(self):
        """Clear transient evidence; preserve anti-replay and lifetime quotas."""
        self._clear_window()

    def _result(self, status, reason, cue=None):
        self._counts[reason] += 1
        return {"status": status, "reason_code": reason, "cue": cue}

    def observe(self, payload: dict, *, received_ns: int, freshness: str = "UNKNOWN",
                consent: bool = False, context_revision: str,
                allow_goal_generation: bool = False) -> dict:
        now = self.now()
        if type(consent) is not bool or type(allow_goal_generation) is not bool:
            raise AttentionError("INVALID_RECEIPT")
        if not consent:
            self._clear_window()
            return self._result("REJECTED", "CONSENT_DENIED")
        if freshness not in {"FRESH", "STALE", "UNKNOWN"}:
            raise AttentionError("INVALID_FRESHNESS")
        if type(received_ns) is not int or not 0 <= received_ns <= now:
            raise AttentionError("INVALID_RECEIPT_CLOCK")
        if not isinstance(context_revision, str) or not _DIGEST.fullmatch(context_revision):
            raise AttentionError("INVALID_CONTEXT_REVISION")
        if freshness != "FRESH" or now - received_ns >= self.policy.max_age_ms * 1000000:
            self._clear_window()
            return self._result("REJECTED", "OBSERVATION_NOT_FRESH")
        try:
            _validate("ConsoleImuRecord", payload)
        except AttentionError:
            self._clear_window()
            raise
        expected = {"robot_id": self.binding.console_robot_alias, "source_id": self.binding.source_id,
                    "sensor_id": self.binding.sensor_id, "sensor_frame_id": self.binding.sensor_frame_id,
                    "session_id": self.binding.source_session_id}
        if any(payload[key] != value for key, value in expected.items()):
            self._clear_window()
            return self._result("REJECTED", "SOURCE_BINDING_MISMATCH")
        fingerprint = _digest(payload)
        seq, source_ns = payload["sequence"], payload["host_monotonic_ns"]
        if self._seq is not None:
            if seq == self._seq:
                if fingerprint != self._fingerprint:
                    self._clear_window()
                    return self._result("REJECTED", "SEQUENCE_COLLISION")
                return self._result("IGNORED", "DUPLICATE")
            if seq < self._seq or source_ns <= self._source_ns or received_ns < self._received_ns:
                self._clear_window()
                return self._result("REJECTED", "OUT_OF_ORDER")
        if (context_revision != self._context_revision or
                (self._received_ns is not None and
                 (received_ns - self._received_ns > self.policy.max_gap_ms * 1000000 or seq != self._seq + 1))):
            self._clear_window()
        self._context_revision = context_revision
        self._seq, self._source_ns, self._received_ns = seq, source_ns, received_ns
        self._fingerprint = fingerprint
        reference = _digest({"scope": vars(self.binding), "payload_digest": fingerprint})
        self._window.append((reference, received_ns))
        while self._window and now - self._window[0][1] >= self.policy.max_age_ms * 1000000:
            self._clear_window()
        rate = math.hypot(*payload["angular_velocity_rad_s"])
        self._high = min(self.policy.min_samples, self._high + 1) if rate >= self.policy.rotation_high_rad_s else 0
        self._low = min(self.policy.min_samples, self._low + 1) if rate <= self.policy.rotation_low_rad_s else 0
        if self._low >= self.policy.min_samples:
            self._rotation_latched = False
        if len(self._window) < self.policy.min_samples:
            return self._result("OBSERVED", "WARMING_UP")
        if not allow_goal_generation:
            return self._result("OBSERVED", "GENERATION_PAUSED")
        if self._proposals >= self.policy.max_proposals:
            return self._result("SUPPRESSED", "ATTENTION_QUOTA")
        if self._last_proposed_ns is not None and now - self._last_proposed_ns < self.policy.cooldown_ms * 1000000:
            return self._result("SUPPRESSED", "COOLDOWN")
        if self._high >= self.policy.min_samples and not self._rotation_latched:
            reason, self._rotation_latched = "SUSTAINED_RATE_UNVERIFIED_FRAME", True
        elif not self._uncertainty_seen:
            reason = "UNCALIBRATED_IMU_CONTEXT"
        else:
            return self._result("OBSERVED", "NO_NEW_QUESTION")
        self._uncertainty_seen = True
        self._proposals += 1
        self._last_proposed_ns = now
        cue = {
            "schema_version": "cog_attention_c1_v0.1-candidate", "attention_session_id": self.session_id,
            "cue_kind": "IMU_DISCREPANCY", "reason_code": reason, "scope": "EPISTEMIC_INQUIRY_ONLY",
            "context_revision": context_revision, "policy_revision": self.policy_revision,
            "source_refs": [ref for ref, _ in self._window],
            "expires_at_monotonic_ns": self._window[0][1] + self.policy.max_age_ms * 1000000,
            "receipt_clock_domain": self.session_id,
            "source_clock_domain": "console.host_receive:" + self.binding.source_id + ":" + self.binding.source_session_id,
            "source_time": payload["host_receive_utc"],
            "origin": "SYNTHETIC" if self.binding.mode == "SYNTHETIC_REPLAY" else "PHYSICAL",
            "epistemic_status": "DERIVED", "evidence_level": "DECLARED_ONLY",
            "calibration_status": "UNVERIFIED", "decision_eligible": False,
            "life_id": None, "chronon_status": "NOT_CONNECTED", "may_actuate": False,
        }
        cue["cue_id"] = _digest(cue)
        return self._result("CUE", reason, _validate("AttentionCue", cue))

    def stats(self) -> dict:
        return {"closed": self._closed, "proposals": self._proposals,
                "window_size": len(self._window), "counts": dict(self._counts)}

    def close(self):
        self._clear_window()
        self._fingerprint = self._context_revision = None
        self._closed = True
