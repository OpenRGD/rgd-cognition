"""Offline CLI. Demo reads no devices, credentials, personal logs or networks."""
from __future__ import annotations
import argparse
import json
from . import __version__
from .demo import run_replay


def main() -> int:
    parser = argparse.ArgumentParser(description="COG candidate offline synthetic lab; NOT a robot deployment")
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)
    demo = sub.add_parser("demo", help="synthetic replay; no real sensors or LLM")
    demo.add_argument("--events", type=int, default=1000)
    args = parser.parse_args()
    if not 1 <= args.events <= 10000:
        parser.error("--events must be between 1 and 10000")
    print(json.dumps(run_replay(args.events), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
