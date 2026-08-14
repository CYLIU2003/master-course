from __future__ import annotations

import json
from pathlib import Path

from scripts.build_lazy_fragment_performance_diagnostic import (
    build_comparison,
    write_comparison_outputs,
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
