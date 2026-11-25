"""COG-RI-02: read-only evidence binding for a stored Console IMU presentation.

No producer, transport, evidence store, autonomous goal, or effect lives here.
An RI local hash only validates recorded bytes. A source is NOT authenticated.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
from threading import RLock
from time import monotonic_ns
from typing import Callable

from jsonschema import Draft202012Validator, FormatChecker

from .attention_c1 import SourceBinding, _digest as c1_digest, _validate as validate_c1
from .ri_observation_ref import (RIReferenceConsumer, RIRefError, validate_ri_notice)

CONSOLE_SCHEMA_BLOB = "8ddbe8d7639e35f0a9442a80e27c9e49f882eb7c"
CONSOLE_SOURCE_COMMIT = "a0ef857cf425c1bb14ad8f62acec21f8c1324866"
RI_SAMPLE_SCHEMA = "urn:openrgd:experimental:reality-ingress:source-sample:v0"
RI_MEDIA_TYPE = "application/vnd.openrgd.experimental.sensor-sample+json"
STORED_PROFILE = "cog-ri-02.console-copy.v0.1-candidate"
BINDING_VERSION = "cog_ri_imu_evidence_binding_v0.1-candidate"


class ImuBindingError(ValueError):
    """Fixed public reasons; never include payload, media, tokens or paths."""


def _require(value: bool, code: str) -> None:
    if not value:
        raise ImuBindingError(code)


def _canonical(value) -> bytes:
    """Matching RI generic canonical JSON presentation, NOT transport bytes."""
    try:
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (UnicodeError, TypeError, ValueError, OverflowError, RecursionError):
        raise ImuBindingError("INVALID_JSON") from None
    _require(len(raw) <= 131072, "PRESENTATION_LIMIT")
    return raw


def _decode(raw: bytes) -> dict:
    _require(type(raw) is bytes and 0 < len(raw) <= 131072, "PRESENTATION_LIMIT")
    def pairs(values):
        obj = {}
        for key, val in values:
            _require(key not in obj, "DUPLICATE_KEY")
            obj[key] = val
        return obj
    def bad(_):
        raise ImuBindingError("NONFINITE")
    try:
        obj = json.loads(raw, object_pairs_hook=pairs, parse_constant=bad)
    except ImuBindingError:
        raise
    except (UnicodeError, TypeError, ValueError, RecursionError):
        raise ImuBindingError("INVALID_JSON") from None
    _require(type(obj) is dict and _canonical(obj) == raw, "NOT_CANONICAL_RI_SAMPLE")
    return obj


class ConsoleImuSchema:
    """Console main exact schema bytes, validated offline; no Console runtime import."""
    def __init__(self, raw: bytes):
        _require(type(raw) is bytes and 0 < len(raw) <= 8192, "CONSOLE_SCHEMA_LIMIT")
        blob = hashlib.sha1(b"blob " + str(len(raw)).encode("ascii") + b"\0" + raw).hexdigest()
        _require(blob == CONSOLE_SCHEMA_BLOB, "CONSOLE_SCHEMA_PIN_MISMATCH")
        try:
            schema = json.loads(raw)
            Draft202012Validator.check_schema(schema)
            self.validator = Draft202012Validator(schema, format_checker=FormatChecker())
        except (ValueError, TypeError, KeyError):
            raise ImuBindingError("CONSOLE_SCHEMA_INVALID") from None

    def validate(self, sample: dict) -> dict:
        _require(type(sample) is dict, "INVALID_CONSOLE_SAMPLE")
        _canonical(sample)
        _require(next(self.validator.iter_errors(sample), None) is None,
                 "CONSOLE_SCHEMA_VIOLATION")
        try:
            validate_c1("ConsoleImuRecord", sample)
        except (ValueError, TypeError):
            raise ImuBindingError("C1_CONSOLE_SCHEMA_VIOLATION") from None
        return deepcopy(sample)


@dataclass(frozen=True)
class IMUBindingPolicy:
    """Configured by trusted host. Publisher authorization is EXTERNAL and absent here.

    No schema field proves that the Console publisher actually owns the device.
    The optional same-boot relation is host-asserted, not a signed clock mapping.
    """
    source_binding: SourceBinding
    max_records: int = 64
    same_boot_publisher_and_ri_asserted: bool = False
    max_receipt_lag_ms: int = 3000

    def __post_init__(self):
        _require(isinstance(self.source_binding, SourceBinding), "SOURCE_BINDING_REQUIRED")
        _require(type(self.max_records) is int and 1 <= self.max_records <= 2048,
                 "INVALID_BINDING_POLICY")
        _require(type(self.max_receipt_lag_ms) is int and 1 <= self.max_receipt_lag_ms <= 60000,
                 "INVALID_BINDING_POLICY")
        _require(type(self.same_boot_publisher_and_ri_asserted) is bool,
                 "INVALID_BINDING_POLICY")


class IMUBindingOwners:
    def __init__(self):
        self.publisher = object()


class RIImuEvidenceBinder:
    """Bind an authorized RI stored presentation to the exact Console sample.

    A successful result is a *byte/projection association*, not device identity,
    time synchronization, calibration, an observation event or motor permission.
    Does not change C1's existing SourceBinding, Attention or GoalAdmission path.
    """
    def __init__(self, console_schema: ConsoleImuSchema, ri_consumer: RIReferenceConsumer,
                 *, policy: IMUBindingPolicy, owners: IMUBindingOwners,
                 clock_ns: Callable[[], int] = monotonic_ns):
        _require(isinstance(console_schema, ConsoleImuSchema) and
                 isinstance(ri_consumer, RIReferenceConsumer) and
                 isinstance(policy, IMUBindingPolicy) and isinstance(owners, IMUBindingOwners),
                 "INVALID_BINDER_CONFIGURATION")
        self.console_schema, self.ri_consumer = console_schema, ri_consumer
        self.policy, self.owners, self.clock = policy, owners, clock_ns
        self._lock = RLock()
        self._seen_samples = {}
        self._seen_observations = {}
        self._last = -1
        self._closed = False

    def _now(self):
        _require(not self._closed, "BINDER_CLOSED")
        now = self.clock()
        if type(now) is not int or now < 0 or now < self._last:
            self._closed = True
            self._seen_samples.clear()
            self._seen_observations.clear()
            raise ImuBindingError("BINDER_CLOCK_REGRESSION")
        self._last = now
        return now

    def bind(self, publisher_channel: object, ri_reader_channel: object, *,
             reference: dict, sample: dict, stored_payload: bytes,
             availability: str = "UNKNOWN") -> dict:
        with self._lock:
            _require(publisher_channel is self.owners.publisher, "UNAUTHORIZED_IMU_PUBLISHER")
            _require(ri_reader_channel is self.ri_consumer.owners.reader, "UNAUTHORIZED_RI_READER")
            _require(self.ri_consumer.policy.metadata_access and self.ri_consumer.policy.consent
                     and self.ri_consumer.policy.payload_access, "RI_ACCESS_NOT_GRANTED")
            _require(availability == "AVAILABLE", "EVIDENCE_NOT_AVAILABLE")
            now = self._now()
            # Schema, presentation and semantic match MUST pass before consuming
            # the RI reference in its own idempotency/ACL gate.
            source = self.console_schema.validate(sample)
            binding = self.policy.source_binding
            _require((source["robot_id"], source["source_id"], source["sensor_id"],
                      source["sensor_frame_id"], source["session_id"]) ==
                     (binding.console_robot_alias, binding.source_id, binding.sensor_id,
                      binding.sensor_frame_id, binding.source_session_id),
                     "CONSOLE_SOURCE_SCOPE_MISMATCH")
            _require(source["reference_frame"] == "imu_sensor_axes_unverified" and
                     source["calibration_revision"] is None and
                     source["time_quality"] == "host_receive_only_not_chronograph" and
                     source["decision_eligible"] is False and source["observation_only"] is True,
                     "UNSUPPORTED_IMU_QUALITY")
            row = _decode(stored_payload)
            _require(row.get("schema_ref_str") == RI_SAMPLE_SCHEMA,
                     "UNSUPPORTED_STORED_REPRESENTATION")
            _require(set(row) == {"schema_ref_str", "producer_str", "source",
                                  "temporal_binding", "payload"}, "UNEXPECTED_STORED_FIELDS")
            payload = row["payload"]
            _require(type(payload) is dict and set(payload) == {"representation_profile", "console_imu_record"}
                     and payload["representation_profile"] == STORED_PROFILE,
                     "UNSUPPORTED_STORED_PROFILE")
            _require(_canonical(payload["console_imu_record"]) == _canonical(source),
                     "CONSOLE_BYTES_NOT_IDENTICAL")
            meta = row["source"]
            _require(type(meta) is dict and
                     meta.get("source_id_str") == source["source_id"] and
                     meta.get("modality_str") == "imu" and
                     meta.get("reference_frame_id_str") == source["sensor_frame_id"] and
                     type(meta.get("sample_sequence_uint")) is int and
                     meta["sample_sequence_uint"] == source["sequence"],
                     "STORED_SOURCE_MISMATCH")
            _require(type(row["producer_str"]) is str and bool(row["producer_str"]),
                     "STORED_PRODUCER_UNKNOWN")
            # RI's receipt belongs to the RI acquisition path, not the Console
            # upstream host measurement. Do not infer exposure or synchronized UTC.
            stamp = row["temporal_binding"]
            _require(type(stamp) is dict and stamp.get("source_time") is None and
                     stamp.get("source_time_status_str") == "UNKNOWN_NOT_EXPOSED_BY_SOURCE",
                     "FABRICATED_SOURCE_TIME")
            domain = stamp.get("clock_domain_ref")
            _require(type(domain) is dict and domain.get("clock_kind_enum_str") == "MONOTONIC",
                     "STORED_CLOCK_DOMAIN_INVALID")
            _require(type(stamp.get("received_monotonic_ns")) is int and
                     stamp["received_monotonic_ns"] >= 0, "STORED_RECEIPT_INVALID")

            try:
                ref = self.ri_consumer.schema.validate(reference)
            except RIRefError:
                raise ImuBindingError("INVALID_RI_REFERENCE") from None
            _require(ref["source_id"] == source["source_id"] and
                     ref["modality"] == "imu" and
                     ref["reference_frame_id"] == source["sensor_frame_id"] and
                     ref["sample_sequence"] == source["sequence"] and
                     ref["payload_media_type"] == RI_MEDIA_TYPE and
                     ref["payload_sha256_hex"] == hashlib.sha256(stored_payload).hexdigest() and
                     ref["payload_size_bytes"] == len(stored_payload) and
                     ref["time"]["received_monotonic_ns"] == stamp["received_monotonic_ns"] and
                     ref["time"]["clock_domain_id"] == domain.get("clock_domain_id_str") and
                     ref["time"]["boot_id"] == domain.get("boot_id_str"),
                     "RI_STORED_REFERENCE_MISMATCH")
            # A validated RI ref MUST NOT become a source-attestation credential.
            _require(ref["source_verified"] is False and ref["robot_binding_verified"] is False
                     and ref["actuation_enabled"] is False and ref["history_committed"] is False,
                     "REFERENCE_AUTHORITY_CLAIM")
            key = (source["source_id"], source["session_id"], source["sequence"])
            obs_key = (ref["source_id"], ref["observation_id"])
            fingerprint = hashlib.sha256(_canonical({"console": source, "ref": ref,
                                                    "stored_digest": ref["payload_sha256_hex"]})).hexdigest()
            if key in self._seen_samples or obs_key in self._seen_observations:
                _require(self._seen_samples.get(key) == fingerprint and
                         self._seen_observations.get(obs_key) == fingerprint,
                         "EVIDENCE_BINDING_COLLISION")
                return {"status": "DUPLICATE", "binding": None}
            _require(len(self._seen_samples) < self.policy.max_records,
                     "BINDING_BACKPRESSURE")

            try:
                result = self.ri_consumer.accept(ri_reader_channel, ref,
                                                 evidence_state=availability, payload_bytes=stored_payload)
            except RIRefError:
                raise ImuBindingError("RI_REFERENCE_ACCESS_OR_INTEGRITY_FAILED") from None
            _require(result["status"] == "ACCEPTED_REFERENCE", "REFERENCE_NOT_ACCEPTED")
            notice = validate_ri_notice(result["notice"])
            _require(notice["reference"] == ref and notice["payload_checked_at_cog"] is True,
                     "REFERENCE_NOT_BYTE_CHECKED")
            _require(notice["evidence_state"] == "AVAILABLE" and
                     notice["source_authentication"] == "NOT_VERIFIED" and
                     notice["calibration_status"] == "UNVERIFIED" and
                     notice["can_generate_goal"] is False and
                     notice["may_actuate"] is False and
                     notice["life_id"] is None and notice["chronon_id"] is None,
                     "REFERENCE_TRUST_ESCALATION")

            # Matching RI receipt and Console host monotonic values requires an
            # independently trusted *host assertion*. Neither schema proves it.
            aligned = (self.policy.same_boot_publisher_and_ri_asserted and
                       notice["time_alignment"] == "HOST_SAME_BOOT_ASSERTED" and
                       source["host_monotonic_ns"] <= stamp["received_monotonic_ns"] <= now)
            freshness = "UNKNOWN"
            if aligned:
                freshness = notice["freshness"]
                if now - source["host_monotonic_ns"] >= self.policy.max_receipt_lag_ms*1000000:
                    freshness = "STALE"
            binding_record = {
                "schema_version": BINDING_VERSION,
                "ri_observation_id": ref["observation_id"],
                "ri_payload_sha256_hex": ref["payload_sha256_hex"],
                "console_sample_sha256_hex": hashlib.sha256(_canonical(source)).hexdigest(),
                "source_id": source["source_id"],
                "sensor_id": source["sensor_id"],
                "frame_id": source["sensor_frame_id"],
                "source_session_id": source["session_id"],
                "sample_sequence": source["sequence"],
                "console_host_receipt_monotonic_ns": source["host_monotonic_ns"],
                "ri_host_receipt_monotonic_ns": ref["time"]["received_monotonic_ns"],
                "ri_boot_id": ref["time"]["boot_id"],
                "ri_clock_domain_id": ref["time"]["clock_domain_id"],
                "c1_local_evidence_ref": c1_digest({
                    "scope": vars(binding), "payload_digest": c1_digest(source)}),
                "byte_relation": "EXACT_STORED_NORMALIZED_COPY",
                "clock_relation": "HOST_SAME_BOOT_ASSERTED" if aligned else "NOT_ESTABLISHED",
                "freshness": freshness,
                "source_authentication": "NOT_VERIFIED",
                "sensor_calibration": "UNVERIFIED",
                "robot_binding_verified": False,
                "decision_eligible": False,
                "can_generate_goal": False,
                "may_actuate": False,
                "grants_authority": False,
                "life_id": None,
                "chronon_id": None,
            }
            binding_record["binding_ref"] = "sha256:"+hashlib.sha256(_canonical(binding_record)).hexdigest()
            validate_binding_record(binding_record)
            self._seen_samples[key] = fingerprint
            self._seen_observations[obs_key] = fingerprint
            return {"status": "CONTENT_MATCHED", "binding": deepcopy(binding_record)}

    def inspect(self) -> dict:
        with self._lock:
            return {"closed": self._closed, "seen_count": len(self._seen_samples),
                    "life_id": None, "chronon_status": "NOT_CONNECTED", "work_connected": False}

    def close(self) -> None:
        with self._lock:
            self._closed = True
            self._seen_samples.clear()
            self._seen_observations.clear()


from pathlib import Path
_BINDING_SCHEMA = json.loads((Path(__file__).parent / "schemas/ri-imu-binding.schema.json").read_text(encoding="utf-8"))
Draft202012Validator.check_schema(_BINDING_SCHEMA)
_BINDING_VALIDATOR = Draft202012Validator(_BINDING_SCHEMA)


def validate_binding_record(value: dict) -> dict:
    _canonical(value)
    _require(next(_BINDING_VALIDATOR.iter_errors(value), None) is None,
             "INVALID_BINDING_RECORD")
    _require(value["binding_ref"] == "sha256:"+hashlib.sha256(_canonical({
        k: v for k, v in value.items() if k != "binding_ref"})).hexdigest(),
        "BINDING_DIGEST_MISMATCH")
    return deepcopy(value)
