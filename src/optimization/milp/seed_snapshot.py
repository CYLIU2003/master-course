"""Optional, immutable evidence of the supplied Stage 1 assignment seed."""
import hashlib
import json
from pathlib import Path

from src.optimization.common.result import ResultSerializer


def write_stage1_seed_snapshot(problem, config, *, applied: bool, source: str, rejection_reason) -> None:
    if not problem.metadata.get("stage1_seed_cost_diagnostic_enabled", False):
        return
    directory = problem.metadata.get("phase3_diagnostics_dir")
    if not directory:
        raise ValueError("Seed evidence requires a diagnosis directory")
    plan = config.fixed_assignment or problem.baseline_plan
    serialized = ResultSerializer.serialize_plan(plan) if applied and plan is not None else None
    if applied and serialized is None:
        raise ValueError("Applied seed is missing its assignment plan")
    plan_bytes = json.dumps(serialized, sort_keys=True, ensure_ascii=False, allow_nan=False).encode("utf-8")
    payload = {
        "schema_version": "stage1_supplied_seed_v1", "applied": applied,
        "source": source, "rejection_reason": rejection_reason,
        "plan": serialized, "plan_sha256": hashlib.sha256(plan_bytes).hexdigest(),
        "semantics": "supplied_pre_solve_seed;not_first_solver_incumbent;not_physical_acceptance",
    }
    path = Path(directory) / "stage1_supplied_seed.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
