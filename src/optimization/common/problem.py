from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Any, Dict, List, Mapping, Optional, Set, Tuple

from src.dispatch.models import VehicleDuty


class OptimizationMode(str, Enum):
    MILP = "milp"
    ALNS = "alns"
    GA = "ga"
    ABC = "abc"
    HYBRID = "hybrid"


@dataclass(frozen=True)
class ProblemTrip:
    trip_id: str
    route_id: str
    origin: str
    destination: str
    departure_min: int
    arrival_min: int
    distance_km: float
    allowed_vehicle_types: Tuple[str, ...]
    energy_kwh: float = 0.0
    fuel_l: float = 0.0
    service_id: Optional[str] = None
    required_soc_departure_percent: Optional[float] = None


@dataclass(frozen=True)
class ProblemRoute:
    route_id: str
    trip_ids: Tuple[str, ...] = ()
    route_name: Optional[str] = None


@dataclass(frozen=True)
class ProblemDepot:
    depot_id: str
    name: str
    charger_ids: Tuple[str, ...] = ()
    import_limit_kw: float = 0.0
    export_limit_kw: float = 0.0
    latitude: Optional[float] = None
    longitude: Optional[float] = None


@dataclass(frozen=True)
class ProblemVehicleType:
    vehicle_type_id: str
    powertrain_type: str
    battery_capacity_kwh: Optional[float] = None
    charge_power_max_kw: Optional[float] = None
    discharge_power_max_kw: Optional[float] = None
    reserve_soc: Optional[float] = None
    fuel_tank_capacity_l: Optional[float] = None
    fuel_consumption_l_per_km: Optional[float] = None
    fixed_use_cost_jpy: float = 0.0


@dataclass(frozen=True)
class ProblemVehicle:
    vehicle_id: str
    vehicle_type: str
    home_depot_id: str
    initial_soc: Optional[float] = None
    battery_capacity_kwh: Optional[float] = None
    reserve_soc: Optional[float] = None
    available: bool = True
    initial_fuel_l: Optional[float] = None
    fuel_tank_capacity_l: Optional[float] = None
    fuel_reserve_l: Optional[float] = None
    fuel_consumption_l_per_km: Optional[float] = None
    fixed_use_cost_jpy: float = 0.0


@dataclass(frozen=True)
class ChargerDefinition:
    charger_id: str
    depot_id: str
    power_kw: float
    bidirectional: bool = False
    simultaneous_ports: int = 1


@dataclass(frozen=True)
class EnergyPriceSlot:
    slot_index: int
    grid_buy_yen_per_kwh: float = 0.0
    grid_sell_yen_per_kwh: float = 0.0
    demand_charge_weight: float = 0.0
    co2_factor: float = 0.0


@dataclass(frozen=True)
class PVSlot:
    slot_index: int
    pv_available_kw: float = 0.0


@dataclass(frozen=True)
class DepotEnergyAsset:
    depot_id: str
    pv_enabled: bool = False
    pv_generation_kwh_by_slot: Tuple[float, ...] = ()
    pv_case_id: str = "none"
    pv_capex_jpy_per_kw: float = 0.0
    pv_om_jpy_per_kw_year: float = 0.0
    pv_life_years: int = 25
    pv_capacity_kw: float = 0.0
    bess_enabled: bool = False
    bess_energy_kwh: float = 0.0
    bess_power_kw: float = 0.0
    bess_initial_soc_kwh: float = 0.0
    bess_soc_min_kwh: float = 0.0
    bess_soc_max_kwh: float = 0.0
    bess_charge_efficiency: float = 0.95
    bess_discharge_efficiency: float = 0.95
    bess_cycle_cost_yen_per_kwh: float = 0.0
    bess_capex_jpy_per_kwh: float = 0.0
    bess_om_jpy_per_kwh_year: float = 0.0
    bess_life_years: int = 15
    allow_grid_to_bess: bool = False
    grid_to_bess_price_mode: str = "tou"
    grid_to_bess_price_threshold_yen_per_kwh: float = 0.0
    grid_to_bess_allowed_slot_indices: Tuple[int, ...] = ()
    bess_priority_mode: str = "cost_driven"
    bess_terminal_soc_min_kwh: float = 0.0
    provisional_energy_cost_yen_per_kwh: float = 0.0


@dataclass(frozen=True)
class LockedOperation:
    trip_id: str
    duty_id: Optional[str] = None
    vehicle_id: Optional[str] = None
    fixed_before_min: Optional[int] = None
    actual_soc: Optional[float] = None
    actual_location: Optional[str] = None


