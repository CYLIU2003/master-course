from __future__ import annotations

import json
from pathlib import Path

import scripts.run_pure_ice_aggregation_weather_ab as weather_ab
from scripts.run_pure_ice_aggregation_weather_ab import (
    REQUIRED_FIXED_HASHES,
    RAIN_SCENARIO_ID,
    SUNNY_SCENARIO_ID,
    ScenarioInput,
    _validate_prepare_request,
    _validate_child_fleet_contract,
    _validate_request_controls,
    _write_child_failure,
    _remove_weather_linked_fields,
    build_prepared_input_contract,
    build_cross_scenario_comparison,
    build_cross_scenario_input_contract,
    build_interleaved_case_schedule,
)


def _prepare_request(*, role: str, weather_date: str, fixed_weekday: bool) -> dict:
    return {
        "selected_depot_ids": ["tsurumaki"],
        "selected_route_ids": [f"route-{index}" for index in range(16)],
        "day_type": "WEEKDAY",
        "service_date": "2025-08-05",
        "service_dates": ["2025-08-05"],
        "include_short_turn": True,
        "include_depot_moves": True,
        "include_deadhead": True,
        "allow_intra_depot_route_swap": False,
        "allow_inter_depot_swap": False,
        "simulation_settings": {
            "time_step_min": 15,
            "timestep_min": 15,
            "use_selected_depot_vehicle_inventory": True,
            "use_selected_depot_charger_inventory": True,
            "allow_partial_service": False,
            "fixed_route_band_mode": True,
            "enable_weather_operation_policy": False,
            "random_seed": 42,
            "objective_mode": "total_cost",
            "mip_gap": 0.1,
            "planning_days": 1,
            "planning_horizon_hours": 24.0,
            "objective_preset": "scalar_total_cost_v1",
            "vehicle_usage_cost_jpy_per_used_bus": 20000.0,
            "vehicle_usage_cost_semantics": "fixed_vehicle_day_cost",
            "diesel_price_per_l": 150.0,
            "counterfactual_pv_source_date": weather_date,
            "comparison_role": role,
            "allow_fixed_weekday_timetable_pv_counterfactual": fixed_weekday,
        },
    }


def _case(*, scenario: str, representation: str) -> dict:
    hashes = {key: f"fixed-{key}" for key in REQUIRED_FIXED_HASHES}
    hashes.update(
        {
            "pv_profile_sha256": f"pv-{scenario}",
            "pv_hash": f"pv-{scenario}",
            "trip_input_sha256": f"trip-{scenario}",
            "prepared_source_sha256": f"prepared-{scenario}",
        }
    )
    return {
        "representation": representation,
        "metrics": {
            "provenance": {"input_hashes": hashes},
            "solve_outcome": {
                "incumbent_objective_jpy": 100.0,
                "certified_best_bound_jpy": 90.0,
                "certified_gap_ratio": 0.1,
            },
            "timing": {"total_solver_time_sec": 10.0},
            "operational_outcomes": {
                "bev_trip_count": 40,
                "ice_trip_count": 224,
                "used_bev_vehicle_count": 15,
                "used_ice_vehicle_count": 17,
                "total_cost_jpy": 1000.0,
                "fuel_liters": 400.0,
                "grid_import_kwh": 10.0,
                "pv_to_bus_kwh": 20.0,
                "pv_to_bess_kwh": 30.0,
                "bess_to_bus_kwh": 25.0,
                "pv_curtail_kwh": 5.0,
                "peak_grid_kw": 2.0,
                "minimum_bev_soc_kwh": 50.0,
                "terminal_bev_soc_kwh_total": 3000.0,
                "terminal_bess_soc_kwh_total": 3000.0,
            },
        },
    }


def test_interleaved_schedule_keeps_complete_pairs_together() -> None:
    schedule = build_interleaved_case_schedule()

    assert len(schedule) == 20
    assert [item["scenario"] for item in schedule[:4]] == [
        "SUNNY",
        "SUNNY",
        "RAIN",
        "RAIN",
    ]
    assert [item["pair_order"] for item in schedule[0::4]] == [
        "AB",
        "BA",
        "AB",
        "BA",
        "AB",
    ]


