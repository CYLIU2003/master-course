from __future__ import annotations

import json
from pathlib import Path

from scripts.build_lazy_fragment_performance_diagnostic import (
    build_comparison,
    build_pure_ice_ab_comparison,
    write_comparison_outputs,
    write_pure_ice_ab_outputs,
)


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_run(
    root: Path,
    *,
    constraints: int,
    pairwise_rows: int,
    time_limit: int,
    solve_time: float,
    research_run: bool,
    vehicle_hash: str,
    lazy: bool,
) -> None:
    root.mkdir()
    separator = (
        {
            "integer_feasible_set_preserved": True,
            "mipsol_callback_count": 1,
            "lazy_constraint_count": 0,
            "lazy_constraint_submission_count": 0,
            "callback_error": None,
        }
        if lazy
        else {}
    )
    _write_json(
        root / "canonical_solver_result.json",
        {
            "solver_status": "time_limit",
            "objective_value": 650_234.0,
            "trip_count_served": 264,
            "trip_count_unserved": 0,
            "metadata": {
                "objective_preset": "research_lexicographic_v1",
                "integrated_fragment_pairwise_constraint_count": pairwise_rows,
                "integrated_fragment_pairwise_constraint_mode": (
                    "lazy_integer_incumbent_separation" if lazy else None
                ),
                "integrated_fragment_transition_lazy_separator": separator,
                "integrated_fragment_occupancy_constraint_count": 24_600,
                "integrated_overlap_clique_constraint_count": 9_420,
            },
            "solver_metadata": {
                "termination_reason": "time_limit",
                "dispatch_fixed_recourse_model_variable_count": 780_112,
                "dispatch_fixed_recourse_model_constraint_count": constraints,
            },
        },
    )
    _write_json(
        root / "solver_settings.json",
        {
            "research_run": research_run,
            "runtime_comparison_eligible": False,
            "runtime_comparison_eligibility_reason": "single run",
            "time_limit_seconds_effective": time_limit,
            "solve_time_sec": solve_time,
            "phase4_phase3_seed_wall_runtime_sec": 100.0,
            "mip_gap_requested_ratio": 0.01,
            "has_feasible_incumbent": True,
            "certified_best_bound": 640_000.0,
            "certified_mip_gap_ratio": 0.01574,
            "nodes_explored": 1,
        },
    )
    fingerprints = {
        key: "same" for key in (
            "trip_ids_sha256",
            "charger_ids_sha256",
            "trip_input_sha256",
            "trip_structure_input_sha256",
            "charger_input_sha256",
            "depot_input_sha256",
            "price_input_sha256",
            "price_value_set_sha256",
            "energy_asset_control_input_sha256",
            "objective_weights_sha256",
            "pv_profile_sha256",
        )
    }
    fingerprints.update(
        {
            "vehicle_ids_sha256": vehicle_hash,
            "vehicle_input_sha256": vehicle_hash,
            "vehicle_type_input_sha256": vehicle_hash,
            "trip_count": 264,
            "vehicle_count": 60,
            "charger_count": 10,
        }
    )
    _write_json(
        root / "optimization_parameters.json",
        {
            "canonical_input_dimensions": fingerprints,
            "effective_optimization_config": {
                "phase": "phase4_integrated",
                "random_seed": 42,
            },
        },
    )
    _write_json(
        root / "run_input_manifest.json",
        {
            "git_sha": "abc" if research_run else "def",
            "prepared_input_id": root.name,
            "prepared_source_sha256": root.name,
        },
    )
    _write_json(root / "summary.json", {"vehicle_count_used": 32})


def test_build_comparison_reports_structure_without_false_speedup_claim(
    tmp_path: Path,
) -> None:
    baseline = tmp_path / "baseline"
    candidate = tmp_path / "candidate"
    output = tmp_path / "output"
    _write_run(
        baseline,
        constraints=1_598_973,
        pairwise_rows=1_243_440,
        time_limit=3_600,
        solve_time=3_600.8,
        research_run=True,
        vehicle_hash="baseline-vehicles",
        lazy=False,
    )
    _write_run(
        candidate,
        constraints=355_533,
        pairwise_rows=0,
        time_limit=600,
        solve_time=601.2,
        research_run=False,
        vehicle_hash="candidate-vehicles",
        lazy=True,
    )

    comparison = build_comparison(baseline, candidate)
    write_comparison_outputs(comparison, output)

    assert comparison["structural_comparison"]["contract_passed"] is True
    assert (
        comparison["structural_comparison"]["constraint_count_removed"]
        == 1_243_440
    )
    assert comparison["outcome_comparison"][
        "all_reported_outcomes_match"
    ] is True
    assert comparison["runtime_claim"]["eligible"] is False
    assert "solver_time_limits_differ" in comparison["runtime_claim"][
        "blockers"
    ]
    assert "canonical_input_fingerprints_differ" in comparison[
        "runtime_claim"
    ]["blockers"]
    assert comparison["research_release"]["ready"] is False
    assert (output / "performance_comparison.json").is_file()
    assert (output / "performance_comparison.csv").is_file()
    markdown = (output / "performance_comparison.md").read_text(
        encoding="utf-8"
    )
    assert "not a speedup claim" in markdown


