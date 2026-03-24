from __future__ import annotations

import argparse
import copy
import csv
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))

from src.optimization import OptimizationConfig, OptimizationEngine, OptimizationMode, ProblemBuilder
from src.optimization.common.result import ResultSerializer


def _load_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def _write_csv(path: Path, rows: List[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames = list(rows[0].keys())
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _default_service_id(scenario: Dict[str, Any]) -> str:
    for row in scenario.get("timetable_rows") or []:
        service_id = str(row.get("service_id") or "").strip()
        if service_id:
            return service_id
    return "WEEKDAY"


def _get_asset_template(scenario: Dict[str, Any], depot_id: str) -> Dict[str, Any]:
    sim_cfg = dict(scenario.get("simulation_config") or {})
    overlay = dict(scenario.get("scenario_overlay") or {})
    for item in list(sim_cfg.get("depot_energy_assets") or []) + list(overlay.get("depot_energy_assets") or []):
        if not isinstance(item, dict):
            continue
        candidate = str(item.get("depot_id") or item.get("depotId") or "")
        if candidate == depot_id:
            return dict(item)
    return {"depot_id": depot_id}


def _build_case_scenario(
    base_scenario: Dict[str, Any],
    *,
    depot_id: str,
    pv_enabled: bool,
    bess_enabled: bool,
    allow_grid_to_bess: bool,
) -> Dict[str, Any]:
    scenario = copy.deepcopy(base_scenario)
    sim_cfg = dict(scenario.get("simulation_config") or {})
    assets = [item for item in (sim_cfg.get("depot_energy_assets") or []) if isinstance(item, dict)]

    template = _get_asset_template(base_scenario, depot_id)
    bess_energy_kwh = float(template.get("bess_energy_kwh") or 500.0)
    bess_power_kw = float(template.get("bess_power_kw") or 250.0)
    pv_capacity_kw = float(template.get("pv_capacity_kw") or 0.0)

    case_asset = {
        **template,
        "depot_id": depot_id,
        "pv_enabled": bool(pv_enabled),
        "bess_enabled": bool(bess_enabled),
        "allow_grid_to_bess": bool(allow_grid_to_bess),
        "pv_capacity_kw": pv_capacity_kw if pv_enabled else 0.0,
        "bess_energy_kwh": bess_energy_kwh if bess_enabled else 0.0,
        "bess_power_kw": bess_power_kw if bess_enabled else 0.0,
        "bess_initial_soc_kwh": (bess_energy_kwh * 0.5) if bess_enabled else 0.0,
        "bess_soc_min_kwh": (bess_energy_kwh * 0.1) if bess_enabled else 0.0,
        "bess_soc_max_kwh": bess_energy_kwh if bess_enabled else 0.0,
    }

    retained_assets = []
    for item in assets:
        candidate = str(item.get("depot_id") or item.get("depotId") or "")
        if candidate != depot_id:
            retained_assets.append(item)
    retained_assets.append(case_asset)

    sim_cfg["depot_energy_assets"] = retained_assets
    scenario["simulation_config"] = sim_cfg
    return scenario


def _mode_from_text(mode_text: str) -> OptimizationMode:
    normalized = str(mode_text or "").strip().lower()
    if normalized == "alns":
        return OptimizationMode.ALNS
    if normalized == "hybrid":
        return OptimizationMode.HYBRID
    return OptimizationMode.MILP


def _solve_case(
    scenario: Dict[str, Any],
    *,
    depot_id: str,
    service_id: str,
    mode: OptimizationMode,
    time_limit_sec: int,
    mip_gap: float,
    random_seed: int,
    alns_iterations: int,
) -> Dict[str, Any]:
    builder = ProblemBuilder()
    engine = OptimizationEngine()
    problem = builder.build_from_scenario(
        scenario,
        depot_id=depot_id,
        service_id=service_id,
        config=OptimizationConfig(mode=mode),
    )
    result = engine.solve(
        problem,
        OptimizationConfig(
            mode=mode,
            time_limit_sec=time_limit_sec,
            mip_gap=mip_gap,
            random_seed=random_seed,
            alns_iterations=alns_iterations,
        ),
    )
    return ResultSerializer.serialize_result(result)


def _extract_row(case_name: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    cost = dict(payload.get("cost_breakdown") or {})
    return {
        "case": case_name,
        "solver_status": payload.get("solver_status"),
        "objective_mode": payload.get("objective_mode"),
        "objective_value": payload.get("objective_value"),
        "feasible": payload.get("feasible"),
        "electricity_cost_final": cost.get("electricity_cost_final", cost.get("energy_cost")),
        "electricity_cost_provisional_leftover": cost.get("electricity_cost_provisional_leftover", 0.0),
        "grid_purchase_cost": cost.get("grid_purchase_cost", 0.0),
        "bess_discharge_cost": cost.get("bess_discharge_cost", 0.0),
        "grid_to_bus_kwh": cost.get("grid_to_bus_kwh", 0.0),
        "bess_to_bus_kwh": cost.get("bess_to_bus_kwh", 0.0),
        "pv_to_bess_kwh": cost.get("pv_to_bess_kwh", 0.0),
        "grid_to_bess_kwh": cost.get("grid_to_bess_kwh", 0.0),
        "peak_grid_kw": cost.get("peak_grid_kw", 0.0),
        "total_cost": cost.get("total_cost", payload.get("objective_value")),
        "total_cost_with_assets": cost.get("total_cost_with_assets", cost.get("total_cost", payload.get("objective_value"))),
    }


def run_case_matrix(
    *,
    scenario_path: Path,
    depot_id: str,
    service_id: str,
    output_dir: Path,
    mode: str,
    time_limit_sec: int,
    mip_gap: float,
    random_seed: int,
    alns_iterations: int,
) -> Tuple[Path, Path]:
    base_scenario = _load_json(scenario_path)
    output_dir.mkdir(parents=True, exist_ok=True)

    case_defs = [
        ("case0", False, False, False),
        ("case1", True, False, False),
        ("case2", True, True, False),
        ("case3", True, True, True),
    ]

    rows: List[Dict[str, Any]] = []
    payloads: Dict[str, Any] = {
        "scenario_path": str(scenario_path),
        "depot_id": depot_id,
        "service_id": service_id,
        "generated_at": datetime.now().isoformat(),
        "mode": mode,
        "cases": {},
    }

    mode_enum = _mode_from_text(mode)
    for case_name, pv_enabled, bess_enabled, allow_grid_to_bess in case_defs:
        scenario = _build_case_scenario(
            base_scenario,
            depot_id=depot_id,
            pv_enabled=pv_enabled,
            bess_enabled=bess_enabled,
            allow_grid_to_bess=allow_grid_to_bess,
        )
        result_payload = _solve_case(
            scenario,
            depot_id=depot_id,
            service_id=service_id,
            mode=mode_enum,
            time_limit_sec=time_limit_sec,
            mip_gap=mip_gap,
            random_seed=random_seed,
            alns_iterations=alns_iterations,
        )
        payloads["cases"][case_name] = result_payload
        rows.append(_extract_row(case_name, result_payload))

    csv_path = output_dir / "case_matrix_summary.csv"
    json_path = output_dir / "case_matrix_results.json"
    _write_csv(csv_path, rows)
    _write_json(json_path, payloads)
    return csv_path, json_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Run real-data Case0-3 matrix for depot energy settings")
    parser.add_argument("--scenario", required=True, help="Path to scenario JSON")
    parser.add_argument("--depot-id", required=True, help="Target depot ID")
    parser.add_argument("--service-id", default="", help="Target service ID (default: auto detect or WEEKDAY)")
    parser.add_argument("--output-dir", default="outputs/case_matrix", help="Output directory")
    parser.add_argument("--mode", default="milp", choices=["milp", "hybrid", "alns"], help="Solver mode")
    parser.add_argument("--time-limit-sec", type=int, default=300)
    parser.add_argument("--mip-gap", type=float, default=0.01)
    parser.add_argument("--random-seed", type=int, default=42)
    parser.add_argument("--alns-iterations", type=int, default=200)
    args = parser.parse_args()

    scenario_path = Path(args.scenario)
    if not scenario_path.exists():
        raise FileNotFoundError(f"Scenario file not found: {scenario_path}")

    scenario = _load_json(scenario_path)
    service_id = str(args.service_id or _default_service_id(scenario))

    csv_path, json_path = run_case_matrix(
        scenario_path=scenario_path,
        depot_id=str(args.depot_id),
        service_id=service_id,
        output_dir=Path(args.output_dir),
        mode=args.mode,
        time_limit_sec=int(args.time_limit_sec),
        mip_gap=float(args.mip_gap),
        random_seed=int(args.random_seed),
        alns_iterations=int(args.alns_iterations),
    )
    print(f"[done] summary csv: {csv_path}")
    print(f"[done] detail json: {json_path}")


if __name__ == "__main__":
    main()
