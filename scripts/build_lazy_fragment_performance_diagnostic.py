from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import platform
import statistics
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
PURE_ICE_AB_SCHEMA_VERSION = "pure_ice_aggregation_ab_v4_phase3_repeated_processes"
PURE_ICE_AB_TARGET_PHASE = "phase3_two_stage"
_PHASE4_ONLY_REQUEST_FIELDS = (
    "integrated_actual_cost_objective",
    "integrated_ev_utilization_mode",
    "integrated_actual_cost_upper_bound_jpy",
    "integrated_actual_cost_upper_bound_delta_ratio",
)
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


def compile_phase3_pure_ice_ab_request(
    source_request: Mapping[str, Any],
    *,
    stage1_time_limit_seconds: int | None = None,
    stage2_time_limit_seconds: int | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Compile the explicit Phase-3 request used by every isolated A/B child.

    Earlier evidence accidentally inherited an integrated Phase-4 request. The
    A/B study evaluates the deployed two-stage method, so this narrowly changes
    the mode and removes only Phase-4-only controls; all other supplied
    controls remain byte-for-byte equivalent in the frozen request artifact.
    When supplied, the two explicit stage limits are also frozen.  This is
    required for a fair A/B run because Phase 3 otherwise allocates Stage 2
    time from the candidate pool, which can differ by representation.
    """

    request = dict(source_request)
    source_mode = str(request.get("mode") or "").strip()
    removed_fields = [
        field for field in _PHASE4_ONLY_REQUEST_FIELDS if field in request
    ]
    for field in removed_fields:
        request.pop(field)
    request["mode"] = PURE_ICE_AB_TARGET_PHASE
    fixed_stage_limits: dict[str, int] = {}
    for field, value in (
        ("stage1_time_limit_seconds", stage1_time_limit_seconds),
        ("stage2_time_limit_seconds", stage2_time_limit_seconds),
    ):
        if value is None:
            continue
        if int(value) < 1:
            raise ValueError(f"{field} must be at least one second")
        request[field] = int(value)
        fixed_stage_limits[field] = int(value)
    transformation = {
        "source_mode": source_mode or None,
        "target_mode": PURE_ICE_AB_TARGET_PHASE,
        "removed_phase4_only_fields": removed_fields,
        "only_intended_request_changes": [
            "mode",
            *removed_fields,
            *fixed_stage_limits,
        ],
        "fixed_stage_time_limits": fixed_stage_limits,
    }
    return request, transformation


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


def _total_physical_memory_bytes() -> int | None:
    """Return installed RAM without adding a third-party runtime dependency."""

    if os.name == "nt":
        import ctypes

        class MemoryStatusEx(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        memory_status = MemoryStatusEx()
        memory_status.dwLength = ctypes.sizeof(memory_status)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(memory_status)):
            return int(memory_status.ullTotalPhys)
        return None
    try:
        return int(os.sysconf("SC_PAGE_SIZE")) * int(os.sysconf("SC_PHYS_PAGES"))
    except (AttributeError, OSError, ValueError):
        return None


def _runtime_environment_snapshot() -> dict[str, Any]:
    """Capture the runtime fields required to reproduce a performance result."""

    try:
        import gurobipy as gp

        gurobi_runtime_version: list[int] | None = list(gp.gurobi.version())
        gurobipy_version: str | None = str(getattr(gp, "__version__", "")) or None
    except ImportError:
        gurobi_runtime_version = None
        gurobipy_version = None

    return {
        "python": {
            "implementation": platform.python_implementation(),
            "version": platform.python_version(),
            "executable": str(Path(sys.executable).resolve()),
        },
        "gurobi": {
            "runtime_version": gurobi_runtime_version,
            "gurobipy_version": gurobipy_version,
        },
        "operating_system": {
            "platform": platform.platform(),
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
        },
        "hardware": {
            "processor": platform.processor() or None,
            "logical_cpu_count": os.cpu_count(),
            "total_physical_memory_bytes": _total_physical_memory_bytes(),
        },
    }


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
    stage1_telemetry = dict(
        solver_metadata.get("stage1_search_telemetry") or {}
    )
    stage1_final = dict(stage1_telemetry.get("final") or {})
    presolve_callback_elapsed_sec = stage1_telemetry.get(
        "last_presolve_callback_runtime_sec"
    )
    aggregation = dict(
        plan_metadata.get(
            "stage1_exact_combustion_clone_flow_aggregation_audit"
        )
        or solver_metadata.get(
            "stage1_exact_combustion_clone_flow_aggregation_audit"
        )
        or plan_metadata.get(
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

    duties = [
        dict(item)
        for item in list(canonical.get("duties") or ())
        if isinstance(item, Mapping)
    ]
    served = int(canonical.get("trip_count_served") or 0)
    unserved = int(canonical.get("trip_count_unserved") or 0)
    first_events = [
        dict(item)
        for item in list(stage1_telemetry.get("incumbent_events") or ())
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
            "research_run": bool(settings.get("research_run", False)),
            "research_run_accepted": bool(
                settings.get("research_run_accepted", False)
            ),
            "successor_pruning_enabled": bool(
                settings.get("successor_pruning_enabled", True)
            ),
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
            "requested_phase": settings.get("requested_phase"),
            "resolved_phase": settings.get("resolved_phase"),
            "executed_phase": settings.get("executed_phase"),
            "phase4_seed_enabled": bool(
                solver_metadata.get("phase4_phase3_seed_enabled", False)
            ),
            "stage1_time_limit_sec": settings.get(
                "stage1_time_limit_seconds_effective"
            ),
            "stage2_time_limit_sec": settings.get(
                "stage2_time_limit_seconds_effective"
            ),
            "rolling_step_time_limit_sec": rolling.get("time_limit_sec"),
            "gurobi_parameters": {
                key: solver_metadata.get(key)
                for key in (
                    "gurobi_threads",
                    "stage1_gurobi_feasibility_tol",
                    "stage2_gurobi_feasibility_tol",
                    "stage2_gurobi_integrality_tol",
                )
            },
            "stage1_gurobi_search_controls": dict(
                solver_metadata.get("stage1_gurobi_search_controls") or {}
            ),
        },
        "model_size": {
            "total_variables": solver_metadata.get("stage1_model_variable_count"),
            "binary_variables": solver_metadata.get(
                "stage1_model_binary_variable_count"
            ),
            "integer_variables": solver_metadata.get(
                "stage1_model_integer_variable_count"
            ),
            "continuous_variables": solver_metadata.get(
                "stage1_model_continuous_variable_count"
            ),
            "constraints": solver_metadata.get("stage1_model_constraint_count"),
            "nonzero_coefficients": solver_metadata.get(
                "stage1_model_nonzero_coefficient_count"
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
            "variable_construction_time_sec": None,
            "constraint_construction_time_sec": None,
            "complete_model_build_time_sec": solver_metadata.get(
                "stage1_pre_optimize_seconds"
            ),
            "presolve_time_sec": presolve_callback_elapsed_sec,
            "root_relaxation_time_sec": stage1_telemetry.get(
                "root_relaxation_runtime_sec"
            ),
            "first_incumbent_time_sec": stage1_telemetry.get(
                "first_incumbent_runtime_sec"
            ),
            "cost_stage_solve_time_sec": solver_metadata.get(
                "stage2_runtime_seconds"
            ),
            "total_solver_time_sec": solver_metadata.get(
                "stage1_runtime_seconds"
            ),
            "runner_wall_time_sec": runner_wall_time_sec,
            "availability": {
                "input_preparation_time_sec": "not_separately_instrumented",
                "constraint_construction_time_sec": (
                    "included_in_complete_model_build_time_sec"
                ),
                "presolve_time_sec": (
                    "last_presolve_callback_elapsed_from_stage1_optimize_start;"
                    "not_a_dedicated_gurobi_presolve_duration_attribute"
                    if presolve_callback_elapsed_sec is not None
                    else "no_stage1_presolve_callback_observed"
                ),
            },
        },
        "solve_outcome": {
            "solver_status": solver_metadata.get("stage1_solver_status"),
            "incumbent_objective_jpy": solver_metadata.get(
                "stage1_objective_value"
            ),
            "raw_gurobi_bound_jpy": settings.get(
                "stage1_gurobi_raw_best_bound"
            ),
            "raw_gurobi_gap_ratio": settings.get(
                "stage1_gurobi_raw_mip_gap_ratio"
            ),
            "root_relaxation_bound_jpy": stage1_telemetry.get(
                "root_relaxation_bound"
            ),
            "independent_certified_lower_bound_jpy": solver_metadata.get(
                "stage1_analytical_objective_lower_bound"
            ),
            "certified_best_bound_jpy": settings.get(
                "stage1_certified_best_bound"
            ),
            "certified_gap_ratio": settings.get(
                "stage1_certified_mip_gap_ratio"
            ),
            "explored_nodes": stage1_final.get("explored_node_count"),
            "root_lp_iterations": stage1_telemetry.get(
                "final_simplex_iteration_count"
            ),
            "first_incumbent_objective_jpy": (
                stage1_telemetry.get("first_incumbent_objective")
                if stage1_telemetry.get("first_incumbent_objective") is not None
                else (
                    first_events[0].get("incumbent_objective")
                    if first_events
                    else None
                )
            ),
            "requested_gap_reached_time_sec": stage1_telemetry.get(
                "requested_gap_reached_runtime_sec"
            ),
            "canonical_final_cost_jpy": accounting_cost.get("total_cost"),
            # The parent A/B coordinator populates this from the isolated child
            # process. Gurobi runs in that child process, so this is not the
            # coordinator's own memory footprint.
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
            # These are the relevant optimization-time proxies. The trip-energy
            # input model is recorded separately below; it is a frozen common
            # input, not a representation-specific post-solve substitution.
            "synthetic_pv_fallback_used": bool(
                settings.get("synthetic_pv_fallback_applied", False)
            ),
            "stage1_objective_proxy_used": bool(
                solver_metadata.get(
                    "stage1_energy_cost_proxy_used_in_objective", False
                )
            ),
            "weather_proxy_forecast_used": bool(
                effective.get("weather_proxy_forecast_path")
                or effective.get("weatherProxyForecastPath")
            ),
            "trip_energy_model": effective.get("trip_energy_model"),
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


def _pure_ice_case_valid(metrics: Mapping[str, Any]) -> bool:
    """Apply the non-negotiable run-level correctness contract."""

    validity = dict(metrics.get("validity") or {})
    provenance = dict(metrics.get("provenance") or {})
    return bool(
        bool(provenance.get("git_sha"))
        and not provenance.get("git_dirty")
        and provenance.get("research_run")
        and provenance.get("research_run_accepted")
        and not provenance.get("successor_pruning_enabled")
        and provenance.get("requested_phase") == PURE_ICE_AB_TARGET_PHASE
        and provenance.get("resolved_phase") == PURE_ICE_AB_TARGET_PHASE
        and provenance.get("executed_phase") == PURE_ICE_AB_TARGET_PHASE
        and not provenance.get("phase4_seed_enabled")
        and validity.get("total_trips") == 264
        and validity.get("served_trips") == validity.get("total_trips")
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
        and not validity.get("synthetic_pv_fallback_used")
        and not validity.get("stage1_objective_proxy_used")
        and not validity.get("weather_proxy_forecast_used")
    )


def _pure_ice_representation_audit_valid(
    metrics: Mapping[str, Any],
    representation: str,
) -> bool:
    """Require evidence that the requested representation reached Stage 1."""
    audit = dict(metrics.get("representation_audit") or {})
    if audit.get("representation") != representation:
        return False
    vehicle_label_count = int(
        audit.get("vehicle_label_flow_variable_count_created") or 0
    )
    aggregate_network_count = int(
        audit.get("aggregate_network_variable_count_created") or 0
    )
    if representation == "discrete":
        return bool(
            audit.get("applied") is False
            and audit.get("integer_feasible_set_changed") is False
            and audit.get("recoverable_physical_dispatch_set_changed") is False
            and vehicle_label_count > 0
            and aggregate_network_count == 0
        )
    if representation == "pure_aggregate":
        recovered_path_count = int(audit.get("recovered_path_count") or 0)
        recovered_vehicle_ids = tuple(audit.get("recovered_vehicle_ids") or ())
        return bool(
            audit.get("applied") is True
            and audit.get("integer_feasible_set_changed") is False
            and audit.get("labeled_extended_feasible_region_relaxed") is False
            and audit.get("recoverable_physical_dispatch_set_changed") is False
            and vehicle_label_count == 0
            and aggregate_network_count > 0
            and recovered_path_count > 0
            and recovered_path_count == len(recovered_vehicle_ids)
        )
    raise ValueError(f"unsupported pure-ICE representation: {representation!r}")


def build_pure_ice_ab_comparison(
    case_a: Mapping[str, Any],
    case_b: Mapping[str, Any],
    *,
    small_exact_parity_passed: bool,
) -> dict[str, Any]:
    controls_match = _ab_control_contract(case_a) == _ab_control_contract(case_b)
    validity_a = dict(case_a.get("validity") or {})
    validity_b = dict(case_b.get("validity") or {})

    representation_correct = bool(
        _pure_ice_representation_audit_valid(case_a, "discrete")
        and _pure_ice_representation_audit_valid(case_b, "pure_aggregate")
    )
    correctness = bool(
        small_exact_parity_passed
        and controls_match
        and representation_correct
        and _pure_ice_case_valid(case_a)
        and _pure_ice_case_valid(case_b)
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
            "case_A_valid": _pure_ice_case_valid(case_a),
            "case_B_valid": _pure_ice_case_valid(case_b),
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


REPEATED_PURE_ICE_METRICS = (
    ("total_variables", "model_size"),
    ("binary_variables", "model_size"),
    ("constraints", "model_size"),
    ("nonzero_coefficients", "model_size"),
    ("complete_model_build_time_sec", "timing"),
    ("presolve_time_sec", "timing"),
    ("total_solver_time_sec", "timing"),
    ("runner_wall_time_sec", "timing"),
    ("incumbent_objective_jpy", "solve_outcome"),
    ("certified_best_bound_jpy", "solve_outcome"),
    ("certified_gap_ratio", "solve_outcome"),
    ("explored_nodes", "solve_outcome"),
    ("peak_memory_bytes", "solve_outcome"),
)


def build_pure_ice_alternating_case_plan(
    repetitions: int,
) -> list[dict[str, Any]]:
    """Build AB/BA pairs so each representation has the same run count."""

    if repetitions < 5:
        raise ValueError("A/B diagnostic requires at least five repetitions")
    plan: list[dict[str, Any]] = []
    for pair_index in range(repetitions):
        pair = (
            ("discrete", "pure_aggregate")
            if pair_index % 2 == 0
            else ("pure_aggregate", "discrete")
        )
        for order_in_pair, representation in enumerate(pair, start=1):
            run_index = len(plan) + 1
            label = "A_discrete" if representation == "discrete" else "B_pure_aggregate"
            plan.append(
                {
                    "run_index": run_index,
                    "pair_index": pair_index + 1,
                    "pair_order": "AB" if pair_index % 2 == 0 else "BA",
                    "order_in_pair": order_in_pair,
                    "representation": representation,
                    "label": label,
                }
            )
    return plan


def _quantile(sorted_values: list[float], probability: float) -> float:
    """Return a deterministic linear-interpolated sample quantile."""

    if not sorted_values:
        raise ValueError("cannot compute a quantile of an empty value set")
    position = (len(sorted_values) - 1) * probability
    lower = int(position)
    upper = min(lower + 1, len(sorted_values) - 1)
    fraction = position - lower
    return sorted_values[lower] + (sorted_values[upper] - sorted_values[lower]) * fraction


def _numeric_summary(values: Iterable[Any]) -> dict[str, Any]:
    numeric_values = sorted(
        float(value)
        for value in values
        if isinstance(value, (int, float)) and not isinstance(value, bool)
    )
    if not numeric_values:
        return {
            "count": 0,
            "median": None,
            "q1": None,
            "q3": None,
            "iqr": None,
            "minimum": None,
            "maximum": None,
        }
    q1 = _quantile(numeric_values, 0.25)
    q3 = _quantile(numeric_values, 0.75)
    return {
        "count": len(numeric_values),
        "median": float(statistics.median(numeric_values)),
        "q1": q1,
        "q3": q3,
        "iqr": q3 - q1,
        "minimum": numeric_values[0],
        "maximum": numeric_values[-1],
    }


def _repeated_case_statistics(
    cases: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    collected = [dict(case) for case in cases]
    statistics_by_metric: dict[str, Any] = {}
    for metric, section in REPEATED_PURE_ICE_METRICS:
        values = [dict(case.get(section) or {}).get(metric) for case in collected]
        statistics_by_metric[metric] = _numeric_summary(values)
    return {
        "run_count": len(collected),
        "metrics": statistics_by_metric,
        "presolve_time_availability": sorted(
            {
                str(dict(case.get("timing") or {}).get("availability", {}).get(
                    "presolve_time_sec"
                ))
                for case in collected
            }
        ),
    }


def _summary_median(summary: Mapping[str, Any], metric: str) -> float | None:
    metrics = dict(summary.get("metrics") or {})
    value = dict(metrics.get(metric) or {}).get("median")
    return None if value is None else float(value)


def build_repeated_pure_ice_ab_comparison(
    case_runs: Iterable[Mapping[str, Any]],
    *,
    small_exact_parity_passed: bool,
) -> dict[str, Any]:
    """Evaluate all isolated A/B runs and derive claims from medians only."""

    runs = [dict(run) for run in case_runs]
    discrete_cases = [
        dict(run["metrics"])
        for run in runs
        if str(run.get("representation")) == "discrete"
    ]
    aggregate_cases = [
        dict(run["metrics"])
        for run in runs
        if str(run.get("representation")) == "pure_aggregate"
    ]
    if len(discrete_cases) < 5 or len(aggregate_cases) < 5:
        raise ValueError("A/B comparison requires at least five runs per representation")

    controls = [
        _ab_control_contract(case)
        for case in (*discrete_cases, *aggregate_cases)
    ]
    controls_match = bool(controls) and all(
        control == controls[0] for control in controls
    )

    def _case_correct(metrics: Mapping[str, Any], representation: str) -> bool:
        return bool(
            _pure_ice_representation_audit_valid(metrics, representation)
            and _pure_ice_case_valid(metrics)
        )

    individual_checks = [
        {
            "run_index": run.get("run_index"),
            "representation": run.get("representation"),
            "passed": _case_correct(
                dict(run["metrics"]), str(run.get("representation"))
            ),
        }
        for run in runs
    ]
    correctness = bool(
        small_exact_parity_passed
        and controls_match
        and all(bool(check["passed"]) for check in individual_checks)
    )
    discrete_summary = _repeated_case_statistics(discrete_cases)
    aggregate_summary = _repeated_case_statistics(aggregate_cases)

    def _median_change(metric: str) -> float | None:
        left = _summary_median(discrete_summary, metric)
        right = _summary_median(aggregate_summary, metric)
        return None if left is None or right is None else right - left

    total_reduction = -float(_median_change("total_variables") or 0.0)
    binary_reduction = -float(_median_change("binary_variables") or 0.0)
    gap_change = _median_change("certified_gap_ratio")
    root_change = _median_change("certified_best_bound_jpy")
    solver_time_change = _median_change("total_solver_time_sec")
    wall_time_change = _median_change("runner_wall_time_sec")

    def _not_worse_by_ten_percent(metric: str) -> bool:
        left = _summary_median(discrete_summary, metric)
        right = _summary_median(aggregate_summary, metric)
        return left in (None, 0.0) or right is None or right <= 1.1 * left

    discrete_solver_time = _summary_median(
        discrete_summary, "total_solver_time_sec"
    )
    aggregate_solver_time = _summary_median(
        aggregate_summary, "total_solver_time_sec"
    )
    median_solver_time_improved = bool(
        discrete_solver_time not in (None, 0.0)
        and aggregate_solver_time is not None
        and aggregate_solver_time < discrete_solver_time
    )
    gap_not_materially_worse = bool(
        gap_change is None or gap_change <= 0.01
    )
    root_not_worse = bool(root_change is None or root_change >= -1.0e-6)

    if not correctness:
        verdict = "FAIL_CORRECTNESS"
    elif (
        total_reduction > 0
        and binary_reduction > 0
        and root_not_worse
        and gap_not_materially_worse
        and median_solver_time_improved
        and _not_worse_by_ten_percent("runner_wall_time_sec")
    ):
        verdict = "PASS_PERFORMANCE"
    elif total_reduction > 0 or binary_reduction > 0:
        verdict = "PASS_STRUCTURAL_ONLY"
    else:
        verdict = "NO_BENEFIT"

    return {
        "schema_version": PURE_ICE_AB_SCHEMA_VERSION,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "execution": {
            "run_count": len(runs),
            "run_count_per_representation": {
                "discrete": len(discrete_cases),
                "pure_aggregate": len(aggregate_cases),
            },
            "child_processes_required": True,
            "target_phase": PURE_ICE_AB_TARGET_PHASE,
            "phase4_execution_forbidden": True,
            "case_plan": [
                {
                    key: run.get(key)
                    for key in ("run_index", "pair_index", "pair_order", "order_in_pair", "representation", "label")
                }
                for run in runs
            ],
        },
        "case_runs": runs,
        "aggregate_statistics": {
            "discrete": discrete_summary,
            "pure_aggregate": aggregate_summary,
        },
        "correctness": {
            "passed": correctness,
            "small_exact_parity_passed": small_exact_parity_passed,
            "control_contract_match": controls_match,
            "all_individual_runs_valid": all(
                bool(check["passed"]) for check in individual_checks
            ),
            "individual_run_checks": individual_checks,
            "median_solver_time_improved": median_solver_time_improved,
            "gap_not_materially_worse": gap_not_materially_worse,
            "bound_not_worse": root_not_worse,
        },
        "changes_from_medians": {
            "total_variable_reduction": total_reduction,
            "binary_variable_reduction": binary_reduction,
            "certified_gap_change_ratio": gap_change,
            "certified_bound_change_jpy": root_change,
            "total_solver_time_change_sec": solver_time_change,
            "runner_wall_time_change_sec": wall_time_change,
        },
        "verdict": verdict,
        "claim_scope": (
            "Same-SHA, same-input Phase-3-only isolated-process repeated A/B "
            "diagnostic. "
            "Performance claims require PASS_PERFORMANCE and use medians only."
        ),
    }


def write_repeated_pure_ice_ab_outputs(
    comparison: Mapping[str, Any], output_dir: Path
) -> None:
    """Persist run-level metrics plus median/IQR evidence for the A/B study."""

    (output_dir / "repeated_comparison.json").write_text(
        json.dumps(comparison, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    summaries = dict(comparison["aggregate_statistics"])
    rows: list[dict[str, Any]] = []
    for metric, _section in REPEATED_PURE_ICE_METRICS:
        discrete = dict(dict(summaries["discrete"])["metrics"][metric])
        aggregate = dict(dict(summaries["pure_aggregate"])["metrics"][metric])
        median_change = (
            None
            if discrete["median"] is None or aggregate["median"] is None
            else float(aggregate["median"]) - float(discrete["median"])
        )
        rows.append(
            {
                "metric": metric,
                "discrete_median": discrete["median"],
                "discrete_q1": discrete["q1"],
                "discrete_q3": discrete["q3"],
                "discrete_minimum": discrete["minimum"],
                "discrete_maximum": discrete["maximum"],
                "aggregate_median": aggregate["median"],
                "aggregate_q1": aggregate["q1"],
                "aggregate_q3": aggregate["q3"],
                "aggregate_minimum": aggregate["minimum"],
                "aggregate_maximum": aggregate["maximum"],
                "median_change": median_change,
            }
        )
    csv_fields = tuple(rows[0])
    with (output_dir / "repeated_comparison.csv").open(
        "w", encoding="utf-8-sig", newline=""
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=csv_fields)
        writer.writeheader()
        writer.writerows(rows)
    lines = [
        "# Repeated pure ICE aggregation A/B diagnostic",
        "",
        f"- correctness: `{dict(comparison['correctness'])['passed']}`",
        f"- verdict: `{comparison['verdict']}`",
        f"- target phase: `{dict(comparison['execution'])['target_phase']}`",
        "- order: alternating AB/BA isolated child processes",
        "- claim scope: median-based only; null presolve time means the solver did not expose a separate value.",
        "",
        "| Metric | Discrete median [Q1, Q3] | Aggregate median [Q1, Q3] | B - A |",
        "|---|---:|---:|---:|",
    ]
    for row in rows:
        lines.append(
            f"| {row['metric']} | {row['discrete_median']} [{row['discrete_q1']}, {row['discrete_q3']}] | "
            f"{row['aggregate_median']} [{row['aggregate_q1']}, {row['aggregate_q3']}] | {row['median_change']} |"
        )
    (output_dir / "repeated_comparison.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
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
                if str(request.get("mode") or "") != PURE_ICE_AB_TARGET_PHASE:
                    raise ValueError(
                        "pure-ICE A/B requires an explicit phase3_two_stage request"
                    )
                phase4_fields = [
                    field
                    for field in _PHASE4_ONLY_REQUEST_FIELDS
                    if field in request
                ]
                if phase4_fields:
                    raise ValueError(
                        "pure-ICE A/B request retains Phase-4-only fields: "
                        + ", ".join(phase4_fields)
                    )
                # Keywords deliberately prevent a BFF-worker signature change
                # from silently shifting threads, profile, or cost controls.
                _run_optimization(
                    scenario_id=scenario_id,
                    job_id=job.job_id,
                    prepared_input_id=prepared_input_id,
                    requested_prepared_input_id=prepared_input_id,
                    mode=PURE_ICE_AB_TARGET_PHASE,
                    time_limit_seconds=int(request.get("time_limit_seconds") or 900),
                    mip_gap=float(request.get("mip_gap") or 0.01),
                    random_seed=int(request.get("random_seed") or 42),
                    service_id=str(request.get("service_id") or "WEEKDAY"),
                    depot_id=str(request.get("depot_id") or "tsurumaki"),
                    rebuild_dispatch=bool(request.get("rebuild_dispatch", False)),
                    use_existing_duties=bool(request.get("use_existing_duties", False)),
                    alns_iterations=int(request.get("alns_iterations") or 500),
                    no_improvement_limit=int(request.get("no_improvement_limit") or 100),
                    destroy_fraction=float(request.get("destroy_fraction") or 0.25),
                    timestep_min=request.get("timestep_min") or request.get("time_step_min"),
                    enable_weather_operation_policy=request.get("enableWeatherOperationPolicy"),
                    weather_proxy_forecast_path=request.get("weatherProxyForecastPath"),
                    research_run=bool(request.get("research_run", True)),
                    stage1_time_limit_seconds=request.get("stage1_time_limit_seconds"),
                    stage2_time_limit_seconds=request.get("stage2_time_limit_seconds"),
                    stage1_best_obj_stop_enabled=bool(request.get("stage1_best_obj_stop_enabled", False)),
                    stage1_gurobi_search_profile=str(request.get("stage1_gurobi_search_profile") or "default"),
                    stage1_root_lp_diagnostic_enabled=bool(request.get("stage1_root_lp_diagnostic_enabled", False)),
                    stage1_root_lp_diagnostic_time_limit_seconds=int(request.get("stage1_root_lp_diagnostic_time_limit_seconds", 30) or 30),
                    stage1_root_lp_diagnostic_method=(
                        int(request["stage1_root_lp_diagnostic_method"])
                        if request.get("stage1_root_lp_diagnostic_method") is not None
                        else 2
                    ),
                    stage1_fragment_transition_cut_mode=str(request.get("stage1_fragment_transition_cut_mode") or "lazy"),
                    stage1_powertrain_selector_strengthening=bool(request.get("stage1_powertrain_selector_strengthening", False)),
                    stage1_activation_start_strengthening=bool(request.get("stage1_activation_start_strengthening", False)),
                    gurobi_threads=int(request.get("gurobi_threads") or 4),
                    run_profile=str(request.get("run_profile") or "day_ahead_and_hourly_rolling"),
                    run_hourly_rolling=bool(request.get("run_hourly_rolling", True)),
                    rolling_execution_minutes=int(request.get("rolling_execution_minutes") or 60),
                    frontend_request_payload=dict(request),
                    stage1_stage2_candidate_limit=int(request.get("stage1_stage2_candidate_limit") or 1),
                    stage1_composition_search_radius=int(request.get("stage1_composition_search_radius") or 0),
                    stage1_bev_frontier_enabled=bool(request.get("stage1_bev_frontier_enabled", False)),
                    stage1_bev_frontier_min_count=int(request.get("stage1_bev_frontier_min_count") or 15),
                    stage1_bev_frontier_max_count=int(request.get("stage1_bev_frontier_max_count") or 35),
                    stage1_bev_frontier_target_time_limit_seconds=int(request.get("stage1_bev_frontier_target_time_limit_seconds") or 120),
                    integrated_actual_cost_objective=False,
                    integrated_ev_utilization_mode="disabled",
                    integrated_actual_cost_upper_bound_jpy=None,
                    integrated_actual_cost_upper_bound_delta_ratio=None,
                    co2_emissions_cap_kg=request.get("co2_emissions_cap_kg"),
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


def _read_process_rss_bytes(process_id: int) -> int | None:
    """Read a process's current resident memory without another dependency."""

    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        class ProcessMemoryCountersEx(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
                ("PrivateUsage", ctypes.c_size_t),
            ]

        process_query_information = 0x0400
        process_vm_read = 0x0010
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        kernel32.OpenProcess.argtypes = (
            wintypes.DWORD,
            wintypes.BOOL,
            wintypes.DWORD,
        )
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
        kernel32.CloseHandle.restype = wintypes.BOOL
        psapi.GetProcessMemoryInfo.argtypes = (
            wintypes.HANDLE,
            ctypes.POINTER(ProcessMemoryCountersEx),
            wintypes.DWORD,
        )
        psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
        handle = kernel32.OpenProcess(
            process_query_information | process_vm_read, False, process_id
        )
        if not handle:
            return None
        try:
            counters = ProcessMemoryCountersEx()
            counters.cb = ctypes.sizeof(counters)
            if not psapi.GetProcessMemoryInfo(
                handle, ctypes.byref(counters), counters.cb
            ):
                return None
            return int(counters.WorkingSetSize)
        finally:
            kernel32.CloseHandle(handle)
    status_path = Path(f"/proc/{process_id}/status")
    if status_path.is_file():
        for line in status_path.read_text(encoding="utf-8").splitlines():
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) * 1024
    return None


