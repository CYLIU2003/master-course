from __future__ import annotations

from types import SimpleNamespace

from bff.services.optimization_run.rolling_chain import (
    _comparison_case_manifest,
)


def _manifest(*, turnaround_buffer_min: int) -> dict:
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
        chain={"service_date": "2025-08-05"},
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
