"""Actual RI A03/A04 + accepted Console helper + COG C1, synthetic only.

Required owner checkouts are explicit. Missing sources fail collection, never
skip. No private publisher source, device, capture or real consent is used.
"""
from copy import deepcopy
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

RI = Path(os.environ["RI_CHECKOUT"])
CONSOLE = Path(os.environ["CONSOLE_CHECKOUT"])
sys.path.insert(0, str(CONSOLE / "scripts/tests"))
from test_ri_periph_compat import fixtures, correlate

from reality_ingress.bounded_intake import (
    SourceScope, preview_spool, apply_spool, GENERALIZED, IntakeError,
)
from reality_ingress.evidence import EvidenceStore
from reality_ingress.evidence_access import LocalEvidenceReader
from reality_ingress.generic import canonical_json
from reality_ingress.consumer_ref import verified_ref_from_store
from rgd_cognition.attention_c1 import SourceBinding, ImuAttention, _digest as c1_digest
from rgd_cognition import ri_imu_binding as imu_binding
from rgd_cognition.ri_imu_binding import ConsoleImuSchema, IMUBindingOwners
from rgd_cognition.ri_observation_ref import (
    RIReferenceContract, RIReferenceConsumer, RIHostPolicy, RILocalOwners,
)
from rgd_cognition.ri_source_binding import (
    SourceOwnedIMUBinder, SourceBindingPolicy, SourceBindingError,
    CONSOLE_MATCHER_BLOB, MAX_NATIVE_U64,
)


class Clock:
    def __init__(self): self.value = 1_000_000_000
    def __call__(self): return self.value


class SourceAssociationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.console, self.row = fixtures()
        # Public Console fixture + the public owner profile metadata used by
        # RI's own cross-owner tests. This is not a private publisher run.
        self.row["producer_str"] = "paky-01/imu_publish.py:IMU-RI-01-candidate"
        self.row["temporal_binding"]["receive_timestamp_method"] = "userspace_after_existing_WIT_serial_read"
        self.clock = Clock()
        self.counter = 0
        self.view, self.reader, self.reader_owner, self.channel = self.produce(self.console, self.row)
        self.ref = json.loads(self.view.reference_json)
        self.binding = SourceBinding("synthetic-cog", self.console["robot_id"],
            self.console["source_id"], self.console["sensor_id"],
            self.console["sensor_frame_id"], self.console["session_id"])
        self.ri_owners = RILocalOwners()
        self.ri_consumer = RIReferenceConsumer(
            RIReferenceContract((RI / "contracts/consumer-observation-ref.v0.1-candidate.schema.json").read_bytes()),
            policy=RIHostPolicy(local_alias=self.binding.local_alias,
                allowed_source_id=self.binding.source_id, allowed_modality="imu",
                allowed_frame_id=self.binding.sensor_frame_id,
                clock_domain_id=self.ref["time"]["clock_domain_id"],
                metadata_access=True, payload_access=True, consent=True),
            owners=self.ri_owners, clock_ns=self.clock)
        self.console_schema = ConsoleImuSchema(
            (CONSOLE / "contracts/console/v1/imu-observation.v0.1.schema.json").read_bytes())
        self.owners = IMUBindingOwners()
        self.binder = self.new_binder()

    def new_binder(self, *, correlator=correlate, enabled=True, max_records=64, binding=None):
        return SourceOwnedIMUBinder(self.console_schema, self.ri_consumer,
            policy=SourceBindingPolicy(binding or self.binding, enabled, max_records),
            owners=self.owners, correlator=correlator)

    def produce(self, console, row):
        """Actual finite A03 intake and scoped A04 release, not a forged ref."""
        self.counter += 1
        folder = self.root / str(self.counter)
        folder.mkdir()
        spool = folder / "spool"
        spool.mkdir(mode=0o700)
        boot = row["temporal_binding"]["clock_domain_ref"]["boot_id_str"]
        scope = SourceScope(row["producer_str"], console["robot_id"], console["sensor_id"],
            console["source_id"], console["sensor_frame_id"], console["session_id"], boot)
        raw = canonical_json(row) + b"\n"
        path = spool / scope.filename
        path.write_bytes(raw)
        path.chmod(0o600)
        completed = {"state": "COMPLETED", "filename": scope.filename,
            "written": 1, "enqueued": 1, "written_bytes": len(raw),
            "history_committed": False, "actuation_enabled": False}
        preview = preview_spool(spool, scope, completed)
        self.assertEqual(preview.status, "PREVIEW", preview)
        store = EvidenceStore(folder / "store")
        report = apply_spool(store, spool, scope, completed,
                            expected_spool_sha256=preview.spool_sha256)
        self.assertEqual(report.status, "IMPORTED", report)
        observation, = store.observations.glob("*.json")
        ref = verified_ref_from_store(store, observation.stem)
        owner = object()
        reader = LocalEvidenceReader(store.root, owner=owner, clock_ns=self.clock)
        reader.register_evidence(owner, canonical_json(ref), purposes=frozenset({"cognition"}),
            retention_seconds=60, metadata_consent=True, payload_consent=True)
        channel = reader.grant(owner, ref["observation_id"], purpose="cognition",
                               ttl_seconds=30, payload=True, max_reads=5)
        view = reader.read(channel, ref["observation_id"], purpose="cognition", include_payload=True)
        self.assertEqual((view.status, view.availability), ("PAYLOAD_RESOLVED", "AVAILABLE"))
        self.assertEqual(view.payload_bytes, canonical_json(row))
        return view, reader, owner, channel

    def bind(self, *, binder=None, view=None, sample=None, reference=None, payload=None, availability=None):
        v = view or self.view
        return (binder or self.binder).bind(self.owners.publisher, self.ri_owners.reader,
            reference=reference if reference is not None else json.loads(v.reference_json),
            sample=self.console if sample is None else sample,
            stored_payload=v.payload_bytes if payload is None else payload,
            availability=v.availability if availability is None else availability)

    def altered(self, *, sequence=None, mono=None, temperature=None):
        console, row = deepcopy(self.console), deepcopy(self.row)
        original = row["payload"]["console_ingest_sample"]
        if sequence is not None:
            console["sequence"] = original["sequence"] = row["source"]["sample_sequence_uint"] = sequence
        if mono is not None:
            console["host_monotonic_ns"] = original["host_monotonic_ns"] = row["temporal_binding"]["received_monotonic_ns"] = mono
        if temperature is not None:
            console["temperature_c"] = original["temperature_c"] = temperature
        return console, row

    def raw_reference(self, payload):
        return dict(self.ref, payload_size_bytes=len(payload),
                    payload_sha256_hex=hashlib.sha256(payload).hexdigest())

    def test_reviewed_owner_blob_pins(self):
        for path, expected in (
            (CONSOLE / "scripts/ri_periph_compat.py", CONSOLE_MATCHER_BLOB),
            (RI / "src/reality_ingress/evidence_access.py", "42cf218b38b49083e2201e10fa2f33bba94ed6df"),
        ):
            raw = path.read_bytes()
            self.assertEqual(hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest(), expected)

    def test_actual_a03_a04_console_and_c1_share_the_same_evidence_reference(self):
        before = canonical_json(self.console), self.view.payload_bytes
        result = self.bind()
        self.assertEqual(result["status"], "ASSOCIATED_SOURCE_CONTENT")
        association = result["association"]
        engine = ImuAttention(self.binding, clock=self.clock)
        observed = engine.observe(self.console, received_ns=self.clock.value, freshness="FRESH",
            consent=True, context_revision="sha256:" + "c" * 64, allow_goal_generation=True)
        self.assertEqual(observed["status"], "OBSERVED")
        for n in (1, 2):
            self.clock.value += 100_000_000
            sample, _ = self.altered(sequence=self.console["sequence"] + n,
                                     mono=self.console["host_monotonic_ns"] + n * 100_000_000)
            observed = engine.observe(sample, received_ns=self.clock.value, freshness="FRESH",
                consent=True, context_revision="sha256:" + "c" * 64, allow_goal_generation=True)
        self.assertEqual(observed["status"], "CUE")
        self.assertIn(association["c1_evidence_ref"], observed["cue"]["source_refs"])
        self.assertEqual(before, (canonical_json(self.console), self.view.payload_bytes))
        self.assertEqual(association["observation_id"], self.ref["observation_id"])
        self.assertEqual(association["origin"], "SYNTHETIC")
        self.assertEqual(association["freshness"], "UNKNOWN")
        self.assertFalse(association["can_generate_goal"])
        self.assertFalse(association["console_boot_verified"])
        self.assertFalse(association["grants_authority"])
        self.assertIsNone(association["life_id"])
        self.assertNotIn("payload", association)
        self.assertFalse(self.binder.inspect()["work_connected"])

    def test_generalized_source_profile_preserves_assembly_metadata_without_truth_claim(self):
        row = deepcopy(self.row)
        row["producer_str"] = GENERALIZED
        row["payload"].update(assembly_policy="strict-no-reuse", synchronized=False,
            component_receipt_ages_ns={"acceleration": 10, "angular_velocity": 5, "vendor_euler": 0},
            host_receipt_span_ns=10)
        view, *_ = self.produce(self.console, row)
        result = self.bind(view=view)
        self.assertEqual(result["status"], "ASSOCIATED_SOURCE_CONTENT")
        self.assertEqual(result["association"]["time_alignment"], "NOT_ESTABLISHED")
        self.assertNotIn("synchronized", result["association"])

    def test_console_matcher_current_pilot_scope_is_not_silently_generalized(self):
        sample, row = deepcopy(self.console), deepcopy(self.row)
        sample["robot_id"] = row["payload"]["console_ingest_sample"]["robot_id"] = "other-robot"
        view, *_ = self.produce(sample, row)
        binding = replace(self.binding, console_robot_alias="other-robot")
        with self.assertRaisesRegex(SourceBindingError, "SOURCE_CONTENT_NOT_MATCHED"):
            self.bind(binder=self.new_binder(binding=binding), view=view, sample=sample)

    def test_default_disabled_and_denied_policy_do_not_invoke_correlator(self):
        def forbidden(*args): raise AssertionError("should not be called")
        default = SourceBindingPolicy(self.binding)
        self.assertFalse(default.enabled)
        with self.assertRaisesRegex(SourceBindingError, "SOURCE_BINDER_DISABLED"):
            self.bind(binder=self.new_binder(enabled=False, correlator=forbidden))
        self.ri_consumer.policy = replace(self.ri_consumer.policy, payload_access=False)
        with self.assertRaisesRegex(SourceBindingError, "SOURCE_ACCESS_NOT_GRANTED"):
            self.bind(binder=self.new_binder(correlator=forbidden))
        self.assertEqual(self.ri_consumer.inspect()["seen_count"], 0)

    def test_foreign_channels_fail_before_data_processing(self):
        with self.assertRaisesRegex(SourceBindingError, "SOURCE_CHANNEL_REQUIRED"):
            self.binder.bind(object(), object(), reference={}, sample={}, stored_payload=b"",
                             availability="AVAILABLE")

    def test_metadata_only_is_not_a_checked_payload(self):
        channel = self.reader.grant(self.reader_owner, self.ref["observation_id"],
            purpose="cognition", ttl_seconds=30)
        meta = self.reader.read(channel, self.ref["observation_id"], purpose="cognition")
        self.assertEqual((meta.status, meta.availability), ("REFERENCE_ONLY", "UNKNOWN"))
        with self.assertRaisesRegex(SourceBindingError, "SOURCE_EVIDENCE_UNAVAILABLE"):
            self.bind(view=meta)
        with self.assertRaisesRegex(SourceBindingError, "SOURCE_REFERENCE_BYTES_MISMATCH"):
            self.bind(reference=json.loads(meta.reference_json))
        self.assertEqual(self.ri_consumer.inspect()["seen_count"], 0)

    def test_existing_metadata_to_payload_collision_is_preserved(self):
        metadata = dict(self.ref, integrity_status="not_verified")
        first = self.ri_consumer.accept(self.ri_owners.reader, metadata, evidence_state="UNKNOWN")
        self.assertEqual(first["status"], "ACCEPTED_REFERENCE")
        with self.assertRaisesRegex(SourceBindingError, "RI_REFERENCE_ACCESS_OR_CONFLICT"):
            self.bind()
        self.assertEqual(self.ri_consumer.inspect()["seen_count"], 1)
        self.assertEqual(self.binder.inspect()["associations"], 0)

    def test_exact_replay_is_inert_and_rechecks_ri_consumer(self):
        self.bind()
        self.assertEqual(self.bind(), {"status": "DUPLICATE", "association": None})
        self.assertEqual(self.binder.inspect()["associations"], 1)
        self.ri_consumer.close()
        with self.assertRaisesRegex(SourceBindingError, "RI_REFERENCE_ACCESS_OR_CONFLICT"):
            self.bind()

    def test_changed_duplicate_sample_is_not_accepted(self):
        self.bind()
        sample = deepcopy(self.console)
        sample["angular_velocity_rad_s"][0] += 0.1
        with self.assertRaisesRegex(SourceBindingError, "SOURCE_CONTENT_NOT_MATCHED"):
            self.bind(sample=sample)

    def test_same_source_session_sequence_different_record_conflicts(self):
        self.bind()
        sample, row = self.altered(temperature=25.0)
        view, *_ = self.produce(sample, row)
        with self.assertRaisesRegex(SourceBindingError, "SOURCE_ASSOCIATION_CONFLICT"):
            self.bind(view=view, sample=sample)
        self.assertEqual(self.ri_consumer.inspect()["seen_count"], 1)

    def test_session_mismatch_and_source_scope_are_rejected(self):
        for field, value in (("session_id", "b" * 32), ("source_id", "foreign-source")):
            sample = dict(self.console, **{field: value})
            with self.assertRaisesRegex(SourceBindingError, "SOURCE_SCOPE_MISMATCH"):
                self.bind(sample=sample)

    def test_revoked_a04_result_cannot_be_mapped_to_available(self):
        self.reader.revoke(self.reader_owner, self.channel)
        blocked = self.reader.read(self.channel, self.ref["observation_id"],
                                   purpose="cognition", include_payload=True)
        self.assertEqual(blocked.availability, "NOT_AUTHORIZED")
        self.assertIsNone(blocked.payload_bytes)
        with self.assertRaisesRegex(SourceBindingError, "SOURCE_EVIDENCE_UNAVAILABLE"):
            self.bind(availability=blocked.availability)

    def test_expired_a04_result_is_not_an_erasure_or_freshness_claim(self):
        self.clock.value += 30_000_000_000
        blocked = self.reader.read(self.channel, self.ref["observation_id"],
                                   purpose="cognition", include_payload=True)
        self.assertEqual((blocked.reason, blocked.availability), ("LEASE_EXPIRED", "NOT_AUTHORIZED"))
        self.assertFalse(blocked.erasure_verified)
        with self.assertRaisesRegex(SourceBindingError, "SOURCE_EVIDENCE_UNAVAILABLE"):
            self.bind(availability=blocked.availability)
        self.clock.value += 30_000_000_000
        retained = self.reader.read(self.channel, self.ref["observation_id"],
                                   purpose="cognition", include_payload=True)
        self.assertEqual((retained.reason, retained.availability), ("RETENTION_EXPIRED", "EXPIRED"))
        self.assertFalse(retained.erasure_verified)

    def test_precision_above_javascript_safe_integer_and_c1_ceiling(self):
        for value in ((1 << 53) + 1, (1 << 63) - 1):
            sample, row = self.altered(sequence=value, mono=value)
            view, *_ = self.produce(sample, row)
            result = self.bind(sample=sample, view=view)
            self.assertEqual(result["status"], "ASSOCIATED_SOURCE_CONTENT")
            self.assertEqual(json.loads(view.payload_bytes)["source"]["sample_sequence_uint"], value)
        sample, row = self.altered(sequence=1 << 63, mono=1 << 63)
        view, *_ = self.produce(sample, row)  # RI native-u64 accepts this domain.
        with self.assertRaisesRegex(SourceBindingError, "SOURCE_INPUT_INVALID"):
            self.bind(sample=sample, view=view)  # Existing C1 intentionally narrower.

    def test_native_wall_counter_and_boolean_bounds_are_independent(self):
        row = deepcopy(self.row)
        row["temporal_binding"]["received_unix_estimate_ns"] = MAX_NATIVE_U64
        view, *_ = self.produce(self.console, row)
        self.assertEqual(self.bind(view=view)["status"], "ASSOCIATED_SOURCE_CONTENT")
        for invalid in (MAX_NATIVE_U64 + 1, True, -1):
            row["temporal_binding"]["received_unix_estimate_ns"] = invalid
            raw = canonical_json(row)
            with self.assertRaisesRegex(SourceBindingError, "SOURCE_INTEGER_DOMAIN"):
                self.bind(reference=self.raw_reference(raw), payload=raw)

    def test_receipt_bracket_boundary_is_not_clock_qualification(self):
        row = deepcopy(self.row)
        row["temporal_binding"]["host_wall_pair_span_ns"] = 50_000_000
        view, *_ = self.produce(self.console, row)
        self.assertEqual(self.bind(view=view)["association"]["time_alignment"], "NOT_ESTABLISHED")
        row["temporal_binding"]["host_wall_pair_span_ns"] += 1
        raw = canonical_json(row)
        with self.assertRaisesRegex(SourceBindingError, "SOURCE_RECEIPT_BRACKET"):
            self.bind(reference=self.raw_reference(raw), payload=raw)

    def test_corrupt_bytes_oversize_duplicate_keys_and_noncanonical_json_fail(self):
        for raw in (self.view.payload_bytes + b"x", b"x" * 4097,
                    b'{"a":1,"a":2}', self.view.payload_bytes + b" ",
                    b'{"x":NaN}', b'{"x":' + b'[' * 30 + b'0' + b']' * 30 + b'}'):
            with self.assertRaises(SourceBindingError):
                self.bind(payload=raw, reference=self.raw_reference(raw))
        self.assertEqual(self.ri_consumer.inspect()["seen_count"], 0)

    def test_previous_normalized_copy_profile_is_not_rewritten(self):
        row = deepcopy(self.row)
        row["payload"] = {"representation_profile": "cog-ri-02.console-copy.v0.1-candidate",
                          "console_imu_record": deepcopy(self.console)}
        raw = canonical_json(row)
        with self.assertRaisesRegex(SourceBindingError, "SOURCE_PROFILE_UNSUPPORTED"):
            self.bind(payload=raw, reference=self.raw_reference(raw))
        self.assertEqual(row["payload"]["console_imu_record"], self.console)

    def test_unknown_source_profile_is_not_implicitly_adopted(self):
        for label in ("future-source-profile", {"claimed": "producer"}, None):
            row = dict(self.row, producer_str=label)
            raw = canonical_json(row)
            with self.assertRaisesRegex(SourceBindingError, "SOURCE_PROFILE_UNSUPPORTED"):
                self.bind(payload=raw, reference=self.raw_reference(raw))

    def test_successor_producer_version_needs_owner_adoption(self):
        # Public synthetic counterexample. No private publisher code executes.
        successor = GENERALIZED.replace("0.1.0a4", "0.1.0a5")
        with self.assertRaisesRegex(IntakeError, "UNSUPPORTED_PRODUCER_PROFILE"):
            SourceScope(successor, self.console["robot_id"], self.console["sensor_id"],
                self.console["source_id"], self.console["sensor_frame_id"],
                self.console["session_id"], self.ref["time"]["boot_id"])
        row = dict(self.row, producer_str=successor)
        raw = canonical_json(row)
        with self.assertRaisesRegex(SourceBindingError, "SOURCE_PROFILE_UNSUPPORTED"):
            self.bind(payload=raw, reference=self.raw_reference(raw))

    def test_source_authority_or_clock_claims_are_refused(self):
        for field in ("source_verified", "robot_binding_verified", "history_committed", "actuation_enabled"):
            with self.assertRaises(SourceBindingError):
                self.bind(reference=dict(self.ref, **{field: True}))
        wrong = deepcopy(self.ref)
        wrong["time"]["chronograf_anchor_ref"] = "invented"
        with self.assertRaises(SourceBindingError): self.bind(reference=wrong)

    def test_matcher_failure_and_overclaimed_result_are_redacted(self):
        def broken(*args): raise RuntimeError("private/path-and-payload")
        with self.assertRaisesRegex(SourceBindingError, "^SOURCE_CORRELATOR_FAILED$"):
            self.bind(binder=self.new_binder(correlator=broken))
        def overclaim(*args): return dict(correlate(*args), source_verified=True)
        with self.assertRaisesRegex(SourceBindingError, "SOURCE_CONTENT_NOT_MATCHED"):
            self.bind(binder=self.new_binder(correlator=overclaim))
        self.assertEqual(self.ri_consumer.inspect()["seen_count"], 0)

    def test_borrowed_inputs_are_snapshotted_before_either_validator(self):
        # Model a producer reusing caller-owned dictionaries after the real
        # Console validation step. The reviewed matcher must see one already
        # captured, revalidated snapshot, not a later mixed presentation.
        sample, reference = deepcopy(self.console), deepcopy(self.ref)
        original_sample = deepcopy(sample)
        validate = imu_binding.validate_c1
        def validate_then_caller_mutates(kind, value):
            checked = validate(kind, value)
            sample["motion_hint"] = "PRIVATE_MUTATED_AFTER_VALIDATION"
            reference["time"]["boot_id"] = "PRIVATE_MUTATED_BOOT"
            return checked
        with patch.object(imu_binding, "validate_c1", side_effect=validate_then_caller_mutates):
            result = self.bind(sample=sample, reference=reference)
        self.assertEqual(result["status"], "ASSOCIATED_SOURCE_CONTENT")
        expected = c1_digest({"scope": vars(self.binding),
                              "payload_digest": c1_digest(original_sample)})
        self.assertEqual(result["association"]["c1_evidence_ref"], expected)
        self.assertNotIn("PRIVATE_MUTATED", str(result))
        self.assertEqual(self.ri_consumer.inspect()["seen_count"], 1)

    def test_ri_consumer_clock_exception_is_redacted_without_association(self):
        def broken_clock():
            raise OSError("PRIVATE_TEST_PATH/clock-source")
        self.ri_consumer.clock_ns = broken_clock
        with self.assertRaisesRegex(SourceBindingError, "^RI_REFERENCE_ACCESS_OR_CONFLICT$"):
            self.bind()
        self.assertEqual(self.ri_consumer.inspect()["seen_count"], 0)
        self.assertEqual(self.binder.inspect()["associations"], 0)

    def test_association_path_performs_no_io_or_process_launch(self):
        with patch("builtins.open", side_effect=AssertionError("file IO")), \
             patch.object(Path, "open", side_effect=AssertionError("path IO")), \
             patch.object(socket, "socket", side_effect=AssertionError("network IO")), \
             patch.object(subprocess, "Popen", side_effect=AssertionError("process IO")):
            result = self.bind()
        self.assertEqual(result["status"], "ASSOCIATED_SOURCE_CONTENT")

    def test_backpressure_preserves_prior_references_and_close_is_terminal(self):
        binder = self.new_binder(max_records=1)
        self.bind(binder=binder)
        sample, row = self.altered(sequence=8, mono=123456790)
        view, *_ = self.produce(sample, row)
        with self.assertRaisesRegex(SourceBindingError, "SOURCE_ASSOCIATION_BACKPRESSURE"):
            self.bind(binder=binder, sample=sample, view=view)
        self.assertEqual(self.ri_consumer.inspect()["seen_count"], 1)
        binder.close()
        self.assertEqual(binder.inspect()["associations"], 0)
        with self.assertRaisesRegex(SourceBindingError, "SOURCE_BINDER_CLOSED"):
            self.bind(binder=binder)


if __name__ == "__main__":
    unittest.main(verbosity=2)
