"""COG-RI-03: associate supplied source-owned IMU bytes with a C1 reference.

This optional local candidate reuses the existing Console correlation function.
The trusted host supplies that reviewed function and already-authorized bytes;
there is no loader, reader, transport, grant issuer or second acquisition path.
The currently reviewed Console matcher supports the Paky-01 pilot scope only.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import hashlib
from threading import RLock
from typing import Callable

from .attention_c1 import SourceBinding, _digest as c1_digest
from .contracts import decode, encode
from .ri_imu_binding import ConsoleImuSchema, IMUBindingOwners, RI_MEDIA_TYPE
from .ri_observation_ref import RIReferenceConsumer

CONSOLE_REVIEW_COMMIT = "b331dd32415eeda0d107676920a6dea91170cc4f"
CONSOLE_MATCHER_BLOB = "34710eba7cecf0235cd2651edd286f5ac79a41fe"
RI_ACCESS_REVIEW_COMMIT = "3b9a9c2e6d7f69aae3dde1e690fc3c90562a1f43"
MAX_SOURCE_BYTES = 4096
MAX_NATIVE_U64 = (1 << 64) - 1
SOURCE_PRODUCERS = frozenset({
    "paky-01/imu_publish.py:IMU-RI-01-candidate",
    "rgd-imu/0.1.0a4:IMU-FOUNDATION-01D-candidate",
})


class SourceBindingError(ValueError):
    """Fixed diagnostic code, never evidence content or a private path."""


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise SourceBindingError(code)


@dataclass(frozen=True)
class SourceBindingPolicy:
    source_binding: SourceBinding
    enabled: bool = False
    max_records: int = 64

    def __post_init__(self):
        _require(type(self.source_binding) is SourceBinding,
                 "SOURCE_BINDING_REQUIRED")
        _require(type(self.enabled) is bool and type(self.max_records) is int
                 and 1 <= self.max_records <= 64, "INVALID_SOURCE_POLICY")


class SourceOwnedIMUBinder:
    """Content association using one existing RI consumer and its replay guard.

    ``correlator`` is trusted installed Console code supplied by the host, never
    code, a module name or a function chosen by a sample. Its revision is checked
    by deployment review/CI, not authenticated by these descriptive constants.
    It is synchronous trusted code; this API does not preempt hostile Python.

    This does not renew access to previously returned bytes. The host must obtain
    current owner authorization/availability for each call, including duplicates.
    No result upgrades an earlier RI01 notice, creates a goal, or grants access.
    """
    def __init__(self, console_schema: ConsoleImuSchema,
                 ri_consumer: RIReferenceConsumer, *, policy: SourceBindingPolicy,
                 owners: IMUBindingOwners, correlator: Callable):
        _require(type(console_schema) is ConsoleImuSchema and
                 type(ri_consumer) is RIReferenceConsumer and
                 type(policy) is SourceBindingPolicy and
                 type(owners) is IMUBindingOwners and callable(correlator),
                 "INVALID_SOURCE_BINDER")
        self.console_schema, self.ri_consumer = console_schema, ri_consumer
        self.policy, self.owners = policy, owners
        self._correlator = correlator
        self._lock = RLock()
        self._samples: dict[tuple, str] = {}
        self._observations: dict[tuple, str] = {}
        self._closed = False

    def bind(self, publisher_channel: object, ri_reader_channel: object, *,
             reference: dict, sample: dict, stored_payload: bytes,
             availability: str = "UNKNOWN") -> dict:
        """Consume a currently authorized checked-payload view, never metadata.

        A04 host mapping: only PAYLOAD_RESOLVED/AVAILABLE may supply these bytes.
        Blocked, expired, withheld, missing and metadata-only results must not be
        passed here as AVAILABLE. A caller boolean/reference is not a grant.
        """
        with self._lock:
            _require(publisher_channel is self.owners.publisher and
                     ri_reader_channel is self.ri_consumer.owners.reader,
                     "SOURCE_CHANNEL_REQUIRED")
            _require(not self._closed, "SOURCE_BINDER_CLOSED")
            _require(self.policy.enabled, "SOURCE_BINDER_DISABLED")
            rp = self.ri_consumer.policy
            _require(rp.metadata_access and rp.payload_access and rp.consent,
                     "SOURCE_ACCESS_NOT_GRANTED")
            _require(type(availability) is str and availability == "AVAILABLE",
                     "SOURCE_EVIDENCE_UNAVAILABLE")
            _require(type(stored_payload) is bytes and
                     0 < len(stored_payload) <= MAX_SOURCE_BYTES,
                     "SOURCE_BYTES_LIMIT")
            try:
                # Retain the existing C1 numeric/shape restrictions, including
                # its signed-63-bit counter ceiling; never coerce an RI u64.
                # Bound borrowed objects, then validate owned snapshots. The
                # validators' returned copies must not capture later mutation
                # of the caller's original objects after validation.
                encode(sample)
                encode(reference)
                sample_snapshot, reference_snapshot = deepcopy(sample), deepcopy(reference)
                source = self.console_schema.validate(sample_snapshot)
                ref = self.ri_consumer.schema.validate(reference_snapshot)
                row = decode(stored_payload)
                _require(encode(row) == stored_payload, "SOURCE_NOT_CANONICAL")
            except SourceBindingError:
                raise
            except Exception:
                raise SourceBindingError("SOURCE_INPUT_INVALID") from None
            binding = self.policy.source_binding
            _require(tuple(source[k] for k in (
                "robot_id", "sensor_id", "source_id", "sensor_frame_id", "session_id")) ==
                (binding.console_robot_alias, binding.sensor_id, binding.source_id,
                 binding.sensor_frame_id, binding.source_session_id),
                "SOURCE_SCOPE_MISMATCH")
            _require(set(row) == {"schema_ref_str", "producer_str", "source",
                                 "temporal_binding", "payload"} and
                     type(row.get("producer_str")) is str and
                     row.get("producer_str") in SOURCE_PRODUCERS,
                     "SOURCE_PROFILE_UNSUPPORTED")
            wrapper = row.get("payload")
            _require(type(wrapper) is dict and "console_ingest_sample" in wrapper
                     and "representation_profile" not in wrapper
                     and "console_imu_record" not in wrapper,
                     "SOURCE_PROFILE_UNSUPPORTED")
            # Dimensional/parser limits are independent from integer ranges.
            stamp = row.get("temporal_binding")
            _require(type(stamp) is dict and all(
                type(stamp.get(k)) is int and 0 <= stamp[k] <= MAX_NATIVE_U64
                for k in ("received_monotonic_ns", "received_unix_estimate_ns",
                          "host_wall_pair_span_ns")), "SOURCE_INTEGER_DOMAIN")
            _require(stamp["host_wall_pair_span_ns"] <= 50_000_000,
                     "SOURCE_RECEIPT_BRACKET")
            _require(ref["integrity_status"] == "verified_local_hash" and
                     ref["payload_media_type"] == RI_MEDIA_TYPE and
                     type(ref["payload_size_bytes"]) is int and
                     ref["payload_size_bytes"] == len(stored_payload) and
                     ref["payload_sha256_hex"] == hashlib.sha256(stored_payload).hexdigest(),
                     "SOURCE_REFERENCE_BYTES_MISMATCH")
            try:
                # Reuse the owner's numeric/session/clock comparison; no copy of
                # its pilot constants or SI normalization is introduced in COG.
                match = self._correlator(deepcopy(source), deepcopy(ref), stored_payload)
            except Exception:
                raise SourceBindingError("SOURCE_CORRELATOR_FAILED") from None
            _require(type(match) is dict and match.get("matched") is True and
                     match.get("reason") == "same_source_content" and
                     match.get("observation_id") == ref["observation_id"] and
                     match.get("integrity_status") == "verified_local_hash" and
                     match.get("origin_status") == "unknown" and all(
                         match.get(k) is False for k in (
                             "source_verified", "robot_binding_verified",
                             "console_boot_verified", "history_committed",
                             "actuation_enabled")), "SOURCE_CONTENT_NOT_MATCHED")
            key = (source["source_id"], source["session_id"], source["sequence"])
            obs_key = (ref["source_id"], ref["observation_id"])
            fingerprint = hashlib.sha256(encode({"sample": source, "reference": ref})).hexdigest()
            duplicate = key in self._samples or obs_key in self._observations
            if duplicate:
                _require(self._samples.get(key) == fingerprint and
                         self._observations.get(obs_key) == fingerprint,
                         "SOURCE_ASSOCIATION_CONFLICT")
            else:
                _require(len(self._samples) < self.policy.max_records,
                         "SOURCE_ASSOCIATION_BACKPRESSURE")
            try:
                # The original whole-reference fingerprint remains authoritative.
                # A not_verified -> verified_local_hash change on an already
                # consumed ID still raises; no reset, sidecar or hidden upgrade.
                receipt = self.ri_consumer.accept(ri_reader_channel, ref,
                    evidence_state="AVAILABLE", payload_bytes=stored_payload)
            except Exception:
                raise SourceBindingError("RI_REFERENCE_ACCESS_OR_CONFLICT") from None
            if duplicate:
                _require(receipt["status"] == "DUPLICATE", "RI_REFERENCE_STATE_CHANGED")
                return {"status": "DUPLICATE", "association": None}
            _require(receipt["status"] == "ACCEPTED_REFERENCE" and
                     receipt["notice"]["payload_checked_at_cog"] is True,
                     "RI_REFERENCE_NOT_FIRST_ACCEPTANCE")
            association = {
                "profile": "cog_ri_source_association_v0.1-candidate",
                "observation_id": ref["observation_id"],
                "payload_sha256_hex": ref["payload_sha256_hex"],
                "c1_evidence_ref": c1_digest({"scope": vars(binding),
                                             "payload_digest": c1_digest(source)}),
                "integrity_scope": "SUPPLIED_SOURCE_BYTES_MATCHED",
                "origin": "SYNTHETIC" if binding.mode == "SYNTHETIC_REPLAY" else "UNKNOWN",
                "freshness": "UNKNOWN", "time_alignment": "NOT_ESTABLISHED",
                "source_authentication": "NOT_VERIFIED",
                "console_boot_verified": False, "calibration_status": "UNVERIFIED",
                "evidence_availability": "AVAILABLE_AT_HOST_HANDOFF",
                "life_id": None, "chronon_id": None,
                "can_generate_goal": False, "may_actuate": False,
                "grants_authority": False, "history_committed": False,
            }
            self._samples[key] = self._observations[obs_key] = fingerprint
            return {"status": "ASSOCIATED_SOURCE_CONTENT", "association": association}

    def inspect(self) -> dict:
        with self._lock:
            return {"closed": self._closed, "associations": len(self._samples),
                    "work_connected": False, "history_connected": False}

    def close(self) -> None:
        with self._lock:
            self._closed = True
            self._samples.clear()
            self._observations.clear()
