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
    ice_fuel_liter: float = 0.0
    ice_co2_kg: float = 0.0
    charge_input_kwh: float = 0.0
    charger_grid_kwh: float = 0.0
    charger_pv_direct_kwh: float = 0.0
    charger_bess_kwh: float = 0.0
    charge_loss_kwh: float = 0.0
    soc_start_ratio: float = 0.0
    soc_end_ratio: float = 0.0
    soc_delta_charge_ratio: float = 0.0
    soc_delta_drive_ratio: float = 0.0
    soc_delta_loss_ratio: float = 0.0
    soc_violation_flag: bool = False
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
    pv_generation_kwh: float = 0.0
    pv_to_bus_kwh: float = 0.0
    pv_to_bess_kwh: float = 0.0
    pv_curtailed_kwh: float = 0.0
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
    tou_energy_price_jpy_per_kwh: float = 0.0
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
class AccountingArtifacts:
    vehicle_slot_ledger: List[VehicleSlotLedgerRow] = field(default_factory=list)
    energy_flow_ledger: List[EnergyFlowLedgerRow] = field(default_factory=list)
    summary: Dict[str, Any] = field(default_factory=dict)

