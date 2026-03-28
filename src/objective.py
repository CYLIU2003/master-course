"""
objective.py — 目的関数構築

仕様書 §9 担当:
  - 各コスト項を加重和で最小化する
  - 係数は config の objective_weights で変更可能
  - 目的関数の各項は個別にログ出力できる構造

最小化対象 (§9.1):
  w1  * vehicle_fixed_cost
  w2  * electricity_cost
  w3  * demand_charge_cost
  w4  * fuel_cost
  w5  * deadhead_cost
  w6  * battery_degradation_cost
  w7  * emission_cost
  w8  * unserved_penalty
  w9  * slack_penalty

単位: 円
"""
from __future__ import annotations

from typing import Any, Dict

from .data_schema import ProblemData
from .gurobi_runtime import ensure_gurobi
from .model_sets import ModelSets
from .parameter_builder import DerivedParams, get_grid_price, get_sell_back_price, resolve_vehicle_energy_site_id


def build_objective(
    model: Any,
    data: ProblemData,
    ms: ModelSets,
    dp: DerivedParams,
    vars: Dict[str, Any],
) -> None:
    """
    目的関数を model に設定する (§9.2)。

    目的関数の各項は vars["obj_terms"] dict に格納し、
    後から個別ログ出力できるようにする。

    Parameters
    ----------
    model : gurobipy.Model
    data  : ProblemData
    ms    : ModelSets
    dp    : DerivedParams
    vars  : 変数辞書
    """
    gp, GRB = ensure_gurobi()
    w = data.objective_weights
    K_ALL = ms.K_ALL
    K_BEV = ms.K_BEV
    K_ICE = ms.K_ICE
    R     = ms.R
    T     = ms.T
    C     = ms.C

    x     = vars["x_assign"]
    u     = vars.get("u_vehicle")
    p_grid = vars.get("p_grid_import")
    p_grid_export = vars.get("p_grid_export")
    peak  = vars.get("peak_demand")
    deg   = vars.get("deg")
    slack_cover = vars.get("slack_cover")
    slack_soc   = vars.get("slack_soc")

    obj_expr = gp.LinExpr()
    obj_terms: Dict[str, Any] = {}

    def _append_term(name: str, expr: Any) -> None:
        if expr is None:
            return
        obj_terms[name] = expr
        nonlocal obj_expr
        obj_expr += expr

    # ===== w1: 車両使用固定費 =====
    if w.get("vehicle_fixed_cost", 0.0) > 0 and u is not None:
        term = gp.LinExpr()
        for k in K_ALL:
            veh = dp.vehicle_lut[k]
            term += w["vehicle_fixed_cost"] * veh.fixed_use_cost * u[k]
        _append_term("vehicle_fixed_cost", term)

    # ===== w2: 電力量料金 =====
    if w.get("electricity_cost", 0.0) > 0:
        term = gp.LinExpr()
        if p_grid is not None:
            delta_h = data.delta_t_hour
            for site_id in ms.I_CHARGE:
                for t in T:
                    buy_price = get_grid_price(dp, site_id, t)
                    term += w["electricity_cost"] * buy_price * p_grid[site_id, t] * delta_h
                    if p_grid_export is not None:
                        sell_price = get_sell_back_price(dp, site_id, t)
                        term += -w["electricity_cost"] * sell_price * p_grid_export[site_id, t] * delta_h
        else:
            # energy_balance を使わない旧モード互換: 既存の走行消費課金をフォールバック
            for k in K_BEV:
                site_id = resolve_vehicle_energy_site_id(ms, dp, k)
                feasible_tasks = ms.vehicle_task_feasible.get(k, set())
                for r in feasible_tasks:
                    energy_per_slot = dp.task_energy_per_slot.get(r, [])
                    for t in T:
                        if t >= len(energy_per_slot):
                            continue
                        energy_kwh = float(energy_per_slot[t] or 0.0)
                        if energy_kwh <= 0.0:
                            continue
                        price = get_grid_price(dp, site_id, t)
                        term += w["electricity_cost"] * price * energy_kwh * x[k, r]
        _append_term("electricity_cost", term)

    # ===== w3: デマンド料金 =====
    if w.get("demand_charge_cost", 0.0) > 0 and peak is not None and data.enable_demand_charge:
        term = gp.LinExpr()
        # demand_charge_rate_per_kw は月額 [円/kW/月]。
        # 最適化ホライズン（planning_horizon_hours）に合わせて日割り換算する。
        horizon_days = data.planning_horizon_hours / 24.0
        monthly_to_horizon_factor = horizon_days / 30.0
        for site_id in ms.I_CHARGE:
            term += (
                w["demand_charge_cost"]
                * data.demand_charge_rate_per_kw
                * monthly_to_horizon_factor
                * peak[site_id]
            )
        _append_term("demand_charge_cost", term)

    # ===== w4: ICE 燃料費 =====
    if w.get("fuel_cost", 0.0) > 0:
        term = gp.LinExpr()
        for k in K_ICE:
            veh = dp.vehicle_lut[k]
            fuel_cost = veh.fuel_cost_coeff  # 円/L
            for r in R:
                if r in ms.vehicle_task_feasible.get(k, set()):
                    fuel_l = dp.task_fuel_ice.get(r, 0.0)
                    term += w["fuel_cost"] * fuel_cost * fuel_l * x[k, r]
        _append_term("fuel_cost", term)

    # ===== w5: 回送コスト (距離ベース簡易) =====
    if w.get("deadhead_cost", 0.0) > 0:
        dh_cost_per_km = 50.0  # 円/km (デフォルト; 拡張可能)
        term = gp.LinExpr()
        y = vars.get("y_follow")
        if y is not None:
            for (k, r1_id, r2_id) in y.keys():
                dh_dist = float(dp.deadhead_distance_km.get(r1_id, {}).get(r2_id, 0.0) or 0.0)
                if dh_dist <= 0.0:
                    continue
                term += w["deadhead_cost"] * dh_cost_per_km * dh_dist * y[k, r1_id, r2_id]
        _append_term("deadhead_cost", term)

    # ===== w6: 電池劣化コスト =====
    if w.get("battery_degradation_cost", 0.0) > 0 and deg is not None and data.enable_battery_degradation:
        term = gp.LinExpr()
        for k in K_BEV:
            for t in T:
                term += w["battery_degradation_cost"] * deg[k, t]
        _append_term("battery_degradation_cost", term)

    # ===== w7: CO2 排出コスト =====
    if w.get("emission_cost", 0.0) > 0:
        term = gp.LinExpr()
        co2_price_per_kg = data.co2_price_per_kg
        for k in K_ICE:
            veh = dp.vehicle_lut[k]
            co2_coeff = veh.co2_emission_coeff  # kg-CO2/L
            for r in R:
                if r in ms.vehicle_task_feasible.get(k, set()):
                    fuel_l = dp.task_fuel_ice.get(r, 0.0)
                    co2_kg = co2_coeff * fuel_l
                    term += w["emission_cost"] * co2_price_per_kg * co2_kg * x[k, r]
        for k in K_BEV:
            site_id = resolve_vehicle_energy_site_id(ms, dp, k)
            feasible_tasks = ms.vehicle_task_feasible.get(k, set())
            for r in feasible_tasks:
                energy_per_slot = dp.task_energy_per_slot.get(r, [])
                for t in T:
                    if t >= len(energy_per_slot):
                        continue
                    co2_factor = dp.grid_co2_factor.get(site_id, {}).get(t, 0.0)
                    if co2_factor <= 0:
                        continue
                    energy_kwh = float(energy_per_slot[t] or 0.0)
                    if energy_kwh <= 0.0:
                        continue
                    term += (
                        w["emission_cost"]
                        * co2_price_per_kg
                        * co2_factor
                        * energy_kwh
                        * x[k, r]
                    )
        _append_term("emission_cost", term)

    # ===== w8: 未割当ペナルティ =====
    if w.get("unserved_penalty", 0.0) > 0 and slack_cover is not None:
        term = gp.LinExpr()
        for r in R:
            task = dp.task_lut[r]
            term += w["unserved_penalty"] * task.penalty_unserved * slack_cover[r]
        _append_term("unserved_penalty", term)

    # ===== w9: 緩和変数ペナルティ =====
    if w.get("slack_penalty", 0.0) > 0 and slack_soc is not None:
        term = gp.LinExpr()
        for k in K_BEV:
            for t in range(len(T) + 1):
                term += w["slack_penalty"] * slack_soc[k, t]
        _append_term("slack_penalty", term)

    # ===== w10: デポ充電インフラコスト (距離 + 電力複合) =====
    depot_infra_weight = w.get("depot_charger_cost", 0.0)
    if depot_infra_weight > 0:
        # デポ距離関連: 車両がデポ外充電器へ迂回する場合の走行コスト
        depot_detour_cost_per_km = w.get("depot_detour_cost_per_km", 80.0)  # 円/km
        # 充電器設置コスト (日割): 設置 site 数 × 日額固定費
        charger_daily_cost = w.get("charger_daily_fixed_cost", 500.0)  # 円/基/日
        term = gp.LinExpr()

        # 充電器利用実績 → 充電器固定費 (利用された充電器のみ)
        z = vars.get("z_charge")
        if z is not None:
            charger_used = {}
            for c in C:
                charger_used[c] = model.addVar(
                    vtype=GRB.BINARY, name=f"charger_used[{c}]")
                for t in T:
                    for k_bev in K_BEV:
                        if c in ms.vehicle_charger_feasible.get(k_bev, set()):
                            model.addConstr(
                                charger_used[c] >= z[k_bev, c, t],
                                name=f"charger_used_link[{c},{k_bev},{t}]",
                            )
                term += depot_infra_weight * charger_daily_cost * charger_used[c]

        # 充電迂回距離コスト
        y = vars.get("y_follow")
        if y is not None:
            for k in K_ALL:
                for r1_id in R:
                    for r2_id in R:
                        if r1_id == r2_id:
                            continue
                        # depot/charger 迂回弧のみ (通常の trip-to-trip は w5 でカバー)
                        if r2_id.startswith("__charger_") or r2_id.startswith("__depot_"):
                            dh_dist = dp.deadhead_distance_km.get(r1_id, {}).get(r2_id, 0.0)
                            if dh_dist > 0 and (k, r1_id, r2_id) in y:
                                term += (
                                    depot_infra_weight
                                    * depot_detour_cost_per_km
                                    * dh_dist
                                    * y[k, r1_id, r2_id]
                                )
        _append_term("depot_charger_cost", term)

    # ===== w11: 充電電力ピークシェービング =====
    peak_shaving_weight = w.get("peak_shaving_cost", 0.0)
    if peak_shaving_weight > 0 and peak is not None:
        # ピーク電力に対するペナルティ (デマンドチャージとは別のインセンティブ)
        term = gp.LinExpr()
        for site_id in ms.I_CHARGE:
            term += peak_shaving_weight * peak[site_id]
        _append_term("peak_shaving_cost", term)

    vars["obj_terms"] = obj_terms
    model.setObjective(obj_expr, GRB.MINIMIZE)
