from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Iterable, List, Optional

from src.data_schema import (
    Charger,
    ElectricityPrice,
    PVProfile,
    ProblemData,
    Site,
    Task,
    Vehicle,
)
from src.dispatch.problemdata_adapter import build_travel_connections_via_dispatch
from src.preprocess.trip_converter import (
    build_vehicle_charger_compat,
    build_vehicle_task_compat,
)
from src.schemas.duty_entities import DutyLeg, VehicleDuty


@dataclass
class ScenarioBuildReport:
    scenario_id: str
    depot_id: str
    service_id: str
    trip_count: int = 0
    graph_edge_count: int = 0
    duty_count: int = 0
    task_count: int = 0
    travel_connection_count: int = 0
    vehicle_count: int = 0
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _as_list(value: Any) -> List[Any]:
    return list(value or [])


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        if value is None or value == "":
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _hhmm_to_idx(time_str: str, start_time: str, delta_t_min: float) -> int:
    h, m = str(time_str).split(":")
    sh, sm = str(start_time).split(":")
    mins = int(h) * 60 + int(m)
    start_mins = int(sh) * 60 + int(sm)
    if mins < start_mins:
        mins += 24 * 60
    return max(0, int((mins - start_mins) / delta_t_min))


def _normalize_soc_value(
    raw_value: Any,
    battery_kwh: Optional[float],
    default_ratio: Optional[float] = None,
) -> Optional[float]:
    if battery_kwh is None:
        return None
    if raw_value is None:
        return battery_kwh * default_ratio if default_ratio is not None else None
    value = _safe_float(raw_value, 0.0)
    if 0.0 <= value <= 1.0:
        return battery_kwh * value
    return value


def _filter_rows_for_scope(
    scenario: Dict[str, Any],
    depot_id: str,
    service_id: str,
) -> List[Dict[str, Any]]:
    allowed_route_ids = {
        str(item.get("routeId"))
        for item in _as_list(scenario.get("depot_route_permissions"))
        if item.get("depotId") == depot_id and item.get("allowed") is True
    }
    timetable_rows = [
        row
        for row in _as_list(scenario.get("timetable_rows"))
        if row.get("service_id", "WEEKDAY") == service_id
    ]
    if allowed_route_ids:
        timetable_rows = [
            row for row in timetable_rows if str(row.get("route_id")) in allowed_route_ids
        ]
    return timetable_rows


def _route_allowed_vehicle_types(
    scenario: Dict[str, Any],
    depot_id: str,
    route_id: str,
    depot_vehicles: List[Dict[str, Any]],
) -> Optional[set[str]]:
    if not depot_vehicles:
        return None
    permissions = {
        (str(item.get("vehicleId")), str(item.get("routeId"))): bool(item.get("allowed"))
        for item in _as_list(scenario.get("vehicle_route_permissions"))
        if item.get("vehicleId") is not None and item.get("routeId") is not None
    }
    allowed_types: set[str] = set()
    for vehicle in depot_vehicles:
        vehicle_id = vehicle.get("id")
        if vehicle_id is None:
            continue
        if permissions.get((str(vehicle_id), route_id), True):
            allowed_types.add(str(vehicle.get("type") or "BEV"))
    return allowed_types


def _normalize_trip_allowed_types(
    trip_like: Dict[str, Any],
    route_allowed_types: Optional[set[str]],
) -> List[str]:
    allowed = [str(item) for item in trip_like.get("allowed_vehicle_types", ["BEV", "ICE"])]
    if route_allowed_types is None:
        return allowed
    return [item for item in allowed if item in route_allowed_types]


def _collect_trips_for_scope(
    scenario: Dict[str, Any],
    depot_id: str,
    service_id: str,
) -> List[Dict[str, Any]]:
    depot_vehicles = [
        vehicle
        for vehicle in _as_list(scenario.get("vehicles"))
        if vehicle.get("depotId") == depot_id
    ]
    prebuilt_trips = [
        trip
        for trip in _as_list(scenario.get("trips"))
        if str(trip.get("route_id", "")) in {
            str(row.get("route_id")) for row in _filter_rows_for_scope(scenario, depot_id, service_id)
        }
    ]
    trips_source = prebuilt_trips or _filter_rows_for_scope(scenario, depot_id, service_id)
    trips: List[Dict[str, Any]] = []
    for index, item in enumerate(trips_source):
        route_id = str(item.get("route_id") or "")
        route_allowed_types = _route_allowed_vehicle_types(
            scenario,
            depot_id,
            route_id,
            depot_vehicles,
        )
        allowed_types = _normalize_trip_allowed_types(item, route_allowed_types)
        if not allowed_types:
            continue
        trips.append(
            {
                "trip_id": str(
                    item.get("trip_id")
                    or f"trip_{route_id}_{item.get('direction', 'out')}_{index:03d}"
                ),
                "route_id": route_id,
                "origin": str(item.get("origin")),
                "destination": str(item.get("destination")),
                "departure": str(item.get("departure")),
                "arrival": str(item.get("arrival")),
                "distance_km": _safe_float(item.get("distance_km"), 0.0),
                "allowed_vehicle_types": allowed_types,
            }
        )
    return trips


