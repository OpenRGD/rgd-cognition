"""Finite installed-wheel smoke for the fixed synthetic process; no live input."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from time import monotonic, sleep

from ..attention_c1_demo import FixtureClock, fixture_sample
from ..core_b_adapter import Limits
from ..runtime_lab import RuntimeLabConfig, RuntimeLabOwners, RuntimeLabError
from . import WorkerLab, WorkerLabConfig


def run_fixture(schema_bytes):
    clock, owners = FixtureClock(), RuntimeLabOwners()
    lab = WorkerLab(schema_bytes, owners=owners, clock_ns=clock,
                    config=RuntimeLabConfig(enabled=True, work=Limits(enabled=True)),
                    worker=WorkerLabConfig(enabled=True, wall_ms=1000))
    event = None
    try:
        s = lab.start(owners.operator)
        lab.request_control(owners.operator, "RESOURCE_NORMAL")
        lab.tick(owners.operator)
        for i in range(3):
            clock.advance(100)
            row = fixture_sample(i)
            row["session_id"] = s["source_session"]
            if lab.offer(owners.synthetic_source, runtime_session=s["runtime_session"],
                         sample=row, consent=True) != "QUEUED":
                raise RuntimeLabError("FIXTURE_INPUT_REJECTED")
            lab.tick(owners.operator)
        eligible = lab.eligible(owners.operator)
        if len(eligible) != 1:
            raise RuntimeLabError("FIXTURE_ADMISSION_MISSING")
        if lab.dispatch(owners.operator, eligible[0]["goal_id"])["status"] != "DISPATCHED":
            raise RuntimeLabError("FIXTURE_DISPATCH_FAILED")
        end = monotonic() + 3
        while monotonic() < end:
            event = lab.tick(owners.operator).get("worker")
            if event is not None:
                break
            sleep(.005)
        if not event or event["status"] != "COMPLETED":
            raise RuntimeLabError("FIXTURE_WORKER_FAILED")
        result = event["result"]
        active = lab.health(owners.operator)
    finally:
        closed = lab.stop(owners.operator)
    if closed["state"] != "STOPPED" or closed["worker_reap_pending"]:
        raise RuntimeLabError("FIXTURE_SHUTDOWN_FAILED")
    return {"fixture_only": True, "result_semantics": result["outcome"]["result_semantics"],
            "verification": result["outcome"]["verification"], "active": active, "closed": closed}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--core-b-checkout", required=True)
    args = p.parse_args()
    with (Path(args.core_b_checkout) / "contracts/kernel/v0.1.0/schemas/kernel-goal-effect.schema.json").open("rb") as handle:
        raw = handle.read(65537)
    print(json.dumps(run_fixture(raw), indent=2))


if __name__ == "__main__":
    main()
