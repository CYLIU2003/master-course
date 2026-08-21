from __future__ import annotations

import argparse
import csv
import hashlib
import json
import subprocess
import sys
import time
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


SCHEMA_VERSION = "lazy_fragment_performance_diagnostic_v1"
PURE_ICE_AB_SCHEMA_VERSION = "pure_ice_aggregation_ab_v1"
INPUT_FINGERPRINT_KEYS = (
    "trip_ids_sha256",
    "vehicle_ids_sha256",
    "charger_ids_sha256",
    "trip_input_sha256",
    "trip_structure_input_sha256",
    "vehicle_input_sha256",
    "charger_input_sha256",
    "depot_input_sha256",
    "vehicle_type_input_sha256",
    "price_input_sha256",
    "price_value_set_sha256",
    "energy_asset_control_input_sha256",
    "objective_weights_sha256",
    "pv_profile_sha256",
)


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"required artifact is missing: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected a JSON object: {path}")
    return payload


def _recursive_values(payload: Any, key: str) -> list[Any]:
    values: list[Any] = []
    if isinstance(payload, Mapping):
        for child_key, child_value in payload.items():
            if child_key == key:
                values.append(child_value)
            values.extend(_recursive_values(child_value, key))
    elif isinstance(payload, list):
        for child in payload:
            values.extend(_recursive_values(child, key))
    return values


def _unique_recursive_scalar(payload: Any, key: str) -> int | float | str | None:
    values = [
        value
        for value in _recursive_values(payload, key)
        if isinstance(value, (int, float, str)) and not isinstance(value, bool)
    ]
    unique_values: list[int | float | str] = []
    for value in values:
        if value not in unique_values:
            unique_values.append(value)
    if not unique_values:
        return None
    if len(unique_values) != 1:
        raise ValueError(
            f"artifact contains inconsistent values for {key}: {unique_values}"
        )
    return unique_values[0]


def _float_or_none(value: Any) -> float | None:
    if value in (None, ""):
        return None
    return float(value)


def _int_or_none(value: Any) -> int | None:
    if value in (None, ""):
        return None
    return int(value)


def _run_snapshot(run_dir: Path) -> dict[str, Any]:
    canonical = _read_json(run_dir / "canonical_solver_result.json")
    settings = _read_json(run_dir / "solver_settings.json")
    parameters = _read_json(run_dir / "optimization_parameters.json")
    manifest = _read_json(run_dir / "run_input_manifest.json")
    summary = _read_json(run_dir / "summary.json")

    plan_metadata = dict(canonical.get("metadata") or {})
    solver_metadata = dict(canonical.get("solver_metadata") or {})
    dimensions = dict(parameters.get("canonical_input_dimensions") or {})
    effective_config = dict(parameters.get("effective_optimization_config") or {})
    separator = dict(
        plan_metadata.get("integrated_fragment_transition_lazy_separator") or {}
    )
    phase4_solve_time = _float_or_none(settings.get("solve_time_sec"))
    phase3_seed_time = _float_or_none(
        settings.get("phase4_phase3_seed_wall_runtime_sec")
    )

    return {
        "run_dir": str(run_dir.resolve()),
        "git_sha": str(manifest.get("git_sha") or settings.get("git_sha") or ""),
        "prepared_input_id": str(manifest.get("prepared_input_id") or ""),
        "prepared_source_sha256": str(
            manifest.get("prepared_source_sha256") or ""
        ),
        "research_run": bool(settings.get("research_run", False)),
        "runtime_comparison_eligible": bool(
            settings.get("runtime_comparison_eligible", False)
        ),
        "runtime_comparison_eligibility_reason": str(
            settings.get("runtime_comparison_eligibility_reason") or ""
        ),
        "phase": str(effective_config.get("phase") or ""),
        "objective_preset": str(plan_metadata.get("objective_preset") or ""),
        "random_seed": effective_config.get("random_seed"),
        "mip_gap_requested_ratio": _float_or_none(
            settings.get("mip_gap_requested_ratio")
        ),
        "time_limit_seconds": _float_or_none(
            settings.get("time_limit_seconds_effective")
        ),
        "phase4_solve_time_seconds": phase4_solve_time,
        "phase3_seed_wall_time_seconds": phase3_seed_time,
        "recorded_solver_time_sum_seconds": (
            None
            if phase4_solve_time is None or phase3_seed_time is None
            else phase4_solve_time + phase3_seed_time
        ),
        "solver_status": str(canonical.get("solver_status") or ""),
        "termination_reason": str(solver_metadata.get("termination_reason") or ""),
        "has_feasible_incumbent": bool(
            settings.get("has_feasible_incumbent", False)
        ),
        "trip_count_served": _int_or_none(canonical.get("trip_count_served")),
        "trip_count_unserved": _int_or_none(
            canonical.get("trip_count_unserved")
        ),
        "vehicle_count_used": _int_or_none(summary.get("vehicle_count_used")),
        "objective_value_jpy": _float_or_none(canonical.get("objective_value")),
        "certified_best_bound_jpy": _float_or_none(
            settings.get("certified_best_bound")
        ),
        "certified_mip_gap_ratio": _float_or_none(
            settings.get("certified_mip_gap_ratio")
        ),
        "nodes_explored": _int_or_none(settings.get("nodes_explored")),
        "model_variable_count": _int_or_none(
            _unique_recursive_scalar(
                canonical, "dispatch_fixed_recourse_model_variable_count"
            )
        ),
        "model_constraint_count": _int_or_none(
            _unique_recursive_scalar(
                canonical, "dispatch_fixed_recourse_model_constraint_count"
            )
        ),
        "explicit_fragment_pairwise_constraint_count": _int_or_none(
            plan_metadata.get("integrated_fragment_pairwise_constraint_count")
        ),
        "fragment_pairwise_constraint_mode": plan_metadata.get(
            "integrated_fragment_pairwise_constraint_mode"
        ),
        "fragment_occupancy_constraint_count": _int_or_none(
            plan_metadata.get("integrated_fragment_occupancy_constraint_count")
        ),
        "overlap_clique_constraint_count": _int_or_none(
            plan_metadata.get("integrated_overlap_clique_constraint_count")
        ),
        "lazy_separator": separator,
        "canonical_input_dimensions": dimensions,
        "input_fingerprints": {
            key: dimensions.get(key) for key in INPUT_FINGERPRINT_KEYS
        },
    }