def test_cross_scenario_contract_allows_only_weather_linked_hash_changes() -> None:
    scenario_runs = {
        "SUNNY": [
            _case(scenario="sunny", representation="discrete"),
            _case(scenario="sunny", representation="pure_aggregate"),
        ],
        "RAIN": [
            _case(scenario="rain", representation="discrete"),
            _case(scenario="rain", representation="pure_aggregate"),
        ],
    }

    contract = build_cross_scenario_input_contract(scenario_runs)
    comparison = build_cross_scenario_comparison(
        scenario_runs=scenario_runs,
        input_contract=contract,
    )

    assert contract["all_fixed_controls_match"] is True
    assert contract["pv_profile_hashes_differ"] is True
    assert set(contract["weather_linked_hash_differences"]) >= {
        "pv_profile_sha256",
        "pv_hash",
        "trip_input_sha256",
    }
    assert len(comparison["rows"]) == 38


def test_prepared_contract_rejects_a_non_weather_charger_difference() -> None:
    common = {
        "route_ids_sha256": "routes",
        "trip_ids_sha256": "trip-ids",
        "trip_structure_without_weather_energy_sha256": "trip-structure",
        "vehicles_sha256": "vehicles",
        "chargers_sha256": "chargers",
        "depots_sha256": "depots",
        "simulation_config_without_weather_sha256": "simulation",
        "scenario_overlay_without_weather_sha256": "overlay",
    }
    contract = build_prepared_input_contract(
        {
            "SUNNY": common,
            "RAIN": {**common, "chargers_sha256": "different-chargers"},
        }
    )

    assert contract["all_fixed_prepared_content_matches"] is False
    assert contract["fixed_prepared_content_checks"]["chargers_sha256"] is False


def test_fresh_prepare_request_preserves_rain_weekday_counterfactual() -> None:
    payload = _prepare_request(
        role="pv_curve_counterfactual",
        weather_date="2025-08-10",
        fixed_weekday=True,
    )

    _validate_prepare_request(payload, code_name="RAIN")


def test_fresh_prepare_request_rejects_a_sunday_service_change() -> None:
    payload = _prepare_request(
        role="pv_curve_counterfactual",
        weather_date="2025-08-10",
        fixed_weekday=True,
    )
    payload["day_type"] = "SUN_HOL"

    try:
        _validate_prepare_request(payload, code_name="RAIN")
    except ValueError as exc:
        assert "day_type" in str(exc)
    else:
        raise AssertionError("SUN_HOL must be rejected")


def test_versioned_prepare_templates_satisfy_the_protocol() -> None:
    root = Path(__file__).resolve().parents[1]
    templates = root / "config" / "research" / "pure_ice_weather_ab"

    _validate_prepare_request(
        json.loads((templates / "sunny_prepare_request.json").read_text()),
        code_name="SUNNY",
    )
    _validate_prepare_request(
        json.loads((templates / "rain_prepare_request.json").read_text()),
        code_name="RAIN",
    )


def test_child_fleet_contract_must_match_the_prepared_fleet(tmp_path: Path) -> None:
    source_run = tmp_path / "source-run"
    source_run.mkdir()
    contract = {
        "schema_version": "scenario_fleet_contract_v2",
        "validation_status": "OK",
        "fleet_contract_hash": "fleet",
        "active_vehicle_id_hash": "vehicle-ids",
        "initial_state_hash": "initial-state",
        "vehicle_parameter_hash": "parameters",
    }
    (source_run / "scenario_fleet_contract.json").write_text(
        json.dumps(contract), encoding="utf-8"
    )

    audit = _validate_child_fleet_contract(
        child={"run_dir": str(source_run)},
        expected_descriptor={
            "fleet_contract_hash": "fleet",
            "fleet_active_vehicle_id_hash": "vehicle-ids",
            "fleet_initial_state_hash": "initial-state",
            "fleet_vehicle_parameter_hash": "parameters",
        },
        run_directory=tmp_path / "child",
    )

    assert audit["accepted"] is True
    assert (tmp_path / "child" / "fleet_contract_validation.json").is_file()


def test_prepared_contract_does_not_hide_a_pv_cost_control_change() -> None:
    stripped = _remove_weather_linked_fields(
        {
            "pv_generation_kwh_by_slot": [1.0, 2.0],
            "pv_marginal_charge_cost_yen_per_kwh": 99.0,
        }
    )

    assert "pv_generation_kwh_by_slot" not in stripped
    assert stripped["pv_marginal_charge_cost_yen_per_kwh"] == 99.0