def _vehicles_for_scope(
    scenario: Dict[str, Any],
    depot_id: str,
) -> List[Dict[str, Any]]:
    return [
        vehicle
        for vehicle in _as_list(scenario.get("vehicles"))
        if vehicle.get("depotId") == depot_id
    ]


def _build_vehicle(vehicle_like: Dict[str, Any]) -> Vehicle:
    vehicle_type = str(vehicle_like.get("type") or "BEV").upper()
    battery_kwh = _safe_float(vehicle_like.get("batteryKwh"), 0.0) or None
    return Vehicle(
        vehicle_id=str(vehicle_like.get("id")),
        vehicle_type=vehicle_type,
        home_depot=str(vehicle_like.get("depotId") or ""),
        battery_capacity=battery_kwh,
        soc_init=_normalize_soc_value(vehicle_like.get("initialSoc"), battery_kwh, 0.8),
        soc_min=_normalize_soc_value(vehicle_like.get("minSoc"), battery_kwh, 0.15),
        soc_max=_normalize_soc_value(vehicle_like.get("maxSoc"), battery_kwh, 0.9),
        soc_target_end=_normalize_soc_value(
            vehicle_like.get("targetEndSoc"), battery_kwh, 0.6
        ),
        charge_power_max=_safe_float(vehicle_like.get("chargePowerKw"), 0.0) or None,
        fuel_tank_capacity=_safe_float(vehicle_like.get("fuelTankL"), 0.0) or None,
        fixed_use_cost=_safe_float(vehicle_like.get("acquisitionCost"), 0.0),
        max_distance=_safe_float(vehicle_like.get("maxDistanceKm"), 9999.0),
    )


def _mean_consumption(
    vehicles: Iterable[Dict[str, Any]],
    vehicle_type: str,
    fallback: float,
) -> float:
    values = [
        _safe_float(item.get("energyConsumption"), 0.0)
        for item in vehicles
        if str(item.get("type") or "").upper() == vehicle_type and item.get("energyConsumption") is not None
    ]
    return sum(values) / len(values) if values else fallback


def _build_tasks(
    trips: List[Dict[str, Any]],
    scenario_vehicles: List[Dict[str, Any]],
    start_time: str,
    delta_t_min: float,
) -> List[Task]:
    bev_rate = _mean_consumption(scenario_vehicles, "BEV", 1.2)
    ice_rate = _mean_consumption(scenario_vehicles, "ICE", 0.4)
    tasks: List[Task] = []
    for trip in trips:
        start_idx = _hhmm_to_idx(trip["departure"], start_time, delta_t_min)
        end_idx = _hhmm_to_idx(trip["arrival"], start_time, delta_t_min)
        if end_idx <= start_idx:
            end_idx = start_idx + 1
        allowed_types = [item.upper() for item in trip["allowed_vehicle_types"]]
        required_vehicle_type = allowed_types[0] if len(allowed_types) == 1 else None
        tasks.append(
            Task(
                task_id=trip["trip_id"],
                start_time_idx=start_idx,
                end_time_idx=end_idx,
                origin=trip["origin"],
                destination=trip["destination"],
                distance_km=trip["distance_km"],
                energy_required_kwh_bev=trip["distance_km"] * bev_rate,
                fuel_required_liter_ice=trip["distance_km"] * ice_rate,
                required_vehicle_type=required_vehicle_type,
                demand_cover=True,
                penalty_unserved=10000.0,
            )
        )
    return tasks


def _build_sites(scenario: Dict[str, Any], depot_id: str) -> List[Site]:
    sites: Dict[str, Site] = {}
    for depot in _as_list(scenario.get("depots")):
        site_id = str(depot.get("id"))
        sites[site_id] = Site(
            site_id=site_id,
            site_type="depot",
            grid_import_limit_kw=_safe_float(
                depot.get("gridImportLimitKw", depot.get("grid_import_limit_kw")),
                9999.0,
            ),
            contract_demand_limit_kw=_safe_float(
                depot.get("contractDemandLimitKw", depot.get("contract_demand_limit_kw")),
                9999.0,
            ),
            site_transformer_limit_kw=_safe_float(
                depot.get("transformerLimitKw", depot.get("site_transformer_limit_kw")),
                9999.0,
            ),
        )

    for site in _as_list(scenario.get("charger_sites")):
        site_id = str(site.get("id") or site.get("site_id"))
        if not site_id:
            continue
        sites[site_id] = Site(
            site_id=site_id,
            site_type=str(site.get("site_type") or "charge_only"),
            grid_import_limit_kw=_safe_float(site.get("grid_import_limit_kw"), 9999.0),
            contract_demand_limit_kw=_safe_float(
                site.get("contract_demand_limit_kw"),
                9999.0,
            ),
            site_transformer_limit_kw=_safe_float(
                site.get("site_transformer_limit_kw"),
                9999.0,
            ),
        )

    if depot_id not in sites:
        sites[depot_id] = Site(site_id=depot_id, site_type="depot")
    return list(sites.values())


