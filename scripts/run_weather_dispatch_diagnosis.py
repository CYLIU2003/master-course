"""Diagnose weather-coupled Phase-3 candidate generation and selection.

The workflow is deliberately split into auditable stages:

* re-read the frozen pure-ICE A/B bundle without changing it;
* generate additional *discrete-representation* Phase-3 candidates through the
  existing isolated BFF worker;
* fix every distinct vehicle-trip assignment and re-optimize only charging,
  PV, and BESS recourse under SUNNY and RAIN;
* select only independently feasible/accounting-consistent candidates by
  canonical actual cost, used-vehicle count, and assignment hash.

It never runs the pure-ICE aggregate representation and never mutates solver
semantics.  Phase 3 remains a two-stage heuristic, not an integrated optimum.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import statistics
import sys
import time
from typing import Any, Iterable, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.build_lazy_fragment_performance_diagnostic import (  # noqa: E402
    _git_output,
    _run_pure_ice_case_in_child_process,
    compile_phase3_pure_ice_ab_request,
)
from scripts.run_pure_ice_aggregation_weather_ab import (  # noqa: E402
    RAIN_SCENARIO_ID,
    REQUIRED_FIXED_HASHES,
    SERVICE_DATE,
    SUNNY_SCENARIO_ID,
    ScenarioInput,
    prepare_fresh_weather_inputs,
)
from scripts.run_frontend_controlled_pv_pair import (  # noqa: E402
    HttpJsonClient,
    _poll_job,
)
from src.dispatch.feasibility import (  # noqa: E402
    FeasibilityEngine,
    evaluate_startup_feasibility,
)
from src.optimization.common.builder import ProblemBuilder  # noqa: E402
from src.optimization.common.evaluator import CostEvaluator  # noqa: E402
from src.optimization.common.feasibility import FeasibilityChecker  # noqa: E402
from src.optimization.common.problem import (  # noqa: E402
    OptimizationConfig,
    OptimizationMode,
)
from src.optimization.engine import OptimizationEngine  # noqa: E402
from src.optimization.rolling.reoptimizer import (  # noqa: E402
    assignment_plan_from_serialized_result,
)
from src.optimization.rolling.acceptance import (  # noqa: E402
    rolling_chain_acceptance_audit,
)


SCHEMA_VERSION = "weather_dispatch_diagnosis_v1"
SCENARIOS = ("SUNNY", "RAIN")
WEATHER_SCENARIO_IDS = {
    "SUNNY": SUNNY_SCENARIO_ID,
    "RAIN": RAIN_SCENARIO_ID,
}
DEFAULT_EXISTING_BUNDLE = (
    REPO_ROOT
    / "output"
    / "diagnostics"
    / "pure_ice_weather_ab_453b1d3_20260827"
)

REQUIRED_CONFIRMATION_INPUT_HASHES = (
    *REQUIRED_FIXED_HASHES,
    "canonical_ablation_input_sha256",
    "prepared_input_sha256",
    "prepared_source_sha256",
    "pv_profile_sha256",
    "pv_hash",
    "trip_input_sha256",
    "fleet_contract_hash",
)

CONFIRMATION_RUN_INPUT_FILES = (
    "summary.json",
    "physical_schedule_validation.json",
    "final_cost_reconciliation.json",
    "rolling_hourly_chain/rolling_chain_summary.json",
    "rolling_hourly_chain/executed_day_accounting.json",
    "stage1_stage2_candidate_evaluation.json",
    "optimization_parameters.json",
    "solver_result.json",
    "canonical_solver_result.json",
)

FIXED_CONFIRMATION_REQUEST_CONTROL_KEYS = (
    "mode",
    "research_run",
    "time_step_min",
    "timestep_min",
    "time_limit_seconds",
    "stage1_time_limit_seconds",
    "stage2_time_limit_seconds",
    "stage1_best_obj_stop_enabled",
    "stage1_powertrain_selector_strengthening",
    "require_all_available_bevs",
    "stage1_stage2_candidate_limit",
    "stage1_composition_search_radius",
    "gurobi_threads",
    "mip_gap",
    "random_seed",
    "run_profile",
    "run_hourly_rolling",
    "rolling_execution_minutes",
    "service_id",
    "depot_id",
)

REQUIRED_EFFECTIVE_FRONTIER_CONTROLS = {
    "stage1_stage2_candidate_limit": 22,
    "stage1_composition_search_radius": 4,
    "stage1_composition_target_time_limit_sec": 60.0,
    "stage1_bev_frontier_enabled": True,
    "stage1_bev_frontier_min_count": 15,
    "stage1_bev_frontier_max_count": 35,
    "stage1_bev_frontier_target_time_limit_sec": 120.0,
}


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def _artifact_identity(path: Path) -> dict[str, Any]:
    """Identify an existing source artifact without rewriting it."""

    resolved = path.resolve()
    if not resolved.is_file():
        raise RuntimeError(f"required finalization input is missing: {resolved}")
    return {
        "path": str(resolved),
        "size_bytes": resolved.stat().st_size,
        "sha256": _sha256_file(resolved),
    }


def _finalization_input_artifacts(
    *,
    output_dir: Path,
    existing_bundle: Path,
    run_dirs: Mapping[str, Path],
    confirmation_dir_name: str,
) -> dict[str, Any]:
    """Hash every raw JSON artifact consumed by read-only finalization."""

    artifacts: dict[str, dict[str, Any]] = {}

    def add(label: str, path: Path) -> None:
        if label in artifacts:
            raise RuntimeError(f"duplicate finalization input label: {label}")
        artifacts[label] = _artifact_identity(path)

    for name in (
        "candidate_discovery_manifest.json",
        "weather_candidate_union.json",
        "cross_weather_fixed_dispatch_matrix.json",
    ):
        add(f"diagnosis/{name}", output_dir / name)

    discovery = _read_json(output_dir / "candidate_discovery_manifest.json")
    preparation_dir = (
        output_dir / confirmation_dir_name / "fresh_prepare" / "preparation"
    )
    for code in SCENARIOS:
        add(
            f"confirmation_request/{code}",
            preparation_dir / code / "frontend_optimization_request.json",
        )
        for relative_path in CONFIRMATION_RUN_INPUT_FILES:
            add(
                f"confirmation_run/{code}/{relative_path}",
                run_dirs[code] / relative_path,
            )

        discovery_run_dir = Path(
            str(dict(discovery["scenarios"][code]).get("run_dir") or "")
        )
        for name in (
            "stage1_stage2_candidate_evaluation.json",
            "solver_result.json",
            "optimization_parameters.json",
        ):
            add(f"candidate_discovery_run/{code}/{name}", discovery_run_dir / name)

        baseline_path = next(
            iter(
                sorted(
                    existing_bundle.glob(
                        f"scenarios/{code}/runs/*_A_discrete/case_metrics.json"
                    )
                )
            ),
            None,
        )
        if baseline_path is None:
            raise RuntimeError(f"missing frozen A baseline for {code}")
        add(f"frozen_A_baseline/{code}/case_metrics.json", baseline_path)

    return {
        "schema_version": "weather_dispatch_finalization_inputs_v1",
        "artifact_count": len(artifacts),
        "artifacts": artifacts,
    }


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_hash(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def assignment_hash_from_rows(rows: Iterable[Mapping[str, Any]]) -> str:
    """Hash the physical vehicle-trip assignment, independent of row order."""

    normalized = sorted(
        (
            str(row.get("trip_id") or ""),
            str(row.get("vehicle_id") or ""),
            str(row.get("duty_id") or ""),
            str(row.get("powertrain") or "").upper(),
        )
        for row in rows
    )
    if not normalized or any(not trip_id or not vehicle_id for trip_id, vehicle_id, _, _ in normalized):
        raise ValueError("assignment rows require non-empty trip_id and vehicle_id")
    if len({trip_id for trip_id, *_ in normalized}) != len(normalized):
        raise ValueError("assignment rows contain duplicate trip IDs")
    return _canonical_hash(normalized)


def deduplicate_candidates(
    candidates: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Deduplicate by physical assignment while retaining all provenance."""

    unique: dict[str, dict[str, Any]] = {}
    for raw in candidates:
        candidate = dict(raw)
        rows = list(candidate.get("vehicle_trip_assignments") or ())
        computed_hash = assignment_hash_from_rows(rows)
        assignment_hash = str(candidate.get("assignment_hash") or computed_hash)
        candidate["source_assignment_hash"] = candidate.get("assignment_hash")
        candidate["assignment_hash"] = computed_hash
        candidate.setdefault("candidate_hash", assignment_hash)
        source = {
            "source_kind": candidate.get("source_kind", "expanded_discrete_A_search"),
            "scenario": candidate.get("source_scenario"),
            "run_dir": candidate.get("source_run_dir"),
            "run_label": candidate.get("source_run_label"),
            "candidate_index": candidate.get("candidate_index"),
            "candidate_hash": candidate.get("candidate_hash"),
            "selected": candidate.get("selected"),
            "selection_rank": candidate.get("candidate_selection_rank"),
            "rejection_reason": candidate.get("rejection_reason"),
        }
        if computed_hash not in unique:
            candidate["provenance"] = [source]
            unique[computed_hash] = candidate
        else:
            unique[computed_hash].setdefault("provenance", []).append(source)
    return [unique[key] for key in sorted(unique)]


def candidate_is_selectable(candidate: Mapping[str, Any]) -> bool:
    """Apply the fail-closed final-candidate correctness gate."""

    try:
        canonical_cost = float(candidate.get("canonical_actual_cost_jpy"))
    except (TypeError, ValueError):
        return False
    return bool(
        candidate.get("selectable") is True
        and candidate.get("stage2_feasible", candidate.get("feasible", False))
        and candidate.get("physical_validation_feasible", False)
        and candidate.get("accounting_reconciliation_passed", False)
        and not candidate.get("fallback_used", False)
        and not candidate.get("repair_used", False)
        and math.isfinite(canonical_cost)
    )


