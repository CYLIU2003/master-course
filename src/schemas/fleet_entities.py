"""
src.schemas.fleet_entities — 車両タイプ・車両インスタンス定義

spec_v3 §2.3 に準拠。powertrain 横断比較を可能にする。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class VehicleType:
    """車両タイプマスタ。BEV / ICE / HEV / PHEV を統一フォームで定義。

    Frequently edited columns (spec_v3 §3.2):
        battery_capacity_kwh, base_energy_rate_kwh_per_km,
        base_fuel_rate_l_per_km, charging_power_max_kw
    """
    vehicle_type_id: str
    powertrain: str                          # "BEV" | "ICE" | "HEV" | "PHEV"
    # --- battery (BEV / HEV / PHEV) ---
    battery_capacity_kwh: Optional[float] = None    # [kWh]  ← 感度分析軸
    usable_battery_ratio: Optional[float] = 0.9
    # --- fuel tank (ICE / HEV / PHEV) ---
    fuel_tank_l: Optional[float] = None             # [L]
    # --- physical ---
    base_vehicle_mass_ton: Optional[float] = None   # [ton]
    passenger_capacity: Optional[int] = None
    seated_capacity: Optional[int] = None
    # --- charging/discharging ---
    charging_power_max_kw: Optional[float] = None   # [kW]  ← 感度分析軸
    discharging_power_max_kw: Optional[float] = None  # [kW] (V2G)
    regen_efficiency: Optional[float] = 0.0          # 回生効率
    charge_efficiency: float = 0.95
    # --- HVAC ---
    hvac_power_kw_cooling: Optional[float] = None   # [kW]
    hvac_power_kw_heating: Optional[float] = None   # [kW]
    # --- base consumption rates (Level 0/1 energy model) ---
    base_energy_rate_kwh_per_km: Optional[float] = None  # [kWh/km]  ← 感度分析軸
    base_fuel_rate_l_per_km: Optional[float] = None       # [L/km]    ← 感度分析軸
    # --- cost params ---
    purchase_cost_jpy: Optional[float] = None          # [JPY]
    fixed_om_cost_jpy_per_day: Optional[float] = None  # [JPY/day]
    fuel_cost_jpy_per_l: float = 145.0                  # [JPY/L] 軽油単価
    co2_emission_factor_kg_per_l: float = 2.58          # [kgCO2/L]
    battery_degradation_cost_coeff: float = 0.0         # [JPY/kWh]


@dataclass
class VehicleInstance:
    """個別車両のインスタンス（spec_v3 §2.3 Vehicle に対応）。"""
    vehicle_id: str
    vehicle_type_id: str
    depot_id: str
    initial_soc_kwh: Optional[float] = None
    initial_fuel_l: Optional[float] = None
    availability_start: Optional[str] = None   # "HH:MM"
    availability_end: Optional[str] = None     # "HH:MM"
    assigned_driver_group: Optional[str] = None
    notes: Optional[str] = None
