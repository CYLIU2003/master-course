"""Separate subproblem certificates, search progress and real executed cost."""
import math


def _finite(value):
    return (float(value) if isinstance(value, (float, int)) and not isinstance(value, bool)
            and math.isfinite(value) else None)


def day_ahead_quality(metadata: dict, *, target_gap: float) -> dict:
    if not math.isfinite(target_gap) or not 0 <= target_gap < 1:
        raise ValueError("Quality target gap must be finite in [0, 1)")
    reports = {}
    for stage in (1, 2):
        objective = _finite(metadata.get(f"stage{stage}_objective_value"))
        bound = _finite(metadata.get("stage1_certified_best_bound" if stage == 1 else "stage2_best_bound"))
        consistent = objective is not None and bound is not None and bound <= objective + 1e-6
        gap = (abs(objective - bound) / abs(objective) if objective else
               0.0 if abs(bound or 0) <= 1e-6 else None) if consistent else None
        reports[f"stage{stage}"] = {"objective_jpy": objective, "lower_bound_jpy": bound,
            "gap_ratio": gap, "target_met": gap is not None and gap <= target_gap,
            "solver_status": metadata.get(f"stage{stage}_solver_status")}
    telemetry = metadata.get("stage1_search_telemetry") or {}
    first = _finite(telemetry.get("first_incumbent_objective"))
    final = reports["stage1"]["objective_jpy"]
    return {"target_gap_ratio": target_gap, **reports,
        "subproblem_gap_targets_met": all(row["target_met"] for row in reports.values()),
        "first_incumbent_objective_jpy": first,
        "incumbent_improvement_jpy": first - final if first is not None and final is not None else None,
        "first_mip_callback_runtime_sec": telemetry.get("first_mip_callback_runtime_sec"),
        "last_presolve_callback_runtime_sec": telemetry.get("last_presolve_callback_runtime_sec"),
        "integrated_global_optimum_proven": False,
        "executed_week_cost_comparison": "NOT_EVALUATED_BY_THIS_CERTIFICATE"}