def test_zero_composition_radius_is_an_explicit_frozen_control() -> None:
    request = {
        "mode": "phase3_two_stage",
        "service_id": "WEEKDAY",
        "depot_id": "tsurumaki",
        "time_step_min": 15,
        "timestep_min": 15,
        "run_profile": "day_ahead_and_hourly_rolling",
        "run_hourly_rolling": True,
        "rolling_execution_minutes": 60,
        "gurobi_threads": 1,
        "stage1_best_obj_stop_enabled": False,
        "stage1_powertrain_selector_strengthening": False,
        "research_run": True,
        "rebuild_dispatch": False,
        "force_reprepare": False,
        "use_existing_duties": False,
        "stage1_stage2_candidate_limit": 1,
        "stage1_composition_search_radius": 0,
    }

    _validate_request_controls(request, "SUNNY")


def test_failed_child_is_persisted_as_a_correctness_failure(tmp_path: Path) -> None:
    payload = _write_child_failure(
        run_directory=tmp_path,
        representation="pure_aggregate",
        error=RuntimeError("day-ahead result is not feasible"),
    )

    assert payload["status"] == "FAIL_CORRECTNESS"
    assert payload["representation"] == "pure_aggregate"
    assert json.loads((tmp_path / "child_failure.json").read_text()) == payload


def test_child_runtime_error_finalizes_the_parent_as_fail_correctness(
    tmp_path: Path, monkeypatch
) -> None:
    common_descriptor = {
        "prepared_source_sha256": "prepared-source",
        "route_ids_sha256": "routes",
        "trip_ids_sha256": "trips",
        "trip_structure_without_weather_energy_sha256": "trip-structure",
        "vehicles_sha256": "vehicles",
        "fleet_contract_hash": "fleet-contract",
        "fleet_active_vehicle_id_hash": "fleet-vehicles",
        "fleet_initial_state_hash": "fleet-initial-state",
        "fleet_vehicle_parameter_hash": "fleet-parameters",
        "chargers_sha256": "chargers",
        "depots_sha256": "depots",
        "simulation_config_without_weather_sha256": "simulation",
        "scenario_overlay_without_weather_sha256": "overlay",
        "weather_and_counterfactual_fields": {},
    }

    monkeypatch.setattr(weather_ab, "_assert_clean_frozen_sha", lambda *_: "frozen-sha")
    monkeypatch.setattr(
        weather_ab, "_prepared_descriptor", lambda _: dict(common_descriptor)
    )
    monkeypatch.setattr(
        weather_ab,
        "_normalized_request",
        lambda scenario, **_: ({"prepared_input_id": scenario.prepared_input_id}, {}),
    )
    monkeypatch.setattr(weather_ab, "_load_completed_case_runs", lambda **_: {})

    def _raise_child_error(**_):
        raise RuntimeError("day-ahead result is not feasible")

    monkeypatch.setattr(weather_ab, "_run_pure_ice_case_in_child_process", _raise_child_error)
    output_dir = tmp_path / "weather-ab"
    result = weather_ab.run_weather_ab(
        sunny=ScenarioInput("SUNNY", SUNNY_SCENARIO_ID, "sunny-prepared", tmp_path / "sunny.json"),
        rain=ScenarioInput("RAIN", RAIN_SCENARIO_ID, "rain-prepared", tmp_path / "rain.json"),
        output_dir=output_dir,
        stage1_time_limit_seconds=435,
        stage2_time_limit_seconds=30,
        small_exact_parity_passed=True,
    )

    assert result["status"] == "FAIL_CORRECTNESS"
    assert result["reason"] == "child_failure_SUNNY_run_01"
    assert result["completed_case_counts"] == {"SUNNY": 0, "RAIN": 0}
    assert json.loads((output_dir / "weather_ab_result.json").read_text())["status"] == "FAIL_CORRECTNESS"
    assert json.loads(
        (output_dir / "scenarios" / "SUNNY" / "runs" / "01_A_discrete" / "child_failure.json").read_text()
    )["error_type"] == "RuntimeError"
