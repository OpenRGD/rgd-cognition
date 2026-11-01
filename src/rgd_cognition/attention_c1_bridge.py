"""COG-C1 composition with the existing C0 Work agenda; no transport client."""
from __future__ import annotations

from copy import deepcopy
from time import monotonic_ns
from typing import Callable

from .agenda_c0 import AgendaError, SessionAgenda
from .attention_c1 import AttentionError, AttentionPolicy, ImuAttention, SourceBinding
from .contracts import ContractError, local_digest, validate
from .rgd_context import validate_context


class AttentionAgenda:
    """One existing Work agenda plus an IMU attention adapter, not a second arbiter.

    No external I/O is performed. The host supplies authorized received records.
    Actual resource telemetry and source authentication remain external duties.
    """
    def __init__(self, *, context_supplier: Callable[[], dict], binding: SourceBinding,
                 policy: AttentionPolicy | None = None, clock: Callable[[], int] = monotonic_ns,
                 resource_state: str = "UNKNOWN"):
        self._supplier = context_supplier
        self.attention = ImuAttention(binding, policy=policy, clock=clock)
        self.work = SessionAgenda(context_supplier=context_supplier, clock=clock,
                                  resource_state=resource_state)
        self._resource, self._user_paused, self._closed = resource_state, False, False

    def _view(self) -> dict:
        try:
            view = deepcopy(self._supplier())
            version = view.get("schema_version")
            if version == "cog_context_slice_v0.2-candidate":
                validate_context(view)
                if view["reference_status"] != "SOURCE_INTEGRITY_VERIFIED":
                    raise AttentionError("CONTEXT_NOT_CURRENT")
            elif version == "cog_context_slice_v0.1-candidate":
                validate("ContextSlice", view)
                if local_digest({k: v for k, v in view.items() if k != "context_revision"}) != view["context_revision"]:
                    raise AttentionError("CONTEXT_REVISION_MISMATCH")
                if self.attention.binding.mode != "SYNTHETIC_REPLAY":
                    raise AttentionError("REAL_FEED_REQUIRES_RGD_CONTEXT")
            else:
                raise AttentionError("UNSUPPORTED_CONTEXT")
            if view["local_alias"] != self.attention.binding.local_alias:
                raise AttentionError("CONTEXT_ALIAS_MISMATCH")
            if view["identity_status"] not in {"UNBOUND", "UNKNOWN"}:
                raise AttentionError("CONTEXT_BINDING_CONFLICT")
            return view
        except AttentionError:
            raise
        except Exception:
            raise AttentionError("CONTEXT_UNAVAILABLE") from None

    def ingest(self, payload: dict, *, received_ns: int, freshness: str = "UNKNOWN",
               consent: bool = False) -> dict:
        if self._closed:
            raise AttentionError("ATTENTION_CLOSED")
        try:
            self.work.checkpoint()  # existing C0 expiry/context invalidation, not a persisted checkpoint
            view = self._view()
        except (AttentionError, AgendaError, ContractError):
            self.attention.invalidate()
            return {"attention": {"status": "REJECTED", "reason_code": "CONTEXT_UNAVAILABLE", "cue": None},
                    "proposal": None}
        assessment = self.attention.observe(
            payload, received_ns=received_ns, freshness=freshness, consent=consent,
            context_revision=view["context_revision"],
            allow_goal_generation=self._resource == "NORMAL" and not self._user_paused)
        cue = assessment["cue"]
        if cue is None:
            return {"attention": assessment, "proposal": None}
        try:
            current = self._view()
            remaining_ms = (cue["expires_at_monotonic_ns"] - self.attention.now()) // 1000000
            if current["context_revision"] != cue["context_revision"] or remaining_ms < 1:
                self.attention.invalidate()
                return {"attention": {"status": "REJECTED", "reason_code": "CUE_EXPIRED_OR_CHANGED", "cue": None},
                        "proposal": None}
            event = validate("InputEvent", {
                "schema_version": "cog_input_v0.1-candidate", "event_id": cue["cue_id"],
                "source_id": "cog-c1.attention", "source_session_id": self.attention.session_id,
                "local_alias": self.attention.binding.local_alias, "kind": "OBSERVATION_NOTICE",
                "origin": cue["origin"], "epistemic_status": "DERIVED", "evidence_level": "DECLARED_ONLY",
                "text": "Esaminare i limiti interpretativi delle letture IMU; nessuna diagnosi dello stato del corpo.",
                "source_refs": cue["source_refs"], "source_clock_domain": cue["source_clock_domain"],
                "source_time": cue["source_time"], "ttl_ms": min(remaining_ms, 60000),
                "privacy_scope": "EPHEMERAL_LOCAL", "calibration_status": "UNVERIFIED",
                "chronon_status": "NOT_CONNECTED", "chronograf_anchor_ref": None, "may_actuate": False,
            })
            proposal = self.work.propose(event, cue_kind=cue["cue_kind"], ttl_ms=event["ttl_ms"])
            # C0 checks the current supplier at admission/start. Do not return a
            # stale candidate as usable after a revision race during admission.
            if proposal["candidate"]["context_revision"] != cue["context_revision"]:
                self.close()
                raise AttentionError("CONTEXT_CHANGED_DURING_ADMISSION")
        except (AgendaError, ContractError):
            self.close()
            raise AttentionError("AGENDA_BOUNDARY_REJECTED") from None
        return {"attention": assessment, "proposal": proposal}

    def set_resources(self, state: str):
        self.work.set_resources(state)
        self._resource = state

    def interrupt_user(self, event: dict):
        self.work.interrupt_user(event)
        self._user_paused = True

    def release_user_attention(self):
        if self._closed:
            raise AttentionError("ATTENTION_CLOSED")
        self._user_paused = False  # Work.resume remains explicit and rechecked.

    def close(self):
        self.attention.close()
        self.work.close()
        self._closed = True
