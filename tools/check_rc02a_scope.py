"""CI-only strict RC02A patch scope; reviewed RI02 baseline, no schema repin."""
import subprocess

BASE = "9235d3759b263bfde2d8644c46845e9a338e9238"
MODIFIED = {
    "src/rgd_cognition/agenda_c0.py",
    "src/rgd_cognition/attention_c1_bridge.py",
    "src/rgd_cognition/core_b_adapter.py",
    "src/rgd_cognition/core_b_c1.py",
    "tests/test_agenda_c0.py",
    "tests_core_b/test_core_b_c1.py",
    "tests_core_b/test_review_closure.py",
    "tools/check_core_b_scope.py",
    "tools/check_core_d_scope.py",
    "tools/check_ri_scope.py",
    "tools/check_ri02_scope.py",
}
ADDED = {"docs/COG-RC-02A.md", "tools/check_rc02a_scope.py"}


def check():
    subprocess.run(["git", "fetch", "--no-tags", "--depth=1", "origin", BASE],
                   check=True, stdout=subprocess.DEVNULL)
    rows = [line.split("\t", 1) for line in subprocess.check_output(
        ["git", "diff", "--no-renames", "--name-status", BASE, "HEAD"],
        text=True).splitlines()]
    expected = {("M", path) for path in MODIFIED} | {("A", path) for path in ADDED}
    actual = {tuple(row) for row in rows}
    if actual != expected:
        raise SystemExit("RC02A_SCOPE_MISMATCH: unexpected=" + str(sorted(actual - expected)) +
                         "; missing=" + str(sorted(expected - actual)))
    subprocess.run(["git", "diff", "--check", BASE, "HEAD"], check=True)
    print("RC02A exact 4 runtime + 3 test + 4 CI guard modifications; 2 additions; schemas and RI runtime unchanged.")


if __name__ == "__main__":
    check()
