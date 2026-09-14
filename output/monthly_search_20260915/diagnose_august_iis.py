"""Bounded saved-IIS analysis only; never a repaired or accepted weekly plan."""
from pathlib import Path
import hashlib
import json
import time
import gurobipy as gp

BASE = Path(__file__).resolve().parent
OUT = BASE / "august_iis_diagnosis"
SOURCE = Path("C:/master-course-worktrees/shibu21-23-monthly-search-20260915/output/monthly_search_campaign_20260915/cases/2025-08-04/diagnostic/2025-08-04/rolling_hourly_chain/hour_048/failure_diagnostics/stage2_infeasible.ilp")


def write(name, data):
    (OUT / name).write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def inspect(model, label):
    model.Params.LogFile = str(OUT / f"{label}.log")
    model.Params.TimeLimit = 60
    model.Params.Threads = 12
    model.Params.Seed = 42
    model.Params.FeasibilityTol = 1e-9
    model.Params.IntFeasTol = 1e-9
    model.Params.Presolve = 0
    model.Params.Aggregate = 0
    model.Params.Method = 1
    model.Params.MIPFocus = 1
    model.optimize()
    result = {"status": model.Status, "solutions": model.SolCount, "runtime": model.Runtime,
              "variables": model.NumVars, "constraints": model.NumConstrs}
    if model.SolCount:
        result.update(constraint_violation=model.ConstrVio, bound_violation=model.BoundVio)
    if model.Status == gp.GRB.INFEASIBLE:
        model.computeIIS()
        model.write(str(OUT / f"{label}_reduced.ilp"))
        constraints = [c.ConstrName for c in model.getConstrs() if c.IISConstr]
        bounds = [{"name": v.VarName, "lb": v.LB if v.IISLB else None,
                   "ub": v.UB if v.IISUB else None} for v in model.getVars() if v.IISLB or v.IISUB]
        result.update(iis_minimal=bool(model.IISMinimal), constraints_in_iis=len(constraints), bounds_in_iis=len(bounds))
        write(f"{label}_iis_members.json", {"constraints": constraints, "bounds": bounds})
    write(f"{label}_summary.json", result)
    return result


def main():
    OUT.mkdir(exist_ok=False)
    digest = hashlib.sha256(SOURCE.read_bytes()).hexdigest()
    write("protocol.json", {"source": str(SOURCE), "sha256": digest,
          "purpose": "Saved infeasible subsystem diagnosis. This is not the full original objective/model or physical replay.",
          "per_solve_seconds": 60, "source_modified": False})
    with gp.read(str(SOURCE)) as original:
        with original.relax() as lp:
            lp_result = inspect(lp, "lp")
        mip_result = inspect(original, "mip")
    assert hashlib.sha256(SOURCE.read_bytes()).hexdigest() == digest
    write("summary.json", {"status": "DIAGNOSIS_COMPLETED", "lp": lp_result, "mip": mip_result,
                           "physical_validation": "NOT_EXECUTED", "weekly_result": False})


if __name__ == "__main__":
    main()
