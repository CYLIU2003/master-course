from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum
import math
import re
from typing import Any, Dict, List, Mapping, Optional, Set, Tuple

from src.dispatch.models import VehicleDuty
from .bess_terminal_policy import (
    BESS_TERMINAL_POLICY_FIXED_TARGET,
    BESS_TERMINAL_POLICY_RETURN_TO_INITIAL,
    normalize_bess_terminal_policy,
)
from .time_axis import (
    chronological_duty_key,
    normalize_horizon_start_min,
    normalize_timestep_min,
)


class OptimizationMode(str, Enum):
    MILP = "milp"
    ALNS = "alns"
    GA = "ga"
    ABC = "abc"
    HYBRID = "hybrid"


VALID_PHASES: Set[str] = {
    "phase1_charging_only",
    "phase2_assignment_only",
    "phase3_two_stage",
    "phase4_integrated",
    "diagnostic",
}

PHASE_ALIASES: Dict[str, str] = {
    "phase1": "phase1_charging_only",
    "phase2": "phase2_assignment_only",
    "phase3": "phase3_two_stage",
    "phase4": "phase4_integrated",
    "diagnostic_mode": "diagnostic",
    "thesis_mode": "phase3_two_stage",
    "debug_mode": "diagnostic",
    "mode_milp_only": "phase3_two_stage",
    "integrated": "phase4_integrated",
}


def normalize_phase(value: Any, *, default: str = "phase3_two_stage") -> str:
    normalized_default = str(default or "phase3_two_stage").strip().lower() or "phase3_two_stage"
    if normalized_default not in VALID_PHASES:
        normalized_default = "phase3_two_stage"
    raw = str(value or "").strip().lower()
    if not raw:
        return normalized_default
    if raw in VALID_PHASES:
        return raw
    if raw in PHASE_ALIASES:
        return PHASE_ALIASES[raw]
    return normalized_default


VALID_SERVICE_COVERAGE_MODES: Set[str] = {"strict", "penalized"}


def normalize_service_coverage_mode(
    raw_value: Any,
    *,
    default: str = "strict",
) -> str:
    normalized_default = str(default or "strict").strip().lower() or "strict"
    if normalized_default not in VALID_SERVICE_COVERAGE_MODES:
        normalized_default = "strict"
    normalized = str(raw_value or normalized_default).strip().lower()
    if normalized in VALID_SERVICE_COVERAGE_MODES:
        return normalized
    return normalized_default


def service_coverage_allows_partial_service(raw_value: Any) -> bool:
    return normalize_service_coverage_mode(raw_value) == "penalized"


def resolve_service_coverage_mode(
    explicit_mode: Any,
    legacy_allow_partial_service: Any | None = None,
    *,
    default: str = "strict",
) -> str:
    explicit_text = str(explicit_mode or "").strip()
    if explicit_text:
        return normalize_service_coverage_mode(explicit_text, default=default)
    if legacy_allow_partial_service is None:
        return normalize_service_coverage_mode(None, default=default)
    return "penalized" if bool(legacy_allow_partial_service) else "strict"


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
    route_family_code: str = ""
    direction: str = ""
    route_variant_type: str = "unknown"
    energy_kwh_by_vehicle_type: Mapping[str, float] = field(default_factory=dict)
    fuel_l_by_vehicle_type: Mapping[str, float] = field(default_factory=dict)
    energy_model_id: str = "distance_average_v0"
    energy_model_provenance: Mapping[str, Any] = field(default_factory=dict)


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
    co2_emission_kg_per_l: Optional[float] = None
    energy_consumption_kwh_per_km: Optional[float] = None
    fixed_use_cost_jpy: float = 0.0


