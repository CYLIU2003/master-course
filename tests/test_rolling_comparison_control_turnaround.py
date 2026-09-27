from __future__ import annotations

from types import SimpleNamespace

from bff.services.optimization_run.rolling_chain import (
    _comparison_case_manifest,
)


def _manifest(*, turnaround_buffer_min: int, controls: dict | None = None) -> dict:
    problem = SimpleNamespace(
        depot_energy_assets={},
        price_slots=(),
        metadata={
            "fixed_route_band_mode": False,
            "default_turnaround_min": 10,
            "turnaround_buffer_min": turnaround_buffer_min,
            "turnaround_time_semantics": (
                "base_turnaround_plus_operational_buffer_before_deadhead"
            ),
        },
    )
    return _comparison_case_manifest(
        scenario={"simulation_config": {}},
        problem=problem,
        input_audit={"service_id": "WEEKDAY"},
        chain={"service_date": "2025-08-05", **(controls or {})},
        physical_validation={},
        executed_day={"cost_breakdown": {}},
        optimization_result={"solver_settings": {}},
    )


def test_comparison_control_hash_includes_turnaround_and_route_band_semantics() -> None:
    zero_buffer = _manifest(turnaround_buffer_min=0)
    fifteen_minute_buffer = _manifest(turnaround_buffer_min=15)

    payload = fifteen_minute_buffer["comparison_control_payload"]
    assert payload["fixed_route_band_mode"] is False
    assert payload["default_turnaround_min"] == 10
    assert payload["turnaround_buffer_min"] == 15
    assert payload["turnaround_time_semantics"] == (
        "base_turnaround_plus_operational_buffer_before_deadhead"
    )
    assert zero_buffer["comparison_control_hash"] != (
        fifteen_minute_buffer["comparison_control_hash"]
    )


def test_search_and_start_policies_change_comparison_hash_not_runtime():
    controls = {"charging_search_requested": "feasibility_first", "stage2_charging_start_policy": "none"}
    baseline = _manifest(turnaround_buffer_min=0, controls=controls)
    for changed in ({"charging_search_requested": "bound_first"},
                    {"stage2_charging_start_policy": "fixed_assignment_binary"}):
        other = _manifest(turnaround_buffer_min=0, controls={**controls, **changed})
        assert other["comparison_control_hash"] != baseline["comparison_control_hash"]
    telemetry = _manifest(turnaround_buffer_min=0, controls={**controls, "runtime_seconds": 900})
    assert telemetry["comparison_control_hash"] == baseline["comparison_control_hash"]
    legacy = _manifest(turnaround_buffer_min=0)
    assert legacy["comparison_control_payload"]["rolling_solver_controls"]["charging_search_requested"] is None
    assert legacy["comparison_control_hash"] != baseline["comparison_control_hash"]