def _same_number(left: Any, right: Any, tolerance: float = 1.0e-9) -> bool:
    if left is None or right is None:
        return left is right
    return abs(float(left) - float(right)) <= tolerance


def build_comparison(
    baseline_run_dir: Path,
    candidate_run_dir: Path,
) -> dict[str, Any]:
    baseline = _run_snapshot(baseline_run_dir)
    candidate = _run_snapshot(candidate_run_dir)
    fingerprint_checks = {}
    for key in INPUT_FINGERPRINT_KEYS:
        baseline_fingerprint = baseline["input_fingerprints"].get(key)
        candidate_fingerprint = candidate["input_fingerprints"].get(key)
        fingerprint_checks[key] = bool(
            baseline_fingerprint
            and candidate_fingerprint
            and baseline_fingerprint == candidate_fingerprint
        )
    mismatched_fingerprints = sorted(
        key for key, matched in fingerprint_checks.items() if not matched
    )

    baseline_constraints = int(baseline["model_constraint_count"] or 0)
    candidate_constraints = int(candidate["model_constraint_count"] or 0)
    removed_constraints = baseline_constraints - candidate_constraints
    constraint_reduction_percent = (
        None
        if baseline_constraints <= 0
        else 100.0 * removed_constraints / baseline_constraints
    )
    baseline_time = baseline["phase4_solve_time_seconds"]
    candidate_time = candidate["phase4_solve_time_seconds"]
    observed_phase4_time_ratio = (
        None
        if not baseline_time or not candidate_time
        else float(baseline_time) / float(candidate_time)
    )

    runtime_blockers: list[str] = []
    if mismatched_fingerprints:
        runtime_blockers.append("canonical_input_fingerprints_differ")
    if baseline["time_limit_seconds"] != candidate["time_limit_seconds"]:
        runtime_blockers.append("solver_time_limits_differ")
    if baseline["research_run"] != candidate["research_run"]:
        runtime_blockers.append("formal_and_diagnostic_run_scopes_differ")
    if not baseline["runtime_comparison_eligible"]:
        runtime_blockers.append("baseline_not_repeated_runtime_comparison")
    if not candidate["runtime_comparison_eligible"]:
        runtime_blockers.append("candidate_not_repeated_runtime_comparison")

    separator = dict(candidate.get("lazy_separator") or {})
    integer_feasible_set_preserved = bool(
        separator.get("integer_feasible_set_preserved", False)
    )
    callback_error = separator.get("callback_error")
    structural_contract_passed = bool(
        baseline["model_variable_count"] == candidate["model_variable_count"]
        and baseline["explicit_fragment_pairwise_constraint_count"]
        == removed_constraints
        and candidate["explicit_fragment_pairwise_constraint_count"] == 0
        and candidate["fragment_pairwise_constraint_mode"]
        == "lazy_integer_incumbent_separation"
        and integer_feasible_set_preserved
        and callback_error in (None, "")
    )
    outcome_match = {
        "objective_value_jpy": _same_number(
            baseline["objective_value_jpy"], candidate["objective_value_jpy"]
        ),
        "certified_best_bound_jpy": _same_number(
            baseline["certified_best_bound_jpy"],
            candidate["certified_best_bound_jpy"],
        ),
        "certified_mip_gap_ratio": _same_number(
            baseline["certified_mip_gap_ratio"],
            candidate["certified_mip_gap_ratio"],
        ),
        "trip_count_served": (
            baseline["trip_count_served"] == candidate["trip_count_served"]
        ),
        "vehicle_count_used": (
            baseline["vehicle_count_used"] == candidate["vehicle_count_used"]
        ),
    }

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "claim_scope": "diagnostic_formulation_evidence_only",
        "baseline": baseline,
        "candidate": candidate,
        "input_comparability": {
            "all_fingerprints_match": not mismatched_fingerprints,
            "fingerprint_checks": fingerprint_checks,
            "mismatched_fingerprints": mismatched_fingerprints,
        },
        "structural_comparison": {
            "contract_passed": structural_contract_passed,
            "model_variable_count_unchanged": (
                baseline["model_variable_count"]
                == candidate["model_variable_count"]
            ),
            "constraint_count_removed": removed_constraints,
            "constraint_count_reduction_percent": constraint_reduction_percent,
            "integer_feasible_set_preserved_by_implementation_contract": (
                integer_feasible_set_preserved
            ),
            "candidate_callback_error": callback_error,
            "candidate_mipsol_callback_count": separator.get(
                "mipsol_callback_count"
            ),
            "candidate_lazy_constraint_count": separator.get(
                "lazy_constraint_count"
            ),
            "candidate_lazy_constraint_submission_count": separator.get(
                "lazy_constraint_submission_count"
            ),
        },
        "outcome_comparison": {
            "all_reported_outcomes_match": all(outcome_match.values()),
            "checks": outcome_match,
            "observed_phase4_solve_time_ratio": observed_phase4_time_ratio,
            "observed_phase4_solve_time_ratio_is_speedup_claim": False,
        },
        "runtime_claim": {
            "eligible": not runtime_blockers,
            "status": "NOT_CERTIFIED" if runtime_blockers else "CERTIFIED",
            "blockers": runtime_blockers,
            "required_next_evidence": (
                "Repeated runs from matched canonical inputs, identical time limits, "
                "and the same formal/diagnostic scope."
            ),
        },
        "research_release": {
            "ready": False,
            "status": "BLOCKED",
            "reasons": [
                "candidate_is_diagnostic_only",
                "candidate_has_no_accepted_rolling_chain",
                "one_percent_gap_not_met",
            ],
        },
        "interpretation": [
            (
                "The explicit fragment-pair rows were removed while retaining "
                "the same variable count and the exact integer-feasibility callback "
                "contract."
            ),
            (
                "The incumbent objective, certified bound, and certified gap did not "
                "improve; after row reduction, high-PV lower-bound strength remains "
                "the dominant proof bottleneck."
            ),
            (
                "The observed wall-clock values are not a certified speedup because "
                "the runs have different time limits, scopes, input fingerprints, "
                "and no repetitions."
            ),
        ],
    }