@dataclass(frozen=True)
class ProblemVehicle:
    """Concrete vehicle candidate for optimization.

    available=True means solvers may assign duties to this vehicle.
    available=False means baseline builders, MILP, and metaheuristics must
    exclude it from assignment candidates while keeping it available for audit.
    """

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
    energy_consumption_kwh_per_km: Optional[float] = None
    fixed_use_cost_jpy: float = 0.0
    charge_power_max_kw: Optional[float] = None
    # Empty means that every charger at the home depot is compatible.  When
    # populated, the formal MILP may use only the listed physical chargers.
    compatible_charger_ids: Tuple[str, ...] = ()


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
    available_pv_surplus_kwh_by_slot: Tuple[float, ...] = ()
    pv_input_semantics: str = "available_surplus_after_depot_load"
    capacity_factor_by_slot: Tuple[float, ...] = ()
    pv_case_id: str = "none"
    pv_capex_jpy_per_kw: float = 0.0
    pv_om_jpy_per_kw_year: float = 0.0
    pv_life_years: int = 25
    pv_capacity_kw: float = 0.0
    pv_supply_scale: float = 1.0
    depot_area_m2: Optional[float] = None
    pv_installable_area_m2: float = 0.0
    usable_area_ratio: float = 0.35
    panel_power_density_kw_m2: float = 0.20
    performance_ratio: float = 0.85
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
    allow_pv_to_bess: bool = True
    allow_grid_to_bess: bool = False
    allow_bess_to_bus: bool = True
    grid_to_bess_price_mode: str = "tou"
    grid_to_bess_price_threshold_yen_per_kwh: float = 0.0
    grid_to_bess_allowed_slot_indices: Tuple[int, ...] = ()
    bess_priority_mode: str = "cost_driven"
    bess_terminal_soc_min_kwh: float = 0.0
    # Empty preserves legacy constructor behavior: a positive target implies
    # fixed_target, otherwise the model uses only the hard terminal floor.
    bess_terminal_soc_policy: str = ""
    bess_terminal_soc_target_kwh: float = 0.0
    bess_terminal_soc_deviation_penalty_yen_per_kwh: float = 20.0
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
    fuel: float = 1.0
    demand: float = 1.0
    vehicle: float = 1.0
    vehicle_usage: float = 1.0
    unserved: float = 10000.0
    switch: float = 0.0
    degradation: float = 0.0
    deviation: float = 0.0
    utilization: float = 0.0
    return_leg_bonus: float = 1.0  # 同一路線の折り返し接続に対するボーナス係数


@dataclass(frozen=True)
class OptimizationScenario:
    scenario_id: str
    horizon_start: Optional[str] = None
    horizon_end: Optional[str] = None
    timestep_min: int = 30
    objective_mode: str = "total_cost"
    diesel_price_yen_per_l: float = 0.0
    demand_charge_on_peak_yen_per_kw: float = 0.0  # Monthly rate [yen/kW/month], converted to horizon in evaluator
    demand_charge_off_peak_yen_per_kw: float = 0.0  # Monthly rate [yen/kW/month], converted to horizon in evaluator
    co2_price_per_kg: float = 0.0
    ice_co2_kg_per_l: float = 2.64
    planning_days: int = 1
    allow_same_day_depot_cycles: bool = True
    max_depot_cycles_per_vehicle_per_day: int = 3
    allow_overnight_depot_moves: str = "forbid"
    overnight_window_start: str = "23:00"
    overnight_window_end: str = "05:00"
    overnight_charge_target_mode: str = "minimum_required"
    fixed_operations_before_t0: Tuple[LockedOperation, ...] = ()
    uncertainty_flags: Mapping[str, bool] = field(default_factory=dict)
    service_coverage_mode: str = "strict"
    # Keep this additive field at the end so existing positional callers retain
    # the historical constructor order.
    horizon_duration_min: Optional[int] = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "timestep_min", normalize_timestep_min(self.timestep_min, default=30))
        if self.horizon_duration_min is not None:
            duration_min = int(self.horizon_duration_min)
            if duration_min <= 0:
                raise ValueError("horizon_duration_min must be positive when provided")
            object.__setattr__(self, "horizon_duration_min", duration_min)
    
    @property
    def planning_horizon_hours(self) -> float:
        """Calculate planning horizon in hours from scenario configuration.
        
        Uses the explicit slot-derived duration when available.  The legacy
        clock calculation remains only for callers that have not migrated.
        """
        if self.horizon_duration_min is not None:
            return float(self.horizon_duration_min) / 60.0
        if not self.horizon_start or not self.horizon_end:
            return float(self.planning_days) * 24.0
        try:
            h_start, m_start = map(int, self.horizon_start.split(":"))
            h_end, m_end = map(int, self.horizon_end.split(":"))
            start_min = h_start * 60 + m_start
            end_min = h_end * 60 + m_end
            if end_min <= start_min:
                end_min += 24 * 60
            duration_hours = (end_min - start_min) / 60.0
            return max(duration_hours, 1.0)
        except (ValueError, AttributeError):
            return float(self.planning_days) * 24.0

    @property
    def demand_charge_horizon_factor(self) -> float:
        """Convert a monthly demand-charge rate to this planning horizon."""

        return (self.planning_horizon_hours / 24.0) / 30.0

    @property
    def demand_charge_on_peak_horizon_yen_per_kw(self) -> float:
        return max(self.demand_charge_on_peak_yen_per_kw, 0.0) * self.demand_charge_horizon_factor

    @property
    def demand_charge_off_peak_horizon_yen_per_kw(self) -> float:
        return max(self.demand_charge_off_peak_yen_per_kw, 0.0) * self.demand_charge_horizon_factor


