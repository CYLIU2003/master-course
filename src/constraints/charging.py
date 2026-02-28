"""
constraints/charging.py — 充電スケジュール制約群

仕様書 §10.4, §10.5 担当:
  - 充電器利用有無リンク制約 (§10.4.2)
  - 同時充電・排他制約
  - 運行中充電禁止
  - SOC 遷移制約 (§10.5)
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


def add_charging_constraints(
    model: Any,
    data: ProblemData,
    ms: ModelSets,
    dp: DerivedParams,
    vars: Dict[str, Any],
) -> None:
    """
    充電制約を model に追加する。

    vars に必要なキー:
      x_assign  : x[k, r]
      z_charge  : z[k, c, t]
      p_charge  : p_charge[k, c, t]
    """
    x = vars["x_assign"]
    z = vars["z_charge"]          # z[k, c, t]
    p = vars["p_charge"]          # p[k, c, t]  [kW]

    K_BEV = ms.K_BEV
    C     = ms.C
    T     = ms.T
    R     = ms.R
    delta_h = data.delta_t_hour  # [hour/slot]

    for k in K_BEV:
        veh = dp.vehicle_lut[k]
        for c in C:
            # 互換性チェック
            if c not in ms.vehicle_charger_feasible.get(k, set()):
                # 互換性なし → 変数を 0 に固定
                for t in T:
                    model.addConstr(z[k, c, t] == 0, name=f"compat_z[{k},{c},{t}]")
                    model.addConstr(p[k, c, t] == 0, name=f"compat_p[{k},{c},{t}]")
                continue

            charger = dp.charger_lut[c]
            # 充電器と車両側の出力上限 [kW]
            max_kw = min(
                charger.power_max_kw,
                veh.charge_power_max if veh.charge_power_max else charger.power_max_kw,
            )

            for t in T:
                # ===== §10.4.2 充電電力上限 =====
                # p[k,c,t] <= max_kw * z[k,c,t]
                model.addConstr(
                    p[k, c, t] <= max_kw * z[k, c, t],
                    name=f"charge_pwr_ub[{k},{c},{t}]",
                )
                # p[k,c,t] >= charger.power_min_kw * z[k,c,t]
                if charger.power_min_kw > 0:
                    model.addConstr(
                        p[k, c, t] >= charger.power_min_kw * z[k, c, t],
                        name=f"charge_pwr_lb[{k},{c},{t}]",
                    )

        # ===== 同時多箇所充電禁止 =====
        for t in T:
            model.addConstr(
                gp.quicksum(z[k, c, t] for c in C) <= 1,
                name=f"single_charge[{k},{t}]",
            )

        # ===== 運行中充電禁止 =====
        for t in T:
            running = gp.quicksum(
                dp.task_active[r][t] * x[k, r]
                for r in R
                if r in ms.vehicle_task_feasible.get(k, set())
            )
            model.addConstr(
                running + gp.quicksum(z[k, c, t] for c in C) <= 1,
                name=f"no_run_charge[{k},{t}]",
            )


def add_soc_constraints(
    model: Any,
    data: ProblemData,
    ms: ModelSets,
    dp: DerivedParams,
    vars: Dict[str, Any],
) -> None:
    """
    SOC 遷移制約を model に追加する (§10.5)。

    单位: energy = power[kW] * delta_t_hour → kWh

    vars に必要なキー:
      x_assign  : x[k, r]
      z_charge  : z[k, c, t]
      p_charge  : p_charge[k, c, t]  [kW]
      soc       : soc[k, t]          [kWh]
      slack_soc : slack_soc[k, t]    (任意)
    """
    x      = vars["x_assign"]
    p      = vars["p_charge"]
    soc    = vars["soc"]
    slack_soc = vars.get("slack_soc")

    K_BEV = ms.K_BEV
    C     = ms.C
    T     = ms.T
    R     = ms.R
    delta_h = data.delta_t_hour

    for k in K_BEV:
        veh = dp.vehicle_lut[k]
        cap = veh.battery_capacity or 200.0
        soc_min = veh.soc_min or 0.0
        soc_max = veh.soc_max or cap
        soc_init = veh.soc_init or cap * 0.8
        eff = veh.charge_efficiency

        # ===== §10.5.1 初期 SOC =====
        model.addConstr(soc[k, 0] == soc_init, name=f"soc_init[{k}]")

        # ===== §10.5.1 SOC 遷移 =====
        for t in T:
            # 走行消費 [kWh]
            drive_energy = gp.quicksum(
                dp.task_energy_per_slot[r][t] * x[k, r]
                for r in R
                if r in ms.vehicle_task_feasible.get(k, set())
            )
            # 充電エネルギー [kWh] = Σ eff * p * delta_h
            charge_energy = gp.quicksum(
                eff * p[k, c, t] * delta_h
                for c in C
                if c in ms.vehicle_charger_feasible.get(k, set())
            )
            model.addConstr(
                soc[k, t + 1] == soc[k, t] - drive_energy + charge_energy,
                name=f"soc_balance[{k},{t}]",
            )

        # ===== §10.5.2 SOC 上下限 =====
        for t in range(len(T) + 1):
            if data.use_soft_soc_constraint and slack_soc is not None:
                model.addConstr(
                    soc[k, t] >= soc_min - slack_soc[k, t],
                    name=f"soc_lb_soft[{k},{t}]",
                )
            else:
                model.addConstr(soc[k, t] >= soc_min, name=f"soc_lb[{k},{t}]")
            model.addConstr(soc[k, t] <= soc_max, name=f"soc_ub[{k},{t}]")

        # ===== §10.5.2 終了時目標 SOC =====
        if veh.soc_target_end is not None:
            model.addConstr(
                soc[k, len(T)] >= veh.soc_target_end,
                name=f"soc_target_end[{k}]",
            )
