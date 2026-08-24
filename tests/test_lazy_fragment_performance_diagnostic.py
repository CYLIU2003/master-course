from __future__ import annotations

import json
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

from scripts.build_lazy_fragment_performance_diagnostic import (
    _load_resumable_pure_ice_case_runs,
    _run_pure_ice_case,
    _runtime_environment_snapshot,
    build_pure_ice_alternating_case_plan,
    build_comparison,
    build_pure_ice_ab_comparison,
    build_repeated_pure_ice_ab_comparison,
    collect_pure_ice_case_metrics,
    compile_phase3_pure_ice_ab_request,
    write_comparison_outputs,
    write_pure_ice_ab_outputs,
    write_repeated_pure_ice_ab_outputs,
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
            "research_run": True,
            "research_run_accepted": True,
            "successor_pruning_enabled": False,
            "representation": representation,
            "audit_representation": representation,
            "prepared_input_id": "prepared-same",
            "input_hashes": {"prepared_source_sha256": "same-input"},
            "random_seed": 42,
            "gurobi_threads": 4,
            "time_limit_sec": 900,
            "requested_gap_ratio": 0.01,
            "gurobi_version": "13.0.1",
            "requested_phase": "phase3_two_stage",
            "resolved_phase": "phase3_two_stage",
            "executed_phase": "phase3_two_stage",
            "phase4_seed_enabled": False,
            "stage1_time_limit_sec": 900,
            "stage2_time_limit_sec": 900,
            "rolling_step_time_limit_sec": 30,
            "gurobi_parameters": {"gurobi_threads": 4},
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
            "synthetic_pv_fallback_used": False,
            "stage1_objective_proxy_used": False,
            "weather_proxy_forecast_used": False,
            "reported_total_cost_jpy": 61_000.0,
        },
        "representation_audit": {
            "representation": representation,
            "applied": is_aggregate,
            "integer_feasible_set_changed": False,
            "labeled_extended_feasible_region_relaxed": False,
            "recoverable_physical_dispatch_set_changed": False,
            "vehicle_label_flow_variable_count_created": (
                0 if is_aggregate else 100
            ),
            "aggregate_network_variable_count_created": (
                40 if is_aggregate else 0
            ),
            "recovered_path_count": 2 if is_aggregate else 0,
            "recovered_vehicle_ids": (
                ["ICE_001", "ICE_002"] if is_aggregate else []
            ),
        },
    }


def test_runtime_environment_snapshot_has_required_reproducibility_fields() -> None:
    snapshot = _runtime_environment_snapshot()

    assert snapshot["python"]["version"]
    assert snapshot["python"]["executable"]
    assert "runtime_version" in snapshot["gurobi"]
    assert snapshot["operating_system"]["platform"]
    assert "logical_cpu_count" in snapshot["hardware"]
    assert "total_physical_memory_bytes" in snapshot["hardware"]


def test_pure_ice_metrics_preserves_presolve_callback_timestamp(
    tmp_path: Path, monkeypatch
) -> None:
    import scripts.build_lazy_fragment_performance_diagnostic as diagnostic

    payloads = {
        "canonical_solver_result.json": {
            "trip_count_served": 264,
            "trip_count_unserved": 0,
            "duties": [],
            "metadata": {},
            "solver_metadata": {
                "stage1_search_telemetry": {
                    "last_presolve_callback_runtime_sec": 0.75,
                },
                "stage1_gurobi_search_controls": {"presolve": 2},
            },
        },
        "solver_settings.json": {
            "time_limit_seconds_effective": 900,
            "mip_gap_requested_ratio": 0.01,
        },
        "optimization_parameters.json": {
            "canonical_input_dimensions": {},
            "effective_optimization_config": {"random_seed": 42},
        },
        "run_input_manifest.json": {
            "git_sha": "frozen-sha",
            "prepared_input_id": "prepared-input",
            "prepared_source_sha256": "prepared-hash",
        },
        "summary.json": {},
    }
    monkeypatch.setattr(
        diagnostic,
        "_read_json",
        lambda path: payloads[path.name],
    )
    monkeypatch.setattr(diagnostic, "_optional_json", lambda _path: {})

    metrics = collect_pure_ice_case_metrics(
        tmp_path,
        representation="discrete",
    )

    assert metrics["timing"]["presolve_time_sec"] == 0.75
    assert (
        metrics["timing"]["availability"]["presolve_time_sec"]
        == "last_presolve_callback_elapsed_from_stage1_optimize_start;"
        "not_a_dedicated_gurobi_presolve_duration_attribute"
    )
    assert metrics["provenance"]["stage1_gurobi_search_controls"] == {
        "presolve": 2
    }


