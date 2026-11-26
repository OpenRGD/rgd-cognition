# COG-RC-03C — offline candidate release readiness

**26 November 2026 · CANDIDATE · non-normative · not merged, released or deployed.**
This increment is stacked on [RC03 integration PR #11](https://github.com/OpenRGD/rgd-cognition/pull/11),
head `b601674bf3a539ce029e1c2253c2ae4b49e291e9`, tree
`aec46c865420d0d975fef4ca420e973e8d723ae3`. It is not permission to merge #11,
replace external owner contracts or install on a robot. The original 19 commits
and previous reviewed heads remain intact. Package version stays `0.1.0a1`.

## Scope migration

Keep all historic C1/Core-B/Core-D/RI01/RI02 checks and their exact pins. The
original RC02A expected path set is still checked, now against the exact historic
RC02A head instead of a future HEAD. Its successor check verifies the fixed tree
and **exact reviewed manifest** (`tools/release-scope.json`) against the actual
candidate HEAD, including file status/mode and whitespace. Existing runtime,
contract/schema, dependency and regression files remain unchanged; the manifest
cannot permit modifications to them or a repin. New files require explicit paths,
not a wildcard or skipped scope check. The next additive wave updates just the
manifest and adds its own tests; future changes to base runtime/schema or a new
release baseline require a separate reviewed guard/version migration. The guard
is source-review evidence, not a cryptographic or authorization boundary: a PR
can change a verifier, so independent review and protected main remain essential.
All existing workflow families continue to run on the candidate checkout.

## Artifact evidence

A dedicated CI matrix checks the manifest with adversarial cases, the historical
RC02A delta, two clean wheel builds from the actual tested Git tree with a fixed
SOURCE_DATE_EPOCH, and byte equality within each runner/interpreter environment.
It stages reviewed version-pinned dependency wheels, installs without an index
into a clean venv, checks dependencies and runs synthetic CLI outside checkout.
Artifacts are short-lived **CI candidates**: wheel, SHA-256, actual test checkout
commit, tree and Git inventory, staged dependency wheel hashes, build environment.
This does not prove bit-for-bit equality across platforms/interpreters, dependency
supply-chain attestation, a hash-locked universal dependency set or a signed
release. Initial wheel staging needs package access. No PyPI, tag, GitHub Release,
Console module catalog, service install, or publication is authorized.

## Operator/reviewer gate

- [ ] Independently approve #11 and owner dispositions; verify ruleset required
  checks and exact main/head before an explicit merge commit. Verify merged tree,
  ancestry and all CI; only then reconcile old review PRs.
- [ ] Review RC03C scope migration and candidate artifact hashes; re-run applicable
  workflows on exact candidate, independently review and add its two check names
  to protection when integrated. No automatic ruleset edits or bypass.
- [ ] Select a reviewed package and dependency wheel set, verify digests, record
  platform/Python and source tree, approve separate release/version/tag decision.
- [ ] For a disposable offline lab only: stage into a new venv, verify wheel and
  dependency hashes before installation, use `--no-index` with reviewed wheelhouse,
  run synthetic CLI, keep previous artifact and environment unchanged. Roll back
  by stopping the lab and discarding this staging venv; no changes to running
  Console, IMU, Voice, Somatic, Chronon stores or OS service. Real host rehearsal
  and resource/privilege acceptance belong to RUNTIME-01C/D.

RC03C implements release-readiness tooling, not M0 completion. RC03B independent
approval/actual merge and separate release approval are still open.
