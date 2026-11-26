"""Pure verifier tests; CI separately checks the actual pinned Git trees."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from check_release_scope import BASE, expected_delta, verify_delta


class ScopeTests(unittest.TestCase):
    def setUp(self):
        self.manifest = json.loads((ROOT / "tools/release-scope.json").read_text())
        self.raw = json.dumps(self.manifest).encode()
        self.rows = sorted(expected_delta(self.raw))
        self.modes = {p: "100644" for _, p in self.rows}

    def test_actual_manifest(self):
        verify_delta(self.raw, self.rows, self.modes)

    def test_extra_runtime_edit_refused(self):
        with self.assertRaisesRegex(ValueError, "RELEASE_SCOPE_MISMATCH"):
            verify_delta(self.raw, self.rows + [("M", "src/rgd_cognition/core_b_adapter.py")], self.modes)

    def test_missing_required_path(self):
        with self.assertRaises(ValueError):
            verify_delta(self.raw, self.rows[:-1], self.modes)

    def test_removal_and_rename_not_allowed(self):
        for status in ("D", "R100", "T"):
            with self.subTest(status=status), self.assertRaises(ValueError):
                verify_delta(self.raw, [(status, self.rows[0][1]), *self.rows[1:]], self.modes)

    def test_nonregular_path_refused(self):
        modes = deepcopy(self.modes)
        modes[self.rows[0][1]] = "120000"
        with self.assertRaisesRegex(ValueError, "NONREGULAR"):
            verify_delta(self.raw, self.rows, modes)

    def test_repin_refused(self):
        for key in ("baseline", "baseline_tree"):
            m = dict(self.manifest, **{key: "0" * 40})
            with self.assertRaisesRegex(ValueError, "PIN_MISMATCH"):
                expected_delta(json.dumps(m).encode())

    def test_unknown_manifest_field_refused(self):
        with self.assertRaises(ValueError):
            expected_delta(json.dumps(dict(self.manifest, broad_allow=True)).encode())

    def test_duplicate_and_traversal_rejected(self):
        for path in (self.manifest["added"][0], "docs/../secret", "docs//new.md", "/docs/file.md"):
            m = dict(self.manifest, added=self.manifest["added"] + [path])
            with self.subTest(path=path), self.assertRaises(ValueError):
                expected_delta(json.dumps(m).encode())

    def test_schema_path_cannot_be_whitelisted(self):
        m = dict(self.manifest, added=self.manifest["added"] + ["src/rgd_cognition/schemas/fake.json"])
        with self.assertRaises(ValueError):
            expected_delta(json.dumps(m).encode())

    def test_base_source_edit_cannot_be_whitelisted(self):
        m = dict(self.manifest, modified=self.manifest["modified"] + ["src/rgd_cognition/core_b_adapter.py"])
        with self.assertRaises(ValueError):
            expected_delta(json.dumps(m).encode())

    def test_duplicate_json_key_rejected(self):
        with self.assertRaises(ValueError):
            expected_delta(b'{"version":1,"version":2}')

    def test_exact_new_file_review(self):
        path = "src/rgd_cognition/example_future.py"
        m = dict(self.manifest, added=self.manifest["added"] + [path])
        raw = json.dumps(m).encode()
        with self.assertRaises(ValueError):
            verify_delta(raw, self.rows, self.modes)
        verify_delta(raw, self.rows + [("A", path)], dict(self.modes, **{path: "100644"}))


if __name__ == "__main__":
    unittest.main()
