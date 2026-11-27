"""Destructive-to-own-fixtures rehearsal ONLY in a disposable Ubuntu GitHub VM.

Not an installer. Refuses pre-existing target paths and requires an explicit flag.
CI environment flags prevent accidental use; they are not an authorization proof.
"""
from __future__ import annotations

import argparse
import grp
import json
import os
from pathlib import Path
import pwd
import re
import shutil
import socket
import stat
import subprocess
import sys
import time

from artifact import verify_bundle

BASE = Path("/opt/rgd-cog")
UNIT = Path("/run/systemd/system/rgd-cog-lab.service")
DROP = Path(str(UNIT) + ".d")
RUN = Path("/run/rgd-cog-lab")
DEVICE = Path("/dev/cog-runtime01c-probe")
SOCKET = Path("/run/rgd-cog-deny.sock")
NAME = "rgd-cog-lab.service"


def command(*args, check=True, timeout=45):
    result = subprocess.run(args, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
    if check and result.returncode:
        raise RuntimeError(f"COMMAND_FAILED:{args[0]}:{result.returncode}:" + result.stderr[-1800:])
    return result


def show(prop):
    return command("systemctl", "show", NAME, "--property=" + prop, "--value").stdout.strip()


def until(predicate, seconds=8):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        result = predicate()
        if result:
            return result
        time.sleep(.05)
    raise RuntimeError("REHEARSAL_WAIT_TIMEOUT")


def read_json(path):
    try:
        raw = path.read_bytes()
        return json.loads(raw) if len(raw) <= 65536 else None
    except (OSError, ValueError):
        return None


def proc_identity(pid):
    try:
        fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
        return fields[19], fields[0]
    except FileNotFoundError:
        return None


def identities_gone(identities):
    for item in identities:
        current = proc_identity(item["pid"])
        if current is not None and current[0] == item["start"]:
            return False
    return True


def cgroup():
    rel = show("ControlGroup")
    if not rel.startswith("/system.slice/") or ".." in rel:
        raise RuntimeError("UNEXPECTED_CGROUP")
    return Path("/sys/fs/cgroup") / rel.lstrip("/")


def limits(group):
    result = {key: (group / key).read_text().strip() for key in
              ("memory.max", "memory.high", "memory.swap.max", "pids.max", "cpu.max")}
    if (result["memory.max"] != str(512 * 1024**2) or
            result["memory.high"] != str(384 * 1024**2) or
            result["memory.swap.max"] != "0" or result["pids.max"] != "16"):
        raise RuntimeError("CGROUP_LIMIT_MISMATCH")
    cpu = result["cpu.max"].split()
    if len(cpu) != 2 or cpu[0] != cpu[1]:
        raise RuntimeError("CPU_QUOTA_MISMATCH")
    return result


def stop():
    command("systemctl", "stop", NAME, check=False, timeout=15)
    if show("MainPID") != "0" or show("ActiveState") not in {"inactive", "failed"}:
        raise RuntimeError("SERVICE_NOT_STOPPED")
    command("systemctl", "reset-failed", NAME, check=False)


def override(exec_start=None, extra=()):
    stop()
    DROP.mkdir(exist_ok=True)
    body = "[Service]\n"
    if exec_start is not None:
        body += "ExecStart=\nExecStart=" + exec_start + "\n"
    body += "\n".join(extra) + "\n"
    (DROP / "rehearsal.conf").write_text(body)
    command("systemctl", "daemon-reload")


def launch():
    command("systemctl", "start", NAME, timeout=15)
    if show("ActiveState") != "active":
        raise RuntimeError("SERVICE_NOT_ACTIVE")


def stage(bundle, label, expected_manifest):
    if verify_bundle(bundle) != expected_manifest:
        raise RuntimeError("SOURCE_BUNDLE_CHANGED")
    dest = BASE / "releases" / label
    shutil.copytree(bundle, dest, symlinks=False)
    # Verify the bytes actually about to be installed against the captured
    # inventory, before installation adds the venv to the exact bundle tree.
    if verify_bundle(dest) != expected_manifest:
        raise RuntimeError("COPIED_BUNDLE_CHANGED")
    command(sys.executable, "-m", "venv", str(dest / "venv"))
    python = str(dest / "venv/bin/python")
    pip = (python, "-m", "pip", "--isolated", "--disable-pip-version-check", "--no-cache-dir")
    command(*pip, "install", "--no-index", "--only-binary=:all:", "--find-links", str(dest / "wheelhouse"),
            "-r", str(dest / "requirements-ci.txt"), timeout=90)
    wheel = dest / "wheelhouse/rgd_cognition-0.1.0a1-py3-none-any.whl"
    command(*pip, "install", "--no-index", "--no-deps", str(wheel), timeout=45)
    command(*pip, "check")
    return dest


def switch(dest):
    stop()
    next_path = BASE / "next"
    next_path.symlink_to(dest)
    next_path.replace(BASE / "current")


def final_service_status(invocation):
    if not re.fullmatch(r"[0-9a-f]{32}", invocation):
        raise RuntimeError("INVALID_SERVICE_INVOCATION")
    result = command("journalctl", "-u", NAME, "_SYSTEMD_INVOCATION_ID=" + invocation,
                     "--no-pager", "-o", "cat", "-n", "20")
    for line in reversed(result.stdout.splitlines()):
        if len(line) > 16384:
            continue
        try:
            data = json.loads(line)
        except ValueError:
            continue
        if type(data) is dict and data.get("profile") == "cog.service.lab.v0.1-candidate":
            return data
    return None


def smoke(report, label):
    # Exact production candidate ExecStart; no weakened security directives.
    override()
    launch()
    invocation, main_pid = show("InvocationID"), int(show("MainPID"))
    group = cgroup()
    snapshot = until(lambda: (lambda data: data if data and
        data.get("health", {}).get("counters", {}).get("worker_completed", 0) >= 1 else None)(
            read_json(RUN / "status.json")), seconds=10)
    report[label] = {"snapshot": snapshot, "cgroup": limits(group),
                     "runtime_max": show("RuntimeMaxUSec"),
                     "timeout_stop": show("TimeoutStopUSec"), "restart": show("Restart")}
    if report[label]["restart"] != "no":
        raise RuntimeError("UNEXPECTED_AUTOMATIC_RESTART")
    if snapshot.get("pid") != main_pid:
        raise RuntimeError("STALE_SERVICE_SNAPSHOT")
    stop()
    final = until(lambda: final_service_status(invocation), seconds=4)
    health = final.get("health", {})
    usage = health.get("work_usage", {})
    if (final.get("pid") != main_pid or final.get("stop_reason") != "SIGNAL_STOP" or
            health.get("state") != "STOPPED" or health.get("worker_active") is not False or
            health.get("worker_reap_pending") is not False or
            any(usage.get(key) != 0 for key in ("reserved_slots", "reserved_steps", "reserved_wall_ms"))):
        raise RuntimeError("SERVICE_FINAL_STATE_NOT_CLEAN")
    report[label]["final_status"] = final
    if group.exists() and "populated 1" in (group / "cgroup.events").read_text():
        raise RuntimeError("SMOKE_CGROUP_NOT_EMPTY")


def run(args):
    os_release = Path("/etc/os-release").read_text()
    if (not args.disposable_ci or os.geteuid() != 0 or os.environ.get("GITHUB_ACTIONS") != "true" or
            os.environ.get("RUNNER_OS") != "Linux" or 'VERSION_ID="22.04"' not in os_release or
            Path("/proc/1/comm").read_text().strip() != "systemd" or
            not Path("/sys/fs/cgroup/cgroup.controllers").is_file()):
        raise RuntimeError("REQUIRES_EXPLICIT_DISPOSABLE_UBUNTU_2204_SYSTEMD_CGROUP2_VM")
    for path in (BASE, UNIT, DROP, RUN, DEVICE, SOCKET):
        if path.exists() or path.is_symlink():
            raise RuntimeError("REFUSE_EXISTING_REHEARSAL_PATH:" + str(path))
    # A unit from /etc or /usr/lib, or a pre-existing static identity, must not
    # be stopped/reused merely because our /run unit file does not yet exist.
    existing = command("systemctl", "show", NAME, "--property=LoadState", "--value", check=False)
    if existing.stdout.strip() != "not-found":
        raise RuntimeError("REFUSE_EXISTING_UNIT")
    for lookup in (pwd.getpwnam, grp.getgrnam):
        try:
            lookup("rgd-cog-lab")
        except KeyError:
            pass
        else:
            raise RuntimeError("REFUSE_EXISTING_STATIC_SERVICE_IDENTITY")
    if args.report.exists() or args.report.is_symlink():
        raise RuntimeError("REFUSE_EXISTING_REPORT")
    if not args.report.parent.is_dir() or BASE in args.report.resolve().parents:
        raise RuntimeError("INVALID_REPORT_DESTINATION")
    manifest = verify_bundle(args.bundle)
    report = {"profile": "cog-runtime01c-systemd-rehearsal-v1", "source_commit": manifest["source_commit"],
              "source_tree": manifest["source_tree"], "hardware_pilot": False,
              "systemd": command("systemctl", "--version").stdout.splitlines()[0],
              "kernel": command("uname", "-r").stdout.strip(), "passed": False}
    server = None
    BASE.mkdir()
    try:
        a = stage(args.bundle, "candidate-a", manifest)
        b = stage(args.bundle, "candidate-b", manifest)
        # verify resolves ExecStart; the initial reviewed target must already
        # exist. Preflight has established that no service/path is being reused.
        (BASE / "current").symlink_to(a)
        shutil.copy2(args.bundle / "rgd-cog-lab.service", UNIT)
        command("systemd-analyze", "verify", str(UNIT))
        command("systemctl", "daemon-reload")
        # Same exact wheel, two independent installations: path rollback, not version compatibility.
        switch(a)
        smoke(report, "initial_service")
        switch(b)
        smoke(report, "second_install")
        switch(a)
        smoke(report, "rollback_service")
        report["rollback_scope"] = "A_TO_B_TO_A_SAME_EXACT_CANDIDATE_TWO_OFFLINE_INSTALLS"
        # Supply harmless outside fixtures and demonstrate access before checking the service.
        (a / "write-probe").write_bytes(b"outside-control\n")
        (a / "write-probe").chmod(0o666)
        with (a / "write-probe").open("ab") as handle:
            handle.write(b"writable\n")
        os.mknod(DEVICE, stat.S_IFCHR | 0o666, os.makedev(1, 3))
        DEVICE.chmod(0o666)
        with DEVICE.open("rb"):
            pass
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(str(SOCKET)); SOCKET.chmod(0o666); server.listen(2)
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.connect(str(SOCKET))
        control, _ = server.accept(); control.close()
        report["outside_controls"] = {"character_device_open": True, "artifact_append": True,
                                      "unix_fixture_connect": True}
        shutil.copy2(Path(__file__).with_name("probe.py"), BASE / "probe.py")
        fixed = "/opt/rgd-cog/current/venv/bin/python -I -B /opt/rgd-cog/probe.py --mode "
        override(fixed + "negative")
        launch()
        negative = until(lambda: read_json(RUN / "negative.json"))
        if negative.get("passed") is not True:
            raise RuntimeError("NEGATIVE_OS_PROBE_FAILED:" + json.dumps(negative))
        report["negative_probes"] = negative
        stop()
        override(fixed + "parent")
        launch()
        identities = [until(lambda n=n: read_json(RUN / (n + ".json"))) for n in ("parent", "child", "grandchild")]
        group = cgroup()
        for item in identities:
            actual = proc_identity(item["pid"])
            if not actual or actual[0] != item["start"] or actual[1] == "Z":
                raise RuntimeError("DESCENDANT_NOT_ALIVE_BEFORE_STOP")
            if str(item["pid"]) not in (group / "cgroup.procs").read_text().split():
                raise RuntimeError("DESCENDANT_OUTSIDE_CGROUP")
        began = time.monotonic(); stop(); elapsed = time.monotonic() - began
        until(lambda: identities_gone(identities), seconds=3)
        if elapsed > 12 or (group.exists() and "populated 1" in (group / "cgroup.events").read_text()):
            raise RuntimeError("DESCENDANT_CLEANUP_FAILED")
        report["process_tree_cleanup"] = {"real_processes": len(identities), "term_ignored": True,
                                           "stop_seconds": elapsed, "all_removed": True}
        # External lifetime bound also applies when the Python supervisor cannot make progress.
        override(fixed + "parent", ("RuntimeMaxSec=2s", "TimeoutStopSec=1s"))
        launch()
        timed_group = cgroup()
        until(lambda: show("ActiveState") == "failed", seconds=8)
        report["external_runtime_limit"] = {"result": show("Result"), "restart": show("NRestarts"),
                                             "test_runtime_seconds": 2, "test_stop_seconds": 1}
        if show("Result") != "timeout" or show("MainPID") != "0" or show("NRestarts") != "0":
            raise RuntimeError("EXTERNAL_RUNTIME_LIMIT_FAILED")
        if timed_group.exists() and "populated 1" in (timed_group / "cgroup.events").read_text():
            raise RuntimeError("EXTERNAL_RUNTIME_LIMIT_LEFT_DESCENDANTS")
        stop()
        report["checks_passed"] = True
    except Exception as error:
        report["failure"] = type(error).__name__ + ":" + str(error)[:2000]
        raise
    finally:
        cleanup_errors = []
        def cleanup_step(name, action):
            try:
                action()
            except Exception as error:
                cleanup_errors.append(name + ":" + type(error).__name__ + ":" + str(error)[:1000])
        def stop_for_cleanup():
            command("systemctl", "stop", NAME, check=False, timeout=15)
            if show("LoadState") != "not-found" and (
                    show("MainPID") != "0" or show("ActiveState") not in {"inactive", "failed"}):
                raise RuntimeError("FINAL_SERVICE_NOT_STOPPED")
        cleanup_step("stop", stop_for_cleanup)
        def collect_journal():
            result = command("journalctl", "-u", NAME, "--no-pager", "-o", "cat", "-n", "80", check=False)
            report["journal"] = result.stdout[-50000:]
            report["journal_returncode"] = result.returncode
        cleanup_step("journal", collect_journal)
        if server is not None:
            cleanup_step("socket_close", server.close)
        for path in (UNIT, DEVICE, SOCKET):
            cleanup_step("unlink:" + str(path), lambda p=path: p.unlink(missing_ok=True))
        for path in (DROP, RUN, BASE):
            if path.is_symlink():
                cleanup_step("unlink:" + str(path), path.unlink)
            elif path.exists():
                cleanup_step("rmtree:" + str(path), lambda p=path: shutil.rmtree(p))
        cleanup_step("daemon_reload", lambda: command("systemctl", "daemon-reload"))
        cleanup_step("reset_failed", lambda: command("systemctl", "reset-failed", NAME, check=False))
        def verify_unloaded():
            state = command("systemctl", "show", NAME, "--property=LoadState", "--value", check=False)
            report["unit_unloaded"] = state.stdout.strip() == "not-found"
            if not report["unit_unloaded"]:
                raise RuntimeError("REHEARSAL_UNIT_STILL_LOADED")
        cleanup_step("unit_unload", verify_unloaded)
        report["fixture_cleanup"] = (not cleanup_errors and all(
            not p.exists() and not p.is_symlink() for p in (BASE, UNIT, DROP, RUN, DEVICE, SOCKET)))
        report["cleanup_errors"] = cleanup_errors
        report["passed"] = report.get("checks_passed", False) and report["fixture_cleanup"]
        args.report.write_text(json.dumps(report, sort_keys=True, indent=2) + "\n")
        if not report["fixture_cleanup"]:
            raise RuntimeError("REHEARSAL_CLEANUP_FAILED")
    print(json.dumps({"status": "SYSTEMD_REHEARSAL_PASS", "source_commit": manifest["source_commit"],
                      "device_network_ipc_denials": True, "process_tree_cleanup": True,
                      "n150_measured": False}, sort_keys=True))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--disposable-ci", action="store_true")
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    run(parser.parse_args())
