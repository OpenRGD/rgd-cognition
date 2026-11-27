# COG-RC-03B — integration review packet

**27 November 2026 · CANDIDATE · NON-NORMATIVE · SESSION_SCOPED · INTERNAL_READ_ONLY.**

This packet records the verified integration target and the remaining acceptance
steps. It does not declare a merge, release, upstream contract adoption or robot
installation. Operator direction is to complete RC03B and continue RUNTIME-01C
and COG-RI-03; the remaining independent approval is a repository gate, not a
request to repeat that direction.

## 1. Refreshed repository evidence

GitHub API evidence was refreshed on **27 November 2026 at approximately
11:20 UTC**. The workflow results below are the latest recorded executions at
the inspected heads; they were re-read, not re-run for this document.

| Item | Observed state |
| --- | --- |
| Protected main | `39af2501bb94ce50921b0ed2ea1359fd82d3bcaa`, initial README-only tree |
| RC03 integration #11 | OPEN / DRAFT, head `b601674bf3a539ce029e1c2253c2ae4b49e291e9`, base main; `mergeable=true`, `mergeable_state=blocked` |
| RC03C #13 | OPEN / DRAFT, head `a83381b13396baa226e3aaa714225db9b3983051`, base RC03 branch; aggregate merge state `unstable` |
| RUNTIME-01A #14 | OPEN / DRAFT, head `1c01c855ebe1927aedd2e70b99ad49d6a1636cb5`, base RC03C; aggregate merge state `unstable` |
| RUNTIME-01B #15 | OPEN / DRAFT, head `a2e8690781d9acfa2c134a0ce9722285d0723d57`, base 01A; aggregate merge state `clean` |
| Independent approvals | Zero submitted reviews on #11, #13, #14 and #15 |
| Inline review threads | None on those four PRs |
| Main protection | Active ruleset 28104469, 16 strict required contexts, one approving review, no bypass actors |

