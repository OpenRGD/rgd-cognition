"""Fixed disposable-CI probes. Never installed in the cognitive Python package."""
from __future__ import annotations

import argparse
import errno
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time

RUN = Path("/run/rgd-cog-lab")


def identity(pid):
    # comm may contain spaces and parentheses; starttime is field 22.
    fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
    return {"pid": pid, "start": fields[19]}


def emit(name, data):
    raw = json.dumps(data, sort_keys=True)
    if len(raw) > 8192:
        raise RuntimeError("PROBE_REPORT_LIMIT")
    (RUN / name).write_text(raw)
    print(raw, flush=True)


def negative():
    checks = {}
    def denied(name, operation, allowed):
        try:
            result = operation()
            if hasattr(result, "close"):
                result.close()
        except OSError as error:
            checks[name] = error.errno in allowed
        else:
            checks[name] = False
    # Outside controls establish these fixtures really exist and are accessible.
    denied("device_hidden", lambda: open("/dev/cog-runtime01c-probe", "rb"), {errno.ENOENT, errno.EACCES, errno.EPERM})
    denied("artifact_read_only", lambda: open("/opt/rgd-cog/current/write-probe", "ab"), {errno.EROFS})
    for name, family, kind, protocol in (
        ("ipv4_socket_denied", socket.AF_INET, socket.SOCK_STREAM, 0),
        ("ipv6_socket_denied", socket.AF_INET6, socket.SOCK_STREAM, 0),
        ("can_socket_denied", socket.AF_CAN, socket.SOCK_RAW, socket.CAN_RAW),
        ("netlink_socket_denied", socket.AF_NETLINK, socket.SOCK_RAW, 0),
        ("unix_socket_denied", socket.AF_UNIX, socket.SOCK_STREAM, 0),
    ):
        denied(name, lambda f=family, k=kind, p=protocol: socket.socket(f, k, p), {errno.EPERM, errno.EACCES})
    denied("socketpair_denied", socket.socketpair, {errno.EPERM, errno.EACCES})
    # InaccessiblePaths can expose a mode-000 replacement inode. stat() itself
    # need not fail; no read/write permission and no new AF_UNIX socket together
    # establish the intended path/IPC boundary without requiring ENOENT.
    try:
        hidden = Path("/run/rgd-cog-deny.sock")
        checks["privileged_socket_path_inaccessible"] = (
            hidden.stat().st_mode & 0o777 == 0 and
            not os.access(hidden, os.R_OK | os.W_OK)
        )
    except OSError as error:
        checks["privileged_socket_path_inaccessible"] = error.errno in {
            errno.EACCES, errno.EPERM, errno.ENOENT}
    values = dict(line.split(":", 1) for line in Path("/proc/self/status").read_text().splitlines() if ":" in line)
    checks["nonroot"] = os.getuid() != 0
    checks["no_foreign_supplementary_groups"] = set(os.getgroups()) <= {os.getgid()}
    checks["no_new_privileges"] = values["NoNewPrivs"].strip() == "1"
    checks["zero_effective_caps"] = int(values["CapEff"], 16) == 0
    checks["zero_bounding_caps"] = int(values["CapBnd"], 16) == 0
    checks["runtime_write_allowed"] = (RUN.stat().st_mode & 0o777) == 0o700
    emit("negative.json", {"mode": "negative", "checks": checks, "passed": all(checks.values())})
    time.sleep(20)  # root controller stops/reaps the finite probe after reading.


def descendants(mode):
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    me = identity(os.getpid())
    emit(mode + ".json", me)
    if mode != "grandchild":
        child_mode = "child" if mode == "parent" else "grandchild"
        subprocess.Popen([sys.executable, "-I", "-B", str(Path(__file__).resolve()), "--mode", child_mode],
                         stdin=subprocess.DEVNULL, close_fds=True, env={"LANG": "C"})
    time.sleep(20)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", required=True, choices=("negative", "parent", "child", "grandchild"))
    mode = parser.parse_args().mode
    negative() if mode == "negative" else descendants(mode)
