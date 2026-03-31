from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

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
from src.route_family_runtime import (
    merge_deadhead_metrics,
    normalize_direction,
    normalize_variant_type,
)
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
        chargers = self._build_chargers_from_scenario(scenario, depot_id)
        price_slots = self._build_price_slots_from_scenario(
            scenario,
            context,
            depot_id,
            timestep_min=timestep_min,
        )
        pv_slots = self._build_pv_slots_from_scenario(scenario)
        vehicle_counts = self._vehicle_counts_from_scenario(scenario, depot_id)
        weights = self._objective_weights_from_scenario(scenario)
        baseline = self._build_baseline_plan_from_scenario(scenario, context)
        charging_cfg = ((scenario.get("scenario_overlay") or {}).get("charging_constraints") or {})
        cost_cfg = ((scenario.get("scenario_overlay") or {}).get("cost_coefficients") or {})
        solver_cfg = ((scenario.get("scenario_overlay") or {}).get("solver_config") or {})
        simulation_cfg = scenario.get("simulation_config") or {}
        objective_mode = normalize_objective_mode(
            simulation_cfg.get("objective_mode")
            or solver_cfg.get("objective_mode")
            or "total_cost"
        )
        fixed_route_band_mode = bool(
            simulation_cfg.get(
                "fixed_route_band_mode",
                solver_cfg.get("fixed_route_band_mode", False),
            )
        )
        max_start_fragments_per_vehicle = int(
            simulation_cfg.get(
                "max_start_fragments_per_vehicle",
                solver_cfg.get("max_start_fragments_per_vehicle", 1),
            )
            or 1
        )
        max_end_fragments_per_vehicle = int(
            simulation_cfg.get(
                "max_end_fragments_per_vehicle",
                solver_cfg.get("max_end_fragments_per_vehicle", 1),
            )
            or 1
        )
        allow_partial_service = bool(
            simulation_cfg.get(
                "allow_partial_service",
                solver_cfg.get("allow_partial_service", False),
            )
        )
        initial_soc_percent = self._safe_float(
            simulation_cfg.get("initial_soc_percent")
            or charging_cfg.get("initial_soc_percent")
        )
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
            max_start_fragments_per_vehicle=max(1, max_start_fragments_per_vehicle),
            max_end_fragments_per_vehicle=max(1, max_end_fragments_per_vehicle),
            allow_partial_service=allow_partial_service,
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
            scenario_vehicles=scenario_vehicles,
            disable_vehicle_acquisition_cost=disable_acquisition_cost,
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
        planning_days: int = 1,
        max_start_fragments_per_vehicle: int = 1,
        max_end_fragments_per_vehicle: int = 1,
        allow_partial_service: bool = False,
        initial_soc_percent: Optional[float] = None,
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
        scenario_vehicles: Optional[Sequence[Dict[str, Any]]] = None,
        disable_vehicle_acquisition_cost: bool = False,
    ) -> CanonicalOptimizationProblem:
        config = config or OptimizationConfig()
        vehicle_counts = vehicle_counts or {}
        timestep_min = max(int(timestep_min or 60), 1)
        if home_depot_charge_pre_window_min is None:
            home_depot_charge_pre_window_min = float(timestep_min)
        if home_depot_charge_post_window_min is None:
            home_depot_charge_post_window_min = float(timestep_min)
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
        base_time_slots = list(self._build_time_slot_prices(context, price_slots, timestep_min=timestep_min))
        
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
                            co2_kg_per_kwh=base_slot.co2_kg_per_kwh,
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

        baseline_source = baseline_plan or self._build_baseline_plan(context)
        max_fragments = max(
            int(max_start_fragments_per_vehicle or 1),
            int(max_end_fragments_per_vehicle or 1),
            1,
        )
        baseline = self._materialize_baseline_plan(
            baseline_source,
            vehicles,
            max_fragments_per_vehicle=max_fragments,
            all_trip_ids={trip.trip_id for trip in trip_nodes},
        )
        return CanonicalOptimizationProblem(
            scenario=OptimizationScenario(
                scenario_id=scenario_id,
                horizon_start=self._min_hhmm(context),
                horizon_end=self._max_hhmm(context),
                timestep_min=timestep_min,
                planning_days=planning_days,
                objective_mode=normalize_objective_mode(objective_mode),
                diesel_price_yen_per_l=float(diesel_price_yen_per_l),
                demand_charge_on_peak_yen_per_kw=float(demand_charge_on_peak_yen_per_kw),
                demand_charge_off_peak_yen_per_kw=float(demand_charge_off_peak_yen_per_kw),
                co2_price_per_kg=float(co2_price_per_kg),
                ice_co2_kg_per_l=float(ice_co2_kg_per_l),
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
                "fixed_route_band_mode": bool(fixed_route_band_mode),
                "planning_days": planning_days,
                "max_start_fragments_per_vehicle": int(max(1, max_start_fragments_per_vehicle)),
                "max_end_fragments_per_vehicle": int(max(1, max_end_fragments_per_vehicle)),
                "allow_partial_service": bool(allow_partial_service),
                "initial_soc_percent": initial_soc_percent,
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
                "enable_contract_overage_penalty": bool(enable_contract_overage_penalty),
                "contract_overage_penalty_yen_per_kwh": contract_overage_penalty_yen_per_kwh,
                "grid_to_bus_priority_penalty_yen_per_kwh": grid_to_bus_priority_penalty_yen_per_kwh,
                "grid_to_bess_priority_penalty_yen_per_kwh": grid_to_bess_priority_penalty_yen_per_kwh,
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

        for depot in depots:
            raw = by_depot_raw.get(depot.depot_id, {})
            if not raw and len(depots) == 1:
                raw = by_depot_raw.get("depot_default") or by_depot_raw.get(canonical_depot_id) or {}
            pv_series = self._align_energy_series_to_slot_count(
                raw.get("pv_generation_kwh_by_slot") or pv_kwh_by_slot,
                slot_count,
            )
            asset = DepotEnergyAsset(
                depot_id=depot.depot_id,
                pv_enabled=bool(raw.get("pv_enabled", len(pv_slots) > 0)),
                pv_generation_kwh_by_slot=pv_series,
                pv_case_id=str(raw.get("pv_case_id") or "default"),
                pv_capex_jpy_per_kw=float(raw.get("pv_capex_jpy_per_kw") or 0.0),
                pv_om_jpy_per_kw_year=float(raw.get("pv_om_jpy_per_kw_year") or 0.0),
                pv_life_years=int(raw.get("pv_life_years") or 25),
                pv_capacity_kw=float(raw.get("pv_capacity_kw") or 0.0),
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
        route_lookup = {
            str(route.get("id") or route.get("route_id") or ""): dict(route)
            for route in scenario.get("routes") or []
            if str(route.get("id") or route.get("route_id") or "")
        }
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
            route_like = route_lookup.get(route_id) or {}
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
                        or route_id
                    ),
                    direction=normalize_direction(
                        row.get("direction")
                        or row.get("canonicalDirection")
                        or route_like.get("canonicalDirection")
                        or "outbound"
                    ),
                    route_variant_type=normalize_variant_type(
                        row.get("routeVariantType")
                        or row.get("route_variant_type")
                        or route_like.get("routeVariantType")
                        or route_like.get("routeVariantTypeManual")
                        or "unknown",
                        direction=normalize_direction(
                            row.get("direction")
                            or row.get("canonicalDirection")
                            or route_like.get("canonicalDirection")
                            or "outbound"
                        ),
                    ),
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
        default_turnaround_min = int((simulation_cfg.get("default_turnaround_min")) or 10)
        return DispatchContext(
            service_date=service_date,
            trips=trips,
            turnaround_rules=turnaround_rules,
            deadhead_rules=deadhead_rules,
            vehicle_profiles=vehicle_profiles or {"BEV": VehicleProfile(vehicle_type="BEV")},
            default_turnaround_min=default_turnaround_min,
        )

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
        final_soc_floor_percent: Optional[float] = None,
        initial_ice_fuel_percent: Optional[float] = None,
        min_ice_fuel_percent: Optional[float] = None,
        max_ice_fuel_percent: Optional[float] = None,
    ) -> Iterable[ProblemVehicle]:
        initial_soc_ratio_override = self._normalize_percent_like_to_ratio(initial_soc_percent)
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
            initial_soc = self._safe_float(vehicle.get("initialSoc"))
            if initial_soc_ratio_override is not None and battery_capacity_kwh is not None:
                initial_soc = initial_soc_ratio_override * battery_capacity_kwh
            if initial_soc is None:
                initial_soc = battery_capacity_kwh
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

            yield ProblemVehicle(
                vehicle_id=vehicle_id,
                vehicle_type=vehicle_type,
                home_depot_id=home_depot_id,
                initial_soc=initial_soc,
                battery_capacity_kwh=battery_capacity_kwh,
                reserve_soc=reserve_soc,
                available=bool(vehicle.get("enabled", True)),
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
        # CRITICAL FIX: When acquisition cost is disabled, use a fixed daily cost
        # instead of 0.0 to ensure vehicle_cost is included in optimization
        if disable_acquisition_cost:
            # Use a reasonable fixed cost per vehicle per day
            # This represents operational readiness cost (e.g., maintenance, insurance)
            # Default: 5000 JPY/vehicle/day
            return 5000.0
        
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

    def _build_baseline_plan(self, context: DispatchContext) -> AssignmentPlan:
        # Build a baseline greedy plan but avoid assigning the same trip to
        # multiple vehicle types. Some trips are allowed for several vehicle
        # types (BEV/ICE); the previous implementation ran the greedy
        # generator per vehicle type over the full trip list which led to the
        # same trip appearing in duties of multiple types. That caused
        # duplicate-assignment infeasibility warnings downstream.
        duties: List[VehicleDuty] = []
        assigned_trip_ids: set[str] = set()
        dispatcher = DispatchGenerator()

        # Iterate vehicle types in deterministic order and assign only
        # currently-unassigned trips that are eligible for that type.
        for vehicle_type in list(context.vehicle_profiles.keys()):
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
            )
            vt_duties = dispatcher.generate_greedy_duties(temp_ctx, vehicle_type)
            duties.extend(vt_duties)
            for duty in vt_duties:
                assigned_trip_ids.update(duty.trip_ids)

        all_trip_ids = {trip.trip_id for trip in context.trips}
        return AssignmentPlan(
            duties=tuple(duties),
            charging_slots=(),
            served_trip_ids=tuple(sorted(assigned_trip_ids)),
            unserved_trip_ids=tuple(sorted(all_trip_ids - assigned_trip_ids)),
            metadata={"source": "dispatch_greedy_baseline"},
        )

    def _materialize_baseline_plan(
        self,
        plan: Optional[AssignmentPlan],
        vehicles: Sequence[ProblemVehicle],
        *,
        max_fragments_per_vehicle: int,
        all_trip_ids: set[str],
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
        assigned_duties, duty_vehicle_map, skipped_trip_ids = assign_duty_fragments_to_vehicles(
            plan.duties,
            vehicles=vehicles,
            max_fragments_per_vehicle=max_fragments_per_vehicle,
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
            generated_slots = list(self._build_time_slot_prices(context, (), timestep_min=timestep_min))
            if tou_bands or default_buy > 0.0 or default_sell > 0.0 or default_co2 > 0.0 or demand_weight > 0.0:
                start_min = min((trip.departure_min for trip in context.trips), default=0)
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
            start_time = self._min_hhmm(context) or "05:00"
            prices = build_electricity_prices_from_tariff(
                rows,
                site_ids=[depot_id or "depot_default"],
                num_periods=max(1, len(list(self._build_time_slot_prices(context, (), timestep_min=timestep_min)))),
                delta_t_min=float(timestep_min),
                start_time=start_time,
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
        return tuple(self._build_time_slot_prices(context, (), timestep_min=timestep_min))

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
    ) -> Iterable[EnergyPriceSlot]:
        if price_slots:
            return price_slots
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