def test_build_comparison_treats_missing_fingerprints_as_not_comparable(
    tmp_path: Path,
) -> None:
    baseline = tmp_path / "baseline"
    candidate = tmp_path / "candidate"
    for root in (baseline, candidate):
        _write_run(
            root,
            constraints=355_533,
            pairwise_rows=0,
            time_limit=600,
            solve_time=601.2,
            research_run=False,
            vehicle_hash="same-vehicles",
            lazy=True,
        )
        parameters_path = root / "optimization_parameters.json"
        parameters = json.loads(parameters_path.read_text(encoding="utf-8"))
        parameters["canonical_input_dimensions"].pop("pv_profile_sha256")
        _write_json(parameters_path, parameters)

    comparison = build_comparison(baseline, candidate)

    assert comparison["input_comparability"][
        "fingerprint_checks"
    ]["pv_profile_sha256"] is False
    assert "pv_profile_sha256" in comparison["input_comparability"][
        "mismatched_fingerprints"
    ]
    assert comparison["runtime_claim"]["eligible"] is False


def _pure_ice_metrics(
    *,
    representation: str,
    total_variables: int,
    binary_variables: int,
    certified_gap: float,
    root_bound: float,
    wall_time: float,
) -> dict:
    is_aggregate = representation == "pure_aggregate"
    return {
        "provenance": {
            "git_sha": "same-sha",
            "git_dirty": False,
            "representation": representation,
            "audit_representation": representation,
            "prepared_input_id": "prepared-same",
            "input_hashes": {"prepared_source_sha256": "same-input"},
            "random_seed": 42,
            "gurobi_threads": 4,
            "time_limit_sec": 900,
            "requested_gap_ratio": 0.01,
            "gurobi_version": "13.0.1",
            "phase3_seed_time_limit_sec": 150,
            "rolling_step_time_limit_sec": 30,
            "gurobi_parameters": {"integrated_mip_focus": 3},
        },
        "model_size": {
            "total_variables": total_variables,
            "binary_variables": binary_variables,
            "integer_variables": 1,
            "continuous_variables": 10,
        },
        "timing": {
            "complete_model_build_time_sec": 100.0,
            "runner_wall_time_sec": wall_time,
        },
        "solve_outcome": {
            "root_relaxation_bound_jpy": root_bound,
            "certified_gap_ratio": certified_gap,
            "requested_gap_reached_time_sec": None,
        },
        "validity": {
            "served_trips": 264,
            "total_trips": 264,
            "duplicate_coverage_count": 0,
            "vehicle_overlap_count": 0,
            "invalid_transition_count": 0,
            "bev_soc_violation_count": 0,
            "ice_fuel_violation_count": 0,
            "charger_violation_count": 0,
            "bess_terminal_error_kwh": 0.0,
            "physical_validation_accepted": True,
            "rolling_step_count": 24,
            "rolling_chain_accepted": True,
            "accounting_eligible": True,
            "accounting_reconciliation_status": "OK",
            "fallback_used": False,
            "post_solve_repair_used": False,
            "reported_total_cost_jpy": 61_000.0,
        },
        "representation_audit": {
            "representation": representation,
            "vehicle_label_flow_variable_count_created": (
                0 if is_aggregate else 100
            ),
            "aggregate_network_variable_count_created": (
                40 if is_aggregate else 0
            ),
        },
    }


def test_pure_ice_ab_reports_structural_only_when_gap_does_not_improve(
    tmp_path: Path,
) -> None:
    case_a = _pure_ice_metrics(
        representation="discrete",
        total_variables=780_000,
        binary_variables=739_000,
        certified_gap=0.06,
        root_bound=58_000.0,
        wall_time=900.0,
    )
    case_b = _pure_ice_metrics(
        representation="pure_aggregate",
        total_variables=536_000,
        binary_variables=507_000,
        certified_gap=0.06,
        root_bound=58_000.0,
        wall_time=902.0,
    )

    comparison = build_pure_ice_ab_comparison(
        case_a,
        case_b,
        small_exact_parity_passed=True,
    )
    write_pure_ice_ab_outputs(comparison, tmp_path)

    assert comparison["correctness"]["passed"] is True
    assert comparison["changes"]["total_variable_reduction"] == 244_000
    assert comparison["changes"]["binary_variable_reduction"] == 232_000
    assert comparison["verdict"] == "PASS_STRUCTURAL_ONLY"
    assert (tmp_path / "case_A_discrete_metrics.json").is_file()
    assert (tmp_path / "case_B_pure_aggregate_metrics.json").is_file()
    header = (tmp_path / "comparison.csv").read_text(
        encoding="utf-8-sig"
    ).splitlines()[0]
    assert header == (
        "metric,A_discrete,B_pure_aggregate,absolute_change,relative_change"
    )


def test_pure_ice_ab_fails_when_controls_differ() -> None:
    case_a = _pure_ice_metrics(
        representation="discrete",
        total_variables=100,
        binary_variables=90,
        certified_gap=0.05,
        root_bound=10.0,
        wall_time=10.0,
    )
    case_b = _pure_ice_metrics(
        representation="pure_aggregate",
        total_variables=80,
        binary_variables=60,
        certified_gap=0.04,
        root_bound=10.0,
        wall_time=9.0,
    )
    case_b["provenance"]["random_seed"] = 7

    comparison = build_pure_ice_ab_comparison(
        case_a,
        case_b,
        small_exact_parity_passed=True,
    )

    assert comparison["correctness"]["control_contract_match"] is False
    assert comparison["verdict"] == "FAIL_CORRECTNESS"
