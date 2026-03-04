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
    "depot_route_permissions":   [ {depotId, routeId, allowed} ... ],
    "vehicle_route_permissions": [ {vehicleId, routeId, allowed} ... ],
    "timetable_rows": [ TimetableRow ... ],
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


def _ensure_dir() -> None:
    _STORE_DIR.mkdir(parents=True, exist_ok=True)


def _path(scenario_id: str) -> Path:
    return _STORE_DIR / f"{scenario_id}.json"


def _load(scenario_id: str) -> Dict[str, Any]:
    p = _path(scenario_id)
    if not p.exists():
        raise KeyError(scenario_id)
    return json.loads(p.read_text(encoding="utf-8"))


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
        "routes": [],
        "depot_route_permissions": [],
        "vehicle_route_permissions": [],
        "timetable_rows": [],
        "simulation_config": None,
        "trips": None,
        "graph": None,
        "duties": None,
        "simulation_result": None,
        "optimization_result": None,
    }
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


def set_field(scenario_id: str, field: str, value: Any) -> None:
    doc = _load(scenario_id)
    doc[field] = value
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
    data["id"] = _new_id()
    doc[field].append(data)
    doc["meta"]["updatedAt"] = _now_iso()
    _save(doc)
    return data


def _update_item(
    scenario_id: str, field: str, item_id_key: str, item_id: str, patch: Dict[str, Any]
) -> Dict[str, Any]:
    doc = _load(scenario_id)
    for item in doc[field]:
        if item.get(item_id_key) == item_id:
            item.update({k: v for k, v in patch.items() if v is not None})
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


def update_vehicle(
    scenario_id: str, vehicle_id: str, patch: Dict[str, Any]
) -> Dict[str, Any]:
    return _update_item(scenario_id, "vehicles", "id", vehicle_id, patch)


def delete_vehicle(scenario_id: str, vehicle_id: str) -> None:
    _delete_item(scenario_id, "vehicles", "id", vehicle_id)


# ── Route helpers ──────────────────────────────────────────────


def list_routes(scenario_id: str) -> List[Dict[str, Any]]:
    return _list_items(scenario_id, "routes")


def get_route(scenario_id: str, route_id: str) -> Dict[str, Any]:
    return _get_item(scenario_id, "routes", "id", route_id)


def create_route(scenario_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
    return _create_item(scenario_id, "routes", data)


def update_route(
    scenario_id: str, route_id: str, patch: Dict[str, Any]
) -> Dict[str, Any]:
    return _update_item(scenario_id, "routes", "id", route_id, patch)


def delete_route(scenario_id: str, route_id: str) -> None:
    _delete_item(scenario_id, "routes", "id", route_id)


# ── Permission helpers ─────────────────────────────────────────


def get_depot_route_permissions(scenario_id: str) -> List[Dict[str, Any]]:
    return _list_items(scenario_id, "depot_route_permissions")


def set_depot_route_permissions(
    scenario_id: str, permissions: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    set_field(scenario_id, "depot_route_permissions", permissions)
    return permissions


def get_vehicle_route_permissions(scenario_id: str) -> List[Dict[str, Any]]:
    return _list_items(scenario_id, "vehicle_route_permissions")


def set_vehicle_route_permissions(
    scenario_id: str, permissions: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    set_field(scenario_id, "vehicle_route_permissions", permissions)
    return permissions
