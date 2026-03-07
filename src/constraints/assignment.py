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

try:
    import gurobipy as gp
    from gurobipy import GRB
except ImportError:
    pass

from ..data_schema import ProblemData
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
    x = vars["x_assign"]          # x[k, r]
    u = vars.get("u_vehicle")     # u[k]  (存在しない場合は None)
    slack = vars.get("slack_cover")  # slack[r]

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
    for k in K_ALL:
        for r in R:
            if r not in ms.vehicle_task_feasible.get(k, set()):
                model.addConstr(x[k, r] == 0, name=f"incompat[{k},{r}]")

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
            for r in R:
                model.addConstr(
                    x[k, r] <= u[k],
                    name=f"use_link[{k},{r}]",
                )

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