def _child_process_tree_ids(root_process_id: int) -> set[int]:
    """Return the root plus live descendants, including venv launcher children."""

    if os.name != "nt":
        return {root_process_id}

    import ctypes
    from ctypes import wintypes

    class ProcessEntry32(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.c_void_p),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", ctypes.c_long),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", ctypes.c_wchar * 260),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateToolhelp32Snapshot.argtypes = (wintypes.DWORD, wintypes.DWORD)
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel32.Process32FirstW.argtypes = (
        wintypes.HANDLE,
        ctypes.POINTER(ProcessEntry32),
    )
    kernel32.Process32FirstW.restype = wintypes.BOOL
    kernel32.Process32NextW.argtypes = (
        wintypes.HANDLE,
        ctypes.POINTER(ProcessEntry32),
    )
    kernel32.Process32NextW.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel32.CloseHandle.restype = wintypes.BOOL
    invalid_handle_value = ctypes.c_void_p(-1).value
    handle = kernel32.CreateToolhelp32Snapshot(0x00000002, 0)
    if handle == invalid_handle_value:
        return {root_process_id}
    children_by_parent: dict[int, set[int]] = {}
    try:
        entry = ProcessEntry32()
        entry.dwSize = ctypes.sizeof(entry)
        has_entry = kernel32.Process32FirstW(handle, ctypes.byref(entry))
        while has_entry:
            children_by_parent.setdefault(int(entry.th32ParentProcessID), set()).add(
                int(entry.th32ProcessID)
            )
            entry.dwSize = ctypes.sizeof(entry)
            has_entry = kernel32.Process32NextW(handle, ctypes.byref(entry))
    finally:
        kernel32.CloseHandle(handle)
    process_ids = {root_process_id}
    pending = [root_process_id]
    while pending:
        parent_id = pending.pop()
        for child_id in children_by_parent.get(parent_id, set()):
            if child_id not in process_ids:
                process_ids.add(child_id)
                pending.append(child_id)
    return process_ids


