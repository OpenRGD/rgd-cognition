"""Unit tests use an explicitly synthetic producer; real Core tests are separate."""
from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from rgd_cognition.contracts import ContractError, local_digest
from rgd_cognition.demo import synthetic_event
from rgd_cognition.reasoning import BaselineReasoner
from rgd_cognition.rgd_context import (
    CORE_COMMIT, RGDContextResolver, ProfileContextError, _capture, validate_context,
)
from rgd_cognition.rgd_host import RGDGroundedHost

ROOT = "sha256:" + "1" * 64


class Clock:
    def __init__(self): self.value = 0
    def __call__(self): return self.value
    def advance(self, ms): self.value += ms * 1000000


def projection():
    return {
        "bundle_id": "fixture_only", "kernel_reference_id": "did:rgd:fixture-model",
        "modules": [], "declared_capabilities": [], "policy_declaration_refs": [],
        "described_joints_count": 0, "source_files_count": 2,
        "toolchain_commit": CORE_COMMIT, "verification_scope": "SOURCE_INTEGRITY_ONLY",
        "issuer_status": "NOT_VERIFIED", "registry_status": "NOT_CHECKED",
        "physical_execution_authorized": False,
    }


class RGDContextTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.resolver = RGDContextResolver("/synthetic-fixture-not-read", local_alias="lab-robot",
                                            expected_source_root=ROOT, clock=self.clock, ttl_ms=10)

    def loaded(self):
        with patch("rgd_cognition.rgd_context._load_projection", return_value=projection()):
            return self.resolver.refresh()

    def test_unloaded_is_unavailable_and_unbound(self):
        view = self.resolver.read()
        self.assertEqual(view["reference_status"], "UNAVAILABLE")
        self.assertEqual(view["identity_status"], "UNBOUND")
        self.assertIsNone(view["profile"])

    def test_verified_source_never_creates_identity_or_approval(self):
        view = self.loaded()
        self.assertEqual(view["reference_status"], "SOURCE_INTEGRITY_VERIFIED")
        for key in ("robot_id", "life_id", "agent_id", "persona_id", "composition_digest"):
            self.assertIsNone(view[key])
        self.assertFalse(view["may_actuate"])
        self.assertEqual(view["profile"]["registry_status"], "NOT_CHECKED")

    def test_copied_view_cannot_mutate_resolver(self):
        view = self.loaded()
        view["profile"]["kernel_reference_id"] = "fake"
        self.assertNotEqual(view, self.resolver.read())

    def test_revision_stable_for_same_source_not_elapsed_time(self):
        first = self.loaded()
        self.clock.advance(2)
        self.assertEqual(first, self.loaded())

    def test_ttl_drops_facts_and_changes_revision(self):
        before = self.loaded()
        self.clock.advance(10)
        after = self.resolver.read()
        self.assertEqual(after["reference_status"], "STALE")
        self.assertIsNone(after["profile"])
        self.assertIsNone(after["source_root"])
        self.assertNotEqual(before["context_revision"], after["context_revision"])

    def test_failed_refresh_discards_last_good_snapshot(self):
        self.loaded()
        with patch("rgd_cognition.rgd_context._load_projection", side_effect=ValueError("PRIVATE_PATH_SECRET")):
            view = self.resolver.refresh()
        self.assertEqual(view["reference_status"], "INVALID")
        self.assertIsNone(view["profile"])
        self.assertNotIn("PRIVATE", json.dumps(view))

    def test_missing_verifier_is_unavailable(self):
        with patch("rgd_cognition.rgd_context._core_api", side_effect=ProfileContextError("RGD_VERIFIER_UNAVAILABLE")):
            view = self.resolver.refresh()
        self.assertEqual(view["reference_status"], "UNAVAILABLE")

    def test_conflicting_pin_is_not_a_valid_snapshot(self):
        with patch("rgd_cognition.rgd_context._load_projection", side_effect=ProfileContextError("RGD_ROOT_CONFLICT")):
            view = self.resolver.refresh()
        self.assertEqual(view["reference_status"], "CONFLICT")
        self.assertIsNone(view["source_root"])

    def test_negative_binding_states_preserved_never_promoted(self):
        for state in ("UNBOUND", "UNKNOWN", "STALE", "CONFLICT"):
            resolver = RGDContextResolver("/fixture", local_alias="lab-robot", expected_source_root=ROOT, binding_status=state)
            with patch("rgd_cognition.rgd_context._load_projection", return_value=projection()):
                view = resolver.refresh()
            self.assertEqual(view["identity_status"], state)
            self.assertIsNone(view["life_id"])

    def test_positive_binding_and_bad_config_rejected(self):
        for extra in ({"binding_status":"VERIFIED"}, {"ttl_ms":True}, {"ttl_ms":0}, {"expected_source_root":"bad"}, {"local_alias":"../../private"}):
            kwargs = {"local_alias":"lab-robot", "expected_source_root":ROOT, **extra}
            with self.assertRaises(ValueError): RGDContextResolver("/fixture", **kwargs)

    def test_invalidated_snapshot_stays_empty(self):
        self.loaded(); self.resolver.invalidate()
        self.assertIsNone(self.resolver.read()["profile"])

    def test_clock_regression_invalidates(self):
        self.clock.advance(2); self.loaded(); self.clock.value = 0
        with self.assertRaises(ProfileContextError): self.resolver.read()
        self.clock.advance(3)
        self.assertIsNone(self.resolver.read()["profile"])

    def test_schema_rejects_spoofed_authority(self):
        for key, value in (("robot_id","fake"), ("may_actuate",True), ("chronon_watermark","fake"), ("identity_status","VERIFIED")):
            view = self.loaded(); view[key] = value
            with self.assertRaises(ContractError): validate_context(view)

    def test_schema_rejects_invalid_source_profile_pair(self):
        view = self.loaded(); view["reference_status"] = "STALE"
        with self.assertRaises(ContractError): validate_context(view)

    def test_context_revision_tamper_rejected(self):
        view = self.loaded(); view["local_alias"] = "another"
        with self.assertRaises(ContractError): validate_context(view)

    def test_schema_failure_does_not_keep_partial_snapshot(self):
        bad = projection(); bad["physical_execution_authorized"] = True
        with patch("rgd_cognition.rgd_context._load_projection", return_value=bad): view = self.resolver.refresh()
        self.assertEqual(view["reference_status"], "INVALID")
        self.assertIsNone(view["profile"])

    def test_capture_rejects_symlinks(self):
        with TemporaryDirectory() as tmp:
            spec = Path(tmp)/"spec"; spec.mkdir()
            (spec/"escape.jsonc").symlink_to(Path(tmp)/"outside")
            with self.assertRaises(ProfileContextError): _capture(spec)

    def test_capture_rejects_oversized_source(self):
        with TemporaryDirectory() as tmp:
            spec = Path(tmp)/"spec"; spec.mkdir()
            (spec/"huge.jsonc").write_bytes(b" " * (1024*1024+1))
            with self.assertRaises(ProfileContextError): _capture(spec)

    def test_capture_ignores_unrelated_private_file_content(self):
        with TemporaryDirectory() as tmp:
            spec = Path(tmp)/"spec"; spec.mkdir()
            (spec/"manifest.jsonc").write_text("{}")
            (spec/"private.env").write_text("SECRET")
            self.assertEqual(_capture(spec), {"manifest.jsonc":b"{}"})

    def test_host_receives_real_context_revision(self):
        view = self.loaded()
        host = RGDGroundedHost(self.resolver, clock=self.clock)
        event = synthetic_event(1)
        host.submit(event); result = host.next_result()
        self.assertEqual(result["trace"]["context_revision"], view["context_revision"])
        self.assertFalse(result["proposal"]["may_actuate"])
        self.assertEqual(host.health()["reference_status"], "SOURCE_INTEGRITY_VERIFIED")

    def test_host_reasoner_gets_profile_without_becoming_identity(self):
        self.loaded()
        captured = []
        class Recorder(BaselineReasoner):
            def assess(inner, event, context, memory, ref):
                captured.append(context)
                return super().assess(event, context, memory, ref)
        host = RGDGroundedHost(self.resolver, clock=self.clock, reasoner=Recorder())
        host.submit(synthetic_event()); host.next_result()
        self.assertEqual(captured[0]["profile"]["bundle_id"], "fixture_only")
        self.assertIsNone(captured[0]["robot_id"])

    def test_context_expiry_during_reasoning_discards_result(self):
        self.loaded()
        outer = self
        class Slow(BaselineReasoner):
            def assess(inner, *args):
                outer.clock.advance(10)
                return super().assess(*args)
        host = RGDGroundedHost(self.resolver, clock=self.clock, reasoner=Slow())
        host.submit(synthetic_event())
        self.assertIsNone(host.next_result())
        self.assertIsNone(host.context["profile"])
        self.assertEqual(host.health()["counters"]["context_changed_during_turn"], 1)

    def test_host_close_purges_profile(self):
        self.loaded(); host = RGDGroundedHost(self.resolver, clock=self.clock); host.close()
        self.assertNotIn("profile", host.context)
        self.assertIsNone(self.resolver.read()["profile"])

    def test_no_parallel_reference_or_alias_allowed(self):
        for kwargs in ({"reference":{}}, {"local_alias":"other"}):
            with self.assertRaises(ValueError): RGDGroundedHost(self.resolver, **kwargs)


if __name__ == "__main__": unittest.main()