def _comparison_rows(comparison: Mapping[str, Any]) -> Iterable[dict[str, Any]]:
    baseline = dict(comparison["baseline"])
    candidate = dict(comparison["candidate"])
    metrics = (
        "model_variable_count",
        "model_constraint_count",
        "explicit_fragment_pairwise_constraint_count",
        "fragment_occupancy_constraint_count",
        "overlap_clique_constraint_count",
        "phase4_solve_time_seconds",
        "phase3_seed_wall_time_seconds",
        "recorded_solver_time_sum_seconds",
        "objective_value_jpy",
        "certified_best_bound_jpy",
        "certified_mip_gap_ratio",
        "trip_count_served",
        "vehicle_count_used",
        "nodes_explored",
    )
    for metric in metrics:
        baseline_value = baseline.get(metric)
        candidate_value = candidate.get(metric)
        delta = None
        if isinstance(baseline_value, (int, float)) and isinstance(
            candidate_value, (int, float)
        ):
            delta = candidate_value - baseline_value
        yield {
            "metric": metric,
            "baseline": baseline_value,
            "candidate": candidate_value,
            "candidate_minus_baseline": delta,
        }


def _render_markdown(comparison: Mapping[str, Any]) -> str:
    structural = dict(comparison["structural_comparison"])
    outcome = dict(comparison["outcome_comparison"])
    runtime = dict(comparison["runtime_claim"])
    lines = [
        "# Lazy fragment separation performance diagnostic",
        "",
        f"- Claim scope: `{comparison['claim_scope']}`",
        f"- Structural contract: `{structural['contract_passed']}`",
        f"- Runtime speedup certified: `{runtime['eligible']}`",
        f"- Research release: `{comparison['research_release']['status']}`",
        "",
        "| Metric | Baseline | Candidate | Candidate - baseline |",
        "|---|---:|---:|---:|",
    ]
    for row in _comparison_rows(comparison):
        lines.append(
            "| {metric} | {baseline} | {candidate} | {delta} |".format(
                metric=row["metric"],
                baseline=row["baseline"],
                candidate=row["candidate"],
                delta=row["candidate_minus_baseline"],
            )
        )
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            *[f"- {item}" for item in comparison["interpretation"]],
            "",
            "## Runtime-claim blockers",
            "",
            *[f"- `{item}`" for item in runtime["blockers"]],
            "",
            (
                "The observed Phase 4 time ratio is "
                f"`{outcome['observed_phase4_solve_time_ratio']}`. "
                "It is diagnostic only and is not a speedup claim."
            ),
            "",
        ]
    )
    return "\n".join(lines)


