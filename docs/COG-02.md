# COG-02 — Canonical RGD context consumer

Candidate, non-normative, non-actuating. Stacked on COG-01 PR #1; no merge,
Core modification, registry enrollment, module install or robot deployment.

## What is real

`RGDContextResolver` calls the genuine `openrgd.core.profile.inspect_profile`,
`ProfileSnapshot.validation_payload` and `build_grounding_context` used by
`rgd check` and `rgd boot`. Supported Core commit:
`afe1a831b950a4e6560f0285a0103fc4eaa343b7` (toolchain distribution `rgd`, version 0.1.1).
It does not implement `OPENRGD_SOURCE_TREE_SHA256_V1` itself or accept a submitted
JSON report claiming to be verified. Three critical Core source blob fingerprints
reject incompatible installed versions. This is code-compatibility checking, not
a full dependency attestation or an OS sandbox; installed Python code is trusted.

The caller supplies an expected source root from its reviewed profile lock.
Self-consistency of a file's own manifest alone is not treated as that pin.
A matching root proves content identity, not issuer identity or physical truth.

## Boundary

- Source is a local extracted profile root or `spec/` directory. No ZIP extraction,
  URL fetching, shell command, driver, network inference or device access.
- Selected source bytes are captured into a bounded private temporary snapshot.
  Core validates that snapshot; the original source is never repaired or modified.
  A second capture rejects observable source changes during inspection. Temporary
  copies are removed on return, not cryptographically erased from disk.
- Limits: 512 directory entries, 1 MiB per source file, 16 MiB captured source,
  depth 12; reject symlinks and nonregular files. Requires a trusted local parent
  directory: this is not protection against a hostile OS or racing ancestor rename.
- Additional duplicate-key/nonfinite/depth guards use the canonical JSONC stripper.
  They deliberately reject ambiguous inputs beyond Core's current checks.
- Output is a bounded projection: module paths/digests, declared skill identifiers,
  policy declaration references and described joint count. No whole raw RGD in the
  prompt, no automatic persona, map, causal priors, free-text policy or instructions.
- Canonical `ProfileSnapshot.robot_id` is exposed as `kernel_reference_id`.
  `robot_id/life_id/agent_id/persona_id` stay null. Binding states are conservative
  negative inputs: UNBOUND, UNKNOWN, STALE, CONFLICT; this increment cannot verify
  enrollment or consume an asserted positive binding.
- Capabilities have distinct declaration/installation/physical verification/
  availability/authorization dimensions. FIELD_TESTED in an example does not
  become actual Paky-01 verification. Authorization remains NOT_GRANTED.
- Composition, registry, issuer, Life and Chronon contracts are not invented here.
  Composition digest and Chronon watermark remain null.

## Compatibility

`cog_context_slice_v0.2-candidate` is a separate local schema. Existing COG-01
v0.1 schemas, generic host, proposal and trace remain unchanged. Exported context
JSON is informational, not a credential or an accepted serialized identity API.
`validate_context` checks shape and local projection revision; only the live
resolver performs canonical inspection. A local context revision is NOT a source
root, composition digest, registry proof or authorization.

`RGDGroundedHost` is an explicit adapter over the existing synchronous host. Its
trusted reasoner receives one immutable context per turn, and proposal/trace refer
to that exact revision. A changed/expired/invalidated context causes the result
to be discarded. COG-01 evidence reference output rules remain unchanged: this
increment supplies the profile to the reasoner, not a new general fact-answering
reasoner or generalized RGD claim-citation API. Existing SOURCE_DECLARED_ONLY
trace/limitation labels concern input-event source claims, not RGD source integrity.

## Freshness and fail-closed behavior

Refresh is explicit, single-threaded, and clears old facts before loading. Failed
refresh never leaves a previous verified profile active. `read()` is memory-only;
it expires the view after a local monotonic TTL (default 60 seconds), clearing
profile facts and source root. It does not poll the filesystem or a registry.
Changes/revocation notifications must call `invalidate()` or `refresh()`; maximum
unnoticed source change is the configured TTL. A clock regression fails closed.
A source revision change requires a NEW resolver with a newly reviewed pin; no
automatic acceptance of a changed manifest. No hot-swap while a turn is running.
Use one resolver per host; this is not a concurrent service or shared authority.

## Explicit operator usage (not run on Paky-01 by this PR)

Install the existing package in a staging virtual environment and explicitly opt
into the pinned Core dependency with `python -m pip install -r requirements-rgd.txt`.
The first install needs network; subsequent inspection does not. No system Python,
BHL environment, running services or existing profile should be overwritten.

```sh
python -m rgd_cognition.rgd_context \
  --profile-root /path/to/reviewed-profile \
  --alias paky-01 \
  --expected-source-root sha256:FULL_REVIEWED_SOURCE_ROOT
```

The example digest is a placeholder, deliberately invalid; obtain the actual root
from the reviewed source lock, not the ZIP hash. Exit 0 means source-integrity-only
success; exit 2 means unavailable/invalid/conflicting input. CLI emits no raw input
paths or exception text. It does not register the alias as a robot identity.

```python
from rgd_cognition.rgd_context import RGDContextResolver
from rgd_cognition.rgd_host import RGDGroundedHost

resolver = RGDContextResolver(profile_root, local_alias="paky-01",
                              expected_source_root=reviewed_source_root)
view = resolver.refresh()
host = RGDGroundedHost(resolver)  # identities can remain UNBOUND
# Submit already-authorized, typed events through the existing COG-01 interface.
```

## Verification and limits

Unit tests use explicitly synthetic projections. The separate required integration
workflow installs the exact Core commit, executes real producer/consumer tests,
compares `check` and `boot` JSON, tests the actual BHL reference tree, negative
fixtures, source immutability, no network/process calls on the exercised path,
and wheel installation outside the checkout. The foundation suite remains separate.
Integration tests fail rather than skip when Core or the pinned checkout is absent.
Dependency versions are pinned, not fully hash-locked; no latest-version claim.
Existing action pins are reused; the earlier Node-runtime deprecation warning
needs a separate action-pin maintenance change.

No locally mounted Paky-01 profile, live robot or enrollment key was available.
Passing CI is software conformance evidence, not hardware/identity/safety validation.
The source-authoring container cannot resolve GitHub/PyPI; local checks are syntax
and schema checks, and the actual executable tests run on GitHub Actions.

## Remaining gates

- Maintainer review of COG-01 and COG-02, branch protections, independent merge.
- Reviewed identity/issuer/binding resolver; do not turn null IDs into guesses.
- Broader typed fact projection and citation-compatible reasoner integration.
- Host isolation, CPU/latency measurement, actual Paky-01 source pin, staging/rollback.
- Memory/Chronon and Voice/model integration in separate reviewed increments.