@dataclass(frozen=True)
class OptimizationObjectiveWeights:
    energy: float = 1.0
    demand: float = 1.0
    vehicle: float = 1.0
    unserved: float = 10000.0
    switch: float = 0.0
    degradation: float = 0.0
    deviation: float = 0.0
    utilization: float = 0.0


@dataclass(frozen=True)
class OptimizationScenario:
    scenario_id: str
    horizon_start: Optional[str] = None
    horizon_end: Optional[str] = None
    timestep_min: int = 30
    objective_mode: str = "total_cost"
    diesel_price_yen_per_l: float = 0.0
    demand_charge_on_peak_yen_per_kw: float = 0.0
    demand_charge_off_peak_yen_per_kw: float = 0.0
    co2_price_per_kg: float = 0.0
    ice_co2_kg_per_l: float = 2.64
    fixed_operations_before_t0: Tuple[LockedOperation, ...] = ()
    uncertainty_flags: Mapping[str, bool] = field(default_factory=dict)


@dataclass(frozen=True)
class OptimizationConfig:
    mode: OptimizationMode = OptimizationMode.HYBRID
    time_limit_sec: int = 300
    mip_gap: float = 0.02
    random_seed: int = 42
    alns_iterations: int = 500
    no_improvement_limit: int = 100
    destroy_fraction: float = 0.25
    partial_milp_trip_limit: int = 40
    rolling_current_min: Optional[int] = None
    target_gap_to_baseline: Optional[float] = None
    warm_start: bool = True
    acceptance: str = "simulated_annealing"
    operator_selection: str = "adaptive_roulette"


@dataclass(frozen=True)
class ChargingSlot:
    vehicle_id: str
    slot_index: int
    charger_id: Optional[str]
    charge_kw: float = 0.0
    discharge_kw: float = 0.0
    charging_depot_id: Optional[str] = None
    charging_latitude: Optional[float] = None
    charging_longitude: Optional[float] = None


@dataclass(frozen=True)
class RefuelSlot:
    vehicle_id: str
    slot_index: int
    refuel_liters: float
    location_id: Optional[str] = None


@dataclass(frozen=True)
class AssignmentPlan:
    duties: Tuple[VehicleDuty, ...] = ()
    charging_slots: Tuple[ChargingSlot, ...] = ()
    refuel_slots: Tuple[RefuelSlot, ...] = ()
    grid_to_bus_kwh_by_depot_slot: Mapping[str, Mapping[int, float]] = field(default_factory=dict)
    bess_to_bus_kwh_by_depot_slot: Mapping[str, Mapping[int, float]] = field(default_factory=dict)
    pv_to_bess_kwh_by_depot_slot: Mapping[str, Mapping[int, float]] = field(default_factory=dict)
    grid_to_bess_kwh_by_depot_slot: Mapping[str, Mapping[int, float]] = field(default_factory=dict)
    pv_curtail_kwh_by_depot_slot: Mapping[str, Mapping[int, float]] = field(default_factory=dict)
    bess_soc_kwh_by_depot_slot: Mapping[str, Mapping[int, float]] = field(default_factory=dict)
    served_trip_ids: Tuple[str, ...] = ()
    unserved_trip_ids: Tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def vehicle_paths(self) -> Dict[str, Tuple[str, ...]]:
        return {
            duty.duty_id: tuple(duty.trip_ids)
            for duty in self.duties
        }


@dataclass(frozen=True)
class OperatorStats:
    selected: int = 0
    accepted: int = 0
    rejected: int = 0
    reward: float = 0.0


@dataclass(frozen=True)
class IncumbentSnapshot:
    iteration: int
    objective_value: float
    feasible: bool


