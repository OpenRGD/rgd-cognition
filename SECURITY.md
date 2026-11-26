# Security boundary — COG-0.1 Foundation

Status: candidate threat model, **not a safety certification**.

## Assets and threats

Protect identity/authorization boundaries, original evidence provenance, private
input, finite CPU/memory, and the independent motion/safety path. Treat transcripts,
source descriptions, model responses and supplied reference metadata as untrusted
DATA. A local alias, reference hash, relationship claim or familiar voice is not
an authenticated security principal. No source ref is dereferenced by this code.

Implemented defenses: closed schemas, bounded serialization, no arbitrary output
text from providers, reference-membership checks (not evidence verification),
privacy DENY before queuing, per-host alias isolation, bounded queues/deduplication,
explicit UNBOUND and NOT_CONNECTED states, no raw-input trace, limited deterministic
renderer, no runtime network/process/device integrations. Code regression tests
inspect imports and run replay with socket/Popen disabled; they cover exercised
paths only, not all dependency or operating-system behavior.

## Not established by this PR

- No OS sandbox, identity authentication, signed grants, kernel-level syscall or
  network prohibition is installed. A Python process has its launcher's privileges.
- A supplied `origin=PHYSICAL` is a declared label, not verified physical evidence.
  `source_time` is preserved; clock synchronization/acquisition freshness is unknown.
- No canonical RGD hash check, registry receipt, Life binding or Chronon writer is
  verified. `context_revision` and proposal/trace hashes use a LOCAL serialization
  recipe; they are not JCS, OpenRGD source roots or signatures.
- In-process provider code is trusted code. Exception handling and post-return
  budgets cannot sandbox malicious or non-returning Python code. Do not load plugins.
- Queue TTL needs a running pump; hashes/IDs and temporary objects are sensitive too.
  Returning a trace is not permission to store/export it. No personal live data in CI.

## Required before any Paky-01 deployment

Separate operator-reviewed plan: dedicated unprivileged user, no dialout/docker or
sudo groups, no device/CAN/body-adapter/GPIO/smart-plug access, restricted local IPC
and egress, service resource limits, source authentication, privacy/retention review,
negative device/socket/API tests, exact-SHA package checks, backup and rollback.
A device mount flag or boolean is never a replacement for those checks. Protect
normal Python runtime necessities; validate the actual deployment permissions.

No Voice playback/camera/microphone/cloud side effects are implemented. Their
future grants are distinct from motor grants. Any future motion integration needs
a separate Somatic RFC, independent authorization and physical safety validation.

Report suspected issues privately to the repository maintainers using GitHub's
available private reporting/contact facilities; do not publish private robot logs,
secrets, biometric data or exploitable credentials in public issues.
