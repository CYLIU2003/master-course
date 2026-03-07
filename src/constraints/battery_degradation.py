"""
constraints/battery_degradation.py — 電池劣化コスト制約 (§10.10)

初版では充放電電力量に比例する線形近似を採用する。
deg[k, t]: 時刻 t の劣化コスト補助変数 [円/slot]
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


def add_battery_degradation_constraints(
    model: Any,
    data: ProblemData,
    ms: ModelSets,
    dp: DerivedParams,
    vars: Dict[str, Any],
) -> None:
    """
    電池劣化変数の制約を追加する (§10.10)。

    vars に必要なキー:
      p_charge : p_charge[k, c, t]  [kW]
      deg      : deg[k, t]          [円/slot]  (劣化コスト)
    """
    if not data.enable_battery_degradation:
        return

    p    = vars["p_charge"]
    deg  = vars.get("deg")
    if deg is None:
        return

    K_BEV = ms.K_BEV
    C     = ms.C
    T     = ms.T
    delta_h = data.delta_t_hour

    for k in K_BEV:
        veh = dp.vehicle_lut[k]
        coeff = veh.battery_degradation_cost_coeff  # [円/kWh-throughput]
        eff   = veh.charge_efficiency

        compatible_c = [c for c in C if c in ms.vehicle_charger_feasible.get(k, set())]

        for t in T:
            # 充電エネルギー [kWh]
            charge_kwh = gp.quicksum(
                eff * p[k, c, t] * delta_h for c in compatible_c
            )
            # deg[k,t] >= coeff * charge_kwh (線形近似)
            model.addConstr(
                deg[k, t] >= coeff * charge_kwh,
                name=f"deg_charge[{k},{t}]",
            )