def select_canonical_candidate(
    candidates: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    """Choose canonical cost, then used fleet, then hash deterministically."""

    eligible = [dict(candidate) for candidate in candidates if candidate_is_selectable(candidate)]
    if not eligible:
        raise ValueError("no selectable fixed-dispatch candidate")
    return min(
        eligible,
        key=lambda row: (
            float(row["canonical_actual_cost_jpy"]),
            int(row.get("used_vehicle_count") or 0),
            str(row.get("assignment_hash") or ""),
        ),
    )


def classify_weather_winners(
    sunny_candidates: Iterable[Mapping[str, Any]],
    rain_candidates: Iterable[Mapping[str, Any]],
    *,
    candidate_target: int,
    unique_candidate_count: int,
) -> dict[str, Any]:
    """Return Case A/B/C without inferring coverage that was not achieved."""

    sunny = select_canonical_candidate(sunny_candidates)
    rain = select_canonical_candidate(rain_candidates)
    if unique_candidate_count < candidate_target:
        case = "C"
        verdict = "INCONCLUSIVE_CANDIDATE_COVERAGE"
    elif sunny["assignment_hash"] != rain["assignment_hash"]:
        case = "A"
        verdict = "FIX_REQUIRED_OR_CONFIRMED_AFTER_RERUN"
    else:
        case = "B"
        verdict = "EXPLAINED_PENDING_THRESHOLD_ANALYSIS"
    return {
        "case": case,
        "verdict": verdict,
        "candidate_target": candidate_target,
        "unique_candidate_count": unique_candidate_count,
        "sunny_selected_assignment_hash": sunny["assignment_hash"],
        "rain_selected_assignment_hash": rain["assignment_hash"],
        "same_selected_assignment": sunny["assignment_hash"] == rain["assignment_hash"],
    }


def validate_fixed_dispatch_evidence(
    *,
    requested_assignment_hash: str,
    solved_assignment_hash: str,
    sunny_recourse_hash: str,
    rain_recourse_hash: str,
) -> dict[str, bool]:
    """State the fixed-dispatch and weather-recourse invariants explicitly."""

    return {
        "dispatch_reoptimization_performed": False,
        "energy_recourse_optimization_performed": True,
        "assignment_unchanged": requested_assignment_hash == solved_assignment_hash,
        "scenario_recourse_can_differ": sunny_recourse_hash != rain_recourse_hash,
    }


def _verify_existing_bundle(bundle: Path) -> dict[str, Any]:
    index = _read_json(bundle / "artifact_hashes.json")
    expected = dict(index.get("sha256") or {})
    mismatches = []
    for relative, expected_hash in sorted(expected.items()):
        path = bundle / relative
        observed = _sha256_file(path) if path.is_file() else None
        if observed != expected_hash:
            mismatches.append(
                {"path": relative, "expected": expected_hash, "observed": observed}
            )
    return {
        "indexed_artifact_count": len(expected),
        "hash_mismatch_count": len(mismatches),
        "hash_mismatches": mismatches,
        "accepted": len(expected) == 103 and not mismatches,
    }


def _rolling_runtime(source_run_dir: Path) -> float | None:
    path = source_run_dir / "rolling_hourly_chain" / "rolling_chain_summary.json"
    if not path.is_file():
        return None
    steps = list(_read_json(path).get("steps") or ())
    values = [float(step.get("elapsed_seconds") or 0.0) for step in steps]
    return sum(values) if values else None


def _source_solver_metadata(source_run_dir: Path) -> dict[str, Any]:
    path = source_run_dir / "solver_result.json"
    return dict(_read_json(path).get("solver_metadata") or {}) if path.is_file() else {}


def _runtime_row(metrics_path: Path) -> dict[str, Any]:
    metrics = _read_json(metrics_path)
    source_run_dir = Path(str(metrics.get("run_dir") or ""))
    solver = _source_solver_metadata(source_run_dir)
    timing = dict(metrics.get("timing") or {})
    outcome = dict(metrics.get("solve_outcome") or {})
    model = dict(metrics.get("model_size") or {})
    execution = dict(metrics.get("execution") or {})
    recourse = dict(solver.get("stage1_time_indexed_energy_recourse_result") or {})
    rolling_runtime = _rolling_runtime(source_run_dir)
    wall = execution.get("parent_observed_wall_time_sec", timing.get("runner_wall_time_sec"))
    measured = sum(
        float(value or 0.0)
        for value in (
            timing.get("complete_model_build_time_sec"),
            timing.get("total_solver_time_sec"),
            rolling_runtime,
        )
    )
    residual = max(float(wall) - measured, 0.0) if wall is not None else None
    scenario = next((part for part in metrics_path.parts if part in SCENARIOS), "UNKNOWN")
    return {
        "scenario": scenario,
        "representation": dict(metrics.get("provenance") or {}).get("representation"),
        "run_label": metrics_path.parent.name,
        "source_run_dir": str(source_run_dir),
        "model_build_time_sec": timing.get("complete_model_build_time_sec"),
        "pre_presolve_variables": model.get("total_variables"),
        "pre_presolve_binary_variables": model.get("binary_variables"),
        "pre_presolve_constraints": model.get("constraints"),
        "pre_presolve_nonzeros": model.get("nonzero_coefficients"),
        "post_presolve_variables": None,
        "post_presolve_constraints": None,
        "post_presolve_availability": "not_instrumented_in_frozen_artifacts",
        "presolve_callback_elapsed_sec": timing.get("presolve_time_sec"),
        "root_relaxation_time_sec": timing.get("root_relaxation_time_sec"),
        "root_bound_jpy": outcome.get("root_relaxation_bound_jpy"),
        "first_incumbent_time_sec": timing.get("first_incumbent_time_sec"),
        "incumbent_update_count": solver.get("incumbent_count"),
        "node_count": outcome.get("explored_nodes"),
        "lp_iteration_count": outcome.get("root_lp_iterations"),
        "stage1_termination_reason": solver.get("stage1_termination_reason"),
        "requested_gap_reached": outcome.get("requested_gap_reached_time_sec") is not None,
        "candidate_pool_generated": solver.get("stage1_distinct_candidate_count") or 1,
        "stage2_candidate_count_evaluated": solver.get("stage1_stage2_candidate_count_evaluated") or 1,
        "stage1_runtime_sec": solver.get("stage1_runtime_seconds"),
        "stage2_runtime_sec": solver.get("stage2_runtime_seconds", timing.get("cost_stage_solve_time_sec")),
        "rolling_runtime_sec": rolling_runtime,
        "runner_wall_time_sec": wall,
        "reporting_accounting_artifact_residual_sec": residual,
        "reporting_residual_semantics": "wall_minus_model_build_minus_solver_minus_rolling;not_separately_instrumented",
        "raw_best_bound_jpy": outcome.get("raw_gurobi_bound_jpy"),
        "analytical_lower_bound_jpy": outcome.get("independent_certified_lower_bound_jpy"),
        "certified_best_bound_jpy": outcome.get("certified_best_bound_jpy"),
        "incumbent_jpy": outcome.get("incumbent_objective_jpy"),
        "raw_gap_ratio": outcome.get("raw_gurobi_gap_ratio"),
        "certified_gap_ratio": outcome.get("certified_gap_ratio"),
        "stage1_energy_recourse_enabled": recourse.get("enabled"),
        "stage1_energy_recourse_objective_jpy": recourse.get("objective_jpy"),
        "stage1_energy_recourse_input_hash": recourse.get("recourse_input_hash"),
        "stage1_energy_recourse_charge_input_kwh": recourse.get("charge_input_kwh"),
        "stage1_energy_recourse_grid_import_kwh": recourse.get("grid_import_kwh"),
        "stage1_energy_recourse_pv_to_bus_kwh": recourse.get("pv_to_bus_kwh"),
        "stage1_energy_recourse_pv_to_bess_kwh": recourse.get("pv_to_bess_kwh"),
        "stage1_energy_recourse_bess_to_bus_kwh": recourse.get("bess_to_bus_kwh"),
        "stage1_energy_recourse_pv_curtailment_kwh": recourse.get("pv_curtailment_kwh"),
    }


def _write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = sorted({key for row in rows for key in row})
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    key: (
                        json.dumps(value, ensure_ascii=False, sort_keys=True)
                        if isinstance(value, (dict, list, tuple))
                        else value
                    )
                    for key, value in row.items()
                }
            )


def analyze_existing_bundle(bundle: Path, output_dir: Path) -> dict[str, Any]:
    """Produce runtime and SUNNY/RAIN gap decomposition from frozen evidence."""

    verification = _verify_existing_bundle(bundle)
    if not verification["accepted"]:
        raise RuntimeError(f"existing bundle hash verification failed: {verification}")
    metrics_paths = sorted(bundle.glob("scenarios/*/runs/*/case_metrics.json"))
    rows = [_runtime_row(path) for path in metrics_paths]
    runtime_payload = {
        "schema_version": SCHEMA_VERSION,
        "source_bundle": str(bundle.resolve()),
        "source_bundle_verification": verification,
        "run_count": len(rows),
        "runs": rows,
        "diagnosis": {
            "A": "requested 10% gap reached near 31 seconds; not an exact integrated optimum",
            "B": "Stage 1 consumed the approximately 435 second cap without reaching requested gap",
            "B_parameter_sweep_performed": False,
        },
    }
    _write_json(output_dir / "aggregation_runtime_decomposition.json", runtime_payload)
    _write_csv(output_dir / "aggregation_runtime_decomposition.csv", rows)
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault((str(row["scenario"]), str(row["representation"])), []).append(row)
    medians = []
    for (scenario, representation), members in sorted(grouped.items()):
        medians.append(
            {
                "scenario": scenario,
                "representation": representation,
                "n": len(members),
                "median_stage1_runtime_sec": statistics.median(float(row["stage1_runtime_sec"]) for row in members),
                "median_solver_runtime_sec": statistics.median(float(row["stage1_runtime_sec"]) + float(row["stage2_runtime_sec"]) for row in members),
                "termination_reasons": sorted({str(row["stage1_termination_reason"]) for row in members}),
                "requested_gap_reached_all": all(bool(row["requested_gap_reached"]) for row in members),
            }
        )
    runtime_md = [
        "# Pure-ICE aggregation runtime diagnosis",
        "",
        "The frozen 103-file bundle was re-hashed with zero mismatches. No B run was started.",
        "",
        "A ended after reaching the requested 10% MIP gap (about 31 seconds); this is not proof of exact integrated optimality. B exhausted the roughly 435-second Stage-1 cap and therefore cannot support a runtime-benefit claim.",
        "",
        "Post-presolve row/column counts were not instrumented in the frozen artifacts and are recorded as unavailable rather than reconstructed.",
        "",
        "| scenario | representation | n | median Stage 1 s | termination | gap reached all |",
        "|---|---:|---:|---:|---|---|",
    ]
    for row in medians:
        runtime_md.append(
            f"| {row['scenario']} | {row['representation']} | {row['n']} | "
            f"{row['median_stage1_runtime_sec']:.3f} | {', '.join(row['termination_reasons'])} | "
            f"{row['requested_gap_reached_all']} |"
        )
    (output_dir / "aggregation_runtime_diagnosis.md").write_text("\n".join(runtime_md) + "\n", encoding="utf-8")

    gap_rows = [row for row in rows if row["representation"] == "discrete"]
    gap_payload = {
        "schema_version": SCHEMA_VERSION,
        "scope": "discrete_representation_A_only",
        "runs": gap_rows,
        "median_by_scenario": {
            scenario: {
                key: statistics.median(float(row[key]) for row in gap_rows if row["scenario"] == scenario)
                for key in (
                    "incumbent_jpy",
                    "raw_best_bound_jpy",
                    "analytical_lower_bound_jpy",
                    "certified_best_bound_jpy",
                    "raw_gap_ratio",
                    "certified_gap_ratio",
                    "root_bound_jpy",
                    "lp_iteration_count",
                )
            }
            for scenario in SCENARIOS
        },
        "diagnosis": (
            "The incumbent is identical. The certified-gap difference is bound-side: "
            "RAIN has a higher Gurobi/certified lower bound while SUNNY remains at the "
            "640000 JPY vehicle-use analytical floor."
        ),
    }
    _write_json(output_dir / "sunny_rain_gap_decomposition.json", gap_payload)
    _write_csv(output_dir / "sunny_rain_gap_decomposition.csv", gap_rows)
    med = gap_payload["median_by_scenario"]
    gap_md = (
        "# SUNNY/RAIN certified-gap diagnosis\n\n"
        "This comparison uses only representation A. Both scenarios have the same "
        f"median incumbent ({med['SUNNY']['incumbent_jpy']:.6f} JPY). SUNNY's certified "
        f"bound is {med['SUNNY']['certified_best_bound_jpy']:.6f} JPY, while RAIN's is "
        f"{med['RAIN']['certified_best_bound_jpy']:.6f} JPY. Therefore the observed "
        "9.5213% versus 1.6564% difference is caused by the bound side, not by a better "
        "RAIN incumbent. The SUNNY analytical weather-energy/fuel floor is zero because "
        "the relaxation can cover energy from pooled free PV/BESS while omitting identity, "
        "charger, timing, and other nonnegative costs; the certified floor consequently "
        "falls back to the 32-vehicle usage floor. No unproved bound correction was added.\n"
    )
    (output_dir / "sunny_rain_gap_diagnosis.md").write_text(gap_md, encoding="utf-8")
    return {"runtime": runtime_payload, "gap": gap_payload}