def _build_chargers(scenario: Dict[str, Any]) -> List[Charger]:
    chargers: List[Charger] = []
    for item in _as_list(scenario.get("chargers")):
        charger_id = str(item.get("id") or item.get("charger_id") or "")
        site_id = str(item.get("siteId") or item.get("site_id") or "")
        if not charger_id or not site_id:
            continue
        chargers.append(
            Charger(
                charger_id=charger_id,
                site_id=site_id,
                power_max_kw=_safe_float(item.get("powerKw", item.get("power_max_kw")), 0.0),
                efficiency=_safe_float(item.get("efficiency"), 0.95),
                power_min_kw=_safe_float(item.get("power_min_kw"), 0.0),
            )
        )
    return chargers


def _expand_profile_rows(
    items: List[Dict[str, Any]],
    value_key: str,
) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for item in items:
        site_id = str(item.get("site_id") or item.get("siteId") or "")
        if not site_id:
            continue
        if item.get("time_idx") is not None:
            rows.append(item)
            continue
        values = item.get("values")
        if isinstance(values, list):
            for idx, value in enumerate(values):
                rows.append({"site_id": site_id, "time_idx": idx, value_key: value})
    return rows


def _build_pv_profiles(scenario: Dict[str, Any]) -> List[PVProfile]:
    rows = _expand_profile_rows(_as_list(scenario.get("pv_profiles")), "pv_generation_kw")
    return [
        PVProfile(
            site_id=str(row.get("site_id") or row.get("siteId")),
            time_idx=_safe_int(row.get("time_idx"), 0),
            pv_generation_kw=_safe_float(
                row.get("pv_generation_kw", row.get("value")),
                0.0,
            ),
        )
        for row in rows
    ]


def _build_electricity_prices(scenario: Dict[str, Any]) -> List[ElectricityPrice]:
    rows = _expand_profile_rows(
        _as_list(scenario.get("energy_price_profiles")),
        "grid_energy_price",
    )
    prices: List[ElectricityPrice] = []
    for row in rows:
        site_id = str(row.get("site_id") or row.get("siteId") or "")
        if not site_id:
            continue
        prices.append(
            ElectricityPrice(
                site_id=site_id,
                time_idx=_safe_int(row.get("time_idx"), 0),
                grid_energy_price=_safe_float(
                    row.get("grid_energy_price", row.get("value")),
                    0.0,
                ),
                sell_back_price=_safe_float(row.get("sell_back_price"), 0.0),
                base_load_kw=_safe_float(row.get("base_load_kw"), 0.0),
            )
        )
    return prices


def _build_turnaround_rules(scenario: Dict[str, Any]) -> Dict[str, int]:
    return {
        str(item.get("stop_id")): max(0, _safe_int(item.get("min_turnaround_min"), 0))
        for item in _as_list(scenario.get("turnaround_rules"))
        if item.get("stop_id") is not None
    }


def _build_deadhead_rules(scenario: Dict[str, Any]) -> Dict[tuple[str, str], int]:
    rules: Dict[tuple[str, str], int] = {}
    for item in _as_list(scenario.get("deadhead_rules")):
        from_stop = item.get("from_stop")
        to_stop = item.get("to_stop")
        if from_stop is None or to_stop is None:
            continue
        rules[(str(from_stop), str(to_stop))] = max(
            1,
            _safe_int(item.get("travel_time_min"), 1),
        )
    return rules


def _build_duty_entities(
    duties_raw: List[Dict[str, Any]],
    depot_id: str,
    service_id: str,
) -> List[VehicleDuty]:
    duties: List[VehicleDuty] = []
    service_day_type = "weekday" if service_id == "WEEKDAY" else service_id.lower()
    for duty_raw in duties_raw:
        legs: List[DutyLeg] = []
        for index, leg_raw in enumerate(_as_list(duty_raw.get("legs"))):
            trip_raw = leg_raw.get("trip") or {}
            legs.append(
                DutyLeg(
                    leg_index=index,
                    leg_type="revenue",
                    trip_id=str(trip_raw.get("trip_id") or ""),
                    from_location_id=trip_raw.get("origin"),
                    to_location_id=trip_raw.get("destination"),
                    start_time=trip_raw.get("departure"),
                    end_time=trip_raw.get("arrival"),
                    duration_min=max(
                        0.0,
                        _hhmm_to_idx(
                            str(trip_raw.get("arrival", "00:00")),
                            str(trip_raw.get("departure", "00:00")),
                            1.0,
                        ),
                    ),
                    distance_km=_safe_float(trip_raw.get("distance_km"), 0.0),
                )
            )
        duty = VehicleDuty(
            duty_id=str(duty_raw.get("duty_id")),
            duty_name=str(duty_raw.get("duty_id") or ""),
            route_id=None,
            depot_id=depot_id,
            service_day_type=service_day_type,
            required_vehicle_type=str(duty_raw.get("vehicle_type") or ""),
            legs=legs,
        )
        duty.compute_summary()
        duties.append(duty)
    return duties