def write_comparison_outputs(
    comparison: Mapping[str, Any],
    output_dir: Path,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "performance_comparison.json").write_text(
        json.dumps(comparison, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    with (output_dir / "performance_comparison.csv").open(
        "w", encoding="utf-8-sig", newline=""
    ) as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=(
                "metric",
                "baseline",
                "candidate",
                "candidate_minus_baseline",
            ),
        )
        writer.writeheader()
        writer.writerows(_comparison_rows(comparison))
    (output_dir / "performance_comparison.md").write_text(
        _render_markdown(comparison),
        encoding="utf-8",
    )


def _optional_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return dict(payload) if isinstance(payload, dict) else {}


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git_output(*args: str) -> str:
    completed = subprocess.run(
        ("git", *args),
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return completed.stdout.strip()


def _phase_metric(
    profile: Mapping[str, Any],
    key: str,
) -> Any:
    phases = [
        dict(item)
        for item in list(profile.get("phases") or ())
        if isinstance(item, Mapping)
    ]
    cost_phase = next(
        (
            phase
            for phase in reversed(phases)
            if "cost" in str(phase.get("phase") or "")
            or "bound" in str(phase.get("search_profile") or "")
        ),
        phases[-1] if phases else {},
    )
    return cost_phase.get(key)


def collect_pure_ice_case_metrics(
    run_dir: Path,
    *,
    representation: str,
    runner_wall_time_sec: float | None = None,
) -> dict[str, Any]:
    """Collect one full frontend/BFF run into the A/B metric schema."""

    canonical = _read_json(run_dir / "canonical_solver_result.json")
    settings = _read_json(run_dir / "solver_settings.json")
    parameters = _read_json(run_dir / "optimization_parameters.json")
    manifest = _read_json(run_dir / "run_input_manifest.json")
    summary = _read_json(run_dir / "summary.json")
    physical = _optional_json(run_dir / "physical_schedule_validation.json")
    rolling = _optional_json(
        run_dir / "rolling_hourly_chain" / "rolling_chain_summary.json"
    )
    accounting = _optional_json(
        run_dir / "rolling_hourly_chain" / "executed_day_accounting.json"
    )
    reconciliation = _optional_json(run_dir / "final_cost_reconciliation.json")

    plan_metadata = dict(canonical.get("metadata") or {})
    solver_metadata = dict(canonical.get("solver_metadata") or {})
    profile = dict(solver_metadata.get("integrated_search_profile") or {})
    callback = dict(profile.get("mip_callback_telemetry") or {})
    presolve = dict(solver_metadata.get("presolve_reduction_summary") or {})
    aggregation = dict(
        plan_metadata.get(
            "integrated_exact_combustion_clone_flow_aggregation_audit"
        )
        or solver_metadata.get(
            "integrated_exact_combustion_clone_flow_aggregation_audit"
        )
        or {}
    )
    dimensions = dict(parameters.get("canonical_input_dimensions") or {})
    effective = dict(parameters.get("effective_optimization_config") or {})
    validation = dict(physical.get("validation_metrics") or {})
    solver_validation = dict(physical.get("solver_validation_metrics") or {})
    accounting_cost = dict(accounting.get("cost_breakdown") or {})

    initial_integer = int(presolve.get("initial_num_int_vars") or 0)
    initial_binary = int(presolve.get("initial_num_bin_vars") or 0)
    duties = [
        dict(item)
        for item in list(canonical.get("duties") or ())
        if isinstance(item, Mapping)
    ]
    served = int(canonical.get("trip_count_served") or 0)
    unserved = int(canonical.get("trip_count_unserved") or 0)
    first_events = [
        dict(item)
        for item in list(callback.get("incumbent_events") or ())
        if isinstance(item, Mapping)
    ]
    input_hashes = {
        key: value
        for key, value in dimensions.items()
        if "sha256" in str(key) or str(key).endswith("_hash")
    }
    input_hashes.update(
        {
            "prepared_source_sha256": manifest.get(
                "prepared_source_sha256"
            ),
            "prepared_input_sha256": rolling.get("prepared_input_sha256"),
            "timetable_hash": rolling.get("trip_input_hash"),
            "vehicle_hash": rolling.get("vehicle_input_hash"),
            "trip_energy_hash": dimensions.get("trip_energy_input_sha256"),
            "pv_hash": dimensions.get("pv_profile_sha256"),
            "tariff_hash": dimensions.get("price_input_sha256"),
            "objective_hash": dimensions.get("objective_weights_sha256"),
        }
    )

    return {
        "schema_version": PURE_ICE_AB_SCHEMA_VERSION,
        "run_dir": str(run_dir.resolve()),
        "provenance": {
            "git_sha": str(
                manifest.get("git_sha") or settings.get("git_sha") or ""
            ),
            "git_dirty": bool(settings.get("git_dirty", True)),
            "representation": representation,
            "audit_representation": aggregation.get("representation"),
            "prepared_input_id": str(manifest.get("prepared_input_id") or ""),
            "input_hashes": input_hashes,
            "random_seed": effective.get("random_seed"),
            "gurobi_threads": (
                solver_metadata.get("gurobi_threads")
                or rolling.get("gurobi_threads")
            ),
            "time_limit_sec": settings.get("time_limit_seconds_effective"),
            "requested_gap_ratio": settings.get("mip_gap_requested_ratio"),
            "gurobi_version": rolling.get("solver_version"),
            "phase3_seed_time_limit_sec": effective.get(
                "phase4_phase3_seed_time_limit_sec"
            ),
            "rolling_step_time_limit_sec": rolling.get("time_limit_sec"),
            "gurobi_parameters": {
                key: solver_metadata.get(key)
                for key in (
                    "integrated_mip_focus",
                    "integrated_heuristics",
                    "integrated_symmetry",
                    "integrated_root_method",
                    "integrated_node_method",
                    "integrated_soft_mem_limit_gb",
                    "integrated_nodefile_start_gb",
                )
            },
        },
        "model_size": {
            "total_variables": presolve.get("initial_num_vars"),
            "binary_variables": initial_binary,
            "integer_variables": max(initial_integer - initial_binary, 0),
            "continuous_variables": presolve.get(
                "initial_num_continuous_vars"
            ),
            "constraints": presolve.get("initial_num_constrs"),
            "nonzero_coefficients": presolve.get(
                "initial_num_nonzero_coefficients"
            ),
            "ice_label_variables": aggregation.get(
                "vehicle_label_flow_variable_count_created"
            ),
            "aggregate_network_variables": aggregation.get(
                "aggregate_network_variable_count_created"
            ),
            "removed_variables": aggregation.get(
                "vehicle_label_flow_variable_count_removed", 0
            ),
            "added_variables": aggregation.get(
                "aggregate_integer_variable_count_added", 0
            ),
            "net_reduction": aggregation.get(
                "net_binary_variable_reduction", 0
            ),
        },
        "timing": {
            "input_preparation_time_sec": None,
            "variable_construction_time_sec": dict(
                profile.get("vehicle_indexed_variable_build") or {}
            ).get("wall_time_sec"),
            "constraint_construction_time_sec": None,
            "complete_model_build_time_sec": profile.get(
                "pre_optimize_wall_time_sec"
            ),
            "presolve_time_sec": None,
            "root_relaxation_time_sec": callback.get(
                "root_relaxation_runtime_sec"
            ),
            "first_incumbent_time_sec": callback.get(
                "first_incumbent_runtime_sec"
            ),
            "cost_stage_solve_time_sec": _phase_metric(
                profile, "wall_time_sec"
            ),
            "total_solver_time_sec": settings.get("solve_time_sec"),
            "runner_wall_time_sec": runner_wall_time_sec,
            "availability": {
                "input_preparation_time_sec": "not_separately_instrumented",
                "constraint_construction_time_sec": (
                    "included_in_complete_model_build_time_sec"
                ),
                "presolve_time_sec": "not_separately_exposed_by_gurobi",
            },
        },
        "solve_outcome": {
            "solver_status": canonical.get("solver_status"),
            "incumbent_objective_jpy": canonical.get("objective_value"),
            "raw_gurobi_bound_jpy": settings.get("gurobi_raw_best_bound"),
            "raw_gurobi_gap_ratio": settings.get("gurobi_raw_mip_gap_ratio"),
            "root_relaxation_bound_jpy": callback.get(
                "root_relaxation_bound"
            ),
            "independent_certified_lower_bound_jpy": plan_metadata.get(
                "integrated_analytical_objective_lower_bound"
            ),
            "certified_best_bound_jpy": settings.get("certified_best_bound"),
            "certified_gap_ratio": settings.get("certified_mip_gap_ratio"),
            "explored_nodes": settings.get("nodes_explored"),
            "root_lp_iterations": callback.get(
                "final_simplex_iteration_count"
            ),
            "first_incumbent_objective_jpy": (
                callback.get("first_incumbent_objective")
                if callback.get("first_incumbent_objective") is not None
                else (
                    first_events[0].get("incumbent_objective")
                    if first_events
                    else None
                )
            ),
            "requested_gap_reached_time_sec": callback.get(
                "requested_gap_reached_runtime_sec"
            ),
            "peak_memory_bytes": None,
        },
        "validity": {
            "served_trips": served,
            "total_trips": served + unserved,
            "used_ice_vehicles": sum(
                1
                for duty in duties
                if str(duty.get("vehicle_type") or "").upper() == "ICE"
            ),
            "duplicate_coverage_count": validation.get(
                "duplicate_trip_count"
            ),
            "vehicle_overlap_count": validation.get(
                "vehicle_time_overlap_count"
            ),
            "invalid_transition_count": validation.get(
                "infeasible_transition_count"
            ),
            "bev_soc_violation_count": int(
                validation.get("ev_soc_lower_violation_count") or 0
            )
            + int(validation.get("ev_soc_upper_violation_count") or 0)
            + int(validation.get("bev_terminal_soc_violation_count") or 0),
            "ice_fuel_violation_count": int(
                validation.get("fuel_lower_violation_count") or 0
            )
            + int(validation.get("fuel_upper_violation_count") or 0),
            "charger_violation_count": sum(
                int(validation.get(key) or 0)
                for key in (
                    "blank_charger_id_count",
                    "unknown_charger_id_count",
                    "charger_depot_mismatch_count",
                    "charging_location_violation_count",
                    "charger_compatibility_violation_count",
                    "charger_power_violation_count",
                    "charger_concurrency_violation_count",
                )
            ),
            "bess_terminal_error_kwh": solver_validation.get(
                "bess_terminal_soc_deviation_kwh"
            ),
            "physical_validation_accepted": bool(physical.get("accepted")),
            "rolling_step_count": rolling.get("step_count"),
            "rolling_chain_accepted": bool(rolling.get("chain_accepted")),
            "accounting_eligible": bool(accounting.get("eligible")),
            "accounting_reconciliation_status": reconciliation.get("status"),
            "reported_total_cost_jpy": accounting_cost.get("total_cost"),
            "fallback_used": bool(settings.get("fallback_applied", False)),
            "post_solve_repair_used": not bool(
                dict(settings.get("research_acceptance_checks") or {}).get(
                    "no_postsolve_modification", False
                )
            ),
        },
        "representation_audit": aggregation,
        "summary_vehicle_count_used": summary.get("vehicle_count_used"),
    }


def _ab_control_contract(metrics: Mapping[str, Any]) -> dict[str, Any]:
    provenance = dict(metrics.get("provenance") or {})
    return {
        key: value
        for key, value in provenance.items()
        if key not in {"representation", "audit_representation"}
    }


def build_pure_ice_ab_comparison(
    case_a: Mapping[str, Any],
    case_b: Mapping[str, Any],
    *,
    small_exact_parity_passed: bool,
) -> dict[str, Any]:
    controls_match = _ab_control_contract(case_a) == _ab_control_contract(case_b)
    validity_a = dict(case_a.get("validity") or {})
    validity_b = dict(case_b.get("validity") or {})

    def _case_correct(metrics: Mapping[str, Any]) -> bool:
        validity = dict(metrics.get("validity") or {})
        return bool(
            validity.get("served_trips") == validity.get("total_trips")
            and validity.get("duplicate_coverage_count") == 0
            and validity.get("vehicle_overlap_count") == 0
            and validity.get("invalid_transition_count") == 0
            and validity.get("bev_soc_violation_count") == 0
            and validity.get("ice_fuel_violation_count") == 0
            and validity.get("charger_violation_count") == 0
            and abs(float(validity.get("bess_terminal_error_kwh") or 0.0))
            <= 1.0e-6
            and validity.get("physical_validation_accepted")
            and validity.get("rolling_step_count") == 24
            and validity.get("rolling_chain_accepted")
            and validity.get("accounting_eligible")
            and validity.get("accounting_reconciliation_status") == "OK"
            and not validity.get("fallback_used")
            and not validity.get("post_solve_repair_used")
        )

    audit_a = dict(case_a.get("representation_audit") or {})
    audit_b = dict(case_b.get("representation_audit") or {})
    representation_correct = bool(
        audit_a.get("representation") == "discrete"
        and int(audit_a.get("vehicle_label_flow_variable_count_created") or 0)
        > 0
        and int(audit_a.get("aggregate_network_variable_count_created") or 0)
        == 0
        and audit_b.get("representation") == "pure_aggregate"
        and int(audit_b.get("vehicle_label_flow_variable_count_created") or 0)
        == 0
        and int(audit_b.get("aggregate_network_variable_count_created") or 0)
        > 0
    )
    correctness = bool(
        small_exact_parity_passed
        and controls_match
        and representation_correct
        and _case_correct(case_a)
        and _case_correct(case_b)
    )

    size_a = dict(case_a.get("model_size") or {})
    size_b = dict(case_b.get("model_size") or {})
    solve_a = dict(case_a.get("solve_outcome") or {})
    solve_b = dict(case_b.get("solve_outcome") or {})
    timing_a = dict(case_a.get("timing") or {})
    timing_b = dict(case_b.get("timing") or {})

    def _change(key: str, left: Mapping[str, Any], right: Mapping[str, Any]) -> float | None:
        a = left.get(key)
        b = right.get(key)
        if a is None or b is None:
            return None
        return float(b) - float(a)

    total_reduction = -float(
        _change("total_variables", size_a, size_b) or 0.0
    )
    binary_reduction = -float(
        _change("binary_variables", size_a, size_b) or 0.0
    )
    root_change = _change(
        "root_relaxation_bound_jpy", solve_a, solve_b
    )
    certified_gap_change = _change(
        "certified_gap_ratio", solve_a, solve_b
    )
    wall_change = _change("runner_wall_time_sec", timing_a, timing_b)
    build_change = _change(
        "complete_model_build_time_sec", timing_a, timing_b
    )
    gap_improved = bool(
        certified_gap_change is not None and certified_gap_change <= -0.01
    )
    gap_time_a = solve_a.get("requested_gap_reached_time_sec")
    gap_time_b = solve_b.get("requested_gap_reached_time_sec")
    gap_time_improved = bool(
        gap_time_a
        and gap_time_b is not None
        and float(gap_time_b) <= 0.8 * float(gap_time_a)
    )
    root_not_worse = bool(root_change is None or root_change >= -1.0e-6)

    def _not_worse_by_ten_percent(a: Any, b: Any) -> bool:
        if a in (None, 0) or b is None:
            return True
        return float(b) <= 1.1 * float(a)

    runtime_not_worse = bool(
        _not_worse_by_ten_percent(
            timing_a.get("complete_model_build_time_sec"),
            timing_b.get("complete_model_build_time_sec"),
        )
        and _not_worse_by_ten_percent(
            timing_a.get("runner_wall_time_sec"),
            timing_b.get("runner_wall_time_sec"),
        )
    )
    if not correctness:
        verdict = "FAIL_CORRECTNESS"
    elif (
        total_reduction > 0
        and binary_reduction > 0
        and root_not_worse
        and (gap_improved or gap_time_improved)
        and runtime_not_worse
    ):
        verdict = "PASS_PERFORMANCE"
    elif total_reduction > 0 or binary_reduction > 0:
        materially_worse_gap = bool(
            certified_gap_change is not None and certified_gap_change > 0.01
        )
        materially_worse_root = bool(
            root_change is not None and root_change < -1.0e-6
        )
        verdict = (
            "NO_BENEFIT"
            if materially_worse_gap or materially_worse_root
            else "PASS_STRUCTURAL_ONLY"
        )
    else:
        verdict = "NO_BENEFIT"

    return {
        "schema_version": PURE_ICE_AB_SCHEMA_VERSION,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "case_A_discrete": dict(case_a),
        "case_B_pure_aggregate": dict(case_b),
        "correctness": {
            "passed": correctness,
            "small_exact_parity_passed": small_exact_parity_passed,
            "control_contract_match": controls_match,
            "representation_audit_match": representation_correct,
            "case_A_valid": _case_correct(case_a),
            "case_B_valid": _case_correct(case_b),
            "case_A_reported_total_cost_jpy": validity_a.get(
                "reported_total_cost_jpy"
            ),
            "case_B_reported_total_cost_jpy": validity_b.get(
                "reported_total_cost_jpy"
            ),
        },
        "changes": {
            "total_variable_reduction": total_reduction,
            "binary_variable_reduction": binary_reduction,
            "root_bound_change_jpy": root_change,
            "certified_gap_change_ratio": certified_gap_change,
            "runner_wall_time_change_sec": wall_change,
            "model_build_time_change_sec": build_change,
        },
        "verdict": verdict,
    }


PURE_ICE_COMPARISON_METRICS = (
    ("total_variables", "model_size"),
    ("binary_variables", "model_size"),
    ("integer_variables", "model_size"),
    ("continuous_variables", "model_size"),
    ("constraints", "model_size"),
    ("nonzero_coefficients", "model_size"),
    ("ice_label_variables", "model_size"),
    ("aggregate_network_variables", "model_size"),
    ("complete_model_build_time_sec", "timing"),
    ("root_relaxation_time_sec", "timing"),
    ("first_incumbent_time_sec", "timing"),
    ("cost_stage_solve_time_sec", "timing"),
    ("total_solver_time_sec", "timing"),
    ("runner_wall_time_sec", "timing"),
    ("incumbent_objective_jpy", "solve_outcome"),
    ("root_relaxation_bound_jpy", "solve_outcome"),
    ("raw_gurobi_bound_jpy", "solve_outcome"),
    ("certified_best_bound_jpy", "solve_outcome"),
    ("certified_gap_ratio", "solve_outcome"),
    ("explored_nodes", "solve_outcome"),
    ("served_trips", "validity"),
    ("used_ice_vehicles", "validity"),
)


def write_pure_ice_ab_outputs(
    comparison: Mapping[str, Any],
    output_dir: Path,
) -> None:
    case_a = dict(comparison["case_A_discrete"])
    case_b = dict(comparison["case_B_pure_aggregate"])
    (output_dir / "case_A_discrete_metrics.json").write_text(
        json.dumps(case_a, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (output_dir / "case_B_pure_aggregate_metrics.json").write_text(
        json.dumps(case_b, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    rows: list[dict[str, Any]] = []
    for metric, section in PURE_ICE_COMPARISON_METRICS:
        a_value = dict(case_a.get(section) or {}).get(metric)
        b_value = dict(case_b.get(section) or {}).get(metric)
        absolute = None
        relative = None
        if isinstance(a_value, (int, float)) and isinstance(
            b_value, (int, float)
        ):
            absolute = float(b_value) - float(a_value)
            if float(a_value) != 0.0:
                relative = absolute / abs(float(a_value))
        rows.append(
            {
                "metric": metric,
                "A_discrete": a_value,
                "B_pure_aggregate": b_value,
                "absolute_change": absolute,
                "relative_change": relative,
            }
        )
    with (output_dir / "comparison.csv").open(
        "w", encoding="utf-8-sig", newline=""
    ) as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=(
                "metric",
                "A_discrete",
                "B_pure_aggregate",
                "absolute_change",
                "relative_change",
            ),
        )
        writer.writeheader()
        writer.writerows(rows)
    lines = [
        "# Pure ICE aggregation A/B diagnostic",
        "",
        f"- correctness: `{dict(comparison['correctness'])['passed']}`",
        f"- verdict: `{comparison['verdict']}`",
        "- claim scope: diagnostic same-SHA, same-input, single-run A/B",
        "",
        "| Metric | A discrete | B pure aggregate | B - A | Relative |",
        "|---|---:|---:|---:|---:|",
    ]
    for row in rows:
        lines.append(
            "| {metric} | {A_discrete} | {B_pure_aggregate} | "
            "{absolute_change} | {relative_change} |".format(**row)
        )
    lines.extend(
        [
            "",
            "No high/low-PV pair, sensitivity sweep, or decomposition "
            "prototype was run.",
            "",
        ]
    )
    (output_dir / "comparison.md").write_text(
        "\n".join(lines), encoding="utf-8"
    )


def _run_pure_ice_case(
    *,
    scenario_id: str,
    prepared_input_id: str,
    request: Mapping[str, Any],
    representation: str,
    log_path: Path,
) -> tuple[Path, float, str]:
    from bff.routers.optimization import _run_optimization
    from bff.store import job_store
    from src.optimization.milp.solver_adapter import (
        _diagnostic_exact_ice_clone_representation,
    )

    job = job_store.create_job(execution_model="thread")
    started = time.perf_counter()
    with log_path.open("w", encoding="utf-8") as log_handle:
        with redirect_stdout(log_handle), redirect_stderr(log_handle):
            print(
                json.dumps(
                    {
                        "event": "case_started",
                        "representation": representation,
                        "job_id": job.job_id,
                        "started_at_utc": datetime.now(timezone.utc).isoformat(),
                    },
                    ensure_ascii=False,
                )
            )
            with _diagnostic_exact_ice_clone_representation(representation):
                _run_optimization(
                    scenario_id,
                    job.job_id,
                    prepared_input_id,
                    prepared_input_id,
                    str(request.get("mode") or "phase4_integrated"),
                    int(request.get("time_limit_seconds") or 900),
                    float(request.get("mip_gap") or 0.01),
                    int(request.get("random_seed") or 42),
                    str(request.get("service_id") or "WEEKDAY"),
                    str(request.get("depot_id") or "tsurumaki"),
                    bool(request.get("rebuild_dispatch", False)),
                    bool(request.get("use_existing_duties", False)),
                    int(request.get("alns_iterations") or 500),
                    int(request.get("no_improvement_limit") or 100),
                    float(request.get("destroy_fraction") or 0.25),
                    request.get("timestep_min") or request.get("time_step_min"),
                    request.get("enableWeatherOperationPolicy"),
                    request.get("weatherProxyForecastPath"),
                    bool(request.get("research_run", True)),
                    request.get("stage1_time_limit_seconds"),
                    request.get("stage2_time_limit_seconds"),
                    bool(request.get("stage1_best_obj_stop_enabled", False)),
                    int(request.get("gurobi_threads") or 4),
                    str(
                        request.get("run_profile")
                        or "day_ahead_and_hourly_rolling"
                    ),
                    bool(request.get("run_hourly_rolling", True)),
                    int(request.get("rolling_execution_minutes") or 60),
                    dict(request),
                    int(request.get("stage1_stage2_candidate_limit") or 1),
                    int(request.get("stage1_composition_search_radius") or 0),
                    bool(request.get("stage1_bev_frontier_enabled", False)),
                    int(request.get("stage1_bev_frontier_min_count") or 15),
                    int(request.get("stage1_bev_frontier_max_count") or 35),
                    int(
                        request.get(
                            "stage1_bev_frontier_target_time_limit_seconds"
                        )
                        or 120
                    ),
                    bool(request.get("integrated_actual_cost_objective", True)),
                    str(
                        request.get("integrated_ev_utilization_mode")
                        or "disabled"
                    ),
                    request.get("integrated_actual_cost_upper_bound_jpy"),
                    request.get(
                        "integrated_actual_cost_upper_bound_delta_ratio"
                    ),
                    request.get("co2_emissions_cap_kg"),
                )
            print(
                json.dumps(
                    {
                        "event": "case_finished",
                        "representation": representation,
                        "finished_at_utc": datetime.now(timezone.utc).isoformat(),
                    },
                    ensure_ascii=False,
                )
            )
    wall_time = time.perf_counter() - started
    completed_job = job_store.get_job(job.job_id)
    run_dir_text = str(completed_job.metadata.get("run_dir") or "")
    if not run_dir_text:
        raise RuntimeError(
            f"{representation} run produced no run_dir; status="
            f"{completed_job.status}, error={completed_job.error}"
        )
    if completed_job.status != "completed":
        raise RuntimeError(
            f"{representation} run failed; run_dir={run_dir_text}, "
            f"error={completed_job.error}"
        )
    return Path(run_dir_text), wall_time, job.job_id


def run_pure_ice_aggregation_ab(
    *,
    scenario_id: str,
    prepared_input_id: str,
    optimization_request_path: Path,
    output_dir: Path,
    small_exact_parity_passed: bool,
) -> dict[str, Any]:
    if _git_output("status", "--porcelain"):
        raise RuntimeError("A/B diagnostic requires a clean Git worktree")
    git_sha = _git_output("rev-parse", "HEAD")
    request = _read_json(optimization_request_path)
    if str(request.get("prepared_input_id") or "") != prepared_input_id:
        raise ValueError(
            "optimization request prepared_input_id does not match the "
            "requested canonical prepared input"
        )
    prepared_path = (
        REPO_ROOT
        / "output"
        / "prepared_inputs"
        / scenario_id
        / f"{prepared_input_id}.json"
    )
    if not prepared_path.is_file():
        raise FileNotFoundError(
            f"canonical prepared input is missing: {prepared_path}"
        )
    output_dir.mkdir(parents=True, exist_ok=False)
    manifest = {
        "schema_version": PURE_ICE_AB_SCHEMA_VERSION,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "git_sha": git_sha,
        "git_dirty": False,
        "scenario_id": scenario_id,
        "prepared_input_id": prepared_input_id,
        "prepared_input_path": str(prepared_path.resolve()),
        "prepared_input_sha256": _sha256_file(prepared_path),
        "optimization_request_path": str(optimization_request_path.resolve()),
        "optimization_request_sha256": _sha256_file(
            optimization_request_path
        ),
        "optimization_request": request,
        "small_exact_parity_passed": small_exact_parity_passed,
        "execution_contract": {
            "case_order": ["A_discrete", "B_pure_aggregate"],
            "run_count_per_representation": 1,
            "normal_bff_worker_used": True,
            "hourly_rolling_required": True,
            "public_api_or_schema_changed": False,
        },
    }
    manifest_path = output_dir / "request_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    case_a_dir, case_a_wall, case_a_job = _run_pure_ice_case(
        scenario_id=scenario_id,
        prepared_input_id=prepared_input_id,
        request=request,
        representation="discrete",
        log_path=output_dir / "case_A.log",
    )
    case_b_dir, case_b_wall, case_b_job = _run_pure_ice_case(
        scenario_id=scenario_id,
        prepared_input_id=prepared_input_id,
        request=request,
        representation="pure_aggregate",
        log_path=output_dir / "case_B.log",
    )
    case_a = collect_pure_ice_case_metrics(
        case_a_dir,
        representation="discrete",
        runner_wall_time_sec=case_a_wall,
    )
    case_b = collect_pure_ice_case_metrics(
        case_b_dir,
        representation="pure_aggregate",
        runner_wall_time_sec=case_b_wall,
    )
    comparison = build_pure_ice_ab_comparison(
        case_a,
        case_b,
        small_exact_parity_passed=small_exact_parity_passed,
    )
    write_pure_ice_ab_outputs(comparison, output_dir)
    manifest.update(
        {
            "case_A": {
                "job_id": case_a_job,
                "run_dir": str(case_a_dir.resolve()),
                "runner_wall_time_sec": case_a_wall,
            },
            "case_B": {
                "job_id": case_b_job,
                "run_dir": str(case_b_dir.resolve()),
                "runner_wall_time_sec": case_b_wall,
            },
            "verdict": comparison["verdict"],
        }
    )
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    required = (
        "request_manifest.json",
        "case_A_discrete_metrics.json",
        "case_B_pure_aggregate_metrics.json",
        "comparison.csv",
        "comparison.md",
        "case_A.log",
        "case_B.log",
    )
    hashes = {
        name: _sha256_file(output_dir / name)
        for name in required
    }
    (output_dir / "artifact_hashes.json").write_text(
        json.dumps(
            {
                "schema_version": "artifact_hashes_v1",
                "sha256": hashes,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return comparison


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Build a claim-scoped structural/runtime diagnostic for the exact "
            "lazy fragment-transition formulation."
        )
    )
    parser.add_argument(
        "--run-pure-ice-aggregation-ab",
        action="store_true",
        help="Execute one discrete and one pure-aggregate full BFF run.",
    )
    parser.add_argument("--baseline-run", type=Path)
    parser.add_argument("--candidate-run", type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--scenario-id")
    parser.add_argument("--prepared-input-id")
    parser.add_argument("--optimization-request", type=Path)
    parser.add_argument(
        "--small-exact-parity-passed",
        action="store_true",
        help="Record the required focused exact-parity test precondition.",
    )
    args = parser.parse_args()

    if args.run_pure_ice_aggregation_ab:
        missing = [
            name
            for name, value in (
                ("--scenario-id", args.scenario_id),
                ("--prepared-input-id", args.prepared_input_id),
                ("--optimization-request", args.optimization_request),
            )
            if not value
        ]
        if missing:
            parser.error("missing A/B arguments: " + ", ".join(missing))
        if not args.small_exact_parity_passed:
            parser.error(
                "--small-exact-parity-passed is required before a 264-trip A/B run"
            )
        comparison = run_pure_ice_aggregation_ab(
            scenario_id=str(args.scenario_id),
            prepared_input_id=str(args.prepared_input_id),
            optimization_request_path=Path(args.optimization_request),
            output_dir=args.output_dir,
            small_exact_parity_passed=True,
        )
        print(
            json.dumps(
                {
                    "verdict": comparison["verdict"],
                    "output_dir": str(args.output_dir.resolve()),
                },
                ensure_ascii=False,
            )
        )
        return 0

    if args.baseline_run is None or args.candidate_run is None:
        parser.error(
            "--baseline-run and --candidate-run are required for the lazy "
            "fragment comparison"
        )

    comparison = build_comparison(args.baseline_run, args.candidate_run)
    write_comparison_outputs(comparison, args.output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
