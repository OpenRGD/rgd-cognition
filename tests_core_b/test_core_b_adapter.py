"""Real COG consumer against exact Core-B schema; no fixture consumer imported."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import importlib.util
import json
import os
from pathlib import Path
import socket
import subprocess
import unittest
from unittest.mock import patch

from rgd_cognition.core_b_adapter import (BridgeError, CoreBSchema, LocalOwners, Limits,
    KernelSession, make_goal, goal_revision, digest, decode, wire)

UPSTREAM = Path(os.environ['CORE_B_CHECKOUT']) / 'contracts/kernel/v0.1.0'
RAW = (UPSTREAM/'schemas/kernel-goal-effect.schema.json').read_bytes()
POS = json.loads((UPSTREAM/'fixtures/positive.json').read_text())['records']
NEG = json.loads((UPSTREAM/'fixtures/negative.json').read_text())['cases']


class Clock:
    def __init__(self): self.value = 100
    def __call__(self): return self.value


def base_context():
    return dict(revision='sha256:'+'1'*64, policy_revision=Limits().revision,
                session_id='test:session', runtime_instance_id='test:runtime', scope='SESSION_SCOPED',
                life_binding_ref=None, life_activation_epoch=None, role_fencing_generation=7)


class BoundaryTests(unittest.TestCase):
    def setUp(self):
        self.schema, self.owners, self.clock = CoreBSchema(RAW), LocalOwners(), Clock()
        self.ctx = base_context()
        self.policy = Limits(enabled=True, total_steps=8, total_wall_ms=4000, queue_items=4)
        self.host = self.new_host(self.policy)
        self.host.set_resources(self.owners.operator, 'NORMAL')

    def new_host(self, policy):
        return KernelSession(self.schema, owners=self.owners, policy=policy,
            context_supplier=lambda: deepcopy(self.ctx), clock_ms=self.clock, clock_domain='test:clock')

    def goal(self, gid='g:1', **kw):
        data = dict(goal_id=gid, task_ref='cog.task.v1:imu-uncertainty', context=self.ctx,
            clock_domain='test:clock', created_ms=100, ttl_ms=1000,
            producer_ref=self.owners.producer(self.owners.model)[0], origin='MODEL',
            budget=dict(wall_time_ms=1000, steps=2, subgoals=2, depth=2, queue_items=1),
            evidence_refs=['test:evidence'])
        data.update(kw)
        return make_goal(self.schema, **data)

    def submit(self, goal=None, key='request:1'):
        return self.host.submit(self.owners.model, goal or self.goal(), key=key)

    def start(self, goal=None):
        goal = goal or self.goal()
        self.submit(goal)
        self.host.move(self.owners.work, goal['goal_id'], 'RUNNING', key='start:1')
        return self.host.ticket(self.owners.work, goal['goal_id'])

    def test_valid_goal_work_finish_and_single_release(self):
        t = self.start()
        result = self.host.finish(self.owners.work, t, code='ANALYSIS_COMPLETE', evidence_refs=['test:evidence'], key='end')
        self.schema.check('AgendaTransition', result['transition'])
        self.assertEqual(result['outcome']['verification'], 'UNVERIFIED')
        before = self.host.inspect()['usage']
        self.assertEqual(before['spent_steps'], 1)
        self.assertEqual(before['reserved_steps'], 0)
        self.assertEqual(before['reserved_slots'], 0)
        self.assertEqual(result, self.host.finish(self.owners.work,t,code='ANALYSIS_COMPLETE',evidence_refs=['test:evidence'],key='end'))
        self.assertEqual(before, self.host.inspect()['usage'])

    def test_exact_duplicate_no_double_reservation(self):
        first = self.submit()
        before = self.host.inspect()['usage']
        self.assertEqual(first,self.submit())
        self.assertEqual(before,self.host.inspect()['usage'])

    def test_same_goal_id_new_key_is_not_new_work(self):
        self.submit()
        with self.assertRaisesRegex(BridgeError, 'GOAL_ID_CONFLICT'): self.submit(key='other')

    def test_model_self_admission_record_refused(self):
        decision = self.submit()
        with self.assertRaisesRegex(BridgeError, 'RECORD_NOT_INGESTIBLE'):
            self.host.accept_record(self.owners.model,'GoalAdmissionDecision',decision)

    def test_model_cannot_start_complete_or_change_resources(self):
        self.submit()
        for operation in (lambda:self.host.move(self.owners.model,'g:1','RUNNING',key='k'),
                          lambda:self.host.set_resources(self.owners.model,'NORMAL')):
            with self.assertRaisesRegex(BridgeError,'WRONG_'): operation()

    def test_claimed_producer_strings_are_not_channels(self):
        for owner in ('cog.local:model', object(), LocalOwners().model, {'role':'Work'}):
            with self.assertRaisesRegex(BridgeError,'UNAUTHENTICATED_PRODUCER'):
                self.host.submit(owner,self.goal(),key='k')

    def test_origin_role_cannot_be_forged(self):
        goal=self.goal();goal['origin']='Work';goal['goal_revision']=goal_revision(goal)
        with self.assertRaisesRegex(BridgeError,'PRODUCER_ROLE_MISMATCH'):self.submit(goal)

    def test_shape_valid_allow_receipt_is_not_a_grant(self):
        gate=deepcopy(POS['gate']['record']);gate['context']=self.ctx
        gate['lifetime']['clock_domain']='test:clock'
        self.schema.check('EffectGateDecision',gate)
        with self.assertRaisesRegex(BridgeError,'RECORD_NOT_INGESTIBLE'):
            self.host.accept_record(self.owners.model,'EffectGateDecision',gate)

    def test_stale_exact_goal_replay_does_not_renew_lifetime(self):
        self.submit();self.clock.value=1100
        with self.assertRaisesRegex(BridgeError,'EXPIRED_OR_FUTURE'):self.submit()
        self.assertEqual(self.host.inspect()['goals']['g:1']['state'],'CANCELLED')

    def test_wall_consumption_retained_after_release(self):
        t=self.start();self.clock.value+=250
        self.host.finish(self.owners.work,t,code='ABSTAIN',evidence_refs=[],key='end')
        usage=self.host.inspect()['usage']
        self.assertEqual(usage['spent_wall_ms'],250)
        self.assertEqual(usage['reserved_wall_ms'],0)

    def test_audit_full_cannot_prevent_administrative_stop(self):
        host=self.new_host(Limits(enabled=True,records=8));host.set_resources(self.owners.operator,'NORMAL')
        host.submit(self.owners.model,self.goal(),key='first');host.move(self.owners.work,'g:1','RUNNING',key='run')
        for i in range(6):
            g=self.goal('deny:'+str(i));g['requested_effects']=['DIGITAL_EFFECT_REQUEST'];g['goal_revision']=goal_revision(g)
            host.submit(self.owners.model,g,key='deny:'+str(i))
        with self.assertRaisesRegex(BridgeError,'BACKPRESSURE'):host.set_resources(self.owners.operator,'LOW')
        self.assertTrue(host._closed)
        self.assertEqual(host._jobs['g:1'].state,'CANCELLED')
        self.assertEqual(host._usage()['reserved_slots'],0)

    def test_default_policy_disabled_and_resources_unknown(self):
        h=self.new_host(Limits())
        d=h.submit(self.owners.model,self.goal(),key='disabled')
        self.assertEqual(d['outcome'],'REJECT')
        h=self.new_host(self.policy)
        d=h.submit(self.owners.model,self.goal(),key='unknown')
        self.assertEqual(d['outcome'],'DEFER')
        self.assertIsNone(d['allocated_budget'])

    def test_deferred_candidate_cannot_be_silently_readmitted(self):
        self.host.set_resources(self.owners.operator,'LOW');d=self.submit()
        self.host.set_resources(self.owners.operator,'NORMAL')
        self.assertEqual(d,self.submit())
        with self.assertRaisesRegex(BridgeError,'GOAL_NOT_ADMITTED'):
            self.host.move(self.owners.work,'g:1','RUNNING',key='start')

    def test_aggregate_steps_reserve_before_consumption(self):
        a=self.goal(budget=dict(wall_time_ms=500,steps=5,subgoals=1,depth=2,queue_items=1))
        b=self.goal('g:2',budget=dict(wall_time_ms=500,steps=5,subgoals=1,depth=2,queue_items=1))
        self.assertEqual(self.submit(a)['outcome'],'ADMIT')
        self.assertEqual(self.submit(b,key='b')['outcome'],'DEFER')
        self.assertEqual(self.host.inspect()['usage']['reserved_steps'],5)

    def test_concurrent_admission_is_atomic(self):
        goals=[self.goal('g:'+str(i),budget=dict(wall_time_ms=500,steps=5,subgoals=0,depth=0,queue_items=1)) for i in range(10)]
        with ThreadPoolExecutor(max_workers=5) as executor:
            ds=list(executor.map(lambda g:self.submit(g,key=g['goal_id']),goals))
        self.assertEqual(sum(d['outcome']=='ADMIT' for d in ds),1)

    def test_aggregate_wall_and_queue_reserved(self):
        for field,value in (('wall_time_ms',3000),('queue_items',3)):
            host=self.new_host(self.policy);host.set_resources(self.owners.operator,'NORMAL')
            g=self.goal();g['budget'][field]=value;g['goal_revision']=goal_revision(g)
            h=deepcopy(g);h['goal_id']='g:2';h['goal_revision']=goal_revision(h)
            self.assertEqual(host.submit(self.owners.model,g,key='a')['outcome'],'ADMIT')
            self.assertEqual(host.submit(self.owners.model,h,key='b')['outcome'],'DEFER')

    def test_consumed_steps_never_refunded(self):
        t=self.start();self.host.finish(self.owners.work,t,code='ANALYSIS_COMPLETE',evidence_refs=['test:evidence'],key='finish')
        goal=self.goal('g:2',budget=dict(wall_time_ms=1,steps=8,subgoals=0,depth=0,queue_items=1))
        self.assertEqual(self.submit(goal,key='new')['outcome'],'DEFER')

    def test_child_requires_running_parent_fresh_admission_and_sibling_limit(self):
        self.start()
        children=[self.goal('child:'+str(i),parent_goal_id='g:1',depth=1) for i in range(3)]
        ds=[self.submit(g,key=g['goal_id']) for g in children]
        self.assertEqual([d['outcome'] for d in ds],['ADMIT','ADMIT','REJECT'])
        self.assertEqual(len({d['decision_id'] for d in ds}),3)

    def test_child_cannot_inherit_or_escape_parent_depth(self):
        g=self.goal();g['budget']['depth']=0;g['goal_revision']=goal_revision(g)
        self.start(g)
        d=self.submit(self.goal('child',parent_goal_id='g:1',depth=1),key='child')
        self.assertEqual(d['outcome'],'REJECT')

    def test_parent_cancellation_stops_child_and_releases(self):
        self.start();self.submit(self.goal('child',parent_goal_id='g:1',depth=1),key='child')
        self.host.move(self.owners.work,'g:1','CANCELLED',key='stop')
        state=self.host.inspect()
        self.assertEqual(state['goals']['child']['state'],'CANCELLED')
        self.assertEqual(state['usage']['reserved_slots'],0)

    def test_pause_reason_and_role_fence_not_conflated(self):
        t=self.start();self.host.move(self.owners.work,'g:1','PAUSED',key='pause',reason='PAUSED_USER')
        self.assertEqual(self.host.inspect()['goals']['g:1']['detail']['reason_code'],'PAUSED_USER')
        self.host.move(self.owners.work,'g:1','RUNNING',key='resume')
        fresh=self.host.ticket(self.owners.work,'g:1')
        self.assertNotEqual(fresh['task_generation'],t['task_generation'])
        self.assertEqual(fresh['context']['role_fencing_generation'],7)
        with self.assertRaisesRegex(BridgeError,'STALE_TASK_RESULT'):
            self.host.finish(self.owners.work,t,code='ANALYSIS_COMPLETE',evidence_refs=['test:evidence'],key='old')

    def test_resource_pause_preserves_transition_chain(self):
        self.start();self.host.set_resources(self.owners.operator,'LOW')
        self.assertEqual(self.host.inspect()['goals']['g:1']['detail']['reason_code'],'PAUSED_LIFE')
        self.host.set_resources(self.owners.operator,'NORMAL')
        self.host.move(self.owners.work,'g:1','RUNNING',key='resume')
        ts=self.host.transitions('g:1')
        for index,row in enumerate(ts):
            self.schema.check('AgendaTransition',row['transition'])
            self.assertEqual(row['transition']['sequence'],index)
            if index:
                self.assertEqual(row['transition']['previous_transition_ref'],ts[index-1]['transition']['transition_id'])
                self.assertEqual(row['transition']['from_state'],ts[index-1]['transition']['to_state'])

    def test_waiting_evidence_is_not_success(self):
        t=self.start();r=self.host.finish(self.owners.work,t,code='INSUFFICIENT_EVIDENCE',evidence_refs=[],key='wait')
        self.assertEqual(r['transition']['to_state'],'PAUSED')
        self.assertEqual(r['outcome']['code'],'INSUFFICIENT_EVIDENCE')

    def test_abstention_preserved_as_inquiry_outcome(self):
        t=self.start();r=self.host.finish(self.owners.work,t,code='ABSTAIN',evidence_refs=[],key='abstain')
        self.assertEqual(r['transition']['to_state'],'COMPLETED')
        self.assertEqual(r['outcome']['code'],'ABSTAIN')
        self.assertEqual(r['outcome']['verification'],'UNVERIFIED')

    def test_terminal_rejected_never_reopens_on_ttl(self):
        g=self.goal();g['requested_effects']=['PHYSICAL_ACTION_REQUEST'];g['goal_revision']=goal_revision(g)
        self.submit(g);self.clock.value=2000
        self.assertEqual(self.host.inspect()['goals']['g:1']['state'],'REJECTED')
        with self.assertRaises(BridgeError):self.host.move(self.owners.work,'g:1','RUNNING',key='restart')

    def test_paused_completion_and_terminal_resume_refused(self):
        t=self.start();self.host.move(self.owners.work,'g:1','PAUSED',key='pause')
        with self.assertRaisesRegex(BridgeError,'NOT_RUNNING'):
            self.host.finish(self.owners.work,t,code='ABSTAIN',evidence_refs=[],key='finish')
        self.host.move(self.owners.work,'g:1','CANCELLED',key='stop')
        with self.assertRaisesRegex(BridgeError,'ILLEGAL_TRANSITION'):
            self.host.move(self.owners.work,'g:1','RUNNING',key='restart')

    def test_unknown_evidence_and_fake_physical_success_refused(self):
        t=self.start()
        for code,refs in [('PHYSICAL_STEP_CONFIRMED',['test:evidence']),('ANALYSIS_COMPLETE',['fake:evidence']),('ANALYSIS_COMPLETE',[])]:
            with self.assertRaises(BridgeError):self.host.finish(self.owners.work,t,code=code,evidence_refs=refs,key='bad')
        self.assertEqual(self.host.inspect()['usage']['spent_steps'],0)

    def test_ttl_half_open_boundary_and_wall_limit(self):
        t=self.start();self.clock.value=1100
        with self.assertRaises(BridgeError):self.host.finish(self.owners.work,t,code='ABSTAIN',evidence_refs=[],key='late')
        self.assertEqual(self.host.inspect()['goals']['g:1']['state'],'CANCELLED')
        self.assertEqual(self.host.inspect()['usage']['reserved_steps'],0)

    def test_future_unaligned_and_foreign_clock(self):
        for field,value in [('created_ms',101),('clock_domain','foreign:clock'),('quality','UNALIGNED')]:
            g=self.goal();g['lifetime'][field]=value;g['goal_revision']=goal_revision(g)
            with self.assertRaises(BridgeError):self.submit(g)

    def test_clock_regression_closes_session(self):
        self.start();self.clock.value=99
        with self.assertRaisesRegex(BridgeError,'CLOCK_REGRESSION'):self.host.inspect()
        self.clock.value=101
        with self.assertRaisesRegex(BridgeError,'SESSION_CLOSED'):self.host.inspect()

    def test_capacity_retains_keys_does_not_evict(self):
        h=self.new_host(Limits(enabled=False,records=8));g=self.goal()
        for i in range(8):h.submit(self.owners.model,self.goal('x:'+str(i)),key='key:'+str(i))
        with self.assertRaisesRegex(BridgeError,'BACKPRESSURE'):h.submit(self.owners.model,self.goal('last'),key='last')
        self.assertEqual(h.submit(self.owners.model,self.goal('x:0'),key='key:0')['outcome'],'REJECT')

    def test_schema_pin_unknown_version_and_ref(self):
        with self.assertRaisesRegex(BridgeError,'PIN_MISMATCH'):CoreBSchema(RAW+b' ')
        with self.assertRaisesRegex(BridgeError,'UNKNOWN_CONTRACT'):self.schema.check('Unknown',{})
        g=self.goal();g['schema_version']='v999'
        with self.assertRaises(BridgeError):self.submit(g)

    def test_no_positive_life_context(self):
        self.ctx.update(scope='LIFE_BOUND',life_binding_ref='fake:binding',life_activation_epoch=1)
        with self.assertRaisesRegex(BridgeError,'LIFE_BOUND_UNSUPPORTED'):self.new_host(self.policy)

    def test_no_effectful_io_on_exercised_path(self):
        import builtins
        with patch.object(socket,'socket',side_effect=AssertionError('network')),patch.object(subprocess,'Popen',side_effect=AssertionError('process')),patch.object(builtins,'open',side_effect=AssertionError('file')):
            t=self.start();self.host.finish(self.owners.work,t,code='ABSTAIN',evidence_refs=[],key='finish')

    def test_mutated_return_cannot_change_internal_state(self):
        d=self.submit();d['allocated_budget']['steps']=10000
        self.assertEqual(self.host.inspect()['usage']['reserved_steps'],2)
        self.assertEqual(self.submit()['allocated_budget']['steps'],2)

    def test_true_goal_revision_is_checked(self):
        g=self.goal();g['budget']['steps']=3
        with self.assertRaisesRegex(BridgeError,'GOAL_REVISION_MISMATCH'):self.submit(g)

    def test_payload_strings_never_execute(self):
        g=self.goal();g['task_ref']='https://invalid.example/run';g['goal_revision']=goal_revision(g)
        self.assertEqual(self.submit(g)['outcome'],'REJECT')

    def test_goal_event_digests_full_payload_and_changed_envelope_conflict(self):
        g=self.goal();p=self.owners.producer(self.owners.model)[0]
        event=dict(schema_version='openrgd_kernel_event_v0.1-candidate',event_id='evt:1',kind='openrgd.kernel.v0_1.goal_candidate',
          producer_kernel_id=p,correlation_id='corr:1',idempotency_key='event:1',context=self.ctx,lifetime=g['lifetime'],
          payload_ref=g['goal_id'],payload_digest=digest(g),provenance=g['provenance'],grants_authority=False)
        d=self.host.accept_record(self.owners.model,'KernelEvent',event,payload=g)
        self.assertEqual(d,self.host.accept_record(self.owners.model,'KernelEvent',event,payload=g))
        event['correlation_id']='changed'
        with self.assertRaisesRegex(BridgeError,'IDEMPOTENCY_CONFLICT'):
            self.host.accept_record(self.owners.model,'KernelEvent',event,payload=g)

    def test_advisory_not_negotiated(self):
        e=deepcopy(POS['event']['record']);e['context']=self.ctx;e['lifetime']['clock_domain']='test:clock'
        e['kind']='openrgd.kernel.v0_1.advisory'
        with self.assertRaisesRegex(BridgeError,'UNNEGOTIATED_EVENT_KIND'):
            self.host.accept_record(self.owners.model,'KernelEvent',e,payload={})

    def test_synthetic_oneiric_uses_actual_c0_review_without_history(self):
        from rgd_cognition.core_b_oneiric import oneiric_goal
        source=digest('source')
        budget=dict(wall_time_ms=1000,steps=3,subgoals=0,depth=0,queue_items=1)
        package=oneiric_goal(self.schema,source_event_ref=source,context=self.ctx,
            clock_domain='test:clock',created_ms=100,ttl_ms=1000,
            producer_ref=self.owners.producer(self.owners.imagination)[0],budget=budget)
        g=package['goal']
        self.assertEqual(self.host.submit(self.owners.imagination,g,key='oneiric:1',
                                          task_detail=package['detail'])['outcome'],'ADMIT')
        self.host.move(self.owners.work,g['goal_id'],'RUNNING',key='oneiric:start')
        t=self.host.ticket(self.owners.work,g['goal_id'])
        first=self.host.review_oneiric(self.owners.work,t,observation_tags=['FOOT_LIFT'],key='review:1')
        second=self.host.review_oneiric(self.owners.work,t,observation_tags=['NO_TRANSLATION'],key='review:2')
        self.assertEqual(second['supersedes_annotation_ref'],first['annotation_id'])
        self.assertIsNone(second['chronon_id'])
        r=self.host.finish(self.owners.work,t,code='ANALYSIS_COMPLETE',evidence_refs=[source],
                           key='oneiric:finish',interpretation=second)
        self.assertEqual(r['outcome']['verification'],'UNVERIFIED')
        self.assertEqual(r['outcome']['interpretation']['label'],'STEP_NOT_SUPPORTED_IN_FIXTURE')
        self.assertEqual(r['cognitive_trace']['interpretation_digest'],digest(second))


# Individually reported semantic mutations, not repeated interpreter counts.
for field in ('budget','lifetime','requested_effects','task_ref','provenance'):
    def changed(self,field=field):
        self.submit();g=self.goal()
        if field=='budget':g[field]['steps']=3
        elif field=='lifetime':g[field]['ttl_ms']=999
        elif field=='requested_effects':g[field]=['COMMUNICATION_REQUEST']
        elif field=='task_ref':g[field]='cog.task.v1:oneiric-first-step';g['goal_kind']='ONEIRIC_REVIEW'
        else:g[field]['evidence_refs']=['test:other']
        g['goal_revision']=goal_revision(g)
        with self.assertRaisesRegex(BridgeError,'IDEMPOTENCY_CONFLICT'):self.submit(g)
    setattr(BoundaryTests,'test_changed_duplicate_'+field,changed)

for field,value in [('revision','sha256:'+'2'*64),('policy_revision','changed:policy'),('session_id','changed:session'),
                    ('runtime_instance_id','changed:runtime'),('role_fencing_generation',8)]:
    def invalidates(self,field=field,value=value):
        t=self.start();self.ctx[field]=value
        with self.assertRaises(BridgeError):self.host.finish(self.owners.work,t,code='ABSTAIN',evidence_refs=[],key='late')
        self.assertEqual(self.host._jobs['g:1'].state,'CANCELLED')
    setattr(BoundaryTests,'test_context_change_'+field,invalidates)

for effect in ('HISTORY_COMMIT_REQUEST','COMMUNICATION_REQUEST','DIGITAL_EFFECT_REQUEST','PHYSICAL_ACTION_REQUEST'):
    def forbidden(self,effect=effect):
        g=self.goal();g['requested_effects']=[effect];g['goal_revision']=goal_revision(g)
        self.assertEqual(self.submit(g)['outcome'],'REJECT')
        req=deepcopy(POS['request']['record']);req['context']=self.ctx;req['lifetime']['clock_domain']='test:clock';req['category']=effect
        with self.assertRaisesRegex(BridgeError,'EFFECT_GATE_NOT_CONNECTED'):self.host.reject_effect(self.owners.work,req)
    setattr(BoundaryTests,'test_effect_'+effect,forbidden)


class SchemaFixtures(unittest.TestCase):
    def setUp(self):self.schema=CoreBSchema(RAW)
    def test_parser_duplicate_nonfinite_depth(self):
        for raw in (b'{"a":1,"a":2}',b'{"a":NaN}',b'{"a":Infinity}',b'{"a":1.0}'):
            with self.assertRaises(BridgeError):decode(raw)
        a={}
        for _ in range(30):a={'a':a}
        with self.assertRaises(BridgeError):wire(a)
    def test_upstream_validator_accepts_actual_cog_outputs(self):
        spec=importlib.util.spec_from_file_location('upstream_shape_only',UPSTREAM/'validate.py')
        mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
        o=LocalOwners();ctx=base_context();g=make_goal(self.schema,goal_id='actual:cog',task_ref='cog.task.v1:imu-uncertainty',
          context=ctx,clock_domain='test:clock',created_ms=100,ttl_ms=1000,producer_ref=o.producer(o.model)[0],origin='MODEL',
          budget=dict(wall_time_ms=100,steps=1,subgoals=0,depth=0,queue_items=1),evidence_refs=['e:1'])
        host=KernelSession(self.schema,owners=o,policy=Limits(enabled=True),context_supplier=lambda:ctx,clock_ms=lambda:100,clock_domain='test:clock')
        host.set_resources(o.operator,'NORMAL');d=host.submit(o.model,g,key='new')
        mod.validate('CognitiveGoalCandidate',g);mod.validate('GoalAdmissionDecision',d)
        row=host.move(o.work,g['goal_id'],'RUNNING',key='run');mod.validate('AgendaTransition',row['transition'])

for name,item in POS.items():
    def positive(self,item=item):self.schema.check(item['type'],item['record'])
    setattr(SchemaFixtures,'test_upstream_positive_'+name,positive)
for case in NEG:
    def negative(self,case=case):
        source=POS[case['base']];record=deepcopy(source['record'])
        for path,value in case['set'].items():
            parts=path.split('.'); node=record
            for part in parts[:-1]:node=node[part]
            node[parts[-1]]=value
        with self.assertRaises(BridgeError):self.schema.check(source['type'],record)
    setattr(SchemaFixtures,'test_upstream_negative_'+case['id'],negative)

if __name__=='__main__':unittest.main()