@dataclass(frozen=True)
class OptimizationConfig:
    mode: OptimizationMode = OptimizationMode.HYBRID
    time_limit_sec: int = 300
    # Optional stage-specific limits.  ``None`` preserves the historical
    # Phase 3 split (half of ``time_limit_sec`` per stage).  Explicit values
    # make the research time budget reproducible and avoid reserving hundreds
    # of seconds for the usually small fixed-assignment charging MILP.
    stage1_time_limit_sec: Optional[int] = None
    stage2_time_limit_sec: Optional[int] = None
    # Stage 1 may derive a Gurobi ``BestObjStop`` threshold from an analytical
    # lower bound.  It is useful for obtaining a feasible planning result
    # quickly, but it changes the stopping rule and therefore must be disabled
    # for like-for-like wall-clock comparisons.
    stage1_best_obj_stop_enabled: bool = True
    # ``None`` leaves Gurobi's default thread selection intact.  Experiments
    # that compare solve time should set this explicitly and record it.
    gurobi_threads: Optional[int] = None
    # Stage-1 search controls are an explicit, auditable solver profile rather
    # than an implicit performance tweak. ``default`` reproduces Gurobi's
    # documented defaults; ``bound_focus`` directs search effort toward the
    # dual bound, while ``root_cut_focus`` also requests Gurobi's aggressive
    # generic cut setting.  Neither changes a model variable, constraint, or
    # objective; every effective control is persisted in run metadata.
    stage1_gurobi_search_profile: str = "default"
    # Gurobi internal model scaling for a controlled numerical diagnostic.
    # ``-1`` preserves the solver default.  Any non-default value changes no
    # model semantics but must be persisted and kept out of research-result
    # acceptance until separately validated on the frozen comparison input.
    stage1_gurobi_scale_flag: int = -1
    # An opt-in research diagnostic solves a separate continuous relaxation
    # after Stage 1 is fully built.  It records aggregate fractional-assignment
    # evidence and never feeds rows, starts, bounds, or decisions back into
    # the production Stage-1 MIP.
    stage1_root_lp_diagnostic_enabled: bool = False
    # The diagnostic runs under the same shared Phase-3 wall-clock deadline.
    # This small default prevents an opt-in observation from consuming the
    # declared Stage-1/Stage-2 research budget.
    stage1_root_lp_diagnostic_time_limit_sec: int = 30
    # Opt-in, read-only scan of the completed Stage-1 constraint matrix.  It
    # identifies the rows and variables that attain the smallest nonzero
    # coefficient reported by Gurobi's aggregate numeric diagnostics.  The
    # scan never adds or changes model content or solver controls and is
    # diagnostic-only, not research-result evidence.
    stage1_numeric_coefficient_diagnostic_enabled: bool = False
    # The default lazy separator keeps exact fragment-transition rows out of
    # the root LP. ``lifted_root`` adds compact, integer-equivalent lifted
    # aggregates; ``lazy_root_cuts`` submits violated rows at fractional nodes;
    # ``explicit_root`` materializes every row. All modes preserve the integer
    # feasible set and are recorded for controlled diagnostics.
    stage1_fragment_transition_cut_mode: str = "lazy"
    # Stage 1 is the runtime-dominant assignment MILP and uses Gurobi's
    # documented default.  Stage 2 uses stricter primal and integrality
    # tolerances because its terminal SOC equality and physical charger
    # selection are independently audited.  In particular, a loose integer
    # tolerance can otherwise classify a tiny positive charger-assignment
    # value as binary zero while leaving a linked continuous charging-power
    # residue.  Effective values are persisted in solver_settings.json.
    stage1_gurobi_feasibility_tol: float = 1.0e-6
    stage2_gurobi_feasibility_tol: float = 1.0e-9
    stage2_gurobi_integrality_tol: float = 1.0e-9
    # Phase 3 may retain several distinct Stage 1 assignments and run the
    # fixed-assignment Stage 2 dispatch for each one.  The selected plan is the
    # feasible candidate with the lowest canonical evaluated cost; this remains
    # a two-stage heuristic and is not an integrated global-optimality claim.
    stage1_stage2_candidate_limit: int = 1
    # Optional local search over *used vehicle* powertrain compositions around
    # the primary Stage 1 incumbent.  A positive radius explicitly resolves
    # (BEV + d, ICE - d) and (BEV - d, ICE + d) for d=1..radius before the
    # existing per-trip powertrain-pattern enumeration.  This is deliberately
    # separate from a policy minimum-BEV constraint: it broadens the candidate
    # evidence and never adds a BEV preference to the objective.
    #
    # ``0`` preserves the legacy candidate search for non-formal callers.
    # Formal frontend research runs enforce a radius of at least two at the
    # BFF boundary and fail release when that evidence is unresolved.  The
    # Phase 4 seed uses a wider symmetric radius so a poor primary incumbent
    # cannot prevent economically relevant one-for-one powertrain swaps from
    # reaching the integrated MIP start.
    stage1_composition_search_radius: int = 0
    # Each exact used-powertrain target receives a bounded share of the
    # Stage 1 candidate-enumeration reserve.  The cap must be long enough for
    # the full-network count-constrained MIP to discover an incumbent; a
    # shorter diagnostic slice can incorrectly leave every adjacent target
    # unresolved without proving feasibility or infeasibility.
    stage1_composition_target_time_limit_sec: float = 60.0
    # Optional lower-bound frontier over the number of activated electric
    # vehicles.  Unlike ``stage1_composition_search_radius``, each temporary
    # solve adds only ``sum(used_electric) >= K``.  ICE activation and the
    # total used fleet therefore remain endogenous to the unchanged economic
    # objective.  This is an evidence-generating search, not a BEV preference.
    stage1_bev_frontier_enabled: bool = False
    stage1_bev_frontier_min_count: int = 15
    stage1_bev_frontier_max_count: int = 35
    stage1_bev_frontier_target_time_limit_sec: float = 120.0
    # Phase 4 may be requested as an accounting-cost oracle only through this
    # explicit contract.  The engine then removes every solver-only preference
    # term and verifies the raw MILP objective against canonical accounting.
    integrated_actual_cost_objective: bool = False
    trip_energy_model: str = "distance_average_v0"
    trip_energy_sensitivity_scale: float = 1.0
    bev_trip_energy_sensitivity_scale: float = 1.0
    ice_trip_fuel_sensitivity_scale: float = 1.0
    # Optional Phase 4 policy frontiers.  Both retain the same canonical-cost
    # structural contract, but optimize ICE fuel first and total cost second.
    # ``integrated_actual_cost_upper_bound_jpy`` turns the unconstrained
    # maximum-EV case into a cost-constrained epsilon frontier point.
    integrated_ev_utilization_mode: str = "disabled"
    integrated_actual_cost_upper_bound_jpy: Optional[float] = None
    integrated_actual_cost_upper_bound_delta_ratio: Optional[float] = None
    co2_emissions_cap_kg: Optional[float] = None
    # A full-network Phase 4 model is substantially harder than the Phase 3
    # decomposition.  When enabled, the engine first solves Phase 3 on the
    # *same in-memory canonical problem* and accepts its plan only after full
    # coverage, Stage 2, and independent physical-feasibility checks pass.
    # The accepted plan is a MIP start/upper bound only; it is never returned
    # as a Phase 4 result or treated as integrated optimality evidence.
    phase4_phase3_seed_enabled: bool = False
    phase4_phase3_seed_time_limit_sec: int = 600
    # Phase 4 needs one physically verified same-problem incumbent, not a
    # separate exhaustive proof over Stage-1 powertrain compositions.  The
    # integrated MILP itself keeps every feasible composition in scope.
    # Retain the wider Phase-3 search as an explicit diagnostic option only.
    phase4_phase3_seed_composition_search_enabled: bool = True
    phase4_phase3_seed_bev_frontier_enabled: bool = False
    # After the neutral Phase 3 seed search, a bounded fixed-assignment
    # neighborhood may activate currently unused BEVs and exchange BEV
    # identities.  Every candidate is accepted only after an exact Stage 2
    # charging/SOC solve plus canonical cost and physical validation.  This is
    # an upper-bound generator; it never changes the integrated objective or
    # supplies optimality evidence by itself.
    phase4_phase3_seed_unused_bev_neighborhood_enabled: bool = False
    phase4_phase3_seed_unused_bev_neighborhood_time_limit_sec: int = 120
    phase4_phase3_seed_unused_bev_neighborhood_per_solve_sec: int = 5
    phase4_phase3_seed_unused_bev_neighborhood_max_evaluations: int = 512
    # Route-band duty repartition is more expensive than fixed-duty identity
    # replacement.  Give it a separate, explicit budget so it cannot consume
    # the proven fixed-duty neighborhood's time allowance.
    phase4_phase3_seed_route_band_repartition_time_limit_sec: int = 90
    phase4_phase3_seed_powertrain_duty_swap_rounds: int = 2
    phase4_phase3_seed_unused_bev_identity_exchange_rounds: int = 2
    # A Phase 3 plan is physically valid under the decomposed Stage 2 model,
    # but that alone does not prove it satisfies every Phase 4 constraint.
    # Before the unrestricted integrated search, temporarily fix only the
    # seed's dispatch binaries and let the integrated model rebuild charging,
    # charger occupancy, SOC, PV and BESS recourse.  A feasible recourse is
    # then promoted to a complete integrated MIP start.
    phase4_integrated_seed_recourse_preflight_enabled: bool = True
    phase4_integrated_seed_recourse_time_limit_sec: int = 300
    mip_gap: float = 0.02
    random_seed: int = 42
    alns_iterations: int = 800  # Increased from 500
    no_improvement_limit: int = 150  # Increased from 100
    destroy_fraction: float = 0.25
    partial_milp_trip_limit: int = 40
    rolling_current_min: Optional[int] = None
    # Set only by the fixed-assignment charging re-optimizer.  The MILP then
    # solves the remaining service day and the caller executes the first
    # ``rolling_execution_minutes`` before supplying updated state again.
    rolling_horizon_policy: str = ""
    rolling_execution_minutes: Optional[int] = None
    rolling_observed_on_peak_kw_by_depot: Mapping[str, float] = field(default_factory=dict)
    rolling_observed_off_peak_kw_by_depot: Mapping[str, float] = field(default_factory=dict)
    # Vehicles with positive charge power in both the last executed slot and
    # the first remaining planned slot.  The first slot of the next rolling
    # horizon continues those sessions, so setup time must not be charged twice.
    rolling_active_charge_session_vehicle_ids: Tuple[str, ...] = ()
    target_gap_to_baseline: Optional[float] = None
    warm_start: bool = True
    acceptance: str = "simulated_annealing"
    operator_selection: str = "adaptive_roulette"
    use_data_driven_peak_removal: bool = True
    peak_hour_windows_min: Tuple[Tuple[int, int], ...] = ((7 * 60, 9 * 60),)
    worst_trip_scoring: str = "marginal_cost"
    thesis_mode: bool = False
    debug_mode: bool = False
    research_run: bool = False
    allow_postsolve_repair: bool = True
    phase: str = ""
    requested_phase_token: str = ""
    requested_phase: str = ""
    resolved_phase: str = ""
    executed_phase: str = ""
    diagnostic_mode: bool = False
    fixed_assignment: Optional["AssignmentPlan"] = None


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
    # Energy provenance is independent of the physical charger.  Legacy
    # artifacts may omit this and encode the source as ``grid:<depot>`` etc.
    energy_source: Optional[str] = None