def _assert_clean_sha(expected_sha: str | None = None) -> str:
    dirty = _git_output("status", "--porcelain")
    if dirty:
        raise RuntimeError(f"formal diagnosis requires a clean worktree: {dirty}")
    sha = _git_output("rev-parse", "HEAD")
    if expected_sha is not None and sha != expected_sha:
        raise RuntimeError(f"Git SHA drift: expected {expected_sha}, observed {sha}")
    return sha


def _candidate_request(
    scenario: ScenarioInput,
    *,
    stage1_seconds: int,
    stage2_seconds: int,
    candidate_limit: int,
) -> dict[str, Any]:
    source = _read_json(scenario.optimization_request_path)
    request, _ = compile_phase3_pure_ice_ab_request(
        source,
        stage1_time_limit_seconds=stage1_seconds,
        stage2_time_limit_seconds=stage2_seconds,
    )
    request.update(
        {
            "time_limit_seconds": stage1_seconds + stage2_seconds + 120,
            "stage1_stage2_candidate_limit": candidate_limit,
            "stage1_composition_search_radius": 4,
            "stage1_composition_target_time_limit_seconds": 60.0,
            "stage1_bev_frontier_enabled": True,
            "stage1_bev_frontier_min_count": 15,
            "stage1_bev_frontier_max_count": 35,
            "stage1_bev_frontier_target_time_limit_seconds": 120.0,
            "stage1_powertrain_selector_strengthening": False,
            "stage1_best_obj_stop_enabled": False,
            "gurobi_threads": 1,
        }
    )
    return request


def discover_candidates(
    *,
    output_dir: Path,
    base_url: str,
    existing_bundle: Path,
    stage1_seconds: int,
    stage2_seconds: int,
    candidate_limit: int,
) -> dict[str, Any]:
    """Fresh Prepare and run one expanded A-only candidate search per weather."""

    frozen_sha = _assert_clean_sha()
    started = datetime.now(timezone.utc)
    fresh_dir = output_dir / "fresh_prepare"
    scenarios, prepare_evidence = prepare_fresh_weather_inputs(
        base_url=base_url,
        output_dir=fresh_dir,
        sunny_prepare_request_path=existing_bundle / "preparation" / "SUNNY" / "frontend_prepare_request.json",
        rain_prepare_request_path=existing_bundle / "preparation" / "RAIN" / "frontend_prepare_request.json",
        optimization_template_path=existing_bundle / "preparation" / "SUNNY" / "frontend_optimization_request.json",
        frozen_sha=frozen_sha,
        study_started_at_utc=started,
    )
    results: dict[str, Any] = {}
    for code in SCENARIOS:
        scenario = scenarios[code]
        request = _candidate_request(
            scenario,
            stage1_seconds=stage1_seconds,
            stage2_seconds=stage2_seconds,
            candidate_limit=candidate_limit,
        )
        scenario_dir = output_dir / "candidate_discovery" / code
        request_path = scenario_dir / "expanded_candidate_request.json"
        _write_json(request_path, request)
        result = _run_pure_ice_case_in_child_process(
            scenario_id=scenario.scenario_id,
            prepared_input_id=scenario.prepared_input_id,
            optimization_request_path=request_path,
            representation="discrete",
            run_directory=scenario_dir,
            expected_git_sha=frozen_sha,
        )
        _write_json(scenario_dir / "candidate_discovery_result.json", result)
        results[code] = result
    _assert_clean_sha(frozen_sha)
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "git_sha": frozen_sha,
        "started_at_utc": started.isoformat(),
        "finished_at_utc": datetime.now(timezone.utc).isoformat(),
        "representation": "discrete",
        "pure_ice_aggregate_B_executed": False,
        "fresh_prepare": prepare_evidence,
        "candidate_controls": {
            "candidate_limit": candidate_limit,
            "composition_radius": 4,
            "bev_frontier_enabled": True,
            "stage1_time_limit_seconds": stage1_seconds,
            "stage2_time_limit_seconds": stage2_seconds,
        },
        "scenarios": results,
    }
    _write_json(output_dir / "candidate_discovery_manifest.json", manifest)
    return manifest


def _load_candidate_rows_from_run(code: str, source_run_dir: Path) -> list[dict[str, Any]]:
    path = source_run_dir / "stage1_stage2_candidate_evaluation.json"
    if not path.is_file():
        solver = _read_json(source_run_dir / "solver_result.json")
        solver_metadata = dict(solver.get("solver_metadata") or {})
        candidates = list(
            solver_metadata.get("stage1_stage2_candidate_evaluation") or ()
        )
        selected_candidate_index = int(
            solver_metadata.get("stage1_stage2_selected_candidate_index") or 0
        )
    else:
        candidate_payload = _read_json(path)
        candidates = list(candidate_payload.get("candidates") or ())
        selected_candidate_index = int(
            candidate_payload.get("selected_candidate_index") or 0
        )
    rows = []
    for raw in candidates:
        row = dict(raw)
        row.update(
            {
                "source_kind": "expanded_discrete_A_search",
                "source_scenario": code,
                "source_run_dir": str(source_run_dir.resolve()),
                "selected": int(row.get("candidate_index") or 0)
                == selected_candidate_index,
                "candidate_selection_rank": row.get("candidate_index"),
                "rejection_reason": (
                    None
                    if int(row.get("candidate_index") or 0)
                    == selected_candidate_index
                    else "not_selected_by_source_run"
                ),
            }
        )
        rows.append(row)
    return rows


def _load_existing_a_candidates(existing_bundle: Path) -> list[dict[str, Any]]:
    """Recover the sole candidate from each frozen candidate-limit-one A run."""

    candidates: list[dict[str, Any]] = []
    counts = {code: 0 for code in SCENARIOS}
    for case_metrics_path in sorted(
        existing_bundle.glob("scenarios/*/runs/*_A_discrete/case_metrics.json")
    ):
        metrics = _read_json(case_metrics_path)
        source_scenario = case_metrics_path.parents[2].name.upper()
        if source_scenario not in counts:
            raise RuntimeError(
                f"unexpected existing A scenario: {source_scenario}"
            )
        run_dir = Path(str(metrics.get("run_dir") or ""))
        solver = _read_json(run_dir / "solver_result.json")
        scenario = _read_json(run_dir / "effective_scenario.json")
        powertrain_by_vehicle = {
            str(vehicle.get("id") or ""): str(vehicle.get("type") or "").upper()
            for vehicle in list(scenario.get("vehicles") or ())
        }
        assignment = dict(solver.get("assignment") or {})
        assignment_rows = [
            {
                "duty_id": f"milp_{vehicle_id}",
                "trip_id": str(trip_id),
                "vehicle_id": str(vehicle_id),
                "powertrain": powertrain_by_vehicle.get(str(vehicle_id), ""),
            }
            for vehicle_id, trip_ids in assignment.items()
            for trip_id in list(trip_ids or ())
        ]
        physical_hash = assignment_hash_from_rows(assignment_rows)
        metadata = dict(solver.get("solver_metadata") or {})
        used_vehicle_ids = set(assignment)
        used_bev = sum(
            powertrain_by_vehicle.get(str(vehicle_id)) == "BEV"
            for vehicle_id in used_vehicle_ids
        )
        used_ice = sum(
            powertrain_by_vehicle.get(str(vehicle_id)) == "ICE"
            for vehicle_id in used_vehicle_ids
        )
        bev_trips = sum(
            1
            for row in assignment_rows
            if str(row.get("powertrain") or "").upper() == "BEV"
        )
        ice_trips = len(assignment_rows) - bev_trips
        recourse = dict(
            metadata.get("stage1_time_indexed_energy_recourse_result") or {}
        )
        run_label = case_metrics_path.parent.name
        candidates.append(
            {
                "source_kind": "frozen_existing_A_run",
                "source_scenario": source_scenario,
                "source_run_dir": str(run_dir.resolve()),
                "source_run_label": run_label,
                "candidate_index": 1,
                "candidate_selection_rank": 1,
                "selected": True,
                "rejection_reason": None,
                "candidate_hash": physical_hash,
                "candidate_hash_semantics": (
                    "derived_physical_assignment_hash_because_candidate_limit_one_"
                    "run_has_no_native_candidate_pool_artifact"
                ),
                "assignment_hash": physical_hash,
                "vehicle_trip_assignments": assignment_rows,
                "used_bev": used_bev,
                "used_ice": used_ice,
                "bev_trips": bev_trips,
                "ice_trips": ice_trips,
                "stage1_relaxed_objective_jpy": metadata.get(
                    "stage1_objective"
                ),
                "stage1_recourse_objective_jpy": recourse.get("objective_jpy"),
                "stage2_actual_canonical_cost_jpy": solver.get(
                    "objective_value"
                ),
                "stage2_feasible": (
                    str(metadata.get("stage2_solver_status") or "").lower()
                    == "optimal"
                    and not list(solver.get("unserved_tasks") or ())
                ),
                "physical_validation_feasible": bool(
                    dict(metrics.get("validity") or {}).get(
                        "physical_validation_accepted"
                    )
                ),
                "accounting_reconciliation_passed": (
                    dict(metrics.get("validity") or {}).get(
                        "accounting_reconciliation_status"
                    )
                    == "OK"
                ),
                "stage1_candidate_priority_cost_semantics": (
                    "stage1_weather_aware_relaxed_objective"
                ),
                "stage1_candidate_priority_is_solver_native": True,
            }
        )
        counts[source_scenario] += 1
    if counts != {"SUNNY": 5, "RAIN": 5}:
        raise RuntimeError(f"expected five frozen A runs per scenario: {counts}")
    return candidates


def build_candidate_union(
    output_dir: Path,
    existing_bundle: Path = DEFAULT_EXISTING_BUNDLE,
) -> list[dict[str, Any]]:
    manifest = _read_json(output_dir / "candidate_discovery_manifest.json")
    existing_candidates = _load_existing_a_candidates(existing_bundle)
    expanded_candidates: list[dict[str, Any]] = []
    for code in SCENARIOS:
        source_run_dir = Path(str(dict(manifest["scenarios"][code]).get("run_dir") or ""))
        expanded_candidates.extend(_load_candidate_rows_from_run(code, source_run_dir))
    candidates = [*expanded_candidates, *existing_candidates]
    unique = deduplicate_candidates(candidates)
    existing_unique = deduplicate_candidates(existing_candidates)
    existing_payload = {
        "schema_version": SCHEMA_VERSION,
        "source_bundle": str(existing_bundle.resolve()),
        "source_bundle_sha256_verification": "103_of_103_passed",
        "representation": "discrete_A",
        "candidate_limit_per_run": 1,
        "native_candidate_pool_artifact_available": False,
        "recovery_semantics": (
            "the_authoritative_final_assignment_is_the_sole_candidate_in_each_"
            "candidate_limit_one_run"
        ),
        "run_count": len(existing_candidates),
        "run_count_by_scenario": {
            code: sum(
                row.get("source_scenario") == code for row in existing_candidates
            )
            for code in SCENARIOS
        },
        "unique_physical_assignment_count": len(existing_unique),
        "candidates": existing_candidates,
    }
    _write_json(output_dir / "existing_A_candidate_audit.json", existing_payload)
    _write_csv(
        output_dir / "existing_A_candidate_audit.csv",
        [
            {
                key: value
                for key, value in row.items()
                if key != "vehicle_trip_assignments"
            }
            for row in existing_candidates
        ],
    )
    payload = {
        "schema_version": SCHEMA_VERSION,
        "existing_A_candidates_collected_first": True,
        "existing_A_run_count": len(existing_candidates),
        "existing_A_unique_physical_assignment_count": len(existing_unique),
        "expanded_candidate_count": len(expanded_candidates),
        "candidate_count_before_deduplication": len(candidates),
        "unique_physical_assignment_count": len(unique),
        "target_unique_assignment_count": 12,
        "target_reached": len(unique) >= 12,
        "candidates": unique,
    }
    _write_json(output_dir / "weather_candidate_union.json", payload)
    _write_csv(
        output_dir / "weather_candidate_union.csv",
        [
            {key: value for key, value in row.items() if key != "vehicle_trip_assignments"}
            for row in unique
        ],
    )
    return unique


