# COG-RUNTIME-01C — isolated synthetic service rehearsal

27 November 2026. **Candidate / non-normative / SESSION_SCOPED / synthetic-only.**
Based on frozen [01B #15](https://github.com/OpenRGD/rgd-cognition/pull/15),
`a2e8690781d9acfa2c134a0ce9722285d0723d57`.
Master [#2](https://github.com/OpenRGD/rgd-cognition/issues/2), design
[#12](https://github.com/OpenRGD/rgd-cognition/issues/12).

## Problem and delivered boundary

01A/01B required the caller to keep pumping `tick()`, and the fixed child inherited
its caller's OS privileges. This increment supplies one continuously pumped,
finite synthetic session and a reviewed systemd service candidate. The actual
systemd rehearsal is executed only in a disposable Ubuntu 22.04 GitHub VM.
The authoring container has no running systemd; local Python tests do not prove
OS isolation. A successful rehearsal report, not this document, is the OS evidence.

No previous runtime/schema, Core/RI pin, package version, Foundation CLI or
protected main is changed. The C0 path remains historical; unchanged Core-B is
the sole Work admission. Governance packet: [RC03B](COG-RC-03B-INTEGRATION.md).
Independent review, source integration and N150 acceptance remain separate gates.

## One finite service session

`python -I -B -m rgd_cognition.service_lab run --enable-synthetic-lab
--core-b-checkout PATH --runtime-dir DIR --duration-seconds 60` explicitly enables
only the existing fixed synthetic fixture. Omitting opt-in refuses to start.
There is no source/model/task/plugin/command/network parameter.

The loop generates nominal 10 Hz fixture samples and pumps every 10 ms, dispatching
only already-ADMITTED goals through existing WorkerLab. One flight, no second
admission, automatic resume, policy rollover or remote inference. A missed sample
slot is dropped and counted, not converted to a burst of fresh inputs. Maximum
configured session is eight hours; the service unit is deliberately fixed at 60 s.

The session clock is actual monotonic time floored to an explicit 1 ms resolution,
matching the existing integer-ms C1/Core-B lifetime arithmetic. It does not invent
time or extend TTL. This avoids the historical `CREATION_BUCKET_NOT_REACHED`
deferral caused by supplying a sub-ms creation time to a current integer-ms receiver.
Service duration and the unchanged worker's independent deadline use full real
monotonic time. Fixture source timestamps remain declared synthetic metadata,
not qualified sensor time, Chronograf, a boot identity or calibration.

SIGTERM/SIGINT handlers only set a stop flag. The owner loop performs logical Work
stop/reap in `finally`; no async mutation of Work in a signal handler. A status
write fault stops the session. The service does not resume across restart.

## Diagnostics, not history or liveness

A private owned 0700 RuntimeDirectory contains one atomic 0600 `status.json` and
an advisory singleton lock. Directory-FD/no-follow operations reject symlinks,
nonregular or multiply linked files, unsafe modes, duplicate/noncanonical JSON
and oversized reads. The parent paths must be operator trusted.

Snapshots contain fixed health fields, local session references and bounded
counters; no sample, result payload, transcript or private reasoning is stored.
`cache_only=true`, `liveness_verified=false` and `fixture_only=true` are explicit.
The status CLI is for the same service user; root test tooling reads the file only
for rehearsal evidence. RuntimeDirectory is removed on stop. The final redacted
snapshot is also printed to inherited journal stdout for supervisor diagnostics;
journal retention remains the host operator's policy, not canonical history.

## Linux unit

`tools/runtime01c/rgd-cog-lab.service` has no `[Install]` section and `Restart=no`.
It uses a transient dedicated unprivileged `DynamicUser`, empty capabilities,
NoNewPrivileges, private devices/network/tmp, read-only system/home protection,
restricted namespaces/native syscalls and no new network/Unix sockets. Inherited
journal stdout/stderr are intentional IPC; there is no socket activation.

`RestrictAddressFamilies=none` does not cover `socketpair()` or already inherited
sockets by itself. The explicit socket/socketpair syscall denial and native ABI
restriction close the new-socket path for this fixed workload. It is not a
general hostile-code sandbox certification. Device access and actual denial of
privileged socket fixtures are tested separately from import/AST checks.

Applied candidate limits: MemoryHigh 384 MiB, MemoryMax 512 MiB, no swap, CPU quota
one core, TasksMax 16, no core dumps. These are imposed limits, not N150 measured
resource needs. KillMode=control-group, TimeoutStopSec=5 s and RuntimeMaxSec=75 s
provide an external finite lifetime even when Python cannot make progress.
There is no autonomous progress watchdog claiming to detect every stalled loop.

Official target references:
- [systemd 249 exec](https://www.freedesktop.org/software/systemd/man/249/systemd.exec.html)
- [systemd 249 service](https://www.freedesktop.org/software/systemd/man/249/systemd.service.html)
- [Ubuntu 22.04 resource control](https://manpages.ubuntu.com/manpages/jammy/man5/systemd.resource-control.5.html)

## Exact candidate artifact

The CI builds two clean wheels from the exact tested tree with a fixed build
timestamp and compares them within one runner/interpreter. `artifact.py` bundles
the candidate wheel, version-pinned dependency wheels, requirements, exact Core-B
schema and unit. Every file has size/SHA-256, and source commit/tree are recorded.
Verification rejects missing/extra/changed files, symlinks, path traversal and
Core-B schema drift. Hashes establish supplied byte consistency, not publisher
authentication or an approved Module Registry release. The bundle targets the
tested Python/platform; no universal/cross-platform reproducibility claim.

Two fresh venvs are installed with `--no-index` from that bundle. The rehearsal
stops the service before switching an operator-owned `current` symlink A→B→A and
executes a genuine synthetic inquiry after each switch. Both installs use the
same reviewed code: this proves staging/path rollback, not cross-version data
migration or compatibility. Nothing is published to a package or module registry.

## Executable isolation evidence

`rehearse.py` requires explicit `--disposable-ci`, root, a disposable GitHub Linux
VM marker, Ubuntu 22.04, active systemd and cgroup v2. It refuses collisions with
existing units/users/paths. The markers prevent mistakes, not authenticate an
operator. This is a CI rehearsal, **not a robot installation command**.

The dedicated workflow requires actual execution, with no silent skip:
1. Service tests normally and under `-O`, actual admitted/completed child and
   SIGTERM shutdown; exact historical and 01C scope checks.
2. Two clean matching wheels, bundle verification and two offline installations.
3. Exact candidate service running under its unit; real Work result, current
   cgroup memory/CPU/task settings, stop and empty group.
4. Harmless outside controls: an accessible char-device sentinel, writable
   artifact sentinel and world-connectable Unix socket. Inside the same sandbox,
   device/RO/network/CAN/Unix access attempts must be denied, capabilities zero
   and no-new-privileges active. No robot hardware or real daemon is probed.
5. A fixed finite TERM-ignoring parent, child and grandchild are confirmed alive
   in the service cgroup before stop. Their process-start identities and group
   emptiness must demonstrate cleanup, rather than waiting for their finite exit.
6. A shortened external runtime cap ends an unresponsive fixture with no restart.
7. Fixture removal and service unload are part of the pass gate, even on errors.

The report records test checkout/tree, OS/systemd, negative outcomes, cgroup
settings, cleanup and rollback scope. CI artifacts have seven-day retention.
The PR's exact-head run/decoded logs are the validation record; no claim is made
for a pending, cancelled or failed run. Local tests use Python 3.12; dedicated
service CI uses Python 3.10 on Ubuntu 22.04, complementary to existing matrices.

## Remaining boundaries

- 01D: exact staged artifact on N150, actual latency/load/RSS, 8-hour wall-clock
  soak, source/operator interruption and owner-approved host rollback.
- Existing WorkerLab's version-bound private Work snapshot remains a candidate
  dependency; a public immutable dispatch accessor needs owner agreement.
- New sources, authenticated transport, source-profile reconciliation and RI
  access semantics belong to COG-RI-03/M2. This service connects none of them.
- No model, Voice/Visual output, Life enrollment, Chronon writer, retained
  autobiography, actuator or digital-effect dispatch is introduced.
- Linux VM rehearsal is not physical safety certification or permission to
  install on Paky-01. Package version remains 0.1.0a1; main review remains open.