@dataclass(frozen=True)
class RefuelSlot:
    vehicle_id: str
    slot_index: int
    refuel_liters: float
    location_id: Optional[str] = None


@dataclass(frozen=True)
class VehicleCostLedgerEntry:
    vehicle_id: str
    day_index: int
    provisional_drive_cost_jpy: float = 0.0
    provisional_leftover_cost_jpy: float = 0.0
    realized_charge_cost_jpy: float = 0.0
    realized_refuel_cost_jpy: float = 0.0
    realized_bess_discharge_cost_jpy: float = 0.0
    contract_overage_allocated_jpy: float = 0.0
    start_soc_kwh: Optional[float] = None
    end_soc_kwh: Optional[float] = None
    start_fuel_l: Optional[float] = None
    end_fuel_l: Optional[float] = None


@dataclass(frozen=True)
class DailyCostLedgerEntry:
    day_index: int
    service_date: Optional[str] = None
    ev_provisional_drive_cost_jpy: float = 0.0
    ev_realized_charge_cost_jpy: float = 0.0
    ev_leftover_provisional_cost_jpy: float = 0.0
    ice_provisional_drive_cost_jpy: float = 0.0
    ice_realized_refuel_cost_jpy: float = 0.0
    ice_leftover_provisional_cost_jpy: float = 0.0
    demand_charge_jpy: float = 0.0
    total_cost_jpy: float = 0.0


