from __future__ import annotations

import json
import logging
import math
from pathlib import Path
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Tuple

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
from src.objective_modes import (
    effective_co2_price_per_kg,
    legacy_objective_weights_for_mode,
    normalize_objective_mode,
)
from src.preprocess.trip_converter import (
    build_vehicle_charger_compat,
    build_vehicle_task_compat,
)
from src.route_family_runtime import (
    DeadheadMetric,
    merge_deadhead_metrics,
    normalize_direction,
    normalize_variant_type,
    route_variant_bucket,
)
from src.schemas.duty_entities import DutyLeg, VehicleDuty
from src.route_code_utils import extract_route_series_from_candidates
from src.value_normalization import coerce_list
from bff.services.ice_vehicle_reference import apply_ice_reference_defaults
from bff.store import scenario_store


logger = logging.getLogger(__name__)


_DEFAULT_LIFETIME_YEAR = 12.0
_DEFAULT_OPERATION_DAYS_PER_YEAR = 300.0
_DEFAULT_RESIDUAL_VALUE_YEN = 0.0
_CATALOG_FAST_ROUTE_STOP_TIMES_DIR = (
    Path(__file__).resolve().parents[2]
    / "data"
    / "catalog-fast"
    / "tokyu_bus_data"
    / "route_stop_times"
)
_CATALOG_FAST_NORMALIZED_STOPS_PATH = (
    Path(__file__).resolve().parents[2]
    / "data"
    / "catalog-fast"
    / "normalized"
    / "stops.jsonl"
)


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
    return coerce_list(value)


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


def _normalize_direction(value: Any, default: str = "outbound") -> str:
    return normalize_direction(value, default=default)


def _normalize_variant_type(value: Any, *, direction: str = "outbound") -> str:
    return normalize_variant_type(value, direction=direction)


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
    
    # P0: SOC正規化のルール統一 (常に比率として解釈)
    if value > 1.0:
        logger.warning(f"SOC value {value} > 1.0. Assuming it is a percentage. Dividing by 100.")
        value = value / 100.0
        
    # 比率が 0~1 に収まるようにクリップ
    value = max(0.0, min(1.0, value))
    
    return battery_kwh * value


def _scenario_overlay_costs(scenario: Dict[str, Any]) -> Dict[str, Any]:
    overlay = scenario.get("scenario_overlay") or {}
    costs = overlay.get("cost_coefficients") or {}
    return dict(costs) if isinstance(costs, dict) else {}


def _scenario_overlay_solver(scenario: Dict[str, Any]) -> Dict[str, Any]:
    overlay = scenario.get("scenario_overlay") or {}
    solver = overlay.get("solver_config") or {}
    return dict(solver) if isinstance(solver, dict) else {}


def _dailyized_vehicle_cost(vehicle_like: Dict[str, Any]) -> float:
    purchase_cost = _safe_float(vehicle_like.get("acquisitionCost"), 0.0)
    residual_value = _safe_float(
        vehicle_like.get("residualValueYen", vehicle_like.get("residual_value_yen")),
        _DEFAULT_RESIDUAL_VALUE_YEN,
    )
    lifetime_year = max(
        _safe_float(
            vehicle_like.get("lifetimeYear", vehicle_like.get("lifetime_year")),
            _DEFAULT_LIFETIME_YEAR,
        ),
        1.0,
    )
    operation_days_per_year = max(
        _safe_float(
            vehicle_like.get(
                "operationDaysPerYear",
                vehicle_like.get("operation_days_per_year"),
            ),
            _DEFAULT_OPERATION_DAYS_PER_YEAR,
        ),
        1.0,
    )
    return max(0.0, purchase_cost - residual_value) / (lifetime_year * operation_days_per_year)


def _hhmm_to_minutes(time_str: str) -> int:
    parts = str(time_str or "").split(":")
    if len(parts) < 2:
        return 0
    try:
        hour = int(parts[0])
        minute = int(parts[1])
    except ValueError:
        return 0
    return max(0, hour * 60 + minute)


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius_km = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlon / 2) ** 2
    )
    return radius_km * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _build_stop_coord_lookup(scenario: Dict[str, Any]) -> Dict[str, Tuple[float, float]]:
    lookup: Dict[str, Tuple[float, float]] = {}
    for stop in _as_list(scenario.get("stops")):
        stop_id = str(stop.get("id") or stop.get("stop_id") or "").strip()
        if not stop_id:
            continue
        lat = _safe_float(stop.get("lat"), 0.0)
        lon = _safe_float(stop.get("lon"), 0.0)
        if lat == 0.0 and lon == 0.0:
            continue
        lookup[stop_id] = (lat, lon)
    return lookup


def _variant_distance_factor(trip_like: Dict[str, Any], route_like: Dict[str, Any]) -> float:
    direction = _normalize_direction(
        trip_like.get("direction")
        or trip_like.get("canonicalDirection")
        or trip_like.get("canonical_direction")
        or route_like.get("canonicalDirection")
        or route_like.get("canonical_direction")
        or "outbound"
    )
    variant = _normalize_variant_type(
        trip_like.get("routeVariantType")
        or trip_like.get("route_variant_type")
        or route_like.get("routeVariantType")
        or route_like.get("route_variant_type")
        or "unknown",
        direction=direction,
    )
    factors = {
        "main": 1.08,
        "short_turn": 1.12,
        "branch": 1.1,
        "depot": 1.15,
        "unknown": 1.1,
    }
    return float(factors.get(route_variant_bucket(variant, direction=direction), factors["unknown"]))


