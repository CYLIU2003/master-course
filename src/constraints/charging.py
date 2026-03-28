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

from ..data_schema import ProblemData
from ..gurobi_runtime import ensure_gurobi
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
    gp, _ = ensure_gurobi()
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
        compatible_c = [c for c in C if c in ms.vehicle_charger_feasible.get(k, set())]
        for c in compatible_c:

            charger = dp.charger_lut[c]
            # 充電器と車両側の出力上限 [kW]
            max_kw = min(
                charger.power_max_kw,
                veh.charge_power_max if veh.charge_power_max else charger.power_max_kw,
            )

            for t in T:
                if (k, c, t) not in z or (k, c, t) not in p:
                    continue
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
                gp.quicksum(z[k, c, t] for c in compatible_c if (k, c, t) in z) <= 1,
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
                running + gp.quicksum(z[k, c, t] for c in compatible_c if (k, c, t) in z) <= 1,
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

    【モデリング仮定 — 論文 §10.5 に記載すること】
    走行エネルギーは task_energy_event_per_slot を使用し、
    トリップ終了直前の1スロットに集中計上する（イベントベース方式）。
    実際には走行中に連続消費されるため、モデル上のSOCは実運用より
    高く見える場合がある。soc_min には最大単一トリップ消費の
    50%以上の安全マージンを確保することを推奨する。

    单位: energy = power[kW] * delta_t_hour → kWh

    vars に必要なキー:
      x_assign  : x[k, r]
      z_charge  : z[k, c, t]
      p_charge  : p_charge[k, c, t]  [kW]
      soc       : soc[k, t]          [kWh]
      slack_soc : slack_soc[k, t]    (任意)
    """
    gp, _ = ensure_gurobi()
    x      = vars["x_assign"]
    p      = vars["p_charge"]
    soc    = vars["soc"]
    y      = vars.get("y_follow")
    slack_soc = vars.get("slack_soc")

    K_BEV = ms.K_BEV
    C     = ms.C
    T     = ms.T
    R     = ms.R
    delta_h = data.delta_t_hour

    for k in K_BEV:
        veh = dp.vehicle_lut[k]
        cap = veh.battery_capacity if veh.battery_capacity is not None else 200.0
        soc_min = veh.soc_min if veh.soc_min is not None else 0.0
        soc_max = veh.soc_max if veh.soc_max is not None else cap
        soc_init = veh.soc_init if veh.soc_init is not None else cap * 0.8
        eff = veh.charge_efficiency

        # ===== §10.5.1 初期 SOC =====
        model.addConstr(soc[k, 0] == soc_init, name=f"soc_init[{k}]")

        # Deadhead energy is applied at the slot right before the successor trip starts.
        deadhead_terms_by_slot = {t: [] for t in T}
        if y is not None:
            for (kk, r1, r2) in y.keys():
                if kk != k:
                    continue
                dh = float(dp.deadhead_energy_kwh.get(r1, {}).get(r2, 0.0) or 0.0)
                if dh <= 0.0:
                    continue
                t2 = dp.task_lut.get(r2)
                if t2 is None:
                    continue
                event_t = min(max(int(t2.start_time_idx) - 1, 0), len(T) - 1)
                deadhead_terms_by_slot[event_t].append((dh, y[kk, r1, r2]))

        # ===== §10.5.1 SOC 遷移 =====
        for t in T:
            # 走行消費 [kWh]
            drive_energy = gp.quicksum(
                (
                    (
                        (dp.task_energy_event_per_slot.get(r) or dp.task_energy_per_slot.get(r) or [0.0] * len(T))[t]
                        if t < len((dp.task_energy_event_per_slot.get(r) or dp.task_energy_per_slot.get(r) or []))
                        else 0.0
                    )
                )
                * x[k, r]
                for r in R
                if r in ms.vehicle_task_feasible.get(k, set())
            )
            # 充電エネルギー [kWh] = Σ (charger_eff * vehicle_eff * p * delta_h)
            # p は系統/サイト側の受電電力として扱うため、
            # 蓄電可能エネルギーは充電器側効率と車両側効率の積で換算する。
            charge_energy = gp.quicksum(
                (dp.charger_lut[c].efficiency if c in dp.charger_lut else 1.0)
                * eff
                * p[k, c, t]
                * delta_h
                for c in C
                if c in ms.vehicle_charger_feasible.get(k, set()) and (k, c, t) in p
            )

            deadhead_energy = gp.quicksum(
                coeff * y_var for coeff, y_var in deadhead_terms_by_slot.get(t, [])
            )
            model.addConstr(
                soc[k, t + 1] == soc[k, t] - drive_energy - deadhead_energy + charge_energy,
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


def add_ice_fuel_constraints(
    model: Any,
    data: ProblemData,
    ms: ModelSets,
    dp: DerivedParams,
    vars: Dict[str, Any],
) -> None:
    """
    ICE 燃料残量の時系列制約を追加する。

    vars に必要なキー:
      x_assign : x[k, r]
      fuel     : fuel[k, t] [L]
    """
    gp, _ = ensure_gurobi()
    x = vars["x_assign"]
    fuel = vars.get("fuel")
    if fuel is None:
        return

    K_ICE = ms.K_ICE
    T = ms.T
    R = ms.R

    for k in K_ICE:
        veh = dp.vehicle_lut[k]
        tank_cap = float(veh.fuel_tank_capacity or 0.0)
        if tank_cap <= 0.0:
            tank_cap = 200.0

        model.addConstr(fuel[k, 0] == tank_cap, name=f"fuel_init[{k}]")

        for t in T:
            burn = gp.quicksum(
                (
                    (dp.task_fuel_per_slot.get(r) or [0.0] * len(T))[t]
                    if t < len((dp.task_fuel_per_slot.get(r) or []))
                    else 0.0
                ) * x[k, r]
                for r in R
                if r in ms.vehicle_task_feasible.get(k, set())
            )
            model.addConstr(
                fuel[k, t + 1] == fuel[k, t] - burn,
                name=f"fuel_balance[{k},{t}]",
            )

        for t in range(len(T) + 1):
            model.addConstr(fuel[k, t] >= 0.0, name=f"fuel_lb[{k},{t}]")
            model.addConstr(fuel[k, t] <= tank_cap, name=f"fuel_ub[{k},{t}]")