@dataclass(frozen=True)
class AssignmentPlan:
    duties: Tuple[VehicleDuty, ...] = ()
    charging_slots: Tuple[ChargingSlot, ...] = ()
    refuel_slots: Tuple[RefuelSlot, ...] = ()
    grid_to_bus_kwh_by_depot_slot: Mapping[str, Mapping[int, float]] = field(default_factory=dict)
    pv_to_bus_kwh_by_depot_slot: Mapping[str, Mapping[int, float]] = field(default_factory=dict)
    bess_to_bus_kwh_by_depot_slot: Mapping[str, Mapping[int, float]] = field(default_factory=dict)
    pv_to_bess_kwh_by_depot_slot: Mapping[str, Mapping[int, float]] = field(default_factory=dict)
    grid_to_bess_kwh_by_depot_slot: Mapping[str, Mapping[int, float]] = field(default_factory=dict)
    pv_curtail_kwh_by_depot_slot: Mapping[str, Mapping[int, float]] = field(default_factory=dict)
    bess_soc_kwh_by_depot_slot: Mapping[str, Mapping[int, float]] = field(default_factory=dict)
    contract_over_limit_kwh_by_depot_slot: Mapping[str, Mapping[int, float]] = field(default_factory=dict)
    vehicle_soc_kwh_by_vehicle_slot: Mapping[str, Mapping[int, float]] = field(default_factory=dict)
    vehicle_cost_ledger: Tuple[VehicleCostLedgerEntry, ...] = ()
    daily_cost_ledger: Tuple[DailyCostLedgerEntry, ...] = ()
    served_trip_ids: Tuple[str, ...] = ()
    unserved_trip_ids: Tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def duty_vehicle_map(self) -> Dict[str, str]:
        raw = self.metadata.get("duty_vehicle_map") if isinstance(self.metadata, Mapping) else {}
        if not isinstance(raw, Mapping):
            raw = {}
        normalized: Dict[str, str] = {}
        for duty in self.duties:
            duty_id = str(duty.duty_id)
            mapped = str(raw.get(duty_id) or "").strip()
            normalized[duty_id] = mapped or _fallback_vehicle_id_from_duty_id(duty_id)
        return normalized

    def vehicle_id_for_duty(self, duty_id: str) -> str:
        duty_key = str(duty_id or "")
        raw = self.metadata.get("duty_vehicle_map") if isinstance(self.metadata, Mapping) else {}
        if isinstance(raw, Mapping):
            mapped = str(raw.get(duty_key) or "").strip()
            if mapped:
                return mapped
        return _fallback_vehicle_id_from_duty_id(duty_key)

    def duties_by_vehicle(self) -> Dict[str, Tuple[VehicleDuty, ...]]:
        grouped: Dict[str, List[VehicleDuty]] = {}
        for duty in self.duties:
            grouped.setdefault(self.vehicle_id_for_duty(duty.duty_id), []).append(duty)
        horizon_start_min = normalize_horizon_start_min(
            self.metadata.get("horizon_start_min")
            or self.metadata.get("horizon_start")
        )
        return {
            vehicle_id: tuple(
                sorted(
                    duties,
                    key=lambda duty: chronological_duty_key(
                        duty, horizon_start_min=horizon_start_min
                    ),
                )
            )
            for vehicle_id, duties in grouped.items()
        }

    def vehicle_fragment_counts(self) -> Dict[str, int]:
        return {
            vehicle_id: len(duties)
            for vehicle_id, duties in self.duties_by_vehicle().items()
        }

    def vehicles_with_multiple_fragments(self) -> Tuple[str, ...]:
        return tuple(
            sorted(
                vehicle_id
                for vehicle_id, count in self.vehicle_fragment_counts().items()
                if count > 1
            )
        )

    def max_fragments_observed(self) -> int:
        counts = self.vehicle_fragment_counts()
        return max(counts.values(), default=0)

    def count_used_available_vehicles(
        self,
        problem: "CanonicalOptimizationProblem",
    ) -> int:
        available_ids = {
            str(vehicle.vehicle_id)
            for vehicle in problem.vehicles
            if bool(getattr(vehicle, "available", True))
        }
        return len(set(self.duties_by_vehicle()).intersection(available_ids))

    def unused_available_vehicle_ids(
        self,
        problem: "CanonicalOptimizationProblem",
    ) -> Tuple[str, ...]:
        used_ids = set(self.duties_by_vehicle())
        return tuple(
            sorted(
                str(vehicle.vehicle_id)
                for vehicle in problem.vehicles
                if bool(getattr(vehicle, "available", True))
                and str(vehicle.vehicle_id) not in used_ids
            )
        )

    def vehicle_paths(self) -> Dict[str, Tuple[str, ...]]:
        paths: Dict[str, List[str]] = {}
        for vehicle_id, duties in self.duties_by_vehicle().items():
            vehicle_path: List[str] = []
            for duty in duties:
                vehicle_path.extend(duty.trip_ids)
            paths[vehicle_id] = vehicle_path
        return {
            vehicle_id: tuple(trip_ids)
            for vehicle_id, trip_ids in paths.items()
        }