def _problem_and_config(source_run_dir: Path) -> tuple[Any, OptimizationConfig]:
    scenario = _read_json(source_run_dir / "effective_scenario.json")
    parameters = _read_json(source_run_dir / "optimization_parameters.json")
    effective = dict(parameters.get("effective_optimization_config") or {})
    config = OptimizationConfig(
        mode=OptimizationMode.MILP,
        time_limit_sec=30,
        stage1_time_limit_sec=None,
        stage2_time_limit_sec=30,
        stage1_best_obj_stop_enabled=False,
        gurobi_threads=1,
        mip_gap=float(effective.get("mip_gap") or 0.1),
        random_seed=int(effective.get("random_seed") or 42),
        warm_start=True,
        thesis_mode=False,
        research_run=True,
        allow_postsolve_repair=False,
        phase="phase1_charging_only",
        requested_phase_token="phase1_charging_only",
        requested_phase="phase1_charging_only",
        resolved_phase="phase1_charging_only",
        executed_phase="phase1_charging_only",
    )
    problem = ProblemBuilder().build_from_scenario(
        scenario,
        depot_id="tsurumaki",
        service_id="WEEKDAY",
        config=config,
        planning_days=1,
    )
    return problem, config


def _serialized_assignment(problem: Any, candidate: Mapping[str, Any]) -> dict[str, Any]:
    rows = list(candidate.get("vehicle_trip_assignments") or ())
    trip_lookup = problem.dispatch_context.trips_by_id()
    vehicle_type = {
        str(vehicle.vehicle_id): str(vehicle.vehicle_type).upper()
        for vehicle in problem.vehicles
    }
    vehicle_by_id = {
        str(vehicle.vehicle_id): vehicle
        for vehicle in problem.vehicles
    }
    grouped: dict[str, list[dict[str, Any]]] = {}
    duty_vehicle_map: dict[str, str] = {}
    for row in rows:
        duty_id = str(row.get("duty_id") or "")
        vehicle_id = str(row.get("vehicle_id") or "")
        grouped.setdefault(duty_id, []).append(dict(row))
        previous = duty_vehicle_map.setdefault(duty_id, vehicle_id)
        if previous != vehicle_id:
            raise ValueError(f"duty {duty_id} maps to multiple vehicles")
    feasibility = FeasibilityEngine()
    duties = []
    for duty_id, duty_rows in sorted(grouped.items()):
        duty_rows.sort(key=lambda row: (trip_lookup[str(row["trip_id"])].departure_min, str(row["trip_id"])))
        legs = []
        previous_trip = None
        mapped_vehicle = duty_vehicle_map[duty_id]
        mapped_type = vehicle_type.get(mapped_vehicle, "")
        vehicle = vehicle_by_id.get(mapped_vehicle)
        if vehicle is None:
            raise ValueError(f"candidate duty {duty_id} maps to an unknown vehicle")
        for row in duty_rows:
            trip = trip_lookup[str(row["trip_id"])]
            deadhead = 0
            if previous_trip is None:
                startup = evaluate_startup_feasibility(
                    trip,
                    problem.dispatch_context,
                    str(vehicle.home_depot_id),
                )
                if not startup.feasible:
                    raise ValueError(
                        f"candidate duty {duty_id} has infeasible startup: "
                        f"{startup.reason_code}"
                    )
                deadhead = int(startup.deadhead_time_min or 0)
            else:
                connection = feasibility.can_connect(
                    previous_trip,
                    trip,
                    problem.dispatch_context,
                    mapped_type,
                )
                if not connection.feasible:
                    raise ValueError(f"candidate duty {duty_id} has infeasible transition")
                deadhead = int(connection.deadhead_time_min or 0)
            legs.append({"trip_id": str(trip.trip_id), "deadhead_from_prev_min": deadhead})
            previous_trip = trip
        duties.append({"duty_id": duty_id, "vehicle_type": mapped_type, "legs": legs})
    served = sorted(str(row["trip_id"]) for row in rows)
    return {
        "duties": duties,
        "served_trip_ids": served,
        "unserved_trip_ids": [],
        "metadata": {
            "duty_vehicle_map": duty_vehicle_map,
            "source": "weather_dispatch_candidate_union_fixed_assignment",
        },
    }


def _plan_assignment_hash(plan: Any, problem: Any) -> str:
    vehicle_type = {
        str(vehicle.vehicle_id): str(vehicle.vehicle_type).upper()
        for vehicle in problem.vehicles
    }
    rows = []
    for duty in plan.duties:
        vehicle_id = plan.vehicle_id_for_duty(duty.duty_id)
        for leg in duty.legs:
            rows.append(
                {
                    "duty_id": duty.duty_id,
                    "trip_id": leg.trip.trip_id,
                    "vehicle_id": vehicle_id,
                    "powertrain": vehicle_type.get(vehicle_id, ""),
                }
            )
    return assignment_hash_from_rows(rows)


def _flow_hash(plan: Any) -> str:
    return _canonical_hash(
        {
            "grid": plan.grid_to_bus_kwh_by_depot_slot,
            "pv_bus": plan.pv_to_bus_kwh_by_depot_slot,
            "pv_bess": plan.pv_to_bess_kwh_by_depot_slot,
            "bess_bus": plan.bess_to_bus_kwh_by_depot_slot,
            "curtail": plan.pv_curtail_kwh_by_depot_slot,
        }
    )


def _fixed_dispatch_evaluation(
    problem: Any,
    config: OptimizationConfig,
    candidate: Mapping[str, Any],
) -> dict[str, Any]:
    serialized = _serialized_assignment(problem, candidate)
    fixed_plan = assignment_plan_from_serialized_result(problem, serialized)
    requested_hash = _plan_assignment_hash(fixed_plan, problem)
    solved = OptimizationEngine().solve(problem, replace(config, fixed_assignment=fixed_plan))
    solved_hash = _plan_assignment_hash(solved.plan, problem)
    physical = FeasibilityChecker().evaluate(problem, solved.plan)
    evaluated = CostEvaluator().evaluate(problem, solved.plan)
    metadata = dict(solved.solver_metadata or {})
    result_total = float(dict(solved.cost_breakdown or {}).get("total_cost", math.inf))
    accounting_delta = abs(float(evaluated.total_cost) - result_total)
    used_vehicle_count = len(solved.plan.duties_by_vehicle())
    accepted = bool(
        solved.feasible
        and physical.feasible
        and evaluated.evaluation_feasible
        and solved_hash == requested_hash
        and not solved.plan.unserved_trip_ids
        and len(solved.plan.served_trip_ids) == len(problem.trips) == 264
        and str(metadata.get("stage2_solver_status") or "").lower() == "optimal"
        and not metadata.get("postsolve_repair_applied", False)
        and accounting_delta <= 1.0e-6
    )
    costs = dict(solved.cost_breakdown or {})
    return {
        "assignment_hash": requested_hash,
        "solved_assignment_hash": solved_hash,
        "canonical_actual_cost_jpy": float(evaluated.total_cost),
        "used_vehicle_count": used_vehicle_count,
        "stage2_feasible": bool(solved.feasible),
        "physical_validation_feasible": bool(physical.feasible),
        "physical_validation_errors": list(physical.errors),
        "accounting_reconciliation_passed": accounting_delta <= 1.0e-6,
        "accounting_reconciliation_delta_jpy": accounting_delta,
        "fallback_used": bool(metadata.get("fallback_used", False)),
        "repair_used": bool(metadata.get("postsolve_repair_applied", False)),
        "selectable": accepted,
        "dispatch_reoptimization_performed": False,
        "energy_recourse_optimization_performed": True,
        "assignment_unchanged": solved_hash == requested_hash,
        "stage2_solver_status": metadata.get("stage2_solver_status"),
        "stage2_runtime_seconds": metadata.get("stage2_runtime_seconds"),
        "recourse_hash": _flow_hash(solved.plan),
        "costs_jpy": {
            key: costs.get(key)
            for key in (
                "electricity_cost",
                "fuel_cost",
                "vehicle_usage_cost",
                "demand_cost",
                "degradation_cost",
                "stationary_battery_degradation_cost",
            )
        },
        "energy": {
            key: costs.get(key)
            for key in (
                "grid_import_kwh",
                "pv_to_bus_kwh",
                "pv_to_bess_kwh",
                "bess_to_bus_kwh",
                "pv_curtail_kwh",
                "peak_grid_kw",
            )
        },
        "minimum_bev_soc_kwh": metadata.get("minimum_bev_soc_kwh"),
        "terminal_bev_soc_kwh_total": metadata.get("terminal_bev_soc_kwh_total"),
        "terminal_bess_soc_kwh_total": metadata.get("terminal_bess_soc_kwh_total"),
    }


