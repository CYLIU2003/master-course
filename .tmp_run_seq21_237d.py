import json
from copy import deepcopy
from pathlib import Path

from bff.mappers.scenario_to_problemdata import build_problem_data_from_scenario
from bff.services.run_preparation import materialize_scenario_from_prepared_input
from src.pipeline.solve import solve_problem_data

sid = "237d5623-aa94-4f72-9da1-17b9070264be"
prep_dir = Path("output/prepared_inputs") / sid
prep_files = sorted(prep_dir.glob("prepared-*.json"), key=lambda p: p.stat().st_mtime)
if not prep_files:
    raise SystemExit("prepared input not found")
prep_path = prep_files[-1]
prep = json.loads(prep_path.read_text(encoding="utf-8"))

out_dir = Path("output/tmp_seq21_237d")
out_dir.mkdir(parents=True, exist_ok=True)


def run_case(case_name: str, *, coeffs: dict | None, allow_partial: bool):
    base = {"id": sid, "meta": {"id": sid}}
    scenario = materialize_scenario_from_prepared_input(base, deepcopy(prep))
    scenario.setdefault("simulation_config", {})
    scenario.setdefault("scenario_overlay", {})
    sim = scenario["simulation_config"]
    overlay = scenario["scenario_overlay"]
    solver_cfg = overlay.setdefault("solver_config", {})
    cost_cfg = overlay.setdefault("cost_coefficients", {})

    sim["disable_vehicle_acquisition_cost"] = True
    sim["objective_mode"] = "total_cost"
    sim["time_step_min"] = 60
    sim["timestep_min"] = 60
    sim["allow_partial_service"] = bool(allow_partial)
    solver_cfg["objective_mode"] = "total_cost"
    solver_cfg["mode"] = "mode_milp_only"
    solver_cfg["allow_partial_service"] = bool(allow_partial)

    if coeffs:
        sim["enable_contract_overage_penalty"] = bool(coeffs.get("enable_contract_overage_penalty", True))
        sim["contract_overage_penalty_yen_per_kwh"] = float(coeffs.get("contract_overage_penalty_yen_per_kwh", 500.0))
        sim["grid_to_bus_priority_penalty_yen_per_kwh"] = float(coeffs.get("grid_to_bus_priority_penalty_yen_per_kwh", 10.0))
        sim["grid_to_bess_priority_penalty_yen_per_kwh"] = float(coeffs.get("grid_to_bess_priority_penalty_yen_per_kwh", 2.0))
        cost_cfg["enable_contract_overage_penalty"] = sim["enable_contract_overage_penalty"]
        cost_cfg["contract_overage_penalty_yen_per_kwh"] = sim["contract_overage_penalty_yen_per_kwh"]
        cost_cfg["grid_to_bus_priority_penalty_yen_per_kwh"] = sim["grid_to_bus_priority_penalty_yen_per_kwh"]
        cost_cfg["grid_to_bess_priority_penalty_yen_per_kwh"] = sim["grid_to_bess_priority_penalty_yen_per_kwh"]

    scope = prep.get("scope") or {}
    service_id = (scope.get("service_ids") or [None])[0]
    depot_id = (scope.get("depot_ids") or [None])[0]

    data, report = build_problem_data_from_scenario(
        scenario,
        depot_id=depot_id,
        service_id=service_id,
        mode="mode_milp_only",
        use_existing_duties=False,
        analysis_scope=scenario.get("dispatch_scope"),
    )
    setattr(data, "allow_partial_service", bool(allow_partial))

    res = solve_problem_data(
        data,
        mode="mode_milp_only",
        time_limit_seconds=300,
        mip_gap=0.01,
        random_seed=42,
        output_dir=str(out_dir / case_name),
    )
    result = res["result"]
    status = str(getattr(result, "status", "UNKNOWN") or "UNKNOWN")
    unserved_tasks = list(getattr(result, "unserved_tasks", []) or [])
    task_count = int(report.task_count or 0)
    served_count = max(0, task_count - len(unserved_tasks))
    feasible_statuses = {"OPTIMAL", "TIME_LIMIT", "SUBOPTIMAL", "FEASIBLE"}
    feasible = status in feasible_statuses
    summary = {
        "case": case_name,
        "allow_partial_service": bool(allow_partial),
        "coeffs": coeffs or {},
        "solver_status": status,
        "feasible": feasible,
        "objective_mode": "total_cost",
        "unserved": len(unserved_tasks),
        "served": served_count,
        "warnings": [],
        "infeasibility_reasons": [str(getattr(result, "infeasibility_info", "") or "")] if getattr(result, "infeasibility_info", "") else [],
        "objective_value": getattr(result, "objective_value", None),
        "obj_breakdown": dict(getattr(result, "obj_breakdown", {}) or {}),
        "build_report": report.to_dict(),
    }
    (out_dir / f"{case_name}_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


results = {}
results["case_2_low"] = run_case(
    "case_2_low",
    coeffs={
        "enable_contract_overage_penalty": True,
        "contract_overage_penalty_yen_per_kwh": 200.0,
        "grid_to_bus_priority_penalty_yen_per_kwh": 5.0,
        "grid_to_bess_priority_penalty_yen_per_kwh": 1.0,
    },
    allow_partial=True,
)
results["case_2_high"] = run_case(
    "case_2_high",
    coeffs={
        "enable_contract_overage_penalty": True,
        "contract_overage_penalty_yen_per_kwh": 1500.0,
        "grid_to_bus_priority_penalty_yen_per_kwh": 30.0,
        "grid_to_bess_priority_penalty_yen_per_kwh": 10.0,
    },
    allow_partial=True,
)
results["case_1_baseline"] = run_case(
    "case_1_baseline",
    coeffs=None,
    allow_partial=False,
)

(out_dir / "summary_all.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps({
    k: {
        "solver_status": v.get("solver_status"),
        "feasible": v.get("feasible"),
        "served": v.get("served"),
        "unserved": v.get("unserved"),
    }
    for k, v in results.items()
}, ensure_ascii=False))
print(f"out_dir={out_dir}")
