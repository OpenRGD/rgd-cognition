"""Genuine RI v0.4/PR4 producer -> COG local metadata consumer conformance.

Physical sensors are NOT used. The actual RI EvidenceStore writes synthetic
bytes only inside TemporaryDirectory for producer-fixture testing.
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
from reality_ingress.timebase import receive_stamp
from reality_ingress.generic import SAMPLE_SCHEMA, envelope_from_sample
from rgd_cognition.host import CognitiveHost
from rgd_cognition.contracts import ContractError, validate
from rgd_cognition.ri_observation_ref import (
    RIReferenceContract, RIHostPolicy, RILocalOwners, RIReferenceConsumer,
    RIRefError, RI_COMMIT, RI_SCHEMA_BLOB, validate_ri_notice,
)

RI = Path(os.environ["RI_CHECKOUT"])
CONTRACT = (RI / "contracts/consumer-observation-ref.v0.1-candidate.schema.json").read_bytes()


class Clock:
    def __init__(self, current=0):
        self.current = current
    def __call__(self):
        return self.current


class RIConsumerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = EvidenceStore(Path(self.temp.name) / "ri-evidence")
        self.payload = b"synthetic-camera-frame-contents"
        self.stamp = receive_stamp()
        self.envelope = self.store.record(
            data=self.payload, source_id="source.synthetic.camera", modality="rgb",
            reference_frame_id="frame.camera.synthetic", sequence=7,
            timestamp=self.stamp, media_type="image/jpeg",
            representation={"kind_str": "reencoded_jpeg_synthetic"},
        )
        self.ref = verified_ref_from_store(self.store, self.envelope["observation_id_str"])
        self.contract = RIReferenceContract(CONTRACT)
        self.clock = Clock(self.ref["time"]["received_monotonic_ns"] + 1_000_000)
        self.owners = RILocalOwners()
        self.policy = RIHostPolicy(
            local_alias="lab-robot", allowed_source_id=self.ref["source_id"],
            allowed_modality=self.ref["modality"],
            allowed_frame_id=self.ref["reference_frame_id"],
            clock_domain_id=self.ref["time"]["clock_domain_id"],
            boot_id=self.ref["time"]["boot_id"],
            same_boot_clock_trusted=self.ref["time"]["boot_id"] is not None,
            metadata_access=True, consent=True, payload_access=True,
            max_age_ms=3000, max_records=8)
        self.consumer = RIReferenceConsumer(self.contract, policy=self.policy,
                                            owners=self.owners, clock_ns=self.clock)

    def tearDown(self):
        self.temp.cleanup()

    def accept(self, ref=None, **kw):
        return self.consumer.accept(self.owners.reader, self.ref if ref is None else ref, **kw)

    def test_exact_ri_schema_blob_and_origin_remain_separate(self):
        self.assertEqual(len(RI_COMMIT), 40)
        size=len(CONTRACT)
        self.assertEqual(hashlib.sha1(b"blob " + str(size).encode() + b"\0" + CONTRACT).hexdigest(), RI_SCHEMA_BLOB)
        self.assertEqual(self.contract.validate(self.ref), self.ref)
        self.assertFalse(self.ref["source_verified"])
        self.assertFalse(self.ref["robot_binding_verified"])
        self.assertIsNone(self.ref["time"]["chronograf_anchor_ref"])
        self.assertEqual(self.ref["integrity_status"], "verified_local_hash")
        with self.assertRaisesRegex(RIRefError, "RI_SCHEMA_PIN_MISMATCH"):
            RIReferenceContract(CONTRACT + b" ")

    def test_real_ri_store_ref_to_inert_cog_notice_preserves_id_hash_frame_and_time(self):
        result=self.accept(evidence_state="AVAILABLE", payload_bytes=self.payload)
        self.assertEqual(result["status"], "ACCEPTED_REFERENCE")
        notice=result["notice"]
        validate_ri_notice(notice)
        self.assertEqual(notice["reference"], self.ref)
        self.assertEqual(notice["reference"]["observation_id"], self.envelope["observation_id_str"])
        self.assertEqual(notice["reference"]["payload_sha256_hex"], hashlib.sha256(self.payload).hexdigest())
        self.assertEqual(notice["reference"]["sample_sequence"],7)
        self.assertEqual(notice["reference"]["reference_frame_id"],"frame.camera.synthetic")
        self.assertEqual(notice["reference"]["time"],self.ref["time"])
        self.assertTrue(notice["payload_checked_at_cog"])
        self.assertFalse(notice["can_generate_goal"])
        self.assertFalse(notice["may_actuate"])
        self.assertIsNone(notice["life_id"])
        self.assertIsNone(notice["chronon_id"])
        self.assertEqual(notice["source_authentication"], "NOT_VERIFIED")
        self.assertEqual(notice["epistemic_status"], "UNKNOWN")
        self.assertEqual(notice["perception_status"], "NOT_CONNECTED")
        if self.ref["time"]["boot_id"] is not None:
            self.assertEqual(notice["freshness"], "FRESH")
        with self.assertRaises(ContractError):
            validate("InputEvent",notice)  # no implicit COG/Work input conversion

    def test_valid_hash_from_ri_does_not_authenticate_camera_or_robot(self):
        n=self.accept(evidence_state="AVAILABLE")["notice"]
        self.assertEqual(n["reference"]["integrity_status"],"verified_local_hash")
        self.assertFalse(n["reference"]["source_verified"])
        self.assertFalse(n["reference"]["robot_binding_verified"])
        self.assertFalse(n["reference"]["history_committed"])
        self.assertEqual(n["source_authentication"],"NOT_VERIFIED")
        self.assertFalse(n["payload_checked_at_cog"])

    def test_unverified_envelope_preserves_not_verified(self):
        ref=unverified_ref_from_envelope(self.envelope)
        n=self.accept(ref, evidence_state="UNKNOWN")["notice"]
        self.assertEqual(n["reference"]["integrity_status"],"not_verified")
        self.assertFalse(n["payload_checked_at_cog"])

    def test_missing_evidence_is_not_zero_or_false_observation(self):
        n=self.accept(evidence_state="UNAVAILABLE")["notice"]
        self.assertEqual(n["evidence_state"],"UNAVAILABLE")
        self.assertEqual(n["reference"]["payload_size_bytes"], len(self.payload))
        self.assertFalse(n["payload_checked_at_cog"])
        self.assertFalse(n["can_generate_goal"])

    def test_denied_consent_or_access_leaks_no_ref(self):
        for perm in ({"consent": False}, {"metadata_access": False}):
            cfg={**vars(self.policy), **perm}
            h=RIReferenceConsumer(self.contract,policy=RIHostPolicy(**cfg),owners=self.owners,clock_ns=self.clock)
            result=h.accept(self.owners.reader,self.ref,evidence_state="AVAILABLE")
            self.assertEqual(result, {"status":"BLOCKED","reason":"ACCESS_OR_CONSENT_DENIED","notice":None})
            self.assertEqual(h.inspect()["seen_count"],0)

    def test_redacted_and_erased_never_expose_media_ref(self):
        for state in ("REDACTED","ERASED","NOT_AUTHORIZED"):
            r=self.accept(evidence_state=state)
            self.assertEqual(r["status"],"BLOCKED")
            self.assertIsNone(r["notice"])
            self.assertEqual(self.consumer.inspect()["seen_count"],0)

    def test_untrusted_owner_and_model_role_claims_fail(self):
        with self.assertRaisesRegex(RIRefError,"UNAUTHORIZED_READER"):
            self.consumer.accept(object(),self.ref,evidence_state="AVAILABLE")
        with self.assertRaisesRegex(RIRefError,"UNAUTHORIZED_READER"):
            self.consumer.accept("reader",self.ref,evidence_state="AVAILABLE")

    def test_corrupt_payload_bytes_rejected_and_not_cached(self):
        with self.assertRaisesRegex(RIRefError,"PAYLOAD_DIGEST_MISMATCH"):
            self.accept(evidence_state="AVAILABLE",payload_bytes=b"tampered")
        self.assertEqual(self.consumer.inspect()["seen_count"],0)
        self.assertEqual(self.accept(evidence_state="AVAILABLE",payload_bytes=self.payload)["status"],"ACCEPTED_REFERENCE")

    def test_missing_payload_grant_rejected(self):
        cfg={**vars(self.policy),"payload_access":False}
        h=RIReferenceConsumer(self.contract,policy=RIHostPolicy(**cfg),owners=self.owners,clock_ns=self.clock)
        with self.assertRaisesRegex(RIRefError,"PAYLOAD_ACCESS_NOT_GRANTED"):
            h.accept(self.owners.reader,self.ref,evidence_state="AVAILABLE",payload_bytes=self.payload)

    def test_external_ghost_identity_and_time_claims_rejected(self):
        for path,val in (("source_verified", True),("robot_binding_verified",True),
                         ("history_committed",True),("actuation_enabled",True),
                         ("integrity_status","remote_attested"),
                         ("observation_id","invalid"),
                         ("time",{**self.ref["time"],"chronograf_anchor_ref":"fake"}),
                         ("unexpected_field", "tool:can")):
            c=deepcopy(self.ref); c[path]=val
            with self.subTest(path=path), self.assertRaisesRegex(RIRefError,"INVALID_RI_REFERENCE"):
                self.accept(c,evidence_state="AVAILABLE")

    def test_wrong_source_modality_frame_rejected(self):
        for field,val in (("source_id","foreign"),("modality","audio"),
                          ("reference_frame_id","frame.world")):
            c=deepcopy(self.ref); c[field]=val
            with self.subTest(field=field),self.assertRaisesRegex(RIRefError,"SOURCE_SCOPE_MISMATCH"):
                self.accept(c,evidence_state="AVAILABLE")

    def test_cross_host_monotonic_is_unknown_not_stale_or_fresh(self):
        cfg={**vars(self.policy),"same_boot_clock_trusted":False}
        h=RIReferenceConsumer(self.contract,policy=RIHostPolicy(**cfg),owners=self.owners,clock_ns=self.clock)
        n=h.accept(self.owners.reader,self.ref,evidence_state="AVAILABLE")["notice"]
        self.assertEqual(n["freshness"],"UNKNOWN")
        self.assertEqual(n["time_alignment"],"NOT_ESTABLISHED")
        self.assertIsNone(n["receipt_age_ns"])
        self.assertFalse(n["can_generate_goal"])

    def test_unknown_or_foreign_boot_cannot_be_fresh(self):
        c=deepcopy(self.ref);c["time"]["boot_id"]=None
        n=self.accept(c,evidence_state="AVAILABLE")["notice"]
        self.assertEqual(n["freshness"],"UNKNOWN")

    def test_stale_same_boot_is_stale_not_fresh(self):
        self.clock.current=self.ref["time"]["received_monotonic_ns"]+4_000_000_000
        n=self.accept(evidence_state="AVAILABLE")["notice"]
        if self.policy.same_boot_clock_trusted:
            self.assertEqual(n["freshness"],"STALE")
            self.assertGreaterEqual(n["receipt_age_ns"],4_000_000_000)
        else:self.assertEqual(n["freshness"],"UNKNOWN")
        self.assertFalse(n["can_generate_goal"])

    def test_future_sameboot_receipt_rejected(self):
        if not self.policy.same_boot_clock_trusted:self.skipTest("Host boot ID unavailable")
        self.clock.current=self.ref["time"]["received_monotonic_ns"]-1
        with self.assertRaisesRegex(RIRefError,"FUTURE_RECEIPT"):
            self.accept(evidence_state="AVAILABLE")

    def test_same_observation_exact_replay_inert_and_changed_digest_conflict(self):
        self.accept(evidence_state="AVAILABLE")
        self.clock.current+=4_000_000_000
        self.assertEqual(self.accept(evidence_state="AVAILABLE"),
                         {"status":"DUPLICATE","reason":"INERT_REPLAY","notice":None})
        changed=deepcopy(self.ref);changed["payload_sha256_hex"]="0"*64
        with self.assertRaisesRegex(RIRefError,"OBSERVATION_ID_COLLISION"):
            self.accept(changed,evidence_state="AVAILABLE")

    def test_corrupt_bytes_on_duplicate_still_rejected(self):
        self.accept(evidence_state="AVAILABLE",payload_bytes=self.payload)
        with self.assertRaisesRegex(RIRefError,"PAYLOAD_DIGEST_MISMATCH"):
            self.accept(evidence_state="AVAILABLE",payload_bytes=b"tampered")
        self.assertEqual(self.accept(evidence_state="AVAILABLE")["status"],"DUPLICATE")

    def test_foreign_clock_domain_never_qualifies_freshness(self):
        c=deepcopy(self.ref)
        c["time"]["clock_domain_id"]="foreign.clock.domain"
        n=self.accept(c,evidence_state="AVAILABLE")["notice"]
        self.assertEqual(n["freshness"],"UNKNOWN")
        self.assertEqual(n["time_alignment"],"NOT_ESTABLISHED")
        self.assertIsNone(n["receipt_age_ns"])

    def test_same_id_local_hash_status_upgrade_is_explicit_conflict(self):
        self.accept(unverified_ref_from_envelope(self.envelope))
        with self.assertRaisesRegex(RIRefError,"OBSERVATION_ID_COLLISION"):
            self.accept(self.ref)

    def test_bounded_backlog_and_no_early_key_eviction(self):
        cfg={**vars(self.policy),"max_records":1}
        h=RIReferenceConsumer(self.contract,policy=RIHostPolicy(**cfg),owners=self.owners,clock_ns=self.clock)
        self.assertEqual(h.accept(self.owners.reader,self.ref)["status"],"ACCEPTED_REFERENCE")
        ref2=deepcopy(self.ref);ref2["observation_id"]="obs_"+"f"*32
        with self.assertRaisesRegex(RIRefError,"REFERENCE_BACKPRESSURE"):
            h.accept(self.owners.reader,ref2)
        self.assertEqual(h.accept(self.owners.reader,self.ref)["status"],"DUPLICATE")

    def test_monotonic_regression_fails_closed(self):
        self.accept(evidence_state="AVAILABLE")
        self.clock.current-=10
        with self.assertRaisesRegex(RIRefError,"LOCAL_CLOCK_REGRESSION"):
            self.accept(evidence_state="AVAILABLE")
        self.assertTrue(self.consumer.inspect()["closed"])
        self.assertEqual(self.consumer.inspect()["seen_count"],0)

    def test_generic_v04_observation_id_preserved(self):
        stamp=receive_stamp()
        row={"schema_ref_str":SAMPLE_SCHEMA,"producer_str":"synthetic.offline.test",
             "source":{"source_id_str":"source.synthetic.imu","modality_str":"joint_state",
                       "reference_frame_id_str":"frame.synthetic.arm","sample_sequence_uint":7},
             "temporal_binding":stamp,"payload":{"measurements":{}}}
        from reality_ingress.generic import envelope_from_sample
        env=envelope_from_sample(row,"0"*64,"payloads/00/test.bin",14)
        ref=unverified_ref_from_envelope(env)
        self.assertEqual(ref["observation_id"],env["observation_id_str"])
        self.assertFalse(ref["source_verified"])
        self.assertEqual(ref["modality"],"joint_state")

    def test_consumer_has_no_io_or_effect_dispatch(self):
        import builtins
        with patch.object(socket,"socket",side_effect=AssertionError("network")), \
             patch.object(subprocess,"Popen",side_effect=AssertionError("subprocess")), \
             patch.object(builtins,"open",side_effect=AssertionError("new file")):
            r=self.accept(evidence_state="AVAILABLE")
        self.assertFalse(r["notice"]["may_actuate"])

    def test_existing_cog_continues_if_ri_offline(self):
        h=CognitiveHost(local_alias="lab-robot")
        self.assertEqual(h.health()["mode"],"OFFLINE_LAB")
        self.assertIsNone(h.next_result())
        self.assertEqual(h.health()["memory_status"],"NOT_CONNECTED")
        h.close()

    def test_close_purges_seen_without_fabricated_continuity(self):
        self.accept(evidence_state="AVAILABLE")
        self.consumer.close()
        self.assertEqual(self.consumer.inspect()["seen_count"],0)
        with self.assertRaisesRegex(RIRefError,"CONSUMER_CLOSED"):
            self.accept()

if __name__ == "__main__":unittest.main()
