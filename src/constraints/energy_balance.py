"""
constraints/energy_balance.py — 電力需給バランス制約

仕様書 §10.6, §10.7 担当:
  各地点・時刻で充電需要 = 系統受電 + PV自家消費 + V2G放電 が成立する制約。
  PV・V2G が無効の場合は系統受電 = 充電需要のみ。

  単位: kW (電力), kWh (エネルギー)
  ※ kW × delta_t_hour = kWh に注意 (§16)
"""
from __future__ import annotations

from typing import Any, Dict

from ..data_schema import ProblemData
from ..gurobi_runtime import ensure_gurobi
from ..model_sets import ModelSets
from ..parameter_builder import (
    DerivedParams,
    get_base_load,
    get_pv_gen,
    resolve_vehicle_energy_site_id,
)


def add_energy_balance_constraints(
    model: Any,
    data: ProblemData,
    ms: ModelSets,
    dp: DerivedParams,
    vars: Dict[str, Any],
) -> None:
    """
    各地点・時刻の電力収支制約を追加する (§10.6)。

    vars に必要なキー:
      p_charge      : p_charge[k, c, t]   [kW]
      p_grid_import : p_grid_import[i, t] [kW]  (site_id, time_idx)
      p_pv_used     : p_pv_used[i, t]    [kW]  (PV 有効時)
      p_pv_curtail  : p_pv_curtail[i, t] [kW]  (PV 有効時)
      p_discharge   : p_discharge[k, c, t] (V2G 有効時)
    """
    gp, _ = ensure_gurobi()
    p           = vars["p_charge"]
    p_grid      = vars["p_grid_import"]
    p_pv_used   = vars.get("p_pv_used")
    p_pv_cur    = vars.get("p_pv_curtail")
    p_dis       = vars.get("p_discharge")

    K_BEV = ms.K_BEV
    T     = ms.T

    # Depo サイトのみで電力収支を管理する簡易版
    # (terminal_B には充電器が無い想定)
    charge_sites = ms.I_CHARGE

    for site_id in charge_sites:
        site_chargers = ms.C_at_site.get(site_id, [])
        if not site_chargers:
            continue

        site = dp.site_lut.get(site_id)
        grid_limit = site.grid_import_limit_kw if site else 9999.0

        for t in T:
            # 地点 site の全充電電力合計 [kW]
            total_charge_kw = gp.quicksum(
                p[k, c, t]
                for k in K_BEV
                for c in site_chargers
                if c in ms.vehicle_charger_feasible.get(k, set())
            )
            
            # 地点 site の全放電電力合計 [kW] (P0: V2G有効時のエネルギー収支)
            total_discharge_kw = 0.0
            if data.enable_v2g and p_dis is not None:
                total_discharge_kw = gp.quicksum(
                    p_dis[k, c, t]
                    for k in K_BEV
                    for c in site_chargers
                    if c in ms.vehicle_charger_feasible.get(k, set())
                )

            # 基礎負荷 [kW]
            base = get_base_load(dp, site_id, t)

            if data.enable_pv and p_pv_used is not None and p_pv_cur is not None:
                # PV 有効: §10.6 電力収支
                pv_cap = get_pv_gen(dp, site_id, t)
                model.addConstr(
                    p_pv_used[site_id, t] + p_pv_cur[site_id, t] <= pv_cap,
                    name=f"pv_cap[{site_id},{t}]",
                )
                # §10.8 自家消費優先
                model.addConstr(
                    p_pv_used[site_id, t] <= total_charge_kw + base - total_discharge_kw,
                    name=f"pv_self_consume[{site_id},{t}]",
                )
                # 電力収支
                model.addConstr(
                    p_grid[site_id, t] + p_pv_used[site_id, t] + total_discharge_kw == total_charge_kw + base,
                    name=f"power_balance[{site_id},{t}]",
                )
            else:
                # PV なし: 系統受電 = 充電需要 + 基礎負荷
                model.addConstr(
                    p_grid[site_id, t] + total_discharge_kw == total_charge_kw + base,
                    name=f"power_balance_no_pv[{site_id},{t}]",
                )

            # §10.7 系統受電上限
            model.addConstr(
                p_grid[site_id, t] <= grid_limit,
                name=f"grid_import_ub[{site_id},{t}]",
            )


def add_demand_charge_constraints(
    model: Any,
    data: ProblemData,
    ms: ModelSets,
    dp: DerivedParams,
    vars: Dict[str, Any],
) -> None:
    """
    デマンド料金制約を追加する (§10.7)。

    vars に必要なキー:
      p_grid_import : p_grid_import[i, t]
      peak_demand   : peak_demand[i]
    """
    ensure_gurobi()
    if not data.enable_demand_charge:
        return

    x_assign  = vars.get("x_assign")
    peak      = vars.get("peak_demand")
    if peak is None:
        return

    charge_sites = ms.I_CHARGE
    delta_h = max(float(data.delta_t_hour or 0.0), 1.0e-9)

    for site_id in charge_sites:
        site = dp.site_lut.get(site_id)
        contract_kw = site.contract_demand_limit_kw if site else 9999.0

        for t in ms.T:
            operating_demand_kw = 0.0
            if x_assign is not None:
                for vehicle_id in ms.K_BEV:
                    if resolve_vehicle_energy_site_id(ms, dp, vehicle_id) != site_id:
                        continue
                    for task_id in ms.vehicle_task_feasible.get(vehicle_id, set()):
                        energy_per_slot = dp.task_energy_per_slot.get(task_id, [])
                        if t >= len(energy_per_slot):
                            continue
                        energy_kwh = float(energy_per_slot[t] or 0.0)
                        if energy_kwh <= 0.0:
                            continue
                        operating_demand_kw += (energy_kwh / delta_h) * x_assign[vehicle_id, task_id]
            model.addConstr(operating_demand_kw <= peak[site_id], name=f"peak_track[{site_id},{t}]")
        model.addConstr(
            peak[site_id] <= contract_kw,
            name=f"contract_demand[{site_id}]",
        )
