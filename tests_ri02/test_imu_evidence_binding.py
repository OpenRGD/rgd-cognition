"""RI-02 exact-source binding, from genuine RI v0.4 producer to COG consumer.

All IMU numeric readings and RI payloads are SYNTHETIC; no device/network/Chronon.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from reality_ingress.consumer_ref import verified_ref_from_store, unverified_ref_from_envelope
from reality_ingress.evidence import EvidenceStore
from reality_ingress.generic import SAMPLE_SCHEMA, MEDIA_TYPE, canonical_json, record_sample
from rgd_cognition.attention_c1 import AttentionPolicy, ImuAttention
from rgd_cognition.attention_c1_demo import fixture_binding, fixture_sample
from rgd_cognition.ri_observation_ref import (
    RIReferenceContract, RIReferenceConsumer, RIHostPolicy, RILocalOwners,
)
from rgd_cognition.ri_imu_binding import (
    CONSOLE_SCHEMA_BLOB, CONSOLE_SOURCE_COMMIT, ConsoleImuSchema,
    IMUBindingOwners, IMUBindingPolicy, RIImuEvidenceBinder,
    ImuBindingError, STORED_PROFILE, _decode, _canonical, validate_binding_record,
)

RI = Path(os.environ["RI_CHECKOUT"])
CONSOLE = Path(os.environ["CONSOLE_CHECKOUT"])
RI_SCHEMA = (RI / "contracts/consumer-observation-ref.v0.1-candidate.schema.json").read_bytes()
CONSOLE_SCHEMA = (CONSOLE / "contracts/console/v1/imu-observation.v0.1.schema.json").read_bytes()


class Clock:
    def __init__(self, now): self.now = now
    def __call__(self): return self.now
    def advance(self, milliseconds): self.now += milliseconds * 1000000


class BindingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = EvidenceStore(Path(self.temp.name) / "ri-store")
        self.binding = fixture_binding()
        self.sample = fixture_sample(7,rate=0.55)
        self.console_contract = ConsoleImuSchema(CONSOLE_SCHEMA)
        self.ri_contract = RIReferenceContract(RI_SCHEMA)
        self.stamp_ns = self.sample["host_monotonic_ns"] + 2_000_000
        self.stamp = {
            "received_monotonic_ns": self.stamp_ns,
            "received_unix_estimate_ns": 0,
            "host_wall_pair_span_ns": 0,
            "clock_domain_ref": {"clock_kind_enum_str": "MONOTONIC",
                                 "clock_domain_id_str": "chronos.monotonic.boot:fixture-boot",
                                 "boot_id_str": "fixture-boot"},
            "source_time": None,
            "source_time_status_str": "UNKNOWN_NOT_EXPOSED_BY_SOURCE",
        }
        self.clock = Clock(self.stamp_ns + 1_000_000)
        self.ri_owners = RILocalOwners()
        self.ri_policy = RIHostPolicy(
            local_alias=self.binding.local_alias,
            allowed_source_id=self.sample["source_id"],
            allowed_modality="imu",
            allowed_frame_id=self.sample["sensor_frame_id"],
            clock_domain_id="chronos.monotonic.boot:fixture-boot",
            boot_id="fixture-boot", same_boot_clock_trusted=True,
            metadata_access=True,consent=True,payload_access=True,
            max_age_ms=3000,max_records=32,
        )
        self.owners = IMUBindingOwners()
        self.binder = self.make_binder()
        self.ref, self.raw = self.make_record(self.sample)

    def tearDown(self):
        self.temp.cleanup()

    def make_binder(self, *, policy=None, ri_policy=None):
        consumer = RIReferenceConsumer(self.ri_contract, policy=ri_policy or self.ri_policy,
                                       owners=self.ri_owners, clock_ns=self.clock)
        return RIImuEvidenceBinder(self.console_contract, consumer,
                                   owners=self.owners, clock_ns=self.clock,
                                   policy=policy or IMUBindingPolicy(
                                       source_binding=self.binding,
                                       same_boot_publisher_and_ri_asserted=True,
                                       max_receipt_lag_ms=3000, max_records=32))

    def make_record(self, sample, *, override=None):
        stamp = deepcopy(self.stamp)
        if override: stamp.update(override)
        row={
            "schema_ref_str": SAMPLE_SCHEMA,
            "producer_str": "fixture.console.normalized.readonly",
            "source": {
                "source_id_str": sample["source_id"],
                "modality_str": "imu",
                "reference_frame_id_str": sample["sensor_frame_id"],
                "sample_sequence_uint": sample["sequence"],
            },
            "temporal_binding": stamp,
            "payload": {"representation_profile": STORED_PROFILE,
                        "console_imu_record": deepcopy(sample)}
        }
        envelope, _ = record_sample(self.store, row)
        ref=verified_ref_from_store(self.store,envelope["observation_id_str"])
        return ref,canonical_json(row)

    def accept(self, ref=None, sample=None, raw=None, availability="AVAILABLE",
               binder=None, owner=None, reader=None):
        return (binder or self.binder).bind(
            self.owners.publisher if owner is None else owner,
            self.ri_owners.reader if reader is None else reader,
            reference=self.ref if ref is None else ref,
            sample=self.sample if sample is None else sample,
            stored_payload=self.raw if raw is None else raw,
            availability=availability)

    def test_schema_pins_and_real_ri_producer_fixture(self):
        self.assertEqual(CONSOLE_SOURCE_COMMIT,"a0ef857cf425c1bb14ad8f62acec21f8c1324866")
        blob=hashlib.sha1(b"blob " + str(len(CONSOLE_SCHEMA)).encode() + b"\0" + CONSOLE_SCHEMA).hexdigest()
        self.assertEqual(blob, CONSOLE_SCHEMA_BLOB)
        self.assertEqual(self.console_contract.validate(self.sample), self.sample)
        self.assertEqual(self.ref["payload_sha256_hex"],hashlib.sha256(self.raw).hexdigest())
        self.assertEqual(self.ref["payload_media_type"],MEDIA_TYPE)
        self.assertFalse(self.ref["source_verified"])
        with self.assertRaisesRegex(ImuBindingError,"CONSOLE_SCHEMA_PIN_MISMATCH"):
            ConsoleImuSchema(CONSOLE_SCHEMA+b" ")

    def test_actual_RI_generic_payload_corresponds_to_exact_console_record(self):
        output = self.accept()
        self.assertEqual(output["status"],"CONTENT_MATCHED")
        b = validate_binding_record(output["binding"])
        self.assertEqual(b["ri_observation_id"],self.ref["observation_id"])
        self.assertEqual(b["ri_payload_sha256_hex"],self.ref["payload_sha256_hex"])
        self.assertEqual(b["console_sample_sha256_hex"],hashlib.sha256(_canonical(self.sample)).hexdigest())
        self.assertEqual(b["source_session_id"],self.sample["session_id"])
        self.assertEqual(b["sample_sequence"],7)
        self.assertEqual(b["frame_id"],self.sample["sensor_frame_id"])
        self.assertEqual(b["byte_relation"],"EXACT_STORED_NORMALIZED_COPY")
        self.assertEqual(b["clock_relation"],"HOST_SAME_BOOT_ASSERTED")
        self.assertEqual(b["freshness"],"FRESH")
        self.assertEqual(b["source_authentication"],"NOT_VERIFIED")
        self.assertFalse(b["decision_eligible"])
        self.assertFalse(b["can_generate_goal"])
        self.assertFalse(b["may_actuate"])
        self.assertIsNone(b["life_id"])
        self.assertIsNone(b["chronon_id"])
        self.assertEqual(self.binder.inspect()["seen_count"],1)

    def test_c1_real_detector_reference_is_locally_reproducible_not_an_RI_id(self):
        b=self.accept()["binding"]
        attn_clock=Clock(self.sample["host_monotonic_ns"]+10_000_000)
        detector=ImuAttention(self.binding,policy=AttentionPolicy(cooldown_ms=100),clock=attn_clock)
        out=None
        for index in (5,6,7):
            sample=fixture_sample(index, rate=0.55)
            attn_clock.advance(100)
            out=detector.observe(sample,received_ns=attn_clock(),freshness="FRESH",
                consent=True,context_revision="sha256:"+"3"*64,allow_goal_generation=True)
        self.assertEqual(out["status"],"CUE")
        self.assertIn(b["c1_local_evidence_ref"],out["cue"]["source_refs"])
        self.assertEqual(out["cue"]["origin"],"SYNTHETIC")
        self.assertFalse(out["cue"]["may_actuate"])
        self.assertNotEqual(b["c1_local_evidence_ref"],b["ri_observation_id"])

    def test_not_an_inputevent_or_goal_and_no_reinterpretation(self):
        from rgd_cognition.contracts import validate,ContractError
        b=self.accept()["binding"]
        for contract in ("InputEvent","CognitiveProposal"):
            with self.assertRaises(ContractError):validate(contract,b)
        self.assertFalse(b["grants_authority"])
        self.assertEqual(b["sensor_calibration"],"UNVERIFIED")

    def test_duplicate_is_inert_and_no_reread(self):
        before=self.accept()["binding"]
        self.assertEqual(self.accept(),{"status":"DUPLICATE","binding":None})
        self.assertEqual(self.binder.inspect()["seen_count"],1)
        self.assertIsNotNone(before)

    def test_same_session_and_sequence_with_changed_evidence_conflicts(self):
        self.accept()
        changed=deepcopy(self.sample);changed["orientation_euler_deg"]=[1,2,3]
        changed_ref, changed_raw = self.make_record(changed)
        with self.assertRaisesRegex(ImuBindingError,"EVIDENCE_BINDING_COLLISION"):
            self.accept(ref=changed_ref,sample=changed,raw=changed_raw)
        self.assertEqual(self.binder.inspect()["seen_count"],1)

    def test_payload_modification_or_mutated_console_is_refused(self):
        wrong=deepcopy(self.sample);wrong["angular_velocity_rad_s"][0]=0.72
        with self.assertRaisesRegex(ImuBindingError,"CONSOLE_BYTES_NOT_IDENTICAL"):
            self.accept(sample=wrong)
        with self.assertRaises(ImuBindingError):
            self.accept(raw=self.raw+b" ")
        with self.assertRaises(ImuBindingError):
            self.accept(raw=self.raw.replace(b"fixture-publisher",b"another-publisher"))
        self.assertEqual(self.binder.inspect()["seen_count"],0)

    def test_source_sensor_frame_session_sequence_are_exactly_bound(self):
        for key,value in (("sensor_id","other-imu"),("source_id","other-source"),
                          ("sensor_frame_id","frame.other"),("session_id","b"*32)):
            s=deepcopy(self.sample);s[key]=value
            with self.subTest(key=key),self.assertRaisesRegex(ImuBindingError,"CONSOLE_SOURCE_SCOPE_MISMATCH"):
                self.accept(sample=s)
        s=deepcopy(self.sample);s["sequence"]=9
        with self.assertRaisesRegex(ImuBindingError,"CONSOLE_BYTES_NOT_IDENTICAL"):
            self.accept(sample=s)

    def test_fake_verified_identity_and_chronograf_claims_denied(self):
        r=deepcopy(self.ref);r["source_verified"]=True
        with self.assertRaises(ImuBindingError):self.accept(ref=r)
        r=deepcopy(self.ref);r["robot_binding_verified"]=True
        with self.assertRaises(ImuBindingError):self.accept(ref=r)
        r=deepcopy(self.ref);r["time"]["chronograf_anchor_ref"]="fake"
        with self.assertRaises(ImuBindingError):self.accept(ref=r)
        self.assertEqual(self.binder.inspect()["seen_count"],0)

    def test_foreign_boot_alignment_does_not_claim_freshness(self):
        p=RIHostPolicy(**{**vars(self.ri_policy),"same_boot_clock_trusted":False})
        h=self.make_binder(ri_policy=p)
        bound=self.accept(binder=h)["binding"]
        self.assertEqual(bound["clock_relation"],"NOT_ESTABLISHED")
        self.assertEqual(bound["freshness"],"UNKNOWN")
        self.assertFalse(bound["can_generate_goal"])

    def test_late_ingest_marks_stale_without_renewal(self):
        self.clock.advance(4000)
        bound=self.accept()["binding"]
        self.assertEqual(bound["clock_relation"],"HOST_SAME_BOOT_ASSERTED")
        self.assertEqual(bound["freshness"],"STALE")
        self.assertFalse(bound["can_generate_goal"])

    def test_unaligned_console_clock_is_not_falsely_compared(self):
        altered=deepcopy(self.sample)
        altered["host_monotonic_ns"]=self.stamp_ns+1_000_000
        ref,raw=self.make_record(altered)
        bound=self.accept(ref=ref,sample=altered,raw=raw)["binding"]
        self.assertEqual(bound["clock_relation"],"NOT_ESTABLISHED")
        self.assertEqual(bound["freshness"],"UNKNOWN")

    def test_unsupported_presentation_wont_be_mapped_as_sensor_sample(self):
        d=_decode(self.raw);d["payload"]["representation_profile"]="camera.frame"
        other=_canonical(d)
        with self.assertRaisesRegex(ImuBindingError,"UNSUPPORTED_STORED_PROFILE"):
            self.accept(raw=other)
        d=_decode(self.raw);d["payload"]["console_imu_record"]["decision_eligible"]=True
        with self.assertRaises(ImuBindingError):self.accept(raw=_canonical(d))

    def test_no_evidence_no_binding(self):
        for state in ("UNAVAILABLE","UNKNOWN","REDACTED","ERASED","NOT_AUTHORIZED"):
            with self.subTest(state=state),self.assertRaisesRegex(ImuBindingError,"EVIDENCE_NOT_AVAILABLE"):
                self.accept(availability=state)
        self.assertEqual(self.binder.inspect()["seen_count"],0)

    def test_denied_consent_and_acl_refuse_binding(self):
        for key in ("consent","metadata_access","payload_access"):
            p=RIHostPolicy(**{**vars(self.ri_policy),key:False})
            b=self.make_binder(ri_policy=p)
            with self.subTest(key=key),self.assertRaisesRegex(ImuBindingError,"RI_ACCESS_NOT_GRANTED"):
                self.accept(binder=b)

    def test_untrusted_publisher_and_ri_reader_refused(self):
        with self.assertRaisesRegex(ImuBindingError,"UNAUTHORIZED_IMU_PUBLISHER"):
            self.accept(owner=object())
        with self.assertRaisesRegex(ImuBindingError,"UNAUTHORIZED_RI_READER"):
            self.accept(reader="reader")

    def test_unverified_ri_ref_preserves_its_claim(self):
        env=self.store.get_observation(self.ref["observation_id"])
        ref=unverified_ref_from_envelope(env)
        b=self.accept(ref=ref)["binding"]
        self.assertEqual(b["byte_relation"],"EXACT_STORED_NORMALIZED_COPY")
        self.assertFalse(ref["source_verified"])
        self.assertEqual(ref["integrity_status"],"not_verified")

    def test_no_new_evidence_store_or_unsafe_imports(self):
        from rgd_cognition import ri_imu_binding
        import inspect
        body=inspect.getsource(ri_imu_binding)
        for string in ("from reality_ingress", "import serial", "import cv2", "import requests", "subprocess.run", "socket.socket", "os.system"):
            self.assertNotIn(string,body)
        # Code under test accesses in-memory dict/bytes only.
        with patch.object(socket,"socket",side_effect=AssertionError("network")),patch.object(subprocess,"Popen",side_effect=AssertionError("process")):
            self.assertEqual(self.accept()["status"],"CONTENT_MATCHED")

    def test_record_schema_wont_accept_positive_authority(self):
        b=self.accept()["binding"]
        for key,value in (("decision_eligible",True),("may_actuate",True),
                          ("can_generate_goal",True),("life_id","life:x"),
                          ("robot_binding_verified",True), ("clock_relation","CHRONOGRAF_VERIFIED")):
            other=deepcopy(b);other[key]=value
            with self.subTest(key=key),self.assertRaisesRegex(ImuBindingError,"INVALID_BINDING_RECORD"):
                validate_binding_record(other)

    def test_bounded_backpressure_and_close(self):
        policy=IMUBindingPolicy(source_binding=self.binding,max_records=1,same_boot_publisher_and_ri_asserted=True)
        b=self.make_binder(policy=policy)
        self.assertEqual(self.accept(binder=b)["status"],"CONTENT_MATCHED")
        sample=fixture_sample(8,rate=0.55)
        ref,raw=self.make_record(sample)
        with self.assertRaisesRegex(ImuBindingError,"BINDING_BACKPRESSURE"):
            self.accept(binder=b,ref=ref,sample=sample,raw=raw)
        b.close()
        with self.assertRaisesRegex(ImuBindingError,"BINDER_CLOSED"):
            self.accept(binder=b)

    def test_noncanonical_or_duplicate_key_cannot_be_accepted(self):
        with self.assertRaisesRegex(ImuBindingError,"DUPLICATE_KEY"):
            _decode(b'{"a":1,"a":2}')
        with self.assertRaises(ImuBindingError):_decode(b'{"a":NaN}')
        with self.assertRaises(ImuBindingError):_decode(self.raw+b"\n")

    def test_binding_never_claims_physical_step_or_autonomous_goal(self):
        from rgd_cognition.core_b_adapter import TASKS
        b=self.accept()["binding"]
        self.assertEqual(set(TASKS),{"cog.task.v1:imu-uncertainty","cog.task.v1:oneiric-first-step"})
        self.assertFalse(b["can_generate_goal"])
        self.assertIsNone(b["life_id"])
        self.assertEqual(self.binder.inspect()["work_connected"],False)

    def test_wrong_ri_schema_bytes_refused(self):
        with self.assertRaises(ValueError): RIReferenceContract(RI_SCHEMA+b" ")
        # Console and RI schemas have deliberately independent exact pins.
        with self.assertRaises(ImuBindingError): ConsoleImuSchema(RI_SCHEMA)

    def test_none_or_foreign_types_never_qualify(self):
        with self.assertRaises(ImuBindingError):
            self.accept(raw=b"{}")
        with self.assertRaises(ImuBindingError):
            self.accept(sample={})
        with self.assertRaises(ImuBindingError):
            self.accept(ref={})

    def test_same_observation_id_different_document_rejected(self):
        self.accept()
        altered=deepcopy(self.ref);altered["sample_sequence"]=999
        with self.assertRaises(ImuBindingError):self.accept(ref=altered)


    def test_bindings_are_content_committed_and_cannot_be_forged(self):
        bound = self.accept()["binding"]
        broken = deepcopy(bound)
        broken["sample_sequence"] += 1
        with self.assertRaisesRegex(ImuBindingError,"BINDING_DIGEST_MISMATCH"):
            validate_binding_record(broken)
        broken = deepcopy(bound)
        broken["binding_ref"] = "sha256:" + "1"*64
        with self.assertRaisesRegex(ImuBindingError,"BINDING_DIGEST_MISMATCH"):
            validate_binding_record(broken)

    def test_ri_source_seq_and_frame_tampering_cannot_pass(self):
        broken=deepcopy(self.ref)
        for name, value in (("sample_sequence", 999),
                            ("reference_frame_id", "other"),
                            ("source_id", "other-source"),
                            ("payload_media_type", "image/jpeg")):
            candidate=deepcopy(broken)
            candidate[name]=value
            with self.subTest(name=name), self.assertRaises(ImuBindingError):
                self.accept(ref=candidate)

    def test_missing_boot_id_does_not_fabricate_alignment(self):
        # The same host can still match bytes without claiming synchronized time.
        alt = deepcopy(self.stamp)
        alt["clock_domain_ref"]["boot_id_str"] = "other-boot"
        ref,raw = self.make_record(self.sample,override=alt)
        result = self.accept(ref=ref,raw=raw)
        self.assertEqual(result["binding"]["clock_relation"],"NOT_ESTABLISHED")
        self.assertEqual(result["binding"]["freshness"],"UNKNOWN")
        self.assertFalse(result["binding"]["can_generate_goal"])

    def test_replayed_same_obs_cannot_rerefresh_after_staleness(self):
        result=self.accept()["binding"]
        self.assertEqual(result["freshness"],"FRESH")
        self.clock.advance(5000)
        duplicate=self.accept()
        self.assertEqual(duplicate,{"status":"DUPLICATE","binding":None})

    def test_source_kind_does_not_certify_physical_imu(self):
        self.assertEqual(self.sample["source_kind"],"physical")
        result=self.accept()["binding"]
        self.assertEqual(result["source_authentication"],"NOT_VERIFIED")
        self.assertFalse(result["robot_binding_verified"])
        self.assertEqual(result["sensor_calibration"],"UNVERIFIED")
        self.assertFalse(result["decision_eligible"])

    def test_ri_store_integrity_detection_is_separate_from_binder(self):
        env=self.store.get_observation(self.ref["observation_id"])
        digest=env["evidence"]["payload_sha256_hex_str"]
        self.store._payload_path(digest).write_bytes(b"corrupted")
        from reality_ingress.evidence import IntegrityError
        with self.assertRaises(IntegrityError):
            verified_ref_from_store(self.store,self.ref["observation_id"])
        # A stale *copy* from before corruption could still match supplied bytes.
        # That is why real RI freshness/revocation must remain a separate owner gate.
        b=self.accept()["binding"]
        self.assertEqual(b["source_authentication"],"NOT_VERIFIED")

    def test_source_byte_format_is_not_canonical_transport_proof(self):
        result=self.accept()["binding"]
        self.assertEqual(result["byte_relation"],"EXACT_STORED_NORMALIZED_COPY")
        self.assertNotIn("raw_sensor_payload_ref",result)
        self.assertNotIn("chronograf_anchor_ref",result)
        self.assertNotIn("model_id",result)

    def test_policy_unknown_or_unaligned_clock_never_promotes_freshness(self):
        pol=IMUBindingPolicy(self.binding, same_boot_publisher_and_ri_asserted=False)
        result=self.accept(binder=self.make_binder(policy=pol))["binding"]
        self.assertEqual(result["clock_relation"],"NOT_ESTABLISHED")
        self.assertEqual(result["freshness"],"UNKNOWN")

if __name__=="__main__":unittest.main()
