"""
src.schemas.route_entities — 路線・ネットワーク・Trip 生成エンティティ

spec_v3 §2 に準拠。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional


# ---------------------------------------------------------------------------
# Layer A — 路線ネットワーク
# ---------------------------------------------------------------------------

@dataclass
class Route:
    """路線マスタ。"""
    route_id: str
    route_name: str
    operator_id: str = ""
    mode: str = "urban_bus"           # "urban_bus" | "shuttle" | "BRT"
    direction_set: List[str] = field(default_factory=lambda: ["outbound", "inbound"])
    base_headway_min_peak: Optional[float] = None     # [min]
    base_headway_min_offpeak: Optional[float] = None  # [min]
    route_type: str = "bidirectional"  # "loop" | "bidirectional" | "branch"
    notes: Optional[str] = None


@dataclass
class Terminal:
    """始終端停留所（デポ/充電拠点を兼ねる場合あり）。"""
    terminal_id: str
    terminal_name: str
    lat: Optional[float] = None
    lon: Optional[float] = None
    is_depot: bool = False
    has_charger_site: bool = False
    charger_site_id: Optional[str] = None


@dataclass
class Stop:
    """路線上の停留所。"""
    stop_id: str
    route_id: str
    direction_id: str
    stop_sequence: int
    stop_name: str
    lat: Optional[float] = None
    lon: Optional[float] = None
    elevation_m: Optional[float] = None
    is_terminal: bool = False
    dwell_time_mean_min: float = 0.5      # [min]
    boarding_mean: Optional[float] = None
    alighting_mean: Optional[float] = None


@dataclass
class Segment:
    """Stop-to-stop 最小区間。路線編集の主対象。

    Frequently edited columns (spec_v3 §3.2):
        distance_km, scheduled_run_time_min,
        grade_avg_pct, signal_count,
        traffic_level, congestion_index
    """
    segment_id: str
    route_id: str
    direction_id: str
    from_stop_id: str
    to_stop_id: str
    sequence: int
    distance_km: float = 0.0               # [km]  ← 感度分析軸
    scheduled_run_time_min: float = 0.0    # [min] ← 感度分析軸
    mean_speed_kmh: Optional[float] = None  # [km/h]
    speed_limit_kmh: Optional[float] = None # [km/h]
    grade_avg_pct: Optional[float] = None   # [%]   ← 感度分析軸
    grade_max_pct: Optional[float] = None   # [%]
    intersection_count: Optional[int] = None
    signal_count: Optional[int] = None     # ← 感度分析軸
    curvature_level: Optional[float] = None
    road_type: Optional[str] = None         # "arterial"|"local"|"express"|"mixed"
    traffic_level: Optional[float] = None   # 0.0–1.0  ← 感度分析軸
    congestion_index: Optional[float] = None  # 0.0–3.0  ← 感度分析軸
    surface_condition: Optional[str] = None
    deadhead_allowed: bool = True
    energy_factor_override: Optional[float] = None  # BEV [kWh/km] 上書き
    fuel_factor_override: Optional[float] = None    # ICE [L/km]   上書き


@dataclass
class RouteVariant:
    """分岐・短折返しを扱うルートパターン。"""
    variant_id: str
    route_id: str
    direction_id: str
    variant_name: str
    segment_id_list: List[str] = field(default_factory=list)
    is_default: bool = True


@dataclass
class TimetablePattern:
    """ダイヤパターン（headway/固定発車時刻）。

    Frequently edited columns (spec_v3 §3.2):
        headway_min, start_time, end_time
    """
    pattern_id: str
    route_id: str
    direction_id: str
    variant_id: str
    service_day_type: str          # "weekday" | "saturday" | "holiday"
    start_time: str                # "HH:MM"
    end_time: str                  # "HH:MM"
    headway_min: float             # [min]  ← 感度分析軸
    dispatch_rule: str = "fixed_headway"  # "fixed_headway"|"fixed_departure"|"custom"


@dataclass
class ServiceCalendarRow:
    """日付 ↔ サービス日種別マッピング。"""
    date: str                # "YYYY-MM-DD"
    service_day_type: str    # "weekday" | "saturday" | "holiday" | "custom_event_day"
    is_active: bool = True


# ---------------------------------------------------------------------------
# Layer B — Trip 生成エンティティ
# ---------------------------------------------------------------------------

@dataclass
class GeneratedTrip:
    """route-detail layer から生成された trip（最適化モデルへの直接入力）。

    BEV と ICE/HEV の両推定値を保持し、同一路線条件で比較可能にする。
    """
    trip_id: str
    route_id: str
    direction_id: str
    variant_id: str
    service_day_type: str
    departure_time: str               # "HH:MM" or datetime str
    arrival_time: str                 # "HH:MM" or datetime str
    origin_terminal_id: str
    destination_terminal_id: str
    distance_km: float = 0.0          # [km]
    scheduled_runtime_min: float = 0.0  # [min]
    scheduled_dwell_total_min: float = 0.0  # [min]
    deadhead_before_km: Optional[float] = None  # [km]
    deadhead_after_km: Optional[float] = None   # [km]
    # --- エネルギー推定 (spec_v3 §5) ---
    estimated_energy_kwh_bev: Optional[float] = None  # [kWh/trip]
    estimated_fuel_l_ice: Optional[float] = None      # [L/trip]
    estimated_energy_rate_kwh_per_km: Optional[float] = None  # [kWh/km]
    estimated_fuel_rate_l_per_km: Optional[float] = None      # [L/km]
    # --- component breakdown (agent_route_editable §3.4) ---
    energy_breakdown: Dict[str, float] = field(default_factory=dict)
    fuel_breakdown: Dict[str, float] = field(default_factory=dict)
    # --- trip category ---
    trip_category: str = "revenue"    # "revenue"|"deadhead"|"pull_out"|"pull_in"


@dataclass
class DeadheadArc:
    """Trip 間の接続弧（デッドヘッド）。"""
    arc_id: str
    from_trip_id: str
    to_trip_id: str
    from_terminal_id: str
    to_terminal_id: str
    deadhead_time_min: float = 0.0       # [min]
    deadhead_distance_km: float = 0.0   # [km]
    deadhead_energy_kwh_bev: Optional[float] = None  # [kWh]
    deadhead_fuel_l_ice: Optional[float] = None      # [L]
    is_feasible_connection: bool = True
    infeasibility_reason: Optional[str] = None
