from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import pandas as pd

from src.dataset_integrity import evaluate_dataset_integrity, validate_rows_against_schema
from src.scenario_overlay import default_scenario_overlay
from src.tokyu_shard_loader import (
    TOKYU_SHARD_ROOT,
    day_type_to_service_id,
    load_manifest as load_tokyu_shard_manifest,
    shard_runtime_ready,
)
from src.value_normalization import (
    coerce_list,
    coerce_str_list,
    first_non_empty_list,
    normalize_for_python,
    normalize_text_nfkc,
)


DEFAULT_OPERATOR_ID = "tokyu"
DEFAULT_DATASET_ID = "tokyu_full"
MISSING_BUILT_DATA_MESSAGE = "Timetable/trip data not found. Run data-prep first."

_REPO_ROOT = Path(__file__).resolve().parents[1]
_DATA_ROOT = _REPO_ROOT / "data"
_SEED_ROOT = _DATA_ROOT / "seed" / DEFAULT_OPERATOR_ID
_BUILT_ROOT = _DATA_ROOT / "built"
_CATALOG_FAST_ROOT = _DATA_ROOT / "catalog-fast"
_CATALOG_FAST_NORMALIZED_ROOT = _CATALOG_FAST_ROOT / "normalized"

_DEPOT_MASTER_CANDIDATES = (
    _REPO_ROOT / "tokyu_bus_depots_master_full.json",
    _REPO_ROOT / "tokyu_bus_depots_master.json",
    _SEED_ROOT / "sources" / "tokyu_bus_depots_master.json",
    _SEED_ROOT / "depots.json",
)

_ROUTE_TO_DEPOT_CANDIDATES = (
    _REPO_ROOT / "tokyu_bus_route_to_depot_full.csv",
    _REPO_ROOT / "tokyu_bus_route_to_depot.csv",
    _SEED_ROOT / "sources" / "tokyu_bus_route_to_depot.csv",
    _SEED_ROOT / "route_to_depot.csv",
)


def _read_json(path: Path) -> Dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return dict(payload) if isinstance(payload, dict) else {}


def _read_csv_rows(path: Path) -> List[Dict[str, Any]]:
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        return [dict(row) for row in csv.DictReader(fh)]


