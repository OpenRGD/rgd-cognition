"""Explicit synthetic service rehearsal; disabled unless the operator opts in."""
from __future__ import annotations

import argparse
import json
import sys

from . import (PrivateStatus, ServiceConfig, ServiceLabError, ServiceLoop,
               StopSignal, read_core_b_schema)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="run one finite synthetic laboratory session")
    run.add_argument("--enable-synthetic-lab", action="store_true")
    run.add_argument("--core-b-checkout", required=True)
    run.add_argument("--runtime-dir", required=True)
    run.add_argument("--duration-seconds", type=int, default=60)
    status = commands.add_parser("status", help="read cached diagnostics; does not prove liveness")
    status.add_argument("--runtime-dir", required=True)
    args = parser.parse_args()
    try:
        if args.command == "status":
            with PrivateStatus(args.runtime_dir) as output:
                report = output.read()
        else:
            config = ServiceConfig(enabled=args.enable_synthetic_lab,
                                   duration_seconds=args.duration_seconds)
            if not config.enabled:
                raise ServiceLabError("SERVICE_DISABLED")
            with PrivateStatus(args.runtime_dir, writer=True) as output, StopSignal() as stop:
                loop = ServiceLoop(read_core_b_schema(args.core_b_checkout), config)
                report = loop.run(output.publish, stop)
        print(json.dumps(report, allow_nan=False, sort_keys=True, separators=(",", ":")))
        return 0
    except Exception as exc:
        reason = str(exc) if isinstance(exc, ServiceLabError) else "SERVICE_START_FAILED"
        print(json.dumps({"error": reason, "fixture_only": True}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
