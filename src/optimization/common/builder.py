from __future__ import annotations

from collections import Counter, deque
from dataclasses import dataclass
import math
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from src.dispatch.dispatcher import DispatchGenerator
from src.dispatch.graph_builder import ConnectionGraphBuilder
from src.dispatch.models import (
    DeadheadRule,
    DispatchContext,
    DutyLeg,
    Trip,
    TurnaroundRule,
    VehicleDuty,
    VehicleProfile,
    hhmm_to_min,
)
from src.dispatch.route_band import trip_route_band_key
from src.optimization.common.cost_components import normalize_cost_component_flags
from src.route_family_runtime import (
    merge_deadhead_metrics,
    normalize_direction,
    normalize_variant_type,
)
from .soc_utils import normalize_soc_ratio_like, resolve_soc_kwh
from src.preprocess.tariff_loader import build_electricity_prices_from_tariff, load_tariff_csv
from src.objective_modes import (
    canonical_objective_weights_for_mode,
    effective_co2_price_per_kg,
    normalize_objective_mode,
)

from .problem import (
    AssignmentPlan,
    CanonicalOptimizationProblem,
    ChargerDefinition,
    DepotEnergyAsset,
    EnergyPriceSlot,
    OptimizationConfig,
    OptimizationObjectiveWeights,
    OptimizationScenario,
    ProblemDepot,
    ProblemRoute,
    ProblemTrip,
    ProblemVehicle,
    ProblemVehicleType,
    PVSlot,
    resolve_service_coverage_mode,
    service_coverage_allows_partial_service,
)
from .pv_area import (
    DEFAULT_PERFORMANCE_RATIO,
    estimate_depot_pv_from_area,
    positive_ratio_or_default,
    safe_optional_float,
)
from .vehicle_assignment import assign_duty_fragments_to_vehicles, merge_duty_vehicle_maps


