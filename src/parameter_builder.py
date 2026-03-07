"""
parameter_builder.py — 派生パラメータ生成

仕様書 §14.2 担当:
  - 入力データから can_follow, energy_consumption_rate 等の派生パラメータを生成する
  - Big-M 値を安全に計算する

単位: kW, kWh, hour, km (§16)
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .data_schema import ProblemData
from .model_sets import ModelSets


@dataclass
class DerivedParams:
    """
    MILP・シミュレータで用いる派生パラメータコンテナ。

    仕様書 §6.1.2, §6.2.2, §6.4 等の値を保持する。
    """

    # --- §6.1.2 タスク間接続 ---
    # can_follow[r1][r2] = True なら車両 k が r1 の直後に r2 を連続担当可能
    can_follow: Dict[str, Dict[str, bool]] = field(default_factory=dict)
    # deadhead_time_slot[r1][r2]
    deadhead_time_slot: Dict[str, Dict[str, int]] = field(default_factory=dict)
    # deadhead_energy_kwh[r1][r2]
    deadhead_energy_kwh: Dict[str, Dict[str, float]] = field(default_factory=dict)
    # deadhead_distance_km[r1][r2]
    deadhead_distance_km: Dict[str, Dict[str, float]] = field(default_factory=dict)

    # --- §6.1.1 タスク基本情報 (整備済み dict 形式) ---
    task_duration_slot: Dict[str, int] = field(default_factory=dict)   # end - start
    task_energy_bev: Dict[str, float] = field(default_factory=dict)    # [kWh]
    task_fuel_ice: Dict[str, float] = field(default_factory=dict)      # [L]
    task_distance_km: Dict[str, float] = field(default_factory=dict)   # [km]

    # --- 時刻別タスク状態 ---
    # task_active[r][t] = 1 なら時刻 t にタスク r は走行中
    task_active: Dict[str, List[int]] = field(default_factory=dict)
    # task_energy_per_slot[r][t] = その時刻に消費する BEV エネルギー [kWh]
    task_energy_per_slot: Dict[str, List[float]] = field(default_factory=dict)

    # --- §6.4 電力・PV (site_id, time_idx → value) ---
    pv_gen_kw: Dict[str, Dict[int, float]] = field(default_factory=dict)
    grid_price: Dict[str, Dict[int, float]] = field(default_factory=dict)
    sell_back_price: Dict[str, Dict[int, float]] = field(default_factory=dict)
    base_load_kw: Dict[str, Dict[int, float]] = field(default_factory=dict)

    # --- 車両パラメータ dict (LUT) ---
    vehicle_lut: dict = field(default_factory=dict)  # vid -> Vehicle
    task_lut: dict = field(default_factory=dict)     # tid -> Task
    charger_lut: dict = field(default_factory=dict)  # cid -> Charger
    site_lut: dict = field(default_factory=dict)     # sid -> Site

    # --- §6.5 Big-M ---
    BIG_M_ASSIGN: float = 1e6
    BIG_M_CHARGE: float = 1e6
    BIG_M_SOC: float = 1e6

    # --- 重複タスクペア ---
    overlap_pairs: List[Tuple[str, str]] = field(default_factory=list)


def build_derived_params(data: ProblemData, ms: ModelSets) -> DerivedParams:
    """
    ProblemData + ModelSets → DerivedParams を構築する。

    Parameters
    ----------
    data : ProblemData
    ms   : ModelSets

    Returns
    -------
    DerivedParams
    """
    dp = DerivedParams()

    # --- LUT 構築 ---
    dp.vehicle_lut = {v.vehicle_id: v for v in data.vehicles}
    dp.task_lut    = {t.task_id: t for t in data.tasks}
    dp.charger_lut = {c.charger_id: c for c in data.chargers}
    dp.site_lut    = {s.site_id: s for s in data.sites}

    # --- Big-M ---
    dp.BIG_M_ASSIGN = data.BIG_M_ASSIGN
    dp.BIG_M_CHARGE = data.BIG_M_CHARGE
    dp.BIG_M_SOC    = data.BIG_M_SOC

    # --- タスク基本情報 ---
    for t in data.tasks:
        dp.task_duration_slot[t.task_id] = t.end_time_idx - t.start_time_idx
        dp.task_energy_bev[t.task_id]    = t.energy_required_kwh_bev
        dp.task_fuel_ice[t.task_id]      = t.fuel_required_liter_ice
        dp.task_distance_km[t.task_id]   = t.distance_km

    # --- §10.5 時刻別タスク状態 ---
    T = data.num_periods
    for t in data.tasks:
        active = [0] * T
        energy = [0.0] * T
        span = t.end_time_idx - t.start_time_idx + 1
        per_slot = t.energy_required_kwh_bev / span if span > 0 else 0.0
        for ti in range(T):
            if t.start_time_idx <= ti <= t.end_time_idx:
                active[ti] = 1
                energy[ti] = per_slot
        dp.task_active[t.task_id] = active
        dp.task_energy_per_slot[t.task_id] = energy

    # --- 重複ペア ---
    task_list = data.tasks
    for i, t1 in enumerate(task_list):
        for t2 in task_list[i+1:]:
            if not (t1.end_time_idx < t2.start_time_idx or t2.end_time_idx < t1.start_time_idx):
                dp.overlap_pairs.append((t1.task_id, t2.task_id))

    # --- §6.1.2 タスク間接続 ---
    # travel_connection.csv がある場合はそちらを優先
    if data.travel_connections:
        for tc in data.travel_connections:
            dp.can_follow.setdefault(tc.from_task_id, {})[tc.to_task_id] = tc.can_follow
            dp.deadhead_time_slot.setdefault(tc.from_task_id, {})[tc.to_task_id] = tc.deadhead_time_slot
            dp.deadhead_energy_kwh.setdefault(tc.from_task_id, {})[tc.to_task_id] = tc.deadhead_energy_kwh
            dp.deadhead_distance_km.setdefault(tc.from_task_id, {})[tc.to_task_id] = tc.deadhead_distance_km
    else:
        # デフォルト: 時間的に先行かつ重複しないペアを接続可能とする
        _default_can_follow(data, dp)

    # --- §6.4 PV・電力料金 ---
    for pv in data.pv_profiles:
        dp.pv_gen_kw.setdefault(pv.site_id, {})[pv.time_idx] = pv.pv_generation_kw

    for ep in data.electricity_prices:
        dp.grid_price.setdefault(ep.site_id, {})[ep.time_idx] = ep.grid_energy_price
        dp.sell_back_price.setdefault(ep.site_id, {})[ep.time_idx] = ep.sell_back_price
        dp.base_load_kw.setdefault(ep.site_id, {})[ep.time_idx] = ep.base_load_kw

    # can_follow を ProblemData にも保存
    data.can_follow_matrix = dp.can_follow

    return dp


def _default_can_follow(data: ProblemData, dp: DerivedParams) -> None:
    """travel_connection.csv が無い場合のデフォルト接続判定"""
    for t1 in data.tasks:
        dp.can_follow[t1.task_id] = {}
        dp.deadhead_time_slot[t1.task_id] = {}
        dp.deadhead_energy_kwh[t1.task_id] = {}
        dp.deadhead_distance_km[t1.task_id] = {}
        for t2 in data.tasks:
            if t1.task_id == t2.task_id:
                continue
            # 同一地点なら 1 スロット、異地点なら 2 スロットの回送
            same_loc = (t1.destination == t2.origin)
            dh_slot = 1 if same_loc else 2
            can = (t1.end_time_idx + dh_slot) <= t2.start_time_idx
            dp.can_follow[t1.task_id][t2.task_id] = can
            dp.deadhead_time_slot[t1.task_id][t2.task_id] = dh_slot if can else 0
            dp.deadhead_energy_kwh[t1.task_id][t2.task_id] = 0.0 if same_loc else 5.0
            dp.deadhead_distance_km[t1.task_id][t2.task_id] = 0.0 if same_loc else 15.0


def get_grid_price(dp: DerivedParams, site_id: str, t_idx: int,
                   default: float = 25.0) -> float:
    """地点・時刻の系統電力料金を返す [円/kWh]"""
    return dp.grid_price.get(site_id, {}).get(t_idx, default)


def get_pv_gen(dp: DerivedParams, site_id: str, t_idx: int) -> float:
    """地点・時刻の PV 発電量を返す [kW]"""
    return dp.pv_gen_kw.get(site_id, {}).get(t_idx, 0.0)


def get_base_load(dp: DerivedParams, site_id: str, t_idx: int) -> float:
    """地点・時刻の基礎負荷を返す [kW]"""
    return dp.base_load_kw.get(site_id, {}).get(t_idx, 0.0)


def compute_safe_big_m(data: ProblemData) -> float:
    """
    Big-M の安全上界を計算する。
    最大バッテリー容量 × (num_periods + 1) で概算。
    §6.5 参照。
    """
    max_cap = max(
        (v.battery_capacity or 0.0) for v in data.vehicles
        if v.vehicle_type == "BEV"
    ) if any(v.vehicle_type == "BEV" for v in data.vehicles) else 500.0
    return max_cap * (data.num_periods + 1)
