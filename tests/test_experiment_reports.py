from __future__ import annotations


def _make_scenario_doc(
    *,
    depot_id: str = "meguro",
    route_ids: list[str] | None = None,
    overlay_mode: str = "mode_milp_only",
    objective_mode: str = "total_cost",
    experiment_method: str | None = None,
    experiment_notes: str | None = None,
    random_seed: int | None = 42,
) -> dict:
    return {
        "meta": {"randomSeed": random_seed},
        "dispatch_scope": {
            "depotSelection": {"primaryDepotId": depot_id},
            "depotId": depot_id,
        },
        "routes": [{"id": route_id, "name": route_id} for route_id in (route_ids or ["route-A", "route-B"])],
        "vehicle_templates": [
            {"id": "tmpl-bev", "name": "BEV Bus", "type": "BEV"},
            {"id": "tmpl-ice", "name": "ICE Bus", "type": "ICE"},
        ],
        "scenario_overlay": {
            "depot_ids": [depot_id],
            "route_ids": route_ids or ["route-A", "route-B"],
            "cost_coefficients": {
                "grid_flat_price_per_kwh": 20.0,
                "grid_sell_price_per_kwh": 10.0,
                "demand_charge_cost_per_kw": 1200.0,
                "diesel_price_per_l": 155.0,
                "grid_co2_kg_per_kwh": 0.432,
                "co2_price_per_kg": 5.0,
                "pv_enabled": False,
                "pv_scale": 0.0,
                "tou_pricing": [
                    {"start_hour": 0, "end_hour": 8, "price_per_kwh": 15.0},
                    {"start_hour": 8, "end_hour": 20, "price_per_kwh": 25.0},
                ],
            },
            "charging_constraints": {"depot_power_limit_kw": 200.0},
            "solver_config": {
                "mode": overlay_mode,
                "objective_mode": objective_mode,
                "time_limit_seconds": 300,
                "mip_gap": 0.01,
                "alns_iterations": 1000,
                "allow_partial_service": False,
                "unserved_penalty": 10000.0,
                "objective_weights": {},
            },
        },
        "simulation_config": {
            "solver_mode": overlay_mode,
            "objective_mode": objective_mode,
            "fleet_templates": [
                {"vehicle_template_id": "tmpl-bev", "vehicle_count": 5, "initial_soc": 0.8},
                {"vehicle_template_id": "tmpl-ice", "vehicle_count": 3, "initial_soc": None},
            ],
            "experiment_method": experiment_method,
            "experiment_notes": experiment_notes,
        },
    }


def _make_simulation_result() -> dict:
    return {
        "scenario_id": "test-scenario",
        "scope": {"depotId": "meguro", "serviceId": "WEEKDAY"},
        "total_energy_kwh": 120.5,
        "total_distance_km": 800.0,
        "feasibility_violations": [],
        "summary": {
            "trip_count_served": 220,
            "trip_count_by_type": {"BEV": 120, "ICE": 100},
        },
        "simulation_summary": {
            "total_operating_cost": 18500.0,
            "total_energy_cost": 1200.0,
            "total_fuel_cost": 16000.0,
            "total_demand_charge": 300.0,
            "total_co2_kg": 250.0,
            "total_grid_kwh": 60.0,
            "peak_demand_kw": 45.0,
            "feasibility_report": {"feasible": True},
        },
    }


def _make_optimization_result(mode: str = "mode_milp_only") -> dict:
    return {
        "mode": mode,
        "objective_mode": "total_cost",
        "solver_status": "OPTIMAL",
        "objective_value": 18000.0,
        "solve_time_seconds": 42.0,
        "mip_gap": 0.0,
        "cost_breakdown": {
            "total_cost": 18000.0,
            "energy_cost": 1100.0,
            "fuel_cost": 15500.0,
            "peak_demand_cost": 400.0,
            "vehicle_cost": 1000.0,
            "total_co2_kg": 240.0,
        },
        "summary": {
            "trip_count_served": 220,
            "trip_count_by_type": {"BEV": 120, "ICE": 100},
        },
    }


def test_log_simulation_experiment_returns_required_keys(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from bff.services.experiment_reports import log_simulation_experiment

    payload = log_simulation_experiment(
        scenario_id="test-sc-001",
        scenario_doc=_make_scenario_doc(),
        simulation_result=_make_simulation_result(),
    )

    assert payload["report_type"] == "simulation"
    assert payload["scenario_id"] == "test-sc-001"
    assert payload["method"] == "MILP"
    assert payload["fleet_templates"]
    assert payload["report"]["results"]["bev_trips"] == 120
    assert payload["report"]["results"]["ice_trips"] == 100


def test_log_optimization_experiment_hybrid_label(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from bff.services.experiment_reports import log_optimization_experiment

    payload = log_optimization_experiment(
        scenario_id="test-sc-opt",
        scenario_doc=_make_scenario_doc(overlay_mode="mode_alns_milp"),
        optimization_result=_make_optimization_result(mode="mode_alns_milp"),
    )

    assert payload["report_type"] == "optimization"
    assert payload["method"] == "MILP+ALNS"


def test_explicit_experiment_method_overrides_mode(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from bff.services.experiment_reports import log_simulation_experiment

    payload = log_simulation_experiment(
        scenario_id="test-sc",
        scenario_doc=_make_scenario_doc(experiment_method="GA"),
        simulation_result=_make_simulation_result(),
    )

    assert payload["method"] == "GA"


def test_simulation_profile_cli_parser_has_subcommands():
    import importlib

    cli = importlib.import_module("scripts.simulation_profile_cli")
    parser = cli._build_parser()
    export_args = parser.parse_args(["export", "--scenario", "test-id"])
    apply_args = parser.parse_args(["apply", "--scenario", "test-id", "--input", "some.json"])
    show_args = parser.parse_args(["show", "--scenario", "test-id"])

    assert export_args.command == "export"
    assert apply_args.command == "apply"
    assert show_args.command == "show"
