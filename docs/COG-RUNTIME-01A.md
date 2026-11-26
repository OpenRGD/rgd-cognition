# COG-RUNTIME-01A — supervised lifecycle laboratory

**26 November 2026 · candidate / non-normative / SESSION_SCOPED / INTERNAL_READ_ONLY.**
[Design issue #12](https://github.com/OpenRGD/rgd-cognition/issues/12) ·
[RC03 #11](https://github.com/OpenRGD/rgd-cognition/pull/11) ·
[RC03C #13](https://github.com/OpenRGD/rgd-cognition/pull/13).
This is the first caller-pumped runtime lab, not a daemon or an installed service.
No live source, worker execution, transport, OS isolation, Life or history writer.

## Ownership and explicit lifecycle

`RuntimeLab` creates exactly one actual `CoreBAttentionHost`, hence one actual
`ImuAttention` and `KernelSession`. C0 is not called for admission. Existing
contracts, runtime modules, upstream pins and regression tests are unchanged.
The trusted operator and synthetic-source owner tokens are in-process capabilities,
not credentials or sandbox boundaries. The supervisor is bound to one caller
thread; `tick()` handles at most one control or one input and advances the real
Work heartbeat, including when no input is pending. There is no background task
or blocking wait. Health is a cached diagnostic, not proof of process liveness.
The runtime is disabled by default; explicit lab enable and resource NORMAL are
separate from the existing Work policy's enabled flag. Optional real pinned
`RGDContextResolver` may supply an already refreshed profile in the lab; no
reloading/repinning in the event loop. Context revocation closes the session.

Start from STOPPED creates new synthetic source/session labels and runtime UUID;
state is DEGRADED until the trusted operator declares NORMAL. PAUSE and STOP
supersede pending normal controls, cannot be crowded out by input/control
capacity, and are processed before input on the next tick (not asynchronous
preemption). PAUSE invokes the existing Work barrier, clears queued observations
and transient Attention. RELEASE only removes that barrier, not automatic work
resume. STOP closes Work and purges queues/replay metadata. FAULT requires
explicit stop and a new start; no automatic quota reset or session restoration.

## Bounded ingress and clocks

A synthetic source must match the configured source/sensor/frame/alias and both
runtime and source session labels. COG retains the existing Console/C1 record
schema and validation. Denial does not parse or retain that sample; drops pending
observations and clears transient Attention. This is per-presentation lab consent,
not a real revocation service or erasure guarantee. The supervisor assigns its own
session-relative monotonic receipt at first acceptance; it does not use foreign
host counters for local TTL. Fingerprints are local content hashes, not signatures.
Existing C1 source order checks and ceil/floor cue deadline deferral are preserved.

Input queue <=64, control queue <=8, default replay cache 256 (all configurable
within hard caps), default max session 24h. Retain accepted fingerprints until
original local receipt expiry; equal replay is inert, changed same key conflicts.
Session high-water rejects older sequences/source counters even after fingerprints
expire. New valid samples dropped under pressure or pause consume their sequence
so retry cannot obtain a renewed TTL. No across-reboot/durable replay proof;
trusted fixture source could create new labels/content. Unknown/unavailable real
sources remain outside this wave. Clock exception/regression, session limit,
context or Work fault fail closed with redacted reason and release of local
reservations; no fabricated elapsed time. No scheduler executes accepted goals
in 01A. Actual Work reserves/invalidates/expires them. 01B owns worker dispatch,
logical revocation and process cancellation. Do not claim preemptive provider
limits from this increment.

## Verification

New tests exercise 1,000 synthetic samples, actual C1->Core-B admission (C0
admission patched to fail if invoked), idle Work expiry, priority pause/stop,
resource recovery, duplicates/conflict/pressure/expiry, session/source isolation,
clock failures, actual pinned RGD context revocation, audit saturation and bounded
health. The lab does not open a socket or launch a process. Core-B schema is supplied
from its exact pinned checkout; the CLI reads that bounded local schema only.

```sh
# Explicit synthetic replay in a development environment, not Paky-01 deployment:
python -m rgd_cognition.runtime_lab --core-b-checkout /path/to/pinned/core-b --events 1000
```

Default fixture replay: 1,000 processed, zero pending input, 4 cue admissions,
peak retained replay entries 30 at a 3 s TTL and 10 Hz *simulated* clock. Work
steps consumed = 0; goal expiry releases all reservations, stop purges replay.
UUIDs differ across runs. These are functional fixture counters, not measured
N150 throughput, latency or resource acceptance. CI on 3.10/3.12 also runs normal
and optimized tests and installed-wheel CLI; previous nine workflow families remain.
No live producer, remote provider, output, persistence, device, service installation,
privilege or release. M0 governance and independent review still required.