def cross_evaluate(output_dir: Path) -> dict[str, Any]:
    evaluation_git_sha = _assert_clean_sha()
    unique = list(_read_json(output_dir / "weather_candidate_union.json").get("candidates") or ())
    discovery = _read_json(output_dir / "candidate_discovery_manifest.json")
    contexts = {}
    for code in SCENARIOS:
        source_run_dir = Path(str(dict(discovery["scenarios"][code]).get("run_dir") or ""))
        contexts[code] = _problem_and_config(source_run_dir)
    matrix_rows = []
    by_scenario: dict[str, list[dict[str, Any]]] = {code: [] for code in SCENARIOS}
    for candidate in unique:
        for code in SCENARIOS:
            problem, config = contexts[code]
            started = time.perf_counter()
            row = _fixed_dispatch_evaluation(problem, config, candidate)
            row.update(
                {
                    "scenario": code,
                    "source_candidate_hash": candidate.get("candidate_hash"),
                    "evaluation_wall_time_sec": time.perf_counter() - started,
                }
            )
            matrix_rows.append(row)
            by_scenario[code].append(row)
    verdict = classify_weather_winners(
        by_scenario["SUNNY"],
        by_scenario["RAIN"],
        candidate_target=12,
        unique_candidate_count=len(unique),
    )
    sunny_selected = select_canonical_candidate(by_scenario["SUNNY"])
    rain_selected = select_canonical_candidate(by_scenario["RAIN"])
    fixed_evidence = validate_fixed_dispatch_evidence(
        requested_assignment_hash=sunny_selected["assignment_hash"],
        solved_assignment_hash=sunny_selected["solved_assignment_hash"],
        sunny_recourse_hash=sunny_selected["recourse_hash"],
        rain_recourse_hash=next(
            row["recourse_hash"]
            for row in by_scenario["RAIN"]
            if row["assignment_hash"] == sunny_selected["assignment_hash"]
        ),
    )
    payload = {
        "schema_version": SCHEMA_VERSION,
        "evaluation_git_sha": evaluation_git_sha,
        "candidate_discovery_git_sha": discovery.get("git_sha"),
        "git_dirty_before_after": False,
        "candidate_count": len(unique),
        "dispatch_reoptimization_performed": False,
        "energy_recourse_optimization_performed": True,
        "verdict": verdict,
        "fixed_dispatch_evidence": fixed_evidence,
        "selected": {"SUNNY": sunny_selected, "RAIN": rain_selected},
        "rows": matrix_rows,
    }
    _assert_clean_sha(evaluation_git_sha)
    _write_json(output_dir / "cross_weather_fixed_dispatch_matrix.json", payload)
    _write_csv(output_dir / "cross_weather_fixed_dispatch_matrix.csv", matrix_rows)
    md = [
        "# Cross-weather fixed-dispatch matrix",
        "",
        f"Verdict: **{verdict['verdict']}** (Case {verdict['case']}).",
        "",
        "Dispatch was fixed for every row; only charging/PV/BESS recourse was optimized.",
        "",
        "| scenario | assignment | selectable | canonical cost JPY | used vehicles | recourse hash |",
        "|---|---|---:|---:|---:|---|",
    ]
    for row in sorted(matrix_rows, key=lambda item: (str(item["scenario"]), float(item["canonical_actual_cost_jpy"]))):
        md.append(
            f"| {row['scenario']} | {str(row['assignment_hash'])[:12]} | {row['selectable']} | "
            f"{float(row['canonical_actual_cost_jpy']):.6f} | {row['used_vehicle_count']} | "
            f"{str(row['recourse_hash'])[:12]} |"
        )
    (output_dir / "cross_weather_fixed_dispatch_matrix.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    return payload


def _normal_confirmation_request(scenario: ScenarioInput) -> dict[str, Any]:
    """Build the public-path request whose narrow controls the policy broadens."""

    request = _read_json(scenario.optimization_request_path)
    request.update(
        {
            "mode": "phase3_two_stage",
            "research_run": True,
            "prepared_input_id": scenario.prepared_input_id,
            "service_id": "WEEKDAY",
            "depot_id": "tsurumaki",
            "stage1_stage2_candidate_limit": 1,
            "stage1_composition_search_radius": 0,
            "stage1_bev_frontier_enabled": False,
        }
    )
    expected_controls = {
        "time_step_min": 15,
        "timestep_min": 15,
        "time_limit_seconds": 585,
        "stage1_time_limit_seconds": 435,
        "stage2_time_limit_seconds": 30,
        "stage1_powertrain_selector_strengthening": False,
        "require_all_available_bevs": False,
        "stage1_best_obj_stop_enabled": False,
        "gurobi_threads": 1,
        "mip_gap": 0.1,
        "random_seed": 42,
        "run_profile": "day_ahead_and_hourly_rolling",
        "run_hourly_rolling": True,
        "rolling_execution_minutes": 60,
    }
    mismatches = {
        key: {"expected": expected, "observed": request.get(key)}
        for key, expected in expected_controls.items()
        if request.get(key) != expected
    }
    if mismatches:
        raise RuntimeError(
            f"normal confirmation request drifted from frozen controls: {mismatches}"
        )
    return request


def _powertrain_selector_is_disabled(
    frontend_request: Mapping[str, Any],
    solver_metadata: Mapping[str, Any],
) -> bool:
    """Verify selector OFF at its request and model-build evidence endpoints."""

    return bool(
        frontend_request.get("stage1_powertrain_selector_strengthening") is False
        and solver_metadata.get(
            "stage1_powertrain_selector_strengthening_enabled"
        )
        is False
    )


def _rolling_chain_is_accepted(rolling: Mapping[str, Any]) -> bool:
    """Require every shared Rolling acceptance invariant, not only 24 steps."""

    return bool(rolling_chain_acceptance_audit(rolling)["accepted"])


def _day_ahead_research_is_accepted(summary: Mapping[str, Any]) -> bool:
    """Keep physical feasibility separate from full research acceptance."""

    return bool(
        dict(summary.get("solution_validity") or {}).get(
            "research_acceptance_status"
        )
        == "ACCEPTED"
    )


def _executed_day_total_cost_jpy(accounting: Mapping[str, Any]) -> float:
    """Return the unique accepted Rolling-day cost, failing on split totals."""

    if accounting.get("eligible") is not True:
        raise RuntimeError("executed-day accounting is not eligible")
    breakdown = dict(accounting.get("cost_breakdown") or {})
    totals: dict[str, float] = {}
    for key in ("total_cost", "total_cost_with_assets", "objective_value"):
        value = breakdown.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise RuntimeError(f"executed-day accounting lacks numeric {key}")
        numeric = float(value)
        if not math.isfinite(numeric):
            raise RuntimeError(f"executed-day accounting has non-finite {key}")
        totals[key] = numeric
    if max(totals.values()) - min(totals.values()) > 1.0e-6:
        raise RuntimeError(f"executed-day accounting totals disagree: {totals}")
    return totals["total_cost"]


def _confirmation_gate(run_dir: Path, expected_sha: str) -> dict[str, Any]:
    summary = _read_json(run_dir / "summary.json")
    physical = _read_json(run_dir / "physical_schedule_validation.json")
    accounting = _read_json(run_dir / "final_cost_reconciliation.json")
    rolling = _read_json(
        run_dir / "rolling_hourly_chain" / "rolling_chain_summary.json"
    )
    executed_day_accounting = _read_json(
        run_dir / "rolling_hourly_chain" / "executed_day_accounting.json"
    )
    executed_day_total_cost_jpy = _executed_day_total_cost_jpy(
        executed_day_accounting
    )
    candidates = _read_json(run_dir / "stage1_stage2_candidate_evaluation.json")
    parameters = _read_json(run_dir / "optimization_parameters.json")
    solver_result = _read_json(run_dir / "solver_result.json")
    canonical_solver_result = _read_json(run_dir / "canonical_solver_result.json")
    frontend_request_envelope = dict(parameters.get("frontend_request") or {})
    frontend_request = dict(
        frontend_request_envelope.get("raw_frontend_body")
        or frontend_request_envelope
    )
    bev_utilization_policy = dict(
        frontend_request_envelope.get("interactive_bev_utilization_policy") or {}
    )
    effective_config = dict(parameters.get("effective_optimization_config") or {})
    canonical_inputs = dict(parameters.get("canonical_input_dimensions") or {})
    runtime_controls = dict(summary.get("interactive_runtime_controls") or {})
    requested_runtime_controls = dict(runtime_controls.get("requested") or {})
    effective_runtime_controls = dict(runtime_controls.get("effective") or {})
    stage1_recourse_configuration = dict(
        dict(solver_result.get("solver_metadata") or {}).get(
            "stage1_time_indexed_energy_recourse_configuration"
        )
        or {}
    )
    model_build_metadata = dict(canonical_solver_result.get("metadata") or {})
    selected_index = int(candidates.get("selected_candidate_index") or 0)
    candidate_rows = list(candidates.get("candidates") or ())
    if selected_index <= 0 or selected_index > len(candidate_rows):
        raise RuntimeError("normal confirmation lacks a valid selected candidate index")
    selected = dict(candidate_rows[selected_index - 1])
    selected_physical_hash = assignment_hash_from_rows(
        selected.get("vehicle_trip_assignments") or ()
    )
    acceptance_checks = dict(
        dict(summary.get("solution_validity") or {}).get(
            "research_acceptance_checks"
        )
        or {}
    )
    checks = {
        "served_264": int(summary.get("trip_count_served") or 0) == 264,
        "unserved_zero": int(summary.get("trip_count_unserved", -1)) == 0,
        "physical_validation_passed": physical.get("accepted") is True,
        "rolling_24_of_24": (
            int(rolling.get("expected_step_count") or 0) == 24
            and int(rolling.get("step_count") or 0) == 24
            and _rolling_chain_is_accepted(rolling)
        ),
        "accounting_reconciliation_passed": accounting.get("status") == "OK",
        "git_sha_matches": (
            str(rolling.get("day_ahead_git_sha") or "") == expected_sha
            and str(rolling.get("rolling_runner_git_sha") or "") == expected_sha
            and rolling.get("rolling_runner_git_dirty") is False
        ),
        "fallback_and_repair_absent": (
            acceptance_checks.get("no_fallback") is True
            and acceptance_checks.get("no_postsolve_modification") is True
            and not bool(selected.get("fallback_used", False))
            and not bool(selected.get("repair_used", False))
        ),
        "day_ahead_research_acceptance_passed": (
            _day_ahead_research_is_accepted(summary)
        ),
        "candidate_coverage_applied": (
            int(candidates.get("requested_candidate_limit") or 0) >= 22
            and int(candidates.get("composition_search_radius_requested") or 0)
            >= 4
            and int(candidates.get("candidate_count_evaluated") or 0) >= 12
        ),
        "frozen_runtime_controls_preserved": (
            runtime_controls.get("scope") == "research_batch_run"
            and runtime_controls.get("override_applied") is False
            and requested_runtime_controls.get("gurobi_threads") == 1
            and effective_runtime_controls.get("gurobi_threads") == 1
            and effective_config.get("gurobi_threads") == 1
            and int(rolling.get("gurobi_threads") or 0) == 1
        ),
        "frozen_solver_limits_preserved": (
            int(effective_config.get("time_limit_sec") or 0) == 585
            and int(effective_config.get("stage1_time_limit_sec") or 0) == 435
            and int(effective_config.get("stage2_time_limit_sec") or 0) == 30
            and float(effective_config.get("mip_gap") or -1.0) == 0.1
            and int(effective_config.get("random_seed") or -1) == 42
            and effective_config.get("stage1_best_obj_stop_enabled") is False
            # The selector flag is a request/model-build control.  Older
            # effective-config schemas omit it, so verify both authoritative
            # endpoints instead of treating an omitted derived key as ON.
            and _powertrain_selector_is_disabled(
                frontend_request,
                model_build_metadata,
            )
        ),
        "effective_frontier_controls_preserved": all(
            effective_config.get(key) == expected
            for key, expected in REQUIRED_EFFECTIVE_FRONTIER_CONTROLS.items()
        ),
        "bev_utilization_policy_preserved": (
            frontend_request.get("require_all_available_bevs") is False
            and bev_utilization_policy.get("enabled") is False
            and int(bev_utilization_policy.get("minimum_used_bev_count") or 0) == 0
            and bev_utilization_policy.get("mathematical_effect")
            == "no additional minimum-BEV-use constraint"
        ),
        "executed_day_accounting_is_authoritative": (
            executed_day_accounting.get("eligible") is True
            and int(executed_day_accounting.get("expected_slot_count") or 0) == 96
            and int(executed_day_accounting.get("executed_slot_count") or 0) == 96
            and not list(executed_day_accounting.get("missing_slots") or ())
            and not list(executed_day_accounting.get("duplicate_slots") or ())
        ),
        "stage1_weather_recourse_used_in_objective": (
            stage1_recourse_configuration.get("used_in_stage1_objective") is True
        ),
    }
    if not all(checks.values()):
        raise RuntimeError(f"normal confirmation gate failed: {checks}")
    return {
        "run_dir": str(run_dir.resolve()),
        "checks": checks,
        "selected_candidate_index": selected_index,
        "selected_internal_assignment_hash": selected.get("assignment_hash"),
        "selected_physical_assignment_hash": selected_physical_hash,
        "day_ahead_selected_canonical_actual_cost_jpy": candidates.get(
            "selected_canonical_actual_cost_jpy"
        ),
        "executed_day_accounting_total_cost_jpy": executed_day_total_cost_jpy,
        "final_cost_source": (
            "rolling_hourly_chain/executed_day_accounting.json:"
            "cost_breakdown.total_cost"
        ),
        "candidate_count_evaluated": candidates.get("candidate_count_evaluated"),
        "prepared_input_id": rolling.get("prepared_input_id"),
        "service_date": rolling.get("service_date"),
        "calendar_policy": rolling.get("calendar_policy"),
        "prepared_input_sha256": rolling.get("prepared_input_sha256"),
        "trip_input_hash": rolling.get("trip_input_hash"),
        "vehicle_input_hash": rolling.get("vehicle_input_hash"),
        "fleet_contract_hash": rolling.get("scenario_fleet_contract_hash"),
        "day_ahead_assignment_hash": rolling.get("day_ahead_assignment_hash"),
        "runtime_controls": runtime_controls,
        "interactive_bev_utilization_policy": bev_utilization_policy,
        # Persist the complete effective configuration. A hand-maintained
        # whitelist previously omitted frontier bounds and target budgets.
        "effective_solver_controls": effective_config,
        "canonical_input_hashes": canonical_inputs,
        "stage1_time_indexed_energy_recourse_configuration": (
            stage1_recourse_configuration
        ),
    }


def confirm_normal_runs(
    *,
    output_dir: Path,
    base_url: str,
    existing_bundle: Path,
    confirmation_dir_name: str = "normal_path_confirmation",
) -> dict[str, Any]:
    """Fresh Prepare and validate one public normal-path run per weather case."""

    frozen_sha = _assert_clean_sha()
    started = datetime.now(timezone.utc)
    confirmation_dir = output_dir / confirmation_dir_name
    confirmation_dir.mkdir(parents=True, exist_ok=False)
    scenarios, prepare_evidence = prepare_fresh_weather_inputs(
        base_url=base_url,
        output_dir=confirmation_dir / "fresh_prepare",
        sunny_prepare_request_path=(
            existing_bundle / "preparation" / "SUNNY" / "frontend_prepare_request.json"
        ),
        rain_prepare_request_path=(
            existing_bundle / "preparation" / "RAIN" / "frontend_prepare_request.json"
        ),
        optimization_template_path=(
            existing_bundle
            / "preparation"
            / "SUNNY"
            / "frontend_optimization_request.json"
        ),
        frozen_sha=frozen_sha,
        study_started_at_utc=started,
    )
    client = HttpJsonClient(base_url)
    results: dict[str, Any] = {}
    progress_log: list[dict[str, Any]] = []
    for code in SCENARIOS:
        scenario = scenarios[code]
        case_dir = confirmation_dir / code
        case_dir.mkdir(parents=True, exist_ok=False)
        request = _normal_confirmation_request(scenario)
        _write_json(case_dir / "frontend_optimization_request.json", request)
        submit, _ = client.request_json(
            "POST",
            f"/api/scenarios/{scenario.scenario_id}/run-optimization",
            request,
            timeout_seconds=180.0,
        )
        job_id = str(submit.get("job_id") or submit.get("jobId") or "").strip()
        if not job_id:
            raise RuntimeError(f"{code} public optimization returned no job ID")
        terminal, _ = _poll_job(
            client=client,
            job_id=job_id,
            timeout_seconds=7200.0,
            poll_interval_seconds=5.0,
            log=progress_log,
        )
        _write_json(case_dir / "frontend_job_terminal_response.json", terminal)
        if terminal.get("status") != "completed":
            raise RuntimeError(f"{code} public optimization failed: {terminal}")
        run_dir = Path(str(dict(terminal.get("metadata") or {}).get("run_dir") or ""))
        if not run_dir.is_dir():
            raise RuntimeError(f"{code} run directory is missing: {run_dir}")
        results[code] = {
            "scenario_id": scenario.scenario_id,
            "job_id": job_id,
            **_confirmation_gate(run_dir, frozen_sha),
        }
        _write_json(case_dir / "confirmation_gate.json", results[code])
    expected = dict(
        _read_json(output_dir / "cross_weather_fixed_dispatch_matrix.json").get(
            "selected"
        )
        or {}
    )
    winner_checks = {
        code: results[code]["selected_physical_assignment_hash"]
        == str(dict(expected.get(code) or {}).get("assignment_hash") or "")
        for code in SCENARIOS
    }
    if not all(winner_checks.values()):
        raise RuntimeError(f"normal path did not recover diagnosed winners: {winner_checks}")
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "git_sha": frozen_sha,
        "git_dirty_before_after": False,
        "started_at_utc": started.isoformat(),
        "finished_at_utc": datetime.now(timezone.utc).isoformat(),
        "fresh_prepare": prepare_evidence,
        "public_endpoint": "/api/scenarios/{scenario_id}/run-optimization",
        "requested_candidate_limit": 1,
        "requested_composition_radius": 0,
        "requested_bev_frontier_enabled": False,
        "pure_ice_aggregate_B_executed": False,
        "winner_matches_fixed_dispatch_diagnosis": winner_checks,
        "scenarios": results,
        "progress_log": progress_log,
    }
    _assert_clean_sha(frozen_sha)
    _write_json(confirmation_dir / "confirmation_manifest.json", manifest)
    return manifest


