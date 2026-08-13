from scripts.build_thesis_experiment_matrix import build_experiment_matrix


def test_experiment_matrix_uses_only_frontend_bff_execution_contract() -> None:
    payload = build_experiment_matrix()

    assert payload["execution_semantics"] == "frontend_bff_only_no_direct_solver"
    assert all(
        "/simulation/prepare" in case["execution_path"]
        and "run-optimization" in case["execution_path"]
        for case in payload["cases"]
    )
    assert all(case["research_run_required"] is True for case in payload["cases"])


def test_experiment_matrix_contains_required_sensitivities() -> None:
    payload = build_experiment_matrix()
    families = {case["family"] for case in payload["cases"]}

    assert {
        "time_discretization",
        "trip_energy_sensitivity",
        "pv_supply_transition",
        "route_band_ablation",
        "vehicle_day_cost_sensitivity",
        "cost_co2_epsilon_frontier",
    } <= families
    baseline = next(
        row
        for row in payload["ablation_contract"]
        if row["case_id"].startswith("M0_")
    )
    assert baseline["candidate_generation_available"] is True
    assert baseline["reporting_eligible"] is False

    pv_cases = [
        case
        for case in payload["cases"]
        if case["family"] == "pv_supply_transition"
    ]
    assert [case["prepare_settings"]["pv_scale"] for case in pv_cases] == [
        0.0,
        0.25,
        0.5,
        0.75,
        1.0,
    ]

    route_band_cases = {
        case["case_id"]: case
        for case in payload["cases"]
        if case["family"] == "route_band_ablation"
    }
    assert route_band_cases["ROUTE_BAND_ON"][
        "prepare_request_overrides"
    ] == {"allow_intra_depot_route_swap": False}
    assert route_band_cases["ROUTE_BAND_OFF"][
        "prepare_request_overrides"
    ] == {"allow_intra_depot_route_swap": True}
    assert payload["parameter_semantics"]["pv_scale"].startswith(
        "Multiplicative alpha"
    )
    time_15 = next(
        case for case in payload["cases"] if case["case_id"] == "TIME_15"
    )
    assert time_15["optimization_request_overrides"] == {
        "mode": "phase4_integrated",
        "research_run": True,
        "integrated_actual_cost_objective": True,
        "stage1_best_obj_stop_enabled": False,
        "run_profile": "day_ahead_and_hourly_rolling",
        "run_hourly_rolling": True,
        "time_step_min": 15,
        "timestep_min": 15,
        "rolling_execution_minutes": 60,
    }
    assert payload["parameter_semantics"]["time_discretization"].startswith(
        "Varies the internal"
    )
    co2_cap = next(
        case for case in payload["cases"] if case["case_id"] == "CO2_CAP_500"
    )
    assert co2_cap["optimization_request_overrides"][
        "co2_emissions_cap_kg"
    ] == 500.0
    vehicle_day_cases = [
        case
        for case in payload["cases"]
        if case["family"] == "vehicle_day_cost_sensitivity"
    ]
    assert all(
        case["prepare_settings"]["objective_preset"]
        == "scalar_total_cost_v1"
        for case in vehicle_day_cases
    )
    assert all(
        case["prepare_settings"]["vehicle_usage_cost_semantics"]
        == "fixed_vehicle_day_cost"
        for case in vehicle_day_cases
    )


def test_experiment_matrix_separates_method_and_component_ablations() -> None:
    payload = build_experiment_matrix()

    method_rows = {
        row["case_id"]: row for row in payload["ablation_contract"]
    }
    assert set(method_rows) == {
        "M0_rule_based_dispatch_arrival_charge",
        "M1_fixed_dispatch_optimized_energy",
        "M2_optimized_dispatch_simple_charge",
        "M3_integrated_dispatch_energy_bess",
    }
    assert (
        method_rows["M0_rule_based_dispatch_arrival_charge"]["reporting_eligible"]
        is False
    )
    assert (
        method_rows["M2_optimized_dispatch_simple_charge"]["reporting_eligible"]
        is False
    )
    assert (
        method_rows["M1_fixed_dispatch_optimized_energy"]["reporting_eligible"]
        is False
    )
    assert (
        method_rows["M3_integrated_dispatch_energy_bess"]["reporting_eligible"]
        is False
    )
    assert (
        method_rows["M1_fixed_dispatch_optimized_energy"]["implementation_status"]
        == "EXPLICIT_PHASE1_FRONTEND_RUN_AVAILABLE"
    )
    assert (
        method_rows["M1_fixed_dispatch_optimized_energy"][
            "candidate_generation_available"
        ]
        is True
    )
    assert (
        "thesis_ablation/day_ahead_method_candidates.json"
        in payload["required_outputs"]
    )
    assert (
        "thesis_ablation_comparison/day_ahead_method_comparison.json"
        in payload["required_outputs"]
    )
    assert len(payload["component_ablation_contract"]) == 3
