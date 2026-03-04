"""
src/dispatch/context_builder.py

Timetable-first loader for DispatchContext.

This module converts CSV inputs (route_master / operations) into dispatch-layer
dataclasses so the pipeline can run in the required order:

    timetable -> feasibility rules -> connection graph -> dispatch -> validation
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from .models import DeadheadRule, DispatchContext, Trip, TurnaroundRule, VehicleProfile


def _read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path, encoding="utf-8")


def _safe_float(value: Any, default: float) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value: Any, default: int) -> int:
    try:
        if value is None or value == "":
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _normalize_vehicle_type(raw: Any) -> str:
    text = str(raw).strip().upper()
    if text in ("BEV", "EV", "EV_BUS"):
        return "BEV"
    if text in ("ICE", "ENGINE", "ENGINE_BUS", "DIESEL"):
        return "ICE"
    if "BEV" in text or text.startswith("EV"):
        return "BEV"
    if "ICE" in text or "ENGINE" in text or "DIESEL" in text:
        return "ICE"
    return "BEV"


def _parse_allowed_types(raw: Any, default_types: tuple[str, ...]) -> tuple[str, ...]:
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return default_types

    text = str(raw).strip()
    if not text:
        return default_types

    parts = [p.strip() for p in text.replace("/", ",").split(",") if p.strip()]
    mapped = {_normalize_vehicle_type(p) for p in parts}
    if not mapped:
        return default_types
    ordered = [t for t in ("BEV", "ICE") if t in mapped]
    return tuple(ordered) if ordered else default_types


def _to_hhmm(value: Any) -> str:
    text = str(value).strip()
    parts = text.split(":")
    if len(parts) < 2:
        raise ValueError(f"Invalid HH:MM value: '{value}'")
    hour = int(parts[0])
    minute = int(parts[1])
    return f"{hour:02d}:{minute:02d}"


def _build_distance_lookup(
    data_dir: Path,
) -> tuple[dict[tuple[str, str], float], dict[str, float]]:
    by_route_direction: dict[tuple[str, str], float] = {}
    by_route: dict[str, float] = {}

    segments = _read_csv(data_dir / "route_master" / "segments.csv")
    if not segments.empty and {"route_id", "direction", "distance_km"}.issubset(
        segments.columns
    ):
        grouped = segments.groupby(["route_id", "direction"], dropna=False)[
            "distance_km"
        ].sum()
        for (route_id, direction), distance in grouped.items():
            by_route_direction[(str(route_id).strip(), str(direction).strip())] = (
                _safe_float(distance, 0.0)
            )

    routes = _read_csv(data_dir / "route_master" / "routes.csv")
    if not routes.empty and "route_id" in routes.columns:
        for _, row in routes.iterrows():
            route_id = str(row.get("route_id", "")).strip()
            if not route_id:
                continue
            total = _safe_float(row.get("total_distance_km", 0.0), 0.0)
            route_type = str(row.get("route_type", "")).strip().lower()
            if total > 0:
                by_route[route_id] = (
                    (total / 2.0) if route_type == "bidirectional" else total
                )

    return by_route_direction, by_route


def _build_turnaround_rules(data_dir: Path) -> dict[str, TurnaroundRule]:
    path = data_dir / "operations" / "turnaround_rules.csv"
    rows = _read_csv(path)
    if rows.empty:
        return {}

    rules: dict[str, TurnaroundRule] = {}
    for _, row in rows.iterrows():
        stop_id = str(row.get("stop_id", "")).strip()
        if not stop_id:
            continue
        mins = _safe_int(row.get("min_turnaround_min", 0), 0)
        if mins < 0:
            mins = 0
        rules[stop_id] = TurnaroundRule(stop_id=stop_id, min_turnaround_min=mins)
    return rules


def _build_deadhead_rules(data_dir: Path) -> dict[tuple[str, str], DeadheadRule]:
    path = data_dir / "operations" / "deadhead_rules.csv"
    rows = _read_csv(path)

    rules: dict[tuple[str, str], DeadheadRule] = {}
    if not rows.empty:
        for _, row in rows.iterrows():
            from_stop = str(row.get("from_stop", row.get("from_stop_id", ""))).strip()
            to_stop = str(row.get("to_stop", row.get("to_stop_id", ""))).strip()
            if not from_stop or not to_stop or from_stop == to_stop:
                continue
            minutes = _safe_int(row.get("travel_time_min", 0), 0)
            # from!=to with 0 cannot be distinguished from "no rule" in current API.
            if minutes <= 0:
                minutes = 1
            rules[(from_stop, to_stop)] = DeadheadRule(
                from_stop=from_stop,
                to_stop=to_stop,
                travel_time_min=minutes,
            )

    # Alias rules: if two stop IDs share identical coordinates, add 1-min deadhead.
    stops = _read_csv(data_dir / "route_master" / "stops.csv")
    if not stops.empty and {"stop_id", "lat", "lon"}.issubset(stops.columns):
        valid = stops.dropna(subset=["stop_id", "lat", "lon"]).copy()
        valid["lat"] = valid["lat"].astype(float).round(6)
        valid["lon"] = valid["lon"].astype(float).round(6)
        grouped = valid.groupby(["lat", "lon"], dropna=False)
        for _, group in grouped:
            stop_ids = sorted(
                {str(s).strip() for s in group["stop_id"].tolist() if str(s).strip()}
            )
            if len(stop_ids) < 2:
                continue
            for from_stop in stop_ids:
                for to_stop in stop_ids:
                    if from_stop == to_stop:
                        continue
                    key = (from_stop, to_stop)
                    if key in rules:
                        continue
                    rules[key] = DeadheadRule(
                        from_stop=from_stop,
                        to_stop=to_stop,
                        travel_time_min=1,
                    )

    return rules


def _build_vehicle_profiles(
    data_dir: Path,
    default_vehicle_types: tuple[str, ...],
) -> dict[str, VehicleProfile]:
    profiles: dict[str, VehicleProfile] = {}
    vehicles = _read_csv(data_dir / "operations" / "vehicles.csv")

    if not vehicles.empty and "vehicle_type" in vehicles.columns:
        vehicles = vehicles.copy()
        vehicles["_norm_type"] = vehicles["vehicle_type"].map(_normalize_vehicle_type)

        bev_rows = vehicles[vehicles["_norm_type"] == "BEV"]
        if len(bev_rows) > 0:
            cap = (
                bev_rows["battery_capacity_kwh"].astype(float).mean()
                if "battery_capacity_kwh" in bev_rows.columns
                else 300.0
            )
            eff_km_per_kwh = (
                bev_rows["efficiency_km_per_kwh"].astype(float).mean()
                if "efficiency_km_per_kwh" in bev_rows.columns
                else 1.0
            )
            profiles["BEV"] = VehicleProfile(
                vehicle_type="BEV",
                battery_capacity_kwh=float(cap) if cap > 0 else 300.0,
                energy_consumption_kwh_per_km=(1.0 / eff_km_per_kwh)
                if eff_km_per_kwh > 0
                else 1.0,
            )

        ice_rows = vehicles[vehicles["_norm_type"] == "ICE"]
        if len(ice_rows) > 0:
            profiles["ICE"] = VehicleProfile(
                vehicle_type="ICE",
                fuel_tank_capacity_l=150.0,
                fuel_consumption_l_per_km=0.2,
            )

    for vehicle_type in default_vehicle_types:
        norm = _normalize_vehicle_type(vehicle_type)
        if norm == "BEV" and norm not in profiles:
            profiles[norm] = VehicleProfile(
                vehicle_type="BEV",
                battery_capacity_kwh=300.0,
                energy_consumption_kwh_per_km=1.0,
            )
        if norm == "ICE" and norm not in profiles:
            profiles[norm] = VehicleProfile(
                vehicle_type="ICE",
                fuel_tank_capacity_l=150.0,
                fuel_consumption_l_per_km=0.2,
            )

    return profiles


def load_dispatch_context_from_csv(
    data_dir: str | Path,
    service_date: str,
    default_turnaround_min: int = 10,
    service_type: str | None = None,
    default_vehicle_types: tuple[str, ...] = ("BEV", "ICE"),
    default_trip_distance_km: float = 10.0,
) -> DispatchContext:
    """
    Load DispatchContext from CSV files under *data_dir*.

    Optional files:
    - operations/turnaround_rules.csv (stop_id,min_turnaround_min)
    - operations/deadhead_rules.csv (from_stop,to_stop,travel_time_min)

    Required for trip generation:
    - route_master/timetable.csv
    """
    root = Path(data_dir)

    timetable = _read_csv(root / "route_master" / "timetable.csv")
    distance_by_route_dir, distance_by_route = _build_distance_lookup(root)

    trips: list[Trip] = []
    if not timetable.empty:
        if (
            service_type
            and service_type != "すべて"
            and "service_type" in timetable.columns
        ):
            timetable = timetable[
                timetable["service_type"].astype(str).str.strip() == service_type
            ]

        for _, row in timetable.iterrows():
            trip_id = str(row.get("trip_id", "")).strip()
            route_id = (
                str(row.get("route_id", "route_unknown")).strip() or "route_unknown"
            )
            direction = str(row.get("direction", "outbound")).strip() or "outbound"
            try:
                dep = _to_hhmm(row.get("dep_time", "00:00"))
                arr = _to_hhmm(row.get("arr_time", "00:00"))
            except ValueError:
                continue

            if not trip_id:
                dep_compact = dep.replace(":", "")
                trip_id = f"{route_id}_{direction}_{dep_compact}"

            origin = str(row.get("from_stop_id", "")).strip() or f"{route_id}_origin"
            destination = (
                str(row.get("to_stop_id", "")).strip() or f"{route_id}_destination"
            )

            distance = distance_by_route_dir.get((route_id, direction))
            if distance is None or distance <= 0:
                distance = distance_by_route.get(route_id, default_trip_distance_km)
            if distance <= 0:
                distance = default_trip_distance_km

            allowed = _parse_allowed_types(
                row.get("required_bus_type"),
                tuple(_normalize_vehicle_type(v) for v in default_vehicle_types),
            )

            trips.append(
                Trip(
                    trip_id=trip_id,
                    route_id=route_id,
                    origin=origin,
                    destination=destination,
                    departure_time=dep,
                    arrival_time=arr,
                    distance_km=float(distance),
                    allowed_vehicle_types=allowed,
                )
            )

    turnaround_rules = _build_turnaround_rules(root)
    deadhead_rules = _build_deadhead_rules(root)
    vehicle_profiles = _build_vehicle_profiles(
        root,
        tuple(_normalize_vehicle_type(v) for v in default_vehicle_types),
    )

    return DispatchContext(
        service_date=service_date,
        trips=trips,
        turnaround_rules=turnaround_rules,
        deadhead_rules=deadhead_rules,
        vehicle_profiles=vehicle_profiles,
        default_turnaround_min=max(0, default_turnaround_min),
    )
