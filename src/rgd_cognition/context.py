"""Reference-only projection. No identity/signature/Core-hash verification here."""
from __future__ import annotations
from copy import deepcopy
from .contracts import local_digest, validate


def context_slice(local_alias: str, reference: dict | None = None) -> dict:
    if reference is not None:
        validate("ReferenceInput", reference)
        if reference["local_alias"] != local_alias:
            raise ValueError("REFERENCE_INSTANCE_MISMATCH")
    ref = deepcopy(reference) if reference is not None else {}
    view = {
        "schema_version": "cog_context_slice_v0.1-candidate",
        "local_alias": local_alias,
        "robot_id": None, "life_id": None, "agent_id": None, "persona_id": None,
        "identity_status": "UNBOUND",
        "reference_status": "DECLARED_ONLY" if reference is not None else "NONE",
        "source_ref": ref.get("source_ref"),
        "source_root": ref.get("source_root"),
        "composition_digest": ref.get("composition_digest"),
        "policy_revision": "cog-lab-no-effects-v1",
        "instance_binding_revision": None, "life_binding_epoch": None,
        "chronon_watermark": None,
        "unknowns": ["IDENTITY_UNBOUND", "RGD_VERIFIER_NOT_CONNECTED", "CHRONON_NOT_CONNECTED"],
        "may_actuate": False,
    }
    view["context_revision"] = local_digest(view)
    return validate("ContextSlice", view)


class DisconnectedMemory:
    """Availability only, not a parallel implementation of Memory's RecallBundle."""
    @staticmethod
    def status() -> dict:
        return validate("MemoryAvailability", {
            "schema_version": "cog_memory_availability_v0.1-candidate",
            "status": "NOT_CONNECTED", "recall_bundle": None,
            "chronon_watermark": None, "reason_codes": ["CHRONON_NOT_CONNECTED"],
        })
