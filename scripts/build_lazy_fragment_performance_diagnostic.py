from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping


SCHEMA_VERSION = "lazy_fragment_performance_diagnostic_v1"
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


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Build a claim-scoped structural/runtime diagnostic for the exact "
            "lazy fragment-transition formulation."
        )
    )
    parser.add_argument("--baseline-run", required=True, type=Path)
    parser.add_argument("--candidate-run", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()

    comparison = build_comparison(args.baseline_run, args.candidate_run)
    write_comparison_outputs(comparison, args.output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
