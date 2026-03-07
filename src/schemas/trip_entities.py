"""
src.schemas.trip_entities — シナリオ Trip エンティティ

不確実性評価のための scenario-specific trip energy を保持。
spec_v3 §6.3 に準拠。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional


@dataclass
class ScenarioTripEnergy:
    """不確実性シナリオごとの trip エネルギー消費量サンプル。

    spec_v3 §6.3:
        e_bev_scenario[t,k,omega] = e_bev[t,k] * energy_multiplier[omega,t]
    """
    trip_id: str
    vehicle_type_id: str
    scenario_id: str
    # --- 変動パラメータ ---
    travel_time_multiplier: float = 1.0
    energy_multiplier: float = 1.0
    congestion_index_shift: float = 0.0
    ambient_temp_c: float = 20.0
    passenger_load_multiplier: float = 1.0
    rainfall_flag: bool = False
    # --- 結果 ---
    energy_kwh: Optional[float] = None      # [kWh/trip]
    fuel_l: Optional[float] = None          # [L/trip]
    runtime_min: Optional[float] = None     # [min]
    # --- breakdown (agent_route_editable §3.4) ---
    energy_breakdown: Dict[str, float] = field(default_factory=dict)
