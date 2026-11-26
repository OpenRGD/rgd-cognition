"""Optional COG-02 host adapter. COG-01 wire contracts are unchanged."""
from __future__ import annotations
from copy import deepcopy

from .context import context_slice
from .host import CognitiveHost
from .rgd_context import RGDContextResolver, validate_context


class RGDGroundedHost(CognitiveHost):
    """One resolver per single-threaded host; refresh only between turns.

    The parent host is still a synchronous lab runtime with trusted in-process
    providers. This adapter is not enrollment, a daemon or a hardware sandbox.
    """
    def __init__(self, resolver: RGDContextResolver, **settings):
        if not isinstance(resolver, RGDContextResolver):
            raise TypeError("RGD_RESOLVER_REQUIRED")
        if "local_alias" in settings or "reference" in settings:
            raise ValueError("AMBIGUOUS_CONTEXT_SOURCE")
        self._resolver = resolver
        self._turn_context = None
        view = validate_context(resolver.read())
        super().__init__(local_alias=view["local_alias"], **settings)
        self._context = view

    @property
    def context(self) -> dict:
        if self._turn_context is not None:
            return deepcopy(self._turn_context)
        if self._closed:
            return deepcopy(self._context)
        return validate_context(self._resolver.read())

    def health(self) -> dict:
        report = super().health()
        view = self.context
        report.update(identity_status=view["identity_status"],
                      reference_status=view["reference_status"],
                      context_revision=view["context_revision"])
        return report

    def _process(self, item, started):
        view = self.context
        self._context = view
        self._turn_context = view
        try:
            result = super()._process(item, started)
        finally:
            self._turn_context = None
        current = self.context
        self._context = current
        if current["context_revision"] != view["context_revision"]:
            # Discard a response computed from a revoked/refreshed/expired view.
            if result is not None:
                self._stats["processed"] -= 1
            self._stats["context_changed_during_turn"] += 1
            return None
        return result

    def close(self) -> None:
        alias = self._context["local_alias"]
        super().close()
        self._resolver.invalidate("RGD_HOST_CLOSED")
        self._context = context_slice(alias)