@dataclass(frozen=True)
class CanonicalOptimizationProblem:
    scenario: OptimizationScenario
    dispatch_context: Any
    trips: Tuple[ProblemTrip, ...]
    vehicles: Tuple[ProblemVehicle, ...]
    routes: Tuple[ProblemRoute, ...] = ()
    depots: Tuple[ProblemDepot, ...] = ()
    vehicle_types: Tuple[ProblemVehicleType, ...] = ()
    chargers: Tuple[ChargerDefinition, ...] = ()
    price_slots: Tuple[EnergyPriceSlot, ...] = ()
    pv_slots: Tuple[PVSlot, ...] = ()
    depot_energy_assets: Mapping[str, DepotEnergyAsset] = field(default_factory=dict)
    feasible_connections: Mapping[str, Tuple[str, ...]] = field(default_factory=dict)
    objective_weights: OptimizationObjectiveWeights = field(
        default_factory=OptimizationObjectiveWeights
    )
    baseline_plan: Optional[AssignmentPlan] = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    _trip_by_id_cache: Dict[str, ProblemTrip] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "_trip_by_id_cache",
            {trip.trip_id: trip for trip in self.trips},
        )
        self._validate_depot_energy_assets()

    def _validate_depot_energy_assets(self) -> None:
        if not self.depot_energy_assets:
            return
        slot_count = len(self.price_slots)
        for depot_id, asset in self.depot_energy_assets.items():
            if not isinstance(asset, DepotEnergyAsset):
                raise ValueError(f"depot_energy_assets[{depot_id}] must be DepotEnergyAsset")
            if asset.pv_enabled and asset.pv_generation_kwh_by_slot:
                if slot_count > 0 and len(asset.pv_generation_kwh_by_slot) != slot_count:
                    raise ValueError(
                        f"Depot {depot_id} pv_generation_kwh_by_slot length ({len(asset.pv_generation_kwh_by_slot)}) "
                        f"must match price slot count ({slot_count})"
                    )
            if asset.bess_enabled:
                if asset.bess_soc_min_kwh > asset.bess_soc_max_kwh:
                    raise ValueError(f"Depot {depot_id} has invalid BESS bounds: min > max")
                if not (asset.bess_soc_min_kwh <= asset.bess_initial_soc_kwh <= asset.bess_soc_max_kwh):
                    raise ValueError(
                        f"Depot {depot_id} initial BESS SOC must be within [min, max]"
                    )

    def trip_by_id(self) -> Dict[str, ProblemTrip]:
        return self._trip_by_id_cache

    def eligible_trip_ids(self, vehicle_type: Optional[str] = None) -> List[str]:
        if vehicle_type is None:
            return [trip.trip_id for trip in self.trips]
        return [
            trip.trip_id
            for trip in self.trips
            if vehicle_type in trip.allowed_vehicle_types
        ]


def classify_peak_slots(
    price_slots: Tuple[EnergyPriceSlot, ...],
) -> Tuple[Set[int], Set[int]]:
    """Partition price slot indices into (on_peak, off_peak) sets.

    If any slot carries an explicit demand_charge_weight, that field drives the
    classification.  Otherwise the median grid-buy price is used as a threshold.
    Returns a pair (on_peak_indices, off_peak_indices).
    """
    if not price_slots:
        return set(), set()

    explicit_slots = [
        slot for slot in price_slots if abs(float(slot.demand_charge_weight or 0.0)) > 1.0e-9
    ]
    if explicit_slots:
        on_peak = {
            slot.slot_index
            for slot in price_slots
            if float(slot.demand_charge_weight or 0.0) > 0.0
        }
        off_peak = {slot.slot_index for slot in price_slots if slot.slot_index not in on_peak}
        return on_peak, off_peak

    sorted_prices = sorted(float(slot.grid_buy_yen_per_kwh or 0.0) for slot in price_slots)
    threshold = sorted_prices[len(sorted_prices) // 2] if sorted_prices else 0.0
    on_peak = {
        slot.slot_index
        for slot in price_slots
        if float(slot.grid_buy_yen_per_kwh or 0.0) >= threshold
    }
    off_peak = {slot.slot_index for slot in price_slots if slot.slot_index not in on_peak}
    return on_peak, off_peak


@dataclass(frozen=True)
class OptimizationEngineResult:
    mode: OptimizationMode
    solver_status: str
    objective_value: float
    plan: AssignmentPlan
    feasible: bool
    warnings: Tuple[str, ...] = ()
    infeasibility_reasons: Tuple[str, ...] = ()
    cost_breakdown: Mapping[str, float] = field(default_factory=dict)
    solver_metadata: Mapping[str, Any] = field(default_factory=dict)
    operator_stats: Mapping[str, OperatorStats] = field(default_factory=dict)
    incumbent_history: Tuple[IncumbentSnapshot, ...] = ()


@dataclass(frozen=True)
class SolutionState:
    problem: CanonicalOptimizationProblem
    plan: AssignmentPlan
    cost_breakdown: Mapping[str, float]
    feasible: bool
    infeasibility_reasons: Tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def objective(self) -> float:
        return float(
            self.cost_breakdown.get(
                "objective_value",
                self.cost_breakdown.get("total_cost", float("inf")),
            )
        )

    def clone(self, **changes: Any) -> "SolutionState":
        return replace(self, **changes)

    def is_feasible(self) -> bool:
        return self.feasible
