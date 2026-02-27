#!/usr/bin/env python3
"""
Electric bus scheduling / charging / PV co-optimization prototype for Gurobi.

Usage examples
--------------
python solve_ebus_gurobi.py \
    --config ebus_prototype_config.json \
    --stage assignment_only

python solve_ebus_gurobi.py \
    --config ebus_prototype_config.json \
    --stage full_with_pv \
    --output result_full_with_pv.json

Stages
------
- assignment_only
- assignment_plus_soc
- assignment_soc_charging
- full_with_pv

Notes
-----
- This script is designed to match the JSON structure in ebus_prototype_config.json.
- It intentionally keeps the first prototype MILP simple.
- Location consistency is implemented in a relaxed prototype form:
  if manual bus_can_charge_at data is absent, charging is allowed at every node when idle.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple


VALID_STAGES = {
    "assignment_only",
    "assignment_plus_soc",
    "assignment_soc_charging",
    "full_with_pv",
}


class ConfigError(Exception):
    """Raised when the input JSON is structurally invalid."""


def load_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def validate_config(cfg: Dict[str, Any]) -> None:
    required_top = [
        "sets",
        "bus_params",
        "trip_params",
        "charger_params",
        "energy_params",
        "model_options",
    ]
    for key in required_top:
        if key not in cfg:
            raise ConfigError(f"Missing top-level key: {key}")

    sets = cfg["sets"]
    for key in ["buses", "trips", "depots", "charger_types"]:
        if key not in sets or not isinstance(sets[key], list) or len(sets[key]) == 0:
            raise ConfigError(f"sets.{key} must be a non-empty list")

    time_info = cfg["model_options"]["time_discretization"]
    if "num_periods" not in time_info:
        raise ConfigError("model_options.time_discretization.num_periods is required")

    num_periods = time_info["num_periods"]
    if num_periods <= 0:
        raise ConfigError("num_periods must be positive")

    price = cfg["energy_params"].get("grid_price_yen_per_kwh", [])
    pv = cfg["energy_params"].get("pv_gen_kwh", [])
    if price and len(price) != num_periods:
        raise ConfigError("Length of energy_params.grid_price_yen_per_kwh must equal num_periods")
    if pv and len(pv) != num_periods:
        raise ConfigError("Length of energy_params.pv_gen_kwh must equal num_periods")


def build_indices(cfg: Dict[str, Any]) -> Dict[str, List[Any]]:
    buses = cfg["sets"]["buses"]
    trips = cfg["sets"]["trips"]
    depots = cfg["sets"]["depots"]
    charger_types = cfg["sets"]["charger_types"]
    num_periods = cfg["model_options"]["time_discretization"]["num_periods"]
    times = list(range(num_periods))
    return {
        "B": buses,
        "R": trips,
        "C": depots,
        "S": charger_types,
        "T": times,
    }


def derive_overlap_pairs(cfg: Dict[str, Any]) -> List[Tuple[str, str]]:
    pre = cfg.get("precomputed_helpers", {})
    explicit = pre.get("overlap_pairs", [])
    if explicit:
        return [tuple(pair) for pair in explicit]

    trip_params = cfg["trip_params"]
    trips = cfg["sets"]["trips"]
    pairs: List[Tuple[str, str]] = []
    for i, r1 in enumerate(trips):
        s1 = trip_params[r1]["start_t"]
        e1 = trip_params[r1]["end_t"]
        for r2 in trips[i + 1 :]:
            s2 = trip_params[r2]["start_t"]
            e2 = trip_params[r2]["end_t"]
            # time interval overlap (inclusive prototype interpretation)
            if not (e1 < s2 or e2 < s1):
                pairs.append((r1, r2))
    return pairs


def get_trip_active(cfg: Dict[str, Any], r: str, t: int) -> int:
    helper = cfg.get("precomputed_helpers", {}).get("trip_active", {})
    if r in helper:
        return int(helper[r][t])

    p = cfg["trip_params"][r]
    return int(p["start_t"] <= t <= p["end_t"])


def get_trip_energy_at_time(cfg: Dict[str, Any], r: str, t: int) -> float:
    helper = cfg.get("precomputed_helpers", {}).get("trip_energy_at_time", {})
    if r in helper:
        return float(helper[r][t])

    p = cfg["trip_params"][r]
    start_t = p["start_t"]
    end_t = p["end_t"]
    if start_t <= t <= end_t:
        span = end_t - start_t + 1
        return float(p["energy_kwh"]) / float(span)
    return 0.0


def get_charge_allowed(cfg: Dict[str, Any], b: str, c: str, t: int) -> int:
    manual = (
        cfg.get("precomputed_helpers", {})
        .get("bus_can_charge_at", {})
        .get("manual_override_example", {})
    )
    if b in manual and c in manual[b]:
        return int(manual[b][c][t])
    return 1


def stage_flags(stage: str) -> Dict[str, bool]:
    return {
        "assignment": True,
        "soc": stage in {"assignment_plus_soc", "assignment_soc_charging", "full_with_pv"},
        "charging": stage in {"assignment_soc_charging", "full_with_pv"},
        "pv": stage == "full_with_pv",
    }


def build_and_solve(cfg: Dict[str, Any], stage: str, verbose: bool = True) -> Dict[str, Any]:
    try:
        import gurobipy as gp
        from gurobipy import GRB
    except Exception as e:  # pragma: no cover
        raise RuntimeError(
            "gurobipy is not available in this environment. Install Gurobi + gurobipy first."
        ) from e

    validate_config(cfg)
    idx = build_indices(cfg)
    flags = stage_flags(stage)

    B, R, C, S, T = idx["B"], idx["R"], idx["C"], idx["S"], idx["T"]
    num_periods = len(T)
    delta_h = float(cfg["model_options"]["time_discretization"]["delta_h"])
    charge_eff = float(cfg["energy_params"].get("charge_efficiency", 1.0))

    trip_params = cfg["trip_params"]
    bus_params = cfg["bus_params"]
    charger_params = cfg["charger_params"]
    energy_params = cfg["energy_params"]
    overlap_pairs = derive_overlap_pairs(cfg)

    model = gp.Model(f"ebus_{stage}")
    model.Params.OutputFlag = 1 if verbose else 0

    # -------------------------
    # Variables
    # -------------------------
    x = model.addVars(B, R, vtype=GRB.BINARY, name="x")

    soc = None
    if flags["soc"]:
        soc = model.addVars(B, range(num_periods + 1), lb=0.0, vtype=GRB.CONTINUOUS, name="soc")

    y = None
    e = None
    if flags["charging"]:
        y = model.addVars(B, C, S, T, vtype=GRB.BINARY, name="y")
        e = model.addVars(B, C, S, T, lb=0.0, vtype=GRB.CONTINUOUS, name="e")

    pv_use = None
    grid_buy = None
    if flags["pv"]:
        pv_use = model.addVars(T, lb=0.0, vtype=GRB.CONTINUOUS, name="pv_use")
        grid_buy = model.addVars(T, lb=0.0, vtype=GRB.CONTINUOUS, name="grid_buy")

    elif flags["charging"]:
        # still track grid purchase in charging stage as a convenience accounting variable
        grid_buy = model.addVars(T, lb=0.0, vtype=GRB.CONTINUOUS, name="grid_buy")

    # -------------------------
    # Objective
    # -------------------------
    if flags["pv"] or flags["charging"]:
        prices = energy_params["grid_price_yen_per_kwh"]
        model.setObjective(gp.quicksum(prices[t] * grid_buy[t] for t in T), GRB.MINIMIZE)
    else:
        model.setObjective(0.0, GRB.MINIMIZE)

    # -------------------------
    # Assignment constraints
    # -------------------------
    # Every trip must be assigned to exactly one bus.
    for r in R:
        model.addConstr(gp.quicksum(x[b, r] for b in B) == 1, name=f"assign_once[{r}]")

    # No bus can cover overlapping trips.
    for b in B:
        for r1, r2 in overlap_pairs:
            model.addConstr(x[b, r1] + x[b, r2] <= 1, name=f"overlap[{b},{r1},{r2}]")

    # -------------------------
    # SOC-related constraints
    # -------------------------
    if flags["soc"] and soc is not None:
        # Initial SOC
        for b in B:
            model.addConstr(soc[b, 0] == float(bus_params[b]["soc_init_kwh"]), name=f"soc_init[{b}]")

        # SOC bounds on all times
        for b in B:
            soc_min = float(bus_params[b]["soc_min_kwh"])
            soc_max = float(bus_params[b]["soc_max_kwh"])
            for tt in range(num_periods + 1):
                model.addConstr(soc[b, tt] >= soc_min, name=f"soc_lb[{b},{tt}]")
                model.addConstr(soc[b, tt] <= soc_max, name=f"soc_ub[{b},{tt}]")

        # SOC transition
        for b in B:
            for t in T:
                trip_use = gp.quicksum(
                    get_trip_energy_at_time(cfg, r, t) * x[b, r]
                    for r in R
                )
                charge_in = 0.0
                if flags["charging"] and e is not None:
                    charge_in = gp.quicksum(charge_eff * e[b, c, s, t] for c in C for s in S)

                model.addConstr(
                    soc[b, t + 1] == soc[b, t] - trip_use + charge_in,
                    name=f"soc_balance[{b},{t}]",
                )

    # -------------------------
    # Charging-related constraints
    # -------------------------
    if flags["charging"] and y is not None and e is not None:
        # Link charging energy to charging decision.
        for b in B:
            for c in C:
                for s in S:
                    power_kw = float(charger_params[c][s]["power_kw"])
                    max_e = power_kw * delta_h
                    for t in T:
                        model.addConstr(
                            e[b, c, s, t] <= max_e * y[b, c, s, t],
                            name=f"charge_link[{b},{c},{s},{t}]",
                        )

        # Charger count limit.
        for c in C:
            for s in S:
                count = int(charger_params[c][s]["count"])
                for t in T:
                    model.addConstr(
                        gp.quicksum(y[b, c, s, t] for b in B) <= count,
                        name=f"charger_count[{c},{s},{t}]",
                    )

        # A bus can use at most one charger slot at a time.
        for b in B:
            for t in T:
                model.addConstr(
                    gp.quicksum(y[b, c, s, t] for c in C for s in S) <= 1,
                    name=f"one_charge_action[{b},{t}]",
                )

        # A bus cannot charge while it is operating a trip.
        for b in B:
            for t in T:
                run_expr = gp.quicksum(get_trip_active(cfg, r, t) * x[b, r] for r in R)
                model.addConstr(
                    run_expr + gp.quicksum(y[b, c, s, t] for c in C for s in S) <= 1,
                    name=f"no_run_and_charge[{b},{t}]",
                )

        # Relaxed/prototype location feasibility.
        for b in B:
            for c in C:
                for s in S:
                    for t in T:
                        allowed = get_charge_allowed(cfg, b, c, t)
                        model.addConstr(
                            y[b, c, s, t] <= allowed,
                            name=f"charge_allowed[{b},{c},{s},{t}]",
                        )

        # Energy accounting in charging stage.
        for t in T:
            total_charge = gp.quicksum(e[b, c, s, t] for b in B for c in C for s in S)
            if flags["pv"] and pv_use is not None and grid_buy is not None:
                pv_cap = float(energy_params["pv_gen_kwh"][t])
                model.addConstr(pv_use[t] <= pv_cap, name=f"pv_cap[{t}]")
                model.addConstr(total_charge == pv_use[t] + grid_buy[t], name=f"power_balance[{t}]")
            elif grid_buy is not None:
                model.addConstr(total_charge == grid_buy[t], name=f"power_balance_no_pv[{t}]")

    model.optimize()

    result: Dict[str, Any] = {
        "stage": stage,
        "solver_status_code": int(model.Status),
        "solver_status": status_to_text(model.Status),
        "objective_value": None,
        "x_assignment": {},
        "soc_time_series": {},
        "charge_schedule_y": {},
        "charge_energy_e": {},
        "pv_use": {},
        "grid_buy": {},
    }

    if model.SolCount == 0:
        return result

    result["objective_value"] = float(model.ObjVal)

    for b in B:
        result["x_assignment"][b] = {}
        for r in R:
            val = x[b, r].X
            if val > 0.5:
                result["x_assignment"][b][r] = 1

    if soc is not None:
        for b in B:
            result["soc_time_series"][b] = [round(float(soc[b, t].X), 6) for t in range(num_periods + 1)]

    if y is not None:
        for b in B:
            result["charge_schedule_y"][b] = {}
            for c in C:
                for s in S:
                    key = f"{c}|{s}"
                    series = [int(round(y[b, c, s, t].X)) for t in T]
                    if any(series):
                        result["charge_schedule_y"][b][key] = series

    if e is not None:
        for b in B:
            result["charge_energy_e"][b] = {}
            for c in C:
                for s in S:
                    key = f"{c}|{s}"
                    series = [round(float(e[b, c, s, t].X), 6) for t in T]
                    if any(abs(v) > 1e-9 for v in series):
                        result["charge_energy_e"][b][key] = series

    if pv_use is not None:
        result["pv_use"] = {str(t): round(float(pv_use[t].X), 6) for t in T}

    if grid_buy is not None:
        result["grid_buy"] = {str(t): round(float(grid_buy[t].X), 6) for t in T}

    return result


def status_to_text(status_code: int) -> str:
    mapping = {
        1: "LOADED",
        2: "OPTIMAL",
        3: "INFEASIBLE",
        4: "INF_OR_UNBD",
        5: "UNBOUNDED",
        6: "CUTOFF",
        7: "ITERATION_LIMIT",
        8: "NODE_LIMIT",
        9: "TIME_LIMIT",
        10: "SOLUTION_LIMIT",
        11: "INTERRUPTED",
        12: "NUMERIC",
        13: "SUBOPTIMAL",
        14: "INPROGRESS",
        15: "USER_OBJ_LIMIT",
    }
    return mapping.get(status_code, f"UNKNOWN_{status_code}")


def write_json(path: Path, data: Dict[str, Any]) -> None:
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def parse_args(argv: List[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Solve electric bus prototype MILP with Gurobi")
    parser.add_argument("--config", type=Path, required=True, help="Path to prototype JSON config")
    parser.add_argument(
        "--stage",
        type=str,
        default="full_with_pv",
        choices=sorted(VALID_STAGES),
        help="Model stage to solve",
    )
    parser.add_argument("--output", type=Path, default=Path("result_ebus.json"), help="Output JSON path")
    parser.add_argument("--quiet", action="store_true", help="Disable Gurobi solver log")
    return parser.parse_args(argv)


def main(argv: List[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    cfg = load_json(args.config)
    try:
        result = build_and_solve(cfg, stage=args.stage, verbose=not args.quiet)
    except ConfigError as e:
        print(f"[CONFIG ERROR] {e}", file=sys.stderr)
        return 2
    except RuntimeError as e:
        print(f"[RUNTIME ERROR] {e}", file=sys.stderr)
        return 3

    write_json(args.output, result)
    print(f"Saved result to: {args.output}")
    print(f"Solver status: {result['solver_status']}")
    if result["objective_value"] is not None:
        print(f"Objective value: {result['objective_value']:.6f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
