"""Actual COG #6 Work/Oneiric result -> exact CORE-D candidate consumer tests.

Synthetic only, offline, no positive Life identity/history/effect permissions.
"""
from __future__ import annotations
from copy import deepcopy
import importlib.util
import os
from pathlib import Path
import socket
import subprocess
import unittest
from unittest.mock import patch

from rgd_cognition.core_b_adapter import (
    BridgeError, CoreBSchema, LocalOwners, Limits, KernelSession,
    digest, validate_result_bundle,
)
from rgd_cognition.core_b_oneiric import oneiric_goal
from rgd_cognition.core_d_projection import (
    CoreDShape, CORE_D_COMMIT, CORE_D_SCHEMA_BLOB, project_oneiric,
    validate_projection, history_commit_preview,
)

HERE = Path(__file__).resolve().parent
CORE_D = Path(os.environ["CORE_D_CHECKOUT"]) / "contracts/temporal-memory/v0.1.0"
CORE_B = Path(os.environ["CORE_B_CHECKOUT"]) / "contracts/kernel/v0.1.0"
D_BYTES = (CORE_D / "schemas/temporal-memory.schema.json").read_bytes()
B_BYTES = (CORE_B / "schemas/kernel-goal-effect.schema.json").read_bytes()


class Clock:
    def __init__(self): self.value = 100
    def __call__(self): return self.value


def ctx():
    return dict(revision="sha256:" + "1" * 64,
        policy_revision=Limits().revision, session_id="test:session:core-d",
        runtime_instance_id="test:runtime:core-d", scope="SESSION_SCOPED",
        life_binding_ref=None, life_activation_epoch=None, role_fencing_generation=4)


