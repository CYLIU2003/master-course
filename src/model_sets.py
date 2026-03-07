"""
model_sets.py — 集合・インデックス定義

仕様書 §5 に対応した集合の構築ヘルパー。
ProblemData を受け取り、K_BEV, K_ICE, R, T, I, C などを返す。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, FrozenSet, List, Set

from .data_schema import ProblemData


@dataclass
class ModelSets:
    """
    仕様書 §5 の集合一覧を格納するコンテナ。

    Attributes
    ----------
    K_BEV : list  §5.1  BEV 車両 ID リスト
    K_ICE : list  §5.1  ICE 車両 ID リスト
    K_ALL : list  §5.1  全車両 ID リスト
    R     : list  §5.2  全タスク ID リスト
    R_BEV_ELIGIBLE : list  §5.2  BEV 担当可能タスク
    R_ICE_ELIGIBLE : list  §5.2  ICE 担当可能タスク
    T     : list  §5.3  時刻インデックスリスト [0, num_periods)
    I_DEPOT  : list §5.4 デポ地点 ID
    I_CHARGE : list §5.4 充電可能地点 ID
    I_ROUTE  : list §5.4 中継地点 ID
    I_ALL    : list §5.4 全地点 ID
    C        : list §5.5 充電器 ID リスト
    C_at_site: dict §5.5 site_id -> [charger_id, ...]
    K_COMPAT_charger: dict §5.5 charger_id -> [vehicle_id, ...]
    """

    K_BEV: List[str] = field(default_factory=list)
    K_ICE: List[str] = field(default_factory=list)
    K_ALL: List[str] = field(default_factory=list)

    R: List[str] = field(default_factory=list)
    R_BEV_ELIGIBLE: List[str] = field(default_factory=list)
    R_ICE_ELIGIBLE: List[str] = field(default_factory=list)

    T: List[int] = field(default_factory=list)

    I_DEPOT: List[str] = field(default_factory=list)
    I_CHARGE: List[str] = field(default_factory=list)
    I_ROUTE: List[str] = field(default_factory=list)
    I_ALL: List[str] = field(default_factory=list)

    C: List[str] = field(default_factory=list)
    C_at_site: Dict[str, List[str]] = field(default_factory=dict)
    K_COMPAT_charger: Dict[str, List[str]] = field(default_factory=dict)

    # 互換性テーブル
    vehicle_task_feasible: Dict[str, Set[str]] = field(default_factory=dict)   # vid -> {tid}
    vehicle_charger_feasible: Dict[str, Set[str]] = field(default_factory=dict) # vid -> {cid}


def build_model_sets(data: ProblemData) -> ModelSets:
    """
    ProblemData から ModelSets を構築して data に紐付ける。

    Returns
    -------
    ModelSets
    """
    ms = ModelSets()

    # --- §5.1 車両集合 ---
    for v in data.vehicles:
        ms.K_ALL.append(v.vehicle_id)
        if v.vehicle_type == "BEV":
            ms.K_BEV.append(v.vehicle_id)
        else:
            ms.K_ICE.append(v.vehicle_id)

    # --- §5.2 タスク集合 ---
    ms.R = [t.task_id for t in data.tasks]

    # required_vehicle_type に基づいて振り分け
    for t in data.tasks:
        rvt = (t.required_vehicle_type or "").upper()
        if rvt == "ICE":
            ms.R_ICE_ELIGIBLE.append(t.task_id)
        elif rvt == "BEV":
            ms.R_BEV_ELIGIBLE.append(t.task_id)
        else:
            # どちらでも OK → 両方に追加
            ms.R_BEV_ELIGIBLE.append(t.task_id)
            ms.R_ICE_ELIGIBLE.append(t.task_id)

    # --- §5.3 時刻集合 ---
    ms.T = list(range(data.num_periods))

    # --- §5.4 地点集合 ---
    for site in data.sites:
        ms.I_ALL.append(site.site_id)
        if site.site_type == "depot":
            ms.I_DEPOT.append(site.site_id)
            ms.I_CHARGE.append(site.site_id)
        elif site.site_type == "charge_only":
            ms.I_CHARGE.append(site.site_id)
        else:
            ms.I_ROUTE.append(site.site_id)

    # --- §5.5 充電器集合 ---
    ms.C = [c.charger_id for c in data.chargers]
    for c in data.chargers:
        ms.C_at_site.setdefault(c.site_id, []).append(c.charger_id)

    # --- 互換性テーブル ---
    # デフォルト: 全車両が全タスク・充電器に使用可能
    for v in data.vehicles:
        ms.vehicle_task_feasible[v.vehicle_id] = set(ms.R)
        ms.vehicle_charger_feasible[v.vehicle_id] = set(ms.C)

    for vc in data.vehicle_task_compat:
        if not vc.feasible:
            ms.vehicle_task_feasible.get(vc.vehicle_id, set()).discard(vc.task_id)
        else:
            ms.vehicle_task_feasible.setdefault(vc.vehicle_id, set()).add(vc.task_id)

    for vc in data.vehicle_charger_compat:
        if not vc.feasible:
            ms.vehicle_charger_feasible.get(vc.vehicle_id, set()).discard(vc.charger_id)
        else:
            ms.vehicle_charger_feasible.setdefault(vc.vehicle_id, set()).add(vc.charger_id)

    # --- vehicle_type を考慮した task 互換性の絞り込み ---
    for v in data.vehicles:
        allowed = set()
        for t in data.tasks:
            rvt = (t.required_vehicle_type or "").upper()
            if rvt and rvt != v.vehicle_type:
                continue  # 不一致な車種は除外
            if t.task_id in ms.vehicle_task_feasible.get(v.vehicle_id, set()):
                allowed.add(t.task_id)
        ms.vehicle_task_feasible[v.vehicle_id] = allowed

    # charger → compatible vehicle リスト
    for v_id, c_set in ms.vehicle_charger_feasible.items():
        for c_id in c_set:
            ms.K_COMPAT_charger.setdefault(c_id, []).append(v_id)

    # ProblemData に集合キャッシュをセット
    data.K_BEV = ms.K_BEV[:]
    data.K_ICE = ms.K_ICE[:]
    data.K_ALL = ms.K_ALL[:]

    return ms