Sources: [main](https://github.com/OpenRGD/rgd-cognition/tree/main),
[PR #11](https://github.com/OpenRGD/rgd-cognition/pull/11),
[#13](https://github.com/OpenRGD/rgd-cognition/pull/13),
[#14](https://github.com/OpenRGD/rgd-cognition/pull/14),
[#15](https://github.com/OpenRGD/rgd-cognition/pull/15),
[ruleset](https://github.com/OpenRGD/rgd-cognition/rules/28104469).

GitHub's `mergeable` field describes whether histories can be combined without
a textual conflict. It does not satisfy draft state, required approval, required
checks or documented owner acceptance. Ruleset enforcement is active even
though the separate legacy branch-protection object reports disabled.

The current ruleset also dismisses stale approvals, requires resolved review
conversations, blocks force pushes/deletion and has no bypass actors. Code-owner
approval is not an enabled GitHub rule. Core and RI/Console semantic dispositions
remain project acceptance requirements recorded in #11 and the master tracker.

## 2. Frozen atomic target

RC03 #11 contains all original nine review heads and the RC02A corrections:
19 commits ahead of main, 82 changed paths. The target source tree is
`aec46c865420d0d975fef4ca420e973e8d723ae3`.
GitHub's test merge `d251ab57ed82b8c9f6060d6d8e46ae6db22fec8a`
has the same tree. That test object is not an actual main merge.

| Original PR | Exact reviewed head |
| --- | --- |
| #1 Foundation | `aef3cd4be6c9405d3c8069d90b031484e11d6f4b` |
| #3 RGD context | `940757af306dc538d3f3e0c70fed5f0671024be9` |
| #4 C0 legacy lab | `a964c2f3bd65969267b9d6ca14b5eb8557f40f35` |
| #5 C1 attention | `a8ae925c9cacbce8bd7a6db01833d4159445d47a` |
| #6 Core-B Work | `a2526ba414409cc92641dc95bbddd6564317fcc4` |
| #7 Core-D projection | `3b78e835ca963ea80ee20885d3552e5f200c2b99` |
| #8 RI01 references | `29a8a0b60ce365d2a0fd1f38313a3a319793bc6a` |
| #9 RI02 candidate binding | `9235d3759b263bfde2d8644c46845e9a338e9238` |
| #10 RC02A hardening | `b601674bf3a539ce029e1c2253c2ae4b49e291e9` |

Use one ancestry-preserving merge commit for #11. Squashing or rebasing would
discard the reviewed commit ancestry and invalidate the recorded integration
strategy. Do not publish the old #4/#6 states separately: their findings are
corrected only when #10 is included. Preserve historical scope pins and review
records.

## 3. Defects the reviewer must close

[RC02A](COG-RC-02A.md) and [PR #10](https://github.com/OpenRGD/rgd-cognition/pull/10)
record seven reproduced findings and sixteen added regression methods. The
existing exact-head CI is successful; this packet does not claim a new
independent execution of those reproductions.

| Finding | Required invariant in the integrated candidate |
| --- | --- |
| RC-01 | REJECTED/DEFERRED remain final non-admission dispositions; later expiry does not turn them into admitted work. |
| RC-02 | The immutable C0 request fingerprint includes the complete event, requested budgets, TTL, effect/network request and context; changed reuse conflicts. |
| RC-03 | C0 has a session pause barrier with explicit trusted-host release, including audit-exhaustion failure behavior. C0 remains a legacy lab. |
| RC-04 | Core-B transition, outcome and trace contexts match exactly, including revision and fences. |
| RC-05 | Result code, state transition, detail reason and semantics remain consistent even after local digests are recomputed. |
| RC-06 | The admission receiver validates the typed C1 companion, original cue/session/clock/provenance and original evidence lifetime before reserving work. |
| RC-07 | The operator-owned Core-B Work barrier prevents admission/start/resume/tickets/late completion and Oneiric review; releasing it does not resume work or revive old tickets. |

Core-B is the sole intended runtime admission owner. C0 is not a second
production scheduler. Local digests and schema validity are consistency
evidence, not issuer authentication, verified physical identity or permission.

## 4. CI evidence and applicable check sets

The refresh matched head SHA, `pull_request` event, PR number and workflow run,
then checked the individual matrix jobs.

| PR | Families / jobs | Result | Representative run |
| --- | ---: | --- | --- |
| #11 | 8 / 16 | All SUCCESS | [Core-B 45796314989](https://github.com/OpenRGD/rgd-cognition/actions/runs/45796314989) |
| #13 | 9 / 18 | All SUCCESS | [Packaging 45807415311](https://github.com/OpenRGD/rgd-cognition/actions/runs/45807415311) |
| #14 | 10 / 20 | All SUCCESS | [Runtime 45808057155](https://github.com/OpenRGD/rgd-cognition/actions/runs/45808057155) |
| #15 | 11 / 22 | All SUCCESS | [Worker 45814347526](https://github.com/OpenRGD/rgd-cognition/actions/runs/45814347526) |

Shared-SHA aggregate check lists also contain cancelled push runs created when
a successor branch initially pointed to the predecessor SHA. Those are not
failures of the correct PR's tested code. They can affect aggregate status
presentation; inspect the actual target PR's required-check decision before
merging, and obtain fresh applicable runs if GitHub requires them. Never remove
required checks to work around this state.

Current required contexts (each with `-py3.10` and `-py3.12`, GitHub Actions
integration ID 15368):

- `foundation`
- `rgd-context`
- `agenda-c0`
- `attention-c1`
- `core-b-adapter`
- `cog-core-d`
- `cog-ri`
- `ri-imu-binding`

Additional protection is staged with the increment that supplies the jobs:

| Increment | New applicable pair | Total original-plus-new contexts |
| --- | --- | ---: |
| RC03C #13 | `release-readiness-py3.10`, `release-readiness-py3.12` | 18 |
| RUNTIME-01A #14 | `runtime-lab-py3.10`, `runtime-lab-py3.12` | 20 |
| RUNTIME-01B #15 | `runtime-worker-py3.10`, `runtime-worker-py3.12` | 22 |
| RUNTIME-01C | `runtime-isolation-ubuntu22-py3.10` (single Ubuntu 22.04 rehearsal job) | 23 |

Do not add successor-only checks to frozen #11, where those workflows do not
exist. The newer six contexts were not required by the inspected ruleset.
The authorized repository administrator must verify appropriate enforcement
when integrating each stage; this packet does not change administrative rules.

## 5. Required disposition record

These entries remain **OPEN** until an eligible owner/reviewer records actual
acceptance with its scope and source revision.

| Disposition | What must be recorded | Current evidence |
| --- | --- | --- |
| Independent RC03 review | Approval of combined #11 diff at the exact reviewed head, including RC02A findings and original discussions | No submitted review on #11 |
| Core semantic review | Lifecycle, task, outcome, trace, pause/resource semantics and single Work admission; acceptance or explicit candidate-only scope | Required by #11; no acceptance inferred here |
| RI/Console disposition | Treatment of #9's normalized-copy binding versus the producer-owned record contract; prevent silent adoption or duplicate ingest ownership | COG-RI-03 reconciliation is a separate workstream; no transport approval inferred |
| RC03C review | Fixed historical scope, exact reviewed evolution manifest, wheel/dependency provenance and limits of reproducibility | CI successful; no submitted review on #13 |
| Runtime review | Explicit caller-driven lifecycle, fixture-only subprocess, original ticket lifetime, cleanup/failure semantics and lack of existing OS isolation | CI successful; no submitted review on #14/#15 |

Candidate-only acceptance must explicitly preserve the limitations: no
normative Core/RI schema adoption, positive Life/robot identity, History writer,
live transport, real provider, external effects or deployment. It does not
resolve an incompatible producer/consumer contract by assertion.

## 6. Ordered execution after gates are satisfied

1. Re-read #11 head, main, required checks, draft state, reviews, threads and
   owner dispositions. Preserve the expected head
   `b601674bf3a539ce029e1c2253c2ae4b49e291e9`; if it changed, stop and review
   the new source. The operator has directed integration, but an approval
   by another eligible GitHub reviewer is still required.
2. Make #11 ready for review as part of the review workflow. After all actual
   gates pass, merge with a merge commit under an expected-head check. No
   self-approval, force push, administrative bypass or weakened protection.
3. Read the resulting main commit and tree. Verify the expected candidate tree
   when the base is unchanged, both merge parents, all nine original ancestor
   heads and applicable CI. If main advanced independently, review the combined
   tree and rerun CI instead of asserting equality to the old target.
4. Only after inclusion is verified, reconcile the original PR records with
   links to the integration. Do not delete review branches during the audit.
5. Retarget #13 to the verified main as appropriate. Inspect its resulting diff,
   preserve history, obtain applicable exact-head/base CI and independent
   acceptance. If strict up-to-date checks need a base update, use an
   ancestry-preserving merge and review the new head; do not silently rebase.
   Add its applicable required-check pair at the integration stage.
6. Apply the same process to #14, then #15. Never merge them into unprotected
   intermediate branches merely to avoid the main review gate. Preserve
   old scope guards and the exact review manifest.
7. Review RUNTIME-01C independently on the complete candidate. Its lab evidence
   must distinguish packaging/service validation from actual OS enforcement.
   The supervised N150 benchmark remains RUNTIME-01D, with measured acceptance.
8. Record any release/version/tag decision separately. Integrating source does
   not publish a package or install a service on Paky-01.

## 7. Closure criteria

- [x] Current main/heads/ruleset independently re-read.
- [x] Correct PR/head CI metadata and matrix jobs verified.
- [x] Frozen ancestry, fixed findings and integration sequence made reviewable.
- [ ] Independent exact-head approval recorded.
- [ ] Core and RI/Console owner dispositions recorded.
- [ ] #11 actually merged under protected main rules.
- [ ] Resulting main tree, included ancestry and CI verified.
- [ ] Historical PR records reconciled after verified inclusion.
- [ ] Successor review/integration and applicable protection completed.

**RC03B remains blocked on the unchecked acceptance/integration items.**
RUNTIME-01C implementation and COG-RI-03 reconciliation may advance in separate
reviewable candidates while the frozen baseline awaits independent approval.
This packet is a status and execution record, not an approval substitution.
