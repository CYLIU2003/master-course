from __future__ import annotations

from dataclasses import dataclass
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


@dataclass(frozen=True)
class ProblemBuilder:
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
        chargers = self._build_chargers_from_scenario(scenario, depot_id)
        price_slots = self._build_price_slots_from_scenario(scenario, context, depot_id)
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
        initial_soc_percent = self._safe_float(
            simulation_cfg.get("initial_soc_percent")
            or charging_cfg.get("initial_soc_percent")
        )
        final_soc_floor_percent = self._safe_float(
            simulation_cfg.get("final_soc_floor_percent")
            or charging_cfg.get("final_soc_floor_percent")
        )
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
            initial_soc_percent=initial_soc_percent,
            final_soc_floor_percent=final_soc_floor_percent,
        )

    def build_from_dispatch(
        self,
        context: DispatchContext,
        *,
        scenario_id: str,
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
        max_start_fragments_per_vehicle: int = 1,
        max_end_fragments_per_vehicle: int = 1,
        initial_soc_percent: Optional[float] = None,
        final_soc_floor_percent: Optional[float] = None,
    ) -> CanonicalOptimizationProblem:
        config = config or OptimizationConfig()
        vehicle_counts = vehicle_counts or {}
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
        trip_nodes = tuple(trip_nodes_list)
        route_nodes = self._build_routes(trip_nodes)
        vehicle_types = self._build_vehicle_types(context.vehicle_profiles)
        vehicles = tuple(
            self._build_vehicles(
                context.vehicle_profiles,
                vehicle_counts,
            )
        )
        inferred_import_limit = depot_import_limit_kw
        if inferred_import_limit is None:
            charger_capacity = sum(charger.power_kw * max(charger.simultaneous_ports, 1) for charger in chargers)
            inferred_import_limit = charger_capacity if charger_capacity > 0 else 1000.0

        depots = (
            ProblemDepot(
                depot_id="depot_default",
                name="Default Depot",
                charger_ids=tuple(charger.charger_id for charger in chargers),
                import_limit_kw=float(inferred_import_limit),
            ),
        )
        time_slots = tuple(self._build_time_slot_prices(context, price_slots))
        pv_series = tuple(self._build_pv_slots(time_slots, pv_slots))
        feasible_connections: Dict[str, Tuple[str, ...]] = {}
        for vehicle_type in context.vehicle_profiles:
            graph = self._build_graph(context, vehicle_type)
            for trip_id, successors in graph.items():
                merged = set(feasible_connections.get(trip_id, ()))
                merged.update(successors)
                feasible_connections[trip_id] = tuple(sorted(merged))

        baseline = baseline_plan or self._build_baseline_plan(context)
        return CanonicalOptimizationProblem(
            scenario=OptimizationScenario(
                scenario_id=scenario_id,
                horizon_start=self._min_hhmm(context),
                horizon_end=self._max_hhmm(context),
                timestep_min=30,
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
                "max_start_fragments_per_vehicle": int(max(1, max_start_fragments_per_vehicle)),
                "max_end_fragments_per_vehicle": int(max(1, max_end_fragments_per_vehicle)),
                "initial_soc_percent": initial_soc_percent,
                "final_soc_floor_percent": final_soc_floor_percent,
            },
        )

    def _build_graph(
        self,
        context: DispatchContext,
        vehicle_type: str,
    ) -> Dict[str, List[str]]:
        return ConnectionGraphBuilder().build(context, vehicle_type)

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
        vehicle_profiles = self._build_vehicle_profiles(vehicles)

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
                    distance_km=float(row.get("distance_km") or 0.0),
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
                travel_time_min=max(1, int(metric.travel_time_min)),
            )
            for key, metric in deadhead_metrics.items()
        }

        service_date = str((scenario.get("meta") or {}).get("updatedAt") or "2026-01-01")[:10]
        default_turnaround_min = int(
            ((scenario.get("simulation_config") or {}).get("default_turnaround_min")) or 10
        )
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
    ) -> Iterable[ProblemVehicle]:
        for vehicle_type, profile in profiles.items():
            count = vehicle_counts.get(vehicle_type, self.default_vehicle_count_per_type)
            for idx in range(count):
                yield ProblemVehicle(
                    vehicle_id=f"{vehicle_type}_{idx + 1:03d}",
                    vehicle_type=vehicle_type,
                    home_depot_id="depot_default",
                    initial_soc=profile.battery_capacity_kwh,
                    battery_capacity_kwh=profile.battery_capacity_kwh,
                    reserve_soc=profile.battery_capacity_kwh * 0.1
                    if profile.battery_capacity_kwh
                    else None,
                    fuel_consumption_l_per_km=profile.fuel_consumption_l_per_km,
                    fixed_use_cost_jpy=profile.fixed_use_cost_jpy,
                )

    def _build_vehicle_profiles(
        self,
        vehicles: Sequence[Dict[str, Any]],
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
            
            # Compute daily fixed use cost
            purchase_cost = self._safe_float(vehicle.get("acquisitionCost")) or 0.0
            residual_value = self._safe_float(vehicle.get("residualValueYen") or vehicle.get("residual_value_yen")) or 0.0
            lifetime_year = max(self._safe_float(vehicle.get("lifetimeYear") or vehicle.get("lifetime_year")) or 12.0, 1.0)
            operation_days = max(self._safe_float(vehicle.get("operationDaysPerYear") or vehicle.get("operation_days_per_year")) or 365.0, 1.0)
            fixed_use_cost_jpy = (purchase_cost - residual_value) / (lifetime_year * operation_days)

            profiles.setdefault(
                vehicle_type,
                VehicleProfile(
                    vehicle_type=vehicle_type,
                    battery_capacity_kwh=self._safe_float(vehicle.get("batteryKwh")),
                    energy_consumption_kwh_per_km=self._safe_float(vehicle.get("energyConsumption")),
                    fuel_tank_capacity_l=self._safe_float(vehicle.get("fuelTankL")),
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
                    fuel_consumption_l_per_km=profile.fuel_consumption_l_per_km,
                    fixed_use_cost_jpy=profile.fixed_use_cost_jpy,
                )
            )
        return tuple(items)

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
        return distance_km * bev.energy_consumption_kwh_per_km

    def _estimate_trip_fuel(self, distance_km: float, context: DispatchContext) -> float:
        fuel_rates = [
            profile.fuel_consumption_l_per_km
            for profile in context.vehicle_profiles.values()
            if profile.fuel_consumption_l_per_km is not None and profile.fuel_consumption_l_per_km > 0
        ]
        if not fuel_rates:
            return 0.0
        return distance_km * min(fuel_rates)

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
            generated_slots = list(self._build_time_slot_prices(context, ()))
            if tou_bands or default_buy > 0.0 or default_sell > 0.0 or default_co2 > 0.0 or demand_weight > 0.0:
                start_min = min((trip.departure_min for trip in context.trips), default=0)
                expanded: List[EnergyPriceSlot] = []
                for slot in generated_slots:
                    minute_of_day = (start_min + slot.slot_index * 30) % (24 * 60)
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
                num_periods=max(1, len(list(self._build_time_slot_prices(context, ())))),
                delta_t_min=30.0,
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
        return tuple(self._build_time_slot_prices(context, ()))

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
    ) -> Iterable[EnergyPriceSlot]:
        if price_slots:
            return price_slots
        start = min(trip.departure_min for trip in context.trips) if context.trips else 0
        end = max(trip.arrival_min for trip in context.trips) if context.trips else 0
        slot_index = 0
        generated: List[EnergyPriceSlot] = []
        for minute in range(start, end + 30, 30):
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
    ) -> Iterable[PVSlot]:
        if pv_slots:
            return pv_slots
        return [
            PVSlot(
                slot_index=slot.slot_index,
                pv_available_kw=40.0 if 10 <= slot.slot_index <= 18 else 0.0,
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
