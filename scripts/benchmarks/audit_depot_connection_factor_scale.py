"""Read-only representation audit of a previously prepared diagnostic fixture.

This command does not solve, certify a new prepared input, or reuse a previous
SHA's outcome as research evidence. Its output only measures model domains.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-worktree", required=True, type=Path)
    parser.add_argument("--manifest-directory", required=True)
    parser.add_argument("--week", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    source = args.source_worktree.resolve()
    output = args.output.resolve()
    if output.exists():
        raise ValueError("Audit output already exists; use a new path")
    os.environ["SCENARIO_STORE_PATH"] = str(source / "output/scenarios")
    from bff.store import scenario_store
    from bff.services.run_preparation import load_prepared_input, materialize_scenario_from_prepared_input
    from src.optimization.common.builder import ProblemBuilder
    from src.optimization.common.problem import OptimizationConfig, OptimizationMode
    from src.optimization.milp.depot_connection_factors import (
        SuccessorRow, factor_depot_connections,
    )
    from src.optimization.milp.model_builder import MILPModelBuilder
    from src.optimization.milp.solver_adapter import GurobiMILPAdapter

    manifest_path = source / args.manifest_directory / args.week / "derived_scenarios.json"
    case = json.loads(manifest_path.read_text(encoding="utf-8"))["cases"][0]
    prepared_path = source / "output/prepared_inputs" / case["scenario_id"] / f'{case["prepared_input_id"]}.json'
    prepared_sha = hashlib.sha256(prepared_path.read_bytes()).hexdigest()
    scenario = scenario_store._load(case["scenario_id"], skip_graph_arcs=True,
                                    repair_missing_master=False, repair_route_metadata=False)
    prepared = load_prepared_input(scenario_id=case["scenario_id"], prepared_input_id=case["prepared_input_id"],
                                   scenarios_dir=source / "output/prepared_inputs")
    scenario = materialize_scenario_from_prepared_input(scenario, prepared)
    config = OptimizationConfig(mode=OptimizationMode.MILP, phase="phase3_two_stage",
                                gurobi_threads=12, random_seed=42, research_run=False,
                                allow_postsolve_repair=False)
    started = time.perf_counter()
    print("Building canonical fixture; no solver will run", flush=True)
    problem = ProblemBuilder().build_from_scenario(scenario, depot_id="tsurumaki", service_id="WEEKDAY",
                                                  config=config, planning_days=7)
    build_seconds = time.perf_counter() - started
    del prepared, scenario
    print(f"Canonical fixture built: {len(problem.trips)} trips in {build_seconds:.2f}s", flush=True)
    started = time.perf_counter()
    builder = MILPModelBuilder()
    rows = tuple(SuccessorRow(row.vehicle_id, row.from_trip_id, row.selected_successors)
                 for row in builder.iter_arc_successors(problem, problem.trip_by_id()))
    candidate_count = sum(len(row.targets) for row in rows)
    print(f"Factoring {candidate_count} original vehicle-labelled connections", flush=True)
    explicit, factors = factor_depot_connections(GurobiMILPAdapter(), problem, rows)
    represented = sum(len(factor.origins) * len(factor.targets) for factor in factors)
    incidence = sum(len(factor.origins) + len(factor.targets) for factor in factors)
    if len(explicit) + represented != candidate_count:
        raise ValueError("Candidate accounting mismatch")
    if hashlib.sha256(prepared_path.read_bytes()).hexdigest() != prepared_sha:
        raise ValueError("Prepared regression fixture changed")
    report = {
        "schema_version": "depot_connection_factor_scale_audit_v1",
        "claim_scope": "REPRESENTATION_REGRESSION_ONLY_NOT_A_SOLVER_OR_RESEARCH_RESULT",
        "source_git_sha": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "fixture_git_sha": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=source, text=True).strip(),
        "prepared_input_sha256": prepared_sha, "prepared_input_id": case["prepared_input_id"],
        "trips": len(problem.trips), "vehicles": len(problem.vehicles),
        "canonical_build_seconds": build_seconds,
        "factor_domain_seconds": time.perf_counter() - started,
        "complete_candidate_connections": candidate_count,
        "explicit_connections": len(explicit), "represented_connections": represented,
        "factor_incidence_variables": incidence, "connection_variables_after_factoring": len(explicit) + incidence,
        "factor_count": len(factors), "candidate_connections_removed": 0,
        "largest_origin_group": max((len(f.origins) for f in factors), default=0),
        "largest_target_group": max((len(f.targets) for f in factors), default=0),
        "config": asdict(config),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "config"}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
