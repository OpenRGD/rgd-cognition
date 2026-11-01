"""Review-closure adversarial tests against the real Core-B candidate schema.

Offline, deterministic, non-actuating. No Chronon, Life identity or telemetry.
"""
from copy import deepcopy
import unittest

from test_core_b_adapter import Clock, RAW, base_context
from rgd_cognition.core_b_adapter import (
    BridgeError, CoreBSchema, LocalOwners, Limits, KernelSession,
    make_goal, digest, check_detail, validate_result_bundle,
)
from rgd_cognition.core_b_oneiric import oneiric_goal


class ClosureTests(unittest.TestCase):
    def setUp(self):
        self.clock=Clock()
        self.ctx=base_context()
        self.schema=CoreBSchema(RAW)
        self.owners=LocalOwners()
        self.policy=Limits(enabled=True,total_steps=12,total_wall_ms=6000,queue_items=6)
        self.work=KernelSession(self.schema,owners=self.owners,policy=self.policy,
            context_supplier=lambda:deepcopy(self.ctx),clock_ms=self.clock,
            clock_domain='test:clock')
        self.work.set_resources(self.owners.operator,'NORMAL')

    def goal(self,name='g:a'):
        return make_goal(self.schema,goal_id=name,task_ref='cog.task.v1:imu-uncertainty',
            context=self.ctx,clock_domain='test:clock',created_ms=100,ttl_ms=1800,
            producer_ref=self.owners.producer(self.owners.model)[0],origin='MODEL',
            budget=dict(wall_time_ms=1000,steps=3,subgoals=0,depth=0,queue_items=1),
            evidence_refs=['test:evidence'])

    def start(self,name='g:a'):
        g=self.goal(name)
        self.assertEqual(self.work.submit(self.owners.model,g,key=name)['outcome'],'ADMIT')
        self.work.move(self.owners.work,name,'RUNNING',key=name+':start')
        return g,self.work.ticket(self.owners.work,name)

    def finish(self, name='g:a', code='ANALYSIS_COMPLETE'):
        g,t=self.start(name)
        r=self.work.finish(self.owners.work,t,code=code,
            evidence_refs=['test:evidence'] if code=='ANALYSIS_COMPLETE' else [],
            key=name+':finish')
        return g,r

    def oneiric(self,name='dream:one',steps=4):
        src=digest('fixture:first-step')
        package=oneiric_goal(self.schema,source_event_ref=src,context=self.ctx,
            clock_domain='test:clock',created_ms=100,ttl_ms=1500,
            producer_ref=self.owners.producer(self.owners.imagination)[0],
            budget=dict(wall_time_ms=1000,steps=steps,subgoals=0,depth=0,queue_items=1),goal_id=name)
        self.assertEqual(self.work.submit(self.owners.imagination,package['goal'],
            key=name+':submit',task_detail=package['detail'])['outcome'],'ADMIT')
        self.work.move(self.owners.work,name,'RUNNING',key=name+':start')
        return package,self.work.ticket(self.owners.work,name)

    def test_result_links_are_full_and_validate(self):
        g,r=self.finish()
        self.assertEqual(validate_result_bundle(self.schema,r),r)
        o,t=r['outcome'],r['cognitive_trace']
        self.assertEqual(o['goal_id'],g['goal_id'])
        self.assertEqual(o['goal_revision'],g['goal_revision'])
        self.assertEqual(o['context'],g['context'])
        self.assertEqual(t['goal_revision'],o['goal_revision'])
        self.assertEqual(t['admission_ref'],r['transition']['admission_ref'])
        self.assertEqual(o['trace_ref'],t['trace_id'])
        self.assertEqual(t['outcome_digest'],digest({k:v for k,v in o.items() if k!='trace_ref'}))
        self.assertFalse(t['may_actuate'])
        self.assertEqual(t['memory_status'],'NOT_CONNECTED')
        self.assertEqual(t['verification'],'UNVERIFIED')
        self.assertEqual(o['result_semantics'],'INQUIRY_FINISHED_UNVERIFIED')

    def test_no_fabricated_old_trace_or_cognitive_proposal(self):
        from rgd_cognition.contracts import validate, ContractError
        _,r=self.finish()
        with self.assertRaises(ContractError):validate('CognitiveTrace',r['cognitive_trace'])
        with self.assertRaises(ContractError):validate('CognitiveProposal',r['outcome'])

    def test_trace_and_outcome_must_share_goal_context(self):
        _,a=self.finish('g:a')
        _,b=self.finish('g:b')
        bad=deepcopy(a);bad['outcome']=b['outcome']
        with self.assertRaisesRegex(BridgeError,'RESULT_'):
            validate_result_bundle(self.schema,bad)
        bad=deepcopy(a);bad['cognitive_trace']=b['cognitive_trace']
        with self.assertRaisesRegex(BridgeError,'RESULT_'):
            validate_result_bundle(self.schema,bad)

    def test_stripped_or_swapped_result_not_accepted(self):
        _,r=self.finish()
        bad=deepcopy(r);bad['outcome'].pop('goal_revision')
        with self.assertRaises(BridgeError):validate_result_bundle(self.schema,bad)
        bad=deepcopy(r);bad['outcome']['context']['policy_revision']='changed:policy'
        with self.assertRaisesRegex(BridgeError,'RESULT_'):
            validate_result_bundle(self.schema,bad)
        bad=deepcopy(r);bad['outcome']['result_semantics']='ABSTAINED_UNVERIFIED'
        with self.assertRaisesRegex(BridgeError,'RESULT_'):
            validate_result_bundle(self.schema,bad)
        bad=deepcopy(r);bad['cognitive_trace']['reason_codes']=['FAKE_SUCCESS']
        with self.assertRaisesRegex(BridgeError,'RESULT_'):
            validate_result_bundle(self.schema,bad)

    def test_full_result_replay_inert_mutation_conflicts(self):
        g,t=self.start()
        r=self.work.finish(self.owners.work,t,code='ABSTAIN',evidence_refs=[],key='finished')
        spent=self.work.inspect()['usage']['spent_steps']
        self.assertEqual(r,self.work.finish(self.owners.work,t,code='ABSTAIN',evidence_refs=[],key='finished'))
        self.assertEqual(spent,self.work.inspect()['usage']['spent_steps'])
        with self.assertRaisesRegex(BridgeError,'IDEMPOTENCY_CONFLICT'):
            self.work.finish(self.owners.work,t,code='ANALYSIS_COMPLETE',evidence_refs=['test:evidence'],key='finished')

    def test_insufficient_evidence_is_traceable_pause(self):
        _,r=self.finish(code='INSUFFICIENT_EVIDENCE')
        self.assertEqual(r['transition']['to_state'],'PAUSED')
        self.assertEqual(r['outcome']['result_semantics'],'INQUIRY_PAUSED_EVIDENCE')
        self.assertEqual(r['cognitive_trace']['reason_codes'],['INSUFFICIENT_EVIDENCE'])
        self.assertIsNone(r['outcome']['interpretation'])

    def test_explicit_abstention_stays_unverified(self):
        _,r=self.finish(code='ABSTAIN')
        self.assertEqual(r['transition']['to_state'],'COMPLETED')
        self.assertEqual(r['outcome']['result_semantics'],'ABSTAINED_UNVERIFIED')
        self.assertEqual(r['cognitive_trace']['verification'],'UNVERIFIED')

    def test_context_invalidation_charges_elapsed_wall(self):
        g,t=self.start()
        self.clock.value=350
        self.ctx['revision']='sha256:'+'2'*64
        with self.assertRaisesRegex(BridgeError,'CONTEXT_OR_FENCE_CHANGED'):
            self.work.inspect()
        usage=self.work._usage()
        self.assertEqual(usage['spent_wall_ms'],250)
        self.assertEqual(usage['reserved_wall_ms'],0)
        self.assertEqual(usage['reserved_steps'],0)
        self.assertEqual(self.work._jobs[g['goal_id']].detail['reason_code'],'CONTEXT_OR_FENCE_CHANGED')
        self.assertEqual(self.work._jobs[g['goal_id']].detail['goal_revision'],g['goal_revision'])
        self.assertTrue(self.work._jobs[g['goal_id']].detail['local_invalidation'])
        check_detail('InvalidationReport',self.work._jobs[g['goal_id']].detail)

    def test_context_unavailable_still_charges_time(self):
        g,t=self.start()
        self.clock.value=410
        del self.ctx['policy_revision']
        with self.assertRaisesRegex(BridgeError,'CONTEXT_UNAVAILABLE'):
            self.work.inspect()
        self.assertEqual(self.work._usage()['spent_wall_ms'],310)
        self.assertEqual(self.work._usage()['reserved_slots'],0)

    def test_close_charges_then_releases_once(self):
        self.start()
        self.clock.value=445
        report=self.work.close()
        self.assertEqual(report['status'],'CLOSED_LOCAL_ONLY')
        self.assertEqual(report['usage']['spent_wall_ms'],345)
        self.assertEqual(report['usage']['reserved_steps'],0)
        self.assertEqual(report['usage']['reserved_wall_ms'],0)
        self.assertEqual(report['usage']['reserved_slots'],0)
        self.assertIsNone(report['life_id'])
        self.assertEqual(self.work.close()['usage']['spent_wall_ms'],345)
        with self.assertRaisesRegex(BridgeError,'SESSION_CLOSED'):
            self.work.inspect()

    def test_pause_does_not_charge_idle_time_at_close(self):
        self.start()
        self.clock.value=250
        self.work.move(self.owners.work,'g:a','PAUSED',key='pause',reason='PAUSED_USER')
        self.clock.value=900
        report=self.work.close()
        self.assertEqual(report['usage']['spent_wall_ms'],150)
        self.assertEqual(report['usage']['reserved_wall_ms'],0)

    def test_context_revocation_at_overrun_charges_bounded_allowance(self):
        g,t=self.start()
        self.clock.value=1400
        self.ctx['revision']='sha256:'+'5'*64
        with self.assertRaises(BridgeError):self.work.inspect()
        self.assertEqual(self.work._usage()['spent_wall_ms'],1000)
        self.assertEqual(self.work._usage()['reserved_wall_ms'],0)
        self.assertEqual(self.work._jobs['g:a'].detail['reason_code'],'WALL_BUDGET_EXHAUSTED')

    def test_oneiric_revision_chain_end_to_end(self):
        package,t=self.oneiric()
        g=package['goal']
        first=self.work.review_oneiric(self.owners.work,t,
            observation_tags=['FOOT_LIFT'],key='dream:first')
        second=self.work.review_oneiric(self.owners.work,t,
            observation_tags=['NO_TRANSLATION'],key='dream:second')
        self.assertEqual(first['label'],'INSUFFICIENT_EVIDENCE')
        self.assertEqual(second['supersedes_annotation_ref'],first['annotation_id'])
        self.assertEqual(second['label'],'STEP_NOT_SUPPORTED_IN_FIXTURE')
        r=self.work.finish(self.owners.work,t,code='ANALYSIS_COMPLETE',
                           evidence_refs=[package['detail']['source_event_ref']],
                           interpretation=second,key='dream:finish')
        self.assertEqual(validate_result_bundle(self.schema,r),r)
        self.assertEqual(r['outcome']['interpretation'],second)
        self.assertEqual(r['outcome']['annotation_history'],[first,second])
        self.assertEqual(r['cognitive_trace']['interpretation_digest'],digest(second))
        self.assertEqual(r['cognitive_trace']['annotation_chain_digest'],digest([first,second]))
        self.assertEqual(r['outcome']['context'],g['context'])
        self.assertIsNone(second['chronon_id']);self.assertIsNone(second['life_id'])
        self.assertEqual(r['cognitive_trace']['chronon_link_status'],'NOT_CONNECTED')
        self.assertEqual(self.work.inspect()['usage']['spent_steps'],3)

    def test_oneiric_without_review_cannot_claim_completion(self):
        pkg,t=self.oneiric()
        with self.assertRaisesRegex(BridgeError,'ONEIRIC_ANNOTATION_REQUIRED'):
            self.work.finish(self.owners.work,t,code='ANALYSIS_COMPLETE',
                             evidence_refs=[pkg['detail']['source_event_ref']],key='finish')
        self.assertEqual(self.work.inspect()['usage']['spent_steps'],0)

    def test_oneiric_annotation_is_not_trusted_from_payload(self):
        pkg,t=self.oneiric()
        first=self.work.review_oneiric(self.owners.work,t,
            observation_tags=['FOOT_LIFT'],key='first')
        fake=deepcopy(first);fake['label']='STEP_PLAUSIBLE_IN_FIXTURE'
        with self.assertRaises(BridgeError):
            self.work.finish(self.owners.work,t,code='ANALYSIS_COMPLETE',
                evidence_refs=[pkg['detail']['source_event_ref']],key='fake',interpretation=fake)
        self.assertEqual(self.work.inspect()['usage']['spent_steps'],1)

    def test_oneiric_replay_does_not_spend_twice(self):
        pkg,t=self.oneiric()
        first=self.work.review_oneiric(self.owners.work,t,observation_tags=['FOOT_LIFT'],key='same')
        self.assertEqual(first,self.work.review_oneiric(self.owners.work,t,
                        observation_tags=['FOOT_LIFT'],key='same'))
        self.assertEqual(self.work.inspect()['usage']['spent_steps'],1)
        with self.assertRaisesRegex(BridgeError,'IDEMPOTENCY_CONFLICT'):
            self.work.review_oneiric(self.owners.work,t,observation_tags=['NO_TRANSLATION'],key='same')

    def test_oneiric_model_does_not_own_work(self):
        pkg,t=self.oneiric()
        with self.assertRaisesRegex(BridgeError,'WRONG_WORK_OWNER'):
            self.work.review_oneiric(self.owners.model,t,observation_tags=['FOOT_LIFT'],key='fake')
        self.assertEqual(self.work.inspect()['usage']['spent_steps'],0)

    def test_oneiric_foreign_source_or_over_budget_fails(self):
        pkg,t=self.oneiric(steps=2)
        self.work.review_oneiric(self.owners.work,t,observation_tags=['FOOT_LIFT'],key='one')
        self.work.review_oneiric(self.owners.work,t,observation_tags=['NO_TRANSLATION'],key='two')
        with self.assertRaisesRegex(BridgeError,'BUDGET_EXHAUSTED'):
            self.work.review_oneiric(self.owners.work,t,observation_tags=['NO_TRANSLATION'],key='three')
        with self.assertRaisesRegex(BridgeError,'BUDGET_EXHAUSTED'):
            self.work.finish(self.owners.work,t,code='ANALYSIS_COMPLETE',
                 evidence_refs=[pkg['detail']['source_event_ref']],key='finish',
                 interpretation=self.work._jobs[pkg['goal']['goal_id']].annotations[-1])

    def test_task_detail_schema_rejects_invalid_rewrite(self):
        pkg,t=self.oneiric()
        with self.assertRaisesRegex(BridgeError,'INVALID_DETAIL'):
            changed=deepcopy(pkg['detail']);changed['initial_label']='UNKNOWN'
            # A malformed candidate fails before the idempotency evaluation.
            self.work.submit(self.owners.imagination,pkg['goal'],key='dream:one:submit',task_detail=changed)

    def test_oneiric_lineage_cannot_be_rewritten_even_with_locally_rehashed_data(self):
        from rgd_cognition.contracts import local_digest
        pkg,t=self.oneiric()
        a=self.work.review_oneiric(self.owners.work,t,observation_tags=['FOOT_LIFT'],key='one')
        b=self.work.review_oneiric(self.owners.work,t,observation_tags=['NO_TRANSLATION'],key='two')
        r=self.work.finish(self.owners.work,t,code='ANALYSIS_COMPLETE',
            evidence_refs=[pkg['detail']['source_event_ref']],key='finish',interpretation=b)
        bad=deepcopy(r)
        last=bad['outcome']['annotation_history'][-1]
        last['supersedes_annotation_ref']=digest('falsified-predecessor')
        last['annotation_id']=local_digest({k:v for k,v in last.items() if k!='annotation_id'})
        bad['outcome']['interpretation']=deepcopy(last)
        trace=bad['cognitive_trace']
        trace['interpretation_digest']=digest(last)
        trace['annotation_chain_digest']=digest(bad['outcome']['annotation_history'])
        trace['outcome_digest']=digest({k:v for k,v in bad['outcome'].items() if k!='trace_ref'})
        trace['trace_id']=digest({k:v for k,v in trace.items() if k!='trace_id'})
        bad['outcome']['trace_ref']=trace['trace_id']
        with self.assertRaisesRegex(BridgeError,'RESULT_ANNOTATION_LINEAGE_MISMATCH'):
            validate_result_bundle(self.schema,bad)

    def test_oneiric_result_remains_reviewable_after_volatile_close(self):
        pkg,t=self.oneiric()
        first=self.work.review_oneiric(self.owners.work,t,observation_tags=['FOOT_LIFT'],key='first')
        r=self.work.finish(self.owners.work,t,code='ANALYSIS_COMPLETE',
            evidence_refs=[pkg['detail']['source_event_ref']],key='finish',interpretation=first)
        self.work.close()
        self.assertEqual(validate_result_bundle(self.schema,r),r)
        self.assertIsNone(r['outcome']['interpretation']['chronon_id'])
        self.assertEqual(self.work._jobs,{})

    def test_oneiric_task_requires_genuine_bound_provenance(self):
        from rgd_cognition.core_b_adapter import goal_revision
        pkg=oneiric_goal(self.schema,source_event_ref=digest('one'),context=self.ctx,
             clock_domain='test:clock',created_ms=100,ttl_ms=1500,
             producer_ref=self.owners.producer(self.owners.imagination)[0],
             budget=dict(wall_time_ms=1000,steps=3,subgoals=0,depth=0,queue_items=1))
        g=pkg['goal'];g['provenance']['class']='DERIVED';g['goal_revision']=goal_revision(g)
        pkg['detail']['goal_revision']=g['goal_revision']
        with self.assertRaisesRegex(BridgeError,'ONEIRIC_SOURCE_UNBOUND'):
            self.work.submit(self.owners.imagination,g,key='one',task_detail=pkg['detail'])


if __name__=='__main__':
    unittest.main()
