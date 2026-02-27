"""
model_core.py — 共通データ構造・ヘルパー関数

電気バスシミュレーションのコアモデル。
Gurobi / ALNS 両ソルバーから共通で使用する。
"""
from __future__ import annotations

import copy
import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# データクラス定義
# ---------------------------------------------------------------------------

@dataclass
class BusSpec:
    """バス 1 台の仕様"""
    bus_id: str
    category: str              # "BEV" or "ICE"
    cap_kwh: float             # バッテリ容量 [kWh]
    soc_init_kwh: float        # 初期 SOC [kWh]
    soc_min_kwh: float         # SOC 下限 [kWh]
    soc_max_kwh: float         # SOC 上限 [kWh]
    efficiency_km_per_kwh: float = 1.0   # 電費 [km/kWh]  (BEV)
    fuel_efficiency_km_per_l: float = 0.0  # 燃費 [km/L]  (ICE)
    co2_g_per_km: float = 0.0             # CO2 排出原単位 [g/km]


@dataclass
class TripSpec:
    """便 1 本の仕様"""
    trip_id: str
    start_t: int               # 開始時刻インデックス
    end_t: int                 # 終了時刻インデックス
    energy_kwh: float          # 走行消費電力量 [kWh]
    distance_km: float = 0.0   # 走行距離 [km]（ICE コスト計算用）
    start_node: str = "depot_A"
    end_node: str = "terminal_B"


@dataclass
class ChargerSpec:
    """充電器 1 タイプの仕様"""
    depot: str
    charger_type: str   # "slow" / "fast"
    power_kw: float
    count: int
    efficiency: float = 0.95


@dataclass
class ProblemConfig:
    """最適化問題全体の設定"""
    # --- システム規模 ---
    num_buses: int = 3
    num_trips: int = 6
    num_periods: int = 32
    delta_h: float = 0.5          # 時間刻み [h]
    start_time: str = "06:00"
    end_time: str = "22:00"

    # --- 集合 ---
    buses: List[BusSpec] = field(default_factory=list)
    trips: List[TripSpec] = field(default_factory=list)
    depots: List[str] = field(default_factory=lambda: ["depot_A", "terminal_B"])
    charger_types: List[str] = field(default_factory=lambda: ["slow", "fast"])
    chargers: List[ChargerSpec] = field(default_factory=list)

    # --- エネルギー ---
    charge_efficiency: float = 0.95
    pv_gen_kwh: List[float] = field(default_factory=list)
    grid_price_yen_per_kwh: List[float] = field(default_factory=list)

    # --- ICE 関連 ---
    diesel_yen_per_l: float = 145.0

    # --- フラグ ---
    enable_pv: bool = True
    enable_terminal_soc: bool = False
    terminal_soc_kwh: Optional[float] = None
    enable_demand_charge: bool = False
    contract_power_kw: Optional[float] = None

    # --- 補助データ ---
    overlap_pairs: List[Tuple[str, str]] = field(default_factory=list)
    trip_active: Dict[str, List[int]] = field(default_factory=dict)
    trip_energy_at_time: Dict[str, List[float]] = field(default_factory=dict)
    bus_can_charge_at: Dict[str, Dict[str, List[int]]] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# ユーティリティ
# ---------------------------------------------------------------------------

def make_time_labels(start: str, delta_h: float, num_periods: int) -> List[str]:
    """時刻ラベルを生成する"""
    h, m = map(int, start.split(":"))
    labels = []
    for i in range(num_periods):
        total_min = int((h * 60 + m) + i * delta_h * 60)
        labels.append(f"{total_min // 60:02d}:{total_min % 60:02d}")
    return labels


def compute_overlap_pairs(trips: List[TripSpec]) -> List[Tuple[str, str]]:
    """時間が重複する便のペアを列挙"""
    pairs: List[Tuple[str, str]] = []
    for i, t1 in enumerate(trips):
        for t2 in trips[i + 1:]:
            if not (t1.end_t < t2.start_t or t2.end_t < t1.start_t):
                pairs.append((t1.trip_id, t2.trip_id))
    return pairs