def test_pure_ice_case_forwards_selector_by_keyword(
    tmp_path: Path, monkeypatch
) -> None:
    import bff.routers.optimization as optimization
    from bff.store import job_store
    import src.optimization.milp.solver_adapter as solver_adapter

    job = SimpleNamespace(job_id="test-job")
    completed_job = SimpleNamespace(
        status="completed", error=None, metadata={"run_dir": str(tmp_path)}
    )
    observed: dict = {}

    monkeypatch.setattr(job_store, "create_job", lambda **_kwargs: job)
    monkeypatch.setattr(job_store, "get_job", lambda _job_id: completed_job)
    monkeypatch.setattr(
        solver_adapter,
        "_diagnostic_exact_ice_clone_representation",
        lambda _representation: nullcontext(),
    )
    monkeypatch.setattr(
        optimization,
        "_run_optimization",
        lambda **kwargs: observed.update(kwargs),
    )

    _run_pure_ice_case(
        scenario_id="scenario-1",
        prepared_input_id="prepared-1",
        request={
            "mode": "phase3_two_stage",
            "stage1_powertrain_selector_strengthening": True,
            "stage1_activation_start_strengthening": True,
            "stage1_activation_start_strengthening_vehicle_ids": ["vehicle-1"],
            "stage1_root_lp_diagnostic_method": 1,
            "stage1_root_lp_diagnostic_exact_clique_separation_enabled": True,
            "stage1_root_lp_diagnostic_exact_clique_time_limit_seconds": 60,
            "gurobi_threads": 4,
        },
        representation="discrete",
        log_path=tmp_path / "bff_worker.log",
    )

    assert observed["stage1_powertrain_selector_strengthening"] is True
    assert observed["stage1_activation_start_strengthening"] is True
    assert observed["stage1_activation_start_strengthening_vehicle_ids"] == ["vehicle-1"]
    assert observed["stage1_root_lp_diagnostic_method"] == 1
    assert observed["stage1_root_lp_diagnostic_exact_clique_separation_enabled"] is True
    assert observed["stage1_root_lp_diagnostic_exact_clique_time_limit_seconds"] == 60
    assert observed["gurobi_threads"] == 4
    assert observed["mode"] == "phase3_two_stage"


def test_compile_phase3_pure_ice_ab_request_removes_only_phase4_controls() -> None:
    source = {
        "mode": "phase4_integrated",
        "prepared_input_id": "prepared-same",
        "random_seed": 42,
        "gurobi_threads": 4,
        "integrated_actual_cost_objective": True,
        "integrated_ev_utilization_mode": "required",
        "integrated_actual_cost_upper_bound_jpy": 1.0,
        "integrated_actual_cost_upper_bound_delta_ratio": 0.01,
    }

    compiled, transformation = compile_phase3_pure_ice_ab_request(source)

    assert compiled == {
        "mode": "phase3_two_stage",
        "prepared_input_id": "prepared-same",
        "random_seed": 42,
        "gurobi_threads": 4,
    }
    assert transformation["source_mode"] == "phase4_integrated"
    assert transformation["target_mode"] == "phase3_two_stage"
    assert transformation["removed_phase4_only_fields"] == [
        "integrated_actual_cost_objective",
        "integrated_ev_utilization_mode",
        "integrated_actual_cost_upper_bound_jpy",
        "integrated_actual_cost_upper_bound_delta_ratio",
    ]


