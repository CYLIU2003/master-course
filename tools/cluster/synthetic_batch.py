"""Create a reproducible 12-month deployment check for the batch CLI.

Each month is one fictional day, not a month-long or accepted research result.
This prepares inputs only; batch.py performs idempotent submission and collection.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--settings", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--batch-id", required=True)
    parser.add_argument("--year", type=int, default=2025)
    parser.add_argument("--profile", choices=["alns_no_gurobi_v1", "existing_solver_v1"], default="alns_no_gurobi_v1")
    parser.add_argument("--one-per-worker", action="store_true", help="Pin for fleet deployment verification; default is performance-aware auto assignment")
    args = parser.parse_args()
    # configure switches cwd to the frozen release. User-supplied paths must
    # retain their meaning in the directory where the command was invoked.
    args.output = args.output.resolve()
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from tools.cluster.serve_controller import configure
    settings = configure(args.settings.resolve())
    from bff.services.cluster.contracts import canonical, read_config, segment
    from bff.services.run_preparation import get_or_build_run_preparation
    from bff.store import scenario_store, output_paths
    from tools.cluster.monthly_smoke import scenario_for_month
    segment(args.batch_id)
    if args.output.exists():
        raise ValueError("Batch file already exists; resume it with batch.py run")
    workers = [worker for worker in read_config().workers if worker.enabled]
    if args.one_per_worker and len(workers) != 12:
        raise ValueError("This fleet check expects the parent plus eleven registered workers")
    tasks = []
    for month in range(1, 13):
        scenario = scenario_for_month(args.year, month)
        scenario_id = segment(f"{args.batch_id}-{month:02d}")
        try:
            scenario_store.get_scenario_document_shallow(scenario_id)
        except KeyError:
            pass
        else:
            raise ValueError("Synthetic scenario already exists; resume the saved batch or choose a new batch ID")
        scenario["meta"]["id"] = scenario_id
        scenario["simulation_config"]["execution_profile"] = args.profile
        no_gurobi = args.profile == "alns_no_gurobi_v1"
        mode = "mode_alns_only" if no_gurobi else "phase3_two_stage"
        scenario["simulation_config"]["solver_mode"] = mode
        scenario["scenario_overlay"]["solver_config"]["mode"] = mode
        scenario_store._save(scenario)
        # Persist the same normalized scope used by the public BFF before
        # Prepare freezes its hash; a later process must see identical flags.
        scenario_store.set_dispatch_scope(scenario_id, {"depotId": "SMOKE_DEPOT", "serviceId": "WEEKDAY"})
        prepared = get_or_build_run_preparation(scenario_store.get_scenario_document(scenario_id),
            Path(settings["release"]) / "data/built/tokyu_full", output_paths.outputs_root() / "prepared_inputs", None)
        if not prepared.is_valid:
            raise ValueError(f"Month {month} failed Prepare: {prepared.error}")
        tasks.append({"task_id": f"month-{month:02d}", "submission": {
            "scenario_id": scenario_id, "worker_id": workers[month - 1].id if args.one_per_worker else None,
            "minimum_ram_gb": 1,
            "request": {"execution_profile": args.profile, "mode": "alns" if no_gurobi else mode,
                "prepared_input_id": prepared.prepared_input_id, "rebuild_dispatch": False,
                "use_existing_duties": False, "research_run": False, "random_seed": 42,
                "run_hourly_rolling": False, "run_profile": "day_ahead_exploratory",
                "time_limit_seconds": 5 if no_gurobi else 30, "alns_iterations": 5, "no_improvement_limit": 3,
                "gurobi_threads": 1, "timestep_min": 30}}})
    manifest = {"schema_version": 1, "batch_id": args.batch_id,
                "controller_url": f"http://127.0.0.1:{settings.get('port', 8868)}",
                "git_sha": settings["git_sha"], "tasks": tasks}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("xb") as output:
        output.write(canonical(manifest))
    print(json.dumps({"tasks": len(tasks), "manifest": str(args.output), "profile": args.profile,
                      "scope": "12 independent synthetic days; no research acceptance"}))


if __name__ == "__main__":
    main()
