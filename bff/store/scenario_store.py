"""
bff/store/scenario_store.py

JSON-file-backed scenario store.
One file per scenario: outputs/scenarios/{scenario_id}.json

Each file stores the complete scenario document:
{
    "meta":    { id, name, description, mode, createdAt, updatedAt, status },
    "depots":  [ Depot ... ],
    "vehicles": [ Vehicle ... ],
    "routes":  [ Route ... ],
    "stops":   [ Stop ... ],
    "depot_route_permissions":   [ {depotId, routeId, allowed} ... ],
    "vehicle_route_permissions": [ {vehicleId, routeId, allowed} ... ],
    "route_import_meta": { "odpt": { ... } },
    "stop_import_meta": { "odpt": { ... } },
    "timetable_import_meta": { "odpt": { ... } },
    "stop_timetable_import_meta": { "odpt": { ... } },
    "timetable_rows": [ TimetableRow ... ],   # service_id field included
    "stop_timetables": [ StopTimetable ... ],
    "calendar": [ ServiceCalendar ... ],      # WEEKDAY/SAT/SUN_HOL definitions
    "calendar_dates": [ CalendarDate ... ],   # exception overrides
    "dispatch_scope": { "depotId": str | null, "serviceId": str },
    "simulation_config": { ... } | null,
    "trips":   [ Trip ... ] | null,
    "graph":   { ... } | null,
    "duties":  [ VehicleDuty ... ] | null,
    "simulation_result":  { ... } | null,
    "optimization_result": { ... } | null,
}
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

_STORE_DIR = Path(__file__).parent.parent.parent / "outputs" / "scenarios"


def _default_dispatch_scope() -> Dict[str, Any]:
    return {"depotId": None, "serviceId": "WEEKDAY"}


def _default_v1_2_fields() -> Dict[str, Any]:
    return {
        "deadhead_rules": [],
        "turnaround_rules": [],
        "charger_sites": [],
        "chargers": [],
        "pv_profiles": [],
        "energy_price_profiles": [],
        "experiment_case_type": None,
        "problemdata_build_audit": None,
        "optimization_audit": None,
        "simulation_audit": None,
    }


def _ensure_dir() -> None:
    _STORE_DIR.mkdir(parents=True, exist_ok=True)


def _path(scenario_id: str) -> Path:
    return _STORE_DIR / f"{scenario_id}.json"


def _load(scenario_id: str) -> Dict[str, Any]:
    p = _path(scenario_id)
    if not p.exists():
        raise KeyError(scenario_id)
    doc = json.loads(p.read_text(encoding="utf-8"))
    doc.setdefault("vehicle_templates", [])
    doc.setdefault("route_depot_assignments", [])
    doc.setdefault("route_import_meta", {})
    doc.setdefault("stop_import_meta", {})
    doc.setdefault("timetable_import_meta", {})
    doc.setdefault("stop_timetable_import_meta", {})
    doc.setdefault("stops", [])
    doc.setdefault("timetable_rows", [])
    doc.setdefault("stop_timetables", [])
    doc.setdefault("calendar", _default_calendar())
    doc.setdefault("calendar_dates", [])
    doc.setdefault("simulation_config", None)
    doc.setdefault("trips", None)
    doc.setdefault("graph", None)
    doc.setdefault("duties", None)
    doc.setdefault("simulation_result", None)
    doc.setdefault("optimization_result", None)
    doc.setdefault("dispatch_scope", _default_dispatch_scope())
    for key, value in _default_v1_2_fields().items():
        doc.setdefault(key, value)
    return doc


def _save(doc: Dict[str, Any]) -> None:
    _ensure_dir()
    scenario_id = doc["meta"]["id"]
    _path(scenario_id).write_text(
        json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8"
    )


# ── Public helpers ─────────────────────────────────────────────


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    return str(uuid.uuid4())


def _invalidate_dispatch_artifacts(doc: Dict[str, Any]) -> None:
    doc["trips"] = None
    doc["graph"] = None
    doc["duties"] = None
    doc["simulation_result"] = None
    doc["optimization_result"] = None
    doc["problemdata_build_audit"] = None
    doc["optimization_audit"] = None
    doc["simulation_audit"] = None
    doc["meta"]["status"] = "draft"


def _normalize_dispatch_scope(doc: Dict[str, Any]) -> Dict[str, Any]:
    scope = doc.setdefault("dispatch_scope", {})
    scope["serviceId"] = str(scope.get("serviceId") or "WEEKDAY")
    depot_ids = {
        str(depot.get("id"))
        for depot in doc.get("depots") or []
        if depot.get("id") is not None
    }
    depot_id = scope.get("depotId")
    if depot_id is None:
        scope["depotId"] = None
    else:
        depot_id = str(depot_id)
        scope["depotId"] = depot_id if depot_id in depot_ids else None
    return dict(scope)


def _sync_depot_route_permissions(
    doc: Dict[str, Any],
    permissions: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    depots = [
        str(depot.get("id"))
        for depot in doc.get("depots") or []
        if depot.get("id") is not None
    ]
    routes = [
        str(route.get("id"))
        for route in doc.get("routes") or []
        if route.get("id") is not None
    ]
    existing = {
        (str(item.get("depotId")), str(item.get("routeId"))): bool(item.get("allowed"))
        for item in doc.get("depot_route_permissions") or []
        if item.get("depotId") is not None and item.get("routeId") is not None
    }
    incoming = {
        (str(item.get("depotId")), str(item.get("routeId"))): bool(item.get("allowed"))
        for item in permissions or []
        if item.get("depotId") is not None and item.get("routeId") is not None
    }

    normalized: List[Dict[str, Any]] = []
    for depot_id in depots:
        for route_id in routes:
            key = (depot_id, route_id)
            allowed = incoming.get(key)
            if allowed is None:
                allowed = existing.get(key)
            if allowed is None:
                allowed = True
            normalized.append(
                {
                    "depotId": depot_id,
                    "routeId": route_id,
                    "allowed": bool(allowed),
                }
            )

    doc["depot_route_permissions"] = normalized
    return list(normalized)


def _sync_vehicle_route_permissions(
    doc: Dict[str, Any],
    permissions: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    valid_vehicle_ids = {
        str(vehicle.get("id"))
        for vehicle in doc.get("vehicles") or []
        if vehicle.get("id") is not None
    }
    valid_route_ids = {
        str(route.get("id"))
        for route in doc.get("routes") or []
        if route.get("id") is not None
    }

    merged: Dict[tuple[str, str], Dict[str, Any]] = {}
    for item in doc.get("vehicle_route_permissions") or []:
        vehicle_id = item.get("vehicleId")
        route_id = item.get("routeId")
        if vehicle_id is None or route_id is None:
            continue
        vehicle_id = str(vehicle_id)
        route_id = str(route_id)
        if vehicle_id not in valid_vehicle_ids or route_id not in valid_route_ids:
            continue
        merged[(vehicle_id, route_id)] = {
            "vehicleId": vehicle_id,
            "routeId": route_id,
            "allowed": bool(item.get("allowed")),
        }

    for item in permissions or []:
        vehicle_id = item.get("vehicleId")
        route_id = item.get("routeId")
        if vehicle_id is None or route_id is None:
            continue
        vehicle_id = str(vehicle_id)
        route_id = str(route_id)
        if vehicle_id not in valid_vehicle_ids or route_id not in valid_route_ids:
            continue
        merged[(vehicle_id, route_id)] = {
            "vehicleId": vehicle_id,
            "routeId": route_id,
            "allowed": bool(item.get("allowed")),
        }

    doc["vehicle_route_permissions"] = list(merged.values())
    return list(doc["vehicle_route_permissions"])


def _default_calendar() -> List[Dict[str, Any]]:
    """Seed three standard service types for every new scenario."""
    return [
        {
            "service_id": "WEEKDAY",
            "name": "平日",
            "mon": 1,
            "tue": 1,
            "wed": 1,
            "thu": 1,
            "fri": 1,
            "sat": 0,
            "sun": 0,
            "start_date": "2026-01-01",
            "end_date": "2026-12-31",
        },
        {
            "service_id": "SAT",
            "name": "土曜",
            "mon": 0,
            "tue": 0,
            "wed": 0,
            "thu": 0,
            "fri": 0,
            "sat": 1,
            "sun": 0,
            "start_date": "2026-01-01",
            "end_date": "2026-12-31",
        },
        {
            "service_id": "SUN_HOL",
            "name": "日曜・休日",
            "mon": 0,
            "tue": 0,
            "wed": 0,
            "thu": 0,
            "fri": 0,
            "sat": 0,
            "sun": 1,
            "start_date": "2026-01-01",
            "end_date": "2026-12-31",
        },
    ]


# ── Scenario CRUD ──────────────────────────────────────────────


def list_scenarios() -> List[Dict[str, Any]]:
    _ensure_dir()
    results = []
    for p in sorted(_STORE_DIR.glob("*.json")):
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
            results.append(doc["meta"])
        except Exception:
            pass
    return results


def create_scenario(name: str, description: str, mode: str) -> Dict[str, Any]:
    scenario_id = _new_id()
    now = _now_iso()
    meta = {
        "id": scenario_id,
        "name": name,
        "description": description,
        "mode": mode,
        "createdAt": now,
        "updatedAt": now,
        "status": "draft",
    }
    doc: Dict[str, Any] = {
        "meta": meta,
        "depots": [],
        "vehicles": [],
        "vehicle_templates": [],
        "routes": [],
        "stops": [],
        "route_depot_assignments": [],
        "depot_route_permissions": [],
        "vehicle_route_permissions": [],
        "route_import_meta": {},
        "stop_import_meta": {},
        "timetable_import_meta": {},
        "timetable_rows": [],
        "stop_timetable_import_meta": {},
        "stop_timetables": [],
        "calendar": _default_calendar(),
        "calendar_dates": [],
        "dispatch_scope": _default_dispatch_scope(),
        "simulation_config": None,
        "trips": None,
        "graph": None,
        "duties": None,
        "simulation_result": None,
        "optimization_result": None,
    }
    doc.update(_default_v1_2_fields())
    _save(doc)
    return meta


def get_scenario(scenario_id: str) -> Dict[str, Any]:
    return _load(scenario_id)["meta"]


def update_scenario(
    scenario_id: str,
    name: Optional[str] = None,
    description: Optional[str] = None,
    mode: Optional[str] = None,
    status: Optional[str] = None,
) -> Dict[str, Any]:
    doc = _load(scenario_id)
    if name is not None:
        doc["meta"]["name"] = name
    if description is not None:
        doc["meta"]["description"] = description
    if mode is not None:
        doc["meta"]["mode"] = mode
    if status is not None:
        doc["meta"]["status"] = status
    doc["meta"]["updatedAt"] = _now_iso()
    _save(doc)
    return doc["meta"]


def delete_scenario(scenario_id: str) -> None:
    p = _path(scenario_id)
    if not p.exists():
        raise KeyError(scenario_id)
    p.unlink()


# ── Generic sub-document accessors ────────────────────────────


def get_field(scenario_id: str, field: str) -> Any:
    return _load(scenario_id)[field]


def set_field(
    scenario_id: str, field: str, value: Any, *, invalidate_dispatch: bool = False
) -> None:
    doc = _load(scenario_id)
    doc[field] = value
    if invalidate_dispatch:
        _invalidate_dispatch_artifacts(doc)
    doc["meta"]["updatedAt"] = _now_iso()
    _save(doc)


# ── Master-data helpers ────────────────────────────────────────


def _list_items(scenario_id: str, field: str) -> List[Dict[str, Any]]:
    return list(get_field(scenario_id, field))


def _get_item(
    scenario_id: str, field: str, item_id_key: str, item_id: str
) -> Dict[str, Any]:
    items = _list_items(scenario_id, field)
    for item in items:
        if item.get(item_id_key) == item_id:
            return item
    raise KeyError(item_id)


def _create_item(scenario_id: str, field: str, data: Dict[str, Any]) -> Dict[str, Any]:
    doc = _load(scenario_id)
    item = dict(data)
    item["id"] = _new_id()
    doc[field].append(item)
    if field in {"depots", "vehicles", "routes"}:
        _invalidate_dispatch_artifacts(doc)
    if field in {"depots", "routes"}:
        _sync_depot_route_permissions(doc)
        _normalize_dispatch_scope(doc)
    if field in {"vehicles", "routes"}:
        _sync_vehicle_route_permissions(doc)
    doc["meta"]["updatedAt"] = _now_iso()
    _save(doc)
    return item


def _update_item(
    scenario_id: str, field: str, item_id_key: str, item_id: str, patch: Dict[str, Any]
) -> Dict[str, Any]:
    doc = _load(scenario_id)
    for item in doc[field]:
        if item.get(item_id_key) == item_id:
            item.update({k: v for k, v in patch.items() if v is not None})
            if field in {"depots", "vehicles", "routes"}:
                _invalidate_dispatch_artifacts(doc)
            if field in {"depots", "routes"}:
                _sync_depot_route_permissions(doc)
                _normalize_dispatch_scope(doc)
            if field in {"vehicles", "routes"}:
                _sync_vehicle_route_permissions(doc)
            doc["meta"]["updatedAt"] = _now_iso()
            _save(doc)
            return item
    raise KeyError(item_id)


def _delete_item(scenario_id: str, field: str, item_id_key: str, item_id: str) -> None:
    doc = _load(scenario_id)
    before = len(doc[field])
    doc[field] = [i for i in doc[field] if i.get(item_id_key) != item_id]
    if len(doc[field]) == before:
        raise KeyError(item_id)
    if field in {"depots", "vehicles", "routes"}:
        _invalidate_dispatch_artifacts(doc)
    if field in {"depots", "routes"}:
        _sync_depot_route_permissions(doc)
        _normalize_dispatch_scope(doc)
    if field in {"vehicles", "routes"}:
        _sync_vehicle_route_permissions(doc)
    doc["meta"]["updatedAt"] = _now_iso()
    _save(doc)


# ── Depot helpers ──────────────────────────────────────────────


def list_depots(scenario_id: str) -> List[Dict[str, Any]]:
    return _list_items(scenario_id, "depots")


def get_depot(scenario_id: str, depot_id: str) -> Dict[str, Any]:
    return _get_item(scenario_id, "depots", "id", depot_id)


def create_depot(scenario_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
    return _create_item(scenario_id, "depots", data)


def update_depot(
    scenario_id: str, depot_id: str, patch: Dict[str, Any]
) -> Dict[str, Any]:
    return _update_item(scenario_id, "depots", "id", depot_id, patch)


def delete_depot(scenario_id: str, depot_id: str) -> None:
    _delete_item(scenario_id, "depots", "id", depot_id)
    doc = _load(scenario_id)
    doc["route_depot_assignments"] = [
        item
        for item in doc.get("route_depot_assignments") or []
        if str(item.get("depotId")) != depot_id
    ]
    doc["meta"]["updatedAt"] = _now_iso()
    _save(doc)


# ── Vehicle helpers ────────────────────────────────────────────


def list_vehicles(
    scenario_id: str, depot_id: Optional[str] = None
) -> List[Dict[str, Any]]:
    items = _list_items(scenario_id, "vehicles")
    if depot_id:
        items = [v for v in items if v.get("depotId") == depot_id]
    return items


def get_vehicle(scenario_id: str, vehicle_id: str) -> Dict[str, Any]:
    return _get_item(scenario_id, "vehicles", "id", vehicle_id)


def create_vehicle(scenario_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
    return _create_item(scenario_id, "vehicles", data)


def _next_vehicle_copy_name(existing_names: set[str], base_name: str) -> str:
    candidate = f"{base_name} (copy)"
    if candidate not in existing_names:
        existing_names.add(candidate)
        return candidate

    idx = 2
    while True:
        candidate = f"{base_name} (copy {idx})"
        if candidate not in existing_names:
            existing_names.add(candidate)
            return candidate
        idx += 1


def create_vehicle_batch(
    scenario_id: str, data: Dict[str, Any], quantity: int
) -> List[Dict[str, Any]]:
    if quantity < 1:
        raise ValueError("quantity must be >= 1")

    if quantity == 1:
        return [create_vehicle(scenario_id, data)]

    doc = _load(scenario_id)
    base_name = (data.get("modelName") or "New vehicle").strip() or "New vehicle"
    created: List[Dict[str, Any]] = []

    for idx in range(quantity):
        item = dict(data)
        item["id"] = _new_id()
        item["modelName"] = f"{base_name} #{idx + 1}"
        doc["vehicles"].append(item)
        created.append(item)

    doc["meta"]["updatedAt"] = _now_iso()
    _save(doc)
    return created


def _allowed_route_ids_for_depot(
    doc: Dict[str, Any], depot_id: str
) -> Optional[set[str]]:
    matching_permissions = [
        permission
        for permission in doc.get("depot_route_permissions", [])
        if permission.get("depotId") == depot_id
    ]
    if not matching_permissions:
        return None
    return {
        str(permission.get("routeId"))
        for permission in matching_permissions
        if permission.get("allowed") is True
    }


def duplicate_vehicle_batch(
    scenario_id: str,
    vehicle_id: str,
    quantity: int,
    target_depot_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    if quantity < 1:
        raise ValueError("quantity must be >= 1")

    doc = _load(scenario_id)
    source = next((v for v in doc["vehicles"] if v.get("id") == vehicle_id), None)
    if source is None:
        raise KeyError(vehicle_id)
    effective_target_depot_id = target_depot_id or source.get("depotId")

    existing_names = {
        (item.get("modelName") or "").strip()
        for item in doc["vehicles"]
        if isinstance(item.get("modelName"), str)
    }
    base_name = (source.get("modelName") or "Vehicle").strip() or "Vehicle"
    source_permissions = [
        perm
        for perm in doc.get("vehicle_route_permissions", [])
        if perm.get("vehicleId") == vehicle_id
    ]
    allowed_route_ids = (
        _allowed_route_ids_for_depot(doc, str(effective_target_depot_id))
        if effective_target_depot_id
        else set()
    )
    created_items: List[Dict[str, Any]] = []

    for _ in range(quantity):
        created = {k: v for k, v in source.items() if k != "id"}
        created["id"] = _new_id()
        if effective_target_depot_id:
            created["depotId"] = effective_target_depot_id
        created["modelName"] = _next_vehicle_copy_name(existing_names, base_name)
        doc["vehicles"].append(created)
        created_items.append(created)

        for perm in source_permissions:
            route_id = perm.get("routeId")
            if allowed_route_ids is not None and route_id not in allowed_route_ids:
                continue
            doc["vehicle_route_permissions"].append(
                {
                    **perm,
                    "vehicleId": created["id"],
                }
            )

    doc["meta"]["updatedAt"] = _now_iso()
    _save(doc)
    return created_items


def update_vehicle(
    scenario_id: str, vehicle_id: str, patch: Dict[str, Any]
) -> Dict[str, Any]:
    return _update_item(scenario_id, "vehicles", "id", vehicle_id, patch)


def delete_vehicle(scenario_id: str, vehicle_id: str) -> None:
    doc = _load(scenario_id)
    before = len(doc["vehicles"])
    doc["vehicles"] = [v for v in doc["vehicles"] if v.get("id") != vehicle_id]
    if len(doc["vehicles"]) == before:
        raise KeyError(vehicle_id)
    doc["vehicle_route_permissions"] = [
        p for p in doc["vehicle_route_permissions"] if p.get("vehicleId") != vehicle_id
    ]
    doc["meta"]["updatedAt"] = _now_iso()
    _save(doc)


def duplicate_vehicle(scenario_id: str, vehicle_id: str) -> Dict[str, Any]:
    return duplicate_vehicle_batch(scenario_id, vehicle_id, quantity=1)[0]


def duplicate_vehicle_to_depot(
    scenario_id: str,
    vehicle_id: str,
    *,
    target_depot_id: Optional[str] = None,
) -> Dict[str, Any]:
    return duplicate_vehicle_batch(
        scenario_id,
        vehicle_id,
        quantity=1,
        target_depot_id=target_depot_id,
    )[0]


def list_vehicle_templates(scenario_id: str) -> List[Dict[str, Any]]:
    doc = _load(scenario_id)
    return list(doc.get("vehicle_templates") or [])


def get_vehicle_template(scenario_id: str, template_id: str) -> Dict[str, Any]:
    doc = _load(scenario_id)
    for item in doc.get("vehicle_templates") or []:
        if item.get("id") == template_id:
            return item
    raise KeyError(template_id)


def create_vehicle_template(scenario_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
    doc = _load(scenario_id)
    item = dict(data)
    item["id"] = _new_id()
    doc.setdefault("vehicle_templates", []).append(item)
    doc["meta"]["updatedAt"] = _now_iso()
    _save(doc)
    return item


def update_vehicle_template(
    scenario_id: str, template_id: str, patch: Dict[str, Any]
) -> Dict[str, Any]:
    doc = _load(scenario_id)
    templates = doc.setdefault("vehicle_templates", [])
    for item in templates:
        if item.get("id") == template_id:
            item.update({k: v for k, v in patch.items() if v is not None})
            doc["meta"]["updatedAt"] = _now_iso()
            _save(doc)
            return item
    raise KeyError(template_id)


def delete_vehicle_template(scenario_id: str, template_id: str) -> None:
    doc = _load(scenario_id)
    templates = doc.setdefault("vehicle_templates", [])
    before = len(templates)
    doc["vehicle_templates"] = [i for i in templates if i.get("id") != template_id]
    if len(doc["vehicle_templates"]) == before:
        raise KeyError(template_id)
    doc["meta"]["updatedAt"] = _now_iso()
    _save(doc)


# ── Route helpers ──────────────────────────────────────────────


def _operator_matches_route(route: Dict[str, Any], operator: Optional[str]) -> bool:
    if not operator:
        return True
    source = str(route.get("source") or "").lower()
    if operator == "tokyu":
        return source in {"", "manual", "odpt"}
    if operator == "toei":
        return source in {"", "manual", "gtfs"}
    return source == operator.lower()


def _route_assignment_map(doc: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    valid_route_ids = {
        str(route.get("id"))
        for route in doc.get("routes") or []
        if route.get("id") is not None
    }
    valid_depot_ids = {
        str(depot.get("id"))
        for depot in doc.get("depots") or []
        if depot.get("id") is not None
    }
    assignments: Dict[str, Dict[str, Any]] = {}
    for item in doc.get("route_depot_assignments") or []:
        route_id = item.get("routeId")
        depot_id = item.get("depotId")
        if route_id is None or depot_id is None:
            continue
        route_id = str(route_id)
        depot_id = str(depot_id)
        if route_id not in valid_route_ids or depot_id not in valid_depot_ids:
            continue
        assignments[route_id] = {
            "routeId": route_id,
            "depotId": depot_id,
            "assignmentType": str(item.get("assignmentType") or "manual_override"),
            "confidence": float(item.get("confidence") or 0.0),
            "reason": str(item.get("reason") or ""),
            "sourceRefs": list(item.get("sourceRefs") or []),
            "updatedAt": str(item.get("updatedAt") or _now_iso()),
        }
    return assignments


def list_routes(
    scenario_id: str,
    depot_id: Optional[str] = None,
    operator: Optional[str] = None,
) -> List[Dict[str, Any]]:
    doc = _load(scenario_id)
    assignments = _route_assignment_map(doc)
    items: List[Dict[str, Any]] = []
    for route in doc.get("routes") or []:
        if not _operator_matches_route(route, operator):
            continue
        route_id = route.get("id")
        assignment = assignments.get(str(route_id)) if route_id is not None else None
        effective_depot_id = assignment.get("depotId") if assignment else route.get("depotId")
        if depot_id and effective_depot_id != depot_id:
            continue
        items.append(
            {
                **route,
                "depotId": effective_depot_id,
                "assignmentType": assignment.get("assignmentType") if assignment else None,
                "assignmentConfidence": assignment.get("confidence") if assignment else None,
                "assignmentReason": assignment.get("reason") if assignment else None,
            }
        )
    return items


def get_route(scenario_id: str, route_id: str) -> Dict[str, Any]:
    doc = _load(scenario_id)
    route = _get_item(scenario_id, "routes", "id", route_id)
    assignment = _route_assignment_map(doc).get(route_id)
    if assignment is None:
        return route
    return {
        **route,
        "depotId": assignment.get("depotId"),
        "assignmentType": assignment.get("assignmentType"),
        "assignmentConfidence": assignment.get("confidence"),
        "assignmentReason": assignment.get("reason"),
    }


def create_route(scenario_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
    return _create_item(scenario_id, "routes", data)


def update_route(
    scenario_id: str, route_id: str, patch: Dict[str, Any]
) -> Dict[str, Any]:
    return _update_item(scenario_id, "routes", "id", route_id, patch)


def delete_route(scenario_id: str, route_id: str) -> None:
    _delete_item(scenario_id, "routes", "id", route_id)
    doc = _load(scenario_id)
    doc["route_depot_assignments"] = [
        item
        for item in doc.get("route_depot_assignments") or []
        if str(item.get("routeId")) != route_id
    ]
    doc["meta"]["updatedAt"] = _now_iso()
    _save(doc)


def replace_routes_from_source(
    scenario_id: str,
    source: str,
    routes: List[Dict[str, Any]],
    import_meta: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    doc = _load(scenario_id)
    route_import_meta = doc.setdefault("route_import_meta", {})
    preserved = [r for r in doc["routes"] if r.get("source") != source]
    doc["routes"] = preserved + routes
    surviving_route_ids = {
        str(r.get("id")) for r in doc["routes"] if r.get("id") is not None
    }
    doc["route_depot_assignments"] = [
        assignment
        for assignment in doc.get("route_depot_assignments") or []
        if str(assignment.get("routeId") or "") in surviving_route_ids
    ]
    if import_meta is not None:
        route_import_meta[source] = import_meta

    # Prune permissions referencing route IDs that no longer exist.
    doc["depot_route_permissions"] = [
        perm
        for perm in doc.get("depot_route_permissions") or []
        if str(perm.get("routeId", "")) in surviving_route_ids
    ]
    doc["vehicle_route_permissions"] = [
        perm
        for perm in doc.get("vehicle_route_permissions") or []
        if str(perm.get("routeId", "")) in surviving_route_ids
    ]

    _invalidate_dispatch_artifacts(doc)
    _normalize_dispatch_scope(doc)
    doc["meta"]["updatedAt"] = _now_iso()
    _save(doc)
    return list(doc["routes"])


def get_route_import_meta(
    scenario_id: str, source: Optional[str] = None
) -> Dict[str, Any]:
    doc = _load(scenario_id)
    route_import_meta = doc.get("route_import_meta") or {}
    if source is None:
        return dict(route_import_meta)
    value = route_import_meta.get(source)
    return dict(value) if isinstance(value, dict) else {}


def list_route_depot_assignments(
    scenario_id: str,
    operator: Optional[str] = None,
    unresolved_only: bool = False,
) -> List[Dict[str, Any]]:
    doc = _load(scenario_id)
    routes_by_id = {
        str(route.get("id")): dict(route)
        for route in doc.get("routes") or []
        if route.get("id") is not None and _operator_matches_route(route, operator)
    }
    depots_by_id = {
        str(depot.get("id")): dict(depot)
        for depot in doc.get("depots") or []
        if depot.get("id") is not None
    }
    assignments = _route_assignment_map(doc)
    items: List[Dict[str, Any]] = []
    for route_id, route in routes_by_id.items():
        assignment = assignments.get(route_id)
        if unresolved_only and assignment is not None:
            continue
        depot = depots_by_id.get(str(assignment.get("depotId"))) if assignment else None
        items.append(
            {
                "routeId": route_id,
                "routeName": route.get("name"),
                "routeCode": route.get("routeCode") or route_id,
                "startStop": route.get("startStop"),
                "endStop": route.get("endStop"),
                "source": route.get("source"),
                "tripCount": route.get("tripCount") or 0,
                "stopCount": len(list(route.get("stopSequence") or [])),
                "depotId": assignment.get("depotId") if assignment else None,
                "depotName": depot.get("name") if depot else None,
                "assignmentType": assignment.get("assignmentType") if assignment else None,
                "confidence": assignment.get("confidence") if assignment else None,
                "reason": assignment.get("reason") if assignment else "",
                "sourceRefs": assignment.get("sourceRefs") if assignment else [],
                "updatedAt": assignment.get("updatedAt") if assignment else None,
            }
        )
    items.sort(
        key=lambda item: (
            str(item.get("depotName") or "~"),
            str(item.get("routeCode") or ""),
            str(item.get("routeName") or ""),
        )
    )
    return items


def upsert_route_depot_assignment(
    scenario_id: str,
    route_id: str,
    data: Dict[str, Any],
) -> Dict[str, Any]:
    doc = _load(scenario_id)
    route_exists = any(
        str(route.get("id")) == route_id for route in doc.get("routes") or []
    )
    if not route_exists:
        raise KeyError(route_id)

    depot_id = data.get("depotId")
    if depot_id is not None:
        depot_id = str(depot_id)
        valid_depot_ids = {
            str(depot.get("id"))
            for depot in doc.get("depots") or []
            if depot.get("id") is not None
        }
        if depot_id not in valid_depot_ids:
            raise ValueError(f"Unknown depot '{depot_id}'")

    doc["route_depot_assignments"] = [
        item
        for item in doc.get("route_depot_assignments") or []
        if str(item.get("routeId")) != route_id
    ]
    if depot_id is not None:
        doc["route_depot_assignments"].append(
            {
                "routeId": route_id,
                "depotId": depot_id,
                "assignmentType": str(data.get("assignmentType") or "manual_override"),
                "confidence": float(data.get("confidence") or 1.0),
                "reason": str(data.get("reason") or ""),
                "sourceRefs": list(data.get("sourceRefs") or []),
                "updatedAt": _now_iso(),
            }
        )
    _invalidate_dispatch_artifacts(doc)
    doc["meta"]["updatedAt"] = _now_iso()
    _save(doc)
    assignment = _route_assignment_map(doc).get(route_id)
    return {
        "routeId": route_id,
        "depotId": assignment.get("depotId") if assignment else None,
        "assignmentType": assignment.get("assignmentType") if assignment else None,
        "confidence": assignment.get("confidence") if assignment else None,
        "reason": assignment.get("reason") if assignment else "",
        "sourceRefs": assignment.get("sourceRefs") if assignment else [],
        "updatedAt": assignment.get("updatedAt") if assignment else None,
    }


def list_stops(scenario_id: str) -> List[Dict[str, Any]]:
    return _list_items(scenario_id, "stops")


def replace_stops_from_source(
    scenario_id: str,
    source: str,
    stops: List[Dict[str, Any]],
    import_meta: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    doc = _load(scenario_id)
    stop_import_meta = doc.setdefault("stop_import_meta", {})
    preserved = [stop for stop in doc.get("stops", []) if stop.get("source") != source]
    normalized_stops = []
    seen_ids = set()
    for stop in stops:
        stop_id = stop.get("id")
        if not stop_id or stop_id in seen_ids:
            continue
        seen_ids.add(stop_id)
        normalized_stops.append(dict(stop))
    doc["stops"] = preserved + normalized_stops
    if import_meta is not None:
        stop_import_meta[source] = import_meta
    _invalidate_dispatch_artifacts(doc)
    doc["meta"]["updatedAt"] = _now_iso()
    _save(doc)
    return list(doc["stops"])


def get_stop_import_meta(
    scenario_id: str, source: Optional[str] = None
) -> Dict[str, Any]:
    doc = _load(scenario_id)
    stop_import_meta = doc.get("stop_import_meta") or {}
    if source is None:
        return dict(stop_import_meta)
    value = stop_import_meta.get(source)
    return dict(value) if isinstance(value, dict) else {}


def set_stop_import_meta(
    scenario_id: str, source: str, import_meta: Dict[str, Any]
) -> Dict[str, Any]:
    doc = _load(scenario_id)
    stop_import_meta = doc.setdefault("stop_import_meta", {})
    stop_import_meta[source] = import_meta
    doc["meta"]["updatedAt"] = _now_iso()
    _save(doc)
    return dict(import_meta)


def set_timetable_import_meta(
    scenario_id: str, source: str, import_meta: Dict[str, Any]
) -> Dict[str, Any]:
    doc = _load(scenario_id)
    timetable_import_meta = doc.setdefault("timetable_import_meta", {})
    timetable_import_meta[source] = import_meta
    doc["meta"]["updatedAt"] = _now_iso()
    _save(doc)
    return dict(import_meta)


def get_timetable_import_meta(
    scenario_id: str, source: Optional[str] = None
) -> Dict[str, Any]:
    doc = _load(scenario_id)
    timetable_import_meta = doc.get("timetable_import_meta") or {}
    if source is None:
        return dict(timetable_import_meta)
    value = timetable_import_meta.get(source)
    return dict(value) if isinstance(value, dict) else {}


def upsert_timetable_rows_from_source(
    scenario_id: str,
    source: str,
    rows: List[Dict[str, Any]],
    *,
    replace_existing_source: bool = False,
) -> List[Dict[str, Any]]:
    doc = _load(scenario_id)
    existing_rows = list(doc.get("timetable_rows") or [])

    preserved_rows = [row for row in existing_rows if row.get("source") != source]
    source_rows = (
        []
        if replace_existing_source
        else [row for row in existing_rows if row.get("source") == source]
    )

    def _row_key(row: Dict[str, Any]) -> str:
        trip_id = row.get("trip_id")
        if trip_id:
            return f"trip:{trip_id}"
        return json.dumps(
            {
                "route_id": row.get("route_id"),
                "service_id": row.get("service_id"),
                "direction": row.get("direction"),
                "origin": row.get("origin"),
                "destination": row.get("destination"),
                "departure": row.get("departure"),
                "arrival": row.get("arrival"),
            },
            ensure_ascii=False,
            sort_keys=True,
        )

    merged: Dict[str, Dict[str, Any]] = {}
    for row in source_rows:
        merged[_row_key(row)] = dict(row)
    for row in rows:
        candidate = dict(row)
        candidate["source"] = source
        merged[_row_key(candidate)] = candidate

    doc["timetable_rows"] = preserved_rows + list(merged.values())
    _invalidate_dispatch_artifacts(doc)
    doc["meta"]["updatedAt"] = _now_iso()
    _save(doc)
    return list(doc["timetable_rows"])


def set_stop_timetable_import_meta(
    scenario_id: str, source: str, import_meta: Dict[str, Any]
) -> Dict[str, Any]:
    doc = _load(scenario_id)
    stop_timetable_import_meta = doc.setdefault("stop_timetable_import_meta", {})
    stop_timetable_import_meta[source] = import_meta
    doc["meta"]["updatedAt"] = _now_iso()
    _save(doc)
    return dict(import_meta)


def get_stop_timetable_import_meta(
    scenario_id: str, source: Optional[str] = None
) -> Dict[str, Any]:
    doc = _load(scenario_id)
    stop_timetable_import_meta = doc.get("stop_timetable_import_meta") or {}
    if source is None:
        return dict(stop_timetable_import_meta)
    value = stop_timetable_import_meta.get(source)
    return dict(value) if isinstance(value, dict) else {}


def upsert_stop_timetables_from_source(
    scenario_id: str,
    source: str,
    items: List[Dict[str, Any]],
    *,
    replace_existing_source: bool = False,
) -> List[Dict[str, Any]]:
    doc = _load(scenario_id)
    existing_items = list(doc.get("stop_timetables") or [])
    preserved_items = [item for item in existing_items if item.get("source") != source]
    source_items = (
        []
        if replace_existing_source
        else [item for item in existing_items if item.get("source") == source]
    )

    merged: Dict[str, Dict[str, Any]] = {
        str(item.get("id") or item.get("stopId") or uuid.uuid4()): dict(item)
        for item in source_items
    }
    for item in items:
        candidate = dict(item)
        candidate["source"] = source
        merged[str(candidate.get("id") or candidate.get("stopId") or uuid.uuid4())] = (
            candidate
        )

    doc["stop_timetables"] = preserved_items + list(merged.values())
    _invalidate_dispatch_artifacts(doc)
    doc["meta"]["updatedAt"] = _now_iso()
    _save(doc)
    return list(doc["stop_timetables"])


# ── Permission helpers ─────────────────────────────────────────


def get_depot_route_permissions(scenario_id: str) -> List[Dict[str, Any]]:
    doc = _load(scenario_id)
    return list(doc.get("depot_route_permissions") or [])


def set_depot_route_permissions(
    scenario_id: str, permissions: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    doc = _load(scenario_id)
    # Store permissions as given by the caller (may reference entities
    # not yet created, e.g. during cross-scenario setup). The _sync
    # helpers are called on entity lifecycle events to prune stale entries.
    sanitized = [
        {
            "depotId": str(item.get("depotId")),
            "routeId": str(item.get("routeId")),
            "allowed": bool(item.get("allowed")),
        }
        for item in permissions
        if item.get("depotId") is not None and item.get("routeId") is not None
    ]
    doc["depot_route_permissions"] = sanitized
    _invalidate_dispatch_artifacts(doc)
    _normalize_dispatch_scope(doc)
    doc["meta"]["updatedAt"] = _now_iso()
    _save(doc)
    return list(sanitized)


def get_vehicle_route_permissions(scenario_id: str) -> List[Dict[str, Any]]:
    doc = _load(scenario_id)
    return list(doc.get("vehicle_route_permissions") or [])


def set_vehicle_route_permissions(
    scenario_id: str, permissions: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    doc = _load(scenario_id)
    # Store permissions as given by the caller (may reference entities
    # not yet created). The _sync helpers are called on entity lifecycle
    # events to prune stale entries.
    sanitized = [
        {
            "vehicleId": str(item.get("vehicleId")),
            "routeId": str(item.get("routeId")),
            "allowed": bool(item.get("allowed")),
        }
        for item in permissions
        if item.get("vehicleId") is not None and item.get("routeId") is not None
    ]
    doc["vehicle_route_permissions"] = sanitized
    _invalidate_dispatch_artifacts(doc)
    doc["meta"]["updatedAt"] = _now_iso()
    _save(doc)
    return list(sanitized)


def get_deadhead_rules(scenario_id: str) -> List[Dict[str, Any]]:
    doc = _load(scenario_id)
    return list(doc.get("deadhead_rules") or [])


def set_deadhead_rules(
    scenario_id: str, rules: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    doc = _load(scenario_id)
    sanitized = [
        {
            "from_stop": str(item.get("from_stop")),
            "to_stop": str(item.get("to_stop")),
            "travel_time_min": int(item.get("travel_time_min") or 0),
            "distance_km": float(item.get("distance_km") or 0.0),
            "energy_kwh_bev": (
                float(item.get("energy_kwh_bev"))
                if item.get("energy_kwh_bev") is not None
                else None
            ),
            "fuel_l_ice": (
                float(item.get("fuel_l_ice"))
                if item.get("fuel_l_ice") is not None
                else None
            ),
        }
        for item in rules
        if item.get("from_stop") is not None and item.get("to_stop") is not None
    ]
    doc["deadhead_rules"] = sanitized
    _invalidate_dispatch_artifacts(doc)
    doc["meta"]["updatedAt"] = _now_iso()
    _save(doc)
    return list(sanitized)


def get_turnaround_rules(scenario_id: str) -> List[Dict[str, Any]]:
    doc = _load(scenario_id)
    return list(doc.get("turnaround_rules") or [])


def set_turnaround_rules(
    scenario_id: str, rules: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    doc = _load(scenario_id)
    sanitized = [
        {
            "stop_id": str(item.get("stop_id")),
            "min_turnaround_min": int(item.get("min_turnaround_min") or 0),
        }
        for item in rules
        if item.get("stop_id") is not None
    ]
    doc["turnaround_rules"] = sanitized
    _invalidate_dispatch_artifacts(doc)
    doc["meta"]["updatedAt"] = _now_iso()
    _save(doc)
    return list(sanitized)


def get_dispatch_scope(scenario_id: str) -> Dict[str, Any]:
    doc = _load(scenario_id)
    return _normalize_dispatch_scope(doc)


def set_dispatch_scope(scenario_id: str, scope: Dict[str, Any]) -> Dict[str, Any]:
    doc = _load(scenario_id)
    current = _normalize_dispatch_scope(doc)
    next_scope = {
        "depotId": scope.get("depotId"),
        "serviceId": str(
            scope.get("serviceId") or current.get("serviceId") or "WEEKDAY"
        ),
    }
    doc["dispatch_scope"] = next_scope
    normalized = _normalize_dispatch_scope(doc)
    if normalized != current:
        _invalidate_dispatch_artifacts(doc)
    doc["meta"]["updatedAt"] = _now_iso()
    _save(doc)
    return normalized


# ── Calendar helpers ───────────────────────────────────────────


def get_calendar(scenario_id: str) -> List[Dict[str, Any]]:
    """Return the list of service_id definitions for this scenario."""
    doc = _load(scenario_id)
    return doc.get("calendar") or _default_calendar()


def set_calendar(
    scenario_id: str, entries: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """Replace the entire calendar (list of service_id definitions)."""
    doc = _load(scenario_id)
    doc["calendar"] = entries
    _invalidate_dispatch_artifacts(doc)
    doc["meta"]["updatedAt"] = _now_iso()
    _save(doc)
    return entries


def upsert_calendar_entry(scenario_id: str, entry: Dict[str, Any]) -> Dict[str, Any]:
    """Insert or update a single service_id entry (keyed by service_id)."""
    doc = _load(scenario_id)
    calendar: List[Dict[str, Any]] = doc.get("calendar") or _default_calendar()
    sid = entry["service_id"]
    replaced = False
    for i, e in enumerate(calendar):
        if e.get("service_id") == sid:
            calendar[i] = entry
            replaced = True
            break
    if not replaced:
        calendar.append(entry)
    doc["calendar"] = calendar
    _invalidate_dispatch_artifacts(doc)
    doc["meta"]["updatedAt"] = _now_iso()
    _save(doc)
    return entry


def delete_calendar_entry(scenario_id: str, service_id: str) -> None:
    """Delete a service_id definition. Raises KeyError if not found."""
    doc = _load(scenario_id)
    calendar: List[Dict[str, Any]] = doc.get("calendar") or []
    before = len(calendar)
    doc["calendar"] = [e for e in calendar if e.get("service_id") != service_id]
    if len(doc["calendar"]) == before:
        raise KeyError(service_id)
    _invalidate_dispatch_artifacts(doc)
    doc["meta"]["updatedAt"] = _now_iso()
    _save(doc)


# ── Calendar dates helpers ─────────────────────────────────────


def get_calendar_dates(scenario_id: str) -> List[Dict[str, Any]]:
    """Return exception date overrides for this scenario."""
    doc = _load(scenario_id)
    return doc.get("calendar_dates") or []


def set_calendar_dates(
    scenario_id: str, entries: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """Replace the entire calendar_dates list."""
    doc = _load(scenario_id)
    doc["calendar_dates"] = entries
    _invalidate_dispatch_artifacts(doc)
    doc["meta"]["updatedAt"] = _now_iso()
    _save(doc)
    return entries


def upsert_calendar_date(scenario_id: str, entry: Dict[str, Any]) -> Dict[str, Any]:
    """Insert or update a single date exception (keyed by date)."""
    doc = _load(scenario_id)
    dates: List[Dict[str, Any]] = doc.get("calendar_dates") or []
    date_key = entry["date"]
    replaced = False
    for i, e in enumerate(dates):
        if e.get("date") == date_key:
            dates[i] = entry
            replaced = True
            break
    if not replaced:
        dates.append(entry)
    doc["calendar_dates"] = dates
    _invalidate_dispatch_artifacts(doc)
    doc["meta"]["updatedAt"] = _now_iso()
    _save(doc)
    return entry


def delete_calendar_date(scenario_id: str, date: str) -> None:
    """Delete a date exception. Raises KeyError if not found."""
    doc = _load(scenario_id)
    dates: List[Dict[str, Any]] = doc.get("calendar_dates") or []
    before = len(dates)
    doc["calendar_dates"] = [e for e in dates if e.get("date") != date]
    if len(doc["calendar_dates"]) == before:
        raise KeyError(date)
    _invalidate_dispatch_artifacts(doc)
    doc["meta"]["updatedAt"] = _now_iso()
    _save(doc)
