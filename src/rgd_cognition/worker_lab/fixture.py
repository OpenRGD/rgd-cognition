"""Fixed, stdlib-only synthetic inquiry worker. Not a general tool executor.

Invoked by an absolute reviewed script path with isolated Python flags. One
bounded JSON request on stdin, one bounded JSON response on stdout, then exit.
No imports of host/Work objects, commands, devices, network or persistence.
"""
from __future__ import annotations

import hashlib
import json
import re
import signal
import sys
import time

MAX_FRAME = 4096
PROFILE = "cog.runtime.fixture-worker.v0.1-candidate"
TASK = "cog.task.v1:imu-uncertainty"
MODES = frozenset({"NORMAL", "BLOCK", "CRASH", "MALFORMED", "OVERSIZE", "WRONG_TICKET", "TRAILING", "IGNORE_TERM"})
REF = re.compile(r"sha256:[0-9a-f]{64}\Z")


class WorkerProtocolError(ValueError):
    pass


def _require(condition):
    if not condition:
        raise WorkerProtocolError("INVALID_WORKER_FRAME")


def _pairs(pairs):
    result = {}
    for k, v in pairs:
        _require(k not in result)
        result[k] = v
    return result


def _bad(_):
    raise WorkerProtocolError("INVALID_WORKER_FRAME")


def encode_frame(value):
    try:
        data = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"),
                          allow_nan=False).encode("ascii")
    except (ValueError, TypeError, RecursionError, UnicodeError):
        raise WorkerProtocolError("INVALID_WORKER_FRAME") from None
    _require(0 < len(data) <= MAX_FRAME)
    return data


def decode_frame(data):
    _require(type(data) is bytes and 0 < len(data) <= MAX_FRAME)
    try:
        value = json.loads(data, object_pairs_hook=_pairs, parse_constant=_bad)
        _require(type(value) is dict and encode_frame(value) == data)
        return value
    except (ValueError, TypeError, RecursionError, UnicodeError):
        raise WorkerProtocolError("INVALID_WORKER_FRAME") from None


def validate_request(value):
    _require(type(value) is dict and set(value) == {
        "profile", "task_ref", "request_id", "ticket_digest", "evidence_refs", "fixture_only"})
    _require(value["profile"] == PROFILE and value["task_ref"] == TASK and value["fixture_only"] is True)
    for k in ("request_id", "ticket_digest"):
        _require(type(value[k]) is str and REF.fullmatch(value[k]) is not None)
    refs = value["evidence_refs"]
    _require(type(refs) is list and 1 <= len(refs) <= 16 and
             all(type(x) is str and REF.fullmatch(x) is not None for x in refs) and len(set(refs)) == len(refs))
    encode_frame(value)
    return value


def expected_response(request):
    request = validate_request(request)
    # This is a deterministic reference-presence inquiry, not reasoning over
    # payloads or a claim about physical motion. Work marks it UNVERIFIED.
    return {"profile": PROFILE, "request_id": request["request_id"],
            "ticket_digest": request["ticket_digest"],
            "request_sha256": hashlib.sha256(encode_frame(request)).hexdigest(),
            "code": "ANALYSIS_COMPLETE", "evidence_refs": list(request["evidence_refs"]),
            "fixture_only": True}


def validate_response(raw, request):
    actual = decode_frame(raw)
    expected = expected_response(request)
    _require(encode_frame(actual) == encode_frame(expected))
    return actual


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in MODES:
        return 2
    mode = sys.argv[1]
    try:
        request = validate_request(decode_frame(sys.stdin.buffer.read(MAX_FRAME + 1)))
        if mode == "BLOCK":
            time.sleep(3)  # fixed finite fault fixture; supervisor must cancel/reap
        if mode == "IGNORE_TERM":
            signal.signal(signal.SIGTERM, signal.SIG_IGN)
            sys.stdout.buffer.write(b"{")  # readiness marker, never a valid result
            sys.stdout.buffer.flush()
            time.sleep(3)
        if mode == "CRASH":
            return 7
        if mode == "MALFORMED":
            out = b'{"bad":'
        elif mode == "OVERSIZE":
            out = b"x" * (MAX_FRAME + 1)
        else:
            response = expected_response(request)
            if mode == "WRONG_TICKET":
                response["ticket_digest"] = "sha256:" + "0" * 64
            out = encode_frame(response)
            if mode == "TRAILING":
                out += b"\n{}"
        sys.stdout.buffer.write(out)
        sys.stdout.buffer.flush()
        return 0
    except (ValueError, OSError, TypeError):
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
