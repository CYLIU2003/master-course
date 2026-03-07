"""
constraints/charger_capacity.py — 充電器容量・台数制約

仕様書 §10.4 担当:
  - 各充電器の同時利用は高々 1 台 (§10.4.1)
  - §10.4.3 互換性制約は assignment.py / charging.py で処理済み
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


def add_charger_capacity_constraints(
    model: Any,
    data: ProblemData,
    ms: ModelSets,
    dp: DerivedParams,
    vars: Dict[str, Any],
) -> None:
    """
    充電器台数制約を model に追加する。

    vars に必要なキー:
      z_charge : z[k, c, t]
    """
    z = vars["z_charge"]
    K_BEV = ms.K_BEV
    C     = ms.C
    T     = ms.T

    for c in C:
        for t in T:
            # §10.4.1: 各充電器は同時に高々 1 台
            compatible_k = [k for k in K_BEV if c in ms.vehicle_charger_feasible.get(k, set())]
            if not compatible_k:
                continue
            model.addConstr(
                gp.quicksum(z[k, c, t] for k in compatible_k) <= 1,
                name=f"charger_cap[{c},{t}]",
            )