def _stop_sequence_from_trip_stop_times(trip_like: Dict[str, Any]) -> List[str]:
    raw_stop_times = _as_list(trip_like.get("stop_times") or trip_like.get("stopTimes"))
    if not raw_stop_times:
        return []
    ordered = sorted(raw_stop_times, key=lambda item: _safe_int((item or {}).get("stop_sequence"), 0))
    stop_ids: List[str] = []
    for row in ordered:
        if not isinstance(row, dict):
            continue
        stop_id = str(row.get("stop_id") or row.get("stopId") or "").strip()
        if stop_id:
            stop_ids.append(stop_id)
    return stop_ids


def _distance_from_stop_sequence_km(
    stop_ids: List[str],
    stop_coords: Dict[str, Tuple[float, float]],
    detour_factor: float,
) -> float:
    if len(stop_ids) < 2:
        return 0.0
    total = 0.0
    for idx in range(1, len(stop_ids)):
        prev_coords = stop_coords.get(stop_ids[idx - 1])
        curr_coords = stop_coords.get(stop_ids[idx])
        if not prev_coords or not curr_coords:
            continue
        total += _haversine_km(prev_coords[0], prev_coords[1], curr_coords[0], curr_coords[1])
    return total * max(detour_factor, 1.0)


def _estimate_distance_from_trip_stop_times_km(
    trip_like: Dict[str, Any],
    stop_coords: Dict[str, Tuple[float, float]],
    detour_factor: float,
) -> float:
    stop_ids = _stop_sequence_from_trip_stop_times(trip_like)
    return _distance_from_stop_sequence_km(stop_ids, stop_coords, detour_factor)


def _route_stop_sequence(route_like: Dict[str, Any]) -> List[str]:
    return [
        str(item)
        for item in coerce_list(route_like.get("stopSequence") or route_like.get("stop_sequence"))
        if str(item or "").strip()
    ]


def _estimate_route_distance_from_sequence_km(
    route_like: Dict[str, Any],
    stop_coords: Dict[str, Tuple[float, float]],
    detour_factor: float,
) -> float:
    return _distance_from_stop_sequence_km(_route_stop_sequence(route_like), stop_coords, detour_factor)


def _slot_price_from_tou(
    tou_bands: List[Dict[str, Any]],
    *,
    slot_index: int,
    delta_t_min: float,
    start_time: str,
    default_price: float,
) -> float:
    if not tou_bands:
        return default_price
    minute_of_day = (_hhmm_to_minutes(start_time) + int(round(slot_index * delta_t_min))) % (24 * 60)
    half_hour_index = minute_of_day // 30
    for band in tou_bands:
        start_hour = _safe_int(band.get("start_hour"), 0)
        end_hour = _safe_int(band.get("end_hour"), 48)
        if start_hour <= half_hour_index < end_hour:
            return _safe_float(band.get("price_per_kwh"), default_price)
    return default_price


def _objective_weights_from_scenario(scenario: Dict[str, Any]) -> Dict[str, float]:
    simulation_cfg = scenario.get("simulation_config") or {}
    overlay_solver = _scenario_overlay_solver(scenario)
    objective_mode = normalize_objective_mode(
        simulation_cfg.get("objective_mode")
        or overlay_solver.get("objective_mode")
        or "total_cost"
    )
    unserved_penalty = _safe_float(
        simulation_cfg.get("unserved_penalty", overlay_solver.get("unserved_penalty")),
        10000.0,
    )
    explicit_weights = (
        simulation_cfg.get("objective_weights")
        or overlay_solver.get("objective_weights")
        or {}
    )
    return legacy_objective_weights_for_mode(
        objective_mode=objective_mode,
        unserved_penalty=unserved_penalty,
        explicit_weights=explicit_weights if isinstance(explicit_weights, dict) else {},
    )


