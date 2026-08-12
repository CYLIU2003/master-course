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
        if row["case_id"].startswith("M0_")
    )
    assert baseline["candidate_generation_available"] is True
    assert baseline["reporting_eligible"] is False


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
