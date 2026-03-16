from __future__ import annotations

import copy
import os
from functools import lru_cache
from typing import Any, Dict, Optional

from src.research_dataset_loader import (
    DEFAULT_DATASET_ID,
    build_dataset_bootstrap,
    default_vehicle_templates,
)

DEFAULT_PRELOAD_MASTER_DATASET_ID = os.environ.get(
    "PRELOAD_MASTER_DATASET_ID",
    "tokyu_dispatch_ready",
).strip() or "tokyu_dispatch_ready"


def default_preload_dataset_id() -> str:
    return DEFAULT_PRELOAD_MASTER_DATASET_ID


def _resolve_dataset_id(dataset_id: Optional[str] = None) -> str:
    return str(dataset_id or DEFAULT_PRELOAD_MASTER_DATASET_ID or DEFAULT_DATASET_ID)


@lru_cache(maxsize=16)
def _cached_preloaded_master_data(dataset_id: str) -> Dict[str, Any]:
    target_dataset_id = _resolve_dataset_id(dataset_id)
    try:
        bootstrap = build_dataset_bootstrap(
            target_dataset_id,
            scenario_id=f"app-master:{target_dataset_id}",
            random_seed=42,
        )
    except KeyError:
        bootstrap = build_dataset_bootstrap(
            DEFAULT_DATASET_ID,
            scenario_id=f"app-master:{DEFAULT_DATASET_ID}",
            random_seed=42,
        )
        target_dataset_id = DEFAULT_DATASET_ID

    return {
        "datasetId": target_dataset_id,
        "datasetVersion": (bootstrap.get("dispatch_scope") or {}).get("datasetVersion"),
        "depots": list(bootstrap.get("depots") or []),
        "routes": list(bootstrap.get("routes") or []),
        "vehicleTemplates": list(
            bootstrap.get("vehicle_templates") or default_vehicle_templates()
        ),
        "routeDepotAssignments": list(
            bootstrap.get("route_depot_assignments") or []
        ),
        "depotRoutePermissions": list(
            bootstrap.get("depot_route_permissions") or []
        ),
        "dispatchScope": dict(bootstrap.get("dispatch_scope") or {}),
        "feedContext": dict(bootstrap.get("feed_context") or {}),
    }


def get_preloaded_master_data(dataset_id: Optional[str] = None) -> Dict[str, Any]:
    target_dataset_id = _resolve_dataset_id(dataset_id)
    return copy.deepcopy(_cached_preloaded_master_data(target_dataset_id))


def repair_missing_master_data(
    doc: Dict[str, Any],
    *,
    dataset_id: Optional[str] = None,
) -> bool:
    target_dataset_id = dataset_id or (
        (doc.get("scenario_overlay") or {}).get("dataset_id")
        or (doc.get("scenario_overlay") or {}).get("datasetId")
        or (doc.get("feed_context") or {}).get("datasetId")
        or (doc.get("feed_context") or {}).get("dataset_id")
    )
    if not target_dataset_id:
        return False

    current_scope = doc.get("dispatch_scope") if isinstance(doc.get("dispatch_scope"), dict) else {}
    current_depot_selection = dict(current_scope.get("depotSelection") or {})
    current_route_selection = dict(current_scope.get("routeSelection") or {})
    current_service_selection = dict(current_scope.get("serviceSelection") or {})

    has_core_master_data = all(
        bool(doc.get(key))
        for key in (
            "depots",
            "routes",
            "vehicle_templates",
            "route_depot_assignments",
        )
    )

    current_permissions = list(doc.get("depot_route_permissions") or [])
    current_depots = list(doc.get("depots") or [])
    current_routes = list(doc.get("routes") or [])
    full_matrix_size = len(current_depots) * len(current_routes)
    is_full_matrix_allow_all = (
        bool(current_permissions)
        and full_matrix_size > 0
        and len(current_permissions) == full_matrix_size
        and all(bool(item.get("allowed")) for item in current_permissions)
    )

    has_scope_selection = (
        bool(list(current_depot_selection.get("depotIds") or []))
        and bool(list(current_route_selection.get("includeRouteIds") or []))
        and bool(list(current_service_selection.get("serviceIds") or []))
    )

    if has_core_master_data and current_permissions and not is_full_matrix_allow_all and has_scope_selection:
        return False

    payload = get_preloaded_master_data(str(target_dataset_id))
    changed = False

    field_mapping = (
        ("depots", "depots"),
        ("routes", "routes"),
        ("vehicle_templates", "vehicleTemplates"),
        ("route_depot_assignments", "routeDepotAssignments"),
    )
    for local_key, preload_key in field_mapping:
        if doc.get(local_key):
            continue
        value = payload.get(preload_key) or []
        if not value:
            continue
        doc[local_key] = [dict(item) if isinstance(item, dict) else item for item in value]
        changed = True

    current_permissions = list(doc.get("depot_route_permissions") or [])
    current_depots = list(doc.get("depots") or payload.get("depots") or [])
    current_routes = list(doc.get("routes") or payload.get("routes") or [])
    full_matrix_size = len(current_depots) * len(current_routes)
    is_full_matrix_allow_all = (
        bool(current_permissions)
        and full_matrix_size > 0
        and len(current_permissions) == full_matrix_size
        and all(bool(item.get("allowed")) for item in current_permissions)
    )
    if not current_permissions or is_full_matrix_allow_all:
        permissions = payload.get("depotRoutePermissions") or []
        if permissions:
            doc["depot_route_permissions"] = [
                dict(item) if isinstance(item, dict) else item for item in permissions
            ]
            changed = True

    scope = doc.get("dispatch_scope")
    preload_scope = payload.get("dispatchScope") or {}
    if isinstance(scope, dict):
        depot_selection = dict(scope.get("depotSelection") or {})
        route_selection = dict(scope.get("routeSelection") or {})
        service_selection = dict(scope.get("serviceSelection") or {})
        if not list(depot_selection.get("depotIds") or []) and preload_scope.get("depotSelection"):
            scope["depotSelection"] = dict(preload_scope.get("depotSelection") or {})
            scope["depotId"] = scope["depotSelection"].get("primaryDepotId")
            changed = True
        if not list(route_selection.get("includeRouteIds") or []) and preload_scope.get("routeSelection"):
            scope["routeSelection"] = dict(preload_scope.get("routeSelection") or {})
            changed = True
        if not list(service_selection.get("serviceIds") or []) and preload_scope.get("serviceSelection"):
            scope["serviceSelection"] = dict(preload_scope.get("serviceSelection") or {})
            scope["serviceId"] = (scope["serviceSelection"].get("serviceIds") or ["WEEKDAY"])[0]
            changed = True

    return changed
