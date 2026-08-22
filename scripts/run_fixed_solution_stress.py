"""Evaluate an accepted canonical plan under fixed-decision stress inputs."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from typing import Any, Mapping


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.optimization import OptimizationConfig, OptimizationMode, ProblemBuilder
from src.optimization.validation.fixed_solution_stress import (
    evaluate_fixed_solution_stress,
    standard_fixed_solution_stresses,
)


def _read_object(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"expected a JSON object: {path}")
    return data


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git_output(*args: str) -> str:
    return subprocess.check_output(
        ["git", *args], cwd=REPO_ROOT, text=True
    ).strip()


def _source_git_sha(source_run: Path) -> str:
    provenance = _read_object(source_run / "code_provenance.json")
    for key in ("git_sha", "commit_sha", "code_sha"):
        value = str(provenance.get(key) or "").strip()
        if value:
            return value
    raise ValueError("source code_provenance.json has no Git SHA")


def _build_problem(
    scenario: Mapping[str, Any],
    request: Mapping[str, Any],
) -> Any:
    phase = str(request.get("mode") or "").strip()
    if phase != "phase3_two_stage":
        raise ValueError("fixed-decision stress requires a phase3_two_stage source")
    config = OptimizationConfig(
        mode=OptimizationMode.MILP,
        time_limit_sec=int(request.get("time_limit_seconds") or 0),
        stage1_time_limit_sec=request.get("stage1_time_limit_seconds"),
        stage2_time_limit_sec=request.get("stage2_time_limit_seconds"),
        stage1_best_obj_stop_enabled=bool(
            request.get("stage1_best_obj_stop_enabled")
        ),
        stage1_stage2_candidate_limit=int(
            request.get("stage1_stage2_candidate_limit") or 1
        ),
        stage1_composition_search_radius=int(
            request.get("stage1_composition_search_radius") or 0
        ),
        gurobi_threads=request.get("gurobi_threads"),
        mip_gap=float(request.get("mip_gap") or 0.0),
        random_seed=int(request.get("random_seed") or 0),
        research_run=bool(request.get("research_run")),
        allow_postsolve_repair=False,
        phase=phase,
        requested_phase=phase,
        resolved_phase=phase,
        executed_phase=phase,
    )
    return ProblemBuilder().build_from_scenario(
        dict(scenario),
        depot_id=str(request.get("depot_id") or ""),
        service_id=str(request.get("service_id") or ""),
        config=config,
        planning_days=1,
    )


def run(args: argparse.Namespace) -> dict[str, Any]:
    source_run = Path(args.source_run).resolve()
    request_path = Path(args.optimization_request).resolve()
    output_dir = Path(args.output_dir).resolve()
    required_paths = {
        "effective_scenario": source_run / "effective_scenario.json",
        "canonical_result": source_run / "canonical_solver_result.json",
        "code_provenance": source_run / "code_provenance.json",
        "request": request_path,
    }
    missing = [name for name, path in required_paths.items() if not path.is_file()]
    if missing:
        raise FileNotFoundError("missing required stress input artifacts: " + ", ".join(missing))
    if output_dir.exists():
        raise FileExistsError(f"refusing to overwrite stress artifact directory: {output_dir}")
    if _git_output("status", "--porcelain"):
        raise RuntimeError("fixed-decision stress requires a clean Git worktree")
    current_sha = _git_output("rev-parse", "HEAD")
    source_sha = _source_git_sha(source_run)
    if current_sha != source_sha:
        raise RuntimeError(
            "source result Git SHA differs from stress evaluator SHA: "
            f"source={source_sha}, evaluator={current_sha}; run a fresh baseline first"
        )

    scenario = _read_object(required_paths["effective_scenario"])
    canonical = _read_object(required_paths["canonical_result"])
    request = _read_object(request_path)
    problem = _build_problem(scenario, request)
    canonical_trip_ids = {
        str(trip_id)
        for values in dict(canonical.get("vehicle_paths") or {}).values()
        for trip_id in list(values or ())
    }
    problem_trip_ids = {str(trip.trip_id) for trip in problem.trips}
    if canonical_trip_ids != problem_trip_ids:
        raise RuntimeError(
            "canonical assignment trip IDs do not match reconstructed source problem"
        )

    output_dir.mkdir(parents=True, exist_ok=False)
    results = [
        evaluate_fixed_solution_stress(
            problem=problem,
            canonical_result=canonical,
            stress=stress,
        )
        for stress in standard_fixed_solution_stresses(canonical)
    ]
    manifest = {
        "schema_version": "fixed_solution_stress_manifest_v1",
        "git_sha": current_sha,
        "git_dirty": False,
        "source_run": str(source_run),
        "source_run_git_sha": source_sha,
        "source_artifact_sha256": {
            name: _sha256(path) for name, path in required_paths.items()
        },
        "source_controls": {
            key: request.get(key)
            for key in (
                "mode", "research_run", "prepared_input_id", "time_limit_seconds",
                "gurobi_threads", "mip_gap", "random_seed", "service_id", "depot_id",
            )
        },
        "reoptimization_performed": False,
        "problem_scope": {
            "trip_count": len(problem.trips),
            "vehicle_count": len(problem.vehicles),
            "charger_count": len(problem.chargers),
            "time_slot_count": len(problem.price_slots),
        },
    }
    (output_dir / "stress_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (output_dir / "fixed_solution_stress.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    rows = [
        {
            "stress": item["stress"]["name"],
            "physical_accepted": item["physical_accepted"],
            "completion_rate": item["completion_rate"],
            "minimum_soc_kwh": item["minimum_soc_kwh"],
            "physical_violation_count": item["physical_violation_count"],
            "baseline_cost_jpy": item["baseline_cost_jpy"],
            "fixed_decision_cost_jpy": item["fixed_decision_cost_jpy"],
            "additional_cost_jpy": item["additional_cost_jpy"],
            "cost_status": item["cost_status"],
        }
        for item in results
    ]
    with (output_dir / "fixed_solution_stress.csv").open(
        "w", newline="", encoding="utf-8"
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return {"output_dir": str(output_dir), "results": len(results)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-run", required=True)
    parser.add_argument("--optimization-request", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    print(json.dumps(run(args), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
