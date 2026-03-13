from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import pandas as pd

from src.scenario_overlay import default_scenario_overlay


DEFAULT_OPERATOR_ID = "tokyu"
DEFAULT_DATASET_ID = "tokyu_core"
MISSING_BUILT_DATA_MESSAGE = "Timetable/trip data not found. Run data-prep first."

_REPO_ROOT = Path(__file__).resolve().parents[1]
_DATA_ROOT = _REPO_ROOT / "data"
_SEED_ROOT = _DATA_ROOT / "seed" / DEFAULT_OPERATOR_ID
_BUILT_ROOT = _DATA_ROOT / "built"


def _read_json(path: Path) -> Dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return dict(payload) if isinstance(payload, dict) else {}


def _read_csv_rows(path: Path) -> List[Dict[str, Any]]:
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        return [dict(row) for row in csv.DictReader(fh)]


def _read_parquet_rows(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    frame = pd.read_parquet(path)
    frame = frame.where(pd.notnull(frame), None)
    return [dict(item) for item in frame.to_dict(orient="records")]


def _seed_dataset_path(dataset_id: str) -> Path:
    return _SEED_ROOT / "datasets" / f"{dataset_id}.json"


def _built_dataset_dir(dataset_id: str) -> Path:
    return _BUILT_ROOT / dataset_id


def load_seed_version() -> Dict[str, Any]:
    return _read_json(_SEED_ROOT / "version.json")


def load_seed_depots() -> List[Dict[str, Any]]:
    payload = _read_json(_SEED_ROOT / "depots.json")
    return [dict(item) for item in payload.get("depots") or [] if isinstance(item, dict)]


def load_route_to_depot_rows() -> List[Dict[str, Any]]:
    return _read_csv_rows(_SEED_ROOT / "route_to_depot.csv")


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
    version = load_seed_version()
    return str(version.get("dataset_version") or version.get("seed_version") or "unknown")


def _included_route_codes(definition: Dict[str, Any]) -> Optional[set[str]]:
    included = definition.get("included_routes")
    if included == "ALL":
        return None
    return {str(item) for item in list(included or []) if str(item).strip()}


def _normalize_route_id(route_code: str, depot_id: str) -> str:
    return f"{DEFAULT_OPERATOR_ID}:{depot_id}:{route_code}"


def _normalize_route_row(row: Dict[str, Any]) -> Dict[str, Any]:
    route_id = str(
        row.get("id") or row.get("route_id") or row.get("routeId") or ""
    ).strip()
    route_code = str(
        row.get("routeCode") or row.get("route_code") or route_id
    ).strip()
    normalized = {
        "id": route_id or route_code,
        "name": row.get("name") or row.get("routeLabel") or row.get("route_label") or route_code,
        "routeCode": route_code,
        "routeLabel": row.get("routeLabel") or row.get("route_label") or row.get("name") or route_code,
        "startStop": row.get("startStop") or row.get("origin") or row.get("start_stop") or "",
        "endStop": row.get("endStop") or row.get("destination") or row.get("end_stop") or "",
        "distanceKm": float(row.get("distanceKm") or row.get("distance_km") or 0.0),
        "durationMin": int(float(row.get("durationMin") or row.get("duration_min") or 0)),
        "color": row.get("color") or row.get("route_color") or "",
        "enabled": bool(row.get("enabled", True)),
        "source": row.get("source") or "built_dataset",
        "depotId": row.get("depotId") or row.get("depot_id"),
        "routeFamilyCode": row.get("routeFamilyCode") or row.get("route_family_code"),
        "routeFamilyLabel": row.get("routeFamilyLabel") or row.get("route_family_label"),
        "routeVariantType": row.get("routeVariantType") or row.get("route_variant_type"),
        "canonicalDirection": row.get("canonicalDirection") or row.get("canonical_direction"),
        "tripCount": int(float(row.get("tripCount") or row.get("trip_count") or 0)),
        "stopSequence": list(row.get("stopSequence") or row.get("stop_sequence") or []),
    }
    return normalized


def _normalize_timetable_row(row: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "trip_id": str(row.get("trip_id") or row.get("tripId") or "").strip(),
        "route_id": str(row.get("route_id") or row.get("routeId") or "").strip(),
        "service_id": str(row.get("service_id") or row.get("serviceId") or "WEEKDAY").strip() or "WEEKDAY",
        "direction": str(row.get("direction") or "outbound").strip() or "outbound",
        "origin": row.get("origin") or row.get("origin_name") or row.get("origin_stop_name") or "",
        "destination": row.get("destination") or row.get("destination_name") or row.get("destination_stop_name") or "",
        "departure": str(row.get("departure") or row.get("departure_time") or "").strip(),
        "arrival": str(row.get("arrival") or row.get("arrival_time") or "").strip(),
        "distance_km": float(row.get("distance_km") or row.get("distanceKm") or 0.0),
        "allowed_vehicle_types": list(row.get("allowed_vehicle_types") or row.get("allowedVehicleTypes") or ["BEV", "ICE"]),
        "source": row.get("source") or "built_dataset",
    }


def _normalize_trip_row(row: Dict[str, Any]) -> Dict[str, Any]:
    normalized = _normalize_timetable_row(row)
    return {
        **normalized,
        "trip_id": normalized["trip_id"] or f"trip:{normalized['route_id']}:{normalized['departure']}",
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


def _filter_rows_by_route_ids(
    rows: Iterable[Dict[str, Any]],
    route_ids: set[str],
) -> List[Dict[str, Any]]:
    return [row for row in rows if str(row.get("route_id") or "") in route_ids]


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


def get_dataset_status(dataset_id: str) -> Dict[str, Any]:
    definition = load_dataset_definition(dataset_id)
    manifest = get_built_manifest(dataset_id)
    built_dir = _built_dataset_dir(dataset_id)
    required_files = {
        "routes": built_dir / "routes.parquet",
        "trips": built_dir / "trips.parquet",
        "timetables": built_dir / "timetables.parquet",
    }
    built_available = bool(manifest) and all(path.exists() for path in required_files.values())
    dataset_version = str(
        (manifest or {}).get("dataset_version")
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
        "builtAvailable": built_available,
        "warning": None if built_available else MISSING_BUILT_DATA_MESSAGE,
        "manifest": manifest,
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
    depots = [
        dict(item)
        for item in load_seed_depots()
        if str(item.get("id") or item.get("depotId") or "")
        in {str(value) for value in definition.get("included_depots") or []}
    ]
    route_rows = load_route_to_depot_rows()

    if status["builtAvailable"]:
        built_dir = _built_dataset_dir(dataset_id)
        routes = _filter_built_routes(
            definition,
            _read_parquet_rows(built_dir / "routes.parquet"),
            route_rows,
        )
        route_ids = {str(item.get("id") or "") for item in routes}
        timetable_rows = _filter_rows_by_route_ids(
            [_normalize_timetable_row(item) for item in _read_parquet_rows(built_dir / "timetables.parquet")],
            route_ids,
        )
        trips = _filter_rows_by_route_ids(
            [_normalize_trip_row(item) for item in _read_parquet_rows(built_dir / "trips.parquet")],
            route_ids,
        )
        source = "built_dataset"
    else:
        routes = _seed_route_items(definition, route_rows)
        timetable_rows = []
        trips = []
        source = "seed_only"

    route_assignments = _build_route_assignments(routes, route_rows)
    depot_permissions = _build_depot_permissions(route_assignments)
    calendar_entries = _derive_calendar_entries(timetable_rows)
    overlay = default_scenario_overlay(
        scenario_id=scenario_id,
        dataset_id=dataset_id,
        dataset_version=str(status.get("datasetVersion") or _dataset_version_for(dataset_id)),
        random_seed=random_seed,
        depot_ids=[str(item.get("id") or item.get("depotId")) for item in depots],
        route_ids=[str(item.get("id") or "") for item in routes if item.get("id")],
    )
    return {
        "depots": depots,
        "routes": routes,
        "route_depot_assignments": route_assignments,
        "depot_route_permissions": depot_permissions,
        "timetable_rows": timetable_rows,
        "trips": trips,
        "calendar": calendar_entries,
        "calendar_dates": [],
        "stop_timetables": [],
        "dispatch_scope": {
            "scopeId": f"{dataset_id}:{status.get('datasetVersion')}",
            "operatorId": DEFAULT_OPERATOR_ID,
            "datasetVersion": status.get("datasetVersion"),
            "depotSelection": {
                "mode": "include",
                "depotIds": overlay.depot_ids,
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
        "scenario_overlay": overlay.model_dump(),
        "dataset_status": status,
    }
