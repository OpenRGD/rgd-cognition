"""Adversarial byte-inventory tests; systemd/wheel execution is separate CI."""
from copy import deepcopy
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools/runtime01c"))
from artifact import ArtifactError, SCHEMA_PATH, assemble, verify_bundle
import artifact


class ArtifactTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.wheels = self.root / "wheels"
        self.wheels.mkdir()
        (self.wheels / "rgd_cognition-0.1.0a1-py3-none-any.whl").write_bytes(b"inventory-test-fixture-not-an-installable-wheel")
        # Exact reviewed schema is supplied by the owning repository checkout.
        self.core = Path(os.environ.get("CORE_B_CHECKOUT", "/nonexistent"))
        self.bundle = self.root / "bundle"

    def create(self):
        return assemble(source=ROOT, wheels=self.wheels, core_b=self.core,
                        output=self.bundle, source_commit="a"*40, source_tree="b"*40)

    def manifest(self, change):
        path = self.bundle / "manifest.json"
        data = json.loads(path.read_text()); change(data)
        path.write_text(json.dumps(data))

    def test_round_trip_exact_inventory(self):
        expected = self.create()
        self.assertEqual(verify_bundle(self.bundle), expected)
        self.assertTrue(expected["fixture_only"])

    def test_changed_content_rejected(self):
        self.create()
        (self.bundle / "rgd-cog-lab.service").write_text("weakened")
        with self.assertRaisesRegex(ArtifactError, "CONTENT_MISMATCH"):
            verify_bundle(self.bundle)

    def test_missing_and_extra_members_rejected(self):
        self.create()
        (self.bundle / "unexpected.py").write_text("pass")
        with self.assertRaisesRegex(ArtifactError, "INVENTORY_MISMATCH"):
            verify_bundle(self.bundle)
        (self.bundle / "unexpected.py").unlink()
        (self.bundle / "requirements-ci.txt").unlink()
        with self.assertRaisesRegex(ArtifactError, "INVENTORY_MISMATCH"):
            verify_bundle(self.bundle)

    def test_symlink_input_and_member_rejected(self):
        path = self.wheels / "bad.whl"
        path.symlink_to(ROOT / "README.md")
        with self.assertRaisesRegex(ArtifactError, "NONREGULAR"):
            self.create()
        path.unlink(); self.create()
        (self.bundle / "link").symlink_to(ROOT / "README.md")
        with self.assertRaisesRegex(ArtifactError, "NONREGULAR"):
            verify_bundle(self.bundle)

    def test_existing_output_never_overwritten(self):
        self.bundle.mkdir(); (self.bundle / "keep").write_text("original")
        with self.assertRaises(FileExistsError):
            self.create()
        self.assertEqual((self.bundle / "keep").read_text(), "original")

    def test_manifest_duplicate_and_unknown_fields_rejected(self):
        self.create()
        self.manifest(lambda value: value.update(permission="ALLOW"))
        with self.assertRaisesRegex(ArtifactError, "INVALID_MANIFEST"):
            verify_bundle(self.bundle)
        (self.bundle / "manifest.json").write_text('{"profile":1,"profile":2}')
        with self.assertRaisesRegex(ArtifactError, "DUPLICATE_KEY"):
            verify_bundle(self.bundle)

    def test_traversal_rejected_even_if_rehashed(self):
        self.create()
        self.manifest(lambda value: value["files"].update({"../outside.whl": {"sha256":"0"*64,"size":0}}))
        with self.assertRaises(ArtifactError):
            verify_bundle(self.bundle)

    def test_schema_repin_rejected_even_if_inventory_rehashed(self):
        import hashlib
        self.create()
        raw = b'{"fake":"schema"}'
        (self.bundle / SCHEMA_PATH).write_bytes(raw)
        self.manifest(lambda value: value["files"].update({SCHEMA_PATH: {
            "sha256": hashlib.sha256(raw).hexdigest(), "size": len(raw)}}))
        with self.assertRaisesRegex(ArtifactError, "CORE_B_SCHEMA_PIN_MISMATCH"):
            verify_bundle(self.bundle)

    def test_manifest_size_bool_and_claimed_identity_rejected(self):
        original = self.create()
        for transform in (
            lambda value: value["files"]["requirements-ci.txt"].update(size=True),
            lambda value: value.update(fixture_only=False),
            lambda value: value.update(source_commit="main"),
        ):
            data = deepcopy(original); transform(data)
            (self.bundle / "manifest.json").write_text(json.dumps(data))
            with self.assertRaises(ArtifactError):
                verify_bundle(self.bundle)

    def test_file_growth_is_read_with_a_hard_bound_and_fifo_is_refused(self):
        path = self.root / "growing-file"
        path.write_bytes(b"x")
        original_read = os.read
        observed = []
        def grow_then_read(fd, requested):
            if not observed:
                path.write_bytes(b"x" * 100)
            data = original_read(fd, requested)
            observed.append((requested, len(data)))
            return data
        with patch.object(artifact.os, "read", side_effect=grow_then_read):
            with self.assertRaisesRegex(ArtifactError, "FILE_CHANGED_OR_OVERSIZED"):
                artifact._file(path, limit=8)
        self.assertEqual(observed, [(9, 9)])
        fifo = self.root / "fifo"
        os.mkfifo(fifo, 0o600)
        with self.assertRaisesRegex(ArtifactError, "NONREGULAR_OR_OVERSIZED_FILE"):
            artifact._file(fifo, limit=8)

    def test_unlisted_directory_is_rejected_before_descending_into_it(self):
        self.create()
        outside = self.bundle / "unlisted-empty-directory"
        outside.mkdir()
        original_scan = os.scandir
        visited = []
        def observed_scan(path):
            visited.append(Path(path))
            if Path(path) == outside:
                raise AssertionError("must not scan an unlisted directory")
            return original_scan(path)
        with patch.object(artifact.os, "scandir", side_effect=observed_scan):
            with self.assertRaisesRegex(ArtifactError, "INVENTORY_MISMATCH"):
                verify_bundle(self.bundle)
        self.assertNotIn(outside, visited)


if __name__ == "__main__":
    unittest.main()
