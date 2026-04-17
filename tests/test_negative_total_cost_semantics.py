from __future__ import annotations

from types import SimpleNamespace

from bff.routers.optimization import _canonical_cost_breakdown_json, _cost_breakdown
from bff.services.experiment_reports import _optimization_result_payload


def test_cost_breakdown_prefers_accounting_total_cost_over_objective_value() -> None:
    payload = _cost_breakdown(
        {
            "objective_value": -49718.03699606294,
            "obj_breakdown": {
                "total_cost": 61781.96300393706,
                "return_leg_bonus": 111500.0,
            },
        },
        None,
    )

    assert payload["total_cost"] == 61781.96300393706
    assert payload["return_leg_bonus"] == 111500.0


def test_canonical_cost_breakdown_json_keeps_bonus_separate_from_total_cost() -> None:
    engine_result = SimpleNamespace(
        cost_breakdown={
            "total_cost": 61781.96300393706,
            "energy_cost": 61781.96300393706,
            "vehicle_cost": 1234.0,
            "driver_cost": 0.0,
            "return_leg_bonus": 111500.0,
        },
        objective_value=-49718.03699606294,
        solver_metadata={"objective_mode": "total_cost"},
        mode=SimpleNamespace(value="milp"),
    )
    problem = SimpleNamespace(
        scenario=SimpleNamespace(objective_mode="total_cost"),
        depot_energy_assets={},
    )

    payload = _canonical_cost_breakdown_json(
        problem=problem,
        engine_result=engine_result,
        scenario_id="scenario-1",
    )

    assert payload["total_cost"] == 61781.96300393706
    assert payload["components"]["vehicle_fixed_cost"] == 1234.0
    assert payload["components"]["return_leg_bonus"] == 111500.0


def test_experiment_report_payload_exposes_return_leg_bonus_and_demand_charge() -> None:
    payload = _optimization_result_payload(
        {
            "solver_status": "BASELINE_FALLBACK",
            "objective_value": -49718.03699606294,
            "summary": {},
            "simulation_summary": {},
            "cost_breakdown": {
                "total_cost": 61781.96300393706,
                "return_leg_bonus": 111500.0,
                "demand_charge": 4321.0,
            },
        }
    )

    assert payload["objective_value"] == -49718.03699606294
    assert payload["total_cost_jpy"] == 61781.96300393706
    assert payload["return_leg_bonus_jpy"] == 111500.0
    assert payload["demand_charge_jpy"] == 4321.0
