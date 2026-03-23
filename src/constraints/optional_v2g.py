"""
constraints/optional_v2g.py — V2G (Vehicle-to-Grid) 制約 (§10.9)

V2G が有効な場合のみロードされる任意制約群。
  - 充電と放電の同時実行禁止
  - 放電電力上限
  - 系統逆潮流制約

単位: kW, kWh (§16)
"""
from __future__ import annotations

from typing import Any, Dict

from ..data_schema import ProblemData
from ..gurobi_runtime import ensure_gurobi
from ..model_sets import ModelSets
from ..parameter_builder import DerivedParams


def add_v2g_constraints(
    model: Any,
    data: ProblemData,
    ms: ModelSets,
    dp: DerivedParams,
    vars: Dict[str, Any],
) -> None:
    """
    V2G 制約を model に追加する (§10.9)。

    vars に必要なキー:
      z_charge     : z_charge[k, c, t]      (充電フラグ)
      z_discharge  : z_discharge[k, t]      (放電フラグ)
      p_charge     : p_charge[k, c, t] [kW]
      p_discharge  : p_discharge[k, c, t] [kW]
      soc          : soc[k, t]
    """
    gp, _ = ensure_gurobi()
    if not data.enable_v2g:
        return

    z_c  = vars.get("z_charge")
    z_d  = vars.get("z_discharge")
    p_c  = vars["p_charge"]
    p_d  = vars.get("p_discharge")

    if p_d is None:
        return

    K_BEV = ms.K_BEV
    C     = ms.C
    T     = ms.T
    delta_h = data.delta_t_hour

    for k in K_BEV:
        veh = dp.vehicle_lut[k]
        dis_max = veh.discharge_power_max or 0.0
        dis_eff = veh.discharge_efficiency

        compatible_c = [c for c in C if c in ms.vehicle_charger_feasible.get(k, set())]

        for t in T:
            # § 10.9 充放電同時禁止
            if z_c is not None and z_d is not None:
                charge_flag = gp.quicksum(z_c[k, c, t] for c in compatible_c)
                model.addConstr(
                    charge_flag + z_d[k, t] <= 1,
                    name=f"no_sim_charge_discharge[{k},{t}]",
                )

            # 放電電力上限
            for c in compatible_c:
                model.addConstr(
                    p_d[k, c, t] <= dis_max * (z_d[k, t] if z_d else 1),
                    name=f"dis_pwr_ub[{k},{c},{t}]",
                )
