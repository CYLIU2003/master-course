from scripts.build_thesis_experiment_matrix import build_experiment_matrix


def test_experiment_matrix_uses_only_frontend_bff_execution_contract() -> None:
    payload = build_experiment_matrix()

    assert payload["execution_semantics"] == "frontend_bff_only_no_direct_solver"
    assert all(
        "prepare-simulation" in case["execution_path"]
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
        if row["case_id"].startswith("B0_")
    )
    assert baseline["reporting_eligible"] is False