def build_case_a_candidate_selection_audit(
    *,
    output_dir: Path,
    confirmation_manifest: Mapping[str, Any],
) -> dict[str, Any]:
    """Persist the six fail-closed Case-A candidate/selection checks."""

    discovery = _read_json(output_dir / "candidate_discovery_manifest.json")
    union = _read_json(output_dir / "weather_candidate_union.json")
    matrix = _read_json(output_dir / "cross_weather_fixed_dispatch_matrix.json")
    matrix_rows = list(matrix.get("rows") or ())
    selected = dict(matrix.get("selected") or {})
    confirmation = dict(confirmation_manifest.get("scenarios") or {})
    audit_rows: list[dict[str, Any]] = []
    scenario_audits: dict[str, Any] = {}

    for code in SCENARIOS:
        source_run_dir = Path(
            str(dict(discovery["scenarios"][code]).get("run_dir") or "")
        )
        source_candidates_payload = _read_json(
            source_run_dir / "stage1_stage2_candidate_evaluation.json"
        )
        source_candidates = list(source_candidates_payload.get("candidates") or ())
        solver_result = _read_json(source_run_dir / "solver_result.json")
        source_parameters = _read_json(
            source_run_dir / "optimization_parameters.json"
        )
        recourse_configuration = dict(
            dict(solver_result.get("solver_metadata") or {}).get(
                "stage1_time_indexed_energy_recourse_configuration"
            )
            or {}
        )
        input_hashes = dict(
            source_parameters.get("canonical_input_dimensions") or {}
        )
        canonical_by_hash = {
            str(row["assignment_hash"]): dict(row)
            for row in matrix_rows
            if row.get("scenario") == code
        }
        ranked_source = []
        for raw in source_candidates:
            candidate = dict(raw)
            physical_hash = assignment_hash_from_rows(
                candidate.get("vehicle_trip_assignments") or ()
            )
            matrix_row = canonical_by_hash.get(physical_hash)
            if matrix_row is None:
                raise RuntimeError(
                    f"{code} source candidate missing from cross matrix: {physical_hash}"
                )
            ranked_source.append((candidate, physical_hash, matrix_row))
        proxy_order = sorted(
            ranked_source,
            key=lambda item: (
                float(item[0]["stage1_candidate_priority_cost_jpy"]),
                item[1],
            ),
        )
        canonical_order = sorted(
            ranked_source,
            key=lambda item: (
                float(item[2]["canonical_actual_cost_jpy"]),
                int(item[2]["used_vehicle_count"]),
                item[1],
            ),
        )
        proxy_rank = {item[1]: index for index, item in enumerate(proxy_order, 1)}
        canonical_rank = {
            item[1]: index for index, item in enumerate(canonical_order, 1)
        }
        selected_index = int(source_candidates_payload.get("selected_candidate_index") or 0)
        for candidate, physical_hash, matrix_row in ranked_source:
            source_index = int(candidate.get("candidate_index") or 0)
            audit_rows.append(
                {
                    "scenario": code,
                    "assignment_hash": physical_hash,
                    "candidate_hash": candidate.get("candidate_hash"),
                    "source_candidate_index": source_index,
                    "source_selected": source_index == selected_index,
                    "source_rejection_reason": (
                        None
                        if source_index == selected_index
                        else "not_selected_by_source_run"
                    ),
                    "stage1_candidate_priority_cost_jpy": candidate.get(
                        "stage1_candidate_priority_cost_jpy"
                    ),
                    "stage1_energy_recourse_objective_jpy": candidate.get(
                        "stage1_recourse_objective_jpy"
                    ),
                    "stage1_proxy_rank": proxy_rank[physical_hash],
                    "stage2_canonical_actual_cost_jpy": matrix_row.get(
                        "canonical_actual_cost_jpy"
                    ),
                    "stage2_canonical_rank": canonical_rank[physical_hash],
                    "rank_reversed": (
                        proxy_rank[physical_hash] != canonical_rank[physical_hash]
                    ),
                    "stage2_feasible": matrix_row.get("stage2_feasible"),
                    "physical_validation_feasible": matrix_row.get(
                        "physical_validation_feasible"
                    ),
                    "accounting_reconciliation_passed": matrix_row.get(
                        "accounting_reconciliation_passed"
                    ),
                    "selectable": matrix_row.get("selectable"),
                }
            )
        canonical_winner = canonical_order[0][1]
        confirmed = dict(confirmation.get(code) or {})
        recourse_input_hash = recourse_configuration.get("recourse_input_hash")
        selection_semantics = str(
            source_candidates_payload.get("selection_semantics") or ""
        )
        checks = {
            "weather_pv_bess_tariff_inputs_enter_stage1": bool(
                input_hashes.get("pv_profile_sha256")
                and input_hashes.get("price_input_sha256")
                and input_hashes.get("energy_asset_control_input_sha256")
                and recourse_input_hash
                and recourse_configuration.get("arbitrary_weather_assignment_bias_used")
                is False
            ),
            "stage1_recourse_used_in_objective": (
                recourse_configuration.get("used_in_stage1_objective") is True
            ),
            "proxy_vs_canonical_rank_compared": len(ranked_source) >= 12,
            "selection_not_first_feasible_or_stage1_only": (
                "minimum_canonical_actual_cost" in selection_semantics
                and int(source_candidates_payload.get("candidate_count_evaluated") or 0)
                >= 12
            ),
            "physical_assignment_hash_deduplication_applied": (
                int(union.get("candidate_count_before_deduplication") or 0)
                > int(union.get("unique_physical_assignment_count") or 0)
                >= 12
            ),
            "stage2_canonical_minimum_selected": (
                canonical_winner
                == str(dict(selected.get(code) or {}).get("assignment_hash") or "")
                == str(confirmed.get("selected_physical_assignment_hash") or "")
            ),
        }
        if not all(checks.values()):
            raise RuntimeError(f"Case A selection audit failed for {code}: {checks}")
        scenario_rows = [row for row in audit_rows if row["scenario"] == code]
        second = canonical_order[1][2]
        scenario_audits[code] = {
            "source_run_dir": str(source_run_dir.resolve()),
            "candidate_count": len(ranked_source),
            "stage1_time_indexed_energy_recourse_configuration": (
                recourse_configuration
            ),
            "canonical_input_hashes": input_hashes,
            "selection_semantics": selection_semantics,
            "proxy_canonical_rank_reversal_count": sum(
                bool(row["rank_reversed"]) for row in scenario_rows
            ),
            "canonical_winner_assignment_hash": canonical_winner,
            "canonical_winner_cost_jpy": canonical_order[0][2].get(
                "canonical_actual_cost_jpy"
            ),
            "canonical_second_assignment_hash": canonical_order[1][1],
            "canonical_second_cost_jpy": second.get("canonical_actual_cost_jpy"),
            "canonical_first_second_delta_jpy": (
                float(second["canonical_actual_cost_jpy"])
                - float(canonical_order[0][2]["canonical_actual_cost_jpy"])
            ),
            "confirmed_normal_run_dir": confirmed.get("run_dir"),
            "checks": checks,
        }

    payload = {
        "schema_version": SCHEMA_VERSION,
        "verdict": "FIXED",
        "case": "A",
        "cause": (
            "normal_path_candidate_coverage_was_one_candidate; canonical_selection_"
            "itself_was_correct_for_the_candidates_it_received"
        ),
        "fix": {
            "candidate_limit_minimum": 22,
            "composition_search_radius_minimum": 4,
            "bev_frontier_enabled": True,
            "final_order": (
                "stage2_canonical_actual_cost_then_used_vehicle_count_then_"
                "assignment_hash"
            ),
            "arbitrary_weather_bias_added": False,
        },
        "candidate_union": {
            key: union.get(key)
            for key in (
                "existing_A_run_count",
                "expanded_candidate_count",
                "candidate_count_before_deduplication",
                "unique_physical_assignment_count",
                "target_reached",
            )
        },
        "scenarios": scenario_audits,
        "rows": audit_rows,
    }
    _write_json(output_dir / "case_a_candidate_selection_audit.json", payload)
    _write_csv(output_dir / "case_a_candidate_selection_audit.csv", audit_rows)
    md = [
        "# Case A candidate-generation and selection audit",
        "",
        "Verdict: **FIXED**. The previous normal path evaluated one candidate; the fixed policy evaluates the neutral 22-candidate composition/frontier coverage. No weather bias was added.",
        "",
        "| scenario | candidates | proxy/canonical reversals | winner | second-place delta JPY | six checks |",
        "|---|---:|---:|---|---:|---|",
    ]
    for code in SCENARIOS:
        audit = scenario_audits[code]
        md.append(
            f"| {code} | {audit['candidate_count']} | "
            f"{audit['proxy_canonical_rank_reversal_count']} | "
            f"{str(audit['canonical_winner_assignment_hash'])[:12]} | "
            f"{float(audit['canonical_first_second_delta_jpy']):.6f} | PASS |"
        )
    (output_dir / "case_a_candidate_selection_audit.md").write_text(
        "\n".join(md) + "\n", encoding="utf-8"
    )
    return payload