_FRAGMENT_SUFFIX_RE = re.compile(r"(?:__frag\d+)(?:__[^_]+\d*)*$")

DAY_MINUTES = 24 * 60


def day_index_for_minute(minute: int, horizon_start_min: int = 0) -> int:
    adjusted = int(minute) - int(horizon_start_min or 0)
    if adjusted < 0:
        adjusted = 0
    return adjusted // DAY_MINUTES


def _fallback_vehicle_id_from_duty_id(duty_id: str) -> str:
    raw = str(duty_id or "").strip()
    if raw.startswith("milp_") and len(raw) > 5:
        raw = raw[5:]
    return _FRAGMENT_SUFFIX_RE.sub("", raw)


def normalize_required_soc_departure_ratio(
    raw_value: Any,
    *,
    treat_values_le_one_as_percent: bool = False,
) -> Optional[float]:
    if raw_value is None:
        return None
    try:
        parsed = float(raw_value)
    except (TypeError, ValueError):
        return None
    if parsed <= 0.0:
        return None
    if parsed > 1.0 or treat_values_le_one_as_percent:
        parsed = parsed / 100.0
    return min(parsed, 1.0)


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
    wall_clock_sec: float = 0.0


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
            pv_capacity_kw = float(asset.pv_capacity_kw or 0.0)
            if not math.isfinite(pv_capacity_kw) or pv_capacity_kw < 0.0:
                raise ValueError(
                    f"Depot {depot_id} PV capacity must be finite and non-negative"
                )
            pv_supply_scale = float(asset.pv_supply_scale)
            if not math.isfinite(pv_supply_scale) or pv_supply_scale < 0.0:
                raise ValueError(
                    f"Depot {depot_id} PV supply scale must be finite and non-negative"
                )
            if any(
                not math.isfinite(float(value)) or float(value) < 0.0
                for value in asset.pv_generation_kwh_by_slot
            ):
                raise ValueError(
                    f"Depot {depot_id} PV generation must be finite and non-negative"
                )
            if any(
                not math.isfinite(float(value))
                or not (0.0 <= float(value) <= 1.0)
                for value in asset.capacity_factor_by_slot
            ):
                raise ValueError(
                    f"Depot {depot_id} PV capacity factors must be finite and within [0, 1]"
                )
            if asset.pv_enabled and asset.pv_generation_kwh_by_slot:
                if slot_count > 0 and len(asset.pv_generation_kwh_by_slot) != slot_count:
                    raise ValueError(
                        f"Depot {depot_id} pv_generation_kwh_by_slot length ({len(asset.pv_generation_kwh_by_slot)}) "
                        f"must match price slot count ({slot_count})"
                    )
            if asset.pv_enabled and asset.capacity_factor_by_slot:
                if slot_count > 0 and len(asset.capacity_factor_by_slot) != slot_count:
                    raise ValueError(
                        f"Depot {depot_id} capacity_factor_by_slot length ({len(asset.capacity_factor_by_slot)}) "
                        f"must match price slot count ({slot_count})"
                    )
            bess_energy_kwh = float(asset.bess_energy_kwh or 0.0)
            bess_power_kw = float(asset.bess_power_kw or 0.0)
            bess_soc_values = (
                float(asset.bess_initial_soc_kwh or 0.0),
                float(asset.bess_soc_min_kwh or 0.0),
                float(asset.bess_soc_max_kwh or 0.0),
                float(asset.bess_terminal_soc_min_kwh or 0.0),
                float(asset.bess_terminal_soc_target_kwh or 0.0),
            )
            if (
                not math.isfinite(bess_energy_kwh)
                or not math.isfinite(bess_power_kw)
                or bess_energy_kwh < 0.0
                or bess_power_kw < 0.0
            ):
                raise ValueError(
                    f"Depot {depot_id} BESS energy and power must be finite and non-negative"
                )
            if not (0.0 < float(asset.bess_charge_efficiency) <= 1.0):
                raise ValueError(
                    f"Depot {depot_id} BESS charge efficiency must be within (0, 1]"
                )
            if not (0.0 < float(asset.bess_discharge_efficiency) <= 1.0):
                raise ValueError(
                    f"Depot {depot_id} BESS discharge efficiency must be within (0, 1]"
                )
            if any(not math.isfinite(value) or value < 0.0 for value in bess_soc_values):
                raise ValueError(
                    f"Depot {depot_id} BESS SOC values must be finite and non-negative"
                )
            if asset.bess_soc_max_kwh > bess_energy_kwh:
                raise ValueError(
                    f"Depot {depot_id} BESS maximum SOC exceeds energy capacity"
                )
            if asset.bess_enabled:
                if bess_energy_kwh <= 0.0:
                    raise ValueError(
                        f"Depot {depot_id} enabled BESS requires positive energy capacity"
                    )
                if asset.bess_soc_min_kwh > asset.bess_soc_max_kwh:
                    raise ValueError(f"Depot {depot_id} has invalid BESS bounds: min > max")
                if not (asset.bess_soc_min_kwh <= asset.bess_initial_soc_kwh <= asset.bess_soc_max_kwh):
                    raise ValueError(
                        f"Depot {depot_id} initial BESS SOC must be within [min, max]"
                    )
                terminal_floor = float(asset.bess_terminal_soc_min_kwh or 0.0)
                if not (0.0 <= terminal_floor <= asset.bess_soc_max_kwh):
                    raise ValueError(
                        f"Depot {depot_id} terminal BESS SOC floor must be "
                        "within [0, max]"
                    )
                target = float(asset.bess_terminal_soc_target_kwh or 0.0)
                terminal_policy = normalize_bess_terminal_policy(
                    asset.bess_terminal_soc_policy,
                    has_explicit_target=target > 0.0,
                )
                effective_terminal_floor = max(
                    terminal_floor,
                    float(asset.bess_soc_min_kwh or 0.0),
                )
                if (
                    terminal_policy == BESS_TERMINAL_POLICY_RETURN_TO_INITIAL
                    and float(asset.bess_initial_soc_kwh or 0.0)
                    < effective_terminal_floor
                ):
                    raise ValueError(
                        f"Depot {depot_id} cannot return to an initial BESS "
                        "SOC below the effective terminal floor"
                    )
                if terminal_policy == BESS_TERMINAL_POLICY_FIXED_TARGET and not (
                    effective_terminal_floor
                    <= target
                    <= float(asset.bess_soc_max_kwh or 0.0)
                ):
                    raise ValueError(
                        f"Depot {depot_id} fixed terminal BESS SOC target must "
                        "be within [effective terminal floor, max]"
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
