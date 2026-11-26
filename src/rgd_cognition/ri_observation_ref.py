"""RI->COG reference-only candidate: no devices, network, Work, or authority.

A Reality Ingress v0.4/PR4 reference supplies metadata about stored evidence.
Only a trusted local host can authorize presentation and qualify same-boot
receipt freshness. It cannot authenticate the physical source or a Life.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
import re
from threading import RLock
from time import monotonic_ns
from typing import Callable

from jsonschema import Draft202012Validator

from .contracts import encode, validate

RI_COMMIT = "5372f758df79c93fc887f3858d878635447f4a4d"
RI_SCHEMA_BLOB = "3d92e074e71593bf6db0a735394c628ea131668d"
_NOTICE_SCHEMA_VERSION = "cog_ri_reference_notice_v0.1-candidate"
_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:/@+-]{0,255}\Z")
_OBSID = re.compile(r"obs_[0-9a-f]{32}\Z")
_EVIDENCE_STATES = frozenset({"UNKNOWN", "AVAILABLE", "UNAVAILABLE", "REDACTED", "ERASED", "NOT_AUTHORIZED"})


class RIRefError(ValueError):
    """Fixed reason codes only; do not echo media, secrets or observations."""


def _require(test: bool, code: str) -> None:
    if not test:
        raise RIRefError(code)


def _wire(value) -> bytes:
    # Reuses the bounded COG JSON encoder, not a canonical Chronon digest.
    try:
        return encode(value)
    except (ValueError, TypeError, OverflowError, RecursionError):
        raise RIRefError("INVALID_REFERENCE_ENCODING") from None


class RIReferenceContract:
    """RI schema supplied out of band; byte-pinned and checked offline."""
    def __init__(self, schema_bytes: bytes):
        _require(type(schema_bytes) is bytes and 0 < len(schema_bytes) <= 8192, "RI_SCHEMA_LIMIT")
        sha = hashlib.sha1(b"blob " + str(len(schema_bytes)).encode("ascii") + b"\0" + schema_bytes).hexdigest()
        _require(sha == RI_SCHEMA_BLOB, "RI_SCHEMA_PIN_MISMATCH")
        try:
            data = json.loads(schema_bytes, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
            Draft202012Validator.check_schema(data)
        except (ValueError, TypeError, KeyError):
            raise RIRefError("INVALID_RI_SCHEMA") from None
        _require(data.get("$id") == "urn:openrgd:reality-ingress:consumer-observation-ref:v0.1-candidate",
                 "RI_SCHEMA_VERSION_MISMATCH")
        self._validator = Draft202012Validator(data)

    def validate(self, ref: dict) -> dict:
        _require(type(ref) is dict, "INVALID_RI_REFERENCE")
        _wire(ref)
        _require(next(self._validator.iter_errors(ref), None) is None, "INVALID_RI_REFERENCE")
        return deepcopy(ref)


@dataclass(frozen=True)
class RIHostPolicy:
    """Host-side configuration, never inferred from the RI record or an LLM.

    The same_boot_clock_trusted flag is a local host assumption; it is not a
    Chronograf time qualification or multi-host synchronization proof.
    """
    local_alias: str
    allowed_source_id: str
    allowed_modality: str
    allowed_frame_id: str
    clock_domain_id: str
    boot_id: str | None = None
    same_boot_clock_trusted: bool = False
    metadata_access: bool = False
    consent: bool = False
    payload_access: bool = False
    max_age_ms: int = 3000
    max_records: int = 64

    def __post_init__(self):
        for name in ("local_alias", "allowed_source_id", "allowed_modality",
                     "allowed_frame_id", "clock_domain_id"):
            value = getattr(self, name)
            _require(type(value) is str and _TOKEN.fullmatch(value) is not None,
                     "INVALID_HOST_POLICY")
        _require(self.boot_id is None or (type(self.boot_id) is str and
                     len(self.boot_id) <= 128 and bool(self.boot_id)), "INVALID_HOST_POLICY")
        _require(all(type(getattr(self, x)) is bool for x in (
                     "same_boot_clock_trusted", "metadata_access", "consent", "payload_access")),
                 "INVALID_HOST_POLICY")
        _require(type(self.max_age_ms) is int and 1 <= self.max_age_ms <= 60000,
                 "INVALID_HOST_POLICY")
        _require(type(self.max_records) is int and 1 <= self.max_records <= 4096,
                 "INVALID_HOST_POLICY")
        if self.same_boot_clock_trusted:
            _require(self.boot_id is not None, "BOOT_REQUIRED_FOR_ALIGNMENT")


class RILocalOwners:
    """Opaque in-process capability; not remote authentication or hostile code isolation."""
    def __init__(self):
        self.reader = object()


class RIReferenceConsumer:
    """A separate metadata consumer; never creates a COG InputEvent or Work goal.

    Receipt time belongs to RI's host clock domain; source capture time is
    unknown. Duplicates are inert, retain original TTL judgment and cannot
    convert old references into fresh observations. No media store is created.
    """
    def __init__(self, schema: RIReferenceContract, *, policy: RIHostPolicy,
                 owners: RILocalOwners, clock_ns: Callable[[], int] = monotonic_ns):
        _require(isinstance(schema, RIReferenceContract) and
                 isinstance(policy, RIHostPolicy) and isinstance(owners, RILocalOwners),
                 "INVALID_CONSUMER_CONFIGURATION")
        self.schema, self.policy, self.owners, self.clock_ns = schema, policy, owners, clock_ns
        self._lock = RLock()
        self._last_ns = -1
        self._seen: dict[tuple[str, str], str] = {}
        self._closed = False

    def _now(self) -> int:
        _require(not self._closed, "CONSUMER_CLOSED")
        now = self.clock_ns()
        if type(now) is not int or now < 0 or now < self._last_ns:
            self._closed = True
            self._seen.clear()
            raise RIRefError("LOCAL_CLOCK_REGRESSION")
        self._last_ns = now
        return now

    def accept(self, channel: object, reference: dict, *, evidence_state: str = "UNKNOWN",
               payload_bytes: bytes | None = None) -> dict:
        with self._lock:
            _require(channel is self.owners.reader, "UNAUTHORIZED_READER")
            _require(not self._closed, "CONSUMER_CLOSED")
            # No observation ID/hash is returned for denied metadata or consent.
            if not self.policy.metadata_access or not self.policy.consent:
                return {"status": "BLOCKED", "reason": "ACCESS_OR_CONSENT_DENIED", "notice": None}
            _require(type(evidence_state) is str and evidence_state in _EVIDENCE_STATES,
                     "UNKNOWN_EVIDENCE_STATE")
            if evidence_state in {"REDACTED", "ERASED", "NOT_AUTHORIZED"}:
                return {"status": "BLOCKED", "reason": evidence_state, "notice": None}
            ref = self.schema.validate(reference)
            _require(ref["source_id"] == self.policy.allowed_source_id and
                     ref["modality"] == self.policy.allowed_modality and
                     ref["reference_frame_id"] == self.policy.allowed_frame_id,
                     "SOURCE_SCOPE_MISMATCH")
            _require(_OBSID.fullmatch(ref["observation_id"]) is not None, "BAD_OBSERVATION_ID")
            self._now()
            stamp = ref["time"]
            same_boot = (self.policy.same_boot_clock_trusted and
                         stamp["boot_id"] == self.policy.boot_id and
                         stamp["clock_domain_id"] == self.policy.clock_domain_id)
            age = None
            freshness = "UNKNOWN"
            if same_boot:
                age = self._last_ns - stamp["received_monotonic_ns"]
                _require(age >= 0, "FUTURE_RECEIPT")
                freshness = "STALE" if age >= self.policy.max_age_ms * 1_000_000 else "FRESH"
            # If an authorized caller presents bytes, verify them even for a
            # duplicate: replay must never silently "accept" corrupt content.
            checked_bytes = False
            if payload_bytes is not None:
                _require(self.policy.payload_access and evidence_state == "AVAILABLE",
                         "PAYLOAD_ACCESS_NOT_GRANTED")
                _require(type(payload_bytes) is bytes and len(payload_bytes) <= 1_048_576,
                         "PAYLOAD_TOO_LARGE_OR_INVALID")
                _require(len(payload_bytes) == ref["payload_size_bytes"] and
                         hashlib.sha256(payload_bytes).hexdigest() == ref["payload_sha256_hex"],
                         "PAYLOAD_DIGEST_MISMATCH")
                checked_bytes = True
            key = (ref["source_id"], ref["observation_id"])
            fingerprint = hashlib.sha256(_wire(ref)).hexdigest()
            old = self._seen.get(key)
            if old is not None:
                _require(old == fingerprint, "OBSERVATION_ID_COLLISION")
                return {"status": "DUPLICATE", "reason": "INERT_REPLAY", "notice": None}
            _require(len(self._seen) < self.policy.max_records, "REFERENCE_BACKPRESSURE")
            notice = {
                "schema_version": _NOTICE_SCHEMA_VERSION,
                "reference": ref,
                "local_alias": self.policy.local_alias,
                "session_scope": "SESSION_SCOPED_UNBOUND",
                "source_authentication": "NOT_VERIFIED",
                "source_time_quality": "UNKNOWN",
                "calibration_status": "UNVERIFIED",
                "epistemic_status": "UNKNOWN",
                "evidence_state": evidence_state,
                "freshness": freshness,
                "time_alignment": "HOST_SAME_BOOT_ASSERTED" if same_boot else "NOT_ESTABLISHED",
                "receipt_age_ns": age,
                "payload_checked_at_cog": checked_bytes,
                "perception_status": "NOT_CONNECTED",
                "life_id": None,
                "chronon_id": None,
                "may_actuate": False,
                "can_generate_goal": False,
                "grants_authority": False,
            }
            validate_ri_notice(notice)
            self._seen[key] = fingerprint
            return {"status": "ACCEPTED_REFERENCE", "reason": "REFERENCE_METADATA_ONLY", "notice": notice}

    def inspect(self) -> dict:
        with self._lock:
            return {"closed": self._closed, "seen_count": len(self._seen),
                    "life_id": None, "chronon_status": "NOT_CONNECTED",
                    "work_connected": False}

    def close(self) -> None:
        with self._lock:
            self._seen.clear()
            self._closed = True


# Closed companion schema; never extend COG-01 InputEvent or Core-B records.
from pathlib import Path
_NOTICE_SCHEMA = json.loads((Path(__file__).parent / "schemas/ri-reference-notice.schema.json").read_text(encoding="utf-8"))
Draft202012Validator.check_schema(_NOTICE_SCHEMA)
_NOTICE_VALIDATOR = Draft202012Validator(_NOTICE_SCHEMA)


def validate_ri_notice(notice: dict) -> dict:
    _wire(notice)
    _require(next(_NOTICE_VALIDATOR.iter_errors(notice), None) is None, "INVALID_COG_RI_NOTICE")
    return deepcopy(notice)