def test_compile_phase3_pure_ice_ab_request_freezes_explicit_stage_limits() -> None:
    compiled, transformation = compile_phase3_pure_ice_ab_request(
        {"mode": "phase3_two_stage", "prepared_input_id": "prepared-same"},
        stage1_time_limit_seconds=435,
        stage2_time_limit_seconds=30,
    )

    assert compiled["stage1_time_limit_seconds"] == 435
    assert compiled["stage2_time_limit_seconds"] == 30
    assert transformation["fixed_stage_time_limits"] == {
        "stage1_time_limit_seconds": 435,
        "stage2_time_limit_seconds": 30,
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


def test_pure_ice_ab_fails_when_aggregate_recovery_changes_dispatch_set() -> None:
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
    case_b["representation_audit"][
        "recoverable_physical_dispatch_set_changed"
    ] = True

    comparison = build_pure_ice_ab_comparison(
        case_a,
        case_b,
        small_exact_parity_passed=True,
    )

    assert comparison["correctness"]["representation_audit_match"] is False
    assert comparison["verdict"] == "FAIL_CORRECTNESS"


def test_repeated_pure_ice_ab_uses_alternating_pairs_and_median_statistics(
    tmp_path: Path,
) -> None:
    plan = build_pure_ice_alternating_case_plan(5)

    assert [item["pair_order"] for item in plan[::2]] == [
        "AB",
        "BA",
        "AB",
        "BA",
        "AB",
    ]
    assert sum(item["representation"] == "discrete" for item in plan) == 5
    assert sum(item["representation"] == "pure_aggregate" for item in plan) == 5

    runs = []
    for item in plan:
        is_aggregate = item["representation"] == "pure_aggregate"
        metrics = _pure_ice_metrics(
            representation=item["representation"],
            total_variables=536_000 if is_aggregate else 780_000,
            binary_variables=507_000 if is_aggregate else 739_000,
            certified_gap=0.06,
            root_bound=58_000.0,
            wall_time=880.0 if is_aggregate else 900.0,
        )
        metrics["timing"]["total_solver_time_sec"] = (
            850.0 if is_aggregate else 870.0
        )
        metrics["timing"]["presolve_time_sec"] = None
        metrics["solve_outcome"]["peak_memory_bytes"] = (
            3_000_000 if is_aggregate else 4_000_000
        )
        runs.append({**item, "metrics": metrics})

    comparison = build_repeated_pure_ice_ab_comparison(
        runs,
        small_exact_parity_passed=True,
    )
    write_repeated_pure_ice_ab_outputs(comparison, tmp_path)

    assert comparison["correctness"]["passed"] is True
    assert comparison["execution"]["run_count_per_representation"] == {
        "discrete": 5,
        "pure_aggregate": 5,
    }
    assert comparison["aggregate_statistics"]["discrete"]["metrics"][
        "peak_memory_bytes"
    ]["median"] == 4_000_000.0
    assert comparison["aggregate_statistics"]["pure_aggregate"]["metrics"][
        "total_solver_time_sec"
    ]["median"] == 850.0
    assert comparison["verdict"] == "PASS_PERFORMANCE"
    assert comparison["correctness"]["median_solver_time_improved"] is True
    assert (tmp_path / "repeated_comparison.json").is_file()
    assert (tmp_path / "repeated_comparison.csv").is_file()
    assert "alternating AB/BA" in (tmp_path / "repeated_comparison.md").read_text(
        encoding="utf-8"
    )


def test_repeated_pure_ice_ab_rejects_fewer_than_five_repetitions() -> None:
    try:
        build_pure_ice_alternating_case_plan(4)
    except ValueError as error:
        assert "at least five" in str(error)
    else:
        raise AssertionError("expected the five-repetition gate to fail")


def test_resume_loader_uses_only_matching_completed_case_artifact(
    tmp_path: Path,
) -> None:
    plan = build_pure_ice_alternating_case_plan(5)
    completed = plan[0]
    case_dir = tmp_path / "runs" / f"01_{completed['label']}"
    case_dir.mkdir(parents=True)
    metrics = _pure_ice_metrics(
        representation="discrete",
        total_variables=780_000,
        binary_variables=739_000,
        certified_gap=0.06,
        root_bound=58_000.0,
        wall_time=900.0,
    )
    metrics["provenance"]["git_sha"] = "frozen-sha"
    metrics["provenance"]["input_hashes"]["prepared_source_sha256"] = (
        "prepared-hash"
    )
    _write_json(case_dir / "case_metrics.json", metrics)
    _write_json(
        case_dir / "child_result.json",
        {
            "job_id": "job-1",
            "run_dir": str(case_dir),
            "runner_wall_time_sec": 900.0,
        },
    )

    loaded = _load_resumable_pure_ice_case_runs(
        output_dir=tmp_path,
        plan=plan,
        expected_git_sha="frozen-sha",
        expected_prepared_input_sha256="prepared-hash",
    )

    assert list(loaded) == [1]
    assert loaded[1]["representation"] == "discrete"
    assert loaded[1]["metrics"]["provenance"]["representation"] == "discrete"


def test_pure_ice_ab_resume_skips_valid_completed_children(
    tmp_path: Path, monkeypatch
) -> None:
    import scripts.build_lazy_fragment_performance_diagnostic as diagnostic

    scenario_id = "scenario"
    prepared_input_id = "prepared"
    prepared_path = (
        tmp_path
        / "output"
        / "prepared_inputs"
        / scenario_id
        / f"{prepared_input_id}.json"
    )
    prepared_path.parent.mkdir(parents=True)
    prepared_path.write_text("{}", encoding="utf-8")
    request_path = tmp_path / "request.json"
    _write_json(request_path, {"prepared_input_id": prepared_input_id})
    output_dir = tmp_path / "ab"
    interruption = {"enabled": True, "calls": 0}

    monkeypatch.setattr(diagnostic, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(
        diagnostic,
        "_git_output",
        lambda *_args: "frozen-sha" if _args[:2] == ("rev-parse", "HEAD") else "",
    )
    monkeypatch.setattr(
        diagnostic,
        "_runtime_environment_snapshot",
        lambda: {"runtime": "test"},
    )
    monkeypatch.setattr(
        diagnostic,
        "compile_phase3_pure_ice_ab_request",
        lambda request, **_kwargs: (dict(request), {"fixed": True}),
    )

    def fake_child(*, representation: str, run_directory: Path, **_kwargs: object) -> dict:
        interruption["calls"] += 1
        if interruption["enabled"] and interruption["calls"] == 2:
            raise RuntimeError("simulated parent interruption")
        metrics = _pure_ice_metrics(
            representation=representation,
            total_variables=536_000 if representation == "pure_aggregate" else 780_000,
            binary_variables=507_000 if representation == "pure_aggregate" else 739_000,
            certified_gap=0.06,
            root_bound=58_000.0,
            wall_time=900.0,
        )
        metrics["provenance"]["git_sha"] = "frozen-sha"
        metrics["provenance"]["input_hashes"]["prepared_source_sha256"] = (
            diagnostic._sha256_file(prepared_path)
        )
        child = {
            "metrics": metrics,
            "job_id": f"job-{interruption['calls']}",
            "run_dir": str(run_directory),
            "runner_wall_time_sec": 900.0,
            "parent_observed_wall_time_sec": 900.0,
            "peak_rss_bytes": 4_000_000,
            "rss_sample_count": 1,
        }
        _write_json(
            run_directory / "child_result.json",
            {
                "job_id": child["job_id"],
                "run_dir": child["run_dir"],
                "runner_wall_time_sec": child["runner_wall_time_sec"],
            },
        )
        return child

    monkeypatch.setattr(diagnostic, "_run_pure_ice_case_in_child_process", fake_child)

    try:
        diagnostic.run_pure_ice_aggregation_ab(
            scenario_id=scenario_id,
            prepared_input_id=prepared_input_id,
            optimization_request_path=request_path,
            output_dir=output_dir,
            small_exact_parity_passed=True,
            stage1_time_limit_seconds=435,
            stage2_time_limit_seconds=30,
        )
    except RuntimeError as error:
        assert "simulated parent interruption" in str(error)
    else:
        raise AssertionError("expected simulated parent interruption")

    interruption["enabled"] = False
    comparison = diagnostic.run_pure_ice_aggregation_ab(
        scenario_id=scenario_id,
        prepared_input_id=prepared_input_id,
        optimization_request_path=request_path,
        output_dir=output_dir,
        small_exact_parity_passed=True,
        stage1_time_limit_seconds=435,
        stage2_time_limit_seconds=30,
        resume=True,
    )

    assert comparison["execution"]["run_count"] == 10
    assert interruption["calls"] == 11
    manifest = json.loads((output_dir / "request_manifest.json").read_text())
    assert manifest["resume_history"][0]["completed_run_indices_before_resume"] == [1]


def test_single_pure_ice_diagnostic_is_frozen_and_never_claims_comparison(
    tmp_path: Path, monkeypatch
) -> None:
    import scripts.build_lazy_fragment_performance_diagnostic as diagnostic

    scenario_id = "scenario"
    prepared_input_id = "prepared"
    prepared_path = (
        tmp_path
        / "output"
        / "prepared_inputs"
        / scenario_id
        / f"{prepared_input_id}.json"
    )
    prepared_path.parent.mkdir(parents=True)
    prepared_path.write_text("{}", encoding="utf-8")
    request_path = tmp_path / "request.json"
    _write_json(
        request_path,
        {
            "prepared_input_id": prepared_input_id,
            "random_seed": 42,
            "gurobi_threads": 4,
        },
    )
    output_dir = tmp_path / "single"

    monkeypatch.setattr(diagnostic, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(
        diagnostic,
        "_git_output",
        lambda *_args: "frozen-sha" if _args[:2] == ("rev-parse", "HEAD") else "",
    )
    monkeypatch.setattr(
        diagnostic,
        "_runtime_environment_snapshot",
        lambda: {"runtime": "test"},
    )
    monkeypatch.setattr(
        diagnostic,
        "compile_phase3_pure_ice_ab_request",
        lambda request, **kwargs: ({**request, **kwargs}, {"fixed": True}),
    )

    def fake_child(*, representation: str, run_directory: Path, **_kwargs: object) -> dict:
        metrics = _pure_ice_metrics(
            representation=representation,
            total_variables=536_000,
            binary_variables=507_000,
            certified_gap=0.028,
            root_bound=58_000.0,
            wall_time=900.0,
        )
        metrics["provenance"]["git_sha"] = "frozen-sha"
        metrics["provenance"]["input_hashes"]["prepared_source_sha256"] = (
            diagnostic._sha256_file(prepared_path)
        )
        return {
            "metrics": metrics,
            "job_id": "job-1",
            "run_dir": str(run_directory),
            "runner_wall_time_sec": 900.0,
            "parent_observed_wall_time_sec": 901.0,
            "peak_rss_bytes": 4_000_000,
            "rss_sample_count": 1,
        }

    monkeypatch.setattr(diagnostic, "_run_pure_ice_case_in_child_process", fake_child)

    result = diagnostic.run_pure_ice_aggregation_single_diagnostic(
        scenario_id=scenario_id,
        prepared_input_id=prepared_input_id,
        optimization_request_path=request_path,
        output_dir=output_dir,
        representation="pure_aggregate",
        stage1_time_limit_seconds=870,
        stage2_time_limit_seconds=30,
        wall_clock_overhead_seconds=120,
        stage1_gurobi_search_profile="incumbent_focus",
    )

    assert result["verdict"] == "DIAGNOSTIC_COMPLETE_NOT_A_COMPARISON"
    assert result["claim_scope"]["ab_comparison"] is False
    assert result["claim_scope"]["performance_claim_forbidden"] is True
    assert result["claim_scope"]["formal_research_acceptance_forbidden"] is True
    manifest = json.loads((output_dir / "request_manifest.json").read_text())
    assert manifest["representation"] == "pure_aggregate"
    assert manifest["solver_controls"]["stage1_time_limit_seconds"] == 870
    assert manifest["solver_controls"]["time_limit_seconds"] == 1020
    assert manifest["solver_controls"]["stage1_gurobi_search_profile"] == (
        "incumbent_focus"
    )
    assert manifest["phase3_request_transformation"][
        "stage1_gurobi_search_profile_override"
    ] == "incumbent_focus"
    assert manifest["single_diagnostic_wall_clock_contract"] == {
        "stage1_time_limit_seconds": 870,
        "stage2_time_limit_seconds": 30,
        "wall_clock_overhead_seconds": 120,
        "time_limit_seconds": 1020,
        "semantics": (
            "shared_wall_clock_budget_equals_explicit_stage_solver_caps_"
            "plus_model_construction_and_finalization_allowance"
        ),
    }
    assert (output_dir / "run" / "case_metrics.json").is_file()
    assert (output_dir / "diagnostic_result.json").is_file()
    assert (output_dir / "artifact_hashes.json").is_file()


def test_repeated_pure_ice_ab_fails_when_any_child_control_drifts() -> None:
    plan = build_pure_ice_alternating_case_plan(5)
    runs = []
    for item in plan:
        metrics = _pure_ice_metrics(
            representation=item["representation"],
            total_variables=536_000
            if item["representation"] == "pure_aggregate"
            else 780_000,
            binary_variables=507_000
            if item["representation"] == "pure_aggregate"
            else 739_000,
            certified_gap=0.06,
            root_bound=58_000.0,
            wall_time=900.0,
        )
        runs.append({**item, "metrics": metrics})
    runs[-1]["metrics"]["provenance"]["gurobi_threads"] = 8

    comparison = build_repeated_pure_ice_ab_comparison(
        runs,
        small_exact_parity_passed=True,
    )

    assert comparison["correctness"]["control_contract_match"] is False
    assert comparison["verdict"] == "FAIL_CORRECTNESS"


def test_repeated_pure_ice_ab_fails_when_representation_audit_is_missing() -> None:
    plan = build_pure_ice_alternating_case_plan(5)
    runs = []
    for item in plan:
        metrics = _pure_ice_metrics(
            representation=item["representation"],
            total_variables=536_000
            if item["representation"] == "pure_aggregate"
            else 780_000,
            binary_variables=507_000
            if item["representation"] == "pure_aggregate"
            else 739_000,
            certified_gap=0.06,
            root_bound=58_000.0,
            wall_time=900.0,
        )
        runs.append({**item, "metrics": metrics})
    runs[0]["metrics"]["representation_audit"] = {}

    comparison = build_repeated_pure_ice_ab_comparison(
        runs,
        small_exact_parity_passed=True,
    )

    assert comparison["correctness"]["individual_run_checks"][0]["passed"] is False
    assert comparison["verdict"] == "FAIL_CORRECTNESS"
