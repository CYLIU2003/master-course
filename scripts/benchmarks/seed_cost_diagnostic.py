"""Evaluate the actual supplied seed with the same fixed-assignment Stage 2."""
from dataclasses import replace
import hashlib
import json
import math
import time
from pathlib import Path

from src.optimization.common.result import ResultSerializer
from src.optimization.engine import OptimizationEngine
from src.optimization.validation.physical_event_schedule import validate_physical_event_schedule
from scripts.benchmarks.optimization_quality import day_ahead_quality


def _write(path: Path, payload: dict) -> None:
    # Match canonical diagnostic serialization, including infeasible +/-Infinity
    # objectives. Retain the native reasons instead of masking them with an I/O error.
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")


def _assignment(plan) -> tuple:
    return tuple(sorted((plan.vehicle_id_for_duty(d.duty_id), tuple(d.trip_ids)) for d in plan.duties))


def compare_costs(seed_result, seed_physical: dict, final_result, target_gap: float) -> dict:
    """Measure forecast cost change only after both fixed-assignment solves pass."""
    quality = day_ahead_quality(seed_result.plan.metadata, target_gap=target_gap)
    final_quality = day_ahead_quality(final_result.plan.metadata, target_gap=target_gap)
    costs = [r.cost_breakdown.get("total_cost") for r in (seed_result, final_result)]
    finite = all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in costs)
    accepted = (seed_result.feasible and final_result.feasible
                and seed_physical.get("accepted") is True and not seed_physical.get("violations")
                and quality["stage2"]["target_met"] and final_quality["stage2"]["target_met"] and finite)
    return {"status": "COMPARABLE_FORECAST_COSTS" if accepted else "COST_COMPARISON_BLOCKED",
        "seed_forecast_total_cost_jpy": costs[0] if finite else None,
        "final_forecast_total_cost_jpy": costs[1] if finite else None,
        "seed_infeasibility_reasons": list(getattr(seed_result, 'infeasibility_reasons', ())),
        "seed_physical_accepted": seed_physical.get('accepted'),
        "seed_physical_violations": seed_physical.get('violations', []),
        "seed_to_final_forecast_cost_reduction_jpy": costs[0]-costs[1] if accepted else None,
        "seed_stage2_quality": quality["stage2"], "final_stage2_quality": final_quality["stage2"],
        "semantics": "same_problem_supplied_seed_vs_final_assignment;not_first_incumbent_or_executed_week_cost",
        "integrated_global_optimum_proven": False}


def evaluate_supplied_seed(problem, config, final_result, output: Path, *, wall_seconds: int) -> dict:
    """Run after the main solve; do not feed the seed evaluation back into search."""
    snapshot_path = output / "day_ahead_failure_diagnostics/stage1_supplied_seed.json"
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    plan_bytes = json.dumps(snapshot["plan"], sort_keys=True, ensure_ascii=False, allow_nan=False).encode("utf-8")
    if hashlib.sha256(plan_bytes).hexdigest() != snapshot["plan_sha256"]:
        raise ValueError("Supplied seed hash mismatch")
    folder = output / "supplied_seed_cost"
    folder.mkdir(exist_ok=False)
    if not snapshot["applied"] or snapshot["plan"] is None:
        blocked = {"status": "SEED_NOT_APPLIED", "reason": snapshot["rejection_reason"],
                   "seed_to_final_forecast_cost_reduction_jpy": None}
        _write(folder/"comparison.json", blocked)
        return blocked
    seed = ResultSerializer.deserialize_plan(problem, snapshot["plan"])
    seed_problem = replace(problem, metadata={**problem.metadata,
        "phase3_diagnostics_dir": str(folder/"failure_diagnostics"),
        "stage1_seed_cost_diagnostic_enabled": False})
    seed_config = replace(config, phase="phase1_charging_only", fixed_assignment=seed,
                          time_limit_sec=wall_seconds, warm_start=False)
    started = time.perf_counter()
    result = OptimizationEngine().solve(seed_problem, seed_config)
    _write(folder/"canonical_solver_result.json", ResultSerializer.serialize_result(result))
    physical = validate_physical_event_schedule(problem=seed_problem,
        serialized_result=ResultSerializer.serialize_plan(result.plan))
    _write(folder/"physical_validation.json", physical)
    if result.feasible and _assignment(seed) != _assignment(result.plan):
        raise ValueError("Fixed Stage 2 changed the supplied seed assignment")
    comparison = compare_costs(result, physical, final_result, float(config.mip_gap))
    comparison.update(seed_snapshot_sha256=hashlib.sha256(snapshot_path.read_bytes()).hexdigest(),
                      seed_plan_sha256=snapshot["plan_sha256"], seed_assignment_preserved=result.feasible,
                      elapsed_seconds=time.perf_counter()-started,
                      stage2_time_limit_sec=config.stage2_time_limit_sec, wall_time_limit_sec=wall_seconds)
    _write(folder/"comparison.json", comparison)
    return comparison
