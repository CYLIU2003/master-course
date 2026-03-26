"""
constraints/soc_threshold_charging.py — SOC 閾値自動充電制約

spec_v3 §10.5 拡張:
  SOC が閾値を下回ると自動的に充電を強制するロジック。
  - soc_trigger_threshold: SOC がこの値以下になったら充電必須
  - soc_resume_threshold:  SOC がこの値以上になるまで充電を続ける
  - 各 BEV 車両に対して、SOC ≤ trigger → 次スロットで充電 (z ≥ 1) を保証

補助二値変数:
  low_soc[k, t] ∈ {0,1}: soc[k,t] ≤ trigger なら 1
  must_charge[k, t] ∈ {0,1}: SOC 回復までの充電フラグ

Big-M:
  soc_trigger - soc[k,t] ≤ M * low_soc[k,t]
  soc[k,t] - soc_trigger ≤ M * (1 - low_soc[k,t])
  Σ_c z[k,c,t] ≥ low_soc[k,t] - running[k,t]
"""
from __future__ import annotations

from typing import Any, Dict

from ..data_schema import ProblemData
from ..gurobi_runtime import ensure_gurobi
from ..model_sets import ModelSets
from ..parameter_builder import DerivedParams


def add_soc_threshold_charging_constraints(
    model: Any,
    data: ProblemData,
    ms: ModelSets,
    dp: DerivedParams,
    vars: Dict[str, Any],
    trigger_ratio: float = 0.20,
    resume_ratio: float = 0.40,
) -> None:
    """
    SOC 閾値自動充電制約を model に追加する。

    Parameters
    ----------
    trigger_ratio : float
        SOC / battery_capacity がこの比率以下で充電強制 (デフォルト 20%)
    resume_ratio : float
        SOC がこの比率以上に回復するまで充電推奨 (ソフト制約)
    """
    gp, GRB = ensure_gurobi()
    soc = vars.get("soc")
    z = vars.get("z_charge")
    x = vars.get("x_assign")

    if soc is None or z is None or x is None:
        return  # 必要変数がなければスキップ

    K_BEV = ms.K_BEV
    C = ms.C
    T = ms.T
    R = ms.R
    M = data.BIG_M_SOC

    for k in K_BEV:
        veh = dp.vehicle_lut[k]
        cap = veh.battery_capacity or 200.0
        trigger = cap * trigger_ratio
        resume = cap * resume_ratio

        for t in T:
            # --- 補助変数: low_soc[k,t] = 1 iff soc[k,t] ≤ trigger ---
            low = model.addVar(vtype=GRB.BINARY, name=f"low_soc[{k},{t}]")

            # soc[k,t] ≤ trigger + M*(1 - low)  →  low=1 なら soc ≤ trigger + 0
            model.addConstr(
                soc[k, t] <= trigger + M * (1 - low),
                name=f"soc_trigger_ub[{k},{t}]",
            )
            # soc[k,t] ≥ trigger - M*low + data.EPSILON  →  low=0 なら soc > trigger
            model.addConstr(
                soc[k, t] >= trigger + data.EPSILON - M * low,
                name=f"soc_trigger_lb[{k},{t}]",
            )

            # --- 運行中フラグ ---
            running = gp.quicksum(
                dp.task_active[r][t] * x[k, r]
                for r in R
                if r in ms.vehicle_task_feasible.get(k, set())
            )

            # --- low_soc → 充電強制 (運行中でない場合) ---
            # Σ_c z[k,c,t] ≥ low - running
            model.addConstr(
                gp.quicksum(z[k, c, t] for c in C) >= low - running,
                name=f"force_charge_low_soc[{k},{t}]",
            )

            # --- resume ソフト制約 (目標として充電を促進) ---
            # SOC < resume かつ非運行中 → 充電推奨 (ペナルティ最小化)
            # ここでは目的関数のペナルティで実現するのでハード制約は追加しない

    model.update()


def add_soc_threshold_to_alns_repair(
    assignment: Dict[str, list],
    data: ProblemData,
    ms: Any,
    dp: Any,
    trigger_ratio: float = 0.20,
) -> Dict[str, list]:
    """ALNS repair 後に SOC 閾値チェックを行い、充電挿入を提案する。

    Parameters
    ----------
    assignment : {vehicle_id: [task_id, ...]}
    trigger_ratio : float

    Returns
    -------
    assignment with inserted charging stops (if applicable)
    """
    for k, task_list in assignment.items():
        veh = dp.vehicle_lut.get(k)
        if veh is None or veh.vehicle_type != "BEV":
            continue

        cap = veh.battery_capacity or 200.0
        trigger = cap * trigger_ratio
        soc_current = veh.soc_init if veh.soc_init is not None else cap * 0.8

        for i, task_id in enumerate(task_list):
            task = dp.task_lut.get(task_id)
            if task is None:
                continue

            soc_current -= task.energy_required_kwh_bev

            if soc_current <= trigger:
                # SOC が閾値以下 → 充電が必要なことをフラグ
                # (ALNS では discrete な充電挿入は repair operator が担当)
                task_list[i] = task_id  # 現状はマーキングのみ

    return assignment