def _run_pure_ice_case_in_child_process(
    *,
    scenario_id: str,
    prepared_input_id: str,
    optimization_request_path: Path,
    representation: str,
    run_directory: Path,
    expected_git_sha: str,
) -> dict[str, Any]:
    """Run exactly one normal BFF worker in an isolated Python process."""

    child_result_path = run_directory / "child_result.json"
    process_log_path = run_directory / "child_process.log"
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--run-pure-ice-aggregation-child",
        "--output-dir",
        str(run_directory.resolve()),
        "--scenario-id",
        scenario_id,
        "--prepared-input-id",
        prepared_input_id,
        "--optimization-request",
        str(optimization_request_path.resolve()),
        "--child-representation",
        representation,
        "--child-result-path",
        str(child_result_path.resolve()),
        "--expected-git-sha",
        expected_git_sha,
    ]
    peak_rss_bytes = 0
    rss_sample_count = 0
    observed_process_ids: set[int] = set()
    started = time.perf_counter()
    with process_log_path.open("w", encoding="utf-8") as log_handle:
        process = subprocess.Popen(
            command,
            cwd=REPO_ROOT,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            text=True,
        )
        while process.poll() is None:
            process_ids = _child_process_tree_ids(process.pid)
            rss_values = [
                _read_process_rss_bytes(process_id)
                for process_id in process_ids
            ]
            sampled_rss_bytes = sum(
                value for value in rss_values if value is not None
            )
            if sampled_rss_bytes > 0:
                peak_rss_bytes = max(peak_rss_bytes, sampled_rss_bytes)
                rss_sample_count += 1
                observed_process_ids.update(
                    process_id
                    for process_id, value in zip(process_ids, rss_values)
                    if value is not None
                )
            time.sleep(0.2)
        process_ids = _child_process_tree_ids(process.pid)
        rss_values = [
            _read_process_rss_bytes(process_id)
            for process_id in process_ids
        ]
        sampled_rss_bytes = sum(value for value in rss_values if value is not None)
        if sampled_rss_bytes > 0:
            peak_rss_bytes = max(peak_rss_bytes, sampled_rss_bytes)
            rss_sample_count += 1
            observed_process_ids.update(
                process_id
                for process_id, value in zip(process_ids, rss_values)
                if value is not None
            )
    wall_time = time.perf_counter() - started
    if process.returncode != 0:
        raise RuntimeError(
            f"{representation} child process failed with exit code "
            f"{process.returncode}; inspect {process_log_path}"
        )
    if rss_sample_count == 0 or peak_rss_bytes <= 0:
        raise RuntimeError(
            "peak RSS was unavailable for isolated child process; refusing "
            "to produce an incomplete performance artifact"
        )
    child_result = _read_json(child_result_path)
    metrics = dict(child_result.get("metrics") or {})
    if not metrics:
        raise RuntimeError(f"child result contains no metrics: {child_result_path}")
    if str(metrics.get("provenance", {}).get("representation")) != representation:
        raise RuntimeError("child result representation does not match its request")
    metrics.setdefault("solve_outcome", {})["peak_memory_bytes"] = peak_rss_bytes
    metrics.setdefault("execution", {}).update(
        {
            "process_isolated": True,
            "child_process_id": process.pid,
            "child_process_command": command,
            "parent_measured_peak_rss_bytes": peak_rss_bytes,
            "rss_scope": "maximum sampled concurrent RSS across child process tree",
            "rss_sample_count": rss_sample_count,
            "observed_process_ids": sorted(observed_process_ids),
            "parent_observed_wall_time_sec": wall_time,
            "child_result_path": str(child_result_path.resolve()),
            "child_process_log_path": str(process_log_path.resolve()),
        }
    )
    return {
        "metrics": metrics,
        "job_id": child_result.get("job_id"),
        "run_dir": child_result.get("run_dir"),
        "runner_wall_time_sec": child_result.get("runner_wall_time_sec"),
        "parent_observed_wall_time_sec": wall_time,
        "peak_rss_bytes": peak_rss_bytes,
        "rss_sample_count": rss_sample_count,
    }