def _read_jsonl_rows(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    items: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            text = line.strip()
            if not text:
                continue
            payload = json.loads(text)
            if isinstance(payload, dict):
                items.append(dict(payload))
    return items


def _first_existing_path(candidates: Iterable[Path]) -> Path | None:
    for path in candidates:
        if path.exists():
            return path
    return None


def _normalize_depot_master_row(row: Dict[str, Any]) -> Dict[str, Any]:
    depot_id = str(
        row.get("id")
        or row.get("depotId")
        or row.get("depot_id")
        or ""
    ).strip()
    route_codes = [
        normalize_text_nfkc(code)
        for code in coerce_list(row.get("routeCodes") or row.get("route_codes"))
        if str(code or "").strip()
    ]
    return {
        "id": depot_id,
        "depotId": depot_id,
        "name": row.get("name") or "",
        "region": row.get("region") or "",
        "address": row.get("address") or "",
        "phone": row.get("phone") or "",
        "location": row.get("location") or row.get("address") or "",
        "lat": _safe_optional_float(row.get("lat") or row.get("latitude")),
        "lon": _safe_optional_float(row.get("lon") or row.get("longitude")),
        "normalChargerCount": _safe_int(row.get("normalChargerCount"), 0),
        "normalChargerPowerKw": _safe_float(row.get("normalChargerPowerKw"), 0.0),
        "fastChargerCount": _safe_int(row.get("fastChargerCount"), 0),
        "fastChargerPowerKw": _safe_float(row.get("fastChargerPowerKw"), 0.0),
        "hasFuelFacility": bool(row.get("hasFuelFacility", True)),
        "parkingCapacity": _safe_int(row.get("parkingCapacity"), 0),
        "overnightCharging": bool(row.get("overnightCharging", True)),
        "enabled": bool(row.get("enabled", True)),
        "researchTarget": bool(row.get("researchTarget", False)),
        "routeMapPdf": row.get("routeMapPdf") or row.get("route_map_pdf") or "",
        "routeMapAsOf": row.get("routeMapAsOf") or row.get("route_map_as_of") or "",
        "routeCodes": route_codes,
        "specialServices": coerce_str_list(row.get("specialServices") or row.get("special_services")),
        "notes": row.get("notes") or row.get("transcription_note") or "",
        "source": row.get("source") or "tokyu_bus_depots_master_full.json",
    }


def _normalize_parquet_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _normalize_parquet_value(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_normalize_parquet_value(item) for item in value]
    if isinstance(value, tuple):
        return [_normalize_parquet_value(item) for item in value]
    if isinstance(value, str) or value is None:
        return value
    if hasattr(value, "tolist"):
        try:
            return _normalize_parquet_value(value.tolist())
        except Exception:
            return value
    return value


def _read_parquet_rows(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    frame = pd.read_parquet(path)
    frame = frame.where(pd.notnull(frame), None)
    return [
        {
            key: _normalize_parquet_value(value)
            for key, value in dict(item).items()
        }
        for item in frame.to_dict(orient="records")
    ]


def _read_parquet_rows_validated(path: Path, *, schema_name: str) -> List[Dict[str, Any]]:
    rows = _read_parquet_rows(path)
    errors = validate_rows_against_schema(rows, schema_name=schema_name)
    if errors:
        raise RuntimeError(
            f"Parquet schema validation failed for '{path}': {'; '.join(errors)}"
        )
    return rows


def _seed_dataset_path(dataset_id: str) -> Path:
    return _SEED_ROOT / "datasets" / f"{dataset_id}.json"


def _built_dataset_dir(dataset_id: str) -> Path:
    return _BUILT_ROOT / dataset_id


def _catalog_fast_normalized_path(filename: str) -> Path:
    return _CATALOG_FAST_NORMALIZED_ROOT / filename


def load_seed_version() -> Dict[str, Any]:
    return _read_json(_SEED_ROOT / "version.json")


def load_seed_depots() -> List[Dict[str, Any]]:
    path = _first_existing_path(_DEPOT_MASTER_CANDIDATES)
    if not path:
        return []
    payload = _read_json(path)
    items = [dict(item) for item in payload.get("depots") or [] if isinstance(item, dict)]
    if path.name == "depots.json":
        return items
    normalized = [_normalize_depot_master_row(item) for item in items]
    return [item for item in normalized if str(item.get("id") or "").strip()]


def load_route_to_depot_rows() -> List[Dict[str, Any]]:
    path = _first_existing_path(_ROUTE_TO_DEPOT_CANDIDATES)
    if not path:
        return []
    rows = _read_csv_rows(path)
    normalized_rows: List[Dict[str, Any]] = []
    for row in rows:
        route_code = normalize_text_nfkc(row.get("route_code") or "")
        depot_id = str(row.get("depot_id") or "").strip()
        if not route_code or not depot_id:
            continue
        service_type = str(row.get("service_type") or "").strip().lower()
        if service_type and service_type != "route_code":
            continue
        normalized_rows.append({
            **row,
            "route_code": route_code,
            "depot_id": depot_id,
        })
    return normalized_rows


def load_dataset_definition(dataset_id: str) -> Dict[str, Any]:
    path = _seed_dataset_path(dataset_id)
    if not path.exists():
        raise KeyError(dataset_id)
    payload = _read_json(path)
    payload.setdefault("dataset_id", dataset_id)
    return payload


def list_dataset_definitions() -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    datasets_dir = _SEED_ROOT / "datasets"
    if not datasets_dir.exists():
        return items
    for path in sorted(datasets_dir.glob("*.json")):
        payload = _read_json(path)
        if payload:
            items.append(payload)
    return items


def get_built_manifest(dataset_id: str) -> Optional[Dict[str, Any]]:
    manifest_path = _built_dataset_dir(dataset_id) / "manifest.json"
    if not manifest_path.exists():
        return None
    payload = _read_json(manifest_path)
    payload["manifest_path"] = str(manifest_path)
    return payload


def _dataset_version_for(dataset_id: str) -> str:
    manifest = get_built_manifest(dataset_id)
    if manifest and manifest.get("dataset_version"):
        return str(manifest["dataset_version"])
    shard_manifest = load_tokyu_shard_manifest(dataset_id)
    if shard_manifest and shard_manifest.get("dataset_version"):
        return str(shard_manifest["dataset_version"])
    if shard_manifest and shard_manifest.get("build_timestamp"):
        return str(shard_manifest["build_timestamp"])
    version = load_seed_version()
    return str(version.get("dataset_version") or version.get("seed_version") or "unknown")


def _included_route_codes(definition: Dict[str, Any]) -> Optional[set[str]]:
    included = definition.get("included_routes")
    if included == "ALL":
        return None
    return {str(item) for item in list(included or []) if str(item).strip()}


def _normalize_route_id(route_code: str, depot_id: str) -> str:
    return f"{DEFAULT_OPERATOR_ID}:{depot_id}:{route_code}"


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, ""):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        if value in (None, ""):
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _safe_optional_float(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _normalize_route_row(row: Dict[str, Any]) -> Dict[str, Any]:
    route_id = str(
        row.get("id") or row.get("route_id") or row.get("routeId") or ""
    ).strip()
    route_code = normalize_text_nfkc(
        row.get("routeCode") or row.get("route_code") or route_id
    )
    normalized = {
        "id": route_id or route_code,
        "name": row.get("name") or row.get("routeLabel") or row.get("route_label") or route_code,
        "routeCode": route_code,
        "routeLabel": row.get("routeLabel") or row.get("route_label") or row.get("name") or route_code,
        "startStop": row.get("startStop") or row.get("origin") or row.get("start_stop") or "",
        "endStop": row.get("endStop") or row.get("destination") or row.get("end_stop") or "",
        "distanceKm": _safe_float(row.get("distanceKm", row.get("distance_km")), 0.0),
        "durationMin": _safe_int(row.get("durationMin", row.get("duration_min")), 0),
        "color": row.get("color") or row.get("route_color") or "",
        "enabled": bool(row.get("enabled", True)),
        "source": row.get("source") or "built_dataset",
        "depotId": row.get("depotId") or row.get("depot_id"),
        "routeFamilyCode": row.get("routeFamilyCode") or row.get("route_family_code"),
        "routeFamilyLabel": row.get("routeFamilyLabel") or row.get("route_family_label"),
        "routeVariantType": row.get("routeVariantType") or row.get("route_variant_type"),
        "canonicalDirection": row.get("canonicalDirection") or row.get("canonical_direction"),
        "tripCount": _safe_int(row.get("tripCount", row.get("trip_count")), 0),
        "stopSequence": coerce_str_list(
            first_non_empty_list(row.get("stopSequence"), row.get("stop_sequence"))
        ),
    }
    return normalized


def _normalize_timetable_row(row: Dict[str, Any]) -> Dict[str, Any]:
    vehicle_types = row.get("allowed_vehicle_types")
    if vehicle_types is None:
        vehicle_types = row.get("allowedVehicleTypes")
    if vehicle_types is None:
        normalized_vehicle_types = ["BEV", "ICE"]
    elif isinstance(vehicle_types, str):
        normalized_vehicle_types = [vehicle_types]
    else:
        normalized_vehicle_types = [str(item) for item in list(vehicle_types)]
    return {
        "trip_id": str(row.get("trip_id") or row.get("tripId") or "").strip(),
        "route_id": str(row.get("route_id") or row.get("routeId") or "").strip(),
        "service_id": str(row.get("service_id") or row.get("serviceId") or "WEEKDAY").strip() or "WEEKDAY",
        "direction": str(row.get("direction") or "outbound").strip() or "outbound",
        "origin": row.get("origin") or row.get("origin_name") or row.get("origin_stop_name") or "",
        "origin_lat": row.get("origin_lat") or row.get("originLat"),
        "origin_lon": row.get("origin_lon") or row.get("originLon"),
        "destination": row.get("destination") or row.get("destination_name") or row.get("destination_stop_name") or "",
        "destination_lat": row.get("destination_lat") or row.get("destinationLat"),
        "destination_lon": row.get("destination_lon") or row.get("destinationLon"),
        "departure": str(row.get("departure") or row.get("departure_time") or "").strip(),
        "arrival": str(row.get("arrival") or row.get("arrival_time") or "").strip(),
        "distance_km": float(row.get("distance_km") or row.get("distanceKm") or 0.0),
        "allowed_vehicle_types": normalized_vehicle_types,
        "source": row.get("source") or "built_dataset",
    }


def _normalize_trip_row(row: Dict[str, Any]) -> Dict[str, Any]:
    normalized = _normalize_timetable_row(row)
    return {
        **normalized,
        "trip_id": normalized["trip_id"] or f"trip:{normalized['route_id']}:{normalized['departure']}",
    }


def _normalize_stop_row(row: Dict[str, Any]) -> Dict[str, Any]:
    stop_id = str(row.get("id") or row.get("stopId") or row.get("stop_id") or "").strip()
    return {
        "id": stop_id,
        "code": str(row.get("code") or row.get("stop_code") or stop_id).strip() or stop_id,
        "name": row.get("name") or row.get("stopName") or row.get("title_ja") or stop_id,
        "kana": row.get("kana") or row.get("title_kana") or "",
        "lat": _safe_optional_float(row.get("lat", row.get("stop_lat"))),
        "lon": _safe_optional_float(row.get("lon", row.get("stop_lon"))),
        "poleNumber": row.get("poleNumber") or row.get("platform_num") or row.get("platformCode") or "",
        "operatorId": row.get("operatorId") or row.get("operator_id") or DEFAULT_OPERATOR_ID,
        "source": row.get("source") or "built_dataset",
    }


def _normalize_stop_timetable_row(row: Dict[str, Any]) -> Dict[str, Any]:
    items = [
        dict(item)
        for item in coerce_list(row.get("items"))
        if isinstance(item, dict)
    ]
    return {
        "id": str(row.get("id") or row.get("stopTimetableId") or "").strip(),
        "stopId": str(row.get("stopId") or row.get("stop_id") or "").strip(),
        "stopName": row.get("stopName") or row.get("stop_name") or "",
        "calendar": row.get("calendar") or row.get("service_id") or "WEEKDAY",
        "service_id": row.get("service_id") or row.get("calendar") or "WEEKDAY",
        "source": row.get("source") or "built_dataset",
        "items": items,
    }


def _seed_route_items(definition: Dict[str, Any], route_rows: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    included_depots = {str(item) for item in definition.get("included_depots") or []}
    included_routes = _included_route_codes(definition)
    items: List[Dict[str, Any]] = []
    seen_ids: set[str] = set()
    for row in route_rows:
        depot_id = str(row.get("depot_id") or "").strip()
        route_code = str(row.get("route_code") or "").strip()
        if not depot_id or not route_code:
            continue
        if included_depots and depot_id not in included_depots:
            continue
        if included_routes is not None and route_code not in included_routes:
            continue
        route_id = _normalize_route_id(route_code, depot_id)
        if route_id in seen_ids:
            continue
        seen_ids.add(route_id)
        items.append(
            {
                "id": route_id,
                "name": route_code,
                "routeCode": route_code,
                "routeLabel": route_code,
                "startStop": "",
                "endStop": "",
                "distanceKm": 0.0,
                "durationMin": 0,
                "color": "",
                "enabled": True,
                "source": "seed",
                "depotId": depot_id,
                "assignmentType": "seed_map",
                "assignmentConfidence": 1.0,
                "assignmentReason": "route_to_depot_seed",
                "tripCount": 0,
                "stopSequence": [],
            }
        )
    return items


def _filter_built_routes(
    definition: Dict[str, Any],
    built_routes: Iterable[Dict[str, Any]],
    route_rows: Iterable[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    included_depots = {str(item) for item in definition.get("included_depots") or []}
    included_routes = _included_route_codes(definition)
    depot_ids_by_route_code: Dict[str, set[str]] = {}
    for row in route_rows:
        route_code = str(row.get("route_code") or "").strip()
        depot_id = str(row.get("depot_id") or "").strip()
        if route_code and depot_id:
            depot_ids_by_route_code.setdefault(route_code, set()).add(depot_id)
    items: List[Dict[str, Any]] = []
    for raw in built_routes:
        route = _normalize_route_row(raw)
        route_code = str(route.get("routeCode") or route.get("id") or "")
        if included_routes is not None and route_code not in included_routes:
            continue
        matched_depots = depot_ids_by_route_code.get(route_code) or set()
        if included_depots and matched_depots and not matched_depots.intersection(included_depots):
            continue
        items.append(route)
    return items


def _load_catalog_fast_routes(
    definition: Dict[str, Any],
    route_rows: Iterable[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    return _filter_built_routes(
        definition,
        _read_jsonl_rows(_catalog_fast_normalized_path("routes.jsonl")),
        route_rows,
    )


def _filter_rows_by_route_ids(
    rows: Iterable[Dict[str, Any]],
    route_ids: set[str],
) -> List[Dict[str, Any]]:
    return [row for row in rows if str(row.get("route_id") or "") in route_ids]


def _available_route_ids_from_rows(*row_groups: Iterable[Dict[str, Any]]) -> set[str]:
    route_ids: set[str] = set()
    for rows in row_groups:
        for row in rows:
            route_id = str(row.get("route_id") or row.get("routeId") or "").strip()
            if route_id:
                route_ids.add(route_id)
    return route_ids


def _filter_routes_by_route_ids(
    routes: Iterable[Dict[str, Any]],
    route_ids: set[str],
) -> List[Dict[str, Any]]:
    if not route_ids:
        return []
    return [
        dict(route)
        for route in routes
        if str((route or {}).get("id") or "").strip() in route_ids
    ]


def _filter_depots_by_route_context(
    depots: Iterable[Dict[str, Any]],
    routes: Iterable[Dict[str, Any]],
    assignments: Iterable[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    referenced_depot_ids = {
        str((route or {}).get("depotId") or "").strip()
        for route in routes
        if str((route or {}).get("depotId") or "").strip()
    }
    referenced_depot_ids.update(
        str((assignment or {}).get("depotId") or "").strip()
        for assignment in assignments
        if str((assignment or {}).get("depotId") or "").strip()
    )
    if not referenced_depot_ids:
        return [dict(item) for item in depots]
    return [
        dict(item)
        for item in depots
        if str((item or {}).get("id") or (item or {}).get("depotId") or "").strip() in referenced_depot_ids
    ]


def _build_route_assignments(
    routes: Iterable[Dict[str, Any]],
    route_rows: Iterable[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    depot_ids_by_route_code: Dict[str, List[str]] = {}
    for row in route_rows:
        route_code = str(row.get("route_code") or "").strip()
        depot_id = str(row.get("depot_id") or "").strip()
        if not route_code or not depot_id:
            continue
        depot_ids_by_route_code.setdefault(route_code, [])
        if depot_id not in depot_ids_by_route_code[route_code]:
            depot_ids_by_route_code[route_code].append(depot_id)

    assignments: List[Dict[str, Any]] = []
    for route in routes:
        route_id = str(route.get("id") or "").strip()
        route_code = str(route.get("routeCode") or route_id).strip()
        depot_id = route.get("depotId")
        candidate_depots = list(depot_ids_by_route_code.get(route_code) or [])
        if depot_id and str(depot_id) not in candidate_depots:
            candidate_depots.insert(0, str(depot_id))
        for candidate in candidate_depots:
            assignments.append(
                {
                    "routeId": route_id,
                    "depotId": candidate,
                    "confidence": 1.0,
                    "reason": "route_to_depot_seed",
                    "source": "seed",
                }
            )
    return assignments


def _build_depot_permissions(assignments: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen: set[tuple[str, str]] = set()
    items: List[Dict[str, Any]] = []
    for assignment in assignments:
        key = (
            str(assignment.get("depotId") or "").strip(),
            str(assignment.get("routeId") or "").strip(),
        )
        if not key[0] or not key[1] or key in seen:
            continue
        seen.add(key)
        items.append({"depotId": key[0], "routeId": key[1], "allowed": True})
    return items


def _calendar_template(service_id: str) -> Dict[str, Any]:
    normalized = service_id.upper()
    if normalized == "SAT":
        flags = {"mon": 0, "tue": 0, "wed": 0, "thu": 0, "fri": 0, "sat": 1, "sun": 0}
        name = "土曜"
    elif normalized in {"SAT_HOL", "SAT_HOLIDAY"}:
        flags = {"mon": 0, "tue": 0, "wed": 0, "thu": 0, "fri": 0, "sat": 1, "sun": 1}
        name = "土曜・休日"
    elif normalized in {"SUN_HOL", "SUN_HOLIDAY"}:
        flags = {"mon": 0, "tue": 0, "wed": 0, "thu": 0, "fri": 0, "sat": 0, "sun": 1}
        name = "日曜・休日"
    else:
        flags = {"mon": 1, "tue": 1, "wed": 1, "thu": 1, "fri": 1, "sat": 0, "sun": 0}
        name = "平日"
    return {
        "service_id": normalized,
        "name": name,
        **flags,
        "start_date": "2026-01-01",
        "end_date": "2026-12-31",
        "source": "built_dataset",
    }


def _derive_calendar_entries(rows: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    service_ids = sorted(
        {
            str(row.get("service_id") or "WEEKDAY").strip() or "WEEKDAY"
            for row in rows
        }
    )
    if not service_ids:
        service_ids = ["WEEKDAY"]
    return [_calendar_template(service_id) for service_id in service_ids]


def _derive_calendar_entries_from_day_types(day_types: Iterable[str]) -> List[Dict[str, Any]]:
    service_ids = [
        day_type_to_service_id(day_type)
        for day_type in day_types
        if str(day_type or "").strip()
    ]
    deduped = list(dict.fromkeys(service_ids))
    return [_calendar_template(service_id) for service_id in (deduped or ["WEEKDAY"])]


def _catalog_preset_to_vehicle_template(
    preset: Dict[str, Any],
    *,
    type_: str,
) -> Dict[str, Any]:
    profile_id = str(
        preset.get("profile_id") or preset.get("vehicle_id") or preset.get("id") or ""
    ).strip()
    template_id = f"tokyu-template-{profile_id.replace('_', '-')}" if profile_id else ""
    model_name = str(
        preset.get("model_name") or preset.get("display_name") or profile_id
    ).strip()
    energy_key = (
        "energy_consumption_kWh_per_km" if type_ == "BEV" else "fuel_consumption_L_per_km"
    )
    return {
        "id": template_id or f"tokyu-template-{type_.lower()}-unknown",
        "name": str(preset.get("display_name") or model_name).strip() or model_name,
        "type": type_,
        "modelName": model_name,
        "capacityPassengers": _safe_int(
            preset.get("passenger_capacity"),
            70 if type_ == "BEV" else 75,
        ),
        "batteryKwh": _safe_optional_float(preset.get("battery_capacity_kWh"))
        if type_ == "BEV"
        else None,
        "fuelTankL": None
        if type_ == "BEV"
        else _safe_optional_float(preset.get("fuel_tank_capacity_L")),
        "energyConsumption": _safe_float(
            preset.get(energy_key),
            1.2 if type_ == "BEV" else 0.2,
        ),
        "chargePowerKw": _safe_optional_float(preset.get("charging_power_dc_kW"))
        if type_ == "BEV"
        else None,
        "minSoc": 0.2 if type_ == "BEV" else None,
        "maxSoc": 0.9 if type_ == "BEV" else None,
        "acquisitionCost": _safe_float(preset.get("purchase_cost_yen"), 0.0),
        "enabled": True,
    }


def default_vehicle_templates() -> List[Dict[str, Any]]:
    catalog_path = _DATA_ROOT / "vehicle_catalog.json"
    catalog = _read_json(catalog_path) if catalog_path.exists() else {}
    templates: List[Dict[str, Any]] = []

    for preset in catalog.get("ev_presets") or []:
        if isinstance(preset, dict):
            templates.append(_catalog_preset_to_vehicle_template(preset, type_="BEV"))
    for preset in catalog.get("engine_presets") or []:
        if isinstance(preset, dict):
            templates.append(_catalog_preset_to_vehicle_template(preset, type_="ICE"))

    if templates:
        return templates

    return [
        {
            "id": "tokyu-template-bev-standard-300",
            "name": "Tokyu Standard BEV 300kWh",
            "type": "BEV",
            "modelName": "Standard BEV 300kWh",
            "capacityPassengers": 70,
            "batteryKwh": 300.0,
            "fuelTankL": None,
            "energyConsumption": 1.2,
            "chargePowerKw": 150.0,
            "minSoc": 0.2,
            "maxSoc": 0.9,
            "acquisitionCost": 30_000_000.0,
            "enabled": True,
        },
        {
            "id": "tokyu-template-bev-compact-220",
            "name": "Tokyu Compact BEV 220kWh",
            "type": "BEV",
            "modelName": "Compact BEV 220kWh",
            "capacityPassengers": 55,
            "batteryKwh": 220.0,
            "fuelTankL": None,
            "energyConsumption": 1.0,
            "chargePowerKw": 90.0,
            "minSoc": 0.2,
            "maxSoc": 0.9,
            "acquisitionCost": 26_000_000.0,
            "enabled": True,
        },
        {
            "id": "tokyu-template-ice-standard",
            "name": "Tokyu Standard ICE",
            "type": "ICE",
            "modelName": "Standard Diesel Bus",
            "capacityPassengers": 75,
            "batteryKwh": None,
            "fuelTankL": 220.0,
            "energyConsumption": 0.42,
            "chargePowerKw": None,
            "minSoc": None,
            "maxSoc": None,
            "acquisitionCost": 22_000_000.0,
            "enabled": True,
        },
    ]


def get_dataset_status(dataset_id: str) -> Dict[str, Any]:
    definition = load_dataset_definition(dataset_id)
    integrity = evaluate_dataset_integrity(dataset_id)
    manifest = integrity.get("manifest") or get_built_manifest(dataset_id)
    shard_manifest = load_tokyu_shard_manifest(dataset_id)
    shard_ready = shard_runtime_ready(dataset_id)
    built_dir = _built_dataset_dir(dataset_id)
    required_files = {
        "routes": built_dir / "routes.parquet",
        "trips": built_dir / "trips.parquet",
        "timetables": built_dir / "timetables.parquet",
        "stops": built_dir / "stops.parquet",
        "stop_timetables": built_dir / "stop_timetables.parquet",
        "tokyu_shards": TOKYU_SHARD_ROOT,
    }
    built_available = bool(integrity.get("built_ready"))
    dataset_version = str(
        (shard_manifest or {}).get("dataset_version")
        or (shard_manifest or {}).get("build_timestamp")
        or (manifest or {}).get("dataset_version")
        or load_seed_version().get("dataset_version")
        or "unknown"
    )
    return {
        "datasetId": definition.get("dataset_id") or dataset_id,
        "description": definition.get("description") or "",
        "note": definition.get("note"),
        "includedDepots": list(definition.get("included_depots") or []),
        "includedRoutes": definition.get("included_routes"),
        "seedVersion": load_seed_version().get("seed_version"),
        "datasetVersion": dataset_version,
        "seedReady": bool(integrity.get("seed_ready")),
        "builtReady": bool(integrity.get("built_ready")),
        "builtAvailable": built_available,
        "shardReady": shard_ready,
        "runtimeReady": bool(built_available or shard_ready),
        "warning": None if (built_available or shard_ready) else MISSING_BUILT_DATA_MESSAGE,
        "missingArtifacts": list(integrity.get("missing_artifacts") or []),
        "integrityError": integrity.get("integrity_error"),
        "manifest": manifest,
        "shardManifest": shard_manifest,
        "paths": {key: str(path) for key, path in required_files.items()},
    }


def list_dataset_statuses() -> List[Dict[str, Any]]:
    return [
        get_dataset_status(str(item.get("dataset_id") or ""))
        for item in list_dataset_definitions()
        if item.get("dataset_id")
    ]


def build_dataset_bootstrap(
    dataset_id: str = DEFAULT_DATASET_ID,
    *,
    scenario_id: str,
    random_seed: int = 42,
) -> Dict[str, Any]:
    definition = load_dataset_definition(dataset_id)
    status = get_dataset_status(dataset_id)
    requested_depot_ids = [str(value) for value in definition.get("included_depots") or [] if str(value)]
    depots_by_id = {
        str(item.get("id") or item.get("depotId") or ""): dict(item)
        for item in load_seed_depots()
        if str(item.get("id") or item.get("depotId") or "")
    }
    if requested_depot_ids:
        depots = [dict(depots_by_id[depot_id]) for depot_id in requested_depot_ids if depot_id in depots_by_id]
    else:
        depots = list(depots_by_id.values())
    route_rows = load_route_to_depot_rows()
    seed_routes = _seed_route_items(definition, route_rows)
    catalog_fast_routes = _load_catalog_fast_routes(definition, route_rows)
    shard_ready = bool(status.get("shardReady"))
    shard_manifest = dict(status.get("shardManifest") or {})
    runtime_features: Dict[str, Any] | None = None
    built_routes: List[Dict[str, Any]] = []
    built_stops: List[Dict[str, Any]] = []
    scope_route_ids: List[str] = []

    if status["builtAvailable"]:
        built_dir = _built_dataset_dir(dataset_id)
        built_routes = _filter_built_routes(
            definition,
            _read_parquet_rows_validated(
                built_dir / "routes.parquet",
                schema_name="routes",
            ),
            route_rows,
        )
        stops_path = built_dir / "stops.parquet"
        if stops_path.exists():
            built_stops = [
                _normalize_stop_row(item)
                for item in _read_parquet_rows_validated(
                    stops_path,
                    schema_name="stops",
                )
            ]
        route_inventory = catalog_fast_routes or built_routes or seed_routes

        if shard_ready:
            routes = route_inventory
            timetable_rows = []
            trips = []
            stops = built_stops
            stop_timetables = []
            calendar_entries = _derive_calendar_entries_from_day_types(
                shard_manifest.get("available_day_types") or []
            )
            scope_route_ids = [
                str(item.get("id") or "").strip()
                for item in routes
                if str(item.get("id") or "").strip()
            ]
            source = "tokyu_shards"
            runtime_features = {
                "tokyuShards": {
                    "enabled": True,
                    "datasetId": dataset_id,
                    "root": str(TOKYU_SHARD_ROOT),
                    "manifestPath": shard_manifest.get("manifest_path"),
                    "buildTimestamp": shard_manifest.get("build_timestamp"),
                    "availableDepots": list(shard_manifest.get("available_depots") or []),
                    "availableRoutes": list(shard_manifest.get("available_routes") or []),
                }
            }
        else:
            route_ids = {
                str(item.get("id") or "").strip()
                for item in route_inventory
                if str(item.get("id") or "").strip()
            }
            built_timetable_rows = _filter_rows_by_route_ids(
                [
                    _normalize_timetable_row(item)
                    for item in _read_parquet_rows_validated(
                        built_dir / "timetables.parquet",
                        schema_name="timetables",
                    )
                ],
                route_ids,
            )
            built_trips = _filter_rows_by_route_ids(
                [
                    _normalize_trip_row(item)
                    for item in _read_parquet_rows_validated(
                        built_dir / "trips.parquet",
                        schema_name="trips",
                    )
                ],
                route_ids,
            )
            built_stop_timetables: List[Dict[str, Any]] = []
            stop_timetables_path = built_dir / "stop_timetables.parquet"
            if stop_timetables_path.exists():
                built_stop_timetables = [
                    _normalize_stop_timetable_row(item)
                    for item in _read_parquet_rows_validated(
                        stop_timetables_path,
                        schema_name="stop_timetables",
                    )
                ]
            available_route_ids = _available_route_ids_from_rows(
                built_timetable_rows,
                built_trips,
            )
            if route_inventory and built_timetable_rows and built_trips:
                routes = route_inventory
                timetable_rows = built_timetable_rows
                trips = built_trips
                stops = built_stops
                stop_timetables = built_stop_timetables
                calendar_entries = _derive_calendar_entries(timetable_rows)
                scope_route_ids = [
                    str(item.get("id") or "").strip()
                    for item in routes
                    if str(item.get("id") or "").strip() in available_route_ids
                ]
                source = "built_dataset"
            else:
                routes = catalog_fast_routes or seed_routes
                timetable_rows = []
                trips = []
                stops = []
                stop_timetables = []
                calendar_entries = _derive_calendar_entries(timetable_rows)
                scope_route_ids = [
                    str(item.get("id") or "").strip()
                    for item in routes
                    if str(item.get("id") or "").strip()
                ]
                source = "seed_only"
    elif shard_ready:
        routes = catalog_fast_routes or seed_routes
        timetable_rows = []
        trips = []
        stops = []
        stop_timetables = []
        calendar_entries = _derive_calendar_entries_from_day_types(
            shard_manifest.get("available_day_types") or []
        )
        scope_route_ids = [
            str(item.get("id") or "").strip()
            for item in routes
            if str(item.get("id") or "").strip()
        ]
        source = "tokyu_shards"
        runtime_features = {
            "tokyuShards": {
                "enabled": True,
                "datasetId": dataset_id,
                "root": str(TOKYU_SHARD_ROOT),
                "manifestPath": shard_manifest.get("manifest_path"),
                "buildTimestamp": shard_manifest.get("build_timestamp"),
                "availableDepots": list(shard_manifest.get("available_depots") or []),
                "availableRoutes": list(shard_manifest.get("available_routes") or []),
            }
        }
    else:
        routes = catalog_fast_routes or seed_routes
        timetable_rows = []
        trips = []
        stops = []
        stop_timetables = []
        calendar_entries = _derive_calendar_entries(timetable_rows)
        scope_route_ids = [
            str(item.get("id") or "").strip()
            for item in routes
            if str(item.get("id") or "").strip()
        ]
        source = "seed_only"

    route_assignments = _build_route_assignments(routes, route_rows)
    depot_permissions = _build_depot_permissions(route_assignments)
    scope_routes = _filter_routes_by_route_ids(routes, set(scope_route_ids)) if scope_route_ids else list(routes)
    scope_depots = _filter_depots_by_route_context(depots, scope_routes, [])
    if not scope_depots and scope_routes:
        scope_depots = _filter_depots_by_route_context(depots, scope_routes, route_assignments)
    scope_depot_ids = [
        str(item.get("id") or item.get("depotId") or "").strip()
        for item in scope_depots
        if str(item.get("id") or item.get("depotId") or "").strip()
    ]
    overlay = default_scenario_overlay(
        scenario_id=scenario_id,
        dataset_id=dataset_id,
        dataset_version=str(status.get("datasetVersion") or _dataset_version_for(dataset_id)),
        random_seed=random_seed,
        depot_ids=scope_depot_ids,
        route_ids=scope_route_ids,
    )
    result = {
        "depots": depots,
        "routes": routes,
        "vehicle_templates": default_vehicle_templates(),
        "route_depot_assignments": route_assignments,
        "depot_route_permissions": depot_permissions,
        "timetable_rows": timetable_rows,
        "trips": trips,
        "stops": stops,
        "calendar": calendar_entries,
        "calendar_dates": [],
        "stop_timetables": stop_timetables,
        "dispatch_scope": {
            "scopeId": f"{dataset_id}:{status.get('datasetVersion')}",
            "operatorId": DEFAULT_OPERATOR_ID,
            "datasetVersion": status.get("datasetVersion"),
            "depotSelection": {
                "mode": "include",
                "depotIds": scope_depot_ids,
                "primaryDepotId": overlay.depot_ids[0] if overlay.depot_ids else None,
            },
            "routeSelection": {
                "mode": "include",
                "includeRouteIds": overlay.route_ids,
                "excludeRouteIds": [],
            },
            "serviceSelection": {
                "serviceIds": [entry["service_id"] for entry in calendar_entries],
            },
            "tripSelection": {
                "includeShortTurn": True,
                "includeDepotMoves": True,
                "includeDeadhead": True,
            },
            "depotId": overlay.depot_ids[0] if overlay.depot_ids else None,
            "serviceId": calendar_entries[0]["service_id"] if calendar_entries else "WEEKDAY",
        },
        "feed_context": {
            "feedId": DEFAULT_OPERATOR_ID,
            "snapshotId": status.get("datasetVersion"),
            "datasetId": dataset_id,
            "datasetFingerprint": f"{dataset_id}:{status.get('datasetVersion')}",
            "source": source,
        },
        "runtime_features": runtime_features,
        "scenario_overlay": overlay.model_dump(),
        "dataset_status": status,
    }
    if (
        dataset_id != DEFAULT_DATASET_ID
        and not list(result.get("trips") or [])
    ):
        fallback = build_dataset_bootstrap(
            DEFAULT_DATASET_ID,
            scenario_id=scenario_id,
            random_seed=random_seed,
        )
        if list(fallback.get("trips") or []):
            fallback_feed_context = dict(fallback.get("feed_context") or {})
            fallback_feed_context["requestedDatasetId"] = dataset_id
            fallback["feed_context"] = fallback_feed_context

            fallback_status = dict(fallback.get("dataset_status") or {})
            fallback_status["requestedDatasetId"] = dataset_id
            fallback_status["fallbackDatasetId"] = DEFAULT_DATASET_ID
            fallback["dataset_status"] = fallback_status
            return normalize_for_python(fallback)
    # Parquet/Arrow 由来の numpy 型を Python ネイティブ型に一括変換して返す。
    # BFF 層で個別ガードを入れているが、ここで一括処理するのが canonical パス。
    return normalize_for_python(result)
