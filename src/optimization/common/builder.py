from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from src.dispatch.dispatcher import DispatchGenerator
from src.dispatch.graph_builder import ConnectionGraphBuilder
from src.dispatch.models import (
    DeadheadRule,
    DispatchContext,
    Trip,
    TurnaroundRule,
    VehicleDuty,
    VehicleProfile,
    hhmm_to_min,
)
from src.preprocess.tariff_loader import build_electricity_prices_from_tariff, load_tariff_csv

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
        return self.build_from_dispatch(
            context,
            scenario_id=str((scenario.get("meta") or {}).get("id") or ""),
            config=config,
            vehicle_counts=vehicle_counts,
            chargers=chargers,
            price_slots=price_slots,
            pv_slots=pv_slots,
            objective_weights=weights,
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
    ) -> CanonicalOptimizationProblem:
        config = config or OptimizationConfig()
        vehicle_counts = vehicle_counts or {}
        trip_nodes = tuple(
            ProblemTrip(
                trip_id=trip.trip_id,
                route_id=trip.route_id,
                origin=trip.origin,
                destination=trip.destination,
                departure_min=trip.departure_min,
                arrival_min=trip.arrival_min,
                distance_km=trip.distance_km,
                allowed_vehicle_types=trip.allowed_vehicle_types,
                energy_kwh=self._estimate_trip_energy(trip.distance_km, context),
                service_id=context.service_date,
            )
            for trip in context.trips
        )
        route_nodes = self._build_routes(trip_nodes)
        vehicle_types = self._build_vehicle_types(context.vehicle_profiles)
        vehicles = tuple(
            self._build_vehicles(
                context.vehicle_profiles,
                vehicle_counts,
            )
        )
        depots = (
            ProblemDepot(
                depot_id="depot_default",
                name="Default Depot",
                charger_ids=tuple(charger.charger_id for charger in chargers),
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

        baseline = self._build_baseline_plan(context)
        return CanonicalOptimizationProblem(
            scenario=OptimizationScenario(
                scenario_id=scenario_id,
                horizon_start=self._min_hhmm(context),
                horizon_end=self._max_hhmm(context),
                timestep_min=30,
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
        trips: List[Trip] = []
        for row in scenario.get("timetable_rows") or []:
            if row.get("service_id") != service_id:
                continue
            route_id = str(row.get("route_id") or "")
            if allowed_route_ids is not None and route_id not in allowed_route_ids:
                continue
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
        deadhead_rules = {
            (str(item.get("from_stop")), str(item.get("to_stop"))): DeadheadRule(
                from_stop=str(item.get("from_stop")),
                to_stop=str(item.get("to_stop")),
                travel_time_min=max(1, int(item.get("travel_time_min") or 1)),
            )
            for item in scenario.get("deadhead_rules") or []
            if item.get("from_stop") is not None and item.get("to_stop") is not None
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
                )

    def _build_vehicle_profiles(
        self,
        vehicles: Sequence[Dict[str, Any]],
    ) -> Dict[str, VehicleProfile]:
        profiles: Dict[str, VehicleProfile] = {}
        for vehicle in vehicles:
            vehicle_type = str(vehicle.get("type") or "BEV").upper()
            profiles.setdefault(
                vehicle_type,
                VehicleProfile(
                    vehicle_type=vehicle_type,
                    battery_capacity_kwh=self._safe_float(vehicle.get("batteryKwh")),
                    energy_consumption_kwh_per_km=self._safe_float(vehicle.get("energyConsumption")),
                    fuel_tank_capacity_l=self._safe_float(vehicle.get("fuelTankL")),
                    fuel_consumption_l_per_km=self._safe_float(vehicle.get("energyConsumption")),
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
                )
            )
        return tuple(items)

    def _build_baseline_plan(self, context: DispatchContext) -> AssignmentPlan:
        duties: List[VehicleDuty] = []
        served_trip_ids: List[str] = []
        dispatcher = DispatchGenerator()
        for vehicle_type in context.vehicle_profiles:
            vt_duties = dispatcher.generate_greedy_duties(context, vehicle_type)
            duties.extend(vt_duties)
            for duty in vt_duties:
                served_trip_ids.extend(duty.trip_ids)
        all_trip_ids = {trip.trip_id for trip in context.trips}
        return AssignmentPlan(
            duties=tuple(duties),
            charging_slots=(),
            served_trip_ids=tuple(sorted(set(served_trip_ids))),
            unserved_trip_ids=tuple(sorted(all_trip_ids - set(served_trip_ids))),
            metadata={"source": "dispatch_greedy_baseline"},
        )

    def _estimate_trip_energy(self, distance_km: float, context: DispatchContext) -> float:
        bev = context.vehicle_profiles.get("BEV")
        if not bev or bev.energy_consumption_kwh_per_km is None:
            return 0.0
        return distance_km * bev.energy_consumption_kwh_per_km

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
                            )
                        )
                elif item.get("time_idx") is not None:
                    expanded.append(
                        EnergyPriceSlot(
                            slot_index=int(item.get("time_idx") or 0),
                            grid_buy_yen_per_kwh=float(item.get("grid_energy_price") or item.get("value") or 0.0),
                            grid_sell_yen_per_kwh=float(item.get("sell_back_price") or 0.0),
                            demand_charge_weight=float(item.get("demand_charge_weight") or 0.0),
                        )
                    )
            if expanded:
                return tuple(sorted(expanded, key=lambda slot: slot.slot_index))

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
                num_periods=max(1, len(self._build_time_slot_prices(context, ()))),
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
        objective_weights = (scenario.get("simulation_config") or {}).get("objective_weights") or {}
        return OptimizationObjectiveWeights(
            energy=float(objective_weights.get("electricity_cost", 1.0)),
            demand=float(objective_weights.get("demand_charge_cost", 1.0)),
            vehicle=float(objective_weights.get("vehicle_fixed_cost", 1.0)),
            unserved=float(objective_weights.get("unserved_penalty", 10000.0)),
            deviation=float(objective_weights.get("deviation_cost", 0.0)),
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
