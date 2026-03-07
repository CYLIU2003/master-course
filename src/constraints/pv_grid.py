"""
constraints/pv_grid.py — PV 出力・系統連系制約

仕様書 §10.8 担当。
PV 利用・出力抑制・逆潮流の制約を追加する。
energy_balance.py の詳細補完として使用する。
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
from ..parameter_builder import DerivedParams, get_pv_gen


def add_pv_grid_constraints(
    model: Any,
    data: ProblemData,
    ms: ModelSets,
    dp: DerivedParams,
    vars: Dict[str, Any],
) -> None:
    """
    PV 制約を追加する。

    vars に必要なキー:
      p_pv_used    : p_pv_used[i, t]     [kW]
      p_pv_curtail : p_pv_curtail[i, t]  [kW]
      p_grid_export: p_grid_export[i, t] [kW] (売電あり時)
    """
    if not data.enable_pv:
        return

    p_pv_used   = vars.get("p_pv_used")
    p_pv_cur    = vars.get("p_pv_curtail")
    p_grid_exp  = vars.get("p_grid_export")

    if p_pv_used is None:
        return

    for site_id in ms.I_CHARGE:
        site = dp.site_lut.get(site_id)

        for t in ms.T:
            pv_cap = get_pv_gen(dp, site_id, t)

            # §10.8 PV 出力 = 使用 + 抑制 (<= 発電量)
            if p_pv_cur is not None:
                model.addConstr(
                    p_pv_used[site_id, t] + p_pv_cur[site_id, t] <= pv_cap,
                    name=f"pv_total[{site_id},{t}]",
                )
            else:
                model.addConstr(
                    p_pv_used[site_id, t] <= pv_cap,
                    name=f"pv_use_ub[{site_id},{t}]",
                )

            # 逆潮流上限 (設定があれば)
            if p_grid_exp is not None and site is not None:
                export_lim = 9999.0  # site_transformer_limit 等で設定可能
                model.addConstr(
                    p_grid_exp[site_id, t] <= export_lim,
                    name=f"grid_export_ub[{site_id},{t}]",
                )