def build_confirmation_input_contract(
    *,
    output_dir: Path,
    existing_bundle: Path,
    confirmation_manifest: Mapping[str, Any],
) -> dict[str, Any]:
    """Compare every canonical final-run input hash with the frozen A baseline."""

    rows: list[dict[str, Any]] = []
    scenarios: dict[str, Any] = {}
    final_hashes_by_scenario: dict[str, dict[str, Any]] = {}
    for code in SCENARIOS:
        baseline_path = next(
            iter(
                sorted(
                    existing_bundle.glob(
                        f"scenarios/{code}/runs/*_A_discrete/case_metrics.json"
                    )
                )
            ),
            None,
        )
        if baseline_path is None:
            raise RuntimeError(f"missing frozen A baseline for {code}")
        baseline = _read_json(baseline_path)
        baseline_provenance = dict(baseline.get("provenance") or {})
        baseline_hashes = dict(baseline_provenance.get("input_hashes") or {})
        baseline_fleet_validation = dict(
            baseline.get("fleet_contract_validation") or {}
        )
        baseline_fleet_expected = dict(
            baseline_fleet_validation.get("expected") or {}
        ).get("fleet_contract_hash")
        baseline_fleet_observed = dict(
            baseline_fleet_validation.get("observed") or {}
        ).get("fleet_contract_hash")
        baseline_fleet_check = dict(
            baseline_fleet_validation.get("checks") or {}
        ).get("fleet_contract_hash")
        if not (
            baseline_fleet_check is True
            and baseline_fleet_expected not in (None, "")
            and baseline_fleet_expected == baseline_fleet_observed
        ):
            raise RuntimeError(
                f"{code} frozen A baseline lacks a valid fleet-contract hash"
            )
        baseline_hashes["fleet_contract_hash"] = baseline_fleet_expected
        confirmed = dict(
            dict(confirmation_manifest.get("scenarios") or {}).get(code) or {}
        )
        missing_confirmation_metadata = sorted(
            key
            for key in (
                "prepared_input_id",
                "prepared_input_sha256",
                "fleet_contract_hash",
                "service_date",
            )
            if confirmed.get(key) in (None, "")
        )
        if missing_confirmation_metadata:
            raise RuntimeError(
                f"{code} Fresh confirmation lacks required metadata: "
                f"{missing_confirmation_metadata}"
            )
        final_hashes = dict(confirmed.get("canonical_input_hashes") or {})
        final_hashes.update(
            {
                "prepared_source_sha256": confirmed.get("prepared_input_sha256"),
                "prepared_input_sha256": confirmed.get("prepared_input_sha256"),
                "timetable_hash": confirmed.get("trip_input_hash"),
                "vehicle_hash": confirmed.get("vehicle_input_hash"),
            }
        )
        final_hashes.update(
            {
                "tariff_hash": final_hashes.get("price_input_sha256"),
                "objective_hash": final_hashes.get("objective_weights_sha256"),
                "pv_hash": final_hashes.get("pv_profile_sha256"),
                "fleet_contract_hash": confirmed.get("fleet_contract_hash"),
            }
        )
        final_hashes_by_scenario[code] = final_hashes
        missing_baseline_keys = sorted(
            key
            for key in REQUIRED_CONFIRMATION_INPUT_HASHES
            if baseline_hashes.get(key) in (None, "")
        )
        if missing_baseline_keys:
            raise RuntimeError(
                f"{code} frozen A baseline lacks mandatory input hashes: "
                f"{missing_baseline_keys}"
            )
        required_baseline_keys = sorted(REQUIRED_CONFIRMATION_INPUT_HASHES)
        missing_final_keys = sorted(
            key for key in required_baseline_keys if final_hashes.get(key) in (None, "")
        )
        if missing_final_keys:
            raise RuntimeError(
                f"{code} Fresh confirmation lacks frozen-A input hashes: "
                f"{missing_final_keys}"
            )
        comparable_keys = required_baseline_keys
        for key in comparable_keys:
            rows.append(
                {
                    "scenario": code,
                    "input_key": key,
                    "frozen_A_sha256": baseline_hashes.get(key),
                    "fresh_confirmation_sha256": final_hashes.get(key),
                    "matches_frozen_A": (
                        baseline_hashes.get(key) == final_hashes.get(key)
                    ),
                }
            )
        mismatches = [
            row["input_key"]
            for row in rows
            if row["scenario"] == code and not row["matches_frozen_A"]
        ]
        scenarios[code] = {
            "scenario_id": WEATHER_SCENARIO_IDS[code],
            "run_dir": confirmed.get("run_dir"),
            "prepared_input_id": confirmed.get("prepared_input_id"),
            "prepared_source_sha256": confirmed.get("prepared_input_sha256"),
            "fleet_contract_hash": confirmed.get("fleet_contract_hash"),
            "service_date": confirmed.get("service_date"),
            "calendar_policy": confirmed.get("calendar_policy"),
            "canonical_input_hashes": final_hashes,
            "effective_solver_controls": confirmed.get(
                "effective_solver_controls"
            ),
            "runtime_controls": confirmed.get("runtime_controls"),
            "frozen_A_baseline": str(baseline_path.resolve()),
            "mismatches_from_frozen_A": mismatches,
            "missing_hashes_from_frozen_A_contract": missing_final_keys,
            "mandatory_hash_keys": list(REQUIRED_CONFIRMATION_INPUT_HASHES),
        }
        if mismatches:
            raise RuntimeError(
                f"{code} Fresh confirmation input drifted from frozen A: {mismatches}"
            )
    cross_scenario_differences = sorted(
        key
        for key in set(final_hashes_by_scenario["SUNNY"])
        | set(final_hashes_by_scenario["RAIN"])
        if final_hashes_by_scenario["SUNNY"].get(key)
        != final_hashes_by_scenario["RAIN"].get(key)
    )
    expected_weather_differences = {
        "canonical_ablation_input_sha256",
        "prepared_input_sha256",
        "prepared_source_sha256",
        "pv_profile_sha256",
        "pv_hash",
    }
    unexpected = sorted(
        set(cross_scenario_differences) - expected_weather_differences
    )
    if unexpected:
        raise RuntimeError(
            f"unexpected SUNNY/RAIN confirmation input differences: {unexpected}"
        )
    service_dates = {
        code: str(scenarios[code].get("service_date") or "") for code in SCENARIOS
    }
    if set(service_dates.values()) != {SERVICE_DATE}:
        raise RuntimeError(
            "SUNNY/RAIN confirmation service date drifted from the fixed "
            f"counterfactual contract: expected={SERVICE_DATE}, "
            f"observed={service_dates}"
        )
    payload = {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS_FULL_INPUT_CONTRACT",
        "fresh_prepare_used": True,
        "fixed_nonweather_inputs_equal": not unexpected,
        "cross_scenario_different_hashes": cross_scenario_differences,
        "service_date_contract": {
            "expected": SERVICE_DATE,
            "observed": service_dates,
            "matches": True,
        },
        "difference_interpretation": {
            "pv_profile_sha256": "authoritative_weather_linked_PV_input",
            "canonical_ablation_input_sha256": (
                "derived_contract_hash_that_includes_weather_linked_PV"
            ),
            "prepared_input_sha256": "scenario_specific_prepared_snapshot",
            "prepared_source_sha256": "scenario_specific_prepared_snapshot",
        },
        "scenarios": scenarios,
        "rows": rows,
    }
    _write_json(output_dir / "normal_confirmation_input_contract.json", payload)
    _write_csv(output_dir / "normal_confirmation_input_contract.csv", rows)
    md = [
        "# Fresh normal-path input contract",
        "",
        "Status: **PASS_FULL_INPUT_CONTRACT**. Every comparable hash matches the frozen A baseline within each scenario.",
        "",
        "SUNNY/RAIN differ only in scenario-specific prepared snapshots, the authoritative PV profile, and the canonical contract hash derived from that PV input.",
        "",
        "| scenario | prepared input | prepared SHA-256 | frozen-A drift |",
        "|---|---|---|---:|",
    ]
    for code in SCENARIOS:
        scenario = scenarios[code]
        md.append(
            f"| {code} | {scenario['prepared_input_id']} | "
            f"{scenario['prepared_source_sha256']} | 0 |"
        )
    (output_dir / "normal_confirmation_input_contract.md").write_text(
        "\n".join(md) + "\n", encoding="utf-8"
    )
    return payload


