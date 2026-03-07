"""
constraints/duty_assignment.py — 行路制約付き割当制約群

日本バス業界の「行路設定表」に基づく車両割当制約を MILP に追加する。

行路制約モード (duty_enabled=True):
  - 各 duty に 1 台の車両を割り当てる
  - 行路内の trip は同一車両が順序どおり担当する
  - 行路間のデッドヘッド接続や充電はレグで規定

任意割当モード (duty_enabled=False):
  - 従来どおり x[k,r] による自由割当 → この関数は何もしない
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Set

try:
    import gurobipy as gp
    from gurobipy import GRB
except ImportError:
    pass

from ..data_schema import ProblemData
from ..model_sets import ModelSets
from ..parameter_builder import DerivedParams
from ..schemas.duty_entities import VehicleDuty, DutyAssignmentConfig


def add_duty_assignment_constraints(
    model: Any,
    data: ProblemData,
    ms: ModelSets,
    dp: DerivedParams,
    vars: Dict[str, Any],
    duties: List[VehicleDuty],
    config: Optional[DutyAssignmentConfig] = None,
) -> Dict[str, Any]:
    """行路表に基づく割当制約を model に追加する。

    Parameters
    ----------
    model : gurobipy.Model
    data : ProblemData
    ms : ModelSets
    dp : DerivedParams
    vars : 既存変数辞書 {x_assign, u_vehicle, ...}
    duties : List[VehicleDuty]  行路リスト
    config : DutyAssignmentConfig

    Returns
    -------
    Dict[str, Any] : 追加変数辞書 {y_duty_assign, ...}
    """
    if config is None:
        config = DutyAssignmentConfig(enabled=True)

    if not config.enabled or not duties:
        return {}

    x = vars["x_assign"]
    u = vars.get("u_vehicle")
    K_ALL = ms.K_ALL
    R = ms.R

    # 行路集合
    D = [d.duty_id for d in duties]
    duty_lut = {d.duty_id: d for d in duties}

    # --- 新変数: y_duty[k, d] = 車両 k が行路 d を担当 ---
    y_duty = {}
    for k in K_ALL:
        for d_id in D:
            y_duty[k, d_id] = model.addVar(
                vtype=GRB.BINARY,
                name=f"y_duty[{k},{d_id}]",
            )
    model.update()

    # ===== 制約 1: 各行路は必ず 1 台が担当 =====
    for d_id in D:
        duty = duty_lut[d_id]
        feasible_vehicles = _get_feasible_vehicles(duty, ms, dp, config)
        model.addConstr(
            gp.quicksum(y_duty[k, d_id] for k in feasible_vehicles) == 1,
            name=f"duty_assign_once[{d_id}]",
        )

    # ===== 制約 2: 各車両は高々 1 つの行路を担当 =====
    for k in K_ALL:
        model.addConstr(
            gp.quicksum(y_duty[k, d_id] for d_id in D) <= 1,
            name=f"vehicle_one_duty[{k}]",
        )

    # ===== 制約 3: 行路内の trip は同一車両が担当 (y → x リンク) =====
    for d_id in D:
        duty = duty_lut[d_id]
        trip_ids = duty.trip_ids
        for tid in trip_ids:
            if tid not in R:
                continue
            for k in K_ALL:
                # y_duty[k, d] <= x[k, tid]  (行路を担当 → 全 trip を担当)
                if (k, tid) in x:
                    model.addConstr(
                        y_duty[k, d_id] <= x[k, tid],
                        name=f"duty_trip_link[{k},{d_id},{tid}]",
                    )

    # ===== 制約 4: 行路内 trip は他の車両が担当不可 =====
    duty_trip_set: Set[str] = set()
    for duty in duties:
        duty_trip_set.update(duty.trip_ids)

    for tid in duty_trip_set:
        if tid not in R:
            continue
        # duty に含まれる trip は、その duty の車両のみが担当可能
        duty_id = None
        for d in duties:
            if tid in d.trip_ids:
                duty_id = d.duty_id
                break
        if duty_id is None:
            continue

        for k in K_ALL:
            if (k, tid) in x:
                # x[k, tid] <= y_duty[k, duty_id]
                model.addConstr(
                    x[k, tid] <= y_duty[k, duty_id],
                    name=f"duty_exclusive[{k},{tid},{duty_id}]",
                )

    # ===== 制約 5: u[k] リンク (行路 → 車両使用) =====
    if u is not None:
        for k in K_ALL:
            for d_id in D:
                model.addConstr(
                    y_duty[k, d_id] <= u[k],
                    name=f"duty_use_link[{k},{d_id}]",
                )

    # ===== 制約 6: 行路稼働時間制約 =====
    delta_h = data.delta_t_hour
    for d_id in D:
        duty = duty_lut[d_id]
        for k in K_ALL:
            veh = dp.vehicle_lut.get(k)
            if veh is None:
                continue
            max_slots = veh.max_operating_time / delta_h
            duty_time_slot = duty.total_operating_time_min / (delta_h * 60.0)
            if duty_time_slot > max_slots:
                # この車両は行路に不適合 → y=0
                model.addConstr(
                    y_duty[k, d_id] == 0,
                    name=f"duty_time_infeasible[{k},{d_id}]",
                )

    # ===== 制約 7: 行路に含まれない trip は従来どおり自由割当 =====
    # (何もしない: x[k, r] の通常 assignment 制約がそのまま適用される)

    return {"y_duty": y_duty}


def _get_feasible_vehicles(
    duty: VehicleDuty,
    ms: ModelSets,
    dp: DerivedParams,
    config: DutyAssignmentConfig,
) -> List[str]:
    """行路に適合する車両リストを返す。"""
    feasible = list(ms.K_ALL)

    if duty.required_vehicle_id:
        return [duty.required_vehicle_id] if duty.required_vehicle_id in ms.K_ALL else []

    if config.enforce_vehicle_type_match and duty.required_vehicle_type:
        if duty.required_vehicle_type == "BEV":
            feasible = [k for k in feasible if k in ms.K_BEV]
        elif duty.required_vehicle_type == "ICE":
            feasible = [k for k in feasible if k in ms.K_ICE]

    if config.enforce_depot_match and duty.depot_id:
        feasible = [
            k for k in feasible
            if dp.vehicle_lut.get(k) and dp.vehicle_lut[k].home_depot == duty.depot_id
        ]

    return feasible


def get_duty_assignment_result(
    vars_dict: Dict[str, Any],
    duties: List[VehicleDuty],
    K_ALL: List[str],
) -> Dict[str, str]:
    """最適化結果から duty → vehicle マッピングを抽出する。

    Returns
    -------
    Dict[duty_id, vehicle_id]
    """
    y_duty = vars_dict.get("y_duty", {})
    if not y_duty:
        return {}

    result: Dict[str, str] = {}
    for d in duties:
        for k in K_ALL:
            if (k, d.duty_id) in y_duty:
                val = y_duty[k, d.duty_id].X
                if val > 0.5:
                    result[d.duty_id] = k
                    break
    return result