def run_pure_ice_aggregation_child(
    *,
    scenario_id: str,
    prepared_input_id: str,
    optimization_request_path: Path,
    representation: str,
    result_path: Path,
    expected_git_sha: str,
) -> None:
    """Child entrypoint with its own clean-SHA pre/post gate."""

    if _git_output("status", "--porcelain"):
        raise RuntimeError("A/B child requires a clean Git worktree at start")
    if _git_output("rev-parse", "HEAD") != expected_git_sha:
        raise RuntimeError("A/B child SHA differs from the parent frozen SHA")
    request = _read_json(optimization_request_path)
    run_dir, wall_time, job_id = _run_pure_ice_case(
        scenario_id=scenario_id,
        prepared_input_id=prepared_input_id,
        request=request,
        representation=representation,
        log_path=result_path.parent / "bff_worker.log",
    )
    if _git_output("status", "--porcelain"):
        raise RuntimeError("A/B child Git worktree changed during the run")
    if _git_output("rev-parse", "HEAD") != expected_git_sha:
        raise RuntimeError("A/B child SHA drifted during the run")
    metrics = collect_pure_ice_case_metrics(
        run_dir,
        representation=representation,
        runner_wall_time_sec=wall_time,
    )
    if not _pure_ice_representation_audit_valid(metrics, representation):
        observed_audit = dict(metrics.get("representation_audit") or {})
        raise RuntimeError(
            "pure-ICE A/B representation audit is missing or does not match "
            f"the requested child representation {representation!r}: "
            f"{observed_audit!r}"
        )
    phase_provenance = dict(metrics.get("provenance") or {})
    observed_phases = {
        key: phase_provenance.get(key)
        for key in ("requested_phase", "resolved_phase", "executed_phase")
    }
    if any(value != PURE_ICE_AB_TARGET_PHASE for value in observed_phases.values()):
        raise RuntimeError(
            "A/B child did not execute the required Phase-3 method: "
            + json.dumps(observed_phases, sort_keys=True)
        )
    result_path.write_text(
        json.dumps(
            {
                "schema_version": "pure_ice_aggregation_child_result_v1",
                "job_id": job_id,
                "run_dir": str(run_dir.resolve()),
                "runner_wall_time_sec": wall_time,
                "git_sha_before_after": expected_git_sha,
                "metrics": metrics,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def _load_resumable_pure_ice_case_runs(
    *,
    output_dir: Path,
    plan: Iterable[Mapping[str, Any]],
    expected_git_sha: str,
    expected_prepared_input_sha256: str,
) -> dict[int, dict[str, Any]]:
    """Load completed A/B children without accepting partial or drifted runs."""

    completed: dict[int, dict[str, Any]] = {}
    for planned_run in plan:
        run_index = int(planned_run["run_index"])
        expected_name = f"{run_index:02d}_{planned_run['label']}"
        metric_paths = sorted(
            path
            for path in output_dir.rglob("case_metrics.json")
            if path.parent.name == expected_name
        )
        if len(metric_paths) > 1:
            raise RuntimeError(
                "A/B resume found multiple completed artifacts for "
                f"run {run_index}: {metric_paths}"
            )
        if not metric_paths:
            continue

        metrics_path = metric_paths[0]
        child_result_path = metrics_path.parent / "child_result.json"
        metrics = _read_json(metrics_path)
        child_result = _read_json(child_result_path)
        provenance = dict(metrics.get("provenance") or {})
        observed_input_hashes = dict(provenance.get("input_hashes") or {})
        representation = str(planned_run["representation"])
        if str(provenance.get("representation") or "") != representation:
            raise RuntimeError(
                f"A/B resume representation drift in {metrics_path}"
            )
        if str(provenance.get("git_sha") or "") != expected_git_sha:
            raise RuntimeError(f"A/B resume Git SHA drift in {metrics_path}")
        if bool(provenance.get("git_dirty", True)):
            raise RuntimeError(f"A/B resume dirty child in {metrics_path}")
        if (
            observed_input_hashes.get("prepared_source_sha256")
            != expected_prepared_input_sha256
        ):
            raise RuntimeError(
                f"A/B resume prepared-input hash drift in {metrics_path}"
            )
        if not _pure_ice_case_valid(metrics) or not _pure_ice_representation_audit_valid(
            metrics, representation
        ):
            raise RuntimeError(
                f"A/B resume refuses invalid completed child: {metrics_path}"
            )
        completed[run_index] = {
            **dict(planned_run),
            "metrics": metrics,
            "job_id": child_result.get("job_id"),
            "run_dir": child_result.get("run_dir"),
            "runner_wall_time_sec": child_result.get("runner_wall_time_sec"),
            "parent_observed_wall_time_sec": dict(metrics.get("timing") or {}).get(
                "parent_observed_wall_time_sec"
            ),
            "peak_rss_bytes": dict(metrics.get("solve_outcome") or {}).get(
                "peak_memory_bytes"
            ),
            "rss_sample_count": dict(metrics.get("timing") or {}).get(
                "rss_sample_count"
            ),
        }
    return completed


def run_pure_ice_aggregation_ab(
    *,
    scenario_id: str,
    prepared_input_id: str,
    optimization_request_path: Path,
    output_dir: Path,
    small_exact_parity_passed: bool,
    repetitions: int = 5,
    stage1_time_limit_seconds: int | None = None,
    stage2_time_limit_seconds: int | None = None,
    resume: bool = False,
) -> dict[str, Any]:
    if _git_output("status", "--porcelain"):
        raise RuntimeError("A/B diagnostic requires a clean Git worktree")
    git_sha = _git_output("rev-parse", "HEAD")
    source_request = _read_json(optimization_request_path)
    if str(source_request.get("prepared_input_id") or "") != prepared_input_id:
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
    if stage1_time_limit_seconds is None or stage2_time_limit_seconds is None:
        raise ValueError(
            "pure-ICE A/B requires explicit fixed --stage1-time-limit-seconds "
            "and --stage2-time-limit-seconds controls"
        )
    request, request_transformation = compile_phase3_pure_ice_ab_request(
        source_request,
        stage1_time_limit_seconds=stage1_time_limit_seconds,
        stage2_time_limit_seconds=stage2_time_limit_seconds,
    )
    if str(request.get("prepared_input_id") or "") != prepared_input_id:
        raise ValueError(
            "compiled Phase-3 request prepared_input_id does not match the "
            "requested canonical prepared input"
        )
    plan = build_pure_ice_alternating_case_plan(repetitions)
    prepared_input_sha256 = _sha256_file(prepared_path)
    frozen_request_path = output_dir / "frozen_optimization_request.json"
    manifest = {
        "schema_version": PURE_ICE_AB_SCHEMA_VERSION,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "git_sha": git_sha,
        "git_dirty": False,
        "scenario_id": scenario_id,
        "prepared_input_id": prepared_input_id,
        "prepared_input_path": str(prepared_path.resolve()),
        "prepared_input_sha256": prepared_input_sha256,
        "optimization_request_path": str(optimization_request_path.resolve()),
        "source_optimization_request_sha256": _sha256_file(
            optimization_request_path
        ),
        "frozen_optimization_request_path": str(frozen_request_path.resolve()),
        "frozen_optimization_request_sha256": None,
        "runtime_environment": _runtime_environment_snapshot(),
        "solver_controls": {
            "random_seed": request.get("random_seed"),
            "gurobi_threads": request.get("gurobi_threads"),
            "time_limit_seconds": request.get("time_limit_seconds"),
            "mip_gap": request.get("mip_gap"),
            "stage1_time_limit_seconds": request.get("stage1_time_limit_seconds"),
            "stage2_time_limit_seconds": request.get("stage2_time_limit_seconds"),
            "stage1_gurobi_search_profile": request.get("stage1_gurobi_search_profile"),
            "stage1_fragment_transition_cut_mode": request.get("stage1_fragment_transition_cut_mode"),
            "run_profile": request.get("run_profile"),
            "rolling_execution_minutes": request.get("rolling_execution_minutes"),
        },
        "source_optimization_request": source_request,
        "phase3_request_transformation": request_transformation,
        "optimization_request": request,
        "small_exact_parity_passed": small_exact_parity_passed,
        "execution_contract": {
            "case_order": [item["pair_order"] for item in plan[::2]],
            "case_plan": plan,
            "run_count_per_representation": repetitions,
            "separate_child_process_per_run": True,
            "parent_rss_sampling_interval_sec": 0.2,
            "normal_bff_worker_used": True,
            "target_phase": PURE_ICE_AB_TARGET_PHASE,
            "phase4_execution_forbidden": True,
            "hourly_rolling_required": True,
            "stage1_time_limit_seconds": int(stage1_time_limit_seconds),
            "stage2_time_limit_seconds": int(stage2_time_limit_seconds),
            "public_api_or_schema_changed": False,
        },
    }
    manifest_path = output_dir / "request_manifest.json"
    completed_case_runs: dict[int, dict[str, Any]] = {}
    resume_attempt_directory: Path | None = None
    if resume:
        if not output_dir.is_dir():
            raise FileNotFoundError(
                f"A/B resume output directory is missing: {output_dir}"
            )
        if (output_dir / "repeated_comparison.json").exists():
            raise RuntimeError("A/B resume refuses an already-finalized bundle")
        existing_manifest = _read_json(manifest_path)
        expected_manifest = {
            **manifest,
            "frozen_optimization_request_sha256": _sha256_file(
                frozen_request_path
            ),
        }
        required_match = (
            "schema_version",
            "git_sha",
            "scenario_id",
            "prepared_input_id",
            "prepared_input_sha256",
            "frozen_optimization_request_sha256",
            "solver_controls",
            "optimization_request",
            "small_exact_parity_passed",
        )
        if any(
            existing_manifest.get(key) != expected_manifest.get(key)
            for key in required_match
        ):
            raise RuntimeError("A/B resume manifest does not match frozen controls")
        existing_plan = dict(existing_manifest.get("execution_contract") or {}).get(
            "case_plan"
        )
        if existing_plan != plan:
            raise RuntimeError("A/B resume case plan does not match frozen manifest")
        completed_case_runs = _load_resumable_pure_ice_case_runs(
            output_dir=output_dir,
            plan=plan,
            expected_git_sha=git_sha,
            expected_prepared_input_sha256=prepared_input_sha256,
        )
        attempt_index = 1
        while (output_dir / "resume_attempts" / f"attempt_{attempt_index:02d}").exists():
            attempt_index += 1
        resume_attempt_directory = (
            output_dir / "resume_attempts" / f"attempt_{attempt_index:02d}"
        )
        manifest = existing_manifest
        manifest.setdefault("resume_history", []).append(
            {
                "resumed_at_utc": datetime.now(timezone.utc).isoformat(),
                "git_sha": git_sha,
                "completed_run_indices_before_resume": sorted(completed_case_runs),
                "resume_attempt_directory": str(resume_attempt_directory.resolve()),
            }
        )
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    else:
        output_dir.mkdir(parents=True, exist_ok=False)
        frozen_request_path.write_text(
            json.dumps(request, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        manifest["frozen_optimization_request_sha256"] = _sha256_file(
            frozen_request_path
        )
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    case_runs: list[dict[str, Any]] = []
    for planned_run in plan:
        if _git_output("status", "--porcelain"):
            raise RuntimeError("A/B diagnostic Git worktree changed during execution")
        if _git_output("rev-parse", "HEAD") != git_sha:
            raise RuntimeError("A/B diagnostic Git SHA drifted during execution")
        if _sha256_file(prepared_path) != prepared_input_sha256:
            raise RuntimeError("A/B diagnostic prepared input changed during execution")
        run_index = int(planned_run["run_index"])
        if run_index in completed_case_runs:
            case_runs.append(completed_case_runs[run_index])
            continue
        run_root = (
            resume_attempt_directory / "runs"
            if resume_attempt_directory is not None
            else output_dir / "runs"
        )
        run_directory = run_root / f"{run_index:02d}_{planned_run['label']}"
        run_directory.mkdir(parents=True, exist_ok=False)
        child = _run_pure_ice_case_in_child_process(
            scenario_id=scenario_id,
            prepared_input_id=prepared_input_id,
            optimization_request_path=frozen_request_path,
            representation=str(planned_run["representation"]),
            run_directory=run_directory,
            expected_git_sha=git_sha,
        )
        metrics = dict(child["metrics"])
        observed_prepared_hash = dict(
            dict(metrics.get("provenance") or {}).get("input_hashes") or {}
        ).get("prepared_source_sha256")
        if observed_prepared_hash != prepared_input_sha256:
            raise RuntimeError(
                "child run prepared-input hash does not match the frozen input"
            )
        if _sha256_file(prepared_path) != prepared_input_sha256:
            raise RuntimeError("A/B diagnostic prepared input changed during child run")
        (run_directory / "case_metrics.json").write_text(
            json.dumps(metrics, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        case_runs.append({**planned_run, **child, "metrics": metrics})
    if (
        _git_output("status", "--porcelain")
        or _git_output("rev-parse", "HEAD") != git_sha
        or _sha256_file(prepared_path) != prepared_input_sha256
    ):
        raise RuntimeError("A/B diagnostic Git state drifted before finalization")
    comparison = build_repeated_pure_ice_ab_comparison(
        case_runs,
        small_exact_parity_passed=small_exact_parity_passed,
    )
    write_repeated_pure_ice_ab_outputs(comparison, output_dir)
    manifest.update(
        {
            "completed_runs": [
                {
                    key: run.get(key)
                    for key in (
                        "run_index", "pair_index", "pair_order", "representation",
                        "job_id", "run_dir", "runner_wall_time_sec",
                        "parent_observed_wall_time_sec", "peak_rss_bytes",
                        "rss_sample_count",
                    )
                }
                for run in case_runs
            ],
            "verdict": comparison["verdict"],
        }
    )
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    required = (
        "request_manifest.json",
        "repeated_comparison.json",
        "repeated_comparison.csv",
        "repeated_comparison.md",
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
        help="Execute alternating isolated-process discrete/pure-aggregate BFF runs.",
    )
    parser.add_argument(
        "--run-pure-ice-aggregation-child",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--resume-pure-ice-aggregation-ab",
        action="store_true",
        help=(
            "Resume an interrupted pure-ICE A/B bundle after revalidating its "
            "frozen manifest and completed child artifacts."
        ),
    )
    parser.add_argument("--baseline-run", type=Path)
    parser.add_argument("--candidate-run", type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--scenario-id")
    parser.add_argument("--prepared-input-id")
    parser.add_argument("--optimization-request", type=Path)
    parser.add_argument("--ab-repetitions", type=int, default=5)
    parser.add_argument("--stage1-time-limit-seconds", type=int)
    parser.add_argument("--stage2-time-limit-seconds", type=int)
    parser.add_argument("--child-representation", choices=("discrete", "pure_aggregate"))
    parser.add_argument("--child-result-path", type=Path)
    parser.add_argument("--expected-git-sha")
    parser.add_argument(
        "--small-exact-parity-passed",
        action="store_true",
        help="Record the required focused exact-parity test precondition.",
    )
    args = parser.parse_args()

    if (
        args.resume_pure_ice_aggregation_ab
        and not args.run_pure_ice_aggregation_ab
    ):
        parser.error(
            "--resume-pure-ice-aggregation-ab requires "
            "--run-pure-ice-aggregation-ab"
        )

    if args.run_pure_ice_aggregation_child:
        missing = [
            name
            for name, value in (
                ("--scenario-id", args.scenario_id),
                ("--prepared-input-id", args.prepared_input_id),
                ("--optimization-request", args.optimization_request),
                ("--child-representation", args.child_representation),
                ("--child-result-path", args.child_result_path),
                ("--expected-git-sha", args.expected_git_sha),
            )
            if not value
        ]
        if missing:
            parser.error("missing child A/B arguments: " + ", ".join(missing))
        run_pure_ice_aggregation_child(
            scenario_id=str(args.scenario_id),
            prepared_input_id=str(args.prepared_input_id),
            optimization_request_path=Path(args.optimization_request),
            representation=str(args.child_representation),
            result_path=Path(args.child_result_path),
            expected_git_sha=str(args.expected_git_sha),
        )
        return 0

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
            repetitions=int(args.ab_repetitions),
            stage1_time_limit_seconds=args.stage1_time_limit_seconds,
            stage2_time_limit_seconds=args.stage2_time_limit_seconds,
            resume=bool(args.resume_pure_ice_aggregation_ab),
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