class GenuineProjectionTests(unittest.TestCase):
    def setUp(self):
        self.b, self.d = CoreBSchema(B_BYTES), CoreDShape(D_BYTES)
        self.clock, self.owners, self.context = Clock(), LocalOwners(), ctx()
        self.work = KernelSession(self.b, owners=self.owners,
            policy=Limits(enabled=True, total_steps=24, total_wall_ms=12000, queue_items=8),
            context_supplier=lambda:deepcopy(self.context),
            clock_ms=self.clock, clock_domain="test:clock:core-d")
        self.work.set_resources(self.owners.operator, "NORMAL")

    def result(self, tags=("FOOT_LIFT", "NO_TRANSLATION"), goal_id="test:goal:dream"):
        source = digest({"fixture":"possible first step", "body":"not enrolled"})
        package = oneiric_goal(self.b, source_event_ref=source, context=self.context,
             clock_domain="test:clock:core-d", created_ms=100, ttl_ms=4000,
             producer_ref=self.owners.producer(self.owners.imagination)[0],
             budget=dict(wall_time_ms=1000, steps=6, subgoals=0, depth=0, queue_items=1),
             goal_id=goal_id)
        self.assertEqual(self.work.submit(self.owners.imagination,package["goal"],
                        key=goal_id+":submit", task_detail=package["detail"])["outcome"],"ADMIT")
        self.work.move(self.owners.work,goal_id,"RUNNING",key=goal_id+":start")
        ticket=self.work.ticket(self.owners.work,goal_id)
        latest=None
        for i,tag in enumerate(tags):
            latest=self.work.review_oneiric(self.owners.work,ticket,
                   observation_tags=[tag],key=goal_id+":review:"+str(i))
        result=self.work.finish(self.owners.work,ticket,code="ANALYSIS_COMPLETE",
            evidence_refs=[source],key=goal_id+":finish",interpretation=latest)
        self.assertEqual(validate_result_bundle(self.b,result),result)
        return result

    def project(self,result=None):
        return project_oneiric(self.d,self.b,result or self.result(),
            knowledge_at_ms=self.clock.value,clock_domain="test:clock:core-d")

    def test_real_work_produces_core_d_shape_valid_records(self):
        r=self.result();p=self.project(r)
        self.assertEqual(validate_projection(self.d,self.b,r,p),p)
        for key,kind in (("oneiric_review","OneiricReview"),
                 ("salience_hint","SalienceHint"),
                 ("cognitive_commitment","CognitiveCommitment")):
            self.assertEqual(self.d.check(kind,p[key]),p[key])
        for x in p["memory_annotations"]:self.d.check("MemoryAnnotation",x)
        self.assertEqual(p["oneiric_review"]["assessment"],"REFUTED")
        self.assertEqual(p["oneiric_review"]["review_outcome"],"REVIEW_COMPLETED")
        self.assertFalse(p["oneiric_review"]["history_committed"])
        self.assertEqual(p["source_trace_ref"],r["cognitive_trace"]["trace_id"])
        self.assertEqual(len(p["memory_annotations"]),2)
        self.assertEqual(p["memory_annotations"][1]["supersedes_annotation_ref"],
                         p["memory_annotations"][0]["record_id"])
        self.assertIsNone(p["memory_annotations"][0]["about_valid_time_assertion_ref"])
        self.assertFalse(p["cognitive_commitment"]["physical_milestone_verified"])

    def test_core_d_own_offline_validator_accepts_live_cog_drafts(self):
        spec=importlib.util.spec_from_file_location("core_d_validator_test_only", CORE_D/"validate.py")
        m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
        p=self.project()
        for item in (p["salience_hint"],*p["memory_annotations"],
                     p["oneiric_review"],p["cognitive_commitment"]):
            self.assertEqual(m.validate(item),item)

    def test_history_boundary_is_blocked_and_does_not_create_request(self):
        r=self.result();p=self.project(r);plan=history_commit_preview(self.d,self.b,r,p)
        self.assertEqual(plan["status"],"BLOCKED_NOT_CONNECTED")
        self.assertEqual(plan["payload_kind"],"ONEIRIC_REVIEW")
        for f in ("history_commit_request","effect_request","history_commit_receipt","life_id","chronon_id"):
            self.assertIsNone(plan[f])
        self.assertFalse(plan["history_committed"])
        with self.assertRaises(BridgeError):self.d.check("HistoryCommitRequest",plan)

    def test_same_projection_clock_is_deterministic(self):
        r=self.result()
        a=self.project(r);b=self.project(r)
        self.assertEqual(a,b)
        self.assertEqual(a["projection_ref"],b["projection_ref"])
        self.assertEqual(a["memory_annotations"][0]["record_id"],b["memory_annotations"][0]["record_id"])

    def test_new_projection_time_does_not_backdate_old_review(self):
        r=self.result();old=self.project(r)
        self.clock.value += 10
        fresh=self.project(r)
        self.assertNotEqual(old["projection_ref"],fresh["projection_ref"])
        self.assertEqual(fresh["projection_at_ms"],110)
        self.assertEqual(fresh["memory_annotations"][0]["knowledge_at_ms"],110)
        self.assertEqual(fresh["oneiric_review"]["knowledge_at_ms"],110)
        self.assertEqual(fresh["oneiric_review"]["source_event_ref"],old["source_event_ref"])

    def test_first_review_remains_unresolved(self):
        r=self.result(tags=("FOOT_LIFT",))
        p=self.project(r)
        self.assertEqual(p["oneiric_review"]["assessment"],"UNRESOLVED")
        self.assertEqual(p["cognitive_commitment"]["assessment"],"UNRESOLVED")
        self.assertEqual(p["cognitive_commitment"]["commitment_kind"],"DECISION")

    def test_plausible_synthetic_step_never_upgrades_to_physical_support(self):
        # Real C0 oneiric review produces PLAUSIBLE_IN_FIXTURE from these tags.
        source=digest("synthetic plausible trial")
        pkg=oneiric_goal(self.b,source_event_ref=source,context=self.context,
            clock_domain="test:clock:core-d",created_ms=100,ttl_ms=4000,
            producer_ref=self.owners.producer(self.owners.imagination)[0],
            budget=dict(wall_time_ms=1000,steps=4,subgoals=0,depth=0,queue_items=1),goal_id="dream:plausible")
        self.work.submit(self.owners.imagination,pkg["goal"],key="p:submit",task_detail=pkg["detail"])
        self.work.move(self.owners.work,"dream:plausible","RUNNING",key="p:start")
        t=self.work.ticket(self.owners.work,"dream:plausible")
        a=self.work.review_oneiric(self.owners.work,t,
            observation_tags=["FOOT_LIFT","FORWARD_DISPLACEMENT","CONTACT_CHANGE"],key="p:review")
        self.assertEqual(a["label"],"STEP_PLAUSIBLE_IN_FIXTURE")
        r=self.work.finish(self.owners.work,t,code="ANALYSIS_COMPLETE",evidence_refs=[source],
            key="p:finish",interpretation=a)
        p=self.project(r)
        self.assertEqual(p["oneiric_review"]["assessment"],"UNRESOLVED")
        self.assertFalse(p["memory_annotations"][0]["physical_milestone_verified"])

    def test_rejects_swapped_cog_result(self):
        a=self.result(goal_id="dream:first")
        b=self.result(goal_id="dream:second")
        p=self.project(a)
        with self.assertRaisesRegex(BridgeError,"CORE_D_PROJECTION_SOURCE_MISMATCH"):
            validate_projection(self.d,self.b,b,p)

    def test_rejects_rewritten_annotation_even_if_record_rehashed(self):
        r=self.result();p=self.project(r);altered=deepcopy(p)
        item=altered["memory_annotations"][1]
        item["assessment"]="SUPPORTED"
        item["record_id"]=digest({k:v for k,v in item.items() if k!="record_id"})
        altered["oneiric_review"]["prior_annotation_ref"]=altered["memory_annotations"][0]["record_id"]
        altered["projection_ref"]=digest({k:v for k,v in altered.items() if k!="projection_ref"})
        with self.assertRaisesRegex(BridgeError,"CORE_D_ANNOTATION_LINEAGE_MISMATCH"):
            validate_projection(self.d,self.b,r,altered)

    def test_rejects_mismatched_supercession_chain(self):
        r=self.result();p=self.project(r);bad=deepcopy(p)
        bad["memory_annotations"][1]["supersedes_annotation_ref"]=digest("invented")
        bad["memory_annotations"][1]["record_id"]=digest({k:v for k,v in bad["memory_annotations"][1].items()
                                                                         if k!="record_id"})
        with self.assertRaisesRegex(BridgeError,"CORE_D_ANNOTATION_LINEAGE_MISMATCH"):
            validate_projection(self.d,self.b,r,bad)

    def test_core_d_not_a_second_goal_admission(self):
        r=self.result();before=self.work.inspect()["usage"]
        p=self.project(r);history_commit_preview(self.d,self.b,r,p)
        self.assertEqual(before,self.work.inspect()["usage"])

    def test_wrong_time_domain_or_backdating_is_rejected(self):
        r=self.result()
        for t,d in ((99,"test:clock:core-d"),(100,"foreign:clock"),
                    (100,"legacy.posix.system"),(True,"test:clock:core-d")):
            with self.assertRaises(BridgeError):project_oneiric(self.d,self.b,r,knowledge_at_ms=t,clock_domain=d)

    def test_context_or_life_spoof_is_rejected(self):
        r=self.result();bad=deepcopy(r)
        bad["cognitive_trace"]["life_id"]="madeup:life"
        with self.assertRaises(BridgeError):self.project(bad)
        bad=deepcopy(r);bad["outcome"]["verification"]="VERIFIED"
        with self.assertRaises(BridgeError):self.project(bad)

    def test_ordinary_imu_result_is_not_oneriic_history(self):
        g=self.result();bad=deepcopy(g)
        bad["outcome"]["task_ref"]="cog.task.v1:imu-uncertainty"
        with self.assertRaises(BridgeError):self.project(bad)

    def test_unknown_core_d_contract_and_changed_schema_pin_fail_closed(self):
        with self.assertRaisesRegex(BridgeError,"CORE_D_SCHEMA_PIN_MISMATCH"):
            CoreDShape(D_BYTES+b" ")
        with self.assertRaisesRegex(BridgeError,"CORE_D_TYPE_NOT_NEGOTIATED"):
            self.d.check("ImportAnchorEvidence",{})

    def test_shape_valid_committed_receipt_does_not_prove_writer(self):
        # Core-D fixture is syntactically fine but cannot be accepted as our own commit.
        from json import loads
        pos=loads((CORE_D/"fixtures/positive.json").read_text())["records"]
        rec=pos["receipt_committed"] if "receipt_committed" in pos else pos["receipt"]
        self.d.check("HistoryCommitReceipt",rec)
        r=self.result();p=self.project(r)
        plan=history_commit_preview(self.d,self.b,r,p)
        self.assertIsNone(plan["history_commit_receipt"])

    def test_no_io_or_effect_dispatch_on_projection(self):
        r=self.result()
        with patch.object(socket,"socket",side_effect=AssertionError("network")), \
             patch.object(subprocess,"Popen",side_effect=AssertionError("process")):
            p=self.project(r);h=history_commit_preview(self.d,self.b,r,p)
        self.assertFalse(h["history_committed"])

    def test_projection_stays_ephemeral_even_after_work_close(self):
        r=self.result();self.work.close()
        p=self.project(r)
        self.assertIsNone(p["life_id"])
        self.assertEqual(p["history_status"],"NOT_CONNECTED")
        self.assertIsNone(history_commit_preview(self.d,self.b,r,p)["history_commit_request"])


if __name__ == "__main__": unittest.main()
