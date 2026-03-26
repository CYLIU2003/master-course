"""
constraints/assignment.py — 割当制約群

仕様書 §10.1, §10.2 担当:
  - 各タスクの担当制約 (§10.1.1)
  - 車両ごとの担当可能性 (§10.1.2)
  - 時間重複タスクの排他制約 (§10.1.2)
  - 稼働時間・距離制約 (§10.2)
  - 未割当ペナルティ緩和 (§10.11)
"""
from __future__ import annotations

from typing import Any, Dict

from ..data_schema import ProblemData
from ..gurobi_runtime import ensure_gurobi
from ..model_sets import ModelSets
from ..parameter_builder import DerivedParams


def add_assignment_constraints(
    model: Any,
    data: ProblemData,
    ms: ModelSets,
    dp: DerivedParams,
    vars: Dict[str, Any],
) -> None:
    """
    割当制約を model に追加する。

    Parameters
    ----------
    model  : gurobipy.Model
    data   : ProblemData
    ms     : ModelSets
    dp     : DerivedParams
    vars   : 変数辞書 {x_assign, u_vehicle, slack_cover, ...}
    """
    gp, _ = ensure_gurobi()
    x = vars["x_assign"]          # x[k, r]
    u = vars.get("u_vehicle")     # u[k]  (存在しない場合は None)
    slack = vars.get("slack_cover")  # slack[r]
    y = vars.get("y_follow")

    K_ALL = ms.K_ALL
    R     = ms.R

    # ===== §10.1.1 各タスクは高々 1 台が担当 =====
    for r in R:
        task = dp.task_lut[r]
        lhs = gp.quicksum(
            x[k, r]
            for k in K_ALL
            if r in ms.vehicle_task_feasible.get(k, set())
        )
        if task.demand_cover and not data.allow_partial_service:
            # 完全充足: sum_k x[k,r] == 1
            model.addConstr(lhs == 1, name=f"assign_once[{r}]")
        elif slack is not None:
            # 不完全許容: sum_k x[k,r] + slack[r] >= 1
            model.addConstr(lhs + slack[r] >= 1, name=f"assign_soft[{r}]")
        else:
            model.addConstr(lhs <= 1, name=f"assign_at_most_one[{r}]")

    # ===== §10.1.2 車種不適合禁止 =====
    # infeasible (k,r) は変数を生成しない設計に変更したため、
    # 明示的な x[k,r]==0 制約は不要。

    # ===== §10.1.2 重複便禁止 =====
    for k in K_ALL:
        for r1, r2 in dp.overlap_pairs:
            c1 = r1 in ms.vehicle_task_feasible.get(k, set())
            c2 = r2 in ms.vehicle_task_feasible.get(k, set())
            if c1 and c2:
                model.addConstr(
                    x[k, r1] + x[k, r2] <= 1,
                    name=f"no_overlap[{k},{r1},{r2}]",
                )

    # ===== §10.1.3 u[k] リンク =====
    if u is not None:
        for k in K_ALL:
            feasible_r = [r for r in R if r in ms.vehicle_task_feasible.get(k, set())]
            if not feasible_r:
                model.addConstr(u[k] == 0, name=f"use_link_empty[{k}]")
                continue
            model.addConstr(
                gp.quicksum(x[k, r] for r in feasible_r) <= len(feasible_r) * u[k],
                name=f"use_link[{k}]",
            )

    # ===== タスク連結アーク制約 (y_follow) =====
    if y is not None and u is not None:
        for k in K_ALL:
            feasible_r = [r for r in R if r in ms.vehicle_task_feasible.get(k, set())]
            if not feasible_r:
                continue

            out_map = {r: [] for r in feasible_r}
            in_map = {r: [] for r in feasible_r}
            edge_count_expr = gp.LinExpr()

            for r1 in feasible_r:
                for r2 in dp.can_follow.get(r1, {}).keys():
                    key = (k, r1, r2)
                    if key not in y:
                        continue
                    out_map[r1].append(r2)
                    in_map.setdefault(r2, []).append(r1)
                    edge_count_expr += y[key]

            # For a connected path on assigned tasks: edges = assigned_tasks - 1 when u=1.
            model.addConstr(
                edge_count_expr == gp.quicksum(x[k, r] for r in feasible_r) - u[k],
                name=f"follow_edge_count[{k}]",
            )

            for r in feasible_r:
                out_expr = gp.quicksum(y[k, r, r2] for r2 in out_map.get(r, []))
                in_expr = gp.quicksum(y[k, r1, r] for r1 in in_map.get(r, []))
                model.addConstr(out_expr <= x[k, r], name=f"follow_out_link[{k},{r}]")
                model.addConstr(in_expr <= x[k, r], name=f"follow_in_link[{k},{r}]")
                model.addConstr(out_expr <= 1, name=f"follow_out_deg[{k},{r}]")
                model.addConstr(in_expr <= 1, name=f"follow_in_deg[{k},{r}]")

    # ===== §10.2 最大稼働時間制約 =====
    delta_h = data.delta_t_hour
    for k in K_ALL:
        veh = dp.vehicle_lut[k]
        max_slots = veh.max_operating_time / delta_h
        operating_time_expr = gp.quicksum(
            dp.task_duration_slot.get(r, 0) * x[k, r]
            for r in R
            if r in ms.vehicle_task_feasible.get(k, set())
        )
        model.addConstr(
            operating_time_expr <= max_slots,
            name=f"max_operating_time[{k}]",
        )

    # ===== §10.2 最大走行距離制約 =====
    for k in K_ALL:
        veh = dp.vehicle_lut[k]
        dist_expr = gp.quicksum(
            dp.task_distance_km.get(r, 0) * x[k, r]
            for r in R
            if r in ms.vehicle_task_feasible.get(k, set())
        )
        model.addConstr(
            dist_expr <= veh.max_distance,
            name=f"max_distance[{k}]",
        )

    # ===== ICE 燃料タンク容量制約 =====
    for k in ms.K_ICE:
        veh = dp.vehicle_lut[k]
        tank_cap = float(veh.fuel_tank_capacity or 0.0)
        if tank_cap <= 0.0:
            continue
        fuel_expr = gp.quicksum(
            dp.task_fuel_ice.get(r, 0.0) * x[k, r]
            for r in R
            if r in ms.vehicle_task_feasible.get(k, set())
        )
        model.addConstr(
            fuel_expr <= tank_cap,
            name=f"fuel_tank_cap[{k}]",
        )
