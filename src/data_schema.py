"""
data_schema.py — 入力データクラス定義

仕様書 §11.1 に準拠した Vehicle / Task / Charger / Site データクラス。
MILP・ALNS 共通の入力スキーマ。

単位系 (§16):
  電力  : kW
  電力量: kWh
  時間  : hour または time_idx
  距離  : km
  SOC   : kWh (内部管理)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# §11.1.1 Vehicle
# ---------------------------------------------------------------------------

@dataclass
class Vehicle:
    """バス車両 1 台の仕様 (BEV / ICE 共通)"""

    vehicle_id: str
    vehicle_type: str                       # "BEV" | "ICE"
    home_depot: str                         # 所属デポ ID

    # ------- BEV 固有 (§6.2.2) -------
    battery_capacity: Optional[float] = None       # [kWh]
    soc_init: Optional[float] = None               # [kWh]
    soc_min: Optional[float] = None                # [kWh]
    soc_max: Optional[float] = None                # [kWh]
    soc_target_end: Optional[float] = None         # [kWh]
    charge_power_max: Optional[float] = None       # [kW]
    charge_efficiency: float = 0.95
    discharge_power_max: Optional[float] = None    # [kW] V2G
    discharge_efficiency: float = 0.95
    battery_degradation_cost_coeff: float = 0.0   # [円/kWh-throughput]

    # ------- ICE 固有 (§6.2.3) -------
    fuel_tank_capacity: Optional[float] = None     # [L]
    fuel_cost_coeff: float = 145.0                 # [円/L]
    co2_emission_coeff: float = 2.58               # [kg-CO2/L]

    # ------- 共通運用 (§6.2.1) -------
    available_start: int = 0                       # 運用開始可能 time_idx
    available_end: int = 9999                      # 運用終了可能 time_idx
    fixed_use_cost: float = 0.0                    # 1日使用固定費 [円]
    max_operating_time: float = 24.0               # 最大稼働時間 [hour]
    max_distance: float = 9999.0                   # 最大走行距離 [km]


# ---------------------------------------------------------------------------
# §11.1.2 Task
# ---------------------------------------------------------------------------

@dataclass
class Task:
    """運行タスク (便 or ブロック) 1 件"""

    task_id: str
    start_time_idx: int                # 開始 time_idx
    end_time_idx: int                  # 終了 time_idx
    origin: str                        # 開始地点 ID
    destination: str                   # 終了地点 ID
    distance_km: float = 0.0           # 走行距離 [km]
    energy_required_kwh_bev: float = 0.0   # BEV 消費電力量 [kWh]
    fuel_required_liter_ice: float = 0.0   # ICE 燃料消費 [L]
    required_vehicle_type: Optional[str] = None  # None=どちらでも可
    demand_cover: bool = True          # 必ずカバーが必要か
    penalty_unserved: float = 10000.0  # 未割当ペナルティ [円]


# ---------------------------------------------------------------------------
# §11.1.3 Charger
# ---------------------------------------------------------------------------

@dataclass
class Charger:
    """充電器 1 基の仕様"""

    charger_id: str
    site_id: str                       # 設置地点 ID
    power_max_kw: float                # 最大出力 [kW]
    efficiency: float = 0.95
    power_min_kw: float = 0.0         # 必要最低出力 [kW]


# ---------------------------------------------------------------------------
# §11.1.4 Site
# ---------------------------------------------------------------------------

@dataclass
class Site:
    """バス停・デポ・充電拠点などの地点"""

    site_id: str
    site_type: str                     # "depot" | "terminal" | "charge_only"
    grid_import_limit_kw: float = 9999.0    # 系統受電上限 [kW]
    contract_demand_limit_kw: float = 9999.0  # 契約電力上限 [kW]
    site_transformer_limit_kw: float = 9999.0  # 設備容量上限 [kW]


# ---------------------------------------------------------------------------
# タスク間接続情報 (§6.1.2)
# ---------------------------------------------------------------------------

@dataclass
class TravelConnection:
    """タスク間の回送・接続情報"""

    from_task_id: str
    to_task_id: str
    can_follow: bool = True
    deadhead_time_slot: int = 0         # 回送時間 [スロット数]
    deadhead_distance_km: float = 0.0
    deadhead_energy_kwh: float = 0.0


# ---------------------------------------------------------------------------
# PV・電力プロファイル
# ---------------------------------------------------------------------------

@dataclass
class PVProfile:
    """地点・時刻別の PV 発電量"""
    site_id: str
    time_idx: int
    pv_generation_kw: float = 0.0       # [kW]


@dataclass
class ElectricityPrice:
    """地点・時刻別の電力料金・基礎負荷"""
    site_id: str
    time_idx: int
    grid_energy_price: float = 0.0      # [円/kWh]
    sell_back_price: float = 0.0        # [円/kWh]
    base_load_kw: float = 0.0           # バス以外の基礎負荷 [kW]


# ---------------------------------------------------------------------------
# 互換性テーブル
# ---------------------------------------------------------------------------

@dataclass
class VehicleTaskCompat:
    """車両とタスクの適合性"""
    vehicle_id: str
    task_id: str
    feasible: bool = True


@dataclass
class VehicleChargerCompat:
    """車両と充電器の適合性"""
    vehicle_id: str
    charger_id: str
    feasible: bool = True


# ---------------------------------------------------------------------------
# 全入力データをまとめたコンテナ
# ---------------------------------------------------------------------------

@dataclass
class ProblemData:
    """
    MILP / シミュレータへの統一入力コンテナ。
    仕様書 §5 の集合定義・§6 のパラメータに対応。
    """

    # --- 基本集合 ---
    vehicles: List[Vehicle] = field(default_factory=list)
    tasks: List[Task] = field(default_factory=list)
    chargers: List[Charger] = field(default_factory=list)
    sites: List[Site] = field(default_factory=list)

    # --- 接続・互換 ---
    travel_connections: List[TravelConnection] = field(default_factory=list)
    vehicle_task_compat: List[VehicleTaskCompat] = field(default_factory=list)
    vehicle_charger_compat: List[VehicleChargerCompat] = field(default_factory=list)

    # --- 時系列プロファイル ---
    pv_profiles: List[PVProfile] = field(default_factory=list)
    electricity_prices: List[ElectricityPrice] = field(default_factory=list)

    # --- 時間軸 ---
    num_periods: int = 32
    delta_t_hour: float = 0.5           # 1スロット [hour]  → delta_t_min = 30
    planning_horizon_hours: float = 16.0

    # --- フラグ (config.json と連動) ---
    allow_partial_service: bool = False
    enable_pv: bool = True
    enable_v2g: bool = False
    enable_battery_degradation: bool = True
    enable_demand_charge: bool = True
    use_soft_soc_constraint: bool = False

    # --- 目的関数係数 (§9.2) ---
    objective_weights: Dict[str, float] = field(default_factory=lambda: {
        "vehicle_fixed_cost": 1.0,
        "electricity_cost": 1.0,
        "demand_charge_cost": 1.0,
        "fuel_cost": 1.0,
        "deadhead_cost": 1.0,
        "battery_degradation_cost": 1.0,
        "emission_cost": 0.0,
        "unserved_penalty": 10000.0,
        "slack_penalty": 1000000.0,
    })

    # --- Big-M 等 (§6.5) ---
    BIG_M_ASSIGN: float = 1e6
    BIG_M_CHARGE: float = 1e6
    BIG_M_SOC: float = 1e6
    EPSILON: float = 1e-6

    # --- 行路 (duty) 関連 (spec_v3 §6 行路設定表) ---
    duty_assignment_enabled: bool = False
    duty_enforce_depot_match: bool = True
    duty_enforce_vehicle_type_match: bool = True
    duty_allow_swap: bool = False
    # duty_list は src.schemas.duty_entities.VehicleDuty のリスト (import cycle 回避のため Any)
    duty_list: List[Any] = field(default_factory=list)
    # duty_trip_mapping: duty_id -> [task_id, ...]
    duty_trip_mapping: Dict[str, List[str]] = field(default_factory=dict)

    # --- 乗客負荷 (spec_v3 §7 trip 負荷率) ---
    passenger_load_enabled: bool = False
    # task_id -> load_factor (0.0 ~ 1.0+)
    task_load_factors: Dict[str, float] = field(default_factory=dict)

    # --- 派生集合キャッシュ (model_sets.py が埋める) ---
    K_BEV: List[str] = field(default_factory=list)
    K_ICE: List[str] = field(default_factory=list)
    K_ALL: List[str] = field(default_factory=list)
    can_follow_matrix: Dict[str, Dict[str, bool]] = field(default_factory=dict)

    @property
    def delta_t_min(self) -> float:
        return self.delta_t_hour * 60.0
