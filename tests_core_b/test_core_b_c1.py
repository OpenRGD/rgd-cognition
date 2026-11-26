"""Actual existing C1/C0 functions + actual COG-02 + exact baseline Core."""
from copy import deepcopy
import os
from pathlib import Path
import unittest
from unittest.mock import patch

from rgd_cognition.attention_c1 import ImuAttention, AttentionPolicy, _digest
from rgd_cognition.attention_c1_demo import FixtureClock, fixture_binding, fixture_sample
from rgd_cognition.context import context_slice
from rgd_cognition.contracts import validate, ContractError
from rgd_cognition.rgd_context import RGDContextResolver, CORE_COMMIT
from rgd_cognition.core_b_adapter import Limits, BridgeError, check_detail, validate_result_bundle, goal_revision, make_goal
from rgd_cognition.core_b_c1 import CoreBAttentionHost, cue_goal

CORE = Path(os.environ['RGD_CORE_CHECKOUT'])
SCHEMA = (Path(os.environ['CORE_B_CHECKOUT'])/'contracts/kernel/v0.1.0/schemas/kernel-goal-effect.schema.json').read_bytes()
ROOT='sha256:c049dc3fb91c19e668ef0d35b9b40d9052caf1a458b1a108d58b1896189dd5f9'


class GenuineIntegration(unittest.TestCase):
    def setUp(self):
        self.clock=FixtureClock()
        self.resolver=RGDContextResolver(CORE,local_alias='lab-robot',expected_source_root=ROOT,clock=self.clock)
        view=self.resolver.refresh()
        self.assertEqual(view['reference_status'],'SOURCE_INTEGRITY_VERIFIED')
        self.host=CoreBAttentionHost(SCHEMA,context_supplier=self.resolver.read,binding=fixture_binding(),
            policy=Limits(enabled=True),attention_policy=AttentionPolicy(cooldown_ms=100),clock=self.clock,role_fence=7)
        self.host.set_resources(self.host.owners.operator,'NORMAL')

    def samples(self,n=3,**kw):
        result=None
        for i in range(n):
            self.clock.advance(100)
            result=self.host.ingest(fixture_sample(i),received_ns=self.clock(),freshness=kw.get('freshness','FRESH'),consent=kw.get('consent',True))
        return result

    def test_actual_attention_to_single_core_b_admission(self):
        with patch('rgd_cognition.agenda_c0.SessionAgenda.propose',side_effect=AssertionError('second admission')):
            r=self.samples()
        self.assertIsInstance(self.host.attention,ImuAttention)
        g,d=r['proposal']['goal'],r['proposal']['admission']
        self.host.schema.check('CognitiveGoalCandidate',g)
        self.host.schema.check('GoalAdmissionDecision',d)
        self.assertEqual(d['outcome'],'ADMIT')
        self.assertEqual(g['context']['revision'],self.resolver.read()['context_revision'])
        self.assertEqual(g['context']['role_fencing_generation'],7)
        self.assertIsNone(g['context']['life_binding_ref'])
        self.assertEqual(g['provenance']['class'],'SYNTHETIC')
        check_detail('TaskDetail',r['proposal']['detail'])
        self.assertEqual(r['proposal']['detail']['source_cue']['policy_revision'],self.host.attention.policy_revision)
        self.assertEqual(self.host.work.inspect()['usage']['reserved_steps'],2)

    def test_old_input_contract_not_repurposed(self):
        r=self.samples()
        with self.assertRaises(ContractError):validate('InputEvent',r['proposal']['goal'])
        self.assertEqual(CORE_COMMIT,'afe1a831b950a4e6560f0285a0103fc4eaa343b7')

    def test_complete_inquiry_is_not_verification(self):
        r=self.samples();g=r['proposal']['goal'];o=self.host.owners
        self.host.work.move(o.work,g['goal_id'],'RUNNING',key='start')
        t=self.host.work.ticket(o.work,g['goal_id'])
        result=self.host.work.finish(o.work,t,code='ANALYSIS_COMPLETE',evidence_refs=g['provenance']['evidence_refs'],key='finish')
        check_detail('Outcome',result['outcome'])
        self.assertEqual(result['transition']['to_state'],'COMPLETED')
        self.assertEqual(result['outcome']['verification'],'UNVERIFIED')

    def test_original_deadline_not_conversion_time(self):
        r=self.samples();cue=r['attention']['cue'];created=self.clock()
        self.clock.advance(200)
        p=cue_goal(self.host.schema,cue,context=self.host._context(),created_ns=created,
            clock_domain=self.host.attention.session_id,producer_ref='cog.local:attention',
            budget=r['proposal']['goal']['budget'])
        self.assertEqual(p['goal'],r['proposal']['goal'])
        end=p['goal']['lifetime']['created_ms']+p['goal']['lifetime']['ttl_ms']
        self.assertLessEqual(end*1000000,cue['expires_at_monotonic_ns'])

    def test_nanosecond_conversion_is_conservative(self):
        r=self.samples();cue=r['attention']['cue'];created=self.clock()+1
        p=cue_goal(self.host.schema,cue,context=self.host._context(),created_ns=created,
            clock_domain=self.host.attention.session_id,producer_ref='cog.local:attention',budget=r['proposal']['goal']['budget'])
        life=p['goal']['lifetime']
        self.assertGreaterEqual(life['created_ms']*1000000,created)
        self.assertLessEqual((life['created_ms']+life['ttl_ms'])*1000000,cue['expires_at_monotonic_ns'])
        self.assertLessEqual(life['ttl_ms'],r['proposal']['goal']['lifetime']['ttl_ms'])

    def test_foreign_clock_and_fabricated_creation_rejected(self):
        r=self.samples();cue=r['attention']['cue']
        for created,domain in ((None,self.host.attention.session_id),(self.clock(),'other:clock')):
            with self.assertRaises(BridgeError):cue_goal(self.host.schema,cue,context=self.host._context(),
                created_ns=created,clock_domain=domain,producer_ref='cog.local:attention',budget=r['proposal']['goal']['budget'])

    def test_cue_semantic_tamper_is_not_reinterpreted(self):
        r=self.samples();cue=deepcopy(r['attention']['cue']);cue['reason_code']='SUSTAINED_RATE_UNVERIFIED_FRAME'
        with self.assertRaisesRegex(BridgeError,'CUE_DIGEST_MISMATCH'):
            cue_goal(self.host.schema,cue,context=self.host._context(),created_ns=self.clock(),
                clock_domain=self.host.attention.session_id,producer_ref='cog.local:attention',budget=r['proposal']['goal']['budget'])

    def test_expired_evidence_does_not_reenter_as_new_work(self):
        r=self.samples();cue=r['attention']['cue'];self.clock.advance(5000)
        with self.assertRaisesRegex(BridgeError,'CUE_EXPIRED'):
            cue_goal(self.host.schema,cue,context=self.host._context(),created_ns=self.clock(),
                clock_domain=self.host.attention.session_id,producer_ref='cog.local:attention',budget=r['proposal']['goal']['budget'])

    def test_context_revocation_rejects_pending_worker(self):
        r=self.samples();g=r['proposal']['goal'];o=self.host.owners
        self.host.work.move(o.work,g['goal_id'],'RUNNING',key='start');t=self.host.work.ticket(o.work,g['goal_id'])
        self.resolver.invalidate()
        with self.assertRaises(BridgeError):self.host.work.finish(o.work,t,code='ABSTAIN',evidence_refs=[],key='late')

    def test_denied_consent_and_unknown_freshness_no_goal(self):
        self.assertIsNone(self.samples(consent=False)['proposal'])
        self.assertIsNone(self.samples(freshness='UNKNOWN')['proposal'])

    def test_default_resources_cannot_be_claimed_by_data(self):
        self.host.set_resources(self.host.owners.operator,'UNKNOWN')
        self.assertIsNone(self.samples()['proposal'])
        with self.assertRaisesRegex(BridgeError,'WRONG_OPERATOR_OWNER'):
            self.host.set_resources(self.host.owners.model,'NORMAL')

    def test_user_pause_and_resume_keep_cause_and_fence(self):
        r=self.samples();g=r['proposal']['goal'];o=self.host.owners
        self.host.work.move(o.work,g['goal_id'],'RUNNING',key='start');old=self.host.work.ticket(o.work,g['goal_id'])
        self.host.interrupt_user(o.operator)
        self.assertEqual(self.host.work.inspect()['goals'][g['goal_id']]['detail']['reason_code'],'PAUSED_USER')
        self.host.release_user_attention(o.operator)
        self.host.work.move(o.work,g['goal_id'],'RUNNING',key='resume')
        with self.assertRaisesRegex(BridgeError,'STALE_TASK_RESULT'):
            self.host.work.finish(o.work,old,code='ABSTAIN',evidence_refs=[],key='late')

    def fresh_cue_package(self):
        # Exercise the real producer without first admitting its goal.
        for i in range(3):
            self.clock.advance(100)
            observed = self.host.attention.observe(fixture_sample(i), received_ns=self.clock(),
                freshness='FRESH', consent=True, context_revision=self.host._context()['revision'],
                allow_goal_generation=True)
        self.assertIsNotNone(observed['cue'])
        return cue_goal(self.host.schema, observed['cue'], context=self.host._context(),
            created_ns=self.clock(), clock_domain=self.host.attention.session_id,
            producer_ref=self.host.owners.producer(self.host.owners.attention)[0],
            budget=dict(wall_time_ms=1000, steps=2, subgoals=0, depth=0, queue_items=1))

    def test_rc06_receiver_refuses_renewed_evidence_deadline(self):
        package = self.fresh_cue_package()
        goal, detail = package['goal'], package['detail']
        goal['lifetime']['ttl_ms'] += 1000
        goal['goal_revision'] = goal_revision(goal)
        detail['goal_revision'] = goal['goal_revision']
        with self.assertRaises(BridgeError):
            self.host.work.submit(self.host.owners.attention, goal, key='extended', task_detail=detail)
        self.assertEqual(self.host.work.inspect()['usage']['reserved_steps'], 0)

    def test_rc07_work_start_blocked_during_operator_pause(self):
        o = self.host.owners
        ctx = self.host._context()
        goal = make_goal(self.host.schema, goal_id='queued:model', task_ref='cog.task.v1:imu-uncertainty',
            context=ctx, clock_domain=self.host.attention.session_id, created_ms=self.clock()//1000000,
            ttl_ms=2000, producer_ref=o.producer(o.model)[0], origin='MODEL',
            budget=dict(wall_time_ms=1000, steps=2, subgoals=0, depth=0, queue_items=1),
            evidence_refs=['fixture:input'])
        self.assertEqual(self.host.work.submit(o.model, goal, key='queued')['outcome'], 'ADMIT')
        self.host.interrupt_user(o.operator)
        with self.assertRaises(BridgeError):
            self.host.work.move(o.work, goal['goal_id'], 'RUNNING', key='start-paused')
        self.assertEqual(self.host.work.inspect()['goals'][goal['goal_id']]['state'], 'ADMITTED')

    def test_rc06_attention_companion_required_and_valid_package_still_admitted(self):
        p = self.fresh_cue_package()
        o = self.host.owners
        with self.assertRaisesRegex(BridgeError,'ATTENTION_TASK_DETAIL_REQUIRED'):
            self.host.work.submit(o.attention,p['goal'],key='no-detail')
        self.assertEqual(self.host.work.inspect()['usage']['reserved_steps'],0)
        result=self.host.work.submit(o.attention,p['goal'],key='with-detail',task_detail=p['detail'])
        self.assertEqual(result['outcome'],'ADMIT')
        self.assertEqual(self.host.work.inspect()['usage']['reserved_steps'],2)

    def test_rc06_deadline_projection_and_cue_identity_are_checked_at_receiver(self):
        p=self.fresh_cue_package()
        def change(which, goal, detail):
            if which=='detail-deadline': detail['deadline_monotonic_ns'] += 1000000
            elif which=='detail-created': detail['created_monotonic_ns'] -= 1000000
            elif which=='provenance': goal['provenance']['class']='DERIVED'
            else:
                cue=detail['source_cue']
                if which=='foreign-clock':cue['receipt_clock_domain']='other:clock'
                elif which=='foreign-session':cue['attention_session_id']='other:session'
                cue['cue_id']=_digest({k:v for k,v in cue.items() if k!='cue_id'})
                goal['goal_id']=cue['cue_id'];detail['goal_id']=goal['goal_id']
            goal['goal_revision']=goal_revision(goal);detail['goal_revision']=goal['goal_revision']
        for kind in ('detail-deadline','detail-created','provenance','foreign-clock','foreign-session'):
            q=deepcopy(p);change(kind,q['goal'],q['detail'])
            with self.subTest(kind=kind),self.assertRaises(BridgeError):
                self.host.work.submit(self.host.owners.attention,q['goal'],key='bad:'+kind,task_detail=q['detail'])
        self.assertEqual(self.host.work.inspect()['usage']['reserved_steps'],0)
        self.assertEqual(self.host.work.submit(self.host.owners.attention,p['goal'],key='valid',task_detail=p['detail'])['outcome'],'ADMIT')

    def test_real_feed_needs_actual_rgd_not_unverified_json(self):
        with self.assertRaises(BridgeError):
            CoreBAttentionHost(SCHEMA,context_supplier=lambda:context_slice('lab-robot'),
                binding=fixture_binding('AUTHORIZED_LOCAL_FEED'),clock=self.clock)

    def test_real_c1_work_result_contains_bound_trace(self):
        result=self.samples()
        package=result['proposal'];goal=package['goal']; owners=self.host.owners
        self.assertEqual(self.host.work._jobs[goal['goal_id']].task_detail,package['detail'])
        self.host.work.move(owners.work,goal['goal_id'],'RUNNING',key='start')
        ticket=self.host.work.ticket(owners.work,goal['goal_id'])
        completed=self.host.work.finish(owners.work,ticket,code='ANALYSIS_COMPLETE',
             evidence_refs=goal['provenance']['evidence_refs'],key='finish')
        self.assertEqual(validate_result_bundle(self.host.schema,completed),completed)
        self.assertEqual(completed['outcome']['context'],goal['context'])
        self.assertEqual(completed['cognitive_trace']['provenance_class'],'SYNTHETIC')
        self.assertEqual(completed['cognitive_trace']['verification'],'UNVERIFIED')
        self.assertIsNone(completed['outcome']['interpretation'])

    def test_fractional_ingest_explicit_deferral_no_false_admission(self):
        # Conservatively rounded creation time falls in the next ms bucket.
        # The source C1 cue is real code over fixture samples; no waiting/sleep.
        self.clock.value+=400_000
        r=self.samples()
        self.assertEqual(r['attention']['status'],'CUE')
        self.assertIsNone(r['proposal'])
        self.assertEqual(r['deferral']['reason_code'],'CREATION_BUCKET_NOT_REACHED')
        self.assertEqual(r['deferral']['original_deadline_ns'],
                         r['attention']['cue']['expires_at_monotonic_ns'])
        self.assertEqual(self.host.work.inspect()['goals'],{})
        self.assertEqual(self.host.work.inspect()['usage']['reserved_steps'],0)
        self.assertIsNone(self.host.work.inspect()['life_id'])

    def test_close_is_session_end_not_life_recovery(self):
        self.samples();self.host.close()
        with self.assertRaises(BridgeError):self.host.work.inspect()
        self.assertIsNone(self.resolver.read()['life_id'])

if __name__=='__main__':unittest.main()
