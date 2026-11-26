# COG-RUNTIME-01B — Bounded Worker & Cancellation

**Candidate · non-normative · SESSION_SCOPED · INTERNAL_READ_ONLY · Linux synthetic lab.**
Stacked on [01A #14](https://github.com/OpenRGD/rgd-cognition/pull/14), exact
`1c01c855ebe1927aedd2e70b99ad49d6a1636cb5`. [Design issue #12](https://github.com/OpenRGD/rgd-cognition/issues/12).
No change to #11, existing runtime modules, Core/RI pins, wire schemas or package version.
Independent review and M0 integration remain mandatory before merge or deployment.

## Architecture and ownership

`WorkerLab` is an explicitly opt-in extension of `RuntimeLab`. 01A remains the
no-process laboratory; its API, code and tests are unchanged. The new Python
subpackage `rgd_cognition.worker_lab` is the only process-launch compartment.
A separate recursive AST regression extends the original Foundation root-module
guard; the existing guard is not removed or weakened. Only this supervisor's
one fixed `Popen` site may import subprocess. This is code regression evidence,
not a security sandbox or proof about dependencies.

- The operator explicitly enables the lab, Work and worker; resource starts
  UNKNOWN. Actual C1 -> Core-B still decides admission; no C0 admission, second
  scheduler or automatic dispatch/resume. `eligible(operator)` reports existing
  admitted or paused synthetic IMU inquiry goals. `dispatch(operator, goal_id,
  resume=False)` starts only an ADMITTED goal. Resume must be explicitly requested
  after Work's session barrier is released. At most one flight.
- The exact pinned `KernelSession` currently has no public complete dispatch
  snapshot. A narrow read-only companion reads its job data under the existing
  lock on the serialized caller thread; never mutates job state. Public Work
  operations own move/ticket/finish/invalidations, aggregate reservations and
  generation. A future stable snapshot contract needs owner review.
- After Work.move(RUNNING) and Work.ticket, the supervisor makes a unique
  request ID bound to the ticket digest and exact admitted evidence refs. A
  separate fixed stdlib-only script receives one bounded canonical JSON request
  via an inherited stdin pipe; stdout is one bounded response and process exit.
  4096-byte hard cap; closed fields; reject duplicate keys, noncanonical,
  nonfinite, trailing, oversize or malformed input, unknown task, changed
  request/ticket/content binding, unapproved evidence refs or authority fields.
  Child gets digests and synthetic refs only, not owner tokens, raw observations,
  credentials, ContextSlice or command/path arguments. No arbitrary model data,
  shell, plugins, network or device interface. The sole task is the deterministic
  synthetic reference-presence inquiry `cog.task.v1:imu-uncertainty`.
- The script path and Python interpreter are host code, fixed mode from trusted
  finite config. Isolated interpreter flags `-I -B`, reduced environment, closed
  inherited FDs, separate session, stderr discarded. Test-only modes exercise
  BLOCK, IGNORE_TERM, CRASH, MALFORMED, OVERSIZE, WRONG_TICKET and TRAILING;
  blocked fixture sleeps at most three seconds even if caller stops pumping.
  No user/model-selected executable or argument list. Subprocess has the same
  user's OS privileges; do not deploy as an isolated production worker yet.

## Deadline, result and cancellation contract

`WorkerLabConfig` is frozen, disabled by default; default 750 ms process wall
budget (hard max 1000 ms), TERM grace default 100 ms (10–250 ms). Supervisor
caps each dispatch by the minimum of original goal/evidence half-open deadline,
remaining actual Work wall reservation (conservative ms bucket), and configured
worker deadline. It separately uses a real monotonic process deadline, so a
frozen synthetic session clock cannot extend a running child. Work charges its
own session clock; fixture runs with a frozen clock do not measure real Work
wall cost. No new canonical clock or time/identity proof.

Caller-driven tick runs 01A priority control and Work heartbeat before polling
bounded nonblocking stdout. A result is eligible only after child exit success
and EOF, canonical exact response matching, both deadlines, current Work state,
generation and exact original ticket checked. Supervisor passes its own ticket
to `Work.finish` (which rechecks Work expiry/context/state under lock) and
validates the returned outcome/trace. The accepted code only denotes the
synthetic inquiry completed **UNVERIFIED**; no physical truth or calibration.
Exactly one result is returned ephemerally; subsequent ticks cannot replay it.

A queued pause/stop wins over a buffered successful reply. Resource degradation,
context/clock/session loss, original TTL expiry and consent denial revoke the
eligible work before accepting another result. In worker-enabled lab, consent
denial explicitly faults and closes the whole session (stronger than 01A's
per-presentation consent). Timeout/crash/invalid frame causes FAILED via actual
Work if still RUNNING; if already revoked/expired/paused, preserve Work's state.
Use existing transition reason vocabulary; separate stable worker diagnostic
codes, not new schemas. No successful result on failure. Unexpected result-bundle
integrity failure closes session without publishing. On stop/fault, Work closes
first; the child is detached from the result channel, TERM then KILL after
bounded wait, and reaped; no accepted late reply. A failed reap retains the
process handle and faults the session; explicit stop must finish cleanup before
restart. No automatic resumption. Cleanup may synchronously wait up to two grace
intervals (bounded); normal tick polls without waiting for worker completion.

**Limits:** caller must continue pumping tick (including idle), and stop in a
finally block. No autonomous watchdog while the caller is suspended/dead; launch
itself is not preemptively bounded. Fixed child has no descendants; the lab does
not prove process-tree containment, syscall/network/device isolation, real-time
interrupts or remote provider cancellation. 01C must test actual dedicated
account/cgroup/device/IPC/egress enforcement and service shutdown. No N150 timing,
real source, real inference, durable memory, voice playback or effects tested.

## Verification and scope

New tests exercise real POSIX subprocesses and real C1/Core-B, strict protocol,
explicit dispatch/one flight, result-to-Work/trace, no new admission, actual
frozen-clock timeout, original deadline, elapsed Work accounting, pause and
resource cancellation, explicit resume/new ticket, context and clock revocation,
consent, restart, child failure/malformed/oversize/bad binding/trailing, TERM
ignore -> KILL/reap, cleanup failure (fault injection) and no result on integrity
failure. Scope: six additions (three worker package modules, test, doc, CI),
manifest update and one CI-only 01A scope adjustment. 01A guard now compares
its exact historical #13 -> #14 delta, not a changing HEAD, while release
manifest and dedicated 01B exact-delta guard protect the descendant. No older
runtime or schema modification. Previous workflow names and checks stay intact.

Explicit development-only smoke:

```sh
python -m rgd_cognition.worker_lab --core-b-checkout /path/to/pinned/core-b
```

No host install, systemd changes, release, merges, hardware access or new
external authority. RUNTIME-01C and 01D remain separate reviewed increments.
