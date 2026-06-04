from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List


@dataclass(frozen=True)
class VehicleSlotLedgerRow:
    scenario_id: str
    run_id: str
    service_date: str
    weather_date: str
    operator_id: str
    vehicle_id: str
    vehicle_type: str
    slot_start: str
    slot_end: str
    slot_index: int
    slot_minutes: int
    route_id: str = ""
    route_short_name: str = ""
    trip_id: str = ""
    block_id: str = ""
    activity_type: str = "idle"
    source_event_id: str = ""
    service_km: float = 0.0
    deadhead_before_km: float = 0.0
    deadhead_after_km: float = 0.0
    deadhead_total_km: float = 0.0
    bev_drive_energy_kwh: float = 0.0
    drive_consumption_kwh: float = 0.0
    aux_consumption_kwh: float = 0.0
    ice_fuel_liter: float = 0.0
    ice_co2_kg: float = 0.0
    charge_input_kwh: float = 0.0
    charger_grid_kwh: float = 0.0
    charger_pv_direct_kwh: float = 0.0
    charger_bess_kwh: float = 0.0
    charge_loss_kwh: float = 0.0
    soc_start_kwh: float = 0.0
    soc_end_kwh: float = 0.0
    battery_capacity_kwh: float = 0.0
    charge_to_battery_kwh: float = 0.0
    fuel_start_l: float = 0.0
    fuel_end_l: float = 0.0
    refuel_l: float = 0.0
    soc_balance_error_kwh: float = 0.0
    fuel_balance_error_l: float = 0.0
    charge_source_balance_error_kwh: float = 0.0
    soc_start_ratio: float = 0.0
    soc_end_ratio: float = 0.0
    soc_delta_charge_ratio: float = 0.0
    soc_delta_drive_ratio: float = 0.0
    soc_delta_loss_ratio: float = 0.0
    soc_violation_flag: bool = False
    soc_violation_type: str = ""
    tou_energy_price_jpy_per_kwh: float = 0.0
    fuel_price_jpy_per_liter: float = 0.0
    battery_degradation_price_jpy_per_kwh: float = 0.0
    electricity_cost_jpy: float = 0.0
    fuel_cost_jpy: float = 0.0
    co2_cost_jpy: float = 0.0
    battery_degradation_cost_jpy: float = 0.0
    provenance_mode: str = "inferred"
    repair_reason: str = ""
    created_by_stage: str = "reporting_aggregation"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class EnergyFlowLedgerRow:
    scenario_id: str
    run_id: str
    service_date: str
    weather_date: str
    operator_id: str
    depot_id: str
    slot_start: str
    slot_end: str
    slot_index: int
    slot_minutes: int
    timestamp: str = ""
    pv_generation_kwh: float = 0.0
    pv_to_bus_kwh: float = 0.0
    pv_to_bess_kwh: float = 0.0
    pv_curtailed_kwh: float = 0.0
    pv_curtailment_kwh: float = 0.0
    pv_export_kwh: float = 0.0
    bess_to_bus_kwh: float = 0.0
    bess_charge_kwh: float = 0.0
    bess_discharge_kwh: float = 0.0
    bess_soc_start_kwh: float = 0.0
    bess_soc_end_kwh: float = 0.0
    grid_to_bus_kwh: float = 0.0
    grid_to_bess_kwh: float = 0.0
    depot_aux_grid_kwh: float = 0.0
    grid_total_kwh: float = 0.0
    grid_kw: float = 0.0
    grid_import_kw: float = 0.0
    grid_import_kwh: float = 0.0
    bus_charging_total_kwh: float = 0.0
    grid_import_cumulative_kwh: float = 0.0
    grid_purchase_cost_jpy: float = 0.0
    grid_purchase_cumulative_cost_jpy: float = 0.0
    pv_balance_error_kwh: float = 0.0
    grid_balance_error_kwh: float = 0.0
    tou_energy_price_jpy_per_kwh: float = 0.0
    grid_emission_factor_kg_per_kwh: float = 0.0
    energy_cost_jpy: float = 0.0
    demand_rate_jpy_per_kw: float = 0.0
    demand_cost_jpy: float = 0.0
    contract_power_kw: float = 0.0
    contract_power_exceeded: bool = False
    contract_overage_kw: float = 0.0
    contract_overage_cost_jpy: float = 0.0
    provenance_mode: str = "inferred"
    repair_reason: str = ""
    created_by_stage: str = "reporting_aggregation"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class VehicleEnergyLedgerRow:
    scenario_id: str
    run_id: str
    operator_id: str
    service_date: str
    weather_date: str
    vehicle_id: str
    vehicle_type: str
    depot_id: str
    slot_index: int
    slot_start: str
    slot_end: str
    slot_minutes: int
    activity_type: str = "idle"
    trip_id: str = ""
    route_id: str = ""
    route_family_code: str = ""
    direction: str = ""
    route_variant_type: str = ""
    distance_km: float = 0.0
    deadhead_km: float = 0.0
    duration_min: float = 0.0
    soc_start_kwh: float = 0.0
    soc_end_kwh: float = 0.0
    soc_delta_kwh: float = 0.0
    battery_capacity_kwh: float = 0.0
    soc_start_pct: float = 0.0
    soc_end_pct: float = 0.0
    bev_drive_consumption_kwh: float = 0.0
    charge_input_kwh: float = 0.0
    charge_to_battery_kwh: float = 0.0
    charge_loss_kwh: float = 0.0
    grid_to_vehicle_kwh: float = 0.0
    pv_to_vehicle_kwh: float = 0.0
    bess_to_vehicle_kwh: float = 0.0
    charge_source_balance_error_kwh: float = 0.0
    soc_balance_error_kwh: float = 0.0
    fuel_start_l: float = 0.0
    fuel_end_l: float = 0.0
    fuel_delta_l: float = 0.0
    fuel_tank_capacity_l: float = 0.0
    fuel_consumed_l: float = 0.0
    refuel_l: float = 0.0
    fuel_balance_error_l: float = 0.0
    diesel_price_yen_per_l: float = 0.0
    fuel_cost_jpy: float = 0.0
    ice_co2_kg: float = 0.0
    electricity_price_yen_per_kwh: float = 0.0
    electricity_cost_jpy: float = 0.0
    vehicle_usage_cost_allocated_jpy: float = 0.0
    co2_cost_jpy: float = 0.0
    source_allocation_method: str = "proportional_by_timestep"
    provenance_mode: str = "inferred"
    repair_reason: str = ""
    created_by_stage: str = "reporting_aggregation"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AccountingArtifacts:
    vehicle_slot_ledger: List[VehicleSlotLedgerRow] = field(default_factory=list)
    vehicle_energy_ledger: List[VehicleEnergyLedgerRow] = field(default_factory=list)
    energy_flow_ledger: List[EnergyFlowLedgerRow] = field(default_factory=list)
    fuel_canonical_ledger: List[Dict[str, Any]] = field(default_factory=list)
    fuel_timeseries: List[Dict[str, Any]] = field(default_factory=list)
    co2_timeseries: List[Dict[str, Any]] = field(default_factory=list)
    initial_soc_ledger: List[Dict[str, Any]] = field(default_factory=list)
    initial_soc_precheck: List[Dict[str, Any]] = field(default_factory=list)
    data_flow_validation: List[Dict[str, Any]] = field(default_factory=list)
    summary: Dict[str, Any] = field(default_factory=dict)

