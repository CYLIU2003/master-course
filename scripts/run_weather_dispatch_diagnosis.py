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


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


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
            "scenario": candidate.get("source_scenario"),
            "run_dir": candidate.get("source_run_dir"),
            "candidate_index": candidate.get("candidate_index"),
            "candidate_hash": candidate.get("candidate_hash"),
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
        candidate.get("stage2_feasible", candidate.get("feasible", False))
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
        candidates = list(dict(solver.get("solver_metadata") or {}).get("stage1_stage2_candidate_evaluation") or ())
    else:
        candidates = list(_read_json(path).get("candidates") or ())
    rows = []
    for raw in candidates:
        row = dict(raw)
        row.update({"source_scenario": code, "source_run_dir": str(source_run_dir.resolve())})
        rows.append(row)
    return rows


def build_candidate_union(output_dir: Path) -> list[dict[str, Any]]:
    manifest = _read_json(output_dir / "candidate_discovery_manifest.json")
    candidates: list[dict[str, Any]] = []
    for code in SCENARIOS:
        source_run_dir = Path(str(dict(manifest["scenarios"][code]).get("run_dir") or ""))
        candidates.extend(_load_candidate_rows_from_run(code, source_run_dir))
    unique = deduplicate_candidates(candidates)
    payload = {
        "schema_version": SCHEMA_VERSION,
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
            "time_step_min": 15,
            "timestep_min": 15,
            "time_limit_seconds": 1950,
            "stage1_time_limit_seconds": 1800,
            "stage2_time_limit_seconds": 30,
            "stage1_stage2_candidate_limit": 1,
            "stage1_composition_search_radius": 0,
            "stage1_bev_frontier_enabled": False,
            "stage1_powertrain_selector_strengthening": False,
            "stage1_best_obj_stop_enabled": False,
            "gurobi_threads": 1,
            "mip_gap": 0.1,
            "random_seed": 42,
            "run_profile": "day_ahead_and_hourly_rolling",
            "run_hourly_rolling": True,
            "rolling_execution_minutes": 60,
        }
    )
    return request


def _confirmation_gate(run_dir: Path, expected_sha: str) -> dict[str, Any]:
    summary = _read_json(run_dir / "summary.json")
    physical = _read_json(run_dir / "physical_schedule_validation.json")
    accounting = _read_json(run_dir / "final_cost_reconciliation.json")
    rolling = _read_json(
        run_dir / "rolling_hourly_chain" / "rolling_chain_summary.json"
    )
    candidates = _read_json(run_dir / "stage1_stage2_candidate_evaluation.json")
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
            and rolling.get("all_steps_feasible") is True
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
        "candidate_coverage_applied": (
            int(candidates.get("requested_candidate_limit") or 0) >= 22
            and int(candidates.get("composition_search_radius_requested") or 0)
            >= 4
            and int(candidates.get("candidate_count_evaluated") or 0) >= 12
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
        "selected_canonical_actual_cost_jpy": candidates.get(
            "selected_canonical_actual_cost_jpy"
        ),
        "candidate_count_evaluated": candidates.get("candidate_count_evaluated"),
        "prepared_input_id": rolling.get("prepared_input_id"),
        "prepared_input_sha256": rolling.get("prepared_input_sha256"),
        "trip_input_hash": rolling.get("trip_input_hash"),
        "vehicle_input_hash": rolling.get("vehicle_input_hash"),
        "fleet_contract_hash": rolling.get("scenario_fleet_contract_hash"),
        "day_ahead_assignment_hash": rolling.get("day_ahead_assignment_hash"),
    }


def confirm_normal_runs(
    *,
    output_dir: Path,
    base_url: str,
    existing_bundle: Path,
) -> dict[str, Any]:
    """Fresh Prepare and validate one public normal-path run per weather case."""

    frozen_sha = _assert_clean_sha()
    started = datetime.now(timezone.utc)
    confirmation_dir = output_dir / "normal_path_confirmation"
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


def finalize_normal_confirmation(
    *,
    output_dir: Path,
    sunny_run_dir: Path,
    rain_run_dir: Path,
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
        / "normal_path_confirmation"
        / "fresh_prepare"
        / "preparation"
    )
    requests = {
        code: _read_json(preparation_dir / code / "frontend_optimization_request.json")
        for code in SCENARIOS
    }
    fixed_control_keys = (
        "mode",
        "research_run",
        "time_step_min",
        "timestep_min",
        "time_limit_seconds",
        "stage1_time_limit_seconds",
        "stage2_time_limit_seconds",
        "stage1_best_obj_stop_enabled",
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
    controls_equal = all(
        requests["SUNNY"].get(key) == requests["RAIN"].get(key)
        for key in fixed_control_keys
    )
    timestep_is_15 = all(
        int(requests[code].get("timestep_min") or 0) == 15
        and int(requests[code].get("time_step_min") or 0) == 15
        for code in SCENARIOS
    )
    if not controls_equal or not timestep_is_15:
        raise RuntimeError(
            "normal confirmation fixed controls failed: "
            f"controls_equal={controls_equal}, timestep_is_15={timestep_is_15}"
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
            }
        ],
    }
    _write_json(
        output_dir / "normal_path_confirmation" / "confirmation_manifest.json",
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
        build_candidate_union(output_dir)
    if args.stage in {"cross", "all"}:
        cross_evaluate(output_dir)
    if args.stage in {"confirm", "all"}:
        confirm_normal_runs(
            output_dir=output_dir,
            base_url=args.base_url,
            existing_bundle=args.existing_bundle.resolve(),
        )
    if args.stage == "finalize":
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
        )
    _write_json(
        output_dir / "artifact_hashes.json",
        {"schema_version": "artifact_hashes_v1", "sha256": _artifact_hashes(output_dir)},
    )


if __name__ == "__main__":
    main()
