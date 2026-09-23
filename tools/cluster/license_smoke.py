"""Explicit tiny license test through the same local/remote admission policy."""
from __future__ import annotations

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from bff.services.optimization_run.solver_policy import guarded_execution


@guarded_execution
def run_license_test(job_id: str) -> dict:
    from src.gurobi_runtime import ensure_gurobi, is_gurobi_available
    from src.solver_policy import optimize_model, usage_record
    is_gurobi_available()
    gp, GRB = ensure_gurobi()
    values = []
    for index in range(2):
        model = gp.Model(f"managed_license_smoke_{index}")
        model.Params.Threads = 1
        model.Params.TimeLimit = 5
        x = model.addVar(lb=1, ub=2)
        model.setObjective(x, GRB.MINIMIZE)
        optimize_model(model)
        if model.Status != GRB.OPTIMAL:
            raise RuntimeError("LICENSE_SMOKE_SOLVE_FAILED")
        values.append(float(model.ObjVal))
        if index == 0:
            model.dispose()  # Some existing auxiliary paths dispose early; teardown must tolerate it.
    from bff.store import job_store
    job_store.update_job(job_id, status="completed")
    return {"objective_values": values, "solver_usage": usage_record(), "research_approval": "NOT_GRANTED_BY_CLUSTER"}


def main():
    from bff.store import job_store, output_paths
    job = job_store.create_job(execution_model="thread")
    result = run_license_test(job.job_id)
    (output_paths.outputs_root() / "managed-license-smoke.json").write_text(json.dumps(result, indent=2), encoding="utf8")
    print(json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