def compute_trip_active(trips: List[TripSpec], num_periods: int) -> Dict[str, List[int]]:
    """各便が各時刻にアクティブかどうかの 0/1 配列"""
    result: Dict[str, List[int]] = {}
    for tr in trips:
        arr = [0] * num_periods
        for t in range(num_periods):
            if tr.start_t <= t <= tr.end_t:
                arr[t] = 1
        result[tr.trip_id] = arr
    return result


def compute_trip_energy_at_time(
    trips: List[TripSpec], num_periods: int
) -> Dict[str, List[float]]:
    """各便の時刻ごとの消費電力量を均等配分"""
    result: Dict[str, List[float]] = {}
    for tr in trips:
        arr = [0.0] * num_periods
        span = tr.end_t - tr.start_t + 1
        per_slot = tr.energy_kwh / span if span > 0 else 0.0
        for t in range(num_periods):
            if tr.start_t <= t <= tr.end_t:
                arr[t] = per_slot
        result[tr.trip_id] = arr
    return result


def compute_default_bus_can_charge(
    buses: List[BusSpec],
    trips: List[TripSpec],
    depots: List[str],
    num_periods: int,
    trip_active: Dict[str, List[int]],
) -> Dict[str, Dict[str, List[int]]]:
    """
    デフォルト: 便を運行していない時間帯はすべてのデポで充電可能とする。
    """
    result: Dict[str, Dict[str, List[int]]] = {}
    for bus in buses:
        result[bus.bus_id] = {}
        for depot in depots:
            result[bus.bus_id][depot] = [1] * num_periods
    return result


def precompute_helpers(cfg: ProblemConfig) -> ProblemConfig:
    """補助パラメータを一括計算して config を更新"""
    cfg = copy.deepcopy(cfg)
    cfg.overlap_pairs = compute_overlap_pairs(cfg.trips)
    cfg.trip_active = compute_trip_active(cfg.trips, cfg.num_periods)
    cfg.trip_energy_at_time = compute_trip_energy_at_time(cfg.trips, cfg.num_periods)
    cfg.bus_can_charge_at = compute_default_bus_can_charge(
        cfg.buses, cfg.trips, cfg.depots, cfg.num_periods, cfg.trip_active
    )
    return cfg


# ---------------------------------------------------------------------------
# JSON ⇔ ProblemConfig 変換
# ---------------------------------------------------------------------------

def load_config_from_json(path: str | Path) -> ProblemConfig:
    """既存の ebus_prototype_config.json 形式を ProblemConfig に変換"""
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)

    td = raw["model_options"]["time_discretization"]
    sets = raw["sets"]
    ep = raw["energy_params"]

    buses = []
    for bid, bp in raw["bus_params"].items():
        buses.append(BusSpec(
            bus_id=bid,
            category="BEV",
            cap_kwh=bp["cap_kwh"],
            soc_init_kwh=bp["soc_init_kwh"],
            soc_min_kwh=bp["soc_min_kwh"],
            soc_max_kwh=bp["soc_max_kwh"],
        ))

    trips = []
    for tid, tp in raw["trip_params"].items():
        trips.append(TripSpec(
            trip_id=tid,
            start_t=tp["start_t"],
            end_t=tp["end_t"],
            energy_kwh=tp["energy_kwh"],
            start_node=tp.get("start_node", "depot_A"),
            end_node=tp.get("end_node", "terminal_B"),
        ))

    chargers = []
    for depot, types in raw["charger_params"].items():
        for ctype, spec in types.items():
            chargers.append(ChargerSpec(
                depot=depot,
                charger_type=ctype,
                power_kw=spec["power_kw"],
                count=spec["count"],
                efficiency=ep.get("charge_efficiency", 0.95),
            ))

    cfg = ProblemConfig(
        num_buses=len(buses),
        num_trips=len(trips),
        num_periods=td["num_periods"],
        delta_h=td["delta_h"],
        start_time=td.get("start_time", "06:00"),
        end_time=td.get("end_time", "22:00"),
        buses=buses,
        trips=trips,
        depots=sets["depots"],
        charger_types=sets["charger_types"],
        chargers=chargers,
        charge_efficiency=ep.get("charge_efficiency", 0.95),
        pv_gen_kwh=ep.get("pv_gen_kwh", []),
        grid_price_yen_per_kwh=ep.get("grid_price_yen_per_kwh", []),
        enable_pv=raw["model_options"]["features"].get("enable_pv", True),
    )
    return precompute_helpers(cfg)