def finalize_normal_confirmation(
    *,
    output_dir: Path,
    sunny_run_dir: Path,
    rain_run_dir: Path,
    existing_bundle: Path = DEFAULT_EXISTING_BUNDLE,
    confirmation_dir_name: str = "normal_path_confirmation",
) -> dict[str, Any]:
    """Consolidate already completed public-path runs without solving again."""

    run_dirs = {"SUNNY": sunny_run_dir.resolve(), "RAIN": rain_run_dir.resolve()}
    execution_shas = {
        code: str(
            _read_json(run_dir / "rolling_hourly_chain" / "rolling_chain_summary.json").get(
                "day_ahead_git_sha"
            )
            or ""
        )
        for code, run_dir in run_dirs.items()
    }
    if len(set(execution_shas.values())) != 1 or not next(iter(execution_shas.values())):
        raise RuntimeError(f"confirmation run SHA mismatch: {execution_shas}")
    execution_sha = next(iter(execution_shas.values()))
    input_artifacts_before = _finalization_input_artifacts(
        output_dir=output_dir,
        existing_bundle=existing_bundle,
        run_dirs=run_dirs,
        confirmation_dir_name=confirmation_dir_name,
    )
    results = {
        code: _confirmation_gate(run_dir, execution_sha)
        for code, run_dir in run_dirs.items()
    }
    expected = dict(
        _read_json(output_dir / "cross_weather_fixed_dispatch_matrix.json").get(
            "selected"
        )
        or {}
    )
    winner_checks = {
        code: results[code]["selected_physical_assignment_hash"]
        == str(dict(expected.get(code) or {}).get("assignment_hash") or "")
        for code in SCENARIOS
    }
    if not all(winner_checks.values()):
        raise RuntimeError(f"confirmed winners differ from diagnosis: {winner_checks}")
    preparation_dir = (
        output_dir
        / confirmation_dir_name
        / "fresh_prepare"
        / "preparation"
    )
    requests = {
        code: _read_json(preparation_dir / code / "frontend_optimization_request.json")
        for code in SCENARIOS
    }
    controls_equal = all(
        requests["SUNNY"].get(key) == requests["RAIN"].get(key)
        for key in FIXED_CONFIRMATION_REQUEST_CONTROL_KEYS
    )
    effective_control_keys = sorted(
        set(results["SUNNY"]["effective_solver_controls"])
        | set(results["RAIN"]["effective_solver_controls"])
    )
    effective_control_differences = [
        key
        for key in effective_control_keys
        if results["SUNNY"]["effective_solver_controls"].get(key)
        != results["RAIN"]["effective_solver_controls"].get(key)
    ]
    effective_controls_equal = not effective_control_differences
    bev_utilization_policies_equal = (
        results["SUNNY"]["interactive_bev_utilization_policy"]
        == results["RAIN"]["interactive_bev_utilization_policy"]
    )
    timestep_is_15 = all(
        int(requests[code].get("timestep_min") or 0) == 15
        and int(requests[code].get("time_step_min") or 0) == 15
        for code in SCENARIOS
    )
    if (
        not controls_equal
        or not effective_controls_equal
        or not bev_utilization_policies_equal
        or not timestep_is_15
    ):
        raise RuntimeError(
            "normal confirmation fixed controls failed: "
            f"request_controls_equal={controls_equal}, "
            f"effective_controls_equal={effective_controls_equal}, "
            f"effective_differences={effective_control_differences}, "
            f"bev_utilization_policies_equal={bev_utilization_policies_equal}, "
            f"timestep_is_15={timestep_is_15}"
        )
    finalization_sha = _git_output("rev-parse", "HEAD")
    finalization_dirty = bool(_git_output("status", "--porcelain"))
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS_NORMAL_PATH_CONFIRMATION",
        "execution_git_sha": execution_sha,
        "execution_git_dirty": False,
        "finalization_git_sha": finalization_sha,
        "finalization_git_dirty": finalization_dirty,
        "public_endpoint": "/api/scenarios/{scenario_id}/run-optimization",
        "fixed_request_controls_equal": controls_equal,
        "fixed_request_control_keys": list(
            FIXED_CONFIRMATION_REQUEST_CONTROL_KEYS
        ),
        "effective_solver_controls_equal": effective_controls_equal,
        "effective_solver_control_keys": effective_control_keys,
        "effective_solver_control_differences": effective_control_differences,
        "bev_utilization_policies_equal": bev_utilization_policies_equal,
        "internal_timestep_15_minutes": timestep_is_15,
        "rolling_execution_minutes": 60,
        "requested_candidate_limit": requests["SUNNY"].get(
            "stage1_stage2_candidate_limit"
        ),
        "requested_composition_radius": requests["SUNNY"].get(
            "stage1_composition_search_radius"
        ),
        "requested_bev_frontier_enabled": bool(
            requests["SUNNY"].get("stage1_bev_frontier_enabled", False)
        ),
        "effective_candidate_limit": 22,
        "effective_composition_radius": 4,
        "effective_bev_frontier_enabled": True,
        "pure_ice_aggregate_B_executed": False,
        "winner_matches_fixed_dispatch_diagnosis": winner_checks,
        "scenarios": results,
        "excluded_diagnostic_runs": [
            {
                "run_dir": str(
                    (
                        REPO_ROOT
                        / "output"
                        / "2026-08-27"
                        / "run_20260827_2359"
                    ).resolve()
                ),
                "reason": "confirmation_harness_overrode_internal_timestep_to_60_minutes",
                "used_for_conclusions": False,
            },
            {
                "run_dir": str(
                    (
                        REPO_ROOT
                        / "output"
                        / "2026-08-28"
                        / "run_20260828_0022"
                    ).resolve()
                ),
                "reason": "public_BFF_interactive_policy_overrode_requested_one_thread_to_four_threads",
                "used_for_conclusions": False,
            },
            {
                "run_dir": str(
                    (
                        REPO_ROOT
                        / "output"
                        / "2026-08-28"
                        / "run_20260828_0034"
                    ).resolve()
                ),
                "reason": "public_BFF_interactive_policy_overrode_requested_one_thread_to_four_threads",
                "used_for_conclusions": False,
            },
        ],
    }
    case_a_audit = build_case_a_candidate_selection_audit(
        output_dir=output_dir,
        confirmation_manifest=manifest,
    )
    input_contract = build_confirmation_input_contract(
        output_dir=output_dir,
        existing_bundle=existing_bundle,
        confirmation_manifest=manifest,
    )
    manifest["case_a_candidate_selection_audit"] = {
        "status": case_a_audit["verdict"],
        "path": str(
            (output_dir / "case_a_candidate_selection_audit.json").resolve()
        ),
    }
    manifest["full_input_contract"] = {
        "status": input_contract["status"],
        "path": str(
            (output_dir / "normal_confirmation_input_contract.json").resolve()
        ),
    }
    input_artifacts_after = _finalization_input_artifacts(
        output_dir=output_dir,
        existing_bundle=existing_bundle,
        run_dirs=run_dirs,
        confirmation_dir_name=confirmation_dir_name,
    )
    if input_artifacts_after != input_artifacts_before:
        raise RuntimeError("raw finalization inputs changed during the re-audit")
    input_artifact_manifest_path = (
        output_dir / confirmation_dir_name / "finalization_input_artifacts.json"
    )
    _write_json(input_artifact_manifest_path, input_artifacts_before)
    manifest["finalization_input_artifacts"] = {
        "artifact_count": input_artifacts_before["artifact_count"],
        "path": str(input_artifact_manifest_path.resolve()),
        "sha256": _sha256_file(input_artifact_manifest_path),
        "artifacts": input_artifacts_before["artifacts"],
    }
    _write_json(
        output_dir / confirmation_dir_name / "confirmation_manifest.json",
        manifest,
    )
    return manifest


def _artifact_hashes(output_dir: Path) -> dict[str, str]:
    return {
        path.relative_to(output_dir).as_posix(): _sha256_file(path)
        for path in sorted(output_dir.rglob("*"))
        if path.is_file() and path.name != "artifact_hashes.json"
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--existing-bundle", type=Path, default=DEFAULT_EXISTING_BUNDLE)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument(
        "--stage",
        choices=(
            "existing",
            "discover",
            "union",
            "cross",
            "confirm",
            "finalize",
            "all",
        ),
        default="all",
    )
    parser.add_argument("--stage1-time-limit-seconds", type=int, default=1800)
    parser.add_argument("--stage2-time-limit-seconds", type=int, default=30)
    parser.add_argument("--candidate-limit", type=int, default=21)
    parser.add_argument("--confirmation-sunny-run-dir", type=Path)
    parser.add_argument("--confirmation-rain-run-dir", type=Path)
    parser.add_argument(
        "--confirmation-dir-name",
        default="normal_path_confirmation",
    )
    args = parser.parse_args()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    if args.stage in {"existing", "all"}:
        analyze_existing_bundle(args.existing_bundle.resolve(), output_dir)
    if args.stage in {"discover", "all"}:
        discover_candidates(
            output_dir=output_dir,
            base_url=args.base_url,
            existing_bundle=args.existing_bundle.resolve(),
            stage1_seconds=args.stage1_time_limit_seconds,
            stage2_seconds=args.stage2_time_limit_seconds,
            candidate_limit=args.candidate_limit,
        )
    if args.stage in {"union", "all"}:
        build_candidate_union(
            output_dir,
            existing_bundle=args.existing_bundle.resolve(),
        )
    if args.stage in {"cross", "all"}:
        cross_evaluate(output_dir)
    confirmation_manifest: dict[str, Any] | None = None
    if args.stage in {"confirm", "all"}:
        confirmation_manifest = confirm_normal_runs(
            output_dir=output_dir,
            base_url=args.base_url,
            existing_bundle=args.existing_bundle.resolve(),
            confirmation_dir_name=args.confirmation_dir_name,
        )
    if args.stage == "all":
        assert confirmation_manifest is not None
        confirmed_scenarios = dict(confirmation_manifest.get("scenarios") or {})
        confirmed_run_paths = {
            code: str(dict(confirmed_scenarios.get(code) or {}).get("run_dir") or "")
            for code in SCENARIOS
        }
        if not all(confirmed_run_paths.values()):
            raise RuntimeError(
                f"all-stage confirmation omitted run directories: {confirmed_run_paths}"
            )
        finalize_normal_confirmation(
            output_dir=output_dir,
            sunny_run_dir=Path(confirmed_run_paths["SUNNY"]),
            rain_run_dir=Path(confirmed_run_paths["RAIN"]),
            existing_bundle=args.existing_bundle.resolve(),
            confirmation_dir_name=args.confirmation_dir_name,
        )
    elif args.stage == "finalize":
        if (
            args.confirmation_sunny_run_dir is None
            or args.confirmation_rain_run_dir is None
        ):
            parser.error(
                "--stage finalize requires both confirmation run directories"
            )
        finalize_normal_confirmation(
            output_dir=output_dir,
            sunny_run_dir=args.confirmation_sunny_run_dir,
            rain_run_dir=args.confirmation_rain_run_dir,
            existing_bundle=args.existing_bundle.resolve(),
            confirmation_dir_name=args.confirmation_dir_name,
        )
    _write_json(
        output_dir / "artifact_hashes.json",
        {"schema_version": "artifact_hashes_v1", "sha256": _artifact_hashes(output_dir)},
    )


if __name__ == "__main__":
    main()