def build_problem_data_from_scenario(
    scenario: Dict[str, Any],
    depot_id: str,
    service_id: str,
    mode: str,
    use_existing_duties: bool = False,
) -> tuple[ProblemData, ScenarioBuildReport]:
    meta = scenario.get("meta") or {}
    simulation_cfg = scenario.get("simulation_config") or {}
    start_time = str(simulation_cfg.get("start_time") or "05:00")
    delta_t_min = _safe_float(simulation_cfg.get("time_step_min"), 15.0)
    delta_t_hour = delta_t_min / 60.0
    planning_horizon_hours = _safe_float(
        simulation_cfg.get("planning_horizon_hours"),
        16.0,
    )
    default_turnaround_min = _safe_int(
        simulation_cfg.get("default_turnaround_min"),
        10,
    )

    trips = _collect_trips_for_scope(scenario, depot_id, service_id)
    scope_vehicles_raw = _vehicles_for_scope(scenario, depot_id)
    vehicles = [_build_vehicle(item) for item in scope_vehicles_raw]
    tasks = _build_tasks(trips, scope_vehicles_raw, start_time, delta_t_min)
    num_periods = max(
        _safe_int(simulation_cfg.get("num_periods"), 0),
        max((task.end_time_idx for task in tasks), default=0) + 2,
        int(math.ceil(planning_horizon_hours / delta_t_hour)),
    )
    sites = _build_sites(scenario, depot_id)
    chargers = _build_chargers(scenario)
    pv_profiles = _build_pv_profiles(scenario)
    electricity_prices = _build_electricity_prices(scenario)

    data = ProblemData(
        vehicles=vehicles,
        tasks=tasks,
        chargers=chargers,
        sites=sites,
        pv_profiles=pv_profiles,
        electricity_prices=electricity_prices,
        num_periods=num_periods,
        delta_t_hour=delta_t_hour,
        planning_horizon_hours=planning_horizon_hours,
        enable_pv=bool(pv_profiles),
        enable_demand_charge=bool(electricity_prices),
    )

    connections, dispatch_report = build_travel_connections_via_dispatch(
        data=data,
        service_date=str(meta.get("updatedAt") or "2026-01-01")[:10],
        default_turnaround_min=default_turnaround_min,
        turnaround_rules=_build_turnaround_rules(scenario),
        deadhead_rules=_build_deadhead_rules(scenario),
    )
    data.travel_connections = connections
    data.vehicle_task_compat = build_vehicle_task_compat(vehicles, tasks)
    data.vehicle_charger_compat = build_vehicle_charger_compat(vehicles, chargers)

    if use_existing_duties and scenario.get("duties"):
        duties = _build_duty_entities(_as_list(scenario.get("duties")), depot_id, service_id)
        if duties:
            data.duty_assignment_enabled = mode == "mode_duty_constrained"
            data.duty_list = duties
            data.duty_trip_mapping = {duty.duty_id: duty.trip_ids for duty in duties}

    report = ScenarioBuildReport(
        scenario_id=str(meta.get("id") or ""),
        depot_id=depot_id,
        service_id=service_id,
        trip_count=len(trips),
        graph_edge_count=dispatch_report.edge_count,
        duty_count=len(_as_list(scenario.get("duties"))),
        task_count=len(tasks),
        travel_connection_count=len(connections),
        vehicle_count=len(vehicles),
    )
    if not vehicles:
        report.errors.append("No vehicles found for selected depot.")
    if not tasks:
        report.errors.append("No tasks could be built for selected scope.")
    if not data.travel_connections and tasks:
        report.warnings.append("No travel connections generated.")

    setattr(
        data,
        "_dispatch_preprocess_report",
        {
            "source": "scenario_to_problemdata",
            "trip_count": report.trip_count,
            "edge_count": report.graph_edge_count,
            "generated_connections": report.travel_connection_count,
            "vehicle_types": tuple(sorted({vehicle.vehicle_type for vehicle in vehicles})),
            "warnings": tuple(report.warnings),
        },
    )
    return data, report