def config_to_dict(cfg: ProblemConfig) -> Dict[str, Any]:
    """ProblemConfig を JSON-safe な dict に変換"""
    return {
        "system": {
            "num_buses": cfg.num_buses,
            "num_trips": cfg.num_trips,
            "num_periods": cfg.num_periods,
            "delta_h": cfg.delta_h,
            "start_time": cfg.start_time,
            "end_time": cfg.end_time,
            "depots": cfg.depots,
            "charger_types": cfg.charger_types,
        },
        "buses": [
            {
                "bus_id": b.bus_id,
                "category": b.category,
                "cap_kwh": b.cap_kwh,
                "soc_init_kwh": b.soc_init_kwh,
                "soc_min_kwh": b.soc_min_kwh,
                "soc_max_kwh": b.soc_max_kwh,
                "efficiency_km_per_kwh": b.efficiency_km_per_kwh,
                "fuel_efficiency_km_per_l": b.fuel_efficiency_km_per_l,
                "co2_g_per_km": b.co2_g_per_km,
            }
            for b in cfg.buses
        ],
        "trips": [
            {
                "trip_id": t.trip_id,
                "start_t": t.start_t,
                "end_t": t.end_t,
                "energy_kwh": t.energy_kwh,
                "distance_km": t.distance_km,
                "start_node": t.start_node,
                "end_node": t.end_node,
            }
            for t in cfg.trips
        ],
        "chargers": [
            {
                "depot": c.depot,
                "charger_type": c.charger_type,
                "power_kw": c.power_kw,
                "count": c.count,
                "efficiency": c.efficiency,
            }
            for c in cfg.chargers
        ],
        "energy": {
            "charge_efficiency": cfg.charge_efficiency,
            "pv_gen_kwh": cfg.pv_gen_kwh,
            "grid_price_yen_per_kwh": cfg.grid_price_yen_per_kwh,
            "diesel_yen_per_l": cfg.diesel_yen_per_l,
            "enable_pv": cfg.enable_pv,
        },
        "options": {
            "enable_terminal_soc": cfg.enable_terminal_soc,
            "terminal_soc_kwh": cfg.terminal_soc_kwh,
            "enable_demand_charge": cfg.enable_demand_charge,
            "contract_power_kw": cfg.contract_power_kw,
        },
    }


# ---------------------------------------------------------------------------
# 結果のデータ構造
# ---------------------------------------------------------------------------

@dataclass
class SolveResult:
    """ソルバーからの結果"""
    solver_name: str                      # "gurobi" or "alns"
    status: str                           # "OPTIMAL", "FEASIBLE", etc.
    objective_value: Optional[float] = None
    solve_time_sec: float = 0.0

    # 便割当: bus_id -> [trip_id, ...]
    assignment: Dict[str, List[str]] = field(default_factory=dict)

    # SOC: bus_id -> [soc_t0, soc_t1, ...]  (len = num_periods + 1)
    soc_series: Dict[str, List[float]] = field(default_factory=dict)

    # 充電スケジュール: bus_id -> {depot|type -> [0/1, ...]}
    charge_schedule: Dict[str, Dict[str, List[int]]] = field(default_factory=dict)

    # 充電エネルギー: bus_id -> {depot|type -> [kWh, ...]}
    charge_energy: Dict[str, Dict[str, List[float]]] = field(default_factory=dict)

    # PV / 買電: time_index -> value
    pv_use: Dict[int, float] = field(default_factory=dict)
    grid_buy: Dict[int, float] = field(default_factory=dict)

    # 追加 KPI
    total_grid_cost_yen: float = 0.0
    total_pv_kwh: float = 0.0
    total_grid_kwh: float = 0.0
    total_co2_kg: float = 0.0
    min_soc_kwh: float = 0.0
    max_simultaneous_chargers: int = 0

    # ALNS 専用
    iteration_log: List[Dict[str, Any]] = field(default_factory=list)
