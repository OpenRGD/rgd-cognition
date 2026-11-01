"""Offline candidate CORE-D projection smoke, no sensor/Chronon/identity/voice."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
from copy import deepcopy

from .core_b_adapter import CoreBSchema, LocalOwners, Limits, KernelSession, digest
from .core_b_oneiric import oneiric_goal
from .core_d_projection import CoreDShape, project_oneiric, history_commit_preview


class Clock:
    def __init__(self):self.ms=100
    def __call__(self):return self.ms


def run(core_b_checkout: Path, core_d_checkout: Path) -> dict:
    core_b=CoreBSchema((core_b_checkout/'contracts/kernel/v0.1.0/schemas/kernel-goal-effect.schema.json').read_bytes())
    core_d=CoreDShape((core_d_checkout/'contracts/temporal-memory/v0.1.0/schemas/temporal-memory.schema.json').read_bytes())
    owners,clock=LocalOwners(),Clock()
    ctx=dict(revision='sha256:'+'1'*64,policy_revision=Limits().revision,
             session_id='demo:session:oneiric',runtime_instance_id='demo:runtime:oneiric',
             scope='SESSION_SCOPED',life_binding_ref=None,life_activation_epoch=None,
             role_fencing_generation=0)
    work=KernelSession(core_b,owners=owners,
                       policy=Limits(enabled=True,total_steps=6,total_wall_ms=3000),
                       context_supplier=lambda:deepcopy(ctx),clock_ms=clock,
                       clock_domain='demo:clock:oneiric')
    work.set_resources(owners.operator,'NORMAL')
    event_ref=digest('fixture possible first step; not physical evidence')
    pkg=oneiric_goal(core_b,source_event_ref=event_ref,context=ctx,
         clock_domain='demo:clock:oneiric',created_ms=100,ttl_ms=2000,
         producer_ref=owners.producer(owners.imagination)[0],
         budget=dict(wall_time_ms=500,steps=3,subgoals=0,depth=0,queue_items=1),
         goal_id='demo:goal:first-step-review')
    decision=work.submit(owners.imagination,pkg['goal'],key='demo:submit',task_detail=pkg['detail'])
    work.move(owners.work,pkg['goal']['goal_id'],'RUNNING',key='demo:start')
    ticket=work.ticket(owners.work,pkg['goal']['goal_id'])
    work.review_oneiric(owners.work,ticket,observation_tags=['FOOT_LIFT'],key='demo:review:1')
    last=work.review_oneiric(owners.work,ticket,observation_tags=['NO_TRANSLATION'],key='demo:review:2')
    result=work.finish(owners.work,ticket,code='ANALYSIS_COMPLETE',evidence_refs=[event_ref],
            interpretation=last,key='demo:finish')
    draft=project_oneiric(core_d,core_b,result,knowledge_at_ms=100,clock_domain='demo:clock:oneiric')
    future=history_commit_preview(core_d,core_b,result,draft)
    work.close()
    return {"fixture_only":True,"core_b_admission":decision['outcome'],
            "result":result['outcome']['result_semantics'],
            "oneiric_assessment":draft['oneiric_review']['assessment'],
            "draft_records":len(draft['memory_annotations'])+3,
            "scope":draft['scope'],"history":future['status'],
            "commit_request":future['history_commit_request'],
            "life_id":future['life_id'],"chronon_id":future['chronon_id'],
            "effects_executed":False}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--core-b-checkout',type=Path,required=True)
    parser.add_argument('--core-d-checkout',type=Path,required=True)
    args=parser.parse_args()
    print(json.dumps(run(args.core_b_checkout,args.core_d_checkout),indent=2,sort_keys=True))

if __name__ == '__main__':main()
