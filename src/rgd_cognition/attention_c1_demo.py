"""Explicitly synthetic Console-shaped samples; never a real sensor recording."""
from __future__ import annotations

import argparse
import json
from .attention_c1 import AttentionPolicy, SourceBinding


class FixtureClock:
    def __init__(self):
        self.value = 1000000000

    def __call__(self):
        return self.value

    def advance(self, milliseconds):
        self.value += milliseconds * 1000000


def fixture_binding(mode="SYNTHETIC_REPLAY"):
    return SourceBinding("lab-robot", "fixture-console-robot", "fixture-publisher",
                         "fixture-imu", "fixture-sensor", "a" * 32, mode)


def fixture_sample(index=0, rate=0.0):
    return {
        "schema_version": "console.imu.v0.1-candidate", "robot_id": "fixture-console-robot",
        "sensor_id": "fixture-imu", "source_id": "fixture-publisher", "sensor_frame_id": "fixture-sensor",
        "session_id": "a" * 32, "sequence": index, "host_monotonic_ns": 1000000000 + index * 100000000,
        "host_receive_utc": "2026-10-31T00:00:00Z", "console_received_at": "2026-10-31T00:00:00Z",
        "source_kind": "physical",  # upstream shape; fixture origin is overridden by trusted binding
        "acceleration_m_s2": [0.0, 0.0, 9.81], "angular_velocity_rad_s": [rate, 0.0, 0.0],
        "orientation_euler_deg": [0.0, 0.0, 0.0], "temperature_c": None, "calibration_revision": None,
        "reference_frame": "imu_sensor_axes_unverified", "time_quality": "host_receive_only_not_chronograph",
        "heading_calibrated": False, "decision_eligible": False, "observation_only": True,
        "motion_hint": "rotation_observed" if abs(rate) >= 0.05 else "low_angular_rate",
    }


def run_demo(count=12):
    from .attention_c1_bridge import AttentionAgenda
    from .context import context_slice
    if type(count) is not int or not 6 <= count <= 10000:
        raise ValueError("INVALID_DEMO_COUNT")
    clock = FixtureClock()
    host = AttentionAgenda(context_supplier=lambda: context_slice("lab-robot"), binding=fixture_binding(),
                           policy=AttentionPolicy(cooldown_ms=100), clock=clock, resource_state="NORMAL")
    results = []
    for index in range(count):
        clock.advance(100)
        result = host.ingest(fixture_sample(index, 0.6 if (index // 3) % 2 else 0.0),
                             received_ns=clock(), freshness="FRESH", consent=True)
        if result["proposal"] is not None:
            goal = host.work.start_next()
            if goal is None:
                raise RuntimeError("DEMO_ADMISSION_FAILED")
            outcome = host.work.run_step(goal["candidate"]["candidate_id"],
                evidence_refs=goal["candidate"]["evidence_refs"][:1], result_code="ANALYSIS_COMPLETE")
            results.append({"reason": result["attention"]["reason_code"], "state": outcome["state"],
                            "origin": result["attention"]["cue"]["origin"]})
    report = {"fixture_only": True, "manual_cue_kind_supplied": False, "samples": count,
              "generated_goals": results, "attention": host.attention.stats(),
              "life_id": None, "chronon_status": "NOT_CONNECTED", "external_effects": False}
    host.close()
    return report


def main():
    parser = argparse.ArgumentParser(description="Synthetic C1 attention/goal-generation replay")
    parser.add_argument("--events", type=int, default=12)
    args = parser.parse_args()
    print(json.dumps(run_demo(args.events), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