def _filter_rows_for_scope(
    scenario: Dict[str, Any],
    depot_id: str,
    service_id: str,
    analysis_scope: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    scope = dict(analysis_scope or scenario.get("dispatch_scope") or {})
    if not analysis_scope:
        scope.setdefault("depotId", depot_id)
        scope.setdefault("serviceId", service_id)
    temp_scenario_id = str((scenario.get("meta") or {}).get("id") or "")
    effective_route_ids = set(scope.get("effectiveRouteIds") or [])
    if temp_scenario_id and not effective_route_ids:
        temp_doc = dict(scenario)
        temp_doc["dispatch_scope"] = scope
        normalized_scope = scenario_store._normalize_dispatch_scope(temp_doc)
        effective_route_ids = set(normalized_scope.get("effectiveRouteIds") or [])
        scope = normalized_scope

    route_lookup = {
        str(route.get("id")): route
        for route in _as_list(scenario.get("routes"))
        if route.get("id") is not None
    }
    _vn_pattern = re.compile(r"__v\d+$")
    timetable_rows = [
        row
        for row in _as_list(scenario.get("timetable_rows"))
        if row.get("service_id", "WEEKDAY") == service_id
        and not _vn_pattern.search(str(row.get("trip_id") or ""))
    ]
    if effective_route_ids:
        timetable_rows = [
            row for row in timetable_rows if str(row.get("route_id")) in effective_route_ids
        ]
    trip_selection = dict(scope.get("tripSelection") or {})
    if trip_selection:
        filtered_rows: List[Dict[str, Any]] = []
        for row in timetable_rows:
            route = route_lookup.get(str(row.get("route_id")) or "") or {}
            variant_type = _normalize_variant_type(
                row.get("routeVariantType")
                or row.get("route_variant_type")
                or row.get("routeVariantTypeManual")
                or route.get("routeVariantTypeManual")
                or route.get("routeVariantType")
                or "unknown"
            )
            variant_bucket = route_variant_bucket(variant_type)
            if not trip_selection.get("includeShortTurn", True) and variant_bucket == "short_turn":
                continue
            if (
                not trip_selection.get("includeDepotMoves", True)
                and variant_bucket == "depot"
            ):
                continue
            filtered_rows.append(row)
        timetable_rows = filtered_rows
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


def _estimate_trip_distance_km(
    trip_like: Dict[str, Any],
    route_like: Dict[str, Any],
    stop_coords: Dict[str, Tuple[float, float]],
) -> float:
    detour_factor = _variant_distance_factor(trip_like, route_like)
    explicit_distance = _safe_float(trip_like.get("distance_km"), 0.0)
    if explicit_distance > 0.0:
        return explicit_distance

    stop_times_distance = _estimate_distance_from_trip_stop_times_km(
        trip_like,
        stop_coords,
        detour_factor,
    )
    if stop_times_distance > 0.0:
        return round(stop_times_distance, 4)

    base_distance = _safe_float(
        route_like.get("distanceKm", route_like.get("distance_km")),
        0.0,
    )
    if base_distance <= 0.0:
        base_distance = _estimate_route_distance_from_sequence_km(route_like, stop_coords, detour_factor)

    stop_sequence = _route_stop_sequence(route_like)
    origin_stop_id = str(trip_like.get("origin_stop_id") or "").strip()
    destination_stop_id = str(trip_like.get("destination_stop_id") or "").strip()
    if (
        base_distance > 0.0
        and origin_stop_id
        and destination_stop_id
        and len(stop_sequence) >= 2
        and origin_stop_id in stop_sequence
        and destination_stop_id in stop_sequence
    ):
        origin_idx = stop_sequence.index(origin_stop_id)
        destination_idx = stop_sequence.index(destination_stop_id)
        span = abs(destination_idx - origin_idx)
        total_span = max(len(stop_sequence) - 1, 1)
        if span > 0:
            return round(base_distance * (span / total_span), 4)
    if base_distance > 0.0:
        return round(base_distance, 4)

    origin_coords = stop_coords.get(origin_stop_id)
    destination_coords = stop_coords.get(destination_stop_id)
    if origin_coords and destination_coords:
        straight_km = _haversine_km(
            origin_coords[0],
            origin_coords[1],
            destination_coords[0],
            destination_coords[1],
        )
        if straight_km > 0.0:
            return round(straight_km * detour_factor, 4)
    return 0.0


def _collect_trips_for_scope(
    scenario: Dict[str, Any],
    depot_id: str,
    service_id: str,
    analysis_scope: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    scoped_rows = _filter_rows_for_scope(scenario, depot_id, service_id, analysis_scope)
    stop_coords = _build_stop_coord_lookup(scenario)
    scope = dict(analysis_scope or scenario.get("dispatch_scope") or {})
    effective_route_ids = {
        str(item)
        for item in scope.get("effectiveRouteIds") or []
        if str(item or "").strip()
    }
    route_selection = dict(scope.get("routeSelection") or {})
    if not effective_route_ids:
        effective_route_ids = {
            str(item)
            for item in route_selection.get("includeRouteIds") or []
            if str(item or "").strip()
        }
    depot_vehicles = [
        vehicle
        for vehicle in _as_list(scenario.get("vehicles"))
        if vehicle.get("depotId") == depot_id
    ]
    allowed_route_ids = {str(row.get("route_id")) for row in scoped_rows}
    if not allowed_route_ids and effective_route_ids:
        allowed_route_ids = set(effective_route_ids)
    scoped_rows_by_trip_id = {
        str(row.get("trip_id") or ""): dict(row)
        for row in scoped_rows
        if str(row.get("trip_id") or "").strip()
    }
    route_lookup = {
        str(route.get("id") or ""): dict(route)
        for route in _as_list(scenario.get("routes"))
        if str(route.get("id") or "").strip()
    }
    prebuilt_trips: List[Dict[str, Any]] = []
    for trip in _as_list(scenario.get("trips")):
        if allowed_route_ids and str(trip.get("route_id", "")) not in allowed_route_ids:
            continue
        trip_id = str(trip.get("trip_id") or "")
        merged_trip = dict(scoped_rows_by_trip_id.get(trip_id) or {})
        merged_trip.update(trip)
        prebuilt_trips.append(merged_trip)
    trips_source = prebuilt_trips or scoped_rows
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
        route_like = route_lookup.get(route_id) or {}
        route_series_code, route_series_prefix, route_series_number, _series_source = extract_route_series_from_candidates(
            str(item.get("routeSeriesCode") or item.get("route_series_code") or ""),
            str(route_like.get("routeCode") or ""),
            str(route_like.get("routeFamilyCode") or ""),
            str(route_like.get("routeLabel") or route_like.get("name") or ""),
        )
        trips.append(
            {
                "trip_id": str(
                    item.get("trip_id")
                    or f"trip_{route_id}_{item.get('direction', 'out')}_{index:03d}"
                ),
                "route_id": route_id,
                "direction": _normalize_direction(
                    item.get("direction")
                    or item.get("direction_id")
                    or item.get("canonicalDirection")
                    or item.get("canonical_direction")
                    or item.get("canonicalDirectionManual")
                    or route_like.get("canonicalDirectionManual")
                    or route_like.get("canonicalDirection")
                    or "outbound"
                ),
                "routeVariantType": _normalize_variant_type(
                    item.get("routeVariantType")
                    or item.get("route_variant_type")
                    or item.get("routeVariantTypeManual")
                    or route_like.get("routeVariantTypeManual")
                    or route_like.get("routeVariantType")
                    or "unknown",
                    direction=_normalize_direction(
                        item.get("direction")
                        or item.get("direction_id")
                        or item.get("canonicalDirection")
                        or item.get("canonical_direction")
                        or item.get("canonicalDirectionManual")
                        or route_like.get("canonicalDirectionManual")
                        or route_like.get("canonicalDirection")
                        or "outbound"
                    ),
                ),
                "routeFamilyCode": str(
                    item.get("routeFamilyCode")
                    or item.get("route_family_code")
                    or item.get("routeSeriesCode")
                    or item.get("route_series_code")
                    or route_like.get("routeFamilyCode")
                    or route_series_code
                    or ""
                ),
                "routeSeriesPrefix": route_series_prefix,
                "routeSeriesNumber": route_series_number,
                "origin": str(item.get("origin")),
                "destination": str(item.get("destination")),
                "origin_stop_id": str(item.get("origin_stop_id") or ""),
                "destination_stop_id": str(item.get("destination_stop_id") or ""),
                "departure": str(item.get("departure")),
                "arrival": str(item.get("arrival")),
                "distance_km": _estimate_trip_distance_km(item, route_like, stop_coords),
                "allowed_vehicle_types": allowed_types,
            }
        )
    zero_distance_count = sum(1 for trip in trips if _safe_float(trip.get("distance_km"), 0.0) <= 0.0)
    zero_distance_ratio = (zero_distance_count / len(trips)) if trips else 0.0
    if zero_distance_ratio >= 0.05:
        logger.warning(
            "Distance estimation audit: zero distance ratio is %.2f%% (%d/%d)",
            zero_distance_ratio * 100.0,
            zero_distance_count,
            len(trips),
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
    vehicle_like = apply_ice_reference_defaults(vehicle_like)
    vehicle_type = str(vehicle_like.get("type") or "BEV").upper()
    battery_kwh = _safe_float(vehicle_like.get("batteryKwh"), 0.0) or None
    fuel_cost_coeff = _safe_float(vehicle_like.get("fuelCostPerL"), 145.0)
    co2_emission_coeff = _safe_float(vehicle_like.get("co2EmissionKgPerL"), 2.58)
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
        fuel_cost_coeff=fuel_cost_coeff,
        co2_emission_coeff=co2_emission_coeff,
        fixed_use_cost=_dailyized_vehicle_cost(vehicle_like),
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
    service_id: str | None = None,
) -> List[Task]:
    # P1: タスクエネルギーフォールバック時の警告出力
    bev_values = [
        _safe_float(item.get("energyConsumption"), 0.0)
        for item in scenario_vehicles
        if str(item.get("type") or "").upper() == "BEV" and item.get("energyConsumption") is not None
    ]
    if not bev_values:
        logger.warning("No BEV energyConsumption found in scenario vehicles. Falling back to default BEV rate (1.2 kWh/km).")
    
    ice_values = [
        _safe_float(item.get("energyConsumption"), 0.0)
        for item in scenario_vehicles
        if str(item.get("type") or "").upper() == "ICE" and item.get("energyConsumption") is not None
    ]
    if not ice_values:
        logger.warning("No ICE energyConsumption found in scenario vehicles. Falling back to default ICE rate (0.4 L/km).")

    bev_rate = _mean_consumption(scenario_vehicles, "BEV", 1.2)
    ice_rate = _mean_consumption(scenario_vehicles, "ICE", 0.4)
    tasks: List[Task] = []
    trip_id_seen: Dict[str, int] = {}
    duplicate_trip_id_count = 0
    for trip in trips:
        start_idx = _hhmm_to_idx(trip["departure"], start_time, delta_t_min)
        end_idx = _hhmm_to_idx(trip["arrival"], start_time, delta_t_min)
        if end_idx <= start_idx:
            end_idx = start_idx + 1
        base_task_id = str(trip.get("trip_id") or "").strip()
        if not base_task_id:
            base_task_id = f"trip_{len(tasks):06d}"
        seen = trip_id_seen.get(base_task_id, 0)
        task_id = base_task_id if seen == 0 else f"{base_task_id}__dup{seen + 1}"
        trip_id_seen[base_task_id] = seen + 1
        if seen > 0:
            duplicate_trip_id_count += 1
        allowed_types = [item.upper() for item in trip["allowed_vehicle_types"]]
        required_vehicle_type = allowed_types[0] if len(allowed_types) == 1 else None
        tasks.append(
            Task(
                task_id=task_id,
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
                route_id=str(trip.get("route_id") or "") or None,
                direction=str(trip.get("direction") or "") or None,
                route_variant_type=str(trip.get("routeVariantType") or "") or None,
                route_family_code=str(trip.get("routeFamilyCode") or "") or None,
                route_series_prefix=str(trip.get("routeSeriesPrefix") or "") or None,
                route_series_number=_safe_int(trip.get("routeSeriesNumber"), default=0) or None,
                origin_stop_id=str(trip.get("origin_stop_id") or "") or None,
                destination_stop_id=str(trip.get("destination_stop_id") or "") or None,
                service_id=str(trip.get("service_id") or service_id or "") or None,
            )
        )
    if duplicate_trip_id_count > 0:
        logger.warning(
            "Detected %d duplicate trip_id values while building tasks; generated unique task_id suffixes.",
            duplicate_trip_id_count,
        )
    return tasks


def _graph_export_band_id(
    route_id: str,
    trip_like: Dict[str, Any],
    route_like: Dict[str, Any],
) -> str:
    route_series_code, _route_series_prefix, _route_series_number, _series_source = (
        extract_route_series_from_candidates(
            str(trip_like.get("routeSeriesCode") or trip_like.get("route_series_code") or ""),
            str(trip_like.get("routeFamilyCode") or trip_like.get("route_family_code") or ""),
            str(route_like.get("routeCode") or route_like.get("route_code") or ""),
            str(route_like.get("routeFamilyCode") or route_like.get("route_family_code") or ""),
            str(
                route_like.get("routeLabel")
                or route_like.get("route_label")
                or route_like.get("name")
                or route_id
                or ""
            ),
        )
    )
    return str(route_series_code or route_id or "").strip()


def _graph_export_stop_name_index(scenario: Dict[str, Any]) -> Dict[str, str]:
    stop_names: Dict[str, str] = {}
    for stop in _as_list(scenario.get("stops")):
        if not isinstance(stop, dict):
            continue
        stop_id = str(stop.get("id") or stop.get("stop_id") or stop.get("stopId") or "").strip()
        if not stop_id:
            continue
        stop_names[stop_id] = str(stop.get("name") or stop.get("stopName") or stop_id).strip() or stop_id
    return stop_names


def _load_catalog_fast_stop_names(stop_ids: Iterable[str]) -> Dict[str, str]:
    requested_ids = {
        str(stop_id or "").strip()
        for stop_id in stop_ids
        if str(stop_id or "").strip()
    }
    if not requested_ids or not _CATALOG_FAST_NORMALIZED_STOPS_PATH.exists():
        return {}

    resolved: Dict[str, str] = {}
    with _CATALOG_FAST_NORMALIZED_STOPS_PATH.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(row, dict):
                continue
            stop_id = str(row.get("id") or row.get("stop_id") or row.get("stopId") or "").strip()
            if not stop_id or stop_id not in requested_ids:
                continue
            stop_name = str(
                row.get("name")
                or row.get("stopName")
                or row.get("title")
                or stop_id
            ).strip() or stop_id
            resolved[stop_id] = stop_name
            if len(resolved) >= len(requested_ids):
                break
    return resolved


def _iter_graph_stop_time_rows(stop_timetables: List[Dict[str, Any]]) -> Iterable[Dict[str, Any]]:
    for raw_row in stop_timetables:
        if not isinstance(raw_row, dict):
            continue
        if isinstance(raw_row.get("items"), list):
            parent_stop_id = str(raw_row.get("stop_id") or raw_row.get("stopId") or "").strip()
            parent_stop_name = str(raw_row.get("stop_name") or raw_row.get("stopName") or parent_stop_id).strip()
            for entry in raw_row.get("items") or []:
                if not isinstance(entry, dict):
                    continue
                stop_id = str(entry.get("stop_id") or entry.get("stopId") or parent_stop_id).strip()
                trip_id = str(
                    entry.get("trip_id")
                    or entry.get("tripId")
                    or entry.get("busTimetable")
                    or ""
                ).strip()
                if not trip_id or not stop_id:
                    continue
                yield {
                    "trip_id": trip_id,
                    "stop_id": stop_id,
                    "stop_name": str(
                        entry.get("stop_name")
                        or entry.get("stopName")
                        or parent_stop_name
                        or stop_id
                    ).strip()
                    or stop_id,
                    "stop_sequence": _safe_int(
                        entry.get("stop_sequence")
                        or entry.get("sequence")
                        or entry.get("seq"),
                        0,
                    ),
                    "arrival_time": str(
                        entry.get("arrival_time")
                        or entry.get("arrivalTime")
                        or entry.get("arrival")
                        or ""
                    ).strip(),
                    "departure_time": str(
                        entry.get("departure_time")
                        or entry.get("departureTime")
                        or entry.get("departure")
                        or ""
                    ).strip(),
                }
            continue

        stop_id = str(raw_row.get("stop_id") or raw_row.get("stopId") or "").strip()
        trip_id = str(raw_row.get("trip_id") or raw_row.get("tripId") or "").strip()
        if not trip_id or not stop_id:
            continue
        yield {
            "trip_id": trip_id,
            "stop_id": stop_id,
            "stop_name": str(
                raw_row.get("stop_name")
                or raw_row.get("stopName")
                or stop_id
            ).strip()
            or stop_id,
            "stop_sequence": _safe_int(
                raw_row.get("stop_sequence")
                or raw_row.get("sequence")
                or raw_row.get("seq"),
                0,
            ),
            "arrival_time": str(
                raw_row.get("arrival_time")
                or raw_row.get("arrivalTime")
                or raw_row.get("arrival")
                or ""
            ).strip(),
            "departure_time": str(
                raw_row.get("departure_time")
                or raw_row.get("departureTime")
                or raw_row.get("departure")
                or ""
            ).strip(),
        }


def _dedupe_consecutive_labels(labels: Iterable[str]) -> List[str]:
    cleaned: List[str] = []
    for label in labels:
        normalized = str(label or "").strip()
        if not normalized:
            continue
        if cleaned and cleaned[-1] == normalized:
            continue
        cleaned.append(normalized)
    return cleaned


def _load_catalog_fast_stop_rows_by_trip_id(
    *,
    route_ids: set[str],
    trip_ids: set[str],
    service_ids: set[str],
) -> Dict[str, List[Dict[str, Any]]]:
    rows_by_trip_id: Dict[str, List[Dict[str, Any]]] = {}
    if not route_ids or not trip_ids:
        return rows_by_trip_id

    for route_id in sorted(route_ids):
        path = _CATALOG_FAST_ROUTE_STOP_TIMES_DIR / f"{route_id}.jsonl"
        if not path.exists():
            continue
        with path.open("r", encoding="utf-8") as handle:
            for raw_line in handle:
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                trip_id = str(row.get("trip_id") or "").strip()
                if not trip_id or trip_id not in trip_ids:
                    continue
                service_id = str(row.get("service_id") or "").strip()
                if service_ids and service_id and service_id not in service_ids:
                    continue
                stop_id = str(row.get("stop_id") or row.get("stopId") or "").strip()
                if not stop_id:
                    continue
                rows_by_trip_id.setdefault(trip_id, []).append(
                    {
                        "stop_id": stop_id,
                        "stop_name": str(
                            row.get("stop_name")
                            or row.get("stopName")
                            or stop_id
                        ).strip()
                        or stop_id,
                        "stop_sequence": _safe_int(
                            row.get("stop_sequence")
                            or row.get("sequence")
                            or row.get("seq"),
                            0,
                        ),
                        "arrival_time": str(
                            row.get("arrival_time")
                            or row.get("arrivalTime")
                            or row.get("arrival")
                            or ""
                        ).strip(),
                        "departure_time": str(
                            row.get("departure_time")
                            or row.get("departureTime")
                            or row.get("departure")
                            or ""
                        ).strip(),
                    }
                )
    for trip_id in list(rows_by_trip_id.keys()):
        rows_by_trip_id[trip_id].sort(
            key=lambda row: (
                _safe_int(row.get("stop_sequence"), 0),
                str(row.get("arrival_time") or row.get("departure_time") or ""),
                str(row.get("stop_name") or ""),
            )
        )
    return rows_by_trip_id


def _build_graph_export_context(
    scenario: Dict[str, Any],
    trips: List[Dict[str, Any]],
    tasks: List[Task],
) -> Dict[str, Any]:
    stop_name_by_id = _graph_export_stop_name_index(scenario)
    route_lookup = {
        str(route.get("id") or ""): dict(route)
        for route in _as_list(scenario.get("routes"))
        if isinstance(route, dict) and str(route.get("id") or "").strip()
    }
    route_stop_ids = {
        stop_id
        for route_like in route_lookup.values()
        for stop_id in _route_stop_sequence(route_like)
        if stop_id
    }
    missing_route_stop_ids = [
        stop_id
        for stop_id in route_stop_ids
        if stop_id not in stop_name_by_id
    ]
    if missing_route_stop_ids:
        stop_name_by_id.update(_load_catalog_fast_stop_names(missing_route_stop_ids))

    stop_rows_by_trip_id: Dict[str, List[Dict[str, Any]]] = {}
    for row in _iter_graph_stop_time_rows(_as_list(scenario.get("stop_timetables"))):
        trip_id = str(row.get("trip_id") or "").strip()
        if not trip_id:
            continue
        stop_id = str(row.get("stop_id") or "").strip()
        stop_name = str(row.get("stop_name") or stop_name_by_id.get(stop_id) or stop_id).strip() or stop_id
        if stop_id and stop_name and stop_id not in stop_name_by_id:
            stop_name_by_id[stop_id] = stop_name
        stop_rows_by_trip_id.setdefault(trip_id, []).append(
            {
                "stop_id": stop_id,
                "stop_name": stop_name,
                "stop_sequence": _safe_int(row.get("stop_sequence"), 0),
                "arrival_time": str(row.get("arrival_time") or "").strip(),
                "departure_time": str(row.get("departure_time") or "").strip(),
            }
        )

    for trip_id in list(stop_rows_by_trip_id.keys()):
        stop_rows_by_trip_id[trip_id].sort(
            key=lambda row: (
                _safe_int(row.get("stop_sequence"), 0),
                str(row.get("arrival_time") or row.get("departure_time") or ""),
                str(row.get("stop_name") or ""),
            )
        )

    requested_trip_ids = {
        str(trip.get("trip_id") or "").strip()
        for trip in trips
        if str(trip.get("trip_id") or "").strip()
    }
    missing_trip_ids = {
        trip_id
        for trip_id in requested_trip_ids
        if trip_id not in stop_rows_by_trip_id
    }
    if missing_trip_ids:
        catalog_rows_by_trip_id = _load_catalog_fast_stop_rows_by_trip_id(
            route_ids={
                str(trip.get("route_id") or "").strip()
                for trip in trips
                if str(trip.get("route_id") or "").strip()
            },
            trip_ids=missing_trip_ids,
            service_ids={
                str(trip.get("service_id") or "").strip()
                for trip in trips
                if str(trip.get("service_id") or "").strip()
            },
        )
        for trip_id, rows in catalog_rows_by_trip_id.items():
            if trip_id in stop_rows_by_trip_id or not rows:
                continue
            stop_rows_by_trip_id[trip_id] = rows
            for row in rows:
                stop_id = str(row.get("stop_id") or "").strip()
                stop_name = str(row.get("stop_name") or stop_id).strip() or stop_id
                if stop_id and stop_name and stop_id not in stop_name_by_id:
                    stop_name_by_id[stop_id] = stop_name

    band_stop_sequences: Dict[str, List[List[str]]] = {}
    band_labels_by_band_id: Dict[str, str] = {}
    for route_id, route_like in route_lookup.items():
        band_id = _graph_export_band_id(route_id, route_like, route_like)
        if not band_id:
            continue
        band_labels_by_band_id.setdefault(
            band_id,
            str(
                route_like.get("routeFamilyLabel")
                or route_like.get("routeLabel")
                or route_like.get("routeFamilyCode")
                or route_like.get("name")
                or band_id
            ).strip()
            or band_id,
        )
        sequence_labels = _dedupe_consecutive_labels(
            stop_name_by_id.get(stop_id, stop_id)
            for stop_id in _route_stop_sequence(route_like)
        )
        if len(sequence_labels) >= 2:
            band_stop_sequences.setdefault(band_id, []).append(sequence_labels)

    task_stop_sequences: Dict[str, List[Dict[str, Any]]] = {}
    for trip, task in zip(trips, tasks):
        task_id = str(task.task_id or "").strip()
        base_trip_id = str(trip.get("trip_id") or "").strip()
        route_id = str(trip.get("route_id") or "").strip()
        route_like = route_lookup.get(route_id) or {}
        band_id = _graph_export_band_id(route_id, trip, route_like)
        if band_id:
            band_labels_by_band_id.setdefault(
                band_id,
                str(
                    route_like.get("routeFamilyLabel")
                    or route_like.get("routeLabel")
                    or route_like.get("routeFamilyCode")
                    or trip.get("routeFamilyCode")
                    or band_id
                ).strip()
                or band_id,
            )
        stop_rows = list(stop_rows_by_trip_id.get(base_trip_id) or [])
        if not stop_rows or not task_id:
            continue
        normalized_points = [
            {
                "stop_id": str(row.get("stop_id") or "").strip(),
                "stop_label": str(
                    row.get("stop_name")
                    or stop_name_by_id.get(str(row.get("stop_id") or "").strip())
                    or row.get("stop_id")
                    or ""
                ).strip(),
                "stop_sequence": _safe_int(row.get("stop_sequence"), 0),
                "arrival_time": str(row.get("arrival_time") or "").strip(),
                "departure_time": str(row.get("departure_time") or "").strip(),
            }
            for row in stop_rows
        ]
        normalized_points = [
            row
            for row in normalized_points
            if str(row.get("stop_label") or "").strip()
        ]
        if not normalized_points:
            continue
        task_stop_sequences[task_id] = normalized_points
        if band_id:
            band_sequence = _dedupe_consecutive_labels(
                row.get("stop_label") or ""
                for row in normalized_points
            )
            if len(band_sequence) >= 2:
                band_stop_sequences.setdefault(band_id, []).append(band_sequence)

    return {
        "band_stop_sequences": band_stop_sequences,
        "task_stop_sequences": task_stop_sequences,
        "band_labels_by_band_id": band_labels_by_band_id,
        "planning_start_time": str(
            ((scenario.get("simulation_config") or {}).get("start_time")) or "05:00"
        ).strip()
        or "05:00",
    }


def _build_sites(scenario: Dict[str, Any], depot_id: str) -> List[Site]:
    sites: Dict[str, Site] = {}
    charging_cfg = ((scenario.get("scenario_overlay") or {}).get("charging_constraints") or {})
    depot_power_limit_kw = charging_cfg.get("depot_power_limit_kw")
    for depot in _as_list(scenario.get("depots")):
        site_id = str(depot.get("id"))
        sites[site_id] = Site(
            site_id=site_id,
            site_type="depot",
            grid_import_limit_kw=_safe_float(
                depot.get(
                    "gridImportLimitKw",
                    depot.get("grid_import_limit_kw", depot_power_limit_kw),
                ),
                9999.0,
            ),
            contract_demand_limit_kw=_safe_float(
                depot.get(
                    "contractDemandLimitKw",
                    depot.get("contract_demand_limit_kw", depot_power_limit_kw),
                ),
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
        sites[depot_id] = Site(
            site_id=depot_id,
            site_type="depot",
            grid_import_limit_kw=_safe_float(depot_power_limit_kw, 9999.0),
            contract_demand_limit_kw=_safe_float(depot_power_limit_kw, 9999.0),
        )
    elif depot_power_limit_kw is not None:
        site = sites[depot_id]
        sites[depot_id] = Site(
            site_id=site.site_id,
            site_type=site.site_type,
            grid_import_limit_kw=_safe_float(depot_power_limit_kw, site.grid_import_limit_kw),
            contract_demand_limit_kw=_safe_float(
                depot_power_limit_kw,
                site.contract_demand_limit_kw,
            ),
            site_transformer_limit_kw=site.site_transformer_limit_kw,
        )
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


def _build_electricity_prices(
    scenario: Dict[str, Any],
    *,
    site_ids: List[str],
    num_periods: int,
    delta_t_min: float,
    start_time: str,
) -> List[ElectricityPrice]:
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
                co2_factor=_safe_float(row.get("co2_factor"), 0.0),
            )
        )
    if prices:
        return prices

    cost_cfg = _scenario_overlay_costs(scenario)
    tou_bands = [
        dict(item)
        for item in _as_list(cost_cfg.get("tou_pricing"))
        if isinstance(item, dict)
    ]
    default_buy_price = _safe_float(cost_cfg.get("grid_flat_price_per_kwh"), 0.0)
    default_sell_price = _safe_float(cost_cfg.get("grid_sell_price_per_kwh"), 0.0)
    default_co2_factor = _safe_float(cost_cfg.get("grid_co2_kg_per_kwh"), 0.0)
    if not site_ids:
        site_ids = ["depot_default"]
    if not any(
        (
            tou_bands,
            default_buy_price > 0.0,
            default_sell_price > 0.0,
            default_co2_factor > 0.0,
            _safe_float(cost_cfg.get("demand_charge_cost_per_kw"), 0.0) > 0.0,
        )
    ):
        return prices
    for site_id in site_ids:
        for time_idx in range(max(num_periods, 0)):
            prices.append(
                ElectricityPrice(
                    site_id=site_id,
                    time_idx=time_idx,
                    grid_energy_price=_slot_price_from_tou(
                        tou_bands,
                        slot_index=time_idx,
                        delta_t_min=delta_t_min,
                        start_time=start_time,
                        default_price=default_buy_price,
                    ),
                    sell_back_price=default_sell_price,
                    base_load_kw=0.0,
                    co2_factor=default_co2_factor,
                )
            )
    return prices


def _build_turnaround_rules(scenario: Dict[str, Any]) -> Dict[str, int]:
    return {
        str(item.get("stop_id")): max(0, _safe_int(item.get("min_turnaround_min"), 0))
        for item in _as_list(scenario.get("turnaround_rules"))
        if item.get("stop_id") is not None
    }


def _build_deadhead_metrics(
    scenario: Dict[str, Any],
    trips: Optional[List[Dict[str, Any]]] = None,
) -> Dict[tuple[str, str], DeadheadMetric]:
    return merge_deadhead_metrics(
        existing_rules=_as_list(scenario.get("deadhead_rules")),
        trip_rows=trips or [],
        routes=_as_list(scenario.get("routes")),
        stops=_as_list(scenario.get("stops")),
    )


def _build_deadhead_rules(
    scenario: Dict[str, Any],
    trips: Optional[List[Dict[str, Any]]] = None,
) -> Dict[tuple[str, str], int]:
    return {
        key: metric.travel_time_min
        for key, metric in _build_deadhead_metrics(scenario, trips).items()
    }


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
    analysis_scope: Optional[Dict[str, Any]] = None,
) -> tuple[ProblemData, ScenarioBuildReport]:
    meta = scenario.get("meta") or {}
    simulation_cfg = scenario.get("simulation_config") or {}
    solver_cfg = _scenario_overlay_solver(scenario)
    cost_cfg = _scenario_overlay_costs(scenario)
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

    trips = _collect_trips_for_scope(
        scenario,
        depot_id,
        service_id,
        analysis_scope=analysis_scope,
    )
    scope_vehicles_raw = [
        apply_ice_reference_defaults(item)
        for item in _vehicles_for_scope(scenario, depot_id)
    ]
    diesel_price_per_l = _safe_float(cost_cfg.get("diesel_price_per_l"), 145.0)
    vehicles = []
    for item in scope_vehicles_raw:
        vehicle_like = dict(item)
        vehicle_like.setdefault("fuelCostPerL", diesel_price_per_l)
        vehicles.append(_build_vehicle(vehicle_like))
    tasks = _build_tasks(
        trips,
        scope_vehicles_raw,
        start_time,
        delta_t_min,
        service_id=service_id,
    )
    deadhead_metrics = _build_deadhead_metrics(scenario, trips)
    deadhead_rules = {
        key: metric.travel_time_min for key, metric in deadhead_metrics.items()
    }
    num_periods = max(
        _safe_int(simulation_cfg.get("num_periods"), 0),
        max((task.end_time_idx for task in tasks), default=0) + 2,
        int(math.ceil(planning_horizon_hours / delta_t_hour)),
    )
    sites = _build_sites(scenario, depot_id)
    chargers = _build_chargers(scenario)
    pv_profiles = _build_pv_profiles(scenario)
    electricity_prices = _build_electricity_prices(
        scenario,
        site_ids=[site.site_id for site in sites],
        num_periods=num_periods,
        delta_t_min=delta_t_min,
        start_time=start_time,
    )
    objective_weights = _objective_weights_from_scenario(scenario)
    allow_partial_service = bool(
        simulation_cfg.get(
            "allow_partial_service",
            solver_cfg.get("allow_partial_service", False),
        )
    )
    demand_charge_rate_per_kw = _safe_float(
        cost_cfg.get("demand_charge_cost_per_kw"),
        0.0,
    )
    objective_mode = normalize_objective_mode(
        simulation_cfg.get("objective_mode")
        or solver_cfg.get("objective_mode")
        or "total_cost"
    )
    co2_price_per_kg = effective_co2_price_per_kg(
        objective_mode,
        cost_cfg.get("co2_price_per_kg"),
    )

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
        allow_partial_service=allow_partial_service,
        enable_pv=bool(pv_profiles),
        enable_demand_charge=demand_charge_rate_per_kw > 0.0,
        objective_mode=objective_mode,
        objective_weights=objective_weights,
        demand_charge_rate_per_kw=demand_charge_rate_per_kw,
        co2_price_per_kg=co2_price_per_kg,
    )
    data.graph_export_context = _build_graph_export_context(scenario, trips, tasks)

    connections, dispatch_report = build_travel_connections_via_dispatch(
        data=data,
        service_date=str(meta.get("updatedAt") or "2026-01-01")[:10],
        default_turnaround_min=default_turnaround_min,
        turnaround_rules=_build_turnaround_rules(scenario),
        deadhead_rules=deadhead_rules,
        deadhead_metrics=deadhead_metrics,
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
