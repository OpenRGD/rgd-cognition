"""Offline genuine C1 -> Core-B replay. No real sensor, Life or Chronon."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
from .attention_c1_demo import FixtureClock, fixture_binding, fixture_sample
from .context import context_slice
from .core_b_adapter import Limits
from .core_b_c1 import CoreBAttentionHost


def run(schema_bytes):
    clock=FixtureClock()
    host=CoreBAttentionHost(schema_bytes, context_supplier=lambda:context_slice('lab-robot'),
                           binding=fixture_binding(), policy=Limits(enabled=True), clock=clock)
    host.set_resources(host.owners.operator,'NORMAL')
    output=None
    for index in range(3):
        clock.advance(100)
        output=host.ingest(fixture_sample(index),received_ns=clock(),freshness='FRESH',consent=True)
    if not output or not output['proposal']:
        raise RuntimeError('REPLAY_NO_CANDIDATE')
    goal=output['proposal']['goal']
    host.work.move(host.owners.work,goal['goal_id'],'RUNNING',key='demo:start')
    ticket=host.work.ticket(host.owners.work,goal['goal_id'])
    result=host.work.finish(host.owners.work,ticket,code='ANALYSIS_COMPLETE',
                            evidence_refs=goal['provenance']['evidence_refs'],key='demo:finish')
    report={'fixture_only':True,'scope':'SESSION_SCOPED','admission':output['proposal']['admission'],
            'outcome':result,'life_id':None,'chronon_status':'NOT_CONNECTED',
            'usage':host.work.inspect()['usage'],'effects_executed':False}
    host.close()
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--core-b-checkout',required=True)
    args=parser.parse_args()
    path=Path(args.core_b_checkout)/'contracts/kernel/v0.1.0/schemas/kernel-goal-effect.schema.json'
    with path.open('rb') as handle:
        raw=handle.read(65537)
    print(json.dumps(run(raw),indent=2))


if __name__=='__main__':main()
