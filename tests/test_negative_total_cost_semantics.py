from __future__ import annotations

from types import SimpleNamespace

from bff.routers.optimization import _canonical_cost_breakdown_json, _cost_breakdown
from bff.services.experiment_reports import _logger_scenario_payload, _optimization_result_payload


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


def test_experiment_report_uses_accounting_total_and_percent_gap() -> None:
    payload = _optimization_result_payload(
        {
            "solver_status": "feasible",
            "objective_value": 721_657.93,
            "mip_gap": 0.410807,
            "solver_settings": {"mip_gap_achieved_percent": 41.0807},
            "summary": {"trip_count_served": 264},
            "cost_breakdown": {"total_cost": 721_657.93},
            "graph_artifacts": {
                "accounting_summary": {
                    "accounting_total_cost_jpy": 716_926.89,
                    "grid_purchase_cost_jpy": 21_476.40,
                    "bess_total_flow_cost_jpy": 123.45,
                    "energy_cost_jpy": 21_599.85,
                    "fuel_cost_jpy": 48_406.31,
                    "demand_charge_cost_jpy": 5_619.53,
                    "vehicle_usage_cost_jpy": 640_000.0,
                    "total_co2_kg": 1_424.66,
                    "bev_trip_count": 127,
                    "ice_trip_count": 137,
                    "served_trip_count": 264,
                    "unserved_trip_count": 0,
                }
            },
        }
    )

    assert payload["status"] == "FEASIBLE"
    assert payload["objective_value"] == 721_657.93
    assert payload["total_cost_jpy"] == 716_926.89
    assert payload["electricity_cost_jpy"] == 21_599.85
    assert payload["demand_charge_jpy"] == 5_619.53
    assert payload["mip_gap_pct"] == 41.0807
    assert payload["bev_trips"] == 127
    assert payload["ice_trips"] == 137
    assert payload["trip_count_unserved"] == 0


def test_logger_scenario_payload_uses_vehicle_and_depot_asset_fallbacks() -> None:
    payload = _logger_scenario_payload(
        scenario_doc={
            "dispatch_scope": {"depotSelection": {"primaryDepotId": "dep1"}},
            "simulation_config": {
                "fleet_templates": [],
                "depot_energy_assets": [
                    {"depot_id": "dep1", "derived_pv_capacity_kw": 12.5},
                    {"depot_id": "dep2", "pv_capacity_kw": 7.5},
                ],
            },
            "vehicles": [
                {"id": "bev-1", "type": "BEV"},
                {"id": "bev-2", "type": "BEV"},
                {"id": "ice-1", "type": "ICE"},
            ],
            "routes": [{"id": "route-1"}],
        },
        objective="total_cost",
        method="MILP",
        mode="mode_milp_only",
    )

    fleet_counts = {item["vehicle_type"]: item["count"] for item in payload["fleet"]}
    assert fleet_counts == {"BEV": 2, "ICE": 1}
    assert payload["pv"]["capacity_kw"] == 20.0


def test_logger_scenario_payload_converts_gap_and_hashes_effective_date() -> None:
    payload = _logger_scenario_payload(
        scenario_doc={
            "dispatch_scope": {"depotId": "dep1"},
            "simulation_config": {
                "service_date": "2025-08-10",
                "vehicle_usage_cost_jpy_per_used_bus": 20_000,
                "depot_energy_assets": [{"depot_id": "dep1", "pv_capacity_kw": 10.0}],
            },
            "scenario_overlay": {"solver_config": {"mip_gap": 0.1}},
        },
        objective="total_cost",
        method="二段階MILP",
        mode="milp",
    )

    assert payload["solver"]["mip_gap_pct"] == 10.0
    assert payload["costs"]["vehicle_fixed_cost"] == 20_000
    assert payload["service_date"] == "2025-08-10"


def test_logger_scenario_payload_preserves_explicit_zero_vehicle_usage_cost() -> None:
    payload = _logger_scenario_payload(
        scenario_doc={
            "simulation_config": {"vehicle_usage_cost_jpy_per_used_bus": 0.0},
            "scenario_overlay": {
                "solver_config": {
                    "objective_weights": {"vehicle_fixed_cost": 99_999.0}
                }
            },
        },
        objective="total_cost",
        method="MILP",
        mode="milp",
    )

    assert payload["costs"]["vehicle_fixed_cost"] == 0.0
