# COG–RI–02 · Console IMU ↔ Reality Ingress evidence binding

**25 November 2026 · CANDIDATE / NON-NORMATIVE / SESSION_SCOPED / INTERNAL_READ_ONLY / no deploy.**

## Sources and independent pins

| Owner | Source | Exact reviewed revision | Contract |
|---|---|---|---|
| COG | COG-RI-01 draft [PR #8](https://github.com/OpenRGD/rgd-cognition/pull/8) | `29a8a0b60ce365d2a0fd1f38313a3a319793bc6a` | `ri_reference_notice_v0.1` stays unchanged |
| Reality Ingress | Candidate [PR #4](https://github.com/OpenRGD/rgd-reality-ingress/pull/4) | `5372f758df79c93fc887f3858d878635447f4a4d` | RI consumer schema blob `3d92e074e71593bf6db0a735394c628ea131668d` |
| Console/IMU | `OpenRGD/rgd-console` main | `a0ef857cf425c1bb14ad8f62acec21f8c1324866` | `console.imu.v0.1-candidate` blob `8ddbe8d7639e35f0a9442a80e27c9e49f882eb7c` |
| Canonical Core | COG-02 baseline | `afe1a831b950a4e6560f0285a0103fc4eaa343b7` | Source-root and toolchain unchanged |

Console PERIPH [PR #5](https://github.com/OpenRGD/rgd-console/pull/5) / [#6](https://github.com/OpenRGD/rgd-console/pull/6) remain separate drafts. The existing physical chain is **one WIT/CH340 host serial reader → authorized Console loopback ingest → read-only WS**. Neither COG nor RI owns the device or the publisher token. This change adds no listener, file poller, network client or privileged effect.

## Actual relationship established

1. The trusted upstream host already has a **normalized Console IMU record** (not a device stream created here). A **separate authorized RI path** may persist an exact, deterministic *representation* using RI v0.4's existing `source-sample:v0` JSONL/storage mechanism. This producer bridge **has not been deployed** on Paky-01.
2. The explicit stored representation is a RI generic source-sample, media `application/vnd.openrgd.experimental.sensor-sample+json`, whose `payload` is exactly `{ "representation_profile": "cog-ri-02.console-copy.v0.1-candidate", "console_imu_record": <original ConsoleImuRecord> }`. The `source` IDs/frame/sequence and the RI receiver receipt metadata must match the reference exactly.
3. The existing RI EvidenceStore's `record_sample`, `verified_ref_from_store` and `RIReferenceConsumer` are used in the tests. The *new COG module* only receives an authorized reference and already-supplied bytes; it does **not** open the RI store, USB, CAN, serial, microphone, camera, file or socket.
4. The binder checks the exact Console schema bytes against the pinned Git blob, reuses COG-C1 `ConsoleImuRecord` validation, verifies that the stored embedded record is byte-identical under the declared canonical JSON encoding and that the entire stored payload hash/size equals the RI reference. It preserves the original RI `observation_id`, payload hash, source/frame, sensor/session/sequence and both **distinct host receipt clocks**.
5. The resulting inert record relates `RI observation_id` to the *existing* C1 local evidence ref calculated by C1's own digest rules. An integration test confirms that the real C1 `ImuAttention` replay emits the same local evidence ref. **No RI ID is injected into the C1 `InputEvent`, `AttentionCue` or Work ABI.**

## What binding is NOT

Even an exact match of the stored normalized copy **does not prove** that the IMU physically sampled its measurement, that the Console publisher was cryptographically authenticated, that `source_kind=physical` attests hardware, that RI re-encoded *raw* serial bytes, or that the source was calibrated. It cannot certify robot identity or `SELF`, pose, heading, a first step, Chronograf timestamp or a Chronon. `decision_eligible=false`, `can_generate_goal=false`, `may_actuate=false`, `grants_authority=false`, `source_authentication=NOT_VERIFIED`, `life_id=null`, `chronon_id=null` remain mandatory.

The direct C1 numeric feed continues via its existing trusted publisher integration; the optional RI binding provides corroborating, **locally checked content provenance**, not a second admission path. Never infer fresh sensor evidence from a stored reference alone.

## Clock/boot and privacy boundaries

- `ConsoleImuRecord.host_monotonic_ns` is **Console publisher host receipt time**, distinct from RI's `time.received_monotonic_ns`, which is **RI host receipt time**. C1 local receipt is a third time. A `host_receive_utc` string does not authorize comparing monotonic counters from different hosts.
- `HOST_SAME_BOOT_ASSERTED` is used only when an *independent trusted host configuration* asserts the Console publisher and RI receiver share a clock/boot, and the existing RI read-only consumer reports same-boot alignment. Sequence and timing must be consistent. Even then it is an operator-level assumption, **not** Chronograf qualification. Otherwise `clock_relation=NOT_ESTABLISHED`, `freshness=UNKNOWN`. Stale is distinct from unknown; neither regenerates old TTL.
- Current RI reference has no Console publisher session ID. The **explicit stored normalized Console sample** carries `session_id`; it is checked against C1 `SourceBinding` configured by the host. Session mismatch is a hard error. This is not cryptographic owner validation.
- Read ACL, consent, retention and evidence availability are provided by the RI/host owner, **not the reference payload**. Default RI consumer permissions are off. With `ERASED`, `REDACTED`, `UNAVAILABLE`, consent denied or revoked payload access no binding is emitted. The adapter's output contains hashes and references only, no media bytes or private filesystem paths.
- A stored payload whose byte digest matches a previously issued reference may have since been removed from RI storage; the caller must still independently confirm current availability and access. No distributed proof-of-possession is implied.
- Duplicate presentation is inert; same source/session/sequence with changed data or same observation ID with different content is a conflict; bounded session map retains keys, then backpressure, never automatic early replay eviction. No durable replay guard across reboot is claimed.

## Software acceptance and rollback

The opt-in `ri_imu_binding.py` has strict bounded JSON parsing, exact schema pins, closed output companion schema, a finite binder and in-process owner channels. Its tests use the **real RI generic producer/store** with synthetic numeric Console-shaped records and the existing real C1 detector; Console is validated from its pinned source schema. They do *not* start the Console Rust server or a sensor. Existing COG C0/C1/Core-B/Core-D/RI01 runtime code and Core source remain unchanged.

```sh
# In a test environment with reviewed exact COG/RI/Console checkouts:
RI_CHECKOUT=/path/RI CONSOLE_CHECKOUT=/path/Console \
  python -m unittest discover -s tests_ri02 -v
```

For any later **operator-approved physical pilot**, the Console/IMU publisher owner must first authorize a nonblocking *read-only fan-out*, agree the exact stored normalized serialization, current source/boot/session bindings, consent and bounded retention. Disconnecting RI or the binder must leave the live Console WS, C1 numeric path and Somatic controls unaffected. Rollback: disable the RI export and this opt-in consumer; no device restart or reconfiguration should be needed. No PR merge or robot installation is authorized here.

## Return handoff — COG → RI and Console owners

**Decision:** pin the existing RI `consumer-observation-ref.v0.1-candidate` and Console `console.imu.v0.1-candidate` independently; add a COG-only *reference-to-normalized-bytes* verifier, never a new physical publisher. Verified local hash = stored content equality, **not** source authentication. RI copy format is an explicitly proposed candidate, not a currently deployed wire contract.

**Required RI/Console owner response:** (1) confirm the one existing WIT/CH340/Console publisher and safe fan-out point; (2) approve or correct deterministic stored sample encoding and actual source/session/boot metadata; (3) specify authenticated local publisher-to-RI delivery, consent, throttling/backpressure and retention; (4) verify same-boot clock mapping or keep alignment unknown; (5) decide whether a future consumer will receive just a reference or both reference and authorized sample bytes, with ACL enforcement; (6) provide real authorized producer/consumer E2E tests and rollback criteria. No change to existing source IDs, schemas or acquisition is implied.

**PR:** `OpenRGD/rgd-cognition` COG–RI–02 (draft), stacked on [COG PR #8](https://github.com/OpenRGD/rgd-cognition/pull/8). **Open:** owner review, real authenticated fan-out, host performance/consent/retention, real hardware qualification. No Chronon, Voice/Visual output, motion or Life authority is implemented.
