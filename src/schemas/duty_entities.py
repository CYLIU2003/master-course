"""
src.schemas.duty_entities — 行路設定表（Vehicle Duty）エンティティ

日本のバス事業における「行路」データ構造を定義する。
行路: 1台の車両が1日に担当する一連の便（trip）のパターン。

- duty_id: 行路 ID
- 各行路は固定された trip 列を持ち、車両は行路表に従って運用される。
- 行路設定表が指定されない場合は従来どおり任意割当モード。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class DutyLeg:
    """行路中の 1 レグ（1便 or 回送 or 休憩）。"""
    leg_index: int                          # 行路内の順番 (0-based)
    leg_type: str                           # "revenue" | "deadhead" | "break" | "pull_out" | "pull_in"
    trip_id: Optional[str] = None           # revenue leg の場合の trip_id
    from_location_id: Optional[str] = None  # 出発地点 ID
    to_location_id: Optional[str] = None    # 到着地点 ID
    start_time: Optional[str] = None        # "HH:MM"
    end_time: Optional[str] = None          # "HH:MM"
    duration_min: float = 0.0               # [min]
    distance_km: float = 0.0                # [km]
    notes: Optional[str] = None


@dataclass
class VehicleDuty:
    """1 つの行路（1 日の車両運用パターン）。

    日本バス業界の「行路設定表」に対応。
    1 行路 = 出庫 → [便1, 回送, 便2, 休憩, 便3, ...] → 入庫
    """
    duty_id: str
    duty_name: str = ""
    route_id: Optional[str] = None          # 主に担当する路線 ID
    depot_id: str = ""                      # 出庫・入庫デポ ID
    service_day_type: str = "weekday"       # "weekday" | "saturday" | "holiday"

    # --- 出庫・入庫 ---
    pull_out_time: Optional[str] = None     # "HH:MM" 出庫時刻
    pull_in_time: Optional[str] = None      # "HH:MM" 入庫時刻
    pull_out_terminal_id: Optional[str] = None
    pull_in_terminal_id: Optional[str] = None

    # --- レグリスト ---
    legs: List[DutyLeg] = field(default_factory=list)

    # --- 乗務員制約 (将来拡張) ---
    driver_group: Optional[str] = None
    max_work_time_min: float = 960.0        # [min] 16h (法規上の最大)
    max_continuous_drive_min: float = 240.0  # [min] 4h
    required_break_min: float = 30.0        # [min] 最低休憩時間

    # --- 車両制約 ---
    required_vehicle_type: Optional[str] = None  # "BEV" | "ICE" | None=any
    required_vehicle_id: Optional[str] = None    # 特定車両指定

    # --- 充電スロット ---
    charging_opportunities: List["DutyChargingSlot"] = field(default_factory=list)

    # --- 派生情報 (自動計算) ---
    total_revenue_trips: int = 0
    total_distance_km: float = 0.0
    total_operating_time_min: float = 0.0

    @property
    def trip_ids(self) -> List[str]:
        """この行路に含まれる revenue trip の ID リスト。"""
        return [leg.trip_id for leg in self.legs
                if leg.leg_type == "revenue" and leg.trip_id is not None]

    def compute_summary(self) -> None:
        """legs から派生情報を再計算する。"""
        self.total_revenue_trips = len(self.trip_ids)
        self.total_distance_km = sum(leg.distance_km for leg in self.legs)
        self.total_operating_time_min = sum(leg.duration_min for leg in self.legs)


@dataclass
class DutyChargingSlot:
    """行路内の充電機会（休憩中や折返し待ち中）。"""
    slot_index: int                         # duty legs 内での位置
    after_leg_index: int                    # 何番目の leg の後か
    location_id: str = ""                   # 充電拠点 ID
    available_time_min: float = 0.0         # 充電可能時間 [min]
    charger_site_id: Optional[str] = None


@dataclass
class DutyAssignmentConfig:
    """行路割当モードの設定。"""
    enabled: bool = False                   # True=行路制約モード, False=任意割当モード
    duties_csv_path: Optional[str] = None   # vehicle_duties.csv パス
    duty_legs_csv_path: Optional[str] = None  # duty_legs.csv パス
    allow_duty_swap: bool = False           # 行路間の車両入替を許容するか
    enforce_depot_match: bool = True        # 車両デポと行路デポの一致を要求
    enforce_vehicle_type_match: bool = True  # 車両タイプの一致を要求