@dataclass(frozen=True)
class ProblemBuilder:
    # Fallback vehicle count per type when vehicle_counts dict has no entry.
    # This path is only hit by legacy/test callers that omit explicit counts.
    default_vehicle_count_per_type: int = 1

    def build_from_scenario(
        self,
        scenario: Dict[str, Any],
        *,
        depot_id: Optional[str],
        service_id: str,
        config: Optional[OptimizationConfig] = None,
        planning_days: int = 1,
    ) -> CanonicalOptimizationProblem:
        context = self._build_dispatch_context_from_scenario(
            scenario,
            depot_id=depot_id,
            service_id=service_id,
        )
        scenario_vehicles = self._filter_scenario_vehicles_for_scope(
            scenario,
            depot_id=depot_id,
        )
        simulation_cfg = scenario.get("simulation_config") or {}
        disable_acquisition_cost = bool(
            simulation_cfg.get("disable_vehicle_acquisition_cost", False)
        )
        cost_component_flags = self._cost_component_flags_from_scenario(scenario)
        solver_cfg = ((scenario.get("scenario_overlay") or {}).get("solver_config") or {})
        timestep_min = int(
            simulation_cfg.get("timestep_min")
            or simulation_cfg.get("time_step_min")
            or solver_cfg.get("timestep_min")
            or solver_cfg.get("time_step_min")
            or 60
        )
        if timestep_min <= 0:
            timestep_min = 60
        operation_start_time = str(
            simulation_cfg.get("start_time")
            or solver_cfg.get("start_time")
            or "05:00"
        )
        operation_end_time = str(
            simulation_cfg.get("end_time")
            or solver_cfg.get("end_time")
            or "23:00"
        )
        chargers = self._build_chargers_from_scenario(scenario, depot_id)
        price_slots = self._build_price_slots_from_scenario(
            scenario,
            context,
            depot_id,
            timestep_min=timestep_min,
            start_time=operation_start_time,
            slots_per_day=(24 * 60) // max(timestep_min, 1)
            if max(int(planning_days or 1), 1) > 1
            else None,
        )
        pv_slots = self._build_pv_slots_from_scenario(scenario)
        vehicle_counts = self._vehicle_counts_from_scenario(scenario, depot_id)
        weights = self._objective_weights_from_scenario(scenario)
        baseline = self._build_baseline_plan_from_scenario(scenario, context)
        charging_cfg = ((scenario.get("scenario_overlay") or {}).get("charging_constraints") or {})
        cost_cfg = ((scenario.get("scenario_overlay") or {}).get("cost_coefficients") or {})
        solver_cfg = ((scenario.get("scenario_overlay") or {}).get("solver_config") or {})
        simulation_cfg = scenario.get("simulation_config") or {}
        dispatch_scope = scenario.get("dispatch_scope") or {}
        objective_mode = normalize_objective_mode(
            simulation_cfg.get("objective_mode")
            or solver_cfg.get("objective_mode")
            or "total_cost"
        )
        requested_fixed_route_band_mode = bool(
            simulation_cfg.get(
                "fixed_route_band_mode",
                solver_cfg.get("fixed_route_band_mode", False),
            )
        )
        allow_intra_route_swap_raw = dispatch_scope.get("allowIntraDepotRouteSwap")
        fixed_route_band_mode = bool(
            requested_fixed_route_band_mode
            or (
                allow_intra_route_swap_raw is not None
                and not bool(allow_intra_route_swap_raw)
            )
        )
        context.fixed_route_band_mode = fixed_route_band_mode
        milp_max_successors_per_trip = solver_cfg.get("milp_max_successors_per_trip")
        if milp_max_successors_per_trip is None:
            milp_max_successors_per_trip = simulation_cfg.get("milp_max_successors_per_trip")
        planning_days_effective = max(int(planning_days or 1), 1)
        allow_same_day_depot_cycles = bool(
            simulation_cfg.get(
                "allow_same_day_depot_cycles",
                solver_cfg.get("allow_same_day_depot_cycles", True),
            )
        )
        max_depot_cycles_per_vehicle_per_day = int(
            simulation_cfg.get(
                "max_depot_cycles_per_vehicle_per_day",
                solver_cfg.get("max_depot_cycles_per_vehicle_per_day", 3),
            )
            or 3
        )
        if max_depot_cycles_per_vehicle_per_day <= 0:
            max_depot_cycles_per_vehicle_per_day = 1
        daily_fragment_limit = (
            max_depot_cycles_per_vehicle_per_day if allow_same_day_depot_cycles else 1
        )
        default_fragment_limit = max(daily_fragment_limit, 1) * planning_days_effective
        max_start_fragments_per_vehicle = int(
            simulation_cfg.get(
                "max_start_fragments_per_vehicle",
                solver_cfg.get("max_start_fragments_per_vehicle", default_fragment_limit),
            )
            or default_fragment_limit
        )
        max_end_fragments_per_vehicle = int(
            simulation_cfg.get(
                "max_end_fragments_per_vehicle",
                solver_cfg.get("max_end_fragments_per_vehicle", default_fragment_limit),
            )
            or default_fragment_limit
        )
        service_coverage_mode = resolve_service_coverage_mode(
            simulation_cfg.get("service_coverage_mode", solver_cfg.get("service_coverage_mode")),
            simulation_cfg.get("allow_partial_service", solver_cfg.get("allow_partial_service")),
            default="strict",
        )
        allow_partial_service = service_coverage_allows_partial_service(
            service_coverage_mode
        )
        initial_soc_percent = self._safe_float(simulation_cfg.get("initial_soc_percent"))
        if initial_soc_percent is None:
            initial_soc_percent = self._safe_float(charging_cfg.get("initial_soc_percent"))
        initial_soc = self._safe_float(simulation_cfg.get("initial_soc"))
        if initial_soc is None:
            initial_soc = self._safe_float(charging_cfg.get("initial_soc"))
        final_soc_floor_percent = self._safe_float(
            simulation_cfg.get("final_soc_floor_percent")
            or charging_cfg.get("final_soc_floor_percent")
        )
        final_soc_target_percent = self._safe_float(
            simulation_cfg.get("final_soc_target_percent")
            or charging_cfg.get("final_soc_target_percent")
        )
        final_soc_target_tolerance_percent = self._safe_float(
            simulation_cfg.get("final_soc_target_tolerance_percent")
            or charging_cfg.get("final_soc_target_tolerance_percent")
        )
        initial_ice_fuel_percent = self._safe_float(
            simulation_cfg.get("initial_ice_fuel_percent")
        )
        min_ice_fuel_percent = self._safe_float(
            simulation_cfg.get("min_ice_fuel_percent")
        )
        max_ice_fuel_percent = self._safe_float(
            simulation_cfg.get("max_ice_fuel_percent")
        )
        default_ice_tank_capacity_l = self._safe_float(
            simulation_cfg.get("default_ice_tank_capacity_l")
        )
        deadhead_speed_kmh = self._safe_float(
            simulation_cfg.get("deadhead_speed_kmh")
        )
        charging_window_mode = str(
            simulation_cfg.get("charging_window_mode")
            or solver_cfg.get("charging_window_mode")
            or "timetable_layover"
        ).strip().lower()
        if charging_window_mode not in {"home_depot_proxy", "timetable_layover"}:
            charging_window_mode = "timetable_layover"
        home_depot_charge_pre_window_min = self._safe_float(
            simulation_cfg.get("home_depot_charge_pre_window_min")
        )
        if home_depot_charge_pre_window_min is None:
            home_depot_charge_pre_window_min = self._safe_float(
                solver_cfg.get("home_depot_charge_pre_window_min")
            )
        if home_depot_charge_pre_window_min is None:
            home_depot_charge_pre_window_min = float(timestep_min)
        home_depot_charge_post_window_min = self._safe_float(
            simulation_cfg.get("home_depot_charge_post_window_min")
        )
        if home_depot_charge_post_window_min is None:
            home_depot_charge_post_window_min = self._safe_float(
                solver_cfg.get("home_depot_charge_post_window_min")
            )
        if home_depot_charge_post_window_min is None:
            home_depot_charge_post_window_min = float(timestep_min)
        horizon_start_min = hhmm_to_min(operation_start_time)
        enable_contract_overage_penalty = simulation_cfg.get("enable_contract_overage_penalty")
        if enable_contract_overage_penalty is None:
            enable_contract_overage_penalty = solver_cfg.get("enable_contract_overage_penalty")
        if enable_contract_overage_penalty is None:
            enable_contract_overage_penalty = cost_cfg.get("enable_contract_overage_penalty")

        contract_overage_penalty_yen_per_kwh = self._safe_float(
            simulation_cfg.get("contract_overage_penalty_yen_per_kwh")
        )
        if contract_overage_penalty_yen_per_kwh is None:
            contract_overage_penalty_yen_per_kwh = self._safe_float(
                solver_cfg.get("contract_overage_penalty_yen_per_kwh")
            )
        if contract_overage_penalty_yen_per_kwh is None:
            contract_overage_penalty_yen_per_kwh = self._safe_float(
                cost_cfg.get("contract_overage_penalty_yen_per_kwh")
            )

        grid_to_bus_priority_penalty_yen_per_kwh = self._safe_float(
            simulation_cfg.get("grid_to_bus_priority_penalty_yen_per_kwh")
        )
        if grid_to_bus_priority_penalty_yen_per_kwh is None:
            grid_to_bus_priority_penalty_yen_per_kwh = self._safe_float(
                solver_cfg.get("grid_to_bus_priority_penalty_yen_per_kwh")
            )
        if grid_to_bus_priority_penalty_yen_per_kwh is None:
            grid_to_bus_priority_penalty_yen_per_kwh = self._safe_float(
                cost_cfg.get("grid_to_bus_priority_penalty_yen_per_kwh")
            )

        grid_to_bess_priority_penalty_yen_per_kwh = self._safe_float(
            simulation_cfg.get("grid_to_bess_priority_penalty_yen_per_kwh")
        )
        if grid_to_bess_priority_penalty_yen_per_kwh is None:
            grid_to_bess_priority_penalty_yen_per_kwh = self._safe_float(
                solver_cfg.get("grid_to_bess_priority_penalty_yen_per_kwh")
            )
        if grid_to_bess_priority_penalty_yen_per_kwh is None:
            grid_to_bess_priority_penalty_yen_per_kwh = self._safe_float(
                cost_cfg.get("grid_to_bess_priority_penalty_yen_per_kwh")
            )
        selected_depot_record = self._find_selected_depot_record(scenario, depot_id)
        depot_coordinates_by_id = self._depot_coordinates_by_id(scenario)
        depot_import_limit_kw = self._safe_float(
            charging_cfg.get("depot_power_limit_kw")
            or charging_cfg.get("depotPowerLimitKw")
            or cost_cfg.get("depot_power_limit_kw")
            or cost_cfg.get("depotPowerLimitKw")
        )
        demand_charge = float(cost_cfg.get("demand_charge_cost_per_kw") or 0.0)
        diesel_price = float(cost_cfg.get("diesel_price_per_l") or 0.0)
        co2_price_per_kg = effective_co2_price_per_kg(
            objective_mode,
            cost_cfg.get("co2_price_per_kg"),
        )
        ice_co2_kg_per_l = float(cost_cfg.get("ice_co2_kg_per_l") or 2.64)
        return self.build_from_dispatch(
            context,
            scenario_id=str((scenario.get("meta") or {}).get("id") or ""),
            scenario_metadata=scenario,
            config=config,
            vehicle_counts=vehicle_counts,
            chargers=chargers,
            price_slots=price_slots,
            pv_slots=pv_slots,
            objective_weights=weights,
            baseline_plan=baseline,
            depot_import_limit_kw=depot_import_limit_kw,
            objective_mode=objective_mode,
            diesel_price_yen_per_l=diesel_price,
            demand_charge_on_peak_yen_per_kw=demand_charge,
            demand_charge_off_peak_yen_per_kw=demand_charge,
            co2_price_per_kg=co2_price_per_kg,
            ice_co2_kg_per_l=ice_co2_kg_per_l,
            fixed_route_band_mode=fixed_route_band_mode,
            fixed_route_band_mode_requested=requested_fixed_route_band_mode,
            allow_intra_depot_route_swap=(
                bool(allow_intra_route_swap_raw)
                if allow_intra_route_swap_raw is not None
                else None
            ),
            milp_max_successors_per_trip=milp_max_successors_per_trip,
            planning_days=planning_days_effective,
            max_start_fragments_per_vehicle=max(1, max_start_fragments_per_vehicle),
            max_end_fragments_per_vehicle=max(1, max_end_fragments_per_vehicle),
            max_fragments_per_vehicle_per_day=max(1, daily_fragment_limit),
            allow_same_day_depot_cycles=allow_same_day_depot_cycles,
            horizon_start_min=horizon_start_min,
            max_depot_cycles_per_vehicle_per_day=max(1, max_depot_cycles_per_vehicle_per_day),
            allow_partial_service=allow_partial_service,
            service_coverage_mode=service_coverage_mode,
            initial_soc_percent=initial_soc_percent,
            final_soc_floor_percent=final_soc_floor_percent,
            final_soc_target_percent=final_soc_target_percent,
            final_soc_target_tolerance_percent=final_soc_target_tolerance_percent,
            initial_ice_fuel_percent=initial_ice_fuel_percent,
            min_ice_fuel_percent=min_ice_fuel_percent,
            max_ice_fuel_percent=max_ice_fuel_percent,
            default_ice_tank_capacity_l=default_ice_tank_capacity_l,
            deadhead_speed_kmh=deadhead_speed_kmh,
            charging_window_mode=charging_window_mode,
            home_depot_charge_pre_window_min=home_depot_charge_pre_window_min,
            home_depot_charge_post_window_min=home_depot_charge_post_window_min,
            enable_contract_overage_penalty=bool(enable_contract_overage_penalty)
            if enable_contract_overage_penalty is not None
            else True,
            contract_overage_penalty_yen_per_kwh=contract_overage_penalty_yen_per_kwh,
            grid_to_bus_priority_penalty_yen_per_kwh=grid_to_bus_priority_penalty_yen_per_kwh,
            grid_to_bess_priority_penalty_yen_per_kwh=grid_to_bess_priority_penalty_yen_per_kwh,
            selected_depot_record=selected_depot_record,
            depot_coordinates_by_id=depot_coordinates_by_id,
            canonical_depot_id=str(depot_id or "depot_default"),
            timestep_min=timestep_min,
            operation_start_time=operation_start_time,
            operation_end_time=operation_end_time,
            scenario_vehicles=scenario_vehicles,
            disable_vehicle_acquisition_cost=disable_acquisition_cost,
            cost_component_flags=cost_component_flags,
        )

    def build_from_dispatch(
        self,
        context: DispatchContext,
        *,
        scenario_id: str,
        scenario_metadata: Optional[Dict[str, Any]] = None,
        config: Optional[OptimizationConfig] = None,
        vehicle_counts: Optional[Dict[str, int]] = None,
        chargers: Sequence[ChargerDefinition] = (),
        price_slots: Sequence[EnergyPriceSlot] = (),
        pv_slots: Sequence[PVSlot] = (),
        objective_weights: Optional[OptimizationObjectiveWeights] = None,
        baseline_plan: Optional[AssignmentPlan] = None,
        depot_import_limit_kw: Optional[float] = None,
        objective_mode: str = "total_cost",
        diesel_price_yen_per_l: float = 0.0,
        demand_charge_on_peak_yen_per_kw: float = 0.0,
        demand_charge_off_peak_yen_per_kw: float = 0.0,
        co2_price_per_kg: float = 0.0,
        ice_co2_kg_per_l: float = 2.64,
        fixed_route_band_mode: bool = False,
        fixed_route_band_mode_requested: Optional[bool] = None,
        allow_intra_depot_route_swap: Optional[bool] = None,
        milp_max_successors_per_trip: Optional[int] = None,
        planning_days: int = 1,
        max_start_fragments_per_vehicle: int = 1,
        max_end_fragments_per_vehicle: int = 1,
        max_fragments_per_vehicle_per_day: int = 1,
        allow_same_day_depot_cycles: bool = True,
        horizon_start_min: int = 0,
        max_depot_cycles_per_vehicle_per_day: int = 3,
        allow_partial_service: bool = False,
        service_coverage_mode: Optional[str] = None,
        initial_soc_percent: Optional[float] = None,
        initial_soc: Optional[float] = None,
        final_soc_floor_percent: Optional[float] = None,
        final_soc_target_percent: Optional[float] = None,
        final_soc_target_tolerance_percent: Optional[float] = None,
        initial_ice_fuel_percent: Optional[float] = None,
        min_ice_fuel_percent: Optional[float] = None,
        max_ice_fuel_percent: Optional[float] = None,
        default_ice_tank_capacity_l: Optional[float] = None,
        deadhead_speed_kmh: Optional[float] = None,
        charging_window_mode: str = "timetable_layover",
        home_depot_charge_pre_window_min: Optional[float] = None,
        home_depot_charge_post_window_min: Optional[float] = None,
        enable_contract_overage_penalty: bool = True,
        contract_overage_penalty_yen_per_kwh: Optional[float] = None,
        grid_to_bus_priority_penalty_yen_per_kwh: Optional[float] = None,
        grid_to_bess_priority_penalty_yen_per_kwh: Optional[float] = None,
        selected_depot_record: Optional[Dict[str, Any]] = None,
        depot_coordinates_by_id: Optional[Dict[str, Dict[str, Optional[float]]]] = None,
        canonical_depot_id: str = "depot_default",
        timestep_min: int = 60,
        operation_start_time: Optional[str] = None,
        operation_end_time: Optional[str] = None,
        scenario_vehicles: Optional[Sequence[Dict[str, Any]]] = None,
        disable_vehicle_acquisition_cost: bool = False,
        enable_vehicle_cost: bool = True,
        enable_driver_cost: bool = True,
        enable_other_cost: bool = True,
        cost_component_flags: Optional[Mapping[str, Any]] = None,
    ) -> CanonicalOptimizationProblem:
        config = config or OptimizationConfig()
        vehicle_counts = vehicle_counts or {}
        timestep_min = max(int(timestep_min or 60), 1)
        context.horizon_start_min = int(horizon_start_min or 0)
        context.fixed_route_band_mode = bool(fixed_route_band_mode)
        if fixed_route_band_mode_requested is None:
            fixed_route_band_mode_requested = bool(fixed_route_band_mode)
        service_coverage_mode = resolve_service_coverage_mode(
            service_coverage_mode,
            allow_partial_service,
            default="strict",
        )
        allow_partial_service = service_coverage_allows_partial_service(
            service_coverage_mode
        )
        normalized_cost_component_flags = normalize_cost_component_flags(
            cost_component_flags,
            legacy_disable_vehicle_acquisition_cost=disable_vehicle_acquisition_cost,
            legacy_enable_vehicle_cost=enable_vehicle_cost,
            legacy_enable_driver_cost=enable_driver_cost,
            legacy_enable_other_cost=enable_other_cost,
        )
        if home_depot_charge_pre_window_min is None:
            home_depot_charge_pre_window_min = float(timestep_min)
        if home_depot_charge_post_window_min is None:
            home_depot_charge_post_window_min = float(timestep_min)
        normalized_start_time = self._normalize_hhmm(operation_start_time) or self._min_hhmm(context) or "05:00"
        normalized_end_time = self._normalize_hhmm(operation_end_time) or self._max_hhmm(context) or "23:00"
        canonical_depot_id = str(canonical_depot_id or "depot_default")
        bev_reference_capacity_kwh = self._reference_bev_capacity_kwh(context)
        final_soc_floor_ratio = self._normalize_percent_like_to_ratio(final_soc_floor_percent)
        trip_nodes_list: List[ProblemTrip] = []
        for trip in context.trips:
            energy_kwh = self._estimate_trip_energy(trip.distance_km, context)
            has_electric_vehicle = any(
                str(vt).upper() in {"BEV", "PHEV", "FCEV"}
                for vt in trip.allowed_vehicle_types
            )
            required_soc_departure_percent = None
            if has_electric_vehicle:
                required_soc_departure_percent = self._derive_required_soc_departure_percent(
                    trip_energy_kwh=energy_kwh,
                    bev_capacity_kwh=bev_reference_capacity_kwh,
                    final_soc_floor_ratio=final_soc_floor_ratio,
                )
            trip_nodes_list.append(
                ProblemTrip(
                    trip_id=trip.trip_id,
                    route_id=trip.route_id,
                    origin=trip.origin,
                    destination=trip.destination,
                    departure_min=trip.departure_min,
                    arrival_min=trip.arrival_min,
                    distance_km=trip.distance_km,
                    allowed_vehicle_types=trip.allowed_vehicle_types,
                    energy_kwh=energy_kwh,
                    fuel_l=self._estimate_trip_fuel(trip.distance_km, context),
                    service_id=context.service_date,
                    required_soc_departure_percent=required_soc_departure_percent,
                    route_family_code=str(getattr(trip, "route_family_code", "") or ""),
                    direction=str(getattr(trip, "direction", "") or ""),
                    route_variant_type=str(getattr(trip, "route_variant_type", "") or ""),
                )
            )

        # ===== Multi-day trip replication =====
        # When planning_days > 1, replicate base day trips for each additional day
        planning_days = max(1, planning_days)
        if planning_days > 1:
            base_trip_nodes = list(trip_nodes_list)
            day_offset_min = 24 * 60  # 1440 minutes per day
            for day_idx in range(1, planning_days):
                offset = day_idx * day_offset_min
                for base_trip in base_trip_nodes:
                    replicated_trip = ProblemTrip(
                        trip_id=f"d{day_idx}_{base_trip.trip_id}",
                        route_id=base_trip.route_id,
                        origin=base_trip.origin,
                        destination=base_trip.destination,
                        departure_min=base_trip.departure_min + offset,
                        arrival_min=base_trip.arrival_min + offset,
                        distance_km=base_trip.distance_km,
                        allowed_vehicle_types=base_trip.allowed_vehicle_types,
                        energy_kwh=base_trip.energy_kwh,
                        fuel_l=base_trip.fuel_l,
                        service_id=f"{base_trip.service_id}_d{day_idx}" if base_trip.service_id else f"d{day_idx}",
                    required_soc_departure_percent=base_trip.required_soc_departure_percent,
                    route_family_code=base_trip.route_family_code,
                    direction=base_trip.direction,
                    route_variant_type=base_trip.route_variant_type,
                )
                    trip_nodes_list.append(replicated_trip)
        
        trip_nodes = tuple(trip_nodes_list)
        route_nodes = self._build_routes(trip_nodes)
        vehicle_types = self._build_vehicle_types(context.vehicle_profiles)
        vehicles = tuple(
            self._build_vehicles_from_records(
                scenario_vehicles or (),
                context.vehicle_profiles,
                default_home_depot_id=canonical_depot_id,
                disable_vehicle_acquisition_cost=disable_vehicle_acquisition_cost,
                initial_soc_percent=initial_soc_percent,
                initial_soc=initial_soc,
                final_soc_floor_percent=final_soc_floor_percent,
                initial_ice_fuel_percent=initial_ice_fuel_percent,
                min_ice_fuel_percent=min_ice_fuel_percent,
                max_ice_fuel_percent=max_ice_fuel_percent,
            )
        )
        if not vehicles:
            vehicles = tuple(
                self._build_vehicles(
                    context.vehicle_profiles,
                    vehicle_counts,
                    default_home_depot_id=canonical_depot_id,
                )
            )
        available_vehicles = tuple(
            vehicle for vehicle in vehicles if bool(getattr(vehicle, "available", True))
        )
        unavailable_vehicles = tuple(
            vehicle for vehicle in vehicles if not bool(getattr(vehicle, "available", True))
        )
        inferred_import_limit = depot_import_limit_kw
        if inferred_import_limit is None:
            charger_capacity = sum(charger.power_kw * max(charger.simultaneous_ports, 1) for charger in chargers)
            inferred_import_limit = charger_capacity if charger_capacity > 0 else 1000.0

        depots = (
            ProblemDepot(
                depot_id=canonical_depot_id,
                name=str((selected_depot_record or {}).get("name") or "Default Depot"),
                charger_ids=tuple(charger.charger_id for charger in chargers),
                import_limit_kw=float(inferred_import_limit),
                latitude=self._safe_float((selected_depot_record or {}).get("lat")),
                longitude=self._safe_float((selected_depot_record or {}).get("lon")),
            ),
        )
        slots_per_day: Optional[int] = None
        if planning_days > 1:
            slots_per_day = max(1, (24 * 60) // max(timestep_min, 1))
        elif operation_start_time and operation_end_time:
            duration_min = self._daily_window_duration_min(normalized_start_time, normalized_end_time)
            slots_per_day = max(1, int(math.ceil(duration_min / float(max(timestep_min, 1)))))

        base_time_slots = list(
            self._build_time_slot_prices(
                context,
                price_slots,
                timestep_min=timestep_min,
                start_time=normalized_start_time,
                slots_per_day=slots_per_day,
            )
        )
        
        # ===== Multi-day price slot tiling =====
        # When planning_days > 1, tile price slots for each additional day
        if planning_days > 1:
            slots_per_day = len(base_time_slots)
            all_time_slots: List[EnergyPriceSlot] = list(base_time_slots)
            for day_idx in range(1, planning_days):
                for base_slot in base_time_slots:
                    all_time_slots.append(
                        EnergyPriceSlot(
                            slot_index=day_idx * slots_per_day + base_slot.slot_index,
                            grid_buy_yen_per_kwh=base_slot.grid_buy_yen_per_kwh,
                            grid_sell_yen_per_kwh=base_slot.grid_sell_yen_per_kwh,
                            co2_factor=base_slot.co2_factor,
                        )
                    )
            time_slots = tuple(all_time_slots)
        else:
            time_slots = tuple(base_time_slots)
        
        pv_series = tuple(self._build_pv_slots(time_slots, pv_slots, planning_days=planning_days))
        depot_energy_assets = self._build_depot_energy_assets_from_scenario(
            scenario_id=scenario_id,
            time_slots=time_slots,
            pv_slots=pv_series,
            depots=depots,
            metadata_source=scenario_metadata or {},
            timestep_min=timestep_min,
            canonical_depot_id=canonical_depot_id,
        )
        feasible_connections: Dict[str, Tuple[str, ...]] = {}
        for vehicle_type in context.vehicle_profiles:
            graph = self._build_graph(context, vehicle_type)
            for trip_id, successors in graph.items():
                merged = set(feasible_connections.get(trip_id, ()))
                merged.update(successors)
                feasible_connections[trip_id] = tuple(sorted(merged))
        if planning_days > 1:
            base_feasible_connections = dict(feasible_connections)
            for day_idx in range(1, planning_days):
                prefix = f"d{day_idx}_"
                for trip_id, successors in base_feasible_connections.items():
                    feasible_connections[f"{prefix}{trip_id}"] = tuple(
                        f"{prefix}{succ_trip_id}" for succ_trip_id in successors
                    )

        max_fragments = max(
            int(max_start_fragments_per_vehicle or 1),
            int(max_end_fragments_per_vehicle or 1),
            1,
        )
        all_trip_ids = {trip.trip_id for trip in trip_nodes}
        if baseline_plan is not None:
            baseline = self._materialize_baseline_plan(
                baseline_plan,
                available_vehicles,
                max_fragments_per_vehicle=max_fragments,
                max_fragments_per_vehicle_per_day=max(1, int(max_fragments_per_vehicle_per_day or 1)),
                allow_same_day_depot_cycles=bool(allow_same_day_depot_cycles),
                horizon_start_min=int(horizon_start_min or 0),
                all_trip_ids=all_trip_ids,
                dispatch_context=context,
                fixed_route_band_mode=bool(fixed_route_band_mode),
            )
        else:
            baseline = self._build_baseline_plan(
                context,
                vehicles=available_vehicles,
                max_fragments_per_vehicle=max_fragments,
                max_fragments_per_vehicle_per_day=max(1, int(max_fragments_per_vehicle_per_day or 1)),
                allow_same_day_depot_cycles=bool(allow_same_day_depot_cycles),
                horizon_start_min=int(horizon_start_min or 0),
                all_trip_ids=all_trip_ids,
                feasible_connections=feasible_connections,
                fixed_route_band_mode=bool(fixed_route_band_mode),
            )
        return CanonicalOptimizationProblem(
            scenario=OptimizationScenario(
                scenario_id=scenario_id,
                horizon_start=normalized_start_time,
                horizon_end=normalized_end_time,
                timestep_min=timestep_min,
                planning_days=planning_days,
                objective_mode=normalize_objective_mode(objective_mode),
                diesel_price_yen_per_l=float(diesel_price_yen_per_l),
                demand_charge_on_peak_yen_per_kw=float(demand_charge_on_peak_yen_per_kw),
                demand_charge_off_peak_yen_per_kw=float(demand_charge_off_peak_yen_per_kw),
                co2_price_per_kg=float(
                    co2_price_per_kg
                    if normalized_cost_component_flags.get("co2_cost", True)
                    else 0.0
                ),
                ice_co2_kg_per_l=float(ice_co2_kg_per_l),
                allow_same_day_depot_cycles=bool(allow_same_day_depot_cycles),
                max_depot_cycles_per_vehicle_per_day=max(1, int(max_depot_cycles_per_vehicle_per_day or 1)),
                service_coverage_mode=service_coverage_mode,
            ),
            dispatch_context=context,
            trips=trip_nodes,
            routes=route_nodes,
            depots=depots,
            vehicle_types=vehicle_types,
            vehicles=vehicles,
            chargers=tuple(chargers),
            price_slots=time_slots,
            pv_slots=pv_series,
            depot_energy_assets=depot_energy_assets,
            feasible_connections=feasible_connections,
            objective_weights=objective_weights or OptimizationObjectiveWeights(),
            baseline_plan=baseline,
            metadata={
                "service_date": context.service_date,
                "config_mode": config.mode.value,
                "trip_count": len(trip_nodes),
                "route_count": len(route_nodes),
                "charger_count": len(chargers),
                "baseline_plan_source": (baseline.metadata or {}).get("source", "dispatch_greedy_baseline"),
                "objective_mode": normalize_objective_mode(objective_mode),
                "fixed_route_band_mode": bool(fixed_route_band_mode),
                "fixed_route_band_mode_requested": bool(fixed_route_band_mode_requested),
                "allow_intra_depot_route_swap": (
                    bool(allow_intra_depot_route_swap)
                    if allow_intra_depot_route_swap is not None
                    else None
                ),
                "fixed_route_band_mode_forced_by_scope_swap_lock": bool(
                    not bool(fixed_route_band_mode_requested)
                    and allow_intra_depot_route_swap is not None
                    and not bool(allow_intra_depot_route_swap)
                ),
                "service_coverage_mode": service_coverage_mode,
                "milp_max_successors_per_trip": milp_max_successors_per_trip,
                "planning_days": planning_days,
                "operation_start_time": normalized_start_time,
                "operation_end_time": normalized_end_time,
                "horizon_start_min": int(horizon_start_min or 0),
                "same_day_depot_cycles_enabled": bool(allow_same_day_depot_cycles),
                "allow_same_day_depot_cycles": bool(allow_same_day_depot_cycles),
                "max_depot_cycles_per_vehicle_per_day": max(1, int(max_depot_cycles_per_vehicle_per_day or 1)),
                "daily_fragment_limit": max(1, int(max_fragments_per_vehicle_per_day or 1)),
                "max_start_fragments_per_vehicle": int(max(1, max_start_fragments_per_vehicle)),
                "max_end_fragments_per_vehicle": int(max(1, max_end_fragments_per_vehicle)),
                "available_vehicle_count_total": len(available_vehicles),
                "unavailable_vehicle_count_total": len(unavailable_vehicles),
                "available_vehicle_ids": tuple(
                    sorted(str(vehicle.vehicle_id) for vehicle in available_vehicles)
                ),
                "unavailable_vehicle_ids": tuple(
                    sorted(str(vehicle.vehicle_id) for vehicle in unavailable_vehicles)
                ),
                "allow_partial_service": bool(allow_partial_service),
                "initial_soc_percent": initial_soc_percent,
                "initial_soc": initial_soc,
                "final_soc_floor_percent": final_soc_floor_percent,
                "final_soc_target_percent": final_soc_target_percent,
                "final_soc_target_tolerance_percent": final_soc_target_tolerance_percent,
                "required_soc_departure_unit": "percent_0_100",
                "initial_ice_fuel_percent": initial_ice_fuel_percent,
                "min_ice_fuel_percent": min_ice_fuel_percent,
                "max_ice_fuel_percent": max_ice_fuel_percent,
                "default_ice_tank_capacity_l": default_ice_tank_capacity_l,
                "deadhead_speed_kmh": deadhead_speed_kmh,
                "charging_window_mode": str(charging_window_mode or "timetable_layover").strip().lower(),
                "home_depot_charge_pre_window_min": float(home_depot_charge_pre_window_min or 0.0),
                "home_depot_charge_post_window_min": float(home_depot_charge_post_window_min or 0.0),
                "enable_contract_overage_penalty": bool(enable_contract_overage_penalty)
                and bool(normalized_cost_component_flags.get("contract_overage_penalty", True)),
                "contract_overage_penalty_yen_per_kwh": (
                    contract_overage_penalty_yen_per_kwh
                    if normalized_cost_component_flags.get("contract_overage_penalty", True)
                    else 0.0
                ),
                "grid_to_bus_priority_penalty_yen_per_kwh": (
                    grid_to_bus_priority_penalty_yen_per_kwh
                    if normalized_cost_component_flags.get("grid_to_bus_priority_penalty", True)
                    else 0.0
                ),
                "grid_to_bess_priority_penalty_yen_per_kwh": (
                    grid_to_bess_priority_penalty_yen_per_kwh
                    if normalized_cost_component_flags.get("grid_to_bess_priority_penalty", True)
                    else 0.0
                ),
                "charge_session_start_penalty_yen": (
                    2.0 if normalized_cost_component_flags.get("charge_session_start_penalty", True) else 0.0
                ),
                "slot_concurrency_penalty_yen": (
                    1.0 if normalized_cost_component_flags.get("slot_concurrency_penalty", True) else 0.0
                ),
                "early_charge_penalty_yen_per_kwh": (
                    0.5 if normalized_cost_component_flags.get("early_charge_penalty", True) else 0.0
                ),
                "charge_to_upper_buffer_penalty_yen_per_kwh": (
                    0.2 if normalized_cost_component_flags.get("soc_upper_buffer_penalty", True) else 0.0
                ),
                "final_soc_target_penalty_per_kwh": (
                    50.0 if normalized_cost_component_flags.get("final_soc_target_penalty", True) else 0.0
                ),
                "driver_fragment_start_cost_yen": (
                    0.0 if not normalized_cost_component_flags.get("driver_cost", True) else None
                ),
                "cost_component_flags": dict(normalized_cost_component_flags),
                "depot_coordinates_by_id": dict(depot_coordinates_by_id or {}),
            },
        )

    def _find_selected_depot_record(
        self,
        scenario: Dict[str, Any],
        depot_id: Optional[str],
    ) -> Optional[Dict[str, Any]]:
        selected_id = str(depot_id or "").strip()
        depots = [item for item in (scenario.get("depots") or []) if isinstance(item, dict)]
        if not depots:
            return None
        if selected_id:
            for depot in depots:
                candidate = str(depot.get("id") or depot.get("depotId") or "").strip()
                if candidate == selected_id:
                    return dict(depot)
        return dict(depots[0])

    def _depot_coordinates_by_id(
        self,
        scenario: Dict[str, Any],
    ) -> Dict[str, Dict[str, Optional[float]]]:
        out: Dict[str, Dict[str, Optional[float]]] = {}
        for depot in scenario.get("depots") or []:
            if not isinstance(depot, dict):
                continue
            depot_id = str(depot.get("id") or depot.get("depotId") or "").strip()
            if not depot_id:
                continue
            out[depot_id] = {
                "lat": self._safe_float(depot.get("lat")),
                "lon": self._safe_float(depot.get("lon")),
            }
        return out

    def _build_depot_energy_assets_from_scenario(
        self,
        *,
        scenario_id: str,
        time_slots: Sequence[EnergyPriceSlot],
        pv_slots: Sequence[PVSlot],
        depots: Sequence[ProblemDepot],
        metadata_source: Dict[str, Any],
        timestep_min: int,
        canonical_depot_id: str,
    ) -> Dict[str, DepotEnergyAsset]:
        del scenario_id
        assets: Dict[str, DepotEnergyAsset] = {}
        overlay = (metadata_source.get("scenario_overlay") or {}) if isinstance(metadata_source, dict) else {}
        sim_cfg = metadata_source.get("simulation_config") or {} if isinstance(metadata_source, dict) else {}
        depot_assets_raw = list(sim_cfg.get("depot_energy_assets") or [])
        if isinstance(overlay, dict):
            depot_assets_raw.extend(list((overlay.get("depot_energy_assets") or [])))

        slot_count = len(time_slots)
        slot_h = max(float(timestep_min) / 60.0, 1.0e-9)
        has_explicit_pv_profiles = bool(
            metadata_source.get("pv_profiles") if isinstance(metadata_source, Mapping) else False
        )
        pv_kwh_by_slot = [0.0] * slot_count
        for pv in pv_slots:
            if 0 <= int(pv.slot_index) < slot_count:
                pv_kwh_by_slot[int(pv.slot_index)] = max(float(pv.pv_available_kw or 0.0), 0.0) * slot_h

        by_depot_raw: Dict[str, Dict[str, Any]] = {}
        for item in depot_assets_raw:
            if not isinstance(item, dict):
                continue
            depot_id = str(item.get("depot_id") or item.get("depotId") or "depot_default")
            by_depot_raw[depot_id] = dict(item)

        depot_area_by_id = self._depot_area_by_id(metadata_source)

        for depot in depots:
            raw = by_depot_raw.get(depot.depot_id, {})
            if not raw and len(depots) == 1:
                raw = by_depot_raw.get("depot_default") or by_depot_raw.get(canonical_depot_id) or {}
            depot_area_m2 = (
                raw.get("depot_area_m2")
                if "depot_area_m2" in raw
                else raw.get("depotAreaM2", depot_area_by_id.get(depot.depot_id))
            )
            usable_area_ratio = raw.get("usable_area_ratio", raw.get("usableAreaRatio"))
            panel_power_density_kw_m2 = raw.get(
                "panel_power_density_kw_m2",
                raw.get("panelPowerDensityKwM2"),
            )
            estimate = estimate_depot_pv_from_area(
                depot_area_m2,
                usable_area_ratio=usable_area_ratio,
                panel_power_density_kw_m2=panel_power_density_kw_m2,
            )
            performance_ratio = positive_ratio_or_default(
                raw.get("performance_ratio", raw.get("performanceRatio")),
                DEFAULT_PERFORMANCE_RATIO,
            )
            capacity_factor_series = self._align_factor_series_to_slot_count(
                self._capacity_factor_series_for_depot_asset(
                    raw,
                    fallback_generation_kwh_by_slot=pv_kwh_by_slot if has_explicit_pv_profiles else [],
                    fallback_slot_h=slot_h,
                ),
                slot_count,
            )
            pv_enabled = estimate.depot_area_m2 is not None and estimate.capacity_kw > 0.0
            if pv_enabled:
                pv_series = tuple(
                    round(estimate.capacity_kw * max(float(factor or 0.0), 0.0) * slot_h, 6)
                    for factor in capacity_factor_series
                )
            else:
                capacity_factor_series = tuple(0.0 for _ in range(slot_count))
                pv_series = tuple(0.0 for _ in range(slot_count))
            asset = DepotEnergyAsset(
                depot_id=depot.depot_id,
                pv_enabled=pv_enabled,
                pv_generation_kwh_by_slot=pv_series,
                capacity_factor_by_slot=capacity_factor_series,
                pv_case_id=str(raw.get("pv_case_id") or "default"),
                pv_capex_jpy_per_kw=float(raw.get("pv_capex_jpy_per_kw") or 0.0),
                pv_om_jpy_per_kw_year=float(raw.get("pv_om_jpy_per_kw_year") or 0.0),
                pv_life_years=int(raw.get("pv_life_years") or 25),
                pv_capacity_kw=round(estimate.capacity_kw, 6) if pv_enabled else 0.0,
                depot_area_m2=estimate.depot_area_m2,
                pv_installable_area_m2=round(estimate.installable_area_m2, 6),
                usable_area_ratio=estimate.usable_area_ratio,
                panel_power_density_kw_m2=estimate.panel_power_density_kw_m2,
                performance_ratio=performance_ratio,
                bess_enabled=bool(raw.get("bess_enabled", False)),
                bess_energy_kwh=float(raw.get("bess_energy_kwh") or 0.0),
                bess_power_kw=float(raw.get("bess_power_kw") or 0.0),
                bess_initial_soc_kwh=float(raw.get("bess_initial_soc_kwh") or 0.0),
                bess_soc_min_kwh=float(raw.get("bess_soc_min_kwh") or 0.0),
                bess_soc_max_kwh=float(raw.get("bess_soc_max_kwh") or 0.0),
                bess_charge_efficiency=float(raw.get("bess_charge_efficiency") or 0.95),
                bess_discharge_efficiency=float(raw.get("bess_discharge_efficiency") or 0.95),
                bess_cycle_cost_yen_per_kwh=float(raw.get("bess_cycle_cost_yen_per_kwh") or 0.0),
                bess_capex_jpy_per_kwh=float(raw.get("bess_capex_jpy_per_kwh") or 0.0),
                bess_om_jpy_per_kwh_year=float(raw.get("bess_om_jpy_per_kwh_year") or 0.0),
                bess_life_years=int(raw.get("bess_life_years") or 15),
                allow_grid_to_bess=bool(raw.get("allow_grid_to_bess", False)),
                grid_to_bess_price_mode=str(raw.get("grid_to_bess_price_mode") or "tou"),
                grid_to_bess_price_threshold_yen_per_kwh=float(
                    raw.get("grid_to_bess_price_threshold_yen_per_kwh") or 0.0
                ),
                grid_to_bess_allowed_slot_indices=tuple(
                    int(v)
                    for v in (raw.get("grid_to_bess_allowed_slot_indices") or [])
                    if str(v).strip() != ""
                ),
                bess_priority_mode=str(raw.get("bess_priority_mode") or "cost_driven"),
                bess_terminal_soc_min_kwh=float(raw.get("bess_terminal_soc_min_kwh") or 0.0),
                provisional_energy_cost_yen_per_kwh=float(raw.get("provisional_energy_cost_yen_per_kwh") or 0.0),
            )
            assets[depot.depot_id] = asset
        return assets

    def _depot_area_by_id(self, metadata_source: Mapping[str, Any]) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        if not isinstance(metadata_source, Mapping):
            return out
        for depot in metadata_source.get("depots") or []:
            if not isinstance(depot, Mapping):
                continue
            depot_id = str(depot.get("id") or depot.get("depot_id") or depot.get("depotId") or "").strip()
            if not depot_id:
                continue
            if "depot_area_m2" in depot:
                out[depot_id] = depot.get("depot_area_m2")
            elif "depotAreaM2" in depot:
                out[depot_id] = depot.get("depotAreaM2")
            elif "areaM2" in depot:
                out[depot_id] = depot.get("areaM2")
        return out

    def _capacity_factor_series_for_depot_asset(
        self,
        raw: Mapping[str, Any],
        *,
        fallback_generation_kwh_by_slot: Sequence[Any],
        fallback_slot_h: float,
    ) -> Sequence[Any]:
        if raw:
            factor_rows = self._flatten_capacity_factor_rows(
                raw.get("pv_capacity_factor_by_date") or raw.get("pvCapacityFactorByDate") or []
            )
            if factor_rows:
                return factor_rows
            direct_factors = raw.get("capacity_factor_by_slot") or raw.get("capacityFactorBySlot")
            if direct_factors:
                return direct_factors
            generated_by_date = self._capacity_factor_from_generation_rows(
                raw,
                raw.get("pv_generation_kwh_by_date") or raw.get("pvGenerationKwhByDate") or [],
                fallback_slot_h=fallback_slot_h,
            )
            if generated_by_date:
                return generated_by_date
            direct_generation = raw.get("pv_generation_kwh_by_slot") or raw.get("pvGenerationKwhBySlot")
            if direct_generation:
                return self._capacity_factor_from_generation_series(
                    raw,
                    direct_generation,
                    slot_h=fallback_slot_h,
                )
        return self._capacity_factor_from_generation_series(
            raw,
            fallback_generation_kwh_by_slot,
            slot_h=fallback_slot_h,
        )

    def _flatten_capacity_factor_rows(self, rows: Sequence[Any]) -> list[float]:
        combined: list[float] = []
        for item in rows:
            if not isinstance(item, Mapping):
                continue
            for value in item.get("capacity_factor_by_slot") or item.get("capacityFactorBySlot") or []:
                try:
                    combined.append(max(0.0, min(float(value or 0.0), 1.0)))
                except (TypeError, ValueError):
                    combined.append(0.0)
        return combined

    def _legacy_pv_capacity_kw(self, raw: Mapping[str, Any]) -> float:
        parsed = safe_optional_float(
            raw.get("legacy_pv_capacity_kw")
            or raw.get("legacyPvCapacityKw")
            or raw.get("pv_capacity_kw")
            or raw.get("pvCapacityKw")
        )
        return max(float(parsed or 0.0), 0.0)

    def _capacity_factor_from_generation_rows(
        self,
        raw: Mapping[str, Any],
        rows: Sequence[Any],
        *,
        fallback_slot_h: float,
    ) -> list[float]:
        values: list[tuple[float, float]] = []
        for item in rows:
            if not isinstance(item, Mapping):
                continue
            try:
                slot_minutes = max(int(item.get("slot_minutes") or item.get("slotMinutes") or 60), 1)
            except (TypeError, ValueError):
                slot_minutes = 60
            duration_h = max(slot_minutes / 60.0, 1.0e-9)
            for value in item.get("pv_generation_kwh_by_slot") or item.get("pvGenerationKwhBySlot") or []:
                try:
                    values.append((max(float(value or 0.0), 0.0), duration_h))
                except (TypeError, ValueError):
                    values.append((0.0, duration_h))
        if not values:
            return []
        legacy_capacity_kw = self._legacy_pv_capacity_kw(raw)
        if legacy_capacity_kw <= 0.0:
            legacy_capacity_kw = max((energy / max(duration_h, 1.0e-9)) for energy, duration_h in values)
        if legacy_capacity_kw <= 0.0:
            return [0.0 for _energy, _duration_h in values]
        return [
            max(0.0, min(energy / (legacy_capacity_kw * max(duration_h, 1.0e-9)), 1.0))
            for energy, duration_h in values
        ]

    def _capacity_factor_from_generation_series(
        self,
        raw: Mapping[str, Any],
        values: Sequence[Any],
        *,
        slot_h: float,
    ) -> list[float]:
        energies: list[float] = []
        for value in values:
            try:
                energies.append(max(float(value or 0.0), 0.0))
            except (TypeError, ValueError):
                energies.append(0.0)
        if not energies:
            return []
        legacy_capacity_kw = self._legacy_pv_capacity_kw(raw)
        if legacy_capacity_kw <= 0.0:
            legacy_capacity_kw = max(energy / max(slot_h, 1.0e-9) for energy in energies)
        if legacy_capacity_kw <= 0.0:
            return [0.0 for _value in energies]
        denominator = legacy_capacity_kw * max(slot_h, 1.0e-9)
        return [max(0.0, min(energy / denominator, 1.0)) for energy in energies]

    def _align_factor_series_to_slot_count(
        self,
        values: Sequence[Any],
        slot_count: int,
    ) -> Tuple[float, ...]:
        series: list[float] = []
        for value in values:
            try:
                series.append(max(0.0, min(float(value or 0.0), 1.0)))
            except (TypeError, ValueError):
                series.append(0.0)
        if slot_count <= 0:
            return tuple()
        if not series:
            return tuple(0.0 for _ in range(slot_count))
        if len(series) == slot_count:
            return tuple(series)
        if slot_count % len(series) == 0:
            expand_factor = slot_count // len(series)
            aligned: List[float] = []
            for value in series:
                aligned.extend([value] * expand_factor)
            return tuple(aligned)
        if len(series) % slot_count == 0:
            compress_factor = len(series) // slot_count
            return tuple(
                sum(series[idx * compress_factor : (idx + 1) * compress_factor]) / float(compress_factor)
                for idx in range(slot_count)
            )
        aligned = [0.0] * slot_count
        scale = len(series) / float(slot_count)
        for slot_idx in range(slot_count):
            start = slot_idx * scale
            end = (slot_idx + 1) * scale
            left = int(start)
            right = int(math.ceil(end))
            total_weight = 0.0
            weighted_value = 0.0
            for raw_idx in range(left, min(right, len(series))):
                overlap_start = max(start, raw_idx)
                overlap_end = min(end, raw_idx + 1)
                weight = max(0.0, overlap_end - overlap_start)
                weighted_value += series[raw_idx] * weight
                total_weight += weight
            aligned[slot_idx] = weighted_value / total_weight if total_weight > 0.0 else 0.0
        return tuple(aligned)

    def _pv_generation_series_for_depot_asset(
        self,
        raw: Mapping[str, Any],
        *,
        fallback: Sequence[Any],
    ) -> Sequence[Any]:
        if not raw:
            return fallback
        generated_from_factors = self._pv_generation_from_capacity_factor_rows(raw)
        if generated_from_factors:
            return generated_from_factors
        generated_by_date = self._flatten_pv_generation_rows(
            raw.get("pv_generation_kwh_by_date") or raw.get("pvGenerationKwhByDate") or []
        )
        if generated_by_date:
            return generated_by_date
        return raw.get("pv_generation_kwh_by_slot") or fallback

    def _flatten_pv_generation_rows(self, rows: Sequence[Any]) -> list[float]:
        combined: list[float] = []
        for item in rows:
            if not isinstance(item, Mapping):
                continue
            for value in item.get("pv_generation_kwh_by_slot") or item.get("pvGenerationKwhBySlot") or []:
                try:
                    combined.append(float(value or 0.0))
                except (TypeError, ValueError):
                    combined.append(0.0)
        return combined

    def _pv_generation_from_capacity_factor_rows(self, raw: Mapping[str, Any]) -> list[float]:
        rows = raw.get("pv_capacity_factor_by_date") or raw.get("pvCapacityFactorByDate") or []
        if not isinstance(rows, Sequence):
            return []
        try:
            capacity_kw = float(raw.get("pv_capacity_kw") or raw.get("pvCapacityKw") or 0.0)
        except (TypeError, ValueError):
            capacity_kw = 0.0
        combined: list[float] = []
        for item in rows:
            if not isinstance(item, Mapping):
                continue
            try:
                slot_minutes = max(int(item.get("slot_minutes") or item.get("slotMinutes") or 60), 1)
            except (TypeError, ValueError):
                slot_minutes = 60
            duration_h = max(slot_minutes / 60.0, 1.0e-9)
            for value in item.get("capacity_factor_by_slot") or item.get("capacityFactorBySlot") or []:
                try:
                    factor = max(float(value or 0.0), 0.0)
                except (TypeError, ValueError):
                    factor = 0.0
                combined.append(capacity_kw * factor * duration_h)
        return combined

    def _align_energy_series_to_slot_count(
        self,
        values: Sequence[Any],
        slot_count: int,
    ) -> Tuple[float, ...]:
        series = [float(v or 0.0) for v in values]
        if slot_count <= 0:
            return tuple()
        if not series:
            return tuple(0.0 for _ in range(slot_count))
        if len(series) == slot_count:
            return tuple(series)
        if slot_count % len(series) == 0:
            expand_factor = slot_count // len(series)
            aligned: List[float] = []
            for value in series:
                distributed = value / float(expand_factor)
                aligned.extend([distributed] * expand_factor)
            return tuple(aligned)
        if len(series) % slot_count == 0:
            compress_factor = len(series) // slot_count
            return tuple(
                sum(series[idx * compress_factor : (idx + 1) * compress_factor])
                for idx in range(slot_count)
            )
        aligned = [0.0] * slot_count
        scale = len(series) / float(slot_count)
        for slot_idx in range(slot_count):
            start = slot_idx * scale
            end = (slot_idx + 1) * scale
            left = int(start)
            right = int(math.ceil(end))
            energy = 0.0
            for raw_idx in range(left, min(right, len(series))):
                overlap_start = max(start, raw_idx)
                overlap_end = min(end, raw_idx + 1)
                overlap = max(0.0, overlap_end - overlap_start)
                if overlap > 0.0:
                    energy += series[raw_idx] * overlap
            aligned[slot_idx] = energy
        return tuple(aligned)

    def _build_graph(
        self,
        context: DispatchContext,
        vehicle_type: str,
    ) -> Dict[str, List[str]]:
        return ConnectionGraphBuilder().build(context, vehicle_type)

    def _estimate_trip_distance_km(
        self,
        row: Dict[str, Any],
        route_like: Dict[str, Any],
    ) -> float:
        explicit = self._safe_float(
            row.get("distance_km")
            or row.get("distanceKm")
            or route_like.get("distanceKm")
            or route_like.get("distance_km")
        )
        if explicit is not None and explicit > 0.0:
            return explicit

        origin_lat = self._safe_float(row.get("origin_lat") or row.get("originLat"))
        origin_lon = self._safe_float(row.get("origin_lon") or row.get("originLon"))
        destination_lat = self._safe_float(row.get("destination_lat") or row.get("destinationLat"))
        destination_lon = self._safe_float(row.get("destination_lon") or row.get("destinationLon"))
        if None not in (origin_lat, origin_lon, destination_lat, destination_lon):
            straight_km = self._haversine_km(
                float(origin_lat),
                float(origin_lon),
                float(destination_lat),
                float(destination_lon),
            )
            if straight_km > 0.0:
                return straight_km * 1.3

        runtime_min = self._safe_float(
            row.get("runtime_min") or row.get("runtimeMin") or row.get("durationMin")
        )
        if runtime_min is not None and runtime_min > 0.0:
            return runtime_min / 60.0 * 17.0
        return 0.0

    def _haversine_km(
        self,
        lat1: float,
        lon1: float,
        lat2: float,
        lon2: float,
    ) -> float:
        radius_km = 6371.0
        dlat = math.radians(lat2 - lat1)
        dlon = math.radians(lon2 - lon1)
        a = (
            math.sin(dlat / 2.0) ** 2
            + math.cos(math.radians(lat1))
            * math.cos(math.radians(lat2))
            * math.sin(dlon / 2.0) ** 2
        )
        return radius_km * 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))

    def _build_dispatch_context_from_scenario(
        self,
        scenario: Dict[str, Any],
        *,
        depot_id: Optional[str],
        service_id: str,
    ) -> DispatchContext:
        vehicles = [
            vehicle
            for vehicle in scenario.get("vehicles") or []
            if depot_id is None or vehicle.get("depotId") == depot_id
        ]
        allowed_route_ids = self._allowed_route_ids_for_depot(scenario, depot_id)
        simulation_cfg = scenario.get("simulation_config") or {}
        disable_acquisition_cost = bool(
            simulation_cfg.get("disable_vehicle_acquisition_cost", False)
        )
        default_ice_tank_capacity_l = self._safe_float(
            simulation_cfg.get("default_ice_tank_capacity_l")
        )
        vehicle_profiles = self._build_vehicle_profiles(
            vehicles,
            disable_acquisition_cost=disable_acquisition_cost,
            default_ice_tank_capacity_l=default_ice_tank_capacity_l,
        )

        route_allowed_vehicle_types = self._allowed_vehicle_types_for_routes(
            scenario,
            vehicles,
            allowed_route_ids,
        )
        route_lookup: Dict[str, Dict[str, Any]] = {}
        for route in scenario.get("routes") or []:
            if not isinstance(route, dict):
                continue
            route_like = dict(route)
            route_id = str(route.get("id") or route.get("route_id") or "").strip()
            route_code = str(route.get("routeCode") or route.get("route_code") or "").strip()
            family_code = str(
                route.get("routeFamilyCode")
                or route.get("route_family_code")
                or route_code
                or route_id
            ).strip()
            direction = normalize_direction(route.get("direction") or route.get("canonicalDirection") or "outbound")
            variant_type = normalize_variant_type(
                route.get("routeVariantType")
                or route.get("route_variant_type")
                or route.get("routeVariantTypeManual")
                or "unknown",
                direction=direction,
            )
            lookup_keys = {
                route_id,
                route_code,
                family_code,
                f"{family_code}|{direction}|{variant_type}",
                f"{route_code}|{direction}|{variant_type}",
            }
            for key in lookup_keys:
                key_text = str(key or "").strip()
                if key_text:
                    route_lookup[key_text] = route_like
        trips: List[Trip] = []
        source_rows = list(scenario.get("timetable_rows") or [])
        if not source_rows:
            source_rows = list(scenario.get("trips") or [])
        for row in source_rows:
            row_service_id = row.get("service_id")
            if row_service_id is not None and row_service_id != service_id:
                continue
            route_id = str(row.get("route_id") or "")
            if allowed_route_ids is not None and route_id not in allowed_route_ids:
                continue
            route_code = str(row.get("route_code") or row.get("routeCode") or "").strip()
            family_code = str(
                row.get("routeFamilyCode")
                or row.get("route_family_code")
                or route_code
                or route_id
            ).strip()
            direction = normalize_direction(
                row.get("direction")
                or row.get("canonicalDirection")
                or "outbound"
            )
            variant_type = normalize_variant_type(
                row.get("routeVariantType")
                or row.get("route_variant_type")
                or "unknown",
                direction=direction,
            )
            route_like = (
                route_lookup.get(route_id)
                or route_lookup.get(route_code)
                or route_lookup.get(family_code)
                or route_lookup.get(f"{family_code}|{direction}|{variant_type}")
                or route_lookup.get(f"{route_code}|{direction}|{variant_type}")
                or {}
            )
            explicit_allowed = row.get("allowed_vehicle_types")
            allowed = (
                tuple(str(item) for item in explicit_allowed)
                if isinstance(explicit_allowed, list) and explicit_allowed
                else tuple(route_allowed_vehicle_types.get(route_id) or tuple(vehicle_profiles.keys()))
            )
            if not allowed:
                continue
            trips.append(
                Trip(
                    trip_id=str(row.get("trip_id") or f"{route_id}_{len(trips):04d}"),
                    route_id=route_id,
                    origin=str(row.get("origin") or ""),
                    destination=str(row.get("destination") or ""),
                    departure_time=str(row.get("departure") or "00:00"),
                    arrival_time=str(row.get("arrival") or "00:00"),
                    distance_km=self._estimate_trip_distance_km(row, route_like),
                    allowed_vehicle_types=allowed,
                    origin_stop_id=str(row.get("origin_stop_id") or ""),
                    destination_stop_id=str(row.get("destination_stop_id") or ""),
                    route_family_code=str(
                        row.get("routeFamilyCode")
                        or row.get("route_family_code")
                        or route_like.get("routeFamilyCode")
                        or family_code
                    ),
                    direction=direction,
                    route_variant_type=variant_type,
                )
            )

        turnaround_rules = {
            str(item.get("stop_id")): TurnaroundRule(
                stop_id=str(item.get("stop_id")),
                min_turnaround_min=max(0, int(item.get("min_turnaround_min") or 0)),
            )
            for item in scenario.get("turnaround_rules") or []
            if item.get("stop_id") is not None
        }
        deadhead_metrics = merge_deadhead_metrics(
            existing_rules=scenario.get("deadhead_rules") or [],
            trip_rows=source_rows,
            routes=scenario.get("routes") or [],
            stops=scenario.get("stops") or [],
            depots=scenario.get("depots") or [],
            assumed_speed_kmh=float(
                self._safe_float(
                    (scenario.get("simulation_config") or {}).get(
                        "deadhead_speed_kmh",
                        ((scenario.get("scenario_overlay") or {}).get("solver_config") or {}).get(
                            "deadhead_speed_kmh"
                        ),
                    )
                )
                or 18.0
            ),
        )
        deadhead_rules = {
            key: DeadheadRule(
                from_stop=metric.from_stop,
                to_stop=metric.to_stop,
                travel_time_min=max(0, int(metric.travel_time_min)),
            )
            for key, metric in deadhead_metrics.items()
        }

        service_date = str((scenario.get("meta") or {}).get("updatedAt") or "2026-01-01")[:10]
        turnaround_value = simulation_cfg.get("default_turnaround_min", 10)
        default_turnaround_min = 10 if turnaround_value is None else max(0, int(turnaround_value))
        return DispatchContext(
            service_date=service_date,
            trips=trips,
            turnaround_rules=turnaround_rules,
            deadhead_rules=deadhead_rules,
            vehicle_profiles=vehicle_profiles or {"BEV": VehicleProfile(vehicle_type="BEV")},
            default_turnaround_min=default_turnaround_min,
            location_aliases=self._build_dispatch_location_aliases(
                scenario=scenario,
                trips=trips,
            ),
        )

    def _build_dispatch_location_aliases(
        self,
        *,
        scenario: Dict[str, Any],
        trips: Sequence[Trip],
    ) -> Dict[str, Tuple[str, ...]]:
        alias_sets: Dict[str, set[str]] = {}

        def _register(alias: Any, target: Any) -> None:
            alias_text = str(alias or "").strip()
            target_text = str(target or "").strip()
            if not alias_text or not target_text:
                return
            alias_sets.setdefault(alias_text, set()).add(target_text)

        stop_ids_by_name: Dict[str, set[str]] = {}
        for stop in scenario.get("stops") or []:
            if not isinstance(stop, dict):
                continue
            stop_id = str(stop.get("id") or stop.get("stop_id") or "").strip()
            stop_name = str(stop.get("name") or stop.get("stop_name") or "").strip()
            if not stop_id:
                continue
            _register(stop_id, stop_id)
            if stop_name:
                _register(stop_id, stop_name)
                _register(stop_name, stop_id)
                stop_ids_by_name.setdefault(stop_name.casefold(), set()).add(stop_id)

        for trip in trips:
            _register(trip.origin, trip.origin_stop_id or trip.origin)
            _register(trip.destination, trip.destination_stop_id or trip.destination)
            if trip.origin_stop_id:
                _register(trip.origin_stop_id, trip.origin_stop_id)
                _register(trip.origin_stop_id, trip.origin)
            if trip.destination_stop_id:
                _register(trip.destination_stop_id, trip.destination_stop_id)
                _register(trip.destination_stop_id, trip.destination)

        for sibling_ids in stop_ids_by_name.values():
            if len(sibling_ids) < 2:
                continue
            ordered_ids = sorted(str(item).strip() for item in sibling_ids if str(item).strip())
            for from_stop_id in ordered_ids:
                for to_stop_id in ordered_ids:
                    if from_stop_id == to_stop_id:
                        continue
                    _register(from_stop_id, to_stop_id)

        for depot in scenario.get("depots") or []:
            if not isinstance(depot, dict):
                continue
            depot_id = str(depot.get("id") or depot.get("depotId") or "").strip()
            depot_name = str(depot.get("name") or "").strip()
            if depot_id:
                _register(depot_id, depot_id)
                if depot_name:
                    _register(depot_id, depot_name)
                    for stop_id in stop_ids_by_name.get(depot_name.casefold(), set()):
                        _register(depot_id, stop_id)
            if depot_name:
                _register(depot_name, depot_name)
                for stop_id in stop_ids_by_name.get(depot_name.casefold(), set()):
                    _register(depot_name, stop_id)

        return {
            alias: tuple(sorted(targets))
            for alias, targets in alias_sets.items()
            if targets
        }

    def _build_vehicles(
        self,
        profiles: Dict[str, VehicleProfile],
        vehicle_counts: Dict[str, int],
        *,
        default_home_depot_id: str,
    ) -> Iterable[ProblemVehicle]:
        for vehicle_type, profile in profiles.items():
            count = vehicle_counts.get(vehicle_type, self.default_vehicle_count_per_type)
            for idx in range(count):
                yield ProblemVehicle(
                    vehicle_id=f"{vehicle_type}_{idx + 1:03d}",
                    vehicle_type=vehicle_type,
                    home_depot_id=str(default_home_depot_id or "depot_default"),
                    initial_soc=profile.battery_capacity_kwh,
                    battery_capacity_kwh=profile.battery_capacity_kwh,
                    reserve_soc=profile.battery_capacity_kwh * 0.1
                    if profile.battery_capacity_kwh
                    else None,
                    initial_fuel_l=profile.fuel_tank_capacity_l,
                    fuel_tank_capacity_l=profile.fuel_tank_capacity_l,
                    fuel_reserve_l=profile.fuel_tank_capacity_l * 0.1
                    if profile.fuel_tank_capacity_l
                    else None,
                    fuel_consumption_l_per_km=profile.fuel_consumption_l_per_km,
                    energy_consumption_kwh_per_km=profile.energy_consumption_kwh_per_km,
                    fixed_use_cost_jpy=profile.fixed_use_cost_jpy,
                )

    def _build_vehicles_from_records(
        self,
        vehicles: Sequence[Dict[str, Any]],
        profiles: Dict[str, VehicleProfile],
        *,
        default_home_depot_id: str,
        disable_vehicle_acquisition_cost: bool,
        initial_soc_percent: Optional[float] = None,
        initial_soc: Optional[float] = None,
        final_soc_floor_percent: Optional[float] = None,
        initial_ice_fuel_percent: Optional[float] = None,
        min_ice_fuel_percent: Optional[float] = None,
        max_ice_fuel_percent: Optional[float] = None,
    ) -> Iterable[ProblemVehicle]:
        initial_soc_ratio_override = normalize_soc_ratio_like(
            initial_soc_percent if initial_soc_percent is not None else initial_soc
        )
        reserve_soc_ratio_override = self._normalize_percent_like_to_ratio(final_soc_floor_percent)
        initial_fuel_ratio_override = self._normalize_percent_like_to_ratio(initial_ice_fuel_percent)
        min_fuel_ratio_override = self._normalize_percent_like_to_ratio(min_ice_fuel_percent)
        max_fuel_ratio_override = self._normalize_percent_like_to_ratio(max_ice_fuel_percent)
        for index, vehicle in enumerate(vehicles):
            if not isinstance(vehicle, dict):
                continue
            vehicle_id = str(vehicle.get("id") or "").strip() or f"veh_{index + 1:03d}"
            vehicle_type = str(vehicle.get("type") or "BEV").upper()
            profile = profiles.get(vehicle_type)

            battery_capacity_kwh = self._safe_float(vehicle.get("batteryKwh"))
            if battery_capacity_kwh is None and profile is not None:
                battery_capacity_kwh = profile.battery_capacity_kwh
            initial_soc_kwh = resolve_soc_kwh(
                vehicle.get("initialSoc"),
                battery_capacity_kwh,
                initial_soc_ratio_override,
                fallback_full_when_missing=True,
            )
            reserve_soc = self._safe_float(vehicle.get("reserveSoc"))
            if reserve_soc_ratio_override is not None and battery_capacity_kwh is not None:
                reserve_soc = reserve_soc_ratio_override * battery_capacity_kwh
            if reserve_soc is None and battery_capacity_kwh is not None:
                reserve_soc = battery_capacity_kwh * 0.1

            fuel_tank_capacity_l = self._safe_float(vehicle.get("fuelTankL"))
            if fuel_tank_capacity_l is None and profile is not None:
                fuel_tank_capacity_l = profile.fuel_tank_capacity_l
            initial_fuel_l = self._safe_float(vehicle.get("initialFuelL"))
            if initial_fuel_ratio_override is not None and fuel_tank_capacity_l is not None:
                initial_fuel_l = initial_fuel_ratio_override * fuel_tank_capacity_l
            if max_fuel_ratio_override is not None and fuel_tank_capacity_l is not None and initial_fuel_l is not None:
                initial_fuel_l = min(initial_fuel_l, max_fuel_ratio_override * fuel_tank_capacity_l)
            if initial_fuel_l is None:
                initial_fuel_l = fuel_tank_capacity_l
            fuel_reserve_l = self._safe_float(vehicle.get("fuelReserveL"))
            if min_fuel_ratio_override is not None and fuel_tank_capacity_l is not None:
                fuel_reserve_l = min_fuel_ratio_override * fuel_tank_capacity_l
            if fuel_reserve_l is None and fuel_tank_capacity_l is not None:
                fuel_reserve_l = fuel_tank_capacity_l * 0.1

            fuel_l_per_km = self._safe_float(
                vehicle.get("fuelConsumptionLPerKm")
                or vehicle.get("fuel_consumption_l_per_km")
            )
            if fuel_l_per_km is None:
                fuel_eff_km_per_l = self._safe_float(
                    vehicle.get("fuelEfficiencyKmPerL")
                    or vehicle.get("fuel_efficiency_km_per_l")
                )
                if fuel_eff_km_per_l and fuel_eff_km_per_l > 0:
                    fuel_l_per_km = 1.0 / fuel_eff_km_per_l
            if fuel_l_per_km is None and profile is not None:
                fuel_l_per_km = profile.fuel_consumption_l_per_km

            energy_kwh_per_km = self._safe_float(
                vehicle.get("energyConsumption")
                or vehicle.get("energy_consumption_kwh_per_km")
            )
            if energy_kwh_per_km is None and profile is not None:
                energy_kwh_per_km = profile.energy_consumption_kwh_per_km

            fixed_use_cost_jpy = self._vehicle_fixed_use_cost_jpy(
                vehicle,
                disable_acquisition_cost=disable_vehicle_acquisition_cost,
            )
            if fixed_use_cost_jpy <= 0.0 and profile is not None:
                fixed_use_cost_jpy = profile.fixed_use_cost_jpy

            home_depot_id = str(
                vehicle.get("depotId")
                or vehicle.get("homeDepotId")
                or default_home_depot_id
                or "depot_default"
            ).strip() or "depot_default"
            raw_available = vehicle.get("available")
            if raw_available is None:
                raw_available = vehicle.get("enabled", True)

            yield ProblemVehicle(
                vehicle_id=vehicle_id,
                vehicle_type=vehicle_type,
                home_depot_id=home_depot_id,
                initial_soc=initial_soc_kwh,
                battery_capacity_kwh=battery_capacity_kwh,
                reserve_soc=reserve_soc,
                available=bool(raw_available),
                initial_fuel_l=initial_fuel_l,
                fuel_tank_capacity_l=fuel_tank_capacity_l,
                fuel_reserve_l=fuel_reserve_l,
                fuel_consumption_l_per_km=fuel_l_per_km,
                energy_consumption_kwh_per_km=energy_kwh_per_km,
                fixed_use_cost_jpy=fixed_use_cost_jpy,
            )

    def _build_vehicle_profiles(
        self,
        vehicles: Sequence[Dict[str, Any]],
        *,
        disable_acquisition_cost: bool = False,
        default_ice_tank_capacity_l: Optional[float] = None,
    ) -> Dict[str, VehicleProfile]:
        profiles: Dict[str, VehicleProfile] = {}
        for vehicle in vehicles:
            vehicle_type = str(vehicle.get("type") or "BEV").upper()
            fuel_eff_km_per_l = self._safe_float(vehicle.get("fuelEfficiencyKmPerL") or vehicle.get("fuel_efficiency_km_per_l"))
            fuel_l_per_km = None
            if fuel_eff_km_per_l and fuel_eff_km_per_l > 0:
                fuel_l_per_km = 1.0 / fuel_eff_km_per_l
            explicit_fuel_l_per_km = self._safe_float(vehicle.get("fuelConsumptionLPerKm") or vehicle.get("fuel_consumption_l_per_km"))
            if explicit_fuel_l_per_km is not None:
                fuel_l_per_km = explicit_fuel_l_per_km
            
            fixed_use_cost_jpy = self._vehicle_fixed_use_cost_jpy(
                vehicle,
                disable_acquisition_cost=disable_acquisition_cost,
            )
            fuel_tank_capacity_l = self._safe_float(vehicle.get("fuelTankL"))
            if (
                (fuel_tank_capacity_l is None or fuel_tank_capacity_l <= 0.0)
                and vehicle_type not in {"BEV", "PHEV", "FCEV"}
            ):
                fallback = self._safe_float(default_ice_tank_capacity_l)
                fuel_tank_capacity_l = fallback if fallback is not None and fallback > 0.0 else 300.0

            profiles.setdefault(
                vehicle_type,
                VehicleProfile(
                    vehicle_type=vehicle_type,
                    battery_capacity_kwh=self._safe_float(vehicle.get("batteryKwh")),
                    energy_consumption_kwh_per_km=self._safe_float(vehicle.get("energyConsumption")),
                    fuel_tank_capacity_l=fuel_tank_capacity_l,
                    fuel_consumption_l_per_km=fuel_l_per_km,
                    fixed_use_cost_jpy=fixed_use_cost_jpy,
                ),
            )
        return profiles

    def _build_routes(self, trips: Tuple[ProblemTrip, ...]) -> Tuple[ProblemRoute, ...]:
        grouped: Dict[str, List[str]] = {}
        for trip in trips:
            grouped.setdefault(trip.route_id, []).append(trip.trip_id)
        return tuple(
            ProblemRoute(route_id=route_id, trip_ids=tuple(trip_ids))
            for route_id, trip_ids in sorted(grouped.items())
        )

    def _build_vehicle_types(
        self,
        profiles: Dict[str, VehicleProfile],
    ) -> Tuple[ProblemVehicleType, ...]:
        items: List[ProblemVehicleType] = []
        for vehicle_type_id, profile in profiles.items():
            powertrain = "BEV" if profile.battery_capacity_kwh is not None else "ICE"
            items.append(
                ProblemVehicleType(
                    vehicle_type_id=vehicle_type_id,
                    powertrain_type=powertrain,
                    battery_capacity_kwh=profile.battery_capacity_kwh,
                    reserve_soc=profile.battery_capacity_kwh * 0.1
                    if profile.battery_capacity_kwh
                    else None,
                    fuel_tank_capacity_l=profile.fuel_tank_capacity_l,
                    fuel_consumption_l_per_km=profile.fuel_consumption_l_per_km,
                    energy_consumption_kwh_per_km=profile.energy_consumption_kwh_per_km,
                    fixed_use_cost_jpy=profile.fixed_use_cost_jpy,
                )
            )
        return tuple(items)

    def _vehicle_fixed_use_cost_jpy(
        self,
        vehicle: Dict[str, Any],
        *,
        disable_acquisition_cost: bool,
    ) -> float:
        if disable_acquisition_cost:
            return 0.0

        purchase_cost = self._safe_float(vehicle.get("acquisitionCost")) or 0.0
        residual_value = self._safe_float(
            vehicle.get("residualValueYen")
            or vehicle.get("residual_value_yen")
        ) or 0.0
        lifetime_year = max(
            self._safe_float(vehicle.get("lifetimeYear") or vehicle.get("lifetime_year")) or 12.0,
            1.0,
        )
        operation_days = max(
            self._safe_float(vehicle.get("operationDaysPerYear") or vehicle.get("operation_days_per_year")) or 365.0,
            1.0,
        )
        return (purchase_cost - residual_value) / (lifetime_year * operation_days)

    def _filter_scenario_vehicles_for_scope(
        self,
        scenario: Dict[str, Any],
        *,
        depot_id: Optional[str],
    ) -> List[Dict[str, Any]]:
        selected_depot_id = str(depot_id or "").strip()
        scoped: List[Dict[str, Any]] = []
        for vehicle in scenario.get("vehicles") or []:
            if not isinstance(vehicle, dict):
                continue
            vehicle_depot_id = str(vehicle.get("depotId") or "").strip()
            if selected_depot_id and vehicle_depot_id != selected_depot_id:
                continue
            scoped.append(dict(vehicle))
        return scoped

    def _build_baseline_plan(
        self,
        context: DispatchContext,
        *,
        vehicles: Sequence[ProblemVehicle] = (),
        max_fragments_per_vehicle: int = 1,
        max_fragments_per_vehicle_per_day: int = 1,
        allow_same_day_depot_cycles: bool = True,
        horizon_start_min: int = 0,
        all_trip_ids: Optional[set[str]] = None,
        feasible_connections: Optional[Mapping[str, Tuple[str, ...]]] = None,
        fixed_route_band_mode: bool = False,
    ) -> AssignmentPlan:
        baseline_all_trip_ids = all_trip_ids or {trip.trip_id for trip in context.trips}

        pooled_plan: Optional[AssignmentPlan] = None
        if vehicles and self._supports_pooled_shared_baseline(context, vehicles):
            pooled_plan = self._build_pooled_shared_baseline(
                context,
                vehicles=vehicles,
                all_trip_ids=baseline_all_trip_ids,
                feasible_connections=feasible_connections,
                fixed_route_band_mode=fixed_route_band_mode,
            )
            if len(pooled_plan.unserved_trip_ids) == 0:
                return pooled_plan

        # Build a baseline greedy plan but avoid assigning the same trip to
        # multiple vehicle types. Some trips are allowed for several vehicle
        # types (BEV/ICE); the previous implementation ran the greedy
        # generator per vehicle type over the full trip list which led to the
        # same trip appearing in duties of multiple types. That caused
        # duplicate-assignment infeasibility warnings downstream.
        duties: List[VehicleDuty] = []
        assigned_trip_ids: set[str] = set()
        duty_vehicle_map: Dict[str, str] = {}
        startup_rejected_vehicle_ids_by_duty: Dict[str, List[str]] = {}
        dispatcher = DispatchGenerator()
        vehicles_by_type: Dict[str, Tuple[ProblemVehicle, ...]] = {}
        for vehicle in vehicles:
            vehicles_by_type.setdefault(str(vehicle.vehicle_type), tuple())
            vehicles_by_type[str(vehicle.vehicle_type)] = (
                *vehicles_by_type[str(vehicle.vehicle_type)],
                vehicle,
            )

        # Iterate vehicle types in deterministic order and assign only
        # currently-unassigned trips that are eligible for that type.
        # Materialize after each type so scarce fleets (for example a handful
        # of BEVs versus many ICE buses) do not absorb every shared trip
        # before the abundant type gets a chance to cover the overflow.
        for vehicle_type in self._ordered_vehicle_types_for_baseline(
            context,
            available_vehicle_counts={
                vehicle_type: len(type_vehicles)
                for vehicle_type, type_vehicles in vehicles_by_type.items()
            },
        ):
            # filter context.trips to those eligible for this vehicle type and
            # not yet assigned
            eligible_trips = [
                t for t in context.trips
                if vehicle_type in t.allowed_vehicle_types and t.trip_id not in assigned_trip_ids
            ]
            if not eligible_trips:
                continue
            # create a shallow DispatchContext with the filtered trips
            temp_ctx = DispatchContext(
                service_date=context.service_date,
                trips=eligible_trips,
                turnaround_rules=context.turnaround_rules,
                deadhead_rules=context.deadhead_rules,
                vehicle_profiles=context.vehicle_profiles,
                default_turnaround_min=context.default_turnaround_min,
                fixed_route_band_mode=bool(fixed_route_band_mode),
                location_aliases=dict(getattr(context, "location_aliases", {}) or {}),
            )
            vt_duties = dispatcher.generate_greedy_duties(temp_ctx, vehicle_type)
            if vehicles:
                assignment_debug: Dict[str, Any] = {}
                materialized_duties, materialized_map, _skipped_trip_ids = assign_duty_fragments_to_vehicles(
                    vt_duties,
                    vehicles=vehicles_by_type.get(vehicle_type, ()),
                    max_fragments_per_vehicle=max_fragments_per_vehicle,
                    max_fragments_per_vehicle_per_day=max_fragments_per_vehicle_per_day,
                    allow_same_day_depot_cycles=allow_same_day_depot_cycles,
                    horizon_start_min=horizon_start_min,
                    dispatch_context=context,
                    fixed_route_band_mode=bool(fixed_route_band_mode),
                    debug_metadata=assignment_debug,
                )
                duties.extend(materialized_duties)
                duty_vehicle_map = merge_duty_vehicle_maps(
                    duty_vehicle_map,
                    materialized_map,
                )
                for duty_id, vehicle_ids in dict(
                    assignment_debug.get("startup_rejected_vehicle_ids_by_duty") or {}
                ).items():
                    startup_rejected_vehicle_ids_by_duty.setdefault(str(duty_id), []).extend(
                        str(vehicle_id) for vehicle_id in vehicle_ids
                    )
                selected_duties = materialized_duties
            else:
                duties.extend(vt_duties)
                selected_duties = vt_duties
            for duty in selected_duties:
                assigned_trip_ids.update(duty.trip_ids)

        fallback_plan = AssignmentPlan(
            duties=tuple(duties),
            charging_slots=(),
            refuel_slots=(),
            served_trip_ids=tuple(sorted(assigned_trip_ids)),
            unserved_trip_ids=tuple(sorted(baseline_all_trip_ids - assigned_trip_ids)),
            metadata={
                "source": "dispatch_greedy_baseline",
                "duty_vehicle_map": merge_duty_vehicle_maps(duty_vehicle_map),
                "startup_rejected_vehicle_ids_by_duty": {
                    duty_id: tuple(sorted(set(vehicle_ids)))
                    for duty_id, vehicle_ids in startup_rejected_vehicle_ids_by_duty.items()
                },
            },
        )
        if pooled_plan is not None and len(pooled_plan.served_trip_ids) > len(fallback_plan.served_trip_ids):
            return pooled_plan
        return fallback_plan

    def _supports_pooled_shared_baseline(
        self,
        context: DispatchContext,
        vehicles: Sequence[ProblemVehicle],
    ) -> bool:
        if not context.trips or not vehicles:
            return False
        available_types = {str(vehicle.vehicle_type) for vehicle in vehicles if str(vehicle.vehicle_type).strip()}
        if not available_types:
            return False
        for trip in context.trips:
            if not available_types.issubset({str(vehicle_type) for vehicle_type in trip.allowed_vehicle_types}):
                return False
        return True

    def _build_pooled_shared_baseline(
        self,
        context: DispatchContext,
        *,
        vehicles: Sequence[ProblemVehicle],
        all_trip_ids: set[str],
        feasible_connections: Optional[Mapping[str, Tuple[str, ...]]] = None,
        fixed_route_band_mode: bool = False,
    ) -> AssignmentPlan:
        trip_map = context.trips_by_id()
        trip_ids = {trip.trip_id for trip in context.trips}
        if not trip_ids or not vehicles:
            return AssignmentPlan(
                duties=(),
                charging_slots=(),
                refuel_slots=(),
                served_trip_ids=(),
                unserved_trip_ids=tuple(sorted(all_trip_ids)),
                metadata={"source": "dispatch_pooled_shared_path_cover_baseline", "duty_vehicle_map": {}},
            )

        if feasible_connections is not None:
            graph = {
                trip_id: tuple(next_id for next_id in feasible_connections.get(trip_id, ()) if next_id in trip_ids)
                for trip_id in trip_ids
            }
        else:
            representative_vehicle_type = str(vehicles[0].vehicle_type)
            graph = self._build_graph(context, representative_vehicle_type)
            graph = {
                trip_id: tuple(next_id for next_id in graph.get(trip_id, ()) if next_id in trip_ids)
                for trip_id in trip_ids
            }

        if fixed_route_band_mode:
            graph = {
                trip_id: tuple(
                    next_id
                    for next_id in next_ids
                    if trip_route_band_key(trip_map.get(next_id))
                    == trip_route_band_key(trip_map.get(trip_id))
                )
                for trip_id, next_ids in graph.items()
            }

        matched_successor, matched_predecessor, matching_cost = self._minimum_cost_maximum_matching(
            graph,
            trip_map=trip_map,
            context=context,
        )
        predecessor_by_trip = {
            trip_id: predecessor
            for trip_id, predecessor in matched_predecessor.items()
            if predecessor is not None
        }
        successor_by_trip = {
            trip_id: successor
            for trip_id, successor in matched_successor.items()
            if successor is not None
        }

        start_trip_ids = sorted(
            (trip_id for trip_id in trip_ids if trip_id not in predecessor_by_trip),
            key=lambda trip_id: (
                trip_map[trip_id].departure_min,
                trip_map[trip_id].arrival_min,
                trip_id,
            ),
        )
        chains: List[List[Trip]] = []
        visited: set[str] = set()
        for start_trip_id in start_trip_ids:
            if start_trip_id in visited:
                continue
            chain: List[Trip] = []
            current_trip_id: Optional[str] = start_trip_id
            while current_trip_id and current_trip_id not in visited:
                chain.append(trip_map[current_trip_id])
                visited.add(current_trip_id)
                current_trip_id = successor_by_trip.get(current_trip_id)
            if chain:
                chains.append(chain)
        for trip_id in sorted(
            trip_ids - visited,
            key=lambda item: (
                trip_map[item].departure_min,
                trip_map[item].arrival_min,
                item,
            ),
        ):
            chains.append([trip_map[trip_id]])

        available_vehicles = list(vehicles)
        vehicle_type_counts = Counter(str(vehicle.vehicle_type) for vehicle in vehicles)
        duties: List[VehicleDuty] = []
        duty_vehicle_map: Dict[str, str] = {}
        served_trip_ids: set[str] = set()
        skipped_trip_ids: List[str] = []

        for chain in sorted(
            chains,
            key=lambda item: (
                item[0].departure_min if item else 10**9,
                item[-1].arrival_min if item else 10**9,
                item[0].trip_id if item else "",
            ),
        ):
            vehicle = self._select_vehicle_for_shared_chain(
                chain,
                vehicles=available_vehicles,
                context=context,
                vehicle_type_counts=vehicle_type_counts,
            )
            if vehicle is None:
                skipped_trip_ids.extend(trip.trip_id for trip in chain)
                continue
            available_vehicles = [
                candidate
                for candidate in available_vehicles
                if str(candidate.vehicle_id) != str(vehicle.vehicle_id)
            ]
            duty = self._build_shared_chain_duty(
                chain,
                vehicle=vehicle,
                context=context,
            )
            duties.append(duty)
            duty_vehicle_map[str(duty.duty_id)] = str(vehicle.vehicle_id)
            served_trip_ids.update(duty.trip_ids)

        unserved_trip_ids = tuple(
            sorted((all_trip_ids - set(served_trip_ids)).union(set(skipped_trip_ids)))
        )
        return AssignmentPlan(
            duties=tuple(duties),
            charging_slots=(),
            refuel_slots=(),
            served_trip_ids=tuple(sorted(served_trip_ids)),
            unserved_trip_ids=unserved_trip_ids,
            metadata={
                "source": "dispatch_pooled_shared_path_cover_baseline",
                "duty_vehicle_map": merge_duty_vehicle_maps(duty_vehicle_map),
                "path_cover_chain_count": len(chains),
                "path_cover_matching_cost": float(matching_cost),
                "path_cover_matching_mode": "max_cardinality_min_deadhead_wait",
            },
        )

    def _select_vehicle_for_shared_chain(
        self,
        chain: Sequence[Trip],
        *,
        vehicles: Sequence[ProblemVehicle],
        context: DispatchContext,
        vehicle_type_counts: Mapping[str, int],
    ) -> Optional[ProblemVehicle]:
        if not chain or not vehicles:
            return None
        first_trip = chain[0]
        origin_key = str(first_trip.origin_stop_id or first_trip.origin)
        best_vehicle: Optional[ProblemVehicle] = None
        best_score: Optional[Tuple[int, int, float, str]] = None
        for vehicle in vehicles:
            if str(vehicle.vehicle_type) not in first_trip.allowed_vehicle_types:
                continue
            home_depot_id = str(vehicle.home_depot_id or "").strip()
            if not home_depot_id:
                continue
            deadhead_min = int(context.get_deadhead_min(home_depot_id, origin_key) or 0)
            if deadhead_min <= 0 and not context.locations_equivalent(home_depot_id, origin_key):
                continue
            score = (
                int(vehicle_type_counts.get(str(vehicle.vehicle_type), 0) or 0),
                -deadhead_min,
                -float(vehicle.fixed_use_cost_jpy or 0.0),
                str(vehicle.vehicle_id),
            )
            if best_score is None or score > best_score:
                best_score = score
                best_vehicle = vehicle
        return best_vehicle

    def _build_shared_chain_duty(
        self,
        chain: Sequence[Trip],
        *,
        vehicle: ProblemVehicle,
        context: DispatchContext,
    ) -> VehicleDuty:
        legs: List[DutyLeg] = []
        home_depot_id = str(vehicle.home_depot_id or "").strip()
        previous_trip: Optional[Trip] = None
        for trip in chain:
            if previous_trip is None:
                origin_key = str(trip.origin_stop_id or trip.origin)
                deadhead_min = int(context.get_deadhead_min(home_depot_id, origin_key) or 0)
            else:
                from_key = str(previous_trip.destination_stop_id or previous_trip.destination)
                to_key = str(trip.origin_stop_id or trip.origin)
                deadhead_min = int(context.get_deadhead_min(from_key, to_key) or 0)
            legs.append(DutyLeg(trip=trip, deadhead_from_prev_min=max(deadhead_min, 0)))
            previous_trip = trip
        return VehicleDuty(
            duty_id=str(vehicle.vehicle_id),
            vehicle_type=str(vehicle.vehicle_type),
            legs=tuple(legs),
        )

    def _maximum_bipartite_matching(
        self,
        graph: Mapping[str, Tuple[str, ...]],
    ) -> Tuple[Dict[str, Optional[str]], Dict[str, Optional[str]]]:
        left_nodes = list(graph.keys())
        pair_left: Dict[str, Optional[str]] = {node: None for node in left_nodes}
        pair_right: Dict[str, Optional[str]] = {}
        for successors in graph.values():
            for successor in successors:
                pair_right.setdefault(successor, None)
        distance: Dict[str, int] = {}
        infinity = 10**9

        def bfs() -> bool:
            queue: deque[str] = deque()
            best_augment_distance = infinity
            for node in left_nodes:
                if pair_left[node] is None:
                    distance[node] = 0
                    queue.append(node)
                else:
                    distance[node] = infinity
            while queue:
                node = queue.popleft()
                if distance[node] >= best_augment_distance:
                    continue
                for successor in graph.get(node, ()):
                    predecessor = pair_right.get(successor)
                    if predecessor is None:
                        best_augment_distance = distance[node] + 1
                    elif distance.get(predecessor, infinity) == infinity:
                        distance[predecessor] = distance[node] + 1
                        queue.append(predecessor)
            return best_augment_distance != infinity

        def dfs(node: str) -> bool:
            for successor in graph.get(node, ()):
                predecessor = pair_right.get(successor)
                if predecessor is None or (
                    distance.get(predecessor, infinity) == distance[node] + 1
                    and dfs(predecessor)
                ):
                    pair_left[node] = successor
                    pair_right[successor] = node
                    return True
            distance[node] = infinity
            return False

        while bfs():
            for node in left_nodes:
                if pair_left[node] is None:
                    dfs(node)

        return pair_left, pair_right

    def _minimum_cost_maximum_matching(
        self,
        graph: Mapping[str, Tuple[str, ...]],
        *,
        trip_map: Mapping[str, Trip],
        context: DispatchContext,
    ) -> Tuple[Dict[str, Optional[str]], Dict[str, Optional[str]], float]:
        """Maximum-cardinality path-cover matching with deadhead/wait tie-breaks.

        The large dummy cost makes every feasible edge preferable to leaving a
        trip unmatched, preserving minimum vehicle count. Among maximum
        matchings, edge cost favors lower deadhead first, then lower idle wait.
        """
        left_nodes = sorted(
            graph.keys(),
            key=lambda trip_id: (
                trip_map[trip_id].departure_min if trip_id in trip_map else 10**9,
                trip_map[trip_id].arrival_min if trip_id in trip_map else 10**9,
                trip_id,
            ),
        )
        right_nodes = sorted(
            trip_map.keys(),
            key=lambda trip_id: (
                trip_map[trip_id].departure_min,
                trip_map[trip_id].arrival_min,
                trip_id,
            ),
        )
        if not left_nodes or not right_nodes:
            pair_left, pair_right = self._maximum_bipartite_matching(graph)
            return pair_left, pair_right, 0.0

        try:
            import numpy as np
            from scipy.optimize import linear_sum_assignment
        except Exception:
            pair_left, pair_right = self._maximum_bipartite_matching(graph)
            return pair_left, pair_right, 0.0

        dummy_cost = 1.0e9
        invalid_cost = 1.0e12
        right_index = {trip_id: idx for idx, trip_id in enumerate(right_nodes)}
        cost_matrix = np.full(
            (len(left_nodes), len(right_nodes) + len(left_nodes)),
            invalid_cost,
            dtype=float,
        )
        for left_idx, from_trip_id in enumerate(left_nodes):
            cost_matrix[left_idx, len(right_nodes) + left_idx] = dummy_cost
            for to_trip_id in graph.get(from_trip_id, ()):
                to_idx = right_index.get(to_trip_id)
                if to_idx is None:
                    continue
                edge_cost = self._path_cover_edge_cost(
                    trip_map.get(from_trip_id),
                    trip_map.get(to_trip_id),
                    context=context,
                )
                cost_matrix[left_idx, to_idx] = min(edge_cost, dummy_cost - 1.0)

        row_ind, col_ind = linear_sum_assignment(cost_matrix)
        pair_left: Dict[str, Optional[str]] = {node: None for node in left_nodes}
        pair_right: Dict[str, Optional[str]] = {node: None for node in right_nodes}
        total_cost = 0.0
        for row_idx, col_idx in zip(row_ind, col_ind):
            from_trip_id = left_nodes[int(row_idx)]
            chosen_cost = float(cost_matrix[int(row_idx), int(col_idx)])
            if int(col_idx) >= len(right_nodes) or chosen_cost >= dummy_cost:
                continue
            to_trip_id = right_nodes[int(col_idx)]
            pair_left[from_trip_id] = to_trip_id
            pair_right[to_trip_id] = from_trip_id
            total_cost += chosen_cost
        return pair_left, pair_right, total_cost

    def _path_cover_edge_cost(
        self,
        from_trip: Optional[Trip],
        to_trip: Optional[Trip],
        *,
        context: DispatchContext,
    ) -> float:
        if from_trip is None or to_trip is None:
            return 1.0e8
        from_location = str(from_trip.destination_stop_id or from_trip.destination or "").strip()
        to_location = str(to_trip.origin_stop_id or to_trip.origin or "").strip()
        if not from_location or not to_location:
            deadhead_min = 0
        elif context.locations_equivalent(from_location, to_location):
            deadhead_min = 0
        else:
            deadhead_min = max(int(context.get_deadhead_min(from_location, to_location) or 0), 0)
        ready_min = int(from_trip.arrival_min) + int(deadhead_min)
        wait_min = max(int(to_trip.departure_min) - ready_min, 0)
        # Deadhead dominates idle wait; deterministic suffix avoids arbitrary
        # solver-dependent choices between otherwise identical arcs.
        deterministic_tie = (sum(ord(ch) for ch in str(to_trip.trip_id)) % 1000) / 1000.0
        return float(deadhead_min) * 1000.0 + float(wait_min) + deterministic_tie

    def _ordered_vehicle_types_for_baseline(
        self,
        context: DispatchContext,
        *,
        available_vehicle_counts: Optional[Mapping[str, int]] = None,
    ) -> List[str]:
        vehicle_types = list(context.vehicle_profiles.keys())
        if not available_vehicle_counts:
            return vehicle_types
        return sorted(
            vehicle_types,
            key=lambda vehicle_type: (
                -max(int(available_vehicle_counts.get(vehicle_type, 0) or 0), 0),
                vehicle_type,
            ),
        )

    def _materialize_baseline_plan(
        self,
        plan: Optional[AssignmentPlan],
        vehicles: Sequence[ProblemVehicle],
        *,
        max_fragments_per_vehicle: int,
        max_fragments_per_vehicle_per_day: int = 1,
        allow_same_day_depot_cycles: bool = True,
        horizon_start_min: int = 0,
        all_trip_ids: set[str],
        dispatch_context: Optional[DispatchContext] = None,
        fixed_route_band_mode: bool = False,
    ) -> AssignmentPlan:
        if plan is None:
            return AssignmentPlan(
                duties=(),
                charging_slots=(),
                refuel_slots=(),
                served_trip_ids=(),
                unserved_trip_ids=tuple(sorted(all_trip_ids)),
                metadata={"source": "dispatch_greedy_baseline", "duty_vehicle_map": {}},
            )
        assignment_debug: Dict[str, Any] = {}
        assigned_duties, duty_vehicle_map, skipped_trip_ids = assign_duty_fragments_to_vehicles(
            plan.duties,
            vehicles=vehicles,
            max_fragments_per_vehicle=max_fragments_per_vehicle,
            max_fragments_per_vehicle_per_day=max_fragments_per_vehicle_per_day,
            allow_same_day_depot_cycles=allow_same_day_depot_cycles,
            horizon_start_min=horizon_start_min,
            dispatch_context=dispatch_context,
            fixed_route_band_mode=bool(fixed_route_band_mode),
            debug_metadata=assignment_debug,
        )
        served_trip_ids = tuple(
            sorted({trip_id for duty in assigned_duties for trip_id in duty.trip_ids})
        )
        unserved_trip_ids = tuple(
            sorted((all_trip_ids - set(served_trip_ids)).union(set(skipped_trip_ids)))
        )
        return AssignmentPlan(
            duties=assigned_duties,
            charging_slots=(),
            refuel_slots=(),
            served_trip_ids=served_trip_ids,
            unserved_trip_ids=unserved_trip_ids,
            metadata={
                **dict(plan.metadata),
                "duty_vehicle_map": merge_duty_vehicle_maps(duty_vehicle_map),
                "startup_rejected_vehicle_ids_by_duty": dict(
                    assignment_debug.get("startup_rejected_vehicle_ids_by_duty") or {}
                ),
            },
        )

    def _build_baseline_plan_from_scenario(
        self,
        scenario: Dict[str, Any],
        context: DispatchContext,
    ) -> Optional[AssignmentPlan]:
        dispatch_plan = scenario.get("dispatch_plan") or {}
        plans = list(dispatch_plan.get("plans") or [])
        if not plans:
            return None

        trip_map = context.trips_by_id()
        duties: List[VehicleDuty] = []
        served_trip_ids: List[str] = []

        for plan in plans:
            for duty_raw in plan.get("duties") or []:
                legs: List[DutyLeg] = []
                for leg_raw in duty_raw.get("legs") or []:
                    trip_id = str(((leg_raw.get("trip") or {}).get("trip_id")) or "")
                    trip = trip_map.get(trip_id)
                    if trip is None:
                        continue
                    legs.append(
                        DutyLeg(
                            trip=trip,
                            deadhead_from_prev_min=int(leg_raw.get("deadhead_time_min") or 0),
                        )
                    )
                if not legs:
                    continue
                duties.append(
                    VehicleDuty(
                        duty_id=str(duty_raw.get("duty_id") or f"DUTY-{len(duties)+1:04d}"),
                        vehicle_type=str(duty_raw.get("vehicle_type") or legs[0].trip.allowed_vehicle_types[0]),
                        legs=tuple(legs),
                    )
                )
                served_trip_ids.extend(leg.trip.trip_id for leg in legs)

        if not duties:
            return None

        all_trip_ids = {trip.trip_id for trip in context.trips}
        served_set = set(served_trip_ids)
        return AssignmentPlan(
            duties=tuple(duties),
            charging_slots=(),
            served_trip_ids=tuple(sorted(served_set)),
            unserved_trip_ids=tuple(sorted(all_trip_ids - served_set)),
            metadata={"source": "scenario_dispatch_plan"},
        )

    def _estimate_trip_energy(self, distance_km: float, context: DispatchContext) -> float:
        bev = context.vehicle_profiles.get("BEV")
        if not bev or bev.energy_consumption_kwh_per_km is None:
            return 0.0
        return max(distance_km, 0.0) * bev.energy_consumption_kwh_per_km

    def _estimate_trip_fuel(self, distance_km: float, context: DispatchContext) -> float:
        fuel_rates = [
            profile.fuel_consumption_l_per_km
            for profile in context.vehicle_profiles.values()
            if profile.fuel_consumption_l_per_km is not None and profile.fuel_consumption_l_per_km > 0
        ]
        if not fuel_rates:
            return 0.0
        return max(distance_km, 0.0) * min(fuel_rates)

    def _reference_bev_capacity_kwh(self, context: DispatchContext) -> Optional[float]:
        bev_candidates = [
            profile.battery_capacity_kwh
            for profile in context.vehicle_profiles.values()
            if str(profile.vehicle_type).upper() in {"BEV", "PHEV", "FCEV"}
            and profile.battery_capacity_kwh is not None
            and profile.battery_capacity_kwh > 0
        ]
        if not bev_candidates:
            return None
        return float(max(bev_candidates))

    def _normalize_percent_like_to_ratio(self, value: Any) -> Optional[float]:
        parsed = self._safe_float(value)
        if parsed is None:
            return None
        if parsed < 0.0:
            return None
        if parsed > 1.0:
            parsed = parsed / 100.0
        return min(parsed, 1.0)

    def _derive_required_soc_departure_percent(
        self,
        *,
        trip_energy_kwh: float,
        bev_capacity_kwh: Optional[float],
        final_soc_floor_ratio: Optional[float],
    ) -> Optional[float]:
        cap = float(bev_capacity_kwh or 0.0)
        if cap <= 0.0:
            return None
        floor_ratio = max(0.0, float(final_soc_floor_ratio or 0.0))
        trip_ratio = max(0.0, float(trip_energy_kwh or 0.0)) / cap
        required_ratio = min(1.0, floor_ratio + trip_ratio)
        return required_ratio * 100.0

    def _build_chargers_from_scenario(
        self,
        scenario: Dict[str, Any],
        depot_id: Optional[str],
    ) -> Tuple[ChargerDefinition, ...]:
        chargers: List[ChargerDefinition] = []
        for item in scenario.get("chargers") or []:
            charger_id = item.get("id") or item.get("charger_id")
            charger_depot_id = item.get("siteId") or item.get("site_id") or depot_id or "depot_default"
            if not charger_id:
                continue
            if depot_id is not None and str(charger_depot_id) != depot_id:
                continue
            chargers.append(
                ChargerDefinition(
                    charger_id=str(charger_id),
                    depot_id=str(charger_depot_id),
                    power_kw=float(item.get("powerKw") or item.get("power_kw") or 0.0),
                    bidirectional=bool(item.get("bidirectional", False)),
                    simultaneous_ports=int(item.get("simultaneous_ports") or 1),
                )
            )
        return tuple(chargers)

    def _build_price_slots_from_scenario(
        self,
        scenario: Dict[str, Any],
        context: DispatchContext,
        depot_id: Optional[str],
        timestep_min: int,
        start_time: Optional[str] = None,
        slots_per_day: Optional[int] = None,
    ) -> Tuple[EnergyPriceSlot, ...]:
        profile_rows = scenario.get("energy_price_profiles") or []
        if profile_rows:
            expanded: List[EnergyPriceSlot] = []
            for item in profile_rows:
                site_id = str(item.get("site_id") or item.get("siteId") or depot_id or "depot_default")
                if depot_id is not None and site_id != depot_id:
                    continue
                values = item.get("values")
                if isinstance(values, list):
                    for idx, value in enumerate(values):
                        expanded.append(
                            EnergyPriceSlot(
                                slot_index=idx,
                                grid_buy_yen_per_kwh=float(value or 0.0),
                                grid_sell_yen_per_kwh=float(item.get("sell_back_price") or 0.0),
                                demand_charge_weight=float(item.get("demand_charge_weight") or 0.0),
                                co2_factor=float(item.get("co2_factor") or 0.0),
                            )
                        )
                elif item.get("time_idx") is not None:
                    expanded.append(
                        EnergyPriceSlot(
                            slot_index=int(item.get("time_idx") or 0),
                            grid_buy_yen_per_kwh=float(item.get("grid_energy_price") or item.get("value") or 0.0),
                            grid_sell_yen_per_kwh=float(item.get("sell_back_price") or 0.0),
                            demand_charge_weight=float(item.get("demand_charge_weight") or 0.0),
                            co2_factor=float(item.get("co2_factor") or 0.0),
                        )
                    )
            if expanded:
                return tuple(sorted(expanded, key=lambda slot: slot.slot_index))

        overlay_costs = ((scenario.get("scenario_overlay") or {}).get("cost_coefficients") or {})
        if isinstance(overlay_costs, dict):
            tou_bands = [
                dict(item)
                for item in overlay_costs.get("tou_pricing") or []
                if isinstance(item, dict)
            ]
            default_buy = float(overlay_costs.get("grid_flat_price_per_kwh") or 0.0)
            default_sell = float(overlay_costs.get("grid_sell_price_per_kwh") or 0.0)
            default_co2 = float(overlay_costs.get("grid_co2_kg_per_kwh") or 0.0)
            demand_weight = float(overlay_costs.get("demand_charge_cost_per_kw") or 0.0)
            generated_slots = list(
                self._build_time_slot_prices(
                    context,
                    (),
                    timestep_min=timestep_min,
                    start_time=start_time,
                    slots_per_day=slots_per_day,
                )
            )
            if tou_bands or default_buy > 0.0 or default_sell > 0.0 or default_co2 > 0.0 or demand_weight > 0.0:
                start_min = self._hhmm_to_min(start_time) if start_time else min(
                    (trip.departure_min for trip in context.trips),
                    default=0,
                )
                expanded: List[EnergyPriceSlot] = []
                for slot in generated_slots:
                    minute_of_day = (start_min + slot.slot_index * timestep_min) % (24 * 60)
                    half_hour_index = minute_of_day // 30
                    buy_price = default_buy
                    for band in tou_bands:
                        try:
                            start_hour = int(band.get("start_hour") or 0)
                            end_hour = int(band.get("end_hour") or 48)
                        except (TypeError, ValueError):
                            continue
                        if start_hour <= half_hour_index < end_hour:
                            buy_price = float(band.get("price_per_kwh") or default_buy)
                            break
                    expanded.append(
                        EnergyPriceSlot(
                            slot_index=slot.slot_index,
                            grid_buy_yen_per_kwh=buy_price,
                            grid_sell_yen_per_kwh=default_sell,
                            demand_charge_weight=demand_weight,
                            co2_factor=default_co2,
                        )
                    )
                return tuple(expanded)

        tariff_cfg = (
            (scenario.get("simulation_config") or {}).get("tariff")
            or scenario.get("tariff")
            or {}
        )
        csv_path = tariff_cfg.get("csv_path")
        if csv_path:
            rows = load_tariff_csv(Path(csv_path))
            tariff_start_time = start_time or self._min_hhmm(context) or "05:00"
            prices = build_electricity_prices_from_tariff(
                rows,
                site_ids=[depot_id or "depot_default"],
                num_periods=max(
                    1,
                    len(
                        list(
                            self._build_time_slot_prices(
                                context,
                                (),
                                timestep_min=timestep_min,
                                start_time=start_time,
                                slots_per_day=slots_per_day,
                            )
                        )
                    ),
                ),
                delta_t_min=float(timestep_min),
                start_time=tariff_start_time,
            )
            if prices:
                grouped: Dict[int, EnergyPriceSlot] = {}
                for price in prices:
                    grouped[price.time_idx] = EnergyPriceSlot(
                        slot_index=price.time_idx,
                        grid_buy_yen_per_kwh=price.grid_energy_price,
                        grid_sell_yen_per_kwh=price.sell_back_price,
                        demand_charge_weight=price.base_load_kw,
                        co2_factor=0.0,
                    )
                return tuple(grouped[idx] for idx in sorted(grouped))
        return tuple(
            self._build_time_slot_prices(
                context,
                (),
                timestep_min=timestep_min,
                start_time=start_time,
                slots_per_day=slots_per_day,
            )
        )

    def _build_pv_slots_from_scenario(
        self,
        scenario: Dict[str, Any],
    ) -> Tuple[PVSlot, ...]:
        rows = scenario.get("pv_profiles") or []
        expanded: List[PVSlot] = []
        for item in rows:
            values = item.get("values")
            if isinstance(values, list):
                for idx, value in enumerate(values):
                    expanded.append(PVSlot(slot_index=idx, pv_available_kw=float(value or 0.0)))
            elif item.get("time_idx") is not None:
                expanded.append(
                    PVSlot(
                        slot_index=int(item.get("time_idx") or 0),
                        pv_available_kw=float(item.get("pv_generation_kw") or item.get("value") or 0.0),
                    )
                )
        return tuple(sorted(expanded, key=lambda slot: slot.slot_index))

    def _vehicle_counts_from_scenario(
        self,
        scenario: Dict[str, Any],
        depot_id: Optional[str],
    ) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for vehicle in scenario.get("vehicles") or []:
            if depot_id is not None and vehicle.get("depotId") != depot_id:
                continue
            vehicle_type = str(vehicle.get("type") or "BEV").upper()
            counts[vehicle_type] = counts.get(vehicle_type, 0) + 1
        return counts

    def _allowed_route_ids_for_depot(
        self,
        scenario: Dict[str, Any],
        depot_id: Optional[str],
    ) -> Optional[set[str]]:
        if depot_id is None:
            return None
        matching = [
            item for item in scenario.get("depot_route_permissions") or []
            if item.get("depotId") == depot_id
        ]
        if not matching:
            return None
        return {
            str(item.get("routeId"))
            for item in matching
            if bool(item.get("allowed", True))
        }

    def _allowed_vehicle_types_for_routes(
        self,
        scenario: Dict[str, Any],
        vehicles: Sequence[Dict[str, Any]],
        allowed_route_ids: Optional[set[str]],
    ) -> Dict[str, List[str]]:
        vehicle_type_by_id = {
            str(vehicle.get("id")): str(vehicle.get("type") or "BEV").upper()
            for vehicle in vehicles
            if vehicle.get("id") is not None
        }
        route_allowed: Dict[str, set[str]] = {}
        permissions = scenario.get("vehicle_route_permissions") or []
        if permissions:
            for permission in permissions:
                route_id = str(permission.get("routeId") or "")
                vehicle_id = str(permission.get("vehicleId") or "")
                if not route_id or vehicle_id not in vehicle_type_by_id:
                    continue
                if allowed_route_ids is not None and route_id not in allowed_route_ids:
                    continue
                if bool(permission.get("allowed")):
                    route_allowed.setdefault(route_id, set()).add(vehicle_type_by_id[vehicle_id])
        if not route_allowed:
            all_types = sorted(set(vehicle_type_by_id.values()))
            for route in scenario.get("routes") or []:
                route_id = str(route.get("id") or "")
                if not route_id:
                    continue
                if allowed_route_ids is not None and route_id not in allowed_route_ids:
                    continue
                route_allowed[route_id] = set(all_types)
        return {route_id: sorted(types) for route_id, types in route_allowed.items()}

    def _objective_weights_from_scenario(
        self,
        scenario: Dict[str, Any],
    ) -> OptimizationObjectiveWeights:
        component_flags = self._cost_component_flags_from_scenario(scenario)
        simulation_config = scenario.get("simulation_config") or {}
        overlay_solver = ((scenario.get("scenario_overlay") or {}).get("solver_config") or {})
        objective_mode = normalize_objective_mode(
            simulation_config.get("objective_mode")
            or overlay_solver.get("objective_mode")
            or "total_cost"
        )
        explicit_weights = (
            simulation_config.get("objective_weights")
            or overlay_solver.get("objective_weights")
            or {}
        )
        objective_weights = canonical_objective_weights_for_mode(
            objective_mode=objective_mode,
            unserved_penalty=float(
                simulation_config.get("unserved_penalty")
                or overlay_solver.get("unserved_penalty")
                or 10000.0
            ),
            explicit_weights=explicit_weights if isinstance(explicit_weights, dict) else {},
        )
        energy_terms_enabled = any(
            bool(component_flags.get(key, True))
            for key in (
                "electricity_cost",
                "fuel_cost",
                "contract_overage_penalty",
                "charge_session_start_penalty",
                "slot_concurrency_penalty",
                "early_charge_penalty",
                "soc_upper_buffer_penalty",
                "grid_to_bus_priority_penalty",
                "grid_to_bess_priority_penalty",
            )
        )
        if not component_flags["vehicle_fixed_cost"]:
            objective_weights["vehicle_fixed_cost"] = 0.0
        if not energy_terms_enabled:
            objective_weights["electricity_cost"] = 0.0
        if not component_flags["demand_charge_cost"]:
            objective_weights["demand_charge_cost"] = 0.0
        if not component_flags["unserved_penalty"]:
            objective_weights["unserved_penalty"] = 0.0
        if not component_flags["switch_cost"]:
            objective_weights["switch_cost"] = 0.0
        if not component_flags["battery_degradation_cost"]:
            objective_weights["degradation"] = 0.0
        if not component_flags["deviation_cost"]:
            objective_weights["deviation_cost"] = 0.0
        return OptimizationObjectiveWeights(
            energy=float(objective_weights.get("electricity_cost", 1.0)),
            demand=float(objective_weights.get("demand_charge_cost", 1.0)),
            vehicle=float(objective_weights.get("vehicle_fixed_cost", 1.0)),
            unserved=float(objective_weights.get("unserved_penalty", 10000.0)),
            deviation=float(objective_weights.get("deviation_cost", 0.0)),
            switch=float(objective_weights.get("switch_cost", 0.0)),
            degradation=float(objective_weights.get("degradation", 0.0)),
            utilization=float(objective_weights.get("utilization", 0.0)),
        )

    def _cost_component_flags_from_scenario(
        self,
        scenario: Dict[str, Any],
    ) -> Dict[str, bool]:
        simulation_config = scenario.get("simulation_config") or {}
        return normalize_cost_component_flags(
            simulation_config.get("cost_component_flags"),
            legacy_disable_vehicle_acquisition_cost=simulation_config.get(
                "disable_vehicle_acquisition_cost"
            ),
            legacy_enable_vehicle_cost=simulation_config.get("enable_vehicle_cost"),
            legacy_enable_driver_cost=simulation_config.get("enable_driver_cost"),
            legacy_enable_other_cost=simulation_config.get("enable_other_cost"),
        )

    def _safe_float(self, value: Any) -> Optional[float]:
        try:
            return None if value is None else float(value)
        except (TypeError, ValueError):
            return None

    def _build_time_slot_prices(
        self,
        context: DispatchContext,
        price_slots: Sequence[EnergyPriceSlot],
        *,
        timestep_min: int,
        start_time: Optional[str] = None,
        slots_per_day: Optional[int] = None,
    ) -> Iterable[EnergyPriceSlot]:
        if price_slots:
            return price_slots
        if slots_per_day is not None and slots_per_day > 0:
            start_min = self._hhmm_to_min(start_time) if start_time else min(
                (trip.departure_min for trip in context.trips),
                default=0,
            )
            generated: List[EnergyPriceSlot] = []
            for slot_index in range(int(slots_per_day)):
                minute = (start_min + slot_index * timestep_min) % (24 * 60)
                generated.append(
                    EnergyPriceSlot(
                        slot_index=slot_index,
                        grid_buy_yen_per_kwh=20.0 if minute < 16 * 60 else 28.0,
                        grid_sell_yen_per_kwh=8.0,
                    )
                )
            return generated
        start = min(trip.departure_min for trip in context.trips) if context.trips else 0
        end = max(trip.arrival_min for trip in context.trips) if context.trips else 0
        slot_index = 0
        generated: List[EnergyPriceSlot] = []
        for minute in range(start, end + timestep_min, timestep_min):
            generated.append(
                EnergyPriceSlot(
                    slot_index=slot_index,
                    grid_buy_yen_per_kwh=20.0 if minute < 16 * 60 else 28.0,
                    grid_sell_yen_per_kwh=8.0,
                )
            )
            slot_index += 1
        return generated

    def _build_pv_slots(
        self,
        time_slots: Sequence[EnergyPriceSlot],
        pv_slots: Sequence[PVSlot],
        planning_days: int = 1,
    ) -> Iterable[PVSlot]:
        if pv_slots:
            # Tile provided pv_slots for multi-day scenarios
            if planning_days > 1:
                base_slots = list(pv_slots)
                slots_per_day = len(base_slots)
                all_pv_slots: List[PVSlot] = list(base_slots)
                for day_idx in range(1, planning_days):
                    for base_slot in base_slots:
                        all_pv_slots.append(
                            PVSlot(
                                slot_index=day_idx * slots_per_day + base_slot.slot_index,
                                pv_available_kw=base_slot.pv_available_kw,
                            )
                        )
                return all_pv_slots
            return pv_slots
        return [
            PVSlot(
                slot_index=slot.slot_index,
                pv_available_kw=40.0 if 10 <= (slot.slot_index % 48) <= 18 else 0.0,  # Modulo for multi-day
            )
            for slot in time_slots
        ]

    def _min_hhmm(self, context: DispatchContext) -> Optional[str]:
        if not context.trips:
            return None
        return min(trip.departure_time for trip in context.trips)

    def _max_hhmm(self, context: DispatchContext) -> Optional[str]:
        if not context.trips:
            return None
        return max(trip.arrival_time for trip in context.trips)

    def _normalize_hhmm(self, value: Any) -> Optional[str]:
        if value is None:
            return None
        text = str(value).strip()
        if not text:
            return None
        try:
            minutes = hhmm_to_min(text) % (24 * 60)
        except ValueError:
            return None
        hh = minutes // 60
        mm = minutes % 60
        return f"{hh:02d}:{mm:02d}"

    def _hhmm_to_min(self, value: Any) -> int:
        normalized = self._normalize_hhmm(value)
        if normalized is None:
            return 0
        hh, mm = normalized.split(":")
        return int(hh) * 60 + int(mm)

    def _daily_window_duration_min(self, start_hhmm: str, end_hhmm: str) -> int:
        start_min = self._hhmm_to_min(start_hhmm)
        end_min = self._hhmm_to_min(end_hhmm)
        duration = end_min - start_min
        if duration <= 0:
            duration += 24 * 60
        return duration
