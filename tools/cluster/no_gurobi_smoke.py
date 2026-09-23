"""Exercise actual Prepare -> BFF -> canonical ALNS -> artifact writing in isolation."""
from __future__ import annotations

import argparse
import importlib.abc
import json
import os
from pathlib import Path
import sys


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--without-gurobipy", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(root))
    args.output = args.output.resolve()
    args.output.mkdir(parents=True, exist_ok=False)
    os.environ["MC_OUTPUTS_DIR"] = str(args.output)
    os.environ["SCENARIO_STORE_PATH"] = str(args.output / "scenarios")
    calls = {"Env": 0, "Model": 0}
    if args.without_gurobipy:
        class NoGurobi(importlib.abc.MetaPathFinder):
            def find_spec(self, fullname, path, target=None):
                if fullname == "gurobipy" or fullname.startswith("gurobipy."):
                    raise ModuleNotFoundError("gurobipy intentionally unavailable")
        sys.meta_path.insert(0, NoGurobi())
    else:
        import gurobipy
        def forbidden(name):
            def call(*args, **kwargs):
                calls[name] += 1
                raise AssertionError("Native Gurobi entry reached: " + name)
            return call
        gurobipy.Env = forbidden("Env")
        gurobipy.Model = forbidden("Model")
    from src.solver_policy import NO_GUROBI_PROFILE, solver_policy_scope
    from bff.store import scenario_store, job_store
    from bff.services.run_preparation import get_or_build_run_preparation
    from bff.routers.optimization import RunOptimizationBody, enqueue_optimization
    from tools.cluster.monthly_smoke import scenario_for_month
    scenario = scenario_for_month(2025, 1)
    config = scenario["simulation_config"]
    config.update(execution_profile=NO_GUROBI_PROFILE, solver_mode="mode_alns_only")
    scenario["scenario_overlay"]["solver_config"]["mode"] = "mode_alns_only"
    scenario_id = scenario["meta"]["id"]
    scenario_store._save(scenario)
    def synchronous(**submission):
        submission["fn"](*submission["args"])
        return True
    with solver_policy_scope(NO_GUROBI_PROFILE) as usage:
        prepared = get_or_build_run_preparation(scenario_store.get_scenario_document(scenario_id),
            args.dataset.resolve(), args.output / "prepared_inputs", None)
        if not prepared.is_valid:
            raise RuntimeError(prepared.error)
        request = RunOptimizationBody(execution_profile=NO_GUROBI_PROFILE, mode="alns",
            prepared_input_id=prepared.prepared_input_id, rebuild_dispatch=False,
            run_profile="day_ahead_exploratory", run_hourly_rolling=False,
            research_run=False, time_limit_seconds=3, alns_iterations=5,
            no_improvement_limit=3, gurobi_threads=1, timestep_min=30)
        response = enqueue_optimization(scenario_id, request, {"built_dir": str(args.dataset.resolve())}, submit=synchronous)
    job = job_store.get_job(response["job_id"])
    from dataclasses import asdict
    record = {"job_status": job.status, "error": job.error, "native_calls": calls,
              "solver_usage": asdict(usage), "run_dir": job.metadata.get("run_dir"),
              "gurobipy_unavailable": args.without_gurobipy,
              "claim_scope": "DIAGNOSTIC, NOT USED FOR RESEARCH CONCLUSIONS"}
    (args.output / "no_gurobi_audit.json").write_text(json.dumps(record, indent=2), encoding="utf8")
    print(json.dumps(record), flush=True)
    return 0 if job.status == "completed" and not any(calls.values()) and usage.forbidden_calls == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
